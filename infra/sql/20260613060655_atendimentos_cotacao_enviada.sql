-- Âncora do reengajamento (ADR 0022): marca quando a IA apresentou o preço pela 1ª vez.
-- Substitui o proxy `intencao IN ('cotacao','agendamento')` no cron `reengajar_silenciosos`,
-- que disparava antes de a IA cotar. First-write-wins (carimbado por marcar_cotacao_enviada,
-- guard cotacao_enviada_em IS NULL). Schema-only — não aplicar seeds em prod.
ALTER TABLE barravips.atendimentos
  ADD COLUMN IF NOT EXISTS cotacao_enviada_em timestamptz;

COMMENT ON COLUMN barravips.atendimentos.cotacao_enviada_em IS
  'Instante em que a IA apresentou o preço pela 1ª vez (first-write-wins). Âncora do reengajamento (ADR 0022).';
