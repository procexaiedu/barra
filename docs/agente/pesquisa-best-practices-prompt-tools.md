# Pesquisa — Best practices de prompt/context engineering e design de tools (Claude Sonnet 4.6)

> **Data:** 2026-05-28 · **Escopo:** agente conversacional LangGraph do Barra Vips (`api/src/barra/agente/`), calibrado para **Claude Sonnet 4.6** via **API Anthropic** (chat) + `langchain-anthropic` 1.x.
> **Natureza:** pesquisa e destilação — **não altera prompt, tool nem código**. Confronta as recomendações oficiais atuais da Anthropic com o estado real do agente e separa (a) o que já seguimos, citando arquivo, de (b) lacunas, cada uma com proposta concreta apontando arquivo/trecho.
> **Como ler:** cada linha das tabelas termina em **"já fazemos — ver `<arquivo>`"** ou **"lacuna → `<mudança concreta>`"**. Status: ✅ já fazemos · 🟡 parcial · 🔴 lacuna.

## Método e fontes

Quatro frentes de pesquisa (3 sobre a doc oficial Anthropic, 1 destilando os docs de design internos) + leitura integral dos prompts vivos e da implementação. As URLs oficiais resolvem em `platform.claude.com` (o antigo `docs.anthropic.com`/`docs.claude.com` redireciona para lá). Fontes oficiais citadas ao longo do doc:

| Tag | Fonte oficial |
|---|---|
| **PBP** | Prompting best practices — `https://platform.claude.com/docs/en/docs/build-with-claude/prompt-engineering/claude-4-best-practices` |
| **CTX** | Effective context engineering for AI agents — `https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents` |
| **EFF** | Effort — `https://platform.claude.com/docs/en/build-with-claude/effort` |
| **ADP** | Adaptive thinking — `https://platform.claude.com/docs/en/build-with-claude/adaptive-thinking` |
| **EXT** | Extended thinking — `https://platform.claude.com/docs/en/build-with-claude/extended-thinking` |
| **CACHE** | Prompt caching — `https://platform.claude.com/docs/en/build-with-claude/prompt-caching` |
| **PRICE** | Pricing — `https://platform.claude.com/docs/en/about-claude/pricing` |
| **CHAR** | Keep Claude in character — `https://platform.claude.com/docs/en/test-and-evaluate/strengthen-guardrails/keep-claude-in-character` |
| **WTOOL** | Writing effective tools for AI agents — `https://www.anthropic.com/engineering/writing-tools-for-agents` |
| **DTOOL** | Define tools (implement tool use) — `https://platform.claude.com/docs/en/docs/agents-and-tools/tool-use/implement-tool-use` |
| **HTOOL** | Handle tool calls (`is_error`, `tool_result`) — `https://platform.claude.com/docs/en/agents-and-tools/tool-use/handle-tool-calls` |
| **PAR** | Parallel tool use — `https://platform.claude.com/docs/en/agents-and-tools/tool-use/parallel-tool-use` |
| **STRICT** | Strict tool use — `https://platform.claude.com/docs/en/agents-and-tools/tool-use/strict-tool-use` |
| **SO** | Structured outputs — `https://platform.claude.com/docs/en/build-with-claude/structured-outputs` |
| **TREF** | Tool reference (`input_examples`, `defer_loading`) — `https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-reference` |
| **TSEARCH** | Tool search tool (catálogos grandes) — `https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-search-tool` |

**Veredito geral:** o agente está **muito alinhado** com as práticas oficiais — em vários pontos a implementação é exemplar (consolidação de tools, `enviar_midia(tag)` mantendo UUID fora do LLM, guarda de privacidade em schema, reminder no user turn, prefixo de cache global byte-idêntico). As lacunas reais são poucas e concentradas: **strict tool use desligado**, **effort não testado no loop de tools**, **pré-aquecimento de cache não implementado**, **`input_examples` ausentes** e **deriva doc↔código** (os docs subestimam o que o código já faz).

---

## Status de execução (2026-05-28)

Após a pesquisa, nesta sessão foram implementados e verificados (escolha: "docs + strict/examples no escalar"):

- ✅ **Strict tool use no `escalar`** (per-tool, §2.6): `STRICT_TOOLS={"escalar"}` em `ferramentas/__init__.py`; `build_tools_para_bind` aplica strict por nome; `_sanitizar_para_strict` passou a remover `min/maxLength` e `min/maxItems` (era o blocker). **Validado contra a API real** (200 OK, sem 400). `settings.anthropic_strict_tools` default → `True` (kill-switch mantido).
- ✅ **`input_examples` no `escalar`** (§2.2): `INPUT_EXAMPLES` em `ferramentas/__init__.py`, injetado por `build_tools_para_bind`; passthrough confirmado no `langchain-anthropic` 1.4.3 (`AnthropicTool` reconhece o campo).
- ✅ **Reconciliação de docs** (§3): corrigidos `00-indice` (4 breakpoints), `01 §2.1` (8→5 tools), `03 §4.4` (BP_JANELA shipado), `03` (`persona.md.j2`→`persona.md`), `10 §5.1` (reminder proativo). Restam os samples de código de `03 §4.1`/`§5` (FAQ fundida) e `06` (vision OpenRouter).
- ✅ **Verificação**: 118 testes do agente verdes + 8 skips de DB, `mypy src` limpo, snapshot de tools regenerado.

