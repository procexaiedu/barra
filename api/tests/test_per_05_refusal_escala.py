"""PER-05/TOOLS-01: refusal do Sonnet escala (modelo_recusou) e Pix duvidoso em vez de mudo.

Cobre o DoD sem tocar a API real (chat/vision FAKE) nem o banco (pool/conn mockados), entao
roda no gate `-m "not needs_key and not needs_db"`:

(a) refusal do Sonnet (stop_reason=refusal, chega em 200 OK) ->
    - no `no_llm`: loga stop_details.category e roteia para post_process (sem bolha crua);
    - no `processar_turno`: aciona escalar_por_exaustao(motivo="modelo_recusou") (bucket=defesa
      via mapping real), IA pausa e NENHUM enviar_turno e despachado ao cliente.
(b) vision do Pix com finish_reason=max_tokens/refusal -> comprovante DUVIDOSO (em_revisao):
    o fluxo avanca (nunca trava) em vez de levantar ValueError.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest
from langchain_core.messages import AIMessage

from barra.dominio.escaladas.modelos import TipoEscalada
from barra.workers.coordenador import escalar_por_exaustao, processar_turno
from barra.workers.pix import ExtracaoPix, VisionInconclusiva, _extrair_via_openrouter, validar_pix

_ATEND_ID = UUID("00000000-0000-0000-0000-0000000000bb")
_MODELO_ID = UUID("00000000-0000-0000-0000-0000000000c1")
_CLIENTE_ID = UUID("00000000-0000-0000-0000-0000000000c2")
_CONV_ID = "00000000-0000-0000-0000-0000000000c3"

_USAGE = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}


# ============================================================================
# (a1) no_llm: refusal loga category e roteia para post_process
# ============================================================================


class _FakeChatBound:
    def __init__(self, resp: AIMessage) -> None:
        self._resp = resp

    async def ainvoke(self, _messages: Any) -> AIMessage:
        return self._resp


class _FakeChat:
    model = "claude-test"

    def __init__(self, resp: AIMessage) -> None:
        self._resp = resp

    def bind_tools(self, _tools: Any) -> _FakeChatBound:
        return _FakeChatBound(self._resp)


async def test_no_llm_refusal_loga_categoria_e_roteia_post_process(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from barra.agente.nos.llm import no_llm

    resp = AIMessage(
        content="",
        usage_metadata=_USAGE,  # type: ignore[arg-type]
        response_metadata={"stop_reason": "refusal", "stop_details": {"category": "sexual"}},
    )
    node = no_llm(_FakeChat(resp), [])
    runtime = SimpleNamespace(context=SimpleNamespace(turno_id="t-1"))

    with caplog.at_level(logging.WARNING, logger="barra.agente.nos.llm"):
        comando = await node({"messages": []}, runtime)  # type: ignore[arg-type]

    # refusal sem tool_calls -> post_process (nao "tools"); o resp vai no state via `messages`.
    assert comando.goto == "post_process"
    enviado = comando.update["messages"][0]
    assert enviado.response_metadata["stop_reason"] == "refusal"
    # stop_details.category logado (sinal para auditoria do safety filter).
    assert "category=sexual" in caplog.text


# ============================================================================
# (a2) processar_turno: refusal escala modelo_recusou, sem bolha crua ao cliente
# ============================================================================


class _FakeResult:
    async def fetchone(self) -> dict[str, Any]:
        return {
            "id": _ATEND_ID,
            "ia_pausada": False,
            "estado": "Triagem",
            "modelo_id": _MODELO_ID,
            "cliente_id": _CLIENTE_ID,
            "conversa_id": UUID(_CONV_ID),
        }

    async def fetchall(self) -> list[dict[str, Any]]:
        return []


class _FakeConn:
    async def execute(self, *_a: Any, **_k: Any) -> _FakeResult:
        return _FakeResult()

    def transaction(self) -> _FakeConn:
        return self

    async def __aenter__(self) -> _FakeConn:
        return self

    async def __aexit__(self, *_a: Any) -> None:
        return None


class _FakePool:
    def connection(self) -> _FakeConn:
        return _FakeConn()


class _FakeRedis:
    def __init__(self) -> None:
        self.enqueue_job = AsyncMock()

    async def set(self, *_a: Any, **_k: Any) -> bool:
        return True

    async def delete(self, *_a: Any, **_k: Any) -> None:
        return None

    async def get(self, *_a: Any, **_k: Any) -> None:
        return None


class _FakeGraphRefusal:
    async def ainvoke(self, *_a: Any, **_k: Any) -> dict[str, Any]:
        # stop_reason=refusal chega num 200 OK (nao excecao); o no llm o poe no response_metadata.
        return {
            "messages": [
                AIMessage(
                    content="",
                    usage_metadata=_USAGE,  # type: ignore[arg-type]
                    response_metadata={"stop_reason": "refusal"},
                )
            ]
        }


class _FakeGraphTruncado:
    async def ainvoke(self, *_a: Any, **_k: Any) -> dict[str, Any]:
        # STOP-03: max_tokens + tool_calls = tool_use truncado; o no llm NAO despachou a tool e
        # roteou p/ post_process. O coordenador le o sinal e escala modelo_truncado.
        return {
            "messages": [
                AIMessage(
                    content="",
                    usage_metadata=_USAGE,  # type: ignore[arg-type]
                    response_metadata={"stop_reason": "max_tokens"},
                    tool_calls=[
                        {"name": "consultar_agenda", "args": {}, "id": "tc1", "type": "tool_call"}
                    ],
                )
            ]
        }


class _FakeSettings:
    anthropic_modelo_principal = "claude-test"


@asynccontextmanager
async def _lock_noop(*_a: Any, **_k: Any) -> Any:
    yield None


def _ctx_coord(redis: _FakeRedis, graph: Any = None) -> dict[str, Any]:
    return {
        "redis": redis,
        "db_pool": _FakePool(),
        "graph": graph or _FakeGraphRefusal(),
        "settings": _FakeSettings(),
        "job_id": "job-per05",
        "score": 1000,
    }


async def test_coordenador_refusal_escala_modelo_recusou_sem_bolha() -> None:
    redis = _FakeRedis()
    with (
        patch("barra.workers.coordenador.adquirir_lock", _lock_noop),
        patch("barra.workers.coordenador.escalar_por_exaustao", new=AsyncMock()) as mock_escalar,
    ):
        await processar_turno(_ctx_coord(redis), conversa_id=_CONV_ID)

    # escala defesa com motivo proprio (modelo_recusou), IA pausa via abrir_handoff.
    mock_escalar.assert_awaited_once()
    assert mock_escalar.await_args.kwargs["motivo"] == "modelo_recusou"

    # NENHUMA bolha crua ao cliente: nao despachou enviar_turno.
    enviados = [
        c for c in redis.enqueue_job.call_args_list if c.args and c.args[0] == "enviar_turno"
    ]
    assert enviados == []


async def test_motivo_modelo_recusou_mapeia_bucket_defesa() -> None:
    """modelo_recusou -> handoff Fernando (tipo=outro) + metrica bucket=defesa (mapping real)."""
    with (
        patch("barra.dominio.escaladas.service.abrir_handoff", new=AsyncMock()) as mock_handoff,
        patch("barra.workers.coordenador.AGENTE_ESCALADA") as mock_metric,
    ):
        await escalar_por_exaustao(_FakePool(), _ATEND_ID, "turno-per05", motivo="modelo_recusou")

    mock_handoff.assert_awaited_once()
    kwargs = mock_handoff.await_args.kwargs
    assert kwargs["tipo"] == TipoEscalada.outro
    assert kwargs["responsavel"] == "Fernando"
    assert kwargs["observacao"] == "modelo_recusou"
    mock_metric.labels.assert_called_once_with("defesa", "modelo_recusou")


async def test_coordenador_truncado_escala_modelo_truncado_sem_bolha() -> None:
    """STOP-03: tool_use truncado por max_tokens -> escala modelo_truncado, sem bolha ao cliente."""
    redis = _FakeRedis()
    with (
        patch("barra.workers.coordenador.adquirir_lock", _lock_noop),
        patch("barra.workers.coordenador.escalar_por_exaustao", new=AsyncMock()) as mock_escalar,
    ):
        await processar_turno(_ctx_coord(redis, _FakeGraphTruncado()), conversa_id=_CONV_ID)

    mock_escalar.assert_awaited_once()
    assert mock_escalar.await_args.kwargs["motivo"] == "modelo_truncado"
    enviados = [
        c for c in redis.enqueue_job.call_args_list if c.args and c.args[0] == "enviar_turno"
    ]
    assert enviados == []


async def test_motivo_modelo_truncado_mapeia_bucket_infra() -> None:
    """modelo_truncado -> handoff Fernando (tipo=outro) + metrica bucket=infra (mapping real)."""
    with (
        patch("barra.dominio.escaladas.service.abrir_handoff", new=AsyncMock()) as mock_handoff,
        patch("barra.workers.coordenador.AGENTE_ESCALADA") as mock_metric,
    ):
        await escalar_por_exaustao(_FakePool(), _ATEND_ID, "turno-stop03", motivo="modelo_truncado")

    mock_handoff.assert_awaited_once()
    assert mock_handoff.await_args.kwargs["observacao"] == "modelo_truncado"
    mock_metric.labels.assert_called_once_with("infra", "modelo_truncado")


# ============================================================================
# (b) validar_pix: vision com finish_reason=max_tokens/refusal -> DUVIDOSO
# ============================================================================


class _FakeVisionFinish:
    """AsyncOpenAI fake: choices[0] expoe finish_reason (como o provider real em 200 OK)."""

    def __init__(self, finish_reason: str, content: str | None) -> None:
        self.finish_reason = finish_reason
        self.content = content

        async def _create(**_: Any) -> Any:
            msg = SimpleNamespace(content=self.content)
            choice = SimpleNamespace(message=msg, finish_reason=self.finish_reason)
            return SimpleNamespace(choices=[choice])

        self.chat = SimpleNamespace(completions=SimpleNamespace(create=_create))


class _FakeMinio:
    JPEG = b"\xff\xd8\xff" + b"\x00" * 16

    def get_object(self, _bucket: str, _key: str) -> Any:
        dados = self.JPEG

        class _Resp:
            def read(self_inner: Any) -> bytes:
                return dados

            def close(self_inner: Any) -> None:
                return None

            def release_conn(self_inner: Any) -> None:
                return None

        return _Resp()


class _PixResult:
    def __init__(self, row: dict[str, Any]) -> None:
        self._row = row

    async def fetchone(self) -> dict[str, Any]:
        return self._row


class _PixConn:
    """Conn fake: registra os execute e devolve uma linha que serve tanto ao SELECT de contexto
    quanto ao INSERT ... RETURNING id (chaves combinadas num unico dict)."""

    def __init__(self) -> None:
        self.execs: list[tuple[str, Any]] = []
        self._row = {
            "media_object_key": "conversas/x/m/abc.jpg",
            "chave_pix_modelo": "modelo@pix.example",
            "titular_modelo": "Maria Silva",
            "id": uuid4(),
        }

    async def execute(self, query: str, params: Any = None) -> _PixResult:
        self.execs.append((query, params))
        return _PixResult(self._row)

    @asynccontextmanager
    async def transaction(self) -> Any:
        yield self


class _PixPool:
    def __init__(self, conn: _PixConn) -> None:
        self._conn = conn

    @asynccontextmanager
    async def connection(self) -> Any:
        yield self._conn


class _PixRedis:
    def __init__(self) -> None:
        self.jobs: list[tuple[str, dict[str, Any]]] = []

    async def enqueue_job(self, name: str, **kwargs: Any) -> None:
        self.jobs.append((name, kwargs))


@pytest.mark.parametrize("finish", ["length", "content_filter"])
async def test_validar_pix_finish_reason_inconclusivo_marca_duvidoso(finish: str) -> None:
    from barra.settings import get_settings

    conn = _PixConn()
    redis = _PixRedis()
    ctx = {
        "db_pool": _PixPool(conn),
        "minio": _FakeMinio(),
        "vision_client": _FakeVisionFinish(finish, content=""),
        "settings": get_settings(),
        "redis": redis,
    }

    with patch("barra.workers.pix.aplicar_comando", new=AsyncMock()) as mock_aplicar:
        # NUNCA trava: completa sem levantar (sem ValueError silencioso).
        await validar_pix(ctx, mensagem_id=str(uuid4()), atendimento_id=str(_ATEND_ID))

    # comprovante marcado DUVIDOSO (em_revisao) e fluxo avancado pela porta unica.
    mock_aplicar.assert_awaited_once()
    assert mock_aplicar.await_args.kwargs["comando"] == "atualizar_pix"
    assert mock_aplicar.await_args.kwargs["payload"]["decisao"] == "em_revisao"

    # o INSERT do comprovante gravou em_revisao com extracao vazia (vision nao extraiu).
    inserts = [p for q, p in conn.execs if "INSERT INTO barravips.comprovantes_pix" in q]
    assert len(inserts) == 1
    assert "em_revisao" in inserts[0]  # decisao_pipeline

    # card a modelo sinaliza a duvidez.
    cards = [k for n, k in redis.jobs if n == "enviar_card"]
    assert len(cards) == 1
    assert cards[0]["tipo"] == "pix_em_revisao"


@pytest.mark.parametrize(
    ("finish", "content"),
    [("length", '{"plausibilidade_visual": true}'), ("content_filter", ""), ("stop", "")],
)
async def test_extrair_via_openrouter_sinaliza_inconclusivo(finish: str, content: str) -> None:
    """finish_reason=max_tokens/refusal (ou content vazio) -> VisionInconclusiva, nunca ValueError."""
    client = _FakeVisionFinish(finish, content=content)
    with pytest.raises(VisionInconclusiva):
        await _extrair_via_openrouter(
            b"\xff\xd8\xff",
            media_type="image/jpeg",
            client=client,
            modelo="m",  # type: ignore[arg-type]
        )


async def test_extrair_via_openrouter_stop_valido_extrai() -> None:
    """finish_reason=stop com JSON valido -> ExtracaoPix (caminho feliz intacto)."""
    payload = ExtracaoPix(
        plausibilidade_visual=True, valor=Decimal("100.00"), confianca="alta"
    ).model_dump_json()
    client = _FakeVisionFinish("stop", content=payload)
    extracao = await _extrair_via_openrouter(
        b"\xff\xd8\xff",
        media_type="image/jpeg",
        client=client,
        modelo="m",  # type: ignore[arg-type]
    )
    assert extracao.plausibilidade_visual is True
    assert extracao.valor == Decimal("100.00")
