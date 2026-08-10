export const meta = {
  name: 'atlas-corpus',
  description: 'Enriquece o corpus real do Vendedor (1512 threads nao-ops) com uma ficha unificada por thread (LLM) e consolida um ATLAS navegavel: inventario das tabelas corpus.*, distribuicoes, exemplos-ouro por categoria e os achados dispersos dos .md num lugar so. Saida 100% local em scripts/eval_corpus/ (sem escrita em prod, moeda Claude Code).',
  phases: [
    { title: 'Ficha', detail: 'fan-out: cada agente puxa seu batch via SQL e emite 1 ficha/thread' },
    { title: 'Consolidar', detail: 'funde os 6 relatorios .md de achados num bloco unico' },
    { title: 'Navegar', detail: 'valida exemplos-ouro por categoria + escreve o guia de navegacao' },
  ],
}

// ---- parametros ----
const SONNET = 'claude-sonnet-4-6'
const OPUS = 'claude-opus-4-8[1m]'   // workflow NAO herda modelo da sessao; ID exato (memoria workflow_modelo_herda_sessao)
const N_BATCH = 80      // ~19 threads/agente sobre as 1512 nao-ops
const CAP = 60          // turnos no transcript (a jornada inteira, nao so a cotacao)
const DIR = '/Users/farjallat/barra/scripts/eval_corpus'

// ---- SQL: cada agente traz seu batch (thread features + transcript) ----
const fichaSql = (i) => `WITH pop AS (
  SELECT instancia, remote_jid, desfecho_proxy, tipo_atendimento_proxy,
         tem_valor, tem_pix, tem_local, tem_saida, agenda_firme, objecao, negou,
         n_turnos, horas
  FROM corpus.threads
  WHERE thread_ops = false
    AND abs(hashtext(remote_jid)) % ${N_BATCH} = ${i}
)
SELECT p.instancia, p.remote_jid, p.desfecho_proxy, p.tipo_atendimento_proxy,
       p.tem_valor, p.tem_pix, p.tem_local, p.tem_saida, p.agenda_firme, p.objecao, p.negou,
       p.n_turnos, p.horas,
  string_agg(
    'T' || t.turno_idx || ' ' || (CASE WHEN t.from_me THEN 'V: ' ELSE 'C: ' END) ||
    COALESCE(NULLIF(btrim(t.texto), ''), CASE WHEN t.tem_midia THEN '[midia]' ELSE '[--]' END),
    E'\\n' ORDER BY t.turno_idx
  ) FILTER (WHERE t.turno_idx <= ${CAP}) AS transcript
FROM pop p
JOIN corpus.turnos t USING (instancia, remote_jid)
GROUP BY p.instancia, p.remote_jid, p.desfecho_proxy, p.tipo_atendimento_proxy,
         p.tem_valor, p.tem_pix, p.tem_local, p.tem_saida, p.agenda_firme, p.objecao, p.negou,
         p.n_turnos, p.horas
ORDER BY p.remote_jid`

const FICHA_SCHEMA = {
  type: 'object',
  properties: {
    fichas: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          instancia: { type: 'string' },
          remote_jid: { type: 'string' },
          desfecho_proxy: { type: ['string', 'null'] },          // passthrough do SQL (cross-tab no JS)
          tipo_atendimento_proxy: { type: ['string', 'null'] },  // passthrough (medir resgate dos nulos)
          tipo_atendimento: { type: 'string', enum: ['interno', 'externo', 'externo_pickup', 'remoto', 'ambos', 'indefinido'] },
          estagio_max: { type: 'string', enum: ['saudacao_only', 'sondagem', 'cotou', 'negociou', 'combinou', 'prova_vinda'] },
          objecoes: { type: 'array', items: { type: 'string', enum: ['preco', 'horario', 'local_distancia', 'risco_seguranca', 'golpe_desconfianca', 'indeciso', 'nenhuma', 'outro'] } },
          conduta_vendedor: { type: 'array', items: { type: 'string', enum: ['cotacao_limpa', 'empurrao_urgencia', 'pergunta_colada', 'recusou_desconto', 'deu_desconto', 'ancora_horario', 'enviou_midia', 'desviou_preco', 'reengajou', 'tom_frio', 'tom_quente'] } },
          tag_qualidade: { type: 'string', enum: ['ouro', 'anti_padrao', 'neutro', 'ops_ruido'] },
          resumo_1linha: { type: 'string' },
          confianca: { type: 'number' },
        },
        required: ['instancia', 'remote_jid', 'tipo_atendimento', 'estagio_max', 'objecoes', 'conduta_vendedor', 'tag_qualidade', 'resumo_1linha', 'confianca'],
      },
    },
  },
  required: ['fichas'],
}

