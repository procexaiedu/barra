"""Pergunta minima e Pendencia de forma de pagamento (spec 0005, ticket 03) — pela PORTA UNICA.

Este arquivo testa o VAI-E-VEM do grupo, nao mensagens isoladas. E a diferenca que importa: as
duas condutas do ticket so existem no tempo — o "600" que completa um anuncio de dez minutos
atras, o "Sim" que responde uma pergunta feita cinco segundos antes, o "Dinheiro" que atinge uma
venda de quatro dias atras e nao a de hoje. Um teste que mandasse cada mensagem sozinha provaria
um agente sem memoria, que nao e o agente que a producao roda.

Por isso cada cenario aqui e uma CONVERSA: mensagens em sequencia, com relogio crescente, todas
entrando por `processar_mensagem_do_grupo` — a mesma porta do webhook. A grafia e a do export
"Modelo Yasmin Ruiva/financeiro" (13/08/2026), incluindo o espaco sobrando no fim da linha.

O que fica provado:

1. Anuncio sem o minimo gera UMA pergunta objetiva; a resposta curta completa o registro, com a
   venda datada do dia do ANUNCIO e ancorada na mensagem do anuncio.
2. A forma de pagamento dita depois atinge a venda CERTA — a citada no contexto ("O Lucas de
   ontem"), nao a ultima registrada.
3. Venda sem forma carrega Pendencia; venda em dinheiro sai marcada em especie e nao gera
   expectativa de comprovante.
4. Pendencia nao trava nada: com uma venda pendente, outras registram e conciliam normalmente.
5. As mensagens do grupo que contem "pix" e NAO sao resposta de pagamento (chave Pix ditada,
   "Pix erick", conferencia de fechamento) nao escrevem forma nenhuma.

`needs_db` com `TEST_DATABASE_URL` + ROLLBACK sempre: o contexto da conversa e derivado do log de
origem e a pendencia e uma coluna com FK — FakeConn provaria o mock, nao a conduta.
"""

import os
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from barra.agente_financeiro import ResultadoDaPorta, processar_mensagem_do_grupo
from barra.agente_financeiro.leitura import IntencaoDoGrupo, LerIntencao
from barra.dominio.grupo_financeiro.fechamento import TUDO_CONCILIADO
from barra.dominio.grupo_financeiro.modelos import MensagemDoGrupo
from barra.dominio.grupo_financeiro.pagamento import (
    PREFIXO_DO_DESEMPATE,
    montar_pergunta_de_desempate,
)
from barra.dominio.grupo_financeiro.pendencia import EM_ESPECIE_COM_A_MODELO, Pendencia
from barra.dominio.grupo_financeiro.pergunta import PREFIXO_DA_PERGUNTA
from barra.dominio.grupo_financeiro.repo import vendas_sem_forma_de_pagamento

pytestmark = pytest.mark.needs_db

# --- mensagens reais do export (grafia intacta) -------------------------------------------------

ANUNCIO_GABRIEL = "Atendimento no nosso local \nCliente Gabriel \nPerfil bianca/yasmin \n700 1h"
ANUNCIO_RAMON = "Atendimento no nosso local \nCliente ramon \nPerfil bianca \n600 1h"
ANUNCIO_RAMON_SEM_VALOR = "Atendimento no nosso local \nCliente ramon \nPerfil bianca"
ANUNCIO_LUCAS = "Atendimento no nosso local\nCliente Lucas \nBianca seu nome \n600 1h"

# "pix" que NAO e resposta de pagamento — todas do grupo real de 12 e 13/08.
PIX_QUE_NAO_E_RESPOSTA = (
    "Pix erick",
    "Pode enviar nesse pix",
    "Minha Chave Pix para transferência: +5571999840879",
    "Yasmin confere por favor \n\n600 pix \n600 pix",
    "Envia para o site e envia o comprovante por favor",
)


@pytest_asyncio.fixture
async def conn() -> AsyncIterator[AsyncConnection[dict[str, Any]]]:
    connection = await AsyncConnection.connect(
        os.environ["TEST_DATABASE_URL"],
        autocommit=False,
        row_factory=dict_row,
        prepare_threshold=None,
    )
    try:
        yield connection
    finally:
        try:
            await connection.rollback()
        finally:
            await connection.close()


# --- seeds --------------------------------------------------------------------------------------


async def _seed_modelo(c: AsyncConnection[dict[str, Any]], nome: str) -> UUID:
    modelo_id = uuid4()
    await c.execute(
        """
        INSERT INTO barravips.modelos
            (id, nome, idade, numero_whatsapp, valor_padrao, tipo_atendimento_aceito,
             percentual_repasse, status)
        VALUES (%s, %s, %s, %s, %s, %s::barravips.tipo_atendimento_enum[], %s,
                'ativa'::barravips.modelo_status_enum)
        """,
        (modelo_id, nome, 25, f"test-wpp-{uuid4().hex}", 700, ["interno"], Decimal("40")),
    )
    return modelo_id


async def _seed_apelido(c: AsyncConnection[dict[str, Any]], modelo_id: UUID, nome: str) -> None:
    await c.execute(
        """
        INSERT INTO barravips.modelo_nomes_anuncio (modelo_id, nome, nome_normalizado)
        VALUES (%s, %s, %s)
        """,
        (modelo_id, nome, nome.strip().lower()),
    )


class _Grupo:
    """O Grupo financeiro montado + o relogio da conversa.

    O relogio anda sozinho a cada mensagem (30 s) porque a ORDEM e o dado: e ela que diz qual
    pergunta o "Sim" esta respondendo. Mensagens carimbadas no mesmo instante deixariam a
    "mensagem imediatamente anterior" ao sabor do desempate do banco.
    """

    def __init__(self, modelo_id: UUID, grupo_id: UUID, jid: str, inicio: datetime) -> None:
        self.modelo_id = modelo_id
        self.grupo_id = grupo_id
        self.jid = jid
        self.relogio = inicio

    def avancar(self, delta: timedelta) -> None:
        self.relogio += delta


