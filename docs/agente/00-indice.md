# 00 — Índice da Spec do Agente de Atendimento

> **Projeto:** Central Inteligente de Atendimento — Barra Vips
> **Escopo:** especificação completa do agente LangGraph (módulo 5.3 + coordenador 5.2 + humanização 5.5 + pipelines de mídia) para o piloto P0.
> **Audiência:** agentes de IA construindo o backend a partir da base de código existente em `api/src/barra/`.
> **Pré-requisitos:** ler `CLAUDE.md`, `CONTEXT.md`, `docs/mvp/00-indice.md`, `docs/adr/0001-*.md` e `docs/adr/0002-*.md` antes de codar.

## Como usar

Cada arquivo cobre **uma fronteira clara** do agente. Carregue apenas os arquivos relevantes para a tarefa em andamento. Quando algo divergir entre `docs/agente/` e `docs/mvp/`, **`docs/agente/` é a verdade técnica corrente** — divergências e por quês ficam em `01-arquitetura.md §6`.

| Arquivo | Conteúdo | Carregar quando |
|---------|----------|-----------------|
| [01-arquitetura.md](01-arquitetura.md) | Decisões de arquitetura, mapa de módulos, divergências com `docs/mvp/`, fluxo end-to-end | Sempre, antes de qualquer mudança no agente |
| [02-estado-fluxo.md](02-estado-fluxo.md) | State LangGraph (TypedDict), thread_id, checkpoint, política de hidratação, fluxo de turno | Implementando `agente/graph.py`, `agente/estado.py` ou coordenador |
| [03-prompts.md](03-prompts.md) | Templates Jinja2, breakpoints `cache_control`, dataclass Persona, contexto dinâmico | Editando `agente/prompts/*.md` ou `agente/llm.py` |
| [04-tools.md](04-tools.md) | Catálogo completo de tools, contratos Pydantic, idempotência, comportamento de escalada | Implementando `agente/ferramentas/*.py` |
| [05-humanizacao.md](05-humanizacao.md) | Chunking, jitter/typing, dedupe, cancel-on-new-message, ordem texto/mídia, persistência saída | Implementando `agente/humanizacao.py` ou `workers/envio.py` |
| [06-pipelines-midia.md](06-pipelines-midia.md) | Transcrição de áudio, OCR/vision para Pix, comportamento de imagem fora-fluxo | Implementando `workers/media.py` ou `workers/pix.py` |
| [07-coordenador.md](07-coordenador.md) | Webhook → debounce → lock → resolução → invocação grafo → dispatch; cron de timeouts | Implementando `webhook/despacho.py`, `webhook/debounce.py`, `workers/timeouts.py` |
| [08-evals.md](08-evals.md) | LangSmith datasets, cenários canônicos, métricas Prometheus, gate de pronto-pra-piloto | Escrevendo testes ou evals em `evals/` |
| [09-roteiro.md](09-roteiro.md) | Marcos M0–M6, checklist executável por marco, comandos de verificação | Planejando ou executando uma sprint |
| [10-persona-jailbreak.md](10-persona-jailbreak.md) | Política AUP, non-disclosure passivo, protocolos defensivos, reminder injection, adversarial dataset | Editando persona/regras/protocolos; antes de cada release de prompt |

## Stack do agente (resumo)

