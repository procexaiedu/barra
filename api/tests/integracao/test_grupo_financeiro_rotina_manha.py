"""Rotina diaria da manha (spec 0005, ticket 10) — pela porta de RELOGIO do modulo.

O gesto real e o do export: a gestora anuncia a venda e volta dias depois para perguntar "Foi pix
ou din ?", venda por venda. Aqui isso vira UMA mensagem por grupo, uma vez por dia, de manha.

Os testes entram por onde a producao entra: `cobrar_pendencias_do_grupo` (o que o cron chama por
grupo) e `cobrar_pendencias_da_manha` (o worker inteiro, com a lista de grupos e a entrega). A
RESPOSTA do humano volta pela porta unica (`processar_mensagem_do_grupo`), que e exatamente o
combinado do ticket: a rotina so pergunta; quem resolve e o fluxo normal.

Relogio INJETADO em todo lugar, sem `sleep` nenhum — padrao dos workers de relogio da casa. O
unico teste que ancora no relogio real e o de "grupo parado", porque "sem movimento" e uma
afirmacao sobre `created_at`, que o banco escreve com `now()`: ali a rotina roda tres dias no
futuro em vez de o teste esperar tres dias.

`needs_db` com `TEST_DATABASE_URL` + ROLLBACK sempre.
"""

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from barra.agente_financeiro import (
    ResultadoDaPorta,
    cobrar_pendencias_do_grupo,
    processar_mensagem_do_grupo,
)
from barra.dominio.grupo_financeiro.modelos import GrupoFinanceiro, MensagemDoGrupo
from barra.settings import get_settings
from barra.workers.rotina_financeira import cobrar_pendencias_da_manha

pytestmark = pytest.mark.needs_db

ANUNCIO = "Atendimento no nosso local \nCliente {cliente} \nPerfil {apelido} \n{valor} 1h"

# 13/08 22:00 UTC = 13/08 19:00 em Brasilia (o grupo anuncia a venda no dia dela) e 14/08 11:00
# UTC = 14/08 08:00 BRT (a janela da manha em que o cron roda). Fixos: e a distancia entre os
# dois que faz a cobranca dizer "ontem".
NOITE_DE_ONTEM = datetime(2026, 8, 13, 22, 0, tzinfo=UTC)
MANHA = datetime(2026, 8, 14, 11, 0, tzinfo=UTC)


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


# --- o grupo -------------------------------------------------------------------------------------


class _Falas:
    """O que o agente postou no grupo. Coleta em vez de ir a rede."""

    def __init__(self) -> None:
        self.enviadas: list[str] = []

    async def __call__(self, texto: str, *, citar: str | None = None) -> None:
        self.enviadas.append(texto)

    @property
    def ultima(self) -> str | None:
        return self.enviadas[-1] if self.enviadas else None


class _EvolutionFalsa:
    """Entrega falsa: guarda (instance, jid, texto) em vez de falar com a Evolution."""

    def __init__(self) -> None:
        self.enviados: list[dict[str, Any]] = []

    async def enviar_texto_avulso(self, **kw: Any) -> str:
        self.enviados.append(kw)
        return f"3EB0{uuid4().hex[:12]}"


class _Grupo:
    def __init__(self, modelo_id: UUID, grupo_id: UUID, jid: str, apelido: str) -> None:
        self.modelo_id = modelo_id
        self.id = grupo_id
        self.jid = jid
        self.apelido = apelido
        self.relogio = NOITE_DE_ONTEM

    def como_cadastro(self) -> GrupoFinanceiro:
        return GrupoFinanceiro(id=self.id, modelo_id=self.modelo_id, jid=self.jid, nome="")


