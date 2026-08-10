# Pontuação do prompt v1 — empurrão na cotação (ponto 4 do flywheel)

> **Ponto 4** do plano. Mede empiricamente se o **prompt v1** evita o ÚNICO anti-padrão robusto que o ponto 2 isolou: o **empurrão que afasta** — `f_glued_urgency` (urgência colada ao preço) e `f_glued_question` (pergunta/CTA de fechamento colada ao preço).
> **Gerado:** 2026-06-13 por workflows Claude Code offline (moeda abundante; não consumiu crédito de API de prod nem subiu o agente; §0 do `CLAUDE.md`). Read-only sobre `corpus.turnos/eval_cotacao/eval_judge_pred`; só a tabela NOVA `corpus.eval_v1_score` recebeu DDL/INSERT.

## Receita (do handoff ponto 2)

Para cada thread eb04 `hold_out=true` em `corpus.eval_cotacao` com `label_bin` e `cotacao_turno` (n=335):
1. **contexto** = `corpus.turnos` WHERE `turno_idx < cotacao_turno` (lead-up do cliente, SEM a reação).
2. **gera** o turno de cotação do candidato = roda o prompt v1 renderizado sobre esse contexto (modelo barato, offline).
3. **detecta** `f_glued_urgency` + `f_glued_question` (rubrica do juiz §12, `detector_features.md`).

Agrega a taxa dos dois traços no v1 e compara contra o **baseline do Vendedor real** (a taxa dos mesmos traços nos turnos de cotação REAIS de eb04, já em `corpus.eval_judge_pred`, run_tag='v1'). Menor = melhor. **NÃO** pontua por conversão prevista (κ≈0.07 — ponto 2 provou que o desfecho da cotação é quase-acaso).

## Perfil de modelo SINTÉTICO usado (fixo, igual p/ todos os 335 contextos)

A modelo eb04 do corpus não está no painel (prod só tem "Lucia Teste"). Perfil placeholder coerente, renderizado pelas MESMAS funções de produção (`barra.agente.persona.render_prefixo_geral`/`render_bp3`/`render_contexto_dinamico` — ver `render_v1_prompt.py`):

- **Identidade**: Manu, 25, pt-BR, Barra (Campinas-SP), endereço "Chácara da Barra, Campinas-SP", aceita interno+externo.
- **Programas**: Encontro 1h R$400 · Encontro 2h R$700 · Pernoite 12h R$2.500 · Atendimento ao casal 1h R$700.
- **Fetiches** (inclusos): beijo na boca, oral sem camisinha, namoradinha.
- **Contexto dinâmico**: estado `Qualificado`, agenda livre, sem bloqueios, sem cliente recorrente.
- **desconto_max_pct** = 0.10 (explícito, p/ não depender de `.env`).

Isso NÃO afeta a métrica: urgência/pergunta colada ao preço independe dos valores/agenda.

## Resultado

| Traço | **v1 (candidato)** | **Vendedor real (baseline)** | Δ |
|---|---|---|---|
| `f_glued_urgency` | **0.3%** (1/335) | 15.2% (51/335) | **−14.9pp** |
| `f_glued_question` | **0.0%** (0/335) | 17.3% (58/335) | **−17.3pp** |
| **qualquer empurrão** | **0.3%** (1/335) | 26.0% (87/335) | **−25.7pp** |

n efetivo = **335** (hold-out eb04 inteiro; sem truncamento). 1 turno saiu `sem_cotacao` (a candidata passou ponto de encontro, não preço — caso legítimo onde o contexto já estava pós-cotação).

O único turno do v1 com empurrão (ref do cliente omitida — PII): "...sou carinhosa e atenciosa 🥰 / 30-50 minutos tá ótimo, **te espero rs**" → "te espero" colado ao valor = urgência leve. Os 4 outros suspeitos de superfície ("seria hoje?", "que horário vc tava pensando?", "tinha algum tempo em mente?") foram **adjudicados como SONDAGEM de funil**, não CTA de fechamento — limpos pela rubrica §12.

> **Lift validado é negativo (ponto 2):** `f_glued_urgency` −13.3pp e `f_glued_question` −9.3pp no desfecho real. Menos empurrão = melhor. O v1 praticamente zera ambos; o baseline humano os comete ~1 em cada 4 cotações.

