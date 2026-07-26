# 02 — Virar a chave: `extrair` no grafo, extração fora de `TOOLS`, enxugar os guards

**O que construir:** o grafo vivo passa a usar o nó `extrair` como caminho único da extração. `registrar_extracao` sai do catálogo `TOOLS` (o chat #1 nunca mais a chama), o fallback #2 e os guards de caminho-duplo são removidos do `llm.py`/`estado.py`, e os testes de roteamento são reescritos para o novo contrato. Depois deste ticket, o modelo mental é "o chat conversa; um nó lê o estado" — a extração roda **sempre**, pós-fala, no `extrair`, e a reoferta é inerente a ele.

Escopo:
- `TOOLS` passa a `[consultar_agenda, enviar_midia, escalar]` (ordem fixa — invariante de prefixo). O objeto `@tool registrar_extracao` continua existindo e mantém `handle_tool_error=True` (setado explicitamente, já que sai da lista iterada); seu schema é bindado só no `extrair`.
- `graph.py` registra o nó `extrair` (recebendo `chat`, `chat_extracao_barata` e `registrar_extracao`); sem `add_edge` de saída (roteia só por `Command`). `nos/__init__.py` exporta `no_extrair` sem sombrear o submódulo.
- `llm.py`: o ramo sem tool_calls roteia `goto="extrair"`; truncamento e mídia esgotada continuam indo direto a `post_process` (comportamento atual preservado). Removidos: bloco fallback #2, binds forçados (`chat_forcado`/`chat_forcado_barato`), guards de reentrada de extração, `_extraiu_no_turno`, e os helpers movidos para o `extrair` no ticket 01. `Literal`/Protocol do `Command` atualizados (o `llm` deixa de rotear para si na reoferta).
- `estado.py`: removidas `_extracao_forcada` e `_resposta_inline_concluida`; `_reoferta_tentada` mantida (agora checada no `extrair`).
- **Sem mudança:** `dominio/atendimentos/service.py` (`registrar_extracao_ia` intacto), `ferramentas/extracao.py` (a tool em si), `workers/coordenador.py`, `nos/prepare_context.py` (marcadores A2 intactos), `nos/tools.py`, `_idempotencia.py`.

**Bloqueado por:** 01 (o mecanismo do nó `extrair` precisa estar provado — sobretudo a injeção de `ToolRuntime` — antes de deletar o caminho antigo).

**Status:** ready-for-agent

- [ ] `registrar_extracao` fora de `TOOLS`; chat #1 com as 3 tools restantes em ordem fixa; `handle_tool_error` ainda cobre `registrar_extracao`.
- [ ] Grafo wired: nó `extrair` registrado, `llm` sem tool_calls → `extrair` → `post_process`, reoferta `extrair` → `llm`; sem fan-out (só `Command` nas saídas novas); `nos/__init__.py` exporta `no_extrair`.
- [ ] `llm.py` e `estado.py` enxutos: fallback #2, binds forçados, guards de reentrada de extração e as duas flags deletados; cap de mídia + `_midia_esgotada` preservados.
- [ ] `tests/agente/test_llm_forca_extracao.py` reescrito para o novo contrato (llm→extrair; extrair→post_process/llm; mute na 2ª falha; truncamento/mídia esgotada não passam por `extrair`).
- [ ] Gate completo verde: `make lint` + `make typecheck` + `make test` + `needs_db` no DB real (`-m "needs_db and not needs_key"`); side-effects verdes (`test_aviso_saida`, `test_bolha_pix`, `test_extracao_loc_pin`, `test_tools_idempotencia`, `test_registrar_extracao` — a tool/FSM não mudam).
- [ ] Review da **langgraph-reviewer** sobre o diff (roteamento por `Command`, injeção de `ToolRuntime`, ausência de fan-out) sem apontamentos bloqueantes.
- [ ] Invalidação única do cache de prefixo (remoção de `registrar_extracao` do catálogo) registrada no PR.
- [ ] **Pré-deploy (gated §0, não bloqueia o merge):** replay de conduta no simulador DeepSeek provando paridade nos cenários de reoferta (conflito de agenda, cotação ausente, par preço×duração) e de escalada canned (piso, tipo não aceito). Consome crédito real → autorização à parte.
