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
  desfecho real?).
- `extracao.py` — `extrair_perfis`: monta `PerfilCaso`s do corpus (`corpus.threads` +
  `corpus.turnos`), só SELECT, **sem crédito**. Convertidos (`convertido_provavel`) e
  perdidos (`perdido_sumiu`/`perdido_objecao`); a persona embute as falas reais do cliente
  como âncora. Modelo = `MODELO_SINTETICA` (a ponte corpus→modelo real é irrecuperável).
- `ddl.sql` — `corpus.eval_e2e` (uma linha por corrida). **Não aplicado em prod** (§0).

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

## Falta (próximos passos)

1. ~~**Extração de `PerfilCaso` do corpus**~~ — **FEITO** (`extracao.py`, validado em
   `tests/agente/test_e2e_extracao.py`). Deriva abertura/roteiro/persona/rótulos de
   `corpus.threads` + `corpus.turnos`, convertidas e não-convertidas, sem crédito.
2. ~~**Sessão turn-by-turn (cliente = Claude Code)**~~ — **FEITO** (`sessao.py`, validado com
   `--fake`: subiu, conduziu Novo→`Aguardando_confirmacao` em 3 turnos, `/fim` reverteu).
3. **Persistência em `corpus.eval_e2e`** + veredito por corrida. Atenção ao isolamento
   transacional: o seed precisa de ROLLBACK (não poluir prod), mas `corpus.eval_e2e` precisa
   de COMMIT — **conexões separadas**. A persistência ainda não está ligada na `sessao.py`.
4. **Corrida real** (gasta crédito): rodar a sessão sem `--fake` sobre um lote de refs
   convertidas + perdidas, comparar a taxa de condução por desfecho real.
