"""Backfill dos atendimentos presos ANTES do deploy da issue #98 (b612e38, 21/07).

Contexto: a pausa em massa antiga gravava `ia_pausada_motivo='modelo_em_atendimento'` — o mesmo
motivo do "modelo está com o cliente agora" (pós-Pix/pós-Foto). A volta cirúrgica do #98 só solta
o balde novo (`modelo_pausada`), então quem foi pausado ANTES do deploy ficou preso para sempre:
cliente escreve e a IA nunca responde (reclamação do Fernando, 21/07 19:05 — "Foi respondido
apenas 1 mensagem").

O que faz (mesma semântica do POST /modelos/{id}/ativar para os presos, ver
dominio/modelos/routes.py::ativar_modelo): para cada atendimento NÃO-terminal da modelo com
`ia_pausada=true` e motivo `modelo_em_atendimento` em estado PRÉ-execução (Novo/Triagem/
Qualificado — nunca Confirmado/Em_execucao, que são a modelo com o cliente de verdade), abre um
Handoff `modelo_pausada` via `abrir_handoff` (muda o motivo para `handoff_ia`, cria escalada; o
card no grupo de Coordenação sai pelo cron `reconciliar_cards_escalada`). A volta é a Devolução
de sempre: `IA assume` respondendo o card, ou o botão do painel.

⚠️ ESCREVE NO BANCO APONTADO POR --dsn E DISPARA CARDS REAIS via cron. Rodar contra produção
só com autorização explícita (CLAUDE.md §0). Use --dry-run primeiro (só lista).

Uso:
    uv run python ../scripts/backfill_presos_pre_98.py --dsn "$PROD_DSN" --modelo <uuid> --dry-run
    uv run python ../scripts/backfill_presos_pre_98.py --dsn "$PROD_DSN" --modelo <uuid>
"""

import argparse
import asyncio

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from barra.dominio.escaladas.modelos import TipoEscalada
from barra.dominio.escaladas.service import abrir_handoff

_ESTADOS_PRE_EXECUCAO = ("Novo", "Triagem", "Qualificado")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dsn", required=True)
    ap.add_argument("--modelo", required=True, help="modelo_id (uuid)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    conn = await AsyncConnection.connect(args.dsn, row_factory=dict_row)
    try:
        async with conn.transaction():
            res = await conn.execute(
                """
                SELECT a.id, a.numero_curto, a.estado::text AS estado, a.created_at
                  FROM barravips.atendimentos a
                 WHERE a.modelo_id = %s
                   AND a.estado = ANY(%s::barravips.estado_atendimento_enum[])
                   AND a.ia_pausada = true
                   AND a.ia_pausada_motivo = 'modelo_em_atendimento'
                 ORDER BY a.created_at
                 FOR UPDATE OF a
                """,
                (args.modelo, list(_ESTADOS_PRE_EXECUCAO)),
            )
            presos = await res.fetchall()
            for p in presos:
                print(f"preso: #{p['numero_curto']} {p['id']} estado={p['estado']} desde {p['created_at']}")
            if args.dry_run or not presos:
                print(f"{len(presos)} presos; dry-run={args.dry_run} — nada alterado.")
                await conn.rollback()
                return
            for p in presos:
                await abrir_handoff(
                    conn,
                    atendimento_id=p["id"],
                    responsavel="modelo",
                    tipo=TipoEscalada.modelo_pausada,
                    resumo_operacional="Cliente ficou sem resposta enquanto voce estava pausada.",
                    acao_esperada="Retome a conversa com o cliente",
                    origem="painel",
                    autor="Fernando",
                )
        print(f"{len(presos)} handoffs abertos — cards saem pelo cron reconciliar_cards_escalada.")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
