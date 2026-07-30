# Eixo A — redundância intra-arquivo e forma (`regras.md.j2`)

Objeto: `api/src/barra/agente/prompts/regras.md.j2`, **53.155 chars** na versão de 30/07 11:32 (o
`inventario-turno.md` mediu 53.007 e o `mapa-de-ecos.md` numera linhas de antes da edição — todas as
linhas citadas aqui foram reverificadas contra o arquivo atual).

**Magnitude do eixo: 1.823 chars (3,4% da conduta, ≈ 570 tokens).** 824 em corte seguro, 999 em corte
com gate. Isso é o teto honesto de A1+A2 — a redundância intra-arquivo **não** é onde está a gordura.
Duas medições sustentam isso:

- Só **3 pares de n-gramas ≥ 30 chars** se repetem no arquivo fora de par regra↔exemplo (L48↔L300,
  L197↔L199, L248↔L265). Repetição literal quase não existe; o que existe é paráfrase.
- O bloco mais pesado, `<conducao_da_venda>` (22,5% da conduta), é o **menos** redundante por char
  (3,5% recuperável). Os densos são pequenos: `<menage>` 7,7%, `<desconto>` 6,6%.

Consequência para quem for priorizar: cortar redundância paga ~3%; o resto do custo de atenção é
estrutural (blocos inaplicáveis ao turno — 21% da conduta pelo §2 do inventário) e é outro eixo.

**Ecos declarados no `agente/CLAUDE.md` que NÃO trato como redundância** (verificados um a um):
`<nucleo>`↔`<nucleo_final>` (sanduíche primacy/recency), `<cotacao>` bullet-2 ↔ lista-de-quem-ganha-nome
(a "segunda porta do Completo", eco intra-bloco declarado), e o preâmbulo de `<exemplos>` como portador
da instrução de substituição. Onde argumento contra um deles, digo explicitamente.

---

## A1 — mesma regra, 2+ sites intra-arquivo

### A1.1 · "Depois do teto não há oferta nova" — 3 sites em 6 linhas · **147 chars** · risco baixo

| site | redação | papel |
|---|---|---|
| `:160` | "Uma vez feita, esse é o seu melhor valor: não desce mais um centavo**, não tem terceira oferta**" | canônico do teto |
| `:161` | "Depois do teto — ele pedindo menos DE NOVO, a terceira insistência — … **não há oferta nova**. \"Poxa amor não consigo\"" | **canônico** (é o item que define o gatilho) |
| `:165` | "A recusa só volta se ele pedir de novo, explícito, um número abaixo do valor na mesa **— e depois do teto não há oferta nova, só \"Poxa amor não consigo\"**" | carona |

Repetição tipo (ii): paráfrase sem caso novo. `:161` é o item 5 da própria escada — quem lê `:165`
acabou de ler `:161` quatro linhas antes.

- Cortar: o trecho grifado de `:165` (**66**) e ", não tem terceira oferta" de `:160` (**25**).
- (b) Protege: a terceira insistência não gerar uma 3ª oferta (ADR-0031).
- (c) Risco **baixo** — o gatilho e a fala sobrevivem em `:161` intactos; e há rede de código
  (`_abaixo_do_piso` escala `fora_de_oferta` antes de gravar).
- (d) Gate: `evals/e2e/cenarios.py::desconto_abaixo_teto` + `desconto_entre_degrau_teto` (HARD no
  `conduta_gate.py`).

Terceira carona no mesmo bloco: `:163` afirma "A escada é sua, nunca dita: você não explica que existe
degrau, teto, limite nem política (…)" e emenda "**— o cliente vê só a oferta, nunca a regra por trás
dela**" (**56**), que é a mesma frase dita ao contrário. A sentença seguinte ("Pergunta sobre o seu
limite … recebe o valor que está na mesa") acrescenta caso → **manter**. Risco baixo, mesmo gate.

### A1.2 · "Cobra dobrado (por pessoa)" — 2 sites em 2 linhas · **112 chars** · risco baixo

