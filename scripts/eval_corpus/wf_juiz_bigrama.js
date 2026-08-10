export const meta = {
  name: 'juiz-bigrama',
  description: 'Testa os 2 candidatos nao-operacionalizaveis da mineracao contrastiva (freia-insistencia-apos-recusa, ignora-pedido-de-video-redireciona) com juiz LLM de janela 2-turnos: detecta o gatilho na fala do cliente e classifica o braco da resposta do Vendedor, depois estratifica a conversao por braco. Juiz cego ao desfecho.',
  phases: [
    { title: 'Julgar', detail: 'juizes leem threads pre-filtradas e classificam gatilho + braco, cego ao label' },
    { title: 'Rotular-desfecho', detail: 'busca label_bin das threads julgadas (sem mostrar ao juiz)' },
    { title: 'Sintetizar', detail: 'estratifica conversao por braco + teste de duas proporcoes + veredito' },
  ],
}

// ---- parametros ----
const SONNET = 'claude-sonnet-4-6'
const OPUS = 'claude-opus-4-8[1m]'   // workflow NAO herda modelo da sessao; ID exato (memoria)
const N_BATCH = 10
const CAP = 60
const N_JUIZES = 3

// Gatilhos: regex de RECALL amplo nas falas do CLIENTE (o juiz filtra a precisao depois).
const TRIG_VIDEO = "(chamada de v|videochamada|video chamada|v[ií]deo|me chama no|liga pra mim|ligar|[áa]udio|prova que|ao vivo|tempo real|verificar|verifica[çc])"
const TRIG_RECUSA = "(n[ãa]o quero|n[ãa]o curto|n[ãa]o fa[çc]o|n[ãa]o gosto|acho que n[ãa]o|vou pensar|vou ver|talvez|depois (eu )?(te )?(chamo|falo|vejo)|outra hora|fica pra|agora n[ãa]o|hoje n[ãa]o|deixa (pra|quieto)|t[áa] caro|muito caro|salgado|t[áa] puxado|t[ôo] sem)"

const batchSql = (i) => `WITH cli AS (
  SELECT e.instancia, e.remote_jid,
    string_agg(CASE WHEN NOT t.from_me THEN lower(t.texto) END, ' ' ORDER BY t.turno_idx) AS c_text
  FROM corpus.eval_cotacao e
  JOIN corpus.turnos t USING (instancia, remote_jid)
  WHERE e.label_bin IS NOT NULL
  GROUP BY 1, 2
), pop AS (
  SELECT instancia, remote_jid FROM cli
  WHERE c_text ~ '${TRIG_VIDEO}' OR c_text ~ '${TRIG_RECUSA}'
)
SELECT p.instancia, p.remote_jid,
  string_agg(
    'T' || t.turno_idx || ' ' || (CASE WHEN t.from_me THEN 'V: ' ELSE 'C: ' END) ||
    COALESCE(NULLIF(btrim(t.texto), ''), CASE WHEN t.tem_midia THEN '[midia]' ELSE '[--]' END),
    E'\\n' ORDER BY t.turno_idx
  ) FILTER (WHERE t.turno_idx <= ${CAP}) AS transcript
FROM pop p
JOIN corpus.turnos t USING (instancia, remote_jid)
WHERE abs(hashtext(p.remote_jid)) % ${N_BATCH} = ${i}
GROUP BY p.instancia, p.remote_jid
ORDER BY p.remote_jid`

const JUIZ_SCHEMA = {
  type: 'object',
  properties: {
    threads: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          instancia: { type: 'string' },
          remote_jid: { type: 'string' },
          // Candidato 1: cliente recusa um servico/extra OU sinaliza encerramento/hesitacao.
          recusa_gatilho: { type: 'boolean' },
          recusa_braco: { type: 'string', enum: ['recuou', 'insistiu', 'neutro', 'na'] },
          // Candidato 2: cliente pede chamada de video / ligacao / prova ao vivo de que e real.
          video_gatilho: { type: 'boolean' },
          video_braco: { type: 'string', enum: ['ignorou_pivotou', 'ofereceu_midia', 'aceitou_chamada', 'outro', 'na'] },
          nota: { type: 'string' },
        },
        required: ['instancia', 'remote_jid', 'recusa_gatilho', 'recusa_braco', 'video_gatilho', 'video_braco', 'nota'],
      },
    },
  },
  required: ['threads'],
}

