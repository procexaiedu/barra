# agente/CLAUDE.md

Escopo: subsistema LangGraph que conduz a IA por modelo.

## Direção das dependências (regra dura)

`agente/` PODE importar `from barra.dominio.<x>.service import …`. `dominio/` **nunca** importa de `agente/`. Quebrar isso é bug arquitetural — corrija antes de seguir, não contorne com import tardio.

## Prompts são markdown, com Jinja onde há variável

`prompts/persona.md` e `prompts/regras.md.j2` são a fonte de verdade. O plano (`persona.md`) é markdown puro; os que interpolam variável usam Jinja com sufixo `.md.j2` (ex.: `regras.md.j2` interpola `desconto_max_pct` no bloco `<desconto>` — ADR-0004; `docs/agente/09 §4.4`). Para mudar tom ou regra de negócio do agente, edite o markdown — não cole string nova em `graph.py`, `classificador.py` nem em nenhum nó. Strings de prompt hardcoded no código são bug.

## Fronteira conduta ↔ tool description

Recorte da regra acima: tool descriptions (`ferramentas/*.py`, docstrings + `Field(description=…)`) são code-side por natureza — fazem parte do schema enviado ao modelo, então a regra "strings de prompt hardcoded são bug" não as proíbe; **ela delimita o que pode entrar nelas**. O modelo lê o prompt (BP_GERAL) e as descriptions (BP_TOOLS) no MESMO turno — duplicar conduta não é "senão ele não vê", ele vê os dois. Duplicar compra só redundância + drift (mude o protocolo no `regras.md.j2` e a DESC passa a mentir em silêncio). Três categorias:

1. **Mecânica de campo** (como preencher o arg, computação p/ derivar o valor, idempotência, o que a tool faz no sistema) → **só na DESC**; não migra pro prompt. Ex.: aritmética de horário relativo (`_DESC_HORARIO`), "grave `valor_acordado` junto com `duracao_horas`" (`_DESC_VALOR`), semântica do `limpar`.
2. **Conduta client-facing** (como falar/se portar com o cliente: foto antes de vídeo, desculpa pessoal, jeito de recusar) → **só no `regras.md.j2`**. Se a DESC precisa tocar, **referencia** ("siga sua conduta de X"), não reescreve. Faz certo hoje: o `ToolException` de `ConflitoAgenda` ("ver sua conduta de indisponibilidade"). Faz pela metade: o `Returns` do `consultar_agenda` (referencia E repete).
3. **Tool-selection policy** ("quando chamar / quando NÃO chamar") → versão **curta** na DESC (a Anthropic endossa "be prescriptive about *when* to call it"); o protocolo completo fica no prompt (`<quando_usar_escalar>`, protocolos de disclosure). A DESC aponta a fronteira, não replica o protocolo. **A fronteira NEGATIVA na DESC ("quando NÃO usar") NÃO é alvo de dedup**, ainda quando espelha o protocolo positivo do prompt: a Anthropic é explícita que exemplos negativos "define boundaries and ensure the tool doesn't over-trigger" — afirmar o limite pelos dois lados (positivo no prompt, negativo na DESC) é pedagogia, não duplicação. O "Quando NÃO usar" do `escalar` é o caso certo: complementa `<quando_usar_escalar>`, não o re-cola.

Regra de **leitura** usada nos dois lados (ex.: "cliente diz 'você' = a modelo" — `<sonda_o_encontro>` e `_DESC_TIPO_ATENDIMENTO`): **uma** afirmação canônica, o outro site referencia.

**Dedup não é deleção grátis:** remover uma cláusula de DESC que duplica o prompt pode regredir se o reforço no ponto de uso for load-bearing (cf. sensibilidade do "seria hoje?") — gate por simulador/eval antes de tirar, nunca mecânico.

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
