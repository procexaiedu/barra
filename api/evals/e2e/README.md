# Camada e2e — o agente conduz o atendimento (cliente simulado)

Testa se a **IA por modelo** consegue **conduzir um atendimento sozinha**, turno a turno,
contra um **cliente simulado ancorado num caso real do corpus** — a pergunta "o agente
substitui o Vendedor?".

Difere das outras camadas de eval:

| Camada | O que mede | Turnos |
|---|---|---|
| 1 — gate de segurança (`../seguranca/`) | isolamento/AUP/máquina de estados | 1, isolado |
| 2 — shadow (`../shadow/`) | 1 ponto de decisão vs Vendedor humano | 1, do corpus |
| **e2e (aqui)** | **a IA conduz a conversa inteira até a confirmação** | **multi-turn** |

## Linha de chegada (importante)

A IA, **pela conversa com o cliente**, leva o atendimento no máximo até
`Aguardando_confirmacao` (ou `Confirmado`, com Pix externo). `Fechado`/`Perdido` **nunca**
saem do chat do cliente — são **Registro de resultado** (modelo/Fernando) ou **timeout**
(cron). Confirmado em `dominio/atendimentos/service._decidir_transicao` e nas tools
(`agente/ferramentas/extracao.py`, `pix.py`).

Por isso **"completou o atendimento" = conduziu até a confirmação**, sem escalar por
incapacidade nem violar invariante. É exatamente o trabalho do Vendedor — ele também não
fecha no sistema. O desfecho real do corpus (`desfecho_proxy`) entra como **rótulo de
comparação**, não como algo que o agente produz.

`_decidir_transicao` sobe **um degrau por extração**
(`Novo→Triagem→Qualificado→Aguardando_confirmacao`), então conduzir é naturalmente
multi-turn.

## Peças

- `perfil.py` — `PerfilCaso`: o caso (modelo, abertura, persona/objeções, roteiro do
  cliente, desfecho real do corpus). `perfil_para_fixture` → fixture do `harness.seedar`.
- `cliente.py` — `ClienteRoteirizado` (falas fixas, offline, sem crédito). **O cliente nunca
  é um 2º LLM** (decisão do dev): na corrida real o cliente é o **Claude Code** conduzindo via
  `sessao.py`. Só o agente usa a API.
- `runner.py` — `rodar_e2e`: o loop multi-turn batch (reusa `harness.seedar`/`rodar_turno`),
  com um `ClienteSimulado` (ex.: `ClienteRoteirizado` na validação offline). Para na linha de
  chegada, em handoff, no sumiço do cliente ou em `max_turnos`.
- `sessao.py` — **servidor de sessão turn-by-turn** (o cliente é o Claude Code). Segura a
  conexão e roda **um turno do agente por POST `/turno`**. `GET /perfil` devolve as falas reais
  p/ o Claude Code se ancorar. Dois modos no `/fim`: padrão **ROLLBACK** (nada commita);
  `--persistir` **COMMITA** em barravips p/ o Fernando avaliar (ver abaixo). `--fake` valida sem
  crédito; corrida real ou `--persistir` exigem `E2E_AUTORIZADO=1` (§0).
- `persistencia.py` — **persiste a corrida no painel /observabilidade** (decisão: reusar o
  painel). Modelo sandbox fixa `🧪 E2E Sandbox`; cada caso vira uma conversa `origem='e2e'`
  (a migration `*_conversas_origem_e2e.sql` adiciona a coluna; o painel esconde e2e por padrão,
  filtro "E2E" no toggle). A cada turno grava a bolha da IA em `mensagens` (o worker de envio
  não roda no harness). `limpar_sandbox(conn)` apaga tudo da sandbox.
- `avaliacao.py` — `avaliar_e2e`: veredito determinístico (conduziu? vazou? bateu o
  desfecho real?). `gravar_veredito`: persiste a corrida em `corpus.eval_e2e` (conn AUTOCOMMIT
  separada, sobrevive ao rollback do seed; `run_tag` = registro de "já testado").
- `extracao.py` — `extrair_perfis` (por desfecho) e **`extrair_nucleo` (por EIXO DE
  COMPORTAMENTO**: decidido_rapido, objetor, ghost_pos_cotacao, explorador_ambiguo,
  pre_cotacao_sumiu, externo — dedup global, `por_eixo` de cada). Só SELECT, **sem crédito**.
  A persona embute as falas reais como âncora. Modelo = `MODELO_SINTETICA`.
- `lote.py` — monta o **núcleo de refs por eixo** (`extrair_nucleo`) com porta por item para o
  fan-out de sub-agentes; `--run-tag` pula refs já testadas (dedup via `corpus.eval_e2e`).
- `cenarios.py` — **catálogo de cenários sintéticos de funcionalidade** (`CenarioFunc`): fluxos
  que o corpus de venda não tem (externo c/Pix, pickup, remoto, desconto fora do piso,
  disclosure, jailbreak, foto de portaria), com `roteiro_cliente` fixo e expectativas (tool/estado).
