-- Intencao do cliente extraida pela IA (registrar_extracao / M3d, docs/agente/04 §3.1).
-- Dirige as transicoes de estado da extracao (02 §11): Novo -> Triagem exige intencao
-- definida; Triagem -> Qualificado exige intencao='agendamento' (+ horario + tipo). Precisa
-- ser coluna persistida porque a intencao declarada num turno governa transicoes de turnos
-- seguintes (o cliente diz "quero agendar" antes de informar o horario).
--
-- RLS: coluna nova em tabela existente (atendimentos ja tem RLS habilitada em 0001) — sem
-- nova policy. Sem backfill: registros antigos ficam com intencao NULL (estado preservado).

-- 1) Enum canonico ------------------------------------------------------
DO $$ BEGIN
  CREATE TYPE barravips.intencao_enum AS ENUM (
    'curiosidade',
    'cotacao',
    'agendamento'
  );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

COMMENT ON TYPE barravips.intencao_enum IS
  'Intencao do cliente extraida pela IA (04 §3.1). Dirige Novo->Triagem e Triagem->Qualificado (02 §11).';

-- 2) Coluna nova --------------------------------------------------------
ALTER TABLE barravips.atendimentos
  ADD COLUMN IF NOT EXISTS intencao barravips.intencao_enum;
