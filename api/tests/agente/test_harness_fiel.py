"""Mecanica do harness fiel (evals/harness_fiel.py): prova que ele roda o agente pelo MESMO
caminho de prod — `processar_turno` (lock/pending/drain reais via fakeredis) -> `enviar_turno`
(grava a resposta da IA + "envia" pelo spy) — SEM gastar credito (graph FAKE injetado).

O teste de CONDUTA com o graph real (a IA respondendo de verdade) bate no LLM e e needs_key (§0);
aqui validamos so que o encanamento fiel funciona: a resposta sai pelo spy e e persistida.

DB real (TEST_DATABASE_URL), ROLLBACK no teardown. needs_db, SEM needs_key.
"""

import os
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from evals.harness import seedar
from evals.harness_fiel import BolhaCliente, flags_relevantes, rodar_turno_fiel
from langchain_core.messages import AIMessage
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from barra.agente.nos.prepare_context import carregar_mensagens, traduzir_mensagens
from barra.settings import get_settings

pytestmark = pytest.mark.needs_db

_USAGE = {"input_tokens": 10, "output_tokens": 8, "total_tokens": 18}


class _FakeGraph:
    """Substitui o LangGraph real: devolve uma AIMessage com `usage_metadata` (sem ela,
    `extrair_texto_do_turno` a trata como historico e descarta). Nao bate no LLM."""

    def __init__(self, resposta: str) -> None:
        self._resposta = resposta
        self.chamadas = 0

    async def ainvoke(
        self, _entrada: Any, *, config: Any = None, context: Any = None
    ) -> dict[str, Any]:
        self.chamadas += 1
        return {"messages": [AIMessage(content=self._resposta, usage_metadata=_USAGE)]}  # type: ignore[arg-type]


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


