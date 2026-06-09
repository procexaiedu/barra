"""Placeholder — não implementado.

A validação de borda do webhook NÃO vive aqui. Ela está distribuída em `routes.py`
(token HMAC → 401; instância cadastrada + UNIQUE `evolution_instance_id`) e em
`despacho.py`/`debounce.py` (dedupe por `evolution_message_id` + coalescência de turno).
`settings.jid_permitido` é allowlist de teste da Fase 1.5, não um gate de produção.
Ver `webhook/CLAUDE.md` ("A borda real").
"""
