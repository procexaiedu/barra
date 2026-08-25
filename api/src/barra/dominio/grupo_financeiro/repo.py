"""SQL puro do Grupo financeiro (spec 0005): cadastro do vinculo, log de origem e Venda registrada.

**Toda leitura de venda deste modulo filtra `anulada_em IS NULL`** (ticket 05). Anulacao e estado
com rastro, nao DELETE: a linha continua no banco provando de onde veio, e uma unica consulta que
esquecer o filtro devolve para o extrato (ou para a cobranca de pendencia) uma venda que o grupo
apagou. Por isso o filtro esta em cada SELECT e nao numa VIEW opcional — quem escrever a consulta
seguinte copia o padrao que ja esta aqui.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.errors import UniqueViolation

from barra.dominio.financeiro.calculos import comissao_sql
from barra.dominio.grupo_financeiro.anuncio import normalizar
from barra.dominio.grupo_financeiro.bolso import VendaComBolso
from barra.dominio.grupo_financeiro.cobranca import CobrancaDaAgencia
from barra.dominio.grupo_financeiro.comprovante import (
    RUIDO_DA_CHAVE,
    ChaveComDono,
    ChaveVista,
    Classificacao,
    ComprovanteDoGrupo,
    EstabelecimentoComDono,
    PapelCadastrado,
    QuemMandou,
    normalizar_chave,
    normalizar_estabelecimento,
)
from barra.dominio.grupo_financeiro.correcao import Mudanca
from barra.dominio.grupo_financeiro.dados_cadastrais import (
    CampoCadastral,
    DadoCadastralRegistrado,
    mesmo_valor,
)
from barra.dominio.grupo_financeiro.deslocamento import PlanoDoDeslocamento
from barra.dominio.grupo_financeiro.ficha import (
    FaturamentoPorOrigem,
    FaturamentoPorSite,
    FichaDeAgendamento,
    FichaLida,
    ParticipanteDaFicha,
    PromocaoDaFicha,
    TipoDeEventoDaFicha,
    normalizar_site,
)
from barra.dominio.grupo_financeiro.modelos import (
    EventoDaVenda,
    FormaPagamento,
    GrupoCadastrado,
    GrupoFinanceiro,
    GrupoSemDona,
    MensagemDoGrupo,
    MensagemRegistrada,
    TipoDeEvento,
    VendaNoPainel,
    VendaRegistrada,
)
from barra.dominio.grupo_financeiro.nomes import (
    CadastroDeNomes,
    OrigemDoAnuncio,
    separar_origem,
)
from barra.dominio.grupo_financeiro.pendencia import em_especie
from barra.dominio.grupo_financeiro.razao import Bolso
from barra.dominio.grupo_financeiro.rotina import MovimentoDoGrupo
from barra.dominio.grupo_financeiro.temporada import (
    DeslocamentoParaORazao,
    EstadoDaTemporada,
    LancamentoManual,
    OrigemDoLancamento,
    PagamentoDaTemporada,
    ParteDoDeslocamento,
    SentidoDoLancamento,
    Temporada,
    TipoDeLancamentoManual,
    TransferenciaParaORazao,
    VendaParaORazao,
)

_logger = logging.getLogger(__name__)

_COLUNAS_DA_VENDA = (
    "id",
    "modelo_id",
    "valor",
    "data",
    "mensagem_id",
    "cliente_nome",
    "local_atendimento",
    "duracao_minutos",
    "forma_pagamento",
    "comprovante_id",
    "anulada_em",
    "recebido_por_modelo_id",
)

_CAMPOS_DA_VENDA = """id, modelo_id, valor, data, mensagem_id, cliente_nome, local_atendimento,
                      duracao_minutos, forma_pagamento, comprovante_id, anulada_em,
                      recebido_por_modelo_id"""

_CAMPOS_DA_VENDA_V = """v.id, v.modelo_id, v.valor, v.data, v.mensagem_id, v.cliente_nome,
                        v.local_atendimento, v.duracao_minutos, v.forma_pagamento,
                        v.comprovante_id, v.anulada_em, v.recebido_por_modelo_id"""

# O read model do BOLSO (ticket 21). Projecao propria e nao `_CAMPOS_DA_VENDA` + duas colunas:
# `VendaRegistrada` nao carrega bolso de proposito (`bolso.VendaComBolso` explica por que), e uma
# projecao so serviria as duas leituras obrigando uma delas a carregar o que nao le.
_COLUNAS_DO_BOLSO = (
    "id",
    "modelo_id",
    "valor",
    "data",
    "bolso",
    "forma_pagamento",
    "cliente_nome",
    "bolso_mensagem_id",
)

_CAMPOS_DO_BOLSO = """id, modelo_id, valor, data, bolso, forma_pagamento, cliente_nome,
                      bolso_mensagem_id"""

_COLUNAS_DO_COMPROVANTE = (
    "id",
    "grupo_id",
    "mensagem_id",
    "classificacao",
    "valor",
    "data_transferencia",
    "pagador",
    "chave_destino",
    "titular_destino",
    "chave_conhecida",
    "valor_abatido",
    "estabelecimento",
)

_CAMPOS_DO_COMPROVANTE = """id, grupo_id, mensagem_id, classificacao, valor, data_transferencia,
                            pagador, chave_destino, titular_destino, chave_conhecida,
                            valor_abatido, estabelecimento"""

_COLUNAS_DA_COBRANCA = (
    "id",
    "grupo_id",
    "modelo_id",
    "mensagem_id",
    "descricao",
    "valor",
    "data",
    "comprovante_id",
    "quitada_em",
    "anulada_em",
)

_CAMPOS_DA_COBRANCA = """id, grupo_id, modelo_id, mensagem_id, descricao, valor, data,
                         comprovante_id, quitada_em, anulada_em"""


async def buscar_grupo_cadastrado_por_jid(
    conn: AsyncConnection[Any], jid: str
) -> GrupoCadastrado | None:
    """Resolve QUALQUER grupo cadastrado pelo JID, com o papel dele. `ativo=false` = nao existe.

    Closed-world: quem nao esta aqui nao e grupo nosso. O numero da ProceX e compartilhado (myEYE +
    estes grupos + os grupos pessoais das modelos), entao "nao achei" tem que significar SILENCIO,
    nunca um palpite.

    Desde a onda `20260820` a tabela guarda tres papeis (ADR-0046 §2) e `modelo_id` e NULO em dois
    deles. A juncao com `modelos` e por isso um LEFT JOIN — com o INNER de antes, o Grupo de fichas
    responderia "nao cadastrado" e o card postado la seria ignorado em silencio, que e o bug mais
    caro possivel neste modulo: o telefonista ve a ficha no grupo e o sistema nao tem nenhuma.

    Uma consulta so para os tres papeis, e nao uma por papel: toda mensagem de grupo passa por
    aqui, inclusive as de grupo alheio.
    """
    cur = await conn.execute(
        """
        SELECT g.id, g.papel::text AS papel, g.modelo_id, g.jid, g.nome, m.numero_whatsapp
          FROM barravips.grupos_financeiros g
          LEFT JOIN barravips.modelos m ON m.id = g.modelo_id
         WHERE g.jid = %s AND g.ativo
         LIMIT 1
        """,
        (jid,),
    )
    row = await cur.fetchone()
    if row is None:
        return None
    dados = _como_dict(row, ("id", "papel", "modelo_id", "jid", "nome", "numero_whatsapp"))
    papel = dados["papel"]
    if papel in ("fichas", "caixa_telefonistas"):
        return GrupoSemDona(id=dados["id"], papel=papel, jid=dados["jid"], nome=dados["nome"] or "")
    if papel != "modelo" or dados["modelo_id"] is None:
        # O CHECK `grupos_financeiros_papel_exige_modelo` proibe as duas metades disto, e um papel
        # que este codigo nao conhece so aparece quando alguem acrescentar um valor ao enum sem
        # passar por aqui. Nos dois casos a conduta e a de sempre: silencio, nunca um palpite sobre
        # de quem e o dinheiro.
        _logger.warning("grupo_financeiro_papel_inesperado jid=%s papel=%s", jid, papel)
        return None
    return GrupoFinanceiro(
        id=dados["id"],
        modelo_id=dados["modelo_id"],
        jid=dados["jid"],
        nome=dados["nome"] or "",
        # O numero dela vem JUNTO (JOIN, nao segunda consulta) porque o unico uso dele e decidir,
        # ainda dentro do turno, se quem falou foi a propria modelo — a tranca da chave Pix do
        # ticket 12. Buscar depois seria uma ida ao banco por mensagem de grupo social.
        numero_modelo=dados["numero_whatsapp"],
    )


async def buscar_grupo_por_jid(conn: AsyncConnection[Any], jid: str) -> GrupoFinanceiro | None:
    """O grupo DA MODELO deste JID — `None` para todo o resto, inclusive o Grupo de fichas.

    Continua sendo a porta de quem so sabe lidar com a dona do grupo (a cobranca, a venda, o
    fechamento): para eles um grupo sem modelo e indistinguivel de um grupo que nao e nosso, e a
    conduta certa e a mesma nos dois casos. Quem precisa enxergar o papel chama
    `buscar_grupo_cadastrado_por_jid`.
    """
    grupo = await buscar_grupo_cadastrado_por_jid(conn, jid)
    return grupo if isinstance(grupo, GrupoFinanceiro) else None


async def registrar_mensagem(
    conn: AsyncConnection[Any], grupo_id: UUID, msg: MensagemDoGrupo
) -> UUID | None:
    """Persiste a mensagem com origem completa. Devolve `None` quando ja estava registrada.

    O `ON CONFLICT DO NOTHING` sobre `chave_dedup` E o gate de idempotencia da porta: a segunda
    entrega da mesma mensagem nao insere linha, `RETURNING` volta vazio e a porta para ali — sem
    janela em memoria, sem depender de o webhook ser chamado uma vez so (ele nao e).
    """
    cur = await conn.execute(
        """
        INSERT INTO barravips.grupo_financeiro_mensagens
            (grupo_id, chave_dedup, evolution_message_id, autor_jid, autor_nome, de_mim,
             tipo, texto, caption, media_url, quoted_message_id, recebida_em)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (chave_dedup) DO NOTHING
        RETURNING id
        """,
        (
            grupo_id,
            msg.chave_dedup(),
            msg.evolution_message_id,
            msg.autor_jid,
            msg.autor_nome,
            msg.de_mim,
            msg.tipo,
            msg.texto,
            msg.caption,
            msg.media_url,
            msg.quoted_message_id,
            msg.recebida_em,
        ),
    )
    row = await cur.fetchone()
    if row is None:
        return None
    return cast(UUID, _como_dict(row, ("id",))["id"])


async def gravar_texto_da_mensagem(
    conn: AsyncConnection[Any], mensagem_id: UUID, texto: str
) -> None:
    """Escreve no log de origem o que a mensagem DIZ — o texto transcrito de um audio (ticket 06).

    A transcricao vai para a MESMA coluna do texto digitado, e nao para uma coluna de audio: e o
    que faz o "600" falado responder a pergunta minima igual ao "600" escrito, sem que
    `mensagens_recentes` (o contexto) nem nenhum leitor deste modulo precise saber que existe um
    segundo lugar onde procurar o que foi dito. `tipo='audio'` continua registrando a ORIGEM.
    """
    await conn.execute(
        "UPDATE barravips.grupo_financeiro_mensagens SET texto = %s WHERE id = %s",
        (texto, mensagem_id),
    )


async def carregar_cadastro_de_nomes(conn: AsyncConnection[Any]) -> CadastroDeNomes:
    """Le o cadastro que o resolver closed-world usa: nome verdadeiro + nomes de anuncio.

    Duas consultas pequenas por anuncio (a casa tem dezenas de modelos, nao milhares) em vez de
    um JOIN com `unaccent`/`lower` no banco: a normalizacao mora no Python (`anuncio.normalizar`),
    entao a MESMA regra vale para o que se grava e para o que se procura — e nao dependemos de
    extensao instalada no Postgres. Sem cache de proposito: apelido cadastrado pelo grupo
    (ticket 04) tem que valer no anuncio seguinte.

    Nao filtra por `status`: venda e fato passado, e modelo pausada/inativa tambem vendeu.
    """
    cur = await conn.execute("SELECT id, nome FROM barravips.modelos")
    modelos = [
        (linha["id"], linha["nome"])
        for linha in (_como_dict(row, ("id", "nome")) for row in await cur.fetchall())
    ]
    cur = await conn.execute(
        "SELECT modelo_id, nome FROM barravips.modelo_nomes_anuncio WHERE ativo"
    )
    apelidos = [
        (linha["modelo_id"], linha["nome"])
        for linha in (_como_dict(row, ("modelo_id", "nome")) for row in await cur.fetchall())
    ]
    return CadastroDeNomes.de_linhas(modelos=modelos, apelidos=apelidos)


async def registrar_venda(
    conn: AsyncConnection[Any],
    *,
    modelo_id: UUID,
    valor: Decimal,
    data: date,
    mensagem_id: UUID,
    chave_conteudo: str,
    cliente_nome: str | None = None,
    local_atendimento: str | None = None,
    duracao_minutos: int | None = None,
    recebido_por_modelo_id: UUID | None = None,
    origem: OrigemDoAnuncio | None = None,
    site: str | None = None,
) -> VendaRegistrada | None:
    """Insere a Venda registrada (ADR-0043) e devolve a linha. `None` = ja existia.

    `recebido_por_modelo_id` e a festinha em que UMA modelo recebeu por todas (ticket 13): as N
    linhas continuam sendo N, cada uma no valor da sua modelo, e so o debito do bruto muda de dona
    (ADR-0045 §6). Ele vem de `rateio.LinhaDoAnuncio.recebido_por` — nunca daqui, e nunca por
    default: `None` significa "ela mesma", que e o caso de quase toda venda.

    Devolve a entidade inteira (e nao so o id) porque quem chama precisa dela na mesma hora para
    dizer o que registrou e o que ficou pendente — reler a linha logo depois de escreve-la seria
    uma ida ao banco para buscar o que o proprio INSERT ja tem na mao.

    O `ON CONFLICT (chave_conteudo) DO NOTHING` e o **dedup cross-grupo** (ticket 04): o mesmo
    anuncio postado no grupo da outra participante, ou repostado depois de apagado, nao vira
    linha nova. Ele mora no banco, e nao num SELECT antes do INSERT, porque duas entregas
    concorrentes do mesmo fato passariam as duas por qualquer checagem previa — o indice unico e
    a unica barreira que uma corrida nao atravessa.

    O `WHERE anulada_em IS NULL` no ON CONFLICT nao e filtro: e a INFERENCIA do indice parcial
    (ticket 05). O dedup vale entre linhas VIVAS, entao apagar e repostar o mesmo anuncio volta a
    registrar — sem isso, o repost do gesto de correcao morreria contra a linha ja anulada e a
    venda desapareceria do sistema sem ninguem notar.

    `origem` e `site` sao a metrica do ticket 16 pelo caminho do TEXTO LIVRE — a venda que nasce do
    anuncio escrito solto, sem card. A origem vem da marca colada ao nome ("fake Bianca",
    `nomes.separar_origem`) e o site so vem preenchido quando alguem o disser; os dois sao NULOS
    por default, e nulo e resposta legitima. Pela outra porta (o card) quem grava e
    `registrar_venda_da_ficha`, que os copia da `PromocaoDaFicha`.
    """
    cur = await conn.execute(
        f"""
        INSERT INTO barravips.vendas_registradas
            (modelo_id, valor, data, cliente_nome, local_atendimento, duracao_minutos,
             mensagem_id, chave_conteudo, recebido_por_modelo_id, origem, site)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s::barravips.origem_anuncio_enum, %s)
        ON CONFLICT (chave_conteudo) WHERE anulada_em IS NULL DO NOTHING
        RETURNING {_CAMPOS_DA_VENDA}
        """,
        (
            modelo_id,
            valor,
            data,
            cliente_nome,
            local_atendimento,
            duracao_minutos,
            mensagem_id,
            chave_conteudo,
            recebido_por_modelo_id,
            origem,
            normalizar_site(site),
        ),
    )
    row = await cur.fetchone()
    return None if row is None else _venda(row)


async def venda_por_chave_de_conteudo(
    conn: AsyncConnection[Any], chave_conteudo: str
) -> VendaRegistrada | None:
    """A venda que JA representa este fato — quem venceu o dedup cross-grupo.

    Buscada so quando o INSERT nao gravou: e ela que o aviso de duplicata cita, para o grupo ver
    que o agente reconheceu o anuncio (e nao que engoliu a venda).
    """
    cur = await conn.execute(
        f"""
        SELECT {_CAMPOS_DA_VENDA}
          FROM barravips.vendas_registradas
         WHERE chave_conteudo = %s
           AND anulada_em IS NULL
         LIMIT 1
        """,
        (chave_conteudo,),
    )
    row = await cur.fetchone()
    return None if row is None else _venda(row)


async def vendas_da_mensagem(
    conn: AsyncConnection[Any], mensagem_id: UUID
) -> list[VendaRegistrada]:
    """As vendas que ja nasceram DESTE anuncio.

    Um anuncio de duas modelos pode estar registrado pela metade (uma participante conhecida, a
    outra ainda um Nome de anuncio desconhecido). Quando a resposta do grupo ensina quem e a
    outra, e esta lista que diz o que NAO precisa ser registrado de novo.

    E tambem a lista que a delecao da mensagem-fonte anula (ticket 05) — por isso so as vivas: a
    reentrega do mesmo evento de delecao nao tem o que anular de novo.
    """
    cur = await conn.execute(
        f"""
        SELECT {_CAMPOS_DA_VENDA}
          FROM barravips.vendas_registradas
         WHERE mensagem_id = %s
           AND anulada_em IS NULL
         ORDER BY created_at
        """,
        (mensagem_id,),
    )
    return [_venda(row) for row in await cur.fetchall()]


async def gravar_nomes_de_anuncio(
    conn: AsyncConnection[Any], modelo_id: UUID, nomes: Sequence[str]
) -> tuple[str, ...]:
    """Ensina ao cadastro os Nomes de anuncio que o grupo acabou de atribuir a uma modelo.

    E o que fecha o ciclo do resolver closed-world: o agente perguntou "'fran loira' e quem?",
    alguem respondeu, e a resposta vira CADASTRO — no proximo anuncio o nome resolve sozinho e a
    pergunta nao se repete. Sem isso, o closed-world exigiria que Fernando cadastrasse apelido
    por apelido para o agente parar de perguntar.

    `ON CONFLICT (nome_normalizado) DO NOTHING`: o UNIQUE global e closed-world tambem na escrita
    — um nome que ja e de outra mulher NAO muda de dona por uma frase no grupo. Devolve o que de
    fato entrou, e o vazio e um "nao aprendi nada" que o chamador tem que tratar (nao registrar a
    venda), nunca um sucesso silencioso.
    """
    gravados: list[str] = []
    for nome in nomes:
        # A marca de origem sai ANTES de virar cadastro (ticket 16): "fake bianca" ensina
        # "bianca". Gravar a marca junto criaria um segundo apelido para a mesma mulher — um que
        # so casa quando o telefonista repete a palavra —, e a origem e fato da VENDA, nao nome
        # dela (docs/dominio/grupo-financeiro.md, _Avoid_). Nome que era SO a marca ("fake") nao
        # ensina nada e e descartado aqui, na ultima porta antes do INSERT: qualquer caminho que
        # chegue com ele — pergunta do agente, resposta do grupo, replay do export — para neste
        # mesmo `continue`.
        _, sem_marca = separar_origem(nome.strip())
        limpo = sem_marca.strip()
        normalizado = normalizar(limpo)
        if not normalizado:
            continue
        cur = await conn.execute(
            """
            INSERT INTO barravips.modelo_nomes_anuncio (modelo_id, nome, nome_normalizado)
            VALUES (%s, %s, %s)
            ON CONFLICT (nome_normalizado) DO NOTHING
            RETURNING nome
            """,
            (modelo_id, limpo, normalizado),
        )
        if await cur.fetchone() is not None:
            gravados.append(limpo)
    return tuple(gravados)


async def mensagens_recentes(
    conn: AsyncConnection[Any],
    grupo_id: UUID,
    *,
    antes_de: datetime,
    antes_da_mensagem: UUID,
    desde: datetime,
    limite: int,
) -> list[MensagemRegistrada]:
    """O contexto do grupo imediatamente ANTES desta mensagem, do mais recente para o mais antigo.

    E o substituto de uma tabela de estado conversacional: quem responde "600" ou "Sim" nao diz
    a que esta respondendo, e o que responde a isso e o log de origem que o ticket 01 ja guarda.

    O corte usa o par `(recebida_em, id)` e nao so o timestamp: o grupo dispara varias mensagens
    no mesmo segundo ("O Lucas de ontem" / "Foi pix também amiga ?" saem com 5 s de diferenca, e
    num rig de teste com relogio injetado saem no MESMO instante). `id` e uuidv7, entao ordenar
    por ele desempata pela ordem real de insercao — sem isso a "mensagem imediatamente anterior"
    seria sorteada, e e dela que a confirmacao herda a forma de pagamento.

    Mensagem APAGADA sai do contexto (ticket 05). Ela sumiu da tela de todo mundo: se continuasse
    aqui, um anuncio que a gestora apagou seguiria esperando resposta e capturaria o proximo
    numero solto do grupo — e o agente responderia a uma pergunta que ninguem mais ve.
    """
    cur = await conn.execute(
        """
        SELECT m.id,
               coalesce(nullif(m.texto, ''), m.caption, '') AS texto,
               m.de_mim,
               m.recebida_em,
               m.evolution_message_id,
               EXISTS (
                   SELECT 1 FROM barravips.vendas_registradas v
                    WHERE v.mensagem_id = m.id AND v.anulada_em IS NULL
               ) AS tem_venda
          FROM barravips.grupo_financeiro_mensagens m
         WHERE m.grupo_id = %s
           AND m.apagada_em IS NULL
           AND m.recebida_em >= %s
           AND (m.recebida_em, m.id) < (%s, %s)
         ORDER BY m.recebida_em DESC, m.id DESC
         LIMIT %s
        """,
        (grupo_id, desde, antes_de, antes_da_mensagem, limite),
    )
    colunas = ("id", "texto", "de_mim", "recebida_em", "evolution_message_id", "tem_venda")
    return [
        MensagemRegistrada(
            id=dados["id"],
            texto=dados["texto"] or "",
            de_mim=bool(dados["de_mim"]),
            recebida_em=dados["recebida_em"],
            evolution_message_id=dados["evolution_message_id"],
            tem_venda=bool(dados["tem_venda"]),
        )
        for dados in (_como_dict(row, colunas) for row in await cur.fetchall())
    ]


async def vendas_sem_forma_de_pagamento(
    conn: AsyncConnection[Any], modelo_id: UUID
) -> list[VendaRegistrada]:
    """As vendas DA MODELO com **Pendencia de forma de pagamento**, da mais antiga para a mais nova.

    Escopo MODELO, como todo o resto da conferencia (o Fechamento, as cobrancas abertas, a fila do
    abate). Foi GRUPO ate 14/08 e o replay do export mostrou o estrago: o anuncio de duas modelos
    e postado no grupo de UMA delas, entao a venda da parceira nasce ancorada aqui — e a cobranca
    da manha perguntava a Yasmin "foi pix ou dinheiro?" sobre a venda da Julia, duas linhas
    identicas na mesma mensagem (o valor de cada uma e o mesmo). Pior que a estetica: a resposta
    "Pix" dela podia escrever a forma na venda da OUTRA, que e o erro que nunca mais e descoberto.

    Escopo modelo tambem e o unico que fecha a conta dos dois lados: a venda que a modelo tem
    anunciada no grupo da parceira e cobrada aqui, no grupo dela, que e onde ela responde.

    Ordem antiga->nova porque e a fila natural da cobranca (ticket 10) e o desempate mais
    defensavel quando so ha uma aberta.

    Dentro do mesmo dia quem ordena e o **relogio do grupo** (`recebida_em` da mensagem que
    anunciou), nao o id: duas vendas gravadas na mesma transacao nascem com o mesmo instante de
    banco e ids v7 do mesmo milissegundo, e ai a ordem sai ao acaso. Isso importa porque as
    RECENTES sao as que a cobranca da manha nomeia (as antigas viram resumo) e as recentes sao as
    que a pergunta de desempate oferece — "a ultima que o grupo anunciou" tem que ser a ultima que
    o grupo anunciou, nao a que o sorteio do uuid pos por ultimo.
    """
    cur = await conn.execute(
        f"""
        SELECT {_CAMPOS_DA_VENDA_V}
          FROM barravips.vendas_registradas v
          LEFT JOIN barravips.grupo_financeiro_mensagens m ON m.id = v.mensagem_id
         WHERE v.modelo_id = %s
           AND v.forma_pagamento IS NULL
           AND v.anulada_em IS NULL
         ORDER BY v.data, m.recebida_em, v.id
        """,
        (modelo_id,),
    )
    return [_venda(row) for row in await cur.fetchall()]


async def venda_aberta_da_mensagem_citada(
    conn: AsyncConnection[Any], grupo_id: UUID, evolution_message_id: str
) -> UUID | None:
    """A venda aberta ancorada na mensagem que o autor citou (quote) — o sinal mais forte de todos.

    Duas mensagens ancoram a mesma venda e o grupo cita as duas: o **anuncio** e o **recibo** que
    o agente postou citando o anuncio. Por isso o segundo salto (`quoted_message_id` da citada):
    responder "foi pix" no recibo tem que valer tanto quanto responder no anuncio.
    """
    cur = await conn.execute(
        """
        WITH citada AS (
            SELECT id, quoted_message_id
              FROM barravips.grupo_financeiro_mensagens
             WHERE grupo_id = %s AND evolution_message_id = %s
             LIMIT 1
        )
        SELECT v.id
          FROM barravips.vendas_registradas v
          JOIN barravips.grupo_financeiro_mensagens m ON m.id = v.mensagem_id
          JOIN citada c ON m.id = c.id OR m.evolution_message_id = c.quoted_message_id
         WHERE v.forma_pagamento IS NULL
           AND v.anulada_em IS NULL
         ORDER BY v.created_at DESC
         LIMIT 1
        """,
        (grupo_id, evolution_message_id),
    )
    row = await cur.fetchone()
    if row is None:
        return None
    return cast(UUID, _como_dict(row, ("id",))["id"])


async def definir_forma_de_pagamento(
    conn: AsyncConnection[Any],
    venda_id: UUID,
    *,
    forma: FormaPagamento,
    mensagem_id: UUID,
) -> VendaRegistrada | None:
    """Resolve a Pendencia de forma de pagamento. `None` se ela ja tinha sido resolvida.

    O `forma_pagamento IS NULL` no WHERE e o que impede a absorcao de virar sobrescrita: duas
    respostas seguidas ("Pix" … "Dinheiro") nao podem trocar a forma calada — mudar o que ja foi
    dito e CORRECAO, e correcao tem porta propria e rastro (quote no recibo, ticket 05).

    `pagamento_mensagem_id` guarda QUAL mensagem disse a forma. E a auditoria da unica decisao
    contextual do modulo: quando a venda estiver marcada errada, e essa coluna que mostra qual
    "Sim" o agente ligou a qual venda.
    """
    # ESPECIE FIXA O BOLSO (ADR-0047 §2, ultima linha da tabela de evidencia): dinheiro vivo nao
    # tem outro bolso — ele fica com quem o recebeu. Escrito aqui, na mesma transacao da forma,
    # porque e a mesma fala que diz as duas coisas ("recebi, foi dinheiro"): um segundo UPDATE
    # noutro lugar seria a venda existindo por um instante com a forma dita e o bolso ignorado, e
    # e nesse instante que a cobranca da manha a leria como pendente.
    #
    # O `bolso = 'nao_dito'` no CASE e o que impede a regra fraca de atropelar a forte: se um
    # comprovante ja tinha provado `empresa`, "foi dinheiro" nao reescreve — o conflito entre os
    # dois e conversa para a porta (`bolso.confrontar_bolso`), nunca para este UPDATE.
    especie = em_especie(forma)
    cur = await conn.execute(
        f"""
        UPDATE barravips.vendas_registradas
           SET forma_pagamento = %s,
               pagamento_mensagem_id = %s,
               bolso = CASE WHEN %s::boolean AND bolso = 'nao_dito'
                            THEN 'dela'::barravips.bolso_da_venda_enum ELSE bolso END,
               bolso_mensagem_id = CASE WHEN %s::boolean AND bolso = 'nao_dito'
                            THEN %s ELSE bolso_mensagem_id END
         WHERE id = %s AND forma_pagamento IS NULL AND anulada_em IS NULL
        RETURNING {_CAMPOS_DA_VENDA}
        """,
        (forma, mensagem_id, especie, especie, mensagem_id, venda_id),
    )
    row = await cur.fetchone()
    return None if row is None else _venda(row)


# --- correcao e anulacao (ticket 05) ------------------------------------------------------------


async def vendas_da_mensagem_citada(
    conn: AsyncConnection[Any], grupo_id: UUID, evolution_message_id: str
) -> list[VendaRegistrada]:
    """As vendas VIVAS ancoradas na mensagem que o autor citou — o alvo da correcao por quote.

    Duas mensagens ancoram a mesma venda e o grupo cita as duas: o **anuncio** e o **recibo** que
    o agente postou citando o anuncio. Dai o segundo salto (`quoted_message_id` da citada):
    corrigir respondendo o recibo — que e o que o proprio recibo pede — tem que valer tanto quanto
    corrigir respondendo o anuncio.

    Devolve LISTA (e nao uma venda) porque um anuncio de duas modelos rendeu duas linhas e o
    recibo delas e um so: quem decide se a correcao cabe nas duas e o dominio, nao a consulta.
    """
    cur = await conn.execute(
        f"""
        WITH citada AS (
            SELECT id, quoted_message_id
              FROM barravips.grupo_financeiro_mensagens
             WHERE grupo_id = %s AND evolution_message_id = %s
             LIMIT 1
        )
        SELECT {_CAMPOS_DA_VENDA_V}
          FROM barravips.vendas_registradas v
          JOIN barravips.grupo_financeiro_mensagens m ON m.id = v.mensagem_id
          JOIN citada c ON m.id = c.id OR m.evolution_message_id = c.quoted_message_id
         WHERE v.anulada_em IS NULL
         ORDER BY v.created_at
        """,
        (grupo_id, evolution_message_id),
    )
    return [_venda(row) for row in await cur.fetchall()]


async def corrigir_venda(
    conn: AsyncConnection[Any], venda: VendaRegistrada, *, chave_conteudo: str
) -> VendaRegistrada | None:
    """Grava o estado JA corrigido da venda. `None` = a correcao nao coube.

    Recebe a entidade inteira (saida de `correcao.aplicar_correcao`) e escreve todos os campos
    corrigiveis de uma vez: o que decide o que mudou e o dominio, e um UPDATE que reescreve o
    estado inteiro nunca fica dessincronizado de um diff.

    A `chave_conteudo` e recalculada pelo chamador e vem junto **obrigatoriamente**: ela e derivada
    de data+valor+modelo+cliente, entao corrigir qualquer um deles sem recalcular deixaria o dedup
    vigiando um fato que nao existe mais — e o repost do anuncio ja corrigido entraria como venda
    nova.

    `None` acontece quando a chave nova ja pertence a outra linha VIVA (a correcao transformaria
    esta venda numa copia de outra) ou quando a venda deixou de estar viva no meio do caminho. O
    savepoint e o que impede essa colisao de abortar a transacao inteira do webhook — sem ele, um
    grupo perderia a mensagem seguinte por causa de uma correcao redundante.
    """
    row: Any = None
    try:
        async with conn.transaction():
            cur = await conn.execute(
                f"""
                UPDATE barravips.vendas_registradas
                   SET valor = %s, data = %s, cliente_nome = %s, duracao_minutos = %s,
                       forma_pagamento = %s, chave_conteudo = %s
                 WHERE id = %s AND anulada_em IS NULL
                RETURNING {_CAMPOS_DA_VENDA}
                """,
                (
                    venda.valor,
                    venda.data,
                    venda.cliente_nome,
                    venda.duracao_minutos,
                    venda.forma_pagamento,
                    chave_conteudo,
                    venda.id,
                ),
            )
            row = await cur.fetchone()
    except UniqueViolation:
        return None
    return None if row is None else _venda(row)


async def anular_venda(conn: AsyncConnection[Any], venda_id: UUID) -> VendaRegistrada | None:
    """Anula a venda (a mensagem-fonte foi apagada). `None` = ela ja estava anulada.

    UPDATE e nunca DELETE: a venda pode ja ter sido contada, e o rastro do que existiu e o que
    permite alguem entender depois por que o total de um dia mudou. O `anulada_em IS NULL` no
    WHERE torna a reentrega do mesmo evento de delecao inofensiva.
    """
    cur = await conn.execute(
        f"""
        UPDATE barravips.vendas_registradas
           SET anulada_em = now()
         WHERE id = %s AND anulada_em IS NULL
        RETURNING {_CAMPOS_DA_VENDA}
        """,
        (venda_id,),
    )
    row = await cur.fetchone()
    return None if row is None else _venda(row)


async def marcar_mensagem_apagada(
    conn: AsyncConnection[Any], grupo_id: UUID, evolution_message_id: str, *, em: datetime
) -> UUID | None:
    """Carimba a mensagem como apagada e devolve o id dela. `None` = o grupo nao a conhece.

    A linha do log NAO some: ela e a origem auditavel das vendas que nasceram dali. O carimbo e o
    que tira a mensagem do CONTEXTO (`mensagens_recentes`) — apagada, ela para de esperar resposta.

    `coalesce` preserva o primeiro carimbo: reentrega do evento nao reescreve a hora da delecao.
    """
    cur = await conn.execute(
        """
        UPDATE barravips.grupo_financeiro_mensagens
           SET apagada_em = coalesce(apagada_em, %s)
         WHERE grupo_id = %s AND evolution_message_id = %s
        RETURNING id
        """,
        (em, grupo_id, evolution_message_id),
    )
    row = await cur.fetchone()
    if row is None:
        return None
    return cast(UUID, _como_dict(row, ("id",))["id"])


async def registrar_eventos_da_venda(
    conn: AsyncConnection[Any],
    venda_id: UUID,
    *,
    tipo: TipoDeEvento,
    mensagem_id: UUID | None,
    mudancas: Sequence[Mudanca] = (),
) -> None:
    """Grava o rastro: uma linha por campo corrigido, ou uma linha unica para a anulacao.

    Escrito na MESMA transacao do efeito. Rastro que pode faltar quando o efeito aconteceu nao e
    auditoria — e um log que so registra os casos felizes.
    """
    if not mudancas:
        await conn.execute(
            """
            INSERT INTO barravips.venda_registrada_eventos (venda_id, tipo, mensagem_id)
            VALUES (%s, %s, %s)
            """,
            (venda_id, tipo, mensagem_id),
        )
        return
    for mudanca in mudancas:
        await conn.execute(
            """
            INSERT INTO barravips.venda_registrada_eventos
                (venda_id, tipo, campo, valor_anterior, valor_novo, mensagem_id)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (venda_id, tipo, mudanca.campo, mudanca.de, mudanca.para, mensagem_id),
        )


