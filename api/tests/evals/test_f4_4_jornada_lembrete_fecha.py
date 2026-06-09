"""F4.4 -- jornada E2E que chega a `Fechado` pela COBRANCA PROATIVA do Valor final (Lembrete de
fechamento) dentro de uma jornada.

A F4.2 ja chega a `Fechado`, mas pelo fecho ESPONTANEO da modelo (`modelo_fecha_card`): a modelo,
por conta propria, responde o card com o Valor final. A F4.4 fecha o OUTRO caminho do mesmo desfecho
-- o que CONTEXT.md/ADR-0009 chamam de "Lembrete de fechamento": passado o fim do atendimento e
ainda em `Em_execucao`, o cron `cobrar_valor_final` (workers/lembrete_valor.py, provado isolado na
F0.9) cobra PROATIVAMENTE o Valor final mandando um card no grupo de Coordenacao; a modelo responde
ESSE card com o valor -> `Fechado`. O fecho vem em RESPOSTA a cobranca do sistema, nao de um impulso
da modelo. Este gate tranca a existencia de uma jornada de interno COMPLETA que fecha pela cobranca
proativa e a prova de que o ato pos-loop dispara o lembrete real E leva `Em_execucao -> Fechado`.

Duas metades, espelhando o padrao do roadmap (F0.x/F1.x/F4.1/F4.2/F4.3):

- **Estrutural (PURO, sem DB/LLM)** -- roda no `make test`: ao menos um `Cenario` (e um `CenarioFixo`)
  declara `cobrar_e_fechar = True` e e uma jornada de interno COMPLETA (o roteiro alcanca `Em_execucao`
  pela foto de portaria antes do fecho) -- nao um fecho do nada. Gate de PR de verdade.

- **Espinha (needs_db)** -- roda no Postgres efemero do CI (pos-F0.1): semeia um atendimento em
  `Em_execucao` com bloqueio `em_atendimento` pela MESMA porta que `sim/loop.py:jornada` usa
  (`runner._seed_entidades`) e aplica o EXATO ato pos-loop que o `jornada` dispara
  (`loop._aplicar_ato(..., "lembrete_cobra_e_fecha")`), provando que (a) a cobranca proativa
  disparou -- um card `lembrete_valor` foi enviado pelo cron real `cobrar_valor_final` -- e (b) a
  resposta da modelo a esse card leva `Em_execucao -> Fechado` + Valor final + bloqueio concluido +
  IA despausada. E "pela conversa" menos o LLM conduzir a venda ate a portaria -- essa metade (grafo
  real + Sonnet ate Em_execucao, depois o lembrete + fecho) e a parte ★API.
"""

import importlib
import importlib.util
import os
import sys
from collections.abc import AsyncIterator
from decimal import Decimal
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


def _cenarios_cobra() -> list[Any]:
    return [c for c in cenarios.CENARIOS if getattr(c, "cobrar_e_fechar", False)]


def _fixos_cobra() -> list[Any]:
    return [c for c in cenarios_fixos.todos_fixos() if getattr(c, "cobrar_e_fechar", False)]


def _roteiro_alcanca_em_execucao(cen: Any) -> bool:
    """O roteiro do cenario dispara a foto de portaria em Aguardando_confirmacao (=> Em_execucao)
    em algum passo -- prova de que e uma jornada de interno COMPLETA, nao um fecho do nada."""
    if cen.decidir_ato is None:
        return False
    for indice in range(cen.max_turnos + 2):
        ato = cen.decidir_ato(indice, {"estado": "Aguardando_confirmacao", "ia_pausada": False})
        if ato == "enviar_foto_portaria":
            return True
    return False


# --- estrutural (PURO) -------------------------------------------------------------------------


def test_existe_jornada_persona_que_cobra_e_fecha():
    # anti-vacuo: o conjunto E2E nao esta vazio -- senao "nenhuma cobra" seria verde-vazio.
    assert cenarios.CENARIOS, "CENARIOS vazio"
    cobra = _cenarios_cobra()
    assert cobra, (
        "nenhum Cenario (persona) fecha pela cobranca proativa (cobrar_e_fechar) -- F4.4 exige a "
        "jornada que fecha pelo Lembrete de fechamento"
    )


def test_existe_jornada_fixa_que_cobra_e_fecha():
    assert cenarios_fixos.todos_fixos(), "conjunto fixo vazio"
    cobra = _fixos_cobra()
    assert cobra, (
        "nenhum CenarioFixo fecha pela cobranca proativa (cobrar_e_fechar) -- F4.4 exige a jornada "
        "fixa que fecha pelo Lembrete de fechamento"
    )


def test_persona_que_cobra_alcanca_em_execucao_antes_do_fecho():
    # o lembrete (cobra o valor final em Em_execucao) so faz sentido apos a jornada chegar em
    # Em_execucao pela foto de portaria; uma jornada que "cobra" sem percorrer o interno seria um
    # fecho do nada.
    for cen in _cenarios_cobra():
        assert _roteiro_alcanca_em_execucao(cen), (
            f"{cen.nome}: cobrar_e_fechar=True mas o roteiro nunca alcanca Em_execucao pela portaria"
        )