Itens **não** feitos (dependem de tráfego/medição ou decisão de produto): pré-aquecimento de cache (§4 #1), A/B de effort (§4 #2), poda de few-shot (§1.2), flatten do `payload` (§2.3), adaptive thinking (§1.4).

---

## 1. Prompt / context engineering

### 1.1 Estrutura do prompt, role e tags XML

| Prática recomendada | Fonte | Status no Barra | Proposta |
|---|---|---|---|
| Delimitar tipos de conteúdo (instruções, contexto, exemplos, input) com **tags XML** semânticas e consistentes | PBP (§ Structure prompts with XML tags); CTX | ✅ **já fazemos** — `prompts/persona.md` (`<persona>`,`<voz>`,`<exemplos>`,`<armadilhas_de_voz>`) e `prompts/regras.md.j2` (`<conduta>`,`<cotacao>`,`<recusa_de_pratica>`,`<protocolo_*>`,`<quando_usar_escalar>`) são todos tag-delimitados; registrado em `03-prompts.md §2.2` | nenhuma — ok |
| **Conteúdo estável no topo, volátil/variável no fim** ("stable first, volatile last"); query/contexto por-request depois do prefixo | PBP (§ Long context); CACHE | ✅ **já fazemos** — prefixo `system` estável (`build_system_messages` em `agente/llm.py`) + contexto dinâmico e reminder concatenados **no último `HumanMessage`** (`nos/prepare_context.py:_anexar_contexto_dinamico`, `:_injetar_reminder_se_necessario`), nunca em `SystemMessage` | nenhuma — ok |
| **Role no system prompt** define tom/comportamento; detalhar personalidade e traços | PBP (§ Give Claude a role); CHAR | ✅ **já fazemos** — `persona.md` `<identidade>` + `<voz>` definem a persona geral; identidade por-modelo em `identidade.md.j2` (BP_MODELO) | nenhuma — ok |
| "Right altitude": **mínimo conjunto de informação que especifica o comportamento**; nem lógica frágil hardcoded, nem vago | CTX | ✅ **já fazemos** — contexto dinâmico curado (`contexto_dinamico.md.j2`): `pix_status` humanizado (`_PIX_STATUS_HUMANO`), histórico resumido (`_resumir_historico` → "fechou 2x (R$1.2k)"), enums traduzidos — não despeja schema cru ao LLM | nenhuma — ok |
| Migração 4.6: **sem prefill no último turno assistant** (retorna 400); injetar lembretes/continuação **no user turn** | PBP (§ Migrating away from prefilled responses) | ✅ **já fazemos** — não usamos prefill; o `<lembrete_silencioso>` é injetado no último `HumanMessage` (`nos/prepare_context.py:_injetar_reminder_se_necessario`), exatamente o padrão recomendado para 4.6 | nenhuma — ok |

### 1.2 Few-shot / exemplos

| Prática recomendada | Fonte | Status no Barra | Proposta |
|---|---|---|---|
| Exemplos são a alavanca mais confiável para tom/formato; few-shot domina sobre adjetivos | PBP (§ Use examples effectively) | ✅ **já fazemos** — persona ensina o tom por demonstração, não por adjetivo (decisão `03-prompts.md §2.2`; "4 atributos inegociáveis demonstrados nos exemplos") | nenhuma — ok |
| Exemplos **relevantes, diversos e estruturados** (`<example>`/`<examples>`), cobrindo edge cases reais | PBP; CTX | ✅ **já fazemos** — `<exemplos>` da `persona.md` e os `<exemplo_*>` dos protocolos em `regras.md.j2` cobrem abertura, EN, cotação, recusa em camadas, dupla, atraso, disclosure; derivados de `docs/agente/conversas-reais/` | nenhuma — ok |
| **3–5 exemplos** dão o melhor resultado; **não "empilhar lista de edge cases"** no prompt | PBP ("Include 3–5 examples for best results"); CTX ("curate diverse, canonical examples", anti-padrão "stuff a laundry list of edge cases") | 🟡 **parcial** — a `persona.md` viva cresceu para ~11 `<exemplo>` em `<exemplos>` + ~14 pares em `<armadilhas_de_voz>`, e `regras.md.j2` soma ~15+ exemplos nos protocolos; `03-prompts.md §2.2` ainda manda "manter 4-6 exemplos" (drift). Tudo no prefixo **global sempre-quente** (barato via cache), mas há risco de o modelo captar padrão não-intencional | lacuna → rodar uma **poda guiada por eval** (`08-evals.md`): confirmar via rubrica `persona`/`coerencia_multiturno` que cada exemplo "ganha seu lugar" e que nenhum induz padrão indevido; remover os redundantes de `persona.md`/`regras.md.j2` e reconciliar a contagem em `03-prompts.md §2.2` |
| Exemplos positivos ("como comunicar") **superam** instruções negativas para verbosidade/estilo | PBP (§ Response length and verbosity) | ✅ **já fazemos** — `<armadilhas_de_voz>` usa pares `<errado>`/`<certo>` (mostra o certo, não só proíbe); few-shot demonstram brevidade | nenhuma — ok |

### 1.3 Instruction-following literal do 4.6

| Prática recomendada | Fonte | Status no Barra | Proposta |
|---|---|---|---|
| 4.x segue instruções **literalmente**; declarar escopo explicitamente; não conta com generalização silenciosa | PBP (§ More literal instruction following) | ✅ **já fazemos** — regras escritas em escopo explícito (ex.: `<trava_de_escopo>` "só puxe o assunto se o cliente perguntou antes"; `<revelacao_de_endereco>` define cada camada) | nenhuma — ok |
| **Dizer o que fazer, não o que não fazer**; suavizar linguagem forçada (`CRITICAL`/`MUST`/`NUNCA`) que faz 4.6 over-triggar | PBP (§ Control format; § Tool usage) | 🟡 **parcial** — a decisão está registrada (`03-prompts.md §3.1`, `§9`: "CRITICAL/NUNCA/PARE causa overtrigger") e a maior parte do texto é positiva; ainda restam `**Nunca**`/`**sempre**` em pontos de regra dura (`regras.md.j2` `<revelacao_de_endereco>`, `<pix_externo>`) — alguns são regra de negócio inegociável | lacuna → revisar os `**Nunca**`/`**sempre**` remanescentes em `regras.md.j2`: onde for regra dura legítima, manter; onde for ênfase, reescrever em forma positiva (ex.: "Revele o AP só quando o cliente avisar que está chegando" em vez de "**Nunca** dê o AP antes") |
| **Explicar o porquê** das instruções ("add context/motivation") melhora a aderência | PBP (§ Add context to improve performance) | ✅ **já fazemos** — e muito bem: blocos `**Por quê:**` por toda `regras.md.j2` (`<cotacao>`, `<revelacao_de_endereco>`, `<trava_de_escopo>`, `<indisponibilidade>`, `<periodo_de_trabalho>`) e na `persona.md` | nenhuma — ok |
| Para querer **ação** (não sugestão), ser explícito | PBP (§ Tool usage) | ✅ **já fazemos** — `<quando_usar_escalar>` e as descrições de tool instruem ação direta ("Use a tool `escalar`…", "chame `registrar_extracao` uma vez por turno") | nenhuma — ok |

### 1.4 Effort e thinking (Sonnet 4.6)

| Prática recomendada | Fonte | Status no Barra | Proposta |
|---|---|---|---|
| **Setar `effort` explicitamente** — default do Sonnet 4.6 é `high`; não setar causa "unexpected latency" | EFF (§ Recommended effort levels for Sonnet 4.6); PBP (§ Migrating 4.5→4.6) | ✅ **já fazemos** — `settings.anthropic_effort="low"` passado em `core/llm.py:criar_chat_anthropic` (`effort=`); decisão e justificativa em `03-prompts.md §6.1`/`§6.2` | nenhuma — ok |
| Para **chat/baixa latência**, a recomendação oficial é `effort: "low"` | EFF ("Low effort: …chat and non-coding use cases where faster turnaround is prioritized") | ✅ **já fazemos** — `effort="low"` + `thinking=disabled` = setup oficial de menor latência, correto para a resposta ao cliente no WhatsApp | nenhuma — ok |
| Para **fluxos com tools** ("tool-heavy workflows"), a recomendação é `effort: "medium"` | EFF (§ Recommended; "Medium … tool-heavy workflows") | 🟡 **parcial** — o agente roda um **loop ReAct** com `registrar_extracao` (esperado todo turno), `escalar`, `pedir_pix_deslocamento`, `enviar_midia`. `effort=low` enviesa o modelo a **menos tool calls / ação direta sem preâmbulo** (EFF § Effort with tool use) — risco real de **pular `registrar_extracao`** ou subaproveitar a extração | lacuna → A/B no harness de evals (`08-evals.md`): rodar o corpus com `effort=medium` só no nó `llm` e comparar a rubrica `tool_use_correto` + `instruction_following` + custo/latência vs `low`. `settings.anthropic_effort` já é o knob; decidir por dado |
| `effort` vai em `output_config.effort` no raw SDK; no `langchain-anthropic` 1.x é **kwarg direto** `effort=` | EFF; `03-prompts.md §6.2` (validado empírico 2026-05-24) | ✅ **já fazemos** — `core/llm.py` usa `effort=settings.anthropic_effort`; reconfirmar a cada bump de `langchain-anthropic` | nenhuma — ok (revalidar no upgrade) |
| **Adaptive thinking** (`thinking:{type:"adaptive"}`) é o modo recomendado no 4.6; `budget_tokens` está **deprecated**; adaptive auto-liga **interleaved thinking** entre tool calls | ADP; EXT | 🟡 **parcial (decisão deliberada)** — usamos `thinking={"type":"disabled"}` (`settings.anthropic_thinking`), escolha consciente de latência (`03-prompts.md §6.2.1`, sem effort hibridizado). Não usamos `budget_tokens` (bom — já estaria deprecated) | lacuna → **experimento opcional**: testar `thinking=adaptive` + `effort=low` no nó `llm` (adaptive pula raciocínio em turnos simples e pensa nos multi-step de tool) e medir corretude de extração/escalada vs latência no `08-evals.md`. Manter `disabled` se o ganho não pagar a latência — registrar o resultado em `03-prompts.md §6.2.1` |
| **Não alternar modos de thinking** (adaptive↔enabled↔disabled) na mesma conversa — quebra o cache de `messages` (system/tools sobrevivem) | ADP (§ Prompt caching); CACHE | ✅ **já fazemos** — `thinking` é fixo (`disabled`) por config, nunca alternado por turno | nenhuma — ok (manter como restrição se adotar adaptive: escolher um modo e fixar) |
| `max_tokens` é teto rígido de custo; vigiar `stop_reason:"max_tokens"` | ADP (§ Cost control); EXT | ✅ **já fazemos** — `anthropic_max_tokens=1024` como guard-rail; `nos/llm.py` observa `stop_reason=="max_tokens"` via métrica `TURNO_TRUNCADO` | nenhuma — ok |
| `display:"omitted"` no thinking reduz time-to-first-token quando o raciocínio não é mostrado | ADP | ➖ **N/A hoje** (thinking disabled) | se adotar adaptive thinking (item acima), ligar `display:"omitted"` — o agente nunca mostra raciocínio ao cliente, então corta latência sem mudar qualidade |

### 1.5 Context engineering para agentes

| Prática recomendada | Fonte | Status no Barra | Proposta |
|---|---|---|---|
| Contexto é **recurso finito** (context rot / attention budget); buscar o menor conjunto de tokens de alto sinal | CTX | ✅ **já fazemos** — janela deslizante de 20 (`nos/prepare_context.py:carregar_mensagens`), fatos duráveis re-injetados via snapshot de `registrar_extracao` em vez de manter todo o histórico (`02-estado-fluxo.md §4`) | nenhuma — ok |
| **Just-in-time retrieval** vs pré-carregar tudo; manter identificadores leves e buscar sob demanda | CTX | ✅ **já fazemos** — as próximas 48h vão no contexto; janelas além disso só via tool `consultar_agenda` (`ferramentas/leitura.py`), híbrido recomendado (pré-carrega o quente, busca o resto) | nenhuma — ok |
| Curadoria de tool results compactos e token-efficient | CTX; WTOOL | ✅ **já fazemos** — `consultar_agenda` devolve markdown enxuto; tools de escrita devolvem string curta | nenhuma — ok (ver §2.4) |
| Sem checkpointer/estado gordo no P0; estado vive na fonte (Postgres), prompt remontado do zero | CTX (state management) | ✅ **já fazemos** — `build_graph()` sem checkpointer (`graph.py`), `EstadoAgente` minimalista (`estado.py`), deps via Runtime Context API (`contexto.py`) — alinhado a `agente/CLAUDE.md` | nenhuma — ok |
| Isolamento de contexto por escopo (não vazar contexto entre domínios) | CTX | ✅ **já fazemos** — isolamento por par `(cliente_id, modelo_id)` em toda carga de janela/histórico (`carregar_mensagens`, `_resolver_variaveis`, `_resumir_historico`) — invariante de `agente/CLAUDE.md` | nenhuma — ok |

### 1.6 Steering de formato / verbosidade de saída

| Prática recomendada | Fonte | Status no Barra | Proposta |
|---|---|---|---|
| **Casar o estilo do prompt com a saída desejada** (ex.: tirar markdown do prompt reduz markdown na saída) | PBP (§ Match your prompt style) | ✅ **já fazemos** — prompts em prosa/WhatsApp; `<armadilhas_de_voz>` bane bullets/markdown/`código`; few-shot são bolhas curtas em minúsculo | nenhuma — ok |
| 4.6 é mais conciso e pode **pular resumo pós-tool**; pedir explicitamente se quiser | PBP (§ Communication style) | ✅ **já fazemos por design** — não queremos resumo pós-tool ao cliente: `<tools_disponiveis>` instrui "responda em personagem como se já soubesse; tool é interna ao seu raciocínio" | nenhuma — ok |
| Controlar verbosidade via persona/few-shot, **não** via `max_tokens` (que trunca) | PBP; `03-prompts.md §6.1` | ✅ **já fazemos** — brevidade vem da persona ("1-3 bolhas, espelhe a brevidade do cliente"); `max_tokens=1024` é só guard-rail | nenhuma — ok |
| Sem `temperature`/`top_p`/`top_k`; variabilidade vem dos exemplos | PBP; `03-prompts.md §6.4` | ✅ **já fazemos** — `criar_chat_anthropic` não seta temperatura; variação de abertura está nos few-shot (`<voz>` "nunca abra duas conversas iguais") | nenhuma — ok |

### 1.7 Prompt caching

| Prática recomendada | Fonte | Status no Barra | Proposta |
|---|---|---|---|
| Ordem do prefixo **`tools → system → messages`**; cada nível é segmento independente | CACHE | ✅ **já fazemos** — render nessa ordem; `agente/CLAUDE.md` e `03-prompts.md §1` documentam | nenhuma — ok |
| **Cache de tools é segmento próprio**: pôr `cache_control` na **última tool** (não retroage do `system`) | CACHE; DTOOL | ✅ **já fazemos** — `agente/llm.py:build_tools_para_bind` marca a última tool (`escalar`) | nenhuma — ok |
| Até **4 breakpoints**; pôr o breakpoint no último bloco que **não** muda | CACHE | ✅ **já fazemos — e os 4 estão ativos**: BP_TOOLS (`build_tools_para_bind`) → BP_GERAL persona+regras+FAQ fundidos (`persona.py:render_prefixo_geral` num único `SystemMessage`) → BP_MODELO (`build_system_messages` 2º bloco) → BP_JANELA (`marcar_cache_na_penultima`, chamado em `nos/prepare_context.py:114`). ⚠️ **`03-prompts.md §4.4` está defasado** (diz "BP4/cauda adiado P1"); o `agente/CLAUDE.md` e o código já operam os 4 | lacuna **(doc)** → atualizar `03-prompts.md §1`/`§4.4`/`§5` para refletir os 4 breakpoints ativos e a fusão do BP_GERAL (ver §3 deste doc) |
| **Mínimo cacheável: 1.024 tokens no Sonnet 4.6**, sobre o prefixo cumulativo; abaixo disso não cacheia (silencioso) | CACHE | ✅ **já fazemos** — registrado em `03-prompts.md §1`; prefixo geral ~3-5K passa o mínimo com folga | nenhuma — ok |
| TTL: 5m (default, write **1,25×**, refresh grátis) vs 1h (write **2×**); read = **0,1×**; 1h paga após **2 reads** | CACHE; PRICE | ✅ **já fazemos com escolha consciente** — `cache_ttl_geral=cache_ttl_modelo="1h"` no piloto esparso (gaps > 5min entre conversas reescreveriam o 5m); análise completa em `03-prompts.md §1`. Regra "TTL mais longo antes do mais curto" validada em `build_system_messages` | nenhuma — ok (rever para 5m no scale, quando o prefixo global ficar sempre-quente — já previsto em `03 §1`) |
| Medir cache por `cache_read_input_tokens`/`cache_creation_input_tokens`; **reads dominando writes** = saúde (não há número oficial de write-rate) | CACHE | ✅ **já fazemos** — `nos/llm.py:_instrumentar_tokens` lê write de `ephemeral_5m+ephemeral_1h` (nunca de `cache_creation`, que vem 0 no langchain 1.4.3) e read de `cache_read`; tripwire de write-rate em `08-evals.md §3.1` (gate ≤10-15%) | nenhuma — ok |
| **Anti-padrão**: `cache_control` no bloco com timestamp/contexto/mensagem do cliente → write a cada request, zero read | CACHE | ✅ **já evitamos** — o último `HumanMessage` (contexto dinâmico + reminder) **nunca** leva `cache_control` (`nos/prepare_context.py`); breakpoint da janela é na **penúltima** (`marcar_cache_na_penultima`) | nenhuma — ok |
| Ordem de chaves estável no JSON dos blocos `tool_use` (Swift/Go embaralham e quebram cache) | CACHE | ✅ **não afeta o P0** — a janela cacheada (BP_JANELA) é remontada da tabela `mensagens` como texto puro (Human/AI), sem blocos `tool_use`/`tool_result` (esses vivem em `tool_calls`, fora da janela). Guard-rail de byte-identidade em `agente/CLAUDE.md` | nenhuma — ok (atenção se o BP4 do P1 passar a cachear `tool_result`) |
| **Pré-aquecer** o prefixo estável com `max_tokens:0` antes do tráfego (deploy/startup) | CACHE; `03-prompts.md §4.5` | 🔴 **lacuna (já desenhado, não implementado)** — o prefixo global (`tools`+BP_GERAL, ~3-5K) é compartilhado por todas as modelos; após deploy de `persona.md`/`regras.md.j2`/`faq.md` ou gap > TTL, um burst de conversas paralelas **reescreve o mesmo prefixo N vezes** a 2× | lacuna → implementar um disparo `max_tokens:0` com `cache_control` no fim do prefixo global no **deploy de prompt** e/ou startup do worker (compatível: thinking disabled, `tool_choice=auto`, sem structured outputs, sem stream — confirmado por CACHE). Local natural: hook de deploy + `barra.workers`/coordenador (`07-coordenador.md §2`) |
| Isolamento de cache é **por workspace** (desde 2026-02-05) | CACHE; `03-prompts.md §4.5` | ✅ **já anotado** — garantir prod num único workspace para o prefixo global valer entre modelos | nenhuma — ok (verificação operacional, não de código) |

---

## 2. Design de tools

Catálogo P0 (5 tools, `ferramentas/__init__.py`): `consultar_agenda` (leitura) · `registrar_extracao` · `pedir_pix_deslocamento` · `enviar_midia` · `escalar` (escrita).

### 2.1 Granularidade do catálogo

| Prática recomendada | Fonte | Status no Barra | Proposta |
|---|---|---|---|
| **"Fewer, more thoughtful tools"**: mais tools não é melhor; consolidar relacionadas; evitar sobreposição | WTOOL; DTOOL; CTX | ✅ **já fazemos** — catálogo de **5** tools; consolidações registradas em `04-tools.md §1`/`§2.2`: removidas `consultar_cliente`/`consultar_faq`/`consultar_pix_status` (dados foram para o contexto/BP) e `consultar_midia` colapsada em `enviar_midia(tag)` | nenhuma — ok |
| Cada tool com **propósito claro e distinto**; um humano deve saber qual usar | WTOOL; CTX | ✅ **já fazemos** — as 5 tools não se sobrepõem; leitura única (`consultar_agenda`) só para além das 48h | nenhuma — ok |
| Consolidar ações relacionadas numa tool com parâmetro de modo, em vez de 1 tool por ação | DTOOL; WTOOL | ✅ **já fazemos** — `enviar_midia(tag, tipo)` cobre foto/vídeo e todas as tags numa só tool (`ferramentas/midia.py`), em vez de uma tool por tipo de mídia | nenhuma — ok |
| Catálogos grandes degradam seleção (>30–50 tools) → considerar tool search / `defer_loading` | TSEARCH; TREF | ✅ **N/A favorável** — 5 tools, muito abaixo do limiar; tool search e `defer_loading` desnecessários | nenhuma — ok |
| Namespacing por prefixo quando há muitas tools | WTOOL; DTOOL | ➖ **não necessário** — 5 tools, nomes de domínio claros (PT-BR) | nenhuma — ok |

### 2.2 Descrições de tools

| Prática recomendada | Fonte | Status no Barra | Proposta |
|---|---|---|---|
| Descrições **extremamente detalhadas** (fator nº 1); ≥3-4 frases; o que faz, **quando usar e quando não**, o que cada param significa, caveats | DTOOL; WTOOL | ✅ **já fazemos** — docstrings ricas: `escalar` (motivo deriva responsável; "não escreva mais texto"), `registrar_extracao` (transições, `limpar`, "uma vez por turno"), `pedir_pix_deslocamento` ("apenas externo", "uma vez", não digitar a chave), `consultar_agenda` ("apenas além das 48h", limite 14 dias), `enviar_midia` (rotação, foto→vídeo) | nenhuma — ok |
| Incluir **"quando NÃO usar"** | DTOOL | ✅ **já fazemos** — `consultar_agenda` ("as próximas 48h já estão no contexto; responda direto, sem tool"); `pedir_pix_deslocamento` ("APENAS para atendimento externo") | nenhuma — ok |
| Usar **`input_examples`** para tools complexas (não exemplos na string) | DTOOL; TREF | ✅ **feito (2026-05-28)** — implementado (antes nenhuma tool declarava `input_examples`); `03-prompts.md §3.1` e `04-tools.md` já anotam "input_examples a avaliar" para `registrar_extracao`/`escalar` | lacuna → adicionar `input_examples` a `registrar_extracao` (a mais complexa, ~15 campos) e `escalar`, cobrindo casos canônicos do corpus. Custo ~100-200 tokens, pagos **uma vez** no segmento `tools` cacheado. Verificar antes se `langchain-anthropic` 1.x propaga `input_examples` no `convert_to_anthropic_tool`; se não, injetar no dict de `build_tools_para_bind` (`agente/llm.py`). Cada exemplo deve validar contra o `input_schema` (inválido = 400) |

### 2.3 Schemas de input

| Prática recomendada | Fonte | Status no Barra | Proposta |
|---|---|---|---|
| **Nomes de parâmetro inequívocos** (`user_id`, não `user`) | WTOOL | ✅ **já fazemos** — `motivo`, `resumo_operacional`, `acao_esperada`, `data_inicio`/`data_fim`, `tag`, `tipo`, `legenda` | nenhuma — ok |
| `enum`/`required`/descrições de campo; modelos de dados estritos | DTOOL; WTOOL | ✅ **já fazemos** — `EscaladaPayload.motivo` (`Literal` de 14 valores), `ExtracaoPayload` (Literais para intenção/urgência/tipo etc.), `proxima_acao_esperada` `required` com `min/max_length`, `Field(description=...)` em campos sutis | nenhuma — ok |
| `additionalProperties:false` em todos os níveis | SO; STRICT | ✅ **já fazemos** — `ConfigDict(extra="forbid")` em `EscaladaPayload`, `ExtracaoPayload`, `SinaisQualificacao` (`ferramentas/escalada.py`, `extracao.py`) | nenhuma — ok |
| Parâmetros explícitos de topo em vez de objeto aninhado | DTOOL ("group into a single tool with an `action` parameter" — mas top-level fields); `04-tools.md §7` ("Anthropic recomenda parâmetros explícitos de topo") | 🟡 **parcial** — `escalar` e `registrar_extracao` embrulham os args num único `payload: BaseModel` (LLM vê `{"payload": {...}}`); `pedir_pix`/`enviar_midia`/`consultar_agenda` já usam top-level. O wrapper adiciona um nível de aninhamento | lacuna **(ajuste fino)** → achatar `escalar` para `escalar(motivo, resumo_operacional, acao_esperada)` (baixo risco — 3 campos) em `ferramentas/escalada.py`, mantendo a validação. `registrar_extracao` (~15 campos) é mais trabalhoso — avaliar custo/benefício; também ajuda o strict (menos aninhamento) |
| Param faltando: Sonnet tende a **inferir** valor (vs Opus pergunta) → bons schemas + `required` reduzem inferência errada | DTOOL (overview) | ✅ **já fazemos** — campos críticos são `required` com limites; opcionais têm default explícito (`exclude_defaults` no dump de `registrar_extracao`) | nenhuma — ok |

### 2.4 Tool results (compactos e high-signal)

| Prática recomendada | Fonte | Status no Barra | Proposta |
|---|---|---|---|
| Retornar só **informação de alto sinal**; results compactos | WTOOL; CTX | ✅ **já fazemos** — tools de escrita devolvem confirmação curta; `consultar_agenda` devolve markdown enxuto dos bloqueios | nenhuma — ok |
| **Identificadores semânticos > UUIDs opacos**; manter IDs internos fora do que o LLM raciocina | WTOOL | ✅ **já fazemos — exemplar** — `enviar_midia(tag)`: o LLM pede por **tag**, o sistema escolhe a foto por rotação e o `midia_id` (UUID) **nunca** passa pelo LLM (`ferramentas/midia.py`); idem chave Pix de 32+ chars anexada pela humanização (`pedir_pix_deslocamento` não retorna a chave) | nenhuma — ok |
| Paginação/range/filtro/truncamento com defaults sensatos | WTOOL | ✅ **já fazemos** — `consultar_agenda` limita a janela a 14 dias (erro instrutivo se exceder) | nenhuma — ok |

### 2.5 Erro recuperável vs falha de infraestrutura

| Prática recomendada | Fonte | Status no Barra | Proposta |
|---|---|---|---|
| Erro de execução **recuperável** → devolver no `tool_result` com `is_error:true` para o modelo se adaptar | HTOOL | ✅ **já fazemos** — política fechada em `04-tools.md §6`: erro recuperável vira **string `"ERRO: ..."`** (sai como `status=success` de propósito — é o loop funcionando), ex.: `ConflitoAgenda` em `registrar_extracao`/`pedir_pix`, chave Pix ausente, janela > 14 dias | nenhuma — ok |
| **Mensagens de erro instrutivas/acionáveis** ("o que deu errado + o que tentar"), não "failed" | HTOOL; WTOOL | ✅ **já fazemos** — "ERRO: o horário escolhido já está reservado… Ofereça outro horário ao cliente e registre de novo" (`extracao.py`); "ERRO: modelo não tem chave Pix… Escale para Fernando" (`pix.py`) | nenhuma — ok |
| Distinguir erro tratável pelo modelo de **falha de infra** (exceção/`is_error` de sistema) | HTOOL (inferido); `04-tools.md §6` | ✅ **já fazemos** — falha de infra (DB indisponível, exceção inesperada) **sobe como exceção tipada**; o `ToolNode` formata `is_error`/`status=error` e o coordenador escala por exaustão — buckets de métrica distintos (não mascara infra como sucesso) | nenhuma — ok |
| Nome de tool inválido: modelo retenta 2-3× antes de desistir; eliminar de vez com `strict` | HTOOL; STRICT | 🟡 **parcial** — hoje sem strict (ver §2.6); a validação Pydantic pós-call captura args/enum inválidos como erro recuperável, mas a um custo de round-trip | ver §2.6 (strict no `escalar`) |

### 2.6 Structured outputs / strict tool use

| Prática recomendada | Fonte | Status no Barra | Proposta |
|---|---|---|---|
| **Strict tool use** (`strict:true`) = grammar-constrained decoding: garante `name` válido e input conforme schema (ex.: enum sempre válido) | STRICT; SO | ✅ **feito (2026-05-28)** — strict per-tool no `escalar` shipado e validado contra a API; antes `settings.anthropic_strict_tools=False` (global); `agente/llm.py:build_tools_para_bind` aplica strict a **todas** as tools quando ligado. `04-tools.md §7` planejava strict **por-tool** em `escalar`/`registrar_extracao`. Motivo do OFF documentado em `settings.py:87-95`: "Schema is too complex" (comprimento de descriptions + enum de 14 valores em `escalar.motivo`) mesmo após `_sanitizar_para_strict`/`_desencapsular_anyof_null` | lacuna → tornar o strict **por-tool** em `build_tools_para_bind` (aceitar um conjunto de tools strict, não um flag global) e ligar para **`escalar`** primeiro — é a maior alavanca (o `motivo` é a chave de roteamento de handoff **e** o label de métrica; grammar garante enum válido sem round-trip) e o schema é pequeno (1 enum + 2 strings, cabe nos limites). Manter `registrar_extracao` não-strict até achatar/enxugar o schema. Limites a respeitar (SO/STRICT): ≤20 strict tools, ≤24 params opcionais, **≤16 union types** (cada `X|None` conta — relevante p/ `registrar_extracao`) |
| Limitações de JSON Schema no strict (sem `minimum`/`maximum`, `pattern` complexo, `additionalProperties≠false`, etc.) | SO (§ limitations) | ✅ **já tratado** — `_sanitizar_para_strict`/`_desencapsular_anyof_null` em `agente/llm.py` já removem `minimum`/`maximum`, `pattern` com lookahead e `anyOf:{null}`; prontos para quando o strict ligar | nenhuma — ok (a infra de sanitização já existe) |
| **Structured outputs** é GA, sem beta header; `tool_choice:any`/`tool` **incompatível** com extended thinking → manter `tool_choice:auto` | SO; DTOOL; EXT | ✅ **já fazemos** — `tool_choice` fica em `auto` (default, não setamos forçado); compatível com qualquer futura adoção de thinking e não invalida cache de tools/system (`04-tools.md §7`) | nenhuma — ok |
| **PII/PHI nunca no schema** (nome de campo/`enum`/`const`/`pattern`) — grammar do strict é cacheada ~24h fora das proteções de prompt | STRICT; SO | ✅ **já fazemos — exemplar** — invariante explícito em `04-tools.md §7` e nos comentários de `escalada.py`/`extracao.py`: nenhum dado de cliente entra em nome de campo/enum; dado sensível só no message content (protegido). Coerente com "dado vem no contexto, não em tool de leitura" | nenhuma — ok |
| Strict garante **forma**, não **correção** → manter validação de domínio | STRICT | ✅ **já fazemos** — defesa-em-profundidade: validação Pydantic pós-call + guarda do piso de desconto em `dominio/atendimentos/service.py` (ADR-0004), independente do strict | nenhuma — ok |
| Structured outputs nativo Anthropic (constrained decoding) é garantia mais forte que JSON prompt-based | SO; `06-pipelines-midia.md §0` | 🟡 **parcial (decisão de provider)** — o vision do Pix usa `response_format` json_schema via **OpenRouter** (escolha de provider, `06-pipelines-midia.md §2.3`), validação Pydantic manual; não é o constrained decoding nativo da Anthropic | lacuna **(revisitar, fora do chat)** → se a acurácia da extração de Pix oscilar, avaliar migrar o vision para structured outputs Anthropic-native (agora GA) — registrar a decisão em `06-pipelines-midia.md §2.3`. Fora do escopo do agente conversacional |

### 2.7 Parallel tool use e caching de tools

| Prática recomendada | Fonte | Status no Barra | Proposta |
|---|---|---|---|
| Parallel tool use é default; **todos os `tool_result` numa única mensagem `user`** | PAR | ✅ **já fazemos** — execução via `ToolNode` do LangGraph (`nos/tools.py`), que devolve os results no padrão correto do loop ReAct | nenhuma — ok |
| Calls num turno são **não-ordenadas/independentes**; desabilitar paralelo só quando precisa de ≤1 tool/turno | PAR | ✅ **decisão consciente** — **não** usamos `disable_parallel_tool_use` porque `enviar_midia` múltipla (2 fotos no mesmo turno) depende do paralelo; `escalar` em paralelo com outra tool é tolerável (as 3 camadas cobrem o texto) — `04-tools.md §3.5` | nenhuma — ok |
| Idempotência de side-effects (calls não-ordenadas podem repetir em replay) | PAR (inferido) | ✅ **já fazemos** — `_executar_idempotente` por `(turno_id, tool_name, call_idx)` em `ferramentas/_idempotencia.py`; `call_idx` ordinal injetado de forma determinística em `nos/tools.py:_ToolNodeComMidiaIdx` (replay-safe) | nenhuma — ok |
| Cachear o bloco de tools (última tool) e mantê-lo **byte-idêntico** entre modelos; qualquer mudança em tool invalida tudo | CACHE; DTOOL | ✅ **já fazemos** — `TOOLS` é constante de módulo congelada, ordem fixa, sem `build_tools(modelo)` (`ferramentas/__init__.py`); `cache_control` na última tool; invariante em `agente/CLAUDE.md` | nenhuma — ok |
| Grammar do strict é cacheada 24h; mudar só `name`/`description` não invalida | STRICT | ➖ **N/A hoje** (strict off) | relevante quando ligar strict no `escalar` (§2.6) — benefício adicional do strict |

---

## 3. Deriva doc ↔ código (registro canônico a reconciliar)

Os docs de design são o **registro canônico** das decisões. Hoje vários pontos do `03`/`04`/`01`/`10` ficaram **atrás do código** — isso não é bug, mas confunde quem lê os docs para decidir. Os próprios docs reconhecem parte disso. Reconciliar é **baixo esforço, ganho de manutenibilidade**.

| Deriva | Doc desatualizado | Realidade no código | Ação |
|---|---|---|---|
| **Breakpoints de cache** | `03-prompts.md §4.4` diz "3 fixos no P0 + BP4/cauda adiado P1" | **4 ativos**: a fusão persona+regras+FAQ (`persona.py:render_prefixo_geral`) liberou o slot e `marcar_cache_na_penultima` roda em `prepare_context.py:114`. `agente/CLAUDE.md` já descreve os 4 | atualizar `03 §1`/`§4.4`/`§5` para 4 breakpoints + BP_GERAL fundido |
| **FAQ fundida** | `03 §4.1`/`§5` mostram BP1 (persona+regras) e BP2 (FAQ) **separados** | **fundidos** num único `SystemMessage` (`render_prefixo_geral` = persona+regras+FAQ); `build_system_messages` recebe um só `geral_md` | atualizar os exemplos de `03 §4.1`/`§5` |
| **Contagem de tools** | `01-arquitetura.md §2.1` diz "8 tools no P0" | **5 tools** (`ferramentas/__init__.py`, `04-tools.md §1`) | corrigir `01 §2.1` |
| **Strict por-tool** | `04-tools.md §7` planeja strict ON em `escalar`/`registrar_extracao` | **OFF global** (`settings.anthropic_strict_tools=False`) por complexidade de schema | reconciliar `04 §7` com o estado real + o plano da §2.6 acima |
| **Reminder proativo vs reativo** | `10-persona-jailbreak.md §5.1` mostra heurística **reativa** (≥8 turnos + sinais de drift) | **proativa** (≥8 turnos, sem esperar drift) — `_precisa_reminder` em `prepare_context.py`; `03 §10` já é a versão corrente | alinhar `10 §5.1` a `03 §10` |
| **Vision Pix** | blocos de código em `06 §2.2`/`§2.3` mostram `messages.parse()` Anthropic-native | **OpenRouter** json_schema (`06 §0` item 4) | marcar o código antigo de `06` como histórico (parcialmente já feito) |
| **Persona file** | `03 §2` referencia `persona.md.j2` | arquivo real é **`persona.md`** (markdown puro); só `regras.md.j2` é Jinja | corrigir referência em `03 §2` |
| **Contagem de few-shot** | `03 §2.2` manda "manter 4-6 exemplos" | `persona.md` viva tem ~11 + armadilhas; ligado à §1.2 | reconciliar após a poda guiada por eval (§1.2) |

---

## 4. Top de maior impacto (esforço × ganho)

Ordenado por valor (ganho alto / esforço baixo primeiro). Itens marcados **(experimento)** exigem medição antes de adotar.

1. **Pré-aquecer o prefixo global de cache** (`max_tokens:0` no deploy de prompt/startup) — **esforço BAIXO · ganho MÉDIO-ALTO.** Elimina o burst de cache writes a 2× quando um deploy de `persona.md`/`regras.md.j2`/`faq.md` (ou gap > TTL) invalida o prefixo compartilhado por todas as modelos. Já desenhado (`03 §4.5`), compatível com a config atual. → §1.7.
2. **A/B de `effort=medium` no loop de tools** — **esforço BAIXO · ganho MÉDIO.** `effort=low` enviesa o 4.6 a menos tool calls; isso ameaça o `registrar_extracao` esperado todo turno. É só um knob (`settings.anthropic_effort`) + fixtures no `08-evals.md` medindo `tool_use_correto` vs latência/custo. → §1.4.
3. **Reconciliar a deriva doc↔código** (`03`/`04`/`01`/`10`) — **esforço BAIXO · ganho MÉDIO.** Os docs são o registro canônico; hoje subestimam o que o código já faz (4 breakpoints, FAQ fundida, 5 tools, reminder proativo) e podem levar a decisões erradas. → §3.
4. **Strict tool use por-tool no `escalar`** — **esforço MÉDIO · ganho MÉDIO-ALTO.** Grammar-constrained garante `motivo` (chave de roteamento + métrica) sempre válido, elimina round-trips de reparo, e a grammar fica cacheada 24h. Exige tornar o strict por-tool em `build_tools_para_bind` (a sanitização de schema já existe). → §2.6.
5. **`input_examples` em `registrar_extracao` e `escalar`** — **esforço BAIXO-MÉDIO · ganho MÉDIO.** Anthropic recomenda exemplos de input para tools complexas; custo pago uma vez no segmento `tools` cacheado. Verificar passthrough no `langchain-anthropic` 1.x. → §2.2.
6. **Poda guiada por eval dos few-shot da persona** — **esforço MÉDIO · ganho BAIXO-MÉDIO.** A persona cresceu além dos 4-6 exemplos recomendados; confirmar que cada exemplo ganha seu lugar e não induz padrão indevido, e reconciliar a contagem no `03 §2.2`. → §1.2.
7. **Achatar o wrapper `payload`** (`escalar` → params de topo) — **esforço MÉDIO · ganho BAIXO.** Alinha com "parâmetros explícitos de topo" e ajuda o strict; baixo risco no `escalar` (3 campos). Ajuste fino. → §2.3.
8. **(experimento) Adaptive thinking + `effort=low` no nó `llm`** — **esforço MÉDIO · ganho INCERTO.** Adaptive pula raciocínio em turnos simples e pensa nos multi-step de tool (interleaved thinking automático), mas adiciona latência. Medir corretude de extração/escalada vs latência no `08-evals.md` antes de mexer; se adotar, ligar `display:"omitted"` e fixar o modo (não alternar — quebra cache de messages). → §1.4.
9. **Revisar `**Nunca**`/`**sempre**` remanescentes** em `regras.md.j2` — **esforço BAIXO · ganho BAIXO.** Onde for ênfase (não regra dura), reescrever em forma positiva (4.6 over-trigga em linguagem forçada). → §1.3.

### Pontos onde já somos exemplares (não mexer)

- Consolidação de catálogo (5 tools) e `enviar_midia(tag)` mantendo UUID fora do LLM — §2.1/§2.4.
- Guarda de privacidade: nenhum dado de cliente em nome de campo/enum/schema — §2.6.
- Erro recuperável (string) vs falha de infra (exceção/`is_error`) com buckets distintos — §2.5.
- Reminder no user turn (não prefill) — alinhado ao 4.6 — §1.1.
- Prefixo de cache global byte-idêntico entre modelos, ordem `tools→system→messages`, breakpoint na penúltima da janela — §1.7.
- `effort` setado explicitamente + `low` para a resposta conversacional (recomendação oficial de baixa latência) — §1.4.
