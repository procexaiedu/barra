export const meta = {
  name: 'rotular-cotacao',
  description: 'Rotula a reação imediata à cotação (§12) em todas as 784 threads com cotação — 3 juízes, voto majoritário',
  phases: [{ title: 'Rotular' }],
}

// ---- parâmetros ----
const N = 60          // partições hash → ~13 threads por batch
const CAP = 40        // turnos máximos no transcript (cotação é cedo; foco na reação imediata)
const N_JUIZES = 3
const MODEL = 'claude-sonnet-4-6'

const sqlBatch = (i) => `WITH pop AS (
  SELECT instancia, remote_jid
  FROM corpus.threads
  WHERE tem_valor AND NOT thread_ops
    AND abs(hashtext(remote_jid)) % ${N} = ${i}
)
SELECT p.instancia, p.remote_jid,
  string_agg(
    'T' || t.turno_idx || ' ' || (CASE WHEN t.from_me THEN 'V: ' ELSE 'C: ' END) ||
    COALESCE(NULLIF(btrim(t.texto), ''), CASE WHEN t.tem_midia THEN '[midia]' ELSE '[--]' END),
    E'\\n' ORDER BY t.turno_idx
  ) FILTER (WHERE t.turno_idx <= ${CAP}) AS transcript
FROM pop p
JOIN corpus.turnos t USING (instancia, remote_jid)
GROUP BY p.instancia, p.remote_jid
ORDER BY p.remote_jid`

const SCHEMA = {
  type: 'object',
  properties: {
    labels: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          instancia: { type: 'string' },
          remote_jid: { type: 'string' },
          cotacao_turno: { type: ['integer', 'null'] },
          reacao: { type: 'string', enum: ['fechou_logistica', 'engajou', 'silenciou', 'desviou', 'objecao_preco', 'cotacao_nao_encontrada'] },
          confianca: { type: 'number' },
          justificativa: { type: 'string' },
        },
        required: ['instancia', 'remote_jid', 'cotacao_turno', 'reacao', 'confianca', 'justificativa'],
      },
    },
  },
  required: ['labels'],
}

const promptBatch = (i) => `Você é um anotador de um corpus de vendas por WhatsApp (acompanhante/Elite Baby). O Vendedor (V) se passa pela modelo e atende o Cliente (C). Tarefa: para CADA thread do seu batch, classificar a REAÇÃO IMEDIATA do Cliente à COTAÇÃO de preço.

PASSO 1 — Busque seus dados. Use Postgres (procure "pg_execute_query"; se faltar schema, faça ToolSearch "select:mcp__postgres__pg_execute_query"). Rode EXATAMENTE (operation="select"):

${sqlBatch(i)}

Cada linha é uma thread (instancia, remote_jid, transcript). No transcript, "Tn V: ..." = Vendedor, "Tn C: ..." = Cliente, "[midia]" = foto/vídeo, Tn = índice do turno.

PASSO 2 — Para cada thread:
a) Ache a COTAÇÃO: PRIMEIRO turno V com PREÇO de programa (ex.: "400 1h no meu local", "cachê 600"). Pix/uber/deslocamento NÃO é a cotação. Sem preço no transcript → reacao="cotacao_nao_encontrada", cotacao_turno=null.
b) Classifique a reação IMEDIATA do Cliente nos 1–3 turnos do Cliente LOGO APÓS a cotação. Classifique a reação AO NÚMERO, não o desfecho final — uma conversa que esfria 20 turnos depois ainda pode ter "engajou" na hora.

ENUM (escolha 1):
- fechou_logistica — C dá COMPROMISSO concreto de encontro: passa/aceita horário, dá endereço de chegada, "bora/confirmado/fechou", manda localização, topa uber/pix. (Apenas PERGUNTAR região/horário/se atende fora NÃO é fechou — isso é engajou.)
- engajou — C reage positivo/quente sem ainda fechar logística: elogia, "adorei", manda mídia, pergunta sobre serviço/região/horário, segue interessado.
- silenciou — C não responde após o número (nenhum turno C após a cotação, ou só some).
- desviou — C enrola/esfria sem objeção de preço: "vou ver", "depois te chamo", muda de assunto, encerra por motivo pessoal.
- objecao_preco — C reclama do valor: "tá caro", "salgado", "achei que era menos", contrapropõe valor menor.

REGRAS:
- Só a reação do Cliente, só a janela imediata pós-cotação. Ignore o que o V faz e o que ocorre muito depois.
- Mídia do Cliente logo após a cotação conta como engajou, salvo se já fechou logística.
- confianca honesta (fronteiras engajou↔fechou_logistica e engajou↔desviou são borradas).
- Retorne TODAS as threads do batch via saída estruturada (uma entrada por thread).`

