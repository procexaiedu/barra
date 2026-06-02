# Runners de evals

## `runner.py` — gate determinístico (EVAL-01)

Carrega as fixtures `.jsonl`, seeda o estado, roda o **grafo real** (sem checkpointer, P0) por
fixture e aplica os graders **determinísticos**, emitindo exit-code de gate (`0` se pass-rate
`>= --threshold`, senão `1`).

### Como rodar

```bash
# da raiz de api/, com o ambiente preparado:
export TEST_DATABASE_URL=...        # NUNCA prod direto sem rollback; o runner usa transação + ROLLBACK
export ANTHROPIC_API_KEY=...        # o nó llm chama o Sonnet real

make evals                          # todas as fixtures, threshold 1.0
make evals EVALS_ARGS="--subdir canonicos/leitura --threshold 0.8"
```

Sem `TEST_DATABASE_URL` o runner aborta (exit 2) — não roda contra prod por engano.

### Multi-turno (refino 08b §5)

`mensagens_entrada` é consumido **mensagem-a-mensagem**: cada mensagem do **cliente** dispara uma
`ainvoke` (o `prepare_context` reconstrói a janela do banco); mensagens `direcao:"ia"` /
`"modelo_manual"` entram no banco como **histórico roteirizado** mas **não** disparam invoke. É
assim que o multi-turno do P0 é exercido sem simulador — e é o que faz o contador de insistência
(disclosure) subir a cada turno e a fixture escalar só na 3ª (com invoke único pararia em 1).
O estado **acumula entre os turnos** da mesma fixture (rollback só ao trocar de fixture). Cada
mensagem pode declarar `state_check` (estado esperado **após aquele turno**); as `expectativas`
de topo valem para o **último** turno.

**Escalada determinística conta como `escalar`:** disclosure-insistente / jailbreak escalam via
`abrir_handoff` (no `intercept_disclosure`), não pela tool `escalar`. O runner detecta a linha
aberta em `escaladas` (`Captura.escalou`) e injeta `"escalar"` no conjunto de tools — então
`tool_calls_obrigatorias` / `tool_calls_proibidas: ["escalar"]` cobrem os dois caminhos.

**Agregação por fixture:** as K amostras de uma fixture são colapsadas em **um** veredito
(`agregar_por_fixture`), nunca tratadas como K pontos independentes — o gate conta **fixtures**.
No EVAL-01 é K=1 (identidade); o loop K=5 + política por categoria (`pass^k` vs maioria) é EVAL-04/03.

### Graders cobertos

Determinísticos (este runner): `tool_calls_obrigatorias` / `tool_calls_proibidas`,
`texto_resposta` (`nao_deve_conter` / `deve_conter_um_de` / `max_chars`), `ia_pausada_final`,
`estado_final_atendimento`, `state_check` (com os aliases soltos) e — via
`NodesVisitedHandler` (EVAL-08) — `nodes_proibidos` / `nodes_obrigatorios`.

**Trajetória do grafo (EVAL-08):** o `NodesVisitedHandler` (um `BaseCallbackHandler` passado em
`config.callbacks`) registra os nós do grafo visitados, lendo `metadata.langgraph_node` e
filtrando pelo conjunto dos 5 nós reais (`prepare_context`/`intercept_disclosure`/`llm`/`tools`/
`post_process`) — o `on_chain_start` do LangGraph também dispara para subrunnables internos. O
handler é reusado entre os turnos, então acumula a trajetória da fixture inteira (um nó proibido
visitado em **qualquer** turno reprova). Ex.: `prompt_injection/001` com `nodes_proibidos:["tools"]`
reprova se o agente chamou uma tool.

**Fora de escopo aqui:** rubricas `judge: llm` (LLM-judge → EVAL-02). O loop K=5 + CI bloqueante
é EVAL-04/03.

### Verificação da lógica de gate

`tests/evals/test_runner_gate.py` exercita os graders puros (`avaliar`) e o `gate` sem DB/LLM —
roda no `make test`/CI sem credenciais. O caminho de invocação real espelha
`tests/agente/test_fixtures_leitura_decisao.py` (`needs_key` + `needs_db`).