## Veredito

**O prompt v1 já está limpo do empurrão que afasta.** Produz a cotação quase sempre como a regra `<cotacao>` de `regras.md.j2` prescreve — "cote limpo e deixe o cliente responder; não cole pergunta de fechamento nem urgência no preço". Taxa de empurrão **0.3%** vs **26%** do Vendedor humano real: o v1 corrige exatamente o anti-padrão que o corpus puniu.

**→ O ponto 3 (10b contrastivo de cotação, "limpo vs empurrão") é DISPENSÁVEL para este anti-padrão.** Few-shots contrastivos só teriam alvo se o v1 produzisse empurrão com frequência mensurável; ele não produz. O orçamento do ponto 3 rende mais aplicado **ao reengajamento (§13)**, não à cotação: o ponto 2 mostrou que a perda nº1 é o **sumiço mudo** (55%), e a alavanca de conversão está em reabrir quem silenciou — não em refinar como o preço é entregue (que o v1 já acerta).

### Ressalvas honestas (não inflar o resultado)

- **Ground-truth do detector = LLM, sem anotação humana** (mesma âncora Sonnet do ponto 2). A fronteira "sondagem leve" vs "CTA de fechamento" é borrada; a adjudicação estrita resolveu a favor de "sondagem" (conservador p/ NÃO super-reportar empurrão).
- **Variância de harness observada:** o detector em batch grande (sem reasoning por-item) flagou 2/335 como `f_glued_question`; a re-adjudicação rigorosa dos 5 suspeitos de superfície reclassificou esses 2 ("seria hoje?") como limpos e achou 1 urgência ("te espero"). O número reportado (1/335) é o reconciliado pós-adjudicação. Em qualquer leitura (1 a 3 / 335), o v1 fica **≥1 ordem de grandeza** abaixo do baseline humano.
- **Geração estocástica:** o v1 quase sempre cota em bolhas limpas (preço + incluso + calor), porque a persona/voz/regras o empurram fortemente pra isso. Pequenas variações de redação não movem a conclusão.
- O v1 **não foi medido por conversão** (de propósito — κ≈0.07). Esta pontuação é de ADERÊNCIA ao anti-padrão, não de receita.

## Artefatos (em `scripts/eval_corpus/`)

- `render_v1_prompt.py` — renderiza o system prompt v1 com o perfil sintético, via funções de produção. Reprodutível: `cd api && uv run python ../scripts/eval_corpus/render_v1_prompt.py`.
- `v1_prompt_rendered.txt` — REMOVIDO do repo (03/07): o texto do prompt v1 não deve ser consultado pela sessão que escreve o v2; re-render possível via tag git, se algum dia for preciso.
- `detector_features.md` — rubrica do detector (2 features §12), derivada de `judge_prompt.md`.
- `v1_cotacoes_geradas.json` — as 335 cotações geradas pelo v1 (remote_jid → texto).
- `v1_features_detectadas.json` — as 335 detecções reconciliadas (features por turno).
- **Tabela `corpus.eval_v1_score`** (Postgres prod, schema `corpus`, run_tag='v1') — persistência: 335 linhas, cotação + features.

### Reproduzir a métrica (SQL)

```sql
-- v1
SELECT count(*) n,
  round(100.0*avg(f_glued_urgency::int),1)  pct_urgency,
  round(100.0*avg(f_glued_question::int),1) pct_question,
  round(100.0*avg((f_glued_urgency OR f_glued_question)::int),1) pct_empurrao
FROM corpus.eval_v1_score WHERE run_tag='v1';

-- baseline Vendedor real (eb04 hold-out)
SELECT count(*) n,
  round(100.0*avg(p.f_glued_urgency::int),1)  pct_urgency,
  round(100.0*avg(p.f_glued_question::int),1) pct_question,
  round(100.0*avg((p.f_glued_urgency OR p.f_glued_question)::int),1) pct_empurrao
FROM corpus.eval_judge_pred p JOIN corpus.eval_cotacao c USING (instancia, remote_jid)
WHERE p.run_tag='v1' AND c.hold_out AND c.label_bin IS NOT NULL;
```
