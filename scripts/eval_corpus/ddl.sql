-- Ponto 2 — Eval set offline a partir do corpus real do Vendedor (docs/agente/10 §11/§12).
-- Tabelas de avaliação persistidas no schema corpus.* (mesmo Postgres do MCP).
-- Read-only sobre mensagens_raw/turnos/threads; só estas tabelas novas recebem DDL/INSERT.
-- Idempotente: CREATE IF NOT EXISTS + PK (instancia, remote_jid) para upsert.

-- §12 — Reação imediata à cotação como ground-truth (não o proxy determinístico).
-- Uma linha por thread COM cotação (corpus.threads.tem_valor AND NOT thread_ops).
CREATE TABLE IF NOT EXISTS corpus.eval_cotacao (
  instancia      text    NOT NULL,                 -- eb01..eb04
  remote_jid     text    NOT NULL,                 -- @lid (chave do thread, não telefone)
  reacao_real    text    NOT NULL,                 -- fechou_logistica|engajou|silenciou|desviou|objecao_preco|cotacao_nao_encontrada
  label_bin      text,                             -- GOOD|BAD (null quando cotacao_nao_encontrada)
  n_juizes       int     NOT NULL,                 -- total de juízes que votaram (3)
  n_votos        int     NOT NULL,                 -- juízes que votaram na reação majoritária
  concordancia   numeric NOT NULL,                 -- n_votos / n_juizes
  votos          jsonb   NOT NULL,                 -- [{reacao, confianca}] dos juízes
  justificativa  text,                             -- nota curta do juiz majoritário (spot-check)
  cotacao_turno  int,                              -- turno_idx da cotação localizada (contexto = turnos <= este)
  desfecho_proxy text,                             -- snapshot do proxy para cross-check (§12: silenciou→sumiu)
  hold_out       boolean NOT NULL DEFAULT false,   -- true para eb04 (hold-out cross-modelo, §2/§14)
  criado_em      timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (instancia, remote_jid)
);

-- §11 — Motivo de perda por thread + se foi declarado ou sumiço mudo.
-- Uma linha por thread perdida (proxy perdido_sumiu/perdido_objecao/qualificado_sem_prova, NOT thread_ops).
CREATE TABLE IF NOT EXISTS corpus.eval_perda (
  instancia      text    NOT NULL,
  remote_jid     text    NOT NULL,
  motivo         text    NOT NULL,                 -- enum CONTEXT: sumiu|indisponibilidade|preco|risco|fora_de_area|outro
  declarado      boolean NOT NULL,                 -- true=declarado | false=sumiço mudo
  bloco_grosso   text,                             -- onde a perda nasce (sinal robusto §11): pos_cotacao|pre_cotacao|sem_cotacao
  n_juizes       int     NOT NULL,
  n_votos        int     NOT NULL,
  concordancia   numeric NOT NULL,
  votos          jsonb   NOT NULL,                 -- [{motivo, declarado, confianca}] dos juízes
  justificativa  text,
  obs            text,                             -- exigido quando motivo=outro
  desfecho_proxy text,
  hold_out       boolean NOT NULL DEFAULT false,
  criado_em      timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (instancia, remote_jid)
);

-- Predições do judge offline (entregável 4): roda cego ao label_bin sobre os turnos reais
-- e é comparado com corpus.eval_cotacao.label_bin para calibração (κ/TPR/TNR). Ver judge_prompt.md.
CREATE TABLE IF NOT EXISTS corpus.eval_judge_pred (
  instancia        text    NOT NULL,
  remote_jid       text    NOT NULL,
  outcome_pred     text    NOT NULL,              -- GOOD|BAD
  rubric_score     numeric,                       -- 0..1 aderência §12 (quente+limpo)
  f_warmth         boolean,
  f_bare           boolean,
  f_glued_urgency  boolean,
  f_glued_question boolean,
  f_media_fria     boolean,
  confianca        numeric,
  run_tag          text    NOT NULL DEFAULT 'v1', -- versão do prompt do juiz
  criado_em        timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (instancia, remote_jid, run_tag)
);
