-- Adiciona valor 'dados_editados' em barravips.tipo_evento_enum.
-- Bug encontrado em validação E2E 2026-05-14: PATCH /v1/atendimentos/{id}/dados
-- grava evento 'dados_editados' em barravips.eventos, mas o enum criado em
-- 0001_schema_inicial.sql não inclui esse valor, devolvendo 500
-- InvalidTextRepresentation.

ALTER TYPE barravips.tipo_evento_enum ADD VALUE IF NOT EXISTS 'dados_editados';