async def eventos_da_venda(conn: AsyncConnection[Any], venda_id: UUID) -> list[EventoDaVenda]:
    """O rastro completo de uma venda, do mais recente para o mais antigo.

    A leitura que torna a auditoria CONSULTAVEL: e por ela que o painel (ticket 11) mostra "esta
    venda ja foi R$ 700,00" e que um teste prova que a correcao deixou marca.
    """
    cur = await conn.execute(
        """
        SELECT id, venda_id, tipo, campo, valor_anterior, valor_novo, mensagem_id, created_at
          FROM barravips.venda_registrada_eventos
         WHERE venda_id = %s
         ORDER BY created_at DESC, id DESC
        """,
        (venda_id,),
    )
    colunas = (
        "id",
        "venda_id",
        "tipo",
        "campo",
        "valor_anterior",
        "valor_novo",
        "mensagem_id",
        "created_at",
    )
    return [
        EventoDaVenda(
            id=dados["id"],
            venda_id=dados["venda_id"],
            tipo=dados["tipo"],
            campo=dados["campo"],
            valor_anterior=dados["valor_anterior"],
            valor_novo=dados["valor_novo"],
            mensagem_id=dados["mensagem_id"],
            created_at=dados["created_at"],
        )
        for dados in (_como_dict(row, colunas) for row in await cur.fetchall())
    ]


# --- comprovante de fechamento (ticket 07) ------------------------------------------------------


async def vendas_pix_a_comprovar(
    conn: AsyncConnection[Any], modelo_id: UUID
) -> list[VendaRegistrada]:
    """A fila FIFO do abate: vendas em PIX da modelo, sem comprovante, da mais antiga para a nova.

    Escopo MODELO e nao grupo (diferente de `vendas_sem_forma_de_pagamento`): o Fechamento e a
    conferencia vendido x comprovado **por modelo** (docs/dominio), e a venda casada anunciada no
    grupo da outra participante e dinheiro dela do mesmo jeito — ficaria invisivel para o
    comprovante que ela mesma manda.

    Dinheiro nao entra: fica em especie com a modelo, fora da expectativa de comprovante. Venda
    sem forma dita tambem nao — a pendencia dela e outra, e abater o que talvez nem seja pix
    fecharia a conta com um numero inventado. **Cartao tambem nao** (ticket 11): a prova da venda
    no debito, credito ou link e o print da maquininha, que nao e Comprovante de transferencia e
    nao passa pelo OCR de Pix — a coluna e `text` com CHECK de cinco valores, entao o `= 'pix'`
    aqui e o que mantem as tres formas novas fora da fila sem nenhuma mudanca.

    A fila e de quem **recebeu**, nao de quem trabalhou (ticket 13): `COALESCE(
    recebido_por_modelo_id, modelo_id)`. Na festinha em que uma modelo recebeu por todas, as
    quatro vendas entram na fila DELA — e ela quem pode mandar o comprovante — e saem da fila das
    outras tres, que nunca viram o dinheiro. E a mesma regra do debito do bruto no razao
    (`deslocamentos_para_o_razao`, `razao_repo`), e ela precisa ser a mesma: fila e debito
    discordando sobre de quem e o dinheiro e o extrato que nao fecha consigo mesmo.
    """
    cur = await conn.execute(
        f"""
        SELECT {_CAMPOS_DA_VENDA}
          FROM barravips.vendas_registradas
         WHERE COALESCE(recebido_por_modelo_id, modelo_id) = %s
           AND forma_pagamento = 'pix'
           AND comprovante_id IS NULL
           AND bolso <> 'empresa'
           AND anulada_em IS NULL
         ORDER BY data, id
        """,
        (modelo_id,),
    )
    return [_venda(row) for row in await cur.fetchall()]


async def registrar_comprovante(
    conn: AsyncConnection[Any],
    *,
    grupo_id: UUID,
    mensagem_id: UUID,
    classificacao: Classificacao,
    valor: Decimal | None = None,
    data_transferencia: date | None = None,
    pagador: str | None = None,
    chave_destino: str | None = None,
    titular_destino: str | None = None,
    chave_conhecida: bool = False,
    valor_abatido: Decimal = Decimal("0.00"),
    conteudo_hash: str | None = None,
    estabelecimento: str | None = None,
) -> ComprovanteDoGrupo | None:
    """Persiste o comprovante lido. `None` = esta imagem ja tinha comprovante neste grupo.

    Dois gates de idempotencia, e eles pegam coisas diferentes. `mensagem_id UNIQUE` cobre a
    REENTREGA da mesma mensagem pelo router. `(grupo_id, conteudo_hash)` cobre o REENVIO da mesma
    FOTO, que chega como mensagem nova — o gesto comum de quem acha que a imagem nao foi entregue.
    Sem o segundo, o mesmo Pix de R$ 700,00 abate duas vendas de R$ 700,00 e o Fechamento fecha
    sem acusar nada (medido em 14/08); com ele, o `ON CONFLICT DO NOTHING` devolve `None` ANTES do
    abate, e quem chama decide o que falar.

    `conteudo_hash=None` (o comprovante ilegivel) fica de fora do gate de proposito: o agente
    acabou de pedir a imagem de novo.

    `estabelecimento` e o destino do print de MAQUININHA (ticket 06) e viaja pelo mesmo caminho que
    a chave, na mesma linha: cartao nao e outro fluxo, e o dedup por foto, a anulacao e o painel
    valem igual. A forma de comparacao (`estabelecimento_normalizado`) e derivada AQUI, com a unica
    normalizacao que existe — quem chama nunca a passa pronta, pelo mesmo motivo de
    `criar_chave_pix`: duas normalizacoes sao duas politicas esperando divergir.
    """
    cur = await conn.execute(
        f"""
        INSERT INTO barravips.comprovantes_do_grupo
            (grupo_id, mensagem_id, classificacao, valor, data_transferencia, pagador,
             chave_destino, titular_destino, chave_conhecida, valor_abatido, conteudo_hash,
             estabelecimento, estabelecimento_normalizado)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT DO NOTHING
        RETURNING {_CAMPOS_DO_COMPROVANTE}
        """,
        (
            grupo_id,
            mensagem_id,
            classificacao,
            valor,
            data_transferencia,
            pagador,
            chave_destino,
            titular_destino,
            chave_conhecida,
            valor_abatido,
            conteudo_hash,
            estabelecimento,
            _estabelecimento_normalizado(estabelecimento),
        ),
    )
    row = await cur.fetchone()
    return None if row is None else _comprovante(row)


async def comprovante_por_conteudo(
    conn: AsyncConnection[Any], grupo_id: UUID, conteudo_hash: str
) -> ComprovanteDoGrupo | None:
    """O comprovante que ESTA imagem ja gerou neste grupo — o que o dedup de conteudo recusou.

    Existe para a fala: recusar calado um comprovante reenviado e o pior dos mundos (a modelo
    mandou de novo justamente porque achou que nao tinha chegado, e ficaria mandando). Com a linha
    antiga em maos o agente diz o que ja contou, com valor e data — e o grupo confere de relance.
    """
    cur = await conn.execute(
        f"""
        SELECT {_CAMPOS_DO_COMPROVANTE}
          FROM barravips.comprovantes_do_grupo
         WHERE grupo_id = %s AND conteudo_hash = %s
        """,
        (grupo_id, conteudo_hash),
    )
    row = await cur.fetchone()
    return None if row is None else _comprovante(row)


async def abater_vendas(
    conn: AsyncConnection[Any], comprovante_id: UUID, vendas: Sequence[UUID]
) -> list[VendaRegistrada]:
    """Liga o comprovante as vendas que ele fecha. Devolve so as que ESTE abate baixou.

    O `comprovante_id IS NULL` no WHERE e o que impede um segundo comprovante de reabater uma
    venda ja comprovada (duas entregas concorrentes, ou dois comprovantes do mesmo valor postados
    em sequencia): a venda sai da fila uma vez so, e quem chegou depois ve a fila menor.

    **O abate tambem fixa o BOLSO em `dela`** (ADR-0047 §2, primeira linha da tabela): um
    comprovante dela para a casa que casa com esta venda e a prova mais dura que existe de que o
    dinheiro passou pela conta dela. Fica na mesma transacao do abate porque e o MESMO fato — o
    comprovante que credita a transferencia no razao e o que produz o debito do bruto, e separa-los
    deixaria o saldo com uma perna so por um instante.

    So quando o bolso era `nao_dito`: bolso ja afirmado nao e reescrito por SQL: divergencia entre
    duas evidencias vira pergunta na porta (`bolso.confrontar_bolso`), nunca UPDATE calado. O caso
    `empresa` nem chega aqui — `vendas_pix_a_comprovar` ja o tira da fila, porque o dinheiro que
    caiu direto na casa nao tem transferencia dela para abater.
    """
    baixadas: list[VendaRegistrada] = []
    for venda_id in vendas:
        cur = await conn.execute(
            f"""
            UPDATE barravips.vendas_registradas
               SET comprovante_id = %s,
                   bolso = CASE WHEN bolso = 'nao_dito'
                                THEN 'dela'::barravips.bolso_da_venda_enum ELSE bolso END,
                   bolso_mensagem_id = CASE WHEN bolso = 'nao_dito'
                                THEN (SELECT c.mensagem_id
                                        FROM barravips.comprovantes_do_grupo c
                                       WHERE c.id = %s)
                                ELSE bolso_mensagem_id END
             WHERE id = %s
               AND comprovante_id IS NULL
               AND forma_pagamento = 'pix'
               AND anulada_em IS NULL
            RETURNING {_CAMPOS_DA_VENDA}
            """,
            (comprovante_id, comprovante_id, venda_id),
        )
        row = await cur.fetchone()
        if row is not None:
            baixadas.append(_venda(row))
    return baixadas


