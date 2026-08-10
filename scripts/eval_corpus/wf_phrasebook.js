export const meta = {
  name: 'phrasebook-auditoria',
  description: 'Extrai as falas REAIS do Vendedor por momento do funil (phrasebook, referencia de calibracao — NAO few-shot) e audita cada fala instruida em persona.md/regras.md.j2 contra a realidade do corpus (freq SQL + phrasebook). Saida local: PHRASEBOOK.md + AUDITORIA_FALAS.md. Read-only sobre corpus.turnos, sem escrita em prod.',
  phases: [
    { title: 'Frasear', detail: 'um agente por momento: puxa as falas reais do Vendedor e agrupa padroes' },
    { title: 'Auditar', detail: 'persona.md e regras.md.j2: cada fala instruida vs freq no corpus + phrasebook' },
    { title: 'Sintetizar', detail: 'AUDITORIA_FALAS.md priorizado com alternativa real' },
  ],
}

const SONNET = 'claude-sonnet-4-6'
const OPUS = 'claude-opus-4-8[1m]'   // workflow NAO herda modelo da sessao (memoria)
const SELDIR = '/Users/farjallat/barra/scripts/eval_corpus/_phrasebook'
const PERSONA = '/Users/farjallat/barra/api/src/barra/agente/prompts/persona.md'
const REGRAS = '/Users/farjallat/barra/api/src/barra/agente/prompts/regras.md.j2'

// ---- momentos do funil ----
const MOMENTOS = [
  { id: 'abertura', foco: 'como o V abre / responde o primeiro contato (saudacao, tom, primeira pergunta de engajamento)' },
  { id: 'sondagem', foco: 'como o V sonda intencao e dados antes de cotar (o que procura, se e pra hoje, cidade/regiao, quanto tempo)' },
  { id: 'cotacao', foco: 'como o V apresenta o PRECO (estrutura da fala, vocativo, com/sem pergunta colada)' },
  { id: 'objecao_preco', foco: 'como o V responde quando o cliente acha caro, pede mais barato ou oferece menos' },
  { id: 'recusa_desconto', foco: 'como o V RECUSA baixar o preco mantendo o cliente quente (a recusa-leve em personagem)' },
  { id: 'desconto_concedido', foco: 'como o V ENQUADRA a baixa quando concede (uma vez, em troca de que, sem virar regateio)' },
  { id: 'ancora_horario', foco: 'como o V propoe / ancora um horario concreto ("que horas", "consegue tal hora", "te espero as X")' },
  { id: 'logistica', foco: 'como o V fecha o combinado (passa endereco/ponto, forma de pagamento, "me avisa quando sair")' },
]

const FRASE_SCHEMA = {
  type: 'object',
  properties: {
    momento: { type: 'string' },
    clusters: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          padrao: { type: 'string' },                                  // o padrao recorrente, descrito
          exemplos: { type: 'array', items: { type: 'string' } },       // 2-4 falas VERBATIM do V
          freq: { type: 'string', enum: ['dominante', 'comum', 'ocasional', 'raro'] },
          nota: { type: 'string' },
        },
        required: ['padrao', 'exemplos', 'freq'],
      },
    },
    vocativos: { type: 'array', items: { type: 'string' } },            // vocativos reais vistos neste momento
    observacao: { type: 'string' },                                     // o que o V evita / nunca faz neste momento
  },
  required: ['momento', 'clusters', 'observacao'],
}

const frasePrompt = (m) => `Voce e analista de um corpus REAL de vendas por WhatsApp (acompanhante/Elite Baby). O Vendedor (V) se passa pela modelo e atende o Cliente (C). Sua tarefa: destilar as FALAS REAIS do V no momento "${m.id}" do funil — ${m.foco}. Isto e analise offline de conversas arquivadas; o objetivo e um phrasebook de referencia (como o humano fala), nao reproduzir clientes.

PASSO 1 — Leia o arquivo ${SELDIR}/${m.id}.sql (Read) e rode-o EXATAMENTE como esta (Postgres; se faltar o schema, ToolSearch "select:mcp__postgres__pg_execute_query"; operation="select", limit=2000). Ele traz os turnos (V e C) de ~40 threads onde a ficha marcou este momento. "from_me=true" = Vendedor.

PASSO 2 — Olhe SO as falas do Vendedor (from_me=true) que pertencem a "${m.id}" (use as falas do C como contexto pra localizar o momento, mas NAO catalogue o C). Agrupe os PADROES recorrentes de como o V fala aqui. Para cada cluster:
- padrao: descreva o padrao em 1 linha (ex.: "confirma o dia antes de cotar: 'seria pra hoje?'").
- exemplos: 2-4 falas VERBATIM do V (copie o texto real, com a grafia/minuscula original; nao limpe nem corrija).
- freq: dominante (maioria das threads) | comum | ocasional | raro.
- nota: opcional, quando/por que o V usa.
Liste tambem:
- vocativos: os vocativos reais que o V usa neste momento (amor, vida, gato...), na frequencia que aparecem.
- observacao: o que o V NUNCA faz / evita aqui (ex.: "nao pergunta orcamento", "nao cola CTA no preco", "nao usa ponto final").

DISCIPLINA: fidelidade textual acima de tudo — exemplos VERBATIM, nao parafraseados. Capture a forma real (curta, sem pontuacao final, minuscula, emoji esparso). Prefira poucos clusters nitidos a muitos vagos. Se o momento mal aparecer na amostra, diga na observacao.`