async def _montar_grupo(
    c: AsyncConnection[dict[str, Any]], *, inicio: datetime, apelido: str = "bianca"
) -> _Grupo:
    """Grupo da Yasmin: a modelo, o apelido de anuncio e o vinculo closed-world.

    Nome verdadeiro "Yasmin" cru de proposito: o `barra_test` tem varias "Yasmin" de residuo, e e
    o caso homonimo real do export — "yasmin" sozinho seria ambiguo e quem desempata e o "bianca"
    da mesma linha (intersecao dos candidatos), nunca um palpite.
    """
    modelo_id = await _seed_modelo(c, "Yasmin")
    await _seed_apelido(c, modelo_id, apelido)
    grupo_id = uuid4()
    jid = f"1203634{uuid4().hex[:12]}@g.us"
    await c.execute(
        """
        INSERT INTO barravips.grupos_financeiros (id, modelo_id, jid, nome)
        VALUES (%s, %s, %s, %s)
        """,
        (grupo_id, modelo_id, jid, "Modelo Yasmin Ruiva/financeiro"),
    )
    return _Grupo(modelo_id, grupo_id, jid, inicio)


# --- a conversa ----------------------------------------------------------------------------------


class _Falas:
    """O que o agente postou no grupo. Coleta em vez de ir a rede."""

    def __init__(self) -> None:
        self.enviadas: list[str] = []

    async def __call__(self, texto: str, *, citar: str | None = None) -> None:
        self.enviadas.append(texto)

    @property
    def ultima(self) -> str | None:
        return self.enviadas[-1] if self.enviadas else None


async def _dizer(
    c: AsyncConnection[dict[str, Any]],
    grupo: _Grupo,
    texto: str,
    *,
    falas: _Falas,
    depois: timedelta = timedelta(seconds=30),
    ler_intencao: LerIntencao | None = None,
    **kw: Any,
) -> ResultadoDaPorta:
    """Um humano fala no grupo; a porta processa. O relogio anda ANTES de cada fala."""
    grupo.avancar(depois)
    kw.setdefault("evolution_message_id", f"3EB0{uuid4().hex[:12]}")
    kw.setdefault("autor_nome", "Dani")
    kw.setdefault("autor_jid", "5521999999999@s.whatsapp.net")
    msg = MensagemDoGrupo(grupo_jid=grupo.jid, texto=texto, recebida_em=grupo.relogio, **kw)
    return await processar_mensagem_do_grupo(c, msg, enviar=falas, ler_intencao=ler_intencao)


async def _vendas(c: AsyncConnection[dict[str, Any]], modelo_id: UUID) -> list[dict[str, Any]]:
    cur = await c.execute(
        """
        SELECT id, valor, data, cliente_nome, duracao_minutos, forma_pagamento, mensagem_id,
               pagamento_mensagem_id, anulada_em
          FROM barravips.vendas_registradas
         WHERE modelo_id = %s
         ORDER BY data, id
        """,
        (modelo_id,),
    )
    return list(await cur.fetchall())


# 09/08 01:09 UTC = 08/08 22:09 em Brasilia: a venda e do dia 08, como a gestora conta.
NOITE_DE_08_08 = datetime(2026, 8, 9, 1, 9, tzinfo=UTC)


# --- 1. pergunta minima: falta o valor ----------------------------------------------------------


