# Auditoria de carga instrucional do prompt do agente — diagnóstico e plano

**Data:** 2026-07-30 · **Objeto:** `api/src/barra/agente/prompts/regras.md.j2` (363 linhas,
52.984 chars de `<conduta>`) no contexto do turno completo que chega ao modelo.
**Escopo:** diagnóstico + plano. Nenhum prompt foi editado nesta rodada.

**Anexos** (cada um é uma passada independente, com linha citada e risco por achado):
`inventario-turno.md` · `eixo-a-redundancia-e-forma.md` · `eixo-b-contradicoes-vivas.md` ·
`eixo-c-instrucao-morta.md` · `eixo-d-estrutura-e-determinismo.md`.
Material prévio de hoje (10:53), com números de linha defasados: `contradicoes.md`,
`mapa-de-ecos.md`, `proveniencia.md`.

---

## 1. Inventário do turno real

Detalhe completo em `inventario-turno.md`. O essencial:

Trace `0d7577aeae83b0e29366f6f702892166` (30/07 11:37 BRT, 9º turno de uma negociação).
DeepSeek V4 Flash, **23.582 tokens de input**, 57 de output, cache hit 96,6%.

| bloco | chars | tokens ≈ | % input |
|---|---:|---:|---:|
| `TOOLS` (3 schemas) | 5.814 | 1.810 | 7,7% |
| **BP_GERAL** (`persona.md` 14.239 + `regras.md.j2` 53.007) | **67.246** | **20.950** | **88,8%** |
| BP_MODELO (identidade + programas + fetiches) | 442 | 138 | 0,6% |
| cauda dinâmica (belief + agenda + fala do cliente) | 1.591 | 495 | 2,1% |
| janela (7 msgs do cliente + 7 bolhas dela) | 641 | 200 | **0,8%** |

**Conduta 89%, conversa 0,8%.** Não há trace de `producao` na janela de 7 dias que o MCP
alcança; este é o gate e2e, que roda o `processar_turno` real — com uma ressalva de
fidelidade registrada na §3.1 do inventário (bolhas da IA fora de ordem cronológica no
caminho do e2e, `evals/e2e/persistencia.py:126`; prod não tem o problema).

Peso por bloco de conduta, do maior: `<conducao_da_venda>` 22,5% · `<tipos_de_encontro>` 12,4% ·
`<girias_do_cliente>` 9,7% · `<desconto>` 7,3% · `<exemplos>` 6,6% · `<nucleo>` 5,7% ·
`<fora_do_cardapio>` 4,8% · `<menage>` 4,5% · `<sobe_o_ticket>` 4,5% · resto ≤3,7%.
178 palavras em CAPS, das quais só 27 são `NUNCA`/`NÃO`; 314 negações (5,9/kchar).

---

## 2. Achados, ordenados por custo de atenção

O critério de ordenação é **quanto o achado degrada a obediência no turno**, não chars.
As três primeiras classes custam pouco ou nada em volume e são onde está o dano.

### F1 — A cauda contradiz a conduta no ponto de recency máxima · dano alto, custo ~0 chars

O modelo lê a cauda por último (incidente 29/07 pôs a fala do cliente no fim, e o belief
imediatamente antes dela). O `<nucleo_final>`, site de recency da conduta, está a ~8.500
tokens do fim. Quando cauda e conduta divergem, quem ganha é a cauda — e ela hoje afirma
versões **mais estreitas** que o canônico, sem condição:

- **`contexto_dinamico.md.j2:16`** — "Você já está no meio do atendimento, não recumprimente
  nem se reapresente" renderiza **sem condição**, contra `regras.md.j2:34` ("'Oi' SOZINHO → só
  o cumprimento, em 2 bolhas curtas"). No mesmo bloco, `:15`/`service.py:790` injeta "entender
  o que ele procura" — exatamente o léxico que `regras.md.j2:41` proíbe em caps como
  sonda-de-balcão.