const juizPrompt = (i) => `Voce e anotador de um corpus REAL de vendas por WhatsApp (acompanhante/Elite Baby). O Vendedor (V) se passa pela modelo e atende o Cliente (C). Voce NAO sabe o desfecho das threads e NAO deve adivinhar - so observe o que acontece no texto. Para CADA thread, avalie DOIS gatilhos e a reacao IMEDIATA do Vendedor (o turno V logo apos o gatilho).

PASSO 1 - Busque seus dados. Use Postgres ("pg_execute_query"; se faltar schema, ToolSearch "select:mcp__postgres__pg_execute_query"). Rode EXATAMENTE (operation="select"):

${batchSql(i)}

No transcript "Tn V:" = Vendedor, "Tn C:" = Cliente, "[midia]" = foto/video, Tn = indice do turno. Estas threads foram pre-selecionadas por palavra-chave, entao MUITAS nao terao o gatilho de verdade - seja rigoroso.

PASSO 2 - CANDIDATO 1 (recusa/encerramento):
- recusa_gatilho=true SE em algum ponto o Cliente RECUSA um servico/extra especifico ("nao curto isso", "nao quero X") OU sinaliza desengajamento/encerramento real ("vou pensar", "depois te chamo", "outra hora", "ta caro" como ponto final, some o assunto). Mera pergunta ou negociacao NAO conta.
- Se gatilho, classifique o turno V IMEDIATAMENTE seguinte:
  - recuou: aceita com leveza, sem reempurrar, deixa a porta aberta de forma calorosa ("sem problema amor, quando quiser").
  - insistiu: rebate, repete a oferta, pressiona, usa urgencia, tenta contornar a recusa.
  - neutro: nem um nem outro claramente (muda de assunto operacional sem pressao nem recuo).
- Sem gatilho: recusa_gatilho=false, recusa_braco="na".

PASSO 3 - CANDIDATO 2 (pedido de prova ao vivo):
- video_gatilho=true SE o Cliente pede CHAMADA DE VIDEO, ligacao/audio ao vivo, ou prova em tempo real de que V e real/nao e bot/nao e foto fake. Pedir FOTO ou audio gravado NAO conta (isso e midia, nao prova ao vivo). Pedir video-chamada/ligar/"prova que e vc agora" conta.
- Se gatilho, classifique o turno V IMEDIATAMENTE seguinte:
  - ignorou_pivotou: nao engaja o pedido de prova ao vivo e redireciona pra logistica/agendamento/outro assunto.
  - ofereceu_midia: contorna oferecendo foto/video gravado no lugar da chamada.
  - aceitou_chamada: topa fazer a chamada/ligacao.
  - outro: outra reacao.
- Sem gatilho: video_gatilho=false, video_braco="na".

REGRAS: julgue so o texto, cego ao desfecho. confianca rigorosa - na duvida do gatilho, marque false. Retorne TODAS as threads do batch (uma entrada por thread) via saida estruturada. nota = so quando o gatilho ocorre, 1 frase citando o turno.`

phase('Julgar')