async def test_anuncio_sem_valor_pergunta_uma_vez_e_a_resposta_registra(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """O vai-e-vem inteiro: anuncio incompleto -> UMA pergunta -> "600 1h" -> venda + recibo."""
    grupo = await _montar_grupo(conn, inicio=NOITE_DE_08_08)
    falas = _Falas()

    pediu = await _dizer(conn, grupo, ANUNCIO_RAMON_SEM_VALOR, falas=falas)

    assert pediu.motivo == "sem_valor"
    assert pediu.vendas == ()
    assert await _vendas(conn, grupo.modelo_id) == []
    # UMA mensagem, objetiva, sobre o unico buraco — e nada de forma de pagamento (isso e
    # Pendencia, cobrada de manha, nunca no ato).
    assert falas.enviadas == [pediu.resposta]
    pergunta = falas.enviadas[0]
    assert pergunta.startswith(PREFIXO_DA_PERGUNTA)
    assert "ramon" in pergunta
    assert "quanto foi" in pergunta
    assert "pix" not in pergunta.lower()

    respondeu = await _dizer(conn, grupo, "600 1h", falas=falas, depois=timedelta(minutes=6))

    assert respondeu.motivo is None
    assert len(respondeu.vendas) == 1
    (venda,) = await _vendas(conn, grupo.modelo_id)
    assert venda["valor"] == Decimal("600.00")
    assert venda["duracao_minutos"] == 60
    assert venda["cliente_nome"] == "ramon"  # o resto do anuncio veio junto, sem repostar nada
    assert venda["data"] == date(2026, 8, 8)  # dia do ANUNCIO, nao o da resposta
    assert venda["mensagem_id"] == pediu.mensagem_id  # origem auditavel = onde o fato foi dito
    assert venda["forma_pagamento"] is None  # o registro nunca espera a forma
    assert falas.ultima is not None
    assert falas.ultima.startswith("✅ Registrei:")
    assert "R$ 600,00" in falas.ultima


async def test_anuncio_incompleto_reentregue_nao_pergunta_duas_vezes(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """O router do numero ProceX entrega a mesma mensagem 2x — o grupo nao pode ser perguntado 2x."""
    grupo = await _montar_grupo(conn, inicio=NOITE_DE_08_08)
    falas = _Falas()
    evo = f"3EB0{uuid4().hex[:12]}"

    await _dizer(conn, grupo, ANUNCIO_RAMON_SEM_VALOR, falas=falas, evolution_message_id=evo)
    repetido = await _dizer(
        conn, grupo, ANUNCIO_RAMON_SEM_VALOR, falas=falas, evolution_message_id=evo
    )

    assert repetido.status == "duplicada"
    assert len(falas.enviadas) == 1


async def test_valor_solto_sem_anuncio_esperando_nao_inventa_venda(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Numero solto no grupo so vira venda quando ha uma pergunta minima esperando resposta.

    Sem essa amarra, "600" dito no meio de qualquer conversa (ou "2706" de um apartamento) viraria
    dinheiro na conta de alguem.
    """
    grupo = await _montar_grupo(conn, inicio=NOITE_DE_08_08)
    falas = _Falas()

    solto = await _dizer(conn, grupo, "600", falas=falas)

    assert solto.motivo == "nao_e_anuncio"
    assert await _vendas(conn, grupo.modelo_id) == []
    assert falas.enviadas == []


async def test_resposta_nao_completa_anuncio_ja_registrado(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Anuncio completo + "600" depois = conversa, nao segunda venda."""
    grupo = await _montar_grupo(conn, inicio=NOITE_DE_08_08)
    falas = _Falas()

    await _dizer(conn, grupo, ANUNCIO_RAMON, falas=falas)
    depois = await _dizer(conn, grupo, "600", falas=falas)

    assert depois.vendas == ()
    assert len(await _vendas(conn, grupo.modelo_id)) == 1


# --- 2. pergunta minima: nao da para saber de quem e a venda ------------------------------------


async def test_nome_desconhecido_pergunta_quem_e_e_a_resposta_registra(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """ "Perfil fran loira" fora do cadastro: o agente pergunta e registra na modelo que a
    resposta nomear — closed-world ate no destravamento (o cadastro e quem responde, nao o
    parecido)."""
    grupo = await _montar_grupo(conn, inicio=NOITE_DE_08_08)
    duda = f"Duda{uuid4().hex[:6]}"
    duda_id = await _seed_modelo(conn, duda)
    falas = _Falas()

    pediu = await _dizer(
        conn,
        grupo,
        "Atendimento no nosso local \nCliente Tiago \nPerfil fran loira \n600 1h",
        falas=falas,
    )

    assert pediu.motivo == "nome_desconhecido"
    assert pediu.vendas == ()
    assert falas.enviadas == [pediu.resposta]
    assert "fran loira" in falas.enviadas[0]
    assert "é quem?" in falas.enviadas[0]

    respondeu = await _dizer(conn, grupo, f"é a {duda}", falas=falas, depois=timedelta(minutes=2))

    assert len(respondeu.vendas) == 1
    assert respondeu.modelo_id == duda_id
    (venda,) = await _vendas(conn, duda_id)
    assert venda["valor"] == Decimal("600.00")
    assert venda["cliente_nome"] == "Tiago"
    assert await _vendas(conn, grupo.modelo_id) == []  # nao caiu na dona do grupo


async def test_resposta_com_nome_fora_do_cadastro_nao_registra(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Ensinar apelido NOVO pela resposta e o ticket 04; ate la, nome que o cadastro nao conhece
    continua nao virando venda por palpite."""
    grupo = await _montar_grupo(conn, inicio=NOITE_DE_08_08)
    falas = _Falas()

    await _dizer(
        conn,
        grupo,
        "Atendimento no nosso local \nCliente Tiago \nPerfil fran loira \n600 1h",
        falas=falas,
    )
    respondeu = await _dizer(conn, grupo, "é a fran loira mesmo", falas=falas)

    assert respondeu.vendas == ()
    assert await _vendas(conn, grupo.modelo_id) == []


# --- 3. forma de pagamento: a venda certa, nao a ultima -----------------------------------------


async def test_pagamento_dito_dias_depois_atinge_a_venda_citada_e_nao_a_ultima(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """O caso do ticket, na gramatica do grupo: cita-se o cliente e DEPOIS se pergunta a forma.

    Sem ler a citacao, "Dinheiro" cairia na venda mais recente so por ser a mais recente — e a
    venda de quatro dias atras ficaria pendente para sempre, invisivel no fechamento.
    """
    grupo = await _montar_grupo(conn, inicio=NOITE_DE_08_08)
    falas = _Falas()

    antiga = await _dizer(conn, grupo, ANUNCIO_GABRIEL, falas=falas)
    recente = await _dizer(conn, grupo, ANUNCIO_RAMON, falas=falas, depois=timedelta(days=4))
    assert (len(antiga.vendas), len(recente.vendas)) == (1, 1)

    await _dizer(conn, grupo, "O Gabriel de sexta", falas=falas, depois=timedelta(hours=11))
    await _dizer(conn, grupo, "Foi pix ou din ?", falas=falas, depois=timedelta(seconds=5))
    pago = await _dizer(conn, grupo, "Dinheiro", falas=falas, depois=timedelta(minutes=6))

    assert pago.motivo == "pagamento_absorvido"
    assert pago.pagamentos == antiga.vendas

    por_cliente = {v["cliente_nome"]: v for v in await _vendas(conn, grupo.modelo_id)}
    assert por_cliente["Gabriel"]["forma_pagamento"] == "dinheiro"
    assert por_cliente["Gabriel"]["pagamento_mensagem_id"] == pago.mensagem_id  # auditoria
    assert por_cliente["ramon"]["forma_pagamento"] is None  # a venda recente continua pendente


async def test_sim_responde_a_pergunta_imediatamente_anterior(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """A sequencia literal de 12/08: anuncio -> "O Lucas de ontem" -> "Foi pix também amiga ?" ->
    "Sim". O "Sim" nao carrega forma nenhuma: ele HERDA a da pergunta que acabou de ser feita."""
    grupo = await _montar_grupo(conn, inicio=NOITE_DE_08_08)
    falas = _Falas()

    ramon = await _dizer(conn, grupo, ANUNCIO_RAMON, falas=falas)
    lucas = await _dizer(conn, grupo, ANUNCIO_LUCAS, falas=falas, depois=timedelta(hours=11))
    await _dizer(conn, grupo, "O Lucas de ontem", falas=falas, depois=timedelta(seconds=12))
    await _dizer(conn, grupo, "Foi pix também amiga ?", falas=falas, depois=timedelta(seconds=5))
    pago = await _dizer(conn, grupo, "Sim", falas=falas, depois=timedelta(minutes=1))

    assert pago.pagamentos == lucas.vendas
    por_cliente = {v["cliente_nome"]: v for v in await _vendas(conn, grupo.modelo_id)}
    assert por_cliente["Lucas"]["forma_pagamento"] == "pix"
    assert por_cliente["ramon"]["forma_pagamento"] is None
    assert ramon.vendas != lucas.vendas


async def test_sim_fora_de_pergunta_de_pagamento_nao_marca_nada(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """12/08 19:06 "Ficou com você" -> 19:09 "Sim". O grupo diz "Sim" o dia inteiro para coisa
    nenhuma a ver com forma de pagamento."""
    grupo = await _montar_grupo(conn, inicio=NOITE_DE_08_08)
    falas = _Falas()

    await _dizer(conn, grupo, ANUNCIO_RAMON, falas=falas)
    await _dizer(conn, grupo, "Ficou com você", falas=falas, depois=timedelta(hours=6))
    sim = await _dizer(conn, grupo, "Sim", falas=falas, depois=timedelta(minutes=3))

    assert sim.pagamentos == ()
    (venda,) = await _vendas(conn, grupo.modelo_id)
    assert venda["forma_pagamento"] is None


async def test_forma_ambigua_nao_e_chutada_e_vira_pergunta(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Duas vendas pendentes antigas e um "Pix" solto, sem nada no contexto que desempate.

    Nada e escrito — marcar a venda errada e o unico erro que nao volta, ela some da cobranca e
    do fechamento e ninguem descobre. Mas calar tambem cobra: a forma FOI dita, e quem disse acha
    que resolveu. A conduta e a terceira — devolver a pergunta que uma palavra responde.
    """
    grupo = await _montar_grupo(conn, inicio=NOITE_DE_08_08)
    falas = _Falas()

    await _dizer(conn, grupo, ANUNCIO_GABRIEL, falas=falas)
    await _dizer(conn, grupo, ANUNCIO_RAMON, falas=falas, depois=timedelta(days=1))
    solto = await _dizer(conn, grupo, "Pix", falas=falas, depois=timedelta(days=4))

    assert solto.motivo == "pagamento_ambiguo"
    assert solto.pagamentos == ()
    assert [v["forma_pagamento"] for v in await _vendas(conn, grupo.modelo_id)] == [None, None]

    assert falas.ultima == solto.resposta
    pergunta = falas.enviadas[-1]
    assert pergunta.startswith(PREFIXO_DO_DESEMPATE)
    assert "pix" in pergunta  # a forma dita volta na pergunta, nao e reperguntada
    # Nomeia as candidatas, com valor, para a resposta poder ser um nome so.
    assert "Gabriel" in pergunta and "ramon" in pergunta
    assert "R$ 700,00" in pergunta and "R$ 600,00" in pergunta


async def test_a_resposta_a_pergunta_de_desempate_fecha_a_venda_nomeada(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """A pergunta so vale se a resposta dela couber na allowlist — senao o loop nao fecha."""
    grupo = await _montar_grupo(conn, inicio=NOITE_DE_08_08)
    falas = _Falas()

    await _dizer(conn, grupo, ANUNCIO_GABRIEL, falas=falas)
    await _dizer(conn, grupo, ANUNCIO_RAMON, falas=falas, depois=timedelta(days=1))
    await _dizer(conn, grupo, "Pix", falas=falas, depois=timedelta(days=4))

    fechou = await _dizer(conn, grupo, "o do Gabriel foi pix", falas=falas)

    assert fechou.motivo == "pagamento_absorvido"
    formas = {v["cliente_nome"]: v["forma_pagamento"] for v in await _vendas(conn, grupo.modelo_id)}
    assert formas == {"Gabriel": "pix", "ramon": None}


async def test_desempate_nao_e_reperguntado_a_cada_pix_solto(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Quem responde "Pix" sem nomear repete "Pix" sem nomear. Uma pergunta por janela e o teto.

    A tranca le o log do grupo, como o resto do modulo: a fala do agente volta pelo webhook como
    `de_mim` — e por isso que a reentrega dela entra aqui pela mesma porta.
    """
    grupo = await _montar_grupo(conn, inicio=NOITE_DE_08_08)
    falas = _Falas()

    await _dizer(conn, grupo, ANUNCIO_GABRIEL, falas=falas)
    await _dizer(conn, grupo, ANUNCIO_RAMON, falas=falas, depois=timedelta(days=1))
    primeira = await _dizer(conn, grupo, "Pix", falas=falas, depois=timedelta(days=4))
    assert primeira.resposta is not None

    # a pergunta do agente volta pelo webhook e fica no log do grupo
    eco = await _dizer(conn, grupo, primeira.resposta, falas=falas, de_mim=True)
    assert eco.motivo == "eco_do_agente"

    de_novo = await _dizer(conn, grupo, "Pix", falas=falas)

    assert de_novo.motivo == "pagamento_sem_venda_certa"
    assert de_novo.resposta is None
    assert falas.enviadas.count(primeira.resposta) == 1  # nao repetiu a pergunta


async def test_pix_solto_sem_venda_aberta_segue_em_silencio(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Sem candidata nao ha pergunta possivel — perguntar "em qual?" sobre nada e so ruido."""
    grupo = await _montar_grupo(conn, inicio=NOITE_DE_08_08)
    falas = _Falas()

    solto = await _dizer(conn, grupo, "Pix", falas=falas)

    assert solto.motivo == "pagamento_sem_venda_certa"
    assert solto.resposta is None
    assert falas.enviadas == []


async def test_pergunta_de_pagamento_do_gestor_nao_gera_resposta(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """O agente nao responde "foi pix ou din?" por ninguem — a cobranca dele e outra (ticket 10)."""
    grupo = await _montar_grupo(conn, inicio=NOITE_DE_08_08)
    falas = _Falas()

    await _dizer(conn, grupo, ANUNCIO_RAMON, falas=falas)
    perguntou = await _dizer(conn, grupo, "Foi pix ou din ?", falas=falas)

    assert perguntou.motivo == "pergunta_de_pagamento"
    assert len(falas.enviadas) == 1  # so o recibo do anuncio


@pytest.mark.parametrize("texto", PIX_QUE_NAO_E_RESPOSTA)
async def test_pix_que_nao_e_resposta_nao_escreve_forma(
    conn: AsyncConnection[dict[str, Any]], texto: str
) -> None:
    """Chave Pix ditada, "Pix erick", conferencia de fechamento: contem "pix" e nao dizem como a
    venda foi paga. Absorver qualquer uma delas encerraria a pendencia com a forma errada."""
    grupo = await _montar_grupo(conn, inicio=NOITE_DE_08_08)
    falas = _Falas()

    await _dizer(conn, grupo, ANUNCIO_RAMON, falas=falas)
    ruido = await _dizer(conn, grupo, texto, falas=falas)

    assert ruido.pagamentos == ()
    (venda,) = await _vendas(conn, grupo.modelo_id)
    assert venda["forma_pagamento"] is None


@pytest.mark.parametrize("texto", ["esse foi pix", "essa foi dinheiro", "esse foi dinheiro"])
async def test_demonstrativo_aponta_a_venda_recem_anunciada(
    conn: AsyncConnection[dict[str, Any]], texto: str
) -> None:
    """ "Esse foi pix" logo depois do anuncio e resposta de pagamento, nao conversa.

    Sem o demonstrativo na allowlist a fala inteira era descartada: a modelo respondia, o agente
    nao dizia nada e a venda seguia pendente ate a cobranca da manha — o loop que a rotina existe
    para fechar.
    """
    grupo = await _montar_grupo(conn, inicio=NOITE_DE_08_08)
    falas = _Falas()

    await _dizer(conn, grupo, ANUNCIO_RAMON, falas=falas)
    respondeu = await _dizer(conn, grupo, texto, falas=falas, depois=timedelta(minutes=2))

    assert respondeu.motivo == "pagamento_absorvido"
    (venda,) = await _vendas(conn, grupo.modelo_id)
    assert venda["forma_pagamento"] == ("pix" if "pix" in texto else "dinheiro")


# --- 4. Pendencia: visivel, em especie, e sem travar nada ---------------------------------------


async def test_venda_nasce_com_pendencia_de_forma_de_pagamento(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    grupo = await _montar_grupo(conn, inicio=NOITE_DE_08_08)
    falas = _Falas()

    registrou = await _dizer(conn, grupo, ANUNCIO_GABRIEL, falas=falas)

    (venda_id,) = registrou.vendas
    assert registrou.pendencias == (Pendencia(venda_id, "forma_pagamento"),)


async def test_dinheiro_fica_em_especie_e_sem_expectativa_de_comprovante(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """08/08: "Foi pix ou din ?" -> "Dinheiro". A venda conta no vendido, fica com a modelo e sai
    da fila de comprovante — cobrar comprovante de dinheiro vivo e pedir o que nao existe."""
    grupo = await _montar_grupo(conn, inicio=NOITE_DE_08_08)
    falas = _Falas()

    await _dizer(conn, grupo, ANUNCIO_GABRIEL, falas=falas)
    await _dizer(conn, grupo, "Foi pix ou din ?", falas=falas, depois=timedelta(hours=2))
    pago = await _dizer(conn, grupo, "Dinheiro", falas=falas, depois=timedelta(minutes=6))

    assert pago.pendencias == ()  # a unica pendencia daquela venda morreu aqui
    assert falas.ultima is not None
    assert EM_ESPECIE_COM_A_MODELO in falas.ultima
    assert "Cliente Gabriel" in falas.ultima
    assert "comprovante" not in falas.ultima.lower()
    (venda,) = await _vendas(conn, grupo.modelo_id)
    assert venda["forma_pagamento"] == "dinheiro"


async def test_pix_nao_e_anunciado_como_em_especie(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    grupo = await _montar_grupo(conn, inicio=NOITE_DE_08_08)
    falas = _Falas()

    await _dizer(conn, grupo, ANUNCIO_GABRIEL, falas=falas)
    await _dizer(conn, grupo, "Pix", falas=falas, depois=timedelta(hours=2))

    assert falas.ultima is not None
    assert EM_ESPECIE_COM_A_MODELO not in falas.ultima
    (venda,) = await _vendas(conn, grupo.modelo_id)
    assert venda["forma_pagamento"] == "pix"


async def test_pendencia_nao_impede_registro_nem_conciliacao_das_outras(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Uma venda pendente ha dias nao segura a fila: as seguintes registram e conciliam, e ela
    continua la, cobravel, ate alguem dizer a forma."""
    grupo = await _montar_grupo(conn, inicio=NOITE_DE_08_08)
    falas = _Falas()

    esquecida = await _dizer(conn, grupo, ANUNCIO_GABRIEL, falas=falas)

    nova = await _dizer(conn, grupo, ANUNCIO_LUCAS, falas=falas, depois=timedelta(days=4))
    assert len(nova.vendas) == 1  # registro novo passa por cima da pendencia antiga

    await _dizer(conn, grupo, "O Lucas de ontem", falas=falas, depois=timedelta(minutes=1))
    conciliou = await _dizer(conn, grupo, "Pix", falas=falas, depois=timedelta(seconds=40))
    assert conciliou.pagamentos == nova.vendas

    por_cliente = {v["cliente_nome"]: v for v in await _vendas(conn, grupo.modelo_id)}
    assert por_cliente["Lucas"]["forma_pagamento"] == "pix"
    assert por_cliente["Gabriel"]["forma_pagamento"] is None

    # E a esquecida continua conciliavel depois, sem nada de especial. Quem a concilia e a fala que
    # NOMEIA a venda ("O Gabriel foi dinheiro" diz o cliente e a forma na mesma frase): ela nao
    # precisa da segunda etapa do padrao do grupo ("O Lucas de ontem" -> "Pix").
    tardio = await _dizer(
        conn, grupo, "O Gabriel foi dinheiro", falas=falas, depois=timedelta(days=1)
    )
    assert tardio.pagamentos == esquecida.vendas

    # E o "Dinheiro" solto que vem depois nao acha mais venda aberta: repetir a forma ja dita nao
    # reescreve nada (trocar o que foi dito e correcao, com porta propria — ticket 05).
    repetido = await _dizer(conn, grupo, "Dinheiro", falas=falas, depois=timedelta(seconds=30))
    assert repetido.pagamentos == ()
    assert repetido.motivo == "pagamento_sem_venda_certa"


async def test_segunda_resposta_nao_sobrescreve_forma_ja_dita(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Mudar o que ja foi dito e CORRECAO, e correcao tem porta propria e rastro (ticket 05).

    Aqui a segunda fala nao acha venda aberta nenhuma e cala — a forma dita antes fica de pe.
    """
    grupo = await _montar_grupo(conn, inicio=NOITE_DE_08_08)
    falas = _Falas()

    await _dizer(conn, grupo, ANUNCIO_GABRIEL, falas=falas)
    await _dizer(conn, grupo, "Pix", falas=falas, depois=timedelta(hours=1))
    segunda = await _dizer(conn, grupo, "Dinheiro", falas=falas, depois=timedelta(minutes=2))

    assert segunda.motivo == "pagamento_sem_venda_certa"
    (venda,) = await _vendas(conn, grupo.modelo_id)
    assert venda["forma_pagamento"] == "pix"


async def test_a_fila_segue_o_relogio_do_grupo_e_nao_a_ordem_de_entrega(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Duas mensagens entregues fora de ordem: a fila e a do GRUPO, nao a do webhook.

    A Evolution reentrega e atrasa — o anuncio das 22h pode chegar depois do das 23h. Quem ordena
    a fila e `recebida_em`, nunca a hora do INSERT: as recentes sao as que a cobranca da manha
    nomeia e as que a pergunta de desempate oferece, e "a ultima que o grupo anunciou" tem que ser
    a ultima que o grupo anunciou.
    """
    grupo = await _montar_grupo(conn, inicio=NOITE_DE_08_08)
    falas = _Falas()

    # a mais NOVA (23h) entra primeiro; a mais velha (22h) chega atrasada, depois
    grupo.relogio = NOITE_DE_08_08 + timedelta(hours=1)
    await _dizer(conn, grupo, ANUNCIO_LUCAS, falas=falas, depois=timedelta(0))
    grupo.relogio = NOITE_DE_08_08
    await _dizer(conn, grupo, ANUNCIO_GABRIEL, falas=falas, depois=timedelta(0))

    abertas = await vendas_sem_forma_de_pagamento(conn, grupo.modelo_id)

    assert [v.cliente_nome for v in abertas] == ["Gabriel", "Lucas"]
    # E a pergunta de desempate oferece a mais recente na frente, nao a que o banco inseriu antes.
    pergunta = montar_pergunta_de_desempate(forma="pix", candidatas=abertas)
    assert pergunta is not None
    assert pergunta.index("Lucas") < pergunta.index("Gabriel")


# --- 6. o leitor de fala e injetavel: a conduta nao muda com quem interpreta ---------------------


def _leitor(intencao: IntencaoDoGrupo | None) -> LerIntencao:
    """Um leitor de intencao stubado — o mesmo contrato que a LLM cumpre em producao.

    Stubar a IDA AO PROVIDER e nao a conduta e a mesma escolha do olho e do ouvido: o que estes
    testes provam e o que o GRUPO ve depois da leitura, e isso tem que ser identico com a
    allowlist ou com o modelo lendo. Fosse a conduta que mudasse junto, trocar de leitor seria
    trocar de agente.
    """

    async def ler(texto: str, abertas: Any, contexto: Any) -> IntencaoDoGrupo | None:
        return intencao

    return ler


async def test_leitura_de_uma_venda_rende_o_recibo_nomeado(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """A LLM apontou UMA venda: sai o mesmo recibo de sempre, com cliente, valor e dia.

    O recibo e a porta de correcao do modulo, e ele nao pode encolher porque quem leu a frase
    mudou — e justamente com um leitor que interpreta que a linha de conferencia importa mais.
    """
    grupo = await _montar_grupo(conn, inicio=NOITE_DE_08_08)
    falas = _Falas()
    await _dizer(conn, grupo, ANUNCIO_GABRIEL, falas=falas)
    abertas = await vendas_sem_forma_de_pagamento(conn, grupo.modelo_id)

    dito = await _dizer(
        conn,
        grupo,
        "esse aí o cliente acertou comigo em espécie na hora",
        falas=falas,
        ler_intencao=_leitor(
            IntencaoDoGrupo(tipo="forma_de_pagamento", forma="dinheiro", vendas=tuple(abertas))
        ),
    )

    assert dito.motivo == "pagamento_absorvido"
    (venda,) = await _vendas(conn, grupo.modelo_id)
    assert venda["forma_pagamento"] == "dinheiro"
    assert falas.ultima is not None
    assert "Cliente Gabriel" in falas.ultima
    assert EM_ESPECIE_COM_A_MODELO in falas.ultima


async def test_leitura_coletiva_fecha_a_fila_inteira_com_um_recibo_conferivel(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """ "Foi tudo no pix": UMA resposta fecha as tres pendencias — o gesto que a fila espera.

    A cobranca da manha e consolidada por regra do dominio (uma mensagem, N vendas), entao a
    resposta a ela tambem e. O recibo carrega **quantas** e o **total** porque e com esses dois
    numeros que o gestor confere se o "tudo" dele bateu com o do agente — uma venda anunciada
    depois da cobranca entra nesta conta sem ele saber.
    """
    grupo = await _montar_grupo(conn, inicio=NOITE_DE_08_08)
    falas = _Falas()
    await _dizer(conn, grupo, ANUNCIO_GABRIEL, falas=falas)
    await _dizer(conn, grupo, ANUNCIO_RAMON, falas=falas, depois=timedelta(hours=2))
    await _dizer(conn, grupo, ANUNCIO_LUCAS, falas=falas, depois=timedelta(hours=2))
    abertas = await vendas_sem_forma_de_pagamento(conn, grupo.modelo_id)
    assert len(abertas) == 3

    dito = await _dizer(
        conn,
        grupo,
        "foi tudo no pix amiga",
        falas=falas,
        ler_intencao=_leitor(
            IntencaoDoGrupo(tipo="forma_de_pagamento", forma="pix", vendas=tuple(abertas))
        ),
    )

    assert dito.motivo == "pagamento_coletivo"
    assert len(dito.pagamentos) == 3
    assert [v["forma_pagamento"] for v in await _vendas(conn, grupo.modelo_id)] == ["pix"] * 3
    assert falas.ultima is not None
    assert "3 vendas" in falas.ultima
    assert "R$ 1.900,00" in falas.ultima  # 700 + 600 + 600: o total que se confere de cabeca


async def test_leitura_sem_alvo_pergunta_em_vez_de_chutar(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """A LLM entendeu a forma e NAO soube de qual venda: pergunta, nao escreve.

    E a mesma conduta da allowlist ambigua, e ela e a razao de a troca de leitor ser segura —
    marcar a venda errada e o unico erro do modulo que nao volta (ela some da conferencia e a
    certa nunca mais e cobrada), entao "nao sei" nunca pode virar escrita.
    """
    grupo = await _montar_grupo(conn, inicio=NOITE_DE_08_08)
    falas = _Falas()
    await _dizer(conn, grupo, ANUNCIO_GABRIEL, falas=falas)
    await _dizer(conn, grupo, ANUNCIO_RAMON, falas=falas, depois=timedelta(hours=2))

    dito = await _dizer(
        conn,
        grupo,
        "aquele lá foi pix",
        falas=falas,
        ler_intencao=_leitor(IntencaoDoGrupo(tipo="forma_de_pagamento", forma="pix", vendas=())),
    )

    assert dito.motivo == "pagamento_ambiguo"
    assert all(v["forma_pagamento"] is None for v in await _vendas(conn, grupo.modelo_id))
    assert falas.ultima is not None
    assert falas.ultima.startswith(PREFIXO_DO_DESEMPATE)


async def test_leitura_hesitante_nao_escreve_mesmo_com_alvo(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Confianca baixa com alvo apontado: pergunta do mesmo jeito.

    O modelo diz quando esta interpretando, e interpretar sobre dinheiro e exatamente onde
    perguntar custa uma mensagem e errar custa uma venda. Sem esta linha, o campo `confianca`
    seria enfeite — o alvo entraria no banco igual.
    """
    grupo = await _montar_grupo(conn, inicio=NOITE_DE_08_08)
    falas = _Falas()
    await _dizer(conn, grupo, ANUNCIO_GABRIEL, falas=falas)
    await _dizer(conn, grupo, ANUNCIO_RAMON, falas=falas, depois=timedelta(hours=2))
    abertas = await vendas_sem_forma_de_pagamento(conn, grupo.modelo_id)

    dito = await _dizer(
        conn,
        grupo,
        "acho que o primeiro foi no pix, não lembro bem",
        falas=falas,
        ler_intencao=_leitor(
            IntencaoDoGrupo(
                tipo="forma_de_pagamento",
                forma="pix",
                vendas=(abertas[0],),
                confiavel=False,
            )
        ),
    )

    assert dito.motivo == "pagamento_ambiguo"
    assert all(v["forma_pagamento"] is None for v in await _vendas(conn, grupo.modelo_id))


async def test_provider_fora_cai_na_allowlist_e_o_grupo_nao_fica_surdo(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Leitor devolvendo `None` (provider fora, resposta inconclusiva): a allowlist ainda responde.

    Em 24/07 a `OPENROUTER_API_KEY` sumiu num redeploy e o OCR do Pix passou dias marcando tudo
    `em_revisao` sem ninguem entender por que. Aqui o custo de um dia ruim do provider e voltar ao
    alcance da allowlist — e nao o grupo inteiro ficar sem resposta.
    """
    grupo = await _montar_grupo(conn, inicio=NOITE_DE_08_08)
    falas = _Falas()
    await _dizer(conn, grupo, ANUNCIO_GABRIEL, falas=falas)

    dito = await _dizer(conn, grupo, "Pix", falas=falas, ler_intencao=_leitor(None))

    assert dito.motivo == "pagamento_absorvido"
    (venda,) = await _vendas(conn, grupo.modelo_id)
    assert venda["forma_pagamento"] == "pix"


async def test_pedido_de_fechamento_em_fala_livre_sai_pelo_leitor(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """ "Como tá a conta amiga?" — a frase que a allowlist do fechamento nao tem como cobrir.

    Ela nao carrega nenhuma palavra-gatilho ("fechamento", "extrato", "confere"), entao o pedido
    morria em silencio DEPOIS de a leitura ter entendido: a casa pagava o provider e jogava fora a
    resposta. Aqui nao ha risco de escrita — o extrato so le —, e por isso este e o unico tipo da
    leitura que dispensa a conferencia de alvo.
    """
    grupo = await _montar_grupo(conn, inicio=NOITE_DE_08_08)
    falas = _Falas()
    await _dizer(conn, grupo, ANUNCIO_GABRIEL, falas=falas)

    pediu = await _dizer(
        conn,
        grupo,
        "Como tá a conta amiga ?",
        falas=falas,
        ler_intencao=_leitor(IntencaoDoGrupo(tipo="pedido_de_fechamento")),
    )

    assert pediu.motivo == "fechamento_postado"
    assert falas.ultima is not None
    assert "R$ 700,00" in falas.ultima  # o valor do anuncio do Gabriel, no extrato
    # A venda continua sem forma de pagamento: pedir o extrato nao escreve nada.
    assert all(v["forma_pagamento"] is None for v in await _vendas(conn, grupo.modelo_id))


async def test_leitura_hesitante_nao_atropela_a_allowlist_que_sabe_de_qual_venda(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """O gesto mais comum do grupo real: anuncio, "Foi pix ou din ?", "Pix".

    A allowlist acerta esse por construcao — a pergunta acabou de ser feita sobre a venda que
    acabou de ser anunciada. O leitor, olhando so o texto, hesita (ou aponta a venda errada), e
    por um tempo a leitura hesitante vencia: o replay do export real mostrou "Dinheiro" caindo na
    venda errada e "Sim" virando pergunta de desempate — o agente devolvendo a pergunta que
    acabara de ser respondida.

    A regra que ficou: a LLM assume o turno quando traz o que a allowlist nao tem — um alvo, com
    confianca. Hesitando, ela nao piora o que ja funcionava.
    """
    grupo = await _montar_grupo(conn, inicio=NOITE_DE_08_08)
    falas = _Falas()
    await _dizer(conn, grupo, ANUNCIO_GABRIEL, falas=falas)
    await _dizer(conn, grupo, ANUNCIO_RAMON, falas=falas, depois=timedelta(hours=2))
    abertas = await vendas_sem_forma_de_pagamento(conn, grupo.modelo_id)
    await _dizer(conn, grupo, "Foi pix ou din ?", falas=falas, depois=timedelta(minutes=10))

    dito = await _dizer(
        conn,
        grupo,
        "Pix",
        falas=falas,
        depois=timedelta(minutes=5),
        ler_intencao=_leitor(
            IntencaoDoGrupo(
                tipo="forma_de_pagamento",
                forma="pix",
                vendas=(abertas[0],),  # o alvo ate esta certo — o que falta e confianca
                confiavel=False,
            )
        ),
    )

    assert dito.motivo == "pagamento_absorvido"
    assert falas.ultima is not None
    assert not falas.ultima.startswith(PREFIXO_DO_DESEMPATE)


# --- anulacao dita em fala ("cancela esse atendimento") ------------------------------------------


async def test_cancelar_por_texto_tira_a_venda_da_conta_e_diz_qual(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """ "cancela esse atendimento do denis, ele nao veio" — o gesto que morria calado.

    Sem isto a modelo era cobrada na manha seguinte por um atendimento que nao houve, e a unica
    saida era apagar a mensagem do anuncio. O efeito aqui e o MESMO da delecao (anula + evento);
    o que muda e a superficie.
    """
    grupo = await _montar_grupo(conn, inicio=NOITE_DE_08_08)
    falas = _Falas()
    await _dizer(conn, grupo, ANUNCIO_GABRIEL, falas=falas)
    await _dizer(conn, grupo, ANUNCIO_RAMON, falas=falas, depois=timedelta(hours=2))
    abertas = await vendas_sem_forma_de_pagamento(conn, grupo.modelo_id)
    ramon = next(v for v in abertas if (v.cliente_nome or "").lower() == "ramon")

    cancelou = await _dizer(
        conn,
        grupo,
        "cancela esse atendimento do ramon, ele não veio",
        falas=falas,
        ler_intencao=_leitor(IntencaoDoGrupo(tipo="anulacao_de_venda", vendas=(ramon,))),
    )

    assert cancelou.motivo == "venda_anulada"
    assert cancelou.anuladas == (ramon.id,)
    # A outra venda continua de pe: cancelar e sempre UMA.
    vivas = [
        v["cliente_nome"] for v in await _vendas(conn, grupo.modelo_id) if v["anulada_em"] is None
    ]
    assert vivas == ["Gabriel"]

    assert falas.ultima is not None
    assert falas.ultima.startswith("🗑️ Cancelei:")
    assert "postar o anúncio de novo" in falas.ultima  # o desfazer tem gesto, e ele e dito
    # Nomeia o que morreu: cancelar a venda errada nao deixa sintoma nenhum na conferencia.
    assert "ramon" in falas.ultima and "R$ 600,00" in falas.ultima


async def test_cancelar_sem_dizer_qual_pergunta_em_vez_de_apagar(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Entendeu o QUE fazer e nao de qual venda: apagar no escuro e o erro que nao deixa rastro."""
    grupo = await _montar_grupo(conn, inicio=NOITE_DE_08_08)
    falas = _Falas()
    await _dizer(conn, grupo, ANUNCIO_GABRIEL, falas=falas)
    await _dizer(conn, grupo, ANUNCIO_RAMON, falas=falas, depois=timedelta(hours=2))

    duvidoso = await _dizer(
        conn,
        grupo,
        "cancela esse atendimento",
        falas=falas,
        ler_intencao=_leitor(IntencaoDoGrupo(tipo="anulacao_de_venda", vendas=())),
    )

    assert duvidoso.motivo == "anulacao_ambigua"
    assert duvidoso.anuladas == ()
    assert len(await _vendas(conn, grupo.modelo_id)) == 2
    assert falas.ultima is not None
    assert falas.ultima.startswith("❓ Cancelar qual?")


async def test_leitura_hesitante_nao_apaga_venda_nenhuma(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Confianca baixa com alvo apontado: pergunta, igual ao que a forma de pagamento ja faz.

    Apagar e mais grave que escrever a forma errada — a venda some da conferencia e da cobranca,
    e ninguem procura o que parou de ser pedido.
    """
    grupo = await _montar_grupo(conn, inicio=NOITE_DE_08_08)
    falas = _Falas()
    await _dizer(conn, grupo, ANUNCIO_GABRIEL, falas=falas)
    (gabriel,) = await vendas_sem_forma_de_pagamento(conn, grupo.modelo_id)

    hesitou = await _dizer(
        conn,
        grupo,
        "acho que esse do gabriel não vai acontecer",
        falas=falas,
        ler_intencao=_leitor(
            IntencaoDoGrupo(tipo="anulacao_de_venda", vendas=(gabriel,), confiavel=False)
        ),
    )

    assert hesitou.motivo == "anulacao_ambigua"
    assert len(await _vendas(conn, grupo.modelo_id)) == 1


async def test_repostar_o_anuncio_depois_do_cancelamento_volta_a_valer(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """O desfazer que o recibo do cancelamento promete tem que existir de verdade.

    O indice de dedup e PARCIAL (`WHERE anulada_em IS NULL`): a venda cancelada sai do caminho e o
    mesmo anuncio registra de novo. Sem isto, "é só postar o anúncio de novo" seria uma promessa
    que o banco desmente — e a venda cancelada por engano nao teria volta nenhuma.
    """
    grupo = await _montar_grupo(conn, inicio=NOITE_DE_08_08)
    falas = _Falas()
    await _dizer(conn, grupo, ANUNCIO_GABRIEL, falas=falas)
    (gabriel,) = await vendas_sem_forma_de_pagamento(conn, grupo.modelo_id)
    await _dizer(
        conn,
        grupo,
        "cancela o do gabriel, ele não veio",
        falas=falas,
        ler_intencao=_leitor(IntencaoDoGrupo(tipo="anulacao_de_venda", vendas=(gabriel,))),
    )

    de_novo = await _dizer(conn, grupo, ANUNCIO_GABRIEL, falas=falas, depois=timedelta(minutes=5))

    assert de_novo.motivo is None
    assert len(de_novo.vendas) == 1
    vivas = [
        v["cliente_nome"] for v in await _vendas(conn, grupo.modelo_id) if v["anulada_em"] is None
    ]
    assert vivas == ["Gabriel"]


async def test_pedido_de_fechamento_sai_mesmo_com_a_fila_vazia(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Nada pendente e alguem pergunta a conta: e o melhor momento para responder, nao o pior.

    O leitor so era chamado quando havia venda em aberto ("sem alvo para apontar, não há o que a
    leitura mude") — verdade para forma de pagamento, falso para o extrato. No replay isso apareceu
    exatamente depois de tudo ter sido quitado: a pergunta caiu no silencio.
    """
    grupo = await _montar_grupo(conn, inicio=NOITE_DE_08_08)
    falas = _Falas()
    assert await vendas_sem_forma_de_pagamento(conn, grupo.modelo_id) == []

    pediu = await _dizer(
        conn,
        grupo,
        "e aí amiga, como tá a conta ?",
        falas=falas,
        ler_intencao=_leitor(IntencaoDoGrupo(tipo="pedido_de_fechamento")),
    )

    assert pediu.motivo == "fechamento_postado"
    # Grupo sem movimento responde a linha curta, e nao um extrato de quatro zeros — mas RESPONDE.
    assert falas.ultima == TUDO_CONCILIADO
