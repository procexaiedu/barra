"""F1.1 — costura completa webhook→estado do comando de grupo.

Critério (roadmap F1.1): `fechado 1500 #5` entrando **pelo webhook** registra resultado,
despausa a IA e sincroniza o bloqueio. A nota do item — "(hoje para na classificação)" —
não é um buraco de código: o handler já chama `aplicar_comando` (wiring antigo, commit
928d301). É um buraco de **cobertura**: os testes de webhook existentes
(`test_webhook_integration.py`) usam `FakeConn` e param na **classificação/roteamento**
(ex.: `test_webhook_grupo_reconhecido_por_coordenacao_chat_id` termina em `invalid` porque
o `#N` não existe no fake), enquanto F0.8 prova o **núcleo de serviço** (`aplicar_comando`)
isolado. Nenhum exercita a costura inteira — payload Evolution cru → `extrair_mensagem` →
reconhecimento de grupo (DB) → dedupe (DB) → parse do comando → resolução de modelo por
instance (DB) → resolução de atendimento por `#N` (DB) → `aplicar_comando` → trigger
`sync_bloqueio_estado` → **estado no banco**.

Este gate fecha esse buraco: chama o handler real `evolution_webhook` com uma request
mínima (sem lifespan, p/ não criar pool de prod nem ARQ), apontando o pool ao mesmo conn de
rollback. `needs_db` (Postgres via TEST_DATABASE_URL): a transição terminal vive no UPDATE do
atendimento e o bloqueio é sincronizado por **trigger**; um `FakeConn` não dispara trigger nem
prova a costura. Padrão dos demais testes de integração: conn real autocommit=False + ROLLBACK
sempre.

Dente (vermelho→verde): se `_processar_grupo` parasse na classificação (sem chamar
`aplicar_comando`), o atendimento seguiria `Em_execucao` e estes testes ficariam vermelhos —
exatamente o cenário "para na classificação".
"""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, ClassVar
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from barra.webhook.routes import evolution_webhook


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


# --- request/pool/settings mínimos p/ chamar o handler sem lifespan ---------------------------


class _FakeSettings:
    """Só os campos que o ramo de grupo (texto) do `evolution_webhook` lê. Objeto isolado p/
    não mutar o `app.state.settings` global (que outros testes do processo compartilham)."""

    evolution_webhook_token = ""
    webhook_max_body_bytes = 1_000_000
    jid_permitido = None
    evolution_grupo_coordenacao_jid = None  # desligado: reconhecimento de grupo vem do DB
    evolution_fernando_jids: ClassVar[list[str]] = []
    reset_teste_instances: ClassVar[list[str]] = []


class _PoolUmaConn:
    """Pool que entrega sempre o mesmo conn de rollback (o ramo de grupo abre uma única
    conexão e a reusa para todas as queries do handler)."""

    def __init__(self, c: AsyncConnection[dict[str, Any]]) -> None:
        self._conn = c

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[AsyncConnection[dict[str, Any]]]:
        yield self._conn


class _State:
    pass


class _App:
    def __init__(self, pool: _PoolUmaConn) -> None:
        self.state = _State()
        self.state.settings = _FakeSettings()
        self.state.db_pool = pool


class _Request:
    def __init__(self, payload: dict[str, Any], app: _App) -> None:
        self._payload = payload
        self.app = app
        self.headers: dict[str, str] = {}
        self.state = _State()

    async def json(self) -> dict[str, Any]:
        return self._payload


def _payload_grupo(*, instance: str, grupo_jid: str, texto: str, message_id: str) -> dict[str, Any]:
    """Payload Evolution de uma mensagem da modelo no grupo de Coordenação (fromMe=true)."""
    return {
        "instance": instance,
        "data": {
            "key": {"id": message_id, "remoteJid": grupo_jid, "fromMe": True},
            "message": {"conversation": texto},
        },
    }


async def _chamar_webhook(
    c: AsyncConnection[dict[str, Any]], payload: dict[str, Any]
) -> dict[str, str]:
    request = _Request(payload, _App(_PoolUmaConn(c)))
    return await evolution_webhook(request)  # type: ignore[arg-type]


# --- seeds (espelham test_f0_8_fechado_card; + instance/coordenacao p/ a costura) -------------


