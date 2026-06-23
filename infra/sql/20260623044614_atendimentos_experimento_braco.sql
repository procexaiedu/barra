-- Trilho do A/B vivo (experimento_braco): carimba cada atendimento num braço do experimento
-- — 'controle' | 'tratamento' —, atribuído de forma determinística e sticky por cliente
-- (md5(cliente_id) % 2) em workers/coordenador.resolver_atendimento, SOMENTE quando o flag
-- settings.experimento_braco_ativo está ligado (default OFF). Com OFF a coluna nem é
-- referenciada na query do agente, então o código roda contra o schema pré-migration —
-- ligar o flag exige ESTA migration aplicada antes.
--
-- NULL = atendimento FORA do experimento: default; atendimento criado pelo painel (Fernando,
-- não é braço da IA) ou criado pela IA com o flag desligado. Sem backfill: atendimentos
-- antigos ficam NULL. A leitura por braço (split do Norte cotada→fechado) é consumo
-- downstream desta coluna, fora desta migration.
ALTER TABLE barravips.atendimentos
  ADD COLUMN IF NOT EXISTS experimento_braco text;

-- DROP+ADD torna o CHECK idempotente (rodar 2x não quebra). Coluna nullable: NULL é estado
-- legítimo (fora do experimento), por isso o CHECK admite NULL.
ALTER TABLE barravips.atendimentos
  DROP CONSTRAINT IF EXISTS atendimentos_experimento_braco_check;
ALTER TABLE barravips.atendimentos
  ADD CONSTRAINT atendimentos_experimento_braco_check
  CHECK (experimento_braco IS NULL OR experimento_braco IN ('controle', 'tratamento'));

COMMENT ON COLUMN barravips.atendimentos.experimento_braco IS
  'Braço do A/B vivo (controle|tratamento|NULL=fora). Atribuído determinístico+sticky por cliente na criação pela IA quando settings.experimento_braco_ativo; NULL sem backfill. Trilho de observabilidade — leitura por braço é downstream.';
