# Eval set offline do agente — a partir do corpus real (§11/§12)

> **Ponto 2** do plano de `docs/agente/10 §14`. Transforma os achados §11 (motivo de perda) e §12 (reação à cotação) num **dataset de avaliação persistido + um judge offline calibrado**, para pontuar qualquer versão candidata do system prompt contra turnos reais segurados.
> **Gerado:** 2026-06-12/13 por workflows Claude Code (moeda abundante — não consumiu crédito de API de prod; §0 do `CLAUDE.md`). Read-only sobre `corpus.mensagens_raw/turnos/threads`; só as tabelas novas `corpus.eval_*` receberam DDL/INSERT.

## ⚠️ Este diretório é versionado — mas SÓ o código

O harness ficou fora do git até 2026-08 (o `.gitignore` da raiz excluía a pasta inteira) e por
isso a infraestrutura que fundamentou as decisões de prompt vivia numa máquina só. Agora o
**código** é versionado; o **dado** continua fora, separado arquivo a arquivo pelo `.gitignore`
deste diretório. A regra ao criar arquivo novo é uma pergunta: *contém fala de cliente?* Se sim
(ou na dúvida), ignore.

Fora do git, e por quê:

| O que | Por quê |
|---|---|
| `fichas_threads.jsonl`, `_phrasebook/`, `amostra_estilo_eb.json` | conversa real: `@lid`, nome, telefone, endereço |
| `ATLAS.md`, `PHRASEBOOK.md`, `prompt_aderencia_falas.md` | são corpus destilado (falas verbatim / índice de threads reais), não documentação de método |
| `_auditoria_itens.json`, `dossie_*`, `v1_*.json` | saídas geradas, derivadas de conversa real |
| **`_dados_reais/`** | as constantes de seleção de thread e as fichas reais que saíram dos `.py` — ver abaixo |

Tudo isso é **regenerável** a partir de `corpus.*` pelos scripts versionados. O que se perde ao
não versionar é tempo de recomputo, não conhecimento.

### `_dados_reais/` — a PII que morava dentro do código

`replay_agente.py`, `replay_agente_fiel.py`, `replay_agente_terminal.py`,
`gen_conversas_chave.py` e `gen_conversas_comparativo.py` tinham a seleção de threads reais
(`@lid` do cliente) e as fichas reais das modelos (nome, endereço do ponto de encontro, **chave
Pix = telefone de terceiro**) como literal no arquivo. Isso saiu para JSON em `_dados_reais/`,
carregado por `dados_reais.carregar(modulo, CONSTANTE)`.

Consequência prática: **num clone novo esses scripts falham** com uma mensagem explicando o que
falta. Copie o `_dados_reais/` da máquina que o tem, ou aponte `$EVAL_CORPUS_DADOS` para onde ele
estiver. É de propósito — o dado não deve viajar pelo git.

## O que existe agora (Postgres prod, schema `corpus`)

| Tabela | Linhas | Conteúdo |
|---|---|---|
| `corpus.eval_cotacao` | **784** | reação imediata à cotação (§12): `reacao_real` (5 enum), `label_bin` GOOD/BAD, multi-voto, `cotacao_turno`, `hold_out` (eb04) |
| `corpus.eval_perda` | **580** | motivo de perda (§11): `motivo` (enum CONTEXT), `declarado`, `bloco_grosso`, multi-voto |
| `corpus.eval_judge_pred` | **775** | predições do judge v1 (cego ao label) p/ calibração |
| `corpus.eval_reengajamento` | **1019** | cutucadas/pokes reais (§13): `reviveu`/`gap_bucket`/`tem_midia` determinísticos (SQL), `movimento`/`tem_desconto`/`tipo_silencio` multi-voto na população limpa (718). Ver `reengajamento.md`. |

Construção: para cada thread, **3 juízes Sonnet** leem o transcript (montado por `string_agg` no Postgres, blind ao proxy) e classificam; voto majoritário; `concordancia = n_votos/n_juizes`. DDL em `ddl.sql`.

## Arquivos

