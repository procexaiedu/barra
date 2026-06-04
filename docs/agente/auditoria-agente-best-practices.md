# Auditoria do Agente: as-built x requisitos x best practices

> **Para:** Fernando (operador) + dev · **Escopo:** agente conversacional Elite Baby (LangGraph 1.x + Anthropic Sonnet 4.6, P0/MVP) · **Base:** 7 dossiês de engenharia as-built, 5 checklists de best practices (LangGraph, Anthropic, Segurança, Evals, Confiabilidade), 5 auditorias e 33 verificações adversariais.
>
> _Gerado por workflow multi-agente (54 agentes, 2026-06-02). O código é a fonte de verdade onde divergir dos docs._

---

## 0. Status de implementação (2026-06-02, pós-auditoria — `main` `0dc2de8`)

Esta auditoria é o retrato **"como encontrado"**. O que já foi endereçado desde então (commits `a0f452a` feat-segurança + `0dc2de8` docs+evals, em `origin/main`):

| Item | Status | Onde / o que |
|---|---|---|
| **A1** — Gate de saída na fronteira de envio (SEC-OUT-01) | ✅ **Feito** | `workers/_saida_guard.py` + `enviar_turno`: bloqueia+escala bolha que admite ser IA (reusa `tem_marcador_ia`); cobre os caminhos canned/reengajamento que pulavam o `output_guard`. |
| **A2** — Não-eco de PII + reincidência (SEC-PII-02 / SEC-JB-02) | ✅ **Feito** | Redação de PII **por eco** (só mascara o que veio do inbound do cliente → **nunca a chave Pix da modelo**; CEP/endereço fora). Contador de disclosure/jailbreak por **telefone** (Redis, 24h) escala 3/24h a Fernando **sem bloquear** o cliente. |
| **A3** — Ofuscação + CI de evals (SEC-PI-05 / EVAL-03) | ◑ **Parcial** | `evals.yml` já estava pronto (outro agente). +2 fixtures de ofuscação (Base64, leetspeak/emoji) como **capability/advisory**. **Aberto:** graduar fixtures a `gate:regressao` (exige run live) + secrets/branch-protection (operador). |
| **A4** — Calibrar o judge (EVAL-01/07/10) | ⬜ **Outro fluxo** | Interface de rotulagem do golden já em `main`; calibração conduzida em paralelo. |
| **A5** — Métricas de tool no runner (AGT-08) | ⬜ **Aberto** | Adiado: instrumentação não-verificável sem **run live** de evals (créditos Anthropic esgotados). |
| Docs defasados (§6) — `01`/`02` | ✅ **Feito** | `01-arquitetura`: 5→6 nós + `output_guard` no diagrama/mapa. `02-estado-fluxo`: `_confianca: str` (era `float`). |

**Verificação:** 631 testes sem-DB verdes + 27 novos/ajustados; mypy/ruff limpos; **3 revisores especializados** (isolamento-de-domínio ✅ sem violação · segurança · LangGraph) com correções aplicadas (RG sem pontuação na redação; reincidência não queima a janela de 24h em falha de DB; docstring de replay-safety preciso). As frentes A3/A5 restantes dependem de um **run live de evals** (bloqueado por créditos) e de ação do operador no GitHub.

---

## 1. Como o agente foi desenvolvido (as-built)

### 1.1 O esqueleto: um grafo de 6 nós, sem checkpointer

O agente é um **`StateGraph` custom do LangGraph 1.x** (não `create_react_agent`, deprecado na v1.0), montado em `build_graph()` (`api/src/barra/agente/graph.py:43-80`) e compilado **sem checkpointer no P0** (`builder.compile(checkpointer=None)`, decisão de grilling 2026-05-22, doc 01 §6.7). São **6 nós**:

1. **`prepare_context`** (`agente/nos/prepare_context.py:60-139`) — dono único do contexto e gate de pausa.
2. **`intercept_disclosure`** (`agente/nos/intercept_disclosure.py:37-109`) — primeira rede de defesa.
3. **`llm`** (`agente/nos/llm.py:68-131`) — chamada real ao Sonnet 4.6 via `ChatAnthropic`.
4. **`tools`** (`agente/nos/tools.py:28-88`) — `ToolNode` subclassado.
5. **`post_process`** (`agente/nos/post_process.py:21-35`) — refetch de pausa (cinto-suspensório).
6. **`output_guard`** (`agente/nos/output_guard.py:188-244`) — última rede antes da bolha (ADR 0016).

> Nota: a doc `docs/agente/01-arquitetura.md` ainda descreve "5 nós" e omite `output_guard` no diagrama — **documentação defasada vs. código** (ver §6).

O roteamento **não usa arestas condicionais nem flags de estado**: cada nó decide via `Command(goto=...)`. Existem **apenas 3 arestas estáticas** (`START→prepare_context`; `tools→llm` para fechar o loop ReAct; `post_process→output_guard`). Os nós que podem encerrar o turno (`prepare_context`, `intercept_disclosure`, `llm`, `output_guard`) **não têm aresta estática de saída** — porque uma aresta estática coexistindo com um `Command(goto=END)` causaria *fan-out* (o `llm` rodaria mesmo com a IA pausada — armadilha verificada M0-T4, `graph.py:70-77`).

### 1.2 Estado efêmero + dependências fora do State

