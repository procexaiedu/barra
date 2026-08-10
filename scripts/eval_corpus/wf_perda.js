export const meta = {
  name: 'rotular-perda',
  description: 'Rotula o motivo de perda (§11) em todas as ~580 threads perdidas — enum CONTEXT, declarado vs mudo, bloco grosso',
  phases: [{ title: 'Rotular' }],
}

// ---- parâmetros ----
const N = 45          // partições hash → ~13 threads por batch
const CAP = 60        // turnos (a perda nasce pós-cotação; precisa de mais arco que a cotação)
const N_JUIZES = 3
const MODEL = 'claude-sonnet-4-6'

const sqlBatch = (i) => `WITH pop AS (
  SELECT instancia, remote_jid
  FROM corpus.threads
  WHERE desfecho_proxy IN ('perdido_sumiu','perdido_objecao','qualificado_sem_prova')
    AND NOT thread_ops
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
          motivo: { type: 'string', enum: ['sumiu', 'indisponibilidade', 'preco', 'risco', 'fora_de_area', 'outro'] },
          declarado: { type: 'boolean' },
          bloco_grosso: { type: 'string', enum: ['reagiu_na_cotacao', 'drift_pos_cotacao', 'sem_cotacao'] },
          obs: { type: 'string', description: 'curta; obrigatória quando motivo=outro (ex.: "fora_de_escopo")' },
          confianca: { type: 'number' },
          justificativa: { type: 'string' },
        },
        required: ['instancia', 'remote_jid', 'motivo', 'declarado', 'bloco_grosso', 'obs', 'confianca', 'justificativa'],
      },
    },
  },
  required: ['labels'],
}

const promptBatch = (i) => `Você é um anotador de um corpus de vendas por WhatsApp (acompanhante/Elite Baby). O Vendedor (V) se passa pela modelo e atende o Cliente (C). Estas são threads que NÃO converteram. Tarefa: para CADA thread, classificar POR QUE o Cliente não fechou.

PASSO 1 — Busque seus dados. Use Postgres (procure "pg_execute_query"; se faltar schema, faça ToolSearch "select:mcp__postgres__pg_execute_query"). Rode EXATAMENTE (operation="select"):

${sqlBatch(i)}

No transcript, "Tn V: ..." = Vendedor, "Tn C: ..." = Cliente, "[midia]" = foto/vídeo, Tn = índice do turno.

PASSO 2 — Para cada thread, decida:

motivo (escolha 1, enum do domínio):
- sumiu — Cliente some sem dizer nada (silêncio mudo, nenhuma razão dada). É a maioria.
- indisponibilidade — timing: "hoje não dá", "te chamo depois", "semana que vem", não consegue agora.
- preco — reclama do valor: "tá caro/salgado", "achei que era menos", contrapropõe valor menor e some.
- risco — desconfiança: "tô achando fake", medo, "é golpe?", pede prova e some por receio.
- fora_de_area — distância/localização inviável (cidade/bairro longe demais).
- outro — curioso, engano, ou pediu o que ela NÃO faz (fora de escopo → obs="fora_de_escopo"). Use obs curta.

declarado (boolean):
- true — o Cliente DECLAROU a razão (disse o porquê: caro, hoje não dá, longe, etc.).
- false — sumiço MUDO: não disse nada, simplesmente parou de responder.
(Regra: sumiu ⇒ quase sempre declarado=false; os demais ⇒ geralmente true.)

bloco_grosso (onde a perda nasce):
- reagiu_na_cotacao — o sinal de perda aparece JÁ no número: objeção de preço imediata, ou silêncio logo após a cotação.
- drift_pos_cotacao — o Cliente ENGAJOU na cotação e só esfriou/sumiu DEPOIS, vários turnos à frente. (o padrão dominante)
- sem_cotacao — não houve cotação de preço no transcript.

REGRAS:
- Baseie-se no que está no transcript; não invente. confianca honesta (sumiu↔indisponibilidade é a fronteira mais ruidosa — quando o Cliente diz "te chamo" e some, prefira o que o texto sustenta).
- Retorne TODAS as threads do batch via saída estruturada (uma entrada por thread).`

phase('Rotular')

function aggregateBatch(passes) {
  const byThread = new Map()
  passes.filter(Boolean).forEach((p, jIdx) => {
    for (const l of (p.labels || [])) {
      const k = `${l.instancia}|${l.remote_jid}`
      if (!byThread.has(k)) byThread.set(k, { instancia: l.instancia, remote_jid: l.remote_jid, votos: [] })
      byThread.get(k).votos.push({ motivo: l.motivo, declarado: l.declarado, bloco_grosso: l.bloco_grosso, obs: l.obs, confianca: l.confianca, justificativa: l.justificativa, juiz: jIdx + 1 })
    }
  })
  const mode = (arr) => {
    const c = {}; for (const x of arr) c[String(x)] = (c[String(x)] || 0) + 1
    let best = null, bestN = 0; for (const [k, n] of Object.entries(c)) if (n > bestN) { best = k; bestN = n }
    return { best, bestN }
  }
  const out = []
  for (const t of byThread.values()) {
    const m = mode(t.votos.map(v => v.motivo))
    let motivo = m.best, nVotos = m.bestN
    if (nVotos === 1) { const top = [...t.votos].sort((a, b) => b.confianca - a.confianca)[0]; motivo = top.motivo }
    const decl = mode(t.votos.map(v => v.declarado)).best === 'true'
    const bloco = mode(t.votos.map(v => v.bloco_grosso)).best
    const maj = t.votos.find(v => v.motivo === motivo) || t.votos[0]
    out.push({
      instancia: t.instancia, remote_jid: t.remote_jid,
      motivo, declarado: decl, bloco_grosso: bloco,
      obs: (maj?.obs ?? '').slice(0, 120),
      n_juizes: t.votos.length, n_votos: nVotos,
      concordancia: +(nVotos / t.votos.length).toFixed(3),
      justificativa: (maj?.justificativa ?? '').slice(0, 200),
      votos: t.votos.map(v => ({ m: v.motivo, d: v.declarado, b: v.bloco_grosso, c: v.confianca, j: v.juiz })),
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

const dist = {}, distBloco = {}, byInst = {}
let decl = 0, c3 = 0, c2 = 0, c1 = 0
for (const f of labels) {
  dist[f.motivo] = (dist[f.motivo] || 0) + 1
  distBloco[f.bloco_grosso] = (distBloco[f.bloco_grosso] || 0) + 1
  byInst[f.instancia] = (byInst[f.instancia] || 0) + 1
  if (f.declarado) decl++
  if (f.n_votos === 3) c3++; else if (f.n_votos === 2) c2++; else c1++
}

return {
  resumo: {
    n_threads: labels.length,
    batches_ok: perBatch.filter(Boolean).length,
    dist, distBloco, byInst,
    declarado_pct: labels.length ? +(100 * decl / labels.length).toFixed(1) : 0,
    concordancia: { '3de3': c3, '2de3': c2, '1de3_empate': c1 },
  },
  labels,
}
