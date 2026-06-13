# 00 — Índice da Spec do Agente de Atendimento

> **Projeto:** Central Inteligente de Atendimento — Elite Baby
> **Escopo:** especificação completa do agente LangGraph (módulo 5.3 + coordenador 5.2 + humanização 5.5 + pipelines de mídia) para o piloto P0.
> **Audiência:** agentes de IA construindo o backend a partir da base de código existente em `api/src/barra/`.
> **Pré-requisitos:** ler `CLAUDE.md`, `CONTEXT.md`, `docs/mvp/00-indice.md`, `docs/adr/0001-*.md` e `docs/adr/0002-*.md` antes de codar.

## Como usar

Cada arquivo cobre **uma fronteira clara** do agente. Carregue apenas os arquivos relevantes para a tarefa em andamento. Quando algo divergir entre `docs/agente/` e `docs/mvp/`, **`docs/agente/` é a verdade técnica corrente** — divergências e por quês ficam em `01-arquitetura.md §6`.

| Arquivo | Conteúdo | Carregar quando |
|---------|----------|-----------------|
| [01-arquitetura.md](01-arquitetura.md) | Decisões de arquitetura, mapa de módulos, divergências com `docs/mvp/`, fluxo end-to-end | Sempre, antes de qualquer mudança no agente |
| [02-estado-fluxo.md](02-estado-fluxo.md) | State LangGraph (TypedDict), thread_id, política de hidratação, sliding window, **tabela de transições (§11)**, fluxo de turno | Implementando `agente/graph.py`, `agente/estado.py` ou coordenador |
| [03-prompts.md](03-prompts.md) | Templates Jinja2, breakpoints `cache_control`, dataclass Persona, contexto dinâmico | Editando `agente/prompts/*.md` ou `agente/llm.py` |
| [04-tools.md](04-tools.md) | Catálogo completo de tools, contratos Pydantic, idempotência, comportamento de escalada | Implementando `agente/ferramentas/*.py` |
| [05-humanizacao.md](05-humanizacao.md) | Chunking, jitter/typing, dedupe, cancel-on-new-message, ordem texto/mídia, persistência saída | Implementando `agente/humanizacao.py` ou `workers/envio.py` |
| [06-pipelines-midia.md](06-pipelines-midia.md) | Transcrição de áudio, OCR/vision para Pix, comportamento de imagem fora-fluxo | Implementando `workers/media.py` ou `workers/pix.py` |
| [07-coordenador.md](07-coordenador.md) | Webhook → debounce → lock → resolução → invocação grafo → dispatch; cron de timeouts | Implementando `webhook/despacho.py`, `webhook/debounce.py`, `workers/timeouts.py` |
| [08-evals.md](08-evals.md) | LangSmith datasets, cenários canônicos, métricas Prometheus, gate de pronto-pra-piloto | Escrevendo testes ou evals em `evals/` |
| [08b-evals-pesquisa-producao.md](08b-evals-pesquisa-producao.md) | Pesquisa fact-checada de evals de produção (plano de cutover) | Planejando o cutover de evals |
| [08c-evals-online-e-calibracao-judge.md](08c-evals-online-e-calibracao-judge.md) | Pesquisa fact-checada (jun/2026): camada de eval ONLINE sobre traces de prod + calibração do judge contra rótulo humano (Trust-or-Escalate, indeterminação, overconfidence/style-bias) | Planejando a camada online de evals ou calibrando o judge panel |
| [10-corpus-real-vendedor.md](10-corpus-real-vendedor.md) | Taxonomia de jogadas de venda **minerada e validada** do corpus real (71k msgs, eb01–04); frequência por modelo (validade convergente), anti-padrões quantificados + decisões de produto, candidato→veículo (regra/few-shot/FAQ); §11 motivo de perda, **§12 micro-cotação** (calor é a única alavanca; urgência colada prejudica), **§13 reengajamento** (40% revive; gap curto + pergunta leve vencem; tensões com a política do CONTEXT) | Antes de (re)escrever `prompts/persona.md`, `regras.md.j2`, `faq.md` a partir do comportamento real |
| [10b-corpus-fewshots.md](10b-corpus-fewshots.md) | Banco de **few-shots reais** do Vendedor por jogada (35 exemplos abstraídos p/ o prompt compartilhado), calibrado por §12/§13, com veículo (persona/regra/faq) e itens ⚠ que dependem do Fernando | Ao escrever os blocos de few-shot de `prompts/*` — rodar `/domain-isolation-reviewer` no diff real |
| [11-medicao-offline-flywheel.md](11-medicao-offline-flywheel.md) | **Conclusão do loop de medição offline** (12–13/06): prompt v1 escrito → eval set (`corpus.eval_*`) → v1 pontuado vs hold-out eb04. Achados: cotação não prediz conversão (κ≈0.07); **v1 já limpo do empurrão** (0.3% vs 26%); **reengajamento canned já ótimo** (gap/pergunta_leve validados, mídia-fria refutada). **GEPA sem alvo offline → próxima fronteira = A/B ao vivo** | Decidindo o próximo passo do agente (GEPA/A/B) ou reusando a eval suite p/ pontuar um prompt candidato |