const fichaPrompt = (i) => `Voce e analista de um corpus REAL de vendas por WhatsApp (acompanhante/Elite Baby). O Vendedor (V) se passa pela modelo e atende o Cliente (C). Sua tarefa: ler cada thread e emitir UMA ficha estruturada por thread. Isto NAO conduz nenhum cliente real - e anotacao offline de conversas ja arquivadas.

PASSO 1 - Busque seus dados. Use Postgres (se faltar o schema, faca ToolSearch "select:mcp__postgres__pg_execute_query"). Rode EXATAMENTE (operation="select"):

${fichaSql(i)}

Cada linha e uma thread: instancia, remote_jid, os proxies determinist​icos (desfecho_proxy, tipo_atendimento_proxy) e features booleanas, mais o transcript. No transcript "Tn V:" = Vendedor, "Tn C:" = Cliente, "[midia]" = foto/video, "[--]" = bolha sem texto.

PASSO 2 - Para CADA thread, emita uma ficha. Devolva instancia e remote_jid EXATOS, e copie desfecho_proxy e tipo_atendimento_proxy do SQL para os campos de mesmo nome (passthrough, nao reinterprete esses dois). Os campos que VOCE julga:

- tipo_atendimento: quem se desloca, lido da conversa (NAO do proxy, que e 56% nulo):
  - interno = o cliente vai ate a modelo (pede endereco dela, "foto da portaria", "to chegando").
  - externo = a modelo se desloca ate o cliente (pede endereco do cliente, "pix do uber/deslocamento").
  - externo_pickup = externo mas o CLIENTE busca a modelo de carro (rolê/casa dele), sem pix de deslocamento.
  - remoto = video chamada ao vivo, ninguem se desloca, sem local fisico.
  - ambos = a conversa discute os dois sem fixar.
  - indefinido = nao da pra inferir (morreu antes, so saudacao).
- estagio_max: ponto MAIS FUNDO que a conversa alcancou (ordinal):
  saudacao_only < sondagem (perguntou intencao/dados, sem preco) < cotou (apresentou preco) < negociou (objecao/desconto/contraproposta apos cotar) < combinou (fechou logistica: horario E local/forma firmados) < prova_vinda (pix/foto de portaria/sinal concreto de que o cliente vem).
- objecoes: lista do que o CLIENTE levantou como barreira (use 'nenhuma' se nao houve; pode ter mais de uma). preco, horario (indisponivel/nao bate), local_distancia (longe/fora de area), risco_seguranca, golpe_desconfianca (medo de cair em golpe), indeciso (enrolou sem barreira concreta), outro.
- conduta_vendedor: tags da conduta do V que voce de fato observou (lista, pode ser vazia): cotacao_limpa (cotou o preco sem empurrao), empurrao_urgencia (criou urgencia colada ao preco), pergunta_colada (emendou pergunta no mesmo balao do preco), recusou_desconto, deu_desconto, ancora_horario (propos horario concreto), enviou_midia, desviou_preco (fugiu de dar o preco quando perguntado), reengajou (cutucou depois do silencio), tom_frio, tom_quente.
- tag_qualidade: ouro = conduta exemplar do V digna de virar referencia; anti_padrao = erro claro de conduta (empurrao, desviou do preco, frieza que afastou); neutro = comum, sem licao; ops_ruido = nao e venda (engano, spam, conversa fora do dominio).
- resumo_1linha: <=140 chars, o arco da thread em PT-BR ("cliente pede interno, V cota limpo, fecha horario" / "preco e some mudo").
- confianca: 0..1, o quanto a thread tinha sinal pra voce julgar (threads curtas/mudas = baixa).

DISCIPLINA: uma ficha por thread recebida, NAO pule nenhuma (mesmo as mudas: estagio_max=saudacao_only, tipo=indefinido, confianca baixa). Julgue SO pelo que esta no transcript - nao invente desfecho que o texto nao mostra. Seja rapido e consistente; isto e rotulagem em escala, nao ensaio.`

