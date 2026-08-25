"""Dados cadastrais oportunistas (spec 0005, ticket 12) — pela PORTA UNICA.

O caso e literal do export "Modelo Yasmin Ruiva/financeiro", 09/08/2026:

    [12:55:16] ~ Dani:            Passa o novo apartamento amiga
    [12:55:20] ~ Dani:            Torre e apartamento
    [12:55:39] +55 11 96854-4493: Torre 2 Apt 2706

O que este arquivo prova:

1. "Torre 2 Apt 2706" atualiza os **Dados cadastrais da modelo do grupo** e o agente NAO responde
   — nem recibo, nem "anotei".
2. O agente nunca INICIA pergunta de cadastro: quem pediu o apartamento foi a gestora, e as duas
   mensagens dela (a pergunta e o "Torre e apartamento" pela metade) nao arrancam nada dele. A
   unica pergunta que sobra no grupo continua sendo a **pergunta minima** de uma venda.
3. Toda atualizacao guarda o **valor anterior** — o historico e a auditoria — e nada disso encosta
   na ficha de `barravips.modelos` que a IA de venda le (painel-only).
4. Dado ambiguo ("Torre e apartamento"), de terceiro ("O cliente ta na torre 3 apt 101") e chave
   Pix ditada por quem NAO e a modelo (a mensagem real do gestor passando a conta da casa) sao
   ignorados — fail-closed.
5. O numero do apartamento nao vira dinheiro: com um anuncio incompleto esperando valor, "Torre 2
   Apt 2706" continua sendo endereco.
6. A chave da propria modelo, aprendida assim, muda o que o agente enxerga num comprovante que
   aponta para ela — sem virar destino autorizado da casa.

Tudo entra por `processar_mensagem_do_grupo`; nenhum teste chama funcao interna do modulo (licao
do harness fiel). `needs_db` com `TEST_DATABASE_URL` + ROLLBACK sempre — o dado cadastral E uma
linha com FK para a mensagem-fonte, e um fake provaria o mock.
"""

import os
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from barra.agente_financeiro import ResultadoDaPorta, processar_mensagem_do_grupo
from barra.dominio.grupo_financeiro.comprovante import LeituraDoComprovante
from barra.dominio.grupo_financeiro.modelos import ImagemDoGrupo, MensagemDoGrupo
from barra.dominio.grupo_financeiro.repo import dado_cadastral_atual

pytestmark = pytest.mark.needs_db

# --- mensagens reais do export (grafia intacta) -------------------------------------------------

PERGUNTA_DA_GESTORA = "Passa o novo apartamento amiga"
PEDIDO_PELA_METADE = "Torre e apartamento"
APARTAMENTO = "Torre 2 Apt 2706"
APARTAMENTO_NOVO = "Torre 1 Apt 1904"
"""Nao esta no export: e a MUDANCA, que o export (13 dias de grupo) ainda nao mostrou. O criterio
do ticket e sobre o segundo endereco, entao ele precisa existir aqui."""

CHAVE_DA_CASA = "00000000-0000-0000-0000-000000000000"
"""Chave aleatoria da casa, com valor FICTICIO — a viva nao mora no repositorio (o INSERT dela e
passo de runbook). Aqui ela e so TEXTO: o que o teste cobre e que chave ditada por um gestor nao
vira cadastro da modelo, e para isso basta a forma (32 hex), nunca o valor."""
DECLARACAO_DA_CHAVE = "Minha Chave Pix para transferência: +5571999840879"
"""Mensagem real do grupo — e de um GESTOR passando a conta da casa. E o caso que separa "primeira
pessoa" de "posse": so vira cadastro da modelo quando quem escreve e ela."""

ANUNCIO_SEM_VALOR = "Atendimento no nosso local \nCliente ramon \nPerfil {apelido}"
ANUNCIO_COMPLETO = "Atendimento no nosso local \nCliente Gabriel \nPerfil {apelido} \n700 1h"

# 09/08 15:55 UTC = 09/08 12:55 em Brasilia — a hora do "Passa o novo apartamento amiga".
TARDE_DE_09_08 = datetime(2026, 8, 9, 15, 55, tzinfo=UTC)

JID_DA_GESTORA = "5521999999999@s.whatsapp.net"


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


# --- o grupo e a fronteira (nada fala com a Evolution) ------------------------------------------