## Stack do agente (resumo)

- **Provider LLM:** Anthropic API direto via `anthropic` SDK (Python). Wrapper LangChain via `langchain-anthropic.ChatAnthropic` para integração com LangGraph.
- **Modelo principal (chat):** `claude-sonnet-4-6` — $3/M input, $15/M output, cache read ~0.1×, cache write 1.25× (TTL 5m) ou 2× (TTL 1h). **Sem modelo de fallback:** `RateLimitError` faz retry com backoff e, na exaustão (ou `APIStatusError(status >= 500)`/timeout), o turno escala para Fernando via `escalar_por_exaustao` (`01 §2.6`).
- **Modelo vision (Pix):** via **OpenRouter** (`llm_vision_provider="openrouter"`; cliente OpenAI-compatível + `response_format` json_schema, validação `ExtracaoPix` Pydantic manual — decisão grilling 2026-05-23, `06 §2.3`).
- **Modelo transcrição:** `whisper-1` direto na **OpenAI API** (Anthropic não transcreve áudio), contido em `workers/media.py`. Junto do vision via OpenRouter, são os dois providers não-Anthropic do MVP.
- **Orquestrador:** LangGraph **1.1.10** com **StateGraph custom** (decisão `01 §2.1` — `create_react_agent` foi deprecado na v1.0; rodamos v1.x). **Sem checkpointer no P0** — estado efêmero por turno, prompt montado do zero a partir do Postgres (decisão `02 §3`). SDK: `langchain-anthropic` **1.x** para o chat (sobre `anthropic` **0.97**); vision do Pix via OpenRouter e transcrição via OpenAI (`06`).
- **Worker de turno:** ARQ + Redis (lock de conversa, dedupe, cancel-on-new-message).
- **Tracing:** LangSmith desde o primeiro turno; metas em `08-evals.md §3`.

## Decisões-chave (índice rápido)