phase('Ficha')

const batches = Array.from({ length: N_BATCH }, (_, i) => i)
const fichasRaw = await parallel(
  batches.map((i) => () =>
    agent(fichaPrompt(i), { label: `ficha-b${i}`, phase: 'Ficha', schema: FICHA_SCHEMA, model: SONNET })
  )
)

const fichas = fichasRaw.filter(Boolean).flatMap((r) => r.fichas || [])
const ESPERADO = 1512
log(`Fichas: ${fichas.length}/${ESPERADO} (${(100 * fichas.length / ESPERADO).toFixed(1)}% cobertura), ${fichasRaw.filter(Boolean).length}/${N_BATCH} batches ok`)

// ---- distribuicoes (JS deterministico) ----
const tally = (arr) => arr.reduce((a, k) => ((a[k] = (a[k] || 0) + 1), a), {})
const sortDesc = (obj) => Object.entries(obj).sort((a, b) => b[1] - a[1])
const mdTabela = (titulo, obj, n) => {
  const linhas = sortDesc(obj).map(([k, v]) => `| ${k} | ${v} | ${(100 * v / n).toFixed(1)}% |`).join('\n')
  return `**${titulo}** (n=${n})\n\n| valor | n | % |\n|---|---|---|\n${linhas}`
}

const distTipo = tally(fichas.map((f) => f.tipo_atendimento))
const distEstagio = tally(fichas.map((f) => f.estagio_max))
const distQualidade = tally(fichas.map((f) => f.tag_qualidade))
const distObjecoes = tally(fichas.flatMap((f) => f.objecoes || []))
const distConduta = tally(fichas.flatMap((f) => f.conduta_vendedor || []))

// resgate dos tipo_atendimento_proxy nulos
const nulosProxy = fichas.filter((f) => !f.tipo_atendimento_proxy || f.tipo_atendimento_proxy === '(null)')
const resgate = tally(nulosProxy.map((f) => f.tipo_atendimento))

// cross-tab estagio_max x desfecho_proxy
const crosstab = {}
for (const f of fichas) {
  const d = f.desfecho_proxy || '(null)'
  crosstab[f.estagio_max] = crosstab[f.estagio_max] || {}
  crosstab[f.estagio_max][d] = (crosstab[f.estagio_max][d] || 0) + 1
}

// candidatos a exemplo-ouro e anti-padrao, agrupados por tipo de atendimento
const ouro = fichas.filter((f) => f.tag_qualidade === 'ouro' && (f.confianca || 0) >= 0.5)
const anti = fichas.filter((f) => f.tag_qualidade === 'anti_padrao' && (f.confianca || 0) >= 0.5)
const amostraOuro = ouro.slice(0, 40).map((f) => ({ instancia: f.instancia, remote_jid: f.remote_jid, tipo: f.tipo_atendimento, estagio: f.estagio_max, resumo: f.resumo_1linha }))
const amostraAnti = anti.slice(0, 25).map((f) => ({ instancia: f.instancia, remote_jid: f.remote_jid, tipo: f.tipo_atendimento, resumo: f.resumo_1linha }))

// ---- Consolidar os 6 relatorios .md num bloco unico ----
phase('Consolidar')

const consolidado = await agent(
  `Voce esta montando um ATLAS navegavel do corpus de vendas (para um assistente de codigo reutilizar). Varios achados ja foram minerados e estao DISPERSOS em relatorios .md soltos. Sua tarefa: ler e FUNDIR num unico bloco "O que ja sabemos do corpus", sem perder os numeros-chave.

Leia (Read) cada um destes arquivos em ${DIR}:
- README.md (eval set: cotacao/perda/judge/reengajamento — os numeros e o achado "reacao a cotacao = desfecho")
- mineracao_contrastiva.md (a unica alavanca de conduta com lift: ancora de horario)
- reengajamento.md (canned vs LLM, pergunta_leve melhor)
- score_v1.md (empurrao na cotacao ja limpo no v1)
- voz_estilometria.md (estilo: 0 em-dash, abertura social-leve)
- prompt_aderencia_falas.md e detector_features.md (se existirem; aderencia das falas instruidas vs corpus)

Escreva um markdown PT-BR conciso com:
1. "Camadas de dados existentes" — bullet curto por tabela/relatorio: o que cobre e quantas linhas.
2. "Achados consolidados" — agrupados por tema (desfecho, conduta na cotacao, desconto, reengajamento, estilo/voz), cada achado em 1-2 linhas com o NUMERO que o sustenta e a fonte (qual .md). Marque o que ja virou regra deployada vs o que e so achado.
3. "Limitacoes conhecidas do corpus" — chave @lid->telefone irrecuperavel (sem desfecho real/R$), judge de desfecho quase-acaso (kappa 0.07), ground-truth sem anotacao humana.

Devolva so o markdown (campo md). Nao invente numero que nao esteja nos arquivos; se um arquivo nao existir, ignore.`,
  { label: 'consolidar-relatorios', phase: 'Consolidar', schema: { type: 'object', properties: { md: { type: 'string' } }, required: ['md'] }, model: OPUS }
)