async def _seed_modelo(
    c: AsyncConnection[dict[str, Any]], *, instance: str, grupo_jid: str
) -> UUID:
    modelo_id = uuid4()
    await c.execute(
        """
        INSERT INTO barravips.modelos
            (id, nome, idade, numero_whatsapp, valor_padrao, tipo_atendimento_aceito,
             percentual_repasse, evolution_instance_id, coordenacao_chat_id)
        VALUES (%s, %s, %s, %s, %s, %s::barravips.tipo_atendimento_enum[], %s, %s, %s)
        """,
        (
            modelo_id,
            "Modelo Teste",
            25,
            f"test-wpp-{uuid4().hex}",
            500,
            ["interno", "externo"],
            Decimal("40"),
            instance,
            grupo_jid,
        ),
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


async def _seed_atendimento_em_execucao(
    c: AsyncConnection[dict[str, Any]],
    *,
    cliente_id: UUID,
    modelo_id: UUID,
    conversa_id: UUID,
    tipo: str = "interno",
    estado: str = "Em_execucao",
) -> tuple[UUID, int]:
    """Atendimento com a IA pausada (modelo conduz), devolvendo (id, numero_curto). O
    `numero_curto` é atribuído pelo banco e é o que o comando de grupo cita (`#N`).
    `estado` parametriza o ponto da máquina (Em_execucao p/ o fechamento; Confirmado p/ o
    perdido com bloqueio prévio ainda `bloqueado`)."""
    atendimento_id = uuid4()
    res = await c.execute(
        """
        INSERT INTO barravips.atendimentos
            (id, cliente_id, modelo_id, conversa_id, estado, tipo_atendimento,
             pix_status, ia_pausada, ia_pausada_motivo, responsavel_atual)
        VALUES (%s, %s, %s, %s, %s::barravips.estado_atendimento_enum,
                %s::barravips.tipo_atendimento_enum,
                'nao_solicitado'::barravips.pix_status_enum, true,
                'modelo_em_atendimento'::barravips.ia_pausada_motivo_enum, 'modelo')
        RETURNING numero_curto
        """,
        (atendimento_id, cliente_id, modelo_id, conversa_id, estado, tipo),
    )
    row = await res.fetchone()
    assert row is not None
    return atendimento_id, int(row["numero_curto"])


async def _seed_bloqueio(
    c: AsyncConnection[dict[str, Any]],
    *,
    modelo_id: UUID,
    atendimento_id: UUID,
    estado: str = "em_atendimento",
) -> UUID:
    bloqueio_id = uuid4()
    inicio = datetime.now(UTC) - timedelta(minutes=30)
    await c.execute(
        """
        INSERT INTO barravips.bloqueios (id, modelo_id, atendimento_id, inicio, fim, estado, origem)
        VALUES (%s, %s, %s, %s, %s, %s::barravips.estado_bloqueio_enum,
                'ia'::barravips.origem_bloqueio_enum)
        """,
        (bloqueio_id, modelo_id, atendimento_id, inicio, inicio + timedelta(hours=1), estado),
    )
    await c.execute(
        "UPDATE barravips.atendimentos SET bloqueio_id = %s WHERE id = %s",
        (bloqueio_id, atendimento_id),
    )
    return bloqueio_id


async def _ler_atendimento(c: AsyncConnection[dict[str, Any]], aid: UUID) -> dict[str, Any]:
    res = await c.execute(
        """
        SELECT estado::text AS estado, valor_final, ia_pausada,
               ia_pausada_motivo::text AS ia_pausada_motivo,
               responsavel_atual::text AS responsavel_atual,
               motivo_perda::text AS motivo_perda
          FROM barravips.atendimentos WHERE id = %s
        """,
        (aid,),
    )
    row = await res.fetchone()
    assert row is not None
    return row


async def _estado_bloqueio(c: AsyncConnection[dict[str, Any]], bid: UUID) -> str:
    res = await c.execute(
        "SELECT estado::text AS estado FROM barravips.bloqueios WHERE id = %s", (bid,)
    )
    row = await res.fetchone()
    assert row is not None
    return str(row["estado"])


async def _tem_evento(c: AsyncConnection[dict[str, Any]], aid: UUID, tipo: str) -> bool:
    res = await c.execute(
        "SELECT 1 FROM barravips.eventos WHERE atendimento_id = %s AND tipo = %s LIMIT 1",
        (aid, tipo),
    )
    return await res.fetchone() is not None


# --- F1.1: a costura completa ----------------------------------------------------------------

_INSTANCE = "test-instance-f1-1"
_GRUPO_JID = "120363000000000001@g.us"


@pytest.mark.needs_db
async def test_f1_1_webhook_fechado_registra_despausa_e_sincroniza_bloqueio(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """`fechado 1500 #N` entrando pelo webhook do grupo → Fechado + Valor final + bloqueio
    concluído + IA despausada, ponta a ponta (payload Evolution → estado no banco)."""
    modelo_id = await _seed_modelo(conn, instance=_INSTANCE, grupo_jid=_GRUPO_JID)
    cliente_id = await _seed_cliente(conn)
    conversa_id = await _seed_conversa(conn, cliente_id, modelo_id)
    atendimento_id, numero_curto = await _seed_atendimento_em_execucao(
        conn, cliente_id=cliente_id, modelo_id=modelo_id, conversa_id=conversa_id
    )
    bloqueio_id = await _seed_bloqueio(conn, modelo_id=modelo_id, atendimento_id=atendimento_id)
    assert await _estado_bloqueio(conn, bloqueio_id) == "em_atendimento"

    resposta = await _chamar_webhook(
        conn,
        _payload_grupo(
            instance=_INSTANCE,
            grupo_jid=_GRUPO_JID,
            texto=f"fechado 1500 #{numero_curto}",
            message_id=f"cmd-fechado-{uuid4().hex}",
        ),
    )

    assert resposta == {"status": "processed"}

    a = await _ler_atendimento(conn, atendimento_id)
    assert a["estado"] == "Fechado"
    assert a["valor_final"] == Decimal("1500")
    # bloqueio vinculado concluído pelo trigger sync_bloqueio_estado (costura → trigger).
    assert await _estado_bloqueio(conn, bloqueio_id) == "concluido"
    # despausa a IA no encerramento (CONTEXT.md "Registro de resultado").
    assert a["ia_pausada"] is False
    assert a["ia_pausada_motivo"] is None
    # auditoria do Financeiro + transição.
    assert await _tem_evento(conn, atendimento_id, "fechado_registrado")
    assert await _tem_evento(conn, atendimento_id, "transicao_estado")


@pytest.mark.needs_db
async def test_f1_1_webhook_perdido_registra_despausa_e_cancela_bloqueio(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Costura do ramo irmão: `perdido sumiu #N` pelo webhook → Perdido + Motivo de perda +
    bloqueio cancelado + IA despausada. Seed em **Confirmado** com o **bloqueio prévio** ainda
    `bloqueado` (antes do Em_execucao), porque o trigger só cancela o bloqueio no Perdido se ele
    ainda **não** está `em_atendimento`/`concluido` (CONTEXT.md "Bloqueio"; guard provado em
    F0.6). É o cenário realista em que o Perdido de fato sincroniza o bloqueio."""
    modelo_id = await _seed_modelo(conn, instance=_INSTANCE, grupo_jid=_GRUPO_JID)
    cliente_id = await _seed_cliente(conn)
    conversa_id = await _seed_conversa(conn, cliente_id, modelo_id)
    atendimento_id, numero_curto = await _seed_atendimento_em_execucao(
        conn,
        cliente_id=cliente_id,
        modelo_id=modelo_id,
        conversa_id=conversa_id,
        estado="Confirmado",
    )
    bloqueio_id = await _seed_bloqueio(
        conn, modelo_id=modelo_id, atendimento_id=atendimento_id, estado="bloqueado"
    )
    assert await _estado_bloqueio(conn, bloqueio_id) == "bloqueado"

    resposta = await _chamar_webhook(
        conn,
        _payload_grupo(
            instance=_INSTANCE,
            grupo_jid=_GRUPO_JID,
            texto=f"perdido sumiu #{numero_curto}",
            message_id=f"cmd-perdido-{uuid4().hex}",
        ),
    )

    assert resposta == {"status": "processed"}

    a = await _ler_atendimento(conn, atendimento_id)
    assert a["estado"] == "Perdido"
    assert a["motivo_perda"] == "sumiu"
    assert await _estado_bloqueio(conn, bloqueio_id) == "cancelado"
    assert a["ia_pausada"] is False
    assert await _tem_evento(conn, atendimento_id, "perdido_registrado")
    assert await _tem_evento(conn, atendimento_id, "transicao_estado")


@pytest.mark.needs_db
async def test_f1_1_webhook_fechado_sem_valor_nao_encerra_e_da_ack(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Comando malformado pela costura: `fechado #N` (sem valor) → o parser devolve
    `comando_invalido` (`comando.erro` setado) e o handler dá ack `invalid` (200, p/ a
    Evolution não reentregar em loop). **Nada muda** no banco (segue Em_execucao, bloqueio
    em_atendimento): `aplicar_comando('comando_invalido')` só registra o evento, não
    transiciona. Tranca o "+ Valor final" obrigatório atravessando o handler inteiro, não só
    o serviço (F0.8)."""
    modelo_id = await _seed_modelo(conn, instance=_INSTANCE, grupo_jid=_GRUPO_JID)
    cliente_id = await _seed_cliente(conn)
    conversa_id = await _seed_conversa(conn, cliente_id, modelo_id)
    atendimento_id, numero_curto = await _seed_atendimento_em_execucao(
        conn, cliente_id=cliente_id, modelo_id=modelo_id, conversa_id=conversa_id
    )
    bloqueio_id = await _seed_bloqueio(conn, modelo_id=modelo_id, atendimento_id=atendimento_id)

    resposta = await _chamar_webhook(
        conn,
        _payload_grupo(
            instance=_INSTANCE,
            grupo_jid=_GRUPO_JID,
            texto=f"fechado #{numero_curto}",
            message_id=f"cmd-sem-valor-{uuid4().hex}",
        ),
    )

    # parser devolve comando_invalido (valor_final_obrigatorio, com `comando.erro` setado);
    # o handler resolve o #N, aplica (só loga o evento) e dá ack `invalid`.
    assert resposta == {"status": "invalid"}

    a = await _ler_atendimento(conn, atendimento_id)
    assert a["estado"] == "Em_execucao"
    assert a["valor_final"] is None
    assert await _estado_bloqueio(conn, bloqueio_id) == "em_atendimento"