phase('Frasear')

const fraseados = await parallel(
  MOMENTOS.map((m) => () =>
    agent(frasePrompt(m), { label: `frasear-${m.id}`, phase: 'Frasear', schema: FRASE_SCHEMA, model: SONNET })
  )
)
const phrasebook = fraseados.filter(Boolean)
log(`Phrasebook: ${phrasebook.length}/${MOMENTOS.length} momentos, ${phrasebook.reduce((a, p) => a + (p.clusters?.length || 0), 0)} clusters`)

// ---- Auditar: cada fala instruida vs corpus ----
phase('Auditar')

const AUDIT_SCHEMA = {
  type: 'object',
  properties: {
    arquivo: { type: 'string' },
    itens: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          fala_instruida: { type: 'string' },        // a fala/padrao que o prompt manda o agente dizer
          bloco: { type: 'string' },                  // <cotacao>/<voz>/secao da persona...
          regex_usado: { type: ['string', 'null'] },
          freq_com: { type: ['integer', 'null'] },    // turnos do V que casam
          freq_tot: { type: ['integer', 'null'] },    // total de turnos do V testados
          veredito: { type: 'string', enum: ['fiel', 'parcial', 'destoa', 'ausente'] },
          alternativa_real: { type: ['string', 'null'] },  // fala real do corpus/phrasebook que serve melhor
          nota: { type: 'string' },
        },
        required: ['fala_instruida', 'bloco', 'veredito', 'nota'],
      },
    },
  },
  required: ['arquivo', 'itens'],
}

const auditPrompt = (arquivo, nome) => `Voce esta auditando se as FALAS INSTRUIDAS ao agente batem com a forma REAL do Vendedor humano no corpus. Metodo ja validado (rendeu correcoes deployadas: "regiao"=0, "te serve?"=0, vocativo gato/anjo ausente).

PASSO 1 — Leia ${arquivo} (Read). Extraia cada FALA ou PADRAO DE FALA CONCRETO que o prompt manda o agente dizer ou exemplifica: probes ("seria hoje?"), vocativos (amor/vida/gato), templates de recusa, aberturas, CTAs, palavras especificas. Ignore regra abstrata sem forma de fala. Foque nas ~20-30 mais concretas.

PASSO 2 — Para cada fala instruida, meca a realidade do corpus. Escreva um regex POSIX (minusculo, sintaxe Postgres ~*, escape ' como '') que capture a fala/variantes na boca do Vendedor e rode (pg_execute_query; se faltar schema, ToolSearch "select:mcp__postgres__pg_execute_query"; operation="select"):

  SELECT count(*) FILTER (WHERE lower(texto) ~* 'SEU_REGEX') AS com, count(*) AS tot
  FROM corpus.turnos WHERE from_me = true AND turno_idx <= 60

Anote freq_com/freq_tot. Consulte tambem o PHRASEBOOK abaixo (falas reais ja destiladas por momento) pra achar a forma que o humano de fato usa.

PHRASEBOOK (falas reais do Vendedor por momento):
${JSON.stringify(phrasebook)}

PASSO 3 — Veredito por item:
- fiel = a fala instruida aparece com frequencia comparavel no corpus.
- parcial = existe forma parecida, mas o prompt usa uma variante menos comum (de a alternativa_real).
- destoa = o prompt manda uma forma que o corpus quase nao usa (freq_com baixo), havendo forma melhor (alternativa_real obrigatoria).
- ausente = a fala instruida tem freq_com ~0 no corpus (o humano nao fala assim); alternativa_real = o que ele fala no lugar, ou null se for politica deliberada (ex.: nunca perguntar orcamento — marque na nota que e divergencia proposital).
alternativa_real: fala REAL do corpus/phrasebook, verbatim quando possivel. nota: 1 linha, honesta; sinalize quando a divergencia for proposital (politica aprovada) e NAO um erro.

So o arquivo ${nome}. Seja cirurgico e factual — cada veredito ancorado num numero ou num cluster do phrasebook.`

