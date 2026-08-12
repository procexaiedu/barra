# 12 · Observabilidade: o trace do turno no Langfuse

> Para quem investiga o agente pelo trace — inclusive o Claude Code, via MCP `langfuse-traces`
> (o processo de investigação é a skill `/investigar-trace`; este doc é o dicionário que ela consulta).
> Complementa o ADR 0019 (por que self-hosted, sem masking) com **o que existe no trace hoje e
> como perguntar**. Instrumentação: `core/tracing.py`, `agente/_texto_turno.py`,
> `agente/_versao.py`, `workers/coordenador.py`, `evals/harness.py`.

## 1. Um turno = um trace

O turno é a unidade. O coordenador (`workers/coordenador.py`) abre um span raiz chamado `turno`
com **trace-id determinístico** (`create_trace_id(seed=turno_id)`) e roda o grafo dentro dele — por
isso o mesmo turno nunca vira dois traces, e o score online consegue voltar e se ancorar nele
depois.

O trace nasce autossuficiente: dá para entender o caso **sem abrir uma única observation**.

| Campo do trace | Conteúdo |
|---|---|
| `name` | `turno` (prod) · `turno_eval_gate` / `turno_e2e` / `turno_funil` (rigs) |
| `session_id` | `atendimento_id` — agrupa a negociação inteira em ordem |
| `user_id` | `cliente_id` (UUID opaco, nunca o telefone) |
| `input` | as bolhas do CLIENTE que dispararam o turno |
| `output.resposta_ia` | o que foi despachado (pós output-guard e chunking) |
| `output.desfecho` | mecânica: extração, `erros_tool`, reoferta, disclosure, `horario_minimo` |
| `output.raciocinio` | **o thinking**: o `reasoning_content` de cada passagem do chat #1 |
| `level` | `WARNING` quando houve erro de tool no turno |
| `environment` | `producao` · `desenvolvimento` · `teste` |
| `service.name` | `barra-worker` (o agente) · `barra-api` · `barra-evals` (rigs) |

## 2. O raciocínio (thinking) no trace

Desde **11/08/2026** o chat #1 roda `reasoning_effort=low` em prod
(`settings.deepseek_thinking_chat`, revertível por Env sem deploy). O `reasoning_content` **não é
extraído pelo wrapper langchain-openai** — quem o captura é `_ChatDeepSeekThinking`
(`core/llm.py`), que o guarda em `additional_kwargs` e o devolve ao provider nas assistant com
tool_calls (senão HTTP 400).

`raciocinio_do_turno()` promove esse campo ao `output` do trace: você lê **a fala e o que a IA
pensou antes de escrevê-la na mesma tela**. Uma entrada por passagem do LLM (o loop ReAct chama de
novo depois de cada tool; a regen do guard acrescenta a sua).

Duas coisas que o raciocínio **não** é:
- não é o que vai ao cliente (`extrair_texto_do_turno` lê `content`, nunca este campo);
- não é sinal de vazamento — raciocínio *dentro do texto da bolha* é outro problema, tratado pelo
  Estágio 0 do `output_guard` e pelo score `online_system_leak`.

## 3. Tags: o vocabulário para ACHAR casos

Tags de **escopo** (você já sabe o caso e quer segui-lo):
`modelo_id:<uuid>` · `atendimento_id:<uuid>` · `cliente_id:<uuid>`

Tags de **regime** (`agente/_versao.py:regime_do_turno`) — sob qual conduta o turno rodou:
`modelo_llm:deepseek-v4-flash` · `thinking:low|disabled|high|max` · `prompts:<hash12>`

> `prompts:` é o hash do conteúdo de `agente/prompts/`. É o que separa "antes" de "depois" de uma
> edição de prompt: dois traces com hashes diferentes rodaram condutas diferentes, mesmo que o
> commit seja o mesmo. Muda quando o worker recarrega (o hash é cacheado por processo).

Tags de **desfecho** (`agente/_texto_turno.py:tags_do_turno`) — o que aconteceu:

| Tag | Significa |
|---|---|
| `intencao:<valor>` | a leitura da negociação (`cotacao`, `agendamento`, …) |
| `sem_extracao` | o turno não registrou extração |
| `sem_resposta` | **turno mudo**: nada saiu para o cliente |
| `erro_tool` | tool devolveu erro recuperável (ex.: `ERRO: horario cedo demais`) |
| `reoferta` | a auto-reoferta entrou |
| `disclosure:<categoria>` | o intercept classificou a fala do cliente |

