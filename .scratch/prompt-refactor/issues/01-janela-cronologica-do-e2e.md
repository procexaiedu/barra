# 01 — Janela do e2e volta a chegar em ordem cronológica

**What to build:** hoje, no caminho do gate e2e, as bolhas da IA chegam ao modelo fora de ordem cronológica — a saudação de abertura aparece depois da cotação. A janela que a IA lê no e2e passa a ter a mesma ordem que ela tem em prod, e o baseline do gate fica registrado para servir de referência a todos os tickets seguintes.

A causa é o desempate da consulta da janela: ela assume id time-ordered (uuidv7) e o caminho de persistência do e2e grava a bolha da IA com um uuid aleatório. Prod não tem o problema — grava com o default da tabela.

**Blocked by:** None — can start immediately.

**Status:** resolved

- [x] a bolha da IA persistida pelo caminho do e2e recebe id time-ordered, como o caminho de massa do shadow já faz
- [x] um teste amarra a ordem: dado um turno com 3 bolhas da IA, a janela renderizada devolve as 3 na ordem em que foram ditas
- [x] uma conversa de 8+ turnos no gate mostra a saudação em primeiro lugar na janela, não no meio
- [x] o resultado do `conduta_gate` pós-correção fica registrado num arquivo de baseline sob `.scratch/prompt-refactor/`, com data e commit — é o número contra o qual os tickets 03+ comparam
- [x] `make test` verde

---

Diagnóstico de origem: `.scratch/prompt-refactor/auditoria-carga-instrucional.md` (com os anexos `inventario-turno.md` e `eixo-*.md`, que trazem as linhas citadas).

> Os anexos citam número de linha; este ticket cita bloco/tag de propósito — os números do `regras.md.j2` envelheceram em 40 min durante a própria auditoria.

## Comments

**Implementação (2026-07-30).** Nenhuma mudança de conduta: o ticket é de encanamento do harness,
não toca prompt, e por isso não há bloco/tag afetado nem eco multi-site envolvido.

- `evals/e2e/persistencia.py` (`gravar_resposta_ia`) já estava corrigido na árvore antes de eu
  começar — o INSERT usa o default `barravips.uuidv7()`. Auditei em vez de reescrever.
- Sobrou um `uuid4()` no mesmo caminho: `evals/e2e/massa.py::_disparar_foto_portaria` gravava a
  mensagem da foto de portaria com id aleatório. Trocado pelo default + `RETURNING id` (o handoff
  precisa do id de volta). É latente hoje (o evento roda depois do último turno, ninguém mais lê a
  janela), mas é o mesmo invariante e ficaria como armadilha.
- `carregar_mensagens` e `prepare_context` já desempatam por `id` (`ORDER BY created_at DESC,
  id DESC` + `reverse()`) — nada a mudar em `src/`.
- Teste novo: `tests/agente/test_e2e_conducao.py::test_bolhas_da_ia_voltam_na_ordem_em_que_foram_ditas`
  (`needs_db`, sem `needs_key`). Ele afirma três coisas: as 3 bolhas voltam na ordem em que foram
  ditas; `created_at` empata de verdade (senão o teste não exercitaria o desempate); e todo `id` da
  janela é uuid **v7**. Só a terceira asserção é determinística contra a regressão — com `uuid4()` a
  ordem acerta por acaso ~1/6 das vezes.
- Prova empírica do sintoma (script descartável, fora do repo, tudo com ROLLBACK): repetindo a
  inserção com `uuid4()`, 2 de 3 corridas embaralharam, uma delas exatamente no sintoma do ticket
  ("o encontro de 1h fica 400" antes de "oii amor, tudo bem ?"). `created_at` distintos = 1 nas três.

**Gate pago pendente (§0 — não rodei).** Os critérios 3 e 4 dependem de uma corrida real do
`conduta_gate`, que gasta crédito do agente. O arquivo de baseline
`.scratch/prompt-refactor/baseline-conduta-gate.md` já existe com a estrutura pronta e os campos
marcados `_(pendente)_`; o comando exato está lá. Enquanto não houver autorização frase a frase,
o ticket fica `claimed`.

**Fechamento (driver, 2026-07-30).** A corrida do gate foi autorizada pelo humano frase a frase e
rodou: `E2E_AUTORIZADO=1 make gate-conduta ARGS="--por-eixo 2 --max-turnos 12"`, 12 corridas,
R$ 0,0634, **VEREDITO APROVADO** (`empurrao 0,0%`, `violacoes_duras 0`). Números completos em
`.scratch/prompt-refactor/baseline-conduta-gate.md`.

Critério 3 provado no trace do 8º turno da conversa `externo:eb02:…` (Langfuse
`f6d48c6f66a8a1645b9280820c90b3d9`): a janela chega com a saudação de abertura em PRIMEIRO lugar e
a cotação depois — o sintoma exato que este ticket existia para matar. O mesmo trace mostra 97% de
cache hit no prefixo.

**Achado que o ticket 07 herda:** a corrida reproduziu a falha do 07 (modelo com `<fetiches>` vazio
dizendo "Beijo na boca e oral sem camisinha já vem junto") e o gate marcou `violacoes_duras: 0` —
o HARD não pega esse eixo. Registrado no baseline com o caminho do transcrito, para o 07 usar como
cenário de regressão sem corrida paga nova.

`Status: resolved` — os 4 critérios cumpridos.
