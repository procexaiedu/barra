"""Testes unit do canário de entrega fim-a-fim (workers/canario) — sem Evolution, sem DB, sem rede.

FakeConn responde se a linha do eco existe em `barravips.mensagens`; FakeRedis implementa só o
hash de pendentes; FakeEvolution devolve/estoura o id da sonda. O Telegram é a única saída de rede
e vai por `respx` (httpx real, host mockado): é o canal FORA da Evolution, então o teste garante
que ele sai mesmo — e que uma falha dele não derruba o ciclo.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx
from prometheus_client import REGISTRY

from barra.settings import get_settings
from barra.workers.canario import (
    CHAVE_PENDENTES,
    canario_ligado,
    minutos_do_intervalo,
    rodar_canario,
)

TELEGRAM_URL = "https://api.telegram.org/botTOK/sendMessage"


class _Result:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    async def fetchone(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None


class FakeConn:
    """`eco_de` = ids cujo eco fromMe já virou linha em barravips.mensagens."""

    def __init__(self, eco_de: set[str] | None = None) -> None:
        self.eco_de = eco_de or set()
        self.consultados: list[str] = []

    async def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> _Result:
        assert "FROM barravips.mensagens" in sql, sql
        assert params is not None
        message_id = str(params[0])
        self.consultados.append(message_id)
        return _Result([{"?column?": 1}] if message_id in self.eco_de else [])


class FakeRedis:
    def __init__(self, pendentes: dict[str, str] | None = None) -> None:
        # bytes de propósito: ArqRedis não decodifica respostas.
        self.hash: dict[bytes, bytes] = {
            k.encode(): v.encode() for k, v in (pendentes or {}).items()
        }

    async def hgetall(self, chave: str) -> dict[bytes, bytes]:
        assert chave == CHAVE_PENDENTES
        return dict(self.hash)

    async def hdel(self, chave: str, campo: str) -> int:
        return 1 if self.hash.pop(campo.encode(), None) is not None else 0

    async def hset(self, chave: str, campo: str, valor: str) -> int:
        self.hash[campo.encode()] = valor.encode()
        return 1

    @property
    def pendentes(self) -> dict[str, str]:
        return {k.decode(): v.decode() for k, v in self.hash.items()}


class FakeEvolution:
    def __init__(self, resultado: Any = "MSG-NOVA") -> None:
        self.resultado = resultado
        self.enviados: list[dict[str, Any]] = []

    async def enviar_texto_avulso(self, **kwargs: Any) -> str | None:
        self.enviados.append(kwargs)
        if isinstance(self.resultado, Exception):
            raise self.resultado
        return self.resultado


def _settings(**over: Any) -> Any:
    base = {
        "canario_jid": "5519999990000@s.whatsapp.net",
        "canario_instance_id": "elitebaby01",
        "canario_prazo_eco_min": 10,
        "canario_telegram_token": "TOK",
        "canario_telegram_chat_id": "-100999",
    }
    base.update(over)
    return get_settings().model_copy(update=base)


def _contador(resultado: str) -> float:
    return REGISTRY.get_sample_value("barra_canario_entrega_total", {"resultado": resultado}) or 0.0


def _gauge() -> float | None:
    return REGISTRY.get_sample_value("barra_canario_entrega_ok")


# --------------------------------------------------------------------------- desligado


async def test_desligado_por_default_nao_toca_nada() -> None:
    """Default de produção: JID e instância vazios = inofensivo, sem I/O nenhum."""
    settings = get_settings().model_copy(update={"canario_jid": "", "canario_instance_id": ""})
    assert canario_ligado(settings) is False
    conn, redis, evolution = FakeConn(), FakeRedis(), FakeEvolution()

    assert await rodar_canario(conn, redis, evolution, settings) == 0  # type: ignore[arg-type]

    assert evolution.enviados == []
    assert conn.consultados == []
    assert redis.pendentes == {}


async def test_jid_sem_instancia_continua_desligado() -> None:
    """Meia configuração não liga o canário: sem instância não há de onde a sonda sair."""
    assert canario_ligado(_settings(canario_instance_id="")) is False


# --------------------------------------------------------------------------- ciclo feliz


async def test_envia_sonda_e_registra_pendente() -> None:
    conn, redis, evolution = FakeConn(), FakeRedis(), FakeEvolution("MSG-1")

    assert await rodar_canario(conn, redis, evolution, _settings()) == 0  # type: ignore[arg-type]

    assert evolution.enviados[0]["instance_id"] == "elitebaby01"
    assert evolution.enviados[0]["remote_jid"] == "5519999990000@s.whatsapp.net"
    assert evolution.enviados[0]["texto"].startswith("canario barra ")
    assert list(redis.pendentes) == ["MSG-1"]


async def test_eco_recebido_conta_ok_e_limpa_pendente() -> None:
    antes = _contador("ok")
    conn = FakeConn(eco_de={"MSG-ANTIGA"})
    redis = FakeRedis({"MSG-ANTIGA": "1000.0"})

    falhas = await rodar_canario(conn, redis, FakeEvolution("MSG-2"), _settings())  # type: ignore[arg-type]

    assert falhas == 0
    assert _contador("ok") == antes + 1
    assert _gauge() == 1.0
    # o pendente resolvido saiu; só o da sonda nova ficou
    assert list(redis.pendentes) == ["MSG-2"]


async def test_pendente_dentro_do_prazo_nao_julga() -> None:
    """Sonda recém-enviada sem eco ainda não é veredito — nem alerta nem mexe no gauge."""
    import time

    antes_ok, antes_sem = _contador("ok"), _contador("sem_eco")
    redis = FakeRedis({"MSG-RECENTE": str(time.time())})

    falhas = await rodar_canario(FakeConn(), redis, FakeEvolution("MSG-3"), _settings())  # type: ignore[arg-type]

    assert falhas == 0
    assert (_contador("ok"), _contador("sem_eco")) == (antes_ok, antes_sem)
    assert set(redis.pendentes) == {"MSG-RECENTE", "MSG-3"}


# --------------------------------------------------------------------------- falha (o caso real)


@respx.mock
async def test_sem_eco_apos_prazo_alerta_metrica_log_e_telegram(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """O modo de falha do apagão 24-27/07: a Evolution aceita e o eco nunca volta."""
    rota = respx.post(TELEGRAM_URL).mock(return_value=httpx.Response(200, json={"ok": True}))
    antes = _contador("sem_eco")
    # 1000.0 epoch = 1970: qualquer prazo já venceu.
    redis = FakeRedis({"MSG-PERDIDA": "1000.0"})

    with caplog.at_level("ERROR"):
        falhas = await rodar_canario(FakeConn(), redis, FakeEvolution("MSG-4"), _settings())  # type: ignore[arg-type]

    assert falhas == 1
    assert _contador("sem_eco") == antes + 1
    assert _gauge() == 0.0
    assert "CANARIO_ENTREGA sem_eco" in caplog.text
    assert rota.called
    corpo = rota.calls[0].request.content.decode()
    assert "MSG-PERDIDA" in corpo and "-100999" in corpo
    assert list(redis.pendentes) == ["MSG-4"]  # o vencido saiu, a sonda nova entrou


@respx.mock
async def test_envio_falhou_alerta_sem_propagar_excecao() -> None:
    """Falha no POST /send/text é sinal, não crash: o cron devolve contagem, não levanta (ARQ só
    retenta em Retry explícito — retentar aqui só mascararia o apagão)."""
    respx.post(TELEGRAM_URL).mock(return_value=httpx.Response(200, json={"ok": True}))
    antes = _contador("envio_falhou")
    redis = FakeRedis()

    falhas = await rodar_canario(
        FakeConn(),  # type: ignore[arg-type]
        redis,  # type: ignore[arg-type]
        FakeEvolution(httpx.ConnectError("evolution fora")),  # type: ignore[arg-type]
        _settings(),
    )

    assert falhas == 1
    assert _contador("envio_falhou") == antes + 1
    assert _gauge() == 0.0
    assert redis.pendentes == {}


@respx.mock
async def test_telegram_caido_nao_derruba_o_ciclo(caplog: pytest.LogCaptureFixture) -> None:
    """O canal de alerta é best-effort: se ele cair, métrica e log ERROR continuam de pé."""
    respx.post(TELEGRAM_URL).mock(side_effect=httpx.ConnectError("telegram fora"))
    redis = FakeRedis({"MSG-X": "1000.0"})

    with caplog.at_level("ERROR"):
        falhas = await rodar_canario(FakeConn(), redis, FakeEvolution("MSG-5"), _settings())  # type: ignore[arg-type]

    assert falhas == 1
    assert "CANARIO_ENTREGA sem_eco" in caplog.text


@respx.mock
async def test_sem_token_telegram_so_metrica_e_log(caplog: pytest.LogCaptureFixture) -> None:
    """Default dos envs do Telegram (vazio): degrada para métrica + log, sem tocar a rede."""
    rota = respx.post(TELEGRAM_URL).mock(return_value=httpx.Response(200))
    redis = FakeRedis({"MSG-Y": "1000.0"})

    with caplog.at_level("ERROR"):
        await rodar_canario(
            FakeConn(),  # type: ignore[arg-type]
            redis,  # type: ignore[arg-type]
            FakeEvolution("MSG-6"),  # type: ignore[arg-type]
            _settings(canario_telegram_token="", canario_telegram_chat_id=""),
        )

    assert not rota.called
    assert "CANARIO_ENTREGA sem_eco" in caplog.text


# --------------------------------------------------------------------------- agenda do cron


@pytest.mark.parametrize(
    ("intervalo", "esperado"),
    [
        (60, {0}),
        (30, {0, 30}),
        (15, {0, 15, 30, 45}),
        (1, set(range(60))),
    ],
)
def test_minutos_do_intervalo(intervalo: int, esperado: set[int]) -> None:
    assert minutos_do_intervalo(intervalo) == esperado


def test_cron_canario_registrado() -> None:
    from barra.workers.settings import WorkerSettings

    assert "canario" in {job.name for job in WorkerSettings.cron_jobs}
