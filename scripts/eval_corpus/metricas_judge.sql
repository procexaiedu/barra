-- Métricas de calibração do judge offline (entregável 4).
-- Compara outcome_pred (cego ao label) vs corpus.eval_cotacao.label_bin.
-- Reporta confusão + acurácia + TPR (recall GOOD) + TNR (recall BAD) + Cohen's κ,
-- por recorte (geral / eb04 hold-out / eb01-03 calibração). Base ~54% GOOD: acurácia crua engana, κ é o que vale.

-- :recorte controla o split — rode 3×: 'all' | 'eb04' | 'calib'
WITH j AS (
  SELECT p.outcome_pred, p.rubric_score, p.f_warmth, p.f_bare, p.f_glued_urgency,
         p.f_glued_question, p.f_media_fria, c.label_bin, c.hold_out
  FROM corpus.eval_judge_pred p
  JOIN corpus.eval_cotacao c USING (instancia, remote_jid)
  WHERE c.label_bin IS NOT NULL AND p.run_tag = 'v1'
    AND (:'recorte' = 'all'
         OR (:'recorte' = 'eb04'  AND c.hold_out)
         OR (:'recorte' = 'calib' AND NOT c.hold_out))
),
m AS (
  SELECT count(*)::numeric n,
    count(*) FILTER (WHERE outcome_pred='GOOD' AND label_bin='GOOD')::numeric tp,
    count(*) FILTER (WHERE outcome_pred='BAD'  AND label_bin='BAD')::numeric  tn,
    count(*) FILTER (WHERE outcome_pred='GOOD' AND label_bin='BAD')::numeric  fp,
    count(*) FILTER (WHERE outcome_pred='BAD'  AND label_bin='GOOD')::numeric  fn
  FROM j
),
k AS (
  SELECT *,
    (tp+tn)/n AS po,
    ((tp+fp)/n)*((tp+fn)/n) + ((fn+tn)/n)*((fp+tn)/n) AS pe
  FROM m
)
SELECT :'recorte' AS recorte, n::int, tp::int, tn::int, fp::int, fn::int,
  round(po,3) AS acuracia,
  round(tp/nullif(tp+fn,0),3) AS tpr_recall_good,
  round(tn/nullif(tn+fp,0),3) AS tnr_recall_bad,
  round((po-pe)/nullif(1-pe,0),3) AS cohen_kappa
FROM k;

-- Lift por feature (§12): % GOOD com a feature vs sem — replica os lifts de §12 (warmth deve ser +).
WITH j AS (
  SELECT p.f_warmth, p.f_bare, p.f_glued_urgency, p.f_glued_question, p.f_media_fria, c.label_bin
  FROM corpus.eval_judge_pred p
  JOIN corpus.eval_cotacao c USING (instancia, remote_jid)
  WHERE c.label_bin IS NOT NULL AND p.run_tag = 'v1'
), f AS (
  SELECT 'f_warmth' feat, f_warmth v, label_bin FROM j
  UNION ALL SELECT 'f_bare', f_bare, label_bin FROM j
  UNION ALL SELECT 'f_glued_urgency', f_glued_urgency, label_bin FROM j
  UNION ALL SELECT 'f_glued_question', f_glued_question, label_bin FROM j
  UNION ALL SELECT 'f_media_fria', f_media_fria, label_bin FROM j
)
SELECT feat,
  count(*) FILTER (WHERE v) n_com,
  round(100.0*avg((label_bin='GOOD')::int) FILTER (WHERE v),1) good_pct_com,
  round(100.0*avg((label_bin='GOOD')::int) FILTER (WHERE NOT v),1) good_pct_sem,
  round(100.0*avg((label_bin='GOOD')::int) FILTER (WHERE v) - 100.0*avg((label_bin='GOOD')::int) FILTER (WHERE NOT v),1) lift
FROM f GROUP BY feat ORDER BY lift DESC;

-- rubric_score vs desfecho real: o score de aderência §12 separa GOOD de BAD?
WITH j AS (
  SELECT p.rubric_score, c.label_bin
  FROM corpus.eval_judge_pred p
  JOIN corpus.eval_cotacao c USING (instancia, remote_jid)
  WHERE c.label_bin IS NOT NULL AND p.run_tag = 'v1'
)
SELECT label_bin, count(*) n, round(avg(rubric_score),3) rubric_medio
FROM j GROUP BY label_bin ORDER BY label_bin;