class _Falas:
    """O que o agente postou no grupo. Coleta em vez de ir a rede."""

    def __init__(self) -> None:
        self.enviadas: list[str] = []

    async def __call__(self, texto: str, *, citar: str | None = None) -> None:
        self.enviadas.append(texto)


class _Olho:
    """Leitor de comprovante stubado — nenhum teste desta casa exige chave de provider."""

    def __init__(self, *leituras: LeituraDoComprovante) -> None:
        self.leituras = list(leituras)

    async def __call__(self, imagem: ImagemDoGrupo) -> LeituraDoComprovante | None:
        return self.leituras.pop(0) if self.leituras else None


class _Grupo:
    def __init__(self, modelo_id: UUID, jid: str, apelido: str, numero: str) -> None:
        self.modelo_id = modelo_id
        self.jid = jid
        self.apelido = apelido
        self.numero = numero
        self.jid_da_modelo = f"{numero}@s.whatsapp.net"
        self.relogio = TARDE_DE_09_08


async def _montar_grupo(c: AsyncConnection[dict[str, Any]]) -> _Grupo:
    """O grupo do export: a modelo (com o WhatsApp dela cadastrado), o apelido e o vinculo."""
    modelo_id = uuid4()
    apelido = f"bianca{uuid4().hex[:8]}"
    numero = f"5511{uuid4().int % 1_000_000_000:09d}"
    await c.execute(
        """
        INSERT INTO barravips.modelos
            (id, nome, idade, numero_whatsapp, valor_padrao, tipo_atendimento_aceito,
             percentual_repasse, status)
        VALUES (%s, %s, %s, %s, %s, %s::barravips.tipo_atendimento_enum[], %s,
                'ativa'::barravips.modelo_status_enum)
        """,
        (modelo_id, f"Yasmin {uuid4().hex[:6]}", 25, numero, 700, ["interno"], Decimal("40")),
    )
    await c.execute(
        """
        INSERT INTO barravips.modelo_nomes_anuncio (modelo_id, nome, nome_normalizado)
        VALUES (%s, %s, %s)
        """,
        (modelo_id, apelido, apelido),
    )
    jid = f"1203634{uuid4().hex[:12]}@g.us"
    await c.execute(
        """
        INSERT INTO barravips.grupos_financeiros (id, modelo_id, jid, nome)
        VALUES (%s, %s, %s, %s)
        """,
        (uuid4(), modelo_id, jid, "Modelo Yasmin Ruiva/financeiro"),
    )
    return _Grupo(modelo_id, jid, apelido, numero)


async def _dizer(
    c: AsyncConnection[dict[str, Any]],
    grupo: _Grupo,
    texto: str,
    *,
    falas: _Falas,
    de: str | None = None,
    olho: _Olho | None = None,
    depois: timedelta = timedelta(seconds=20),
    **kw: Any,
) -> ResultadoDaPorta:
    """Um humano digita no grupo. `de=None` = a gestora (Dani), como no export."""
    grupo.relogio += depois
    kw.setdefault("evolution_message_id", f"3EB0{uuid4().hex[:12]}")
    kw.setdefault("autor_nome", "Dani" if de is None else "Yasmin")
    msg = MensagemDoGrupo(
        grupo_jid=grupo.jid,
        texto=texto,
        autor_jid=de or JID_DA_GESTORA,
        recebida_em=grupo.relogio,
        **kw,
    )
    return await processar_mensagem_do_grupo(c, msg, enviar=falas, ler_comprovante=olho)


async def _cadastro(c: AsyncConnection[dict[str, Any]], modelo_id: UUID) -> list[dict[str, Any]]:
    cur = await c.execute(
        """
        SELECT campo, valor, valor_anterior, mensagem_id, observado_em
          FROM barravips.modelo_dados_cadastrais
         WHERE modelo_id = %s
         ORDER BY observado_em, id
        """,
        (modelo_id,),
    )
    return list(await cur.fetchall())


# --- 1. o caso de 09/08: entra calado -----------------------------------------------------------


