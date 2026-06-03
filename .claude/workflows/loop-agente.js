export const meta = {
  name: 'loop-agente',
  description:
    'Loop A do flywheel (Fase 1): [gerar conversas E2E ★API★] -> classificar -> root-cause + juiz-de-iteracao -> propor fix -> cetico (gerador != juiz) -> [gate de invariantes + auto-merge local]. Diagnostico por padrao (aplicar=false); full-auto so com aplicar=true.',
  phases: [
    { title: 'Gerar', detail: 'sim --fixo (so com gerar=true; gasta API Anthropic)' },
    { title: 'Classificar', detail: 'relatorio.py: classificacao E2E + gate det. de invariantes' },
    { title: 'Root-cause', detail: '1 agente/conversa: juiz-de-iteracao (persona) + causa raiz' },
    { title: 'Propor fix', detail: 'fix minimo p/ as nao-limpas (gerador)' },
    { title: 'Verificar fix', detail: 'cetico independente (gerador != juiz)' },
    { title: 'Gate de invariantes', detail: 'so com aplicar=true: revisores no diff + make test + branch -f main' },
  ],
}

// ───────────────────────────────────────────────────────────────────────────────────────────────
// DUAS MOEDAS: credito Claude Code (subagentes deste workflow) = ABUNDANTE; credito API Anthropic
// (o GRAFO REAL na geracao + o RE-RUN) = ESCASSO. Tudo que "pensa" (classificar/root-cause/fix/juiz)
// roda de graca em subagente; so a GERACAO (`gerar`) e o RE-RUN gastam API -> ficam atras de flags.
//
// args:
//   gerar?:        bool (default false) -- roda `evals.sim.gerar_conversas --fixo` antes de classificar
//                  (★API★). Geracao e LONGA (~100 turnos Sonnet); o agente roda em background e espera.
//                  RECOMENDADO p/ o baseline: pre-gerar fora do workflow (Bash run_in_background) e
//                  disparar com gerar=false apontando p/ os jsonl frescos.
//   held_out?:     bool (default false) -- inclui o conjunto HELD-OUT (medicao de generalizacao,
//                  conversas_heldout.jsonl). O Loop A NUNCA itera/fixa sobre o held-out; so mede.
//   aplicar?:      bool (default false) -- FULL-AUTO: aplica os fixes aprovados + gate de invariantes
//                  (subagentes revisores no diff) + auto-merge local (make test/typecheck + branch -f
//                  main). DIAGNOSTICO (false) so propoe; o humano revisa antes de ligar o full-auto.
//   jsonl?:        caminho do conjunto de iteracao (default evals/calibracao/conversas_fixas.jsonl).
//   heldout_jsonl?: caminho do held-out (default evals/calibracao/conversas_heldout.jsonl).
//   canarios?:     string[] -- canaries cross-modelo (par B) a auditar na superficie da IA.
//
// Os agentes rodam com cwd na RAIZ do repo; cada um faz `cd api && uv run ...`. Os caminhos de jsonl
// sao relativos a api/.
// ───────────────────────────────────────────────────────────────────────────────────────────────

// A tool Workflow entrega o global `args` JSON-ENCODED como STRING (verificado nesta harness por um
// workflow-echo: passar {held_out:true} chega como '{"held_out":true}'). Parse defensivo aceita os
// dois (string ou objeto) -- sem ele, A.held_out/A.gerar ficam undefined e TUDO cai no default.
const A = (typeof args === 'string' ? JSON.parse(args) : args) || {}
const JSONL = A.jsonl || 'evals/calibracao/conversas_fixas.jsonl'
const HELDOUT_JSONL = A.heldout_jsonl || 'evals/calibracao/conversas_heldout.jsonl'
const CANARIOS = A.canarios || []
const GERAR = A.gerar === true
const HELD_OUT = A.held_out === true
const APLICAR = A.aplicar === true
const FLAG_CANARY = CANARIOS.map((c) => `--canary "${c}"`).join(' ')
const ehHeldout = (cid) => String(cid).startsWith('fixo_heldout')
const jsonlDe = (cid) => (ehHeldout(cid) ? HELDOUT_JSONL : JSONL)

