"""Testes unit do digest semanal (workers/digest_semanal) — sem DB, sem Evolution real.

FakeConn roteia por substring do SQL (agregados canned); FakeEvolution captura o card.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any

from barra.settings import get_settings
from barra.workers.digest_semanal import enviar_digest_semanal

MODELO = {
    "id": "33333333-3333-4333-8333-333333333333",
    "nome": "Larissa",
    "evolution_instance_id": "inst-1",
    "coordenacao_chat_id": "grupo@g.us",
}


class _Result:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    async def fetchall(self) -> list[dict[str, Any]]:
        return self._rows

    async def fetchone(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None


class FakeConn:
    def __init__(
        self,
        *,
        modelos: list[dict[str, Any]] | None = None,
        ja_enviado: bool = False,
    ) -> None:
        self.modelos = modelos if modelos is not None else [MODELO]
        self.ja_enviado = ja_enviado
        self.params_handoffs: Any = None

    async def execute(self, sql: str, params: Any = None) -> _Result:
        if "FROM barravips.modelos" in sql:
            return _Result(self.modelos)
        if "FROM barravips.envios_evolution" in sql:
            return _Result([{"ok": 1}] if self.ja_enviado else [])
        if "count(DISTINCT m.conversa_id)" in sql:
            return _Result([{"n": 9}])
        if "FROM barravips.atendimentos\n WHERE modelo_id" in sql:
            return _Result([{"n": 5}])
        if "fechado_registrado" in sql:
            return _Result([{"n": 3, "total": Decimal("1250.00")}])
        if "FROM barravips.escaladas" in sql:
            self.params_handoffs = params
            return _Result([{"total": 4, "contidos": 2}])
        raise AssertionError(f"SQL inesperado: {sql}")


class FakeEvolution:
    def __init__(self) -> None:
        self.enviados: list[dict[str, Any]] = []

    async def enviar_texto(self, **kw: Any) -> str:
        self.enviados.append(kw)
        return "msg-1"


def _settings(**over: Any) -> Any:
    return get_settings().model_copy(update={"digest_semanal_ativo": True, **over})


def test_flag_off_nao_envia() -> None:
    evolution = FakeEvolution()
    total = asyncio.run(
        enviar_digest_semanal(FakeConn(), evolution, _settings(digest_semanal_ativo=False))
    )
    assert total == 0 and evolution.enviados == []


def test_sem_modelo_ativa_nao_envia() -> None:
    evolution = FakeEvolution()
    total = asyncio.run(enviar_digest_semanal(FakeConn(modelos=[]), evolution, _settings()))
    assert total == 0 and evolution.enviados == []


def test_ja_enviado_na_semana_pula() -> None:
    evolution = FakeEvolution()
    total = asyncio.run(enviar_digest_semanal(FakeConn(ja_enviado=True), evolution, _settings()))
    assert total == 0 and evolution.enviados == []


def test_envia_card_no_grupo_da_modelo() -> None:
    evolution = FakeEvolution()
    total = asyncio.run(enviar_digest_semanal(FakeConn(), evolution, _settings()))

    assert total == 1
    envio = evolution.enviados[0]
    # canal = grupo de Coordenação DA modelo, tipo card (não passa por humanização)
    assert envio["instance_id"] == "inst-1"
    assert envio["remote_jid"] == "grupo@g.us"
    assert envio["contexto"] == "grupo_coordenacao" and envio["tipo"] == "card"
    assert envio["payload"] == {"card_kind": "digest_semanal", "modelo_id": MODELO["id"]}

    texto = envio["texto"]
    assert "Larissa" in texto
    assert "Conversas com cliente: *9*" in texto
    assert "Atendimentos novos: *5*" in texto
    assert "Fechados: *3*" in texto and "R$" in texto
    assert "Handoffs abertos: *4*" in texto
    assert "Incidentes contidos pelo sistema: *2*" in texto
    # score do judge NUNCA entra no card (telemetria dev; o grupo é lido pela modelo)
    assert "voz" not in texto and "/5" not in texto


def test_filtro_de_contidos_deriva_do_bucket_defesa_canonico() -> None:
    """A taxonomia de defesa não é re-declarada: vem de escaladas/service._BUCKET_DEFESA,
    com `_` escapado (wildcard do LIKE) e prefixo % (a observacao persistida é granular)."""
    from barra.dominio.escaladas.service import _BUCKET_DEFESA
    from barra.workers.digest_semanal import _prefixos_defesa

    prefixos = _prefixos_defesa()
    assert len(prefixos) == len(_BUCKET_DEFESA)
    assert r"output\_leak%" in prefixos  # casa output_leak_ia_self
    assert r"envio\_leak%" in prefixos  # rede final do envio também é defesa contida
    assert r"cross\_modelo\_fishing%" in prefixos  # defesa do isolamento por par
    evolution = FakeEvolution()
    conn = FakeConn()
    asyncio.run(enviar_digest_semanal(conn, evolution, _settings()))
    assert conn.params_handoffs["defesa"] == prefixos


def test_falha_de_um_envio_nao_aborta_o_lote() -> None:
    outro = {**MODELO, "id": "44444444-4444-4444-8444-444444444444", "nome": "Bia"}

    class _EvolutionFalhaPrimeiro(FakeEvolution):
        async def enviar_texto(self, **kw: Any) -> str:
            if not self.enviados and "Larissa" in kw["texto"]:
                self.enviados.append({"falhou": True})
                raise RuntimeError("evolution 500")
            return await super().enviar_texto(**kw)

    evolution = _EvolutionFalhaPrimeiro()
    conn = FakeConn(modelos=[MODELO, outro])
    total = asyncio.run(enviar_digest_semanal(conn, evolution, _settings()))
    assert total == 1
    assert any("Bia" in e.get("texto", "") for e in evolution.enviados)
