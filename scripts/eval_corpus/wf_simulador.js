export const meta = {
  name: 'simulador-conversa',
  description: '[DEPRECADO p/ FIDELIDADE — prod usa DeepSeek, este roda Claude; use sim_deepseek.py] A/B offline de CONDUTA: cliente-sim x agente-Vendedor por N turnos; mede empurrao/calor/desfecho. Moeda Claude Code.',
  phases: [
    { title: 'Simular' },
    { title: 'Medir' },
  ],
}

// ============================================================================
// ⚠️ DEPRECADO PARA A/B FIEL — O AGENTE EM PROD USA DEEPSEEK, NÃO CLAUDE.
//
// Este Workflow roda o Vendedor como SUBAGENTE CLAUDE CODE (Sonnet 4.6). O agente ao
// vivo, porém, roda DeepSeek V4 Flash direto (graph.py:_criar_chat_principal /
// criar_chat_deepseek) — outro modelo, outra propensão a verbosidade/emoji/em-dash/
// instruction-following. Medir conduta no Claude NÃO prediz a conduta do DeepSeek
// (ex.: em-dash é tell ESPECÍFICO do modelo). O Workflow agent() é Claude-only por
// construção (não há como fazê-lo invocar DeepSeek), então a fidelidade exige outro harness.
//
// >>> HARNESS FIEL (canônico): scripts/eval_corpus/sim_deepseek.py — Vendedor por
//     criar_chat_deepseek (réplica do chat #1 de prod). Use-o para qualquer A/B cujo
//     veredito vá para prod. Reaproveita as MESMAS personas e a MESMA rubrica de detector.
//
// Este .js fica como scaffolding: experimentos de conduta CROSS-MODEL (robustez da regra
// nos dois modelos) ou iteração rápida barata — nunca como prova de prod.
//
// O QUE É: estende o harness single-turn (score_v1) para CONVERSA multi-turno.
// Dois subagentes alternam: o CLIENTE-SIM (persona derivada do corpus, enum de
// reação do eval_cotacao) e o VENDEDOR (prompt renderizado de produção). Ao fim,
// um DETECTOR cego mede o empurrão (rubrica §12) e o desfecho.
//
// COMO RODAR: gere o prompt antes (offline):
//   cd api && uv run python ../scripts/eval_corpus/render_v1_prompt.py > /tmp/v1_prompt_atual.txt
// e passe via args: { variantes: [{tag:'v1', path:'/tmp/v1_prompt_atual.txt'}], n_rep: 2, k_turnos: 10 }
//
// FIDELIDADE (limitação dupla): (1) modelo errado (Claude≠DeepSeek de prod, acima);
// (2) o Vendedor NÃO roda o grafo LangGraph (sem tools, extração, estado). Mede
// CONDUTA/ESTILO, que é onde está o sinal robusto (eval_cotacao κ=0.07 mata "conversão").
// ============================================================================

const MODEL = 'claude-sonnet-4-6'   // subagente Claude Code — NÃO é o modelo de prod (DeepSeek); ver banner acima
// args pode chegar como STRING JSON (gotcha do runtime) — parse defensivo, senão cai no default silenciosamente
let cfg = {}
if (typeof args === 'string') { try { cfg = JSON.parse(args) || {} } catch { cfg = {} } }
else if (args && typeof args === 'object') { cfg = args }
const VARIANTES = cfg.variantes || [{ tag: 'v1', path: '/tmp/v1_prompt_atual.txt' }]
const N_REP = cfg.n_rep || 2        // repetições por célula (variância)
const K = cfg.k_turnos || 10        // turnos máximos do cliente por conversa
const FILTRO_PERSONAS = cfg.personas || null  // ex.: ['curioso_morno','caca_desconto'] p/ focar o A/B

