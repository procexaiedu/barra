-- Metricas do eval de reengajamento (ponto 5 / §13). Read-only sobre corpus.eval_reengajamento.
-- A populacao "limpa" = threads de cliente @lid com thread_ops=false (exclui grupos e ops).

-- 0) Sanity da deteccao de poke (deve bater ~1019 pokes / 477 threads do §13).
SELECT count(*) n_pokes, count(DISTINCT (instancia||remote_jid)) n_threads
FROM corpus.eval_reengajamento;

-- 1) Decay por gap (revival), populacao limpa.
WITH er AS (
  SELECT e.* FROM corpus.eval_reengajamento e
  JOIN corpus.threads t USING (instancia, remote_jid)
  WHERE t.thread_ops=false
)
SELECT gap_bucket, count(*) n, sum(reviveu::int) rev,
       round(100.0*avg(reviveu::int),1) reviveu_pct
FROM er GROUP BY gap_bucket
ORDER BY CASE gap_bucket WHEN '40m-2h' THEN 1 WHEN '2-12h' THEN 2 WHEN '12-24h' THEN 3 ELSE 4 END;

-- 2) Lift por movimento (revival) + share do mix humano.
WITH er AS (
  SELECT e.* FROM corpus.eval_reengajamento e
  JOIN corpus.threads t USING (instancia, remote_jid)
  WHERE t.thread_ops=false AND e.movimento IS NOT NULL
)
SELECT movimento, count(*) n,
       round(100.0*count(*)/sum(count(*)) OVER (),1) share_humano_pct,
       round(100.0*avg(reviveu::int),1) reviveu_pct,
       round(avg(concordancia),2) conc_media
FROM er GROUP BY movimento ORDER BY reviveu_pct DESC;

-- 3) Confound: movimento x gap (revela que escassez=94% gap>24h, calor e flat).
WITH er AS (
  SELECT e.* FROM corpus.eval_reengajamento e
  JOIN corpus.threads t USING (instancia, remote_jid)
  WHERE t.thread_ops=false AND e.movimento IS NOT NULL
)
SELECT movimento, gap_bucket, count(*) n, round(100.0*avg(reviveu::int),0) reviveu_pct
FROM er
WHERE movimento IN ('pergunta_leve','calor_saudade','escassez_partida')
GROUP BY movimento, gap_bucket
ORDER BY movimento, CASE gap_bucket WHEN '40m-2h' THEN 1 WHEN '2-12h' THEN 2 WHEN '12-24h' THEN 3 ELSE 4 END;

-- 4) Generalizacao cross-modelo (hold-out eb04 vs eb01-03).
WITH er AS (
  SELECT e.* FROM corpus.eval_reengajamento e
  JOIN corpus.threads t USING (instancia, remote_jid)
  WHERE t.thread_ops=false AND e.movimento IS NOT NULL
)
SELECT (instancia='eb04') AS holdout, movimento, count(*) n,
       round(100.0*avg(reviveu::int),0) reviveu_pct
FROM er WHERE movimento IN ('pergunta_leve','calor_saudade','escassez_partida')
GROUP BY (instancia='eb04'), movimento ORDER BY movimento, holdout;

-- 5) Confiabilidade da codificacao (unanimidade / concordancia).
WITH er AS (
  SELECT e.* FROM corpus.eval_reengajamento e
  JOIN corpus.threads t USING (instancia, remote_jid)
  WHERE t.thread_ops=false AND e.movimento IS NOT NULL
)
SELECT count(*) total,
       round(100.0*count(*) FILTER (WHERE n_votos=3)/count(*),1) unanime_pct,
       round(avg(concordancia),3) conc_media
FROM er;
