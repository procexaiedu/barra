export const meta = {
  name: 'mineracao-contrastiva',
  description: 'Minera comportamentos controlaveis do Vendedor que distinguem WIN (fechou_logistica) de LOSS (desviou/objecao_preco) no corpus real, testa cada um por lift no corpus inteiro e descarta o que ja esta no prompt',
  phases: [
    { title: 'Minerar', detail: 'fan-out le pares WIN/LOSS e extrai comportamentos candidatos' },
    { title: 'Consolidar', detail: 'dedup dos candidatos numa lista canonica' },
    { title: 'Verificar', detail: 'lift no corpus inteiro + checagem "ja codificado no prompt?"' },
    { title: 'Sintetizar', detail: 'relatorio priorizado: net-new com lift real + onde plugar' },
  ],
}

// ---- parametros ----
const SONNET = 'claude-sonnet-4-6'
const OPUS = 'claude-opus-4-8[1m]'   // workflow NAO herda modelo da sessao; setar ID exato (memoria)
const N_BATCH = 18      // particoes hash da AMOSTRA de mineracao
const SAMPLE_MOD = 2    // mina ~1/2 da populacao (geracao de hipotese); a verificacao usa o corpus inteiro
const CAP = 70          // turnos no transcript (o slip acontece ao longo do thread, nao so na cotacao)

const PERSONA = '/Users/farjallat/barra/api/src/barra/agente/prompts/persona.md'
const REGRAS = '/Users/farjallat/barra/api/src/barra/agente/prompts/regras.md.j2'

// ---- SQL da mineracao: cada batch traz uma mistura de WIN e LOSS ----
const minerSql = (i) => `WITH win AS (
  SELECT instancia, remote_jid, 'WIN' AS coorte
  FROM corpus.eval_cotacao
  WHERE reacao_real = 'fechou_logistica'
), loss AS (
  SELECT instancia, remote_jid, 'LOSS' AS coorte
  FROM corpus.eval_cotacao
  WHERE reacao_real IN ('desviou','objecao_preco')
), pop AS (
  SELECT * FROM win UNION ALL SELECT * FROM loss
)
SELECT p.coorte, p.instancia, p.remote_jid,
  string_agg(
    'T' || t.turno_idx || ' ' || (CASE WHEN t.from_me THEN 'V: ' ELSE 'C: ' END) ||
    COALESCE(NULLIF(btrim(t.texto), ''), CASE WHEN t.tem_midia THEN '[midia]' ELSE '[--]' END),
    E'\\n' ORDER BY t.turno_idx
  ) FILTER (WHERE t.turno_idx <= ${CAP}) AS transcript
FROM pop p
JOIN corpus.turnos t USING (instancia, remote_jid)
WHERE abs(hashtext(p.remote_jid)) % ${SAMPLE_MOD} = 0
  AND abs(hashtext(p.remote_jid)) % ${N_BATCH} = ${i}
GROUP BY p.coorte, p.instancia, p.remote_jid
ORDER BY p.coorte, p.remote_jid`

const MINER_SCHEMA = {
  type: 'object',
  properties: {
    candidatos: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          comportamento: { type: 'string' },
          hipotese: { type: 'string' },
          momento: { type: 'string', enum: ['abertura', 'sondagem', 'cotacao', 'objecao', 'logistica', 'reengajamento_intra', 'outro'] },
          contraste: { type: 'string' },
          evidencia_jids: { type: 'array', items: { type: 'string' } },
          operacionalizavel_regex: { type: 'boolean' },
        },
        required: ['comportamento', 'hipotese', 'momento', 'contraste', 'evidencia_jids', 'operacionalizavel_regex'],
      },
    },
  },
  required: ['candidatos'],
}

