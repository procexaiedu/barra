"""Ressurreicao pela foto de portaria (ADR 0027): qual morte ela aceita.

Teste de query (sem banco, no espirito do `test_workers.py`): `FakeConn` captura o SQL do
candidato e devolve "nenhuma linha", entao a funcao so pode responder None. O que se afirma
e a CONDICAO, nao o efeito — os efeitos atomicos tem cobertura `needs_db` em
`tests/integracao/test_foto_portaria.py`.

Regressao pre-producao: a ressurreicao exigia `fonte_decisao_ultima_transicao =
'auto_timeout_interno'`, mas o `timeout_longo` (24h de silencio, `workers/timeouts.py`)
grava `auto_timeout`. Quando quem matava era esse cron, a foto de portaria que chegava
depois NAO ressuscitava — ficava orfa, com uma pessoa real na portaria e a modelo sem card.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

from barra.dominio.atendimentos.service import ressuscitar_interno_foto_portaria


class _Result:
    async def fetchone(self) -> None:
        return None


class _CapturaConn:
    """Captura o SQL do SELECT de candidato; sem candidato a funcao retorna None."""

    def __init__(self) -> None:
        self.query = ""

    @asynccontextmanager
    async def transaction(self) -> Any:
        yield

    async def execute(self, query: str, params: Any = None) -> _Result:
        self.query = query
        return _Result()


def _rodar() -> _CapturaConn:
    conn = _CapturaConn()
    resultado = asyncio.run(
        ressuscitar_interno_foto_portaria(
            conn,  # type: ignore[arg-type]
            conversa_id=uuid4(),
            mensagem_id=uuid4(),
            media_object_key="conversas/x/mensagens/y.jpg",
        )
    )
    assert resultado is None  # sem candidato -> caller segue fora-fluxo
    return conn


def test_ressurreicao_aceita_as_duas_fontes_de_timeout_automatico() -> None:
    conn = _rodar()
    assert "IN ('auto_timeout_interno', 'auto_timeout')" in conn.query


def test_ressurreicao_mantem_as_demais_guardas_do_adr_0027() -> None:
    """Alargar a fonte nao pode afrouxar o resto: interno, bloqueio cancelado, dentro do
    `b.fim` e slot livre (nao-sobreposicao) continuam sendo exigidos."""
    conn = _rodar()
    assert "a.tipo_atendimento = 'interno'" in conn.query
    assert "a.estado = 'Perdido'" in conn.query
    assert "b.estado = 'cancelado'" in conn.query
    assert "b.fim > now()" in conn.query
    assert "NOT EXISTS" in conn.query
    assert "&&" in conn.query  # sobreposicao de tstzrange contra bloqueios ativos
