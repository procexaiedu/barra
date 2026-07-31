# 19 — NUNCA volta a ser sinal

**What to build:** a conduta tem 178 palavras integralmente em maiúscula e só 27 são proibição — as outras 151 são ênfase de contraste (ELE, VOCÊ, DELE, SUA, DENTRO, OFERECE…). O critério documentado reserva o caps para linha dura e failure-mode comprovado; os 13 NUNCA passam no critério, mas competem por saliência com 151 palavras que não são proibição.

Este ticket troca a ênfase de contraste por outro recurso, preservando intactos os NUNCA e os NÃO. Zero chars de ganho: é regravação, não corte.

**É um wide refactor** — toca linhas em todos os blocos do arquivo. Vem depois de todos os tickets cirúrgicos de propósito: vindo antes, conflitaria com cada um deles e tornaria ilegível o diff de todos. Passe único, fácil de reverter.

**Blocked by:** 03, 04, 05, 06, 07, 08, 09, 10, 11, 12, 13, 14, 15, 16, 17, 18

**Status:** claimed

- [x] nenhuma palavra em caps que não seja proibição sobra no arquivo — escopo declarado = **BP_GERAL** (`regras.md.j2` + `persona.md`); no BP_GERAL renderizado, 209 palavras em caps → 33, e as 33 são as 26 de proibição + `"ERRO:"`×2 (literal de sistema) + BDSM×2, CEP, DDD, IA (siglas). Ver `## Comments` para o escopo e a recontagem
- [x] os NUNCA e NÃO existentes continuam idênticos, em número e em posição — `regras.md.j2` NUNCA 13→13, NÃO 13→13; `persona.md` 0→0. Nenhuma linha com proibição foi tocada
- [x] nenhuma regra muda de sentido — o diff é só de ênfase: 176 trocas, todas caixa-alta→minúscula da MESMA palavra, mais 7 negritos por ambiguidade de leitura. Zero palavra removida, zero frase reordenada, zero cláusula nova
- [ ] `conduta_gate` verde contra o baseline de 01 — **gate pago, pendente de autorização** (comando no `## Comments`)
- [ ] A/B no simulador antes e depois, com o resultado anexado ao ticket (é o gate mais fraco da lista; registre o número, não só "passou") — **gate pago, pendente de autorização**; os dois prompts do A/B já estão materializados em `.scratch/prompt-refactor/ab-19/` e o comando exato + a métrica a comparar estão no `## Comments`

---

Diagnóstico de origem: `.scratch/prompt-refactor/auditoria-carga-instrucional.md` (com os anexos `inventario-turno.md` e `eixo-*.md`, que trazem as linhas citadas).

> Os anexos citam número de linha; este ticket cita bloco/tag de propósito — os números do `regras.md.j2` envelheceram em 40 min durante a própria auditoria.

## Comments

### Recontagem: os 178/151/27 do enunciado envelheceram (e dá pra dizer onde)

O enunciado vem da auditoria (30/07 12:27); oito tickets commitaram no `regras.md.j2` depois dela.
Recontei no arquivo atual (`\b[A-ZÁÀÂÃÉÊÍÓÔÕÚÇ]{2,}\b`) e refiz a série por commit:

| commit | total caps | NUNCA | NÃO | proibição |
|---|---:|---:|---:|---:|
| `c44003d` (tag de fase — era o estado da auditoria) | 194 | 13 | 14 | **27** |
| `03da146` (menage vira gate) | 192 | 13 | 14 | 27 |
| `9f8e7e5` (vídeo chamada vira gate) | 189 | 13 | 13 | **26** |
| `8fc4cbf` (HEAD, ponto de partida deste ticket) | 190 | 13 | 13 | **26** |

Ou seja: o 27º sinal de proibição era um `NÃO` que morreu junto com a prosa de negação da vídeo
chamada, no ticket 12 — **o denominador foi o que sobreviveu**, e é ele que este ticket ataca. O
"178" da auditoria é menor que os 190 de hoje porque os tickets cirúrgicos reescreveram linhas
inteiras; a diferença é ruído de contagem, não regressão.

Números com que fechei, para o escopo declarado:

