"""needs_db — `fechar_via_comprovante` contra o Postgres real (auto-baixa por comprovante de Pix).

Verifica o caminho de fechamento REAL: com o valor lido no OCR, o atendimento em `Em_execucao`
vira `Fechado` com `valor_final`, `forma_pagamento='pix'` e o evento `fechado_registrado`
(data-ancora do modulo Financeiro) — o mesmo efeito do `fechado [valor]` de texto, so que o valor
vem do comprovante. Vision + MinIO + Evolution mockados; so o Postgres e real, com ROLLBACK no
teardown (o `DATABASE_URL` pode ser prod self-hosted — nunca commita).

Cobre 3 cenarios: (a) fecha com o valor lido; (b) atendimento ja `Fechado` -> no-op (dedup/2a
foto); (c) OCR sem valor legivel -> nao fecha (nao fabrica valor_final).
"""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from barra.workers.comprovante_fechamento import fechar_via_comprovante
from barra.workers.pix import ExtracaoPix

# --- infra de DB real (ROLLBACK sempre) ----------------------------------------------------------


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


class _PoolDeUmaConexao:
    """Pool fake que sempre devolve a conexao da fixture (mantem tudo na MESMA transacao)."""

    def __init__(self, connection: AsyncConnection[dict[str, Any]]) -> None:
        self._conn = connection

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[AsyncConnection[dict[str, Any]]]:
        yield self._conn


class _FakeMinio:
    JPEG_MAGIC = b"\xff\xd8\xff" + b"\x00" * 16

    def get_object(self, _bucket: str, _key: str) -> Any:
        outer = self

        class _Resp:
            def read(self_inner: Any) -> bytes:
                return outer.JPEG_MAGIC

            def close(self_inner: Any) -> None:
                return None

            def release_conn(self_inner: Any) -> None:
                return None

        return _Resp()


class _FakeVisionClient:
    def __init__(self, extracao: ExtracaoPix) -> None:
        async def _create(**_: Any) -> Any:
            msg = SimpleNamespace(content=extracao.model_dump_json())
            return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

        self.chat = SimpleNamespace(completions=SimpleNamespace(create=_create))


class _FakeEvolution:
    """enviar_texto no-op: o eco de confirmacao no grupo nao pode fazer HTTP nem escrever no DB."""

    def __init__(self) -> None:
        self.enviados: list[dict[str, Any]] = []

    async def enviar_texto(self, **kw: Any) -> str:
        self.enviados.append(kw)
        return "ECO-1"


# --- seed ----------------------------------------------------------------------------------------


async def _seed_em_execucao(c: AsyncConnection[dict[str, Any]], *, estado: str) -> UUID:
    """Modelo (com grupo/instance) + cliente + conversa + atendimento no `estado` dado."""
    modelo_id = uuid4()
    await c.execute(
        """
        INSERT INTO barravips.modelos
            (id, nome, idade, numero_whatsapp, valor_padrao, tipo_atendimento_aceito,
             coordenacao_chat_id, evolution_instance_id)
        VALUES (%s, %s, %s, %s, %s, %s::barravips.tipo_atendimento_enum[], %s, %s)
        """,
        (
            modelo_id,
            "Modelo Teste",
            25,
            f"test-wpp-{uuid4().hex}",
            500,
            ["externo"],
            f"test-grp-{uuid4().hex}@g.us",
            f"inst-{uuid4().hex}",
        ),
    )
    cliente_id = uuid4()
    await c.execute(
        "INSERT INTO barravips.clientes (id, telefone, nome) VALUES (%s, %s, %s)",
        (cliente_id, f"test-tel-{uuid4().hex}", "Cliente Teste"),
    )
    conversa_id = uuid4()
    await c.execute(
        """
        INSERT INTO barravips.conversas (id, cliente_id, modelo_id, evolution_chat_id)
        VALUES (%s, %s, %s, %s)
        """,
        (conversa_id, cliente_id, modelo_id, f"test-chat-{uuid4().hex}"),
    )
    atendimento_id = uuid4()
    await c.execute(
        """
        INSERT INTO barravips.atendimentos
            (id, cliente_id, modelo_id, conversa_id, estado, tipo_atendimento)
        VALUES (%s, %s, %s, %s, %s::barravips.estado_atendimento_enum, 'externo')
        """,
        (atendimento_id, cliente_id, modelo_id, conversa_id, estado),
    )
    return atendimento_id


