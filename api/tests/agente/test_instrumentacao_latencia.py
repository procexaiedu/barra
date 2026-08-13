"""Instrumentação de latência do agente: por nó do grafo, por caminho de LLM e fingerprint.

O que estes testes protegem não é a métrica em si -- é a capacidade de VER. Antes deles a única
duração medida era a do turno inteiro, e num histograma cujo maior bucket finito era 10s: um turno
de 41,7s (pior caso medido em 12/08) aparecia como 10s e os dois alertas de latência não tinham
como disparar. Cf. `_BUCKETS_LATENCIA_TURNO` em core/metrics.py.
"""

import asyncio
import inspect

import pytest
from langchain_core.messages import AIMessage
from prometheus_client import REGISTRY

from barra.agente._instrumentar import medir_llm, medir_no, registrar_fingerprint
from barra.agente.graph import _cronometrado


def _amostra(nome: str, **labels: str) -> float | None:
    return REGISTRY.get_sample_value(nome, labels)


def test_buckets_do_turno_cobrem_acima_do_teto_de_60s() -> None:
    """O default do prometheus_client termina em 10s. Com ele, `histogram_quantile` devolve o
    último bucket FINITO para tudo que passa disso -- p95/p99 saturavam em 10s e os alertas
    `AgenteLatenciaTurnoP95Alta` (>20s) / `P99Alta` (>40s) eram inalcançáveis por construção.
    """
    from barra.core.metrics import _BUCKETS_LATENCIA_TURNO

    finitos = [b for b in _BUCKETS_LATENCIA_TURNO if b != float("inf")]

    assert max(finitos) >= 90, "o maior bucket finito tem de passar do teto de 60s do wait_for"
    # granularidade NA FAIXA DOS ALERTAS (20s e 40s): sem bucket entre 10s e 60s o quantil não tem
    # como separar um turno de 15s de um de 55s, e os dois alertas viram tudo-ou-nada.
    assert len([b for b in finitos if 10 < b <= 60]) >= 3


def test_medir_no_observa_a_duracao() -> None:
    antes = _amostra("agente_no_duracao_seconds_count", no="teste_no") or 0.0

    with medir_no("teste_no"):
        pass

    assert (_amostra("agente_no_duracao_seconds_count", no="teste_no") or 0.0) == antes + 1


def test_medir_no_registra_mesmo_quando_o_no_estoura() -> None:
    """Um nó que falha DEPOIS de 30s é exatamente o caso que precisamos enxergar."""
    antes = _amostra("agente_no_duracao_seconds_count", no="teste_boom") or 0.0

    with pytest.raises(RuntimeError), medir_no("teste_boom"):
        raise RuntimeError("boom")

    assert (_amostra("agente_no_duracao_seconds_count", no="teste_boom") or 0.0) == antes + 1


def test_medir_llm_separa_os_caminhos() -> None:
    """Os três caminhos do turno rodam o MESMO modelo -- a label `modelo` não os distingue."""
    with medir_llm("chat"):
        pass
    with medir_llm("judge_aup"):
        pass

    assert _amostra("agente_llm_duracao_seconds_count", caminho="chat")
    assert _amostra("agente_llm_duracao_seconds_count", caminho="judge_aup")


def test_fingerprint_do_build_vira_serie() -> None:
    """O DeepSeek não tem snapshot pinável (a API só aceita os aliases móveis), então a troca de
    pesos sob o mesmo id só pode ser detectada -- e o `system_fingerprint` é o sinal.
    """
    resp = AIMessage(
        content="",
        response_metadata={"system_fingerprint": "fp_teste_prod0820_fp8"},
    )

    registrar_fingerprint(resp, "deepseek-v4-flash")

    assert (
        _amostra(
            "agente_modelo_fingerprint",
            modelo="deepseek-v4-flash",
            fingerprint="fp_teste_prod0820_fp8",
        )
        == 1
    )


def test_fingerprint_ausente_nao_cria_serie_vazia() -> None:
    registrar_fingerprint(AIMessage(content="", response_metadata={}), "deepseek-v4-flash")

    assert _amostra("agente_modelo_fingerprint", modelo="deepseek-v4-flash", fingerprint="") is None


def test_cronometrado_preserva_a_assinatura_que_o_langgraph_inspeciona() -> None:
    """O footgun real do wrapper. O LangGraph decide se injeta `runtime`/`config` lendo
    `inspect.signature(func).parameters` (langgraph/_internal/_runnable.py). Um wrapper que não
    preserve a assinatura faz o nó rodar SEM runtime, em silêncio -- e aí nada funciona, mas nada
    grita. `functools.wraps` resolve porque `signature` segue `__wrapped__`.
    """

    async def no_falso(state: dict, runtime: object) -> dict:
        return {"ok": True}

    envolvido = _cronometrado("no_falso", no_falso)

    assert list(inspect.signature(envolvido).parameters) == ["state", "runtime"]
    assert asyncio.run(envolvido({}, object())) == {"ok": True}
    assert (_amostra("agente_no_duracao_seconds_count", no="no_falso") or 0.0) == 1


def test_grafo_registra_os_nos_cronometrados_sem_perder_o_runtime() -> None:
    """Prova de ponta: o grafo real compila e os nós continuam recebendo `runtime`."""
    from barra.agente.graph import build_graph

    grafo = build_graph()
    nos = set(grafo.get_graph().nodes)

    assert {"prepare_context", "llm", "tools", "extrair", "output_guard"} <= nos