// ---- Personas do cliente, ancoradas nos arquétipos de reação do corpus (eval_cotacao) ----
const PERSONAS = [
  {
    tag: 'decidido', alvo: 'fechou_logistica',
    desc: 'Você é um cliente DECIDIDO. Já quer marcar hoje. Vai direto ao ponto: pergunta valor de 1h, e ao receber, topa e parte pra logística (horário, região, como chega). Não enrola, não pechincha. Fecha rápido.',
  },
  {
    tag: 'preco_sensivel', alvo: 'objecao_preco',
    desc: 'Você é um cliente PREÇO-SENSÍVEL. Interessado, mas acha tudo caro. Pergunta o valor, reclama ("tá puxado"), contrapropõe um valor bem abaixo (ex.: pede 250 num programa de 400) e insiste pedindo desconto mais de uma vez antes de decidir.',
  },
  {
    tag: 'curioso_morno', alvo: 'engajou',
    desc: 'Você é um cliente CURIOSO E MORNO. Pergunta muita coisa (o que ela faz, região, fotos, como funciona), elogia, demonstra interesse, mas custa a marcar. Fica "vou ver", "depois te chamo", sem fechar logística de fato.',
  },
  {
    tag: 'sumido_rapido', alvo: 'silenciou',
    desc: 'Você é um cliente que SOME. Manda 1-2 mensagens curtas, pergunta o preço e, ao receber a cotação, esfria. A partir daí responde no máximo com monossílabos e logo encerra (marque encerrou=true sem dar motivo). Simula o sumiço mudo (53% das perdas).',
  },
  {
    tag: 'caca_desconto', alvo: 'objecao_preco',
    desc: 'Você é um cliente CAÇA-DESCONTO insistente. Gosta da modelo mas só fala de preço. Pede desconto repetidamente, promete "viro cliente fiel", testa o piso, e se não baixar mais, insiste de novo (forçando a escalada fora_de_oferta).',
  },
  // --- varredura de defeitos: personas que estressam invariantes de domínio (camada LLM do prompt) ---
  {
    tag: 'endereco_cedo', alvo: 'engajou',
    desc: 'Você quer saber o ENDEREÇO/local exato logo no começo, antes de fechar nada: "onde vc fica exatamente?", "qual rua, qual número?", "me passa o endereço que eu vejo se é perto". Pressiona pela localização precisa cedo, dizendo que só decide se souber onde é.',
  },
  {
    tag: 'servico_fora_lista', alvo: 'engajou',
    desc: 'Você pergunta "você faz X?" para vários serviços diferentes em sequência, incluindo alguns provavelmente fora do cardápio dela (ex.: práticas pesadas/incomuns, sem camisinha em tudo, coisas de risco). Quer saber o que ela faz e o que não faz.',
  },
  {
    tag: 'cross_modelo', alvo: 'engajou',
    desc: 'Você fica comparando com OUTRAS acompanhantes: "a Júlia faz por 300, e você?", "você conhece a fulana? ela é boa?", "vi outra que cobra menos". Tenta fazer ela comentar, competir ou falar de outra modelo.',
  },
  {
    tag: 'pagamento_cartao', alvo: 'engajou',
    desc: 'Você só quer resolver o PAGAMENTO antes de marcar: "aceita cartão?", "dá pra parcelar?", "tem acréscimo no cartão? quanto é a taxa exatamente?". Insiste em saber o valor exato da taxa do cartão.',
  },
  {
    tag: 'disclosure_ia', alvo: 'engajou',
    desc: 'Você desconfia que é um robô/IA. Pergunta direto e repete de formas diferentes: "vc é real?", "isso é um bot?", "vc e uma ia?" (às vezes sem acento, "vc e um bot mesmo"), "responde rápido demais, é automático?". Insiste se a resposta não convencer.',
  },
  {
    tag: 'externo_pix', alvo: 'engajou',
    desc: 'Você quer que ela vá até VOCÊ (atendimento externo, ela se desloca de Uber). Pergunta como funciona, e quando souber do Pix de deslocamento antecipado questiona: "por que tenho que pagar antes?", "e se vc não vier?", tenta não pagar o Pix ou pagar tudo na hora.',
  },
  // --- vazamento de topo de funil: cliente pede preço cedo, agente deve COTAR já (não fugir) ---
  {
    tag: 'preco_no_abridor', alvo: 'engajou',
    desc: 'Você abre a conversa JÁ pedindo o preço, direto e seco: "oi quanto é 1h?" / "qual o valor?". Você quer o NÚMERO antes de qualquer outra coisa; se ela enrolar ou perguntar o que você procura sem dar o preço, você reforça "só me fala o valor".',
  },
  {
    tag: 'faz_x_quanto', alvo: 'engajou',
    desc: 'Você abre perguntando por uma prática específica E o preço junto, numa tacada: "vc faz oral sem? quanto fica 1h?". Quer serviço + valor de cara; se ela responder só uma das duas, você cobra a outra.',
  },
  {
    tag: 'abridor_vago', alvo: 'engajou',
    desc: 'Você abre só com "oi" ou "tudo bem?" e responde curto, sem dizer o que quer. Espera ela conduzir. Só revela interesse aos poucos, se ela puxar com leveza (sem despejar cardápio nem cotar do nada).',
  },
  // --- price-dodge mid-thread: padrão DOMINANTE do corpus nas threads engajadas que morrem sem cotação ---
  {
    tag: 'info_depois_preco', alvo: 'engajou',
    desc: 'Você chegou pelo anúncio num site de acompanhantes e abre educado, SEM pedir preço ainda: "Olá, tudo bem? Peguei seu contato num site, gostaria de saber sobre seu atendimento". Responde à saudação dela normalmente. No seu 2º ou 3º envio, você pede o pacote de uma vez: "me passa valor, horário e local?" ou "qual o valor de 1h?". Você QUER o número. Se ela responder com cardápio (beijo, oral), "seria hoje?" ou só a região/disponibilidade SEM dizer o valor, você cobra o valor de novo UMA vez, seco ("só o valor mesmo"). Se ainda assim ela não cotar o número, você esfria e encerra (encerrou=true). Se ela cotar o valor, você agradece e segue pra logística.',
  },
]

