"""F4.3 -- jornada E2E que vira `Perdido (sumiu)` por timeout como continuacao E2E.

Hoje toda jornada do sim fecha (foto de portaria -> Em_execucao -> Fechado pela F4.2) ou avanca por
Pix (Confirmado): o ramo "NAO VOLTA" -- o cliente avisa que saiu, SOME e nunca chega -- nunca era
percorrido pela propria jornada. Esse desfecho NAO e um turno da IA nem um ato do cliente: e o
TIMEOUT determinista de 45 min (`aplicar_timeout_interno`, workers/timeouts.py) que varre o interno em
`Aguardando_confirmacao` com aviso de saida vencido e sem foto de portaria -> `Perdido`, motivo
`sumiu`, bloqueio cancelado. Este gate tranca a existencia de uma jornada graduada que chega ate o
aviso de saida e SOME, e a prova de que o ato de timeout pos-loop leva `Aguardando_confirmacao ->
Perdido (sumiu)` com todos os efeitos.

Duas metades, espelhando o padrao do roadmap (F0.x/F1.x/F4.1/F4.2):

- **Estrutural (PURO, sem DB/LLM)** -- roda no `make test`: ao menos um `Cenario` (e um `CenarioFixo`)
  declara `timeout_sumiu = True` e e uma jornada graduada do ramo "nao volta" (o roteiro envia o aviso
  de saida e depois SOME -- `ficar_em_silencio` -- e NUNCA manda a foto de portaria). Gate de PR.

- **Espinha (needs_db)** -- roda no Postgres efemero do CI (pos-F0.1): semeia um interno em
  `Aguardando_confirmacao` com aviso de saida (e bloqueio `bloqueado`) pela MESMA porta que
  `sim/loop.py:jornada` usa (`runner._seed_entidades`) e aplica o EXATO ato de timeout que o `jornada`
  dispara pos-loop (`loop._aplicar_ato(..., "cliente_some_timeout")` -> `aplicar_timeout_interno`),
  provando `Aguardando_confirmacao -> Perdido` + motivo `sumiu` + bloqueio cancelado. E "pela conversa"
  menos o LLM conduzir ate o aviso de saida -- essa metade (grafo real + Sonnet ate o aviso, depois o
  silencio que vira timeout) e a parte ★API.
"""

import importlib
import importlib.util
import os
import sys
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio

_API = Path(__file__).resolve().parents[2]  # api/
if str(_API) not in sys.path:
    sys.path.insert(0, str(_API))

cenarios = importlib.import_module("evals.sim.cenarios")
cenarios_fixos = importlib.import_module("evals.sim.cenarios_fixos")
loop = importlib.import_module("evals.sim.loop")

_RUNNERS = _API / "evals" / "runners"


def _cenarios_some() -> list[Any]:
    return [c for c in cenarios.CENARIOS if getattr(c, "timeout_sumiu", False)]


def _fixos_some() -> list[Any]:
    return [c for c in cenarios_fixos.todos_fixos() if getattr(c, "timeout_sumiu", False)]


def _roteiro_envia_aviso_e_some(cen: Any) -> bool:
    """O roteiro do cenario dispara o aviso de saida E depois SOME (ficar_em_silencio) e NUNCA manda
    a foto de portaria -- prova de que e o ramo "nao volta" graduado, nao um Perdido do nada."""
    if cen.decidir_ato is None:
        return False
    avisou = somiu = False
    for indice in range(cen.max_turnos + 2):
        ato = cen.decidir_ato(indice, {"estado": "Aguardando_confirmacao", "ia_pausada": False})
        if ato == "enviar_foto_portaria":
            return False  # chegou -> nao e o ramo "nao volta"
        if ato == "enviar_aviso_saida":
            avisou = True
        if ato == "ficar_em_silencio":
            somiu = True
    return avisou and somiu


# --- estrutural (PURO) -------------------------------------------------------------------------


def test_existe_jornada_persona_que_some():
    # anti-vacuo: o conjunto E2E nao esta vazio -- senao "nenhuma some" seria verde-vazio.
    assert cenarios.CENARIOS, "CENARIOS vazio"
    some = _cenarios_some()
    assert some, (
        "nenhum Cenario (persona) some por timeout (timeout_sumiu) -- F4.3 exige o ramo Perdido"
    )


def test_existe_jornada_fixa_que_some():
    assert cenarios_fixos.todos_fixos(), "conjunto fixo vazio"
    some = _fixos_some()
    assert some, (
        "nenhum CenarioFixo some por timeout (timeout_sumiu) -- F4.3 exige o ramo fixo Perdido"
    )


def test_persona_que_some_avisa_e_some_sem_chegar():
    # o timeout (Aguardando_confirmacao -> Perdido) so faz sentido apos o aviso de saida e o silencio
    # subsequente; uma jornada que "some" sem avisar (ou que chega pela portaria) seria outro ramo.
    for cen in _cenarios_some():
        assert _roteiro_envia_aviso_e_some(cen), (
            f"{cen.nome}: timeout_sumiu=True mas o roteiro nao avisa-e-some sem chegar pela portaria"
        )


