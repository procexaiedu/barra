export const meta = {
  name: 'pilot-cotacao',
  description: 'Piloto: 3 juízes rotulam a reação imediata à cotação em 1 batch (~15 threads) do corpus',
  phases: [{ title: 'Rotular' }],
}

// ---- parâmetros do piloto ----
const N = 52          // nº de partições hash (784/52 ≈ 15 threads por batch)
const I = 0           // batch a rodar no piloto
const CAP = 40        // turnos máximos no transcript (cotação é cedo; foco na reação imediata)
const N_JUIZES = 3
const MODEL = 'claude-sonnet-4-6'

const SQL = `WITH pop AS (
  SELECT instancia, remote_jid
  FROM corpus.threads
  WHERE tem_valor AND NOT thread_ops
    AND abs(hashtext(remote_jid)) % ${N} = ${I}
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
          cotacao_turno: { type: ['integer', 'null'], description: 'turno_idx (Tn) da PRIMEIRA cotação de preço do Vendedor; null se não houver' },
          reacao: { type: 'string', enum: ['fechou_logistica', 'engajou', 'silenciou', 'desviou', 'objecao_preco', 'cotacao_nao_encontrada'] },
          confianca: { type: 'number', description: '0.0 a 1.0' },
          justificativa: { type: 'string', description: 'PT-BR, <=140 chars, citando o turno' },
        },
        required: ['instancia', 'remote_jid', 'cotacao_turno', 'reacao', 'confianca', 'justificativa'],
      },
    },
  },
  required: ['labels'],
}

const PROMPT = `Você é um anotador de um corpus de vendas por WhatsApp (acompanhante/Elite Baby). O Vendedor (V) se passa pela modelo e atende o Cliente (C). Sua tarefa: para CADA thread do seu batch, classificar a REAÇÃO IMEDIATA do Cliente à COTAÇÃO de preço.

PASSO 1 — Busque seus dados. Use a ferramenta de Postgres (procure por "pg_execute_query"; se não tiver schema, faça ToolSearch "select:mcp__postgres__pg_execute_query" antes). Rode EXATAMENTE esta query (operation="select"):

${SQL}

Cada linha é uma thread: instancia, remote_jid e um transcript com linhas "Tn V: ..." (Vendedor) ou "Tn C: ..." (Cliente). "[midia]" = foto/vídeo enviado naquele turno. Tn é o índice do turno.

PASSO 2 — Para cada thread:
a) Ache a COTAÇÃO: o PRIMEIRO turno do Vendedor (V) que apresenta um PREÇO de programa (ex.: "400 1h no meu local", "cachê 600", "500 1h"). Anote o Tn em cotacao_turno. Preço de Pix/uber/deslocamento NÃO é a cotação do programa. Se não houver nenhuma cotação de preço no transcript → reacao="cotacao_nao_encontrada", cotacao_turno=null.
b) Classifique a reação IMEDIATA do Cliente nos turnos LOGO APÓS a cotação (1 a 3 turnos do Cliente). Classifique a reação AO NÚMERO, não o desfecho final da conversa — uma conversa que esfria 20 turnos depois ainda pode ter "engajou" na hora.

ENUM (escolha 1):
- fechou_logistica — C avança pra logística do encontro: dá/pede horário, endereço, "bora", "confirmado", manda localização, topa uber/pix. (o mais forte)
- engajou — C reage positivo/quente sem fechar logística ainda: elogia, "adorei", manda mídia, pergunta sobre o serviço, segue interessado.
- silenciou — C para de responder logo após o número (sem reação registrada após a cotação, ou só some).
- desviou — C enrola/esfria sem objeção explícita de preço: "vou ver", "depois te chamo", muda de assunto, some após desviar.
- objecao_preco — C reclama do valor: "tá caro", "salgado", "achei que era menos", contrapropõe um valor menor.

REGRAS:
- A reação é só do Cliente, e só a janela imediata pós-cotação. Ignore o que o Vendedor faz e o que acontece muito depois.
- Mídia do Cliente logo após a cotação conta como engajamento (engajou), salvo se ele já fechou logística.
- confianca reflete sua certeza (fronteira engajou↔desviou e silenciou↔desviou é borrada — seja honesto).
- Retorne TODAS as threads do batch, uma entrada por thread, via a saída estruturada.`

phase('Rotular')
const passes = await parallel(
  Array.from({ length: N_JUIZES }, (_, j) =>
    () => agent(PROMPT, { label: `juiz-${j + 1}`, phase: 'Rotular', schema: SCHEMA, model: MODEL })
  )
)

// ---- agregação (voto majoritário) ----
const GOOD = new Set(['fechou_logistica', 'engajou'])
const BAD = new Set(['silenciou', 'desviou', 'objecao_preco'])

const byThread = new Map()
passes.filter(Boolean).forEach((p, jIdx) => {
  for (const l of (p.labels || [])) {
    const k = `${l.instancia}|${l.remote_jid}`
    if (!byThread.has(k)) byThread.set(k, { instancia: l.instancia, remote_jid: l.remote_jid, votos: [] })
    byThread.get(k).votos.push({ reacao: l.reacao, confianca: l.confianca, justificativa: l.justificativa, cotacao_turno: l.cotacao_turno, juiz: jIdx + 1 })
  }
})

const final = []
for (const t of byThread.values()) {
  const counts = {}
  for (const v of t.votos) counts[v.reacao] = (counts[v.reacao] || 0) + 1
  let best = null, bestN = 0
  for (const [r, n] of Object.entries(counts)) if (n > bestN) { best = r; bestN = n }
  if (bestN === 1) { // empate total (1/1/1): escolhe o voto de maior confiança
    const top = [...t.votos].sort((a, b) => b.confianca - a.confianca)[0]
    best = top.reacao; bestN = 1
  }
  const maj = t.votos.find(v => v.reacao === best)
  const label_bin = best === 'cotacao_nao_encontrada' ? null : (GOOD.has(best) ? 'GOOD' : BAD.has(best) ? 'BAD' : null)
  final.push({
    instancia: t.instancia,
    remote_jid: t.remote_jid,
    reacao_real: best,
    label_bin,
    n_juizes: t.votos.length,
    n_votos: bestN,
    concordancia: +(bestN / t.votos.length).toFixed(3),
    cotacao_turno: maj?.cotacao_turno ?? null,
    justificativa: maj?.justificativa ?? '',
    votos: t.votos.map(v => ({ reacao: v.reacao, confianca: v.confianca, juiz: v.juiz })),
  })
}

const dist = {}
for (const f of final) dist[f.reacao_real] = (dist[f.reacao_real] || 0) + 1
const conc3 = final.filter(f => f.n_votos === 3).length
const conc2 = final.filter(f => f.n_votos === 2).length
const conc1 = final.filter(f => f.n_votos === 1).length

return {
  resumo: { n_threads: final.length, passes_ok: passes.filter(Boolean).length, dist, concordancia: { '3de3': conc3, '2de3': conc2, '1de3_empate': conc1 } },
  labels: final,
}