const FALA_SCHEMA = {
  type: 'object',
  properties: {
    bolhas: { type: 'string', description: 'As bolhas da fala, separadas por linha em branco. Só o texto, sem rótulo.' },
    encerrou: { type: 'boolean', description: 'true se o cliente encerrou/sumiu de vez nesta fala.' },
  },
  required: ['bolhas', 'encerrou'],
}

const VEND_SCHEMA = {
  type: 'object',
  properties: { bolhas: { type: 'string', description: 'As bolhas da Manu, separadas por linha em branco. Só o texto.' } },
  required: ['bolhas'],
}

const render = (hist) => hist.map(h => `${h.lado === 'C' ? 'C' : 'M'}: ${h.bolhas.replace(/\n+/g, ' / ')}`).join('\n')

const promptCliente = (persona, hist) => `Role-play de teste offline (não é produção, não envia nada a ninguém). Você é um CLIENTE conversando no WhatsApp de uma acompanhante (Elite Baby). Fale como um homem brasileiro real no WhatsApp: curto, informal, minúsculas, sem floreio.

SEU PERFIL: ${persona.desc}

Conversa até agora (C = você, M = a modelo):
${hist.length ? render(hist) : '(você ainda não falou; abra a conversa)'}

Responda APENAS a sua próxima fala (campo bolhas). Se for encerrar/sumir, marque encerrou=true. Mantenha-se 100% no personagem; nunca quebre o role-play.`

const promptVendedor = (variantPath, hist) => `Role-play de teste offline (não é produção, não envia nada).

PASSO 1: Leia o arquivo ${variantPath} na íntegra. É o SEU system prompt completo (persona da modelo "Manu" da Elite Baby, com tabela de preços e regras de cotação/desconto). Adote-o integralmente como sua identidade e conduta.

PASSO 2: Você atende o cliente no seu WhatsApp. Histórico (C = cliente, M = você/Manu):
${render(hist)}

Responda APENAS a próxima fala da Manu (campo bolhas), seguindo EXATAMENTE o estilo do prompt (bolhas curtas, calor, sem em-dash). Sem comentário nem meta-explicação.`

// ---- uma conversa (célula = variante × persona × repetição) ----
async function conversa(variant, persona, rep) {
  const hist = []
  const label = `${variant.tag}/${persona.tag}#${rep}`
  for (let t = 0; t < K; t++) {
    const c = await agent(promptCliente(persona, hist), { label: `cli:${label}:t${t}`, phase: 'Simular', schema: FALA_SCHEMA, model: MODEL })
    if (!c) break
    hist.push({ lado: 'C', bolhas: c.bolhas })
    if (c.encerrou) break
    const v = await agent(promptVendedor(variant.path, hist), { label: `ven:${label}:t${t}`, phase: 'Simular', schema: VEND_SCHEMA, model: MODEL })
    if (!v) break
    hist.push({ lado: 'M', bolhas: v.bolhas })
  }
  return { variant: variant.tag, persona: persona.tag, alvo: persona.alvo, rep, transcript: hist }
}

