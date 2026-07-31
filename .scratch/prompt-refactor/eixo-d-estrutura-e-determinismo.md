# Eixo D — estrutura e fronteira prosa↔código

Objeto: `api/src/barra/agente/prompts/regras.md.j2` (363 linhas). Pesos por bloco vêm de
`inventario-turno.md` §1.2. Linhas citadas foram verificadas no arquivo atual.

---

## D1 — as 7 tags de fase do `<conducao_da_venda>` (11.945 chars, 22,5% da conduta)

### Medição de endereçabilidade

Quem pode APONTAR cada tag: a cauda (`_PROXIMO_PASSO`, `dominio/atendimentos/service.py:786-796`)
e as cross-refs internas do próprio `regras.md.j2`. Contagem real:

| tag | chars | def | cross-refs internas | citada por `_PROXIMO_PASSO` |
|---|---:|---|---|---|
| `<abertura>` | 1.946 | :31 | 1 (`:83`) | sim (`Novo`) |
| `<apresentacao>` | 1.148 | :47 | 1 (`:37`) | sim (`Triagem`) |
| `<cotacao>` | 3.521 | :57 | 1 (`:50`) | sim (`Novo`/`Triagem`/`Qualificado`) |
| `<fechamento>` | 1.979 | :87 | **3** (`:81`, `:98`, `:165`) | sim (`Qualificado`/`Aguardando_confirmacao`) |
| `<recuo_pos_objecao>` | 1.297 | :97 | 1 (`:93`) | **não** |
| `<enquanto_ele_nao_chega>` | 224 | :108 | **0** | sim (`Aguardando_confirmacao`) |
| `<retomada_pos_silencio>` | 847 | :112 | **0** | **não** |

Duas leituras imediatas:

- `_PROXIMO_PASSO` nomeia **5 das 7**. As duas que ele nunca nomeia (`<recuo_pos_objecao>`,
  `<retomada_pos_silencio>`) não são fase do funil — são **reação a um evento do cliente** (ele
  retratou; ele sumiu e voltou), ortogonais à FSM. Nenhum `estado` de atendimento pode apontá-las,
  por construção.
- `<retomada_pos_silencio>` é **endereçada por nada**: zero cross-ref interna, zero ponteiro de
  cauda. É a única das 7 que é puro cabeçalho de seção.

### O que cada tag contém que NÃO seria dedutível numa prosa única com a fase apontada