# --- o bolso da venda (ADR-0047, tickets 14 e 21) ------------------------------------------------
#
# Quatro consultas e um evento. O que elas guardam nao e um estado novo: e a coluna
# `vendas_registradas.bolso` (migration 20260820122000) sendo lida e escrita pela unica regra que
# o ADR-0047 admite — evidencia, com o de->para registrado. Nenhuma delas chuta: `nao_dito` fica
# `nao_dito` ate alguem provar o contrario, e quem o interpreta como `dela` e o razao.

MAX_VENDAS_CONFRONTAVEIS = 10
"""Tamanho da janela que a fala de bolso enxerga.

A escada de `pagamento.escolher_venda_do_bolso` precisa de um universo do tamanho da conversa: com
a vida inteira da modelo na lista, "unica candidata" nunca dispara e toda fala vira `ambigua`. Dez
e a ordem de grandeza do que um grupo real tem em aberto ao mesmo tempo — e a fala que se refere a
uma venda mais velha que isso nomeia o cliente, que e o sinal que continua funcionando."""


async def vendas_para_o_bolso(
    conn: AsyncConnection[Any], modelo_id: UUID, *, limite: int = MAX_VENDAS_CONFRONTAVEIS
) -> list[VendaComBolso]:
    """As vendas recentes da modelo que uma fala de bolso pode estar nomeando.

    Traz as **afirmadas junto com as `nao_dito`**, e isso e a diferenca entre esta consulta e
    `vendas_sem_bolso_dito`: a fala que contradiz um bolso ja afirmado nao pode ser filtrada para
    fora daqui, senao ela cai calada na venda vizinha — que e o erro que ninguem descobre. Quem
    decide o que fazer com a contradicao e `bolso.confrontar_bolso`, e a resposta dele e uma
    pergunta.

    Escopo MODELO (e nao grupo), como a fila do abate e o Fechamento: a venda casada anunciada no
    grupo da parceira e dinheiro dela do mesmo jeito, e a fala sobre o bolso dela acontece no
    grupo dela.

    Mais recentes primeiro — a fala fala quase sempre da venda de agora.
    """
    cur = await conn.execute(
        f"""
        SELECT {_CAMPOS_DO_BOLSO}
          FROM barravips.vendas_registradas
         WHERE COALESCE(recebido_por_modelo_id, modelo_id) = %s
           AND anulada_em IS NULL
         ORDER BY data DESC, id DESC
         LIMIT %s
        """,
        (modelo_id, limite),
    )
    return [_venda_com_bolso(row) for row in await cur.fetchall()]


async def venda_para_o_bolso(conn: AsyncConnection[Any], venda_id: UUID) -> VendaComBolso | None:
    """UMA venda pelos olhos do bolso — a releitura de quem PERDEU o compare-and-swap.

    `definir_bolso_da_venda` devolve `None` quando a coluna deixou de ser o que o chamador viu:
    outra evidencia escreveu entre a leitura e o UPDATE. A conduta dali em diante e perguntar
    (ADR-0047: divergencia nao vira reescrita calada), e uma pergunta precisa dizer o que ESTA
    anotado — com o valor velho na mao, o agente perguntaria nomeando um bolso que ja nao e o da
    coluna, que e errado justamente no unico fato que quem responde pode conferir.

    Por `id` e sem escopo de modelo de proposito: quem chama ja tem a venda em maos e so quer o
    estado de agora dela.
    """
    cur = await conn.execute(
        f"""
        SELECT {_CAMPOS_DO_BOLSO}
          FROM barravips.vendas_registradas
         WHERE id = %s AND anulada_em IS NULL
        """,
        (venda_id,),
    )
    row = await cur.fetchone()
    return None if row is None else _venda_com_bolso(row)


async def vendas_sem_bolso_dito(conn: AsyncConnection[Any], modelo_id: UUID) -> list[VendaComBolso]:
    """A fila da cobranca consolidada da manha pelo lado do bolso (ADR-0047 §3).

    Irma de `vendas_sem_forma_de_pagamento` e deliberadamente do mesmo formato: as duas pendencias
    viajam na MESMA mensagem da manha, porque "nao dito" nunca pode virar uma pergunta nova em
    tempo real — uma pergunta a mais por venda e a metralhadora que o dominio proibe.

    Da mais antiga para a mais nova, que e a ordem natural da cobranca, e com o desempate pelo
    relogio do grupo, como a fila da forma: duas vendas gravadas na mesma transacao nascem com ids
    v7 do mesmo milissegundo, e sem isso a ordem sai ao acaso.

    Le o indice `vendas_registradas_bolso_pendente_idx` (migration 20260820122000).
    """
    cur = await conn.execute(
        """
        SELECT v.id, v.modelo_id, v.valor, v.data, v.bolso, v.forma_pagamento, v.cliente_nome,
               v.bolso_mensagem_id
          FROM barravips.vendas_registradas v
          LEFT JOIN barravips.grupo_financeiro_mensagens m ON m.id = v.mensagem_id
         WHERE COALESCE(v.recebido_por_modelo_id, v.modelo_id) = %s
           AND v.bolso = 'nao_dito'
           AND v.anulada_em IS NULL
         ORDER BY v.data, m.recebida_em, v.id
        """,
        (modelo_id,),
    )
    return [_venda_com_bolso(row) for row in await cur.fetchall()]


async def definir_bolso_da_venda(
    conn: AsyncConnection[Any],
    venda_id: UUID,
    *,
    de: Bolso,
    para: Bolso,
    mensagem_id: UUID | None,
) -> VendaComBolso | None:
    """Escreve o bolso por COMPARE-AND-SWAP. `None` = a coluna ja nao era `de` (nada foi escrito).

    O `bolso = %s` no WHERE recebe o valor que o chamador VIU quando decidiu, e nao um "se estiver
    vazio": e ele que faz da precedencia do ADR-0047 uma garantia e nao uma intencao. Duas
    evidencias chegando no mesmo segundo (o comprovante e a fala) nao podem escrever as duas — a
    segunda ve que a coluna mudou, recebe `None` e cai na conduta de divergencia, que e perguntar.

    E o mesmo desenho do `forma_pagamento IS NULL` de `definir_forma_de_pagamento`, com uma razao a
    mais para ser rigoroso: mudar o bolso inverte o SINAL do saldo da modelo.

    `mensagem_id` e a mensagem que serviu de evidencia — a foto do comprovante, a fala do gestor.
    Nula quando a decisao veio do painel. E a auditoria de `bolso_mensagem_id`: quando o saldo
    estiver torto, e ela que mostra em que o agente se apoiou.
    """
    cur = await conn.execute(
        f"""
        UPDATE barravips.vendas_registradas
           SET bolso = %s::barravips.bolso_da_venda_enum, bolso_mensagem_id = %s
         WHERE id = %s
           AND bolso = %s::barravips.bolso_da_venda_enum
           AND anulada_em IS NULL
        RETURNING {_CAMPOS_DO_BOLSO}
        """,
        (para, mensagem_id, venda_id, de),
    )
    row = await cur.fetchone()
    return None if row is None else _venda_com_bolso(row)


async def registrar_evento_do_bolso(
    conn: AsyncConnection[Any],
    venda_id: UUID,
    *,
    de: Bolso,
    para: Bolso,
    mensagem_id: UUID | None,
) -> None:
    """O rastro do bolso em `venda_registrada_eventos` — append-only, como toda auditoria daqui.

    Entra como `correcao` de campo `bolso` e nao como um tipo de evento novo: o CHECK da tabela
    admite tres tipos (`correcao`, `anulacao`, `abate_desfeito`) e o que aconteceu aqui e
    literalmente uma correcao de um campo da venda. Um tipo novo custaria migration e nao diria
    nada que `campo = 'bolso'` ja nao diga.

    Escrito na MESMA transacao do UPDATE. Rastro que pode faltar quando o efeito aconteceu nao e
    auditoria — e um log que so registra os casos felizes.
    """
    await conn.execute(
        """
        INSERT INTO barravips.venda_registrada_eventos
            (venda_id, tipo, campo, valor_anterior, valor_novo, mensagem_id)
        VALUES (%s, 'correcao', 'bolso', %s, %s, %s)
        """,
        (venda_id, de, para, mensagem_id),
    )


async def ajustar_abate(
    conn: AsyncConnection[Any],
    comprovante_id: UUID,
    *,
    classificacao: Classificacao,
    valor_abatido: Decimal,
) -> None:
    """Corrige o que o comprovante de fato abateu, quando a corrida encolheu a fila.

    Escrito depois do UPDATE das vendas (e nao junto do INSERT) porque so ali se sabe quantas
    baixaram de verdade: entre planejar e abater, outra entrega pode ter fechado a mesma venda —
    e um comprovante `fechamento` que nao fechou nada e um numero que ninguem consegue explicar
    depois.
    """
    await conn.execute(
        """
        UPDATE barravips.comprovantes_do_grupo
           SET classificacao = %s, valor_abatido = %s
         WHERE id = %s
        """,
        (classificacao, valor_abatido, comprovante_id),
    )


# --- cobranca da agencia (ticket 08) -------------------------------------------------------------


async def registrar_cobranca(
    conn: AsyncConnection[Any],
    *,
    grupo_id: UUID,
    modelo_id: UUID,
    mensagem_id: UUID,
    descricao: str,
    valor: Decimal,
    data: date,
    chave_conteudo: str,
) -> CobrancaDaAgencia | None:
    """Insere a Cobranca da agencia e devolve a linha. `None` = ja existia (repost/dedup).

    O `ON CONFLICT (chave_conteudo) WHERE anulada_em IS NULL` e o mesmo desenho da Venda
    registrada: o indice parcial e a unica barreira que uma entrega concorrente nao atravessa, e a
    cobranca ANULADA solta a chave para o repost do gesto de correcao do grupo poder substitui-la.
    """
    cur = await conn.execute(
        f"""
        INSERT INTO barravips.cobrancas_da_agencia
            (grupo_id, modelo_id, mensagem_id, descricao, valor, data, chave_conteudo)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (chave_conteudo) WHERE anulada_em IS NULL DO NOTHING
        RETURNING {_CAMPOS_DA_COBRANCA}
        """,
        (grupo_id, modelo_id, mensagem_id, descricao, valor, data, chave_conteudo),
    )
    row = await cur.fetchone()
    return None if row is None else _cobranca(row)


async def cobranca_por_chave_de_conteudo(
    conn: AsyncConnection[Any], chave_conteudo: str
) -> CobrancaDaAgencia | None:
    """A cobranca que JA representa este fato — quem venceu o dedup. E ela que o aviso cita."""
    cur = await conn.execute(
        f"""
        SELECT {_CAMPOS_DA_COBRANCA}
          FROM barravips.cobrancas_da_agencia
         WHERE chave_conteudo = %s
           AND anulada_em IS NULL
         LIMIT 1
        """,
        (chave_conteudo,),
    )
    row = await cur.fetchone()
    return None if row is None else _cobranca(row)


async def cobrancas_abertas_da_modelo(
    conn: AsyncConnection[Any], modelo_id: UUID
) -> list[CobrancaDaAgencia]:
    """O que esta modelo ainda deve a agencia, da mais antiga para a mais nova.

    Escopo MODELO e nao grupo, como todo o resto da conferencia (docs/dominio, "Fechamento"): a
    cobranca postada num grupo e divida dela do mesmo jeito, e o comprovante que a paga pode
    chegar pelo outro.

    So as ABERTAS: e a unica lista que alguem consome (o casamento do comprovante, a coluna de
    debito do extrato e a cobranca da manha). Cobranca quitada e historia, e historia nao entra na
    conta de quanto falta.
    """
    cur = await conn.execute(
        f"""
        SELECT {_CAMPOS_DA_COBRANCA}
          FROM barravips.cobrancas_da_agencia
         WHERE modelo_id = %s
           AND quitada_em IS NULL
           AND anulada_em IS NULL
         ORDER BY data, id
        """,
        (modelo_id,),
    )
    return [_cobranca(row) for row in await cur.fetchall()]


async def quitar_cobranca(
    conn: AsyncConnection[Any], cobranca_id: UUID, comprovante_id: UUID
) -> CobrancaDaAgencia | None:
    """Amarra o comprovante que pagou a cobranca. `None` = ela ja tinha sido quitada (ou anulada).

    Os dois campos numa tacada so porque o banco exige (`quitacao_tem_prova`): nao existe estado
    intermediario "paga sem comprovante" — que e exatamente o "conferi no olho" que este modulo
    veio substituir. O `quitada_em IS NULL` no WHERE torna a corrida entre dois comprovantes do
    mesmo valor inofensiva: o segundo nao acha o que quitar e cai como retido, com pergunta.
    """
    cur = await conn.execute(
        f"""
        UPDATE barravips.cobrancas_da_agencia
           SET comprovante_id = %s, quitada_em = now()
         WHERE id = %s AND quitada_em IS NULL AND anulada_em IS NULL
        RETURNING {_CAMPOS_DA_COBRANCA}
        """,
        (comprovante_id, cobranca_id),
    )
    row = await cur.fetchone()
    return None if row is None else _cobranca(row)


async def anular_cobrancas_da_mensagem(
    conn: AsyncConnection[Any], mensagem_id: UUID
) -> list[CobrancaDaAgencia]:
    """A mensagem-fonte foi apagada: a cobranca PENDENTE nascida dela deixa de cobrar.

    So a pendente, e o `quitada_em IS NULL` no WHERE e a regra inteira: apagar a mensagem depois
    de a modelo ter pago nao pode desfazer um pagamento que tem comprovante amarrado. A linha
    anulada continua no banco provando o que aconteceu — e solta a `chave_conteudo` para o repost.
    """
    cur = await conn.execute(
        f"""
        UPDATE barravips.cobrancas_da_agencia
           SET anulada_em = now()
         WHERE mensagem_id = %s AND quitada_em IS NULL AND anulada_em IS NULL
        RETURNING {_CAMPOS_DA_COBRANCA}
        """,
        (mensagem_id,),
    )
    return [_cobranca(row) for row in await cur.fetchall()]


async def anular_comprovantes_da_mensagem(
    conn: AsyncConnection[Any], mensagem_id: UUID
) -> tuple[list[ComprovanteDoGrupo], list[VendaRegistrada]]:
    """A foto foi apagada: o comprovante nascido dela deixa de provar, e o abate e desfeito.

    Devolve (comprovantes anulados, vendas soltas). As vendas voltam para a fila de "falta
    comprovar" — que e exatamente onde elas estavam antes da foto errada — em vez de ficarem
    marcadas como pagas por uma prova que nao existe mais no grupo.

    Diferente da Cobranca da agencia, aqui NAO ha o filtro "so a pendente": um comprovante nao tem
    estado intermediario, e quem apagou a foto foi quem a mandou. O simetrico ja e garantido do
    outro lado — apagar o ANUNCIO nao mexe no comprovante, so anula a venda.

    A anulacao tambem solta a chave do dedup de conteudo (`WHERE ... anulado_em IS NULL` no indice
    parcial): quem apagou por engano precisa poder reenviar a MESMA foto.
    """
    cur = await conn.execute(
        f"""
        UPDATE barravips.comprovantes_do_grupo
           SET anulado_em = now()
         WHERE mensagem_id = %s AND anulado_em IS NULL
        RETURNING {_CAMPOS_DO_COMPROVANTE}
        """,
        (mensagem_id,),
    )
    anulados = [_comprovante(row) for row in await cur.fetchall()]
    if not anulados:
        return [], []

    cur = await conn.execute(
        f"""
        UPDATE barravips.vendas_registradas
           SET comprovante_id = NULL
         WHERE comprovante_id = ANY(%s) AND anulada_em IS NULL
        RETURNING {_CAMPOS_DA_VENDA}
        """,
        ([c.id for c in anulados],),
    )
    return anulados, [_venda(row) for row in await cur.fetchall()]


# --- fechamento (ticket 09) ---------------------------------------------------------------------


async def vendas_da_modelo(conn: AsyncConnection[Any], modelo_id: UUID) -> list[VendaRegistrada]:
    """TODAS as Vendas registradas vivas da modelo, da mais antiga para a mais nova.

    Escopo MODELO e sem recorte de data, como o Fechamento manda (docs/dominio): saldo corrente
    continuo, sem periodos estanques. Filtrar por mes aqui faria o extrato "fechar" um periodo — e
    a venda de tres semanas atras que ninguem comprovou sumiria da conta exatamente quando ela
    passa a ser o problema.

    Devolve a venda inteira (e nao SUMs) porque quem soma e o dominio: as tres colunas, a
    diferenca e as Pendencias saem todas da MESMA leitura, e derivar pendencia de uma consulta e
    o total de outra e como um extrato passa a nao fechar consigo mesmo.
    """
    cur = await conn.execute(
        f"""
        SELECT {_CAMPOS_DA_VENDA}
          FROM barravips.vendas_registradas
         WHERE modelo_id = %s
           AND anulada_em IS NULL
         ORDER BY data, id
        """,
        (modelo_id,),
    )
    return [_venda(row) for row in await cur.fetchall()]


async def comprovantes_da_modelo(
    conn: AsyncConnection[Any], modelo_id: UUID
) -> list[ComprovanteDoGrupo]:
    """Os Comprovantes de transferencia dos grupos DELA, do mais antigo para o mais novo.

    Escopo modelo (e nao grupo) pelo mesmo motivo de `vendas_pix_a_comprovar`: a conferencia e
    vendido x comprovado **por modelo**, e um comprovante postado no grupo da outra participante
    e dinheiro dela do mesmo jeito.

    Traz tambem o retido (`nao_classificado`) e o ilegivel: sao eles que viram divergencia no
    extrato. Comprovante que nao casou e a prova de que dinheiro saiu — esconde-lo da conferencia
    seria fechar a conta ignorando o unico dado que nao fecha.

    O ANULADO (ticket 05: a foto foi apagada no grupo) fica de fora, e e a excecao que confirma a
    regra acima: dele nao se sabe mais nem que o dinheiro saiu. As vendas que ele abatia ja
    voltaram para a fila na anulacao.
    """
    cur = await conn.execute(
        f"""
        SELECT {_CAMPOS_DO_COMPROVANTE}
          FROM barravips.comprovantes_do_grupo c
         WHERE c.grupo_id IN (
                   SELECT id FROM barravips.grupos_financeiros WHERE modelo_id = %s
               )
           AND c.anulado_em IS NULL
         ORDER BY c.created_at
        """,
        (modelo_id,),
    )
    return [_comprovante(row) for row in await cur.fetchall()]


# --- dados cadastrais oportunistas (ticket 12) --------------------------------------------------

_COLUNAS_DO_DADO_CADASTRAL = (
    "id",
    "modelo_id",
    "campo",
    "valor",
    "valor_anterior",
    "mensagem_id",
    "observado_em",
)


async def dado_cadastral_atual(
    conn: AsyncConnection[Any], modelo_id: UUID, campo: CampoCadastral
) -> DadoCadastralRegistrado | None:
    """O que vale HOJE neste campo — a observacao mais recente. `None` = nunca foi dito.

    A tabela e append-only: "o valor de agora" e uma leitura, nao uma coluna. Custa o indice
    `(modelo_id, campo, observado_em DESC)` e paga com um historico que ninguem consegue apagar
    sem querer.
    """
    cur = await conn.execute(
        """
        SELECT id, modelo_id, campo, valor, valor_anterior, mensagem_id, observado_em
          FROM barravips.modelo_dados_cadastrais
         WHERE modelo_id = %s AND campo = %s
         ORDER BY observado_em DESC, id DESC
         LIMIT 1
        """,
        (modelo_id, campo),
    )
    row = await cur.fetchone()
    return None if row is None else _dado_cadastral(row)


