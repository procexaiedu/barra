"""Handoff no meio do turno: a IA não pode falar por cima da modelo que já está assumindo.

Dois defeitos que se compunham (auditoria pré-produção 11/08):

1. `processar_turno` despachava com `ignorar_pausa=bool(pos["ia_pausada"])` — o bit do banco não
   distingue "este turno escalou de propósito" (a bolha de espera PRECISA sair) de "a foto de
   portaria chegou enquanto o output_guard rodava" (a bolha NÃO pode sair). Na janela entre o
   `post_process` (que lê `ia_pausada` antes do judge LLM do output_guard) e a releitura do passo
   6, o texto sobrevivia ao zeramento e ia ao cliente com o gate de pausa do fire DESARMADO.

2. `enviar_turno` só checava a pausa UMA vez, antes do laço de bolhas — cobertura no arquivo
   `tests/integracao/test_enviar_turno.py`.

Fakes no padrão de `test_per_05_refusal_escala.py`: sem DB (`_FakePool`), sem rede, sem LLM.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import UUID

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

from barra.dominio.atendimentos.service import MENSAGENS_GUARD_ESCALADA
from barra.workers.coordenador import pausa_aberta_por_este_turno, processar_turno

_ATEND_ID = UUID("00000000-0000-0000-0000-0000000000d1")
_MODELO_ID = UUID("00000000-0000-0000-0000-0000000000d2")
_CLIENTE_ID = UUID("00000000-0000-0000-0000-0000000000d3")
_CONV_ID = "00000000-0000-0000-0000-0000000000d4"

_USAGE = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}
_CANNED = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
_MSG_GUARD = sorted(MENSAGENS_GUARD_ESCALADA)[0]


# --- fakes de banco --------------------------------------------------------------------------


class _Result:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    async def fetchone(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None

    async def fetchall(self) -> list[dict[str, Any]]:
        return self._rows


class _FakeConn:
    """Responde as leituras do coordenador. `pausada_no_passo_6` é o estado que a RELEITURA do
    passo 6 encontra — o resolve do passo 1 devolve sempre `ia_pausada=False` (senão o gate do
    passo 2 abortaria o turno antes do grafo, que é o comportamento já existente e testado)."""

    def __init__(
        self, *, pausada_no_passo_6: bool, critico: bool = False, chave_pix: str | None = None
    ) -> None:
        self._pausada = pausada_no_passo_6
        self._critico = critico
        self._chave_pix = chave_pix

    async def execute(self, query: str, params: Any = None) -> _Result:
        # Turno CRITICO (registrar_extracao que transicionou ou pediu Pix) + a chave lida fresh do
        # cadastro: as duas queries que o resgate do descarte roda (`_SQL_TURNO_CRITICO`,
        # `_SQL_PIX_DO_TURNO`) e que o caminho normal ja rodava.
        if "resultado->>'novo_estado' IS NOT NULL" in query:
            return _Result([{"?column?": 1}] if self._critico else [])
        if "chave_pix" in query:
            return _Result(
                [{"chave_pix": self._chave_pix, "titular_chave": "Manu", "valor": "60"}]
                if self._chave_pix
                else []
            )
        if "FROM barravips.atendimentos" in query and "conversa_id" in query:
            return _Result(
                [
                    {
                        "id": _ATEND_ID,
                        "ia_pausada": False,
                        "estado": "Qualificado",
                        "modelo_id": _MODELO_ID,
                        "cliente_id": _CLIENTE_ID,
                        "conversa_id": UUID(_CONV_ID),
                    }
                ]
            )
        if "SELECT ia_pausada, estado" in query:  # passo 6 (cinto-suspensorio)
            return _Result([{"ia_pausada": self._pausada, "estado": "Qualificado"}])
        if "FROM barravips.mensagens" in query:  # inbound do read receipt
            return _Result(
                [
                    {
                        "evolution_message_id": "evo-1",
                        "conteudo": "to na portaria",
                        "created_at": None,
                    }
                ]
            )
        return _Result([])  # tool_calls (midias/critico), UPDATEs

    def transaction(self) -> _FakeConn:
        return self

    async def __aenter__(self) -> _FakeConn:
        return self

    async def __aexit__(self, *_a: Any) -> None:
        return None


class _FakePool:
    def connection(self) -> _FakeConn:
        return self._conn

    def __init__(self, conn: _FakeConn) -> None:
        self._conn = conn


class _FakeRedis:
    def __init__(self) -> None:
        self.enqueue_job = AsyncMock()
        self._dados: dict[str, Any] = {f"pending:conv:{_CONV_ID}": "1"}

    async def set(self, chave: str, valor: Any = "1", **_k: Any) -> bool:
        self._dados[chave] = valor
        return True

    async def delete(self, chave: str, *_a: Any, **_k: Any) -> None:
        self._dados.pop(chave, None)

    async def get(self, chave: str, *_a: Any, **_k: Any) -> Any:
        return self._dados.get(chave)


class _FakeGraph:
    def __init__(
        self, messages: list[BaseMessage], estado_extra: dict[str, Any] | None = None
    ) -> None:
        self._messages = messages
        self._extra = estado_extra or {}

    async def ainvoke(self, *_a: Any, **_k: Any) -> dict[str, Any]:
        return {"messages": list(self._messages), **self._extra}


class _FakeSettings:
    deepseek_model_chat = "deepseek-test"
    usd_brl_cotacao = 5.5
    pix_deslocamento_valor = 60
    # Teto do turno (asyncio.wait_for em volta do graph.ainvoke): virou setting em 12/08 p/
    # ficar acima do teto por chamada de LLM (`llm_timeout_s`).
    turno_timeout_s = 60.0


@asynccontextmanager
async def _lock_noop(*_a: Any, **_k: Any) -> Any:
    yield None


async def _rodar(
    messages: list[BaseMessage],
    *,
    pausada_no_passo_6: bool,
    critico: bool = False,
    chave_pix: str | None = None,
    estado_extra: dict[str, Any] | None = None,
) -> list[Any]:
    """Roda um turno e devolve as chamadas de `enviar_turno` enfileiradas."""
    redis = _FakeRedis()
    ctx = {
        "redis": redis,
        "db_pool": _FakePool(
            _FakeConn(pausada_no_passo_6=pausada_no_passo_6, critico=critico, chave_pix=chave_pix)
        ),
        "graph": _FakeGraph(messages, estado_extra),
        "settings": _FakeSettings(),
        "job_id": "job-pausa",
        "score": 4242,
    }
    with patch("barra.workers.coordenador.adquirir_lock", _lock_noop):
        await processar_turno(ctx, conversa_id=_CONV_ID)
    return [c for c in redis.enqueue_job.call_args_list if c.args and c.args[0] == "enviar_turno"]


def _bolha(texto: str) -> AIMessage:
    return AIMessage(content=texto, usage_metadata=_USAGE)  # type: ignore[arg-type]


def _escalou_com_sucesso() -> list[BaseMessage]:
    """Turno que ABRIU a própria pausa: bolha de espera + `escalar` que executou."""
    return [
        AIMessage(
            content="Deixa eu ver aqui amor",
            usage_metadata=_USAGE,  # type: ignore[arg-type]
            tool_calls=[
                {
                    "name": "escalar",
                    "args": {"motivo": "fora_de_oferta"},
                    "id": "tc-esc",
                    "type": "tool_call",
                }
            ],
        ),
        ToolMessage(content="Escalada aberta para a modelo.", tool_call_id="tc-esc"),
    ]


# --- (1) pausa EXTERNA no meio do turno ------------------------------------------------------


async def test_pausa_externa_no_meio_do_turno_nao_despacha_bolha() -> None:
    """Foto de portaria (ou Pix, ou pausa manual) commitou `ia_pausada=true` DEPOIS do
    `post_process` e antes da releitura do passo 6: o texto sobreviveu ao zeramento, mas a modelo
    já está indo atender — nada pode sair."""
    envios = await _rodar([_bolha("me manda a foto da portaria amor")], pausada_no_passo_6=True)
    assert envios == []


async def test_pausa_externa_com_texto_e_midia_tambem_e_descartada() -> None:
    """O descarte é do TURNO, não só da bolha: sem isso a mídia sairia por cima da modelo."""
    envios = await _rodar(
        [_bolha("olha essa foto amor"), _bolha("chego já")], pausada_no_passo_6=True
    )
    assert envios == []


async def test_escalar_que_falhou_nao_isenta_do_gate() -> None:
    """Fail-safe: `escalar` com erro recuperável NÃO abriu pausa nenhuma — se `ia_pausada` está
    de pé, a pausa veio de fora e o turno cala (na dúvida, não enviar)."""
    messages: list[BaseMessage] = [
        AIMessage(
            content="Deixa eu ver aqui amor",
            usage_metadata=_USAGE,  # type: ignore[arg-type]
            tool_calls=[
                {"name": "escalar", "args": {}, "id": "tc-erro", "type": "tool_call"},
            ],
        ),
        ToolMessage(content="ERRO: nao deu", tool_call_id="tc-erro", status="error"),
        _bolha("consigo sim amor"),
    ]
    assert await _rodar(messages, pausada_no_passo_6=True) == []


# --- (2) pausa aberta PELO PRÓPRIO TURNO: a canned de espera tem de sair ----------------------


async def test_turno_que_escalou_despacha_com_ignorar_pausa() -> None:
    envios = await _rodar(_escalou_com_sucesso(), pausada_no_passo_6=True)
    assert len(envios) == 1
    assert envios[0].kwargs["chunks"] == ["Deixa eu ver aqui amor"]
    assert envios[0].kwargs["ignorar_pausa"] is True


async def test_escalada_silenciosa_da_guarda_despacha_a_canned() -> None:
    """Guarda de `registrar_extracao` (piso de desconto / tipo não aceito / reagendamento) escala
    por dentro: o `post_process` solta a canned de espera e ela TEM de chegar ao cliente."""
    messages: list[BaseMessage] = [
        AIMessage(
            content="",
            usage_metadata=_USAGE,  # type: ignore[arg-type]
            tool_calls=[
                {"name": "registrar_extracao", "args": {}, "id": "tc-ext", "type": "tool_call"}
            ],
        ),
        ToolMessage(content=_MSG_GUARD, tool_call_id="tc-ext"),
        AIMessage(content="Deixa eu ver aqui amor", usage_metadata=_CANNED),  # type: ignore[arg-type]
    ]
    envios = await _rodar(messages, pausada_no_passo_6=True)
    assert len(envios) == 1
    assert envios[0].kwargs["ignorar_pausa"] is True


# --- (3) caminho feliz: nada disso pode mexer no turno normal ---------------------------------


async def test_caminho_feliz_despacha_normalmente_sem_isencao() -> None:
    """IA não pausada: a bolha sai, e sai COM o gate de pausa do fire armado (`ignorar_pausa`
    False) — a isenção é exceção, não default."""
    envios = await _rodar([_bolha("consigo sim amor")], pausada_no_passo_6=False)
    assert len(envios) == 1
    assert envios[0].kwargs["chunks"] == ["consigo sim amor"]
    assert envios[0].kwargs["ignorar_pausa"] is False


async def test_caminho_feliz_de_turno_que_escalou_mas_devolveram() -> None:
    """Escalou e alguém devolveu para a IA no mesmo intervalo (`ia_pausada=false` no passo 6):
    despacha com o gate ARMADO — não há pausa própria de pé para isentar."""
    envios = await _rodar(_escalou_com_sucesso(), pausada_no_passo_6=False)
    assert len(envios) == 1
    assert envios[0].kwargs["ignorar_pausa"] is False


# --- (4) o descarte não pode ENGOLIR o turno crítico (loop-massa r3, achado 6) ----------------


async def test_turno_descartado_ainda_despacha_a_bolha_critica_do_pix() -> None:
    """`decidido_rapido_a` t5: a extração pediu o Pix (turno CRÍTICO), o output_guard reprovou o
    texto e pausou a IA — e o descarte levava junto a bolha determinística da chave, que o sistema
    já tinha prometido no banco. O cliente que ACABOU de fechar recebia zero mensagens.

    O que sai aqui é só a bolha do SISTEMA (chave lida fresh do cadastro), nunca o texto do
    modelo — que continua zerado."""
    envios = await _rodar(
        [_bolha("")],  # guard zerou o texto
        pausada_no_passo_6=True,
        critico=True,
        chave_pix="manu@pix.com",
        estado_extra={"_pausa_aberta_pelo_guard": True},
    )
    assert len(envios) == 1
    assert envios[0].kwargs["chunks"] == [
        "chave pix: manu@pix.com\nem nome de Manu\nvalor: R$60"
    ]
    assert envios[0].kwargs["critico"] is True
    assert envios[0].kwargs["ignorar_pausa"] is True


async def test_turno_descartado_critico_sem_chave_nao_inventa_bolha() -> None:
    """Crítico por transição de estado, sem Pix pedido: não há bolha determinística a resgatar — e
    o texto do modelo continua barrado (nada sai)."""
    envios = await _rodar([_bolha("")], pausada_no_passo_6=True, critico=True, chave_pix=None)
    assert envios == []


async def test_pausa_do_guard_nao_e_logada_como_externa(caplog: Any) -> None:
    """`_bloquear` escala direto no banco, sem tocar em `messages`: sem o carimbo do State o
    coordenador classificava a pausa do PRÓPRIO grafo como externa e o log mandava o operador
    procurar um pipeline que não pausou nada."""
    import logging

    with caplog.at_level(logging.INFO, logger="barra.workers.coordenador"):
        await _rodar(
            [_bolha("")], pausada_no_passo_6=True, estado_extra={"_pausa_aberta_pelo_guard": True}
        )
    descartes = [r.getMessage() for r in caplog.records if "turno_descartado" in r.getMessage()]
    assert descartes and all("pausa_externa=False" in m for m in descartes)


async def test_sem_carimbo_a_pausa_segue_classificada_como_externa(caplog: Any) -> None:
    """Contraprova do teste acima: sem carimbo (pausa que veio mesmo de fora) o log não muda."""
    import logging

    with caplog.at_level(logging.INFO, logger="barra.workers.coordenador"):
        await _rodar([_bolha("me manda a foto amor")], pausada_no_passo_6=True)
    descartes = [r.getMessage() for r in caplog.records if "turno_descartado" in r.getMessage()]
    assert descartes and all("pausa_externa=True" in m for m in descartes)


# --- predicado isolado ------------------------------------------------------------------------


def test_predicado_reconhece_escalar_e_guarda_e_ignora_o_resto() -> None:
    assert pausa_aberta_por_este_turno(_escalou_com_sucesso()) is True
    assert pausa_aberta_por_este_turno([ToolMessage(content=_MSG_GUARD, tool_call_id="x")]) is True
    assert pausa_aberta_por_este_turno([_bolha("oi amor")]) is False
    assert pausa_aberta_por_este_turno([]) is False
