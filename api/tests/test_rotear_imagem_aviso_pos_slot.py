"""Imagem que chega DEPOIS do fim do slot reservado vira AVISO, não silêncio.

Resquício encontrado na auditoria pré-produção: com o `bloqueio.fim` já passado, a ressurreição
do ADR 0027 (corretamente) não se aplica — a volta é recorrência legítima. Só que o que acontecia
em vez dela era `ROTEAR_IMAGEM_DECISAO.labels("silencio")`: nenhum card, nenhum aviso. Se o
cliente chegou atrasado, há uma PESSOA na portaria da modelo e ela não fica sabendo; se mandou um
Pix em cima da hora, o comprovante fica órfão.

Estes testes rodam SEM banco (`_FakeConn` no estilo de `test_rel_08_...`), porque o gate default
(`-m "not needs_key and not needs_db"`) é o que roda em toda máquina. A cobertura contra o schema
real (a query do candidato, as guardas de janela) vive em `tests/integracao/test_foto_portaria.py`.

Os quatro dentes:
  - foto tardia depois do timeout automático -> escalada owner=modelo + card no grupo;
  - imagem aleatória em conversa sem esse rastro -> NADA (anti-ruído: card demais treina a
    modelo a não ler card);
  - foto dentro do fluxo (atendimento vivo, interno) -> handoff normal, sem regressão e sem
    sequer consultar o candidato do aviso;
  - modelo sem `coordenacao_chat_id` (estado da Catarina em prod hoje) -> degrada com log de
    ERROR, sem gravar escalada que o `reconciliar_cards` moeria em loop.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from fakeredis.aioredis import FakeRedis
from prometheus_client import REGISTRY

from barra.settings import get_settings
from barra.workers.media import rotear_imagem

_METRICA = "agente_rotear_imagem_decisao_total"

# Assinatura da query do candidato ao aviso. `b.fim <= now()` e' o que a separa da ressurreicao
# do ADR 0027 (`b.fim > now()`): os dois ramos sao disjuntos por construcao. Casar por substring
# em vez de importar a constante mantem os testes de nao-regressao (anti-ruido, fluxo normal)
# rodaveis contra a versao ANTERIOR do modulo — sao invariantes, nao dentes novos.
_MARCA_CANDIDATO_AVISO = "AND b.fim <= now()"

# Marcador gravado em `escaladas.observacao` — contrato PERSISTIDO (da a idempotencia do aviso),
# entao o teste crava o literal em vez de reimportar a constante.
_OBS_IMAGEM_POS_SLOT = "imagem_pos_slot"


def _decisoes(label: str) -> float:
    valor = REGISTRY.get_sample_value(_METRICA, {"decisao": label})
    return float(valor or 0.0)


class _Resultado:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    async def fetchone(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None

    async def fetchall(self) -> list[dict[str, Any]]:
        return self._rows


class _FakeConn:
    """Conexão fake que despacha por query. Só as leituras de que o roteamento depende devolvem
    linha; todo o resto (UPDATEs, INSERTs de evento) é no-op, como no banco vazio."""

    def __init__(
        self,
        *,
        atendimento_aberto: dict[str, Any] | None = None,
        mensagem_uuid: UUID | None = None,
        candidato_aviso: dict[str, Any] | None = None,
    ) -> None:
        self._atendimento_aberto = atendimento_aberto
        self._mensagem_uuid = mensagem_uuid
        self._candidato_aviso = candidato_aviso
        self.escalada_id = uuid4()
        self.queries: list[str] = []
        self.escaladas_inseridas: list[Any] = []

    async def execute(self, query: str, params: Any = None) -> _Resultado:
        self.queries.append(query)
        if _MARCA_CANDIDATO_AVISO in query:
            return _Resultado([self._candidato_aviso] if self._candidato_aviso else [])
        if "INSERT INTO barravips.escaladas" in query:
            self.escaladas_inseridas.append(params)
            return _Resultado([{"id": self.escalada_id}])
        if "evolution_message_id = %s" in query:
            return _Resultado([{"id": self._mensagem_uuid}] if self._mensagem_uuid else [])
        if "estado NOT IN ('Fechado', 'Perdido')" in query:
            return _Resultado([self._atendimento_aberto] if self._atendimento_aberto else [])
        if "media_object_key FROM barravips.mensagens" in query:
            return _Resultado([{"media_object_key": "conversas/x/foto.jpg"}])
        return _Resultado([])

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        yield None


class _FakePool:
    def __init__(self, conn: _FakeConn) -> None:
        self._conn = conn

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[_FakeConn]:
        yield self._conn


def _redis_fake() -> FakeRedis:
    redis = FakeRedis()
    redis.enqueue_job = AsyncMock()  # FakeRedis nao tem enqueue_job
    return redis


def _ctx(conn: _FakeConn, redis: FakeRedis) -> dict[str, Any]:
    return {"redis": redis, "db_pool": _FakePool(conn), "settings": get_settings()}


def _candidato(*, coordenacao_chat_id: str | None = "grupo@g.us") -> dict[str, Any]:
    """Linha que `_SQL_CANDIDATO_AVISO_POS_SLOT` devolve: interno morto por timeout automático
    cujo `bloqueio.fim` acabou de passar."""
    return {"atendimento_id": uuid4(), "coordenacao_chat_id": coordenacao_chat_id}


async def test_foto_tardia_apos_timeout_avisa_a_modelo() -> None:
    """Slot já terminado + morte por timeout automático: abre escalada owner=modelo e enfileira
    o card no grupo. Sem isso, uma pessoa real fica na portaria e ninguém sabe."""
    conn = _FakeConn(mensagem_uuid=uuid4(), candidato_aviso=_candidato())
    redis = _redis_fake()
    conversa_id = str(uuid4())
    antes = _decisoes("aviso_pos_slot")

    await rotear_imagem(
        _ctx(conn, redis),
        mensagem_id="evo-msg-1",
        conversa_id=conversa_id,
        media_url="https://evolution.test/portaria.jpg",
        caption=None,
    )

    # 1. Escalada gravada com o marcador de idempotência, owner=modelo (owner=Fernando não vai
    #    ao grupo — `card_escalada_vai_ao_grupo`).
    assert len(conn.escaladas_inseridas) == 1
    params = conn.escaladas_inseridas[0]
    assert params[0] == conn._candidato_aviso["atendimento_id"]  # type: ignore[index]
    assert params[-1] == _OBS_IMAGEM_POS_SLOT
    insert = next(q for q in conn.queries if "INSERT INTO barravips.escaladas" in q)
    assert "'modelo', 'outro'" in insert

    # 2. Card no grupo, pela maquinaria que já existe (`enviar_card` tipo='escalada'), com
    #    _job_id estável (dedupe nativo do ARQ).
    calls = redis.enqueue_job.call_args_list
    assert len(calls) == 1
    assert calls[0].args == ("enviar_card",)
    assert calls[0].kwargs["tipo"] == "escalada"
    assert calls[0].kwargs["escalada_id"] == str(conn.escalada_id)
    assert calls[0].kwargs["_job_id"] == f"card:escalada:{conn.escalada_id}"

    # 3. Observabilidade: a decisão deixou de ser 'silencio'.
    assert _decisoes("aviso_pos_slot") == antes + 1


async def test_imagem_aleatoria_sem_rastro_de_slot_nao_avisa() -> None:
    """Anti-ruído: selfie/meme no meio de conversa comum, sem atendimento morto por timeout com
    slot recém-terminado, continua em SILÊNCIO. Card demais treina a modelo a ignorar card."""
    conn = _FakeConn(mensagem_uuid=uuid4(), candidato_aviso=None)
    redis = _redis_fake()
    antes = _decisoes("silencio")

    await rotear_imagem(
        _ctx(conn, redis),
        mensagem_id="evo-msg-2",
        conversa_id=str(uuid4()),
        media_url="https://evolution.test/meme.jpg",
        caption=None,
    )

    assert conn.escaladas_inseridas == []
    assert redis.enqueue_job.call_args_list == []
    assert _decisoes("silencio") == antes + 1


async def test_foto_dentro_do_fluxo_segue_no_handoff_normal() -> None:
    """Não-regressão: atendimento interno VIVO em Aguardando_confirmacao continua no handoff
    implícito (card 'chegada'), e o ramo do aviso nem é consultado."""
    conn = _FakeConn(
        atendimento_aberto={
            "id": uuid4(),
            "estado": "Aguardando_confirmacao",
            "pix_status": "nao_solicitado",
            "tipo_atendimento": "interno",
        },
        mensagem_uuid=uuid4(),
        candidato_aviso=_candidato(),  # existe candidato, mas nao deve ser sequer consultado
    )
    redis = _redis_fake()

    await rotear_imagem(
        _ctx(conn, redis),
        mensagem_id="evo-msg-3",
        conversa_id=str(uuid4()),
        media_url="https://evolution.test/portaria.jpg",
        caption=None,
    )

    calls = redis.enqueue_job.call_args_list
    assert len(calls) == 1
    assert calls[0].kwargs["tipo"] == "chegada"
    assert all(_MARCA_CANDIDATO_AVISO not in q for q in conn.queries)


async def test_sem_grupo_de_coordenacao_degrada_sem_escalada_orfa(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """`coordenacao_chat_id` NULL (estado da Catarina em prod): não há para onde mandar o card.

    Degrada explicitamente (log de ERROR + label próprio) e NÃO grava a escalada — uma escalada
    owner=modelo sem `card_message_id` faria o cron `reconciliar_cards` re-tentar a cada minuto
    contra `remote_jid=None`, virando AttributeError em loop infinito.
    """
    conn = _FakeConn(mensagem_uuid=uuid4(), candidato_aviso=_candidato(coordenacao_chat_id=None))
    redis = _redis_fake()
    antes = _decisoes("aviso_pos_slot_sem_grupo")

    with caplog.at_level(logging.ERROR, logger="barra.workers.media"):
        await rotear_imagem(
            _ctx(conn, redis),
            mensagem_id="evo-msg-4",
            conversa_id=str(uuid4()),
            media_url="https://evolution.test/portaria.jpg",
            caption=None,
        )

    assert conn.escaladas_inseridas == []
    assert redis.enqueue_job.call_args_list == []
    assert any("aviso_imagem_pos_slot_sem_grupo" in r.getMessage() for r in caplog.records)
    assert _decisoes("aviso_pos_slot_sem_grupo") == antes + 1


async def test_foto_tardia_com_legenda_avisa_e_ainda_responde() -> None:
    """A legenda não engole o aviso: a IA responde ao texto (fora-fluxo com legenda) E a modelo
    recebe o card. Chegar atrasado dizendo "cheguei" é o caso MAIS provável de gente na porta."""
    conn = _FakeConn(mensagem_uuid=uuid4(), candidato_aviso=_candidato())
    redis = _redis_fake()

    await rotear_imagem(
        _ctx(conn, redis),
        mensagem_id="evo-msg-5",
        conversa_id=str(uuid4()),
        media_url="https://evolution.test/portaria.jpg",
        caption="cheguei, to na portaria",
    )

    jobs = [c.args[0] for c in redis.enqueue_job.call_args_list]
    assert "enviar_card" in jobs
    assert "processar_turno" in jobs