O `EstadoAgente` (`agente/estado.py:16-39`) é um `MessagesState` minimalista: `messages` (reducer `add_messages`) + 3 campos transitórios por invocação (`midia_idx`, `_categoria`, `_confianca`). **Sem checkpointer, o State nasce zerado e morre a cada `ainvoke`.** As dependências de runtime (`db_pool`, `redis`) e IDs de escopo (`modelo_id`, `atendimento_id`, `cliente_id`, `turno_id`) **não vivem no State nem em `config['configurable']`** — vivem no `ContextAgente` (dataclass, `agente/contexto.py:23-41`) injetado via **Runtime Context API** (`graph.ainvoke(state, context=ContextAgente(...))`). Motivo técnico: o checkpointer serializaria o `configurable` e quebraria com pool/redis não-serializáveis (langgraph#3441) quando religado no P1. Só `thread_id` (=`conversa_id`) fica em `configurable`.

### 1.3 O fluxo de um turno, ponta a ponta

O turno **não é modelado dentro do grafo** — é orquestrado pelo coordenador ARQ (`workers/coordenador.py`):

1. **Webhook fino** (`webhook/routes.py`) — valida token (HMAC tempo-constante) → teto de corpo → JID allowlist; persiste a mensagem órfã, baixa a mídia 1x e sobe ao MinIO, e **só enfileira**. Áudio dispara `transcrever_audio`+turno; imagem dispara `rotear_imagem`; texto dispara o turno direto.

2. **Debounce + coalescing** — rajadas do mesmo cliente são agrupadas (`_job_id` estático `turno:{conversa_id}`, first-wins, `_defer_by=4s`). O coordenador roda um **drain loop bounded** (`MAX_DRAIN=5`) e processa o burst inteiro num turno. `turno_id = uuid5(NS_TURNO, job_id:score:loop_idx)` — determinístico, base da idempotência no replay.

3. **`prepare_context`** — (a) lê `ia_pausada`; se pausada → `Command(goto=END)` sem montar contexto; (b) carrega a **janela deslizante de 20 mensagens isolada pelo par `(cliente_id, modelo_id)` JUNTOS** (`prepare_context.py:142-165`); (c) **classifica disclosure/jailbreak** via `classificar_janela` (regex sobre a cauda de `HumanMessage`, `_classificador.py:46-77`) e grava `_categoria`/`_confianca`; (d) monta `BP_GERAL` (persona+regras+FAQ fundidos, byte-idêntico) + `BP_MODELO` (as "coisas dela") e concatena contexto dinâmico + reminder anti-drift no **último HumanMessage, fora do cache**.

4. **`intercept_disclosure`** — lê `_categoria`: `jailbreak_attempt` → `abrir_handoff` direto + END; `disclosure_attempt` alta → incrementa `atendimentos.disclosure_tentativas`, <3 devolve negação **canned** (`_canned.py`, pool curado em personagem — Sonnet resiste a negar identidade) e ≥3 escala; prova/ambíguo/None → `llm`.

5. **`llm`** — `chat_bound.ainvoke(state['messages'])` em Sonnet 4.6 (`thinking=disabled`, `effort=low`, `max_tokens=1024`, `max_retries=2`, `timeout=60`). Instrumenta tokens/custo, checa `stop_reason` (refusal/max_tokens em 200 OK), e roteia: tem `tool_calls` → `tools` (loop ReAct, teto `recursion_limit=18`); senão → `post_process`.

6. **`tools`** — executa via `_executar_idempotente`: `INSERT ... ON CONFLICT (turno_id, tool_name, call_idx) DO NOTHING` em `barravips.tool_calls`. **5 tools congeladas**: `consultar_agenda` (leitura), `registrar_extracao`, `pedir_pix_deslocamento`, `enviar_midia`, `escalar`. `strict:true` só em `escalar`.

7. **`post_process`** — refetch de `ia_pausada`; se pausou no meio do turno (Pix/foto-portaria sem lock), substitui a `AIMessage` por uma vazia de mesmo id.

8. **`output_guard`** (ADR 0016) — Etapa 1 determinística (scan de vazamento: auto-referência de IA, fragmento de system, nome/número de **outra modelo** montado do banco + legendas de mídia do turno); Etapa 2 LLM-judge de AUP vinculante (Sonnet, structured output). Bloquear = `abrir_handoff` + bolha vazia. **Falha de infra do judge → default seguro = bloqueia+escala.** Sempre `Command(goto=END)`.

9. **De volta no coordenador** — extrai o texto agregado das `AIMessage` (filtrado por `usage_metadata`), **re-lê `ia_pausada`/estado terminal** (cinto-suspensório), faz `chunk_texto` e despacha **UM job `enviar_turno`** que executa toda a **humanização real fora do grafo** (`workers/envio.py`): read receipt + reading delay, presence "digitando", quebra em bolhas, jitter, cancel-on-new-message, dedupe por set Redis, ordem texto→mídia.

### 1.4 Pipeline de mídia, STT, Pix — tudo fora do grafo

O agente é **cego à imagem no P0**. O único canal de mídia que chega ao LLM é a **transcrição de áudio** (Whisper via `transcrever_audio`), protegida por **spotlighting** (cerca derivada de `sha256(msg_id)[:8]`, marcada como DADO). Pix (`workers/pix.py`) usa vision via OpenRouter (`json_schema strict`) e aplica o veredito pela porta única `aplicar_comando('atualizar_pix')` — **nunca trava** (validado E em_revisão → `Confirmado`+`ia_pausada`). Foto de portaria → handoff implícito atômico, sem vision automática.

### 1.5 Evals: um gate executável de cutover

Em `api/evals/` há um **runner determinístico real** (`runners/runner.py`) que roda o grafo real multi-turno sem checkpointer contra um banco de teste (`TEST_DATABASE_URL`, nunca prod, rollback por amostra), com **graders puros** (`avaliar`/`gate`/`agregar_por_fixture`). **99 fixtures** (21 canônicas + 78 adversariais). Gate K=5 contando **fixtures** (não amostras): adversariais=`pass^k`, canônicos≥80%. LLM-judge (`runners/judge.py`) é **advisory** (`JUDGE_VINCULANTE=False`) até calibração contra golden humano (ADR 0015, ainda `proposed`).

---

## 2. O que o agente precisa ser (requisitos)

Destilado de `CONTEXT.md`, `docs/mvp/01–05`, `docs/agente/00,10` e ADRs 0004/0009/0013/0014/0015/0016. Os **dois invariantes de produto** que tudo protege:

- **Persona/voz/FAQ são GERAIS** — idênticas para todas as modelos. Só "as coisas dela" variam por modelo: identidade óbvia, programas/preços, tipos aceitos, **fetiches**. (override explícito de `CONTEXT.md` em `00-indice.md:53`).
- **Isolamento estrito por par `(cliente, modelo)`** — a IA da modelo A nunca acessa, cita ou se apoia em dado do cliente com a modelo B; não existe perfil único cross-modelo.

| Eixo | Requisito normativo |
|---|---|
| **Persona** | 4 atributos inegociáveis (objetiva, exclusiva, extrovertida, inocente/estrangeira), reforçados por few-shot. Credibilidade crítica: sem contradições/correções bruscas. |
| **Non-disclosure** | Nega ser IA na 1ª/2ª pergunta em personagem; 3ª insistência → escala `disclosure_insistente`. Modelo nomeado ("vc é Claude?") = mesmo balde do genérico. Ao escalar, **simplesmente para** (não se despede, não admite). |
| **Jailbreak** | DAN/"ignore previous"/`[system]`/`</persona>` → escala **direto** (`jailbreak_attempt`), sem deflecção nem contagem. |
| **Máquina de estados** | `Novo→Triagem→Qualificado→Aguardando_confirmacao→Confirmado→Em_execucao→Fechado\|Perdido`. **Determinística no coordenador**; a IA só dispara via `registrar_extracao`/`pedir_pix_deslocamento`. `pix_status`/`ia_pausada` são ortogonais, não estados. |
| **Handoff** | `escalar` é a **única porta** (pausa a IA, gera card na Coordenação por modelo). Devolução é comando explícito, nunca retomada automática. |
| **Escaladas/desconto** | Escala em: desconto abaixo do piso (`fora_de_oferta`), serviço não previsto, conflito de agenda, dúvida fora da FAQ, exaustão. **Desconto de fechamento** one-shot até o piso (`desconto_max_pct` global ~15%, nunca escrito no prompt; guarda determinística no código). Piso incide sobre o **pacote**, nunca sobre o Pix. |
| **Disclosure/AUP** | Não verbaliza termos explícitos, não inventa dados, não envia mídia não cadastrada. ADR 0015: LLM-judge advisory→vinculante após calibração. ADR 0016: output-guard antes da bolha (bloqueia+escala, nunca reescreve). |
| **Pix / portaria** | Externo: `pedir_pix_deslocamento` (R$100 fixo) → `Confirmado`+pausa, **Pix nunca trava** (duvidoso = fila assíncrona de Fernando). Interno: **Foto de portaria** (qualquer imagem em `Aguardando_confirmacao` interno) → handoff implícito, sem vision automática no P0. |
| **Agenda** | Horário em **bloqueio** → recusa com **desculpa pessoal** (nunca revela outro cliente). Horário **fora da Disponibilidade** → **revela a volta e ancora** na 1ª data. Bloqueio fora da disponibilidade → trava dura. |
| **Reengajamento / lembrete** | Reengajamento: 1 toque único ~30min pós-cotação, canned, sem desconto, **flag default OFF**. Lembrete de fechamento: cron determinístico cobrando o valor à modelo, **nunca marca `Perdido` por silêncio**, flag default ON. |

---

## 3. Aderência a best practices (scorecard)

> **Leitura dos status:** "Adotado" inclui casos onde a auditoria inicial apontou gap mas a **verificação adversarial refutou** (`verdict.lacuna_real=false`) — marcados com 🔄 **(auditoria inicial errou)** e a localização real. Os demais refletem o `status_corrigido` do verdict quando existente.

### 3.1 Arquitetura LangGraph — **~89% adotado** (16/18 plenos; 2 parciais; 0 ausentes)

| Prática | Status | Evidência | Prioridade |
|---|---|---|---|
| LG-01 State minimalista, deps fora do State | ✅ Adotado | `EstadoAgente`+`ContextAgente` (`estado.py:16-39`, `contexto.py:23-41`) | baixa |
| LG-02 Reducers só onde acumula | ✅ Adotado | `add_messages` herdado; escalares sem reducer | baixa |
| LG-03 Roteamento explícito, sem fan-out | ✅ Adotado | `graph.py:69-78`; testes dos 3 destinos Command | baixa |
| LG-04 Checkpointer = decisão consciente | ✅ Adotado | `checkpointer=None` registrado (01 §6.7) | baixa |
| LG-05 `thread_id` estável por conversa | ✅ Adotado | `coordenador.py:170-173` | baixa |
| LG-06 Durability mode | ➖ N/A (sem checkpointer no P0) | — | baixa |
| LG-07 Idempotência de side-effects | ✅ Adotado | `tool_calls` PK + `ON CONFLICT` (`_idempotencia.py:37-65`) | média* |
| LG-08 HITL por pausa de domínio | ✅ Adotado | `ia_pausada` + early-exit | baixa |
| LG-09 `interrupt()` disciplinado | ➖ N/A (não usa interrupt) | — | média* |
| LG-10 Revalidar estado pós-resume | ⚠️ Parcial | refetch existe; `output_guard` não reconfere terminal | baixa |
| LG-11 Modularização | ✅ Adotado | 6 nós de responsabilidade única | baixa |
| LG-12 Isolamento por namespace/par | ✅ Adotado | `WHERE cliente_id AND modelo_id` | baixa |
| LG-13 Janela deslizante | ✅ Adotado | `LIMIT 20` (`prepare_context.py:152-165`) | baixa |
| LG-14 Prefixo byte-determinístico | ✅ Adotado | testes de byte-identidade + snapshot de tools | baixa |
| **LG-15 Confiabilidade no grafo** | ✅ **Adotado** 🔄 | **(auditoria inicial errou): está implementado** — modelo de confiabilidade consciente e documentado em `04-tools.md §6` (retry do SDK + `ToolNode.handle_tool_errors` default + escalada do coordenador). `escalar_por_exaustao` **não é TODO**: wired em `coordenador.py:548` para 5 ramos; testes em `test_tools_02_escalada_indisponivel.py` e `test_per_05_refusal_escala.py`. Os "TODO M3f" em `nos/llm.py` são comentários obsoletos. | baixa |
| LG-16 Testes 2 camadas | ⚠️ Parcial | camada (1) forte; sem MemorySaver (N/A sem checkpointer) | baixa |
| LG-17 Connection pool compartilhado | ✅ Adotado | `AsyncConnectionPool` no lifespan (ADR-0002) | baixa |
| LG-18 `recursion_limit` + rota determinística | ✅ Adotado | `RECURSION_LIMIT=18` → `GraphRecursionError`→escala | baixa* |

\*Prioridade herdada de gaps relacionados em §4 (disclosure idempotência, teste do caminho de escalada).

### 3.2 Construção de agentes Anthropic — **~85% adotado** (19/28 plenos incl. 2 refutados; 1 N/A; 7 parciais; 1 ausente)

| Prática | Status | Evidência | Prioridade |
|---|---|---|---|
| AGT-01..06 (simplicidade, tools, schemas poka-yoke, retornos semânticos) | ✅ Adotado | 5 tools congeladas, `Literal`/`extra='forbid'`, `midia_id` fora do LLM | baixa |
| AGT-07 Limitar tamanho de retorno de tool | ⚠️ Parcial | `consultar_agenda` capa por janela (14d), **não por nº de bloqueios** | baixa |
| AGT-08 Eval de tools (tokens/runtime/erro, held-out) | ⚠️ Parcial | suite real, mas **sem métrica de tokens/runtime/contagem de tool-calls**; golden placeholder | **alta** |
| CACHE-01 Ordem tools→system→messages | ✅ Adotado | 4 breakpoints fixos | baixa |
| **CACHE-02 Prefixo ≥1024 tokens** | ✅ **Adotado** 🔄 | **(auditoria inicial errou): satisfeito por construção (~6.700 tokens, ~6,5×) e a ocorrência do cache é MEDIDA e ALARMADA** — `_instrumentar_tokens` (`nos/llm.py:43-52`) + tripwire `AgenteCacheWriteRateAlto` (`alert.rules.yml:34-49`). | baixa |
| CACHE-03..07 (validação usage, breakpoint móvel, TTL, invalidadores, pré-warm) | ✅ Adotado | WRITE=`ephemeral_5m+1h`; `cache_ttl=1h`; pré-aquecimento no startup | baixa/média |
| STOP-01 Switch de `stop_reason` | ⚠️ Parcial | cobre refusal+max_tokens; falta `model_context_window_exceeded` | média |
| **STOP-02 Refusal como evento de segurança** | ✅ **Adotado** 🔄 | **(auditoria inicial errou): cadeia completa** — `nos/llm.py:99-110` lê category sem parse; `coordenador.py:236-247` escala `modelo_recusou` sem bolha; bucketizado como `defesa` em `escaladas/service.py:404`. Só docstrings stale. | baixa |
| STOP-03 max_tokens + tool_use truncado | ❌ Ausente | sem guarda; despacharia tool de bloco truncado | média |
| STOP-04 `pause_turn` (server tools) | ➖ N/A (sem server tools) | — | baixa |
| **STOP-05 Resposta vazia pós-tool** | ✅ **Adotado** 🔄 | **(auditoria inicial errou): guarda real e load-bearing** — `_extrair_texto_do_turno` (`coordenador.py:451-468`) agrega texto de TODAS as `AIMessage` por `usage_metadata`, recuperando o texto da 1ª passagem e descartando o vazio pós-tool. Verificado contra bug de prod 2026-05-27. | baixa |
| STOP-06 Erro HTTP vs stop_reason | ⚠️ Parcial | HTTP/429/529 separados ✅; falta `model_context_window_exceeded` | baixa |
| CTX-01 Altitude do system prompt | ✅ Adotado | secções XML, heurísticas, sem if/else por modelo | baixa |
| **CTX-02 Tokens de alto sinal + gate vinculante** | ✅ **Adotado** 🔄 | **(auditoria inicial errou): há gate vinculante** — `runner.py:585/603/800` (`gate_split` exit-code) com graders **determinísticos** (`nao_deve_conter`, `tool_calls_*`, `isolamento_canary`) cobrindo os modos de falha; judge advisory é por design (ADR 0015). | baixa |
| **CTX-03 3-5 exemplos canônicos** | ✅ **Adotado** 🔄 | **(auditoria inicial errou): exatamente 5 few-shot** em `persona.md:19-50`; o bloco `<armadilhas_de_voz>` é dispositivo contrastivo de anti-padrão de voz, não dump de edge cases. | baixa |
| CTX-04 Retrieval just-in-time + isolamento | ✅ Adotado | IDs no contexto; janela por par | baixa |
| CTX-05 Compactação de threads longas | ⚠️ Parcial | janela capada + notas externas (colunas), **sem sumarização** | média |
| CTX-06 Isolamento de PII no prompt | ✅ Adotado | `_carregar_bp3` não seleciona RG/CPF/tipo_fisico | alta* |
| SO-01/SO-02 Strict tool use + limites de schema | ✅ Adotado | `STRICT_TOOLS={escalar}`+`_sanitizar_para_strict` | baixa |
| SO-03 Tratar refusal/max_tokens no structured output | ⚠️ Parcial | judge cai em default-seguro, **sem ramo explícito stop_reason** | baixa |
| THINK-01/02 Extended thinking | ✅ Adotado / ➖ N/A | `disabled`+`effort=low` (correto p/ chat) | baixa |

### 3.3 Segurança de IA conversacional — **~63% → ~79% adotado** (13/19 plenos após implementação 02/06; 5 parciais; 1 ausente)

| Prática | Status | Evidência | Prioridade |
|---|---|---|---|
| SEC-PI-01 Fronteiras no system prompt | ✅ Adotado | `<protocolo_*>` em `regras.md.j2` + defesa determinística | média |
| SEC-PI-02 Conteúdo de terceiros em HumanMessage | ✅ Adotado | nunca concatenado no SystemMessage | baixa |
| SEC-PI-03 Rotular/JSON-encodar conteúdo não-confiável | ⚠️ Parcial | spotlighting **só no áudio**; texto/legenda crus, sem JSON-encoding | média |
| SEC-PI-04 Instruções do dev fora de tool_result | ✅ Adotado | tools retornam dado/`ERRO:`, não override | baixa |
| SEC-PI-05 Adversarial multimodal/ofuscado em CI | ⚠️ Parcial | +Base64/leetspeak (advisory, 02/06); `evals.yml` existe mas **pula sem secrets** e as fixtures não estão graduadas | **alta** |
| SEC-JB-01 Harmlessness screen na entrada | ⚠️ Parcial | regex de input ✅; **sem screen LLM leve** | média |
| SEC-JB-02 Tratar reincidentes (throttle/ban por cliente) | ✅ Adotado (02/06) | contador por **telefone** (Redis 24h) escala 3/24h a Fernando, sem bloquear o cliente (`intercept_disclosure`) | média |
| SEC-OUT-01 Gate de saída na fronteira de envio | ✅ Adotado (02/06) | rede final em `enviar_turno` (`_saida_guard.py`): bloqueia auto-ref de IA; cobre os caminhos canned/reengajamento | **alta** |
| SEC-OUT-02 Validar estrutura da saída | ✅ Adotado | strict + Pydantic + regex de comandos | baixa |
| SEC-ID-01 Nunca revelar IA / vazar prompt | ✅ Adotado | 3 camadas (prompt + intercept + output_guard) | média |
| SEC-ID-02 Sem segredos no system prompt | ✅ Adotado | piso/chave Pix nunca no prompt; authz no código | baixa |
| SEC-PII-01 Minimização de PII no contexto | ✅ Adotado | ficha cadastral nunca interpolada | baixa |
| SEC-PII-02 Não-eco de PII na saída | ✅ Adotado (02/06) | redação **por eco** de CPF/RG/telefone no envio (preserva a chave Pix da modelo); CEP/endereço fora | média |
| **SEC-PII-03 Não-log de PII** | ✅ **Adotado** 🔄 | **(auditoria inicial errou): anonymizer instalado como cliente LangSmith GLOBAL** (`tracing.py:113-129`, hard gate força tracing off se não construir) + teste `test_sec_10_anonymizer_tracing.py`; nenhum call-site loga PII. | baixa |
| SEC-ISO-01 Isolamento por par no carregamento | ✅ Adotado | `WHERE (cliente_id, modelo_id)` em todas as queries; canary STRONG | alta* |
| SEC-ISO-02 Cache não mistura tenants | ✅ Adotado | dado por-par na cauda, fora do prefixo cacheado | baixa |
| SEC-AGENCY-01 Least privilege de tools | ✅ Adotado | 5 tools, sem execução arbitrária, credenciais no código | baixa |
| SEC-AGENCY-02 HITL p/ ações irreversíveis | ✅ Adotado | fechamento financeiro = comando humano | baixa |
| SEC-AUP-01 Enforcement de AUP + reincidência | ⚠️ Parcial | saída+refusal ✅; **sem reincidência por cliente; judge não calibrado** | **alta** |
| **SEC-MON-01 Monitoramento de injection** | ⚠️ Parcial 🔄 | **(auditoria parcialmente errou): a detecção de SAÍDA existe e é viva** (`output_guard` escaneia toda bolha + `OUTPUT_LEAK_DETECTADO` + EVAL-11 online amostra disclosure que passou). O gap real é só o **fechamento humano do loop** (golden placeholder, secrets de CI, graduação de fixtures). | média |

### 3.4 Evals — **~41% adotado** (5/17 plenos incl. 1 N/A; 9 parciais; 3 ausentes)

| Prática | Status | Evidência | Prioridade |
|---|---|---|---|
| EVAL-01 Golden set de falhas reais | ⚠️ Parcial | rastreabilidade por `#NNN` existe (canônicas); golden de calibração placeholder | **alta** |
| EVAL-02 Capability vs regression | ✅ Adotado | `_gate_da_fixture` separa; graduação é manual | média |
| EVAL-03 Evals em CI com gating | ⚠️ Parcial | workflow real; **pula sem secrets, não é check obrigatório** | **alta** |
| EVAL-04 pass^k + estado isolado | ✅ Adotado | K=5, `pass^k` adversariais, rollback por amostra | baixa |
| EVAL-05 SE/IC + clustered SE | ❌ Ausente | só contagens absolutas, sem barra de erro | média |
| EVAL-06 Paired-difference + power/MDE | ⚠️ Parcial | `bootstrap_pareado` existe mas **órfão** (sem chamador); sem power analysis | baixa |
| EVAL-07 Judge de família distinta | ❌ Ausente | judge é o mesmo Sonnet (self-preference); advisory mitiga | **alta** |
| EVAL-08 Vies de posição | ➖ N/A (judge pointwise, não pareado) | — | baixa |
| EVAL-09 Vies de verbosidade | ⚠️ Parcial | `judge.md` instrui ignorar comprimento; sem medida empírica | baixa |
| EVAL-10 Calibração com kappa | ⚠️ Parcial | maquinaria estatística pronta+testada; **golden placeholder, nunca rodou** | **alta** |
| EVAL-11 Judge 'Unknown' + por dimensão + ler transcripts | ⚠️ Parcial | 4 rubricas isoladas ✅; **sem saída 'Unknown'; revisão não operacionalizada** | média |
| EVAL-12 Graders determinísticos | ✅ Adotado | estado/tools/PII determinísticos; judge só no aberto | baixa |
| EVAL-13 Multi-turno com usuário simulado | ⚠️ Parcial | simulador tau-style existe mas **NÃO-GATE por design**; gate é roteirizado | média |
| EVAL-14 Adversarial mapeado a OWASP | ✅ Adotado | 78 fixtures, vetores OWASP cobertos (mapeamento não explícito) | média |
| EVAL-15 Não-vazamento PII + isolamento | ✅ Adotado | canary STRONG via seed; PII RG/CPF (endereço/tipo_fisico faltam) | alta* |
| EVAL-16 Versionar datasets + anti-contaminação | ⚠️ Parcial | git versiona; **sem campo versão/changelog, sem near-dup por embeddings** | média |
| EVAL-17 Offline + online + loop trace→fixture | ⚠️ Parcial | online cobre 1 rubrica; **loop trace→fixture não operacionalizado** | média |

### 3.5 Confiabilidade em produção — **~80% adotado** (12/15 plenos; 3 parciais; 0 ausentes)

| Prática | Status | Evidência | Prioridade |
|---|---|---|---|
| REL-IDEMP-01 Idempotência de side-effects | ✅ Adotado | `tool_calls` PK; dedupe Redis no envio; lembrete com `SKIP LOCKED` | alta* |
| REL-IDEMP-02 Chave determinística (uuid5) | ✅ Adotado | `turno_id=uuid5(...)`; `call_idx` ordinal replay-safe | média* |
| REL-RETRY-01/02 Retry SDK + degradação 529 | ✅ Adotado | `max_retries=2`/`timeout=60`; escala `modelo_indisponivel` (sem circuit breaker) | baixa/média |
| REL-LAT-01 Streaming p/ chamadas longas | ➖ N/A (`max_tokens=1024`, chamada curta) | — | baixa |
| REL-LAT-02 Prompt caching + max_tokens | ✅ Adotado | 4 breakpoints + pré-warm | baixa |
| REL-OBS-01 Tracing por thread, sem PII | ✅ Adotado | LangSmith com anonymizer + hard gate | média* |
| REL-OBS-02 Métricas operacionais + request_id Anthropic | ⚠️ Parcial | métricas ricas + alertas; **request_id da Anthropic não logado; handoff total não-direto** | média |
| REL-WH-01 Token + JID antes de processar | ✅ Adotado | HMAC tempo-constante, teto de corpo, JID allowlist | baixa |
| REL-WH-02 Dedup por message_id | ⚠️ Parcial | dedup por persistência (forte); **sem janela max-age** | baixa |
| REL-WH-03 Debounce + chave de turno determinística | ✅ Adotado | `_job_id` estático + drain loop | baixa |
| REL-ARQ-01 Jobs idempotentes | ✅ Adotado | turno_id + cinto-suspensório + `SKIP LOCKED` | média* |
| REL-ARQ-02 Crons com guarda de estado + Retry | ⚠️ Parcial | guarda de estado/toques ✅ (fecha o bug histórico); **sem `arq.Retry`** | média |
| REL-DUR-01 Durabilidade consciente | ✅ Adotado | `checkpointer=None` documentado | baixa |
| REL-DEG-01 Degradação graciosa "nunca trava" | ✅ Adotado | Pix/vision/refusal/lembrete sempre avançam | baixa |

---

## 4. Lacunas confirmadas e recomendações priorizadas

> Apenas lacunas confirmadas como reais (`verdict.lacuna_real=true`) ou não verificadas mas plausíveis. **9 gaps da auditoria inicial foram refutados pela verificação adversarial** e estão listados como pontos fortes em §5.

### 4.1 PRIORIDADE ALTA

**A1 — Gate de saída na fronteira de envio (SEC-OUT-01).** *Verdict: lacuna real.*
O `output_guard` vive como nó final do grafo, mas **pelo menos 2 caminhos despacham `enviar_turno` sem passar pelo grafo** — canned de transcrição falha (`coordenador.py:149-159`) e reengajamento (`timeouts.py:197-207`). Estes pulam o guard inteiro.
- **Por que importa neste domínio:** numa operação adulta/anti-disclosure, qualquer bolha que escape do filtro é incidente de marca/AUP. Hoje os textos canned são curados (risco baixo na prática), mas a fronteira real (`enviar_turno`) não tem rede independente.
- **Recomendação:** adicionar checagem determinística barata (`tem_marcador_ia` + scan de PII) no próprio `enviar_texto_job`, reaproveitando `output_guard._scan_vazamento`. **Arquivo: `api/src/barra/workers/envio.py`.**
- **✅ Feito (02/06, `0dc2de8`):** rede final em `enviar_turno` via `workers/_saida_guard.py` (reusa `tem_marcador_ia`) — bloqueia+escala e cobre canned/reengajamento. Flag `envio_guard_habilitado`.

**A2 — Não-vazamento de PII e enforcement de AUP por reincidência (SEC-PII-02 + SEC-AUP-01 + SEC-JB-02).** *Verdict: lacuna real (3 práticas convergentes).*
Não há redação de PII (CPF/RG/CEP/E.164) no caminho de envio, e **nenhuma detecção de reincidência por telefone** (o contador de disclosure é por atendimento e zera em novo par; o teto de turnos é por custo). A AUP da Anthropic exige agir sobre quem submete inputs violadores repetidamente.
- **Por que importa:** o cliente pode enviar o próprio CPF/comprovante e a IA repeti-lo; um número que tenta jailbreak repetidamente não é marcado para ação.
- **Recomendação:** (a) regex de PII no gate de envio (junto de A1); (b) contagem de recusas/jailbreaks por telefone em janela deslizante Redis, com limiar que escala a Fernando. **Arquivos: `api/src/barra/workers/envio.py`, `api/src/barra/agente/nos/intercept_disclosure.py`.**
- **✅ Feito (02/06, `a0f452a`):** (a) redação de PII **por eco** — só mascara o que o cliente mandou no inbound, preservando a chave Pix da modelo (que pode ser CPF/telefone mas nunca vem do cliente); CEP/endereço fora. (b) contador por telefone (Redis 24h) escala 3/24h, **sem bloquear** o cliente; replay-safe por `turno_id` e não queima a janela em falha de DB. Flags `reincidencia_seguranca_*`.

**A3 — Adversarial de ofuscação + CI de evals como gate real (SEC-PI-05 + EVAL-03).** *Verdict: lacunas reais.*
Há **zero fixtures de ataque ofuscado por codificação** (Base64/hex/emoji/leetspeak/homoglyph); o CI `evals.yml` **pula silenciosamente sem secrets** e só 3 fixtures são `gate:'regressao'` bloqueante.
- **Por que importa:** o agente recebe texto arbitrário no WhatsApp; sem gate vinculante, uma regressão que faz a IA vazar identidade/cruzar modelos passa despercebida.
- **Recomendação:** habilitar secrets `TEST_DATABASE_URL`/`ANTHROPIC_API_KEY` + branch protection (tornar `evals` required); graduar `prompt_injection/jailbreak/cross_modelo/pii/injecao_midia` para `gate:'regressao'`; adicionar fixtures de ofuscação. **Arquivos: `.github/workflows/evals.yml`, `api/evals/adversariais/`.**
- **◑ Parcial (02/06):** `evals.yml` já estava feito (path-filter + guard de secrets + doc do pré-requisito). +2 fixtures de ofuscação adicionadas como **capability/advisory** (`prompt_injection/003_base64_ofuscado`, `jailbreak/007_leetspeak_emoji_ofuscado`). **Aberto:** graduar a `gate:regressao` (exige **run live** p/ não deixar o CI vermelho se alguma for flaky) + secrets/branch-protection (**operador**).

**A4 — Calibrar o LLM-judge contra golden humano (EVAL-01 + EVAL-07 + EVAL-10).** *Verdict: lacunas reais.*
A maquinaria estatística está pronta e testada (`calibracao.py`: TPR/TNR/kappa de Cohen/Gwet AC2), mas o `golden.jsonl` é **PLACEHOLDER explícito** ("apague-as") — a calibração **nunca rodou**, o judge permanece advisory, e o judge é o **mesmo Sonnet do agente** (self-preference não quebrado).
- **Por que importa:** o enforcement vinculante de AUP/persona/disclosure recai sobre um judge não-auditado; sem calibração não há gate de regressão de comportamento.
- **Recomendação:** Fernando + sócia rotulam 30-50 (idealmente 100+) turnos de `docs/agente/conversas-reais/` independentemente; rodar `calibrar.py`; ao promover, considerar judge de família distinta (GPT/Gemini via OpenRouter, já usado no Pix) ou medir e descontar o self-preference. **Arquivo: `api/evals/calibracao/golden.jsonl`.**
- **⬜ Em outro fluxo:** conduzido em paralelo por outro agente; a interface de rotulagem do golden já está em `main`. Não faz parte desta entrega (02/06).

**A5 — Instrumentar tokens/runtime nos evals de tools (AGT-08).** *Verdict: lacuna real.*
O runner não mede tokens, runtime nem contagem de tool-calls como métricas de qualidade comparadas entre versões — os blocos `metricas` nas fixtures são **declarados mas mortos** (`avaliar()` os ignora).
- **Recomendação:** instrumentar `num_tool_calls`, tokens (input/output/cache) e runtime por fixture no runner, para detectar regressão de eficiência. **Arquivo: `api/evals/runners/runner.py`.**
- **⬜ Aberto:** adiado por não ser verificável sem **run live** de evals (a captura de tokens roda no caminho DB/LLM; créditos Anthropic esgotados). Fazer junto da graduação de fixtures (A3) quando os créditos voltarem.

### 4.2 PRIORIDADE MÉDIA

| Gap | O que falta / recomendação | Arquivo |
|---|---|---|
| **Idempotência cross-retry do contador de disclosure (LG-07/REL-IDEMP-02, TODO M3a)** | Único side-effect de escrita fora do esquema `tool_calls`; replay pode contar 2× e escalar 1 toque antes. Tornar o incremento idempotente por `turno_id`. | `intercept_disclosure.py:69-70` |
| **STOP-03 — tool_use truncado por max_tokens** | Sem guarda; um bloco truncado poderia despachar tool com args incompletos. Se `stop_reason==max_tokens` E último bloco for `tool_use`, não despachar; reinvocar com teto maior ou escalar. | `agente/nos/llm.py:111-115` |
| **SEC-PI-03 — spotlighting só no áudio** | Texto cru/legenda de imagem entram sem cerca de proveniência. Estender o padrão de cerca/rótulo (ou JSON-encoding com `source/from`) à legenda de imagem. | `prepare_context.py` |
| **SEC-JB-01 — harmlessness screen leve na entrada** | Conteúdo AUP-duro (menor/não-consentido) só é pego na saída. Avaliar screen Haiku/structured output na entrada. | `agente/` |
| **CTX-05 — sumarização de threads longas** | Além de 20 mensagens o histórico cai da janela (perda de recall cross-atendimento). Para P1: camada de sumarização/notas do par. | `prepare_context.py` |
| **REL-OBS-02 — request_id da Anthropic** | Logado é o request_id interno do app, não o `message._request_id` (chave para ticket de suporte). Logar no ramo de erro/refusal. | `agente/nos/llm.py` |
| **REL-ARQ-02 — `arq.Retry` em crons** | Crons engolem exceção transitória sem reagendar (toque perdido até a próxima varredura). Severidade baixa (re-disparo periódico cobre). | `workers/lembrete_valor.py`, `timeouts.py` |
| **EVAL-05 — barras de erro** | Nenhum pass-rate vem com SE/IC ou nº de clusters. Emitir IC bootstrap clusterizado por fixture. | `runners/runner.py` |
| **EVAL-11/13/16/17** | Saída 'Unknown' no judge; fluxos multi-turno fracos (reengajamento, handoff+devolução) como fixtures de gate; campo de versão/changelog + near-dup por embeddings; pipeline trace-de-prod→fixture. | `api/evals/` |

### 4.3 PRIORIDADE BAIXA

- **LG-10** — `output_guard` não reconfere estado terminal (paga custo de judge em turno descartável); + teste de "terminal mid-turno".
- **LG-16** — cobrir a sequência de roteamento por Command num teste mais leve (fakes) para reduzir dependência de `needs_db`.
- **LG-18** — falta teste do caminho `except GraphRecursionError → escalar_por_exaustao`.
- **AGT-07** — `consultar_agenda` sem cap por nº de bloqueios; adicionar top-N + sufixo de truncamento.
- **STOP-06** — `model_context_window_exceeded` sem ramo próprio (improvável com janela de 20).
- **SO-03** — judge não checa `stop_reason` da própria resposta (mascarado pelo default-seguro).
- **EVAL-06** — expor `bootstrap_pareado` via subcomando do runner + registrar MDE para o N atual.
- **REL-RETRY-02** — sem circuit breaker para 529 prolongado.
- **REL-WH-02** — sem janela max-age contra replay antigo (dedup por persistência já mitiga).

---

## 5. Pontos fortes (acima da média)

1. **Isolamento por par como invariante de código, não convenção.** Toda query de contexto filtra `(cliente_id, modelo_id)` JUNTOS; `agente/CLAUDE.md` torna isso gate de PR; o cache separa prefixo geral (compartilhável) do dado por-par na cauda; e há **eval STRONG por canary** plantado num par B real, auditado na **superfície inteira** (resposta + args de TODAS as tools), porque auditar só o output cega ~42% do vazamento.

2. **Suíte adversarial robusta — 78 fixtures em 13 famílias** cobrindo disclosure, jailbreak, prompt injection direta/indireta (incl. via STT), cross-modelo, gaslighting, PII e AUP ambíguo. Acima do "corpus mineral" típico de MVP.

3. **Output guard de saída (ADR 0016) com default seguro.** Scan determinístico + LLM-judge de AUP vinculante; falha de infra do judge → **bloqueia+escala** (nunca passa). Termos cross-modelo montados do banco, não do prompt.

4. **Prompt caching disciplinado e instrumentado.** 4 breakpoints fixos, prefixo byte-idêntico entre modelos (testes de snapshot), WRITE corretamente somado de `ephemeral_5m+1h`, pré-aquecimento no startup, e **tripwire de write-rate alarmado** em Prometheus.

5. **Idempotência determinística sem checkpointer.** `tool_calls` PK `(turno_id, tool_name, call_idx)` + `turno_id=uuid5(...)` replay-safe; "nunca trava por Pix" implementado em profundidade (até vision inconclusiva cai em revisão).

6. **Nove gaps da auditoria inicial foram refutados pela verificação adversarial** — o sistema é mais maduro do que a primeira passada sugeriu. **Auditoria inicial errou em:**
   - **LG-15 / STOP-02:** `escalar_por_exaustao` e a escalada de refusal **estão implementadas** no `coordenador.py:548,236-247` (os "TODO M3f" são comentários stale).
   - **STOP-05:** a guarda contra resposta vazia pós-tool existe em `_extrair_texto_do_turno` (`coordenador.py:451-468`).
   - **SEC-PII-03:** o anonymizer de PII está instalado como cliente LangSmith global com hard gate e teste dedicado.
   - **CACHE-02 / CTX-02 / CTX-03:** prefixo ≥1024 garantido + cache medido/alarmado; gate vinculante determinístico existe; há exatamente 5 few-shot canônicos.

---

## 6. Metodologia e ressalvas

- **% adotado por dimensão (ponderando N/A como neutro):** Arquitetura LangGraph **~89%** · Anthropic **~85%** · Confiabilidade **~80%** · Segurança **~63%** · Evals **~41%**. As duas dimensões mais fracas (Segurança de saída e Evals) convergem para o **mesmo trabalho de operador**: ligar o gate de evals + calibrar o judge + fechar o loop de saída na fronteira de envio.

- **Verificação adversarial:** das 33 práticas com gap apontado, **24 tiveram a lacuna confirmada (`lacuna_real=true`)** e **9 foram refutadas (`lacuna_real=false` → tratadas como adotadas em §3/§5)**. Onde refutado, indiquei explicitamente "auditoria inicial errou: está implementado em X".

- **Achados de menor prioridade não verificados adversarialmente:** dois achados de prioridade **baixa permanecem não verificados** e plausíveis (incluídos em §4.3 como tal): **REL-WH-02** (janela max-age contra replay) e **REL-RETRY-02** (circuit breaker para 529). São refinamentos de resiliência, não riscos abertos — a dedup por persistência e a degradação por escalada já cobrem o caso comum.

- **Documentação defasada (risco de onboarding):** **✅ corrigidos 02/06** — `01-arquitetura.md` (5→6 nós + `output_guard` no diagrama/mapa) e `02-estado-fluxo.md` (`_confianca: str`, era `float`). **Ainda defasados:** `03 §5.3` menciona `AsyncPostgresSaver` ao fim de cada turno; `04/05/06` têm assinaturas antigas e blocos superados (só as emendas `§0` são verdade); os docs de evals citam ~11 fixtures (são 99). **O código vence** (regra do `CLAUDE.md` raiz) — alinhar o resto é trabalho à parte.

- **Fontes de best practice (dos checklists):** Anthropic Engineering (*Building Effective Agents*, *Effective context engineering*, *Writing tools for agents*) + docs oficiais (prompt caching, handling stop reasons, structured outputs, mitigate jailbreaks, AUP, content moderation); LangGraph docs (durable execution, interrupts, memory/store, RetryPolicy, testing); OWASP Top 10 for LLM Applications 2025 (LLM01/02/05/06/07); paper Anthropic *Adding Error Bars to Evals*; tau2-bench (Sierra); LangSmith eval docs; literatura de viés de LLM-judge (self-preference, position, verbosity) e inter-annotator agreement (Cohen kappa / Gwet AC2); ARQ docs (at-least-once); guias de segurança de webhook (HMAC/replay/dedup); anthropic-sdk-python (backoff/retry/timeout).