- `<abertura>`: nada. O conteúdo se auto-identifica pelo gatilho ("o que a 1ª mensagem DELE é
  decide o seu turno", `:32`). A tag não desambigua — ela só serve de **endereço** para `:83`
  ("«Seria agora ?» é a mesma sondagem do dia da `<abertura>`"), que economiza reescrever a frase.
- `<apresentacao>`: aqui a tag faz trabalho semântico real. `:37` a usa para **rotear uma
  ambiguidade da fala dele**: "pergunta que ELE mesmo digitou … NÃO é o texto do site — é a
  `<apresentacao>`, e aí você cumprimenta E responde no mesmo turno". Sem nome de fase, essa frase
  teria de reescrever a conduta inteira em vez de apontá-la.
- `<cotacao>`: nada que dependa da tag XML — o bloco tem a **própria subdivisão interna por
  caixa-alta** ("QUAL preço sai", "EM QUE FORMATO", "COMO você chama", "O QUE VAI JUNTO", "COMO
  você termina o turno", `:60-84`). É a prova, dentro do próprio arquivo, de que organização não
  depende de tag.
- `<fechamento>`: **é o caso que sustenta a subdivisão inteira.** `:81` enuncia a regra do verbo —
  "«Posso confirmar», «vamos confirmar», «fechamos» e «Confirmado ?» são do `<fechamento>`, só
  depois do sim". A conduta **indexa o verbo pela fase**. Numa prosa única essa regra não é
  enunciável na forma curta; viraria uma condicional posicional ("antes do sim dele… depois do sim
  dele…") repetida em cada lugar que a toca — e ela é tocada em `:81`, `:91`, `:105`, `:175`,
  `<nucleo>`:18, `<nucleo_final>`:359 e no reminder:5.
- `<recuo_pos_objecao>`: existe pelo **contraste com `<fechamento>`**, e o contraste é escrito nos
  dois lados: `:93` ("Isso NÃO é o `<recuo_pos_objecao>`: lá ele diz que ainda não fechou … aqui
  ele já quer, só não manda no relógio") e `:98` ("diferente do «vou te avisando» do
  `<fechamento>`"). ~700 chars somados para a mesma distinção. **Mas ela é load-bearing e espelha
  um detector**: `_disciplina.py:326` (`_NAO_E_RECUO`) codifica exatamente que
  `te avis|vou avisando|me confirma|te confirmo` **nunca** é recuo. Prosa e código concordam;
  apagar um lado do contraste desalinha o prompt do detector.
- `<enquanto_ele_nao_chega>` (224 chars, o menor bloco da conduta): dois dos três terços de `:109`
  estão ditos, **mais completos**, na tag A2 `<ja_pediu_a_foto_da_portaria>`
  (`contexto_dinamico.md.j2:25`) — mesmas duas frases proibidas ("vai vir mesmo ?", "chega em
  quanto tempo ?"), mesmas duas prescritas ("Vou me arrumar rs", "Estou te esperando"). O que só o
  BP_GERAL tem é "**já peça a foto da chegada**" ANTES do 1º pedido, quando
  `foto_portaria_pedida_em` é NULL e a tag não sai.
- `<retomada_pos_silencio>`: os três itens (`:113` retome do ponto exato; `:115` repetiu a pergunta
  → responda de novo com OUTRAS palavras; `:117` o que ele acabou de recusar manda) estão
  condensados, em alguns trechos quase palavra por palavra, no `reminder.md.j2:8`. Mas o reminder
  só entra com **≥8 AIMessages** (`_precisa_reminder`, `prepare_context.py:595`) — numa conversa
  curta em que ele volta depois de silêncio, nem reminder nem ponteiro.

### O que só existe por causa da subdivisão (o custo)

1. **Preâmbulo `:27-29` (~980 chars).** As duas primeiras orações de `:27` existem SÓ para declarar
   que há tags e que a cauda aponta uma. A terceira ("o funil não é trilho: ele pode pular na
   frente… você atende onde ELE está") é a salvaguarda anti-amputação registrada em 25/07 — que
   também só é necessária porque existem tags a amputar. Sem tags, o parágrafo cai para `:29`
   (que vale em qualquer fase e não menciona estrutura).
2. **Travessia dupla `:93` ↔ `:98`** — a mesma distinção "vou te avisando" × "vou ver", escrita
   dos dois lados da fronteira.
3. **Ressalva de travessia `:165`** (dentro de `<desconto>`, apontando de volta pro `<fechamento>`:
   "sem ela, uma pergunta dele continua sendo pergunta, e o `<fechamento>` manda responder e
   esperar o sim").
4. **Restatement de regra cross-fase**: a sondagem-do-dia-é-uma-vez aparece em `:44` (`<abertura>`)
   e `:83` (`<cotacao>`), porque a sondagem cabe em duas fases. Ambas apontam a MESMA flag
   `<ja_sondou_o_dia>`.

Overhead honesto de fronteira: **~1,3–1,6k chars de 11,9k (11–13%)**.

### Veredito D1 — **manter, com uma reorganização registrada (não um corte)**

As 4 tags do funil-núcleo se pagam: são o vocabulário que `_PROXIMO_PASSO` e 6 cross-refs internas
usam, `<apresentacao>` resolve um roteamento de ambiguidade (`:37`), e `<fechamento>` carrega a
regra do verbo — o item de conduta com o maior número de ecos e o custo de erro mais documentado.
**Fundir em prosa única não devolve os 11–13%**: o contraste `:93`/`:98` voltaria como condicional
posicional e a regra do verbo teria de ser repetida em cada site que hoje só a aponta.

O desalinho real não é "7 tags é demais" — é que **3 das 7 não são fases**, são reações a evento do
cliente, e a estrutura as trata como se fossem:

- `<retomada_pos_silencio>` (847): gatilho determinístico **já computado e já renderizado**
  (`<tempo_desde_ultima_msg_cliente minutos="N"/>`, `contexto_dinamico.md.j2:17`, dispara em
  ≥3 min) — e essa tag é um **fato nu, sem nenhuma instrução anexada**. A fase existe, o sinal
  existe, o ponteiro não. Registro; não proponho mexer (ver "o que recuso propor").
- `<recuo_pos_objecao>` (1.297): gatilho determinístico já computado (`classificar_recuo` →
  `recuo_detectado` no State, `prepare_context.py:190`), consumido só pelo `extrair`. Registro;
  não proponho (ver D2-4).
- `<enquanto_ele_nao_chega>` (224): tem ponteiro e duplica a tag A2 que já a cobre melhor. É o
  corte mais limpo do bloco e o menor — 224 chars não justificam o risco. Registro; não mexer.

---

## D2 — o que caberia melhor como flag determinística ou canned

### (i) Candidatos fortes

#### D2-1 · Bolha de espera antes do `escalar` → **canned** (não flag)

- **Prosa atual:** `regras.md.j2:269` — "Antes de chamar a ferramenta, deixe uma bolha curta e
  natural de espera («Um momento amor») — sem ela o cliente fica no vácuo; depois de escalar, mais
  nenhum texto no turno. Exceção: no `conteudo_ilegal` … a bolha de espera NÃO existe."
- **Comportamento em prod:** `nos/post_process.py:50-58` acha a AIMessage que carrega o
  `tool_call` de `escalar` e zera tudo DEPOIS dela, preservando o que veio antes. Se a IA não
  escreveu nada antes da tool, **o cliente fica em silêncio com a IA pausada** — exatamente o vácuo
  que o pool `ESPERA_ESCALADA_CANNED` (`_canned.py:93-97`) já existe pra matar. Só que hoje ele é
  injetado **apenas na escalada de GUARDA** (`escalada_de_guarda`, `post_process.py:66-76`, "análise
  prod 22/07: o cliente ficava no vácuo"), nunca na escalada que a própria IA decide.
- **É do tipo "uma vez"?** Sim, e da forma mais estrita: exatamente **uma** bolha, **antes** da
  tool, **nunca** depois. Idempotência disfarçada de prosa — e o cut point já é código.
- **Gancho:** `post_process`, no ramo `corte is not None`: se `mensagens[:corte+1]` não produz
  texto, injeta `escolher_espera_escalada(seed=turno_id)`. **Sem coluna, sem migration, sem
  detector novo** — o pool, o sorteio determinístico por `turno_id` e o corte já existem. A
  exceção documentada (`conteudo_ilegal` sem espera) é lida do arg `motivo` do próprio `tool_call`,
  determinística.
- **Risco de regressão:** baixo. Só age quando o turno sairia mudo. O risco real é injetar "Um
  momento amor" onde a recusa seca deveria ficar sozinha — coberto pela leitura do `motivo`
  (`ferramentas/escalada.py:40,72` tem o enum fechado).
- **Gate:** teste unitário novo, no padrão dos `tests/unit/test_disciplina_*` (o pool e o corte são
  puros); `evals/e2e/conduta_gate.py` só se a massa tiver cenário que escale — caso contrário
  **sem gate e2e, precisa roteiro novo**.

#### D2-2 · O número do teto de desconto pré-computado na cauda

- **Prosa atual:** `regras.md.j2:159` e `:160` — "até
  `{{ (desconto_degrau_pct * 100) | round | int }}`% abaixo do preço de tabela do pacote" e "até
  `{{ (desconto_teto_pct * 100) | round | int }}`%". O modelo recebe o **percentual** e tem de
  multiplicar de cabeça.
- **A aritmética já está escrita em Python:** `dominio/atendimentos/service.py:1045-1066` calcula
  `piso = preco_de_tabela × (1 - desconto_teto_pct)`, por duração, olhando a tabela da modelo. Ela
  é usada para **julgar** a oferta da IA (abaixo do piso → escala `fora_de_oferta`,
  `service.py:362`/`:398`) e **nunca é mostrada a ela**.
- **Comportamento em prod em jogo:** erro de multiplicação/arredondamento cai num de dois lados —
  oferta acima do degrau (desconto tímido, perde a venda que a escada existe pra salvar) ou abaixo
  do piso, e aí a guarda **escala à toa** e a venda vira handoff. `_DESC_VALOR`
  (`ferramentas/extracao.py:105-108`) já nomeia esse modo: "sem a duração o sistema não consegue
  conferir o piso e escala à toa uma oferta válida".
- **É do tipo "N vezes"?** A **contagem** já é (`n_contrapropostas`, ADR-0031). O que falta não é a
  contagem — é o **número**. Então **não é flag nova**: é um campo derivado na cauda, pendurado no
  contador que já existe.
- **Forma mínima proposta:** renderizar o valor do teto **dentro do texto da tag que já sai**,
  `<ja_fez_contraproposta n="1">` (`contexto_dinamico.md.j2:21`), que hoje diz "você tem a segunda
  e ÚLTIMA contraproposta — o teto" sem dizer quanto é. Um campo novo no `ContextoDoTurno`
  (`_contexto_do_turno.py`) + cálculo em `_resolver_variaveis` reusando a função de piso do service
  (o `atendimento` já traz `valor_acordado` e `duracao_horas`) + uma cláusula no template.
  **Sem migration, sem tocar BP_GERAL.**
- **Por que só o teto, e só em `n=1`:** o degrau (`n=0`) não tem tag onde pendurar, e renderizá-lo
  incondicionalmente convida a IA a ofertar desconto antes de ele pedir (`:157` manda defender o
  valor primeiro). Não há hoje sinal de "houve objeção de preço" — `recuo_detectado` não é isso.
  Renderizar só o teto mantém a escada fechada, não entrega a tabela de pisos, e cobre o degrau
  onde a guarda de fato escala.
- **Risco de regressão:** o número na cauda pode ser lido como "oferte isto agora". Mitigação
  estrutural: a tag só existe **depois** de a 1ª contraproposta ter saído, e o texto dela já ordena
  "Só se ele insistir DE NOVO, pedindo abaixo do ofertado".
- **Gate:** `tests/unit/test_contrato_variaveis_contexto.py` (campo novo tem de existir no
  `ContextoDoTurno` e ser lido pelos templates — é o teste que amarra os dois sites);
  `tests/unit/test_contraproposta_flag.py` como vizinho. Comportamento: `sim_deepseek.py` /
  harness lado-a-lado num roteiro de objeção de preço em duas rodadas. `conduta_gate.py` **não**
  mede o valor da contraproposta (mede `cotou`/`empurrao`/`estilo_dist`/fluxo JSD) → **precisa
  roteiro novo** para medir o número.

#### D2-3 · "Tá incluso" com `<fetiches>` vazio → guard determinístico

- **Prosa atual, três sites:** `:48` (`<apresentacao>`: "sem essa linha no seu bloco a apresentação
  fica só no estilo, sem lista de incluso"), `:246` (`<fora_do_cardapio>`: "«tá incluso» você só diz
  de item que está NOMINALMENTE na linha «Inclusos» … nem quando ele aparece num exemplo desta
  conduta"), `:288` (preâmbulo dos `<exemplos>`: não copie item que não está no seu bloco).
- **Falha colhida:** `inventario-turno.md:98-113` — bolha `f6c2995c` disse **"Beijo na boca e oral
  sem camisinha tá incluso amor"** com `<fetiches>` = `(sem fetiches cadastrados)`, copiando o
  `<exemplo>` de `:304` palavra por palavra. É a prova de que **3 proibições em prosa perdem para 1
  exemplo concreto** — e portanto que este item não se corrige com mais prosa.
- **É gate:** o conjunto de itens declaráveis como inclusos é **fechado por modelo**. Mesma forma
  do `bolhas_eco_regiao` (`output_guard.py:313`), que compara a fala contra `tokens_de_lugar` do
  cadastro e dropa a bolha ofensora.
- **Versão mínima proposta (risco quase nulo):** modelo **sem nenhum fetiche incluso** → qualquer
  declaração de "tá incluso"/"vem junto"/"já vem" é ofensa. Zero risco de FP por vocabulário
  porque não há vocabulário a comparar, e é literalmente o que `:48` já ordena. Pega o caso
  observado.
- **Por que NÃO a versão completa** (comparar o item nomeado contra os tokens de Inclusos): `:133`
  estabelece que a penetração vem no programa e **não** está na lista de fetiches — o conjunto
  permitido é `Inclusos ∪ {implícitos do programa}`, e um FP aqui derrubaria a fala que `:133`
  manda dizer ("Você NUNCA nega o sexo"). Só a versão mínima.
- **Gancho:** `output_guard`, mesma família de gatilho de `sonda`/`regiao` (regen 1x → drop da
  bolha). `_lugares_permitidos` (`output_guard.py:484`) já abre a conexão e lê o cadastro do
  modelo — a leitura de `modelo_fetiches` entra na mesma query.
- **Gate:** teste unitário puro (padrão `test_disciplina_*`); e2e com uma modelo da massa sem
  fetiches — a massa do gate já tem (o trace do inventário rodou com `Manu`, `(sem fetiches
  cadastrados)`).

### (ii) Candidatos fracos — ficam prosa, por "Graus de liberdade"

#### D2-4 · Gatilho do `<recuo_pos_objecao>` (já detectado, sem ponteiro)

`classificar_recuo` (`_disciplina.py:398`) roda todo turno e vai ao State como `recuo_detectado`,
mas é consumido só pelo `extrair` (rebaixa `aceita_valor`). Tentador virar `<ele_recuou>` na cauda.
**Não proponho:** (a) não é "uma vez/N vezes" — o próprio docstring de `_recuo_no_turno`
(`_janela_do_turno.py:159-184`) crava que é **EVENTO do turno, não estado**; (b) a conduta de recuo
tem muitos caminhos válidos (recuar limpo × defender uma vez quando o motivo é preço, `:100-103`) —
campo aberto, prosa; (c) o dado que a IA precisa já chega: o rebaixamento produz `<valor_cotado>`
(`contexto_dinamico.md.j2:7`), que instrui "«combinado», «fechamos», «confirmado» não cabem ainda".
Achado: a prosa está certa onde está.

#### D2-5 · "No máximo uma pergunta sua por turno" (`:29`)

Contável (bolhas com "?" no turno). Não há net; a regra só é operacionalizada no feedback de regen
(`output_guard.py:611-614`, `_EXTRA_SONDA`: "uma pergunta sua no turno, no maximo"). **Fraco:**
(a) sem falha colhida; (b) a política de drop não é óbvia — qual pergunta cai? — e dropar a errada
troca um defeito de estilo por uma pergunta perdida, que é exatamente o precedente ruim do drop
mudo da sonda ("deixava o turno sem a pergunta que o modelo quis fazer e a conversa parava",
`output_guard.py:220-221`). Recomendação: **instrumentar como métrica** antes de virar gate. Não
proponho o gate.

#### D2-6 · O branch de 4 vias da `<abertura>` (`:34-37`)

Metade é literal-testável (a âncora do site "peguei seu contato no site"; presença de "?" na 1ª
mensagem). **Não proponho.** O commit mais recente do repo (`397daef`, "o oi com pergunta colada
deixa de fazer a pergunta esperar") é a evidência de que essa classificação erra — e um
classificador cego numa tag da cauda ("é só cumprimento") sobre uma mensagem que TINHA pergunta
reproduz essa regressão **com a autoridade de um bloco interno**, que `<instrucoes_meta>`:6 manda
obedecer em silêncio. É o modo de falha da memória `fix_sondagem_agora_regex_cego_variante`
(detector por literal × prompt por família), agravado porque aqui o detector **calaria** a conduta
certa.

#### D2-7 · Duração pedida que não existe na tabela (`:136`, `:141`)

Gate legítimo, mas o dado já está no BP_MODELO (a tabela) e o teto já tem flag
(`sem_periodo_longo`). O que falta é a rede de SAÍDA, que é o D2-8. Não proponho separado.

#### D2-8 · Preço fora do conjunto fechado da tabela (registro de medição, não de implementação)

"Preço inventado" é failure-mode em caps por prod (escala léxica, `agente/CLAUDE.md`) e a prosa o
proíbe em 4 sites (`:15`, `:61`, `:136`, `:141`). O conjunto de números que a IA pode dizer é
fechado: preços da tabela ∪ extras/dobro pré-computados (`persona.py:render_fetiches`) ∪
`{{ pix_valor }}` ∪ degrau/teto ∪ número do logradouro quando `numero_liberado` ∪ horas. Um guard
"3+ dígitos fora do conjunto" teria a mesma forma do `_RE_CHAVE_PIX` (`output_guard.py:245`).
**Não proponho agora:** o conjunto permitido cruza 5 fontes e um FP derruba uma cotação **correta**
— o pior colateral possível. Precisa ser MEDIDO primeiro contra o corpus de falas reais da IA em
prod, como o `_RE_ECO_REGIAO` foi medido contra 525 falas (`output_guard.py:272-276`).

### (iii) Já determinístico e ainda duplicado como prosa — o achado é o corte, não uma flag

#### D2-9 · A dobra do menage já vem pré-computada

`regras.md.j2:77` ("Os extras «por pessoa» … não somam o «+Extra» dos atos, **DOBRAM** o pacote") e
`:260-262` ("são 2 pessoas, então DOBRA o pacote"). Mas `persona.py:render_fetiches` (linhas
250-256) já monta `"dobro": preco * 2` no BP_MODELO, com o comentário explícito: "Totais
pré-computados: a conta chega pronta no dado — **o modelo copia, não soma** (800+800 já saiu como
«1200» em replay 22/07)". `:262` acerta (aponta a seção "Por pessoa" da tabela); `:77` reescreve a
aritmética que o bloco dela já fez. **Corte candidato:** em `:77`, trocar "DOBRAM o pacote" pela
referência à seção, como `:262` faz. Ganho pequeno em chars, ganho real em não reabrir a conta.

#### D2-10 · O "?" da proposta de confirmação

`:82` dedica um bullet inteiro à regra. Ela **já é cravada deterministicamente**:
`workers/_saida_guard.py:399-418` (`restaurar_interrogacao_proposta`), escrito por causa do
incidente #34, com o próprio comentário admitindo que "prompt a 0.7 não garante, então a rede
crava". A prosa sobrevive com ecos em `<nucleo>`:18, `<nucleo_final>`:359 e reminder:5. Registro:
é o caso em que o trilho determinístico já venceu e a prosa segue em 4 sites. O corte pertence ao
eixo da redundância, com gate por simulador (`agente/CLAUDE.md`: "Dedup não é deleção grátis").

#### D2-11 · `<enquanto_ele_nao_chega>` × `<ja_pediu_a_foto_da_portaria>`

Ver D1: a metade "não cobre" de `:109` está dita, mais completa, na tag A2 da cauda
(`contexto_dinamico.md.j2:25`). Só o BP_GERAL tem "já peça a foto" **antes** do 1º pedido (flag
NULL → tag ausente). Corte candidato: reduzir `:109` a essa metade. 224 chars — registro, não
recomendo mexer.

---

## O que eu recuso propor, e por quê

1. **Injeção condicional por fase / amputar o `<conducao_da_venda>` pela fase da cauda.** Não
   proponho. O motivo de 25/07 continua válido nessa forma: o `extrair` roda DEPOIS do `llm`, então
   o `estado` renderizado é do turno anterior — um prompt cortado por fase chega um turno atrasado
   e o cliente que pula o funil ("quanto é ?" no primeiro oi) cai num prompt sem a fase que ele
   abriu. Nenhuma proposta minha amputa BP_GERAL: D2-2 é **aditiva** na cauda, pendurada num
   contador já materializado; D2-1 é no `post_process`; D2-3 é no `output_guard`.
   - Registro, **sem propor**, a distinção que existe: `min_desde_ultima_msg_cliente` e
     `recuo_detectado` **não** vêm do `extrair` — são computados no `prepare_context` sobre a janela
     do turno atual (`prepare_context.py:184-190`, sobre a janela LIMPA), logo não são um turno
     atrasados e escapam do motivo da recusa. Se algum dia se quiser um ponteiro de cauda para
     `<retomada_pos_silencio>`/`<recuo_pos_objecao>`, esses dois sinais são os candidatos. Mas eles
     não pedem amputação, e 847+1.297 chars de prefixo não justificam abrir a discussão **sem uma
     falha colhida**.
2. **Fundir as 7 tags em prosa única.** A pergunta ofereceu o corte; eu recuso. Perde a regra do
   verbo (`:81`), o roteamento de `:37` e o alinhamento do contraste `:93`/`:98` com
   `_NAO_E_RECUO`, e devolve menos que os 11–13% porque o contraste volta como condicional
   posicional.
3. **Qualquer coisa por-modelo ou por-turno no BP_GERAL.** Nenhuma proposta toca o prefixo
   cacheado.
4. **Flag nova com coluna/migration nesta rodada.** Nada em (i) precisa: D2-1 reusa pool + corte
   existentes; D2-2 é campo derivado no `ContextoDoTurno`; D2-3 é guard de saída. Se alguma virasse
   coluna, seria escrita em prod (CLAUDE.md §0) — registrada, **jamais executada**.
5. **Remover eco multi-site listado no `agente/CLAUDE.md`.** D2-9/10/11 são observações de
   fronteira prosa↔código, não propostas de deleção; o corte é do eixo da redundância e exige gate
   por simulador.