| | `regras.md.j2` | `persona.md` | BP_GERAL renderizado |
|---|---:|---:|---:|
| caps antes | 190 | 19 | 209 |
| — proibição (`NUNCA`/`NÃO`) | 26 | 0 | 26 |
| — literal `"ERRO:"` / siglas (BDSM, CEP, DDD, IA) | 4 | 3 | 7 |
| — **ênfase de contraste (o alvo)** | **160** | **16** | **176** |
| caps depois | 30 | 3 | **33** |
| — não-proibição depois | 4 (`ERRO`×2, `BDSM`×2) | 3 (siglas) | 7 |

Delta de chars: `regras.md.j2` 55.112 → 55.140 (**+28**, os 7 pares de `**`), `persona.md`
14.772 → 14.772 (**0**). É regravação, como o ticket pedia — nada saiu.

### Escopo: BP_GERAL sim, cauda não (e por quê)

O ticket diz "o arquivo" (`regras.md.j2`). Ampliei para **`persona.md`** e parei aí. Motivo:
`persona.md` e `regras.md.j2` são **fundidos num único SystemMessage** (`render_prefixo_geral`) —
é a mesma superfície de saliência, lida no mesmo lugar, pelo mesmo leitor. Deixar caps de contraste
em `persona.md` resolveria metade do denominador dentro do próprio bloco que hospeda os 13 NUNCA.
Reforça: `persona.md` tem **zero** palavra de proibição em caps — as 16 que tinha eram 100%
denominador, sinal puro de ruído.

**Fora do escopo, de propósito: a cauda** (`contexto_dinamico.md.j2`, 28 caps de contraste sobre 11
de proibição; `reminder.md.j2`, 7 caps, nenhuma de proibição). É outra mensagem (última
HumanMessage, por-turno), com orçamento de saliência próprio, e é o arquivo de maior churn da fila
(tickets 03, 05, 09, 11, 12, 15, 16, 17 mexeram nele; há WIP do humano em
`tests/agente/test_prepare_context.py`). O achado F6 da auditoria mede "a conduta", não a cauda.
Fica como follow-up, com o mesmo critério — anotei isso no `agente/CLAUDE.md`.

**Ecos, conferidos:** nenhum eco ficou irreconhecível, porque nenhuma palavra mudou — só a caixa.
O par mais visível é o `<fechamento>` "proponha você um horário" × `<ja_perguntou_o_horario>`
"proponha VOCÊ um horário" (cauda, intocada): mesma frase, caixa diferente, e
`test_disciplina_pergunta_de_horario.py` continua verde sobre a cauda sem eu tocar nele.

### O recurso que substituiu o caps (a decisão que o `agente/CLAUDE.md` não prescrevia)

A seção "Escala léxica de dureza" definia o **numerador** (quando o caps é legítimo) e não dizia
o que usar no lugar da ênfase de contraste. Escolhi, e registrei a escolha no próprio
`agente/CLAUDE.md` (a seção agora prescreve o substituto, para o próximo editor não reintroduzir):

1. **Default: nenhum marcador — a frase carrega o contraste.** Foi a descoberta do passe: em quase
   todos os 176 casos a prosa já nomeia os dois lados, e o caps era redundante com o que a frase
   dizia. "o formato DELE" vem logo depois de "o seu local"; "não somam o '+Extra' dos atos,
   DOBRAM o pacote" já é antítese; "a sondagem proibida é a de INTERESSE, nunca a pergunta de
   horário" já opõe as duas. Tirar a caixa não tirou informação nenhuma.