| Decisão | Onde está detalhada |
|---------|---------------------|
| StateGraph custom em vez de `create_react_agent` (deprecado em LangGraph v1.0) | `01 §2.1` |
| `thread_id = conversa_id` | `02 §2` |
| State minimalista (`MessagesState`) | `02 §3` |
| Coordenador como ARQ job (não inline no webhook) | `07 §1` |
| Anthropic SDK direto + Sonnet 4.6 (sem modelo de fallback; exaustão → escala) | `01 §2.5`, `01 §2.6` |
| Thinking desabilitado no P0; effort fixo no default; `max_tokens` como guard-rail (reavaliar no piloto) | `03 §6` |
| Prompt em **4 breakpoints fixos** (BP_TOOLS + BP_GERAL fundido + BP_MODELO + BP_JANELA na penúltima; BP_JANELA shipado, não mais adiado) (`cache_control`); contexto dinâmico no último user turn (sem cache) + estrutura XML semântica | `03 §1`, `03 §4` |
| Coordenador **drain loop** + `turno_id = uuid5(job_id, loop_idx)` determinístico; debounce **first-wins**; LockBusy → re-defere curto | `07 §3`, `02 §7`, `01 §6.7` |
| FAQ é **arquivo versionado `faq.md`** (`modelo_faq` dropada em 0030); catálogo enxugado para **5 tools** (só `consultar_agenda` de leitura) | `03 §3.2`, `04 §1` |
| Classificação disclosure/jailbreak roda **dentro do grafo** (sobre a janela); modelo nomeado = canned+contador; jailbreak escala direto | `03 §11`, `03 §7`, `01 §6.8` |
| Canal de transcrição keyed por **`conversa_id`** (não `atendimento_id`) | `06 §1.4` |
| Few-shot examples > adjetivos descritivos para tom | `03 §2.2` |
| Tell-what-to-do (sem CRITICAL/NUNCA/PARE em 4.6) | `03 §3.1`, `03 §9` |
| **Negação ativa de IA** (nega 1ª/2ª; escala na 3ª insistência) + interceptação canned em alta confiança | `01 §6.8`, `03 §11` |
| **Persona/voz/FAQ GERAIS** (compartilhadas); só identidade óbvia + programas + `tipos_aceitos` por-modelo. Breakpoints: geral→por-modelo (dinâmico vai no user turn, sem cache) | `03 §1`, `CONTEXT.md` |
| Nó `intercept_disclosure` (canned/escala/llm) + contador persistido `atendimentos.disclosure_tentativas` | `03 §7`, `01 §6.8` |
| `prepare_context` é dono único do contexto (coordenador invoca com `messages` vazio); `gate_pausa` dobrado nele | `03 §7`, `01 §2.3` |
| Bloqueio prévio do externo nasce no `pedir_pix_deslocamento` (fecha double-booking) | `04 §3.2` |
| Integridade de agenda: advisory lock `(modelo, slot)` + EXCLUDE constraint backstop (race entre conversas) | `04 §3.1`, `09` |
| Sonnet sem modelo de fallback: retry no 429, exaustão/5xx/timeout → `escalar_por_exaustao` | `01 §2.6`, `03 §6.3` |
| `stop_reason` em 200 OK tratado: `refusal` → escala (`modelo_recusou` → Fernando, bucket defesa); `max_tokens` → só métrica; `pause_turn` N/A (≠ `recursion_limit`) | `03 §6.3`, `03 §8`, `04` |
| Turno com write tool não é cancelável por cancel-on-new-message | `05 §3`, `02 §8.1` |
| Reminder injection no user turn (combate persona drift) | `03 §10` |
| Classificador heurístico de jailbreak/disclosure no webhook | `03 §7` |
| Adversarial dataset semanal (CI gate ≥90%) | `08 §3` |
| `max_tokens` ~1024 como guard-rail (tom/tamanho vêm da persona, não do teto) | `03 §6.1` |
| Tool `escalar` grava direto via `abrir_handoff` | `04 §3.5` |
| `pedir_pix_deslocamento()` sem args (R$100 fixo) | `04 §3.6` |
| Pix nunca trava o fluxo: validado/duvidoso → `Confirmado`; card sinaliza modelo + fila de revisão de Fernando | `06 §2.2` |
| Sliding window de 20 mensagens | `02 §4` |
| Transcrição via OpenAI Whisper API direto (Anthropic não transcreve) | `06 §1` |
| Pix vision via **OpenRouter** (json_schema + Pydantic manual; `messages.parse()` Anthropic-native preterido por **escolha de provider**, não limitação — segue válido na GA) | `06 §2.3` |
| Lock Redis TTL 60s + heartbeat do worker (15s) | `07 §3.2` |
| Cron timeouts a cada 5min | `07 §4` |
| LangSmith datasets como eval primário | `08 §1` |
| **Desconto de fechamento** até `desconto_max_pct` (one-shot no piso; reativo+proativo); guarda no código; reverte "IA não negocia" | `01 §6.11`, ADR-0004 |
| **Reengajamento** proativo (1 toque ~30min pós-cotação, canned, sem desconto) via cron; P0 atrás de flag `reengajamento_ativo` | `01 §6.12`, `07 §4.5` |
| **Mídia exclusiva** (foto→vídeo + narrativa "ao vivo"); view-once condicional ao suporte da Evolution (pré-req) | `01 §6.13`, `05 §5` |

## Convenções de leitura

- **Trechos de código** mostram o `path/file.py:simbolo` exato sempre que possível.
- **SQL** aparece quando a query não é trivial (índice, RLS, lock).
- **Pydantic schemas** são a fonte de contrato; runtime checks no FastAPI usam-nos diretamente.
- **`# TODO(M{n})`** marca trabalho pendente que pertence a um marco específico da implementação do agente.
- **`docs/mvp/XX §Y.Z`** referencia o produto. **`docs/agente/XX §Y.Z`** referencia esta spec técnica.

## Status