- **Provider LLM:** Anthropic API direto via `anthropic` SDK (Python). Wrapper LangChain via `langchain-anthropic.ChatAnthropic` para integração com LangGraph.
- **Modelo principal (chat):** `claude-sonnet-4-6` — $3/M input, $15/M output, cache read ~0.1×, cache write 1.25× (TTL 5m) ou 2× (TTL 1h).
- **Modelo fallback (chat):** `claude-haiku-4-5` — mesma família, mesmo formato de tool calls, cache compatível. Acionado em `RateLimitError` ou `APIStatusError(status >= 500)`.
- **Modelo vision (Pix):** `claude-sonnet-4-6` (vision nativo + `output_config.format` com Pydantic via `client.messages.parse()`).
- **Modelo transcrição:** `whisper-1` direto na **OpenAI API** (exceção isolada — Anthropic não transcreve áudio). Único provider não-Anthropic do MVP, contido em `workers/media.py`.
- **Orquestrador:** LangGraph 0.4 com **StateGraph custom** (decisão `01 §2.1` — `create_react_agent` foi deprecado na LangGraph v1.0) + `AsyncPostgresSaver` (Supavisor 6543, transaction mode).
- **Worker de turno:** ARQ + Redis (lock de conversa, dedupe, cancel-on-new-message).
- **Tracing:** LangSmith desde o primeiro turno; metas em `08-evals.md §3`.

## Decisões-chave (índice rápido)

| Decisão | Onde está detalhada |
|---------|---------------------|
| StateGraph custom em vez de `create_react_agent` (deprecado em LangGraph v1.0) | `01 §2.1` |
| `thread_id = conversa_id` | `02 §2` |
| State minimalista (`MessagesState`) | `02 §3` |
| Coordenador como ARQ job (não inline no webhook) | `07 §1` |
| Anthropic SDK direto + Sonnet 4.6 / fallback Haiku 4.5 (mesmo provider) | `01 §2.5`, `01 §2.6` |
| Adaptive thinking + effort hibridizado (low default, medium em gatilhos) | `03 §6.2.1` |
| Prompt em 4 breakpoints `cache_control` + estrutura XML semântica | `03 §2.2`, `03 §4` |
| Few-shot examples > adjetivos descritivos para tom | `03 §2.2` |
| Tell-what-to-do (sem CRITICAL/NUNCA/PARE em 4.6) | `03 §3.1`, `03 §9` |
| **Non-disclosure passivo** (não nega ser IA ativamente; escala em insistência) | `10 §2` |
| Reminder injection no user turn (combate persona drift) | `03 §10` |
| Classificador heurístico de jailbreak/disclosure no webhook | `10 §8` |
| Adversarial dataset semanal (CI gate ≥90%) | `10 §7` |
| `max_tokens=512` (não 1024) para disciplinar output curto | `03 §6.1` |
| Retenção de checkpoint (90 dias por thread sem atividade) | `02 §3.2` |
| Tool `escalar` grava direto via `abrir_handoff` | `04 §3.5` |
| `pedir_pix_deslocamento()` sem args (R$100 fixo) | `04 §3.6` |
| Pix recusado: IA permanece pausada até Fernando devolver (override `mvp/04 §3.2`) | `01 §6.1` |
| Sliding window de 20 mensagens | `02 §4` |
| Transcrição via OpenAI Whisper API direto (Anthropic não transcreve) | `06 §1` |
| Pix vision via `client.messages.parse()` + Pydantic | `06 §2` |
| Lock Redis TTL 60s + heartbeat do worker (15s) | `07 §3.2` |
| Cron timeouts a cada 5min | `07 §4` |
| LangSmith datasets como eval primário | `08 §1` |

## Convenções de leitura

- **Trechos de código** mostram o `path/file.py:simbolo` exato sempre que possível.
- **SQL** aparece quando a query não é trivial (índice, RLS, lock).
- **Pydantic schemas** são a fonte de contrato; runtime checks no FastAPI usam-nos diretamente.
- **`# TODO(M{n})`** marca trabalho pendente que pertence a um marco específico do `09-roteiro.md`.
- **`docs/mvp/XX §Y.Z`** referencia o produto. **`docs/agente/XX §Y.Z`** referencia esta spec técnica.

## Status

- **Versão:** 1.2 (revisão pós-pesquisa 2026-05-02 — XML tags + few-shot persona + non-disclosure passivo + classificador adversarial)
- **Próximo passo:** executar M0 do `09-roteiro.md` (skeleton do grafo).
