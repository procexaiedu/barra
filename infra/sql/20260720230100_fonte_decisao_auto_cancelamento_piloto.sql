-- Cancelamento automatico de seguranca do piloto de teste (ADR-0033): fonte de decisao propria
-- p/ diferenciar no dashboard/observabilidade um cancelamento automatico do piloto (safety net,
-- sem cliente real de verdade) dos demais timeouts/transicoes ja existentes.
--
-- ALTER TYPE ... ADD VALUE e idempotente via IF NOT EXISTS. Postgres exige que o ADD VALUE rode
-- FORA de bloco transacional -- este arquivo precisa ser aplicado manualmente via psycopg em
-- autocommit ou via Studio (mesma ressalva de 20260720220000_escalada_e_motivo_pausa_manual.sql).

ALTER TYPE barravips.fonte_decisao_enum ADD VALUE IF NOT EXISTS 'auto_cancelamento_piloto';
