# 22 — O carimbo de cotação do e2e volta a existir, como em prod

**What to build:** no caminho do gate e2e, uma cotação que a IA de fato apresentou não fica
carimbada. O validador de ordem então acusa "confirmou sem ter cotado" em toda conversa que a IA
conduz até `Aguardando_confirmacao` — e o sinal HARD do gate vira ruído exatamente quando a conduta
melhora. Depois deste ticket, o carimbo no e2e acontece pelas mesmas regras que em prod.

A causa é a mesma classe do ticket 01: o caminho de persistência do e2e diverge do de prod. A rede
determinística do ADR 0022 (`_RE_PRECO_RS` / `_RE_PRECO_VALOR` + `_RE_PRECO_CONTEXTO`) mora em
`workers/envio.py`, e o worker de envio **não roda no harness** — o próprio harness documenta isso
em `evals/e2e/persistencia.py` e `evals/e2e/sessao.py`. Prod não tem o problema: lá o backstop
carimba `cotacao_enviada_em` quando o texto enviado tem cara de cotação, cobrindo o LLM que esquece
de marcar `cotacao_apresentada`.

**Blocked by:** None — can start immediately.

**Status:** resolved

- [x] a bolha da IA persistida pelo caminho do e2e passa pelo mesmo backstop de carimbo que o worker
      de envio aplica em prod — mesma regra, sem uma segunda cópia do regex divergindo com o tempo
- [x] um teste amarra o caso medido: a fala `400 1h no meu local amor`, gravada pelo caminho do e2e
      sem `cotacao_apresentada` na extração, deixa `cotacao_enviada_em` carimbado
- [x] o negativo continua valendo: texto sem cara de cotação (canned, reengajamento, número de
      endereço sem duração/local) **não** carimba — carimbar à toa satisfaria o guard de
      `CotacaoAusente` e dispararia reengajamento sem cotação real
- [ ] a corrida do `conduta_gate` volta a `violacoes_duras: 0` na conversa
      `decidido_rapido:eb02:156306795180224@lid` (corrida paga — quem autoriza é o humano)

---

Diagnóstico de origem: `.scratch/prompt-refactor/checkpoint-lote-03-08.md`, seção "A violação dura,
e por que ela NÃO é regressão do lote". O transcrito do caso está em
`api/evals/saidas/conduta-20260730-182944/transcritos.jsonl`, perfil
`decidido_rapido:eb02:156306795180224@lid`, turno 3.

> Este ticket nasceu do checkpoint do lote 03–08, não da auditoria original — por isso o número
> fora da faixa 01–21.

## Comments

Aberto pelo driver em 2026-07-30, depois de o gate do checkpoint reprovar com `violacoes_duras=1`.
A violação é **pré-existente** (aparece em `evals/saidas/fanout-fiel/transcritos.jsonl`, anterior ao
lote) e só ficou visível porque o lote 03–08 melhorou a condução: no baseline
`conduziu decidido_rapido` era 0% — a IA não chegava ao estado que aciona o validador —, e no
checkpoint passou a 50%.

---

Implementado em 2026-07-30. **Onde a regra passou a morar:** `barra/dominio/atendimentos/service.py`,
colada no `UPDATE` que ela dispara (`marcar_cotacao_enviada_por_texto`). Duas funções públicas:

- `texto_tem_cotacao(texto)` — a regra pura (os três regexes vieram inteiros de `workers/envio.py`,
  byte a byte, junto com o comentário que os explica);
- `carimbar_cotacao_por_texto_enviado(conn, atendimento_id, texto)` — o par (decidir, carimbar) num
  ponto só, para que nenhum chamador possa aplicar meia regra.

Escolha do lar: `evals/` pode importar `barra.*` mas nunca o inverso, então o canônico tinha de
ficar em `barra/`; entre `workers/envio.py` (de onde saiu) e o contexto `atendimentos`, o segundo
mantém as duas metades da regra — "este texto é cotação" e "carimbe `cotacao_enviada_em`" — na mesma
camada, e `envio.py` já importava a irmã da linha de cima. Assim o worker só orquestra envio.

Os dois chamadores: `workers/envio.py` (mesma transação do POST, comportamento idêntico — os três
testes de `tests/integracao/test_enviar_turno.py` que cobrem o carimbo em prod passam **sem** troca
de expectativa) e `evals/e2e/persistencia.py::gravar_resposta_ia`, logo depois do INSERT da bolha —
o ponto por onde passam `runner.rodar_e2e`, `sessao` e `massa`.

**Achado que o ticket não previa (critério 4).** Carimbar o banco, sozinho, não zera
`violacoes_duras`: quem produz a violação é `evals/sequencia.py`, e ele deriva o evento
`cotacao_apresentada` **dos args do `registrar_extracao`** — nunca lê `atendimentos`. No transcrito
medido o turno 3 chamou `registrar_extracao` sem o flag e o turno 4 não chamou tool nenhuma; o
carimbo no DB passaria despercebido pelo validador. Então `derivar_eventos` passou a emitir
`cotacao_apresentada` também quando a bolha do turno casa `texto_tem_cotacao` — **a mesma função**,
importada, não uma cópia. Ordem preservada: o evento sai junto com os de extração, antes da
transição do turno, o que mantém a semântica já documentada no módulo ("cotar e confirmar no mesmo
turno NÃO viola"). O caminho alternativo — levar `cotacao_enviada_em` para dentro de
`harness.estado_pos_turno` e derivar o evento do banco — foi descartado: mexeria no dict de estado
que todos os evals consomem e traria o atraso de um turno (o carimbo da bolha N só aparece na
leitura do turno N+1), sem ganho de fidelidade sobre reaplicar a mesma função pura.

O ganho de fidelidade é maior que o do validador: sem o carimbo, o guard `CotacaoAusente` barrava no
harness a transição para `Aguardando_confirmacao` que em prod passa. O gate media conduta pior do
que a real.

Testes novos em `api/tests/unit/test_carimbo_cotacao_backstop.py` (19 casos, sem DB e sem crédito):
regra pura nos dois sentidos, `gravar_resposta_ia` carimbando a fala medida com os guards de prod
(`IS NULL` + `estado IN ('Triagem','Qualificado')`), os negativos que não podem carimbar (canned,
reengajamento, "rua duque de caxias 880 amor", "Consigo às 22h amor") e o validador de ordem nos
dois sentidos — aceita o turno medido e **continua** acusando quando não houve preço nenhum.

Gate: `make lint` ✅, `make typecheck` ✅, `make test` ✅ (1829 passed, 239 skipped). Nenhum
`needs_db` novo. Critério 4 pendente: é corrida paga do `conduta_gate`, autorização do humano.

**Fechado no checkpoint (driver, 2026-07-30).** O `conduta_gate` rodou contra o baseline `dd4a7e9`
e voltou **APROVADO** (`empurrao_pct 0,0%`, `violacoes_duras 0`), com o lote melhorando condução
(`conduziu decidido_rapido` 0% → 50%), desfecho (`bate_desfecho_real` 83,3% → 91,7%) e forma
(`fluxo_jsd` 0,1985 → 0,1896). Números e a comparação das duas corridas em
`.scratch/prompt-refactor/checkpoint-lote-03-08.md`. `Status: resolved`.
