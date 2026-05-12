# agente/CLAUDE.md

Escopo: subsistema LangGraph que conduz a IA por modelo.

## Direção das dependências (regra dura)

`agente/` PODE importar `from barra.dominio.<x>.service import …`. `dominio/` **nunca** importa de `agente/`. Quebrar isso é bug arquitetural — corrija antes de seguir, não contorne com import tardio.

## Prompts são markdown, não código

`prompts/persona.md`, `prompts/faq.md` e `prompts/regras.md` são a fonte de verdade. Para mudar tom, FAQ ou regra de negócio do agente, edite o markdown — não cole string nova em `graph.py`, `classificador.py` nem em nenhum nó. Strings de prompt hardcoded no código são bug.

## Isolamento por par (cliente, modelo)

Ver CONTEXT.md "IA por modelo". A IA da modelo A nunca enxerga histórico do mesmo cliente com a modelo B. Toda função que carrega contexto/histórico recebe `(cliente_id, modelo_id)` juntos; PR que carrega só por `cliente_id` está furando o isolamento — recuse.

## Checkpoint do grafo

LangGraph usa `AsyncPostgresSaver` (`langgraph-checkpoint-postgres`). Estado vive no Postgres. Não guarde estado de conversa em variáveis de módulo nem em dicionário em memória — some no próximo restart do worker.

## Prompt caching (Anthropic SDK 0.42)

Blocos estáveis (persona, FAQ, regras) entram com `cache_control: ephemeral` no início do prompt. Não recrie a árvore de mensagens do zero a cada turno — anexe só a nova mensagem do cliente; recriar perde o cache hit e fica caro.

## Organização

`graph.py` (montagem), `estado.py` (TypedDict do State), `humanizacao.py`, `classificador.py`, `nos/`, `ferramentas/`. Nó novo → `nos/`. Tool nova → `ferramentas/`.
