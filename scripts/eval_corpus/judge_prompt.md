# Judge offline da cotação — rubrica versionada (v1)

> Insumo do ponto 2 (eval set). Pontua **como o Vendedor entregou a cotação**, derivado de `docs/agente/10 §12`.
> O juiz é **cego à reação do cliente** — vê só a conversa até e incluindo o turno da cotação.

## O que o juiz recebe

- `contexto_ate_cotacao`: transcript dos turnos `turno_idx <= cotacao_turno`. A ÚLTIMA fala do Vendedor (V) é a **cotação** (o turno avaliado); o que vem antes é o lead-up do Cliente (C). **Não há nada da reação do cliente** — isso é o que se quer prever/avaliar.

## O que o juiz NÃO pode fazer

- Não inferir o desfecho a partir de pistas que não estão no turno da cotação.
- Não premiar urgência/pressão — §12 mostra que empurrão **afasta** (aparece mais em quem some).

## Rubrica (§12) — traços do turno da cotação

| Traço | Sinal | Direção (§12) |
|---|---|---|
| `f_warmth` | tom caloroso: "amor/vida/carinhosa", acolhimento, emoji orgânico | **+** (única alavanca robusta, +10pp) |
| `f_bare` | preço seco isolado, sem calor | − |
| `f_glued_urgency` | "seria agora?", "vamos confirmar?", pressa colada ao número | **−** (−12pp) |
| `f_glued_question` | pergunta/CTA de fechamento colada ao preço | − (−9pp) |
| `f_media_fria` | mídia fria disparada junto do preço | − leve |

## Saídas

- **features**: os 5 booleanos acima.
- **rubric_score** (0–1): aderência à prescrição §12 = **quente + limpo, sem urgência/pergunta colada**. Alto = cota com calor e sem empurrão. (Este é o métrico para pontuar um prompt candidato — mede adesão, não prevê conversão.)
- **outcome_pred** (GOOD|BAD): aposta de engajamento do cliente. GOOD se quente e limpo; BAD se seco ou com empurrão. **confianca modesta** — §12 diz que a entrega quase não determina o desfecho.

## Como isto vira métrica (validação — entregável 4)

1. Rodar o juiz sobre os turnos REAIS do Vendedor em `corpus.eval_cotacao` (cego ao `label_bin`).
2. `outcome_pred` vs `label_bin`: Cohen's κ + TPR/TNR (não acurácia crua — base ~54% GOOD), geral e só-eb04 (hold-out). **Espera-se κ baixo** — confirma o teto de §12.
3. Presença de cada feature vs `label_bin`: replicar os lifts de §12 (warmth deve favorecer GOOD ~+10pp). Se replicar, o `rubric_score` é um proxy de aderência válido mesmo com outcome_pred fraco.

## Uso futuro (fora do escopo do ponto 2)

Pontuar um prompt candidato: gerar o turno do Vendedor a partir do prompt sobre cada `contexto_ate_cotacao` segurado (eb04) → rodar o juiz → agregar `rubric_score` (e a taxa de anti-padrões urgency/bare). Compara prompts por **aderência §12**, não por conversão prevista.
