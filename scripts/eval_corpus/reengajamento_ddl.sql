-- Ponto 5 — Eval de reengajamento offline a partir do corpus real do Vendedor (docs/agente/10 §13).
-- Mina as CUTUCADAS (pokes) reais e mede o lift de revival por movimento/gap.
-- Read-only sobre mensagens_raw; só esta tabela nova recebe DDL/INSERT.
-- Idempotente: CREATE IF NOT EXISTS + PK (instancia, remote_jid, msg_id) — o poke é no nível de MENSAGEM.

-- §13 — Uma linha por CUTUCADA detectada.
-- poke = mensagem from_me cujo ANTERIOR na thread (por ts) também é from_me, gap >= 40 min.
-- reviveu/gap_bucket/tem_midia/comprimento sao DETERMINISTICOS (SQL); movimento/tem_desconto/
-- tipo_silencio vem do juiz multi-voto.
CREATE TABLE IF NOT EXISTS corpus.eval_reengajamento (
  instancia        text    NOT NULL,                 -- eb01..eb04
  remote_jid       text    NOT NULL,                 -- @lid (chave do thread)
  msg_id           text    NOT NULL,                 -- id da mensagem-poke (nivel de mensagem!)
  poke_ts          timestamptz NOT NULL,             -- quando a cutucada saiu
  poke_rank        int     NOT NULL,                 -- 1=primeira cutucada da thread, 2=segunda...
  texto            text,                             -- texto da cutucada (NULL p/ midia)
  -- ground-truth deterministico (SQL, sem juiz):
  reviveu          boolean NOT NULL,                 -- cliente respondeu (from_me=false) em <=24h apos o poke
  gap_min          int     NOT NULL,                 -- minutos de silencio antes da cutucada
  gap_bucket       text    NOT NULL,                 -- 40m-2h | 2-12h | 12-24h | >24h
  tem_midia        boolean NOT NULL,                 -- poke e imagem/video/audio/sticker
  comprimento_chars int    NOT NULL,                 -- length(texto), 0 p/ midia
  -- features do juiz multi-voto (so na amostra codificada; NULL no resto):
  movimento        text,                             -- pergunta_leve|calor_saudade|escassez_partida|midia_nova|desconto|outro
  tem_desconto     boolean,                          -- juiz: a cutucada oferece desconto/preco menor?
  tipo_silencio    text,                             -- silencio_total | desviou_antes
  n_juizes         int,
  n_votos          int,
  concordancia     numeric,
  votos            jsonb,                            -- [{movimento, tem_desconto, tipo_silencio, confianca}]
  justificativa    text,
  hold_out         boolean NOT NULL DEFAULT false,   -- true p/ eb04 (hold-out cross-modelo)
  criado_em        timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (instancia, remote_jid, msg_id)
);
