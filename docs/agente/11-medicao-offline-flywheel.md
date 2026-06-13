# 11 — Flywheel de medição offline: do corpus ao prompt v1 validado

> **Projeto:** Central Inteligente de Atendimento — Elite Baby
> **Escopo:** fecha o loop iniciado em [`10`](10-corpus-real-vendedor.md)/[`10b`](10b-corpus-fewshots.md). Aqueles docs **mineraram** o corpus real; este registra o que aconteceu depois — escrever o prompt v1, **medir** o v1 contra turnos reais segurados, e a conclusão de que o rendimento offline se esgotou. **Não é o prompt** nem novo insumo de mineração: é o relatório de validação.
> **Data:** 2026-06-13.
> **Audiência:** quem for decidir o próximo passo do agente conversacional (GEPA? A/B ao vivo?) ou reusar a eval suite.
> **Precedência:** onde divergir de um ADR vigente, o ADR vence. Achados empíricos aqui **refinam** §12/§13 do doc 10 (marcados abaixo).

---

## 1. O loop e por que parou

O doc 10 §14 deixou 4 próximos passos. Foram executados como um flywheel de 5 etapas (numeração desta sessão de trabalho, 12–13/06):

| # | Etapa | Estado | Conclusão de uma linha |
|---|---|---|---|
| 1 | Escrever persona/regras/FAQ v1 | ✅ | gate verde + isolamento limpo (memória `prompts_v1_redacao_decisoes`) |
| 2 | §11/§12 → eval set + LLM-judge | ✅ | a **entrega da cotação não prediz conversão** (κ≈0.07) |
| 3 | Reformatar 10b em pares contrastivos | ❌ dispensável | o v1 já está limpo do único traço robusto (ponto 4) |
| 4 | Pontuar o v1 contra o hold-out | ✅ | v1 satura o anti-empurrão (**0.3% vs 26%** do humano) |
| 5 | Eval de reengajamento (§13) | ✅ | reengajamento é **canned já ótimo**; gap/pergunta_leve validados |

**Por que o loop parou:** em tudo que é mensurável offline, o v1 já está no teto. As duas frentes onde um prompt poderia melhorar a conversão — a cotação e o reengajamento — ou **saturam** (cotação: o v1 não comete o empurrão) ou **não passam pelo LLM** (reengajamento: pool canned). **GEPA não tem gradiente pra subir em nenhuma das duas.** O que resta só é medível ao vivo (ver §5).

## 2. Os três achados centrais

**(a) A forma de cotar quase não importa pra conversão (refina §12).**
O judge de desfecho da cotação é quase-acaso: **κ=0.067** (geral), 0.096 (eb04 hold-out), acurácia 0.52 — abaixo do baseline trivial (sempre-GOOD = 0.54). O único traço robusto da *entrega* é negativo: o **empurrão que afasta** — `f_glued_urgency` (lift −13.3pp, §12 dizia −12) e `f_glued_question` (−9.3pp, §12 −9). **O calor NÃO replica em escala** (`f_warmth` +1.0pp; o +10 de §12 era artefato de n=45/57). Cotar é uma **proibição** (não empurre), não um preditor de conversão.

**(b) O v1 já não empurra.** Pontuado sobre o hold-out eb04 inteiro (n=335) vs o Vendedor humano real:

| Traço | v1 | Vendedor real | Δ |
|---|---|---|---|
| `f_glued_urgency` | 0.3% | 15.2% | −14.9pp |
| `f_glued_question` | 0.0% | 17.3% | −17.3pp |
| qualquer empurrão | **0.3%** | **26.0%** | −25.7pp |

≥1 ordem de grandeza abaixo do humano em qualquer leitura. Por isso o ponto 3 (few-shots contrastivos de cotação) ficou sem alvo: o formato `<errado>/<certo>/<porque>` já vive na persona v1 (`<armadilhas_de_voz>`) e o traço que ele combateria já está zerado.

**(c) O reengajamento canned acerta o que o humano erra (valida e refina §13).**
Ground-truth determinístico (`reviveu` = cliente respondeu em 24h, via SQL) sobre **1019 cutucadas reais** deu a §13 a significância que faltava (o doc tinha n=9 em pergunta_leve):
- Gap curto vence: 62%→53%→47%→37% (p=3e-07) → política "~30min" do CONTEXT **validada**.
- `pergunta_leve` é o melhor movimento (68.5%, p=5.8e-05); `escassez` é fraco (27.8%); `desconto` é o pior (11%, n=9). Sobrevivem ao controle de gap.
- **Refuta §13:** mídia a frio **não** é tóxica (55%, ns) — o "14%/n=7" era artefato.
- Os 3 cards canned (`_canned.py`) são **100% pergunta_leve**, curtos, 0% desconto, delay 30min — acertam o move vencedor. O **humano aloca mal** (52% calor, 24% escassez-pior, só 10% pergunta_leve). **A IA reengaja melhor que o vendedor humano nessa dimensão.**