2. **Exceção: negrito, e só onde a minúscula muda a LEITURA.** Usei `**…**` porque é o único
   marcador de ênfase que **já existia** nos prompts (`**ida e volta**` no `<tipos_de_encontro>`,
   e o `judge_pos_envio.md`/`aup_saida.md` inteiros) — não é taxonomia nova. Itálico, que a
   auditoria sugeriu ("já é usado no repo"), **não** é usado em nenhum prompt: só em markdown de
   docs. Sete negritos, todos por ambiguidade real de parsing, nenhum por gosto:

   | site (bloco/tag) | fala | por que a minúscula sozinha não serve |
   |---|---|---|
   | `<abertura>` (regra do "Oi" sozinho) | "Você cumprimenta e **para**" | `para` vira preposição: "cumprimenta e para —" lê como frase truncada |
   | `<abertura>` (o que ela nunca faz) | "você **para** e espera a resposta dele" | idem |
   | `<girias_do_cliente>` (direção do oral) | "o 'oral' da sua lista é o que **você** faz nele" | direção invertida é failure-mode de prod; é a regra inteira |
   | `<girias_do_cliente>` (direção do oral) | "= ele fazendo em **você**" | idem |
   | `<tipos_de_encontro>` (preâmbulo) | "'você/te' na boca dele é **você**" | idem, e aqui a palavra aparece 2x na mesma frase com sentidos opostos |
   | `<desconto>` (avanço = aceite) | "é **sim** ao valor que está na mesa" | `sim` minúsculo lê como partícula ("é sim" = "é mesmo"), não como o substantivo |
   | `<exemplo classe="objeção de preço…">` | "é **sim** ao valor da mesa" | eco do anterior, mesmo motivo |

3. **Não mexi em `"ERRO:"`** (literal que a ferramenta devolve de verdade — minusculizar quebraria
   o casamento) nem nas siglas (BDSM, CEP, DDD, IA).

### O que mudou (bloco/tag, nunca linha)

Um passe único, mecânico e reversível — o script está em `/tmp` mas o resumo é este:

- **`regras.md.j2`**, todos os blocos: 160 palavras de caixa-alta→minúscula. Onde a palavra **abria
  a linha** (os sub-cabeçalhos do `<cotacao>`: `QUAL preço sai` / `EM QUE FORMATO ele sai` / `COMO
  você chama o programa` / `O QUE VAI JUNTO do número` / `COMO você termina o turno`; o `O MOTIVO`
  do `<recuo_pos_objecao>`; o `PREÇO` do `<apresentacao>`; o `UM preço por vez` do `<cotacao>`; os
  ramos `COM`/`SEM` do `<girias_do_cliente>`) ela voltou com **inicial maiúscula**, que é o que
  markdown/prosa já faz num começo de frase — o sub-cabeçalho continua sendo sub-cabeçalho pela
  posição, sem marcador.
- **`persona.md`**, `<voz>` / `<formato_das_bolhas>` / `<armadilhas_de_voz>`: 16 palavras, mesma
  regra, nenhum negrito (nenhuma das 16 era ambígua em minúscula).
- **`agente/CLAUDE.md`**, seção "Escala léxica de dureza nos prompts": parágrafo novo com o
  invariante (caps = proibição, negrito = desambiguação, o resto é prosa), o inventário dos 7
  negritos, o que fica de fora (literal/sigla) e a nota de que a cauda ficou pendente.

Nada por-modelo e nada por-turno entrou no BP_GERAL; zero variável Jinja nova; o prefixo continua
byte-idêntico entre modelas (`test_bp3_render.py` verde). O cache do DeepSeek mira a frio uma vez
no primeiro turno após o deploy, como em qualquer mudança de prompt — não é regressão.

### Testes ajustados (3, todos por caixa, nenhum por sentido)

Nenhum teste quebrou por regra mudada. Os três que quebraram afirmavam a string literal **com a
caixa antiga**; corrigi a caixa na asserção e mais nada:

| teste | asserção | de → para |
|---|---|---|
| `tests/unit/test_enquadramento_do_video_na_bolha.py::test_a_bolha_unica_e_quem_enquadra_o_video` (ticket 14) | a linha do book é uma só | `"UMA linha sua numa bolha"` → `"uma linha sua numa bolha"` |
| `tests/unit/test_enquadramento_do_video_na_bolha.py::test_a_legenda_continua_vazia_nos_dois_sites` (ticket 14) | legenda vazia | `"A legenda das mídias fica VAZIA"` → `"…fica vazia"` |
| `tests/unit/test_fala_ilustrativa_do_incluso.py::test_a_apresentacao_continua_prescrevendo_estilo_mais_incluso_do_bloco_dela` (ticket 18) | o gate por item ficou no `<apresentacao>` | `'os SEUS saem nominalmente…'` → `'os seus saem nominalmente…'` |

