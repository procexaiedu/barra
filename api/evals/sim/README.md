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
