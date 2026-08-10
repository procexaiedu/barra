"""Chaves e TTLs da coalescencia do turno em Redis (01 §4.2).

Sem maquina de estado de debounce: a coalescencia real e o `_job_id` estatico do
`enqueue_job` (SET NX first-wins) somado ao drain loop do coordenador. Aqui ficam so
os nomes de chave e TTLs consumidos por `webhook/despacho.py`.
"""

from uuid import UUID

# TTLs em segundos. Os dois cobrem a janela do `_defer_by` do enqueue (180s, `despacho.py`)
# com folga de 5x: o gate de pendencia do coordenador precisa achar `pending` VIVO quando o job
# deferido finalmente roda, e o drain o rele apos o turno (01 §4.3). Com os 240s anteriores
# sobravam 60s de margem — worker fora do ar por mais que isso (deploy, crash, fila represada)
# fazia a chave expirar e a janela do cliente ser descartada em silencio. `pending` >= `debounce`
# porque `pending` e o unico dos dois que alguem LE; `debounce` e so marcador da janela.
TTL_PENDING = 900
TTL_DEBOUNCE = 900


def chave_pending(conversa_id: UUID | str) -> str:
    return f"pending:conv:{conversa_id}"


def chave_debounce(conversa_id: UUID | str) -> str:
    return f"debounce:conv:{conversa_id}"