// ── schemas ──────────────────────────────────────────────────────────────────────────────────────

// Espelha o stdout de evals.diagnostico.relatorio --json. vereditos[] e permissivo (relay fiel).
const RESUMO_SCHEMA = {
  type: 'object',
  required: ['n', 'e2e_completo', 'taxa_e2e_completo', 'por_terminal', 'vereditos'],
  properties: {
    n: { type: 'number' },
    e2e_completo: { type: 'number' },
    taxa_e2e_completo: { type: 'number' },
    por_terminal: { type: 'object', additionalProperties: true },
    falhas_duras: { type: 'array', items: { type: 'string' } },
    precisa_julgamento: { type: 'array', items: { type: 'string' } },
    invariantes_violacoes: { type: 'array', items: { type: 'object', additionalProperties: true } },
    invariantes_suspeitas: { type: 'array', items: { type: 'object', additionalProperties: true } },
    vereditos: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: true,
        properties: {
          conversa_id: { type: 'string' },
          terminal: { type: 'string' },
          e2e_completo: { type: 'boolean' },
          motivo_escalada: { type: ['string', 'null'] },
          estado_final: { type: ['string', 'null'] },
          flags: { type: 'array', items: { type: 'string' } },
        },
      },
    },
  },
}

// Veredito do juiz-de-iteracao + root-cause de UMA conversa.
const DIAG_SCHEMA = {
  type: 'object',
  required: ['conversa_id', 'e2e_limpo', 'persona_ok', 'camada', 'causa_raiz', 'evidencia'],
  properties: {
    conversa_id: { type: 'string' },
    terminal: { type: 'string', description: 'eco do terminal determinístico do classificador' },
    e2e_limpo: {
      type: 'boolean',
      description:
        'veredito FINAL da conversa: chegou a desfecho legítimo (handoff/escalada correta) E persona aprovada E sem escalada espúria (FP do piso / super-extração de horário). Falso se travou, escalou à toa ou quebrou persona.',
    },
    persona_ok: {
      type: 'boolean',
      description: 'as falas da IA passam na regua_persona.md (voz real que converteu, sem anti-padrão)?',
    },
    escalada_espuria: {
      type: 'boolean',
      description: 'a escalada (se houve) foi falso-positivo (ex.: fora_de_oferta com valor JÁ no piso)?',
    },
    modo_falha: {
      type: 'string',
      description: 'rótulo curto do modo de falha (ex.: piso_fp, super_extracao_horario, travou_triagem, persona_robotica, loop_repeticao, decisao_revertida); "" se limpa.',
    },
    camada: {
      type: 'string',
      enum: ['nenhum', 'prompt', 'tool', 'estado', 'extracao', 'persona', 'cenario_irreal', 'indeterminado'],
      description: 'onde o fix incide; "nenhum" se a conversa está limpa (sem fix).',
    },
    causa_raiz: { type: 'string', description: 'a causa raiz em uma frase; "—" se limpa.' },
    evidencia: { type: 'string', description: 'trecho citado do transcrito/prompt que prova a causa.' },
  },
}

// Fix minimo proposto (gerador).
const FIX_SCHEMA = {
  type: 'object',
  required: ['conversa_id', 'arquivo_alvo', 'mudanca', 'risco_invariante'],
  properties: {
    conversa_id: { type: 'string' },
    arquivo_alvo: { type: 'string', description: 'ex.: src/barra/agente/prompts/persona.md, regras.md.j2, faq.md, ferramentas/*.py, graph.py' },
    mudanca: { type: 'string', description: 'a edição MÍNIMA proposta (o que muda e por quê), citável.' },
    justificativa: { type: 'string', description: 'por que isto resolve a causa raiz sem overfit a 1 conversa.' },
    risco_invariante: {
      type: 'string',
      enum: ['nenhum', 'isolamento', 'aup', 'estado', 'decisoes_produto', 'persona'],
      description: 'qual dos 5 invariantes a mudança PODERIA ameaçar (o cético e o gate confirmam).',
    },
  },
}