- `ddl.sql` — as três tabelas (idempotente).
- `wf_cotacao.js` / `wf_perda.js` — workflows de rotulagem (multi-voto). Re-rodar é idempotente (persist com `ON CONFLICT`).
- `wf_judge_valida.js` — roda o judge sobre os turnos reais.
- `judge_prompt.md` — **a rubrica versionada do judge** (v1), derivada de §12.
- `persistir.py` — lê o output do workflow direto do disco e faz upsert via `jsonb_to_recordset`. Uso: `DATABASE_URL=... python persistir.py <cotacao|perda|judge> <output.json>`.
- `metricas_judge.sql` — κ/TPR/TNR + lifts de feature.
- `wf_pilot_cotacao.js` — piloto (descartável) que validou o método antes da escala.
- **Ponto 5 (reengajamento, §13):** `reengajamento_ddl.sql` (tabela), `wf_reeng.js` (codificação de movimento multi-voto), `persistir_reeng.py` (agrega votos + UPDATE), `metricas_reeng.sql` (decay/lift/confound/hold-out), `reengajamento.md` (**relatório completo + resolução canned-vs-LLM**).

## Resultados-chave

### eval_cotacao (§12) — o ground-truth é sólido (cross-check não-circular)

GOOD 421 (54%) · BAD 355 (45%) · sem cotação no recorte 9. Concordância média **0.92** (605/784 unânimes).
O juiz leu a reação **cego ao `desfecho_proxy`**; o proxy (sinais duros, independente) confirma o achado central de §12:

- `silenciou` → **91.7%** proxy `perdido_sumiu` (§12 amostra: 82%).
- `fechou_logistica` → **70.7%** proxy `convertido_provavel`.

→ **a reação à cotação É o desfecho**: silêncio no número = perda; logística = conversão.

### eval_perda (§11) — reproduz o padrão de perda

`sumiu` 305 (53%) · `indisponibilidade` 135 (23%) · `preco` 79 (14%) · `outro` 37 · `risco` 15 · `fora_de_area` 9.
**Declarado 45% → 55% sumiço mudo** (§11: "56% somem mudos"). `sumiu` é 99% mudo; os demais ~100% declarados. Concordância 80% unânime.

> **Nuance do `bloco_grosso`:** definimos `reagiu_na_cotacao` (objeção OU silêncio imediato ao número) vs `drift_pos_cotacao` (engajou e esfriou depois). Isso **difere** do "drift pós-cotação ~73%" de §11, que agrupa o silêncio-imediato no bloco de perda silenciosa. Os sinais primários (sumiço mudo domina, preço é minoria) reproduzem; o `bloco_grosso` não é diretamente comparável ao número de §11.

### Judge offline (entregável 4) — **validado como FRACO para desfecho, robusto para anti-padrão**

| Recorte | n | acurácia | TPR (good) | TNR (bad) | **Cohen κ** |
|---|---|---|---|---|---|
| GERAL | 775 | 0.517 | 0.330 | 0.740 | **0.067** |
| eb04 (hold-out) | 335 | 0.519 | 0.337 | 0.768 | **0.096** |
| calib eb01-03 | 440 | 0.516 | 0.325 | 0.722 | 0.046 |

κ ≈ 0.07 (quase-acaso); acurácia 0.52 fica **abaixo** do baseline trivial sempre-GOOD (0.54). **Quantifica o teto de §12: a entrega da cotação NÃO prediz o desfecho.** O juiz tem TNR ok (0.74) mas TPR ruim (0.33) — herda o prior intuitivo "preço seco = ruim", que os dados desmentem.

**Lifts de feature vs desfecho real** (o que de fato importa):

| Feature | lift (GOOD% com − sem) | §12 | replica? |
|---|---|---|---|
| `f_glued_urgency` (urgência colada) | **−13.3** | −12 | ✓ forte |
| `f_glued_question` (pergunta colada) | **−9.3** | −9 | ✓ |
| `f_warmth` (calor) | +1.0 | +10 | ✗ (artefato de n pequeno em §12) |
| `f_bare` (preço seco) | +0.4 | −6 | ✗ (≈0) |

→ **O único sinal robusto da entrega é o empurrão que afasta** (urgência/pergunta colada ao preço). É uma **proibição**, não um preditor de conversão. O calor não é a alavanca que §12 (n=45/57, sem significância) sugeriu.

## Como usar (para a sessão de pontuação do prompt)

1. **NÃO** pontue um prompt candidato por conversão prevista — o juiz de desfecho é quase-acaso (κ=0.07).
2. **Pontue por aderência / anti-padrão:** gere o turno do Vendedor do prompt sobre cada `contexto_ate_cotacao` segurado (eb04) e meça a **taxa de `f_glued_urgency` + `f_glued_question`** (validados, lift real negativo). Quanto menor, melhor. Os detectores de feature do `wf_judge_valida.js` são a parte útil; o `outcome_pred` é a fraca.
3. **A alavanca de conversão está no reengajamento (§13), não na cotação** — o eval set de perda confirma: 55% de sumiço mudo é a perda nº1. Priorize avaliar o reengajamento na próxima rodada.