async def registrar_dado_cadastral(
    conn: AsyncConnection[Any],
    *,
    modelo_id: UUID,
    campo: CampoCadastral,
    valor: str,
    mensagem_id: UUID | None,
    observado_em: datetime | None = None,
) -> DadoCadastralRegistrado | None:
    """Observa o dado. Devolve `None` quando ele ja era esse — repetir nao e mudar.

    `observado_em` e o relogio do GRUPO (quando a mensagem foi recebida), nao o do commit: e ele
    que ordena o historico e elege o valor ATUAL do campo (`ORDER BY observado_em DESC, id DESC`).
    Deixar no `now()` do banco faz duas observacoes gravadas na mesma transacao empatarem, e o
    desempate cai no id v7 do mesmo milissegundo — sorteio decidindo qual endereco da modelo o
    painel mostra. `None` mantem o default do banco para quem grava fora de uma mensagem.

    O `valor_anterior` e gravado na MESMA linha e na MESMA transacao do efeito: auditoria que
    pode faltar quando o efeito aconteceu nao e auditoria, e o valor antigo so existe aqui (o
    campo em si nao guarda historia).

    `ON CONFLICT DO NOTHING` sobre o indice parcial `(mensagem_id, campo)`: se algum caminho
    futuro reprocessar a mesma mensagem, ela nao vira uma segunda observacao com
    `valor_anterior` igual ao `valor` — um evento de auditoria que nunca aconteceu.
    """
    atual = await dado_cadastral_atual(conn, modelo_id, campo)
    if atual is not None and mesmo_valor(campo, atual.valor, valor):
        return None
    cur = await conn.execute(
        """
        INSERT INTO barravips.modelo_dados_cadastrais
            (modelo_id, campo, valor, valor_anterior, mensagem_id, observado_em)
        VALUES (%s, %s, %s, %s, %s, COALESCE(%s, now()))
        ON CONFLICT (mensagem_id, campo) WHERE mensagem_id IS NOT NULL DO NOTHING
        RETURNING id, modelo_id, campo, valor, valor_anterior, mensagem_id, observado_em
        """,
        (
            modelo_id,
            campo,
            valor,
            None if atual is None else atual.valor,
            mensagem_id,
            observado_em,
        ),
    )
    row = await cur.fetchone()
    return None if row is None else _dado_cadastral(row)


async def historico_de_dados_cadastrais(
    conn: AsyncConnection[Any], modelo_id: UUID
) -> list[DadoCadastralRegistrado]:
    """Todas as observacoes da modelo, da mais recente para a mais antiga.

    A leitura de AUDITORIA (e a do painel, ticket 11): e por ela que se ve que o apartamento ja
    foi outro e qual mensagem do grupo mudou.
    """
    cur = await conn.execute(
        """
        SELECT id, modelo_id, campo, valor, valor_anterior, mensagem_id, observado_em
          FROM barravips.modelo_dados_cadastrais
         WHERE modelo_id = %s
         ORDER BY observado_em DESC, id DESC
        """,
        (modelo_id,),
    )
    return [_dado_cadastral(row) for row in await cur.fetchall()]


def _dado_cadastral(row: Any) -> DadoCadastralRegistrado:
    dados = _como_dict(row, _COLUNAS_DO_DADO_CADASTRAL)
    return DadoCadastralRegistrado(
        id=dados["id"],
        modelo_id=dados["modelo_id"],
        campo=cast(CampoCadastral, dados["campo"]),
        valor=dados["valor"],
        valor_anterior=dados["valor_anterior"],
        mensagem_id=dados["mensagem_id"],
        observado_em=dados["observado_em"],
    )


# --- rotina diaria da manha (ticket 10) ---------------------------------------------------------


async def grupos_financeiros_ativos(conn: AsyncConnection[Any]) -> list[GrupoFinanceiro]:
    """Os Grupos financeiros que o agente atende, em ordem estavel.

    A rotina da manha nasce de RELOGIO, entao ela e o unico lugar do modulo que precisa da lista
    (todo o resto chega por um JID que ja veio na mensagem). `ativo=false` fica de fora pelo mesmo
    motivo de `buscar_grupo_por_jid`: inativar e desligar a ingestao E a fala daquele grupo.

    **So os grupos de papel `modelo`** (ADR-0046 §2). Desde a onda `20260820`, `grupos_financeiros`
    guarda tambem o Grupo de fichas e o caixa dos telefonistas, e nesses `modelo_id` e NULO — a
    modelo do card vem do resolver closed-world, nao do JID. Sem este filtro a rotina da manha
    montaria um `GrupoFinanceiro` com `modelo_id=None` (o dataclass declara `UUID`, nao
    `UUID | None`, entao nem levanta aqui) e iria cobrar pendencia "da modelo None" num grupo onde
    nenhuma modelo le. O filtro precede o cadastro do primeiro grupo novo, de proposito: depois
    dele, o bug ja teria acontecido uma vez.
    """
    cur = await conn.execute(
        """
        SELECT id, modelo_id, jid, nome
          FROM barravips.grupos_financeiros
         WHERE ativo
           AND papel = 'modelo'
         ORDER BY created_at, id
        """
    )
    colunas = ("id", "modelo_id", "jid", "nome")
    return [
        GrupoFinanceiro(
            id=dados["id"], modelo_id=dados["modelo_id"], jid=dados["jid"], nome=dados["nome"] or ""
        )
        for dados in (_como_dict(row, colunas) for row in await cur.fetchall())
    ]


async def movimento_do_grupo(
    conn: AsyncConnection[Any], grupo_id: UUID, *, desde: datetime
) -> MovimentoDoGrupo:
    """Quanto dinheiro passou por este grupo desde `desde` — vendas registradas e comprovantes.

    A janela e por `created_at` (quando o registro NASCEU), nao pela data da venda: o que a
    rotina decide com isto e "este grupo se mexeu desde ontem?", e um anuncio de hoje sobre um
    atendimento da semana passada e movimento do mesmo jeito.

    Escopo GRUPO (a venda pela mensagem-fonte, o comprovante pela coluna): falar ou calar e
    decisao deste grupo. A modelo pode ter tido movimento no grupo da parceira sem que ninguem
    aqui tenha o que responder.
    """
    cur = await conn.execute(
        """
        SELECT
          (SELECT count(*) FROM barravips.vendas_registradas v
             JOIN barravips.grupo_financeiro_mensagens m ON m.id = v.mensagem_id
            WHERE m.grupo_id = %(grupo)s
              AND v.anulada_em IS NULL
              AND v.created_at >= %(desde)s)                        AS vendas,
          (SELECT coalesce(sum(v.valor), 0) FROM barravips.vendas_registradas v
             JOIN barravips.grupo_financeiro_mensagens m ON m.id = v.mensagem_id
            WHERE m.grupo_id = %(grupo)s
              AND v.anulada_em IS NULL
              AND v.created_at >= %(desde)s)                        AS valor,
          (SELECT count(*) FROM barravips.comprovantes_do_grupo c
            WHERE c.grupo_id = %(grupo)s
              AND c.anulado_em IS NULL
              AND c.created_at >= %(desde)s)                        AS comprovantes
        """,
        {"grupo": grupo_id, "desde": desde},
    )
    row = await cur.fetchone()
    if row is None:  # pragma: no cover - os tres subselects sempre devolvem uma linha
        return MovimentoDoGrupo()
    dados = _como_dict(row, ("vendas", "valor", "comprovantes"))
    return MovimentoDoGrupo(
        vendas=int(dados["vendas"]),
        valor=Decimal(dados["valor"]),
        comprovantes=int(dados["comprovantes"]),
    )


async def reservar_fala_da_rotina(
    conn: AsyncConnection[Any],
    grupo_id: UUID,
    *,
    chave: str,
    texto: str,
    em: datetime,
) -> UUID | None:
    """Reserva a fala do dia no log de origem. `None` = a rotina JA falou neste grupo hoje.

    Duas coisas num INSERT so, e e por isso que nao existe tabela de execucoes da rotina:

    * **Idempotencia** — `chave_dedup` e UNIQUE, entao o segundo disparo do dia (retry do cron,
      redeploy do worker, dois workers no Swarm) nao insere linha e a rotina para ali. O mesmo
      mecanismo que absorve a entrega duplicada do webhook; uma tabela nova so daria ao modulo um
      segundo estado a reconciliar.
    * **Contexto** — a fala fica no log como mensagem `de_mim`, e e ASSIM que a resposta do humano
      encontra a venda certa depois: `escolher_pagamento` varre o contexto recente atras da
      mensagem que nomeia UMA venda aberta, e a cobranca da manha e essa mensagem. Sem a linha
      aqui, "pix" respondido as 9h cairia na venda mais recente por falta de sinal.

    Reservar ANTES de entregar e deliberado: se a Evolution falhar depois, o grupo fica calado
    hoje e a pendencia (que e derivada, nao consumida) volta a ser cobrada amanha. O inverso —
    entregar e so depois reservar — arrisca a mesma cobranca duas vezes no mesmo dia, que e o
    ruido que faz a operacao desligar o agente.
    """
    cur = await conn.execute(
        """
        INSERT INTO barravips.grupo_financeiro_mensagens
            (grupo_id, chave_dedup, de_mim, tipo, texto, recebida_em)
        VALUES (%s, %s, true, 'texto', %s, %s)
        ON CONFLICT (chave_dedup) DO NOTHING
        RETURNING id
        """,
        (grupo_id, chave, texto, em),
    )
    row = await cur.fetchone()
    if row is None:
        return None
    return cast(UUID, _como_dict(row, ("id",))["id"])


# --- leituras do painel (ticket 11) -------------------------------------------------------------
#
# Sao as UNICAS consultas deste arquivo com recorte de data: o agente vive no saldo corrente
# continuo (sem periodo estanque), o painel recorta um periodo porque quem olha o painel esta
# perguntando "quanto entrou em agosto?". Recorte de LEITURA no painel nao e periodo que fecha —
# nada aqui muda o que o Fechamento (derivado, sem janela) responde ao grupo.


async def primeira_venda_registrada(
    conn: AsyncConnection[Any], modelo_ids: Sequence[UUID] | None = None
) -> date | None:
    """Data da Venda registrada mais antiga viva — a borda esquerda do periodo "tudo" no painel.

    Existe porque hoje `atendimentos` esta VAZIO em producao (ADR-0043): sem este piso, "tudo"
    ancoraria no fallback de 2020 e o grafico do operador seria seis anos de vao ate a primeira
    venda anunciada no grupo.
    """
    filtro = ""
    params: list[Any] = []
    if modelo_ids:
        filtro = "AND modelo_id = ANY(%s)"
        params.append(list(modelo_ids))
    cur = await conn.execute(
        f"""
        SELECT MIN(data) AS piso
          FROM barravips.vendas_registradas
         WHERE anulada_em IS NULL {filtro}
        """,
        params,
    )
    row = await cur.fetchone()
    if row is None:
        return None
    piso = _como_dict(row, ("piso",))["piso"]
    return cast("date | None", piso)


async def receita_registrada(
    conn: AsyncConnection[Any],
    *,
    de: date,
    ate: date,
    modelo_ids: Sequence[UUID] | None = None,
) -> tuple[int, Decimal]:
    """(quantas, quanto) de Venda registrada no periodo — a SEGUNDA fonte de receita (ADR-0043).

    Anulada fora (a linha existe so como rastro) e nenhuma juncao com `atendimentos`: as duas
    fontes sao disjuntas por construcao, porque o grupo NUNCA fabrica Atendimento nem Cliente.
    Somar as duas nao dobra nada hoje; o dia em que a IA de venda estiver em producao e a mesma
    venda puder entrar pelas duas portas exige decisao propria de precedencia (ADR-0043,
    "Consequencias") — nao um `DISTINCT` esperto aqui.

    A data e a **data da venda** (o dia em que o atendimento aconteceu, como o grupo conta), e nao
    o `created_at` da linha: um anuncio de ontem postado hoje e receita de ontem.
    """
    filtro = ""
    params: list[Any] = [de, ate]
    if modelo_ids:
        filtro = "AND modelo_id = ANY(%s)"
        params.append(list(modelo_ids))
    cur = await conn.execute(
        f"""
        SELECT COUNT(*)::int AS contagem, COALESCE(SUM(valor), 0)::numeric AS total
          FROM barravips.vendas_registradas
         WHERE anulada_em IS NULL
           AND data >= %s AND data <= %s
           {filtro}
        """,
        params,
    )
    row = await cur.fetchone()
    assert row is not None  # agregado sempre devolve uma linha
    dados = _como_dict(row, ("contagem", "total"))
    return int(dados["contagem"]), Decimal(dados["total"])


# --- a metrica de origem e site (ticket 16) ------------------------------------------------------
#
# Duas leituras irmas de `receita_registrada`, com o mesmo recorte (data da VENDA, anulada fora) e
# a mesma disciplina: nenhuma delas some com a fatia "nao dito". A pergunta do dono e comparativa
# ("onde eu invisto?"), e um relatorio que esconde o que ninguem informou faz o eixo mais preenchido
# parecer o mais rentavel.
#
# Sao DUAS consultas e nao uma com dois GROUP BY porque `origem` e `site` sao dois campos, nao dois
# niveis do mesmo: um card pode dizer o site sem marcar a origem, e vice-versa. Cruzar os dois numa
# so obrigaria o painel a somar as celulas de volta para responder qualquer uma das duas perguntas.


async def faturamento_por_origem(
    conn: AsyncConnection[Any],
    *,
    de: date,
    ate: date,
    modelo_ids: Sequence[UUID] | None = None,
) -> list[FaturamentoPorOrigem]:
    """Quanto o anuncio proprio faturou e quanto o fake faturou no periodo (spec 0006 §45).

    Uma linha por eixo, incluindo `origem = NULL` — a venda cuja origem ninguem disse. O total das
    linhas bate com `receita_registrada` no mesmo periodo, e e assim que o operador confere que a
    metrica nao perdeu venda pelo caminho.
    """
    filtro = ""
    params: list[Any] = [de, ate]
    if modelo_ids:
        filtro = "AND modelo_id = ANY(%s)"
        params.append(list(modelo_ids))
    cur = await conn.execute(
        f"""
        SELECT origem::text AS origem,
               COUNT(*)::int AS vendas,
               COALESCE(SUM(valor), 0)::numeric AS total
          FROM barravips.vendas_registradas
         WHERE anulada_em IS NULL
           AND data >= %s AND data <= %s
           {filtro}
         GROUP BY origem
         ORDER BY total DESC, origem
        """,
        params,
    )
    return [
        FaturamentoPorOrigem(
            origem=cast("OrigemDoAnuncio | None", dados["origem"]),
            vendas=int(dados["vendas"]),
            total=Decimal(dados["total"]),
        )
        for dados in (
            _como_dict(row, ("origem", "vendas", "total")) for row in await cur.fetchall()
        )
    ]


async def faturamento_por_site(
    conn: AsyncConnection[Any],
    *,
    de: date,
    ate: date,
    modelo_ids: Sequence[UUID] | None = None,
) -> list[FaturamentoPorSite]:
    """Quanto cada plataforma faturou no periodo (spec 0006 §68) — a metrica mais fina que a origem.

    Agrupa pela coluna como ela foi GRAVADA: a grafia canonica e responsabilidade da escrita
    (`ficha.normalizar_site`), nao de um `lower()` na consulta. Normalizar aqui esconderia do
    operador que dois cards escreveram a mesma plataforma de dois jeitos, e e ele quem decide se
    "Barra Vips" e "barravips" sao a mesma coisa quando um nome novo aparecer.
    """
    filtro = ""
    params: list[Any] = [de, ate]
    if modelo_ids:
        filtro = "AND modelo_id = ANY(%s)"
        params.append(list(modelo_ids))
    cur = await conn.execute(
        f"""
        SELECT site,
               COUNT(*)::int AS vendas,
               COALESCE(SUM(valor), 0)::numeric AS total
          FROM barravips.vendas_registradas
         WHERE anulada_em IS NULL
           AND data >= %s AND data <= %s
           {filtro}
         GROUP BY site
         ORDER BY total DESC, site
        """,
        params,
    )
    return [
        FaturamentoPorSite(
            site=dados["site"],
            vendas=int(dados["vendas"]),
            total=Decimal(dados["total"]),
        )
        for dados in (_como_dict(row, ("site", "vendas", "total")) for row in await cur.fetchall())
    ]


async def listar_vendas_no_painel(
    conn: AsyncConnection[Any],
    *,
    de: date,
    ate: date,
    modelo_ids: Sequence[UUID] | None = None,
    incluir_anuladas: bool = False,
    limit: int,
    cursor: tuple[date, UUID] | None = None,
) -> tuple[list[VendaNoPainel], tuple[date, UUID] | None]:
    """A lista auditavel: keyset por (data DESC, id DESC), uma linha por Venda registrada.

    **`incluir_anuladas` e o unico lugar do modulo onde a venda anulada aparece.** Toda leitura de
    agente filtra `anulada_em IS NULL` (cabecalho deste arquivo); aqui o operador pode pedir para
    ver o rastro — foi para isso que a anulacao virou estado em vez de DELETE. Default `False`
    para que a lista de todo dia continue sendo a operacao viva.

    O LEFT JOIN no comprovante traz a chave de destino que o OCR leu: e dela que sai a flag de
    chave desconhecida, e ela vem da MESMA coluna que o agente avaliou quando avisou no grupo
    (`chave_conhecida`) — reavaliar a chave aqui contra o cadastro de hoje faria o painel
    contradizer o aviso que o grupo ja leu.
    """
    filtros: list[str] = []
    params: list[Any] = [de, ate]
    if not incluir_anuladas:
        filtros.append("v.anulada_em IS NULL")
    if modelo_ids:
        filtros.append("v.modelo_id = ANY(%s)")
        params.append(list(modelo_ids))
    if cursor:
        dia, venda_id = cursor
        filtros.append("(v.data, v.id) < (%s, %s)")
        params.extend([dia, venda_id])
    filtro_sql = ("AND " + " AND ".join(filtros)) if filtros else ""
    params.append(limit + 1)  # +1 detecta a proxima pagina

    cur = await conn.execute(
        f"""
        SELECT {_CAMPOS_DA_VENDA_V},
               m.nome AS modelo_nome,
               c.id IS NOT NULL AS tem_comprovante,
               c.chave_destino,
               COALESCE(c.chave_conhecida, false) AS chave_conhecida
          FROM barravips.vendas_registradas v
          JOIN barravips.modelos m ON m.id = v.modelo_id
          LEFT JOIN barravips.comprovantes_do_grupo c ON c.id = v.comprovante_id
         WHERE v.data >= %s AND v.data <= %s
           {filtro_sql}
         ORDER BY v.data DESC, v.id DESC
         LIMIT %s
        """,
        params,
    )
    rows = list(await cur.fetchall())
    pagina = rows[:limit]
    proximo: tuple[date, UUID] | None = None
    if len(rows) > limit and pagina:
        ultima = _como_dict(pagina[-1], _COLUNAS_DA_VENDA + _EXTRAS_DO_PAINEL)
        proximo = (ultima["data"], ultima["id"])
    return [_venda_no_painel(row) for row in pagina], proximo


_EXTRAS_DO_PAINEL = ("modelo_nome", "tem_comprovante", "chave_destino", "chave_conhecida")


def _venda_no_painel(row: Any) -> VendaNoPainel:
    dados = _como_dict(row, _COLUNAS_DA_VENDA + _EXTRAS_DO_PAINEL)
    return VendaNoPainel(
        venda=_venda(dados),
        modelo_nome=dados["modelo_nome"],
        tem_comprovante=bool(dados["tem_comprovante"]),
        chave_destino=dados["chave_destino"],
        chave_conhecida=bool(dados["chave_conhecida"]),
    )


def _venda(row: Any) -> VendaRegistrada:
    dados = _como_dict(row, _COLUNAS_DA_VENDA)
    return VendaRegistrada(
        id=dados["id"],
        modelo_id=dados["modelo_id"],
        valor=dados["valor"],
        data=dados["data"],
        mensagem_id=dados["mensagem_id"],
        cliente_nome=dados["cliente_nome"],
        local_atendimento=dados["local_atendimento"],
        duracao_minutos=dados["duracao_minutos"],
        forma_pagamento=dados["forma_pagamento"],
        comprovante_id=dados["comprovante_id"],
        anulada_em=dados["anulada_em"],
        recebido_por_modelo_id=dados["recebido_por_modelo_id"],
    )


def _venda_com_bolso(row: Any) -> VendaComBolso:
    dados = _como_dict(row, _COLUNAS_DO_BOLSO)
    return VendaComBolso(
        id=dados["id"],
        modelo_id=dados["modelo_id"],
        valor=dados["valor"],
        data=dados["data"],
        bolso=dados["bolso"],
        forma_pagamento=dados["forma_pagamento"],
        cliente_nome=dados["cliente_nome"],
        bolso_mensagem_id=dados["bolso_mensagem_id"],
    )


def _cobranca(row: Any) -> CobrancaDaAgencia:
    dados = _como_dict(row, _COLUNAS_DA_COBRANCA)
    return CobrancaDaAgencia(
        id=dados["id"],
        grupo_id=dados["grupo_id"],
        modelo_id=dados["modelo_id"],
        mensagem_id=dados["mensagem_id"],
        descricao=dados["descricao"],
        valor=dados["valor"],
        data=dados["data"],
        comprovante_id=dados["comprovante_id"],
        quitada_em=dados["quitada_em"],
        anulada_em=dados["anulada_em"],
    )


def _comprovante(row: Any) -> ComprovanteDoGrupo:
    dados = _como_dict(row, _COLUNAS_DO_COMPROVANTE)
    return ComprovanteDoGrupo(
        id=dados["id"],
        grupo_id=dados["grupo_id"],
        mensagem_id=dados["mensagem_id"],
        classificacao=dados["classificacao"],
        valor=dados["valor"],
        data_transferencia=dados["data_transferencia"],
        pagador=dados["pagador"],
        chave_destino=dados["chave_destino"],
        titular_destino=dados["titular_destino"],
        chave_conhecida=bool(dados["chave_conhecida"]),
        valor_abatido=dados["valor_abatido"],
        estabelecimento=dados["estabelecimento"],
    )


def _como_dict(row: Any, colunas: tuple[str, ...]) -> dict[str, Any]:
    """Aceita `dict_row` (padrao da casa) e tupla crua (conexao sem row_factory)."""
    if isinstance(row, dict):
        return row
    return dict(zip(colunas, row, strict=False))


# --- temporada e razao (ticket 02) --------------------------------------------------------------
#
# **Nenhuma destas leituras tem recorte de periodo, e isso e o desenho** (ADR-0045 §7): elas
# devolvem a vida inteira da modelo, e quem quer o recorte da Temporada filtra em
# `temporada.lancamentos_do_razao(inicio=..., fim=...)`. Periodo no SQL faria o comprovante que
# chega tres dias depois do fim da temporada sumir da consulta em vez de recalcular o saldo — que
# e exatamente o congelamento que a Temporada nao faz.