// Veredito do cetico independente (gerador != juiz).
const CETICO_SCHEMA = {
  type: 'object',
  required: ['conversa_id', 'aprovado', 'motivo'],
  properties: {
    conversa_id: { type: 'string' },
    aprovado: { type: 'boolean', description: 'o fix sobrevive ao ceticismo (não overfit, não fere invariante/persona autoritativa)?' },
    overfit: { type: 'boolean', description: 'o fix conserta só esta conversa e quebraria/ignoraria as outras?' },
    motivo: { type: 'string', description: 'uma frase: por que aprovou ou rejeitou.' },
  },
}

// ── Gerar (★API★, opcional) ───────────────────────────────────────────────────────────────────────
phase('Gerar')
if (GERAR) {
  log('Fase 1: gerando conversas frescas (GASTA API Anthropic). Geração longa -> background + espera.')
  const cmds =
    `cd api && uv run python -m evals.sim.gerar_conversas --fixo --usar-database-url` +
    (HELD_OUT
      ? ` && uv run python -m evals.sim.gerar_conversas --fixo --held-out --usar-database-url`
      : '')
  await agent(
    `Gere o baseline E2E rodando o GRAFO REAL contra o cliente fixo (★custa API Anthropic★, escassa). ` +
      `A geração é LONGA (dezenas de turnos Sonnet): rode-a em BACKGROUND e ESPERE terminar antes de reportar. ` +
      `Comando(s), da raiz do repo:\n  ${cmds}\n` +
      `Use Bash com run_in_background=true; depois Monitor/Read no arquivo de saída até ver "Gravado:" ` +
      `(uma por invocação). Cada cenário imprime "[i/N] nome: P passos, K falas da IA". ` +
      `Reporte quantas conversas foram gravadas em ${JSONL}` +
      (HELD_OUT ? ` e ${HELDOUT_JSONL}` : '') +
      ` e qualquer cenário que tenha FALHADO (stderr). NÃO prossiga até a geração concluir.`,
    { label: 'gerar:baseline', phase: 'Gerar' },
  )
} else {
  log(`gerar=false: usando os jsonl existentes (${JSONL}${HELD_OUT ? ' + ' + HELDOUT_JSONL : ''}).`)
}

// ── Classificar (GRATIS) ───────────────────────────────────────────────────────────────────────────
phase('Classificar')
const alvos = HELD_OUT ? `${JSONL} ${HELDOUT_JSONL}` : JSONL
const resumo = await agent(
  `Da raiz do repo, rode EXATAMENTE:\n  cd api && uv run python -m evals.diagnostico.relatorio --json ${FLAG_CANARY} ${alvos}\n` +
    `Isso é OFFLINE/PURO (zero API). Retorne EXATAMENTE o JSON impresso no stdout, sem texto antes ou depois.`,
  { label: 'classificar', phase: 'Classificar', schema: RESUMO_SCHEMA, model: 'opus' },
)

const vereditos = resumo.vereditos || []
const vById = Object.fromEntries(vereditos.map((v) => [v.conversa_id, v]))
const violacoes = resumo.invariantes_violacoes || []
if (violacoes.length) {
  log(`GATE DURO: ${violacoes.length} VIOLAÇÃO(ÕES) determinística(s) de invariante -- bloqueia o auto-merge.`)
  for (const a of violacoes) log(`  [${a.invariante}] ${a.conversa_id}: ${a.detalhe}`)
}
log(
  `Classificado: ${resumo.n} conversas, E2E estrutural ${Math.round((resumo.taxa_e2e_completo || 0) * 100)}%. ` +
    `Terminais: ${JSON.stringify(resumo.por_terminal)}. Cada conversa vai ao juiz-de-iteração.`,
)

