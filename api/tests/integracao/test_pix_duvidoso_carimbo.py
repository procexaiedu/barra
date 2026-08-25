"""Ticket 07 — o Pix de deslocamento grava a duvida com o vocabulario UNICO dos dois caminhos.

`comprovantes_pix.motivo_em_revisao` guardava so prosa, e a prosa e o que nenhum filtro agrupa: o
painel tipava aquela coluna como um conjunto fechado de slugs (`valor_divergente`, `ocr_falhou`)
que o backend jamais escreveu, e a linha do motivo na lista renderizava vazia. Agora o motivo
canonico vai carimbado na frente, o detalhe continua inteiro depois dele, e o mesmo motivo e o
label da metrica.

Complementar (nao substituto) de `test_validar_pix.py`, que prova os 4 ramos do invariante "nunca
trava por Pix" — aqui o que se prova e a PALAVRA, e que ela nao mudou nada do fluxo.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from prometheus_client import REGISTRY
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from barra.dominio.grupo_financeiro.comprovante import ler_suspeita
from barra.settings import get_settings
from barra.workers.pix import ExtracaoPix, validar_pix

CHAVE_OK = "modelo@pix.example"
TITULAR_OK = "Maria Silva"


@pytest_asyncio.fixture
async def conn() -> AsyncIterator[AsyncConnection[dict[str, Any]]]:
    """Conexao real com ROLLBACK no teardown — nada persiste."""
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
    def __init__(self, connection: AsyncConnection[dict[str, Any]]) -> None:
        self._conn = connection

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[AsyncConnection[dict[str, Any]]]:
        yield self._conn


class _FakeMinio:
    JPEG_MAGIC = b"\xff\xd8\xff" + b"\x00" * 16

    def get_object(self, _bucket: str, _key: str) -> Any:
        dados = self.JPEG_MAGIC

        class _Resp:
            def read(self) -> bytes:
                return dados

            def close(self) -> None:
                return None

            def release_conn(self) -> None:
                return None

        return _Resp()


class _FakeVisionClient:
    def __init__(self, extracao: ExtracaoPix) -> None:
        async def _create(**_: Any) -> Any:
            msg = SimpleNamespace(content=extracao.model_dump_json())
            return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

        self.chat = SimpleNamespace(completions=SimpleNamespace(create=_create))


class _FakeRedis:
    def __init__(self) -> None:
        self.jobs: list[tuple[str, dict[str, Any]]] = []

    async def enqueue_job(self, name: str, **kwargs: Any) -> None:
        self.jobs.append((name, kwargs))


async def _seed(c: AsyncConnection[dict[str, Any]]) -> tuple[UUID, UUID]:
    modelo_id = uuid4()
    await c.execute(
        """
        INSERT INTO barravips.modelos
            (id, nome, idade, numero_whatsapp, valor_padrao, tipo_atendimento_aceito,
             chave_pix, titular_chave, coordenacao_chat_id, evolution_instance_id)
        VALUES (%s, %s, %s, %s, %s, %s::barravips.tipo_atendimento_enum[], %s, %s, %s, %s)
        """,
        (
            modelo_id,
            "Modelo Teste",
            25,
            f"test-wpp-{uuid4().hex}",
            500,
            ["externo"],
            CHAVE_OK,
            TITULAR_OK,
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
    mensagem_id = uuid4()
    await c.execute(
        """
        INSERT INTO barravips.mensagens
            (id, conversa_id, direcao, tipo, conteudo, media_object_key, evolution_message_id)
        VALUES (%s, %s, 'cliente', 'imagem', '', %s, %s)
        """,
        (
            mensagem_id,
            conversa_id,
            f"conversas/{conversa_id}/mensagens/{uuid4().hex}.jpg",
            f"test-evo-{uuid4().hex}",
        ),
    )
    atendimento_id = uuid4()
    await c.execute(
        """
        INSERT INTO barravips.atendimentos
            (id, cliente_id, modelo_id, conversa_id, estado, tipo_atendimento, pix_status)
        VALUES (%s, %s, %s, %s, 'Aguardando_confirmacao', 'externo', 'aguardando')
        """,
        (atendimento_id, cliente_id, modelo_id, conversa_id),
    )
    return atendimento_id, mensagem_id


def _ctx(c: AsyncConnection[dict[str, Any]], extracao: ExtracaoPix) -> dict[str, Any]:
    return {
        "db_pool": _PoolDeUmaConexao(c),
        "minio": _FakeMinio(),
        "vision_client": _FakeVisionClient(extracao),
        "settings": get_settings(),
        "redis": _FakeRedis(),
    }


async def _comprovante(c: AsyncConnection[dict[str, Any]], atendimento_id: UUID) -> dict[str, Any]:
    res = await c.execute(
        "SELECT decisao_pipeline::text AS decisao_pipeline, motivo_em_revisao"
        " FROM barravips.comprovantes_pix WHERE atendimento_id = %s",
        (atendimento_id,),
    )
    row = await res.fetchone()
    assert row is not None
    return row


async def _estado(c: AsyncConnection[dict[str, Any]], atendimento_id: UUID) -> str:
    res = await c.execute(
        "SELECT estado::text AS estado FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    row = await res.fetchone()
    assert row is not None
    return str(row["estado"])


def _divergencias(motivo: str) -> float:
    # `get_sample_value` NAO duplica o sufixo `_total`: o nome da amostra do Counter
    # `agente_pix_divergencia_total` e exatamente esse.
    return REGISTRY.get_sample_value("agente_pix_divergencia_total", {"motivo": motivo}) or 0.0


@pytest.mark.needs_db
async def test_valor_a_menor_carimba_o_motivo_canonico_e_preserva_a_prosa(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """O revisor continua lendo o numero; o painel passa a ter o que agrupar."""
    atendimento_id, mensagem_id = await _seed(conn)
    esperado = get_settings().pix_deslocamento_valor
    extracao = ExtracaoPix(
        valor=Decimal(esperado) - Decimal("20.00"),
        chave_pix_destinatario=CHAVE_OK,
        titular_destinatario=TITULAR_OK,
        plausibilidade_visual=True,
        confianca="alta",
    )
    antes = _divergencias("valor_abaixo_do_esperado")

    await validar_pix(
        _ctx(conn, extracao),
        mensagem_id=str(mensagem_id),
        atendimento_id=str(atendimento_id),
    )

    cp = await _comprovante(conn, atendimento_id)
    motivo, detalhe = ler_suspeita(cp["motivo_em_revisao"])
    assert motivo == "valor_abaixo_do_esperado"
    assert detalhe.startswith("valor extraido ") and "esperado" in detalhe
    assert _divergencias("valor_abaixo_do_esperado") == antes + 1
    # Suspeita NUNCA trava (01 §6.1): o carimbo nao mudou uma linha do fluxo.
    assert cp["decisao_pipeline"] == "em_revisao"
    assert await _estado(conn, atendimento_id) == "Confirmado"


@pytest.mark.needs_db
async def test_montagem_carimba_imagem_implausivel(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """O "Pix zoado" da ata ganha a MESMA palavra que o comprovante do Grupo financeiro usa."""
    atendimento_id, mensagem_id = await _seed(conn)
    extracao = ExtracaoPix(
        valor=Decimal("999.00"),
        chave_pix_destinatario=CHAVE_OK,
        titular_destinatario=TITULAR_OK,
        plausibilidade_visual=False,
        motivo_se_implausivel="fonte trocada no valor",
        confianca="alta",
    )
    antes = _divergencias("imagem_implausivel")

    await validar_pix(
        _ctx(conn, extracao),
        mensagem_id=str(mensagem_id),
        atendimento_id=str(atendimento_id),
    )

    cp = await _comprovante(conn, atendimento_id)
    motivo, detalhe = ler_suspeita(cp["motivo_em_revisao"])
    assert motivo == "imagem_implausivel"
    assert "fonte trocada no valor" in detalhe
    assert _divergencias("imagem_implausivel") == antes + 1
    assert await _estado(conn, atendimento_id) == "Confirmado"


@pytest.mark.needs_db
async def test_comprovante_limpo_nao_ganha_carimbo_nenhum(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """`motivo_em_revisao` continua NULL quando nao ha duvida — o carimbo nomeia a suspeita, nao
    a inventa."""
    atendimento_id, mensagem_id = await _seed(conn)
    extracao = ExtracaoPix(
        valor=Decimal(get_settings().pix_deslocamento_valor),
        chave_pix_destinatario=CHAVE_OK,
        titular_destinatario=TITULAR_OK,
        plausibilidade_visual=True,
        confianca="alta",
    )

    await validar_pix(
        _ctx(conn, extracao),
        mensagem_id=str(mensagem_id),
        atendimento_id=str(atendimento_id),
    )

    cp = await _comprovante(conn, atendimento_id)
    assert cp["decisao_pipeline"] == "validado"
    assert cp["motivo_em_revisao"] is None
    assert ler_suspeita(cp["motivo_em_revisao"]) == (None, "")
