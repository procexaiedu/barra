"""Persistencia de uma corrida e2e em barravips, para o Fernando avaliar no painel /observabilidade.

Diferente do harness padrao (seed + ROLLBACK), aqui os turnos COMMITAM: a conversa nasce com
`origem='e2e'` (o painel a esconde por padrao; o Fernando ve com o filtro "E2E") sob uma MODELO
SANDBOX fixa e identificavel. A cada turno gravamos a resposta da IA em `mensagens` (direcao='ia')
— em producao quem faz isso e o worker de envio, que nao roda no harness.

⚠️ §0: isto ESCREVE em prod (commit). Exige a migration `*_conversas_origem_e2e.sql` aplicada e
autorizacao do dev. e2e nunca chega a 'Fechado', entao nao entra no financeiro. `limpar_sandbox`
remove tudo da modelo sandbox quando quiser.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from psycopg import AsyncConnection

from evals.harness import Cenario, _seed_programa

from .perfil import MODELO_SINTETICA, PerfilCaso

# Modelo sandbox fixa: todas as conversas e2e ficam sob ela (filtravel por modelo no painel, alem
# do filtro de origem). Nome com prefixo obvio para o Fernando reconhecer.
SANDBOX_MODELO_ID = UUID("e2e00000-0000-4000-8000-000000000001")
SANDBOX_NOME = "🧪 E2E Sandbox"


async def garantir_modelo_sandbox(conn: AsyncConnection[dict[str, Any]]) -> None:
    """Get-or-create idempotente da modelo sandbox + seus programas sinteticos. COMMITA."""
    res = await conn.execute("SELECT 1 FROM barravips.modelos WHERE id = %s", (SANDBOX_MODELO_ID,))
    if await res.fetchone() is None:
        await conn.execute(
            """
            INSERT INTO barravips.modelos
                (id, nome, idade, numero_whatsapp, valor_padrao, tipo_atendimento_aceito,
                 localizacao_operacional, endereco_formatado)
            VALUES (%s, %s, %s, %s, %s, %s::barravips.tipo_atendimento_enum[], %s, %s)
            ON CONFLICT (id) DO NOTHING
            """,
            (
                SANDBOX_MODELO_ID,
                SANDBOX_NOME,
                MODELO_SINTETICA["idade"],
                "e2e-sandbox",
                500,
                MODELO_SINTETICA["tipo_atendimento_aceito"],
                MODELO_SINTETICA["localizacao_operacional"],
                MODELO_SINTETICA["endereco_formatado"],
            ),
        )
        for prog in MODELO_SINTETICA["programas"]:
            await _seed_programa(conn, SANDBOX_MODELO_ID, prog)
    await conn.commit()


async def seed_caso_persistente(
    conn: AsyncConnection[dict[str, Any]], perfil: PerfilCaso
) -> Cenario:
    """Cria cliente/conversa(origem='e2e')/atendimento('Novo') sob a modelo sandbox. COMMITA."""
    await garantir_modelo_sandbox(conn)

    cliente_id = uuid4()
    await conn.execute(
        "INSERT INTO barravips.clientes (id, telefone, nome) VALUES (%s, %s, %s)",
        (cliente_id, f"e2e-{uuid4().hex[:12]}", f"E2E {perfil.desfecho_real} {perfil.thread_ref}"),
    )

    conversa_id = uuid4()
    await conn.execute(
        """
        INSERT INTO barravips.conversas (id, cliente_id, modelo_id, evolution_chat_id, origem)
        VALUES (%s, %s, %s, %s, 'e2e')
        """,
        (conversa_id, cliente_id, SANDBOX_MODELO_ID, f"e2e-chat-{uuid4().hex}"),
    )

    numero = await _proximo_numero_curto(conn)
    atendimento_id = uuid4()
    await conn.execute(
        """
        INSERT INTO barravips.atendimentos
            (id, numero_curto, cliente_id, modelo_id, conversa_id, estado, pix_status, ia_pausada)
        VALUES (%s, %s, %s, %s, %s, 'Novo', 'nao_solicitado', false)
        """,
        (atendimento_id, numero, cliente_id, SANDBOX_MODELO_ID, conversa_id),
    )
    await conn.commit()
    return Cenario(
        cliente_id=cliente_id,
        modelo_id=SANDBOX_MODELO_ID,
        conversa_id=conversa_id,
        atendimento_id=atendimento_id,
        programas=list(MODELO_SINTETICA["programas"]),
    )


async def _proximo_numero_curto(conn: AsyncConnection[dict[str, Any]]) -> int:
    res = await conn.execute(
        "SELECT COALESCE(MAX(numero_curto), 0) + 1 AS n FROM barravips.atendimentos WHERE modelo_id = %s",
        (SANDBOX_MODELO_ID,),
    )
    row = await res.fetchone()
    return int(row["n"]) if row else 1


async def gravar_resposta_ia(
    conn: AsyncConnection[dict[str, Any]], cen: Cenario, texto: str
) -> None:
    """Grava a bolha da IA em `mensagens` (direcao='ia') para o painel mostra-la. NAO commita —
    o caller (sessao) commita o turno inteiro (UPDATEs do grafo + msg cliente + esta bolha).

    No harness o worker de envio nao roda, entao a resposta da IA nao chega a `mensagens` sozinha.
    """
    if not texto.strip():
        return
    await conn.execute(
        """
        INSERT INTO barravips.mensagens
            (id, conversa_id, atendimento_id, direcao, tipo, conteudo, evolution_message_id)
        VALUES (%s, %s, %s, 'ia', 'texto', %s, %s)
        """,
        (uuid4(), cen.conversa_id, cen.atendimento_id, texto, f"e2e-ia-{uuid4().hex}"),
    )


async def limpar_sandbox(conn: AsyncConnection[dict[str, Any]]) -> int:
    """Remove TODAS as conversas/atendimentos/mensagens/clientes da modelo sandbox (e a propria
    modelo). Mensagens e avaliacoes caem por ON DELETE CASCADE. Retorna nº de conversas removidas.
    COMMITA. Use para limpar os dados de teste do painel."""
    res = await conn.execute(
        "SELECT DISTINCT cliente_id FROM barravips.conversas WHERE modelo_id = %s",
        (SANDBOX_MODELO_ID,),
    )
    clientes = [r["cliente_id"] for r in await res.fetchall()]
    await conn.execute(
        "DELETE FROM barravips.atendimentos WHERE modelo_id = %s", (SANDBOX_MODELO_ID,)
    )
    rc = await conn.execute(
        "DELETE FROM barravips.conversas WHERE modelo_id = %s", (SANDBOX_MODELO_ID,)
    )
    removidas = rc.rowcount
    for cliente_id in clientes:
        await conn.execute("DELETE FROM barravips.clientes WHERE id = %s", (cliente_id,))
    await conn.execute("DELETE FROM barravips.modelos WHERE id = %s", (SANDBOX_MODELO_ID,))
    await conn.commit()
    return removidas
