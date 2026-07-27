"""Reconciliação do status de WhatsApp com a Evolution — rede de segurança contra painel mentiroso.

O painel lê `modelos.evolution_status`, um cache escrito SÓ por push (`connection.update` no
webhook). Quando o push se perde — ou quando a instância é pareada por fora do painel, direto no
QR da EvoGo (caso `elitebaby01`/Tatiane, 27/07: instância `open` e painel "WhatsApp pendente") —
o cache trava e ninguém o corrige: a auto-cure do `GET /whatsapp/status` só age no estado
`pareando`, e só enquanto o modal de QR está aberto. Esta varredura pergunta o estado à Evolution
e sincroniza nos dois sentidos.

Não toca em `pareando`: esse estado é do fluxo de QR em curso (instância criada, ainda não
escaneada → a Evolution responde `close`), e rebaixá-lo para `desconectado` mataria a auto-cure
do modal no meio do pareamento.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Estado remoto (EvolutionClient.estado_conexao) → `evolution_status` local. `connecting` e
# `unknown` ficam de fora de propósito: o primeiro é pareamento em curso, o segundo é instância
# inexistente ou Evolution fora do ar — nenhum dos dois é evidência de queda.
_STATUS_POR_ESTADO = {"open": "conectado", "close": "desconectado"}


async def reconciliar_conexao_evolution(conn: Any, evolution: Any) -> int:
    """Sincroniza `evolution_status` das modelos com instância vinculada. Devolve quantas linhas
    mudaram de estado."""
    res = await conn.execute(
        """
        SELECT nome, evolution_instance_id, evolution_status
          FROM barravips.modelos
         WHERE evolution_instance_id IS NOT NULL
           AND evolution_status <> 'pareando'
        """
    )
    modelos = await res.fetchall()

    corrigidos = 0
    for modelo in modelos:
        instance_id = modelo["evolution_instance_id"]
        try:
            estado = await evolution.estado_conexao(instance_id)
        except Exception:
            # Evolution instável não pode virar "desconectado" no painel: pula e tenta no próximo
            # tick (mesma postura do `unknown`).
            logger.warning("reconciliar_conexao_falhou instance=%s", instance_id, exc_info=True)
            continue

        status = _STATUS_POR_ESTADO.get(estado)
        if status is None or status == modelo["evolution_status"]:
            continue

        # Casa por `evolution_instance_id` (UNIQUE parcial, 1 instância = 1 modelo) e não pelo
        # `id`: o uuid viria como texto no protocolo estendido do psycopg e o `=` falharia.
        await conn.execute(
            """
            UPDATE barravips.modelos
               SET evolution_status = %s,
                   evolution_pareado_em = CASE WHEN %s = 'conectado' THEN now()
                                               ELSE evolution_pareado_em END
             WHERE evolution_instance_id = %s
            """,
            (status, status, instance_id),
        )
        corrigidos += 1
        logger.info(
            "reconciliar_conexao_corrigido instance=%s de=%s para=%s",
            instance_id,
            modelo["evolution_status"],
            status,
        )
    return corrigidos
