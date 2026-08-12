# Modelos LLM — levantamento por fontes primárias

**Data do levantamento:** 11/08/2026
**Escopo:** DeepSeek V4 Flash-0731 / V4 Pro · OpenAI GPT-5.6 Luna · Anthropic Claude Sonnet 5 / Haiku 4.5 · Google Gemini 3.6 Flash / 3.5 Flash-Lite / 3.1 Flash-Lite
**Contexto de uso:** agente conversacional de vendas em produção (WhatsApp, PT-BR), chamada síncrona no caminho da resposta, ~25–60k tokens de prompt por turno com prefixo estável, tool calling para extração de estado, LLM-as-judge em evals, domínio adulto (acompanhantes).

## Método e limites deste documento

- **Só fontes primárias.** Toda linha de fato cita a URL da doc oficial do provedor. Onde a doc oficial não responde, está escrito **"não documentado"** — não houve inferência a partir de blogs, changelogs de terceiros ou memória.
- **~46 fetches** de páginas oficiais (api-docs.deepseek.com, developers.openai.com, platform.claude.com, anthropic.com/legal, ai.google.dev, policies.google.com, model-spec.openai.com, cdn.deepseek.com/policies).
- **Páginas que não puderam ser lidas** (bloqueio/404 do servidor, não ausência de informação):
  - `https://openai.com/policies/usage-policies` → **HTTP 403** em todas as variantes. A política de uso da OpenAI **não foi lida na fonte**; usei o Model Spec oficial (`model-spec.openai.com`) e a doc de moderação como substitutos primários, e isso está sinalizado no texto.
  - `https://ai.google.dev/gemini-api/docs/model-versions` → **HTTP 404**.
  - `https://cloud.google.com/vertex-ai/generative-ai/docs/learn/locations` e `.../vertex-ai/docs/general/locations` → redirect + conteúdo sem a tabela de regiões. Regiões do Vertex ficaram como lacuna.
- O orçamento de WebSearch da sessão estava esgotado; a navegação foi feita por URL direta na doc de cada provedor.

## Verificação de identidade dos modelos pedidos