_COLUNAS_DA_TEMPORADA = (
    "id",
    "modelo_id",
    "cidade",
    "data_inicio",
    "data_fim",
    "estado",
    "observacao",
    "fechada_em",
)

_CAMPOS_DA_TEMPORADA = """id, modelo_id, cidade, data_inicio, data_fim, estado, observacao,
                          fechada_em"""

_COLUNAS_DO_PAGAMENTO = (
    "id",
    "modelo_id",
    "valor",
    "data_pagamento",
    "temporada_id",
    "forma_pagamento",
    "observacao",
)

_CAMPOS_DO_PAGAMENTO = """id, modelo_id, valor, data_pagamento, temporada_id, forma_pagamento,
                          observacao"""

_COLUNAS_DA_VENDA_DO_RAZAO = (
    "id",
    "modelo_id",
    "valor",
    "data",
    "bolso",
    "percentual_repasse_snapshot",
    "recebido_por_modelo_id",
    "cliente_nome",
)

_COLUNAS_DA_TRANSFERENCIA = ("id", "valor", "data", "classificacao")

_COLUNAS_DO_DESLOCAMENTO = (
    "id",
    "venda_id",
    "modelo_id",
    "data",
    "valor_antecipado",
    "valor_transporte",
    "recebedor_do_antecipado",
    "pagador_do_transporte",
)

_COLUNAS_DO_LANCAMENTO_MANUAL = (
    "id",
    "modelo_id",
    "tipo",
    "sentido",
    "valor",
    "data",
    "origem",
    "descricao",
    "mensagem_id",
    "temporada_id",
)

_CAMPOS_DO_LANCAMENTO_MANUAL = """id, modelo_id, tipo, sentido, valor, data, origem, descricao,
                                  mensagem_id, temporada_id"""

# A MESMA projecao qualificada, para quando a consulta junta a mensagem-fonte (o quote). Existe
# pelo mesmo motivo de `_CAMPOS_DA_VENDA_V`: `grupo_financeiro_mensagens` tambem tem `id` e
# tambem tem `tipo` (la e texto/audio/imagem, aqui e vale/ajuste), entao a projecao crua sai
# ambigua no JOIN. `id` sem alias e o pior dos dois — e ele que a correcao por quote usa como
# alvo do UPDATE, e um `id` da tabela errada corrigiria a linha errada.
_CAMPOS_DO_LANCAMENTO_MANUAL_R = """r.id, r.modelo_id, r.tipo, r.sentido, r.valor, r.data,
                                    r.origem, r.descricao, r.mensagem_id, r.temporada_id"""


async def criar_temporada(
    conn: AsyncConnection[Any],
    *,
    modelo_id: UUID,
    cidade: str,
    data_inicio: date,
    data_fim: date,
    observacao: str | None = None,
    created_by: UUID | None = None,
) -> Temporada:
    """Abre a Temporada da modelo. Nasce `aberta` — o estado e marca de rotina, nao trava.

    Sem `ON CONFLICT`: nao ha chave de conteudo aqui e o banco nao impede duas temporadas
    sobrepostas da mesma modelo (exigiria `btree_gist`, extensao que o projeto nao usa).
    Sobreposicao e erro de operacao, visivel no painel — e nao um fato que o agente registra
    sozinho: quem abre temporada e gente, pela tela.
    """
    cur = await conn.execute(
        f"""
        INSERT INTO barravips.temporadas
            (modelo_id, cidade, data_inicio, data_fim, observacao, created_by)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING {_CAMPOS_DA_TEMPORADA}
        """,
        (modelo_id, cidade, data_inicio, data_fim, observacao, created_by),
    )
    row = await cur.fetchone()
    if row is None:  # pragma: no cover - INSERT sem ON CONFLICT sempre devolve a linha
        raise RuntimeError("INSERT em barravips.temporadas nao devolveu linha")
    return _temporada(row)


async def temporada_por_id(conn: AsyncConnection[Any], temporada_id: UUID) -> Temporada | None:
    cur = await conn.execute(
        f"SELECT {_CAMPOS_DA_TEMPORADA} FROM barravips.temporadas WHERE id = %s",
        (temporada_id,),
    )
    row = await cur.fetchone()
    return None if row is None else _temporada(row)


async def temporadas_da_modelo(
    conn: AsyncConnection[Any], modelo_id: UUID, *, incluir_canceladas: bool = False
) -> list[Temporada]:
    """As temporadas da modelo, da mais recente para a mais antiga (a ordem em que o painel le).

    A cancelada fica de fora por default: a viagem nao aconteceu, entao ela nao e recorte de nada
    — mas continua no banco, porque cancelar tambem e rastro.
    """
    cur = await conn.execute(
        f"""
        SELECT {_CAMPOS_DA_TEMPORADA}
          FROM barravips.temporadas
         WHERE modelo_id = %s
           AND (%s::boolean OR estado <> 'cancelada')
         ORDER BY data_inicio DESC, id DESC
        """,
        (modelo_id, incluir_canceladas),
    )
    return [_temporada(row) for row in await cur.fetchall()]


async def fechar_temporada(conn: AsyncConnection[Any], temporada_id: UUID) -> Temporada | None:
    """Marca a temporada como fechada. `None` = ela ja estava fechada (ou cancelada).

    Fechar NAO congela calculo nenhum (ADR-0045 §7): o saldo continua derivado e um comprovante
    que chegar depois entra na conta do mesmo jeito. O que muda e a marca de rotina — e o
    pagamento, que e um `financeiro_repasses_pagos` com `temporada_id` e nao um campo daqui.

    O `estado = 'aberta'` no WHERE torna o clique duplo do painel inofensivo, e o `fechada_em` sai
    junto porque o banco exige os dois casados (`temporadas_fechada_tem_data`).
    """
    cur = await conn.execute(
        f"""
        UPDATE barravips.temporadas
           SET estado = 'fechada', fechada_em = now()
         WHERE id = %s AND estado = 'aberta'
        RETURNING {_CAMPOS_DA_TEMPORADA}
        """,
        (temporada_id,),
    )
    row = await cur.fetchone()
    return None if row is None else _temporada(row)


async def cancelar_temporada(conn: AsyncConnection[Any], temporada_id: UUID) -> Temporada | None:
    """A viagem nao aconteceu. `None` = ja cancelada, ou ja fechada — fechada nao volta atras.

    Cancelar uma temporada FECHADA seria apagar o recorte de um pagamento que ja saiu: os
    `financeiro_repasses_pagos` continuariam apontando para ela (`RESTRICT`), e o painel passaria
    a mostrar dinheiro pago numa viagem "que nao houve".
    """
    cur = await conn.execute(
        f"""
        UPDATE barravips.temporadas
           SET estado = 'cancelada'
         WHERE id = %s AND estado = 'aberta'
        RETURNING {_CAMPOS_DA_TEMPORADA}
        """,
        (temporada_id,),
    )
    row = await cur.fetchone()
    return None if row is None else _temporada(row)


async def pagamentos_da_temporada(
    conn: AsyncConnection[Any], temporada_id: UUID
) -> list[PagamentoDaTemporada]:
    """O que a casa JA pagou por esta temporada — o unico fato que a Temporada guarda.

    Le `financeiro_repasses_pagos` FILTRADO pela temporada, e nunca a tabela inteira: ela e a de
    repasse da modelo do Modulo Financeiro desde o ADR-0011 e carrega tambem os repasses de
    Atendimento, que sao outra fonte de receita (ADR-0043). Somar tudo faria um repasse de
    atendimento abater o razao do grupo, calado.
    """
    cur = await conn.execute(
        f"""
        SELECT {_CAMPOS_DO_PAGAMENTO}
          FROM barravips.financeiro_repasses_pagos
         WHERE temporada_id = %s
         ORDER BY data_pagamento, id
        """,
        (temporada_id,),
    )
    return [_pagamento_da_temporada(row) for row in await cur.fetchall()]


async def vendas_para_o_razao(conn: AsyncConnection[Any], modelo_id: UUID) -> list[VendaParaORazao]:
    """As vendas que tocam o razao DELA: as vendas dela **e** as que ela recebeu por outra.

    O `OR recebido_por_modelo_id = %s` e a festinha do ADR-0045 §6: a modelo que recebeu por
    todas carrega o debito do bruto das vendas das outras, e sem esta perna a consulta devolveria
    um saldo bonito para quem esta com o dinheiro de tres pessoas na mao. Quem separa os dois
    casos e `temporada._venda_no_razao`, que sabe de quem e a comissao.
    """
    cur = await conn.execute(
        """
        SELECT id, modelo_id, valor, data, bolso, percentual_repasse_snapshot,
               recebido_por_modelo_id, cliente_nome
          FROM barravips.vendas_registradas
         WHERE (modelo_id = %s OR recebido_por_modelo_id = %s)
           AND anulada_em IS NULL
         ORDER BY data, id
        """,
        (modelo_id, modelo_id),
    )
    return [_venda_para_o_razao(row) for row in await cur.fetchall()]


async def transferencias_para_o_razao(
    conn: AsyncConnection[Any], modelo_id: UUID
) -> list[TransferenciaParaORazao]:
    """Os comprovantes dos grupos dela com uma data que SEMPRE existe.

    `COALESCE(data_transferencia, created_at em BRT)`: o OCR pode nao ter lido a data, e credito
    sem data seria dinheiro invisivel para qualquer recorte de temporada — some da conta sem
    ninguem procurar. O fallback e o dia em que a foto chegou ao grupo, que e a melhor
    aproximacao disponivel e nunca fica longe.

    Traz TODAS as classificacoes (menos o anulado, que nao prova mais nada): quem decide que so a
    de `fechamento` credita e o dominio (`temporada.TRANSFERENCIA_PARA_A_CASA`), nao o SQL — a
    regra fica onde da para le-la e testa-la.
    """
    cur = await conn.execute(
        """
        SELECT c.id,
               c.valor,
               COALESCE(
                   c.data_transferencia,
                   (c.created_at AT TIME ZONE 'America/Sao_Paulo')::date
               ) AS data,
               c.classificacao
          FROM barravips.comprovantes_do_grupo c
         WHERE c.grupo_id IN (
                   SELECT id FROM barravips.grupos_financeiros WHERE modelo_id = %s
               )
           AND c.anulado_em IS NULL
           AND c.valor IS NOT NULL
         ORDER BY data, c.id
        """,
        (modelo_id,),
    )
    return [_transferencia_para_o_razao(row) for row in await cur.fetchall()]


async def deslocamentos_para_o_razao(
    conn: AsyncConnection[Any], modelo_id: UUID
) -> list[DeslocamentoParaORazao]:
    """Os deslocamentos das vendas cujo dinheiro e dela, com a modelo ja resolvida pelo JOIN.

    `deslocamentos_da_venda` nao tem coluna de modelo de proposito (duas verdades sobre "de quem
    e" foi o que o ADR-0045 §6 resolveu na venda), entao a modelo do lancamento e
    `COALESCE(v.recebido_por_modelo_id, v.modelo_id)` — a mesma regra do debito do bruto.

    A data e a da VENDA, e nao a do lancamento: e a venda que pertence a temporada.
    """
    cur = await conn.execute(
        """
        SELECT d.id,
               d.venda_id,
               COALESCE(v.recebido_por_modelo_id, v.modelo_id) AS modelo_id,
               v.data,
               d.valor_antecipado,
               d.valor_transporte,
               d.recebedor_do_antecipado,
               d.pagador_do_transporte
          FROM barravips.deslocamentos_da_venda d
          JOIN barravips.vendas_registradas v ON v.id = d.venda_id
         WHERE COALESCE(v.recebido_por_modelo_id, v.modelo_id) = %s
           AND d.anulado_em IS NULL
           AND v.anulada_em IS NULL
         ORDER BY v.data, d.id
        """,
        (modelo_id,),
    )
    return [_deslocamento_para_o_razao(row) for row in await cur.fetchall()]


async def registrar_deslocamento(
    conn: AsyncConnection[Any],
    *,
    venda_id: UUID,
    plano: PlanoDoDeslocamento,
    mensagem_id: UUID | None = None,
) -> UUID | None:
    """Grava o Deslocamento da venda (ticket 12). `None` = a venda ja tem um deslocamento vivo.

    Os DOIS valores vao juntos (ADR-0046 §6) porque sao dois fatos diferentes: o antecipado que o
    cliente mandou e o que o Uber custou. O `ON CONFLICT DO NOTHING` sobre o indice parcial
    `(venda_id) WHERE anulado_em IS NULL` e o que faz a segunda porta da promocao (o ✅ do
    telefonista chegando depois da fala da modelo) nao cobrar o transporte duas vezes — a mesma
    disciplina do dedup da venda, e pelo mesmo motivo: duas entregas concorrentes do mesmo fato
    passariam as duas por qualquer checagem previa.

    O plano com os dois valores zerados nunca chega aqui (`planejar_deslocamento` devolve `None`),
    e a coluna repete a regra no `CHECK (valor_antecipado > 0 OR valor_transporte > 0)`: a linha de
    deslocamento sem numero nenhum diria no painel que houve transporte sem dizer quanto.

    Nao ha coluna de modelo de proposito — a dona e a da venda (`COALESCE(recebido_por_modelo_id,
    modelo_id)`, como em `deslocamentos_para_o_razao`). Duas verdades sobre "de quem e" foi
    exatamente o que o ADR-0045 §6 resolveu guardando uma so, na venda.
    """
    cur = await conn.execute(
        """
        INSERT INTO barravips.deslocamentos_da_venda
            (venda_id, valor_antecipado, valor_transporte, forma_antecipado,
             recebedor_do_antecipado, pagador_do_transporte, mensagem_id)
        VALUES (%s, %s, %s, %s,
                %s::barravips.parte_do_deslocamento_enum,
                %s::barravips.parte_do_deslocamento_enum, %s)
        ON CONFLICT (venda_id) WHERE anulado_em IS NULL DO NOTHING
        RETURNING id
        """,
        (
            venda_id,
            plano.valor_antecipado,
            plano.valor_transporte,
            plano.forma_antecipado,
            plano.recebedor_do_antecipado,
            plano.pagador_do_transporte,
            mensagem_id,
        ),
    )
    row = await cur.fetchone()
    if row is None:
        return None
    return cast(UUID, _como_dict(row, ("id",))["id"])


async def lancamentos_manuais_da_modelo(
    conn: AsyncConnection[Any], modelo_id: UUID
) -> list[LancamentoManual]:
    """Os vales e ajustes VIVOS da modelo, do mais antigo para o mais novo.

    Anulado fica de fora pela mesma disciplina da venda: a linha continua no banco provando o que
    houve, e o razao nao a soma. Anular tambem solta a `chave_conteudo` para o repost.
    """
    cur = await conn.execute(
        f"""
        SELECT {_CAMPOS_DO_LANCAMENTO_MANUAL}
          FROM barravips.razao_lancamentos_manuais
         WHERE modelo_id = %s
           AND anulado_em IS NULL
         ORDER BY data, id
        """,
        (modelo_id,),
    )
    return [_lancamento_manual(row) for row in await cur.fetchall()]


async def registrar_lancamento_manual(
    conn: AsyncConnection[Any],
    *,
    modelo_id: UUID,
    tipo: TipoDeLancamentoManual,
    sentido: SentidoDoLancamento,
    valor: Decimal,
    data: date,
    origem: OrigemDoLancamento,
    descricao: str | None = None,
    mensagem_id: UUID | None = None,
    temporada_id: UUID | None = None,
    chave_conteudo: str | None = None,
    created_by: UUID | None = None,
) -> LancamentoManual | None:
    """Insere o vale/ajuste e devolve a linha. `None` = ja existia (repost do grupo).

    `valor` e SEMPRE positivo e a direcao vai em `sentido` — o banco recusa o resto (e recusa
    tambem vale que nao seja debito, e origem `grupo` sem `mensagem_id`).

    O `ON CONFLICT (chave_conteudo) WHERE ... DO NOTHING` e o mesmo dedup da Venda registrada, e
    o `chave_conteudo IS NOT NULL` na inferencia e o indice parcial: o que nasce no PAINEL nao
    tem chave e nunca deduplica — la o gestor e responsavel pelo que digita, e dois vales iguais
    no mesmo dia sao um caso real.
    """
    cur = await conn.execute(
        f"""
        INSERT INTO barravips.razao_lancamentos_manuais
            (modelo_id, tipo, sentido, valor, data, descricao, origem, mensagem_id, temporada_id,
             chave_conteudo, created_by)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (chave_conteudo)
            WHERE chave_conteudo IS NOT NULL AND anulado_em IS NULL DO NOTHING
        RETURNING {_CAMPOS_DO_LANCAMENTO_MANUAL}
        """,
        (
            modelo_id,
            tipo,
            sentido,
            valor,
            data,
            descricao,
            origem,
            mensagem_id,
            temporada_id,
            chave_conteudo,
            created_by,
        ),
    )
    row = await cur.fetchone()
    return None if row is None else _lancamento_manual(row)


async def lancamento_manual_por_chave_de_conteudo(
    conn: AsyncConnection[Any], chave_conteudo: str
) -> LancamentoManual | None:
    """O vale que JA representa este fato — quem venceu o dedup. E ele que o aviso cita."""
    cur = await conn.execute(
        f"""
        SELECT {_CAMPOS_DO_LANCAMENTO_MANUAL}
          FROM barravips.razao_lancamentos_manuais
         WHERE chave_conteudo = %s
           AND anulado_em IS NULL
         LIMIT 1
        """,
        (chave_conteudo,),
    )
    row = await cur.fetchone()
    return None if row is None else _lancamento_manual(row)


async def lancamentos_manuais_da_mensagem_citada(
    conn: AsyncConnection[Any], grupo_id: UUID, evolution_message_id: str
) -> list[LancamentoManual]:
    """Os vales VIVOS ancorados na mensagem que o autor citou — o alvo da correcao por quote.

    Espelho exato de `vendas_da_mensagem_citada`, inclusive no segundo salto: duas mensagens
    ancoram o mesmo vale — a FALA do gestor ("adiantei 500 pra ela") e o RECIBO que o agente
    postou citando essa fala. Corrigir respondendo o recibo, que e o que o proprio recibo pede,
    tem que valer tanto quanto corrigir respondendo a fala.

    Escopo pelo GRUPO, e nao pela modelo: `razao_lancamentos_manuais` nao tem grupo, mas a
    mensagem-fonte tem, e e ela que diz onde o quote aconteceu. O lancamento do PAINEL nunca
    aparece aqui — ele nasce sem `mensagem_id`, e nenhum quote no WhatsApp pode alcanca-lo.
    """
    cur = await conn.execute(
        f"""
        WITH citada AS (
            SELECT id, quoted_message_id
              FROM barravips.grupo_financeiro_mensagens
             WHERE grupo_id = %s AND evolution_message_id = %s
             LIMIT 1
        )
        SELECT {_CAMPOS_DO_LANCAMENTO_MANUAL_R}
          FROM barravips.razao_lancamentos_manuais r
          JOIN barravips.grupo_financeiro_mensagens m ON m.id = r.mensagem_id
          JOIN citada c ON m.id = c.id OR m.evolution_message_id = c.quoted_message_id
         WHERE r.anulado_em IS NULL
         ORDER BY r.data, r.id
        """,
        (grupo_id, evolution_message_id),
    )
    return [_lancamento_manual(row) for row in await cur.fetchall()]


async def corrigir_lancamento_manual(
    conn: AsyncConnection[Any],
    lancamento_id: UUID,
    *,
    valor: Decimal,
    data: date,
    chave_conteudo: str | None,
) -> LancamentoManual | None:
    """Grava o estado JA corrigido do vale. `None` = a correcao nao coube (ou o vale morreu).

    Corrige VALOR e DATA e mais nada, de proposito: `tipo`, `sentido` e `origem` sao a identidade
    do lancamento, e trocar qualquer um deles por uma frase no grupo transformaria um vale em
    ajuste (ou um debito em credito) sem ninguem conferir — a correcao que inverte o sinal do
    saldo precisa de gente e de tela.

    A `chave_conteudo` viaja junto porque ela segue o FATO: sem recalcula-la o dedup continuaria
    vigiando o vale de R$ 500,00 que nao existe mais, e o repost da fala ja corrigida nasceria
    como um segundo debito vivo. Colidir com a chave de outro vale vivo devolve `None`, do mesmo
    jeito que `corrigir_venda` — e a porta avisa em vez de aplicar calada.

    O savepoint (`conn.transaction()`) e obrigatorio pelo mesmo motivo de la: sem ele a colisao de
    chave aborta a transacao INTEIRA do webhook, e o grupo perde a mensagem seguinte por causa de
    uma correcao redundante.
    """
    row: Any = None
    try:
        async with conn.transaction():
            cur = await conn.execute(
                f"""
                UPDATE barravips.razao_lancamentos_manuais
                   SET valor = %s, data = %s, chave_conteudo = %s
                 WHERE id = %s AND anulado_em IS NULL
                RETURNING {_CAMPOS_DO_LANCAMENTO_MANUAL}
                """,
                (valor, data, chave_conteudo, lancamento_id),
            )
            row = await cur.fetchone()
    except UniqueViolation:
        return None
    return None if row is None else _lancamento_manual(row)


async def anular_lancamentos_manuais_da_mensagem(
    conn: AsyncConnection[Any], mensagem_id: UUID
) -> list[LancamentoManual]:
    """A mensagem que declarou o vale foi apagada: ele sai do razao e solta a chave de conteudo.

    So o que nasceu no GRUPO tem `mensagem_id`, entao o lancamento do painel nunca e alcancado
    por uma delecao — apagar a fala no WhatsApp nao pode desfazer o que o gestor lancou na tela.
    """
    cur = await conn.execute(
        f"""
        UPDATE barravips.razao_lancamentos_manuais
           SET anulado_em = now()
         WHERE mensagem_id = %s AND anulado_em IS NULL
        RETURNING {_CAMPOS_DO_LANCAMENTO_MANUAL}
        """,
        (mensagem_id,),
    )
    return [_lancamento_manual(row) for row in await cur.fetchall()]