// ---- Navegar: validar exemplos-ouro + guia de navegacao ----
phase('Navegar')

const navegacao = await agent(
  `Voce esta escrevendo a secao "Como navegar o corpus" + "Exemplos-ouro" do ATLAS, para um assistente de codigo que vai consultar o corpus em tarefas futuras de eval/mineracao.

CONTEXTO — a nova camada de ficha por thread (em ${DIR}/fichas_threads.jsonl) tem por thread: tipo_atendimento, estagio_max (funil), objecoes[], conduta_vendedor[], tag_qualidade (ouro|anti_padrao|neutro|ops_ruido), resumo_1linha. As tabelas base sao corpus.threads (features deterministicas), corpus.turnos (transcript por turno, "V:"/"C:") e corpus.eval_* (labels LLM por fatia). Chave de toda thread = (instancia, remote_jid).

Candidatos a exemplo-OURO (ficha marcou ouro, confianca>=0.5):
${JSON.stringify(amostraOuro)}

Candidatos a ANTI-PADRAO:
${JSON.stringify(amostraAnti)}

PASSO 1 — Valide ~2 exemplos-ouro por tipo_atendimento (interno, externo, externo_pickup, remoto) e ~3 anti-padrao, puxando o transcript real (pg_execute_query; se faltar schema, ToolSearch "select:mcp__postgres__pg_execute_query"):
  SELECT 'T'||turno_idx||' '||(CASE WHEN from_me THEN 'V: ' ELSE 'C: ' END)||COALESCE(NULLIF(btrim(texto),''), CASE WHEN tem_midia THEN '[midia]' ELSE '[--]' END)
  FROM corpus.turnos WHERE instancia=$1 AND remote_jid=$2 AND turno_idx<=60 ORDER BY turno_idx
(parameters=[instancia, remote_jid]). Confirme que o transcript bate com o resumo; descarte o que nao bater.

PASSO 2 — Escreva markdown PT-BR (campo md) com:
1. "Como navegar" — receitas curtas de query: "quero N threads onde o cliente objetou preco e o V recusou desconto", "quero exemplos de cotacao limpa interna", etc. — mostrando o JOIN ficha<->turnos por (instancia, remote_jid) e como filtrar pela ficha. (A ficha esta no jsonl, nao no DB; explique o padrao: filtrar no jsonl, puxar transcript no turnos.)
2. "Exemplos-ouro por categoria" — uma tabela: categoria | instancia | remote_jid | por que e referencia. So os que voce validou no PASSO 1.
3. "Anti-padroes de referencia" — idem, os validados.

Seja cirurgico. Devolva so o md.`,
  { label: 'navegar-exemplos', phase: 'Navegar', schema: { type: 'object', properties: { md: { type: 'string' } }, required: ['md'] }, model: OPUS }
)

