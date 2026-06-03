export const meta = {
  name: 'loop-agente',
  description:
    'Loop A do flywheel: classifica conversas E2E, root-cause das falhas, propoe e verifica fixes dentro do envelope de 5 invariantes; auto-merge com gate local. Dry-run por padrao (Fase 0); Fase 1 liga geracao (API) e merge.',
  phases: [
    { title: 'Classificar' },
    { title: 'Root-cause' },
    { title: 'Propor fix' },
    { title: 'Gate de invariantes' },
  ],
}

// ─────────────────────────────────────────────────────────────────────────────────────────────────
// ESQUELETO (C6 da Fase 0). A maquinaria de diagnostico/envelope (C1-C5) e GRATIS (Claude Code); so a
// GERACAO de conversas e o RE-RUN gastam a API Anthropic (escassa) -> ficam atras de `gerar`/!dry_run.
//
// args: { jsonl?: string, canarios?: string[], gerar?: boolean, dry_run?: boolean }
//   - dry_run (default TRUE na Fase 0): NAO gera, NAO aplica fix, NAO mergeia. So diagnostica e propoe.
//   - gerar  (Fase 1): roda `evals.sim.gerar_conversas --fixo` antes de classificar (★API★).
// Rodar da pasta api/. O cwd dos agentes e a raiz do repo; eles fazem `cd api && uv run ...`.
// ─────────────────────────────────────────────────────────────────────────────────────────────────

const JSONL = (args && args.jsonl) || 'evals/calibracao/conversas_fixas.jsonl'
const CANARIOS = (args && args.canarios) || []
const DRY_RUN = !args || args.dry_run !== false // Fase 0: dry-run a menos que explicitamente false
const FLAG_CANARY = CANARIOS.map((c) => `--canary ${c}`).join(' ')

const RESUMO_SCHEMA = {
  type: 'object',
  required: ['n', 'taxa_e2e_completo', 'falhas_duras', 'precisa_julgamento', 'vereditos'],
  properties: {
    n: { type: 'number' },
    e2e_completo: { type: 'number' },
    taxa_e2e_completo: { type: 'number' },
    por_terminal: { type: 'object' },
    falhas_duras: { type: 'array', items: { type: 'string' } },
    precisa_julgamento: { type: 'array', items: { type: 'string' } },
    invariantes_violacoes: { type: 'array' },
    invariantes_suspeitas: { type: 'array' },
    vereditos: { type: 'array' },
  },
}

const DIAG_SCHEMA = {
  type: 'object',
  required: ['conversa_id', 'causa_raiz', 'camada', 'evidencia'],
  properties: {
    conversa_id: { type: 'string' },
    causa_raiz: { type: 'string', description: 'a causa raiz da falha em uma frase' },
    camada: {
      type: 'string',
      enum: ['prompt', 'tool', 'estado', 'extracao', 'persona', 'cenario_irreal', 'indeterminado'],
      description: 'onde o fix deve incidir',
    },
    evidencia: { type: 'string', description: 'trecho do trace/conversa que prova a causa' },
    e2e_limpo: { type: 'boolean', description: 'apos o juiz: a conversa foi E2E limpa?' },
  },
}

const FIX_SCHEMA = {
  type: 'object',
  required: ['conversa_id', 'arquivo_alvo', 'mudanca', 'risco_invariante'],
  properties: {
    conversa_id: { type: 'string' },
    arquivo_alvo: { type: 'string', description: 'persona.md / regras.md.j2 / tool / graph.py / cenario' },
    mudanca: { type: 'string', description: 'a edicao minima proposta' },
    risco_invariante: {
      type: 'string',
      enum: ['nenhum', 'isolamento', 'aup', 'estado', 'decisoes_produto', 'persona'],
      description: 'qual invariante a mudanca poderia ameacar (o gate confirma)',
    },
    sobrevive_ceticismo: { type: 'boolean', description: 'o ceptico aprovou (gerador != juiz)?' },
  },
}

// ── Fase 1 (★API★): geracao de conversas frescas. No dry-run, usa o jsonl existente. ──────────────
if (!DRY_RUN && args && args.gerar) {
  log('Fase 1: gerando conversas frescas (gasta API Anthropic).')
  await agent(
    `Da raiz do repo, rode: \`cd api && uv run python -m evals.sim.gerar_conversas --fixo --usar-database-url\`. ` +
      `Isso roda o GRAFO REAL contra o cliente fixo (custa API). Reporte quantas conversas foram gravadas em ${JSONL}.`,
    { label: 'gerar:fixo', phase: 'Classificar' },
  )
}

// ── Classificar (GRATIS): o harness relatorio.py roda C1+C3 sobre o jsonl e devolve o resumo. ─────
phase('Classificar')
const resumo = await agent(
  `Da raiz do repo, rode: \`cd api && uv run python -m evals.diagnostico.relatorio --json ${FLAG_CANARY} ${JSONL}\`. ` +
    `Retorne EXATAMENTE o JSON impresso no stdout, sem nenhum texto antes ou depois.`,
  { label: 'classificar', phase: 'Classificar', schema: RESUMO_SCHEMA },
)

