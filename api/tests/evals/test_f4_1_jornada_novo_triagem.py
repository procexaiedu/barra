"""F4.1 — jornada E2E que COMECA em `Novo` (1o contato antes da triagem) e exercita Novo->Triagem.

Hoje TODA jornada do sim nasce em `Triagem` (o `estado_inicial` default de `Cenario`/`CenarioFixo`):
`Novo` -- o primeiro contato, antes de a IA extrair qualquer intencao -- nunca era alcancado pela
propria conversa. Este gate tranca a existencia de uma jornada que parte de `Novo` e a prova de que
a costura da jornada de fato leva Novo->Triagem pela conversa.

Duas metades, espelhando o padrao do roadmap (F0.x/F1.x):

- **Estrutural (PURO, sem DB/LLM)** — roda no `make test` padrao: ao menos um `Cenario` (e um
  `CenarioFixo`) declara `estado_inicial = {"atendimento_estado": "Novo"}`, com a 1a fala do cliente
  exprimindo intencao real (cotacao/agendamento) -- o gatilho de Novo->Triagem. Gate de PR de verdade.

- **Espinha (needs_db)** — roda no Postgres efemero do CI (pos-F0.1): semeia a jornada pela MESMA
  porta que `sim/loop.py:jornada` usa (`runner._seed_entidades`, honrando `estado_inicial`) e prova
  que o atendimento nasce em `Novo` (nao coagido ao default `Triagem`); em seguida aplica a EXATA
  rota de dominio que a tool `registrar_extracao` dispara num turno (`registrar_extracao_ia` com
  `intencao`) e prova a transicao Novo->Triagem. E "pela conversa" menos o LLM decidir chamar a tool
  -- essa metade (grafo real + Sonnet) e a parte ★API, bloqueada por credito/banco de teste.
"""

import importlib
import importlib.util
import os
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
import pytest_asyncio

_API = Path(__file__).resolve().parents[2]  # api/
if str(_API) not in sys.path:
    sys.path.insert(0, str(_API))

cenarios = importlib.import_module("evals.sim.cenarios")
cenarios_fixos = importlib.import_module("evals.sim.cenarios_fixos")

_RUNNERS = _API / "evals" / "runners"


def _estado_inicial(cen: Any) -> str:
    return cen.estado_inicial.get("atendimento_estado")


def _cenarios_novo() -> list[Any]:
    return [c for c in cenarios.CENARIOS if _estado_inicial(c) == "Novo"]


def _fixos_novo() -> list[Any]:
    return [c for c in cenarios_fixos.todos_fixos() if _estado_inicial(c) == "Novo"]


# --- estrutural (PURO) -------------------------------------------------------------------------


def test_existe_jornada_persona_comecando_em_novo():
    # anti-vacuo: o conjunto E2E nao esta vazio -- senao "nenhuma comeca em Novo" seria verde-vazio.
    assert cenarios.CENARIOS, "CENARIOS vazio"
    novos = _cenarios_novo()
    assert novos, "nenhum Cenario (persona) comeca em 'Novo' -- F4.1 exige a jornada de 1o contato"


def test_existe_jornada_fixa_comecando_em_novo():
    assert cenarios_fixos.todos_fixos(), "conjunto fixo vazio"
    novos = _fixos_novo()
    assert novos, "nenhum CenarioFixo comeca em 'Novo' -- F4.1 exige a jornada de 1o contato fixa"


def test_persona_novo_primeira_fala_tem_intencao():
    # o gatilho Novo->Triagem e a IA extrair intencao da 1a fala. A persona de 1o contato precisa
    # carregar uma intencao real (preco/agendar/marcar), nao so um "oi" mudo que nada extrai.
    _GATILHOS = ("preco", "preço", "quanto", "valor", "marcar", "agendar", "1h", "uma hora", "hora")
    for cen in _cenarios_novo():
        blob = cen.persona.o_que_quer.lower()
        assert any(g in blob for g in _GATILHOS), (
            f"{cen.nome}: persona de 1o contato em Novo nao exprime intencao (Novo->Triagem nao dispara)"
        )


def test_fixo_novo_primeira_fala_existe():
    for cen in _fixos_novo():
        assert cen.mensagens_cliente and cen.mensagens_cliente[0].strip(), (
            f"{cen.nome}: jornada fixa em Novo sem 1a fala de cliente"
        )


# --- espinha (needs_db): a jornada de fato leva Novo->Triagem pela conversa ----------------------


def _carregar_runner() -> Any:
    """Carrega runner.py por caminho (evals/ fora do pacote `barra`) -- igual a sim/loop.py."""
    caminho = _RUNNERS / "runner.py"
    spec = importlib.util.spec_from_file_location("eval_runner_f4_1", caminho)
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("eval_runner_f4_1", modulo)
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


async def _ler_estado(conn: Any, atendimento_id: UUID) -> str:
    res = await conn.execute(
        "SELECT estado::text AS estado FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    row = await res.fetchone()
    assert row is not None
    return row["estado"]


@pytest.mark.needs_db
async def test_seed_da_jornada_novo_nasce_em_novo_e_transiciona_para_triagem(conn: Any):
    """A jornada de 1o contato semeia um atendimento em `Novo` (pela porta do `jornada`) e a rota
    de dominio do turno (`registrar_extracao_ia` com intencao) o leva a `Triagem`."""
    from barra.dominio.atendimentos.service import registrar_extracao_ia

    runner = _carregar_runner()
    cen = _cenarios_novo()[0]
    fixture_seed = {"estado_inicial": cen.estado_inicial}

    _modelo_id, atendimento_id, _cliente_id, _conversa_id = await runner._seed_entidades(
        conn, fixture_seed
    )

    # 1) nasce em Novo (nao coagido ao default Triagem do _seed_entidades).
    assert await _ler_estado(conn, atendimento_id) == "Novo"

    # 2) o turno (a IA chama registrar_extracao com a intencao da 1a fala) transiciona Novo->Triagem.
    resultado = await registrar_extracao_ia(
        conn,
        str(atendimento_id),
        {"intencao": "cotacao", "proxima_acao_esperada": "cotar 1h"},
    )
    assert resultado["novo_estado"] == "Triagem"
    assert await _ler_estado(conn, atendimento_id) == "Triagem"
