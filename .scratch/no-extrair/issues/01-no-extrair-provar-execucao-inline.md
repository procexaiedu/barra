# 01 — Nó `extrair`: provar execução inline da extração

**O que construir:** um nó novo `agente/nos/extrair.py` que, dado o state de um turno, monta a chamada forçada de extração (modelo barato via `chat_extracao_barata` + system mínimo; fallback para o chat principal quando o barato é `None`), **executa `registrar_extracao` inline** e decide o roteamento do turno. O caminho vivo **não muda** neste ticket: `registrar_extracao` continua em `TOOLS` e o fallback #2 continua em `llm.py`. O objetivo é **de-riscar o footgun** (injeção de `ToolRuntime` na execução inline) e provar o mecanismo ponta a ponta antes de qualquer deleção — model call → execução da tool → persistência em `barravips.tool_calls` → decisão de rota.

Comportamento do nó (espelha o fallback #2 + reentry-guard de reoferta que hoje vivem no `llm`):
- Guard de qualidade: forçado truncado ou sem tool_call → descarta e roteia a `post_process` só com a fala original.
- Execução inline preserva de graça: parse dos args achatados, `handle_tool_error`, idempotência por `(turno_id, "registrar_extracao", 0)` via `_executar_idempotente`, e o enqueue do card de aviso de saída.
- Roteamento: sucesso ou escalada canned (`novo_estado: None`) → `post_process` carregando o `AIMessage` forçado + o `ToolMessage`; `ToolMessage` de erro recuperável (`status=="error"` / `"ERRO:"`) **e** `reoferta_automatica_habilitada` **e** não `_reoferta_tentada` → `llm` removendo a bolha stale do turno + setando `_reoferta_tentada`; 2ª falha → `post_process` (mute).
- A extração roda sobre a janela **sem** a fala final (preserva a semântica atual de evitar dois assistants consecutivos).

**Must-verify:** confirmar que `ToolRuntime[ContextAgente]` é injetado corretamente e que `horario_minimo` propaga (a tool o lê para desambiguar `AntecedenciaInsuficiente`) quando a execução da tool acontece fora de aresta do grafo, dentro do `graph.ainvoke`. Se a injeção inline **não** funcionar, usar o fallback de desenho: extrair o corpo da tool para uma função pura `executar_extracao(ctx, args)` em `ferramentas/extracao.py` e chamá-la com `runtime.context` (duplica ~15 linhas do wrapper, mas elimina a dependência da injeção).

**Bloqueado por:** nada — pode começar imediatamente.

**Status:** ready-for-agent

- [ ] `agente/nos/extrair.py` criado com factory `no_extrair(chat, chat_extracao_barata, tool_extracao)`; helpers `_janela_para_extracao_barata`, `_SYSTEM_EXTRACAO_BARATA` e `_extracao_recente_errou` vivem no módulo novo (copiados do `llm.py`, que segue usando os seus por enquanto).
- [ ] Execução inline de `registrar_extracao` com `ToolRuntime` injetado e `horario_minimo` propagado; a linha `barravips.tool_calls (turno_id, "registrar_extracao", 0)` é persistida e `novo_estado`/`pix_solicitado` ficam legíveis (provado por teste `needs_db`).
- [ ] Card de aviso de saída continua sendo enfileirado quando o snapshot o dispara.
- [ ] Testes de roteamento com chat fake cobrem os 4 caminhos: sucesso→`post_process`, escalada canned→`post_process`, erro recuperável→`llm` (com `RemoveMessage` + `_reoferta_tentada`), 2ª falha→mute, e forçado truncado/sem tool_call→`post_process`.
- [ ] Footgun resolvido: injeção inline funciona **ou** o fallback de função pura está no lugar, com a decisão registrada no PR.
- [ ] Grafo vivo inalterado (`registrar_extracao` ainda em `TOOLS`, fallback #2 ainda em `llm.py`); `make lint` + `make typecheck` + `make test` verdes.
