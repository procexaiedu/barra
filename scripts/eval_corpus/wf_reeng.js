export const meta = {
  name: 'codificar-reengajamento',
  description: 'Codifica o MOVIMENTO da cutucada (§13) numa amostra de pokes reais — 3 juizes, voto majoritario. reviveu/gap/midia ja sao deterministicos (SQL); o juiz so faz movimento/tem_desconto/tipo_silencio.',
  phases: [{ title: 'Codificar' }],
}

// ---- parametros ----
// args (JSON string): { offsets: [..], modo: 'pilot'|'full' }. Default = pilot pequeno.
let ARGS = {}
try { ARGS = typeof args === 'string' ? JSON.parse(args) : (args || {}) } catch { ARGS = {} }
const MODE = ARGS.modo || 'pilot'
const N_JUIZES = 3
const MODEL = 'claude-sonnet-4-6'
const CTX = 12   // turnos de contexto ANTES do poke (p/ o juiz entender o silencio)

// Amostra: pokes de TEXTO (movimento de midia = tem_midia, ja deterministico, nao precisa juiz
// p/ movimento exceto p/ distinguir 'midia_nova'; incluimos midia tambem p/ rotular midia_nova).
// Estratifica por hash do msg_id em N particoes; cada batch = 1 particao.
// pilot: 2 particoes (~ algumas dezenas). full: 24 particoes.
const N_PART = MODE === 'full' ? 24 : 40
const BATCHES = MODE === 'full'
  ? Array.from({ length: N_PART }, (_, i) => i)            // todas as 24
  : (ARGS.offsets || [0, 1])                               // pilot: 2 particoes

// SQL: o poke + a janela de contexto imediatamente anterior (mesma thread, ts < poke_ts, ultimos CTX).
const sqlBatch = (i) => `WITH pokes AS (
  SELECT instancia, remote_jid, msg_id, poke_ts, texto, tem_midia, gap_min, gap_bucket, reviveu, poke_rank
  FROM corpus.eval_reengajamento
  WHERE abs(hashtext(msg_id)) % ${N_PART} = ${i}
)
SELECT p.instancia, p.remote_jid, p.msg_id, p.tem_midia, p.gap_min, p.gap_bucket,
  COALESCE(p.texto, '[MIDIA]') AS poke_texto,
  (SELECT string_agg(
      (CASE WHEN m.from_me THEN 'V: ' ELSE 'C: ' END) ||
      COALESCE(NULLIF(btrim(m.texto),''), '[midia]'), E'\\n' ORDER BY m.ts, m.msg_id)
   FROM (
     SELECT * FROM corpus.mensagens_raw r
     WHERE r.instancia=p.instancia AND r.remote_jid=p.remote_jid AND r.ts < p.poke_ts
     ORDER BY r.ts DESC, r.msg_id DESC LIMIT ${CTX}
   ) m
  ) AS contexto_antes
FROM pokes p
ORDER BY p.remote_jid, p.poke_ts`

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
          msg_id: { type: 'string' },
          movimento: { type: 'string', enum: ['pergunta_leve', 'calor_saudade', 'escassez_partida', 'midia_nova', 'desconto', 'outro'] },
          tem_desconto: { type: 'boolean' },
          tipo_silencio: { type: 'string', enum: ['silencio_total', 'desviou_antes'] },
          confianca: { type: 'number' },
          justificativa: { type: 'string' },
        },
        required: ['instancia', 'remote_jid', 'msg_id', 'movimento', 'tem_desconto', 'tipo_silencio', 'confianca', 'justificativa'],
      },
    },
  },
  required: ['labels'],
}

