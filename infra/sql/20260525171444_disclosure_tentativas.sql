-- =============================================================================
-- 20260525171444_disclosure_tentativas.sql
-- Adiciona barravips.atendimentos.disclosure_tentativas: contador de perguntas
-- diretas de disclosure ("vc e IA/robo?") por atendimento. O no intercept_disclosure
-- (doc 10 §3.1/§8) incrementa a cada disclosure de alta confianca e escala na 3a vez
-- (disclosure_insistente). Sobrevive a janela deslizante de 20 mensagens.
--
-- A tabela atendimentos ja tem FORCE ROW LEVEL SECURITY (0001 §5); esta migration so
-- adiciona coluna, sem recriar policy. Idempotente (ADD COLUMN IF NOT EXISTS): roda 2x
-- sem erro.
--
-- (Nome timestamp porque o NNNN sequencial ja foi alem de 0039 e migrations aplicadas
--  sao imutaveis -- ver infra/sql/CLAUDE.md.)
--
-- Aplicacao: psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f 20260525171444_disclosure_tentativas.sql
-- =============================================================================

ALTER TABLE barravips.atendimentos
  ADD COLUMN IF NOT EXISTS disclosure_tentativas smallint NOT NULL DEFAULT 0;

COMMENT ON COLUMN barravips.atendimentos.disclosure_tentativas IS
  'Contador de perguntas diretas de disclosure ("vc e IA/robo?") por atendimento. '
  'Incrementado pelo no intercept_disclosure, escala na 3a vez (doc 10 §3.1/§8).';