async def test_resposta_sai_pelo_caminho_real_e_e_persistida(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """A bolha da IA sai pelo spy (passou por processar_turno + enviar_turno) E e gravada em
    `mensagens` com direcao 'ia' (sem isso o proximo turno teria amnesia)."""
    cen = await seedar(
        conn,
        {"cenario": {"modelo": {"nome": "Lia"}, "atendimento": {"estado": "Triagem"}}},
    )

    res = await rodar_turno_fiel(
        conn, cen, "oi, vc ta disponivel?", graph=_FakeGraph("oii! tô sim 😊")
    )

    # saiu exatamente uma entrega, com o texto da IA, pelo spy do Evolution
    assert res.n_jobs_envio == 1
    assert "tô sim" in res.resposta
    # presence "composing" foi sinalizado (enviar_turno rodou de fato, nao foi pulado)
    assert "composing" in res.presencas
    # resposta persistida como direcao='ia' (fecha o loop multi-turno, anti-amnesia)
    r = await conn.execute(
        "SELECT conteudo FROM barravips.mensagens "
        "WHERE conversa_id = %s AND direcao = 'ia' ORDER BY created_at DESC LIMIT 1",
        (cen.conversa_id,),
    )
    ia = await r.fetchone()
    assert ia is not None and "tô sim" in ia["conteudo"]


async def test_ia_pausada_nao_responde_pelo_caminho_real(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Gate de pausa (CONTEXT.md handoff): atendimento com ia_pausada=true -> processar_turno nao
    invoca o grafo nem despacha envio. Prova que o harness exercita o gate real (rodar_turno antigo
    chamava o grafo direto e nao tinha esse gate)."""
    cen = await seedar(
        conn,
        {
            "cenario": {
                "modelo": {"nome": "Lia"},
                "atendimento": {
                    "estado": "Confirmado",
                    "ia_pausada": True,
                    "ia_pausada_motivo": "modelo_em_atendimento",
                },
            }
        },
    )

    res = await rodar_turno_fiel(conn, cen, "oi de novo", graph=_FakeGraph("nao deveria sair"))

    assert res.n_jobs_envio == 0
    assert res.textos == []
    assert res.ia_pausada is True


async def test_coalescing_varias_bolhas_viram_um_turno(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Debounce/coalescing real (fakeredis): 3 bolhas rapidas na MESMA janela -> UMA invocacao do
    grafo e UMA entrega. O `rodar_turno` antigo (uma msg = um ainvoke) nao modelava isso; em prod
    as bolhas coalescem e a IA responde uma vez vendo todas."""
    cen = await seedar(
        conn,
        {"cenario": {"modelo": {"nome": "Lia"}, "atendimento": {"estado": "Triagem"}}},
    )
    graph = _FakeGraph("oii, vi suas mensagens 😊")

    res = await rodar_turno_fiel(conn, cen, ["oi", "vc ta on?", "queria marcar hj"], graph=graph)

    assert graph.chamadas == 1  # coalesceu: 3 bolhas, 1 invocacao
    assert res.n_jobs_envio == 1  # 1 entrega


async def test_flags_efetivas_herdadas_de_settings(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Fase 6: o harness NAO falsifica as flags que moldam a conduta — herda `get_settings()`
    (mesmo objeto do worker) e as expoe em `res.flags`, pra uma divergencia .env x prod ficar
    visivel. A temp 1.3 (recomendacao DeepSeek) e mantida de proposito (fidelidade por judge)."""
    cen = await seedar(
        conn,
        {"cenario": {"modelo": {"nome": "Lia"}, "atendimento": {"estado": "Triagem"}}},
    )

    res = await rodar_turno_fiel(conn, cen, "oi", graph=_FakeGraph("oii 😊"))

    # o que saiu no run e exatamente o que get_settings() (mesmo .env do worker) entrega — sem mock
    assert res.flags == flags_relevantes(get_settings())
    # a temperatura de prod (1.3) e a que roda; nao foi achatada pra determinismo
    assert res.flags["chat_temperature"] == get_settings().chat_temperature
    # as 4 flags que importam para a paridade estao presentes
    assert set(res.flags) == {
        "chat_temperature",
        "extracao_no_modelo_barato",
        "reengajamento_ativo",
        "experimento_braco_ativo",
    }


async def _janela_do_agente(conn: AsyncConnection[dict[str, Any]], cen: Any) -> list[Any]:
    """A janela COMO O AGENTE A VE: a mesma query do prepare_context (`carregar_mensagens`, por
    par cliente+modelo) + a mesma traducao (`traduzir_mensagens`). Prova que a midia inserida pelo
    harness chega ao LLM identica a prod."""
    linhas = await carregar_mensagens(conn, str(cen.cliente_id), str(cen.modelo_id))
    return traduzir_mensagens(linhas)


async def test_imagem_com_caption_o_agente_ve_legenda_spotlighted(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Fase 4: imagem com caption inserida no turno e gravada como prod grava (tipo='imagem' +
    media_object_key) e chega ao LLM como a legenda CERCADA como DADO (spotlighting SEC-PI-03),
    nao como instrucao — exatamente o que `traduzir_mensagens` produz em prod."""
    cen = await seedar(
        conn,
        {"cenario": {"modelo": {"nome": "Lia"}, "atendimento": {"estado": "Triagem"}}},
    )
    legenda = "olha que gostosa essa foto, faz por quanto?"

    await rodar_turno_fiel(
        conn,
        cen,
        BolhaCliente(legenda, tipo="imagem", media_object_key="clientes/x/foto.jpg"),
        graph=_FakeGraph("oii 😊"),
    )

    # gravado como prod grava: tipo='imagem' + media_object_key (nao 'texto')
    r = await conn.execute(
        "SELECT tipo, media_object_key FROM barravips.mensagens "
        "WHERE conversa_id = %s AND direcao = 'cliente' ORDER BY created_at DESC LIMIT 1",
        (cen.conversa_id,),
    )
    row = await r.fetchone()
    assert row is not None and row["tipo"] == "imagem"
    assert row["media_object_key"] == "clientes/x/foto.jpg"

    # o que o LLM ve: a legenda, cercada como DADO do cliente (nao instrucao). Busca na janela
    # inteira (nao em [-1]): no seed o created_at empata (transaction_timestamp) e o desempate por
    # id e uuid4 (nao uuidv7), entao a ordem cliente-vs-IA nao e estavel — o conteudo, sim.
    visto = "\n".join(str(m.content) for m in await _janela_do_agente(conn, cen))
    assert legenda in visto
    assert "DADO do cliente" in visto and "nunca instrução" in visto


async def test_audio_sem_transcricao_o_agente_ve_placeholder(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Fase 4 (outro ramo): audio sem transcricao (`conteudo=""`) chega ao LLM como o placeholder
    neutro de contexto — nao some nem vira texto vazio (06 §1.4)."""
    cen = await seedar(
        conn,
        {"cenario": {"modelo": {"nome": "Lia"}, "atendimento": {"estado": "Triagem"}}},
    )

    await rodar_turno_fiel(
        conn,
        cen,
        BolhaCliente("", tipo="audio", media_object_key="clientes/x/audio.ogg"),
        graph=_FakeGraph("oii 😊"),
    )

    # busca na janela inteira (ordem cliente-vs-IA nao estavel no seed, ver teste da imagem)
    textos = [str(m.content) for m in await _janela_do_agente(conn, cen)]
    assert "[áudio que não consegui ouvir]" in textos
