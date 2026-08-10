# Fidelidade de voz — métrica estilométrica + exemplos canônicos reais

> Sessão 1 do handoff de pesquisa (2026-06-16). Tudo **offline**: sem prod, sem WhatsApp, sem
> crédito de API (§0). Métrica em `estilometria.py`; perfil congelado em `perfil_estilo_corpus.json`.

## O problema

Voz deve migrar de *regras textuais* → *exemplos reais + métrica objetiva*. Faltavam as duas pontas:
(1) um sinal de "soa como ela?" e (2) exemplos reais no prefixo. A pesquisa (Anthropic *Effective
context engineering*; arXiv:2509.24930; 2509.14543) recomenda exemplos canônicos diversos (não
exaustivos), 5-7 saturam, e adverte que **registro informal PT-BR é o caso difícil** (o LLM
regride à média e apaga idiossincrasia).

## Camada 1 — estilometria como distância de distribuição (`estilometria.py`)

Pure stdlib (sem numpy/torch) → roda em qualquer lugar, sem DB nem crédito. Mede 6 features entre
um conjunto de bolhas geradas e o **perfil congelado d'ELA** (corpus real, `corpus.mensagens_raw`):

| feature | tipo | distância |
|---|---|---|
| comprimento de bolha | histograma | Jensen-Shannon (base 2, [0,1]) |
| ausência de ponto final | taxa | \|Δ\| |
| emoji-rate | taxa | \|Δ\| |
| vocativos (amor/vida) | taxa | \|Δ\| |
| n-gramas de caractere (trigrama) | distribuição | Jensen-Shannon |
| diversidade lexical (MATTR-50) | escalar | \|Δ\| |