- **`contexto_dinamico.md.j2:7`** (`<valor_cotado>`) — "não cote outro número nem repita este
  solto" colide com três condutas que mandam dar outro número: `:62` (Completo é segunda
  venda), `:145` (upsell "e 2h?") e `:115` (repetir o preço com outras palavras quando ele
  repergunta).
- **`reminder.md.j2:5`** — "pergunta dele não é aceite", incondicional, contra `:165` ("depois
  que a negociação de preço rodou, pergunta de horário/logística é SIM ao valor na mesa"). É a
  reincidência do modo de falha que o `agente/CLAUDE.md` já registra em 30/07: o eco de recency
  afirmando a versão estrita e proibindo o que o canônico prescreve. `:359` repete.
- **`reminder.md.j2:5`** — "o padrão é ele vir até você" contra `:68` (a modelo que não aceita
  interno nunca oferece um local que não tem).

Total: 9 contradições duras vivas (A1–A9 do eixo B) e 6 tensões sem desempate escrito. **18 dos
27 achados prévios já foram corrigidos** nas edições de hoje (11:32) — mas C3 e C9 foram
corrigidos no canônico e **sobreviveram nos ecos**, que é o padrão a vigiar.

Custo em chars: negativo (consertar A1/A3 acrescenta condição). Ganho: o modelo para de
receber ordens que se anulam no último token antes de responder.

### F2 — Exemplo concreto vence proibição em prosa · dano medido, 50 chars

`<exemplo classe="abertura + primeira cotação + apresentação">` (`:304`) mostra a fala literal
**"Beijo na boca e oral sem camisinha tá incluso amor"**. No trace de hoje, com
`<fetiches>` = `(sem fetiches cadastrados)`, a IA emitiu essa string palavra por palavra.

Três cláusulas proibiam exatamente isso: `:48` ("sem essa linha no seu bloco a apresentação
fica só no estilo, sem lista de incluso"), `:246` ("'tá incluso' você só diz de item que está
NOMINALMENTE na linha 'Inclusos'… nem quando ele aparece num exemplo desta conduta") e `:288`
(preâmbulo dos exemplos). Todas perderam.

Agravante do eixo A: a mesma fala está **duplicada** em `:48` e `:304`, dobrando a pressão de
cópia. Este é o achado com melhor custo/benefício da auditoria inteira: dano medido, métrica
binária, perfil de teste já existente (`evals/e2e/perfil.py:26`).

Leitura mais ampla, e é a lição central desta auditoria: **repetir a proibição não compra
obediência** — três sites não venceram um exemplo. Onde a instrução em prosa já falhou, o que
funcionou historicamente foi trilho determinístico. O `proveniencia.md` registra o precedente
exato: para o failure-mode de período longo, "3 reformulações de prosa falharam e exigiram o
trilho `<sem_periodo_longo>`", que foi 9/9.

### F3 — Gate de capacidade escrito em prosa, para uma capacidade que a modelo não tem · 4.400 chars

21% da conduta (≈11.200 chars) é estruturalmente inaplicável ao turno auditado. Parte é
inevitável (o modelo não sabe se o cliente vai pedir droga). Mas uma parte é **inaplicável por
CADASTRO, não por turno** — e portanto previsível fora do prompt:

- **`<menage>` `:258-266` (2.403 chars)** — o bloco inteiro pende de a modelo ter a seção "Por
  pessoa" em `<fetiches>`. O gate está em prosa (`:258`, escrito hoje às 11:32) e as 2.174
  chars seguintes são lidas e descartadas em todo turno de toda modelo que não tem a seção.
  Agravado por `:262` recotar o dobro que `:260` definiu duas linhas antes.
- **Vídeo chamada `:216`/`:227`/`:235`/`:225` (793 chars)** — mesmo padrão em 4 sites: "ela só
  existe se estiver nos seus `<programas>`".
- **Ramos COM/SEM Completo `:124-126` + `:130-132` (1.466 chars)** — bifurcação de conduta por
  cadastro, dentro de `<girias_do_cliente>`.
- **`<fora_do_cardapio>` (2.539 chars)** — o bloco inteiro pende de `<fetiches>`, que no turno
  auditado está vazio.

Isto **não pode** virar renderização condicional no BP_GERAL: ele é byte-idêntico entre todas
as modelos e é o prefixo cacheado. O caminho é o oposto e já tem precedente provado no repo:
a condição vira **tag na cauda** (`<sem_periodo_longo>`, `<local_de_encontro>`) e a prosa no
BP_GERAL encolhe para uma linha.

### F4 — Redundância intra-arquivo · 1.823 chars, dano baixo

O eixo A varreu o arquivo inteiro e o teto honesto é **3,4% da conduta**. Só 3 pares de
n-grama ≥30 chars se repetem fora de par regra↔exemplo. O bloco mais pesado
(`<conducao_da_venda>`, 22,5%) é o **menos** redundante por char (3,5%).

Pior ofensor: **`<desconto>`** — "depois do teto não há oferta nova" em 3 cópias em 6 linhas
(`:160`, `:161`, `:165`), 147 chars; e `:157` termina com 3 formulações da mesma coisa, a do
meio sendo `<nucleo>` linha 2 repetido (109 chars). Vice: `<menage>`, pior em densidade (7,7%)
e agravado por ser bloco que a maioria não ativa.

**Conclusão do eixo:** a hipótese "cresceu por acreção e virou redundante" é **falsa** como
diagnóstico principal. O arquivo é grande, mas é denso. A gordura não está na repetição.

### F5 — Instrução morta · 798 chars, dano baixo

Confirmação por caminho independente do `proveniencia.md`: instrução morta praticamente não
existe. O único bloco integralmente superseded é **`<enquanto_ele_nao_chega>` `:108-110`
(275 chars)**, cujas falas e proibições estão todas na flag A2 `<ja_pediu_a_foto_da_portaria>`
(`contexto_dinamico.md.j2:25`) — que só aparece quando aplicável, e melhor. Resíduo
instrucional próprio: nenhum. Gate: `tests/unit/test_contrato_variaveis_contexto.py:132`
quebra, porque `_PROXIMO_PASSO` cita a tag.

Também morto pela metade: **`:238` (253 chars)** — 2 dos 4 literais que ele nomeia
(`ignorar instruções`, tag falsa) são interceptados por `PADROES_JAILBREAK` e escalam **sem
chegar ao nó `llm`**.

### F6 — Diluição de sinal: o CAPS deixou de ser sinal · dano médio, custo ~0

178 palavras em CAPS na conduta, e só 27 são `NUNCA`(13)/`NÃO`(14). As outras 151 são ênfase
de contraste: `ELE` 12, `VOCÊ` 10, `DELE` 8, `SUA`/`SEU`/`SEUS` 10, `DUAS` 3, `ÚLTIMA` 3,
`DENTRO` 3, `OFERECE` 3, `FECHAMENTO` 3.

O `agente/CLAUDE.md` define a escala: "**NUNCA em caps** só para linha dura do `<nucleo>` ou
failure-mode comprovado em prod". Os 13 `NUNCA` passam nesse critério. O problema é o
**denominador**: 151 palavras em caps que não são proibição competem pela mesma saliência
visual e diluem os 13 que importam. Densidade de negação também é desigual sem justificativa
de failure-mode: `<drogas_e_bebida>` 17,1/kchar e `<fora_do_cardapio>` 11,4/kchar contra 2,4
em `<quando_usar_escalar>`.

Isso não é corte, é **regravação**: trocar o CAPS de contraste por outro recurso (itálico já é
usado no repo, ou reordenar a frase) devolve o CAPS à função de proibição. Zero chars.

### F7 — Estrutura: a subdivisão por fase se paga; o desalinho está noutro lugar

Veredito do eixo D: **manter as tags de fase.** `<fechamento>` é o que torna enunciável a regra
do verbo (`:81` indexa "Posso confirmar" *pela fase*) e `<apresentacao>` resolve o roteamento
de `:37`. Overhead de fronteira medido: 1,3–1,6k de 11,9k chars (11–13%) — preâmbulo `:27-29`,
a travessia dupla `:93`↔`:98`, a ressalva `:165`. Fundir devolveria menos que isso, porque o
contraste voltaria como condicional posicional e desalinharia do detector `_NAO_E_RECUO`.

O desalinho real: **3 das 7 tags não são fases**, são reações a evento do cliente.
`_PROXIMO_PASSO` nomeia só 5, e **`<retomada_pos_silencio>` (847 chars) é endereçada por
nada** — zero cross-ref interna, zero ponteiro de cauda.

Injeção condicional por fase segue **recusada**: o motivo de 25/07 (o `extrair` roda depois do
`llm`, então prompt cortado por fase chega um turno atrasado e o cliente que pula o funil cai
num prompt sem a fase que ele abriu) se sustenta.

---

## 3. Plano de reescrita, priorizado

Ordem = dano corrigido por unidade de risco. **Nada aqui está autorizado a rodar** — cada
etapa precisa do teu aval, e as que tocam prod (migration, redeploy) caem na §0 do `CLAUDE.md`.

### Etapa 1 — Alinhar a cauda com a conduta (ganho máximo, ~0 chars, risco baixo)

Não é corte: é conserto de contradição no ponto de maior autoridade posicional.

| # | mudança | linhas | comportamento protegido | risco | gate |
|---|---|---|---|---|---|
| 1.1 | condicionar "não recumprimente" ao estado (some quando a fala do turno é só um cumprimento) | `contexto_dinamico.md.j2:16` × `regras:34` | abertura de 2 bolhas do "oi" seco (`397daef`) | baixo | `conduta_gate`, cenário de abertura |
| 1.2 | tirar "entender o que ele procura" do `_PROXIMO_PASSO` | `service.py:790`, `CD:15` × `regras:41` | sonda-de-balcão é NUNCA em caps | baixo | `conduta_gate` (`sonda`) |
| 1.3 | abrir exceção no `<valor_cotado>` para segunda venda / upsell / repergunta | `CD:7` × `regras:62`,`:145`,`:115` | Completo como 2ª venda; upsell de 2h | médio | `conduta_gate` + `sim_deepseek` |
| 1.4 | pôr a condição do aceite no eco (era posicional no canônico) | `reminder:5`, `regras:359` × `:165` | avanço pós-negociação = sim | baixo | `conduta_gate` (aceite pós-desconto) |
| 1.5 | condicionar "o padrão é ele vir até você" aos tipos aceitos | `reminder:5` × `regras:68` | nunca oferecer local que não tem | baixo | `sim_deepseek` |
| 1.6 | `<horario_minimo>` de prescrição para piso: "o primeiro horário que você **pode** oferecer" | `regras:179` × `:84`, `CD:18` | proposta cai dentro da janela vaga dele | baixo | `conduta_gate` (janela vaga) |
| 1.7 | as 3 contradições restantes (A4 foto×prova, A7 dois "sins", A9 legenda×enquadramento) | ver eixo B | — | médio | roteiro novo |

A5 (`regras:214` "quem chama o uber é ele → Pix não entra" × Pix determinístico em todo
externo, `service.py:~1198`) **não é conserto de prompt**: falta slot de extração para "o uber é
dele". Vira issue de código, fora deste plano.

### Etapa 2 — Matar o vazamento do exemplo (dano medido, 103 chars, risco baixo)

- **2.1** Trocar em `:304` e `:48` a fala ilustrativa por uma que **não seja um item de
  cardápio plausível** — o problema não é o texto ser exemplo, é ser um item que existe no
  catálogo real e passa por cotação válida. Mantém a forma da fala, remove a cópia utilizável.
- **2.2** Guard no `output_guard`, na família de `sonda`/`regiao`: "tá incluso" com
  `<fetiches>` sem linha "Inclusos" é fail. É o padrão que o repo já usa quando a prosa falha
  (`_RE_PLACEHOLDER` nasceu assim). Métrica binária, gate reproduz a falha hoje.
- **2.3** Só depois de 2.1+2.2 verdes, avaliar tirar a duplicação de `:48`.

### Etapa 3 — Corte seguro (1.622 chars, risco baixo)

| # | corte | chars | gate |
|---|---|---:|---|
| 3.1 | dedup do "depois do teto não há oferta nova" (`:160`/`:161`/`:165` → 1 site) | −147 | `desconto_abaixo_teto` |
| 3.2 | `:157`, as 3 formulações finais → 1 (a do meio é `<nucleo>` 2 repetido) | −109 | `desconto_dentro_degrau` |
| 3.3 | `<enquanto_ele_nao_chega>` `:108-110` inteiro (superseded pela flag A2) | −275 | **quebra** `test_contrato_variaveis_contexto.py:132` — ajustar `_PROXIMO_PASSO` na mesma mudança |
| 3.4 | `:238`, os 2 literais interceptados por `PADROES_JAILBREAK` antes do `llm` | −130 | teste de interceptação existente |
| 3.5 | `:262` recotando o dobro que `:260` definiu | −112 | `sim_deepseek` |
| 3.6 | condicionais negativas de vídeo chamada em `:227`/`:235`, caronas de `:216` | −149 | **sem gate** — o cenário `remoto_videochamada` roda modelo *com* o programa; precisa roteiro novo |
| 3.7 | resto do eixo A (forma: `:212` reduzida sem perder a fala de substituição, e outros) | −700 | caso a caso |

### Etapa 4 — Regravar a escala de dureza (0 chars, risco baixo, dano médio)

Substituir as 151 palavras em CAPS que **não são proibição** (`ELE`, `VOCÊ`, `DELE`, `SUA`,
`DENTRO`, `OFERECE`…) por outro recurso de ênfase, preservando os 13 `NUNCA` e 14 `NÃO`.
Devolve saliência ao léxico que o `agente/CLAUDE.md` reserva para linha dura. Gate: nenhum eval
mede isso — recomendo `sim_deepseek` A/B antes e depois, e é a etapa mais fácil de reverter.

### Etapa 5 — Mover gate de capacidade da prosa para a cauda (4.400 chars, risco médio-alto)

O maior ganho de volume, e o de maior risco. Padrão: `<sem_periodo_longo>` (9/9 onde 3
reformulações de prosa falharam). Para cada família, a cauda ganha a tag negativa e o BP_GERAL
fica com uma linha:

| # | família | chars que saem | por que é seguro fazer assim | gate |
|---|---|---:|---|---|
| 5.1 | `<menage>` sem seção "Por pessoa" | −2.174 | o gate já está em prosa em `:258`; virar tag só o torna estrutural | **sem gate — nenhum eval exercita menage.** Precisa roteiro novo ANTES |
| 5.2 | vídeo chamada ausente de `<programas>` | −650 | 4 sites em prosa, escritos hoje; mesmo failure-mode que exigiu trilho | roteiro novo (modelo sem o programa) |
| 5.3 | `<fetiches>` sem linha "Inclusos" | (casa com 2.2) | o guard da etapa 2 é a metade determinística disto | `perfil.py:26` |
| 5.4 | ramos COM/SEM Completo `:124-126`,`:130-132` | −1.466 | **risco alto** — regra de negócio mudou uma vez em 8 dias (`18333a5` 14/07, revertida por cadastro 22/07). Fazer por último, ou não fazer | roteiro novo |

### Etapa 6 — Determinismo aditivo (eixo D, nenhuma migration)

- **6.1** Bolha de espera antes do `escalar` (`:269`) → canned no `post_process`. O pool
  `ESPERA_ESCALADA_CANNED` e o cut point já existem, mas só cobrem a escalada de *guarda*; na
  escalada que a IA decide, se ela não escreve nada antes da tool o cliente fica mudo com a IA
  pausada. A exceção `conteudo_ilegal` sai do arg `motivo` do tool_call. **A prosa de `:269`
  fica** — o `conteudo_ilegal` sem bolha de espera é conduta que o canned não cobre.
- **6.2** Valor do teto pré-computado na cauda (`:159-160`): `service.py:1045-1066` já calcula
  `piso = tabela × (1 − teto_pct)` e usa para *julgar* a IA, sem nunca mostrar o número. Campo
  derivado no `ContextoDoTurno`, dentro da tag `<ja_fez_contraproposta n="1">` que já sai.
- **6.3** Dar endereço a `<retomada_pos_silencio>` (847 chars órfãs) — ou um ponteiro em
  `_PROXIMO_PASSO`, ou fundir no `<abertura>` como o caso "ele volta".

### O que fica intocado, e por quê

19 cláusulas com falha real observada e sem substituto (tabela completa no eixo C). As que mais
importam:

- **`:212` (maps/waze/proximidade) e `:195` (bairro palavra-por-palavra)** — incidente #36 e o
  cluster "Cambuí". A lição é literal: **proibir sem dar fala de substituição foi o que criou o
  bug**. As duas metades são bug e antídoto; cortar a fala de saída reabre o incidente.
- **`:246` camisinha nunca como "incluso"** — o `judge_conduta` deu 1.0 e nenhum guard pega.
- **`:93` "quer mas não manda no relógio" + a desambiguação vs `<recuo_pos_objecao>`** — #34.
- **`:134` xingamento é jogo falado** — era a raiz do 400→800 do #21.
- **`:37` âncora do texto do site + a contra-cláusula** — as duas LOAD-BEARING (trace
  `f1d32009`, 28/07).
- **Regra transversal:** toda cláusula com backstop determinístico (`:224` legenda vazia,
  `:82` o "?" da proposta, `:206` chave Pix, `:127` "sem limite", eco de região) é a que
  **menos** se corta. O backstop existe porque a prosa falhou ali, e foi calibrado assumindo
  que ela continua no lugar. Vale o aviso do `agente/CLAUDE.md`: dedup não é deleção grátis.

### Pré-requisito de qualquer etapa gated

A ressalva da §3.1 do inventário: no caminho do e2e as bolhas da IA chegam ao modelo fora de
ordem cronológica (`evals/e2e/persistencia.py:126` usa `uuid4()` onde
`prepare_context.py:270` assume `uuidv7()`). Todo gate deste plano passa por esse harness, e
qualquer medição de coerência de fio, repetição ou recency feita antes do conserto é suspeita.
Correção de uma linha, como `evals/shadow/massa.py:204` já faz. **Fazer isso primeiro.**

---

## 4. Veredito quantitativo

| classe | chars | % da conduta |
|---|---:|---:|
| corte seguro (etapas 3.1–3.5) | 1.622 | 3,1% |
| corte com gate existente (3.6–3.7 + etapa 2) | ~1.500 | 2,8% |
| corte com roteiro novo (etapa 5) | ~4.300 | 8,1% |
| **teto realista** | **~7.400** | **~14%** |

14% da conduta, ≈2.300 tokens, ≈11% do BP_GERAL. Descontando a sobreposição entre os eixos A
e C (~300 chars contados duas vezes), e sem tocar em `persona.md`, que esta rodada não
auditou por eixo próprio — os 14.239 chars dela (21% do BP_GERAL, 19 pares de
`<armadilhas_de_voz>`) são a próxima fronteira.

**E o corte não é o conserto.** Nenhuma das duas fontes de degradação que têm evidência —
a cauda contradizendo a conduta no último token (F1) e o exemplo concreto derrotando três
proibições (F2) — se resolve tirando texto. As etapas 1, 2 e 4 custam ~100 chars somados e
valem mais que as etapas 3 e 5 juntas.