## Simulador de conversa — A/B offline

> **Fidelidade ao modelo de prod (LEIA):** o agente ao vivo roda **DeepSeek V4 Flash direto** (`criar_chat_deepseek`), não Claude. Para qualquer A/B cujo veredito vá para prod, use **`sim_deepseek.py`** (Vendedor = DeepSeek, réplica do chat #1). O `wf_simulador.js` roda subagentes **Claude** (Workflow `agent()` é Claude-only) → fica como scaffolding de conduta cross-model, **não** como prova de prod. Em-dash e propensão a emoji/verbosidade são tells **específicos do modelo** — medi-los no Claude é inútil para decidir guard contra DeepSeek.

### `sim_deepseek.py` (canônico, fiel ao DeepSeek)

Harness Python multi-turno: o **Vendedor** sob teste é chamado por `criar_chat_deepseek(settings, temperature=settings.chat_temperature)` — mesmo modelo, temp e thinking-disabled do chat #1 de prod. Cliente-sim e juiz também rodam DeepSeek (só plausibilidade). Mede CONDUTA com medidas **determinísticas** (tamanho do turno da cotação em palavras/bolhas, em-dash, âncora-N+1, incluso, emoji) + um juiz cego (calor, repetição robótica, empurrão, violação, desfecho). **§0: gasta crédito DeepSeek real (autorizado caso a caso); offline, não toca WhatsApp/banco/prod.**

```
cd api && uv run python ../scripts/eval_corpus/render_v1_prompt.py > /tmp/base.txt   # render do HEAD
# (gere a variante por edição do .j2 + re-render, OU por text-patch do render base)
cd api && uv run python ../scripts/eval_corpus/sim_deepseek.py \
    --base /tmp/base.txt --variante /tmp/variante.txt --tag-variante minha_mudanca \
    --personas preco_no_abridor,faz_x_quanto,decidido,sumido_rapido,info_depois_preco,preco_sensivel \
    --n-rep 2 --k 8 --conc 6 --out /tmp/ab.json
```

### `wf_simulador.js` (Claude — scaffolding, NÃO fiel)

Estende o harness single-turn (que mede só o turno da cotação) para **conversa multi-turno**. Dois subagentes alternam: o **cliente-sim** (5 personas ancoradas nos arquétipos de reação do `eval_cotacao`: decidido, preço-sensível, curioso-morno, sumido-rápido, caça-desconto) e o **Vendedor** (lê o prompt renderizado de produção como system, **no modelo Claude**). Ao fim, um **detector cego** mede empurrão (rubrica §12), calor e desfecho por conversa.

- **Para quê:** comparar variantes de prompt **na camada Claude** (robustez cross-model da regra, iteração barata) — **sem tocar prod, sem WhatsApp, sem crédito de API** (moeda Claude Code; respeita §0). Veredito de prod **não** sai daqui (ver `sim_deepseek.py`).
- **Antes de rodar:** `cd api && uv run python ../scripts/eval_corpus/render_v1_prompt.py > /tmp/v1_prompt_atual.txt`. Aí dispare o workflow com `args: { variantes: [{tag:'v1', path:'/tmp/v1_prompt_atual.txt'}], n_rep: 2, k_turnos: 10 }`. A/B = passar duas entradas em `variantes`.
- **Fidelidade (limitação):** o Vendedor **não** roda o grafo LangGraph (sem tools/extração/estado) — mede **conduta/estilo**, que é onde está o sinal robusto (score_v1; conversão é κ=0.07, inútil). Mesmo nível do score_v1, já aceito.
- **Validado (14/06):** conversa de 4 turnos (preço-sensível × v1, orquestrada à mão) confirmou viva a abertura social-leve, a cotação limpa (zero empurrão) e os 3 passos do desconto (oferta do piso → recusa-leve quente abaixo do piso → escalaria na insistência), fiéis ao HEAD.

## Limitações

- Ground-truth **sem anotação humana** — âncora = 3 juízes Sonnet + voto majoritário + cross-check de proxy. Confiabilidade ~75-80% unânime (fronteiras `engajou`↔`fechou_logistica` e `sumiu`↔`indisponibilidade` são borradas).
- `cotacao_turno` buscado nos primeiros 40 turnos (cotação 60 na perda) — 9 cotações ficaram fora da janela (`label_bin` nulo, excluídas das métricas).
- Hold-out eb04 é uma **tag** (`hold_out=true`); todas as threads foram rotuladas. O consumidor decide segurar eb04 na calibração/tuning.
