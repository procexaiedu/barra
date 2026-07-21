-- Retomada da modelo (issue #98): motivo/tipo próprios para "pausado porque a modelo não estava
-- ativa" (freio manual), hoje indistinguível de `modelo_em_atendimento` — que significa "a modelo
-- está com o cliente agora" (pós-Pix/pós-Foto de portaria, CONTEXT.md). Sem essa distinção a volta
-- não tem como ser cirúrgica: soltar por `modelo_em_atendimento` mexeria em atendimentos
-- legitimamente em execução. O painel também escondia os presos, porque filtra
-- `modelo_em_atendimento` não-expirado (dominio/painel/routes.py).
--
-- ALTER TYPE ... ADD VALUE é idempotente via IF NOT EXISTS. Postgres exige que o ADD VALUE rode
-- FORA de bloco transacional (mesmo do psycopg autocommit). O script make migrate aplica cada
-- arquivo em transação por padrão, então este precisa ser aplicado manualmente via psycopg em
-- autocommit ou via Studio (mesma ressalva de 20260720220000_escalada_e_motivo_pausa_manual.sql).

ALTER TYPE barravips.ia_pausada_motivo_enum ADD VALUE IF NOT EXISTS 'modelo_pausada';
ALTER TYPE barravips.tipo_escalada_enum ADD VALUE IF NOT EXISTS 'modelo_pausada';