// ---- montar ATLAS.md (determinismo no JS) ----
const inventario = `## Inventario das tabelas \`corpus.*\` (read-only, Postgres prod self-hosted; ~2026-06-16)

Chave de toda thread = \`(instancia, remote_jid)\` — \`remote_jid\` e o **@lid** do WhatsApp, **nao** o telefone (ponte @lid->telefone irrecuperavel: sem desfecho real/R$).

| Tabela | Linhas | Grao | Conteudo |
|---|---|---|---|
| \`corpus.mensagens_raw\` | 71.335 | bolha (evento) | evento cru do webhook: from_me, push_name, message_type, ts, texto, raw jsonb |
| \`corpus.turnos\` | 29.054 | turno (bolhas agrupadas) | burst-merge ja feito: turno_idx, from_me, texto agregado, n_bolhas, tipos[], tem_midia |
| \`corpus.threads\` | 1.520 | thread (par cli-modelo) | ~30 features deterministicas: desfecho_proxy, tipo_atendimento_proxy, tem_valor/pix/local/saida, agenda_firme, objecao, negou, ghost_pos_cotacao, horas, thread_ops |
| \`corpus.eval_cotacao\` | 784 | thread c/ cotacao | reacao a cotacao (3 juizes Sonnet, voto maioria): reacao_real, label_bin GOOD/BAD |
| \`corpus.eval_perda\` | 580 | thread perdida | motivo de perda (enum CONTEXT) + declarado vs sumico mudo |
| \`corpus.eval_judge_pred\` | 775 | thread | predicoes do judge offline (calibracao; judge de desfecho e FRACO, kappa 0.07) |
| \`corpus.eval_reengajamento\` | 1.019 | poke | cutucadas reais: reviveu/gap/tem_midia + movimento multi-voto |
| **\`fichas_threads.jsonl\`** (local) | ~${fichas.length} | thread nao-ops | **NOVO** — ficha unificada LLM: tipo_atendimento refinado, estagio_max (funil), objecoes[], conduta_vendedor[], tag_qualidade, resumo_1linha |

Distribuicao por instancia: eb04 676 · eb02 541 · eb03 177 · eb01 126 (eb01 raso, eb04 rico). eb04 = hold-out cross-modelo.`

const distribuicoes = `## Distribuicoes da camada de ficha (n=${fichas.length})

${mdTabela('tipo_atendimento (refinado pela ficha)', distTipo, fichas.length)}

> **Resgate dos nulos:** o \`tipo_atendimento_proxy\` deterministico era nulo em ${nulosProxy.length} threads; a ficha classificou: ${sortDesc(resgate).map(([k, v]) => `${k} ${v}`).join(' · ')}.

${mdTabela('estagio_max (ponto mais fundo do funil)', distEstagio, fichas.length)}

${mdTabela('tag_qualidade', distQualidade, fichas.length)}

${mdTabela('objecoes do cliente (multi-rotulo)', distObjecoes, fichas.length)}

${mdTabela('conduta_vendedor (multi-rotulo)', distConduta, fichas.length)}

### Cross-tab estagio_max x desfecho_proxy
${(() => {
  const desfechos = [...new Set(fichas.map((f) => f.desfecho_proxy || '(null)'))]
  const ordem = ['saudacao_only', 'sondagem', 'cotou', 'negociou', 'combinou', 'prova_vinda']
  const head = `| estagio \\\\ desfecho | ${desfechos.join(' | ')} |`
  const sep = `|---|${desfechos.map(() => '---').join('|')}|`
  const linhas = ordem.filter((e) => crosstab[e]).map((e) => `| ${e} | ${desfechos.map((d) => crosstab[e][d] || 0).join(' | ')} |`)
  return [head, sep, ...linhas].join('\n')
})()}`

const atlas_md = `# ATLAS do corpus do Vendedor (Elite Baby)

> Indice navegavel do corpus real de vendas (eb01-04). Gerado por \`wf_atlas_corpus.js\` (workflow Claude Code, moeda abundante; read-only sobre \`corpus.*\`, sem escrita em prod). Atualizado ~2026-06-16.
> **Para que serve:** dar ao assistente de codigo dominio sobre o que existe no corpus sem redescobrir na unha a cada tarefa. A ficha por thread vive em \`fichas_threads.jsonl\` (mesma pasta).

${inventario}

${distribuicoes}

${consolidado?.md || '_(consolidacao dos relatorios indisponivel — agente falhou)_'}

${navegacao?.md || '_(guia de navegacao indisponivel — agente falhou)_'}

---
_Camada de ficha: ${fichas.length}/${ESPERADO} threads nao-ops cobertas. Labels LLM (Sonnet) sem anotacao humana — use como aux de navegacao, nao como ground-truth fechado._
`

return {
  cobertura: `${fichas.length}/${ESPERADO}`,
  batches_ok: `${fichasRaw.filter(Boolean).length}/${N_BATCH}`,
  fichas,
  atlas_md,
  distribuicoes: { distTipo, distEstagio, distQualidade, distObjecoes, distConduta, resgate },
}
