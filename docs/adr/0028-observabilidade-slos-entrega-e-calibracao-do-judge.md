---
status: proposed
---

# Observabilidade do agente em produção: SLOs, entrega de alertas e calibração do judge

Um deep-research (best practices de LLMOps 2025-2026) cruzado com auditoria do código real (22/06/2026, 4 camadas: qualidade da saída / traces / confiabilidade / segurança) confirmou que o monitoramento do agente é **muito mais maduro** do que um diagnóstico ingênuo sugere: output-guard 2-etapas (ADR 0016), EVAL-11 online amostrado, painel de avaliação humana (`avaliacoes_resposta_ia`), tracing Langfuse self-hosted (ADR 0019), anti-loop em 4 níveis com escalada determinística, ~30 métricas Prometheus, **8 regras de alerta** e Alertmanager montados no stack. O problema não é "falta instrumentação" — é o **último elo** aberto em cada camada. Este ADR registra os SLOs e as decisões que fecham (ou explicam por que não dá para fechar ainda) esses elos.

## Estado medido em produção (2026-06-22, leitura read-only do `barravips`)

A auditoria acima é de *capacidade* (a instrumentação existe e está correta). Uma leitura direta do banco de prod revela o *volume*, que reordena as prioridades:

| Métrica | Valor |
|---|---|
| Conversas com qualquer mensagem | **1** (o rig de teste da Lucia) |
| Conversas restantes | 379 — contatos importados (Fase 1), threads vazias |
| Respostas de texto da IA | 31 — **todas no mesmo thread** |
| Mensagens de cliente | 18 (17 texto + 1 imagem) |
| Linhas em `avaliacoes_resposta_ia` | **0** — nenhuma resposta avaliada por humano |

**Consequência que reordena este ADR:** o agente está *deployado mas sem tráfego real* — 1 conversa, 0 clientes reais, 0 rótulos humanos. Toda a maquinaria de **calibração / deriva / baixo-score** (Decisão 4, `fluxo_drift`, worker de baixo-score) é **correta porém prematura**: não há população para amostrar nem ground-truth para calibrar. O **carimbo do judge** (Decisão 4) não está bloqueado só pelo refactor paralelo — está bloqueado por **ausência de dados** (o judge disparou ~0 vezes sobre cliente real; o humano rotulou 0). O gargalo de "monitorar o agente em prod" **não é código** — é **tráfego real + Fernando rotulando** um punhado de respostas no painel. A instrumentação já está sobre-construída para o volume atual; passa a render valor quando o volume chegar. Próximo passo de maior valor: **pôr conversas reais a fluir e semear o ground-truth humano**, não mais instrumentação.

## Decisão

