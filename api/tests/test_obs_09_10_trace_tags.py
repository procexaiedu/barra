"""OBS-09/10 — modelo_id/atendimento_id viram metadata/tags do trace sem inflar o cache.

`metadata_trace_turno` produz um fragmento de config (metadata + tags); o LangChain o leva ao
RunTree do LangSmith. Aqui provamos, sem rede, que (1) os IDs surgem como metadata/tags do run,
com `atendimento_id` também em `gen_ai.conversation.id`, e (2) o fragmento é só config-level —
nunca conteúdo de mensagem/system — logo não pode entrar no prefixo cacheado (tools→system).
"""

from typing import Any

from langchain_core.runnables import RunnableLambda
from langchain_core.tracers.base import BaseTracer
from langchain_core.tracers.schemas import Run

from barra.core import tracing
from barra.core.tracing import metadata_trace_turno

_MODELO_ID = "11111111-1111-4111-8111-111111111111"
_ATENDIMENTO_ID = "22222222-2222-4222-8222-222222222222"
_CLIENTE_ID = "33333333-3333-4333-8333-333333333333"


class _CapturaRuns(BaseTracer):
    """Tracer em memória: guarda o RunTree raiz sem tocar a rede (mock de Client/trace)."""

    def __init__(self) -> None:
        super().__init__()
        self.runs: list[Run] = []

    def _persist_run(self, run: Run) -> None:
        self.runs.append(run)


def test_ids_surgem_como_metadata_e_tags_do_trace() -> None:
    captura = _CapturaRuns()
    config: dict[str, Any] = {"configurable": {"thread_id": "conversa-1"}}
    config |= metadata_trace_turno(_MODELO_ID, _ATENDIMENTO_ID, _CLIENTE_ID)
    config["callbacks"] = [captura]

    RunnableLambda(lambda x: x).invoke({"messages": []}, config=config)

    run = captura.runs[0]
    meta = run.extra["metadata"]
    assert meta["modelo_id"] == _MODELO_ID
    assert meta["atendimento_id"] == _ATENDIMENTO_ID
    assert meta["cliente_id"] == _CLIENTE_ID
    # atendimento_id também sob a convenção OTel gen_ai (thread do LangSmith)
    assert meta["gen_ai.conversation.id"] == _ATENDIMENTO_ID
    # Langfuse (ADR 0019): agrupa a jornada por atendimento + replica as tags no nível do trace
    assert meta["langfuse_session_id"] == _ATENDIMENTO_ID
    # user_id do trace = o cliente (usuário final da IA) — habilita o dashboard de usuários
    assert meta["langfuse_user_id"] == _CLIENTE_ID
    assert "atendimento_id:" + _ATENDIMENTO_ID in meta["langfuse_tags"]
    assert "cliente_id:" + _CLIENTE_ID in meta["langfuse_tags"]
    assert "modelo_id:" + _MODELO_ID in run.tags
    assert "atendimento_id:" + _ATENDIMENTO_ID in run.tags
    assert "cliente_id:" + _CLIENTE_ID in run.tags


def test_gen_ai_conversation_id_e_o_atendimento() -> None:
    frag = metadata_trace_turno(_MODELO_ID, _ATENDIMENTO_ID, _CLIENTE_ID)
    # a "conversa" do trace é o Atendimento, não o modelo_id
    assert frag["metadata"][tracing._GEN_AI_CONVERSATION_ID] == _ATENDIMENTO_ID
    assert frag["metadata"][tracing._GEN_AI_CONVERSATION_ID] != _MODELO_ID


def test_ids_sobrevivem_ao_anonymizer_sec10() -> None:
    """Allowlist por chave: o backstop _VALOR_PII casaria um UUID cujo grupo final de 12 hex é
    todo-dígito (~0.9%, e os UUIDs deste teste caem nesse caso) — sem a isenção, o discriminador
    do trace iria mascarado ao LangSmith. Sob as chaves de ID o valor passa intacto.
    """
    # sanity: estes UUIDs disparam o backstop genérico (grupo final só de dígitos)
    assert tracing._VALOR_PII.search(_MODELO_ID)
    assert tracing._VALOR_PII.search(_ATENDIMENTO_ID)
    assert tracing._VALOR_PII.search(_CLIENTE_ID)

    for chave in ("modelo_id", "atendimento_id", "cliente_id", tracing._GEN_AI_CONVERSATION_ID):
        assert tracing._mascarar(_MODELO_ID, [chave]) == _MODELO_ID
        assert tracing._mascarar(_ATENDIMENTO_ID, [chave]) == _ATENDIMENTO_ID
    assert tracing._mascarar(_CLIENTE_ID, ["cliente_id"]) == _CLIENTE_ID
    # a isenção é por chave: o mesmo valor sob chave de PII continua mascarado
    assert tracing._mascarar(_MODELO_ID, ["telefone"]) == tracing._MASCARA


def test_fragmento_e_so_config_level_nao_toca_prefixo_cacheado() -> None:
    """Invariante de cache: o fragmento só contribui com metadata/tags (nível de config).

    O prefixo cacheado é montado em `agente/prepare_context` a partir do `state`
    (messages/system), nunca do config. Como `metadata_trace_turno` não emite `messages`,
    `system` nem `configurable`, os IDs não têm como entrar no prefixo — o cache não muda.
    """
    frag = metadata_trace_turno(_MODELO_ID, _ATENDIMENTO_ID, _CLIENTE_ID)
    assert set(frag) == {"metadata", "tags"}
    for chave in ("messages", "system", "configurable", "input", "prompt"):
        assert chave not in frag