def _temporada(row: Any) -> Temporada:
    dados = _como_dict(row, _COLUNAS_DA_TEMPORADA)
    return Temporada(
        id=dados["id"],
        modelo_id=dados["modelo_id"],
        cidade=dados["cidade"],
        data_inicio=dados["data_inicio"],
        data_fim=dados["data_fim"],
        estado=cast(EstadoDaTemporada, dados["estado"]),
        observacao=dados["observacao"],
        fechada_em=dados["fechada_em"],
    )


def _pagamento_da_temporada(row: Any) -> PagamentoDaTemporada:
    dados = _como_dict(row, _COLUNAS_DO_PAGAMENTO)
    return PagamentoDaTemporada(
        id=dados["id"],
        modelo_id=dados["modelo_id"],
        valor=dados["valor"],
        data_pagamento=dados["data_pagamento"],
        temporada_id=dados["temporada_id"],
        forma_pagamento=dados["forma_pagamento"],
        observacao=dados["observacao"],
    )


def _venda_para_o_razao(row: Any) -> VendaParaORazao:
    dados = _como_dict(row, _COLUNAS_DA_VENDA_DO_RAZAO)
    return VendaParaORazao(
        id=dados["id"],
        modelo_id=dados["modelo_id"],
        valor=dados["valor"],
        data=dados["data"],
        bolso=cast(Bolso, dados["bolso"]),
        percentual_repasse_snapshot=dados["percentual_repasse_snapshot"],
        recebido_por_modelo_id=dados["recebido_por_modelo_id"],
        cliente_nome=dados["cliente_nome"],
    )


def _transferencia_para_o_razao(row: Any) -> TransferenciaParaORazao:
    dados = _como_dict(row, _COLUNAS_DA_TRANSFERENCIA)
    return TransferenciaParaORazao(
        id=dados["id"],
        valor=dados["valor"],
        data=dados["data"],
        classificacao=cast(Classificacao, dados["classificacao"]),
    )


def _deslocamento_para_o_razao(row: Any) -> DeslocamentoParaORazao:
    dados = _como_dict(row, _COLUNAS_DO_DESLOCAMENTO)
    return DeslocamentoParaORazao(
        id=dados["id"],
        venda_id=dados["venda_id"],
        modelo_id=dados["modelo_id"],
        data=dados["data"],
        valor_antecipado=dados["valor_antecipado"],
        valor_transporte=dados["valor_transporte"],
        recebedor_do_antecipado=cast(ParteDoDeslocamento, dados["recebedor_do_antecipado"]),
        pagador_do_transporte=cast(ParteDoDeslocamento, dados["pagador_do_transporte"]),
    )


def _lancamento_manual(row: Any) -> LancamentoManual:
    dados = _como_dict(row, _COLUNAS_DO_LANCAMENTO_MANUAL)
    return LancamentoManual(
        id=dados["id"],
        modelo_id=dados["modelo_id"],
        tipo=cast(TipoDeLancamentoManual, dados["tipo"]),
        sentido=cast(SentidoDoLancamento, dados["sentido"]),
        valor=dados["valor"],
        data=dados["data"],
        origem=cast(OrigemDoLancamento, dados["origem"]),
        descricao=dados["descricao"],
        mensagem_id=dados["mensagem_id"],
        temporada_id=dados["temporada_id"],
    )


# --- ficha de agendamento (ticket 06) -----------------------------------------------------------
#
# **A modelo NUNCA e coluna da ficha** (ADR-0046 §1): ela vive em `ficha_participantes`, sempre —
# a ficha individual e o caso N=1. Por isso toda leitura por modelo aqui passa por um JOIN, e nao
# por um `WHERE modelo_id = %s` que nao existe. E esse mesmo JOIN que faz o escopo do alvo ser por
# MODELO e nao por grupo (ADR-0046 §2): a lista da Yasmin e a lista das fichas DELA, tenha o card
# caido no grupo dela ou no Grupo de fichas.

_COLUNAS_DA_FICHA = (
    "id",
    "estado",
    "mensagem_id",
    "chave_conteudo",
    "vendedor_id",
    "cliente_nome",
    "cliente_whatsapp",
    "nome_anuncio",
    "site",
    "origem",
    "data",
    "hora",
    "duracao_minutos",
    "tipo_atendimento",
    "tipo_local",
    "endereco",
    "endereco_complemento",
    "valor_total",
    "valor_transporte",
    "valor_antecipado",
    "forma_antecipado",
    "forma_pagamento",
    "observacoes",
)

_CAMPOS_DA_FICHA = """id, estado, mensagem_id, chave_conteudo, vendedor_id, cliente_nome,
                      cliente_whatsapp, nome_anuncio, site, origem, data, hora, duracao_minutos,
                      tipo_atendimento, tipo_local, endereco, endereco_complemento, valor_total,
                      valor_transporte, valor_antecipado, forma_antecipado, forma_pagamento,
                      observacoes"""

_CAMPOS_DA_FICHA_F = """f.id, f.estado, f.mensagem_id, f.chave_conteudo, f.vendedor_id,
                        f.cliente_nome, f.cliente_whatsapp, f.nome_anuncio, f.site, f.origem,
                        f.data, f.hora, f.duracao_minutos, f.tipo_atendimento, f.tipo_local,
                        f.endereco, f.endereco_complemento, f.valor_total, f.valor_transporte,
                        f.valor_antecipado, f.forma_antecipado, f.forma_pagamento, f.observacoes"""


async def registrar_ficha(
    conn: AsyncConnection[Any],
    *,
    lida: FichaLida,
    participantes: Sequence[ParticipanteDaFicha],
    mensagem_id: UUID,
    chave_conteudo: str,
    vendedor_id: UUID | None = None,
) -> FichaDeAgendamento | None:
    """Grava a Ficha de agendamento e as participantes. `None` = ja existia (repost / outro grupo).

    O `ON CONFLICT (chave_conteudo) WHERE estado <> 'cancelada'` e o MESMO desenho da Venda
    registrada e da Cobranca: o indice parcial e a unica barreira que uma entrega concorrente nao
    atravessa, e a ficha CANCELADA solta a chave para o repost poder substituir o que morreu.

    E ele que resolve, de graca, o card postado no grupo de cada participante (ADR-0044 §1): tres
    mensagens, o mesmo fato combinado, UMA ficha com tres participantes — e nao tres fichas
    cobrando tres vezes o mesmo atendimento.

    A ficha nasce `aberta` por default do banco; nenhum estado e passado aqui de proposito, para
    que a maquina do ADR-0044 §1 tenha uma origem so.
    """
    cur = await conn.execute(
        f"""
        INSERT INTO barravips.fichas_de_agendamento
            (mensagem_id, chave_conteudo, vendedor_id, cliente_nome, cliente_whatsapp,
             nome_anuncio, site, origem, data, hora, duracao_minutos, tipo_atendimento, tipo_local,
             endereco, endereco_complemento, valor_total, valor_transporte, valor_antecipado,
             forma_antecipado, forma_pagamento, observacoes)
        VALUES (%s, %s, %s, %s, %s,
                %s, %s, %s::barravips.origem_anuncio_enum, %s, %s, %s,
                %s::barravips.tipo_atendimento_enum, %s::barravips.ficha_tipo_local_enum,
                %s, %s, %s, %s, %s,
                %s, %s, %s)
        ON CONFLICT (chave_conteudo) WHERE estado <> 'cancelada' DO NOTHING
        RETURNING {_CAMPOS_DA_FICHA}
        """,
        (
            mensagem_id,
            chave_conteudo,
            vendedor_id,
            lida.cliente_nome,
            lida.cliente_whatsapp,
            lida.nome_anuncio,
            lida.site,
            lida.origem,
            lida.data,
            lida.hora,
            lida.duracao_minutos,
            lida.tipo_atendimento,
            lida.tipo_local,
            lida.endereco,
            lida.endereco_complemento,
            lida.valor_total,
            lida.valor_transporte,
            lida.valor_antecipado,
            lida.forma_antecipado,
            lida.forma_pagamento,
            lida.observacoes,
        ),
    )
    row = await cur.fetchone()
    if row is None:
        return None
    ficha = _ficha(row)
    gravadas = await _gravar_participantes(conn, ficha.id, participantes)
    return replace(ficha, participantes=gravadas)


async def _gravar_participantes(
    conn: AsyncConnection[Any], ficha_id: UUID, participantes: Sequence[ParticipanteDaFicha]
) -> tuple[ParticipanteDaFicha, ...]:
    """As modelos da ficha, uma linha cada. `ON CONFLICT DO NOTHING` pela UNIQUE (ficha, modelo).

    A colisao aqui nao e caso de erro: o card que nomeia a mesma mulher duas vezes (o nome real
    numa linha e o do perfil noutra) e degradacao normal do dia de pico, e o plano ja a descarta
    — isto e a segunda tranca, para que uma corrida nao aborte a transacao inteira do webhook por
    causa de um nome repetido.
    """
    gravadas: list[ParticipanteDaFicha] = []
    for participante in participantes:
        await conn.execute(
            """
            INSERT INTO barravips.ficha_participantes (ficha_id, modelo_id, valor, ordem)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (ficha_id, modelo_id) DO NOTHING
            """,
            (ficha_id, participante.modelo_id, participante.valor, participante.ordem),
        )
        gravadas.append(participante)
    return tuple(gravadas)


async def ficha_por_chave_de_conteudo(
    conn: AsyncConnection[Any], chave_conteudo: str
) -> FichaDeAgendamento | None:
    """A ficha VIVA que ja representa este combinado — quem venceu o dedup do repost."""
    cur = await conn.execute(
        f"""
        SELECT {_CAMPOS_DA_FICHA}
          FROM barravips.fichas_de_agendamento
         WHERE chave_conteudo = %s
           AND estado <> 'cancelada'
         LIMIT 1
        """,
        (chave_conteudo,),
    )
    row = await cur.fetchone()
    if row is None:
        return None
    ficha = _ficha(row)
    return replace(ficha, participantes=await participantes_da_ficha(conn, ficha.id))


async def fichas_abertas_da_modelo(
    conn: AsyncConnection[Any], modelo_id: UUID
) -> list[FichaDeAgendamento]:
    """As fichas em aberto DESTA modelo, na ordem do dia — a lista numerada do closed-world.

    Escopo por MODELO e nunca por grupo (ADR-0046 §2). O card pode ter caido num Grupo de fichas
    que nao tem dona, e a modelo paga no grupo dela: filtrar por grupo perderia o alvo justamente
    no arranjo que a reunião de 20/08 quer testar.

    `ORDER BY data, hora, id` e o contrato do indice por que a LLM aponta: ela devolve o INDICE da
    lista, nunca um id, e uma ordem instavel faria o indice 2 de agora ser outro atendimento
    daqui a um minuto (a licao do `ORDER BY id` que sorteava "a mais recente"). Nulos por ultimo
    porque a ficha sem data (a que nasceu de um comunicado) e a menos identificada de todas.

    Nao lista ficha de mais ninguem, por construcao: o filtro esta no JOIN.
    """
    cur = await conn.execute(
        f"""
        SELECT {_CAMPOS_DA_FICHA_F}
          FROM barravips.fichas_de_agendamento f
          JOIN barravips.ficha_participantes p ON p.ficha_id = f.id
         WHERE p.modelo_id = %s
           AND f.estado IN ('aberta', 'confirmada')
         ORDER BY f.data NULLS LAST, f.hora NULLS LAST, f.id
        """,
        (modelo_id,),
    )
    fichas = [_ficha(row) for row in await cur.fetchall()]
    return [
        replace(ficha, participantes=await participantes_da_ficha(conn, ficha.id))
        for ficha in fichas
    ]


async def participantes_da_ficha(
    conn: AsyncConnection[Any], ficha_id: UUID
) -> tuple[ParticipanteDaFicha, ...]:
    """As modelos da ficha, na ordem do card, com o nome verdadeiro para o painel e a fala."""
    cur = await conn.execute(
        """
        SELECT p.modelo_id, p.valor, p.ordem, m.nome
          FROM barravips.ficha_participantes p
          JOIN barravips.modelos m ON m.id = p.modelo_id
         WHERE p.ficha_id = %s
         ORDER BY p.ordem, p.modelo_id
        """,
        (ficha_id,),
    )
    return tuple(
        ParticipanteDaFicha(
            modelo_id=dados["modelo_id"],
            valor=dados["valor"],
            ordem=dados["ordem"],
            nome=dados["nome"],
        )
        for dados in (
            _como_dict(row, ("modelo_id", "valor", "ordem", "nome")) for row in await cur.fetchall()
        )
    )


def _ficha(row: Any) -> FichaDeAgendamento:
    dados = _como_dict(row, _COLUNAS_DA_FICHA)
    return FichaDeAgendamento(
        id=dados["id"],
        estado=dados["estado"],
        mensagem_id=dados["mensagem_id"],
        chave_conteudo=dados["chave_conteudo"],
        vendedor_id=dados["vendedor_id"],
        cliente_nome=dados["cliente_nome"],
        cliente_whatsapp=dados["cliente_whatsapp"],
        nome_anuncio=dados["nome_anuncio"],
        site=dados["site"],
        origem=dados["origem"],
        data=dados["data"],
        hora=dados["hora"],
        duracao_minutos=dados["duracao_minutos"],
        tipo_atendimento=dados["tipo_atendimento"],
        tipo_local=dados["tipo_local"],
        endereco=dados["endereco"],
        endereco_complemento=dados["endereco_complemento"],
        valor_total=dados["valor_total"],
        valor_transporte=dados["valor_transporte"],
        valor_antecipado=dados["valor_antecipado"],
        forma_antecipado=dados["forma_antecipado"],
        forma_pagamento=dados["forma_pagamento"],
        observacoes=dados["observacoes"],
    )


# --- promocao da ficha a Venda registrada (ticket 07) -------------------------------------------
#
# A Venda registrada nasce no PAGAMENTO (ADR-0044 §2). Escrita propria, e nao um parametro novo em
# `registrar_venda`: a venda que nasce de uma ficha ja chega com a forma, o bolso, o snapshot do
# repasse, o telefonista e a origem do anuncio — oito colunas que o anuncio de texto livre nao tem
# e nunca vai ter (nem o backfill historico, que roda pela mesma porta). Alargar o INSERT de todo
# mundo para caber um caminho so faria os 88 chamadores de hoje passarem a depender das colunas da
# onda 20260820.
#
# A idempotencia entre as DUAS portas do mesmo fato (a fala da modelo e o ✅ do telefonista,
# ADR-0046 §5) e a mesma `chave_conteudo` de sempre: o segundo gesto colide no indice parcial e
# nao grava. Nao ha "quem chegou primeiro" em codigo — ha um indice unico, que e a unica barreira
# que uma corrida nao atravessa.


async def registrar_venda_da_ficha(
    conn: AsyncConnection[Any],
    *,
    promocao: PromocaoDaFicha,
    mensagem_id: UUID,
    chave_conteudo: str,
    percentual_repasse_snapshot: Decimal | None = None,
    recebido_por_modelo_id: UUID | None = None,
) -> VendaRegistrada | None:
    """Grava a Venda registrada que nasceu da ficha. `None` = ja existia (a outra porta chegou antes).

    `mensagem_id` e a mensagem do GESTO que promoveu (a fala da modelo, o ✅ do telefonista) — e
    nao a do card: e nela que a venda esta ancorada para a correcao por quote e para a anulacao
    por delecao (ticket 05), e apagar o card nao pode apagar o dinheiro que ja entrou. Quem guarda
    o card e `ficha_id`.

    `pagamento_mensagem_id` e `bolso_mensagem_id` recebem essa MESMA mensagem quando ela disse a
    forma / decidiu o bolso: as tres colunas apontam para o mesmo gesto porque foi um gesto so, e
    e assim que a auditoria mostra em que evidencia o agente se apoiou.

    O `percentual_repasse_snapshot` e copiado de `modelos.percentual_repasse` (ADR-0045 §3) e pode
    ser NULO: modelo sem percentual cadastrado nao ganha 50% chutado no codigo — o razao trata
    snapshot nulo como comissao ZERO, e o numero errado no extrato e mais barato que o numero
    inventado no bolso de alguem.

    `recebido_por_modelo_id` e a festinha em que uma recebeu por todas (ticket 13). Ele NAO sai da
    `PromocaoDaFicha`: a promocao e sempre de UMA modelo (o rateio ja esta em `ficha_participantes`)
    e quem recebeu por todas e fato da venda, dito por quem o disser — as N promocoes da mesma
    festinha recebem o mesmo valor aqui, e o razao le `COALESCE(recebido_por_modelo_id, modelo_id)`.
    """
    cur = await conn.execute(
        f"""
        INSERT INTO barravips.vendas_registradas
            (modelo_id, valor, data, cliente_nome, local_atendimento, duracao_minutos,
             mensagem_id, chave_conteudo, forma_pagamento, pagamento_mensagem_id,
             ficha_id, bolso, bolso_mensagem_id, origem, site, vendedor_id,
             percentual_repasse_snapshot, recebido_por_modelo_id)
        VALUES (%s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s::barravips.bolso_da_venda_enum, %s, %s::barravips.origem_anuncio_enum, %s,
                %s, %s, %s)
        ON CONFLICT (chave_conteudo) WHERE anulada_em IS NULL DO NOTHING
        RETURNING {_CAMPOS_DA_VENDA}
        """,
        (
            promocao.modelo_id,
            promocao.valor,
            promocao.data,
            promocao.cliente_nome,
            promocao.local_atendimento,
            promocao.duracao_minutos,
            mensagem_id,
            chave_conteudo,
            promocao.forma_pagamento,
            mensagem_id if promocao.forma_pagamento is not None else None,
            promocao.ficha_id,
            promocao.bolso,
            mensagem_id if promocao.bolso != "nao_dito" else None,
            promocao.origem,
            promocao.site,
            promocao.vendedor_id,
            percentual_repasse_snapshot,
            recebido_por_modelo_id,
        ),
    )
    row = await cur.fetchone()
    return None if row is None else _venda(row)


async def percentual_de_repasse(conn: AsyncConnection[Any], modelo_id: UUID) -> Decimal | None:
    """O percentual de repasse do cadastro da modelo, para congelar na venda (ADR-0045 §3).

    Lido no ATO da promocao e gravado como snapshot: mudar a confianca numa modelo depois nao pode
    reescrever temporada passada em silencio. `None` = nao ha percentual cadastrado, e o razao
    conta comissao zero — nunca 50% por default de codigo (50% e default de CADASTRO).
    """
    cur = await conn.execute(
        "SELECT percentual_repasse FROM barravips.modelos WHERE id = %s",
        (modelo_id,),
    )
    row = await cur.fetchone()
    if row is None:
        return None
    valor = _como_dict(row, ("percentual_repasse",))["percentual_repasse"]
    return None if valor is None else Decimal(valor)


async def marcar_ficha_realizada(
    conn: AsyncConnection[Any], ficha_id: UUID
) -> FichaDeAgendamento | None:
    """A ficha cumpriu seu desfecho: virou dinheiro. `None` = ja nao estava aberta.

    `WHERE estado IN ('aberta','confirmada')` e a tranca de idempotencia do lado da ficha, gemea
    do indice unico do lado da venda: a segunda porta (ADR-0046 §5) encontra a ficha ja
    `realizada` e nao gera evento nenhum. Ficha `cancelada` nao volta a viver por um pagamento —
    dinheiro chegando depois do ❌ e conversa (ticket 20), nao UPDATE calado.
    """
    cur = await conn.execute(
        f"""
        UPDATE barravips.fichas_de_agendamento
           SET estado = 'realizada'
         WHERE id = %s AND estado IN ('aberta', 'confirmada')
        RETURNING {_CAMPOS_DA_FICHA}
        """,
        (ficha_id,),
    )
    row = await cur.fetchone()
    if row is None:
        return None
    ficha = _ficha(row)
    return replace(ficha, participantes=await participantes_da_ficha(conn, ficha.id))


