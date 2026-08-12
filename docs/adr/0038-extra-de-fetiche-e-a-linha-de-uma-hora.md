---
data: 2026-08-11
status: aceito
supersedes: a fórmula preço-hora do ADR-0030 (o extra derivado; o resto do 0030 segue de pé)
refina: ADR-0031, ADR-0037 (o extra desce pela MESMA escada do pacote)
nota: quando escrito, este ADR afirmava que o ADR-0035 (por-pessoa) ficava INTOCADO. Deixou de ser
  verdade no mesmo dia — o ADR-0039 superou o 0035 e trouxe composição para dentro desta regra.
---

# ADR-0038 — O extra de fetiche é a linha de 1 HORA do mesmo programa, no patamar vigente

## Contexto

O ADR-0030 definiu o extra de um **Fetiche** pago como o **preço-hora efetivo do pacote**:
`preco_tabela ÷ duracao_horas`, somado uma vez por fetiche. A revisão de 11/08/2026 do mesmo ADR
rebaixou essa conta a *fallback* (o preço cadastrado por fetiche voltou a ser a fonte de verdade),
mas ela continuou sendo o que quase todo o prod usa — a coluna `modelo_fetiches.preco` guarda o
sentinel de flag na maioria dos vínculos.

Ao revisar a tabela da **Catarina** (Normal: 30min 250 · 1h 400 · 2h 800 · 3h 1.000 · pernoite
2.000), o dono do produto rejeitou a fórmula. Três problemas, em ordem de gravidade:

1. **Ela coincidia por acidente.** Na parte LINEAR da tabela — 400/1h e 800/2h — o preço-hora dá
   exatamente os mesmos R$400. É por isso que a conta passou um ano parecendo certa: os únicos
   pacotes testados eram os que não a distinguiam da regra real.
2. **Ela divergia justamente onde o preço deixa de ser linear**, que é o desenho NORMAL de uma
   tabela (pacote maior, preço-hora menor — ADR-0004). Na 3h a R$1.000 o extra saía R$333; no
   pernoite a R$2.000, R$333 também. O MESMO ato custava menos para quem compra mais tempo, sem
   que ninguém tivesse decidido isso. O fetiche não é proporcional à duração: é um ato.
3. **O extra não acompanhava o desconto.** Pacote negociado para baixo (escada do ADR-0031,
   clampada pelo ADR-0037) com extra de tabela cheia produz um total que não existe em lugar
   nenhum — nem na tabela, nem na escada.

## Decisão

> **O extra por fetiche é o preço da linha de 1 HORA do mesmo programa, no patamar de desconto
> vigente.** Fixo em relação à duração do pacote.

Números canônicos ditados pelo dono do produto (Catarina, programa Normal, 1h = 400 de tabela /
300 no mínimo):

| Situação | Pacote | Extra | Total |
|---|---|---|---|
| 1h cheia, 1 fetiche | 400 | 400 | **800** |
| 1h cheia, 2 fetiches | 400 | 400+400 | **1.200** |
| 1h no mínimo, 1 fetiche | 300 | 300 | **600** |
| 2h cheia, 1 fetiche | 800 | 400 | **1.200** |
| 2h no mínimo, 1 fetiche | 600 | 300 | **900** |
| 3h cheia, 1 fetiche | 1.000 | 400 | **1.400** |
| Pernoite cheia, 1 fetiche | 2.000 | 400 | **2.400** |
| 30min, qualquer | 250 | — | **sem fetiche** |

- **Patamar é ESTÁGIO discreto da escada, não percentual do pacote.** São três: cheio (`preco` da
  linha de 1h), degrau (`degrau_de_desconto` dela) e piso (`piso_de_desconto` dela) — o mesmo
  clamp por `preco_minimo` do ADR-0037. Na 3h no piso o total é 900 + **300** = 1.200, e **não**
  900 + 360: o 0,9 que a linha de 3h sofreu (piso absoluto 900 sobre 1.000) é um fator do PACOTE,
  e aplicá-lo ao extra produziria R$360, que não é preço de nada. O extra é o valor da 1h naquele
  estágio, ponto.
