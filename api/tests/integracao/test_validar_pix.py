"""M5c — `validar_pix` worker contra o Postgres real (06 §2.2 + §0 emendas grilling 2026-05-23).

4 cenarios cobrem os branches do pipeline; em TODOS o fluxo nunca trava (atendimento avanca
para Confirmado + ia_pausada=true), conforme 01 §6.1 e 07 §5. vision_client + MinIO + redis sao
mockados; so o Postgres e real, com ROLLBACK no teardown (banco prod self-hosted).
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

from barra.workers.pix import ExtracaoPix, validar_pix

# --- infra de DB real (ROLLBACK sempre) ------------------------------------------------------


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


# --- mocks de servico externo ---------------------------------------------------------------


class _FakeMinio:
    """Mock de Minio.get_object: devolve um objeto cujo .read() entrega bytes magicos JPEG."""

    JPEG_MAGIC = b"\xff\xd8\xff" + b"\x00" * 16  # so importa o magic byte (mime detection)

    def __init__(self, dados: bytes | None = None) -> None:
        self._dados = dados or self.JPEG_MAGIC
        self.chamadas = 0

    def get_object(self, _bucket: str, _key: str) -> Any:
        self.chamadas += 1
        outer = self

        class _Resp:
            def read(self_inner: Any) -> bytes:
                return outer._dados

            def close(self_inner: Any) -> None:
                return None

            def release_conn(self_inner: Any) -> None:
                return None

        return _Resp()


class _FakeVisionClient:
    """Mock de AsyncOpenAI: chat.completions.create devolve um payload com a ExtracaoPix serializada."""

    def __init__(self, extracao: ExtracaoPix) -> None:
        self._extracao = extracao
        self.chamadas = 0

        async def _create(**_: Any) -> Any:
            self.chamadas += 1
            msg = SimpleNamespace(content=self._extracao.model_dump_json())
            choice = SimpleNamespace(message=msg)
            return SimpleNamespace(choices=[choice])

        self.chat = SimpleNamespace(completions=SimpleNamespace(create=_create))

    async def close(self) -> None:
        return None


class _FakeRedis:
    """Mock de ArqRedis.enqueue_job: guarda as chamadas em ordem."""

    def __init__(self) -> None:
        self.jobs: list[tuple[str, dict[str, Any]]] = []

    async def enqueue_job(self, name: str, **kwargs: Any) -> None:
        self.jobs.append((name, kwargs))


# --- seeders ---------------------------------------------------------------------------------


CHAVE_OK = "modelo@pix.example"
TITULAR_OK = "Maria Silva"


async def _seed_cenario(
    c: AsyncConnection[dict[str, Any]],
    *,
    com_midia: bool = True,
) -> tuple[UUID, UUID]:
    """Modelo (com chave/titular) + cliente + conversa + mensagem + atendimento externo em
    Aguardando_confirmacao com pix_status=aguardando. Retorna (atendimento_id, mensagem_id).

    `com_midia=False` simula o REL-06: o webhook falhou o upload ao MinIO e gravou a mensagem
    como 'texto' sem media_object_key (constraint: tipo != 'texto' exige media_object_key NOT NULL)."""
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
    tipo_msg = "imagem" if com_midia else "texto"
    media_key = f"conversas/{conversa_id}/mensagens/{uuid4().hex}.jpg" if com_midia else None
    await c.execute(
        """
        INSERT INTO barravips.mensagens
            (id, conversa_id, direcao, tipo, conteudo, media_object_key, evolution_message_id)
        VALUES (%s, %s, 'cliente', %s, %s, %s, %s)
        """,
        (
            mensagem_id,
            conversa_id,
            tipo_msg,
            "",
            media_key,
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


async def _ler_atendimento(
    c: AsyncConnection[dict[str, Any]], atendimento_id: UUID
) -> dict[str, Any]:
    res = await c.execute(
        "SELECT estado::text AS estado, pix_status::text AS pix_status, ia_pausada,"
        "       ia_pausada_motivo::text AS ia_pausada_motivo"
        " FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    row = await res.fetchone()
    assert row is not None
    return row


async def _ler_comprovante(
    c: AsyncConnection[dict[str, Any]], atendimento_id: UUID
) -> dict[str, Any]:
    res = await c.execute(
        """
        SELECT decisao_pipeline::text AS decisao_pipeline,
               motivo_em_revisao,
               valor_extraido,
               chave_extraida,
               titular_extraido,
               timestamp_extraido
          FROM barravips.comprovantes_pix WHERE atendimento_id = %s
        """,
        (atendimento_id,),
    )
    row = await res.fetchone()
    assert row is not None
    return row


def _ctx(
    conn: AsyncConnection[dict[str, Any]],
    vision: _FakeVisionClient,
    redis: _FakeRedis,
) -> dict[str, Any]:
    from barra.settings import get_settings

    return {
        "db_pool": _PoolDeUmaConexao(conn),
        "minio": _FakeMinio(),
        "vision_client": vision,
        "settings": get_settings(),
        "redis": redis,
    }


# --- cenarios --------------------------------------------------------------------------------


@pytest.mark.needs_db
async def test_validado_avanca_confirmado_e_enfileira_card(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    atendimento_id, mensagem_id = await _seed_cenario(conn)
    extracao = ExtracaoPix(
        valor=Decimal("100.00"),
        chave_pix_destinatario=CHAVE_OK,
        titular_destinatario=TITULAR_OK,
        banco_origem="Itau",
        plausibilidade_visual=True,
        motivo_se_implausivel=None,
    )
    vision = _FakeVisionClient(extracao)
    redis = _FakeRedis()

    await validar_pix(
        _ctx(conn, vision, redis),
        mensagem_id=str(mensagem_id),
        atendimento_id=str(atendimento_id),
    )

    at = await _ler_atendimento(conn, atendimento_id)
    assert at["estado"] == "Confirmado"
    assert at["pix_status"] == "validado"
    assert at["ia_pausada"] is True
    assert at["ia_pausada_motivo"] == "modelo_em_atendimento"

    cp = await _ler_comprovante(conn, atendimento_id)
    assert cp["decisao_pipeline"] == "validado"
    assert cp["motivo_em_revisao"] is None
    assert cp["valor_extraido"] == Decimal("100.00")
    assert cp["timestamp_extraido"] is None  # drop §0 item 11

    assert len(redis.jobs) == 1
    nome, kwargs = redis.jobs[0]
    assert nome == "enviar_card"
    assert kwargs["tipo"] == "pix_validado"
    assert kwargs["_job_id"] == f"card:pix:{atendimento_id}"


@pytest.mark.needs_db
async def test_underpay_em_revisao_mas_fluxo_avanca(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    atendimento_id, mensagem_id = await _seed_cenario(conn)
    extracao = ExtracaoPix(
        valor=Decimal("50.00"),  # < 100
        chave_pix_destinatario=CHAVE_OK,
        titular_destinatario=TITULAR_OK,
        banco_origem="Itau",
        plausibilidade_visual=True,
        motivo_se_implausivel=None,
    )
    vision = _FakeVisionClient(extracao)
    redis = _FakeRedis()

    await validar_pix(
        _ctx(conn, vision, redis),
        mensagem_id=str(mensagem_id),
        atendimento_id=str(atendimento_id),
    )

    # Fluxo NUNCA trava: avanca mesmo em em_revisao.
    at = await _ler_atendimento(conn, atendimento_id)
    assert at["estado"] == "Confirmado"
    assert at["pix_status"] == "em_revisao"
    assert at["ia_pausada"] is True

    cp = await _ler_comprovante(conn, atendimento_id)
    assert cp["decisao_pipeline"] == "em_revisao"
    assert cp["motivo_em_revisao"] is not None and "valor" in cp["motivo_em_revisao"]

    assert redis.jobs[0][1]["tipo"] == "pix_em_revisao"


@pytest.mark.needs_db
async def test_chave_divergente_em_revisao(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    atendimento_id, mensagem_id = await _seed_cenario(conn)
    extracao = ExtracaoPix(
        valor=Decimal("100.00"),
        chave_pix_destinatario="outro@pix.example",  # diferente do esperado
        titular_destinatario=TITULAR_OK,
        banco_origem="Nubank",
        plausibilidade_visual=True,
        motivo_se_implausivel=None,
    )
    vision = _FakeVisionClient(extracao)
    redis = _FakeRedis()

    await validar_pix(
        _ctx(conn, vision, redis),
        mensagem_id=str(mensagem_id),
        atendimento_id=str(atendimento_id),
    )

    at = await _ler_atendimento(conn, atendimento_id)
    assert at["estado"] == "Confirmado"
    assert at["pix_status"] == "em_revisao"

    cp = await _ler_comprovante(conn, atendimento_id)
    assert cp["decisao_pipeline"] == "em_revisao"
    assert "chave" in (cp["motivo_em_revisao"] or "")

    assert redis.jobs[0][1]["tipo"] == "pix_em_revisao"


@pytest.mark.needs_db
async def test_plausibilidade_falsa_em_revisao(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    atendimento_id, mensagem_id = await _seed_cenario(conn)
    extracao = ExtracaoPix(
        valor=Decimal("100.00"),
        chave_pix_destinatario=CHAVE_OK,
        titular_destinatario=TITULAR_OK,
        banco_origem=None,
        plausibilidade_visual=False,
        motivo_se_implausivel="screenshot de outro app, sem header de banco",
    )
    vision = _FakeVisionClient(extracao)
    redis = _FakeRedis()

    await validar_pix(
        _ctx(conn, vision, redis),
        mensagem_id=str(mensagem_id),
        atendimento_id=str(atendimento_id),
    )

    at = await _ler_atendimento(conn, atendimento_id)
    assert at["estado"] == "Confirmado"
    assert at["pix_status"] == "em_revisao"

    cp = await _ler_comprovante(conn, atendimento_id)
    assert cp["decisao_pipeline"] == "em_revisao"
    assert "plausibilidade" in (cp["motivo_em_revisao"] or "")

    assert redis.jobs[0][1]["tipo"] == "pix_em_revisao"


@pytest.mark.needs_db
async def test_midia_ausente_em_revisao_nao_vira_perdido(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """REL-06: upload do comprovante ao MinIO falhou -> mensagem sem media_object_key.

    `validar_pix` marca DUVIDOSO (em_revisao) e o atendimento avanca para Confirmado, em vez de
    estagnar em Aguardando_confirmacao ate o timeout-24h virar Perdido (Pix NUNCA some/trava,
    01 §6.1). Sem imagem, MinIO e vision nao sao tocados."""
    atendimento_id, mensagem_id = await _seed_cenario(conn, com_midia=False)
    vision = _FakeVisionClient(ExtracaoPix(plausibilidade_visual=True))  # nao deve ser chamado
    redis = _FakeRedis()
    ctx = _ctx(conn, vision, redis)

    await validar_pix(
        ctx,
        mensagem_id=str(mensagem_id),
        atendimento_id=str(atendimento_id),
    )

    # Fluxo NUNCA trava nem some: avanca mesmo sem o comprovante.
    at = await _ler_atendimento(conn, atendimento_id)
    assert at["estado"] == "Confirmado"
    assert at["pix_status"] == "em_revisao"
    assert at["ia_pausada"] is True

    cp = await _ler_comprovante(conn, atendimento_id)
    assert cp["decisao_pipeline"] == "em_revisao"
    assert "midia" in (cp["motivo_em_revisao"] or "")
    assert cp["valor_extraido"] is None  # sem extracao

    # Sem imagem: nao baixa do MinIO nem chama o vision.
    assert ctx["minio"].chamadas == 0
    assert vision.chamadas == 0

    assert redis.jobs[0][1]["tipo"] == "pix_em_revisao"