async def registrar_evento_da_ficha(
    conn: AsyncConnection[Any],
    ficha_id: UUID,
    *,
    tipo: TipoDeEventoDaFicha,
    campo: str | None = None,
    valor_anterior: str | None = None,
    valor_novo: str | None = None,
    mensagem_id: UUID | None = None,
) -> None:
    """Uma linha no rastro APPEND-ONLY da ficha (`authenticated` so tem SELECT e INSERT).

    E o unico lugar onde se ve que a ficha JA foi outra coisa: ela guarda so o estado de agora.
    Sem valor de negocio na hora, e por isso nao devolve nada — quem promove nao muda de conduta
    por causa do evento, e um retorno ignorado convidaria alguem a decidir com base nele.
    """
    await conn.execute(
        """
        INSERT INTO barravips.ficha_de_agendamento_eventos
            (ficha_id, tipo, campo, valor_anterior, valor_novo, mensagem_id)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (ficha_id, tipo, campo, valor_anterior, valor_novo, mensagem_id),
    )


async def venda_da_ficha(
    conn: AsyncConnection[Any], ficha_id: UUID, modelo_id: UUID
) -> VendaRegistrada | None:
    """A venda VIVA que esta ficha ja produziu para esta modelo. `None` = ainda nao virou dinheiro.

    Escopada pela modelo porque a festinha promove uma venda por participante a partir da MESMA
    ficha: sem o filtro, a fala de uma delas encontraria a venda da outra e o agente diria que
    ja estava registrado o que ainda nao esta.
    """
    cur = await conn.execute(
        f"""
        SELECT {_CAMPOS_DA_VENDA}
          FROM barravips.vendas_registradas
         WHERE ficha_id = %s
           AND modelo_id = %s
           AND anulada_em IS NULL
         ORDER BY created_at
         LIMIT 1
        """,
        (ficha_id, modelo_id),
    )
    row = await cur.fetchone()
    return None if row is None else _venda(row)


async def ficha_aberta_da_mensagem_citada(
    conn: AsyncConnection[Any], grupo_id: UUID, evolution_message_id: str
) -> UUID | None:
    """A ficha ABERTA ancorada na mensagem que a modelo citou (quote) — o sinal mais forte de todos.

    O quote resolve dentro do grupo em que a mensagem foi citada, e e por isso que o `grupo_id`
    filtra a MENSAGEM e nao a ficha: a ficha pode ter nascido no Grupo de fichas (ADR-0046 §2), e
    o que a modelo cita no grupo dela e o comunicado. Enquanto o comunicado apenas VINCULA a ficha
    do outro grupo sem virar mensagem-fonte dela, esse salto e o ticket 19 — aqui o quote so acha
    a ficha cuja mensagem-fonte esta no proprio grupo, que e o arranjo de hoje.
    """
    cur = await conn.execute(
        """
        SELECT f.id
          FROM barravips.fichas_de_agendamento f
          JOIN barravips.grupo_financeiro_mensagens m ON m.id = f.mensagem_id
         WHERE m.grupo_id = %s
           AND m.evolution_message_id = %s
           AND f.estado IN ('aberta', 'confirmada')
         LIMIT 1
        """,
        (grupo_id, evolution_message_id),
    )
    row = await cur.fetchone()
    if row is None:
        return None
    return cast(UUID, _como_dict(row, ("id",))["id"])


async def texto_da_mensagem_citada(
    conn: AsyncConnection[Any], grupo_id: UUID, evolution_message_id: str
) -> str | None:
    """O que estava escrito na mensagem que o autor citou. `None` = nao esta no log de origem.

    Existe para UM salto (ticket 19): a modelo cita **o Comunicado** ao pagar, e a ficha que ele
    resume nasceu no Grupo de fichas, ancorada em OUTRA mensagem, de outro grupo. Nenhuma coluna
    liga as duas — o vinculo do comunicado com a ficha e derivado (`modelo + cliente + valor`,
    `casar_comunicado`), e derivar de novo a partir do texto citado devolve o mesmo alvo pela
    mesma regra, em vez de inventar um segundo caminho que pode divergir do primeiro.

    Le a mensagem DESTE grupo, sempre: o quote acontece dentro de um grupo, e cruzar o `grupo_id`
    aqui e o que impede um `evolution_message_id` repetido entre instancias trazer o texto de um
    grupo alheio. A `caption` conta como texto — o comunicado postado como legenda de foto e o
    mesmo documento.
    """
    cur = await conn.execute(
        """
        SELECT COALESCE(NULLIF(texto, ''), caption) AS texto
          FROM barravips.grupo_financeiro_mensagens
         WHERE grupo_id = %s
           AND evolution_message_id = %s
         LIMIT 1
        """,
        (grupo_id, evolution_message_id),
    )
    row = await cur.fetchone()
    if row is None:
        return None
    return cast("str | None", _como_dict(row, ("texto",))["texto"])


# --- caixa dos telefonistas: a segunda fonte, so leitura (ticket 17) -----------------------------
#
# O caixa e o grupo onde o gestor confere o dia com todas as modelos juntas, e a IA entra la **em
# leitura** (spec 0006, Out of Scope). As duas consultas abaixo sao o que a conferencia le, e
# nenhuma delas escreve: o que o caixa diz nao vira linha em `vendas_registradas` em lugar nenhum
# do modulo — contar a mesma venda duas vezes e o risco que o ticket nomeia, e ele se evita nao
# tendo caminho de escrita, nunca somando com cuidado.


async def mensagens_do_caixa(
    conn: AsyncConnection[Any], *, de: date, ate: date
) -> list[MensagemRegistrada]:
    """O que passou pelos grupos de papel `caixa_telefonistas` na janela, em ordem de chegada.

    A janela e por **dia BRT** (`recebida_em AT TIME ZONE 'America/Sao_Paulo'`) e nao por UTC: o
    caixa e escrito de madrugada como todo o resto deste modulo, e datar pelo UTC jogaria a
    conferencia das 22h para o dia seguinte — o mesmo motivo de `dia_brt` existir em `modelos.py`.

    Sem `grupo_id` no parametro de proposito: quem confere pergunta "o que o caixa disse", nao "o
    que aquele grupo disse". Se um dia houver mais de um caixa cadastrado (a casa pode separar por
    turno), a conferencia continua sendo uma so — e o filtro que importa e o `papel`, nunca o JID.

    `tem_venda` sai **sempre falso**, e por construcao: nenhuma Venda registrada aponta para uma
    mensagem do caixa, porque a porta unica devolve `grupo_em_leitura` antes de qualquer escrita.
    Calcula-lo com um EXISTS seria pagar por uma resposta que o roteamento ja garante.

    Mensagem APAGADA fica de fora pelo mesmo motivo do contexto do grupo (`mensagens_recentes`):
    ela sumiu da tela de quem confere, e conferir contra uma linha que ninguem mais ve produziria
    uma divergencia que nao existe.
    """
    cur = await conn.execute(
        """
        SELECT m.id,
               coalesce(nullif(m.texto, ''), m.caption, '') AS texto,
               m.de_mim,
               m.recebida_em,
               m.evolution_message_id,
               false AS tem_venda
          FROM barravips.grupo_financeiro_mensagens m
          JOIN barravips.grupos_financeiros g ON g.id = m.grupo_id
         WHERE g.papel = 'caixa_telefonistas'
           AND g.ativo
           AND m.apagada_em IS NULL
           AND (m.recebida_em AT TIME ZONE 'America/Sao_Paulo')::date >= %s
           AND (m.recebida_em AT TIME ZONE 'America/Sao_Paulo')::date <= %s
         ORDER BY m.recebida_em, m.id
        """,
        (de, ate),
    )
    colunas = ("id", "texto", "de_mim", "recebida_em", "evolution_message_id", "tem_venda")
    return [
        MensagemRegistrada(
            id=dados["id"],
            texto=dados["texto"] or "",
            de_mim=bool(dados["de_mim"]),
            recebida_em=dados["recebida_em"],
            evolution_message_id=dados["evolution_message_id"],
            tem_venda=False,
        )
        for dados in (_como_dict(row, colunas) for row in await cur.fetchall())
    ]


async def vendas_vivas_no_periodo(
    conn: AsyncConnection[Any], *, de: date, ate: date
) -> list[VendaRegistrada]:
    """Todas as Vendas registradas vivas com data na janela, de todas as modelos.

    O outro lado da conferencia do caixa. Escopo de CASA (sem `modelo_id`) porque o caixa e da
    casa: o gestor confere o dia inteiro de uma vez, e a modelo de cada linha sai da propria
    venda.

    Recorte por `data` (o dia do atendimento) e nao por `created_at`: e a data que o caixa conta,
    e casar pelo instante da insercao faria a venda anunciada com atraso divergir sozinha.
    """
    cur = await conn.execute(
        f"""
        SELECT {_CAMPOS_DA_VENDA}
          FROM barravips.vendas_registradas
         WHERE data >= %s
           AND data <= %s
           AND anulada_em IS NULL
         ORDER BY data, id
        """,
        (de, ate),
    )
    return [_venda(row) for row in await cur.fetchall()]


# --- comissao do telefonista (ticket 22, ADR-0048) ------------------------------------------------
#
# Duas leituras, e as duas existem para NAO chutar.
#
# `telefonista_por_jid` responde "quem vendeu isto?" pelo AUTOR da mensagem (ADR-0048 §5): a ficha
# e postada por uma pessoa, e `vendedores.whatsapp_jid` e o unico vinculo. Closed-world: autor que
# o cadastro nao conhece -> venda sem vendedor -> sem comissao, exatamente como o ADR-0012 ja trata
# o atendimento conduzido pela IA. **Nunca por `autor_nome`** — o nome de exibicao do WhatsApp e
# escolhido por quem fala, muda sozinho e se repete; casar por ele seria pagar comissao por palpite.
#
# `comissao_dos_telefonistas` e a PROJECAO (§6): nao ha snapshot por venda, entao o numero sai da
# multiplicacao na hora da leitura e muda quando o cadastro muda. A formula e a do Modulo Financeiro
# (`financeiro/calculos.comissao_sql`) e nao uma copia local — e a mesma conta da outra fonte do §4
# (`atendimentos` Fechado), e duas copias divergiriam no dia em que a base mudasse de novo. Este
# import cruza contexto de proposito: `calculos.py` e a single source of truth das formulas do
# modulo financeiro, como `dashboard/routes.py` ja faz com `VALOR_SERVICO_SQL`.
#
# ⚠️ Esta e SO a metade `vendas_registradas` do faturamento do telefonista. A outra metade —
# `atendimentos WHERE estado='Fechado'` — continua em `financeiro/repo.py::comissao_por_vendedor`.
# As duas SOMAM sem dupla contagem porque as fontes sao disjuntas por construcao (o grupo nunca
# fabrica Atendimento; ADR-0043 e `receita_registrada` acima); o dia em que a IA de venda entrar em
# producao exige decisao de precedencia, nao um DISTINCT esperto aqui.
#
# ⚠️ **Deslocamento nao entra na base** (ADR-0048 §3, ADR-0045 §5): repare que nao ha juncao com
# `deslocamentos_da_venda` abaixo, e e assim que tem que continuar. O antecipado do Uber e reembolso
# de custo, mora em tabela propria e nunca esteve em `vendas_registradas.valor` — somar as duas
# tabelas para dar um "valor total" e o unico jeito conhecido de inflar esta conta.

_DEVICE_NO_JID = re.compile(r":\d+(@|$)")
"""O sufixo de aparelho que o WhatsApp as vezes cola no JID (`...:12@s.whatsapp.net`).

Duas contas do MESMO telefonista chegam com sufixos diferentes conforme o aparelho de onde ele
mandou. Sem tirar isso, o cadastro certo simplesmente para de casar um dia, e o sintoma e o pior
possivel: telefonista cadastrado que fica sem comissao e ninguem descobre ate o fim do mes.
"""


def chave_do_jid(bruto: str | None) -> str | None:
    """O JID normalizado para comparar autor x cadastro. `None` = nao da para comparar.

    Faz o MINIMO que o SQL abaixo tambem faz nos dois lados: `btrim`, `lower` e o sufixo de
    aparelho fora. Nada mais — nao extrai digitos, nao adivinha dominio, nao converte `@lid` em
    telefone. O `@lid` e identificador opaco e continua casando **literalmente**: se o gestor
    cadastrou o `@lid` do telefonista, e por ele que se acha; se cadastrou o telefone, so casa
    quem chegar pelo telefone. Traduzir um no outro seria o palpite que este ticket proibe.
    """
    if not bruto:
        return None
    limpo = _DEVICE_NO_JID.sub(r"\1", bruto.strip().lower())
    return limpo or None


@dataclass(frozen=True)
class TelefonistaDoJid:
    """Quem e o vendedor por tras deste autor, com o numero que projeta a comissao dele.

    `ativo` vem junto mas **nao filtra**: desativar o telefonista o tira dos seletores do painel,
    nao reescreve a autoria de quem postou a ficha. Quem vendeu, vendeu — e a comissao dele
    continua projetada, como o `financeiro_comissoes_pagas` (ON DELETE RESTRICT) ja pressupoe.
    """

    id: UUID
    nome: str
    percentual_comissao: Decimal
    ativo: bool


@dataclass(frozen=True)
class ComissaoDoTelefonista:
    """A projecao de um telefonista num periodo: o que ele vendeu e o que ele leva.

    `faturamento_bruto` e a soma de `vendas_registradas.valor` — bruto, taxa de cartao DENTRO
    (ADR-0048 §2), deslocamento FORA (§3). `comissao` ja vem arredondada em centavos pelo Postgres,
    uma vez so, sobre a soma: arredondar venda a venda e somar da outro centavo.
    """

    vendedor_id: UUID
    vendedor_nome: str
    percentual_comissao: Decimal
    vendas: int
    faturamento_bruto: Decimal
    comissao: Decimal


async def telefonista_por_jid(
    conn: AsyncConnection[Any], jid: str | None
) -> TelefonistaDoJid | None:
    """O vendedor cadastrado com este JID. `None` = nao ha um so, e entao nao ha vendedor.

    `None` cobre os tres casos em que atribuir seria chute: autor ausente (mensagem sem
    `autor_jid`), autor que o cadastro nao conhece, e — a borda que o indice unico nao pega — dois
    cadastros cujos JIDs normalizam para a mesma chave. A unicidade do banco e sobre o texto CRU
    (`vendedores_whatsapp_jid_uniq`), entao `5511...@s.whatsapp.net` e `5511...:2@s.whatsapp.net`
    convivem la e virariam empate aqui. Empate nao se desempata por `LIMIT 1`: o resultado seria
    estavel-ate-nao-ser e a comissao mudaria de dono sem ninguem mexer em nada.

    A normalizacao e a mesma dos dois lados (`chave_do_jid` aqui, `btrim/lower/regexp_replace` no
    SQL) — divergir e o bug classico deste projeto, em que o cadastro esta certo e o casamento
    falha calado.
    """
    chave = chave_do_jid(jid)
    if chave is None:
        return None
    cur = await conn.execute(
        r"""
        SELECT v.id, v.nome, v.percentual_comissao, v.ativo
          FROM barravips.vendedores v
         WHERE v.whatsapp_jid IS NOT NULL
           AND regexp_replace(lower(btrim(v.whatsapp_jid)), ':[0-9]+(@|$)', '\1') = %s
         LIMIT 2
        """,
        (chave,),
    )
    linhas = [
        _como_dict(row, ("id", "nome", "percentual_comissao", "ativo"))
        for row in await cur.fetchall()
    ]
    if len(linhas) != 1:
        if linhas:
            _logger.warning(
                "grupo_financeiro_jid_de_telefonista_ambiguo",
                extra={"quantos": len(linhas)},
            )
        return None
    dados = linhas[0]
    return TelefonistaDoJid(
        id=cast(UUID, dados["id"]),
        nome=str(dados["nome"]),
        percentual_comissao=Decimal(dados["percentual_comissao"]),
        ativo=bool(dados["ativo"]),
    )


async def comissao_dos_telefonistas(
    conn: AsyncConnection[Any],
    *,
    de: date,
    ate: date,
    vendedor_ids: Sequence[UUID] | None = None,
) -> list[ComissaoDoTelefonista]:
    """Quanto cada telefonista vendeu e leva no periodo, pelas Vendas registradas (ADR-0048).

    O recorte e a **data da venda** (o dia do atendimento, como o grupo conta) e nao o `created_at`
    — igual a `receita_registrada`: o anuncio de ontem postado hoje e faturamento de ontem, e o de
    quem o vendeu.

    `anulada_em IS NULL`, como toda leitura de venda deste modulo: venda anulada e rastro, e
    comissionar rastro paga duas vezes a venda que o telefonista corrigiu.

    O JOIN (nao LEFT) em `vendedores` e o `sem vendedor -> sem comissao` do §5 virado consulta:
    venda com `vendedor_id` nulo — a modelo anunciando no grupo dela, a IA conduzindo — nao aparece
    em linha nenhuma, em vez de aparecer numa linha "sem dono" que alguem acabaria pagando.

    O percentual sai de `vendedores.percentual_comissao` e **nao** de `financeiro_comissao_niveis`
    (§1): a tabela de niveis vive como default de cadastro e nao e consultada aqui. Como nao ha
    snapshot (§6), mudar o cadastro reprojeta tambem os meses passados — quem precisar congelar um
    fechamento resolve isso no relatorio, nunca inventando coluna de snapshot na venda.
    """
    filtro = ""
    params: list[Any] = [de, ate]
    if vendedor_ids:
        filtro = "AND v.vendedor_id = ANY(%s)"
        params.append(list(vendedor_ids))
    cur = await conn.execute(
        f"""
        SELECT ven.id AS vendedor_id,
               ven.nome AS vendedor_nome,
               ven.percentual_comissao,
               COUNT(*)::int AS vendas,
               COALESCE(SUM(v.valor), 0)::numeric AS faturamento_bruto,
               round(COALESCE(SUM({comissao_sql("v.valor", "ven.percentual_comissao")}), 0), 2)
                 ::numeric AS comissao
          FROM barravips.vendas_registradas v
          JOIN barravips.vendedores ven ON ven.id = v.vendedor_id
         WHERE v.anulada_em IS NULL
           AND v.data >= %s AND v.data <= %s
           {filtro}
         GROUP BY ven.id, ven.nome, ven.percentual_comissao
         ORDER BY comissao DESC, ven.nome
        """,
        params,
    )
    colunas = (
        "vendedor_id",
        "vendedor_nome",
        "percentual_comissao",
        "vendas",
        "faturamento_bruto",
        "comissao",
    )
    return [
        ComissaoDoTelefonista(
            vendedor_id=cast(UUID, dados["vendedor_id"]),
            vendedor_nome=str(dados["vendedor_nome"]),
            percentual_comissao=Decimal(dados["percentual_comissao"]),
            vendas=int(dados["vendas"]),
            faturamento_bruto=Decimal(dados["faturamento_bruto"]),
            comissao=Decimal(dados["comissao"]),
        )
        for dados in (_como_dict(row, colunas) for row in await cur.fetchall())
    ]


# --- o registro tipado de chaves Pix (ADR-0049 §2, ticket 02) -----------------------------------
#
# `chaves_pix_conhecidas` deixou de ser a lista plana da casa e virou o registro unico de "de quem
# e esta chave". A funcao antiga `chaves_pix_conhecidas() -> list[str]` MORREU no ticket 03: nao
# ha mais um caminho de producao que so precise do booleano — `registro_de_chaves` +
# `comprovante.papel_da_chave` servem os dois (grupo financeiro e Pix de deslocamento).
#
# ⚠️ A normalizacao e SEMPRE `comprovante.normalizar_chave` — a mesma que o OCR compara. Cadastrar
# "+55 71 99984 0879" e o comprovante trazer "+5571999840879" tem que ser a MESMA chave, senao o
# cadastro nao explica nada e o gestor cadastra a mesma chave tres vezes.

# `PapelCadastrado` (os quatro papeis gravaveis de `barravips.papel_da_chave_enum`) mora em
# `comprovante.py`, junto com a quinta resposta que NAO e gravavel — `desconhecida` e a ausencia
# de linha. Uma definicao so: quem le o papel e quem o grava tem que concordar sobre a lista.


@dataclass(frozen=True)
class ChavePixCadastrada:
    """Uma chave do registro, com o dono ja resolvido em nome legivel.

    `modelo_nome` / `vendedor_nome` vem por LEFT JOIN e existem para a tela: a lista de chaves e
    lida por quem nao sabe UUID de cor. Sao `None` sempre que o papel nao pede dono.

    `padrao` e no maximo uma linha no banco inteiro, e ela e sempre `papel='casa'` e `ativo`
    (CHECK `chaves_pix_conhecidas_padrao_e_da_casa_viva`).
    """

    id: UUID
    chave: str
    chave_normalizada: str
    papel: PapelCadastrado
    modelo_id: UUID | None
    modelo_nome: str | None
    vendedor_id: UUID | None
    vendedor_nome: str | None
    titular: str | None
    descricao: str | None
    padrao: bool
    ativo: bool
    created_at: datetime


_COLUNAS_DA_CHAVE = (
    "id",
    "chave",
    "chave_normalizada",
    "papel",
    "modelo_id",
    "modelo_nome",
    "vendedor_id",
    "vendedor_nome",
    "titular",
    "descricao",
    "padrao",
    "ativo",
    "created_at",
)

_SELECT_DA_CHAVE = """
    SELECT c.id, c.chave, c.chave_normalizada, c.papel::text AS papel,
           c.modelo_id, m.nome AS modelo_nome,
           c.vendedor_id, ven.nome AS vendedor_nome,
           c.titular, c.descricao, c.padrao, c.ativo, c.created_at
      FROM barravips.chaves_pix_conhecidas c
      LEFT JOIN barravips.modelos m ON m.id = c.modelo_id
      LEFT JOIN barravips.vendedores ven ON ven.id = c.vendedor_id