const minerPrompt = (i) => `Voce e analista de um corpus REAL de vendas por WhatsApp (acompanhante/Elite Baby). O Vendedor (V) se passa pela modelo e atende o Cliente (C). Vou te dar threads ja rotuladas em duas coortes e quero que voce extraia comportamentos CONTROLAVEIS do Vendedor que aparecem mais nas que converteram.

PASSO 1 - Busque seus dados. Use Postgres (procure "pg_execute_query"; se faltar schema, faca ToolSearch "select:mcp__postgres__pg_execute_query"). Rode EXATAMENTE (operation="select"):

${minerSql(i)}

Cada linha e uma thread: coorte (WIN|LOSS), instancia, remote_jid, transcript. No transcript "Tn V:" = Vendedor, "Tn C:" = Cliente, "[midia]" = foto/video.
- WIN = o cliente deu compromisso concreto de encontro (fechou logistica).
- LOSS = o cliente estava presente e respondendo, mas esfriou/desviou ou bateu no preco e escapou. NAO sao fantasmas mudos - aqui o que o Vendedor fez plausivelmente importou.

PASSO 2 - Compare as WIN com as LOSS e liste comportamentos do VENDEDOR (conduta, nao sorte do cliente) que aparecem MAIS nas WIN. Para cada um:
- comportamento: nome curto (ex.: "ancora horario concreto apos cotar").
- hipotese: o que o V faz, em 1-2 frases, e por que ajudaria a fechar.
- momento: onde no funil acontece.
- contraste: o que as LOSS fizeram no lugar.
- evidencia_jids: remote_jids de threads WIN onde voce viu o comportamento (>=1).
- operacionalizavel_regex: true se da pra detectar por palavra-chave/regex na fala do V; false se so um juiz LLM pegaria.

DISCIPLINA ANTI-VIES (critico): voce SABE o rotulo, entao e facil racionalizar. So liste um comportamento se voce apostaria que ele aparece QUANTITATIVAMENTE mais nas WIN do que nas LOSS - cada candidato sera testado por lift no corpus inteiro depois, cego. Nao liste:
- generico/obvio ("ser educado", "responder rapido") sem forma concreta.
- coisa que e sorte/estado do cliente, nao acao do V.
- mais que ~6 candidatos por batch; prefira poucos e nitidos.`

phase('Minerar')

const batches = Array.from({ length: N_BATCH }, (_, i) => i)
const mined = await parallel(
  batches.map((i) => () =>
    agent(minerPrompt(i), { label: `minerar-b${i}`, phase: 'Minerar', schema: MINER_SCHEMA, model: SONNET })
  )
)

const candidatosRaw = mined.filter(Boolean).flatMap((m) => m.candidatos || [])
log(`Minerados ${candidatosRaw.length} candidatos brutos de ${mined.filter(Boolean).length}/${N_BATCH} batches`)

// ---- Consolidar (barreira justificada: dedup precisa de TODOS os candidatos) ----
phase('Consolidar')

const CONSOLIDA_SCHEMA = {
  type: 'object',
  properties: {
    canonicos: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          id: { type: 'string' },
          comportamento: { type: 'string' },
          hipotese: { type: 'string' },
          momento: { type: 'string' },
          contraste: { type: 'string' },
          evidencia_jids: { type: 'array', items: { type: 'string' } },
          n_miners: { type: 'integer' },
          operacionalizavel_regex: { type: 'boolean' },
        },
        required: ['id', 'comportamento', 'hipotese', 'momento', 'contraste', 'evidencia_jids', 'n_miners', 'operacionalizavel_regex'],
      },
    },
  },
  required: ['canonicos'],
}

