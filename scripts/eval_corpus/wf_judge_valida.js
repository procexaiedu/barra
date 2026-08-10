export const meta = {
  name: 'judge-valida',
  description: 'Roda o judge offline (cego ao label) sobre os turnos reais de cotação para calibrar κ/TPR/TNR vs label_bin',
  phases: [{ title: 'Julgar' }],
}

const N = 52
const MODEL = 'claude-sonnet-4-6'

const sqlBatch = (i) => `WITH pop AS (
  SELECT instancia, remote_jid, cotacao_turno
  FROM corpus.eval_cotacao
  WHERE label_bin IS NOT NULL AND cotacao_turno IS NOT NULL
    AND abs(hashtext(remote_jid)) % ${N} = ${i}
)
SELECT p.instancia, p.remote_jid, p.cotacao_turno,
  string_agg(
    'T' || t.turno_idx || ' ' || (CASE WHEN t.from_me THEN 'V: ' ELSE 'C: ' END) ||
    COALESCE(NULLIF(btrim(t.texto), ''), CASE WHEN t.tem_midia THEN '[midia]' ELSE '[--]' END),
    E'\\n' ORDER BY t.turno_idx
  ) FILTER (WHERE t.turno_idx <= p.cotacao_turno) AS contexto
FROM pop p
JOIN corpus.turnos t USING (instancia, remote_jid)
GROUP BY p.instancia, p.remote_jid, p.cotacao_turno
ORDER BY p.remote_jid`

const SCHEMA = {
  type: 'object',
  properties: {
    preds: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          instancia: { type: 'string' },
          remote_jid: { type: 'string' },
          outcome_pred: { type: 'string', enum: ['GOOD', 'BAD'] },
          rubric_score: { type: 'number', description: '0..1 aderência §12 (quente+limpo)' },
          f_warmth: { type: 'boolean' },
          f_bare: { type: 'boolean' },
          f_glued_urgency: { type: 'boolean' },
          f_glued_question: { type: 'boolean' },
          f_media_fria: { type: 'boolean' },
          confianca: { type: 'number' },
        },
        required: ['instancia', 'remote_jid', 'outcome_pred', 'rubric_score', 'f_warmth', 'f_bare', 'f_glued_urgency', 'f_glued_question', 'f_media_fria', 'confianca'],
      },
    },
  },
  required: ['preds'],
}

const promptBatch = (i) => `Você é um JUIZ offline da qualidade da COTAÇÃO num corpus de vendas por WhatsApp (acompanhante/Elite Baby). O Vendedor (V) se passa pela modelo e atende o Cliente (C). Você avalia COMO o Vendedor entregou o preço — e está CEGO à reação do cliente (ela não aparece no que você vê).

PASSO 1 — Busque seus dados. Use Postgres (procure "pg_execute_query"; se faltar schema, ToolSearch "select:mcp__postgres__pg_execute_query"). Rode EXATAMENTE (operation="select"):

${sqlBatch(i)}

Cada linha: instancia, remote_jid, cotacao_turno, e contexto (transcript "Tn V/C: ..." até e incluindo o turno cotacao_turno). A ÚLTIMA fala do Vendedor (em T{cotacao_turno}) é a COTAÇÃO — o turno que você avalia. O que vem antes é o lead-up do Cliente. NÃO há reação do cliente à cotação (é o que se quer prever).

PASSO 2 — Para cada thread, avalie a COTAÇÃO (a última fala V) pela rubrica de §12:
- f_warmth — tom caloroso: "amor/vida/carinhosa", acolhimento, emoji orgânico. (+ é a única alavanca robusta)
- f_bare — preço seco isolado, sem calor.
- f_glued_urgency — pressa colada ao número: "seria agora?", "vamos confirmar?", "vem agora". (− forte: empurrão afasta)
- f_glued_question — pergunta/CTA de fechamento colada ao preço.
- f_media_fria — mídia fria disparada junto do preço.

Depois produza:
- rubric_score (0..1): aderência à prescrição §12 = QUENTE + LIMPO, sem urgência/pergunta colada. Alto = cota com calor e sem empurrão. NÃO premie urgência.
- outcome_pred (GOOD|BAD): sua aposta de engajamento — GOOD se quente e limpo; BAD se seco ou com empurrão. Seja honesto: a entrega quase não determina o desfecho, então confianca modesta.

REGRAS:
- Avalie SÓ a cotação (última fala V) e o tom; não invente reação do cliente.
- Retorne TODAS as threads do batch via saída estruturada.`

phase('Julgar')

const batches = Array.from({ length: N }, (_, i) => i)
const perBatch = await pipeline(
  batches,
  (i) => agent(promptBatch(i), { label: `judge-b${i}`, phase: 'Julgar', schema: SCHEMA, model: MODEL }),
)

const preds = perBatch.filter(Boolean).flatMap(p => p.preds || [])

const distPred = {}
let warmth = 0, urg = 0
for (const p of preds) {
  distPred[p.outcome_pred] = (distPred[p.outcome_pred] || 0) + 1
  if (p.f_warmth) warmth++
  if (p.f_glued_urgency) urg++
}

return {
  resumo: {
    n: preds.length,
    batches_ok: perBatch.filter(Boolean).length,
    distPred,
    pct_warmth: preds.length ? +(100 * warmth / preds.length).toFixed(1) : 0,
    pct_glued_urgency: preds.length ? +(100 * urg / preds.length).toFixed(1) : 0,
  },
  preds,
}