- `:260` (canônico): "menage/casal é o seu fetiche \"por pessoa\" — são 2 pessoas, então DOBRA o
  pacote; o valor sai da seção \"Por pessoa\" da sua tabela, sobre o pacote que ele considera (o total
  dobrado, nunca o \"+Extra\" dos atos)."
- `:262` (carona): "a cobrança é por DUAS pessoas (dobra o pacote), e você cota pela seção \"Por
  pessoa\" do seu <fetiches> — o total dobrado, não um \"+Extra\"" → vira **"cobra dobrado como acima"**.
- Terceiro site, `<cotacao>:77`, é outro bloco e é onde o extrator/precificador do turno de cotação
  precisa da regra → **manter**.

`:262` só tem conteúdo próprio depois disso (quem é a segunda pessoa, o espelhamento "vocês dois", o
não-cadastro). (b) Protege ADR-0035 (casal/menage dobra, não soma "+Extra"). (c) Risco **baixo**: a
conta fica dita a 2 linhas, no parágrafo que abre o bloco. (d) Gate: **sem gate** — não há cenário e2e
de menage; usar `scripts/eval_corpus/sim_deepseek.py` com uma modelo que tenha seção "Por pessoa".

### A1.3 · "Meta-navegação" na linha 5 do `<nucleo>` · **98 chars** · risco baixo

`:18` termina com "(exceção única de emoji: a contraproposta do <desconto>**; o resto em
<conducao_da_venda>, inclusive quando cabe a sondagem do dia e quando ela já foi usada**)".

O trecho grifado **não é regra** — é sumário de onde ler, num arquivo que o modelo lê inteiro em todo
turno. (b) Protege: nada; a exceção de emoji (que é regra) fica. (c) Risco **baixo**. (d) Gate: nenhum
necessário.

**Contra-argumento que rejeito:** `:18` também repete as duas falas de `:80` ("Seria que horas ?",
"Consigo às 22h, fecha ?") e a desambiguação "a sondagem ABERTA proibida é a de interesse … não a
pergunta de horário" (49 + 126 chars). Parece carona, mas o `agente/CLAUDE.md` registra que essas
duas coisas foram **postas ali de propósito em 30/07** — o eco antigo dizia "sim/não" e proibia a
pergunta de horário que `<fechamento>` prescreve. Cortar reabre o bug nomeado. → **manter os 175.**

### A1.4 · "O verbo: OFERECE antes do sim" — restatement em `<fechamento>` · **47 chars** · risco baixo

`:91` diz "**e o verbo segue a regra de cima**: enquanto ele não disse sim, você OFERECE (\"Seria 15h
então ?\", \"800 as 2h, pode ser ?\"); \"confirmar\" só depois do sim dele" — referencia **e** repete
(o padrão que o `agente/CLAUDE.md` chama de "faz pela metade" na fronteira DESC↔prompt).

- Redação curta: `e o verbo segue a regra de cima ("Seria 15h então ?", "800 as 2h, pode ser ?") —
  "confirmar" só depois do sim.`
- (b) Protege: não cravar horário sobre dado ambíguo antes do sim. As **falas** são o que esse caso
  acrescenta e ficam. (c) Risco **baixo** (o canônico `:81` está 10 linhas acima, e há rede:
  `_PEDE_FECHAMENTO`, `restaurar_interrogacao_proposta`, 5 `ToolException`). (d) Gate: `make evals`
  (o "?" e o verbo têm detector) + `conduta_gate`.

### A1.5 · "Responda a pergunta dele antes de vender" — 4 sites; 1 é carona pura · **54 chars** · risco baixo

Canônico: `:29`, no preâmbulo do `<conducao_da_venda>`, sob o rótulo "**Vale em qualquer fase**".
Caronas com caso novo (→ manter): `:36` (pergunta colada ao cumprimento), `:37` (texto do site × pergunta
dele — é o fix do commit 397daef, **não tocar**).
Carona pura: `:181`, fim do `<agenda>`: "preço não entra se ele não pediu valor**; responder a pergunta
que ele fez vem antes de vender**".

(b) Protege: responder "a partir de que horas?" com hora, não com preço — e essa metade fica.
(c) Risco **baixo**: `:29` já diz "vale em qualquer fase". (d) Gate: `sim_deepseek.py` com turno de
pergunta de horário; sem cenário e2e dedicado.