def test_fixo_que_cobra_alcanca_em_execucao_e_tem_primeira_fala():
    for cen in _fixos_cobra():
        assert cen.mensagens_cliente and cen.mensagens_cliente[0].strip(), (
            f"{cen.nome}: jornada fixa que cobra sem 1a fala de cliente"
        )
        assert _roteiro_alcanca_em_execucao(cen), (
            f"{cen.nome}: cobrar_e_fechar=True mas o roteiro nunca alcanca Em_execucao pela portaria"
        )


# --- espinha (needs_db): o lembrete cobra e o fecho leva Em_execucao -> Fechado ------------------


def _carregar_runner() -> Any:
    """Carrega runner.py por caminho (evals/ fora do pacote `barra`) -- igual a sim/loop.py."""
    caminho = _RUNNERS / "runner.py"
    spec = importlib.util.spec_from_file_location("eval_runner_f4_4", caminho)
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("eval_runner_f4_4", modulo)
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
        SELECT estado::text AS estado, valor_final, ia_pausada,
               ia_pausada_motivo::text AS ia_pausada_motivo
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


async def _cards_lembrete(conn: Any, atendimento_id: UUID) -> int:
    """Quantos cards de Lembrete de fechamento (`card_kind=lembrete_valor`) o cron enviou para o
    atendimento -- a marca da cobranca proativa em `envios_evolution`."""
    from barra.workers.lembrete_valor import CARD_KIND

    res = await conn.execute(
        """
        SELECT count(*) AS n FROM barravips.envios_evolution
         WHERE atendimento_id = %s AND payload->>'card_kind' = %s
        """,
        (atendimento_id, CARD_KIND),
    )
    row = await res.fetchone()
    assert row is not None
    return int(row["n"])


async def _seed_bloqueio_em_atendimento(
    conn: Any, *, modelo_id: UUID, atendimento_id: UUID
) -> UUID:
    """Bloqueio vinculado em curso (em_atendimento), como num atendimento Em_execucao (espelha F0.8)."""
    from datetime import UTC, datetime, timedelta

    bloqueio_id = uuid4()
    inicio = datetime.now(UTC) - timedelta(minutes=30)
    await conn.execute(
        """
        INSERT INTO barravips.bloqueios (id, modelo_id, atendimento_id, inicio, fim, estado, origem)
        VALUES (%s, %s, %s, %s, %s, 'em_atendimento'::barravips.estado_bloqueio_enum,
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
async def test_lembrete_cobra_proativo_e_modelo_fecha_em_execucao_para_fechado(conn: Any):
    """A jornada chega em `Em_execucao` (pela portaria, no ★API) e o ato pos-loop
    (`lembrete_cobra_e_fecha`) (a) dispara o cron real `cobrar_valor_final` -- um card `lembrete_valor`
    e enviado, COBRANCA PROATIVA do Valor final -- e (b) a modelo responde esse card com o valor ->
    `Em_execucao -> Fechado`: Valor final gravado, bloqueio concluido, IA despausada. Os efeitos do
    criterio F4.4 provados no Postgres real."""
    runner = _carregar_runner()
    # semeia pela MESMA porta que o jornada usa, no estado de onde a cobranca/fecho disparam.
    fixture_seed = {"estado_inicial": {"atendimento_estado": "Em_execucao", "ia_pausada": True}}
    modelo_id, atendimento_id, _cliente_id, _conversa_id = await runner._seed_entidades(
        conn, fixture_seed
    )
    bloqueio_id = await _seed_bloqueio_em_atendimento(
        conn, modelo_id=modelo_id, atendimento_id=atendimento_id
    )

    # 1) pre-condicao: Em_execucao (IA pausada), bloqueio em curso, NENHUMA cobranca ainda.
    antes = await _ler_atendimento(conn, atendimento_id)
    assert antes["estado"] == "Em_execucao"
    assert antes["ia_pausada"] is True
    assert await _estado_bloqueio(conn, bloqueio_id) == "em_atendimento"
    assert await _cards_lembrete(conn, atendimento_id) == 0

    # 2) o ato pos-loop da jornada: o lembrete cobra proativamente e a modelo fecha respondendo.
    await loop._aplicar_ato(conn, atendimento_id, "lembrete_cobra_e_fecha")

    # 3) a COBRANCA PROATIVA disparou: ao menos um card de Lembrete de fechamento foi enviado.
    assert await _cards_lembrete(conn, atendimento_id) >= 1

    # 4) o fecho em RESPOSTA a cobranca -> Fechado, com todos os efeitos do registro de resultado.
    depois = await _ler_atendimento(conn, atendimento_id)
    assert depois["estado"] == "Fechado"
    assert depois["valor_final"] is not None and depois["valor_final"] > Decimal("0")
    # bloqueio vinculado concluido pelo trigger sync_bloqueio_estado.
    assert await _estado_bloqueio(conn, bloqueio_id) == "concluido"
    # despausa a IA no encerramento (CONTEXT.md "Registro de resultado").
    assert depois["ia_pausada"] is False
    assert depois["ia_pausada_motivo"] is None
