"""Chaves e TTLs da coalescencia do turno em Redis (01 §4.2).

Sem maquina de estado de debounce: a coalescencia real e o `_job_id` estatico do
`enqueue_job` (SET NX first-wins) somado ao drain loop do coordenador. Aqui ficam so
os nomes de chave e TTLs consumidos por `webhook/despacho.py`.
"""

from uuid import UUID

# TTLs em segundos. `pending` > `debounce` > janela do `_defer_by` (180s): o drain do
# coordenador le `pending` apos o turno (01 §4.3) e o gate de pendencia precisa achar a
# chave viva quando o job deferido rodar; `debounce` cobre a janela do `_defer_by`.
TTL_PENDING = 240
TTL_DEBOUNCE = 200


def chave_pending(conversa_id: UUID | str) -> str:
    return f"pending:conv:{conversa_id}"


def chave_debounce(conversa_id: UUID | str) -> str:
    return f"debounce:conv:{conversa_id}"