const consolidado = await agent(
  `Voce recebeu candidatos de comportamento de Vendedor extraidos por varios analistas de um corpus de vendas. Muitos sao o MESMO comportamento com nomes diferentes. Sua tarefa: fundir numa lista canonica.

Candidatos brutos (JSON):
${JSON.stringify(candidatosRaw)}

Regras:
- Agrupe duplicatas/quase-duplicatas num unico canonico; some quantos analistas distintos o citaram em n_miners (sinal de robustez); una as evidencia_jids (dedup).
- id = slug curto kebab-case.
- Mantenha contraste e hipotese mais nitidos.
- operacionalizavel_regex = true se QUALQUER versao do candidato era detectavel por regex.
- Descarte os genericos/vagos demais para testar. Devolva no maximo ~20 canonicos, ordenados por n_miners desc.`,
  { label: 'consolidar', phase: 'Consolidar', schema: CONSOLIDA_SCHEMA, model: OPUS }
)

const canonicos = (consolidado?.canonicos || [])
log(`Consolidado em ${canonicos.length} comportamentos canonicos`)

// ---- Verificar (pipeline por candidato: lift no corpus inteiro + ja-codificado) ----
phase('Verificar')

const liftSqlTemplate = `WITH vt AS (
  SELECT e.instancia, e.remote_jid, e.label_bin,
    string_agg(CASE WHEN t.from_me THEN t.texto ELSE NULL END, ' ' ORDER BY t.turno_idx) AS v_text
  FROM corpus.eval_cotacao e
  JOIN corpus.turnos t USING (instancia, remote_jid)
  WHERE e.label_bin IS NOT NULL
  GROUP BY e.instancia, e.remote_jid, e.label_bin
)
SELECT (v_text ~* '{{REGEX}}') AS tem,
  count(*) AS n,
  count(*) FILTER (WHERE label_bin = 'GOOD') AS good
FROM vt GROUP BY 1 ORDER BY 1`

const VERIFICA_SCHEMA = {
  type: 'object',
  properties: {
    id: { type: 'string' },
    comportamento: { type: 'string' },
    ja_codificado: { type: 'boolean' },
    citacao_prompt: { type: ['string', 'null'] },
    regex: { type: ['string', 'null'] },
    n_com: { type: ['integer', 'null'] },
    good_com: { type: ['integer', 'null'] },
    n_sem: { type: ['integer', 'null'] },
    good_sem: { type: ['integer', 'null'] },
    lift: { type: ['number', 'null'] },
    veredito: { type: 'string', enum: ['novo_com_lift', 'novo_sem_lift', 'ja_codificado', 'nao_operacionalizavel'] },
    nota: { type: 'string' },
  },
  required: ['id', 'comportamento', 'ja_codificado', 'regex', 'lift', 'veredito', 'nota'],
}

const verificaPrompt = (c) => `Voce vai VERIFICAR uma hipotese de comportamento de Vendedor contra o corpus real e contra o prompt atual do agente. Seja cetico: a maioria das hipoteses de "isso converte" NAO se sustenta no numero (o desfecho da cotacao e quase-acaso, kappa=0.07). Seu trabalho e separar o que tem lift real do que e folclore.

CANDIDATO:
${JSON.stringify(c)}

PASSO 1 - JA ESTA NO PROMPT? Leia os arquivos abaixo (Read) e decida se essa conduta ja esta instruida:
- ${PERSONA}
- ${REGRAS}
Se ja estiver, ja_codificado=true e citacao_prompt = trecho curto que cobre. Se nao, ja_codificado=false, citacao_prompt=null.

PASSO 2 - TEM LIFT? Se operacionalizavel por regex, escreva um regex POSIX (sintaxe Postgres ~*, minusculas) que capture a fala do Vendedor com esse comportamento. Teste mentalmente contra as evidencia_jids. Rode (pg_execute_query, operation="select") EXATAMENTE este SQL trocando {{REGEX}} pelo seu padrao (escape aspas simples como '' ):

${liftSqlTemplate}

Vai retornar 2 linhas (tem=false, tem=true). Calcule:
- n_com/good_com = n e good da linha tem=true; n_sem/good_sem = da linha tem=false.
- lift = (good_com/n_com) - (good_sem/n_sem), em pontos de fracao (ex.: 0.62-0.50 = 0.12).
- Se o regex casar quase nada (n_com < 8) ou quase tudo, ele e inutil: registre e marque veredito conforme o caso (sem lift confiavel).

PASSO 3 - VEREDITO:
- ja_codificado -> "ja_codificado".
- nao da pra regex de jeito honesto -> "nao_operacionalizavel" (regex=null, lift=null), e diga na nota se vale um juiz LLM depois.
- net-new e lift >= +0.05 com n_com >= 8 -> "novo_com_lift".
- net-new mas lift desprezivel/negativo/ruido -> "novo_sem_lift".
nota: 1-2 frases honestas (inclua a confianca e o confound, ja que lift e associacao, nao causa).`

