# Inventário de um turno real — o que chega ao modelo

**Fonte:** trace Langfuse `0d7577aeae83b0e29366f6f702892166` (2026-07-30 11:37 BRT, sessão
`c5039432-6207-4958-b955-33aefbf4234e`, 9º turno da conversa). `service.name=barra-evals`,
env `desenvolvimento` — é o gate e2e (`evals/e2e/conduta_gate.py`), que roda o `processar_turno`
real. **Não há trace de `producao` na janela de 7 dias** que o MCP alcança (`age` máx. 10080 min);
o piloto está sem tráfego nesse período. Dump completo: `/tmp/langfuse_mcp_dumps/trace_0d7577*.json`.

Modelo do turno: **DeepSeek V4 Flash** (`temperature=0.7`, `max_completion_tokens=1024`).
Nó `llm`: **23.582 tokens de input**, 57 de output. Cache hit **22.784/23.582 (96,6%)** — o
prefixo está funcionando; o custo aqui **não é dinheiro, é atenção**.

## 1. Inventário por bloco (nó `llm`, na ordem em que o modelo lê)

Razão medida no turno: 75.734 chars → 23.582 tokens = **3,21 chars/token**.

| # | bloco | chars | tokens ≈ | % do input | natureza |
|---|---|---:|---:|---:|---|
| — | `TOOLS` (3 schemas: `consultar_agenda` 1.436, `enviar_midia` 2.132, `escalar` 2.246) | 5.814 | 1.810 | 7,7% | mecânica + policy |
| 0 | **BP_GERAL** = `persona.md` + `regras.md.j2` fundidos, 1 SystemMessage | **67.246** | **20.950** | **88,8%** | conduta |
| 1 | **BP_MODELO** (`identidade` + `programas` + `fetiches`) | 442 | 138 | 0,6% | contexto |
| 2–8 | janela: 7 mensagens do cliente | 333 | 104 | 0,4% | conversa |
| 9 | **cauda dinâmica** (contexto + fala do cliente) | 1.591 | 495 | 2,1% | contexto |
| 10–16 | janela: 7 bolhas da IA | 308 | 96 | 0,4% | conversa |

**A conversa viva — tudo que o cliente disse e tudo que ela respondeu — é 641 chars: 0,85% do
que o modelo lê.** A instrução é 89%. O turno respondeu a uma mensagem de 74 chars.

Neste turno **não houve `<lembrete_silencioso>`**: o gate é `≥8 AIMessages` (`_precisa_reminder`)
e a janela tinha 7. O reminder (2.861 chars ≈ 890 tok) entra a partir do turno seguinte, sempre
DENTRO da mesma HumanMessage da cauda, antes da fala.

### 1.1 Dentro do BP_GERAL

| parte | chars | tokens ≈ | % do BP_GERAL |
|---|---:|---:|---:|
| `persona.md` (`<persona>`) | 14.239 | 4.435 | 21,2% |
| `regras.md.j2` (`<conduta>`) | 53.007 | 16.514 | 78,8% |

`persona.md` internamente: `<quem_voce_e>` ~1,9k · `<voz>` ~4,7k · `<formato_das_bolhas>` ~1,1k ·
**`<armadilhas_de_voz>` ~6,3k (19 pares)**.

### 1.2 Dentro da `<conduta>` (52.984 chars) — por bloco de topo

