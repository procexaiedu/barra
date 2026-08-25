# Agente financeiro v2 — Ficha de agendamento, Temporada e razão bilateral

> Spec local (sem issue), sucedendo a spec 0005 — que **não** é revogada: o que ela construiu
> continua vivo (ver "O que sobrevive"). Vocabulário: `docs/dominio/grupo-financeiro.md`.
> Decisões estruturais: **ADR-0044** (Ficha de agendamento; a Venda registrada nasce no pagamento)
> e **ADR-0045** (Temporada, comissão e razão bilateral — que revoga o "repasse/split ficam fora"
> do ADR-0043). Origem: reunião de 17/08/2026 com Rossi e Lula (`ata.txt` na raiz).
>
> **Refinada pela reunião de alinhamento de 20/08/2026** (`reuniaoalinhamento.txt`), que produziu
> **ADR-0046** (a ficha vira três documentos; onde cada um é postado), **ADR-0047** (o bolso é fato
> da venda, revogando o ADR-0045 §4) e **ADR-0048** (comissão do telefonista). O template está em
> `docs/dominio/fichas-do-telefonista.md`. As histórias **57–68** e o bloco "O que a reunião de
> 20/08 mudou" carregam o delta; a numeração 1–56 foi preservada porque os tickets a referenciam.

## Problem Statement

O Agente financeiro da spec 0005 está construído e é fiel ao mundo que ele observou: o export real
do Grupo financeiro da Yasmin (06–13/08/2026), em que a **gestora** anuncia em **texto livre** um
serviço **já realizado**, o agente registra com recibo corrigível, cobra a forma de pagamento dias
depois e concilia o comprovante.

Esse mundo acabou. Na reunião de 17/08 a operação Elite Baby mudou o próprio processo, e o software
passou a descrever um fluxo que ninguém mais executa:

- **Quem anuncia deixou de ser a modelo/gestora e passou a ser o telefonista**, num **card
  padronizado** (a Ficha de agendamento) postado no Grupo financeiro individual de cada modelo
  participante — e postado **antes** do serviço, porque o primeiro dono do card é a modelo, que
  precisa saber o que foi combinado ("ela tem que saber de tudo que foi combinado e tudo que foi
  pago com antecedência").
- **O combinado muda entre o post e o serviço.** O telefonista confirma quando o cliente confirma,
  altera hora/valor/desconto, ou marca que não rolou. Os gestos observados são quatro: reação emoji
  (✅/❌), repost da ficha alterada, resposta por quote e edição da mensagem. Hoje o webhook
  **descarta reação na borda** e trata edição no mesmo ramo da revogação — dois desses quatro
  gestos são invisíveis para o sistema.
- **Só a modelo fecha o fato**, quando avisa que recebeu e/ou manda o comprovante. Entre o card e
  o pagamento existe um objeto que já carrega todo o dado e ainda não é receita — e a spec 0005 não
  tem nome para ele. O caso que dói: o card do Igor traz R$ 700, 1h, local próprio; três horas
  depois a modelo escreve só "recebi, foi dinheiro". Sem a ficha guardada, a única saída é
  interrogar a modelo — exatamente a metralhadora de perguntas que o domínio proíbe.

Ao mesmo tempo, o gestor pediu na reunião o que o ADR-0043 e o glossário declararam fora do escopo:

- **Repasse e comissão dentro do sistema** — "já vai falando se falta ela pagar vocês ou falta
  vocês pagarem ela"; "a conta mais maliciosa é a comissão de todas as pessoas, porque não pode ter
  [erro]".
- **Temporada** — a modelo viaja para uma cidade e trabalha 7/10/14 dias; o pagamento é por
  temporada, não por atendimento, com **vale** adiantado no meio. O comando é literalmente "fecha
  pra mim a temporada da fulana, do dia tal ao dia tal".
- E **espécie não pode ficar fora da conta**: uma modelo que fez a temporada inteira em dinheiro
  apareceria com a casa devendo o líquido inteiro, quando ela já está com o bruto na mão.

Somam-se conceitos que a spec não tinha: **cartão** como forma (print da venda, que não é
comprovante Pix), **deslocamento** com rastro de quem recebeu e quem pagou o Uber, **festinha** em
que uma modelo recebe por todas, **origem do anúncio** (próprio × fake) como métrica pedida, e um
compromisso com prazo: fechar **agosto 01–17 de 8 modelos** a partir do histórico dos grupos —
histórico que, verificado no código, **não chega pelo webhook**.

E, três dias depois, a reunião de alinhamento de 20/08 desenhou o card campo a campo e o submeteu à
**Lula**, que opera a rotina. Ela derrubou a premissa de documento único — *"na hora que tem quatro
clientes subindo isso não vai ser tão fácil"*, *"elas não vão ler, aí vão vir no privado e perguntar
três, quatro vezes a mesma coisa, e olha que a gente resume"*. Na mesma conversa o Rossi negou o
pressuposto do parâmetro de bolso (*"varia, não existe só um padrão"*) e pediu, sem que ninguém
puxasse o assunto, a **comissão do telefonista**. O detalhe do template mudou junto: site da
plataforma, nome real da modelo separado do perfil, data e hora, tipo de local, deslocamento em dois
valores e cartão desmembrado em débito/crédito/link.

## Solution

Três camadas, na ordem em que dependem uma da outra.

**1. O razão.** Uma conta corrente única por modelo (ADR-0045), recortada por **Temporada**. Debita
o bruto de toda venda cujo dinheiro caiu na mão dela, as Cobranças da agência, os vales e o
deslocamento que ela recebeu e a casa pagou; credita a comissão de toda venda e cada transferência
dela para a casa. Saldo positivo = a casa deve a ela; negativo = ela deve à casa. É o que entrega a
promessa central da reunião — e **não depende de nenhuma mudança de comportamento humano**, porque
roda sobre o texto livre que o módulo já lê. É também o que permite fazer o backfill de agosto.

**2. A Ficha.** O card do telefonista vira entidade com estado (`aberta → confirmada → realizada |
cancelada`), gravada **calada** — o telefonista não pediu confirmação de nada. Ela é o alvo dos
quatro gestos e a fonte estruturada do registro: quando a modelo avisa o pagamento, a ficha é
promovida a Venda registrada herdando valor, cliente, duração, local, perfil e deslocamento. A
modelo só precisa dizer a forma e mandar o comprovante.

**3. As bordas do dinheiro.** Cartão, deslocamento com dois recebedores, festinha com
`recebido_por_modelo_id`, comprovante cliente → empresa, vale pela fala do grupo, fechar temporada
no painel, métrica fake × original, caixa dos telefonistas em leitura, export CSV.

O agente continua **silencioso por default**, continua **perguntando o mínimo**, continua
**registrando direto com recibo corrigível**, e continua **nunca travando a operação**. O que muda
é o que ele lê, o que ele guarda e a conta que ele fecha.

## User Stories

**A Ficha de agendamento**

1. Como telefonista, quero postar a ficha no formato padronizado, para não ter que repetir a
   informação de nenhum jeito diferente. ⚠️ REVISTA (20/08): são **três** documentos e a ficha
   completa pode não ir para o grupo da modelo — ver 57–59.
2. Como telefonista, quero que a IA não me responda nada quando eu posto a ficha, para o grupo não
   virar um eco de confirmações.
3. Como telefonista, quero marcar ✅ com uma reação na ficha quando o cliente confirma, porque é o
   gesto que eu já faço hoje.
4. Como telefonista, quero marcar ❌ com uma reação quando o cliente não vem, para a ficha não ficar
   sendo cobrada.
5. Como telefonista, quero poder tirar a reação que coloquei por engano, e que o estado da ficha
   volte, porque errar de emoji acontece.
6. Como telefonista, quero repostar a ficha com o valor alterado quando o cliente negocia desconto,
   e que a nova substitua a anterior em vez de virar um segundo atendimento.
7. Como telefonista, quero poder responder a ficha por quote ("mudou pra 800", "não veio"), porque
   às vezes é mais rápido que repostar.
8. Como telefonista, quero poder editar a própria mensagem da ficha e que o sistema releia, porque
   é o gesto mais natural quando eu erro de digitação.
9. Como telefonista, quero que a ficha de uma festinha com quatro modelos vá para o grupo de cada
   uma com o valor dela e o valor total, para cada uma saber o que é dela sem ver a conta da outra.
10. Como telefonista, quero preencher o WhatsApp do cliente só quando for videochamada, porque nos
    outros casos a modelo não tem acesso ao número do cliente.
11. Como telefonista, quero que a IA continue me entendendo se eu esquecer o card e escrever solto
    ("atendimento do Igor 700 1h"), para o sistema não ficar mudo no dia em que eu tiver pressa.

**O pagamento e o registro**

12. Como modelo, quero avisar só "recebi, foi dinheiro" e ter a venda registrada com todos os dados
    da ficha, para não repetir o que o telefonista já digitou.
13. Como modelo, quero mandar o comprovante do Pix e ter a venda fechada sozinha, sem ninguém
    conferir no olho.
14. Como modelo, quero mandar o print da venda no cartão e que ele valha como prova de pagamento,
    porque cartão não gera comprovante Pix.
15. Como modelo, quero responder por áudio e ser entendida, porque é assim que eu uso o WhatsApp.
16. Como modelo, quero que venda paga em dinheiro não me gere cobrança de comprovante, porque
    espécie não tem comprovante.
17. Como modelo, quero receber um recibo curto quando algo for lançado, para conferir de relance e
    corrigir respondendo a mensagem.
18. Como modelo, quero corrigir o valor por quote no recibo e ver o de→para, para saber que a
    correção pegou.
19. Como gestora, quero que um comprovante que não casa com ficha nenhuma fique retido com **uma**
    pergunta, para o dinheiro não sumir e a modelo não ser metralhada.
20. Como gestora, quero que a mesma foto de comprovante reenviada não feche duas fichas, para o
    extrato não bater por acidente.
21. Como gestora, quero que apagar a mensagem da ficha ou do comprovante desfaça o que ela causou,
    porque apagar-e-repostar é como a gente corrige.

**O razão e a Temporada**

22. Como operador, quero saber a qualquer momento se a modelo me deve ou eu devo a ela, num número
    só com sinal, para não fazer a conta de cabeça.
23. Como operador, quero que a venda paga no Pix dela debite o bruto na conta dela, porque o
    dinheiro está com ela.
24. Como operador, quero que a venda paga no Pix da empresa não debite nada dela, porque o dinheiro
    nunca passou pela mão dela.
25. Como operador, quero que venda em dinheiro debite igual, para o saldo não mentir com a modelo
    que fez tudo em espécie.
26. Como operador, quero que cada transferência dela credite o valor exato transferido, para o
    regime (valor inteiro × só a parte da casa) não precisar ser configurado em lugar nenhum.
27. Como operador, quero que a comissão dela seja calculada pelo percentual do cadastro e
    **congelada na venda**, para mudar a confiança numa modelo não reescrever temporada passada.
28. ~~Como operador, quero definir por modelo se ela recebe no Pix dela ou no da empresa.~~
    ⚠️ **RETIRADA (ADR-0047)**: o Rossi negou o pressuposto — *"varia, não existe só um padrão"*.
    Substituída por 62.
29. Como operador, quero que o comprovante determine o bolso quando o pagador for o cliente e o
    destino for a casa, para o razão não depender de ninguém ter dito. ⚠️ REVISTA (ADR-0047): era
    "desmentir um cadastro"; virou a linha principal da tabela de evidência.
30. Como operador, quero abrir uma Temporada para a modelo com cidade e datas, para saber de que
    período estou falando quando pago.
31. Como operador, quero fechar a temporada pelo painel e registrar o pagamento, para o gesto que
    move dinheiro não depender de interpretar uma frase num grupo onde a modelo está.
32. Como operador, quero ver as pendências abertas da temporada antes de fechar, para decidir se
    fecho assim mesmo.
33. Como operador, quero que um comprovante que chega depois de a temporada estar paga recalcule o
    saldo e me mostre a diferença que falta pagar, em vez de ser rejeitado ou ignorado.
34. Como operador, quero lançar um vale adiantado no painel e vê-lo descontado no fechamento.
35. Como operador, quero que o vale dito no grupo ("adiantei 500 pra ela") também seja lançado, com
    recibo corrigível, porque é onde eu falo isso na prática.
36. Como operador, quero que a Cobrança da agência (anúncio/site) continue debitando a modelo e
    sendo quitada pelo comprovante dela, sem nunca abater venda.

**Festinha e deslocamento**

37. Como operador, quero que a venda de uma festinha vire uma linha por modelo, cada uma no valor
    dela, para o faturamento individual de cada uma ficar certo.
38. Como operador, quero registrar que **uma** modelo recebeu o dinheiro de todas, para o débito
    ficar com quem está com o dinheiro e as outras não serem cobradas do que não receberam.
39. Como modelo que não recebeu, quero não ser cobrada de comprovante, porque o dinheiro foi para a
    minha amiga.
40. Como operador, quero registrar quanto foi cobrado do cliente pelo Uber, quem recebeu esse
    dinheiro e quem pagou o Uber, para R$ 100 não sumirem do caixa.
41. Como operador, quero que o deslocamento nunca gere comissão, porque é reembolso de custo e não
    serviço.

**Painel e métrica**

42. Como operador, quero ver em `/financeiro` a lista de temporadas com o saldo de cada modelo,
    para ter o "financeiro dos telefonistas" num lugar só.
43. Como operador, quero ver na ficha da modelo o extrato dela e o saldo, para ter o "financeiro
    individual" que eu confiro com ela.
44. Como operador, quero ver a conferência do que foi pix, dinheiro e cartão, porque é a divisão
    que eu uso.
45. Como operador, quero saber quanto o anúncio fake faturou e quanto o anúncio próprio faturou,
    para decidir onde investir.
46. Como operador, quero exportar a temporada em planilha, para bater com o meu controle no fim do
    mês.
47. Como operador, quero ver as fichas previstas e as que ficaram sem desfecho, para saber o que
    está aberto sem entrar no grupo.

**Rotina, silêncio e backfill**

48. Como modelo, quero não ser metralhada de perguntas em tempo real — uma cobrança consolidada por
    dia basta — para o grupo continuar habitável.
49. Como gestora, quero que a rotina da manhã pergunte se a ficha de ontem rolou, para ficha
    esquecida não virar dinheiro perdido.
50. Como gestora, quero que a rotina fique calada quando não há nada acionável, porque "bom dia,
    nada a relatar" diário é o que faz a operação desligar o agente.
51. Como operador, quero o financeiro de agosto 01–17 das oito modelos calculado a partir do
    histórico dos grupos, para começar a temporada já com o controle na mão.
52. Como desenvolvedor, quero que o backfill rode pela mesma porta da produção, para o que foi
    importado ser exatamente o que teria sido registrado ao vivo.
53. Como desenvolvedor, quero que rodar o backfill duas vezes não duplique nada, porque vou rodar
    de novo quando achar um bug.
54. Como desenvolvedor, quero uma porta única para todo evento de grupo, para o comportamento
    testado ser o comportamento de produção.
55. Como desenvolvedor, quero que mensagem de grupo não cadastrado continue sendo ignorada com log,
    porque o número é compartilhado com o myEYE.
56. Como desenvolvedor, quero que reação continue sendo descartada para o agente de venda, porque
    lá ela é ruído.

**O que a reunião de 20/08 acrescentou**

57. Como telefonista, quero mandar para a modelo um **comunicado curto** — cliente, perfil, origem,
    duração, tipo e endereço do local, valor e forma — sem parênteses para marcar, porque no dia de
    pico ela não lê ficha completa e volta perguntando no privado.
58. Como telefonista, quero que a ficha completa possa ser postada num **grupo de fichas** só nosso,
    e que o sistema entenda igual, para eu poder testar o arranjo sem quebrar o registro.
59. Como modelo, quero que a ficha que chega no meu grupo não traga o número do cliente nem a conta
    da festinha inteira, porque não é informação minha.
60. Como telefonista, quero dar ✅ na ficha **depois** que a modelo me confirma que recebeu, e que
    isso já registre a venda, porque é o gesto que fecha o atendimento do meu lado.
61. Como operador, quero que o ✅ e a fala da modelo não gerem duas vendas quando os dois acontecem,
    porque acontecem quase sempre.
62. Como operador, quero que o sistema descubra em que bolso o dinheiro caiu **daquela venda** — pelo
    comprovante, pela fala ou por ser dinheiro — em vez de assumir um padrão da modelo que não
    existe.
63. Como operador, quero que a venda cujo bolso ninguém disse entre na cobrança consolidada da manhã
    junto com a forma que já é cobrada, sem virar pergunta nova nem travar nada.
64. Como operador, quero cadastrar meus telefonistas com nome e percentual de comissão, para poder
    mexer no número de cada um conforme a experiência.
65. Como operador, quero a comissão do telefonista calculada sobre o **faturamento bruto** que ele
    vendeu, porque é assim que eu pago.
66. Como operador, quero que o deslocamento guarde **o que o cliente antecipou** e **o que o
    transporte custou** como dois números, porque o Uber curto que eu pago do meu bolso tem custo e
    não tem antecipado.
67. Como operador, quero registrar débito, crédito e link como formas distintas de cartão, porque
    são operações diferentes e eu concilio cada uma no seu extrato.
68. Como operador, quero saber por qual **site** a venda entrou (Barra Vips, GSEX, Viva Local,
    Garota com Local…), não só se o anúncio era próprio ou fake, para decidir onde investir.

## Implementation Decisions

**A porta única, generalizada.** Hoje o módulo tem duas entradas
(`processar_mensagem_do_grupo`, `processar_delecao_do_grupo`). Reação e edição têm a mesma forma da
deleção — **gesto sobre uma mensagem que já existe**, não uma mensagem — então as quatro se
unificam numa entrada só que recebe um evento de união e devolve o mesmo resultado. As assinaturas
antigas viram wrappers finos enquanto houver chamador. Vai de 2 costuras para 1, e a principal fica
mais alta do que hoje. Decisão validada com o dev.

**A Ficha de agendamento** é entidade com estado (`aberta → confirmada → realizada | cancelada`),
com a mensagem-fonte como origem, os participantes quando há mais de uma modelo, e os campos do
card. Gravada calada. É o alvo closed-world: a lista de fichas abertas **daquela modelo** é finita e
numerada, e a LLM aponta por **índice**, nunca por id — o mesmo contrato que o leitor já usa. Vale
para o pagamento, para o ✅/❌ e para a alteração.

O escopo é **por modelo, não por grupo** (ADR-0046). A ficha completa pode ser postada num **Grupo
de fichas** dedicado em vez do grupo individual — o arranjo não está decidido, e o código não pode
assumir que o card caiu no grupo de quem vai pagar. Quando ele cai no grupo de fichas, a modelo vem
do campo `Nome da modelo` pelo resolver closed-world, não do JID.

**O parser do card é determinístico**, por rótulos, **sem LLM**, e tem precedência sobre o texto
livre. Não casando, cai no leitor de anúncio que já existe. O template é
`docs/dominio/fichas-do-telefonista.md` (ADR-0046) e são **três** formatos a reconhecer: ficha
individual, ficha de grupo (`Modelo 1..N`) e **comunicado da modelo** — este sem `( )`, com o valor
já escrito. `Valor total` separado de `Valor desta modelo` e `Origem: ( ) Próprio ( ) Fake` foram
**aceitos sem ressalva** na reunião de 20/08; a negociação com o telefonista está fechada.

Campos que a primeira versão desta spec não previa: `Site` (a plataforma — Barra Vips, GSEX, Viva
Local, Garota com Local, e também Instagram/Tinder), `Nome da modelo` (o nome **real**, distinto do
perfil do anúncio), `Data` e `Hora`, `Tipo` de local
(casa/hotel/motel/festa/passeio/jantar-almoço) além do local próprio × saída,
`Número/bloco/complemento` do endereço, `Valor do transporte` **e** `Valor antecipado` como dois
números, e o pagamento com **débito, crédito e link** no lugar de "cartão".

**A Venda registrada nasce no pagamento**, herdando da ficha, por **duas portas equivalentes**: a
fala da modelo ("recebi, foi dinheiro") ou o **✅ do telefonista**, que ele dá depois de ela
confirmar. O que vier primeiro promove; o segundo não duplica, pela chave de conteúdo que já existe.
`ficha_id` é opcional: texto livre e backfill continuam produzindo venda sem ficha.
`forma_pagamento` passa a aceitar **dinheiro, pix, débito, crédito e link**.

**O razão** é uma função **pura** sobre lançamentos, sem I/O — o mesmo desenho das fórmulas de
repasse que já existem no Módulo Financeiro. A regra:

```
débito  ← bruto da venda cujo dinheiro caiu na mão dela (pix dela | dinheiro | cartão dela)
débito  ← Cobrança da agência
débito  ← vale adiantado
débito  ← deslocamento recebido por ela e pago pela casa
crédito ← comissão = percentual_repasse_snapshot × bruto   (de TODA venda)
crédito ← cada transferência dela para a casa (valor do comprovante)

saldo > 0 → a casa deve a ela ;  saldo < 0 → ela deve à casa
```

Verificado contra o caso real (export 12/08): `600 pix + 600 pix`, comprovante de R$ 1.200,00 →
débito 1.200, comissão 600, transferido 1.200 → **saldo +600**. Os três espelhos fecham: não
transferiu → −600; tudo dinheiro → −600; Pix da empresa → +600.

**Em que bolso o dinheiro caiu é fato da venda, não cadastro da modelo** (ADR-0047 — revoga o
ADR-0045 §4). Não existe `recebe_no_proprio_pix`: o Rossi negou o pressuposto de estabilidade
(*"varia, não existe só um padrão"*). A precedência de evidência é: comprovante dela → casa (bolso
dela, e a transferência credita) > comprovante do cliente → casa (empresa) > fala explícita >
`forma = dinheiro` (sempre dela) > **não dito**.

"Não dito" é estado legítimo: entra na cobrança consolidada da manhã ao lado da forma de pagamento
que já é cobrada — mesmo canal, sem pergunta nova. O default do razão enquanto isso é **dela**,
porque é o que o dono descreve como certo (*"o certo vai ser ela receber e enviar pra gente"*) e
porque errar para esse lado é conservador: o saldo mostra a modelo devendo, alguém confere e o
comprovante corrige. O erro oposto esconde dinheiro na mão dela e ninguém procura.

**A comissão reusa o percentual de repasse do cadastro da modelo**, que já existe no domínio, com
snapshot na venda. 50% é default de cadastro, não constante de código — e a reunião de 20/08
confirmou que **as quatro modelos ativas são 50% por regra**. **Taxa de cartão não é descontada** —
bruto = valor do card (decisão do dono do produto).

**A comissão do telefonista** (ADR-0048) é conta separada, de outra pessoa: percentual **por
vendedor** (faixa operacional 1–10%, referência 7%), sobre o **faturamento bruto vendido**, sem
deslocamento na base, **por projeção e sem snapshot** — o padrão do Módulo Financeiro. Substitui o
percentual por nível do ADR-0012, que sobrevive como default de cadastro. Quem é o telefonista da
venda vem do **autor da mensagem** (`vendedores.whatsapp_jid`); autor desconhecido → sem vendedor →
sem comissão, nunca chute. O extrato da modelo **não** mostra essa comissão: ela lê o grupo dela.

**O deslocamento é lançamento próprio** ligado à venda, com **dois valores** (ADR-0046): o
`Valor antecipado` que o cliente mandou e o `Valor do transporte` que o Uber custou — mais quem
recebeu e quem pagou. Com dois valores, os quatro casos deixam de ser tabela e viram uma conta:
`efeito no razão dela = antecipado recebido por ela − transporte pago por ela`. Ela recebe R$ 100 e
a casa paga o Uber → débito 100; ela recebe R$ 100 e paga R$ 60 → débito 40; nada antecipado e ela
paga R$ 15 → **crédito** 15. O último caso é o que um número só não sabia representar, e é o que o
Rossi descreve pagando do próprio bolso. Nunca entra na base de comissão de ninguém.

**Numa venda com N modelos, quem carrega o débito** é indicado por um campo de "recebido por",
default = a própria modelo. Na festinha em que uma recebe por todas, as N vendas apontam para ela.
O repasse **entre modelos** fica fora do sistema.

**A Temporada** é entidade (modelo, cidade, início, fim, estado) e **não congela o cálculo** — o
saldo segue derivado, preservando o princípio do fechamento atual ("não existe tabela de
fechamento"). O que ela guarda como fato são os **pagamentos feitos**. Comprovante atrasado
recalcula o saldo; a diferença contra o já pago aparece como "falta pagar R$ X". Não existe
reabertura, porque nunca houve congelamento.

**Fechar a temporada é ação do painel**, nunca frase no grupo — move dinheiro, e a modelo está no
grupo. O **vale** entra por duas portas: painel e fala no grupo, esta com recibo corrigível.

**O Fechamento postado no grupo** continua sendo leitura pura e mantém as três colunas como
recorte; o número final passa a ser o saldo com sinal. As divergências que já existem
(venda comprovada a menor, Pix órfão) continuam válidas e continuam virando pergunta, nunca trava.

**O webhook** passa a entregar reação e a distinguir edição de revogação **apenas para JIDs de
Grupo financeiro**. O agente de venda continua descartando reação na borda. A grafia real do evento
da EvoGo precisa ser capturada antes de qualquer código — não é adivinhável.

**O ✅ mudou de significado entre as duas reuniões**, e com ele um estado da máquina. Em 17/08 ele
parecia dizer "o cliente confirmou"; em 20/08 ficou claro que vem **depois do pagamento**
(*"depois que ela mandar o OK, o selo"*). Ele promove a venda — e, com isso, **nenhum gesto produz
mais o estado `confirmada`**. Ele sobrevive por uma porta só, a confirmação em texto por quote
("confirmado"). Fica assim de propósito: se ninguém usar essa porta em produção, o estado some e a
máquina vira `aberta → realizada | cancelada`.

**O comunicado da modelo vincula, nunca cria uma segunda ficha.** Se a ficha completa for para um
Grupo de fichas, a modelo vai citar **o comunicado** ao pagar, e o alvo está em outro grupo. O
casamento é por `modelo + cliente + valor` entre as fichas abertas dela — o comunicado não tem data,
então a chave de conteúdo do módulo não serve inteira. Não casando, o comunicado **cria** a ficha:
é o arranjo sem Grupo de fichas, e é o que acontece quando o telefonista pula a ficha completa.

**O backfill roda pelo replay do export `.zip`**, que já existe e chama a porta única; falta só o
modo "gravar de verdade" (hoje é avaliação), idempotente pela chave de conteúdo que já existe.
⚠️ O que ele importa entra como **histórico**: soma no saldo e **não** entra em cobrança. Importar
agosto 01–17 de oito grupos gera centenas de pendências legítimas, e a rotina consolidada as cobraria
nos grupos reais, com as modelos dentro, sobre um mês vencido. É o maior risco do backfill, e é
operacional, não técnico. Pelo mesmo motivo as vendas importadas nascem **sem vendedor** — em agosto
quem anunciava era a gestora — e não geram comissão de telefonista retroativa.
⚠️ Adicionar a IA ao grupo "com histórico" **não entrega o backfill**: o evento de sincronização de
histórico morre na borda do webhook e o cliente da Evolution não tem endpoint de busca de mensagens
antigas.

**Painel**: `/financeiro` ganha Temporadas com o saldo de cada modelo (= o "financeiro dos
telefonistas" que o gestor nomeou), e a ficha da modelo ganha a aba com o extrato dela (= o
"financeiro individual"). **Não toca em `/atendimentos`**, para a IA de venda entrar em produção
sem colidir. Export CSV/XLSX substitui a planilha-espelho prometida.

**O que sobrevive intacto** da spec 0005, e é a maior parte: o seam e a persistência de mensagens
com dedup de entrega, o roteamento por JID, a transcrição de áudio, a tria barata do social, o
resolver closed-world de nomes, o rateio de N modelos, o dedup por conteúdo (a chave já é por
modelo, então o card postado em N grupos já produz N linhas corretamente), o OCR de comprovante e
suas cinco classes, o leitor LLM por índice com a allowlist atrás, a correção por quote, a anulação
por deleção, a Cobrança da agência, os dados cadastrais oportunistas, e a rotina consolidada da
manhã. **Nenhum módulo é descartado.**

**Faseamento**, por dependência e por risco:

- **Fase 0 — razão e backfill.** Não depende de mudança de comportamento humano nem de evento novo
  de webhook: roda sobre o texto livre já lido. Entrega o compromisso de agosto e a promessa
  central da reunião.
- **Fase 1 — a Ficha.** Parser do card, entidade com estado, os quatro gestos, promoção a venda,
  cobrança de ficha sem desfecho.
- **Fase 2 — as bordas do dinheiro.** Deslocamento, cartão, festinha, comprovante cliente →
  empresa, vale pela fala, fechar temporada no painel.
- **Fase 3 — métricas e espelho.** Fake × original, site da plataforma, caixa dos telefonistas em
  leitura, export.

A **comissão do telefonista** (ADR-0048) atravessa as fases: o cadastro e o percentual são de
painel e podem entrar já; o cálculo depende da Venda registrada, então acompanha a Fase 0.

Os pedidos de painel que a reunião de 20/08 trouxe e que **não são deste módulo** — agenda de
temporada, etiqueta A/B/C de cliente, tarefas, renomear Atendimentos para Jobs, histórico de
conversa no cadastro do cliente, gateway de pagamento próprio — estão em
`docs/produto/backlog-painel-20260820.md`. Não estão perdidos e não estão nesta spec.

## Testing Decisions

**Bom teste aqui é comportamento pela porta única**: entra o evento cru do grupo (na grafia real do
export), saem os efeitos observáveis — fichas, linhas de Venda registrada, lançamentos do razão,
pendências, resposta ou silêncio do agente. **Não testar nós internos**: foi o desenho que induziu
quatro bugs falsos no agente de venda, e é a razão de a porta existir.

**O razão é a exceção, e por bem**: é função pura, então ganha uma tabela de casos sem banco —
mais rápida, mais legível e onde os quatro cenários de sinal (transferiu tudo, não transferiu, tudo
dinheiro, Pix da empresa) ficam lado a lado. O caso do export de 12/08 (600+600 contra o
comprovante de R$ 1.200,00 → saldo +600) é o teste de aceitação. Prior art: as fórmulas de repasse
e comissão do Módulo Financeiro já são funções puras testadas assim.

**Fixtures da realidade**: os casos saem do export real e dos **três** templates
(`docs/dominio/fichas-do-telefonista.md`), incluindo as formas degradadas que a operação vai
produzir — campo vazio, X fora do parêntese, card sem a lista de modelos numa festinha, ficha
repostada com um único campo alterado, reação removida, edição que muda o valor depois de a venda já
existir, e o **comunicado da modelo** sendo confundido com a ficha completa (ele não tem `( )` e não
tem `Valor total` — é isso que os separa).

**Dois casos novos que só a segunda porta cria**: ✅ do telefonista antes da fala da modelo, e fala
da modelo antes do ✅. Nos dois a venda tem que existir **uma vez** ao final. É teste de
idempotência, e é onde o bug vai estar.

**Reação e edição precisam de payload real capturado antes do código.** A grafia do evento da EvoGo
não é adivinhável, e o histórico do projeto tem precedente de contrato errado falhando calado.

**Módulos testados**: a porta única generalizada (o grosso), o parser do card (determinístico, fácil
e barato de cobrir), o razão (puro), a promoção ficha → venda, o snapshot de bolso e de percentual,
o motor de temporada com pagamento atrasado, a rota de fechar temporada, e o modo gravação do
replay (rodar duas vezes não duplica).

**Prior art**: testes `needs_db` com base de teste e rollback para o que toca banco; conexão falsa
para o unitário; o cron testado como os workers de relógio existentes; a idempotência testada como
a do dedup do comando de grupo. Rodar `needs_db` isolado do resto — a suíte já tem histórico de
lock quando as duas coisas dividem a mesma base.

## Out of Scope

- **Repasse entre modelos** (a que recebeu por todas acertando com as outras). O sistema fecha com
  cada uma; a divisão entre elas é da operação.
- **Google Sheets sincronizado.** Export de planilha primeiro; integração ao vivo só se o gestor
  ainda pedir depois de usar.
- **Grupo central das modelos.** Só tem recado e conversa social, e a ata manda o dado ir para o
  individual.
- **Escrita no grupo do caixa dos telefonistas.** Ele entra em **leitura** apenas.
- **Taxa de cartão descontada do bruto** (decisão do dono do produto).
- **Criação de Cliente ou Atendimento** a partir do grupo. O ADR-0043 continua valendo nesse ponto,
  e os três motivos dele seguem intactos — inclusive o WhatsApp do cliente, que o card só preenche
  em videochamada.
- **Precedência entre as duas fontes de receita** quando a IA de venda entrar em produção — decisão
  futura própria, como o ADR-0043 já previa.
- **Ideias soltas registradas na reunião e fora desta rodada**: espelho de WhatsApp com etiquetas
  estilo CRM, selo de cliente premium/recorrente, localização da modelo por aplicativo, automação de
  compra de passagem, preenchimento de cadastro da modelo por foto do RG.
- **Tasks no DevContext** para este módulo (decisão explícita do dev, mantida da spec 0005).
- **Tudo que a reunião de 20/08 pediu para o painel fora do financeiro** — agenda de temporada,
  etiqueta A/B/C de cliente, módulo de tarefas espelhando o Google Tasks, renomear Atendimentos para
  "Jobs", endereço do cliente em campos separados, histórico/resumo da conversa no cadastro do
  cliente, renomear a marca, gateway de pagamento próprio com QR Code no WhatsApp, e o resumo da
  conversa enviado à modelo antes do atendimento. Registrados em
  `docs/produto/backlog-painel-20260820.md`, com prioridade a decidir.

## Further Notes

- Ordem de leitura para quem pega isto do zero: `docs/dominio/grupo-financeiro.md` (vocabulário,
  já atualizado com as marcas ⚠️ REVISTO / ⚠️ REVOGADO) → ADR-0043 (por que a entidade é própria) →
  **ADR-0044** e **ADR-0045** → esta spec → spec 0005 (para saber o que já está construído).
- **Estado das pendências do dono do produto** depois de 20/08:
  - ✅ **Resolvida**: o telefonista aceita os campos novos do template — a ficha foi desenhada campo
    a campo com o Rossi e validada pela Lula.
  - ✅ **Resolvida**: as quatro modelos ativas são **50% por regra**, e o anúncio é sempre 50% pago
    pela modelo (na hora ou descontado na temporada).
  - ✅ **Resolvida**: `Data` e `Hora` entram na ficha.
  - ✅ **Dissolvida**: "em qual Pix cada modelo recebe" deixou de ser pergunta ao virar fato da venda
    (ADR-0047).
  - ⏳ **Aberta**: quanto do razão a IA expõe **no grupo** — o fechamento postado passa a poder
    conter comissão, e a modelo lê.
  - ⏳ **Aberta**: o cadastro que falta — cidade e datas da temporada, telefone particular da modelo
    (distinto do número do anúncio) e a chave Pix dela.
  - ⏳ **Aberta**: se o `Valor do job` do comunicado é o valor dela ou o total (a fala foi ambígua).
  - ⏳ **Aberta**: se a ficha completa vai para um **Grupo de fichas** dedicado ou continua no grupo
    individual. O código suporta os dois; a operação decide testando.
- **Ações operacionais com prazo**: (a) pedir ao Rossi o export `.zip` dos oito grupos, e avisá-lo
  de que o esforço de remover e readicionar a IA "com histórico" não entrega o backfill;
  (b) distribuir `docs/dominio/fichas-do-telefonista.md` aos telefonistas para começarem a usar já —
  *"pra ele já se acostumar, pra hora que o sistema estiver no ar"*; (c) mandar ao Rossi os slides da
  apresentação, que ele pediu na reunião.
- Risco a observar no piloto: o telefonista abandonar o card sob pressão. O fallback de texto livre
  existe exatamente por isso, e a métrica de quantas fichas chegaram pelo card × pelo texto livre
  diz se o processo pegou.