async def _ler(c: AsyncConnection[dict[str, Any]], atendimento_id: UUID) -> dict[str, Any]:
    res = await c.execute(
        "SELECT estado::text AS estado, valor_final, forma_pagamento::text AS forma_pagamento"
        " FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    row = await res.fetchone()
    assert row is not None
    return row


async def _tem_evento(c: AsyncConnection[dict[str, Any]], atendimento_id: UUID, tipo: str) -> bool:
    res = await c.execute(
        "SELECT 1 FROM barravips.eventos WHERE atendimento_id = %s AND tipo = %s",
        (atendimento_id, tipo),
    )
    return (await res.fetchone()) is not None


def _ctx(conn: AsyncConnection[dict[str, Any]], extracao: ExtracaoPix) -> dict[str, Any]:
    from barra.settings import get_settings

    return {
        "db_pool": _PoolDeUmaConexao(conn),
        "minio": _FakeMinio(),
        "settings": get_settings(),
        "evolution": _FakeEvolution(),
        "vision_client": _FakeVisionClient(extracao),
    }


# --- cenarios ------------------------------------------------------------------------------------


@pytest.mark.needs_db
async def test_fecha_com_valor_lido(conn: AsyncConnection[dict[str, Any]]) -> None:
    atendimento_id = await _seed_em_execucao(conn, estado="Em_execucao")
    ctx = _ctx(
        conn, ExtracaoPix(valor=Decimal("1500.00"), plausibilidade_visual=True, confianca="alta")
    )

    await fechar_via_comprovante(
        ctx, atendimento_id=str(atendimento_id), object_key="k.jpg", evolution_message_id="IMG-1"
    )

    row = await _ler(conn, atendimento_id)
    assert row["estado"] == "Fechado"
    assert row["valor_final"] == Decimal("1500.00")
    assert row["forma_pagamento"] == "pix"
    # Data-ancora do modulo Financeiro (so `fechado_registrado` entra na receita).
    assert await _tem_evento(conn, atendimento_id, "fechado_registrado")
    # Eco de confirmacao no grupo (nunca sucesso silencioso).
    assert ctx["evolution"].enviados and "fechado" in ctx["evolution"].enviados[0]["texto"].lower()


@pytest.mark.needs_db
async def test_ja_fechado_no_op(conn: AsyncConnection[dict[str, Any]]) -> None:
    atendimento_id = await _seed_em_execucao(conn, estado="Em_execucao")
    # Fecha com valor_final num UPDATE atomico (o constraint atendimentos_fechado_exige_valor_final
    # rejeita 'Fechado' com valor nulo). Esse valor NAO pode ser sobrescrito pela 2a foto.
    await conn.execute(
        "UPDATE barravips.atendimentos SET estado = 'Fechado', valor_final = 999 WHERE id = %s",
        (atendimento_id,),
    )
    ctx = _ctx(
        conn, ExtracaoPix(valor=Decimal("1500.00"), plausibilidade_visual=True, confianca="alta")
    )

    await fechar_via_comprovante(
        ctx, atendimento_id=str(atendimento_id), object_key="k.jpg", evolution_message_id="IMG-2"
    )

    row = await _ler(conn, atendimento_id)
    assert row["valor_final"] == Decimal("999")  # nao refechou


@pytest.mark.needs_db
async def test_sem_valor_nao_fecha(conn: AsyncConnection[dict[str, Any]]) -> None:
    atendimento_id = await _seed_em_execucao(conn, estado="Em_execucao")
    ctx = _ctx(conn, ExtracaoPix(valor=None, plausibilidade_visual=True, confianca="baixa"))

    await fechar_via_comprovante(
        ctx, atendimento_id=str(atendimento_id), object_key="k.jpg", evolution_message_id="IMG-3"
    )

    row = await _ler(conn, atendimento_id)
    assert row["estado"] == "Em_execucao"  # sem valor legivel, nao fabrica valor_final
    assert row["valor_final"] is None