### A1.6 · "\"o que você procura?\"" — 3 sites, 2 no mesmo bloco · **50 chars** · risco baixo

`:41` (abertura, com "em nenhuma paráfrase" — canônico da fase), `:76` ("NÃO cola no preço: sondagem
aberta (\"o que você procura?\")") e `:80` ("A sondagem proibida é a de INTERESSE (\"o que você
procura ?\"), nunca a pergunta de horário").

`:76` e `:80` estão a 4 linhas um do outro, no mesmo `<cotacao>`, com a mesma fala entre parênteses.
`:80` é o site que carrega a **fronteira** (é o que separa esta regra do empurrão) → canônico do bloco.
Cortar: o parêntese de `:76` (**24**) e o rabo ", nunca a sondagem de novo" de `:83` (**26**, que
repete o `:44`+`:83` que ele mesmo acabou de dizer).

(b) Protege: sonda-de-balcão colada ao preço. (c) Risco **baixo** — há rede de código com regen e
feedback (`_RE_SONDA_BALCAO` + `_EXTRA_SONDA`), e a proibição fica dita duas vezes no arquivo.
(d) Gate: `make evals` (métrica de sonda barrada) + `conduta_gate`.

### A1.7 · "\"Só eu amor\" seco te obriga a desmentir depois" — 2 sites, 17 linhas · **70 chars** · risco baixo

Único n-grama literal de 30 chars entre blocos distintos: "e te obriga a desmentir depois" em `:248`
(`<fora_do_cardapio>`, gatilho = "me indica outra") e `:265` (`<menage>`, gatilho = pergunta de
segurança). Canônico é `:265` — é o único que dá a fala substituta ("Só eu e você").

- `:248` vira: `A recusa é de INDICAR, não uma afirmação sobre quem existe aí ("Só eu amor" seco —
  <menage>).`
- (b) Protege: não fechar a porta do cliente que sonda amiga por via indireta. (c) Risco **baixo**: o
  cross-ref para `<menage>` já está na frase e a fala substituta nunca esteve aqui. (d) Gate: **sem
  gate** — precisa de roteiro novo ("me indica outra" + "você atende sozinha?").

### A1.8 · "Período que não está na tabela não existe" — 2 sites · **115 chars** · risco baixo/médio

- `:141` abre o `<sobe_o_ticket>` com "você só oferece pacote que EXISTE em <programas> — a duração E o
  valor saem só da tabela.**Período que não está lá não existe pra vender:** você NUNCA improvisa
  preço…" → a 2ª sentença é a 1ª ao contrário (**47**, risco baixo).
- `:136` (`<girias>`, "meia hora"): "só vira cotação se os 30min existem nos seus <programas> — se não
  existem, ancore no que você tem (\"30min não tenho amor, mínimo 1h 600\")**e NUNCA invente um preço
  pra uma duração que não está na sua tabela**" → o grifado é o 3º site da mesma proibição (`<nucleo>`
  linha 2 + `:141`), 5 linhas depois de `:141` (**68**, risco **médio**: "meia hora" é pedido
  altíssimo-frequência e a proibição fica só no `<nucleo>`/`:141`).
- (b) Protege: inventar preço proporcional (prejuízo). (d) Gate: `cenarios.py::upsell_sinal_de_tempo`
  cobre duração **acima**; o caso "abaixo" (30min) **não tem gate** — roteiro novo ou `sim_deepseek`.

### A1.9 · "A vídeo chamada só existe se estiver em `<programas>`" — 4 sites · **149 chars** · risco baixo

`:216` declara o escopo **global** da condicional: "ela não é sua — você não oferece, não cota e não
promete chamada nenhuma, **em nenhuma seção desta conduta que a mencione como saída**; o pedido de
prova se responde com foto (<midia>)". Isso é exatamente o que dispensa as caronas negativas:

- `:227` (`<midia>`): "**; se não estiver, a recusa fica sozinha e a conversa volta pro encontro**" (**71**)
- `:235` (`<protocolo_disclosure>`): "**; se não tem, ela não entra (<tipos_de_encontro>) e a prova que
  sobra é a foto**" (**78**) — o "sobra a foto" já está em `:216`.
- `:225` mantém o parêntese positivo ("ou pra vídeo chamada paga, se ela estiver na sua tabela").

(b) Protege: prometer chamada a cliente de modelo que não a vende (ADR-0021). (c) Risco **baixo** por
construção (a cláusula `:216` é auto-declarada como cobrindo as outras seções), mas (d) **sem gate**:
`cenarios.py::remoto_videochamada` roda uma modelo **com** o programa; a variante "sem vídeo chamada na
tabela" precisa de roteiro novo (ou `sim_deepseek` com tabela sem o programa).

### A1.10 · A fala da foto de portaria, 2× em 2 linhas · **102 chars** · risco baixo

`:197` (degrau 3, gatilho "me passa o apartamento") e `:199` (gatilho "to indo") repetem literal
"Quando chegar me manda uma foto da portaria amor". `:199` ainda diz a mesma coisa duas vezes dentro de
si ("é a foto que confirma… então peça sempre a foto, nunca só um \"me avisa\"").

- `:199` vira: `Ele avisou que saiu ("to indo") → siga normal, já pedindo a foto da chegada (mesma fala
  do degrau 3): um "cheguei" de texto não vale, é a foto que confirma.`
- (b) Protege: pedir a foto (gatilho do handoff interno) em vez de aceitar "cheguei" em texto.
  (c) Risco **baixo**. (d) Gate: `cenarios.py::foto_portaria` (existe e é barato).

### A1.11 · A dupla proibição do "tá incluso" — **manter**, com ressalva

`:48` (`<apresentacao>`) e `:246` (`<fora_do_cardapio>`) proíbem declarar incluso o que não está na
linha "Inclusos". É redundância real (2 sites), mas cada um traz o que o outro não tem: `:48` dá a
**conduta substituta** ("sem essa linha … fica só no estilo") e `:246` nomeia o **failure mode** ("nem
quando ele aparece num exemplo desta conduta"). Cortar qualquer um cai no padrão do incidente #36
(proibir sem dar fala de substituição). → **manter os dois.**

Ressalva que pertence a outro eixo, mas que este eixo prova: o §3 do inventário mostra o modelo
violando **as duas** e copiando o exemplo. Redundância aqui já foi testada em prod e não comprou
obediência — argumento de que aumentar N não é a alavanca.

---

## A2 — prosa longa → regra curta

Ordenado por chars × risco. Cada reescrita abaixo **preserva todas as falas** (as substituições são o
que o incidente #36 provou ser load-bearing) e corta justificativa que restata a regra.

### A2.1 · `:212` — distância/maps/proximidade · 1.311 → 1.103 · **208 chars** · risco médio

Hoje o parágrafo dá 3 formas proibidas, cada uma com sua justificativa própria, depois 4 falas
substitutas por ramo, depois um sumário ("responde a pergunta, não inventa número e empurra o
fechamento") que só descreve o que as falas já fazem.

Redação curta: as 3 proibições viram **uma lista** (mantendo os 8 exemplos de fala proibida), as duas
justificativas viram uma emenda só ("número inventado quebra a confiança quando não bate, e mandar
pesquisar entrega que você não sabe onde está"), sai o sumário e sai "a sua região **como ela está
escrita no seu bloco**" (que repete o "palavra por palavra" de `:195`).

- (b) Protege: incidente #36 (maps/bairro) e a alucinação de "Cambuí" (cluster nao_contidos 23/07).
- (c) Risco **médio**: a cláusula de distância/tempo **não tem rede de código** — `_RE_ECO_REGIAO` só
  casa locativo+nome próprio, então "uns 15-20min daqui" e "pertinho de você" passam batido. Por isso
  **mantive** as duas justificativas em forma reduzida, em vez de cortá-las: é a justificativa que faz
  o modelo generalizar para formas novas de chute geográfico.
- (d) Gate: `sim_deepseek.py` com os 3 turnos ("fica longe?", "quanto tempo até aí?", pin de
  localização) + `conduta_gate::externo_com_pix`; a métrica de região do output-guard mede o ramo
  interno.

### A2.2 · `:262` + `:265` — `<menage>` · **184 chars** · risco baixo/médio

`:262` já contabilizado em A1.2 (112). Em `:265`, a análise do "Só eu amor" é feita duas vezes dentro
da mesma linha (primeiro a fala, depois o porquê em 250 chars). Reduzir para: `"Só eu amor" seco jura
que mais ninguém existe ali e te obriga a desmentir depois; "Só eu e você" responde o medo real dele
sem dizer nada sobre quem mais existe.` (**72**).

(b) Protege: a pergunta de segurança não ser respondida sobre o prédio. (c) Risco **baixo/médio** (o
contraste é o que ensina). (d) **Sem gate** — roteiro novo.

### A2.3 · `:157` — item 1 do `<desconto>` · 895 → 786 · **109 chars** · risco baixo

O item termina com **três** formulações da mesma coisa: "não mudam sua tabela nem pulam degrau" / "seu
preço sai da sua tabela e do seu histórico interno, nunca da memória dele nem do print que ele
descreve" / "e você não valida, discute nem comenta o número dele". A 2ª é `<nucleo>` linha 2 repetido;
a 3ª é a única **acionável** (diz o que fazer com o número dele).

- Cortar a 2ª. (b) Protege: objeção com referência externa (print/anúncio/"da última vez foi 400") não
  pular degrau. (c) Risco **baixo** — as 3 âncoras concretas de objeção externa ficam. (d) Gate:
  `cenarios.py::desconto_dentro_degrau`.

### A2.4 · `:216` — reescrita do parágrafo da vídeo chamada · 794 → 707 · **87 chars** · risco baixo

(Distinto dos 149 de A1.9, que saem de `<midia>`/`<protocolo_disclosure>`; e de A1.10, contado à parte.)
Aqui, além do escopo global que `:216` já declara, o rabo ": a chave é o sistema que manda, e comprovante só vale em
imagem" repete os itens 4 e 5 do mesmo bloco, 10 linhas acima, depois de já dizer "no mesmo trilho do
uber". Vira "no mesmo trilho do uber (itens 2 a 5 acima)" (**64**). (b) Protege: chave Pix inventada e
"paguei" em texto — ambos com rede de código (`_RE_CHAVE_PIX`, `_eh_pre_anuncio_pix`). (c) Risco
**baixo**. (d) Gate: `cenarios.py::remoto_videochamada`.

### A2.5 · `:117` — dupla justificativa da retomada · 357 → 267 · **90 chars** · risco baixo

"nunca traga de volta um ato ou formato que ele já tirou da mesa (\"sem BDSM\", \"é estilo
namoradinha\") — **reintroduzir o que ele acabou de recusar é o sinal mais claro de que você perdeu o
fio**, e travar num termo que ele já negou espanta na hora." Duas justificativas para uma regra; a 2ª
é a que descreve a consequência no cliente. Cortar a 1ª.

(b) Protege: reintroduzir o que o cliente tirou da mesa em conversa longa. (c) Risco **baixo**.
(d) Gate: harness lado-a-lado (`evals/harness_fiel.py`) em thread longa; sem cenário dedicado.

### A2.6 · `:93` + `:98` — o contraste "vou te avisando" dito dos dois lados · **146 chars** · risco médio

`:93` (`<fechamento>`) e `:98` (`<recuo_pos_objecao>`) enunciam o mesmo contraste, cada um da sua
ponta, a 5 linhas de distância. Intra-arquivo, no mesmo contexto de leitura, o par bidirecional não
compra pedagogia (o argumento de "afirmar o limite pelos dois lados" do `agente/CLAUDE.md` é sobre
prompt × tool description, contextos separados — aqui é o mesmo).

- `:98` fica com o símbolo e o cross-ref: `é ele dizendo que AINDA não fechou (≠ o "vou te avisando" do
  <fechamento>)` (**79**).
- `:93` perde o fecho genérico "Cobrar o sim de uma hora que ele acabou de dizer que não garante … se
  contradiz e derruba a venda", **mantendo** a metade específica ("no mesmo turno em que você disse
  \"me avisa quando sair\"") (**67**).
- (b) Protege: não cobrar "confirmado ?" de quem já quer mas não manda no relógio; e não limpar
  horário/valor de quem não recuou. (c) Risco **médio**: a distinção tem implementação
  (`_disciplina.classificar_recuo`, `_NAO_E_RECUO`) que **lê as formas do prompt** — se a fala sair do
  prompt o detector cega em silêncio; nenhuma fala é cortada aqui, mas é o motivo do risco médio.
- (d) Gate: `judge_pos_envio` no harness lado-a-lado (o judge já mede este caso por nome) +
  `sim_deepseek` com "vou te avisando".

### A2.7 · `:246` — `<fora_do_cardapio>` · 1.270 → 1.196 · **74 chars** · risco médio

A regra "a recusa cobre exatamente o item pedido" é dita 3 vezes seguidas: (a) "cobre EXATAMENTE o item
… nunca os itens vizinhos"; (b) "o não de um ato não desmarca o programa nem apaga o que está no seu
bloco, que segue oferecido com a mesma prontidão de antes"; (c) "Dúvida sobre um item cala aquele item,
ela não cresce pra recusa do resto". Corte (b), fundindo o resto dela em (a) ("…nunca os itens
vizinhos, que seguem oferecidos com a mesma prontidão de antes") e mantendo (c), que acrescenta o caso
da **dúvida** (não só da recusa) e a simetria que generaliza.

- (b) Protege: a recusa de um ato derrubar o encontro inteiro. (c) Risco **médio** — é o bloco com a
  maior densidade de negação do arquivo (11,4/kchar) e a regra não tem rede de código. (d) **Sem gate**
  — `fora_do_cardapio` não tem cenário e2e; precisa de roteiro novo.

### A2.8 · `:48` — a fala de apresentação existe 2× no arquivo · **53 chars** · risco médio, valor alto

"Sou bem tranquila / Estilo namoradinha / Beijo na boca, oral sem camisinha 🥰" aparece inline em `:48`
**e** como diálogo no `<exemplo>` de `:300-304`. É o único n-grama de 42 chars repetido entre regra e
exemplo — e é **exatamente a string que vazou em prod** com `<fetiches>` vazio (§3 do inventário).
Duas cópias dobram a pressão de cópia; o molde canônico é o `<exemplo>`.

- `:48` vira: `… em 2-3 bolhas curtas, na sua ordem — o molde é o <exemplo> de apresentação. Os itens
  que ele cita são ILUSTRATIVOS: os SEUS saem nominalmente da linha "Inclusos" …` (mantém o
  antecedente do "Os itens", que hoje aponta para o parêntese removido).
- (b) Protege: a apresentação em 2-3 bolhas com a ordem estilo→incluso. (c) Risco **médio** (remove um
  molde de forma do site da regra; o molde continua existindo 250 linhas abaixo).
- (d) Gate: `evals/e2e/conduta_gate.py` com modelo `(sem fetiches cadastrados)` — o §3 do inventário
  mostra que esse gate **já reproduz a falha**, então é detector vivo: se o corte não piorar a taxa de
  "tá incluso" com fetiches vazios, passou.

### A2.9 · `:222` — justificativa dupla no `<midia>` · **40 chars** · risco baixo

"nunca como resposta a \"é bot?\": ali a dúvida não é sobre a sua aparência, é teste, **e prova
espontânea só entrega você** (<protocolo_disclosure>). **Queimar o book num teste de bot te deixa sem
mídia na hora do fechamento.**" — dois porquês para a mesma proibição, e o primeiro repete `:233`
("nunca prova espontânea"). Fundir em: `(<protocolo_disclosure>) — e queimar o book num teste te deixa
sem mídia na hora do fechamento.`

(b) Protege: não gastar o book num teste de humanidade. (c) Risco **baixo**. (d) Gate:
`cenarios.py::disclosure_insistente`.

---

## Julguei e decidi manter

| site | por quê |
|---|---|
| `:18` falas + desambiguação (175) | fix declarado de 30/07 no `agente/CLAUDE.md`; cortar reabre o bug do "sim/não" que proibia a pergunta de horário |
| `<nucleo>` ↔ `<nucleo_final>` (912) | sanduíche declarado. Se a aposta de recency vale é questão de estrutura (o `<nucleo_final>` está a ~8,5k tokens do fim), não de redundância |
| `:288` preâmbulo de `<exemplos>` (411) | o `agente/CLAUDE.md` o declara portador da instrução de substituição, e ele é **adjacente** aos exemplos; o `<nucleo>`:15 cobre outro escopo (números na prosa das regras, não nos diálogos) |
| os 6 inline "(com o SEU número)" / "(com o valor da SUA tabela)" (~140) | é a única forma da regra que fica **colada** ao número ilustrativo; dado o §3, cortar é exatamente o movimento errado |
| `:8` `<instrucoes_meta>` (979) | há ~180 chars de teste-de-tag repetido, mas é defesa anti-injeção: redundância ali é defesa em profundidade, não desperdício. Se alguém quiser tentar, o gate existe (`cenarios.py::jailbreak` + `evals/seguranca/aup/`) |
| `:48` ↔ `:246` (dupla proibição do "incluso") | cada site tem metade única (conduta substituta × failure mode) — ver A1.11 |
| `:44` ↔ `:92` ("proponha VOCÊ um horário concreto") | 3 gatilhos distintos (`<ja_sondou_o_dia>`, ele desconversa, `<ja_perguntou_o_horario>`) → tipo (iii), ganha alcance |
| `:89` ↔ `:105` (listas de verbos proibidos) | gatilhos distintos (ele pergunta × ele recuou); as listas divergem, o que é problema do eixo de contradição, não daqui |
| `:132` ↔ `:134` ("só existe se estiver no seu `<fetiches>`") | itens distintos (anal × dominação física) |
| `:54` ↔ `:157` (falas de autoelogio) | funções distintas (autoelogio × defesa de preço); repetir 3 falas curtas é mais barato que um cross-ref que o modelo tem de resolver |
| `:141` / `:149` / `:161` / `:218` / `:248` + tabela `:272` | motivo de escalada no ponto de uso + índice em `<quando_usar_escalar>` é o padrão declarado |

---

## Fronteira com os outros eixos (não desenvolvi)

- `:231` manda "é você mesma nas fotos?" para o book do `<midia>`; `:237` manda a mesma frase para a
  resposta-de-anúncio. Dois destinos para a mesma pergunta → **contradição**, não redundância.
- `<desconto>`:19/`:116` dizem "nesta negociação" e o contador materializado é **por atendimento** →
  eixo de contradição.
- 21% da conduta é estruturalmente inaplicável ao turno médio (§2 do inventário). Isso é ~15× o que
  este eixo inteiro recupera → eixo de estrutura.

---

## Placar

| classe | chars |
|---|---:|
| corte seguro (restatement puro / meta-navegação; nenhuma fala nem caso perdido) | **824** |
| corte com gate (precisa de eval, sim ou roteiro novo antes) | **999** |
| **total** | **1.823** (3,4% de 53.155; ≈ 570 tokens) |

Corte seguro = A1.1 (147) + A1.2 (112) + A1.3 (98) + A1.4 (47) + A1.5 (54) + A1.6 (50) + A1.7 (70) +
A1.8/`:141` (47) + A2.3 (109) + A2.5 (90).
Corte com gate = A2.1 (208) + A1.9 (149) + A2.6 (146) + A1.10 (102) + A2.4/`:216` (87) + A2.7 (74) +
A2.2/`:265` (72) + A1.8/`:136` (68) + A2.8 (53) + A2.9 (40).

Pior ofensor: **`<desconto>`** — 3 cópias intra-bloco de "depois do teto não há oferta nova" em 6
linhas (`:160`, `:161`, `:165`) mais 2 ecos declarados, e 256 chars recuperáveis em 3.877 (6,6%).
Vice: **`<menage>`** (7,7% de densidade, 184 em 2.403) — e é um bloco que a maioria das modelos nem
ativa, então paga a redundância todo turno por nada.
