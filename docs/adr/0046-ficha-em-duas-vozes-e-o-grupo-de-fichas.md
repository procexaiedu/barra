---
data: 2026-08-20
status: aceito
relaciona: ADR-0044 (revisa "a ficha é postada no grupo individual" e a porta da promoção), ADR-0047, ADR-0048, spec 0006, docs/dominio/fichas-do-telefonista.md
---

# ADR-0046 — A ficha em duas vozes, e onde cada uma é postada

## Contexto

O ADR-0044 modelou **um** card: a Ficha de agendamento, postada pelo telefonista no Grupo
financeiro individual de cada modelo participante, servindo ao mesmo tempo como (a) o aviso para a
modelo saber o que foi combinado e (b) a fonte estruturada do registro.

A reunião de alinhamento de 20/08/2026 (`reuniaoalinhamento.txt`) desenhou o card campo a campo com
o Rossi e depois o submeteu à Lula, que opera a rotina. A objeção dela derruba a premissa de
documento único:

> *"Pela nossa dinâmica da rotina, mesmo que pareça rápido agora, na hora que tem quatro clientes
> subindo, isso não vai ser tão fácil. (…) A gente manda de uma forma às vezes até um pouco
> resumida porque elas não entendem o que a gente fala."*

E, sobre a modelo:

> *"Elas não vão ler. Aí elas vão vir no grupo, vão vir no privado e vão perguntar as informações
> três, quatro vezes a mesma coisa. E olha que a gente resume."*

O Rossi converge: *"essa informação aqui — nome do anúncio, valor — é para o sistema. Para o
sistema está ótimo. Agora a gente pode criar uma prévia dessa informação que vai para a modelo."*

Os dois públicos querem coisas opostas. O sistema quer **tudo, rotulado e marcável**; a modelo quer
**o mínimo, já resolvido** — `Tipo: Hotel`, não `( ) Hotel`, porque *"pras meninas eu acho que esse
xzinho assim e tal não seria interessante"*.

Na mesma reunião mudaram também o conjunto de campos (site da plataforma, nome real da modelo
separado do perfil, data e hora, tipo de local, deslocamento em dois valores, cartão desmembrado em
débito/crédito/link) e o gesto de confirmação: o ✅ é do **telefonista**, e ele o dá **depois** de a
modelo avisar que recebeu — *"a modelo recebeu, mandou ok, 'recebi em dinheiro' (…) aí eu vou dar o
vezinho lá nas informações daquele atendimento"*.

## Decisão

**1. São três documentos, não um** (`docs/dominio/fichas-do-telefonista.md`):

- **Ficha de atendimento — individual**: completa, com `( )`, uma modelo.
- **Ficha de atendimento — grupo**: idem, com `Modelo 1..N` e `Valor de cada modelo`.
- **Comunicado da modelo**: resumido, sem `( )`, sem WhatsApp do cliente, sem site, sem nome real,
  sem valores de deslocamento e **sem data e hora** — é prévia, a hora ainda não se sabe.

**2. A ficha completa não é necessariamente postada no grupo da modelo.** A reunião abriu a
possibilidade de um **grupo de fichas** dedicado, com o comunicado indo ao grupo individual:
*"a gente monta um grupo só pra mandar essa ficha preenchida, e dentro do grupo individual a gente
manda essa mesma informação só que resumida"*. Não está decidido — *"a gente pode testar"* — mas o
código **não pode assumir** que a ficha chega no grupo daquela modelo.

Consequência concreta: o alvo closed-world do ADR-0044 (§3) deixa de ser escopado por grupo e passa
a ser escopado **por modelo**. A lista numerada de fichas abertas que a LLM enxerga no grupo
individual da Yasmin é a lista das fichas **da Yasmin**, venham elas de onde vierem. Isso preserva
o isolamento cross-modelo (nenhuma modelo vê ficha de outra) sem depender de onde o card caiu.

**3. A ficha completa não é escrita para a modelo, e por isso não é postada no grupo dela.**
Se o grupo de fichas existir, o grupo individual recebe só o comunicado. Se não existir, a ficha
completa vai para o grupo individual e o comunicado é dispensável. Os dois arranjos funcionam; o
sistema lê o formato que chegar.

**4. Campos novos na ficha completa**, todos ausentes da spec 0006: `Site`, `Nome da modelo` (real,
distinto do perfil), `Data`, `Hora`, `Tipo` de local (casa/hotel/motel/festa/passeio/jantar-almoço),
`Número/bloco/complemento`, `Valor do transporte` **e** `Valor antecipado` como dois valores
distintos, e `Pagamento` com **débito, crédito e link** no lugar de "cartão".

`Valor total` e `Valor desta modelo` — que o ADR-0044 chamou de "os dois campos novos a negociar
com o telefonista" — foram **aceitos sem ressalva** na reunião. A negociação está fechada.

**5. O ✅ do telefonista é a segunda porta do mesmo fato, não um estado anterior.** Ele o dá depois
que a modelo confirma o recebimento. Então a Venda registrada nasce por **qualquer um dos dois
gestos, o que vier primeiro** — a fala da modelo ("recebi, foi dinheiro") ou o ✅ do telefonista — e
o segundo não duplica, pela chave de conteúdo que o módulo já tem. A forma de pagamento vem de quem
a disser; se só veio o ✅, ela entra na cobrança consolidada da manhã como já entra hoje.

**6. Deslocamento tem dois valores, e eles não são o mesmo número.** `Valor antecipado` é o que o
cliente mandou (receita); `Valor do transporte` é o que o Uber custou (custo). Quando o Rossi paga
R$ 15 de um Uber curto sem cobrar do cliente, o antecipado é zero e o transporte não é. A diferença
entre os dois é margem ou prejuízo, e some se o sistema guardar um número só.

## Alternativas rejeitadas

- **Manter documento único e treinar as modelos a lê-lo.** Foi a hipótese do ADR-0044. A pessoa que
  opera a rotina disse que não sobrevive ao dia de pico, e o custo do erro é o que ela descreveu:
  a modelo pergunta no privado três vezes o que estava escrito.
- **Gerar o comunicado a partir da ficha, pela IA.** Elegante e provavelmente o destino final, mas
  exige que a ficha chegue antes e que a IA escreva no grupo da modelo com dado de agendamento —
  fala nova, sem recibo, num grupo onde hoje ela é quase muda. Fica para depois de o processo pegar.
- **Escopar o closed-world por grupo, como o ADR-0044 previa.** Quebra no instante em que a ficha
  for postada no grupo de fichas: a modelo paga no grupo dela e o alvo não está lá.
- **Um campo só de deslocamento.** Foi o desenho do ADR-0045 §5, e ele não distingue "o cliente
  mandou R$ 100 e o Uber custou R$ 60" de "o cliente não mandou nada e o Uber custou R$ 15".

## Consequências

- `docs/dominio/fichas-do-telefonista.md` passa a ser a fonte de verdade do template. O parser
  determinístico do ticket 06 é reescrito contra ele.
- O ADR-0044 fica **revisto** em dois pontos: §1 (a ficha vive no grupo da modelo) e a premissa de
  que só a modelo fecha o fato. O restante segue válido.
- O ADR-0045 §5 fica **revisto**: deslocamento guarda dois valores, não um.
- O roteamento do webhook precisa aceitar um JID novo de Grupo de fichas, do qual **não se deduz a
  modelo pelo grupo** — ela vem do campo `Nome da modelo` do card, pelo resolver closed-world.
- Há um campo do comunicado a confirmar com o Rossi: se `Valor do job` que a modelo vê é o dela ou
  o total. Enquanto não confirmado, vale o dela.
