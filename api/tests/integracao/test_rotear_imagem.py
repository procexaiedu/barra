"""M5b — `rotear_imagem` sob lock:conv (06 §2.1).

Testes contra Postgres real (`needs_db`) com Redis efemero (fakeredis) e `enqueue_job` mockado.

Cobre os 5 caminhos de decisao (06 §2.1):
  - test_pix_aguardando: Aguardando_confirmacao + pix_status='aguardando' -> enqueue validar_pix
  - test_interno: Aguardando_confirmacao + tipo_atendimento='interno' -> chama stub _handoff_foto_portaria
  - test_fora_fluxo_com_legenda: caption setado -> enfileira processar_turno
  - test_fora_fluxo_pura: sem legenda + sem atendimento aberto -> silencio
  - test_lock_busy: lock:conv pre-adquirido -> re-enfileira rotear_imagem com _defer_by

F0.7 (roadmap) — tranca o roteamento por `tipo_atendimento` em Aguardando_confirmacao:
imagem em **externo** = comprovante Pix, NUNCA Foto de portaria (que e interno-only,
CONTEXT.md "Foto de portaria"). O `test_pix_aguardando` acima nao protege o guard
`tipo_atendimento == 'interno'` do branch foto-portaria: o branch do Pix vem antes e
intercepta o caso externo+pix='aguardando', entao apagar aquele guard passa batido nele.
Os dois testes abaixo provam no banco real (estado nao vira Em_execucao, foto_portaria_em
fica NULL) que um externo nunca cai no handoff de foto de portaria.
"""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any, NamedTuple
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from fakeredis.aioredis import FakeRedis
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from barra.settings import get_settings
from barra.workers.media import rotear_imagem

# --- infra: pool de UMA conexao + redis fake (espelha test_coordenador_basico) ---------------


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
    def __init__(self, conexao: AsyncConnection[dict[str, Any]]) -> None:
        self._conn = conexao

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[AsyncConnection[dict[str, Any]]]:
        yield self._conn


def _redis_fake() -> FakeRedis:
    redis = FakeRedis()
    redis.enqueue_job = AsyncMock()  # FakeRedis nao tem enqueue_job
    return redis


def _ctx(pool: _PoolDeUmaConexao, redis: FakeRedis) -> dict[str, Any]:
    return {"redis": redis, "db_pool": pool, "settings": get_settings()}


# --- seeds -----------------------------------------------------------------------------------


async def _seed_modelo(c: AsyncConnection[dict[str, Any]]) -> UUID:
    modelo_id = uuid4()
    await c.execute(
        """
        INSERT INTO barravips.modelos
            (id, nome, idade, numero_whatsapp, valor_padrao, tipo_atendimento_aceito)
        VALUES (%s, %s, %s, %s, %s, %s::barravips.tipo_atendimento_enum[])
        """,
        (modelo_id, "Modelo Teste", 25, f"test-wpp-{uuid4().hex}", 500, ["interno", "externo"]),
    )
    return modelo_id


async def _seed_cliente(c: AsyncConnection[dict[str, Any]]) -> UUID:
    cliente_id = uuid4()
    await c.execute(
        "INSERT INTO barravips.clientes (id, telefone) VALUES (%s, %s)",
        (cliente_id, f"test-tel-{uuid4().hex}"),
    )
    return cliente_id


async def _seed_conversa(
    c: AsyncConnection[dict[str, Any]], cliente_id: UUID, modelo_id: UUID
) -> UUID:
    conversa_id = uuid4()
    await c.execute(
        """
        INSERT INTO barravips.conversas (id, cliente_id, modelo_id, evolution_chat_id)
        VALUES (%s, %s, %s, %s)
        """,
        (conversa_id, cliente_id, modelo_id, f"test-chat-{uuid4().hex}"),
    )
    return conversa_id


async def _seed_atendimento(
    c: AsyncConnection[dict[str, Any]],
    *,
    cliente_id: UUID,
    modelo_id: UUID,
    conversa_id: UUID,
    estado: str,
    tipo_atendimento: str,
    pix_status: str,
) -> UUID:
    atendimento_id = uuid4()
    await c.execute(
        """
        INSERT INTO barravips.atendimentos
            (id, cliente_id, modelo_id, conversa_id, estado, tipo_atendimento, pix_status)
        VALUES (%s, %s, %s, %s, %s::barravips.estado_atendimento_enum,
                %s::barravips.tipo_atendimento_enum,
                %s::barravips.pix_status_enum)
        """,
        (atendimento_id, cliente_id, modelo_id, conversa_id, estado, tipo_atendimento, pix_status),
    )
    return atendimento_id


