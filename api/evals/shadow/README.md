# Camada 2 — Shadow head-to-head contra o Vendedor humano

> **Pergunta que esta camada responde:** *a IA conduz a venda tão bem quanto o Vendedor humano?*
> É o melhor proxy **offline** de "substitui o Vendedor". **Advisory, não-blocking** (o gate
> BLOCKING é a Camada 1, segurança). Informa a decisão de cutover; não a trava sozinha.

## Por que shadow, e não conversão

O corpus tem **a resposta real do humano** em cada turno (71k mensagens, eb01-04). Em vez de
medir se a IA "converte" — impossível offline: o judge de desfecho é quase-acaso (κ=0.07, doc
11 §2) e o `@lid` do corpus não liga ao R$ do painel (memória `corpus_lid_telefone_irrecuperavel`)
— medimos **fidelidade comportamental**: dado o mesmo contexto que o humano viu, a IA faz uma
jogada **tão boa ou melhor**? É a métrica que o flywheel v1 já tocou num único eixo (empurrão na
cotação: IA 0.3% vs humano 26%, `score_v1.md`); a Camada 2 generaliza para **todos os pontos de
decisão**.

## Anatomia (reusa o harness da Camada 1)

Cada **ponto de decisão** do corpus vira uma pseudo-fixture do `evals.harness`:

```
contexto (turnos do corpus, turno_idx < ponto)  ->  historico da pseudo-fixture
última msg do CLIENTE antes da resposta humana   ->  turno_cliente
perfil de modelo SINTÉTICO fixo (Manu)           ->  cenario.modelo  (render_v1_prompt.py)
```

O `gerar.py` seeda isso no DB real (ROLLBACK sempre, **nada commita**), roda o grafo REAL
(`harness.rodar_turno` → `ainvoke` → Sonnet 4.6 com tools/estado) e coleta a **resposta da IA**.
Em paralelo lê do corpus a **resposta real do humano** (o(s) turno(s) `from_me` logo após o
ponto). Saída: `(contexto, resposta_ia, resposta_humano)` por thread — um JSON, igual
`v1_cotacoes_geradas.json`.

## Pontos de decisão (extração do corpus)

Cada um é uma query sobre `corpus.turnos` que localiza o turno do Vendedor a avaliar e corta o
contexto em `turno_idx < esse`. Pontos propostos (estratificar por modelo × desfecho, hold-out eb04):

| Ponto | Localização do turno do Vendedor | Eixo medido |
|---|---|---|
| **saudação** | 1º turno `from_me` da thread | abre quente, não-robótico |
| **cotação** | 1º `from_me` com preço de programa (já em `corpus.eval_cotacao.cotacao_turno`) | calor + sem empurrão (já validado v1) |
| **qualificação** | 1º `from_me` que pergunta horário/local/"pra quem" | coleta certa sem interrogatório |
| **objeção de preço** | `from_me` logo após `corpus.eval_cotacao.reacao_real='objecao_preco'` | desconto até o piso, sem regateio |
| **reengajamento** | poke real (`corpus.eval_reengajamento`, gap ≥40min) | pergunta_leve curta (canned já valida) |

## Scoring (duas moedas, como o dev pediu)

1. **Determinístico (grátis, Moeda A)** — sobre a resposta da IA:
   - empurrão na cotação (`detector_features.md`, já existe);
   - preço cotado bate a tabela sintética (regex de valor);
   - anti-padrões do corpus (doc 10 §6): `oral_gancho`, `endereço_cedo`, `viajante`;
   - persona/isolamento/formato (reusa `evals.checks`).
2. **Juiz Claude Code head-to-head (Moeda A, subagents do plano — NÃO crédito de API)** —
   recebe `contexto + resposta_A + resposta_B` com **posição randomizada** (cego a quem é IA/humano)
   e decide: *qual conduz melhor a venda, ou empate?* Rubrica = as 15 jogadas do doc 10 §4 +
   os anti-padrões. Painel de 3 votos, igual aos `wf_*.js` do flywheel. Persistir em
   `corpus.eval_shadow` (a criar). **Win-rate / tie-rate da IA vs humano** é a leitura de
   "substitui o Vendedor".

> **Único gasto de crédito de API (§0): a GERAÇÃO** — rodar o grafo sobre N contextos. Detecção
> determinística e juízes são Moeda A. Custo ≈ N × (1 turno). N e o custo estimado são decididos
> no gate da §0 antes de rodar (amostra estratificada; sugestão inicial: ~50-100 contextos/ponto).

## Estado

- `gerar.py` — **esqueleto pronto, NÃO executado** (guard `SHADOW_AUTORIZADO=1`). Reusa o harness.
- Extração SQL dos pontos de decisão, `corpus.eval_shadow` (DDL), e o `wf_shadow.js` (juiz
  head-to-head) entram **depois da autorização da §0** — não faz sentido materializá-los antes de
  decidir N e o orçamento.