Tags de **origem** nos rigs: `eval_gate` · `e2e` · `funil`.

## 4. Observations: quem é quem dentro do turno

Os nós do grafo aparecem com o próprio nome (`prepare_context`, `intercept_disclosure`, `llm`,
`tools`, `extrair`, `output_guard`, `post_process`). As chamadas de LLM (`GENERATION`) são
nomeadas — antes eram todas `ChatOpenAI`:

| Nome | O que é |
|---|---|
| `chat_fala` | o chat #1: a fala ao cliente (é aqui que o thinking acontece) |
| `chat_fecha_em_texto` | fecha-em-texto do cap de mídia (`tool_choice="none"`) |
| `extracao_forcada` | extração #2 no prefixo cheio |
| `extracao_forcada_barata` | extração #2 com system mínimo (`extracao_no_modelo_barato`) |
| `guard_regen` | regeneração da fala pelo output_guard |

Duas ausências **de propósito**: o judge de AUP corta callbacks (seriam ~8 spans de ruído antes de
cada bolha; os tokens dele seguem no Prometheus), e o Pix/STT rodam fora do grafo.

Quando a extração paralela está ligada, a generation dela pendura sob o nó `llm` (herda os
contextvars do disparo), não sob o `extrair`.

## 5. Scores

| Score | Origem |
|---|---|
| `online_formato_bolha`, `online_segredo_agendamento`, `online_system_leak`, `online_non_disclosure` | invariantes determinísticos por turno (EVAL-11) |
| `e2e_conduziu`, `e2e_sem_violacoes` | veredito do rig e2e no último turno do cenário |
| agregados (ex.: JSD do sensor de fluxo) | trace sintético por `(nome, janela)` — série temporal, não turno |

## 6. Receitas (MCP `langfuse-traces`)

```
# turnos mudos das últimas 24h
fetch_traces(age=1440, tags="sem_resposta")

# a negociação inteira, em ordem
fetch_traces(age=10080, session_id="<atendimento_id>")

# só o que rodou com a árvore de prompts de hoje
fetch_traces(age=1440, tags="prompts:ab12cd34ef56")

# comparar regimes num grid A/B
fetch_traces(age=1440, tags="funil,thinking:low")

# o turno inteiro, com raciocínio e prompts montados
fetch_trace(trace_id="<id>", include_observations=True, output_mode="full_json_file")

# só as falas do chat #1 (sem o resto do grafo)
fetch_observations(age=1440, type="GENERATION", name="chat_fala")

# onde os invariantes reprovaram
list_scores_v2(name="online_system_leak", value=0)
```

Filtros combinam por AND numa lista de tags. `output_mode="full_json_file"` evita despejar um trace
inteiro no contexto — ele salva em arquivo e devolve o caminho.

## 7. Limites (o que o trace NÃO responde)

- **`total_cost` é espelho, não contabilidade.** O endpoint de modelos do Langfuse não aceita preço
  por usage-type custom, então o `input_cache_read` do DeepSeek fica não-precificado. O custo BRL
  preciso vive no Prometheus e em `atendimentos.custo_ia_brl` (`agente/_custo.calcular_custo_brl`).
- **Ambiente `teste` é no-op por padrão.** A suíte não emite trace (era assim que nasciam os traces
  sem nome e o trace-monstro do `e2e/massa`); rigs pedem `permitir_em_teste=True`.
- **PII sem masking, por decisão (ADR 0019).** O Langfuse está no mesmo perímetro do banco; a
  proteção é controle de acesso. Não reexporte conteúdo de trace para fora desse perímetro.
- **O modelo não fixa snapshot.** `deepseek-v4-flash` muda de peso sem deploy nosso — deriva de
  conduta se mede por eval, não por diff.

## 8. Onde mexer

| Quero… | Arquivo |
|---|---|
| nova tag de desfecho | `agente/_texto_turno.py:tags_do_turno` |
| novo campo no resumo do trace | `core/tracing.py:resumir_trace_turno` |
| novo eixo de regime | `agente/_versao.py:regime_do_turno` |
| nomear uma nova chamada de LLM | `core/llm.py:nomear_run` no ponto de invocação |
| ligar/desligar thinking | Env `DEEPSEEK_THINKING_CHAT` (`disabled` volta ao regime non-thinking) |
| carimbar a versão do código | Env `LANGFUSE_RELEASE` (lido pelo SDK) |