- **Preço CADASTRADO continua vencendo** (`modelo_fetiches.preco >= PRECO_FETICHE_CADASTRADO_MINIMO`,
  revisão de 11/08/2026 do ADR-0030): cadastro explícito manda, é fixo e **não** acompanha o
  patamar — o operador digitou um valor, não uma escada. O sentinel `Decimal("1")` do painel
  legado continua significando "pago sem valor" e cai no derivado.
- ~~**`cobra_por_pessoa` (ADR-0035) é regime próprio e fica exatamente como estava**: são 2 pessoas,
  o pacote DOBRA, então o extra é o pacote inteiro. Não passa pela linha de 1h (funciona até para
  programa que não tem uma).~~ **Revogado no mesmo dia pelo ADR-0039**: composição passou a somar o
  MESMO extra descrito aqui — a linha de 1h do mesmo programa, no patamar vigente — e por isso
  passou a depender dela (o fail-closed abaixo alcança composição também). `cobra_por_pessoa`
  continua no catálogo, como classificação.
- **Sem linha de 1h para o programa em questão, não há extra derivado — `None`, fail-closed.** O
  extra É a uma hora; sem ela cadastrada não existe extra a cotar. O render OMITE a linha, o guard
  não legitima o total dela, o painel devolve 409 (`sem_linha_de_uma_hora_para_o_extra`) e o
  fechamento descarta o fetiche com warning. Inventar uma base a partir do pacote é precisamente o
  que este ADR remove.
- **Fetiche pago é de programa PRESENCIAL.** A **vídeo chamada** (único serviço remoto, ADR-0021)
  sai de todas as seções de extra — tabela de atos, "Por pessoa" e a nota de pacote curto —
  **independentemente da duração**. Exclusão ortogonal à da duração, e não redundante com ela: a
  chamada de 60min da Catarina (R$600, na proporção de R$10/min) tem `horas = 1`, passaria no
  filtro de duração e a IA leria "Vídeo chamada (1h) | R$1.000" — fetiche pago numa chamada de
  vídeo, produto que não existe. O predicado é o que a cauda já usava (`e_video_chamada`, por
  nome normalizado contendo "chamada"), movido de `nos/prepare_context.py` para `agente/persona.py`
  para virar site único de dois consumidores — o gate `<sem_video_chamada>` e o `<fetiches>` —
  sem dependência circular (`prepare_context` já importa o render daqui).
- **Pacote com menos de 1h não tem fetiche pago** (decisão do mesmo dia, ao subir a Catarina;
  `DURACAO_MINIMA_FETICHE_PAGO`). Vale nos DOIS regimes — é sobre a DURAÇÃO, não sobre a conta. A
  regra nasceu como defesa contra a fórmula antiga, que INVERTIA em duração fracionária
  (250 ÷ 0,5h = +R$500 sobre um pacote de R$250); sob a fórmula nova o absurdo aritmético some (o
  extra seria os mesmos R$400), mas a decisão fica de pé por produto: cobrar +R$400 sobre um
  pacote de R$250 é vender a meia hora como se fosse a hora. O caminho é o **upsell** — a conduta
  `pacote_curto` do `<fetiches>` confirma que ela faz o ato, diz "a partir de 1 hora" e cota a
  linha de 1h.

### Onde vive

`dominio/atendimentos/service.py` — site único, como antes:

- `extra_de_fetiche(linha_de_uma_hora, duracao_horas, *, patamar="cheio", preco_cadastrado=None)
  -> Decimal | None` resolve cadastro → derivado (o `preco_pacote` e o `cobra_por_pessoa` que esta
  linha tinha saíram com o ADR-0039, junto com o dobro que era o único consumidor deles);