| bloco | chars | % conduta | CAPS | negações | neg/kchar |
|---|---:|---:|---:|---:|---:|
| `<conducao_da_venda>` | 11.945 | 22,5% | 46 | 66 | 5,5 |
| `<tipos_de_encontro>` | 6.583 | 12,4% | 19 | 39 | 5,9 |
| `<girias_do_cliente>` | 5.126 | 9,7% | 27 | 27 | 5,3 |
| `<desconto>` | 3.877 | 7,3% | 9 | 30 | 7,7 |
| `<exemplos>` | 3.496 | 6,6% | 12 | 16 | 4,6 |
| `<nucleo>` | 3.007 | 5,7% | 9 | 19 | 6,3 |
| `<fora_do_cardapio>` | 2.539 | 4,8% | 7 | 29 | **11,4** |
| `<menage>` | 2.403 | 4,5% | 13 | 11 | 4,6 |
| `<sobe_o_ticket>` | 2.369 | 4,5% | 8 | 14 | 5,9 |
| `<agenda>` | 1.952 | 3,7% | 4 | 8 | 4,1 |
| `<protocolo_disclosure>` | 1.943 | 3,7% | 2 | 15 | 7,7 |
| `<instrucoes_meta>` | 1.882 | 3,6% | 11 | 6 | 3,2 |
| `<midia>` | 1.671 | 3,2% | 5 | 11 | 6,6 |
| `<quando_usar_escalar>` | 1.637 | 3,1% | 2 | 4 | 2,4 |
| `<nucleo_final>` | 913 | 1,7% | 1 | 4 | 4,4 |
| `<drogas_e_bebida>` | 644 | 1,2% | 2 | 11 | **17,1** |
| `<ferramentas>` | 437 | 0,8% | 1 | 4 | 9,2 |

Sub-blocos de `<conducao_da_venda>`: `<cotacao>` 3.521 · `<fechamento>` 1.979 ·
`<abertura>` 1.946 · `<recuo_pos_objecao>` 1.297 · `<apresentacao>` 1.148 ·
`<retomada_pos_silencio>` 847 · `<enquanto_ele_nao_chega>` 224 (+ preâmbulo ~980).

**Léxico de dureza na conduta:** 178 palavras integralmente em CAPS, das quais só 27 são
`NUNCA` (13) e `NÃO` (14) — o resto é **ênfase de contraste** (`ELE` 12, `VOCÊ` 10, `DELE` 8,
`SUA`/`SEU`/`SEUS` 10, `DUAS` 3, `ÚLTIMA` 3, `DENTRO` 3, `OFERECE` 3, `FECHAMENTO` 3…).
314 negações no total (5,9/kchar). `persona.md`: 16 CAPS, zero `NUNCA`, 56 negações.

## 2. Quanto disso é conduta, contexto e ruído NESTE turno

Estado real do turno: `#1`, `Triagem`, `tipo=externo`, cliente fora da cidade dizendo que
avisa se conseguir vir antes de domingo. A modelo (`Manu`) tem **`(sem fetiches cadastrados)`**
e tabela de 3 linhas (Encontro 1h R$400, 2h R$700, Pernoite 12h R$2.500).

| categoria | tokens ≈ | % |
|---|---:|---:|
| conduta (BP_GERAL) | 20.950 | 88,8% |
| mecânica de tool (3 schemas) | 1.810 | 7,7% |
| contexto do turno (BP_MODELO + cauda) | 633 | 2,7% |
| conversa (janela) | 200 | 0,8% |

Dos 16,5k tokens de conduta, os blocos **estruturalmente inaplicáveis a este turno** somam
≈ 11.200 chars (3.500 tok, 21% da conduta): `<menage>` (2.403 — a modelo não tem seção
"Por pessoa"), `<fora_do_cardapio>` (2.539 — o bloco inteiro pende de `<fetiches>`, que está
vazio), `<midia>` (1.671), `<protocolo_disclosure>` (1.943), `<drogas_e_bebida>` (644),
`<enquanto_ele_nao_chega>` (224), `<quando_usar_escalar>` (1.637 — nenhum gatilho na mesa),
mais os degraus 2–3 de endereço em `<tipos_de_encontro>` e a metade "interna" desse bloco
(o tipo já está fixado como externo). Isso é o piso do ruído: são blocos que o modelo
atravessa em TODO turno independentemente do estado.

## 3. Evidência de falha colhida no próprio turno

Bolha da IA nesta mesma conversa (msg `f6c2995c`): **"Beijo na boca e oral sem camisinha tá
incluso amor"** — com `<fetiches>` = `(sem fetiches cadastrados)`.

