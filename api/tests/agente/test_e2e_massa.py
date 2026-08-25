"""Validacao offline do runner em massa de cenarios (evals/e2e/massa.py).

needs_db (DB real via TEST_DATABASE_URL, ROLLBACK sempre), NAO needs_key: graph fake, sem credito
(§0). Cobre o codigo novo mais arriscado: o pos-evento determinístico da foto de portaria
(`_disparar_foto_portaria` -> handoff de dominio -> Em_execucao + IA pausada) e o encanamento do
`rodar_massa` (seed -> conducao fake -> pos-evento -> veredito), sem tocar prod (run_tag=None).
"""

from __future__ import annotations

import importlib
import os
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from evals.e2e.massa import _disparar_foto_portaria, rodar_massa
from evals.harness import estado_pos_turno, seedar
from psycopg import AsyncConnection
from psycopg.rows import dict_row

pytestmark = pytest.mark.needs_db


@pytest.fixture(autouse=True)
def _judge_aup_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    """Neutraliza o LLM-judge de AUP: aqui o graph e fake e o marcador e `not needs_key`, entao o
    no output_guard nao pode sair para a rede. Sem isto o judge chama a API de verdade (gasta
    credito apesar do marcador) e, quando outro teste async ja rodou no mesmo processo, reusa o
    cliente httpx preso ao event loop anterior -> `Event loop is closed` -> exception -> default
    seguro -> turno mudo -> falha que so aparece na suite completa."""
    # importlib porque `nos/__init__` exporta a FUNCAO `output_guard` e sombreia o submodulo
    og = importlib.import_module("barra.agente.nos.output_guard")

    async def _aprovado(*_a: Any, **_k: Any) -> Any:
        return og._VeredictoAup(viola=False, motivo="nenhum")

    monkeypatch.setattr(og, "_julgar_aup", _aprovado)


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


async def test_foto_portaria_dispara_transicao(conn: AsyncConnection[dict[str, Any]]) -> None:
    """Interno em Aguardando_confirmacao + foto de portaria -> Em_execucao, IA pausada (motivo
    modelo_em_atendimento). Evento determinístico de dominio, sem graph/worker/vision."""
    cen = await seedar(
        conn,
        {
            "cenario": {
                "modelo": {"nome": "Manu", "tipo_atendimento_aceito": ["interno"]},
                "atendimento": {"estado": "Aguardando_confirmacao", "tipo_atendimento": "interno"},
            },
            "historico": [],
        },
    )
    await _disparar_foto_portaria(conn, cen)

    est = await estado_pos_turno(conn, cen.atendimento_id)
    assert est["estado"] == "Em_execucao", est
    assert est["ia_pausada"] is True, est