| Modelo pedido | Existe na doc oficial? | ID exato | Fonte |
|---|---|---|---|
| DeepSeek V4 Flash 0731 | Sim, como **snapshot por trás do alias** | alias `deepseek-v4-flash` → "DeepSeek-V4-Flash-0731" | [api-docs.deepseek.com/news](https://api-docs.deepseek.com/news) |
| DeepSeek V4 Pro | Sim | `deepseek-v4-pro` | [pricing](https://api-docs.deepseek.com/quick_start/pricing/) |
| GPT-5.6 Luna | Sim | `gpt-5.6-luna` | [developers.openai.com/api/docs/models](https://developers.openai.com/api/docs/models) |
| Claude Sonnet 5 | Sim | `claude-sonnet-5` | [platform.claude.com/docs/en/about-claude/models/overview](https://platform.claude.com/docs/en/about-claude/models/overview) |
| Claude Haiku 4.5 | Sim | `claude-haiku-4-5-20251001` (alias `claude-haiku-4-5`) | [models/overview](https://platform.claude.com/docs/en/about-claude/models/overview) |
| Gemini 3.6 Flash | Sim (estável) | `gemini-3.6-flash` | [ai.google.dev/gemini-api/docs/models](https://ai.google.dev/gemini-api/docs/models) |
| Gemini 3.5 Flash-Lite | Sim (estável) | `gemini-3.5-flash-lite` | [models](https://ai.google.dev/gemini-api/docs/models) |
| Gemini 3.1 Flash-Lite | Sim (estável desde 07/05/2026) | `gemini-3.1-flash-lite` | [changelog](https://ai.google.dev/gemini-api/docs/changelog) |

⚠️ **Armadilha de alias na OpenAI:** o alias `gpt-5.6` resolve para **`gpt-5.6-sol`**, não para Luna. Luna só é acessível pelo ID completo `gpt-5.6-luna` ([models](https://developers.openai.com/api/docs/models)).

---

# 1. DeepSeek

## 1.1 Preço listado (USD por 1M tokens)

| Modelo | Input (cache hit) | Input (cache miss) | Output | Contexto | Max output | Fonte |
|---|---|---|---|---|---|---|
| `deepseek-v4-flash` | **$0,0028** | **$0,14** | **$0,28** | 1M | 384K | [pricing](https://api-docs.deepseek.com/quick_start/pricing/) |
| `deepseek-v4-pro` | **$0,003625** | **$0,435** | **$0,87** | 1M | 384K | [pricing](https://api-docs.deepseek.com/quick_start/pricing/) |

- Não há coluna separada de "cache write" na tabela oficial; o cache é escrito sem tarifa própria documentada — o preço de escrita é **não documentado**. [pricing](https://api-docs.deepseek.com/quick_start/pricing/)
- Regra de dedução, verbatim: *"The expense = number of tokens × price. The corresponding fees will be directly deducted from your topped-up balance or granted balance, with a preference for using the granted balance first when both balances are available."* [pricing](https://api-docs.deepseek.com/quick_start/pricing/)
- Desconto de horário off-peak: **não documentado** na página atual.
- ⚠️ Observação de auditoria: a razão cache-hit/cache-miss é de **1/50** (flash) e **1/120** (pro), fora do padrão 1/10 dos demais provedores. O número foi lido duas vezes na mesma página, com o mesmo resultado; se o cache for o eixo de decisão, confirme na fatura antes de dimensionar.

## 1.2 Prompt caching (Context Caching on Disk)

| Item | O que a doc diz | Fonte |
|---|---|---|
| Automático ou explícito | **Automático**: *"The DeepSeek API Context Caching on Disk Technology is enabled by default for all users, allowing them to benefit without needing to modify their code."* | [kv_cache](https://api-docs.deepseek.com/guides/kv_cache) |
| Requisito de prefixo | *"A subsequent request can only hit the cache if it **fully matches** a **cache prefix unit**."* — casamento total do prefixo | [kv_cache](https://api-docs.deepseek.com/guides/kv_cache) |
| Granularidade mínima | Unidades de cache são criadas (a) nas fronteiras de requisição, (b) quando prefixos comuns são detectados entre requisições, (c) *"For long inputs or long outputs, the system will carve out cache prefix units at fixed token intervals"*. O número de tokens desse intervalo é **não documentado** | [kv_cache](https://api-docs.deepseek.com/guides/kv_cache) |
| TTL | Sem TTL fixo: *"Once the cache is no longer in use, it will be automatically cleared, usually within a few hours to a few days."* | [kv_cache](https://api-docs.deepseek.com/guides/kv_cache) |
| Verificação | `usage.prompt_cache_hit_tokens` e `usage.prompt_cache_miss_tokens` | [kv_cache](https://api-docs.deepseek.com/guides/kv_cache) · [API ref](https://api-docs.deepseek.com/api/create-chat-completion) |
| O que invalida | **Não documentado** explicitamente além do "casamento total do prefixo" |  |

**Leitura para o Barra:** prefixo estável (persona + histórico) casa com o modelo de cache do DeepSeek sem nenhuma anotação no request — é o provedor com menor esforço de integração de cache dos quatro. O risco é o oposto: sem TTL garantido, o hit rate é **não previsível** por contrato.

## 1.3 Rate limits

| Item | O que a doc diz | Fonte |
|---|---|---|
| Métrica | **Concorrência**, não RPM/TPM. *"A request counts as one concurrent connection from the time it is sent until the model response is complete."* | [rate_limit](https://api-docs.deepseek.com/quick_start/rate_limit) |
| Limites | `deepseek-v4-pro`: **500** conexões concorrentes · `deepseek-v4-flash`: **2500** | [rate_limit](https://api-docs.deepseek.com/quick_start/rate_limit) |
| Tiers | Não há tiers por gasto. Expansão sob demanda: *"If you need higher concurrency, you can submit a capacity expansion request… There is no additional cost for capacity expansion."* | [rate_limit](https://api-docs.deepseek.com/quick_start/rate_limit) |
| Isolamento por usuário | Com `user_id` e cota expandida, cada `user_id` recebe o limite-base; excedente → HTTP 429 | [rate_limit](https://api-docs.deepseek.com/quick_start/rate_limit) |
| RPM / TPM / TPD | **Não documentado** (não existem) |  |
| Erros | 429 "Rate Limit Reached" · 503 "Server Overloaded" · 402 "Insufficient Balance". Orientação de retry: *"retry your request after a brief wait"*; não há política de backoff exponencial documentada | [error_codes](https://api-docs.deepseek.com/quick_start/error_codes) |

## 1.4 Versionamento e depreciação ⚠️

| Pergunta | Resposta da doc | Fonte |
|---|---|---|
| Existem snapshots datados chamáveis? | **Não.** O snapshot 0731 existe, mas **não há ID datado publicado para chamar**. A doc diz: *"The `deepseek-v4-flash` model has been updated to DeepSeek-V4-Flash-0731. The calling method remains unchanged — simply use `deepseek-v4-flash` to access the latest version."* | [news](https://api-docs.deepseek.com/news) |
| O alias muda sob os pés? | **Sim, por design.** É o comportamento documentado do alias | [news](https://api-docs.deepseek.com/news) |
| Por quanto tempo uma versão fica disponível? | **Não documentado** |  |
| Há aviso prévio de troca? | **Não documentado** — não existe página de deprecation policy na doc |  |

**Risco direto para o Barra:** este é o pior cenário possível para a integridade dos evals. O modelo em produção pode ser trocado por baixo sem aviso, sem ID datado para fixar, e sem janela de migração. Qualquer baseline de eval medida hoje contra `deepseek-v4-flash` **não é reprodutível por contrato**. Nenhum outro provedor deste levantamento tem esse buraco.

## 1.5 Structured outputs e tool calling

| Item | O que a doc diz | Fonte |
|---|---|---|
| JSON mode | `response_format: {'type': 'json_object'}`; exige a palavra "json" no prompt **e** um exemplo do formato; exige `max_tokens` dimensionado para não truncar | [json_mode](https://api-docs.deepseek.com/guides/json_mode) |
| Bug conhecido do JSON mode | Verbatim: *"When using the JSON Output feature, the API may occasionally return empty content. We are actively working on optimizing this issue."* | [json_mode](https://api-docs.deepseek.com/guides/json_mode) |
| JSON Schema estrito | **Sim, em beta**, via `base_url = https://api.deepseek.com/beta` + `"strict": true` na função | [tool_calls](https://api-docs.deepseek.com/guides/tool_calls) |
| Requisitos do modo estrito | Todas as properties em `required`; `additionalProperties: false` | [tool_calls](https://api-docs.deepseek.com/guides/tool_calls) |
| Tipos suportados no strict | object, string, number, integer, boolean, array, enum, anyOf, `$ref`, `$def` | [tool_calls](https://api-docs.deepseek.com/guides/tool_calls) |
| Não suportado | `minLength`/`maxLength` em strings; `minItems`/`maxItems` em arrays | [tool_calls](https://api-docs.deepseek.com/guides/tool_calls) |
| Limite de ferramentas | **máx. 128 functions** | [API ref](https://api-docs.deepseek.com/api/create-chat-completion) |
| `tool_choice` | `none` / `auto` / `required` / função específica | [API ref](https://api-docs.deepseek.com/api/create-chat-completion) |
| Profundidade de schema / nº de properties | **Não documentado** |  |
| Parallel tool calls | **Não documentado** |  |

## 1.6 Reasoning / thinking

| Item | O que a doc diz | Fonte |
|---|---|---|
| Parâmetro | `"thinking": {"type": "enabled" \| "disabled", "reasoning_effort": "low" \| "high" \| "max"}` | [API ref](https://api-docs.deepseek.com/api/create-chat-completion) · [reasoning_model](https://api-docs.deepseek.com/guides/reasoning_model) |
| Default | **Não documentado** |  |
| Cobrança dos tokens de raciocínio | `usage.reasoning_tokens` é retornado; **se são faturados como output é não documentado** na página de preço | [API ref](https://api-docs.deepseek.com/api/create-chat-completion) |
| Impacto em latência | **Não documentado** |  |
| Outros parâmetros | `temperature` 0–2 (default 1), `top_p`, `stop` (≤16), `logprobs`, `top_logprobs` (≤20). **`frequency_penalty` e `presence_penalty` estão deprecados** | [API ref](https://api-docs.deepseek.com/api/create-chat-completion) |
| Temperatura recomendada | Código/matemática 0,0 · análise de dados 1,0 · **conversa geral 1,3** · tradução 1,3 · escrita criativa 1,5 | [parameter_settings](https://api-docs.deepseek.com/quick_start/parameter_settings) |

## 1.7 Política de conteúdo, dados e treino ⚠️

| Item | O que a doc diz | Fonte |
|---|---|---|
| Conteúdo sexual | Não há cláusula de uso proibido de conteúdo sexual nos Termos da Open Platform. A única menção a "pornographic" é sobre **uso da marca**: *"Associating our brand elements with content or scenarios that are illegal or non-compliant, contrary to public order and good morals, politically sensitive, vulgar, **pornographic**, gambling-related, violent, or infringe upon third-party rights."* (§5.3(4)) | [ToS](https://cdn.deepseek.com/policies/en-US/deepseek-open-platform-terms-of-service.html) |
| Uso de outputs | *"You may apply the Inputs and Outputs of the Services to a wide range of use cases, including personal use, academic research, derivative product development, training other models (such as model distillation), etc."* (§4.2(3)) | [ToS](https://cdn.deepseek.com/policies/en-US/deepseek-open-platform-terms-of-service.html) |
| **Dados de API usados para treino?** | A Privacy Policy declara uso de dados *"To improve and develop the Services and to train and improve our technology, such as our machine learning models."* Não há isenção para tráfego de API | [Privacy](https://cdn.deepseek.com/policies/en-US/deepseek-privacy-policy.html) |
| Como desativar | Existe *"the right to opt-out of using your Personal Data for training our models or optimizing our technologies"* — o **mecanismo de opt-out não está documentado** na política | [Privacy](https://cdn.deepseek.com/policies/en-US/deepseek-privacy-policy.html) |
| Retenção | *"We retain Personal Data for as long as necessary to provide our Services…"* / *"…we keep this Personal Data for as long as you have an account."* Sem prazo em dias | [Privacy](https://cdn.deepseek.com/policies/en-US/deepseek-privacy-policy.html) |
| Onde os dados ficam | ⚠️ *"To provide you with our services, we directly collect, process and store your Personal Data in People's Republic of China."* | [Privacy](https://cdn.deepseek.com/policies/en-US/deepseek-privacy-policy.html) |
| Regiões / disponibilidade | *"We make no warranty that the Services are available or will continue to be available in certain jurisdictions."* (§1.4). Nenhuma região/endpoint da América do Sul documentada | [ToS](https://cdn.deepseek.com/policies/en-US/deepseek-open-platform-terms-of-service.html) |

**Leitura para o Barra:** é o único provedor deste levantamento onde (a) não há compromisso documentado de não treinar com dados de API, (b) o dado de conversa — que aqui inclui PII sensível de clientes brasileiros e conteúdo sexual explícito — é declaradamente armazenado na China, e (c) não há prazo de retenção. Isso é uma questão de LGPD antes de ser uma questão de política de conteúdo.

---

# 2. OpenAI — GPT-5.6 Luna

## 2.1 Preço listado (USD por 1M tokens)

| Modelo | Input | Cached input | Output | Fonte |
|---|---|---|---|---|
| **`gpt-5.6-luna`** | **$0,20** | **$0,02** | **$1,20** | [pricing](https://developers.openai.com/api/docs/pricing) · [model page](https://developers.openai.com/api/docs/models/gpt-5.6-luna) |
| `gpt-5.6-terra` | $2,00 | $0,20 | $12,00 | [pricing](https://developers.openai.com/api/docs/pricing) |
| `gpt-5.6-sol` (alias `gpt-5.6`) | $5,00 | $0,50 | $30,00 | [pricing](https://developers.openai.com/api/docs/pricing) |

Modificadores documentados na página do Luna ([model page](https://developers.openai.com/api/docs/models/gpt-5.6-luna)):
- **Requisições acima de 272K tokens de input:** multiplicador **2x no input** e **1,5x no output**.
- **Cache write:** **1,25x** a tarifa de input padrão (é o único dos quatro provedores, junto com a Anthropic, que cobra escrita de cache).

Especificações: contexto **1.050.000 tokens**, max output **128.000**, knowledge cutoff **16/02/2026**, entrada texto+imagem, saída só texto. Recursos suportados, verbatim: *"streaming, structured_outputs, function_calling, file_search, image_input, web_search, prompt_caching"*. [model page](https://developers.openai.com/api/docs/models/gpt-5.6-luna)

## 2.2 Prompt caching

| Item | O que a doc diz | Fonte |
|---|---|---|
| Mínimo | *"GPT-5.6 and later models: Caching is available for prefixes containing at least 1,024 tokens."* | [prompt-caching](https://developers.openai.com/api/docs/guides/prompt-caching) |
| Automático ou explícito | **Ambos.** Automático por padrão; em GPT-5.6+ há breakpoints explícitos via `prompt_cache_options.mode = "explicit"`, que desliga os breakpoints automáticos | [prompt-caching](https://developers.openai.com/api/docs/guides/prompt-caching) |
| Prefixo idêntico | *"Cache hits are only possible for exact prefix matches within a prompt."* Conteúdo estático (instruções, exemplos, imagens, tools) precisa ser idêntico; o dinâmico vai no fim | [prompt-caching](https://developers.openai.com/api/docs/guides/prompt-caching) |
| TTL | GPT-5.6+: `prompt_cache_options.ttl` define vida mínima; **`"30m"` é o único valor suportado** e é o default. Modelos anteriores: evicção após 5–10 min de inatividade, até no máximo 1h (retenção estendida até 24h) | [prompt-caching](https://developers.openai.com/api/docs/guides/prompt-caching) |
| Custo | Leitura com desconto; *"Cache writes cost 1.25× the uncached input token rate"* em GPT-5.6+ (modelos anteriores não cobram escrita) | [prompt-caching](https://developers.openai.com/api/docs/guides/prompt-caching) |
| Roteamento | `prompt_cache_key`: *"Requests are routed to a machine based on a hash of the initial prefix."* Recomendação de manter ~**15 requisições por minuto por chave** | [prompt-caching](https://developers.openai.com/api/docs/guides/prompt-caching) |
| O que invalida | Qualquer mudança no prefixo; parâmetros que deveriam ser idênticos e não são (ex.: `detail` de imagem) | [prompt-caching](https://developers.openai.com/api/docs/guides/prompt-caching) |

**Leitura para o Barra:** o TTL de 30 min é o mais generoso dos quatro para um agente de WhatsApp — conversas com pausas de 10–20 min entre mensagens do cliente continuam batendo cache. E `prompt_cache_key` por `atendimento_id` mapeia direto no modelo de sessão do Barra; o limite de ~15 rpm/chave é folgado para uma conversa individual.

## 2.3 Rate limits

Tiers e qualificação ([rate-limits](https://developers.openai.com/api/docs/guides/rate-limits)):

| Tier | Qualificação | Limite mensal |
|---|---|---|
| Free | Geografia permitida | $100 |
| Tier 1 | $5 pagos | $100 |
| Tier 2 | $50 pagos | $500 |
| Tier 3 | $100 pagos | $1.000 |
| Tier 4 | $250 pagos | $5.000 |
| Tier 5 | $1.000 pagos | $200.000 |

Limites específicos do `gpt-5.6-luna` ([model page](https://developers.openai.com/api/docs/models/gpt-5.6-luna)):

| Tier | RPM | TPM | Batch queue |
|---|---|---|---|
| Tier 1 | 500 | 500K | 5M |
| Tier 2 | 5.000 | 2M | 20M |
| Tier 3 | 5.000 | 4M | 40M |
| Tier 4 | 10.000 | 10M | 1B |
| Tier 5 | 30.000 | 180M | 15B |

Métricas usadas: RPM, RPD, TPM, TPD, IPM. Headers: `x-ratelimit-limit-requests`, `x-ratelimit-remaining-requests`, `x-ratelimit-limit-tokens`, `x-ratelimit-remaining-tokens`, `x-ratelimit-reset-*`, `Retry-After`. [rate-limits](https://developers.openai.com/api/docs/guides/rate-limits)

⚠️ **Não documentado:** se tokens cacheados contam para o TPM (a Anthropic documenta explicitamente que não contam; a OpenAI é silente).

## 2.4 Versionamento e depreciação

Política, verbatim ([deprecations](https://developers.openai.com/api/docs/deprecations)):
- Modelos GA: **"At least 6 months"** de aviso prévio.
- Variantes especializadas (ex.: `gpt-5.1-chat-latest`, `gpt-5.3-codex`): **"At least 3 months"**.
- Modelos preview: *"may be retired with much shorter notice, such as 2 weeks."*
- *"If safety or compliance concerns require us to retire a model sooner, we will provide as much notice as reasonably possible."*
- Terminologia: "Deprecation" = processo de aposentadoria (começa no anúncio); "Legacy" = sem atualizações; "Sunset"/"shut down" = inacessível.
- Aliases mapeiam para snapshots; quando o snapshot é depreciado, **os aliases associados desligam na mesma data**.

Entradas relevantes da tabela ([deprecations](https://developers.openai.com/api/docs/deprecations)): `gpt-5-2025-08-07` e `o3-2025-04-16` desligam em 11/12/2026 (substituto `gpt-5.6-sol`); `gpt-5.2-chat-latest`/`gpt-5.3-chat-latest` em 10/08/2026; Assistants API em 26/08/2026.

⚠️ **Snapshot datado do Luna:** a página do modelo lista como único snapshot disponível **`gpt-5.6-luna`** — ou seja, **o ID já é o snapshot**, não há sufixo de data para fixar. Combinado com o aviso de 6 meses, os evals ficam protegidos por prazo, mas não por pinning de data. [model page](https://developers.openai.com/api/docs/models/gpt-5.6-luna)

## 2.5 Structured outputs / JSON Schema estrito

Limites documentados ([structured-outputs](https://developers.openai.com/api/docs/guides/structured-outputs)):

| Restrição | Valor |
|---|---|
| Tipos suportados | String, Number, Boolean, Integer, Object, Array, Enum, `anyOf` |
| `required` | **Todos os campos devem ser required** (opcional se faz com `"type": ["string","null"]`) |
| `additionalProperties` | *"Objects have `additionalProperties: false` must always be set."* |
| Profundidade / tamanho | *"A schema may have up to 5000 object properties total, with up to 10 levels of nesting."* |
| Comprimento de nomes | Soma de nomes de properties, definitions, enums e consts ≤ **120.000 caracteres** |
| Enums | ≤ **1000 valores** no total; com >250 valores, o total de caracteres dos enums ≤ **15.000** |
| Keywords não suportadas | `allOf`, `not`, `dependentRequired`, `dependentSchemas`, `if`, `then`, `else` |
| Unions | *"Root objects must not be `anyOf` and must be an object."* `anyOf` aninhado é aceito se cada ramo for válido |
| Recursão | **Suportada** via `"$ref": "#"` ou `$defs` |

Tool calling ([function-calling](https://developers.openai.com/api/docs/guides/function-calling)): strict mode exige `additionalProperties: false` e todos os campos em `required`; **parallel tool calls** suportados a partir do GPT-5 (`parallel_tool_calls: false` força ≤1 por turno); recomendação de *"fewer than 20 functions available at the start of a turn"*.

## 2.6 Reasoning

| Item | O que a doc diz | Fonte |
|---|---|---|
| Níveis | `none`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max` — *"model-dependent"*, nem todo modelo suporta todos | [reasoning](https://developers.openai.com/api/docs/guides/reasoning) |
| Default | **`medium`** nos modelos GPT-5.6 (e no GPT-5.5) | [reasoning](https://developers.openai.com/api/docs/guides/reasoning) |
| Cobrança | **Sim, como output.** Verbatim: *"reasoning tokens… still occupy space in the model's context window and are billed as output tokens."* | [reasoning](https://developers.openai.com/api/docs/guides/reasoning) |
| Visibilidade | Tokens de raciocínio não são expostos; há resumos opcionais via `summary: "auto" \| "concise"` | [reasoning](https://developers.openai.com/api/docs/guides/reasoning) |
| Latência | Efeitos maiores → mais latência; recomendação de reservar **≥25.000 tokens** para raciocínio + saída ao começar | [reasoning](https://developers.openai.com/api/docs/guides/reasoning) |
| Quais níveis o Luna suporta | ⚠️ **Não documentado** na página do modelo (a doc manda "check the relevant model page", e a página não lista) | [model page](https://developers.openai.com/api/docs/models/gpt-5.6-luna) |

## 2.7 Política de conteúdo adulto ⚠️ (fonte substituta)

A Usage Policy em `openai.com/policies/usage-policies` retornou **HTTP 403** em todas as tentativas — **não foi lida**. O que segue é do **Model Spec oficial** e da doc de moderação, ambos primários, mas não substituem a leitura da Usage Policy:

- **Model Spec, 18/12/2025, seção "Don't respond with erotica or gore"** (nível de autoridade: System), verbatim: *"The assistant should not generate erotica, depictions of illegal or non-consensual sexual activities, or extreme gore, except in scientific, historical, news, artistic or other contexts where sensitive content is appropriate."* O documento acrescenta que a OpenAI está *"exploring how to let developers and users generate erotica and gore in age-appropriate contexts"*, mantendo salvaguardas contra *"sexual deepfakes and revenge porn"*. [model-spec.openai.com/2025-12-18.html](https://model-spec.openai.com/2025-12-18.html)
- **Moderação — categoria `sexual`**, verbatim: *"Content meant to arouse sexual excitement, such as the description of sexual activity, **or that promotes sexual services** (excluding sex education and wellness)."* Categoria `sexual/minors`: *"Sexual content that includes an individual who is under 18 years old."* O endpoint de moderação é **gratuito** e a doc não o apresenta como obrigatório. [moderation](https://developers.openai.com/api/docs/guides/moderation)

⚠️ **Este é o único trecho, entre os quatro provedores, que nomeia explicitamente "promotes sexual services"** — exatamente a descrição funcional do domínio do Barra. Está na definição de uma categoria de classificador, não numa cláusula de proibição de uso, mas é o sinal mais direto que a documentação oficial oferece.

## 2.8 Dados de API e regiões

| Item | O que a doc diz | Fonte |
|---|---|---|
| Treino | *"data sent to the OpenAI API is not used to train or improve OpenAI models (unless you explicitly opt in to share data with us)"* (vigente desde 01/03/2023) | [your-data](https://developers.openai.com/api/docs/guides/your-data) |
| Retenção padrão | Logs de abuse monitoring: **até 30 dias**. Estado de aplicação varia por endpoint | [your-data](https://developers.openai.com/api/docs/guides/your-data) |
| Como desativar | **Modified Abuse Monitoring** (exclui conteúdo dos logs de abuso) e **Zero Data Retention** (exclui dos logs **e** trata `store` como `false`). Ambos exigem *"prior approval by OpenAI and acceptance of additional requirements"* | [your-data](https://developers.openai.com/api/docs/guides/your-data) |
| Data residency | EUA, Europa (EEA + Suíça), Austrália, Canadá, Japão, Índia, Singapura, Coreia do Sul, Reino Unido, Emirados Árabes | [your-data](https://developers.openai.com/api/docs/guides/your-data) |
| **América do Sul / Brasil** | ⚠️ **Não listado** como região de data residency | [your-data](https://developers.openai.com/api/docs/guides/your-data) |
| Latência p/ América do Sul | **Não documentado** |  |
| Ressalva | *"Data residency does not apply to: (1) any transmission or storage of Customer Content outside of the selected region caused by the location of an End User or Customer's infrastructure"* | [your-data](https://developers.openai.com/api/docs/guides/your-data) |

---

# 3. Anthropic — Claude Sonnet 5 e Haiku 4.5

## 3.1 Preço listado (USD por MTok)

| Modelo | Input | Cache write 5m | Cache write 1h | Cache hit | Output | Fonte |
|---|---|---|---|---|---|---|
| **Claude Sonnet 5** (até 31/08/2026, preço introdutório) | **$2** | **$2,50** | **$4** | **$0,20** | **$10** | [pricing](https://platform.claude.com/docs/en/about-claude/pricing) |
| **Claude Sonnet 5** (a partir de 01/09/2026) | **$3** | **$3,75** | **$6** | **$0,30** | **$15** | [pricing](https://platform.claude.com/docs/en/about-claude/pricing) |
| **Claude Haiku 4.5** | **$1** | **$1,25** | **$2** | **$0,10** | **$5** | [pricing](https://platform.claude.com/docs/en/about-claude/pricing) |

Nota verbatim da doc: *"Introductory pricing of $2/$10 per million input/output tokens is in effect through August 31, 2026, after which the standard pricing of $3/$15 per million input/output tokens will take effect."* [pricing](https://platform.claude.com/docs/en/about-claude/pricing)

Outros modificadores relevantes:
- **Batch API:** desconto de 50% (Sonnet 5 $1/$5 no período introdutório; Haiku 4.5 $0,50/$2,50). [pricing](https://platform.claude.com/docs/en/about-claude/pricing)
- **`inference_geo: "us"`:** multiplicador **1,1x** sobre todas as categorias de token. [data-residency](https://platform.claude.com/docs/en/manage-claude/data-residency)
- **Janela de 1M tokens sem prêmio de long-context** em modelos 4.6+: *"A 900k-token request is billed at the same per-token rate as a 9k-token request."* [pricing](https://platform.claude.com/docs/en/about-claude/pricing)
- **Overhead de tool use** (system prompt injetado): Sonnet 5 = **354 tokens** (`auto`/`none`) ou **474** (`any`/`tool`); Haiku 4.5 = **496** / **588**. [pricing](https://platform.claude.com/docs/en/about-claude/pricing)
- ⚠️ **Tokenizer:** modelos 4.7+ usam um tokenizer novo que *"produces approximately 30% more tokens for the same text"*. Sonnet 4.6 e anteriores usam o antigo. Comparação de custo entre gerações precisa recontar tokens. [pricing](https://platform.claude.com/docs/en/about-claude/pricing)

## 3.2 Prompt caching

| Item | Sonnet 5 | Haiku 4.5 | Fonte |
|---|---|---|---|
| **Mínimo cacheável** | **1.024 tokens** | ⚠️ **4.096 tokens** | [prompt-caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching) |
| TTL | 5 min (default) ou 1h (`ttl: "1h"`, custo 2x) | idem | [prompt-caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching) |
| Breakpoints | máx. **4** por requisição | idem | [prompt-caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching) |
| Automático ou explícito | Ambos: `cache_control` no topo do request (automático) ou por bloco (explícito) | idem | [pricing](https://platform.claude.com/docs/en/about-claude/pricing) |
| Prefixo | Casamento de prefixo; ordem de renderização `tools` → `system` → `messages`; mudança em um nível invalida esse nível e todos os seguintes | idem | [prompt-caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching) |
| Janela de lookback | **20 blocos** por breakpoint | idem | [prompt-caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching) |
| Isolamento | **workspace-level** na Claude API; org-level em Bedrock/Google Cloud. Nunca compartilhado entre organizações | [prompt-caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching) |
| Concorrência | Uma entrada só fica legível **depois que a primeira resposta começa a streamar** — N requisições paralelas com o mesmo prefixo pagam todas cheio | [prompt-caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching) |

**O que invalida (tabela oficial)**: definições de tools → cache inteiro; toggle de web search/citations e `speed` → system + messages; `tool_choice`, imagens, `output_config.effort` → messages. [prompt-caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)

⚠️ **Direto para o Barra:** com prompt de 25–60k tokens, ambos passam o mínimo folgadamente. Mas **mudar `effort` entre turnos invalida o cache da conversa** — a doc é explícita: *"Hold effort constant within cached conversations."* [effort](https://platform.claude.com/docs/en/build-with-claude/effort)

## 3.3 Rate limits

Spend caps por tier: Start $500/mês · Build $1.000 · Scale $200.000 · Custom sem cap. [rate-limits](https://platform.claude.com/docs/en/api/rate-limits)

| Tier | Sonnet 5 RPM / ITPM / OTPM | Haiku 4.5 RPM / ITPM / OTPM |
|---|---|---|
| Start | 1.000 / 2.000.000 / 400.000 | 1.000 / 2.000.000 / 400.000 |
| Build | 5.000 / 5.000.000 / 1.000.000 | 5.000 / 5.000.000 / 1.000.000 |
| Scale | 10.000 / 10.000.000 / 2.000.000 | 10.000 / 10.000.000 / 2.000.000 |

Fonte: [rate-limits](https://platform.claude.com/docs/en/api/rate-limits)

Pontos que importam:
- ⚠️ **Tokens lidos do cache NÃO contam para o ITPM** (exceto Haiku 3.5, já aposentado). Verbatim: *"For most Claude models, only uncached input tokens count toward your ITPM rate limits."* Com 80% de hit rate, um limite de 2M ITPM comporta ~10M tokens/min reais. [rate-limits](https://platform.claude.com/docs/en/api/rate-limits)
- **Sonnet 5 tem bucket separado** dos Sonnet 4.x; o Opus 4.x compartilha bucket entre si. [rate-limits](https://platform.claude.com/docs/en/api/rate-limits)
- `max_tokens` **não** entra no cálculo de OTPM — só os tokens realmente gerados. [rate-limits](https://platform.claude.com/docs/en/api/rate-limits)
- Subida de tier: automática por histórico de uso e situação da conta; organizações novas podem começar num **Evaluation tier** com limites abaixo da tabela. Aumento sob demanda via **Request rate limit increase** no Console. [rate-limits](https://platform.claude.com/docs/en/api/rate-limits)
- Algoritmo: **token bucket** (reposição contínua, não reset em janela fixa). [rate-limits](https://platform.claude.com/docs/en/api/rate-limits)

## 3.4 Versionamento e depreciação ✅ (o mais forte dos quatro)

| Pergunta | Resposta da doc | Fonte |
|---|---|---|
| Snapshots datados? | **Sim, sempre.** Verbatim: *"Every Claude model ID is a pinned snapshot… Starting with the Claude 4.6 generation, model IDs use a dateless format that is also a pinned snapshot, not an evergreen pointer."* | [models/overview](https://platform.claude.com/docs/en/about-claude/models/overview) |
| Aliases mudam sob os pés? | **Não** nos modelos 4.6+ — `claude-sonnet-5` já É o snapshot. Em modelos pré-4.6, o alias é um ponteiro de conveniência para um ID datado | [models/overview](https://platform.claude.com/docs/en/about-claude/models/overview) |
| Aviso prévio | *"Anthropic notifies customers with active deployments for models with upcoming retirements, providing at least **60 days' notice** before model retirement for publicly released models."* | [model-deprecations](https://platform.claude.com/docs/en/about-claude/model-deprecations) |
| Ciclo de vida | Active → Legacy → Deprecated (com substituto e data) → Retired (requisições falham) | [model-deprecations](https://platform.claude.com/docs/en/about-claude/model-deprecations) |
| Datas de aposentadoria | `claude-sonnet-5`: **não antes de 30/06/2027** · `claude-haiku-4-5-20251001`: **não antes de 15/10/2026** | [model-deprecations](https://platform.claude.com/docs/en/about-claude/model-deprecations) |
| Auditoria de uso | Export CSV na página Usage do Console, por API key e modelo | [model-deprecations](https://platform.claude.com/docs/en/about-claude/model-deprecations) |

**Leitura para o Barra:** é o único provedor que garante por escrito que o ID chamado é imutável. Evals medidos contra `claude-sonnet-5` são reprodutíveis até a aposentadoria anunciada com 60 dias.

⚠️ **Depreciação de parâmetro relevante:** `temperature`, `top_p`, `top_k` retornam **400** quando setados com valor não-default em modelos 4.7+. [model-deprecations](https://platform.claude.com/docs/en/about-claude/model-deprecations)

## 3.5 Structured outputs e tool calling

Modelos suportados incluem `claude-sonnet-5` e `claude-haiku-4-5-20251001`. [structured-outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)

| Item | Detalhe |
|---|---|
| Modo | `output_config.format` (formato da resposta) e `strict: true` em tools (validação de parâmetros) |
| Suportado | object, array, string, integer, number, boolean, null; `enum`, `const`, `required`, `additionalProperties: false`; `anyOf`, `allOf` (com limitações); `$ref`/`$def`/`definitions` internos; formatos `date-time`, `time`, `date`, `duration`, `email`, `hostname`, `uri`, `ipv4`, `ipv6`, `uuid`; `minItems` **apenas 0 ou 1**; `default` |
| **Não suportado** (verbatim) | *"Recursive schemas, Complex types within enums, External `$ref`…, Numerical constraints (such as `minimum`, `maximum`, `multipleOf`), String constraints (`minLength`, `maxLength`), Array constraints beyond `minItems` of 0 or 1, `additionalProperties` set to anything other than `false`"* |
| Regex em `pattern` | Suporta quantificadores, classes e grupos; **não** suporta backreferences, lookahead/lookbehind, word boundaries |
| Compilação | Primeira requisição com um schema paga latência de compilação de gramática; gramáticas ficam em cache por **24h**; mudança de estrutura invalida |
| Efeito no prompt cache | ⚠️ Mudar `output_config.format` **invalida o prompt cache** da conversa |
| Incompatibilidades | Citations retorna 400; prefill de assistant não é suportado |

Fonte de toda a tabela: [structured-outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)

**Diferença material vs. OpenAI:** a Anthropic **não suporta schemas recursivos**; a OpenAI suporta. Se a extração de estado do Barra tiver estrutura auto-referente, isso é bloqueante do lado Anthropic.

## 3.6 Reasoning / thinking / effort

| Item | Sonnet 5 | Haiku 4.5 | Fonte |
|---|---|---|---|
| Adaptive thinking | **Sim** | ⚠️ **Não** | [models/overview](https://platform.claude.com/docs/en/about-claude/models/overview) |
| Extended thinking (`thinking.type: "enabled"` + `budget_tokens`) | Não | **Sim** | [models/overview](https://platform.claude.com/docs/en/about-claude/models/overview) |
| Parâmetro `effort` | **Sim** (`low`/`medium`/`high`/`xhigh`/`max`) | ⚠️ **Não listado entre os modelos suportados** | [effort](https://platform.claude.com/docs/en/build-with-claude/effort) |
| Default de effort | **`high`** — *"Setting `effort` to `"high"` produces exactly the same behavior as omitting the `effort` parameter entirely."* | n/a | [effort](https://platform.claude.com/docs/en/build-with-claude/effort) |
| Cobrança do raciocínio | *"the tokens Claude spends reasoning are billed as output tokens, even when the thinking text isn't returned to you, and they count toward `max_tokens` alongside the response text."* | idem | [thinking](https://platform.claude.com/docs/en/build-with-claude/thinking) |
| Effort recomendado (Sonnet 5) | `high` default; `xhigh` para coding/agentic difícil; `medium` como economia (comparável a Sonnet 4.6 em high); **`low` para workloads de alto volume/latência-sensíveis, chat e casos não-coding** | [effort](https://platform.claude.com/docs/en/build-with-claude/effort) |
| Efeito de effort em tool use | Effort baixo → menos tool calls, mais consolidadas, sem preâmbulo; effort alto → mais tool calls, plano antes da ação, resumos detalhados | [effort](https://platform.claude.com/docs/en/build-with-claude/effort) |
| Latência | Métricas numéricas **não documentadas**; a doc dá orientação qualitativa ("comparative latency: Fast" para Sonnet 5, "Fastest" para Haiku 4.5) | [models/overview](https://platform.claude.com/docs/en/about-claude/models/overview) |

**Leitura para o Barra:** para chamada síncrona no caminho da resposta do WhatsApp, a recomendação oficial para Sonnet 5 é literalmente o caso de uso do Barra — `low` effort para "chat and non-coding use cases where faster turnaround is prioritized". E `effort` **precisa ficar constante** dentro da conversa por causa do cache.

## 3.7 Política de conteúdo adulto ⚠️

**Usage Policy, vigente desde 15/09/2025 — seção "Do Not Generate Sexually Explicit Content", reproduzida integralmente** ([anthropic.com/legal/aup](https://www.anthropic.com/legal/aup)):

> **Do Not Generate Sexually Explicit Content**
> This includes using our products or services to:
> - Depict or request sexual intercourse or sex acts
> - Generate content related to sexual fetishes or fantasies
> - Facilitate, promote, or depict incest or bestiality
> - Engage in erotic chats

A política **não traz exceções, provisões de verificação de idade, nem carve-outs para plataformas adultas** nesta seção. Ela está nas **Universal Usage Standards** — o tier que se aplica a todos os usuários e todos os casos de uso. [aup](https://www.anthropic.com/legal/aup)

**Additional Use Case Guidelines — chatbots ao consumidor** ([aup](https://www.anthropic.com/legal/aup)):
> *"All consumer-facing chatbots, including any external-facing or interactive AI agent, must disclose to users that they are interacting with AI rather than a human."* — e a divulgação *"must be provided at a minimum at the beginning of each chat session."*

⚠️ **Duas implicações para o Barra**, ambas diretas: (1) "Generate content related to sexual fetishes or fantasies" é um bullet universal, e o Barra opera um catálogo de fetiches como parte do produto; (2) a exigência de divulgar que o interlocutor é IA **no início de cada sessão de chat** conflita com um agente que se apresenta como a modelo no WhatsApp. Nenhuma das duas depende de interpretação — estão escritas na política.

## 3.8 Dados de API e regiões

| Item | O que a doc diz | Fonte |
|---|---|---|
| Treino | **Commercial Terms (vigentes 17/06/2025), §B:** *"Anthropic may not train models on Customer Content from Services."* | [commercial-terms](https://www.anthropic.com/legal/commercial-terms) |
| Retenção padrão | *"Conversation content (your prompts and Claude's outputs) is not retained by default"* — exceto Covered Models (Fable 5 / Mythos 5), que exigem 30 dias | [api-and-data-retention](https://platform.claude.com/docs/en/manage-claude/api-and-data-retention) |
| ⚠️ Conteúdo flagrado | *"if a chat or session is flagged, Anthropic may retain inputs and outputs for **up to 2 years**"* — vale **mesmo com ZDR** | [api-and-data-retention](https://platform.claude.com/docs/en/manage-claude/api-and-data-retention) |
| ZDR | Sob contrato, via time de vendas; habilitado por organização. Messages API e Token Counting são elegíveis; Batch, Files, code execution, Managed Agents **não são** | [api-and-data-retention](https://platform.claude.com/docs/en/manage-claude/api-and-data-retention) |
| Structured outputs sob ZDR | "Yes (qualified)": prompts não são armazenados, mas **o JSON schema fica em cache por até 24h** | [api-and-data-retention](https://platform.claude.com/docs/en/manage-claude/api-and-data-retention) |
| Prompt caching sob ZDR | "Yes": representações KV e hashes em memória pelo TTL, apagados na expiração | [api-and-data-retention](https://platform.claude.com/docs/en/manage-claude/api-and-data-retention) |
| Regiões | `inference_geo`: apenas **`"global"`** (default) e **`"us"`**. Workspace geo: apenas **`"us"`**, imutável após criação | [data-residency](https://platform.claude.com/docs/en/manage-claude/data-residency) |
| **América do Sul** | ⚠️ **Não existe.** Limitação declarada: *"Inference geo: Only `"us"` and `"global"` are available."* | [data-residency](https://platform.claude.com/docs/en/manage-claude/data-residency) |
| Latência p/ América do Sul | **Não documentado** |  |

⚠️ **Contradição prática do domínio:** um agente do domínio adulto, se sinalizado pelos sistemas automatizados de trust & safety, tem input e output retidos por até 2 anos — inclusive PII de clientes. Isso é o oposto do perfil de risco que o projeto quer.

---

# 4. Google — Gemini 3.6 Flash e Flash-Lite

## 4.1 Preço listado (USD por 1M tokens, tier pago)

| Modelo | Input | Output | Context caching | Cache storage | Fonte |
|---|---|---|---|---|---|
| **`gemini-3.6-flash`** | **$1,50** | **$7,50** | $0,15 | $1,00 / 1M tokens / hora | [pricing](https://ai.google.dev/gemini-api/docs/pricing) |
| `gemini-3.5-flash` | $1,50 | $9,00 | $0,15 | $1,00 / 1M tokens / hora | [pricing](https://ai.google.dev/gemini-api/docs/pricing) |
| **`gemini-3.5-flash-lite`** | **$0,30** | **$2,50** | $0,03 | $1,00 / 1M tokens / hora | [pricing](https://ai.google.dev/gemini-api/docs/pricing) |
| **`gemini-3.1-flash-lite`** | **$0,25** (texto/imagem/vídeo); $0,50 (áudio) | **$1,50** | $0,025 (texto) / $0,05 (áudio) | $1,00 / 1M tokens / hora | [pricing](https://ai.google.dev/gemini-api/docs/pricing) |

Batch tier = **metade** do preço standard em todos eles ([pricing](https://ai.google.dev/gemini-api/docs/pricing)).

⚠️ **Modelo de custo diferente dos outros três:** o Google cobra **armazenamento de cache por hora** ($1,00 por 1M tokens por hora), além do preço por token cacheado. Para um prompt de 50k tokens mantido em cache por 1h, isso é ~$0,05/hora **por conversa em cache** — custo que não existe em OpenAI, Anthropic ou DeepSeek.

## 4.2 Context caching

| Item | O que a doc diz | Fonte |
|---|---|---|
| Implícito (automático) | *"Implicit caching is enabled by default for all Gemini 2.5 and newer models"* — *"There is nothing you need to do in order to enable this"* | [caching](https://ai.google.dev/gemini-api/docs/caching) |
| Mínimo de tokens | Gemini 3.5 Flash: **4.096** · Gemini 3.1 Pro Preview: 4.096 · Gemini 2.5 Flash/Pro: 2.048. ⚠️ **Mínimo para 3.6 Flash e Flash-Lite: não documentado** nesta página | [caching](https://ai.google.dev/gemini-api/docs/caching) |
| Explícito | ⚠️ *"The Interactions API does not support explicit caching."* — para gerenciar objetos de cache manualmente é preciso *"switch to the generateContent API"* | [caching](https://ai.google.dev/gemini-api/docs/caching) |
| TTL | **Não documentado** na página de caching |  |
| Prefixo idêntico | **Não afirmado explicitamente.** A doc dá dicas heurísticas: pôr conteúdo grande e reutilizado no início do prompt e enviar requisições parecidas em janelas curtas de tempo | [caching](https://ai.google.dev/gemini-api/docs/caching) |
| Verificação | `usage.total_cached_tokens` | [caching](https://ai.google.dev/gemini-api/docs/caching) |
| O que invalida | **Não documentado** |  |

**Leitura para o Barra:** é o cache menos especificado dos quatro. Não há garantia contratual de hit por prefixo idêntico — a doc trata como otimização best-effort ("increase cache hit likelihood"). Para um custo de produção previsível, isso é uma variável solta.

## 4.3 Rate limits ⚠️

| Item | O que a doc diz | Fonte |
|---|---|---|
| Métricas | RPM, TPM, RPD — estourar qualquer uma gera erro | [rate-limits](https://ai.google.dev/gemini-api/docs/rate-limits) |
| **Números por modelo** | ⚠️ **Não documentados na doc pública.** Verbatim: *"Rate limits depend on a variety of factors (such as your usage tier) and can be viewed in Google AI Studio."* — exigem login no AI Studio | [rate-limits](https://ai.google.dev/gemini-api/docs/rate-limits) |
| Tiers e qualificação | Free (projeto ativo) · **Tier 1**: conta de faturamento ativa vinculada, cap $250 · **Tier 2**: $100+ pagos e 3+ dias do primeiro pagamento, cap $2.000 · **Tier 3**: $1.000+ pagos e 30+ dias, cap $20.000–$100.000+ | [rate-limits](https://ai.google.dev/gemini-api/docs/rate-limits) |
| Limite de gasto em janela | Rolling de 10 minutos: Tier 1 $10 · Tier 2 $200 · Tier 3 $200 | [rate-limits](https://ai.google.dev/gemini-api/docs/rate-limits) |
| Velocidade do upgrade | *"Tier upgrades from the Free to Tier 1 will typically take effect instantly, and subsequent tier upgrades will take effect within 10 minutes."* | [rate-limits](https://ai.google.dev/gemini-api/docs/rate-limits) |

## 4.4 Versionamento e depreciação ⚠️

A página canônica `ai.google.dev/gemini-api/docs/model-versions` retornou **404** — não há política de versionamento legível nessa URL. O que é possível documentar vem do changelog ([changelog](https://ai.google.dev/gemini-api/docs/changelog)):

| Evento | Data | O que mostra |
|---|---|---|
| `gemini-3-pro-preview` lançado | 18/11/2025 | ciclo preview → GA |
| Alias `gemini-pro-latest` repontado para 3 Pro Preview | 21/01/2026 | ⚠️ **aliases `-latest` mudam de modelo sob os pés** |
| Alias `gemini-flash-latest` repontado para `gemini-3-flash-preview` | 21/01/2026 | idem |
| `gemini-3-pro-preview` desligado; **passa a redirecionar** para `gemini-3.1-pro-preview` | 09/03/2026 | ⚠️ **um ID de preview explícito passou a servir outro modelo** — não só o alias |
| `gemini-3.1-flash-lite` preview → GA | 03/03/2026 → 07/05/2026 | ~2 meses de preview |
| `gemini-3.6-flash` e `gemini-3.5-flash-lite` GA | 21/07/2026 | modelos deste levantamento |

- **Snapshots datados chamáveis:** **não documentados** — os IDs estáveis são `gemini-3.6-flash`, `gemini-3.5-flash-lite`, sem sufixo de data.
- **Período de aviso prévio:** **não documentado** em nenhuma página oficial acessível.
- **Por quanto tempo um modelo estável fica disponível:** **não documentado**.

**Risco para os evals do Barra:** intermediário entre DeepSeek e Anthropic. IDs estáveis (não-preview) não foram observados mudando de modelo, mas o precedente de 09/03/2026 mostra que a Google **redireciona IDs**, não apenas aliases, e não há política escrita que impeça isso.

## 4.5 Structured outputs e function calling

| Item | O que a doc diz | Fonte |
|---|---|---|
| Mecanismo | `response_format` com `type: "text"`, `mime_type: "application/json"` e `schema` | [structured-output](https://ai.google.dev/gemini-api/docs/structured-output) |
| Keywords suportadas | tipos string/number/integer/boolean/object/array/null; `title`, `description`; `properties`, `required`, `additionalProperties`; `enum`, `format` (date-time, date, time); `minimum`, `maximum`; `items`, `prefixItems`, `minItems`, `maxItems` | [structured-output](https://ai.google.dev/gemini-api/docs/structured-output) |
| Limites numéricos (nesting, nº properties, enums) | ⚠️ **Não documentados.** A doc só diz: *"Very large or deeply nested schemas may be rejected"* e *"Not all JSON Schema features are supported."* | [structured-output](https://ai.google.dev/gemini-api/docs/structured-output) |
| Modo estrito vs. melhor esforço | Não há flag `strict` documentada em structured outputs. Em function calling existe o modo **`validated`**, que *"ensures function schema adherence"* | [function-calling](https://ai.google.dev/gemini-api/docs/function-calling) |
| Modos de tool choice | `auto` (default) / `any` / `none` / `validated` | [function-calling](https://ai.google.dev/gemini-api/docs/function-calling) |
| Schema de funções | *"only a subset of the OpenAPI schema is supported"*, com limitações em schemas grandes/aninhados no modo `any` | [function-calling](https://ai.google.dev/gemini-api/docs/function-calling) |
| Parallel / compositional | Ambos suportados | [function-calling](https://ai.google.dev/gemini-api/docs/function-calling) |
| Nº de tools | Recomendação de **10–20 tools ativas no máximo** | [function-calling](https://ai.google.dev/gemini-api/docs/function-calling) |
| Structured output + tools juntos | ⚠️ **preview**, limitado à série Gemini 3 | [structured-output](https://ai.google.dev/gemini-api/docs/structured-output) |

## 4.6 Thinking

| Item | O que a doc diz | Fonte |
|---|---|---|
| Parâmetro | `thinking_level`: `minimal`, `low`, `medium`, `high` | [thinking](https://ai.google.dev/gemini-api/docs/thinking) |
| Defaults | `gemini-3.6-flash`: **medium** (ligado por padrão) · `gemini-3.5-flash-lite`: **minimal** (ligado) · `gemini-3-flash-preview` / `gemini-3-pro-preview` / `gemini-3.1-pro-preview`: **high** | [thinking](https://ai.google.dev/gemini-api/docs/thinking) |
| Default do `gemini-3.1-flash-lite` | **Não documentado** na tabela (a doc lista `gemini-3.1-flash-lite-image` como minimal) | [thinking](https://ai.google.dev/gemini-api/docs/thinking) |
| Desligar completamente | ⚠️ **Não documentado** que seja possível — todas as variantes listadas têm thinking "On" por padrão | [thinking](https://ai.google.dev/gemini-api/docs/thinking) |
| Cobrança | **Sim.** Verbatim: *"response pricing is the sum of output tokens and thinking tokens."* Contagem em `interaction.usage.total_thought_tokens` | [thinking](https://ai.google.dev/gemini-api/docs/thinking) |
| Thought signatures | ⚠️ Em modo stateless, *"you **MUST** always resend all `thought` blocks exactly as they were received"*. Em modo stateful a Interactions API cuida disso; nas function calls os SDKs lidam automaticamente | [thinking](https://ai.google.dev/gemini-api/docs/thinking) · [function-calling](https://ai.google.dev/gemini-api/docs/function-calling) |
| Latência | **Não documentada** | [thinking](https://ai.google.dev/gemini-api/docs/thinking) |

⚠️ **Para o Barra:** o requisito de reenviar thought blocks intactos em modo stateless é uma restrição de arquitetura, não um detalhe — o histórico persistido do agente teria que carregar esses blocos verbatim, e qualquer normalização/reescrita do histórico quebra a continuidade do raciocínio.

## 4.7 Política de conteúdo adulto

**Generative AI Prohibited Use Policy, vigente desde 17/12/2024** ([policies.google.com/terms/generative-ai/use-policy](https://policies.google.com/terms/generative-ai/use-policy)):

> **"Sexually explicit content -- for example, content created for the purpose of pornography or sexual gratification."**

Cláusula de exceção, verbatim:
> *"We may make exceptions to these policies based on educational, documentary, scientific, or artistic considerations, or where harms are outweighed by substantial benefits to the public."*

- **Prostituição / serviços de acompanhantes:** **não há cláusula** na política. [use-policy](https://policies.google.com/terms/generative-ai/use-policy)

**Safety filters — este é o diferencial material do Google** ([safety-settings](https://ai.google.dev/gemini-api/docs/safety-settings)):

| Item | Detalhe |
|---|---|
| Categorias ajustáveis | Harassment, Hate speech, **Sexually explicit** (*"Contains references to sexual acts or other lewd content"*), Dangerous |
| Thresholds | `OFF`, `BLOCK_NONE`, `BLOCK_ONLY_HIGH`, `BLOCK_MEDIUM_AND_ABOVE`, `BLOCK_LOW_AND_ABOVE`, `HARM_BLOCK_THRESHOLD_UNSPECIFIED` |
| Default | ⚠️ *"The default block threshold is **Off** for Gemini 2.5 and 3 models."* |
| Não ajustável | *"built-in protections against core harms, such as content that endangers child safety. These types of harm are always blocked and cannot be adjusted."* |

⚠️ **Distinção importante:** o filtro de segurança ser configurável para `OFF` **não é uma autorização de política de uso**. A Prohibited Use Policy continua proibindo conteúdo sexualmente explícito; o controle técnico e o compromisso contratual são camadas separadas. Não confundir "o modelo responde" com "o uso é permitido".

## 4.8 Dados de API e regiões

| Item | Tier pago | Tier gratuito | Fonte |
|---|---|---|---|
| Uso para treino | *"Google doesn't use your prompts (including associated system instructions, cached content, and files such as images, videos, or documents) or responses to improve our products"* | *"Google uses the content you submit to the Services and any generated responses to provide, improve, and develop Google products and services"* | [terms](https://ai.google.dev/gemini-api/terms) |
| Revisão humana | Não declarada para o tier pago | *"human reviewers may read, annotate, and process your API input and output"* | [terms](https://ai.google.dev/gemini-api/terms) |
| Retenção | Logs mantidos *"solely for detecting and preventing violations of the Prohibited Use Policy"*; prazo em dias **não documentado** | — | [terms](https://ai.google.dev/gemini-api/terms) |
| Grounding (Search/Maps) | ⚠️ **30 dias** de retenção *"for debugging and testing of systems"* — em **ambos** os tiers | idem | [terms](https://ai.google.dev/gemini-api/terms) |
| Como desativar | Usar o tier pago é o mecanismo documentado | — | [terms](https://ai.google.dev/gemini-api/terms) |

**Regiões** ([available-regions](https://ai.google.dev/gemini-api/docs/available-regions)):
- Gemini API disponível em **195+ países e territórios**, **incluindo o Brasil** explicitamente.
- Requisito de acesso: **18+ anos, com idade verificada na Conta Google**.
- ⚠️ **Onde as requisições são processadas: não documentado** nessa página. Não há garantia de residência de dados no tier da Gemini API (ai.google.dev).
- Regiões do Vertex AI (incl. `southamerica-east1` / São Paulo): **não foi possível ler a página oficial** — ver Lacunas.

---

# 5. Tabela comparativa para o caso do Barra

Custo por turno estimado com **40k tokens de prompt (90% em cache) + 400 tokens de saída**, usando apenas números da doc oficial:

| Modelo | Input não-cacheado (4k) | Input cacheado (36k) | Output (400) | **Total/turno** | Fonte de preço |
|---|---|---|---|---|---|
| `deepseek-v4-flash` | $0,00056 | $0,0001 | $0,00011 | **~$0,00077** | [DeepSeek pricing](https://api-docs.deepseek.com/quick_start/pricing/) |
| `gpt-5.6-luna` | $0,0008 | $0,00072 | $0,00048 | **~$0,0020** | [OpenAI pricing](https://developers.openai.com/api/docs/pricing) |
| `gemini-3.1-flash-lite` | $0,001 | $0,0009 | $0,0006 | **~$0,0025** + storage de cache/hora | [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing) |
| `claude-haiku-4-5` | $0,004 | $0,0036 | $0,002 | **~$0,0096** | [Anthropic pricing](https://platform.claude.com/docs/en/about-claude/pricing) |
| `gemini-3.5-flash-lite` | $0,0012 | $0,00108 | $0,001 | **~$0,0033** + storage | [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing) |
| `claude-sonnet-5` (intro) | $0,008 | $0,0072 | $0,004 | **~$0,019** | [Anthropic pricing](https://platform.claude.com/docs/en/about-claude/pricing) |
| `gemini-3.6-flash` | $0,006 | $0,0054 | $0,003 | **~$0,014** + storage | [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing) |

*(Aritmética derivada dos preços de tabela; não é número publicado por provedor. Exclui tokens de raciocínio, que são faturados como output em OpenAI, Anthropic e Google — e portanto podem dominar o total.)*

## Matriz de risco por eixo

| Eixo | DeepSeek | OpenAI | Anthropic | Google |
|---|---|---|---|---|
| **Evals reprodutíveis** | ❌ alias muda sem aviso, sem ID datado | ✅ 6 meses de aviso; ID = snapshot | ✅✅ ID é snapshot fixado + 60 dias de aviso | ⚠️ sem política escrita; precedente de redirect de ID |
| **Cache p/ prefixo estável** | ✅ automático, sem esforço; TTL incerto | ✅ TTL 30 min + `prompt_cache_key` | ✅ 4 breakpoints, controle fino; effort trava o cache | ⚠️ best-effort; cobra storage/hora |
| **Custo por turno** | ✅✅ o mais barato por ~2,6x | ✅ | ❌ 5–25x o DeepSeek | ⚠️ intermediário + storage |
| **Structured outputs** | ⚠️ strict só em beta; JSON mode com bug de resposta vazia | ✅✅ limites publicados, recursão suportada | ✅ limites publicados; **sem recursão** | ⚠️ limites não publicados |
| **Política de conteúdo adulto** | ⚠️ silente (nada permite, nada proíbe explicitamente) | ❌ Model Spec proíbe erótica; moderação nomeia "promotes sexual services" | ❌❌ proibição universal explícita + exigência de divulgar IA por sessão | ❌ PUP proíbe; filtros configuráveis ≠ permissão |
| **Dados / LGPD** | ❌❌ armazenado na China, treino sem opt-out documentado | ✅ sem treino; ZDR sob aprovação; sem região BR | ✅ sem treino por contrato; ⚠️ 2 anos se flagrado | ⚠️ tier pago sem treino; retenção sem prazo publicado |
| **Região América do Sul** | ❌ não documentado | ❌ não ofertado | ❌ só `us` / `global` | ⚠️ API disponível no BR; processamento não documentado |

---

# 6. Lacunas: o que a documentação oficial NÃO responde

## 6.1 Lacunas transversais (nenhum dos quatro documenta)

1. **Latência.** Nenhum provedor publica p50/p95 de time-to-first-token ou tokens/s por modelo. A Anthropic dá apenas rótulos qualitativos ("Fast", "Fastest"); os outros três não dão nada. Para uma chamada síncrona no caminho da resposta do WhatsApp, **o eixo mais importante da decisão é o único que nenhuma doc oficial responde.** Só medição própria resolve.
2. **Desempenho para América do Sul.** Nenhuma doc traz região, PoP, roteamento ou latência esperada a partir do Brasil. O Gemini declara *disponibilidade* no Brasil, o que não é o mesmo que processamento regional.
3. **Serviços de acompanhantes / prostituição.** Nenhum dos quatro tem cláusula nomeando escort services ou prostituição na política de uso. A única menção funcionalmente próxima em toda a documentação lida está numa **definição de categoria de classificador** da OpenAI ("or that promotes sexual services"), não numa cláusula de proibição. O domínio do Barra cai numa zona que as políticas cobrem por implicação (conteúdo sexualmente explícito), não por nomeação.
4. **Efeito de conteúdo adulto no comportamento de recusa.** Nenhuma doc quantifica taxa de recusa por domínio, nem oferece um caminho de allowlisting/aprovação para casos adultos legítimos.
5. **Interação entre tokens de raciocínio e cache.** Nenhum provedor documenta se/como o raciocínio de turnos anteriores participa do prefixo cacheado no turno seguinte.

## 6.2 Lacunas específicas por provedor

**DeepSeek**
- Preço de escrita de cache: não documentado.
- Intervalo de tokens em que as "cache prefix units" são criadas: não documentado.
- TTL de cache: só o intervalo vago "a few hours to a few days".
- Política de depreciação/versionamento: **não existe página**.
- Default de `thinking` e se `reasoning_tokens` são faturados como output: não documentado.
- Parallel tool calls, profundidade de schema, limites de properties: não documentados.
- Mecanismo concreto de opt-out de treino: mencionado como direito, sem procedimento.
- ⚠️ A razão cache-hit/cache-miss (1/50 e 1/120) foge do padrão do mercado e merece confirmação em fatura.

**OpenAI**
- ⚠️ **A Usage Policy não pôde ser lida (HTTP 403).** O tratamento de conteúdo adulto neste documento vem do Model Spec e da doc de moderação — primários, mas não são a política de uso contratual. **Isto é uma lacuna de método, não do provedor:** a página precisa ser lida por um humano no navegador antes de qualquer decisão.
- Quais níveis de `reasoning_effort` o `gpt-5.6-luna` especificamente suporta: não documentado na página do modelo.
- Se tokens cacheados contam para o TPM: não documentado.
- Data residency para América do Sul: não ofertada (isto é um fato documentado, não uma lacuna).

**Anthropic**
- Latência numérica por modelo e por nível de effort: não documentada.
- Se `effort` é suportado no Haiku 4.5: o modelo **não aparece** na lista de suportados da doc de effort, mas a doc não afirma negativamente. Ambiguidade a testar empiricamente.
- Prazos de retenção detalhados: os Commercial Terms remetem ao Data Processing Addendum, que não foi lido.
- Nenhuma opção de residência de dados fora de `us`/`global`.

**Google**
- ⚠️ **Números de rate limit por modelo não existem na doc pública** — exigem login no AI Studio. Impossível dimensionar capacidade a partir da documentação.
- ⚠️ **Página de model-versions retorna 404** — não há política de versionamento/depreciação legível.
- Mínimo de tokens para cache implícito em `gemini-3.6-flash` e nos Flash-Lite: não documentado (só 3.5 Flash e 2.5 estão na tabela).
- TTL de cache, regras de invalidação e requisito de prefixo idêntico: não documentados.
- Limites numéricos de JSON Schema (nesting, properties, enums): não documentados.
- Se thinking pode ser completamente desligado nos modelos 3.x: não documentado.
- Default de `thinking_level` do `gemini-3.1-flash-lite`: ausente da tabela.
- Prazo de retenção de logs no tier pago: não documentado.
- ⚠️ **Regiões do Vertex AI** (incl. `southamerica-east1`): as páginas oficiais de locations redirecionaram para conteúdo sem a tabela. Não confirmado por fonte primária.

## 6.3 O que precisa de verificação humana antes de decidir

1. Abrir `https://openai.com/policies/usage-policies` num navegador e ler a seção de conteúdo adulto — é a única fonte contratual da OpenAI sobre o tema e ficou inacessível por automação.
2. Abrir o AI Studio logado para extrair os rate limits reais por modelo Gemini.
3. Confirmar os preços de cache-hit do DeepSeek numa fatura real.
4. Medir latência p50/p95 a partir da infra do Barra (São Paulo) contra os quatro endpoints — nenhum número oficial existe para isso.
5. Ler o Data Processing Addendum da Anthropic para os prazos de retenção que os Commercial Terms não trazem.