async def test_apartamento_dito_no_grupo_atualiza_o_cadastro_sem_o_agente_falar(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """A sequencia real de 12:55 — e o agente atravessa as tres mensagens sem abrir a boca."""
    grupo = await _montar_grupo(conn)
    falas = _Falas()

    await _dizer(conn, grupo, PERGUNTA_DA_GESTORA, falas=falas)
    await _dizer(conn, grupo, PEDIDO_PELA_METADE, falas=falas)
    resultado = await _dizer(conn, grupo, APARTAMENTO, falas=falas, de=grupo.jid_da_modelo)

    assert resultado.status == "registrada"
    assert resultado.motivo == "cadastro_atualizado"
    assert resultado.vendas == ()
    # O ponto do ticket: o efeito e no cadastro, e o grupo nao ouve nada por causa dele.
    assert resultado.resposta is None
    assert falas.enviadas == []

    linhas = await _cadastro(conn, grupo.modelo_id)
    assert len(linhas) == 1
    assert linhas[0]["campo"] == "endereco_operacional"
    assert linhas[0]["valor"] == APARTAMENTO
    assert linhas[0]["valor_anterior"] is None
    assert linhas[0]["mensagem_id"] == resultado.mensagem_id  # origem auditavel
    assert resultado.cadastro is not None
    assert resultado.cadastro.valor == APARTAMENTO


# --- 2. auditoria: o valor anterior nao se perde ------------------------------------------------


async def test_apartamento_novo_guarda_o_anterior_e_o_historico(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    grupo = await _montar_grupo(conn)
    falas = _Falas()

    primeiro = await _dizer(conn, grupo, APARTAMENTO, falas=falas, de=grupo.jid_da_modelo)
    segundo = await _dizer(
        conn,
        grupo,
        APARTAMENTO_NOVO,
        falas=falas,
        de=grupo.jid_da_modelo,
        depois=timedelta(days=3),
    )

    assert segundo.motivo == "cadastro_atualizado"
    assert falas.enviadas == []

    antigo, novo = await _cadastro(conn, grupo.modelo_id)
    assert antigo["valor"] == APARTAMENTO
    assert antigo["mensagem_id"] == primeiro.mensagem_id
    # O que o ticket cobra: o valor anterior PRESERVADO, na linha que o substituiu.
    assert novo["valor"] == APARTAMENTO_NOVO
    assert novo["valor_anterior"] == APARTAMENTO
    assert novo["mensagem_id"] == segundo.mensagem_id


async def test_repetir_o_mesmo_apartamento_nao_inventa_evento(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Observacao que nao muda nada nao vira linha — senao o historico deixa de ser historico."""
    grupo = await _montar_grupo(conn)
    falas = _Falas()

    await _dizer(conn, grupo, APARTAMENTO, falas=falas, de=grupo.jid_da_modelo)
    repetido = await _dizer(conn, grupo, "torre 2, apt 2706", falas=falas, de=grupo.jid_da_modelo)

    assert repetido.motivo == "cadastro_sem_efeito"
    assert repetido.cadastro is None
    assert falas.enviadas == []
    assert len(await _cadastro(conn, grupo.modelo_id)) == 1


# --- 3. o agente nunca comeca uma pergunta de cadastro ------------------------------------------


async def test_agente_nunca_pergunta_cadastro_nem_no_meio_de_uma_venda(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """A gestora pergunta pelo apartamento; o agente nao.

    O contra-exemplo esta na mesma corrida: um anuncio incompleto AINDA arranca a pergunta minima
    (aquilo e venda, ticket 03). O que nao pode existir e uma pergunta sobre cadastro — nem sobre
    o apartamento que ficou pela metade, nem sobre a chave Pix que ninguem deu.
    """
    grupo = await _montar_grupo(conn)
    falas = _Falas()

    await _dizer(conn, grupo, PERGUNTA_DA_GESTORA, falas=falas)
    await _dizer(conn, grupo, PEDIDO_PELA_METADE, falas=falas)
    await _dizer(conn, grupo, APARTAMENTO, falas=falas, de=grupo.jid_da_modelo)
    incompleto = await _dizer(
        conn, grupo, ANUNCIO_SEM_VALOR.format(apelido=grupo.apelido), falas=falas
    )

    assert incompleto.motivo == "sem_valor"
    assert falas.enviadas == [incompleto.resposta]  # a UNICA fala da sequencia
    unica = falas.enviadas[0]
    assert unica.startswith("❓ Só falta saber: ")
    assert "quanto" in unica.lower()
    for palavra in ("apartamento", "torre", "endereço", "chave", "pix", "cadastro"):
        assert palavra not in unica.lower()


# --- 4. fail-closed: ambiguo, de terceiro, chave alheia -----------------------------------------


@pytest.mark.parametrize(
    "texto",
    [
        PERGUNTA_DA_GESTORA,  # a pergunta da gestora nao e o dado
        PEDIDO_PELA_METADE,  # lugar sem numero: ambiguo
        "O cliente tá na torre 3 apt 101",  # dado de terceiro
        "Apt do cliente",
        "2706",  # numero solto nao e endereco de ninguem
        f"Pode enviar nesse pix {CHAVE_DA_CASA}",  # chave DA CASA ditada no grupo
    ],
)
async def test_dado_ambiguo_ou_de_terceiro_e_ignorado(
    conn: AsyncConnection[dict[str, Any]], texto: str
) -> None:
    grupo = await _montar_grupo(conn)
    falas = _Falas()

    resultado = await _dizer(conn, grupo, texto, falas=falas, de=grupo.jid_da_modelo)

    assert resultado.cadastro is None
    assert resultado.motivo != "cadastro_atualizado"
    assert falas.enviadas == []
    assert await _cadastro(conn, grupo.modelo_id) == []


async def test_chave_pix_so_e_dela_quando_e_ela_quem_dita(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """A mesma frase, dois autores: a do gestor e a conta da casa, a dela e o cadastro dela."""
    grupo = await _montar_grupo(conn)
    falas = _Falas()

    do_gestor = await _dizer(conn, grupo, DECLARACAO_DA_CHAVE, falas=falas)

    assert do_gestor.motivo == "cadastro_de_terceiro"
    assert do_gestor.cadastro is None
    assert await _cadastro(conn, grupo.modelo_id) == []

    dela = await _dizer(conn, grupo, DECLARACAO_DA_CHAVE, falas=falas, de=grupo.jid_da_modelo)

    assert dela.motivo == "cadastro_atualizado"
    (linha,) = await _cadastro(conn, grupo.modelo_id)
    assert linha["campo"] == "chave_pix"
    assert linha["valor"] == "+5571999840879"
    assert falas.enviadas == []

    # E ela NAO virou destino autorizado da casa: cadastrar a chave da modelo la faria um Pix para
    # a conta dela passar por fechamento da casa — o oposto do que o aviso do ticket 07 existe
    # para pegar.
    cur = await conn.execute(
        "SELECT count(*) AS n FROM barravips.chaves_pix_conhecidas WHERE chave = %s",
        ("+5571999840879",),
    )
    row = await cur.fetchone()
    assert row is not None and row["n"] == 0


# --- 5. painel-only: a ficha que a IA de venda le nao e tocada ----------------------------------


async def test_dado_cadastral_nao_encosta_na_ficha_da_ia_de_venda(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """`modelos.endereco_formatado`/`chave_pix` sao o que a IA de venda cita para o cliente.

    O dado do grupo e painel-only: entra no modulo que o capturou, nao na ficha operacional (que
    ainda anda casada com o geocode). Escrever la seria colocar na boca do agente de venda um
    endereco sem revisao.
    """
    grupo = await _montar_grupo(conn)
    falas = _Falas()

    await _dizer(conn, grupo, APARTAMENTO, falas=falas, de=grupo.jid_da_modelo)
    await _dizer(conn, grupo, DECLARACAO_DA_CHAVE, falas=falas, de=grupo.jid_da_modelo)

    cur = await conn.execute(
        """
        SELECT endereco_formatado, nome_local, localizacao_operacional,
               endereco_residencial_formatado, chave_pix, titular_chave
          FROM barravips.modelos WHERE id = %s
        """,
        (grupo.modelo_id,),
    )
    ficha = await cur.fetchone()
    assert ficha is not None
    assert all(valor is None for valor in ficha.values()), ficha
    assert len(await _cadastro(conn, grupo.modelo_id)) == 2


# --- 6. o numero do apartamento nunca vira dinheiro ---------------------------------------------


async def test_apartamento_nao_completa_anuncio_esperando_valor(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Anuncio sem valor esperando resposta + "Torre 2 Apt 2706" = endereco, nao R$ 2.706,00."""
    grupo = await _montar_grupo(conn)
    falas = _Falas()

    await _dizer(conn, grupo, ANUNCIO_SEM_VALOR.format(apelido=grupo.apelido), falas=falas)
    resposta = await _dizer(conn, grupo, APARTAMENTO, falas=falas, de=grupo.jid_da_modelo)

    assert resposta.motivo == "cadastro_atualizado"
    assert resposta.vendas == ()
    cur = await conn.execute(
        "SELECT count(*) AS n FROM barravips.vendas_registradas WHERE modelo_id = %s",
        (grupo.modelo_id,),
    )
    row = await cur.fetchone()
    assert row is not None and row["n"] == 0
    assert len(falas.enviadas) == 1  # so a pergunta minima do anuncio


# --- 7. a chave dela muda o que o agente enxerga no comprovante ---------------------------------


async def test_comprovante_para_a_chave_da_modelo_diz_de_quem_e_a_conta(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Sem o cadastro, o destino dela e so "fora da lista da casa"; com ele, o agente sabe de quem e.

    O comprovante deste teste nao mostra o TITULAR — e o caso em que so a chave cadastrada pode
    dizer de quem e a conta. Com ela cadastrada, um Pix do cliente para a conta dela deixa de ser
    "chave fora da lista, confere ai" e passa a ser o que e: dinheiro que entrou pra modelo, que
    nao abate venda nenhuma.
    """
    grupo = await _montar_grupo(conn)
    falas = _Falas()
    leitura = LeituraDoComprovante(
        e_comprovante=True,
        legivel=True,
        valor=Decimal("500.00"),
        data=None,
        pagador="Gabriel",
        chave_destino="+55 71 99984-0879",
        titular_destino=None,
    )

    sem_cadastro = await _dizer(
        conn,
        grupo,
        "",
        falas=falas,
        de=grupo.jid_da_modelo,
        olho=_Olho(leitura),
        tipo="imagem",
        imagem=ImagemDoGrupo(conteudo=b"imagem-de-teste", mimetype="image/jpeg"),
    )
    assert sem_cadastro.resposta is not None
    assert "fora da lista da casa" in sem_cadastro.resposta

    await _dizer(
        conn,
        grupo,
        "Minha chave pix é +5571999840879",
        falas=falas,
        de=grupo.jid_da_modelo,
    )
    com_cadastro = await _dizer(
        conn,
        grupo,
        "",
        falas=falas,
        de=grupo.jid_da_modelo,
        olho=_Olho(leitura),
        tipo="imagem",
        imagem=ImagemDoGrupo(conteudo=b"imagem-de-teste-2", mimetype="image/jpeg"),
    )

    assert com_cadastro.resposta is not None
    assert com_cadastro.motivo == "comprovante_entrada_da_modelo"
    assert "ENTROU pra modelo" in com_cadastro.resposta
    assert "fora da lista da casa" not in com_cadastro.resposta

    # A fronteira: quem pagou tambem foi ela. Nao e entrada — e um Pix dela para a conta dela, que
    # nao fecha nada com a casa e por isso continua merecendo o aviso (e o olho humano).
    dela_para_ela = await _dizer(
        conn,
        grupo,
        "",
        falas=falas,
        de=grupo.jid_da_modelo,
        olho=_Olho(replace(leitura, pagador="Yasmin Nascimento De Albuquerque")),
        tipo="imagem",
        imagem=ImagemDoGrupo(conteudo=b"imagem-de-teste-3", mimetype="image/jpeg"),
    )
    assert dela_para_ela.resposta is not None
    assert "chave da própria modelo" in dela_para_ela.resposta


async def test_o_atual_e_o_mais_recente_do_grupo_e_nao_o_ultimo_a_ser_gravado(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Duas observacoes entregues fora de ordem: vale o relogio do GRUPO.

    O campo nao guarda historia — quem responde "onde ela mora hoje" e o `ORDER BY observado_em
    DESC` do repo. Se `observado_em` fosse a hora do commit, a mensagem atrasada (o retry da
    Evolution) sobrescreveria o endereco novo pelo velho, calada, e o painel passaria a mostrar
    um apartamento onde a modelo nao esta mais.
    """
    grupo = await _montar_grupo(conn)
    falas = _Falas()

    # o endereco NOVO e dito primeiro (hoje); o antigo chega atrasado, dito ha tres dias
    hoje = grupo.relogio
    await _dizer(conn, grupo, APARTAMENTO_NOVO, falas=falas, de=grupo.jid_da_modelo)
    grupo.relogio = hoje - timedelta(days=3)
    atrasada = await _dizer(conn, grupo, APARTAMENTO, falas=falas, de=grupo.jid_da_modelo)

    assert atrasada.motivo == "cadastro_atualizado"  # e uma observacao legitima, so que velha
    atual = await dado_cadastral_atual(conn, grupo.modelo_id, "endereco_operacional")
    assert atual is not None
    assert atual.valor == APARTAMENTO_NOVO