`<apresentacao>` (`regras.md.j2:48`) prevê exatamente esse caso e o proíbe: "Os itens dessa
terceira bolha são ILUSTRATIVOS: os SEUS saem nominalmente da linha 'Inclusos' do seu
`<fetiches>`, e **sem essa linha no seu bloco a apresentação fica só no estilo, sem lista de
incluso**". `<fora_do_cardapio>` (`:246`) repete a proibição por outro ângulo ("'tá incluso'
você só diz de item que está NOMINALMENTE na linha 'Inclusos'… nem quando ele aparece num
exemplo desta conduta"). O `<exemplo classe="abertura + primeira cotação + apresentação">`
(`:304`) mostra a fala literal **"Beijo na boca e oral sem camisinha tá incluso amor"**, e o
preâmbulo de `<exemplos>` (`:288`) manda não copiar item que não está no bloco.

O modelo copiou o exemplo palavra por palavra e ignorou as três cláusulas que o proibiam.
Isto é o eixo "diluição de sinal" com prova: **a proibição está dita 3 vezes, em 3 lugares,
e perde para um exemplo concreto** — que é o que o modelo trata como especificação. Vale
igualmente como prova de que instrução redundante não compra obediência.

## 3.1 Ressalva que contamina a evidência de conduta vinda do e2e (não é do prompt)

No trace, as 7 bolhas da IA chegam ao modelo **todas depois** das 8 mensagens do cliente e em
ordem **não cronológica**: os ids são `30531a4e`, `53553902`, `5747ff2f`, `5b67dba1`,
`9fbcc17b`, `ed6afca4`, `f6c2995c` — hex estritamente crescente. A saudação de abertura
("Oii / Boa noite amor 🥰 / Sou bem tranquila / Estilo namoradinha"), que é o turno 1, aparece
em 4º lugar, depois da cotação.

Causa: `carregar_mensagens` (`nos/prepare_context.py:270`) ordena por
`created_at DESC, id DESC` e o docstring justifica o desempate dizendo que `id` é "uuidv7,
time-ordered". Em prod isso vale — `workers/envio.py:981` omite `id` e pega o default
`barravips.uuidv7()` (`infra/sql/0001_schema_inicial.sql:534`). **No caminho do e2e não vale:**
`evals/e2e/persistencia.py:126` insere a bolha da IA com `uuid4()` explícito, então o desempate
vira aleatório.

Consequência para esta auditoria: parte do comportamento ruim observável no gate e2e — o
re-cumprimento no turno 9, a repetição da apresentação — pode ser resposta a uma conversa
**embaralhada**, não degradação por volume de prompt. A falha da §3 (o "tá incluso" com
`<fetiches>` vazio) **sobrevive à ressalva**: ela não depende de ordem, e o item citado não
existe no bloco em nenhuma ordem. Mas conclusões sobre coerência de fio, repetição e
recency tiradas do e2e ficam suspeitas até isso ser corrigido.

Isso **não é achado de prompt** e não entra no plano de reescrita — é um defeito de fidelidade
do harness, com endereço próprio (`evals/e2e/persistencia.py:126`) e correção de uma linha
(usar `barravips.uuidv7()`, como `evals/shadow/massa.py:204` já faz). Fica registrado porque
qualquer eval que gateie a reescrita passa por esse harness.

## 4. Ordem de leitura, para calibrar primacy/recency

O que o modelo lê imediatamente antes de responder não é a conduta: é
`<situacao_do_atendimento>` → `<cliente>` → `<agenda>` → `<periodo_de_trabalho>` → **fala do
cliente** (recency, incidente 29/07). O `<nucleo_final>` — o site de recency da conduta — está
a ~8.500 tokens de distância do fim do prompt. Qualquer aposta em recency feita pelo
`<nucleo_final>` está, na prática, competindo com a cauda dinâmica, não ocupando o fim.