async def test_rodar_massa_foto_portaria_fake(
    conn: AsyncConnection[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """rodar_massa conduz o cenario foto_portaria com graph fake e dispara o pos-evento ate
    Em_execucao. run_tag=None -> nao grava (nao toca corpus.eval_e2e). Tokens 100% do fake (§0)."""
    from evals.e2e import cenarios as cmod
    from evals.e2e import massa as mmod
    from evals.e2e.sessao import _graph_fake

    so_foto = [c for c in cmod.cenarios() if c.nome == "foto_portaria"]
    monkeypatch.setattr(mmod, "cenarios", lambda: so_foto)

    resultados = await rodar_massa(conn, _graph_fake(), k=1, run_tag=None)

    assert len(resultados) == 1, resultados
    r = resultados[0]
    assert r["cenario"] == "foto_portaria"
    assert r["estado_final"] == "Em_execucao", r
    assert r["avaliacao"].get("estado_esperado_ok") is True, r
    assert not r["violacoes"], r


async def test_rodar_massa_agenda_borda_fora_fake(
    conn: AsyncConnection[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Encanamento do cenario agenda_borda_fora com graph fake: o seed de modelo_disponibilidade
    (janela 10-23h) nao quebra e o veredito traz o check `nao_confirmou_fora_ok`. O VALOR do check so
    e significativo na corrida REAL (o fake nao confirma horario); aqui guardamos o plumbing (§0)."""
    from evals.e2e import cenarios as cmod
    from evals.e2e import massa as mmod
    from evals.e2e.sessao import _graph_fake

    so_borda = [c for c in cmod.cenarios() if c.nome == "agenda_borda_fora"]
    monkeypatch.setattr(mmod, "cenarios", lambda: so_borda)

    resultados = await rodar_massa(conn, _graph_fake(), k=1, run_tag=None)

    assert len(resultados) == 1, resultados
    r = resultados[0]
    assert r["cenario"] == "agenda_borda_fora"
    assert "nao_confirmou_fora_ok" in r["avaliacao"], r


async def test_rodar_massa_desconto_3_faixas_fake(
    conn: AsyncConnection[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Encanamento das 4 fixtures de desconto (o número DELE acima do piso — ADR-0040 —, a oferta
    condicionada ao dia — ADR-0041 —, a escada dela rodando inteira e o pedido abaixo do teto) com
    graph fake: as 4 rodam sem quebrar e o veredito traz o check certo por
    faixa (`nao_escalou_ok` nas 3 primeiras, `tool_esperada_ok` na última). O VALOR do check so e
    significativo na corrida REAL (o fake nao decide tools/escalada); aqui guardamos o plumbing
    (§0) — mesma disciplina de test_rodar_massa_agenda_borda_fora_fake."""
    from evals.e2e import cenarios as cmod
    from evals.e2e import massa as mmod
    from evals.e2e.sessao import _graph_fake

    so_desconto = [c for c in cmod.cenarios() if c.nome.startswith("desconto_")]
    assert {c.nome for c in so_desconto} == {
        "desconto_valor_dele_serve",
        "desconto_condicionado_ao_dia",
        "desconto_entre_degrau_teto",
        "desconto_abaixo_teto",
    }
    monkeypatch.setattr(mmod, "cenarios", lambda: so_desconto)

    resultados = await rodar_massa(conn, _graph_fake(), k=1, run_tag=None)

    por_cenario = {r["cenario"]: r for r in resultados}
    assert set(por_cenario) == {c.nome for c in so_desconto}
    assert "nao_escalou_ok" in por_cenario["desconto_valor_dele_serve"]["avaliacao"]
    assert "nao_escalou_ok" in por_cenario["desconto_condicionado_ao_dia"]["avaliacao"]
    assert "nao_escalou_ok" in por_cenario["desconto_entre_degrau_teto"]["avaliacao"]
    assert "tool_esperada_ok" in por_cenario["desconto_abaixo_teto"]["avaliacao"]


def test_linkar_item_run_noop_sem_handler(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fase 5: sem handler Langfuse (tracing off — pytest/.env vazio) o link e no-op puro: nao
    levanta nem toca a rede, mesmo com trace_id setado. Mesma disciplina best-effort das outras
    funcoes de dataset (garantir/upsert). Forca o handler=None (outro teste da suite pode te-lo
    ligado num global e nao restaurado) p/ o no-op ser testado de forma isolada."""
    from barra.core import tracing

    monkeypatch.setattr(tracing, "_LANGFUSE_HANDLER", None)
    # nao deve levantar nem retornar nada (no-op)
    assert tracing.linkar_item_run("e2e_conducao", "item-x", "run-1", "trace-abc") is None
    # tambem no-op quando falta o trace_id (turno sem escopo)
    assert tracing.linkar_item_run("e2e_conducao", "item-x", "run-1", None) is None


async def test_rodar_massa_com_dataset_run_nao_quebra_sem_handler(
    conn: AsyncConnection[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fase 5: passar `dataset_run` com o tracing OFF (sem chaves Langfuse) e seguro — garantir/
    upsert/link sao no-op e a corrida roda igual. Prova que a integracao nao acopla o eval ao
    Langfuse. Graph fake, run_tag=None: sem credito e sem tocar prod (§0)."""
    from evals.e2e import cenarios as cmod
    from evals.e2e import massa as mmod
    from evals.e2e.sessao import _graph_fake

    from barra.core import tracing

    # forca o tracing OFF (outro teste pode ter ligado o handler global): sem isso o `dataset_run`
    # tentaria criar dataset/run REAIS no Langfuse de prod.
    monkeypatch.setattr(tracing, "_LANGFUSE_HANDLER", None)

    so_foto = [c for c in cmod.cenarios() if c.nome == "foto_portaria"]
    monkeypatch.setattr(mmod, "cenarios", lambda: so_foto)

    resultados = await rodar_massa(
        conn, _graph_fake(), k=1, run_tag=None, dataset_run="run-de-teste"
    )

    assert len(resultados) == 1, resultados
    assert resultados[0]["cenario"] == "foto_portaria"


async def test_tools_do_banco_le_o_rastro_real_do_turno(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """12c (c7): a regua do book conta `enviar_midia` do TURNO, e o rastro que sobrevive a
    regeneracao do output_guard e o de `barravips.tool_calls` — nao o das AIMessages.

    Aqui o que se prova e o contrato com o banco REAL, que o teste puro (FakeConn, unit/
    test_rig_carimbo_e_veredito) nao alcanca: o `ANY(%s::uuid[])` adapta a lista de `turno_id`,
    o `payload` volta como dict (jsonb) e os turnos VIZINHOS nao vazam — os turnos de um caso e2e
    dividem a mesma transacao, entao filtrar por turno_id e o que impede o turno 5 de herdar o
    book do turno 1. ROLLBACK do fixture desfaz os INSERTs."""
    import json
    from uuid import uuid4

    from evals.harness import _tools_do_banco

    turno_a, turno_b = str(uuid4()), str(uuid4())
    for turno_id, idx, tipo in ((turno_a, 0, "foto"), (turno_a, 1, "video"), (turno_b, 0, "foto")):
        await conn.execute(
            "INSERT INTO barravips.tool_calls (turno_id, tool_name, call_idx, payload)"
            " VALUES (%s, 'enviar_midia', %s, %s::jsonb)",
            (turno_id, idx, json.dumps({"tag": "corpo", "tipo": tipo, "legenda": ""})),
        )

    nomes, args = await _tools_do_banco(conn, [turno_a])

    assert nomes == ["enviar_midia", "enviar_midia"]
    assert [a["tipo"] for a in args] == ["foto", "video"], args  # ordem por call_idx
    assert all(isinstance(a, dict) for a in args), "payload jsonb tem que voltar como dict"
    # o turno vizinho da MESMA transacao nao entra
    assert await _tools_do_banco(conn, [turno_b]) == (["enviar_midia"], [args[0]])


async def test_escalada_do_coordenador_e_carimbada_no_turno(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """12d (c8): `escalar_por_exaustao` abre handoff SEM tocar `messages` (07 §3.3) — o unico
    rastro e a linha nova em `barravips.escaladas`. Aqui o contrato REAL que o teste puro
    (FakeConn, unit/test_rig_carimbo_e_veredito) nao alcanca: a coluna `observacao` existe e
    guarda o motivo literal, o filtro `fechada_em IS NULL` casa, e a 2a abertura e no-op pela
    idempotencia do `abrir_handoff` (pausa herdada -> nenhum carimbo novo).

    Usa o MESMO par `mapear_motivo` + `abrir_handoff` que o coordenador usa, para o teste nao
    depender do meu palpite sobre tipo/responsavel. ROLLBACK do fixture desfaz tudo."""
    from evals.harness_fiel import _escalada_nova, _escaladas_abertas

    from barra.dominio.escaladas.service import abrir_handoff, mapear_motivo

    cen = await seedar(
        conn,
        {
            "cenario": {
                "modelo": {"nome": "Manu", "tipo_atendimento_aceito": ["interno"]},
                "atendimento": {"estado": "Qualificado"},
            },
            "historico": [],
        },
    )
    antes = await _escaladas_abertas(conn, cen.atendimento_id)
    assert antes == set()

    tipo, responsavel = mapear_motivo("modelo_indisponivel")
    await abrir_handoff(
        conn,
        atendimento_id=cen.atendimento_id,
        responsavel=responsavel,
        tipo=tipo,
        resumo_operacional="Agente nao encerrou o turno (teste).",
        acao_esperada="Revisar trace.",
        origem="agente",
        autor="sistema",
        observacao="modelo_indisponivel",
    )

    assert await _escalada_nova(conn, cen.atendimento_id, antes) == "modelo_indisponivel"

    # turno seguinte: a escalada ja esta de pe -> `abrir_handoff` e no-op e nada e carimbado.
    agora_abertas = await _escaladas_abertas(conn, cen.atendimento_id)
    await abrir_handoff(
        conn,
        atendimento_id=cen.atendimento_id,
        responsavel=responsavel,
        tipo=tipo,
        resumo_operacional="Segunda tentativa (teste).",
        acao_esperada="Revisar trace.",
        origem="agente",
        autor="sistema",
        observacao="timeout_grafo",
    )
    assert await _escalada_nova(conn, cen.atendimento_id, agora_abertas) is None