const promptBatch = (i) => `Voce e um anotador de um corpus de vendas por WhatsApp (acompanhante/Elite Baby). O Vendedor (V) se passa pela modelo e atende o Cliente (C). Estas sao CUTUCADAS: mensagens em que V cutucou o Cliente que tinha ficado em silencio (V mandou, C nao respondeu, V mandou de novo). Tarefa: para CADA cutucada, classificar O MOVIMENTO que V usou para reabrir.

PASSO 1 — Busque seus dados. Use Postgres ("pg_execute_query"; se faltar schema, ToolSearch "select:mcp__postgres__pg_execute_query"). Rode EXATAMENTE (operation="select"):

${sqlBatch(i)}

Cada linha: (instancia, remote_jid, msg_id, poke_texto = a CUTUCADA a classificar, contexto_antes = ate ${CTX} mensagens ANTERIORES na thread, mais recentes por ultimo; tem_midia, gap_min). "V:" = Vendedor, "C:" = Cliente, "[midia]"/"[MIDIA]" = foto/video/audio.

PASSO 2 — Para cada cutucada, classifique:

movimento (escolha 1 — o que a CUTUCADA (poke_texto) FAZ):
- pergunta_leve — pergunta curta de LOGISTICA/intencao, leve e direta: "seria hoje?", "que horario te serve?", "ainda quer marcar?", "vai querer vida?". O movimento vencedor.
- calor_saudade — afeto/saudade SEM pergunta de logistica forte: "bom dia amor 🥰", "sumido", "to com saudade", "oi vida". Reabre pelo carinho.
- escassez_partida — escassez/partida/agenda fechando: "to indo viajar", "ultima vaga hoje", "so consigo ate as X", "vou sair de SP".
- midia_nova — a cutucada e uma MIDIA nova (foto/video) jogada pra reabrir (tem_midia=true e o movimento e a propria midia). Se tem_midia=true e nao ha texto, e midia_nova.
- desconto — a cutucada OFERECE preco menor/desconto/condicao especial pra reabrir: "faco por X", "te dou um desconto", "promo".
- outro — recados operacionais, repeticao do mesmo, links, nada dos acima.

tem_desconto (boolean): a cutucada menciona desconto/preco menor/condicao especial? (quase sempre false; so true se EXPLICITO).

tipo_silencio (escolha 1 — como o Cliente tinha sumido ANTES da cutucada, olhando contexto_antes):
- silencio_total — o Cliente praticamente nao respondeu / sumiu cedo, pouca ou nenhuma troca antes.
- desviou_antes — houve troca real (o Cliente engajou, perguntou, quase fechou) e ENTAO esfriou/parou.

REGRAS:
- Classifique o MOVIMENTO da cutucada (poke_texto), nao o desfecho. Use contexto_antes so p/ tipo_silencio e p/ desambiguar.
- Se tem_midia=true sem texto -> movimento=midia_nova.
- confianca honesta (calor_saudade vs pergunta_leve e a fronteira borrada: se ha pergunta de logistica concreta, prefira pergunta_leve).
- Retorne TODAS as cutucadas do batch via saida estruturada (uma por msg_id).`

phase('Codificar')

function aggregateBatch(passes) {
  const byMsg = new Map()
  passes.filter(Boolean).forEach((p, jIdx) => {
    for (const l of (p.labels || [])) {
      const k = `${l.instancia}|${l.remote_jid}|${l.msg_id}`
      if (!byMsg.has(k)) byMsg.set(k, { instancia: l.instancia, remote_jid: l.remote_jid, msg_id: l.msg_id, votos: [] })
      byMsg.get(k).votos.push({ movimento: l.movimento, tem_desconto: l.tem_desconto, tipo_silencio: l.tipo_silencio, confianca: l.confianca, justificativa: l.justificativa, juiz: jIdx + 1 })
    }
  })
  const mode = (arr) => {
    const c = {}; for (const x of arr) c[String(x)] = (c[String(x)] || 0) + 1
    let best = null, bestN = 0; for (const [k, n] of Object.entries(c)) if (n > bestN) { best = k; bestN = n }
    return { best, bestN }
  }
  const out = []
  for (const t of byMsg.values()) {
    const m = mode(t.votos.map(v => v.movimento))
    let movimento = m.best, nVotos = m.bestN
    if (nVotos === 1) { const top = [...t.votos].sort((a, b) => b.confianca - a.confianca)[0]; movimento = top.movimento }
    const desc = mode(t.votos.map(v => v.tem_desconto)).best === 'true'
    const sil = mode(t.votos.map(v => v.tipo_silencio)).best
    const maj = t.votos.find(v => v.movimento === movimento) || t.votos[0]
    out.push({
      instancia: t.instancia, remote_jid: t.remote_jid, msg_id: t.msg_id,
      movimento, tem_desconto: desc, tipo_silencio: sil,
      n_juizes: t.votos.length, n_votos: nVotos,
      concordancia: +(nVotos / t.votos.length).toFixed(3),
      justificativa: (maj?.justificativa ?? '').slice(0, 200),
      votos: t.votos.map(v => ({ m: v.movimento, d: v.tem_desconto, s: v.tipo_silencio, c: v.confianca, j: v.juiz })),
    })
  }
  return out
}

const perBatch = await pipeline(
  BATCHES,
  async (i) => {
    const passes = await parallel(
      Array.from({ length: N_JUIZES }, (_, j) =>
        () => agent(promptBatch(i), { label: `b${i}-juiz${j + 1}`, phase: 'Codificar', schema: SCHEMA, model: MODEL })
      )
    )
    return aggregateBatch(passes)
  }
)

const labels = perBatch.filter(Boolean).flat()

const dist = {}, byInst = {}
let c3 = 0, c2 = 0, c1 = 0, desc = 0
for (const f of labels) {
  dist[f.movimento] = (dist[f.movimento] || 0) + 1
  byInst[f.instancia] = (byInst[f.instancia] || 0) + 1
  if (f.tem_desconto) desc++
  if (f.n_votos === 3) c3++; else if (f.n_votos === 2) c2++; else c1++
}

return {
  resumo: {
    modo: MODE, n_pokes: labels.length, batches_ok: perBatch.filter(Boolean).length,
    dist, byInst, com_desconto: desc,
    concordancia: { '3de3': c3, '2de3': c2, '1de3_empate': c1 },
  },
  labels,
}