## 3. A eval suite (ativo reutilizável)

Persistido no Postgres (schema `corpus`, prod self-hosted) — antes só existia como agregado nos docs:

| Tabela | Linhas | Conteúdo |
|---|---|---|
| `corpus.eval_cotacao` | 784 | §12: reação à cotação, `label_bin` GOOD/BAD, multi-voto, `cotacao_turno`, `hold_out` (eb04) |
| `corpus.eval_perda` | 580 | §11: `motivo` (enum CONTEXT), `declarado`, `bloco_grosso`, multi-voto |
| `corpus.eval_judge_pred` | 775 | predições do judge v1 (calibração) |
| `corpus.eval_v1_score` | 335 | pontuação do v1 na cotação (`run_tag='v1'`) |
| `corpus.eval_reengajamento` | 1019/718 | §13: pokes detectados, `reviveu`, `movimento` (3 juízes), `gap_bucket` |

Harness e relatórios versionados em **`scripts/eval_corpus/`** (untracked, não commitado — consistente com o working tree dos pontos 1/2/4/5): `score_v1.md`, `reengajamento.md`, `render_v1_prompt.py`, os `wf_*.js` (workflows de rotulagem multi-voto) e os `*.sql` de métrica reprodutível. Memórias durables: `eval_set_ponto2_judge_fraco`, `score_v1_cotacao_empurrao_limpo`, `eval_reengajamento_ponto5`.

**Reuso:** pontuar qualquer prompt candidato futuro = gerar a cotação sobre os contextos eb04 segurados e medir a taxa de empurrão (`score_v1.md` tem a receita). Calibração: o ground-truth foi ancorado por 3 juízes Sonnet + voto + cross-check de proxy não-circular (`silenciou`→91.7% `perdido_sumiu`; `fechou_logistica`→70.7% `convertido`).

## 4. Por que GEPA não tem alvo offline

GEPA evolui o texto do prompt contra uma métrica com gradiente. As duas métricas robustas que temos não oferecem ladeira:
- **Cotação:** a única métrica válida é a taxa de empurrão, e o v1 já está em 0.3% — saturado, sem espaço pra otimizar.
- **Reengajamento:** o texto é canned (`escolher_reengajamento()` no cron `reengajar_silenciosos`, `workers/timeouts.py` — nunca invoca o grafo). Não há prompt LLM a evoluir; o bloco `<reengajamento>` em `regras.md.j2` é doc não-fiada.

Rodar GEPA hoje queimaria crédito de juiz sem retorno. Reavaliar **se e quando** o reengajamento migrar pra LLM, ou se uma métrica de conversão real (não proxy) ficar disponível.

## 5. Próxima fronteira: A/B ao vivo

O offline atingiu seu teto. As alavancas que sobram são intrinsecamente online:
- **Conversão real** (`Fechado`), não os proxies — `reviveu ≠ Fechado`, e há viés de sobrevivência (só vimos as cutucadas que o Vendedor escolheu mandar).
- **Toque único vs 2º toque** no reengajamento (§13 só mediu a 1ª cutucada; o humano é multi-toque ~2,1/thread).
- **`delay` < 30min** (o decay é monotônico; o ótimo pode ser < 30min).

Isso cai na **§0 do CLAUDE.md** (gasta crédito de agente em prod, exige autorização frase-a-frase) e pressupõe o piloto controlado (rig Lucia, `instancia_lucia_compartilhada`).

## 6. Decisões de produto que emergiram (para Fernando)

- **Ligar o reengajamento** (`reengajamento_ativo` default OFF hoje): a evidência (a) valida a política ~30min/sem-desconto e (b) mostra que o canned da IA aloca o movimento melhor que o humano. É a alavanca da perda nº1 (sumiço mudo, 55%).
- A **forma de cotar** não merece mais investimento de prompt — o v1 já está calibrado; foco futuro vai pro reengajamento e pra prova/mídia, não pra "como cotar".

## 7. Limitações

- **Sem anotação humana.** Âncora = 3 juízes Sonnet + voto + cross-check de proxy. Concordância: 0.92 (cotação) / 0.969 (reengajamento, 89.8% unânime) / mais fraca na fronteira sondagem-vs-CTA da cotação (adjudicada conservadora).
- **Proxy ≠ conversão.** `reviveu` mede reabertura, não `Fechado`; o desfecho da cotação tem teto ~50% de precisão (doc 10 §10). Nenhuma métrica aqui é causal — frequência/aderência validam *generalização*, não *causalidade de conversão*.
- **Hold-out cross-modelo** segura eb04 (o mais rico); eb01 nunca é hold-out (raso). Generalização além das 4 linhas eb01–04 é hipótese.