- `massa.py` — **runner em massa dos cenários** com `ClienteRoteirizado` (Python, sem sub-agente):
  seed → condução → pós-evento determinístico (foto de portaria via `handoff_foto_portaria_ia`,
  sem worker/vision) → veredito. Dedup por `run_tag`, `k` execuções (pass^k; default 1), agrega
  cobertura. `--fake` valida o encanamento sem crédito; `--persistir` COMMITA cada cenário no painel
  (sandbox, §0); real exige `E2E_AUTORIZADO=1` (§0).
- `ddl.sql` — `corpus.eval_e2e` (uma linha por corrida, com coluna `eixo`). **Aplicado em prod 15/06**.

## Observabilidade (Langfuse + scores)

`sessao.py` e `massa.py` ligam o **trace Langfuse de prod** (ADR 0019) no startup via
`harness.habilitar_tracing()` — no-op silencioso sem as envs `LANGFUSE_*`. O `rodar_turno` aceita
`trace_tag` (marca os traces e2e como `"e2e"`, vs `"eval_gate"` do gate) e `escopar_trace` (cria um
trace-id determinístico + span, padrão do `coordenador.py`, devolvido em `ResultadoTurno.trace_id`).
No fim de cada corrida, `avaliacao.pontuar_no_langfuse` empurra o veredito determinístico como
**scores** no trace (`e2e_conduziu`, `e2e_sem_violacoes`, `e2e_bate_desfecho_real` — este só quando
há desfecho real do corpus), e `flush_langfuse` garante a entrega. O Langfuse é **self-hosted**
(`langfuse.procexai.tech`) — o MCP Langfuse aponta para outra instância (cloud).

## Rodar

**Validação offline (sem crédito, chat fake):**

```bash
TEST_DATABASE_URL=<prod-com-rollback> uv run pytest tests/agente/test_e2e_conducao.py -v
```

**Corrida real (gasta crédito do AGENTE, §0 — exige autorização):** sobe a sessão e o Claude
Code conduz como cliente, um turno por vez:

```bash
E2E_AUTORIZADO=1 TEST_DATABASE_URL=<prod-com-rollback> \
  uv run python -m evals.e2e.sessao --ref 'eb04:..@lid' --io /tmp/e2e --port 8765
# depois, por turno (o Claude Code lê /perfil e decide cada fala):
curl -s localhost:8765/perfil
curl -s -XPOST localhost:8765/turno -d '{"texto":"..."}'   # repete até conduzir/sumir
curl -s -XPOST localhost:8765/fim                            # rollback + shutdown
```

Só o agente chama a API (1 ainvoke/turno). O cliente é o Claude Code, ancorado nas falas reais.

## Orquestração multi-perfil (vários clientes em paralelo)

A visão: testar o agente contra **vários perfis de cliente reais ao mesmo tempo**, cada um um
**sub-agente Claude Code** que reage à IA em tempo real, do início ao fim da conversa.

- `lote.py` — `montar_lote`: extrai um **leque diverso** de refs do corpus (uma fatia de cada
  desfecho: convertido / perdido_objecao / perdido_sumiu) e atribui uma **porta por ref**. Só
  SELECT, sem crédito. `uv run python -m evals.e2e.lote --por-grupo 3 --porta-base 8800`.
- **Fan-out**: para cada item do lote, sobe uma `sessao.py` na sua porta e spawna um sub-agente
  conduzindo via `curl` (cada sessão é 1 perfil; portas distintas = sem colisão). Os sub-agentes
  rodam em paralelo. O `/fim` de cada um devolve o **veredito da corrida**.
- **Validado com `--fake`** (custo zero, rollback): 2 sessões + 2 sub-agentes-cliente em paralelo
  (convertido + objeção) conduziram até `Aguardando_confirmacao` e devolveram veredito; o
  `bate_desfecho_real` **discriminou** (true no convertido, false no que o real perdeu por objeção).

## Falta (próximos passos)

1. ~~**Extração de `PerfilCaso` do corpus**~~ — **FEITO** (`extracao.py`).
2. ~~**Sessão turn-by-turn (cliente = Claude Code)**~~ — **FEITO** (`sessao.py`).
3. ~~**Veredito por corrida + persistência em `corpus.eval_e2e`**~~ — **FEITO**: o `/fim` acumula
   os turnos, computa `avaliar_e2e` e devolve o veredito no JSON. Grava em `corpus.eval_e2e` com
   `gravar_veredito` numa conn **AUTOCOMMIT separada** (sobrevive ao rollback do seed), **guarded
   por `E2E_RUN_TAG`** (sem a env, só devolve o veredito; gravar exige a `ddl.sql` aplicada — §0).
4. ~~**Orquestrador multi-perfil**~~ — **FEITO** (`lote.py` + fan-out de sub-agentes, validado fake).
5. **Corrida REAL** (§0 — gasta crédito do agente): rodar o fan-out sem `--fake`, sobre o lote, e
   comparar a taxa de condução por desfecho real. Com `--persistir` (escreve no painel
   `/observabilidade`) e `E2E_RUN_TAG` + `ddl.sql` aplicada (grava vereditos), tudo §0.