- **Versão:** 2.0 (revisão grilling 2026-05-23 comercial — **desconto + reengajamento + mídia exclusiva + indisponibilidade**, a partir do gap-check vs ata da reunião. **Desconto de fechamento** até `desconto_max_pct` (~15%), one-shot no piso, reativo+proativo, regra do % no prompt + guarda no código, reverte "IA não negocia" (ADR-0004, `01 §6.11`). **Reengajamento** proativo 1 toque ~30min pós-cotação via cron `reengajar_silenciosos`, canned sem desconto, **P0 atrás de flag `reengajamento_ativo`** default off (`01 §6.12`, `07 §4.5`, migration `reengajado_em`). **Mídia exclusiva** foto→vídeo + narrativa "ao vivo", `enviar_midia(tipo)`, view-once **condicional** ao suporte da Evolution self-host (`01 §6.13`, `05 §5`). **Indisponibilidade** com desculpa pessoal sem revelar outro cliente (`03 §3.1`). Settings novos `desconto_max_pct`/`reengajamento_*`/`operacao_hora_*`; `CONTEXT.md` +5 termos. Segurança de localização descartada no P0; Pix R$100 fixo mantido). 1.9 (revisão grilling 2026-05-23 humanização — **`05` reescrito + acoplados (`01`,`02`,`04`,`06`,`07`,`08`,`09`)**: **job ÚNICO `enviar_turno` por turno** (ordem/cadência que `max_jobs` quebrava no job-por-chunk); **turno inteiro crítico** não-cancelável e **falha de envio de crítico → escalar** (`critico` no payload, sem rollback); `chunk_texto` **preserva `\n` interno**, cap 600 **soft+`CHUNK_OVERSIZE`**, **cap ~6 bolhas**; envio **estende `EvolutionClient`** (`set_presence`+`enviar_midia`) + **dual-table** `envios_evolution` (obrigatório p/ desambiguar `fromMe`) **+** `mensagens`; idempotência **mark-after-send** (`enviados:{turno_id}`); **cards viram jobs ARQ `enviar_card`** — **descartado o stream `evolution:card`**; ordem **texto→mídia**; cancel via **`turno_atual`** (eliminado `chunks_pendentes`)). 1.8 (revisão grilling 2026-05-23 — **coordenador canônico = drain loop + `turno_id` uuid5 determinístico** (07/02 alinhados ao 01 §4.3/§6.7; uuid7 eliminado); **debounce first-wins**; **LockBusy → re-defere curto**; **contexto dinâmico no último user turn** (sai do `system`, 3 BP fixos + 1 condicional); **canal de transcrição por `conversa_id`** (corrige corrida com atendimento órfão); **classificação disclosure/jailbreak dentro do grafo** sobre a janela (webhook vira métrica); **modelo nomeado tratado como genérico** (canned+contador, `disclosure_explicito` legado); **jailbreak separado → escala direto**; **FAQ = arquivo `faq.md`** (tabela `modelo_faq` dropada em 0030), catálogo enxugado para **5 tools** (só `consultar_agenda` de leitura; `cliente`/`pix_status`/`faq` no prompt, `consultar_midia` colapsada em `enviar_midia(tag)`); limpezas: stream único `evolution:card`, código morto do passo 8, `arq_pool`→`ctx["redis"]`, docstring `consultar_pix_status`). 1.7 (revisão grilling 2026-05-22 — aura/sotaque/origem movida p/ BP3 por-modelo (BP1 fica voz pura); campo `limpar` no `registrar_extracao`; métrica de escalada por bucket defesa/capacidade (gate só capacidade); removido `escalar(cliente_chegou_interno)` morto — foto-portaria é determinística). 1.6 (revisão grilling 2026-05-22 — **persona/voz/FAQ GERAIS** compartilhadas entre todas as modelos; só identidade óbvia (nome/idade/idiomas/localização) + programas/preços + `tipos_aceitos` por-modelo; breakpoints reordenados geral→por-modelo→dinâmico (prefixo global, escalável); override de `CONTEXT.md` "IA por modelo"). 1.5 (revisão grilling 2026-05-22 — fallback de modelo por iteração sem reset; cancel-on-new-message exime turno com write tool; contador `disclosure_tentativas` idempotente por `turno_id`; reagendamento pós-bloqueio escala; integridade de agenda com advisory lock + EXCLUDE constraint; roteamento de imagem sob lock via `rotear_imagem`). 1.4 (revisão grilling 2026-05-22 — `prepare_context` é dono único do contexto; nó `intercept_disclosure` (canned/escala/llm) + contador persistido `disclosure_tentativas`; `gate_pausa` dobrado no `prepare_context`; bloqueio prévio do externo no `pedir_pix_deslocamento`; estados Pix `invalido`/`enviado`/`pix_em_revisao` são legado; webhook não cria atendimento). 1.3 (2026-05-22): negação ativa de IA + interceptação canned; sem checkpointer no P0; thinking off + `max_tokens` guard-rail; externo só promovido pelo Pix; Pix nunca trava o fluxo; mídia cega não responde. 1.2 (2026-05-02): XML tags + few-shot persona + classificador adversarial.
- **Implementação:** M0 parcial (2026-05-22). O esqueleto do grafo compila com os 5 nós em fluxo linear (todos no-op) e o framework de evals está montado (estrutura + 5 fixtures seed). Pendente para fechar o M0: nó `llm` ainda é placeholder, `core/llm.py` é só docstring, `agente/llm.py` não existe, o `lifespan` não monta `app.state.graph` e não há `test_skeleton_responde`.
- **Próximo passo:** fechar o M0 — `core/llm.py` + `agente/llm.py` + nó `llm` chamando a Anthropic + `lifespan` montando `app.state.graph` + `test_skeleton_responde`.