**Agregado** = média simples das 6 (0 = idêntico à voz d'ELA). Sinal **relativo**: compare contra
o **piso de ruído ELA-vs-ELA = 0.0035** (split do mesmo registro). A própria Camada 1 já separa
vendedores diferentes do piso: cross-instância eb02×eb04 = 0.0415 (~12× o piso), eb01×eb03 = 0.0913.

Perfil de referência (33.815 bolhas): ponto final 0,1% · emoji 10,7% · vocativo 22,8% · MATTR 0,68 ·
pico de comprimento em 11-15 chars.

### Rodar
```
# (1x) gerar o perfil congelado a partir do corpus:
cd api && DATABASE_URL=... uv run python ../scripts/eval_corpus/gerar_perfil_estilo.py
# pontuar um candidato (json {"turnos":[...]} ou txt com turnos por linha em branco):
python ../scripts/eval_corpus/estilometria.py perfil_estilo_corpus.json candidato.json
# testes (sem DB/crédito):
uv run pytest ../scripts/eval_corpus/test_estilometria.py
```

## Parte A — 6 exemplos canônicos reais no BP_GERAL (testado e REVERTIDO)

A pesquisa (+ memória) apontou: **substituir os 4 exemplos fabricados** da `persona.md` `<exemplos>`
por **6 reais canônicos**, mantendo `<armadilhas_de_voz>` e as regras de voz (que no nosso caso são
guard-rails validados em prod). Cada exemplo foi escolhido por **forma × situação** e confirmado
como **canônico no corpus** (frequência): saudação (Oii 665 / saudação por horário 1822),
apresentação (sou bem tranquila 711 / namoradinha 643 / beijo+oral sem 704), cotação limpa (no meu
local 671 / aceito cartao 66), sondagem (seria agora 360), serviço (faço sim 40 / sim amor 843),
logística (me avisa 279). Valores viram placeholder `{valor}` para travar cópia literal.

O swap chegou a ser aplicado e passou no gate (`make lint`/`typecheck`/`test` 971 passed; os 2
guard-rails de cache byte-idêntico OK — mudança estática, sem dado por-modelo). **Mas o A/B abaixo
mostrou efeito neutro-a-negativo, então o swap foi REVERTIDO** (decisão do dev). Os 6 exemplos vivem
agora só como constante `BLOCO_REAIS` em `ab_exemplos_render.py`, para o A/B seguir reproduzível. A
`persona.md` em prod permanece com os 4 fabricados.

## Critério 4 — A/B offline (render COM vs SEM exemplos)

3 variantes que diferem SÓ no bloco `<exemplos>`, renderizadas pelas funções de prod (`persona.py`)
com o perfil sintético "Manu". Subagentes Sonnet (mesma família de prod) geraram o 1º turno do
agente para 12 clientes × 2 reps (rep1 = clientes que espelham os exemplos; rep2 = held-out).

Combinado (~60 bolhas/variante; menor agg = mais perto da voz; piso 0.0035):

| variante | agg | comprimento | emoji | vocativo | trigramas | cópia |
|---|---|---|---|---|---|---|
| A_sem (sem exemplos) | **0.1582** | 0.114 | 0.348 | 0.150 | 0.250 | 1 |
| B_fabricados (HEAD) | 0.1635 | 0.165 | 0.300 | 0.178 | 0.234 | 1 |
| C_reais (mudança) | 0.1747 | 0.138 | **0.417** | 0.184 | **0.230** | 4 |

**Direção do efeito (estável em rep1, rep2 e combinado):** adicionar exemplos **não reduziu** a
distância agregada; os reais até a **aumentaram** (A < B < C). O que domina e arrasta o agregado é
**emoji** (todas as variantes super-usam vs corpus 11%; os exemplos reais carregados de emoji
pioram) e **vocativo**. No sinal mais robusto de registro (**trigramas de caractere**, content-
independent), C é **neutro-a-marginalmente-melhor**. Cópia literal: 3 no rep1 do C eram artefato
de clientes que espelhavam os exemplos; com held-out cai a ~1/variante (C ainda lidera).

### Caveats (não over-claim)
- Mede o **simulador** (subagente Sonnet lendo o prompt), não o grafo LangGraph real — mesmo teto
  do `score_v1`/`wf_simulador`.
- n modesto (~60 bolhas/variante, 2 reps).

### Confound de mistura de turnos — RESOLVIDO (`perfil_abertura.py`)

Suspeita: o candidato é só turno de abertura (quente), enquanto o perfil completo inclui a cauda de
logística seca ("Sim", "1707") → o gap de emoji/vocativo poderia ser mistura, não defeito. Construí
uma referência **casada**: primeiras 8 bolhas d'ELA por thread (fase de abertura), `perfil_estilo_abertura.json`.

A abertura é só **levemente** mais quente que o corpus inteiro (emoji 11%→**14,4%**; vocativo 23%→21%).
Re-pontuando o A/B contra ela, **o ranking não muda e os números quase não se movem** (A 0.154 < B 0.159
< C 0.167). E as taxas BRUTAS do candidato confirmam super-aplicação mesmo contra o alvo justo:

| variante | emoji candidato | vocativo candidato |
|---|---|---|
| A_sem | 0.455 | 0.379 |
| B_fabricados | 0.407 | 0.407 |
| C_reais | **0.524** | 0.413 |
| *corpus abertura (alvo)* | *0.144* | *0.208* |

→ O agente usa emoji em **41-52%** das bolhas vs **~14%** reais (mesmo na fase mais quente) = **~3×**;
vocativo ~40% vs ~21% = **~1,8×**. **Confound descartado: super-emoji/vocativo é defeito de voz real,
não artefato de mistura.**

## Variante D — calibrar o `<voz>` (a alavanca, testada; `ab_voz_calibrada.py`)

Variante D = prompt de PROD (4 fabricados) com o `<voz>` editado: emoji/vocativo **esparsos** em vez
de "em toda mensagem" (só texto renderizado em memória, NÃO toca prod). Gerada nos 2 sets de clientes.

| variante | agg vs completo | agg vs abertura | emoji | vocativo |
|---|---|---|---|---|
| B_fabricados (prod) | 0.1635 | 0.1777 | 0.407 | 0.407 |
| **D_calibrada** | **0.1115** | **0.1131** | **0.200** | 0.138 |
| *alvo real (abertura)* | — | — | *0.144* | *0.208* |

**Calibrar cortou a distância agregada ~30%** (0.164→0.111) — de longe o maior ganho de voz do
estudo, muito acima de qualquer mexida em exemplos. Emoji 45%→20% (perto do real 14%); vocativo
caiu a 14% (passou um pouco do alvo 21% — calibração levemente agressiva, dá pra afrouxar). **Check
qualitativo:** a voz seguiu quente e humana ("Oii 😊", "amor", "rs", "🥰", bolhas curtas, "seria
hoje?") — só sem saturar; NÃO ficou robótica.

### APLICADO na persona.md (merge local, sem deploy) — variante E

Decisão do dev: aplicar a calibração. Wording final do `<voz>` (meio-termo: vocativo "só de vez em
quando, não em toda bolha"; "Emoji é raro") afrouxa a D pra não derrubar o vocativo abaixo do alvo.
Re-validado em 2 reps (n=63):

| variante | agg vs completo | agg vs abertura | emoji | vocativo |
|---|---|---|---|---|
| B_fabricados (HEAD anterior) | 0.164 | 0.178 | 0.407 | 0.407 |
| **E_aplicada (persona.md atual)** | **0.106** | **0.113** | 0.286 | **0.254** |
| *alvo real (abertura)* | — | — | *0.144* | *0.208* |

Melhor agregado de todas as variantes (**~35% abaixo do HEAD anterior**), vocativo **0.254 ≈ alvo
0.208** (sem o overshoot da D), emoji 0.286 (melhorou muito; ainda acima de 0.144, com folga futura
sem arriscar esfriar). Voz qualitativamente quente. Commit local `16b5e62` (merge `7566c91`),
gate verde (1002 passed). **Não deployado** (§0 — exige `service update --force` no worker).

## Conclusões acionáveis

1. **A métrica funciona** e dá sinal estável e decision-grade (piso 0.0035; separa instâncias 12-25×).
2. **A troca de exemplos é neutra-a-levemente-negativa** neste harness — não é um ganho de voz
   comprovado, e reintroduz cópia literal ocasional. **Não tratar como melhoria validada.**
3. **A alavanca real de voz é calibração de emoji/vocativo** — confound-controlado, quantificado e
   **APLICADO** na persona.md (merge local `7566c91`, sem deploy): distância agregada −35%
   (0.164→0.106), vocativo no alvo (0.254≈0.208), voz ainda quente. Falta só deploy (§0). Emoji ainda
   tem folga (0.286 vs 0.144) — afrouxar mais o `<voz>` é a próxima micro-iteração, se desejado.
4. **Decisão de produto pendente (dev/Fernando):** a persona `<voz>` manda calor "em toda mensagem"
   — escolha deliberada. A variante D prova que aproximar do alvo real (~14%/21%) é um ganho grande de
   fidelidade e continua quente. Ship exige decisão do produto (contraria a diretriz atual) + §0
   (deploy). Se for, afrouxar a calibração de vocativo (D passou pra 14%, mira ~21%).

## Camada 2 — sanity-check de style-embedding (`embedding_estilo.py`)

Pergunta: o embedding de estilo separa eb02 de eb04 (PT-BR)? Se não, fica-se só na Camada 1.

Rodado em env efêmero (`uv run --with sentence-transformers --with torch`, não toca o venv de prod),
modelo `StyleDistance/styledistance` (content-independent, NAACL 2025; treino majoritário em inglês),
400 bolhas/instância (≥20 chars):

```
distância entre centróides (1-cos): 0.0035
acurácia nearest-centroid (eb02 vs eb04): 0.667   (0.5 = acaso)
```

**Veredito: separação ACIMA do acaso, porém MODESTA (0.667).** Um style-model inglês tem só sinal
fraco-moderado em PT-BR. Para contraste, a Camada 1 (estilometria, stdlib) separa as MESMAS
instâncias de forma muito mais decisiva (eb02×eb04 = 0.0415 vs piso 0.0035 ≈ 12×).

**Decisão:** a **Camada 1 é a métrica primária** (mais clara, sem dependência pesada). A Camada 2
fica como esqueleto rodável; só vale promovê-la com um **style-model multilíngue de verdade** (LUAR
multilíngue, arXiv:2509.16531) — o teste em PT-BR com modelo inglês não justifica adotá-la agora.

### Rodar a Camada 2
```
cd api && DATABASE_URL=... uv run python ../scripts/eval_corpus/embedding_estilo.py amostra
uv run --with sentence-transformers --with torch python ../scripts/eval_corpus/embedding_estilo.py sanity
```