1. **SLOs declarados** (formalizam os limiares que os alertas já encodam; *proposta inicial, tuning do operador pós-go-live*):
   - **Qualidade:** `eval_pass_rate ≥ 0.95` por suite (erosão lenta), com **piso de crater `0.85`** (queda rápida).
   - **Latência:** turno p95 `< 20s` **e** p99 `< 40s` (cauda); HTTP p95 `< 2s`.
   - **Custo:** p95 do custo/turno `< 0.12 BRL` (alinhar a `settings.custo_alvo_brl`).
   - **Segurança:** vazamento `cross_modelo = 0` — qualquer ocorrência é `critical` (invariante #1, não espera taxa).

2. **Multi-window calibrado, não burn-rate cargo-cult.** O burn-rate multi-window clássico (14,4×) é calibrado para SLO de **disponibilidade alta** (99,9%); sobre um objetivo de **qualidade de 0,95** o 14,4× viraria limiar absurdo (>0,72 de falha). Adotamos a *ideia* multi-window — **rápido+profundo** (`<0.85/10m`, critical) ao lado de **lento+raso** (`<0.95/30m`, warning) — mais **p99 de cauda**. Implementado em `infra/monitoring/alert.rules.yml` (`AgenteEvalOnlineDespencou`, `AgenteLatenciaTurnoP99Alta`).

3. **Ligar a entrega do Alertmanager é a ação #1.** Hoje `alertmanager.yml` aponta para `http://localhost:9999/noop`: as **11 regras** sobem e agrupam mas **não chegam a ninguém** — alerta que não entrega é não-alerta. Destino a decidir (recomendado: **webhook→painel**, o canal que o Fernando já olha). Trocar o receiver e recriar o config no stack `barra-vips` **atinge produção (§0)**.

4. **A calibração do judge VIVO exige um carimbo.** Medir TP/FP/FN/κ do judge de prod contra o ground-truth humano do painel é **estruturalmente impossível hoje**: quando o judge bloqueia, a bolha é zerada (`Command(goto=END)`) → **nenhuma mensagem da IA é gravada** → o painel (keyed por `mensagens.id`) **nunca vê** o caso → o **FP do judge** (legítima bloqueada, ex.: o falso-positivo de endereço interno, ADR 0023) não é observável pelo ground-truth atual. Persistir o veredito do judge **por turno** (carimbo) é pré-condição da calibração; o subset *determinístico* tem sinal quase-nulo, porque a Etapa 1 bloqueia **antes** do envio (FP≈0 por construção).

5. **Escopo do trace e boot.** `cliente_id` entra como metadata/tag do trace (filtragem/debug por cliente; UUID opaco, não o telefone E.164 — invariante de cache preservado). O boot **grita** (`WARNING`) quando a chave Langfuse está vazia — antes ficava mudo, indistinguível de "tracing off de propósito" do cenário do redeploy git que zera o `Env` do stack.

## Considered Options

- **Burn-rate multi-window clássico (14,4× / 6× / 3×).** Rejeitado: calibrado para SLO de disponibilidade 99,9%; sobre qualidade 0,95 produz limiares sem sentido. A ideia multi-window foi mantida, o número não.
- **Calibrar o judge só com o guard determinístico offline** (reaplicar `tem_marcador_*`/`_scan_vazamento` sobre mensagens rotuladas). Rejeitado como entrega de valor: o guard determinístico bloqueia antes do envio, então toda mensagem enviada já passou pelos markers → FP≈0; não rende matriz de confusão útil.
- **Redator de PII absoluto por shape de RG/CPF na saída.** Adiado para o **escopo mínimo** (só telefone de OUTRA modelo, que casa com o invariante de isolamento): o redator absoluto arriscaria barrar a **chave Pix legítima** da modelo (protegida hoje justamente por não vir do cliente) e travar o fluxo.
- **Manter o status quo** (threshold estático janela-única + entrega `noop`). Rejeitado: o tree já tinha os alertas certos, mas mudos e sem cauda/crater; o custo de fechar é baixo.

## Consequences

- **Implementado LOCAL, não deployado** (só atinge produção no redeploy do `barra-worker` / recriação do config do Alertmanager — **§0, frase-a-frase**): `cliente_id` + boot warning em `core/tracing.py`; `AgenteLatenciaTurnoP99Alta` + `AgenteEvalOnlineDespencou` em `alert.rules.yml`. Gate verde local (ruff + mypy + pytest; testes de obs estendidos).
- **Pendente de decisão do dev (§0):** destino do Alertmanager; escopo do redator de PII; o deploy em si.
- **Pendente de fechar (arquivos quentes; havia sessão paralela ativa de refactor no momento da auditoria — segurar evitou conflito):** o **carimbo** do veredito do judge por turno (destrava a calibração); o **screening Unicode no webhook** (`normalizar()` como *checagem sobre cópia*, nunca transformando o corpo da msg — casefold/strip de acento corromperia o texto); o **pipeline de baixo-score → dataset de regressão + annotation queue** (torna a avaliação humana não-terminal).
- **`fluxo_drift`** (JSD da forma do funil, cron OFF) é o sinal referenceless mais próximo de uma métrica de qualidade contínua sobre prod; ligá-lo com threshold + roteá-lo ao Alertmanager é trabalho futuro, dependente da entrega estar ligada.