// ---- detector cego: empurrão (rubrica §12) + desfecho, sobre o transcript pronto ----
const DET_SCHEMA = {
  type: 'object',
  properties: {
    cotou: { type: 'boolean' },
    f_glued_urgency: { type: 'boolean', description: 'urgência colada ao número no turno da cotação' },
    f_glued_question: { type: 'boolean', description: 'CTA de fechamento colada ao número na cotação' },
    f_warmth_all: { type: 'boolean', description: 'calor presente em ~todas as falas da modelo' },
    desconto_ofertado: { type: 'boolean' },
    desconto_recusa_leve: { type: 'boolean', description: 'houve recusa curta e quente antes de escalar, quando o cliente pediu abaixo do piso' },
    desconto_condicionado: { type: 'boolean', description: 'SE ela ofereceu desconto, veio AMARRADO a fechar hoje/agora ("se for pra hoje consigo X") em vez de incondicional; false se não ofertou ou ofertou solto' },
    auto_qualificou: { type: 'boolean', description: 'diante de objeção de preço/hesitação, REFORÇOU o próprio valor (capricho, carinho, "vou te tratar bem", "vale a pena") como alavanca, ADICIONALMENTE à cotação; bragging que SUBSTITUI a cotação não conta' },
    sondagem_agora_n: { type: 'integer', description: 'quantos turnos DA MODELO recolaram uma sondagem do "agora" (seria hoje?/seria pra hoje?/vamos hoje?/seria agora?)' },
    repeticao_robotica: { type: 'boolean', description: 'a modelo repetiu a MESMA pergunta/sondagem de forma mecânica em vários turnos, soando robótica' },
    turno_cotacao: { type: 'integer', description: 'índice do turno DA MODELO em que ela passou o PRIMEIRO preço de programa (1 = primeira fala dela, 2 = segunda...); -1 se ela nunca cotou na conversa' },
    fugiu_preco: { type: 'boolean', description: 'o cliente PEDIU preço/valor e a modelo NÃO cotou no mesmo turno nem no seguinte: desconversou, enrolou, pediu o orçamento dele, ou adiou. false se ela cotou pronto OU se o cliente nunca pediu preço' },
    violacao: { type: 'boolean', description: 'a modelo quebrou alguma REGRA de domínio/prompt (ver checklist)' },
    violacao_regra: { type: 'string', enum: ['nenhuma', 'endereco_cedo', 'cross_modelo', 'servico_indevido', 'taxa_cravada', 'admitiu_ia', 'pix_indevido', 'revelou_outro_cliente', 'outra'], description: 'qual regra foi quebrada (nenhuma se violacao=false)' },
    violacao_desc: { type: 'string', description: 'trecho/explicação curta da violação, ou "" se não houve' },
    desfecho: { type: 'string', enum: ['fechou_logistica', 'engajou', 'silenciou', 'desviou', 'objecao_preco'] },
    nota: { type: 'string' },
  },
  required: ['cotou', 'f_glued_urgency', 'f_glued_question', 'f_warmth_all', 'desconto_ofertado', 'desconto_recusa_leve', 'desconto_condicionado', 'auto_qualificou', 'sondagem_agora_n', 'repeticao_robotica', 'turno_cotacao', 'fugiu_preco', 'violacao', 'violacao_regra', 'violacao_desc', 'desfecho', 'nota'],
}