- `calcular_preco_extra_fetiche(...)` (mesma assinatura, sem `preco_cadastrado`) é o derivado;
- `valor_no_patamar(preco, preco_minimo, patamar)` é o despacho entre os três estágios — consome
  `degrau_de_desconto`/`piso_de_desconto`, não recalcula nada;
- `linha_de_uma_hora(conn, modelo_id, programa_id)` lê a linha da 1h para os chamadores de banco.

Quatro chamadores, todos pelo site único: o render do `<fetiches>` (`agente/persona.py`), o
`_valores_legitimos` do `agente/nos/output_guard.py`, o `POST /atendimentos/{id}/fetiches` do
painel e o rastro do fechamento (`registrar_fetiches_do_fechamento`).

**A "assinatura congelada" prometida na revisão de 11/08 do ADR-0030 morre aqui, de propósito.** A
entrada mudou de natureza: o extra não depende mais da linha do PACOTE, e sim da linha de 1h do
programa + do patamar. Uma assinatura preservada teria deixado os quatro chamadores compilando com
a conta errada; o tipo novo obriga cada um a dizer de qual 1h está falando.

### O que a IA lê

O `<fetiches>` deixa de ter a coluna "Extra" por pacote (que só existia porque o extra variava com
a duração) e passa a `| Pacote | +1 fetiche | +2 fetiches |`, com o valor nomeado no cabeçalho:
*"Inversão: cada fetiche soma +R$400, o valor da sua 1h"*. **Os totais são pré-computados,
inclusive o de dois fetiches** — não negociável: há incidente real de produção com a bolha
"1200 (800+800)", erro aritmético do LLM. A IA copia, nunca soma. A coluna "Extra" volta apenas
quando a modelo tem programas com 1h de preços diferentes (Normal 400 e Completo 600), único caso
em que o extra varia de linha para linha.

O bloco por-modelo é estático (tabela cheia, pré-requisito do cache), então ele **diz a regra** do
patamar e manda pegar o número do turno — nunca manda calcular.

## Alternativas rejeitadas

- **Manter o preço-hora (ADR-0030).** Rejeitada pelo dono do produto: cobra menos pelo mesmo ato
  em pacote maior, e a coincidência em 1h/2h escondia isso.
- **Extra como fator do valor negociado** (`extra_cheio × valor_negociado ÷ preco_tabela`). É a
  leitura "percentual" de patamar, e produz números que não existem em tabela nenhuma — R$360 na
  3h da Catarina no piso. Rejeitada explicitamente na decisão.
- **Extra cadastrado obrigatório por fetiche.** Seria o mais simples de explicar, mas exigiria
  recadastrar todo o prod (9 vínculos com o sentinel) antes de qualquer venda voltar a cotar
  extra. O derivado é a rede; o cadastro continua vencendo quando existe.
- **Eleger um programa quando o pacote tem mais de um serviço** (o maior, o mais caro, o de maior
  duração). Qualquer escolha seria arbitrária e silenciosa. Fail-closed com erro nomeado.

## Consequências

**Positivas**
- O extra passa a ter uma definição que o operador consegue verificar sozinho, olhando a própria
  tabela ("é a minha 1h") — sem divisão nenhuma.
- Render, guard, painel e fechamento continuam saindo do mesmo site: mudar a conta muda os quatro
  juntos ou não muda nenhum.
- O guard passa a legitimar os totais nos três patamares e para 1 e 2 fetiches (800, 1.200, 700,
  1.050, 600, 900…). Sem isso, a fala CORRETA no meio da negociação — "600 amor, com a inversão",
  no piso da 1h — seria barrada como preço fantasma, que é exatamente o que o `<desconto>` manda
  fazer.

**Negativas / a acompanhar**
- **A exclusão da vídeo chamada vale no RENDER, não no domínio.** O `<fetiches>` nunca imprime a
  chamada, mas `extra_de_fetiche` não conhece o nome do programa: o painel, se alguém vincular um
  fetiche pago a um atendimento cujo serviço vendido é vídeo chamada, ainda calcula um extra, e o
  guard ainda legitimaria o total (direção aditiva). Levar o predicado ao domínio exigiria subir
  `e_video_chamada` para `core/` (`dominio/` não importa `barra.agente`) — vale se aparecer um
  caso real.
