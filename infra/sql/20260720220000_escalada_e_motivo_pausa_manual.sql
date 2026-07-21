-- Handoff manual por operador (ADR-0032, spec docs/specs/0003-handoff-manual-operador.md):
-- novo motivo/tipo distintos dos automáticos (Pix, Foto de portaria, Lembrete de fechamento)
-- para diferenciar no dashboard/observabilidade uma pausa por decisão humana livre de uma
-- pausa determinística do state machine.
--
-- ALTER TYPE ... ADD VALUE é idempotente via IF NOT EXISTS. Postgres exige que o ADD VALUE rode
-- FORA de bloco transacional (mesmo do psycopg autocommit). O script make migrate aplica cada
-- arquivo em transação por padrão, então este precisa ser aplicado manualmente via psycopg em
-- autocommit ou via Studio (mesma ressalva de 20260613120100_escalada_tipo_video_chamada.sql).

ALTER TYPE barravips.ia_pausada_motivo_enum ADD VALUE IF NOT EXISTS 'pausa_manual_operador';
ALTER TYPE barravips.tipo_escalada_enum ADD VALUE IF NOT EXISTS 'pausa_manual_operador';