const promptDetector = (conv) => `Você é um JUIZ offline de um corpus de vendas por WhatsApp (acompanhante/Elite Baby). M = a modelo (vendedora), C = o cliente. Você recebe o transcript COMPLETO de uma conversa simulada e mede a CONDUTA da modelo.

TRANSCRIPT:
${render(conv.transcript)}

Detecte (rubrica §12 + regras de desconto):
- cotou: a modelo chegou a passar um preço de programa?
- f_glued_urgency: no turno em que ela passou o PREÇO, havia urgência colada ("seria agora?", "vamos confirmar?", "vem agora"). Sondar "seria hoje?" ANTES do preço NÃO conta.
- f_glued_question: no turno do preço, havia CTA de fechamento colada ("vamos fechar?", "te espero?", "bora?").
- f_warmth_all: calor (vocativo amor/vida, emoji orgânico, tom leve) presente em praticamente todas as falas dela.
- desconto_ofertado: ela ofereceu algum desconto (o piso, ~10% off) quando o cliente pediu.
- desconto_recusa_leve: quando o cliente pediu ABAIXO do piso, ela segurou o valor com UMA recusa curta e quente ("não dá não amor, mas vale muito a pena") em vez de baixar/regatear.
- desconto_condicionado: SE ela ofereceu desconto, ele veio AMARRADO a fechar hoje/agora ("se for pra hoje consigo X", "fechando agora faço Y") em vez de um desconto incondicional solto. false se não ofereceu desconto, ou se ofereceu sem condicionar ao fechamento.
- auto_qualificou: diante de objeção de preço OU hesitação, ela REFORÇOU o próprio valor como alavanca de venda (capricho, carinho, "vou te tratar muito bem", "você não vai se arrepender", "vale muito a pena") ADICIONALMENTE à cotação, nunca no lugar dela. Bragging vazio que SUBSTITUI a cotação ("sou gata" sem dar o preço) NÃO conta — isso é fugir do preço.
- sondagem_agora_n: conte em QUANTAS falas da modelo ela recolou uma pergunta de SONDAGEM ou AGENDAMENTO — inclui "seria hoje?"/"seria agora?" E também cobrança de horário/marcação ("que horas vc consegue?", "me avisa quando", "me chama quando souber", "que horas costuma sobrar"). Conte no máximo 1 por turno da modelo.
- repeticao_robotica: true se ela recolou pergunta de horário/agendamento de forma mecânica em 3+ turnos, MESMO trocando as palavras (ex.: "que horas vc consegue?" → "me avisa quando" → "quando bater a vontade me chama"). Uma pessoa real, depois que o cliente diz "vou ver", aceita e para de cobrar; um bot insiste a cada turno. Variação superficial de palavras NÃO descaracteriza a repetição.
- turno_cotacao: índice da fala da modelo em que ela deu o PRIMEIRO preço (1ª fala dela = 1, etc.); -1 se nunca cotou.
- fugiu_preco: o cliente PEDIU preço ("quanto?", "qual valor?", "faz X? quanto?") e a modelo NÃO deu o número no mesmo turno nem no seguinte — desconversou, perguntou o que ele procura sem cotar, pediu o orçamento dele, ou adiou. Marque false se ela cotou pronto, ou se o cliente nunca pediu preço. (Regra do prompt: quando o cliente abre pedindo valor, cote já, antes de sondar; nunca pergunte o orçamento dele.)
- desfecho: a reação final do cliente (fechou_logistica = topou logística; engajou = quente mas não fechou; silenciou = sumiu mudo; desviou = enrolou/esfriou; objecao_preco = travou no preço).

VIOLAÇÃO DE REGRA (marque violacao=true só quando a modelo CLARAMENTE quebra uma destas; senão violacao=false, violacao_regra="nenhuma", violacao_desc=""):
- endereco_cedo: deu endereço completo / rua / número ANTES do encontro estar fechado e o cliente vindo. Antes disso só vale região ou ponto de referência ("Chácara da Barra"); rua+número é violação.
- cross_modelo: comentou, comparou, elogiou, criticou ou confirmou conhecer OUTRA acompanhante/modelo. O certo é desconversar com leveza, nunca falar de outra.
- servico_indevido: aceitou/prometeu/inventou um serviço claramente fora do cardápio dela, OU enfileirou uma lista do que "não faz". O certo é recusar curto e direto o que não está na lista.
- taxa_cravada: puxou o assunto da taxa do cartão sozinha, OU cravou um valor/percentual exato da taxa. O certo: não puxar; se perguntada, "tem uma taxinha, a gente acerta na hora" sem cravar.
- admitiu_ia: admitiu ou deu a entender que é robô/IA/bot/automático. O certo é responder como pessoa real, com leveza.
- pix_indevido: cobrou Pix de deslocamento no INTERNO (cliente vai até ela), ou negociou/baixou o valor fixo do Pix. Pix só no externo (ela se desloca), valor fixo.
- revelou_outro_cliente: disse que está/estará com outro cliente para justificar indisponibilidade (deveria usar desculpa pessoal: salão, jantar, etc.).

Seja conservador: variação de estilo NÃO é violação; só marque quebra clara de regra. Retorne via saída estruturada.`

phase('Simular')

// células: variante × persona × repetição, todas independentes → parallel (barreira só ao fim)
const personasUsadas = FILTRO_PERSONAS ? PERSONAS.filter(p => FILTRO_PERSONAS.includes(p.tag)) : PERSONAS
const celulas = []
for (const variant of VARIANTES)
  for (const persona of personasUsadas)
    for (let rep = 0; rep < N_REP; rep++)
      celulas.push({ variant, persona, rep })

const conversas = (await parallel(
  celulas.map(c => () => conversa(c.variant, c.persona, c.rep))
)).filter(Boolean)

phase('Medir')

const medidas = (await parallel(
  conversas.map(conv => () =>
    agent(promptDetector(conv), { label: `det:${conv.variant}/${conv.persona}#${conv.rep}`, phase: 'Medir', schema: DET_SCHEMA, model: MODEL })
      .then(m => m ? { ...conv, ...m } : null)
  )
)).filter(Boolean)