async def _montar_grupo(c: AsyncConnection[dict[str, Any]], *, ativo: bool = True) -> _Grupo:
    """Um Grupo financeiro novo (modelo + Nome de anuncio + vinculo closed-world)."""
    modelo_id = uuid4()
    apelido = f"bianca{uuid4().hex[:8]}"
    await c.execute(
        """
        INSERT INTO barravips.modelos
            (id, nome, idade, numero_whatsapp, valor_padrao, tipo_atendimento_aceito,
             percentual_repasse, status)
        VALUES (%s, %s, %s, %s, %s, %s::barravips.tipo_atendimento_enum[], %s,
                'ativa'::barravips.modelo_status_enum)
        """,
        (
            modelo_id,
            f"Yasmin {uuid4().hex[:6]}",
            25,
            f"test-wpp-{uuid4().hex}",
            600,
            ["interno"],
            Decimal("40"),
        ),
    )
    await c.execute(
        """
        INSERT INTO barravips.modelo_nomes_anuncio (modelo_id, nome, nome_normalizado)
        VALUES (%s, %s, %s)
        """,
        (modelo_id, apelido, apelido),
    )
    grupo_id = uuid4()
    jid = f"1203634{uuid4().hex[:12]}@g.us"
    await c.execute(
        """
        INSERT INTO barravips.grupos_financeiros (id, modelo_id, jid, nome, ativo)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (grupo_id, modelo_id, jid, "Modelo Yasmin Ruiva/financeiro", ativo),
    )
    return _Grupo(modelo_id, grupo_id, jid, apelido)


async def _dizer(
    c: AsyncConnection[dict[str, Any]],
    grupo: _Grupo,
    texto: str,
    *,
    falas: _Falas,
    depois: timedelta = timedelta(minutes=1),
    **kw: Any,
) -> ResultadoDaPorta:
    """Um humano digita no grupo — pela porta unica, como a producao."""
    grupo.relogio += depois
    kw.setdefault("evolution_message_id", f"3EB0{uuid4().hex[:12]}")
    kw.setdefault("autor_nome", "Dani")
    kw.setdefault("autor_jid", "5521999999999@s.whatsapp.net")
    msg = MensagemDoGrupo(grupo_jid=grupo.jid, texto=texto, recebida_em=grupo.relogio, **kw)
    return await processar_mensagem_do_grupo(c, msg, enviar=falas)


async def _vender(
    c: AsyncConnection[dict[str, Any]],
    grupo: _Grupo,
    *,
    cliente: str,
    valor: str,
    forma: str | None = None,
    falas: _Falas,
) -> tuple[UUID, str]:
    """Um anuncio de venda (e, quando dita, a forma). Devolve (venda_id, id da mensagem)."""
    message_id = f"3EB0{uuid4().hex[:12]}"
    lancou = await _dizer(
        c,
        grupo,
        ANUNCIO.format(cliente=cliente, apelido=grupo.apelido, valor=valor),
        falas=falas,
        evolution_message_id=message_id,
    )
    (venda_id,) = lancou.vendas
    if forma is not None:
        pago = await _dizer(
            c,
            grupo,
            "Pix" if forma == "pix" else "Dinheiro",
            falas=falas,
            quoted_message_id=message_id,
        )
        assert pago.pagamentos == (venda_id,)
    return venda_id, message_id


async def _forma_da_venda(c: AsyncConnection[dict[str, Any]], venda_id: UUID) -> str | None:
    cur = await c.execute(
        "SELECT forma_pagamento FROM barravips.vendas_registradas WHERE id = %s", (venda_id,)
    )
    row = await cur.fetchone()
    assert row is not None
    return row["forma_pagamento"]


async def _falas_da_rotina(c: AsyncConnection[dict[str, Any]], grupo: _Grupo) -> list[str]:
    """As linhas que a rotina deixou no log de origem — a prova de "no maximo UMA por dia"."""
    cur = await c.execute(
        """
        SELECT texto FROM barravips.grupo_financeiro_mensagens
         WHERE grupo_id = %s AND chave_dedup LIKE 'rotina:%%'
         ORDER BY recebida_em
        """,
        (grupo.id,),
    )
    return [row["texto"] for row in await cur.fetchall()]


# --- 1. a cobranca consolidada: uma mensagem com as pendencias e o saldo -------------------------


async def test_uma_mensagem_cobra_as_pendencias_e_posta_o_saldo(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Duas pendencias de naturezas diferentes viram UMA fala — nao uma pergunta por venda."""
    grupo = await _montar_grupo(conn)
    falas = _Falas()
    gabriel, _ = await _vender(conn, grupo, cliente="Gabriel", valor="700", falas=falas)
    ramon, _ = await _vender(conn, grupo, cliente="Ramon", valor="600", forma="pix", falas=falas)
    ditas_antes = len(falas.enviadas)

    rotina = await cobrar_pendencias_do_grupo(
        conn, grupo.como_cadastro(), agora=MANHA, enviar=falas
    )

    assert rotina.status == "cobrou"
    assert len(falas.enviadas) == ditas_antes + 1, "a cobranca da manha e UMA mensagem"
    fala = falas.ultima
    assert fala is not None
    # A venda sem forma vai NOMEADA (e o que faz a resposta achar a venda certa)...
    assert "Cliente Gabriel · R$ 700,00 · ontem — foi pix ou dinheiro?" in fala
    # ...e a de comprovante vai agregada (a resposta dela e uma foto, e o abate e FIFO).
    assert "📸 Falta o comprovante de R$ 600,00 (1 venda em pix)." in fala
    assert "📊 Em aberto: R$ 1.300,00 de R$ 1.300,00 vendidos (R$ 0,00 já comprovados)." in fala
    assert {(p.venda_id, p.tipo) for p in rotina.pendencias} == {
        (gabriel, "forma_pagamento"),
        (ramon, "comprovante"),
    }
    assert await _falas_da_rotina(conn, grupo) == [fala]


async def test_muitas_pendencias_nomeia_as_RECENTES_e_resume_as_antigas(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Consolidada quer dizer legivel, nao completa: seis pendencias nao viram seis perguntas.

    E as nomeadas sao as MAIS RECENTES. A fila de forma de pagamento nao anda sozinha (a venda
    fica aberta ate alguem falar), entao nomear as mais antigas faria o agente repetir a mesma
    mensagem todas as manhas — as quatro vendas que ninguem respondeu — enquanto a de ontem, a
    unica que a gestora ainda lembra, sumia no resumo.

    O que sobra do teto nao some: vira uma linha com quantas, DE QUANDO e quanto, e continua sendo
    cobrado amanha (a pendencia e derivada da venda, nao consumida pela cobranca).
    """
    grupo = await _montar_grupo(conn)
    falas = _Falas()
    for i, cliente in enumerate(("Gabriel", "Igor", "Lucas", "Ramon", "Erick", "Tiago")):
        await _vender(conn, grupo, cliente=cliente, valor=str(100 + i), falas=falas)

    rotina = await cobrar_pendencias_do_grupo(
        conn, grupo.como_cadastro(), agora=MANHA, enviar=falas
    )

    fala = rotina.fala
    assert fala is not None
    assert fala.count("foi pix ou dinheiro?") == 4
    # As quatro ULTIMAS anunciadas vao nomeadas; as duas primeiras viram resumo.
    assert "Cliente Tiago" in fala and "Cliente Erick" in fala
    assert "Cliente Gabriel" not in fala and "Cliente Igor" not in fala
    # 100 + 101: o que ficou de fora aparece somado e datado, nunca escondido.
    assert "❓ E mais 2 vendas sem forma de pagamento de ontem (R$ 201,00)." in fala


async def test_o_resumo_diz_de_quando_sao_as_vendas_que_sobraram(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """O caso do export: a divida velha e a de ontem na mesma manha.

    "E mais 2 vendas" sem data e um numero sem tempo — a gestora nao consegue decidir se aquilo e
    coisa de ontem (responde agora) ou pendencia de uma semana (resolve no painel). Com a janela,
    a mesma linha diz as duas coisas.
    """
    grupo = await _montar_grupo(conn)
    falas = _Falas()
    # Duas vendas antigas (dias diferentes) e quatro recentes, que ocupam as nomeadas.
    grupo.relogio -= timedelta(days=5)
    await _vender(conn, grupo, cliente="Gabriel", valor="100", falas=falas)
    grupo.relogio += timedelta(days=2)
    await _vender(conn, grupo, cliente="Igor", valor="101", falas=falas)
    grupo.relogio += timedelta(days=3)
    for i, cliente in enumerate(("Lucas", "Ramon", "Erick", "Tiago")):
        await _vender(conn, grupo, cliente=cliente, valor=str(102 + i), falas=falas)

    rotina = await cobrar_pendencias_do_grupo(
        conn, grupo.como_cadastro(), agora=MANHA, enviar=falas
    )

    fala = rotina.fala
    assert fala is not None
    assert "❓ E mais 2 vendas sem forma de pagamento de 08/08 a 10/08 (R$ 201,00)." in fala


# --- 2. silencio e o default ---------------------------------------------------------------------


async def test_grupo_sem_pendencia_e_sem_movimento_fica_em_silencio(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Grupo parado nao recebe "bom dia".

    A rotina roda TRES DIAS depois do movimento (relogio injetado no futuro) em vez de o teste
    esperar: "sem movimento" e uma afirmacao sobre quando o registro nasceu, e quem escreve isso
    e o `now()` do banco.
    """
    grupo = await _montar_grupo(conn)
    falas = _Falas()
    # Venda em dinheiro: conta no vendido, fica em especie com a modelo e NAO gera pendencia.
    await _vender(conn, grupo, cliente="Igor", valor="900", forma="dinheiro", falas=falas)
    ditas_antes = len(falas.enviadas)

    daqui_a_tres_dias = datetime.now(UTC) + timedelta(days=3)
    rotina = await cobrar_pendencias_do_grupo(
        conn, grupo.como_cadastro(), agora=daqui_a_tres_dias, enviar=falas
    )

    assert rotina.status == "silencio"
    assert rotina.fala is None
    assert len(falas.enviadas) == ditas_antes
    assert await _falas_da_rotina(conn, grupo) == []


async def test_grupo_vazio_nunca_fala(conn: AsyncConnection[dict[str, Any]]) -> None:
    """Nenhuma venda, nenhum comprovante: a rotina passa reto pelo grupo."""
    grupo = await _montar_grupo(conn)
    falas = _Falas()

    rotina = await cobrar_pendencias_do_grupo(
        conn, grupo.como_cadastro(), agora=MANHA, enviar=falas
    )

    assert rotina.status == "silencio"
    assert falas.enviadas == []


async def test_movimento_sem_pendencia_posta_so_o_saldo(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Houve dinheiro e nada a cobrar: uma linha fechando o dia, sem cobranca nenhuma."""
    grupo = await _montar_grupo(conn)
    falas = _Falas()
    await _vender(conn, grupo, cliente="Igor", valor="900", forma="dinheiro", falas=falas)

    rotina = await cobrar_pendencias_do_grupo(
        conn, grupo.como_cadastro(), agora=MANHA, enviar=falas
    )

    assert rotina.status == "cobrou"
    assert rotina.fala == "☀️ Bom dia! Ontem: 1 venda (R$ 900,00) — tudo conciliado por aqui."
    assert "foi pix ou dinheiro?" not in (rotina.fala or "")


# --- 3. a resposta do humano cai no fluxo normal e atinge a venda certa --------------------------


async def test_resposta_a_cobranca_resolve_a_pendencia_pela_porta_unica(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """ "Pix" respondido de manha vira forma de pagamento da venda cobrada — sem nada novo.

    A cobranca da manha entra no log como mensagem do agente, e e ela que o contexto le: e por
    isso que a resposta acha a venda mesmo tendo sido dada um dia depois do anuncio.
    """
    grupo = await _montar_grupo(conn)
    falas = _Falas()
    gabriel, _ = await _vender(conn, grupo, cliente="Gabriel", valor="700", falas=falas)
    igor, _ = await _vender(conn, grupo, cliente="Igor", valor="900", forma="dinheiro", falas=falas)

    await cobrar_pendencias_do_grupo(conn, grupo.como_cadastro(), agora=MANHA, enviar=falas)
    grupo.relogio = MANHA
    respondeu = await _dizer(conn, grupo, "Pix", falas=falas, depois=timedelta(minutes=4))

    assert respondeu.motivo == "pagamento_absorvido"
    assert respondeu.pagamentos == (gabriel,)
    assert await _forma_da_venda(conn, gabriel) == "pix"
    # A venda que ja tinha forma nao foi tocada pela resposta.
    assert await _forma_da_venda(conn, igor) == "dinheiro"


async def test_duas_pendencias_a_resposta_citada_atinge_so_a_venda_citada(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Com duas vendas cobradas na mesma mensagem, um "Pix" solto NAO escreve nada.

    Marcar a venda errada e o erro que nunca mais e descoberto (ela some do Fechamento e ninguem
    a cobra de novo), entao o modulo prefere a pendencia viva — e, como a forma ja foi dita,
    devolve a pergunta de desempate em vez de calar. Quem fecha a conta e o gesto que o grupo ja
    usa: responder CITANDO o anuncio.
    """
    grupo = await _montar_grupo(conn)
    falas = _Falas()
    gabriel, _ = await _vender(conn, grupo, cliente="Gabriel", valor="700", falas=falas)
    igor, anuncio_do_igor = await _vender(conn, grupo, cliente="Igor", valor="900", falas=falas)

    cobranca = await cobrar_pendencias_do_grupo(
        conn, grupo.como_cadastro(), agora=MANHA, enviar=falas
    )
    assert cobranca.fala is not None
    assert "Cliente Gabriel" in cobranca.fala and "Cliente Igor" in cobranca.fala

    grupo.relogio = MANHA
    solto = await _dizer(conn, grupo, "Pix", falas=falas, depois=timedelta(minutes=3))
    assert solto.motivo == "pagamento_ambiguo"
    assert solto.resposta is not None
    assert "Gabriel" in solto.resposta and "Igor" in solto.resposta
    assert await _forma_da_venda(conn, gabriel) is None
    assert await _forma_da_venda(conn, igor) is None

    citou = await _dizer(
        conn,
        grupo,
        "Pix",
        falas=falas,
        depois=timedelta(minutes=2),
        quoted_message_id=anuncio_do_igor,
    )
    assert citou.pagamentos == (igor,)
    assert await _forma_da_venda(conn, igor) == "pix"
    assert await _forma_da_venda(conn, gabriel) is None, "a venda nao citada continua pendente"


# --- 4. idempotencia: uma fala por grupo por dia, mesmo com retry/redeploy -----------------------


async def test_reexecucao_no_mesmo_dia_nao_duplica_a_cobranca(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Segundo disparo do dia (retry do cron, redeploy do worker) nao fala de novo — e no dia
    seguinte a pendencia que ficou aberta volta a ser cobrada."""
    grupo = await _montar_grupo(conn)
    falas = _Falas()
    await _vender(conn, grupo, cliente="Gabriel", valor="700", falas=falas)

    primeira = await cobrar_pendencias_do_grupo(
        conn, grupo.como_cadastro(), agora=MANHA, enviar=falas
    )
    ditas = len(falas.enviadas)
    segunda = await cobrar_pendencias_do_grupo(
        conn, grupo.como_cadastro(), agora=MANHA + timedelta(hours=2), enviar=falas
    )

    assert primeira.status == "cobrou"
    assert segunda.status == "ja_falou"
    assert segunda.fala is None
    assert len(falas.enviadas) == ditas
    assert len(await _falas_da_rotina(conn, grupo)) == 1

    amanha = await cobrar_pendencias_do_grupo(
        conn, grupo.como_cadastro(), agora=MANHA + timedelta(days=1), enviar=falas
    )
    assert amanha.status == "cobrou"
    assert amanha.fala is not None and "Cliente Gabriel" in amanha.fala
    assert len(await _falas_da_rotina(conn, grupo)) == 2


# --- 5. o worker: a lista de grupos e a entrega pela instancia da ProceX -------------------------


def _settings(**over: Any) -> Any:
    return get_settings().model_copy(
        update={
            "grupo_financeiro_rotina_ativa": True,
            "grupo_financeiro_instancia": "procex",
            # A rotina inteira e sobre FALAR; o default de producao e o modo so escuta, entao
            # todo teste daqui que espera mensagem tem que ligar a boca explicitamente.
            "grupo_financeiro_responde": True,
            **over,
        }
    )


async def test_worker_cobra_o_grupo_ativo_pela_instancia_da_procex(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """O cron varre os grupos ATIVOS e entrega pelo numero da ProceX, nao pelo da modelo.

    O grupo desligado tem pendencia de verdade (a venda foi anunciada quando ele ainda estava
    ativo): inativar tem que calar a FALA tambem, nao so a ingestao — senao o agente seguiria
    cobrando num grupo de onde a operacao o tirou.
    """
    grupo = await _montar_grupo(conn)
    desligado = await _montar_grupo(conn)
    falas = _Falas()
    await _vender(conn, grupo, cliente="Gabriel", valor="700", falas=falas)
    await _vender(conn, desligado, cliente="Ramon", valor="600", falas=falas)
    await conn.execute(
        "UPDATE barravips.grupos_financeiros SET ativo = false WHERE id = %s", (desligado.id,)
    )
    evolution = _EvolutionFalsa()

    cobrados = await cobrar_pendencias_da_manha(conn, evolution, _settings(), agora=MANHA)

    assert cobrados >= 1
    meus = [e for e in evolution.enviados if e["remote_jid"] == grupo.jid]
    assert len(meus) == 1
    assert meus[0]["instance_id"] == "procex"
    assert "Cliente Gabriel" in meus[0]["texto"]
    assert [e for e in evolution.enviados if e["remote_jid"] == desligado.jid] == []


async def test_worker_desligado_nao_toca_em_nada(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Kill-switch e instancia vazia: os dois calam a rotina inteira antes de qualquer leitura."""
    evolution = _EvolutionFalsa()

    assert (
        await cobrar_pendencias_da_manha(
            conn, evolution, _settings(grupo_financeiro_rotina_ativa=False), agora=MANHA
        )
        == 0
    )
    assert (
        await cobrar_pendencias_da_manha(
            conn, evolution, _settings(grupo_financeiro_instancia=""), agora=MANHA
        )
        == 0
    )
    assert (
        await cobrar_pendencias_da_manha(
            conn, evolution, _settings(grupo_financeiro_responde=False), agora=MANHA
        )
        == 0
    )
    assert evolution.enviados == []


async def test_modo_so_escuta_nao_queima_a_reserva_do_dia(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Calada, a rotina nao pode CONSUMIR o dia do grupo.

    `reservar_fala_da_rotina` existe para o grupo nao ser cobrado duas vezes no mesmo dia. Se a
    rotina rodasse muda e ainda assim reservasse, o dia em que a boca fosse ligada encontraria a
    reserva ja gasta e o grupo ficaria calado — um silencio que ninguem pediu e que so apareceria
    24h depois. Por isso o corte e ANTES de qualquer leitura, e nao um `enviar` no-op la dentro.
    """
    grupo = await _montar_grupo(conn)
    falas = _Falas()
    await _vender(conn, grupo, cliente="Gabriel", valor="700", falas=falas)
    evolution = _EvolutionFalsa()

    calado = await cobrar_pendencias_da_manha(
        conn, evolution, _settings(grupo_financeiro_responde=False), agora=MANHA
    )
    assert calado == 0
    assert evolution.enviados == []

    # Mesmo dia, mesma pendencia, boca ligada: a cobranca sai — prova de que a passada muda nao
    # gastou a reserva.
    cobrados = await cobrar_pendencias_da_manha(conn, evolution, _settings(), agora=MANHA)
    assert cobrados == 1
    assert [e["remote_jid"] for e in evolution.enviados] == [grupo.jid]