const verificados = await pipeline(
  canonicos,
  (c) => agent(verificaPrompt(c), { label: `verificar-${c.id}`, phase: 'Verificar', schema: VERIFICA_SCHEMA, model: SONNET })
)

const vlist = verificados.filter(Boolean)
const aproveitaveis = vlist.filter((v) => v.veredito === 'novo_com_lift')
log(`Verificados ${vlist.length}; com lift real e net-new: ${aproveitaveis.length}`)

// ---- Sintetizar relatorio priorizado ----
phase('Sintetizar')

const SINTESE_SCHEMA = {
  type: 'object',
  properties: {
    relatorio_md: { type: 'string' },
    top: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          comportamento: { type: 'string' },
          lift: { type: ['number', 'null'] },
          onde_plugar: { type: 'string' },
          redacao_sugerida: { type: 'string' },
        },
        required: ['comportamento', 'lift', 'onde_plugar', 'redacao_sugerida'],
      },
    },
  },
  required: ['relatorio_md', 'top'],
}

const sintese = await agent(
  `Voce e o redator final de uma mineracao contrastiva do corpus real do Vendedor (WIN=fechou_logistica vs LOSS=desviou/objecao_preco). Recebe os comportamentos ja VERIFICADOS (lift no corpus inteiro de 775 threads rotuladas + se ja estao no prompt). Produza um relatorio de acao para o dev.

VERIFICADOS (JSON):
${JSON.stringify(vlist)}

Escreva relatorio_md (markdown, PT-BR) com:
1. Resumo de 3 linhas: quantos candidatos, quantos net-new com lift, qual o achado mais forte.
2. Tabela dos "novo_com_lift" ordenados por lift desc: comportamento | lift | n_com | momento | onde plugar (qual arquivo/secao de prompt: persona.md ou regras.md.j2, e qual bloco tipo <cotacao>/<desconto>/<logistica>).
3. Para cada um do top, uma redacao_sugerida curta no tom do Vendedor (sem em-dash, minimalista) pronta pra colar no prompt.
4. Secao "Descartados e por que": os ja_codificado (com a citacao), os novo_sem_lift (folclore desmentido pelo numero) e os nao_operacionalizavel (candidatos a um juiz LLM numa proxima rodada).
5. Caveat honesto: lift e associacao, nao causa; mineracao viu so ~1/2 da populacao; verificacao usou o corpus inteiro.

Preencha tambem top[] com os novo_com_lift (comportamento, lift, onde_plugar, redacao_sugerida). Seja conciso e cirurgico - o dev decide o que vira PR.`,
  { label: 'sintetizar', phase: 'Sintetizar', schema: SINTESE_SCHEMA, model: OPUS }
)

return {
  resumo: {
    candidatos_brutos: candidatosRaw.length,
    canonicos: canonicos.length,
    verificados: vlist.length,
    novo_com_lift: aproveitaveis.length,
    por_veredito: vlist.reduce((a, v) => ((a[v.veredito] = (a[v.veredito] || 0) + 1), a), {}),
  },
  top: sintese?.top || [],
  relatorio_md: sintese?.relatorio_md || '',
  verificados: vlist,
}