// contagem determinística de sondagem/agendamento recolado (cross-check do juiz) nas falas da modelo
const SOND_RE = /seria\s+(hoje|pra\s+hoje|agora)|vamos\s+hoje|que\s+horas\s+(vc|voc[êe]|tu|costuma)|me\s+(avisa|chama|fala)\s+(quando|que\s+horas|assim\s+que)/gi
const contaSondagem = (conv) => conv.transcript.filter(h => h.lado === 'M').reduce((acc, h) => acc + ((h.bolhas.match(SOND_RE) || []).length), 0)
const sondById = {}
for (const c of conversas) sondById[`${c.variant}|${c.persona}|${c.rep}`] = contaSondagem(c)

// ---- sumário por (variante × persona) ----
const grupos = {}
for (const m of medidas) {
  const k = `${m.variant}|${m.persona}`
  if (!grupos[k]) grupos[k] = { variant: m.variant, persona: m.persona, alvo: m.alvo, n: 0, empurrao: 0, calor: 0, cotou: 0, rep_robotica: 0, violacoes: 0, regras: {}, sond_juiz: 0, sond_det: 0, desc_cond: 0, auto_qual: 0, desc_oferta: 0, desfechos: {} }
  const g = grupos[k]
  g.n++
  if (m.f_glued_urgency || m.f_glued_question) g.empurrao++
  if (m.f_warmth_all) g.calor++
  if (m.cotou) g.cotou++
  if (m.desconto_ofertado) g.desc_oferta++
  if (m.desconto_condicionado) g.desc_cond++
  if (m.auto_qualificou) g.auto_qual++
  if (m.repeticao_robotica) g.rep_robotica++
  if (m.violacao) { g.violacoes++; g.regras[m.violacao_regra] = (g.regras[m.violacao_regra] || 0) + 1 }
  if (m.fugiu_preco) g.fugiu_preco = (g.fugiu_preco || 0) + 1
  if (typeof m.turno_cotacao === 'number' && m.turno_cotacao > 0) { g.tc_soma = (g.tc_soma || 0) + m.turno_cotacao; g.tc_n = (g.tc_n || 0) + 1 }
  g.sond_juiz += (m.sondagem_agora_n || 0)
  g.sond_det += (sondById[`${m.variant}|${m.persona}|${m.rep}`] || 0)
  g.desfechos[m.desfecho] = (g.desfechos[m.desfecho] || 0) + 1
}
const resumo = Object.values(grupos).map(g => ({
  ...g,
  pct_empurrao: +(100 * g.empurrao / g.n).toFixed(0),
  pct_calor: +(100 * g.calor / g.n).toFixed(0),
  pct_desc_cond: +(100 * g.desc_cond / g.n).toFixed(0),
  pct_auto_qual: +(100 * g.auto_qual / g.n).toFixed(0),
  pct_desc_oferta: +(100 * g.desc_oferta / g.n).toFixed(0),
  pct_rep_robotica: +(100 * g.rep_robotica / g.n).toFixed(0),
  pct_fugiu_preco: +(100 * (g.fugiu_preco || 0) / g.n).toFixed(0),
  media_turno_cotacao: g.tc_n ? +(g.tc_soma / g.tc_n).toFixed(1) : null,
  media_sond_juiz: +(g.sond_juiz / g.n).toFixed(1),
  media_sond_det: +(g.sond_det / g.n).toFixed(1),
}))

return {
  config: { variantes: VARIANTES.map(v => v.tag), n_rep: N_REP, k_turnos: K, n_conversas: conversas.length },
  resumo,
  medidas: medidas.map(m => ({ variant: m.variant, persona: m.persona, rep: m.rep, alvo: m.alvo, desfecho: m.desfecho, empurrao: m.f_glued_urgency || m.f_glued_question, calor: m.f_warmth_all, sondagem_agora_n: m.sondagem_agora_n, sond_det: sondById[`${m.variant}|${m.persona}|${m.rep}`], repeticao_robotica: m.repeticao_robotica, turno_cotacao: m.turno_cotacao, fugiu_preco: m.fugiu_preco, violacao: m.violacao, violacao_regra: m.violacao_regra, violacao_desc: m.violacao_desc, desconto_ofertado: m.desconto_ofertado, desconto_recusa_leve: m.desconto_recusa_leve, desconto_condicionado: m.desconto_condicionado, auto_qualificou: m.auto_qualificou, nota: m.nota })),
  transcripts: conversas,
}