"""


def _chave_cadastrada(dados: dict[str, Any]) -> ChavePixCadastrada:
    return ChavePixCadastrada(
        id=cast(UUID, dados["id"]),
        chave=str(dados["chave"]),
        chave_normalizada=str(dados["chave_normalizada"]),
        papel=cast(PapelCadastrado, str(dados["papel"])),
        modelo_id=dados["modelo_id"],
        modelo_nome=dados["modelo_nome"],
        vendedor_id=dados["vendedor_id"],
        vendedor_nome=dados["vendedor_nome"],
        titular=dados["titular"],
        descricao=dados["descricao"],
        padrao=bool(dados["padrao"]),
        ativo=bool(dados["ativo"]),
        created_at=cast(datetime, dados["created_at"]),
    )


async def listar_chaves_pix(
    conn: AsyncConnection[Any], *, incluir_inativas: bool = False
) -> list[ChavePixCadastrada]:
    """O registro inteiro, ordenado como a tela le: a padrao primeiro, depois casa, modelo,
    telefonista, terceiro; ativas antes das inativas.

    `incluir_inativas=False` e o default porque a pergunta do dia e "para onde o dinheiro vai
    hoje". Quem RESOLVE PAPEL (ticket 03) precisa do oposto — a chave inativa continua sendo da
    modelo tal e continua explicando comprovante antigo — e por isso passa `True`.

    Sem cache, pelo mesmo motivo de `chaves_pix_conhecidas`: chave cadastrada agora tem que valer
    no proximo comprovante. Sao poucas linhas — a casa tem uma mao de chaves, nao um catalogo.
    """
    filtro = "" if incluir_inativas else "WHERE c.ativo"
    cur = await conn.execute(
        f"""
        {_SELECT_DA_CHAVE}
        {filtro}
         ORDER BY c.padrao DESC,
                  CASE c.papel
                    WHEN 'casa' THEN 0 WHEN 'modelo' THEN 1
                    WHEN 'telefonista' THEN 2 ELSE 3
                  END,
                  c.ativo DESC,
                  COALESCE(m.nome, ven.nome, c.titular, c.chave),
                  c.created_at
        """
    )
    return [
        _chave_cadastrada(dados)
        for dados in (_como_dict(row, _COLUNAS_DA_CHAVE) for row in await cur.fetchall())
    ]


async def registro_de_chaves(conn: AsyncConnection[Any]) -> tuple[ChaveComDono, ...]:
    """O cadastro inteiro no formato que `comprovante.papel_da_chave` consome (ticket 03).

    E o unico adaptador entre o banco e a pergunta "de quem e esta chave": o grupo financeiro e o
    Pix de deslocamento leem daqui, e por isso passaram a concordar. Antes eram duas fontes —
    `chaves_pix_conhecidas() -> list[str]` (lista plana da casa) e `modelos.chave_pix` — e duas
    comparacoes.

    **Traz as INATIVAS.** Inativar nunca deletar: a chave desligada continua tendo dono e continua
    explicando o comprovante de tres semanas atras. Quem pergunta "este destino esta autorizado
    HOJE?" filtra por `ChaveComDono.ativo` — a autorizacao e do chamador, a autoria e daqui.

    `dono_nome` cai para `titular` quando o papel nao tem dono (casa, terceiro): e o unico nome que
    existe para essas linhas, e e o que o painel mostra.
    """
    return tuple(
        ChaveComDono(
            chave=c.chave,
            papel=c.papel,
            dono_id=c.modelo_id or c.vendedor_id,
            dono_nome=c.modelo_nome or c.vendedor_nome or c.titular,
            titular=c.titular,
            ativo=c.ativo,
        )
        for c in await listar_chaves_pix(conn, incluir_inativas=True)
    )


# `chave_destino` e guardada como o OCR leu; a comparacao e sempre sobre a forma normalizada. O
# padrao vem de `comprovante.RUIDO_DA_CHAVE` e viaja como PARAMETRO da query — reescrever a classe
# de caracteres aqui criaria uma segunda normalizacao de chave Pix, que e exatamente a duplicacao
# que o ticket 03 acabou de encerrar entre o dominio e `workers/pix.py`.
_DESTINO_NORMALIZADO = "lower(regexp_replace(c.chave_destino, %s, '', 'g'))"


async def vezes_que_o_destino_apareceu(
    conn: AsyncConnection[Any],
    chave: str | None,
    *,
    exceto: UUID | None = None,
) -> int:
    """Quantos comprovantes ja foram para ESTE destino — a pergunta que decide se o ⚠️ ainda e novo.

    Conta o registro INTEIRO, de todos os grupos, porque a chave e a mesma coisa em todos eles: o
    aviso repetido e o que treina o gestor a ignorar o alarme, e ele nao para de ser repetido so
    porque a segunda foto veio no grupo de outra modelo. Quem quer a leitura por modelo tem a fila
    de sugestoes, que carrega `quem_mandou`.

    `exceto` existe porque quem pergunta ja gravou o comprovante deste turno — sem ele, toda chave
    voltaria `vezes >= 1` e o alarme nunca sairia nem na primeira vez.

    Comprovante anulado (correcao no grupo) nao conta: se a linha foi desfeita, o destino dela nao
    aconteceu.
    """
    alvo = normalizar_chave(chave) if chave else ""
    if not alvo:
        # Destino que o OCR nao leu nao tem contagem — nao ha o que casar, e "" casaria com toda
        # chave que a normalizacao tambem zerou.
        return 0
    cur = await conn.execute(
        f"""
        SELECT count(*) AS vezes
          FROM barravips.comprovantes_do_grupo c
         WHERE c.anulado_em IS NULL
           AND c.chave_destino IS NOT NULL
           AND {_DESTINO_NORMALIZADO} = %s
           AND (%s::uuid IS NULL OR c.id <> %s::uuid)
        """,
        (RUIDO_DA_CHAVE, alvo, exceto, exceto),
    )
    row = await cur.fetchone()
    return 0 if row is None else int(_como_dict(row, ("vezes",))["vezes"])


async def destinos_vistos_em_comprovantes(
    conn: AsyncConnection[Any], *, desde: date | None = None
) -> tuple[ChaveVista, ...]:
    """Cada destino que ja apareceu em comprovante, agregado — a materia-prima da fila do painel.

    Devolve TUDO, inclusive as chaves ja cadastradas: quem sabe o que e "sugestao" e
    `comprovante.sugestoes_de_cadastro`, que compara com o registro pela mesma `papel_da_chave`
    que o grupo usa. Filtrar aqui exigiria uma terceira comparacao de chave dentro do SQL.

    Nao existe tabela de sugestoes, e e de proposito (ADR-0049 §5): a fila e uma CONSULTA sobre
    `comprovantes_do_grupo`, entao cadastrar a chave e o proprio gesto que tira a linha da fila —
    sem invalidacao, sem estado que envelhece, sem "sugestao fantasma" de chave ja classificada.

    `desde` recorta a janela de observacao. Sem ele, uma chave aposentada ha um ano continuaria
    pedindo classificacao para sempre.
    """
    cur = await conn.execute(
        f"""
        SELECT {_DESTINO_NORMALIZADO} AS normalizada,
               (array_agg(c.chave_destino ORDER BY c.created_at DESC))[1] AS chave,
               count(*) AS vezes,
               min(c.created_at)::date AS primeiro_em,
               max(c.created_at)::date AS ultimo_em,
               COALESCE(sum(c.valor), 0) AS valor_total,
               array_remove(array_agg(DISTINCT c.titular_destino), NULL) AS titulares,
               jsonb_agg(DISTINCT jsonb_build_object(
                   'id', g.modelo_id::text, 'nome', m.nome)) AS quem_mandou
          FROM barravips.comprovantes_do_grupo c
          JOIN barravips.grupos_financeiros g ON g.id = c.grupo_id
          JOIN barravips.modelos m ON m.id = g.modelo_id
         WHERE c.anulado_em IS NULL
           AND c.chave_destino IS NOT NULL
           AND {_DESTINO_NORMALIZADO} <> ''
           AND (%s::date IS NULL OR c.created_at >= %s::date)
         GROUP BY 1
         ORDER BY count(*) DESC, max(c.created_at) DESC
        """,
        (RUIDO_DA_CHAVE, RUIDO_DA_CHAVE, desde, desde),
    )
    colunas = (
        "normalizada",
        "chave",
        "vezes",
        "primeiro_em",
        "ultimo_em",
        "valor_total",
        "titulares",
        "quem_mandou",
    )
    return tuple(
        ChaveVista(
            chave=str(dados["chave"]),
            vezes=int(dados["vezes"]),
            primeiro_em=cast(date, dados["primeiro_em"]),
            ultimo_em=cast(date, dados["ultimo_em"]),
            valor_total=Decimal(dados["valor_total"]),
            titulares=tuple(str(t) for t in (dados["titulares"] or ())),
            quem_mandou=tuple(
                QuemMandou(modelo_id=UUID(q["id"]), nome=str(q["nome"]))
                for q in (dados["quem_mandou"] or ())
            ),
        )
        for dados in (_como_dict(row, colunas) for row in await cur.fetchall())
    )


async def obter_chave_pix(conn: AsyncConnection[Any], chave_id: UUID) -> ChavePixCadastrada | None:
    cur = await conn.execute(f"{_SELECT_DA_CHAVE} WHERE c.id = %s", (chave_id,))
    row = await cur.fetchone()
    if row is None:
        return None
    return _chave_cadastrada(_como_dict(row, _COLUNAS_DA_CHAVE))


async def chave_pix_padrao_da_casa(conn: AsyncConnection[Any]) -> ChavePixCadastrada | None:
    """A UMA chave padrao da casa, ou `None` enquanto ninguem escolheu.

    `None` e estado legitimo e nao trava nada: as outras chaves da casa recebem tao legitimamente
    quanto a padrao (ADR-0049 §2). Quem quiser um destino para SUGERIR ao cliente usa esta; quem
    quiser saber se um destino e legitimo usa o papel, nunca a padrao.
    """
    cur = await conn.execute(f"{_SELECT_DA_CHAVE} WHERE c.padrao")
    row = await cur.fetchone()
    if row is None:
        return None
    return _chave_cadastrada(_como_dict(row, _COLUNAS_DA_CHAVE))


async def criar_chave_pix(
    conn: AsyncConnection[Any],
    *,
    chave: str,
    papel: PapelCadastrado,
    modelo_id: UUID | None = None,
    vendedor_id: UUID | None = None,
    titular: str | None = None,
    descricao: str | None = None,
) -> UUID:
    """Cadastra a chave e devolve o id. Levanta `UniqueViolation` se a chave ja existe.

    A `chave_normalizada` e derivada aqui e nunca vem do chamador: e ela que carrega o UNIQUE, e
    deixar o formato na mao de quem chama e como a mesma chave entraria duas vezes com grafias
    diferentes.

    Nao marca padrao: `definir_chave_pix_padrao` e um gesto proprio, porque trocar a padrao mexe em
    DUAS linhas.
    """
    cur = await conn.execute(
        """
        INSERT INTO barravips.chaves_pix_conhecidas
            (chave, chave_normalizada, papel, modelo_id, vendedor_id, titular, descricao)
        VALUES (%s, %s, %s::barravips.papel_da_chave_enum, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            chave,
            normalizar_chave(chave),
            papel,
            modelo_id,
            vendedor_id,
            titular,
            descricao,
        ),
    )
    row = await cur.fetchone()
    assert row is not None
    return cast(UUID, _como_dict(row, ("id",))["id"])


_CAMPOS_EDITAVEIS_DA_CHAVE = frozenset(
    {"chave", "papel", "modelo_id", "vendedor_id", "titular", "descricao", "ativo"}
)


async def atualizar_chave_pix(
    conn: AsyncConnection[Any], chave_id: UUID, campos: dict[str, Any]
) -> bool:
    """UPDATE parcial. `False` = a chave nao existe. `campos` vazio nao toca no banco.

    ⚠️ `padrao` NAO entra aqui de proposito — ela e a unica coluna cuja escrita mexe em outra
    linha, e passa por `definir_chave_pix_padrao`. Trocar a padrao por UPDATE simples bate no
    indice unico parcial e vira um 500 sem explicacao.

    Trocar `chave` recalcula `chave_normalizada` junto: separar as duas deixaria o registro
    apontando para a grafia antiga na comparacao, que e o unico lugar onde ela importa.

    ⚠️ Inativar NAO limpa `padrao` aqui: o CHECK `chaves_pix_conhecidas_padrao_e_da_casa_viva`
    rejeitaria a linha. Quem inativa a padrao tem que limpar a padrao antes — o painel faz os dois
    na mesma transacao (`routes.patch_chave_pix`), e a ordem importa.
    """
    campos = {c: v for c, v in campos.items() if c in _CAMPOS_EDITAVEIS_DA_CHAVE}
    if not campos:
        return await obter_chave_pix(conn, chave_id) is not None

    sets: list[str] = []
    params: list[Any] = []
    for coluna, valor in campos.items():
        if coluna == "chave":
            sets.append("chave = %s")
            params.append(valor)
            sets.append("chave_normalizada = %s")
            params.append(normalizar_chave(str(valor)))
        elif coluna == "papel":
            sets.append("papel = %s::barravips.papel_da_chave_enum")
            params.append(valor)
        else:
            sets.append(f"{coluna} = %s")
            params.append(valor)
    params.append(chave_id)
    cur = await conn.execute(
        f"UPDATE barravips.chaves_pix_conhecidas SET {', '.join(sets)} WHERE id = %s",
        params,
    )
    return cur.rowcount > 0


async def definir_chave_pix_padrao(conn: AsyncConnection[Any], chave_id: UUID | None) -> bool:
    """Move a padrao da casa: limpa a antiga e marca a nova, na MESMA transacao.

    `chave_id=None` so limpa — e o gesto de "nenhuma padrao", que e estado legitimo.

    As duas escritas TEM que ser uma so operacao: o indice unico parcial
    `chaves_pix_conhecidas_padrao_uniq` admite exatamente uma linha com `padrao`, entao marcar a
    nova antes de limpar a antiga falha sempre. Devolve `False` se a chave nao existe — e nesse
    caso a padrao antiga fica onde estava, porque o UPDATE de limpeza roda depois da checagem.
    """
    if chave_id is not None and await obter_chave_pix(conn, chave_id) is None:
        return False
    await conn.execute("UPDATE barravips.chaves_pix_conhecidas SET padrao = false WHERE padrao")
    if chave_id is None:
        return True
    cur = await conn.execute(
        "UPDATE barravips.chaves_pix_conhecidas SET padrao = true WHERE id = %s",
        (chave_id,),
    )
    return cur.rowcount > 0


# --- de quem e esta maquininha? (ADR-0049 §6, ticket 06) ------------------------------------------
# O irmao do registro de chaves, e de proposito tao parecido: cartao nao tem chave Pix, mas o print
# da maquininha traz o NOME DO ESTABELECIMENTO — a mesma evidencia, noutro campo. Tudo o que muda
# entre os dois e a normalizacao (ver `comprovante.normalizar_estabelecimento`) e a tabela; a
# pergunta, o tipo de resposta (`PapelResolvido`) e o closed-world sao os mesmos.


def _estabelecimento_normalizado(nome: str | None) -> str | None:
    """A forma de comparacao gravada junto do que o OCR leu — `None` quando nao ha o que comparar.

    Nome que a normalizacao ZERA (so pontuacao, so simbolo) tambem vira `None`: "" casaria com toda
    linha que tambem tivesse zerado, e um destino vazio nao e um destino.
    """
    normalizado = normalizar_estabelecimento(nome) if nome else ""
    return normalizado or None


@dataclass(frozen=True)
class EstabelecimentoCadastrado:
    """Uma maquininha do registro, com o dono ja resolvido em nome legivel — irma de
    `ChavePixCadastrada`. `modelo_nome`/`vendedor_nome` vem por LEFT JOIN e existem para a tela."""

    id: UUID
    nome: str
    nome_normalizado: str
    papel: PapelCadastrado
    modelo_id: UUID | None
    modelo_nome: str | None
    vendedor_id: UUID | None
    vendedor_nome: str | None
    descricao: str | None
    ativo: bool
    created_at: datetime


_COLUNAS_DO_ESTABELECIMENTO = (
    "id",
    "nome",
    "nome_normalizado",
    "papel",
    "modelo_id",
    "modelo_nome",
    "vendedor_id",
    "vendedor_nome",
    "descricao",
    "ativo",
    "created_at",
)

_SELECT_DO_ESTABELECIMENTO = """
    SELECT e.id, e.nome, e.nome_normalizado, e.papel::text AS papel,
           e.modelo_id, m.nome AS modelo_nome,
           e.vendedor_id, ven.nome AS vendedor_nome,
           e.descricao, e.ativo, e.created_at
      FROM barravips.estabelecimentos_conhecidos e
      LEFT JOIN barravips.modelos m ON m.id = e.modelo_id
      LEFT JOIN barravips.vendedores ven ON ven.id = e.vendedor_id
"""


def _estabelecimento_cadastrado(dados: dict[str, Any]) -> EstabelecimentoCadastrado:
    return EstabelecimentoCadastrado(
        id=cast(UUID, dados["id"]),
        nome=str(dados["nome"]),
        nome_normalizado=str(dados["nome_normalizado"]),
        papel=cast(PapelCadastrado, str(dados["papel"])),
        modelo_id=dados["modelo_id"],
        modelo_nome=dados["modelo_nome"],
        vendedor_id=dados["vendedor_id"],
        vendedor_nome=dados["vendedor_nome"],
        descricao=dados["descricao"],
        ativo=bool(dados["ativo"]),
        created_at=cast(datetime, dados["created_at"]),
    )


async def listar_estabelecimentos(
    conn: AsyncConnection[Any], *, incluir_inativos: bool = False
) -> list[EstabelecimentoCadastrado]:
    """O registro de maquininhas, na ordem em que a tela le: casa, modelo, telefonista, terceiro.

    Mesmo par de defaults da chave e pelo mesmo motivo: a pergunta do dia e "de quem e a maquininha
    que esta rodando", e quem RESOLVE PAPEL precisa do oposto (`incluir_inativos=True`) porque a
    maquininha devolvida continua explicando o print antigo.
    """
    filtro = "" if incluir_inativos else "WHERE e.ativo"
    cur = await conn.execute(
        f"""
        {_SELECT_DO_ESTABELECIMENTO}
        {filtro}
         ORDER BY CASE e.papel
                    WHEN 'casa' THEN 0 WHEN 'modelo' THEN 1
                    WHEN 'telefonista' THEN 2 ELSE 3
                  END,
                  e.ativo DESC,
                  COALESCE(m.nome, ven.nome, e.nome),
                  e.created_at
        """
    )
    return [
        _estabelecimento_cadastrado(dados)
        for dados in (_como_dict(row, _COLUNAS_DO_ESTABELECIMENTO) for row in await cur.fetchall())
    ]


async def registro_de_estabelecimentos(
    conn: AsyncConnection[Any],
) -> tuple[EstabelecimentoComDono, ...]:
    """O cadastro inteiro no formato que `comprovante.papel_do_estabelecimento` consome.

    Irmao exato de `registro_de_chaves`, inclusive na decisao que mais custa: **traz as INATIVAS**.
    Autoria nao e autorizacao — quem quiser saber se a maquininha esta em uso hoje filtra por
    `EstabelecimentoComDono.ativo` do lado de fora.
    """
    return tuple(
        EstabelecimentoComDono(
            nome=e.nome,
            papel=e.papel,
            dono_id=e.modelo_id or e.vendedor_id,
            dono_nome=e.modelo_nome or e.vendedor_nome or e.nome,
            ativo=e.ativo,
        )
        for e in await listar_estabelecimentos(conn, incluir_inativos=True)
    )


async def criar_estabelecimento(
    conn: AsyncConnection[Any],
    *,
    nome: str,
    papel: PapelCadastrado,
    modelo_id: UUID | None = None,
    vendedor_id: UUID | None = None,
    descricao: str | None = None,
) -> UUID:
    """Cadastra a maquininha e devolve o id. Levanta `UniqueViolation` se ela ja existe.

    `nome_normalizado` e derivado aqui e nunca vem do chamador — e ele que carrega o UNIQUE, e e a
    mesma disciplina de `criar_chave_pix`: a grafia de comparacao e do repositorio, nunca de quem
    digita.

    Este e o gesto que a fila de sugestoes (ticket 05) termina: a pergunta *"esse PagBank apareceu
    4 vezes recebendo da Yasmin — de quem e?"* vira UMA linha aqui, e a sugestao some porque a fila
    e derivada, nao materializada.
    """
    cur = await conn.execute(
        """
        INSERT INTO barravips.estabelecimentos_conhecidos
            (nome, nome_normalizado, papel, modelo_id, vendedor_id, descricao)
        VALUES (%s, %s, %s::barravips.papel_da_chave_enum, %s, %s, %s)
        RETURNING id
        """,
        (nome, normalizar_estabelecimento(nome), papel, modelo_id, vendedor_id, descricao),
    )
    row = await cur.fetchone()
    assert row is not None
    return cast(UUID, _como_dict(row, ("id",))["id"])


async def estabelecimentos_vistos_em_comprovantes(
    conn: AsyncConnection[Any], *, desde: date | None = None
) -> tuple[ChaveVista, ...]:
    """Cada maquininha que ja apareceu em print, agregada — a fila do painel, a MESMA do ticket 05.

    Devolve `ChaveVista` (e nao um tipo proprio) porque para o gestor e uma pergunta so: "de quem e
    este destino?". Quem separa o que ainda nao tem dono e `comprovante.sugestoes_de_estabelecimento`,
    que compara com o registro pela mesma funcao que o grupo usa — filtrar aqui exigiria uma
    terceira comparacao de nome dentro do SQL.

    Agrupa por `estabelecimento_normalizado`, a coluna que o Python escreveu: e por isso que
    "PagBank" e "PAG BANK" contam como a MESMA maquininha sem `unaccent` no banco (ver a migration
    20260820131500). `titulares` fica vazio de proposito — comprovante de cartao nao tem titular de
    conta, e inventar um faria a fila mostrar nome de gente onde ha nome de loja.
    """
    cur = await conn.execute(
        """
        SELECT c.estabelecimento_normalizado AS normalizado,
               (array_agg(c.estabelecimento ORDER BY c.created_at DESC))[1] AS nome,
               count(*) AS vezes,
               min(c.created_at)::date AS primeiro_em,
               max(c.created_at)::date AS ultimo_em,
               COALESCE(sum(c.valor), 0) AS valor_total,
               jsonb_agg(DISTINCT jsonb_build_object(
                   'id', g.modelo_id::text, 'nome', m.nome)) AS quem_mandou
          FROM barravips.comprovantes_do_grupo c
          JOIN barravips.grupos_financeiros g ON g.id = c.grupo_id
          JOIN barravips.modelos m ON m.id = g.modelo_id
         WHERE c.anulado_em IS NULL
           AND c.estabelecimento_normalizado IS NOT NULL
           AND (%s::date IS NULL OR c.created_at >= %s::date)
         GROUP BY 1
         ORDER BY count(*) DESC, max(c.created_at) DESC
        """,
        (desde, desde),
    )
    colunas = (
        "normalizado",
        "nome",
        "vezes",
        "primeiro_em",
        "ultimo_em",
        "valor_total",
        "quem_mandou",
    )
    return tuple(
        ChaveVista(
            chave=str(dados["nome"]),
            vezes=int(dados["vezes"]),
            primeiro_em=cast(date, dados["primeiro_em"]),
            ultimo_em=cast(date, dados["ultimo_em"]),
            valor_total=Decimal(dados["valor_total"]),
            quem_mandou=tuple(
                QuemMandou(modelo_id=UUID(q["id"]), nome=str(q["nome"]))
                for q in (dados["quem_mandou"] or ())
            ),
        )
        for dados in (_como_dict(row, colunas) for row in await cur.fetchall())
    )