def test_fixo_que_some_avisa_e_some_e_tem_primeira_fala():
    for cen in _fixos_some():
        assert cen.mensagens_cliente and cen.mensagens_cliente[0].strip(), (
            f"{cen.nome}: jornada fixa que some sem 1a fala de cliente"
        )
        assert _roteiro_envia_aviso_e_some(cen), (
            f"{cen.nome}: timeout_sumiu=True mas o roteiro nao avisa-e-some sem chegar pela portaria"
        )


# --- espinha (needs_db): o ato de timeout leva Aguardando_confirmacao -> Perdido(sumiu) ----------


def _carregar_runner() -> Any:
    """Carrega runner.py por caminho (evals/ fora do pacote `barra`) -- igual a sim/loop.py."""
    caminho = _RUNNERS / "runner.py"
    spec = importlib.util.spec_from_file_location("eval_runner_f4_3", caminho)
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("eval_runner_f4_3", modulo)
    spec.loader.exec_module(modulo)
    return modulo


@pytest_asyncio.fixture
async def conn() -> AsyncIterator[Any]:
    from psycopg import AsyncConnection
    from psycopg.rows import dict_row

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


async def _ler_atendimento(conn: Any, atendimento_id: UUID) -> dict[str, Any]:
    res = await conn.execute(
        """
        SELECT estado::text AS estado, motivo_perda::text AS motivo_perda,
               fonte_decisao_ultima_transicao::text AS fonte, ia_pausada
          FROM barravips.atendimentos WHERE id = %s
        """,
        (atendimento_id,),
    )
    row = await res.fetchone()
    assert row is not None
    return row


async def _estado_bloqueio(conn: Any, bloqueio_id: UUID) -> str:
    res = await conn.execute(
        "SELECT estado::text AS estado FROM barravips.bloqueios WHERE id = %s", (bloqueio_id,)
    )
    row = await res.fetchone()
    assert row is not None
    return str(row["estado"])


async def _seed_bloqueio_bloqueado(conn: Any, *, modelo_id: UUID, atendimento_id: UUID) -> UUID:
    """Bloqueio vinculado do horario combinado, ainda `bloqueado` (a modelo nao iniciou o
    atendimento, porque o cliente sumiu) -- o timeout deve cancela-lo (espelha test_timeout_interno)."""
    bloqueio_id = uuid4()
    inicio = datetime.now(UTC) + timedelta(hours=2)
    await conn.execute(
        """
        INSERT INTO barravips.bloqueios (id, modelo_id, atendimento_id, inicio, fim, estado, origem)
        VALUES (%s, %s, %s, %s, %s, 'bloqueado'::barravips.estado_bloqueio_enum,
                'ia'::barravips.origem_bloqueio_enum)
        """,
        (bloqueio_id, modelo_id, atendimento_id, inicio, inicio + timedelta(hours=1)),
    )
    await conn.execute(
        "UPDATE barravips.atendimentos SET bloqueio_id = %s WHERE id = %s",
        (bloqueio_id, atendimento_id),
    )
    return bloqueio_id


@pytest.mark.needs_db
async def test_ato_de_timeout_leva_aguardando_para_perdido_sumiu(conn: Any):
    """A jornada chega em `Aguardando_confirmacao` (interno, com aviso de saida) e SOME; o ato de
    timeout pos-loop (`cliente_some_timeout`) -- que envelhece o aviso e dispara o MESMO cron de prod
    (`aplicar_timeout_interno`) -- leva `Aguardando_confirmacao -> Perdido` com motivo `sumiu` e
    bloqueio cancelado, provado no Postgres real."""
    runner = _carregar_runner()
    # semeia pela MESMA porta que o jornada usa, no estado/tipo de onde o timeout dispara.
    fixture_seed = {
        "estado_inicial": {
            "atendimento_estado": "Aguardando_confirmacao",
            "tipo_atendimento": "interno",
        }
    }
    modelo_id, atendimento_id, _cliente_id, _conversa_id = await runner._seed_entidades(
        conn, fixture_seed
    )
    bloqueio_id = await _seed_bloqueio_bloqueado(
        conn, modelo_id=modelo_id, atendimento_id=atendimento_id
    )
    # simula que o aviso de saida ja foi enviado na jornada (o ato `enviar_aviso_saida` seta now()).
    await conn.execute(
        "UPDATE barravips.atendimentos SET aviso_saida_em = now() WHERE id = %s",
        (atendimento_id,),
    )

    # 1) pre-condicao: interno em Aguardando_confirmacao, aviso enviado, sem foto, bloqueio bloqueado.
    antes = await _ler_atendimento(conn, atendimento_id)
    assert antes["estado"] == "Aguardando_confirmacao"
    assert antes["motivo_perda"] is None
    assert await _estado_bloqueio(conn, bloqueio_id) == "bloqueado"

    # 2) o ato de timeout da jornada (cliente sumiu, 45 min vencidos) -> Perdido (sumiu).
    await loop._aplicar_ato(conn, atendimento_id, "cliente_some_timeout")

    depois = await _ler_atendimento(conn, atendimento_id)
    assert depois["estado"] == "Perdido"
    assert depois["motivo_perda"] == "sumiu"
    assert depois["fonte"] == "auto_timeout_interno"
    # bloqueio vinculado cancelado pela CTE do timeout (CONTEXT.md "Bloqueio").
    assert await _estado_bloqueio(conn, bloqueio_id) == "cancelado"