const batches = Array.from({ length: N_BATCH }, (_, i) => i)
const perBatch = await pipeline(
  batches,
  async (i) => {
    const passes = await parallel(
      Array.from({ length: N_JUIZES }, (_, j) =>
        () => agent(juizPrompt(i), { label: `b${i}-juiz${j + 1}`, phase: 'Julgar', schema: JUIZ_SCHEMA, model: SONNET })
      )
    )
    // voto majoritario por thread
    const byThread = new Map()
    passes.filter(Boolean).forEach((p) => {
      for (const t of (p.threads || [])) {
        const k = `${t.instancia}|${t.remote_jid}`
        if (!byThread.has(k)) byThread.set(k, { instancia: t.instancia, remote_jid: t.remote_jid, votos: [] })
        byThread.get(k).votos.push(t)
      }
    })
    const mode = (arr) => {
      const c = {}
      for (const x of arr) c[x] = (c[x] || 0) + 1
      let best = null, bestN = 0
      for (const [k, n] of Object.entries(c)) if (n > bestN) { best = k; bestN = n }
      return { best, bestN, total: arr.length }
    }
    const out = []
    for (const t of byThread.values()) {
      const recTrig = t.votos.filter(v => v.recusa_gatilho).length
      const vidTrig = t.votos.filter(v => v.video_gatilho).length
      const recMaj = recTrig >= 2
      const vidMaj = vidTrig >= 2
      const recArm = recMaj ? mode(t.votos.filter(v => v.recusa_gatilho).map(v => v.recusa_braco)) : null
      const vidArm = vidMaj ? mode(t.votos.filter(v => v.video_gatilho).map(v => v.video_braco)) : null
      out.push({
        instancia: t.instancia, remote_jid: t.remote_jid,
        recusa_gatilho: recMaj,
        recusa_braco: recMaj && recArm.bestN >= 2 ? recArm.best : (recMaj ? 'ambiguo' : 'na'),
        video_gatilho: vidMaj,
        video_braco: vidMaj && vidArm.bestN >= 2 ? vidArm.best : (vidMaj ? 'ambiguo' : 'na'),
        n_juizes: t.votos.length,
      })
    }
    return out
  }
)

const julgados = perBatch.filter(Boolean).flat()
const nRec = julgados.filter(t => t.recusa_gatilho).length
const nVid = julgados.filter(t => t.video_gatilho).length
log(`Julgadas ${julgados.length} threads; gatilho recusa: ${nRec}, gatilho video: ${nVid}`)

// ---- buscar label_bin (separado do juiz, que ficou cego) ----
phase('Rotular-desfecho')

const LABEL_SCHEMA = {
  type: 'object',
  properties: {
    labels: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          instancia: { type: 'string' },
          remote_jid: { type: 'string' },
          label_bin: { type: 'string', enum: ['GOOD', 'BAD'] },
        },
        required: ['instancia', 'remote_jid', 'label_bin'],
      },
    },
  },
  required: ['labels'],
}

const labelResp = await agent(
  `Tarefa unica e deterministica: rode a query abaixo e devolva TODAS as ~775 linhas via saida estruturada, sem alterar nada. Use pg_execute_query com operation="select" e passe limit=2000 para NAO truncar (sao ~775 linhas, todas necessarias). Se a chamada falhar por rate-limit, espere e tente de novo ate conseguir.

SELECT instancia, remote_jid, label_bin
FROM corpus.eval_cotacao
WHERE label_bin IS NOT NULL`,
  { label: 'fetch-labels-v2', phase: 'Rotular-desfecho', schema: LABEL_SCHEMA, model: SONNET }
)

const labelMap = new Map()
for (const l of (labelResp?.labels || [])) labelMap.set(`${l.instancia}|${l.remote_jid}`, l.label_bin)

// ---- estatistica: conversao por braco dentro da populacao com gatilho ----
function contagem(threads, getArm, armsAlvo) {
  const stat = {}
  for (const a of armsAlvo) stat[a] = { n: 0, good: 0 }
  let semLabel = 0
  for (const t of threads) {
    const arm = getArm(t)
    if (!armsAlvo.includes(arm)) continue
    const lab = labelMap.get(`${t.instancia}|${t.remote_jid}`)
    if (!lab) { semLabel++; continue }
    stat[arm].n++
    if (lab === 'GOOD') stat[arm].good++
  }
  return { stat, semLabel }
}

function ztest(g1, n1, g2, n2) {
  if (n1 === 0 || n2 === 0) return null
  const p1 = g1 / n1, p2 = g2 / n2, p = (g1 + g2) / (n1 + n2)
  const se = Math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2))
  if (se === 0) return null
  return +((p1 - p2) / se).toFixed(2)
}

