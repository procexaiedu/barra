"""Chaves e TTLs da coalescencia do turno em Redis (01 §4.2).

Sem maquina de estado de debounce: a coalescencia real e o `_job_id` estatico do
`enqueue_job` (SET NX first-wins) somado ao drain loop do coordenador. Aqui ficam so
os nomes de chave e TTLs consumidos por `webhook/despacho.py`.
"""

from uuid import UUID

# TTLs em segundos. `pending` > `debounce`: o drain do coordenador le `pending` apos o
# turno (01 §4.3); `debounce` e a janela curta do `_defer_by` do enqueue.
TTL_PENDING = 120
TTL_DEBOUNCE = 10


def chave_pending(conversa_id: UUID | str) -> str:
    return f"pending:conv:{conversa_id}"


def chave_debounce(conversa_id: UUID | str) -> str:
    return f"debounce:conv:{conversa_id}"