// ── Root-cause + juiz-de-iteracao -> Propor fix -> Cetico (GRATIS, pipeline) ────────────────────────
// TODA conversa passa pelo juiz (o classificador determinístico nunca crava e2e_limpo=True sozinho).
// O juiz ancora persona em regua_persona.md (nunca critério próprio -> sem deriva auto-referente).
const todos = vereditos.map((v) => v.conversa_id)

const itens = await pipeline(
  todos,
  // Stage 1 — root-cause + juiz-de-iteracao (1 agente/conversa)
  (cid) => {
    const v = vById[cid] || {}
    const jsonl = jsonlDe(cid)
    return agent(
      `Você é o JUIZ-DE-ITERAÇÃO do Loop A para a conversa "${cid}" (${ehHeldout(cid) ? 'HELD-OUT/generalização' : 'iteração'}).\n\n` +
        `Veredito determinístico (já calculado, NÃO recalcule): terminal=${v.terminal}, e2e_completo=${v.e2e_completo}, ` +
        `motivo_escalada=${v.motivo_escalada}, estado_final=${v.estado_final}, flags=${JSON.stringify(v.flags || [])}.\n\n` +
        `PASSO 1 — leia o transcrito SEM estourar contexto:\n` +
        `  cd api && uv run python -m evals.diagnostico.extrair ${jsonl} ${cid}\n` +
        `(omite o prompt_montado ~24k/turno; já traz o veredito + flags). Só rode \`--prompt-do-turno IDX\` ` +
        `no turno ia EXATO que falhou se precisar do prompt que o gerou. NUNCA carregue o jsonl inteiro.\n\n` +
        `PASSO 2 — julgue PERSONA contra api/evals/diagnostico/regua_persona.md (LEIA o arquivo): as falas da IA ` +
        `soam como modelo real que converteu (calorosa, curta, 1ª pessoa) ou como assistente/robô? Cite o marcador.\n\n` +
        `PASSO 3 — se há suspeita de DECISÃO DE PRODUTO (videocall/cartão/piso/agenda), confira contra ` +
        `api/evals/diagnostico/decisoes_produto.md: a decisão correta NÃO é bug. Recusar videocall com voz boa = LIMPO.\n\n` +
        `PASSO 4 — para escaladas com flag escalada_fp_possivel (fora_de_oferta/reagendamento): confirme se foi ` +
        `GENUÍNA (valor realmente abaixo do piso / horário realmente indisponível) ou ESPÚRIA (FP do piso: ofertou ` +
        `o piso e escalou mesmo assim; super-extração de horário vago). Espúria = e2e_limpo=false.\n\n` +
        `VEREDITO: e2e_limpo = (chegou a desfecho legítimo) E (persona_ok) E (não houve escalada espúria) E (não travou/repetiu). ` +
        `Se limpa: camada="nenhum", causa_raiz="—". Se cenário irreal (o cliente fixo forçou algo impossível), camada="cenario_irreal". ` +
        `Caso contrário aponte camada+causa_raiz+evidência citada.`,
      { label: `diag:${cid}`, phase: 'Root-cause', schema: DIAG_SCHEMA, model: 'opus' },
    )
  },
  // Stage 2 — propor fix (so p/ nao-limpas, fixaveis; held-out NUNCA gera fix: e medicao, nao iteracao)
  (diag) => {
    if (!diag) return null
    const semFix =
      diag.e2e_limpo === true ||
      ['nenhum', 'cenario_irreal', 'indeterminado'].includes(diag.camada) ||
      ehHeldout(diag.conversa_id)
    if (semFix) return { diag, fix: null }
    return agent(
      `Proponha o fix MÍNIMO (Loop A é DESENVOLVIMENTO: persona/prompt/tool/grafo são editáveis) para:\n` +
        `  conversa=${diag.conversa_id} | camada=${diag.camada} | causa_raiz=${diag.causa_raiz}\n  evidência: ${diag.evidencia}\n\n` +
        `Regras: (1) a edição mais cirúrgica que resolve a CAUSA, não a 1 conversa (anti-overfit). ` +
        `(2) NÃO reverta nenhuma das 5 invariantes — leia api/evals/diagnostico/decisoes_produto.md e ` +
        `api/evals/diagnostico/regua_persona.md; declare qual invariante a mudança poderia ameaçar. ` +
        `(3) Aponte o arquivo-alvo real (provavelmente src/barra/agente/prompts/*.md|*.j2 ou ferramentas/*.py). ` +
        `Você está PROPONDO (não aplique nada agora).`,
      { label: `fix:${diag.conversa_id}`, phase: 'Propor fix', schema: FIX_SCHEMA, model: 'opus' },
    ).then((fix) => ({ diag, fix }))
  },
  // Stage 3 — cetico independente (gerador != juiz): refuta o fix
  (par) => {
    if (!par || !par.fix) return par
    return agent(
      `Você é um CÉTICO independente (NÃO foi quem propôs). Tente REFUTAR este fix proposto:\n` +
        `  conversa=${par.fix.conversa_id} | arquivo=${par.fix.arquivo_alvo} | risco=${par.fix.risco_invariante}\n` +
        `  mudança: ${par.fix.mudanca}\n  justificativa: ${par.fix.justificativa}\n\n` +
        `Pergunte: (a) overfit? conserta só "${par.fix.conversa_id}" e quebraria outras conversas/casos? ` +
        `(b) fere algum invariante (isolamento/AUP/estado/decisões de produto/persona)? Confira contra ` +
        `api/evals/diagnostico/decisoes_produto.md e regua_persona.md. (c) há um fix mais simples/seguro? ` +
        `Na dúvida, REJEITE (aprovado=false). Aprove só se sobrevive a (a) e (b).`,
      { label: `cetico:${par.diag.conversa_id}`, phase: 'Verificar fix', schema: CETICO_SCHEMA, model: 'opus' },
    ).then((cetico) => ({ ...par, cetico }))
  },
)