class _MsgSeed(NamedTuple):
    id: UUID
    evolution_id: str


async def _seed_msg_cliente_orfa(c: AsyncConnection[dict[str, Any]], conversa_id: UUID) -> _MsgSeed:
    """Devolve (id interno, evolution_id). Espelha o webhook: a mensagem e persistida com os
    DOIS ids; o `rotear_imagem` recebe o `evolution_message_id` e resolve o UUID interno antes
    de chamar `validar_pix`/`_handoff_foto_portaria`."""
    mensagem_id = uuid4()
    evolution_message_id = f"test-evo-{uuid4().hex}"
    await c.execute(
        """
        INSERT INTO barravips.mensagens
            (id, conversa_id, direcao, tipo, conteudo, media_object_key, evolution_message_id,
             created_at)
        VALUES (%s, %s, 'cliente', 'imagem', '', %s, %s, %s)
        """,
        (
            mensagem_id,
            conversa_id,
            f"conversas/{conversa_id}/mensagens/{uuid4().hex}.jpg",
            evolution_message_id,
            datetime.now(UTC),
        ),
    )
    return _MsgSeed(mensagem_id, evolution_message_id)


# --- testes ----------------------------------------------------------------------------------


@pytest.mark.needs_db
async def test_pix_aguardando(conn: AsyncConnection[dict[str, Any]]) -> None:
    """Aguardando_confirmacao + pix_status='aguardando' -> enqueue validar_pix com _job_id estavel.

    Regressao: o webhook enfileira `rotear_imagem` com o `evolution_message_id` (string), mas
    `validar_pix` opera pelo UUID interno de `mensagens.id`. O `rotear_imagem` deve RESOLVER o
    UUID antes de repassar — senao `validar_pix` estoura em `UUID(mensagem_id)`."""
    modelo_id = await _seed_modelo(conn)
    cliente_id = await _seed_cliente(conn)
    conversa_id = await _seed_conversa(conn, cliente_id, modelo_id)
    atendimento_id = await _seed_atendimento(
        conn,
        cliente_id=cliente_id,
        modelo_id=modelo_id,
        conversa_id=conversa_id,
        estado="Aguardando_confirmacao",
        tipo_atendimento="externo",
        pix_status="aguardando",
    )
    msg = await _seed_msg_cliente_orfa(conn, conversa_id)

    redis = _redis_fake()
    ctx = _ctx(_PoolDeUmaConexao(conn), redis)

    await rotear_imagem(
        ctx,
        mensagem_id=msg.evolution_id,
        conversa_id=str(conversa_id),
        media_url="https://evolution.test/img.jpg",
        caption=None,
    )

    calls = redis.enqueue_job.call_args_list
    assert len(calls) == 1
    assert calls[0].args == ("validar_pix",)
    kwargs = calls[0].kwargs
    # `validar_pix` recebe o UUID interno RESOLVIDO, nao o evolution_message_id que entrou.
    assert kwargs["mensagem_id"] == str(msg.id)
    assert kwargs["atendimento_id"] == str(atendimento_id)
    # `validar_pix` nao aceita media_url (assinatura enxuta, 06 §0 item 2): nao deve ser passado.
    assert "media_url" not in kwargs
    # _job_id (idempotencia) mantem o evolution_message_id, estavel por mensagem.
    assert kwargs["_job_id"] == f"pix:{atendimento_id}:{msg.evolution_id}"