phase('Rotular')

const GOOD = new Set(['fechou_logistica', 'engajou'])
const BAD = new Set(['silenciou', 'desviou', 'objecao_preco'])

function aggregateBatch(passes) {
  const byThread = new Map()
  passes.filter(Boolean).forEach((p, jIdx) => {
    for (const l of (p.labels || [])) {
      const k = `${l.instancia}|${l.remote_jid}`
      if (!byThread.has(k)) byThread.set(k, { instancia: l.instancia, remote_jid: l.remote_jid, votos: [] })
      byThread.get(k).votos.push({ reacao: l.reacao, confianca: l.confianca, justificativa: l.justificativa, cotacao_turno: l.cotacao_turno, juiz: jIdx + 1 })
    }
  })
  const out = []
  for (const t of byThread.values()) {
    const counts = {}
    for (const v of t.votos) counts[v.reacao] = (counts[v.reacao] || 0) + 1
    let best = null, bestN = 0
    for (const [r, n] of Object.entries(counts)) if (n > bestN) { best = r; bestN = n }
    if (bestN === 1) { const top = [...t.votos].sort((a, b) => b.confianca - a.confianca)[0]; best = top.reacao }
    const maj = t.votos.find(v => v.reacao === best)
    const label_bin = best === 'cotacao_nao_encontrada' ? null : (GOOD.has(best) ? 'GOOD' : BAD.has(best) ? 'BAD' : null)
    out.push({
      instancia: t.instancia, remote_jid: t.remote_jid,
      reacao_real: best, label_bin,
      n_juizes: t.votos.length, n_votos: bestN,
      concordancia: +(bestN / t.votos.length).toFixed(3),
      cotacao_turno: maj?.cotacao_turno ?? null,
      justificativa: (maj?.justificativa ?? '').slice(0, 200),
      votos: t.votos.map(v => ({ r: v.reacao, c: v.confianca, j: v.juiz })),
    })
  }
  return out
}

const batches = Array.from({ length: N }, (_, i) => i)
const perBatch = await pipeline(
  batches,
  async (i) => {
    const passes = await parallel(
      Array.from({ length: N_JUIZES }, (_, j) =>
        () => agent(promptBatch(i), { label: `b${i}-juiz${j + 1}`, phase: 'Rotular', schema: SCHEMA, model: MODEL })
      )
    )
    return aggregateBatch(passes)
  }
)

const labels = perBatch.filter(Boolean).flat()

// ---- sumário ----
const dist = {}, distBin = {}, byInst = {}
let c3 = 0, c2 = 0, c1 = 0
for (const f of labels) {
  dist[f.reacao_real] = (dist[f.reacao_real] || 0) + 1
  distBin[f.label_bin ?? 'null'] = (distBin[f.label_bin ?? 'null'] || 0) + 1
  byInst[f.instancia] = (byInst[f.instancia] || 0) + 1
  if (f.n_votos === 3) c3++; else if (f.n_votos === 2) c2++; else c1++
}

return {
  resumo: {
    n_threads: labels.length,
    batches_ok: perBatch.filter(Boolean).length,
    dist, distBin, byInst,
    concordancia: { '3de3': c3, '2de3': c2, '1de3_empate': c1 },
  },
  labels,
}