// ── Agregacao do baseline ───────────────────────────────────────────────────────────────────────────
const bons = itens.filter(Boolean)
const diags = bons.map((i) => i.diag).filter(Boolean)
const fixesPropostos = bons
  .filter((i) => i.fix)
  .map((i) => ({ ...i.fix, aprovado_cetico: !!(i.cetico && i.cetico.aprovado), cetico: i.cetico || null }))
const fixesAprovados = fixesPropostos.filter((f) => f.aprovado_cetico)

const taxa = (lista) => (lista.length ? lista.filter((d) => d.e2e_limpo).length / lista.length : null)
const iteracao = diags.filter((d) => !ehHeldout(d.conversa_id))
const heldout = diags.filter((d) => ehHeldout(d.conversa_id))
const sumario = {
  n: diags.length,
  taxa_e2e_limpo_total: taxa(diags),
  taxa_e2e_limpo_iteracao: taxa(iteracao),
  taxa_e2e_limpo_heldout: heldout.length ? taxa(heldout) : null,
  modos_falha: diags
    .filter((d) => !d.e2e_limpo)
    .map((d) => ({ conversa_id: d.conversa_id, modo: d.modo_falha, camada: d.camada, causa: d.causa_raiz })),
}
log(
  `Juiz-de-iteração: E2E LIMPO ${Math.round((sumario.taxa_e2e_limpo_total || 0) * 100)}% ` +
    `(iteração ${Math.round((sumario.taxa_e2e_limpo_iteracao || 0) * 100)}%` +
    (sumario.taxa_e2e_limpo_heldout != null ? `, held-out ${Math.round(sumario.taxa_e2e_limpo_heldout * 100)}%` : '') +
    `). ${fixesAprovados.length}/${fixesPropostos.length} fixes sobreviveram ao cético.`,
)

