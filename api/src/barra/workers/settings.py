"""ARQ WorkerSettings — registra envio, timeouts, pix.

Idempotência: dedupe_key = (conversa_id, turno_id, chunk_idx) consultada antes do envio.
"""