const recCont = contagem(julgados.filter(t => t.recusa_gatilho), t => t.recusa_braco, ['recuou', 'insistiu', 'neutro', 'ambiguo'])
const vidCont = contagem(julgados.filter(t => t.video_gatilho), t => t.video_braco, ['ignorou_pivotou', 'ofereceu_midia', 'aceitou_chamada', 'outro', 'ambiguo'])

const recZ = ztest(recCont.stat.recuou.good, recCont.stat.recuou.n, recCont.stat.insistiu.good, recCont.stat.insistiu.n)
const vidZ = ztest(vidCont.stat.ignorou_pivotou.good, vidCont.stat.ignorou_pivotou.n, vidCont.stat.ofereceu_midia.good, vidCont.stat.ofereceu_midia.n)

const stats = {
  recusa: { contraste: 'recuou vs insistiu', ...recCont, z: recZ },
  video: { contraste: 'ignorou_pivotou vs ofereceu_midia', ...vidCont, z: vidZ },
}
log(`recusa z=${recZ} | video z=${vidZ}`)

// ---- sintese ----
phase('Sintetizar')

const SINTESE_SCHEMA = {
  type: 'object',
  properties: {
    relatorio_md: { type: 'string' },
    veredito_recusa: { type: 'string', enum: ['merece_ab', 'enterrar', 'inconclusivo_n'] },
    veredito_video: { type: 'string', enum: ['merece_ab', 'enterrar', 'inconclusivo_n'] },
  },
  required: ['relatorio_md', 'veredito_recusa', 'veredito_video'],
}

const sintese = await agent(
  `Voce e o redator final da rodada 2 da mineracao contrastiva do corpus do Vendedor. Testamos os 2 candidatos que regex nao pegava, com juiz de janela 2-turnos (3 juizes, voto majoritario, CEGO ao desfecho), estratificando a conversao (label_bin GOOD%) por braco da resposta do Vendedor DENTRO da populacao onde o gatilho ocorreu.

CANDIDATO 1 - "freia-insistencia-apos-recusa": hipotese = quando o cliente recusa/encerra, RECUAR com leveza converte mais do que INSISTIR.
CANDIDATO 2 - "ignora-pedido-de-video-redireciona": hipotese = quando o cliente pede prova ao vivo (chamada de video), IGNORAR-E-PIVOTAR pra logistica converte mais do que OFERECER MIDIA gravada (a conduta atual do prompt).

ESTATISTICA (JSON; n=threads com gatilho e desfecho conhecido; good=GOOD entre elas; z = teste de duas proporcoes do contraste principal, |z|>1.96 ~ p<0.05):
${JSON.stringify(stats, null, 2)}

Escreva relatorio_md (markdown PT-BR) com:
1. Resumo de 2-3 linhas: qual hipotese se sustenta, qual nao, e onde o n e pequeno demais pra concluir.
2. Por candidato: tabela braco | n | GOOD% ; a diferenca do contraste principal e o z; veredito.
3. Caveat HONESTO obrigatorio: mesmo estratificado, a ESCOLHA do braco pelo Vendedor nao foi randomizada (ele pode recuar/pivotar justamente nas threads que ja iam mal ou bem) - entao isto e quase-experimento observacional, nao causal; n pequeno (gatilhos sao raros) amplia o intervalo. So um A/B ao vivo (ou no simulador) fecha causa.
4. Recomendacao por candidato: merece_ab (sinal direcional + n decente, vale um A/B no wf_simulador.js), enterrar (sem sinal ou contra a hipotese), ou inconclusivo_n (n pequeno demais, so vale reolhar com mais corpus).

Preencha veredito_recusa e veredito_video coerentes com o texto. Conciso e cirurgico.`,
  { label: 'sintetizar', phase: 'Sintetizar', schema: SINTESE_SCHEMA, model: OPUS }
)

return {
  resumo: {
    julgadas: julgados.length,
    gatilho_recusa: nRec,
    gatilho_video: nVid,
    labels_carregados: labelMap.size,
  },
  stats,
  veredito_recusa: sintese?.veredito_recusa,
  veredito_video: sintese?.veredito_video,
  relatorio_md: sintese?.relatorio_md || '',
}