// ── Gate de invariantes + auto-merge local (★FULL-AUTO★, so com aplicar=true) ───────────────────────
phase('Gate de invariantes')
let resultadoAplicacao = null
if (APLICAR && !violacoes.length && fixesAprovados.length) {
  log(`FULL-AUTO: aplicando ${fixesAprovados.length} fix(es) aprovado(s) + gate de invariantes + auto-merge local.`)
  // 1) aplica os fixes (1 agente, edições cirúrgicas nos arquivos-alvo)
  await agent(
    `Aplique estes fixes APROVADOS (edições cirúrgicas, mínimas, nos arquivos indicados). NÃO toque em mais nada:\n` +
      fixesAprovados.map((f) => `- ${f.arquivo_alvo}: ${f.mudanca}`).join('\n') +
      `\nDepois rode \`cd api && make format\` para normalizar. Reporte os arquivos tocados (git diff --stat).`,
    { label: 'aplicar-fixes', phase: 'Gate de invariantes', model: 'opus' },
  )
  // 2) gate de invariantes: revisores no DIFF (qualquer BLOQUEANTE reverte)
  const revisoes = await parallel([
    () =>
      agent(
        `Revise \`git diff\` (raiz do repo) contra os invariantes de domínio (isolamento cross-modelo, máquina ` +
          `de estados, decisões de produto). Reporte BLOQUEANTE/ATENÇÃO com arquivo:linha.`,
        { label: 'gate:domain-isolation', phase: 'Gate de invariantes', agentType: 'domain-isolation-reviewer' },
      ),
    () =>
      agent(`Revise \`git diff\` contra os footguns de LangGraph/ARQ. Reporte bloqueante/risco.`, {
        label: 'gate:langgraph',
        phase: 'Gate de invariantes',
        agentType: 'langgraph-reviewer',
      }),
  ])
  // 3) gate local + promocao (espelha fluxo_integracao_worktrees_paralelos): make test/typecheck e branch -f main.
  //    O agente DEVE reverter (git checkout --) se algum revisor reportou BLOQUEANTE ou se os gates falharem.
  const merge = await agent(
    `Decida o AUTO-MERGE LOCAL com gate (sem push). Revisões de invariantes:\n` +
      revisoes.filter(Boolean).map((r, i) => `--- revisor ${i + 1} ---\n${r}`).join('\n') +
      `\n\nSe QUALQUER revisor reportou BLOQUEANTE: faça \`git checkout -- .\` (reverte os fixes) e reporte BLOQUEADO. ` +
      `Senão rode \`cd api && make test && make typecheck\`. Se passarem: \`git add -A && git commit\` os fixes do Loop A ` +
      `e promova a main local com \`git branch -f main HEAD\` (NÃO faça push). Se falharem: \`git checkout -- .\` e reporte. ` +
      `Reporte o resultado final (MERGED / BLOQUEADO / REVERTIDO) e o motivo.`,
    { label: 'auto-merge', phase: 'Gate de invariantes', model: 'opus' },
  )
  resultadoAplicacao = { revisoes: revisoes.filter(Boolean).length, merge }
} else if (APLICAR) {
  log(
    violacoes.length
      ? 'aplicar=true mas há VIOLAÇÃO determinística de invariante -> NÃO aplica nada.'
      : 'aplicar=true mas nenhum fix sobreviveu ao cético -> nada a aplicar.',
  )
} else {
  log('aplicar=false (DIAGNÓSTICO): fixes apenas PROPOSTOS. O humano revisa antes de ligar o full-auto.')
}

return {
  modo: APLICAR ? 'full-auto' : 'diagnostico',
  gerou: GERAR,
  classificacao: {
    n: resumo.n,
    taxa_e2e_completo_estrutural: resumo.taxa_e2e_completo,
    por_terminal: resumo.por_terminal,
    invariantes_violacoes: violacoes,
    invariantes_suspeitas: resumo.invariantes_suspeitas || [],
  },
  juiz: sumario,
  vereditos_juiz: diags,
  fixes_propostos: fixesPropostos,
  fixes_aprovados: fixesAprovados,
  aplicacao: resultadoAplicacao,
}