- **O preço sobe para quem vende pacote longo com fetiche.** No pernoite da Catarina o extra vai de
  R$333 para R$400. É a decisão, não um efeito colateral — mas é uma mudança de preço em prod.
- **Programa sem 1h cadastrada perde o extra derivado, em silêncio para o cliente.** A linha some
  do `<fetiches>` (a IA nunca lê um número inventado), mas o operador só descobre pelo 409 do
  painel ou pelo warning do fechamento. Cadastrar a 1h de todo programa vira pré-requisito
  operacional; vale um alerta no painel — fora do escopo desta mudança.
- **Pacote com mais de um serviço vendido deixou de ter extra derivado** (antes saía da soma
  dividida pelo MAX da duração). Fail-closed nomeado, mas é um caminho do painel que passou a
  recusar onde antes gravava.
- **O snapshot do painel/fechamento continua gravando no patamar CHEIO.** O extra acompanha o
  patamar na FALA (render + guard), mas quem materializa `atendimento_fetiches` não deriva o
  patamar do `valor_acordado` — o breakdown de um atendimento fechado com desconto não fecha a
  conta com o valor final. Já era assim antes deste ADR; fica registrado como pendência.
- **A escada vai mudar em seguida** (passará a depender de o encontro ser hoje ou não, frente
  separada). Como o extra CONSOME `degrau_de_desconto`/`piso_de_desconto` em vez de reimplementá-los,
  essa mudança chega ao extra sozinha — mas os números canônicos da tabela acima são deste regime
  de escada, e precisam ser reconferidos quando ele mudar.

---

## Emenda (11/08/2026, com o ADR-0040) — a fonte do patamar

O regime **não muda**: o extra continua descendo pela mesma escada do pacote, em patamar
**discreto** (`cheio`/`degrau`/`piso`), nunca por fator multiplicativo. Muda **de onde sai o
patamar**.

Até aqui, `patamar_da_mesa` vinha do contador de rodadas (`patamar_vigente(encontro, n)`). Isso
funcionava porque `n_contrapropostas` carregava dois fatos que coincidiam: **quantas rodadas foram
gastas** e **em que estágio o valor da mesa está**. O ADR-0040 separou os dois — a rodada passou a
poder ser consumida por um número que veio do CLIENTE. Na 2h da Catarina (800, mínimo 600, degrau
700), aceitar os 700 dele com `encontro="hoje"` esgota a escada, e `patamar_vigente(hoje, 1)`
responderia `piso`: o extra sairia cotado a 600 em cima de um pacote de 700, num patamar que ela
nunca ofereceu.

**Emenda:** `patamar_do_valor(preco, preco_minimo, valor_da_mesa) -> Patamar` (ao lado de
`valor_no_patamar`, mesmos sites únicos) = o patamar **mais raso** cujo valor é `<= valor_da_mesa`.
Em 800/600: `800 → cheio`, `750 → degrau`, `700 → degrau`, `650 → piso`, `600 → piso`. Discreto e
monotônico.

`patamar_da_mesa` passa a sair dele quando há valor na mesa, com `patamar_vigente` de fallback — e
com uma regra de precedência que é a parte não óbvia:

> **O valor só manda quando já saiu do preço cheio.** `valor_acordado` é gravado **já na cotação** e
> **não** acompanha a contraproposta que ela fez e ele ainda não aceitou. Mesa parada no preço cheio
> não significa "a negociação está no cheio", significa "a mesa não se moveu" — ali quem sabe é o
> contador. É o "nada regride": mesa intacta nunca puxa o patamar de volta para cima de um desconto
> que já foi ofertado.

A pendência do snapshot (o painel/fechamento ainda materializa `atendimento_fetiches` no patamar
cheio) segue aberta e não é tocada por esta emenda.