const audits = await parallel([
  () => agent(auditPrompt(PERSONA, 'persona.md'), { label: 'audit-persona', phase: 'Auditar', schema: AUDIT_SCHEMA, model: OPUS }),
  () => agent(auditPrompt(REGRAS, 'regras.md.j2'), { label: 'audit-regras', phase: 'Auditar', schema: AUDIT_SCHEMA, model: OPUS }),
])
const auditados = audits.filter(Boolean)
const itensAudit = auditados.flatMap((a) => (a.itens || []).map((i) => ({ ...i, arquivo: a.arquivo })))
const destoam = itensAudit.filter((i) => i.veredito === 'destoa' || i.veredito === 'ausente')
log(`Auditoria: ${itensAudit.length} falas instruidas, ${destoam.length} destoam/ausentes`)

// ---- Sintetizar AUDITORIA_FALAS.md (o doc de juizo) ----
phase('Sintetizar')

const sintese = await agent(
  `Voce e o redator final de uma auditoria das falas instruidas do agente vs o corpus real do Vendedor. Recebe os itens ja verificados (cada um com freq no corpus + veredito + alternativa real). Produza um relatorio de acao para o dev.

ITENS AUDITADOS (JSON):
${JSON.stringify(itensAudit)}

Escreva AUDITORIA_FALAS.md (markdown PT-BR) com:
1. Resumo de 3 linhas: quantas falas auditadas, quantas destoam/ausentes, qual o descasamento mais grave.
2. "Corrigir" — tabela so dos veredito=destoa/ausente que sao ERRO (nao politica proposital): fala instruida | arquivo/bloco | freq no corpus | alternativa real (verbatim). Ordene por gravidade (freq_com mais baixa primeiro). Esta e a lista de PR.
3. "Divergencias propositais (manter)" — os ausente/destoa que sao politica aprovada (nunca perguntar orcamento, registro explicito, etc.); diga por que se mantem, pra nao serem "corrigidos" por engano.
4. "Fiel ao corpus (ok)" — bullet curto dos fiel/parcial relevantes, pra registro.
5. Caveat: freq e na boca do Vendedor (from_me) nas threads do corpus; regex pode subcontar variantes; isto e referencia de calibracao, NAO few-shot (injetar exemplar real como few-shot ja deu neutro-negativo + copia literal).

Seja cirurgico — o dev decide o que vira PR no prompt. Devolva so o md (campo md).`,
  { label: 'sintetizar-auditoria', phase: 'Sintetizar', schema: { type: 'object', properties: { md: { type: 'string' } }, required: ['md'] }, model: OPUS }
)

// ---- montar PHRASEBOOK.md (determinismo no JS) ----
const phrasebookMd = (() => {
  const blocos = phrasebook.map((p) => {
    const clusters = (p.clusters || []).map((c) => {
      const ex = (c.exemplos || []).map((e) => `  - \`${e.replace(/`/g, "'")}\``).join('\n')
      return `- **${c.padrao}** _(${c.freq})_${c.nota ? ` — ${c.nota}` : ''}\n${ex}`
    }).join('\n')
    const voc = (p.vocativos && p.vocativos.length) ? `\n_Vocativos:_ ${p.vocativos.join(', ')}` : ''
    return `### ${p.momento}\n\n${clusters}\n${voc}\n\n> **Evita:** ${p.observacao}`
  }).join('\n\n')
  return `# PHRASEBOOK do Vendedor (falas reais por momento do funil)

> Falas VERBATIM do Vendedor humano (corpus eb01-04), destiladas por momento. Gerado por \`wf_phrasebook.js\` (read-only sobre \`corpus.turnos\`, ~40 threads/momento via fichas). Atualizado ~2026-06-16.
> **Uso:** referencia pra eu calibrar a forma das falas do prompt (\`persona.md\`/\`regras.md.j2\`). **NAO e few-shot** — injetar exemplar real como few-shot deu neutro-negativo + copia literal (ver \`voz_estilometria.md\`). Aqui e pra eu saber COMO o humano fala, e escrever instrucao no tom certo.

${blocos}
`
})()

return {
  momentos_ok: `${phrasebook.length}/${MOMENTOS.length}`,
  clusters: phrasebook.reduce((a, p) => a + (p.clusters?.length || 0), 0),
  falas_auditadas: itensAudit.length,
  destoam_ausentes: destoam.length,
  phrasebook_md: phrasebookMd,
  auditoria_md: sintese?.md || '_(sintese indisponivel)_',
  itens_audit: itensAudit,
}