@pytest.mark.needs_db
async def test_interno_aciona_foto_portaria(conn: AsyncConnection[dict[str, Any]]) -> None:
    """Aguardando_confirmacao + interno (sem Pix em curso) -> handoff implicito de foto de
    portaria (M5d, 06 §4): estado vira Em_execucao + card chegada enfileirado.

    O detalhe dos 4 efeitos atomicos do handoff (UPDATE atendimento + bloqueio + escalada +
    evento) vive em `test_foto_portaria.py`; aqui o foco e provar o DESPACHO do rotear_imagem.
    """
    modelo_id = await _seed_modelo(conn)
    cliente_id = await _seed_cliente(conn)
    conversa_id = await _seed_conversa(conn, cliente_id, modelo_id)
    atendimento_id = await _seed_atendimento(
        conn,
        cliente_id=cliente_id,
        modelo_id=modelo_id,
        conversa_id=conversa_id,
        estado="Aguardando_confirmacao",
        tipo_atendimento="interno",
        pix_status="nao_solicitado",
    )
    msg = await _seed_msg_cliente_orfa(conn, conversa_id)

    redis = _redis_fake()
    ctx = _ctx(_PoolDeUmaConexao(conn), redis)

    await rotear_imagem(
        ctx,
        mensagem_id=msg.evolution_id,
        conversa_id=str(conversa_id),
        media_url="https://evolution.test/portaria.jpg",
        caption=None,
    )

    res = await conn.execute(
        "SELECT estado::text AS estado FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    assert a is not None
    assert a["estado"] == "Em_execucao"

    calls = redis.enqueue_job.call_args_list
    assert len(calls) == 1
    assert calls[0].args == ("enviar_card",)
    assert calls[0].kwargs["tipo"] == "chegada"
    assert calls[0].kwargs["_job_id"] == f"card:chegada:{atendimento_id}"


@pytest.mark.needs_db
async def test_fora_fluxo_com_legenda_enfileira_turno(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Fora-fluxo COM legenda: IA cega responde a legenda -> enfileira processar_turno (06 §3)."""
    modelo_id = await _seed_modelo(conn)
    cliente_id = await _seed_cliente(conn)
    conversa_id = await _seed_conversa(conn, cliente_id, modelo_id)
    # estado fora dos dois branches: Novo e nao-interno (ou interno, mas estado != Aguardando).
    await _seed_atendimento(
        conn,
        cliente_id=cliente_id,
        modelo_id=modelo_id,
        conversa_id=conversa_id,
        estado="Triagem",
        tipo_atendimento="externo",
        pix_status="nao_solicitado",
    )
    msg = await _seed_msg_cliente_orfa(conn, conversa_id)

    redis = _redis_fake()
    ctx = _ctx(_PoolDeUmaConexao(conn), redis)

    await rotear_imagem(
        ctx,
        mensagem_id=msg.evolution_id,
        conversa_id=str(conversa_id),
        media_url="https://evolution.test/foto-aleatoria.jpg",
        caption="olha que linda essa selfie minha",
    )

    calls = redis.enqueue_job.call_args_list
    assert len(calls) == 1
    assert calls[0].args == ("processar_turno",)
    assert calls[0].kwargs["conversa_id"] == str(conversa_id)
    assert calls[0].kwargs["_job_id"] == f"turno:{conversa_id}"


@pytest.mark.needs_db
async def test_fora_fluxo_sem_legenda_fica_em_silencio(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Sem atendimento aberto e sem legenda: IA cega fica calada (06 §3)."""
    modelo_id = await _seed_modelo(conn)
    cliente_id = await _seed_cliente(conn)
    conversa_id = await _seed_conversa(conn, cliente_id, modelo_id)
    # Sem atendimento aberto: resolver_atendimento_existente devolve None -> silencio.
    msg = await _seed_msg_cliente_orfa(conn, conversa_id)

    redis = _redis_fake()
    ctx = _ctx(_PoolDeUmaConexao(conn), redis)

    await rotear_imagem(
        ctx,
        mensagem_id=msg.evolution_id,
        conversa_id=str(conversa_id),
        media_url="https://evolution.test/nada.jpg",
        caption=None,
    )

    assert redis.enqueue_job.call_args_list == []


@pytest.mark.needs_db
async def test_lock_busy_redefer(conn: AsyncConnection[dict[str, Any]]) -> None:
    """Lock pre-adquirido (turno de texto em voo): re-enfileira rotear_imagem com _defer_by."""
    modelo_id = await _seed_modelo(conn)
    cliente_id = await _seed_cliente(conn)
    conversa_id = await _seed_conversa(conn, cliente_id, modelo_id)
    msg = await _seed_msg_cliente_orfa(conn, conversa_id)

    redis = _redis_fake()
    # Simula turno de texto retendo o lock — o adquirir_lock vai erguer LockBusy.
    await redis.set(f"lock:conv:{conversa_id}", "outro-worker", ex=60)

    ctx = _ctx(_PoolDeUmaConexao(conn), redis)

    await rotear_imagem(
        ctx,
        mensagem_id=msg.evolution_id,
        conversa_id=str(conversa_id),
        media_url="https://evolution.test/img.jpg",
        caption=None,
    )

    calls = redis.enqueue_job.call_args_list
    assert len(calls) == 1
    assert calls[0].args == ("rotear_imagem",)
    kwargs = calls[0].kwargs
    # LockBusy estoura antes de resolver o UUID: o re-enqueue mantem o evolution_message_id.
    assert kwargs["mensagem_id"] == msg.evolution_id
    assert kwargs["conversa_id"] == str(conversa_id)
    assert kwargs["caption"] is None
    assert "_defer_by" in kwargs


async def _ler_atendimento(
    c: AsyncConnection[dict[str, Any]], atendimento_id: UUID
) -> dict[str, Any]:
    res = await c.execute(
        """
        SELECT estado::text AS estado,
               foto_portaria_em,
               responsavel_atual::text AS responsavel_atual,
               ia_pausada
          FROM barravips.atendimentos
         WHERE id = %s
        """,
        (atendimento_id,),
    )
    row = await res.fetchone()
    assert row is not None
    return row


@pytest.mark.needs_db
async def test_externo_aguardando_e_pix_nunca_foto_portaria(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """F0.7: externo em Aguardando_confirmacao = comprovante Pix, NUNCA Foto de portaria.

    Caso realista (pix_status='aguardando'): a imagem deve seguir o pipeline do Pix
    (`validar_pix`) e o atendimento NAO pode sofrer o handoff de foto de portaria — provado
    no banco real (estado segue Aguardando_confirmacao, `foto_portaria_em` NULL, IA nao pausada).
    """
    modelo_id = await _seed_modelo(conn)
    cliente_id = await _seed_cliente(conn)
    conversa_id = await _seed_conversa(conn, cliente_id, modelo_id)
    atendimento_id = await _seed_atendimento(
        conn,
        cliente_id=cliente_id,
        modelo_id=modelo_id,
        conversa_id=conversa_id,
        estado="Aguardando_confirmacao",
        tipo_atendimento="externo",
        pix_status="aguardando",
    )
    msg = await _seed_msg_cliente_orfa(conn, conversa_id)

    redis = _redis_fake()
    ctx = _ctx(_PoolDeUmaConexao(conn), redis)

    await rotear_imagem(
        ctx,
        mensagem_id=msg.evolution_id,
        conversa_id=str(conversa_id),
        media_url="https://evolution.test/comprovante.jpg",
        caption=None,
    )

    # Despacho: pipeline do Pix, nao handoff de foto de portaria.
    calls = redis.enqueue_job.call_args_list
    assert len(calls) == 1
    assert calls[0].args == ("validar_pix",)
    # Nenhum card 'chegada' (assinatura do handoff de foto de portaria) foi enfileirado.
    assert all(c.kwargs.get("tipo") != "chegada" for c in calls)

    # Banco real: a foto de portaria NAO rodou (estado intacto, sem marca de chegada).
    a = await _ler_atendimento(conn, atendimento_id)
    assert a["estado"] == "Aguardando_confirmacao"
    assert a["foto_portaria_em"] is None
    assert a["responsavel_atual"] != "modelo"
    assert a["ia_pausada"] is False


@pytest.mark.needs_db
async def test_externo_aguardando_sem_pix_nao_vira_foto_portaria(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """F0.7 (dente do guard): externo em Aguardando_confirmacao SEM Pix em curso nunca vira
    Foto de portaria.

    Sonda que isola o guard `tipo_atendimento == 'interno'` do branch foto-portaria: com
    `pix_status != 'aguardando'` o branch do Pix nao intercepta, entao o unico anteparo contra o
    externo cair no handoff de foto de portaria e aquele guard. Comportamento correto = silencio
    (06 §3). Apagar o guard (`and tipo_atendimento == 'interno'`) faz este externo virar
    Em_execucao -> teste vermelho (dente provado).
    """
    modelo_id = await _seed_modelo(conn)
    cliente_id = await _seed_cliente(conn)
    conversa_id = await _seed_conversa(conn, cliente_id, modelo_id)
    atendimento_id = await _seed_atendimento(
        conn,
        cliente_id=cliente_id,
        modelo_id=modelo_id,
        conversa_id=conversa_id,
        estado="Aguardando_confirmacao",
        tipo_atendimento="externo",
        pix_status="nao_solicitado",
    )
    msg = await _seed_msg_cliente_orfa(conn, conversa_id)

    redis = _redis_fake()
    ctx = _ctx(_PoolDeUmaConexao(conn), redis)

    await rotear_imagem(
        ctx,
        mensagem_id=msg.evolution_id,
        conversa_id=str(conversa_id),
        media_url="https://evolution.test/foto-qualquer.jpg",
        caption=None,
    )

    # Silencio: sem foto de portaria, sem Pix (pix nao foi solicitado), sem turno (sem legenda).
    assert redis.enqueue_job.call_args_list == []

    # Banco real: o externo nao sofreu o handoff de foto de portaria.
    a = await _ler_atendimento(conn, atendimento_id)
    assert a["estado"] == "Aguardando_confirmacao"
    assert a["foto_portaria_em"] is None
    assert a["responsavel_atual"] != "modelo"
    assert a["ia_pausada"] is False
