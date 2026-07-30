# Checkpoint do lote 03–08 — corrida de 2026-07-30

Corrida autorizada frase a frase pelo humano. Mesmos parâmetros do baseline (é o que a torna
comparável): `E2E_AUTORIZADO=1 make gate-conduta ARGS="--por-eixo 2 --max-turnos 12"`.

## Números, lado a lado

| métrica | classe | baseline `dd4a7e9` | checkpoint `91b6413` | leitura |
|---|---|---|---|---|
| `n_corridas` | contexto | 12 | 12 | igual |
| `empurrao_pct` (HARD, ≤5,0%) | **HARD** | 0,0% | **0,0%** | mantido |
| `violacoes_duras` (HARD, 0) | **HARD** | 0 | **1** | ⚠️ ver diagnóstico |
| `conduziu` `decidido_rapido` | advisory | 0% | **50%** | melhorou |
| `bate_desfecho_real_pct` | advisory | 83,3% | **91,7%** | melhorou |
| `estilo_dist_medio` (voz) | advisory | 0,2014 | 0,2118 | ~estável |
| `fluxo_jsd` (forma) | advisory | 0,1985 | 0,2341 | ~estável |
| custo (R$) | — | 0,0634 | 0,0910 | conversas mais longas |
| veredito | — | APROVADO ✅ | **REPROVADO ❌** | pelo HARD acima |
| transcritos | — | `conduta-20260730-145037` | `conduta-20260730-182944` | |

## A violação dura, e por que ela NÃO é regressão do lote

```
perfil : decidido_rapido:eb02:156306795180224@lid   (eixo decidido_rapido, 4 turnos)
violação: ordem: confirmou sem ter cotado (funil-vazamento)
          (gatilho='estado:Aguardando_confirmacao', faltou 'cotacao_apresentada')
```

A IA **cotou**. No turno 3 ela disse, literalmente:

> `400 1h no meu local amor` / `To num hotel bem discreto, você vai gostar rs`

O que faltou não foi a cotação — foi o **carimbo**. O `registrar_extracao` do turno rodou sem
marcar `cotacao_apresentada=True`, que é a falha conhecida do LLM ("cobrindo o LLM que esquece de
marcar `cotacao_apresentada`", comentário em `workers/envio.py`). Para exatamente isso existe a
**rede determinística do ADR 0022**, e a fala acima a casa com folga:

- `_RE_PRECO_VALOR` → `400` (3 dígitos) ✅
- `_RE_PRECO_CONTEXTO` → `1h` **e** `no meu local` ✅

**Em produção o carimbo teria acontecido e não haveria violação.** Mas o backstop mora em
`workers/envio.py`, e o worker de envio **não roda no harness e2e** — o próprio harness documenta
isso em três pontos (`evals/e2e/persistencia.py:6`, `:116`, `evals/e2e/sessao.py:222`).

Três evidências de que é artefato de harness, não regressão de conduta:

1. **Pré-existente ao lote.** A mesma violação, no mesmo eixo, está gravada em
   `evals/saidas/fanout-fiel/transcritos.jsonl` — artefato anterior a qualquer commit deste lote.
2. **O baseline nunca percorreu o caminho.** Lá `conduziu decidido_rapido = 0%`: a IA não chegava a
   `Aguardando_confirmacao` nesse eixo, então o validador de ordem nunca era acionado. Agora chega
   (50%) e o validador dispara.
3. **Todo o resto melhorou.** `bate_desfecho_real` +8,4 pp, `conduziu` do eixo +50 pp, `empurrao`
   mantido em 0,0%, voz e forma estáveis.

Ou seja: o lote **melhorou a condução** e, ao melhorar, expôs um buraco que já existia no harness.
É a mesma classe de bug do ticket 01 — o caminho de persistência do e2e divergindo de prod.

## O que os tickets do lote provaram nesta corrida

- **03/04/05/06** — nenhum HARD regrediu; a melhora de `conduziu` e `bate_desfecho_real` é
  consistente com o que eles pretendiam (a cauda parou de proibir a abertura e de travar a segunda
  venda; o horário mínimo virou piso). Os critérios de comportamento por cenário continuam
  dependendo de `evals.e2e.massa`, que não rodou.
- **07** — não houve nenhuma bolha de incluso fantasma nesta corrida, ao contrário do baseline (que
  produziu "Beijo na boca e oral sem camisinha já vem junto" com `<fetiches>` vazio). Consistente
  com a troca da fala ilustrativa, mas com N=1 não se conclui causalidade.
- **08** — `empurrao_pct` e a escada de desconto não regrediram; nenhuma expectativa foi afrouxada.

## Pendência que este checkpoint abre

O harness e2e precisa aplicar o backstop do ADR 0022 ao gravar a bolha da IA, como o ticket 01 fez
com o `uuidv7()`. Sem isso, todo gate futuro que conduzir bem vai reprovar por esta violação —
e o sinal HARD fica inutilizável justamente quando a conduta melhora.