Cada uma continua afirmando exatamente a mesma regra, sobre exatamente a mesma frase. As outras
asserções desses arquivos (que não citam caps) passaram sem toque, o que é a evidência de que o
diff é só de ênfase. Varri o resto de `src/`, `tests/` e `evals/` por literais em caixa-alta do
prompt: os outros hits ou são da **cauda** (fora do escopo — `test_disciplina_pergunta_de_horario`,
`test_pecas_do_turno`, `test_contrato_variaveis_contexto`), ou são de **tool description**
(`ferramentas/extracao.py`, que não toquei), ou são docstring/descrição de cenário
(`evals/e2e/massa.py:457`, `evals/e2e/cenarios.py`) — nenhum é asserção.

### Verificação rodada (sem crédito)

```
make lint      → All checks passed
make typecheck → Success: no issues found in 142 source files
pytest -m "not needs_key and not needs_db" → 1885 passed, 247 deselected
```

`needs_db` **não** foi rodado de propósito: o `DATABASE_URL` do `.env` aponta para o Postgres
self-hosted de produção (§0).

### Gates pagos — o que rodar, e o que comparar

**1. `conduta_gate` contra o baseline de 01** (`baseline-conduta-gate.md`, commit `dd4a7e9`):

```sh
cd api && E2E_AUTORIZADO=1 TEST_DATABASE_URL='<dsn do self-hosted>' \
  make gate-conduta ARGS="--por-eixo 2 --max-turnos 12"
```

Comparar contra o baseline: `empurrao_pct` ≤ 5,0% (baseline 0,0%) e `violacoes_duras` = 0
(baseline 0). `conduziu_por_eixo` é advisory e o baseline registra que 0% ali é artefato do
roteiro — não leia como regressão. Custo da corrida do baseline: R$ 0,0634.

**2. A/B no simulador** — os dois prompts **já estão materializados**, sem crédito, para o humano
só autorizar:

| arquivo | o que é | chars | caps |
|---|---|---:|---:|
| `.scratch/prompt-refactor/ab-19/bp_geral_base.txt` | BP_GERAL de `HEAD` (`8fc4cbf`), antes do passe | 67.113 | 209 |
| `.scratch/prompt-refactor/ab-19/bp_geral_variante.txt` | BP_GERAL da árvore, depois do passe | 67.141 | 33 |

```sh
cd api && uv run python ../scripts/eval_corpus/sim_deepseek.py \
  --base     ../.scratch/prompt-refactor/ab-19/bp_geral_base.txt \
  --variante ../.scratch/prompt-refactor/ab-19/bp_geral_variante.txt \
  --tag-base caps --tag-variante sem_caps \
  --personas preco_no_abridor,faz_x_quanto,decidido,sumido_rapido,info_depois_preco,preco_sensivel \
  --n-rep 2 --k 8 --conc 6 \
  --out ../.scratch/prompt-refactor/ab-19/resultado.json
```

**Métrica a registrar** (`resumo_por_variante`, um número por variante — anexe a tabela, não
"passou"): as que medem justamente o que o caps sustentava, e onde uma queda seria o custo real
deste ticket —

- `violacoes` (contagem absoluta) e `pct_prometeu_subir` — o sinal de proibição. **Esperado: igual**;
  os 13 NUNCA não foram tocados. Se subir, foi o denominador que estava segurando algo, e o passe
  se reverte inteiro num `git revert`.
- `pct_incluso`, `pct_ancora_n1`, `pct_empurrao`, `pct_fugiu_preco` — as condutas cujo enunciado
  perdeu caps (`ILUSTRATIVOS`/`NOMINALMENTE`, `FECHAMENTO`/`OFERECE`, `ABERTA`/`INTERESSE`).
- `media_bolhas_cotacao` / `pct_cotacao_le2bolhas` / `emoji_no_turno_cotacao` — controle de voz.

O ticket já avisa que este é o gate mais fraco da lista (o juiz de desfecho tem κ≈0,07); ele serve
para **detectar queda**, não para provar ganho. Com `--n-rep 2` e 6 personas são 12 conversas por
braço: diferença de 1-2 conversas é ruído, e é assim que deve ser lida.

### Nada de produção

Nenhum deploy, nenhum `git push`, nenhuma migration, nenhum `make test-llm`. A mudança é de prompt
e só vale em prod depois de `docker service update --force <stack>_barra-worker` — que **não**
fiz e não deve ser feito antes dos dois gates acima.
