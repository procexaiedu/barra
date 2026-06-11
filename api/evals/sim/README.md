# Simulador de cliente dual-control (EVAL-12)

Um cliente-LLM que conversa com o grafo em **loop fechado** e dispara as transições do atendimento
por **atos observáveis** (mandar Pix, foto de portaria, aviso de saída, ficar em silêncio) — não
por mensagens da IA. Inspirado em tau2-bench (dual-control) + RealUserSim (anti-leakage).

## POR QUE é NÃO-GATE (leia antes de usar)

**Proibido usar o simulador como critério de cutover.** Razões:

- **Infla** (até ~9 pp): o cliente-LLM é cooperativo e não cobre a cauda adversarial de forma
  determinística; "verde no sim" superestima a robustez real.
- **Não-determinístico:** cliente-LLM + agente-LLM em loop → resultado varia entre runs; gate de
  go-live precisa ser reproduzível.
- **Redundante no P0:** o multi-turno do P0 já é coberto por fixtures **pré-roteirizadas**
  (`scripted_5/`, EVAL-01) — mesmas seeds, graders determinísticos.

O simulador serve para **DESCOBRIR** falhas. O fluxo é: rodar jornadas → achar uma trajetória ruim
(vazamento de persona, estado errado, recusa indevida) → **promover essa trajetória a uma fixture
pré-roteirizada de `scripted_5/`** (transcrevendo as mensagens do cliente + o `state_check`
esperado). É o **corpus determinístico** que conta para o gate, **nunca** o verde-no-sim.

## Componentes

- `atos.py` — os atos dual-control que **mutam o estado real** no banco de teste (`enviar_pix`
  válido/duvidoso, `enviar_foto_portaria`, `enviar_aviso_saida`, `ficar_em_silencio`). SQL puro
  parametrizado; cada ato cita a regra de `CONTEXT.md` que espelha.
- `cliente.py` — `PersonaCliente` (intenção + dados plausíveis, **nunca o gabarito**) e
  `montar_prompt_cliente` (**puro**, anti-leakage: recusa montar prompt com termo de gabarito).
  `ClienteSimulado.decidir` chama o Sonnet (needs_anthropic_api).
- `loop.py` — `jornada(...)`: o loop fechado cliente ↔ grafo (reusa `runner.py` por caminho),
  coleta a `Trajetoria`. needs_db + needs_anthropic_api.

## Anti-leakage (RealUserSim) — invariante crítico

O cliente simulado **nunca** recebe o gabarito/expectativas da fixture — só sua intenção + dados +
o que observa (as últimas bolhas da IA). Se ele visse o gabarito, "atuaria para o teste" e
inflaria/mascararia as falhas. `montar_prompt_cliente` é puro e **levanta `ValueError`** se um
termo de gabarito (`expectativas`, `tool_calls_*`, `nao_deve_conter`, `isolamento_canary`,
`state_check`, `nodes_*`, `limiar_aceite`) escapar para a persona. Coberto offline por
`tests/evals/test_sim_anti_leakage.py`.

## Como rodar (passo do operador) · `needs_db` + `needs_anthropic_api`

```python
# da raiz de api/, com TEST_DATABASE_URL + ANTHROPIC_API_KEY, dentro de transação + ROLLBACK
from evals.sim.cliente import ClienteSimulado, PersonaCliente
from evals.sim.loop import jornada

persona = PersonaCliente(
    nome="Rafa",
    o_que_quer="agendar um programa interno pra hoje a noite",
    orcamento="ate uns 600",
    atos_disponiveis=["enviar_aviso_saida", "enviar_foto_portaria"],
)
seed = {"estado_inicial": {"atendimento_estado": "Triagem", "ia_pausada": False}}
traj = await jornada(conn, seed, ClienteSimulado(persona), max_turnos=8)
# inspecionar traj.passos -> se achar falha, roteirizar como fixture em scripted_5/
```

O loop **não** roda offline (chama o grafo e o cliente-LLM). A verificação offline cobre só a
lógica pura anti-leakage; o run live é passo do operador.

## Rodada em massa (`massa.py`) — continua NÃO-GATE

`uv run python -m evals.sim.massa` roda a composição completa (~52 jornadas: 19 cenários robo ×
K=2 com perfis de `perfis.py` + 11 fixos + 3 held-out) com teto de custo (`--teto-brl`, aborta) e
escrita incremental em `evals/registros/rodadas/<carimbo>/massa.jsonl`. Os **perfis** variam só a
FORMA da persona (apressado, regateiro, desconfiado…), nunca o objetivo — senão os roteiros
`decidir_ato` por índice/estado dessincronizariam. O `estilo` passa pelo mesmo check anti-leakage
de `montar_prompt_cliente`.

O veredito da rodada é de `evals.diagnostico.veredito` (offline) e o gate continua sendo o runner
K=5 (`make cutover`) — o verde da massa segue **não** contando para o cutover; ela contribui com
invariantes-duros, taxa E2E estrutural e a fila do juiz. Ver `evals/README.md` §"Rodada de go-live".

### Ponte Claude Code (`--cliente-ponte`)

Com `--cliente-ponte`, o lado cliente dos cenários robo deixa de chamar a API (regra: **crédito
de API só para o agente do Barra**): `cliente_ponte.py` escreve cada turno do cliente como
`<rodada>/ponte/<id>__t<N>.pedido.json` (prompt já renderizado por `montar_prompt_cliente`, mesmo
guard anti-leakage) e espera o `*.resposta.json` (`{"mensagem": ...}`), escrito por um agente do
Claude Code (tokens do plano). Resposta deve ser gravada atomicamente (tmp + `mv`); sem resposta
em 15 min a jornada falha sozinha e a rodada segue. Fixos/held-out seguem roteirizados (já eram
custo zero do lado cliente).
