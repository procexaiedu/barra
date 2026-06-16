# agente/CLAUDE.md

Escopo: subsistema LangGraph que conduz a IA por modelo.

## Direção das dependências (regra dura)

`agente/` PODE importar `from barra.dominio.<x>.service import …`. `dominio/` **nunca** importa de `agente/`. Quebrar isso é bug arquitetural — corrija antes de seguir, não contorne com import tardio.

## Prompts são markdown, com Jinja onde há variável

`prompts/persona.md` e `prompts/regras.md.j2` são a fonte de verdade. O plano (`persona.md`) é markdown puro; os que interpolam variável usam Jinja com sufixo `.md.j2` (ex.: `regras.md.j2` interpola `desconto_max_pct` no bloco `<desconto>` — ADR-0004; `docs/agente/09 §4.4`). Para mudar tom ou regra de negócio do agente, edite o markdown — não cole string nova em `graph.py`, `classificador.py` nem em nenhum nó. Strings de prompt hardcoded no código são bug.

## Isolamento por par (cliente, modelo)

Ver CONTEXT.md "IA por modelo". A IA da modelo A nunca enxerga histórico do mesmo cliente com a modelo B. Toda função que carrega contexto/histórico recebe `(cliente_id, modelo_id)` juntos; PR que carrega só por `cliente_id` está furando o isolamento — recuse.

## Sem checkpointer no P0

O grafo compila **sem** `checkpointer=` (`docs/agente/01 §6.7`). O prompt é montado do zero a cada turno a partir da tabela `mensagens` (sliding window, `01 §2.2`) — não há estado de conversa entre invocações. Estado vive no Postgres (`mensagens`/`eventos`), nunca em variável de módulo nem dicionário em memória. Continuidade/idempotência vêm de `tool_calls` + `turno_id` determinístico por `(job_id, loop_idx)` (`01 §6.7`), não de checkpoint. Reintrodução só em P1, se vier interrupt/time-travel.

## Prompt caching (chat via langchain-anthropic 1.x; raw SDK anthropic 0.97 no lock)

Blocos estáveis entram com `cache_control` no `system`, na ordem de render `tools → system → messages`. Sem checkpointer, a árvore é **re-renderizada todo turno** (`01 §6.7`) — o cache hit não depende de reusar o objeto, e sim de o **prefixo (`tools`+`system`) sair byte-idêntico** entre turnos. Recriar é correto; o que mata o cache é vazar variabilidade no prefixo. Detalhe completo em `docs/agente/03-prompts.md §4`.

**Invariante de prefixo global (quebrar isto derruba o cache de TODAS as modelos):**
- 4 breakpoints fixos, na ordem do prefixo: **BP_TOOLS** (`cache_control` na última tool via `build_tools_para_bind`; cache de tools é segmento próprio — doc oficial `tool-use-with-prompt-caching` — não retroage de breakpoint no `system`) → **BP_GERAL** (persona+regras+FAQ FUNDIDOS num único SystemMessage; antes eram 2 separados, fusão libera 1 breakpoint pro BP_JANELA) → **BP_MODELO** (identidade + programas, por-modelo) → **BP_JANELA** (`marcar_cache_na_penultima` na janela deslizante; lookback de 20 blocos da Anthropic estende o cache entre turnos enquanto a janela for append-only).
- `tools` e BP_GERAL são **byte-idênticos entre todas as modelos**. Nenhuma descrição de tool nem BP_GERAL interpola dado por-modelo — o nome da modelo vive só no BP_MODELO. `TOOLS` é constante de módulo congelada, ordem fixa; **proibido** `build_tools(modelo)` ou subsetting de tools por modelo.
- Dado por-modelo só no BP_MODELO. Dado por-turno (contexto dinâmico, reminder) vai no **último turno do usuário, SEM `cache_control`** — nunca em bloco `system` nem na penúltima.
- Listas/dicts no prefixo renderizam em ordem determinística (`ORDER BY` / `sorted`), senão os bytes variam e o cache mira a frio em silêncio.

**Guard-rails (testes obrigatórios):** (1) BP_GERAL e o bloco `tools` renderizam byte-idênticos para 2 modelos diferentes; (2) a mesma conversa renderiza byte-idêntica em 2 renders (cobre `traduz_mensagens`, pré-requisito do BP_JANELA — append-only invariant).

**Validação em prod:** hit-rate e write-rate como métrica viva; write-rate alto em regime (>10-15% pós-warmup) = invalidador silencioso no prefixo → investigar antes de culpar custo.

## Organização

`graph.py` (montagem), `estado.py` (TypedDict do State), `classificador.py`, `nos/`, `ferramentas/`. Nó novo → `nos/`. Tool nova → `ferramentas/`. A humanização (chunking/jitter/presence) não vive aqui: roda no worker `enviar_turno` (`workers/`, despachada via `despachar_humanizacao`).