// Violacao DURA de invariante ja reprova o lote -- nem adianta propor fix de qualidade por cima.
const violacoes = resumo.invariantes_violacoes || []
if (violacoes.length) {
  log(`GATE DURO: ${violacoes.length} violacao(oes) de invariante -- bloqueia antes de qualquer fix.`)
}

// As conversas que precisam de atencao: falhas duras + fila do juiz (persona/conduta/FP).
const problemas = Array.from(new Set([...(resumo.falhas_duras || []), ...(resumo.precisa_julgamento || [])]))
log(`Classificado: ${resumo.n} conversas, taxa E2E ${Math.round(resumo.taxa_e2e_completo * 100)}%, ${problemas.length} a investigar.`)

// ── Root-cause (GRATIS): um agente por conversa-problema, evidencia disjunta (padrao do blog). ────
// Inclui o JUIZ-DE-ITERACAO: para os `precisa_julgamento`, o agente decide e2e_limpo ancorando a
// persona em evals/diagnostico/regua_persona.md (NUNCA num criterio proprio -> sem deriva).
const diagnosticos = await pipeline(
  problemas,
  (cid) =>
    agent(
      `Root-cause da conversa "${cid}". Leia-a em ${JSONL} (campo conversa_id). Use os campos de ` +
        `diagnostico do turno (prompt_montado, thinking, tool_io, nodes, extracao) e, se houver, o trace no ` +
        `LangSmith projeto barra-vips-sim (MCP: fetch_runs/get_thread_history por atendimento_id). ` +
        `Para persona/conduta, julgue contra api/evals/diagnostico/regua_persona.md (ancorada nas conversas ` +
        `que converteram) -- nunca num criterio seu. Devolva a causa raiz, a camada do fix e a evidencia.`,
      { label: `root-cause:${cid}`, phase: 'Root-cause', schema: DIAG_SCHEMA },
    ),
  // Propor fix (GRATIS) -- generate-and-filter: o gerador propoe, um ceptico independente filtra.
  (diag) => {
    if (!diag || diag.e2e_limpo === true || diag.camada === 'cenario_irreal') return null
    return agent(
      `Proponha o fix MINIMO para: ${diag.causa_raiz} (camada ${diag.camada}, conversa ${diag.conversa_id}). ` +
        `Evidencia: ${diag.evidencia}. Depois CHAME um ceptico independente (gerador != juiz) que verifica se o ` +
        `fix nao overfitta a 1 conversa e nao fere persona autoritativa. Declare o invariante que a mudanca poderia ` +
        `ameacar (o gate confirma depois). Voce esta na Fase 0: PROPONHA, nao aplique.`,
      { label: `fix:${diag.conversa_id}`, phase: 'Propor fix', schema: FIX_SCHEMA },
    )
  },
)

const fixes = diagnosticos.flat().filter(Boolean).filter((f) => f.sobrevive_ceticismo !== false)

// ── Gate de invariantes (GRATIS): o envelope. So roda quando ha fix a aplicar (Fase 1). ───────────
// Na Fase 1, ANTES de aplicar+mergear: os subagentes revisores no DIFF + os graders do runner.
phase('Gate de invariantes')
if (!DRY_RUN && fixes.length) {
  // 1 verificador por invariante de codigo (memory-and-rule-adherence): domain-isolation-reviewer
  // (isolamento+estado+decisoes), langgraph-reviewer (grafo). Qualquer BLOQUEANTE reverte o fix.
  const revisoes = await parallel([
    () =>
      agent(`Revise o diff atual (git diff) contra os invariantes de dominio. Reporte BLOQUEANTE/ATENCAO.`, {
        label: 'gate:domain-isolation',
        phase: 'Gate de invariantes',
        agentType: 'domain-isolation-reviewer',
      }),
    () =>
      agent(`Revise o diff atual (git diff) contra os footguns de LangGraph/ARQ. Reporte bloqueante/risco.`, {
        label: 'gate:langgraph',
        phase: 'Gate de invariantes',
        agentType: 'langgraph-reviewer',
      }),
  ])
  log(`Gate de invariantes: ${revisoes.filter(Boolean).length} revisores rodaram. (Fase 1 aplica auto-merge se limpos + make test verde.)`)
  // Fase 1 (auto-merge com gate local): se gate limpo -> `cd api && make test && make typecheck` e
  // promocao local `git branch -f main`. Reverte o fix se qualquer um falhar. NAO no dry-run.
}

return {
  dry_run: DRY_RUN,
  taxa_e2e_completo: resumo.taxa_e2e_completo,
  violacoes_invariante: violacoes.length,
  investigadas: problemas.length,
  fixes_propostos: fixes,
}
