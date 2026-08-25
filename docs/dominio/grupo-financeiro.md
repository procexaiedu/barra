# Domínio — Grupo financeiro e Agente financeiro

Verbetes do módulo de ingestão financeira por grupo (sessão de domain modeling de 13/08/2026).
São termos que a **IA conversacional de venda não usa** — vivem no grupo interno de finanças de
cada modelo e no Módulo Financeiro do painel. **Mesma regra de precedência:** onde divergir de um
ADR não-superseded, o ADR vence. Decisões estruturais: ADR-0043 (a entidade), **ADR-0044** (a
Ficha de agendamento e a venda que nasce no pagamento), **ADR-0045** (Temporada, comissão e o
razão bilateral), **ADR-0046** (a ficha em duas vozes), **ADR-0047** (o bolso é fato da venda) e
**ADR-0048** (comissão do telefonista).

> **Atenção — reunião de 17/08/2026.** O processo da operação mudou: quem anuncia passou a ser o
> **telefonista**, num card padronizado postado **antes** do serviço, e o repasse entrou no
> sistema. Os verbetes abaixo marcados com ⚠️ REVISTO descrevem o mundo novo; onde este arquivo
> ainda descrever o mundo de 13/08, os ADRs 0044/0045 vencem.

> **Atenção — alinhamento de 20/08/2026.** O card virou **três** documentos
> (`docs/dominio/fichas-do-telefonista.md`), o **bolso deixou de ser cadastro da modelo**, o
> deslocamento passou a ter **dois** valores, "cartão" virou **débito/crédito/link** e entrou a
> **Comissão do telefonista**. ADRs 0046/0047/0048.

> Fonte de comportamento: o agente se baseia **nas mensagens reais do grupo financeiro** (export
> de referência: grupo "Modelo Yasmin Ruiva/financeiro"). O myEYE serviu só de referência de
> funcionamento (rascunho → pergunta mínima → recibo), não de espelho de fluxo.

## O grupo e o agente

**Grupo financeiro**:
Grupo de WhatsApp **por modelo** com a modelo, os **gestores** (Dani, Parcerias, FEH — papel, não
cadastro) e o **Agente financeiro**. É onde a operação anuncia vendas realizadas, cobra forma de
pagamento, posta **Cobrança da agência** e recebe **Comprovante de transferência**. Grupo social e
vivo: tem conversa, sticker e mídia que não são dado. Vínculo grupo↔modelo é cadastro
(closed-world); mensagem em grupo não cadastrado é ignorada.
_Avoid_: confundir com a **Coordenação por modelo** (grupo de 2 — número da modelo + Fernando —
onde a IA de venda envia cards); confundir com a **Conversa cliente**; tratar tudo que chega como
dado a registrar.

**Agente financeiro**:
A IA ingestora que participa do Grupo financeiro com **número próprio da ProceX** (identidade
separada, o mesmo número em todos os grupos). Postura: **ingestão silenciosa com pergunta mínima**
— grava calado o que está completo, pergunta só o que falta para o mínimo do registro, e emite
**recibo** curto ao lançar ("✅ Registrei: … — corrige aí se algo estiver errado"). Lança **direto**
quando o mínimo está completo (sem "posso lançar?": quem afirmou o fato é o humano do grupo; o
recibo é a porta de correção). Ingere de **qualquer participante**, texto ou **áudio transcrito**.
Substitui o papel de secretaria do gestor: é ele quem cobra "foi pix ou dinheiro?", pede
comprovante e faz o **Fechamento**. Atualiza **Dados cadastrais da modelo** (torre/apto, chaves)
de forma **oportunista e calada** — nunca sai perguntando cadastro. Nunca trava a operação:
divergência vira pergunta no grupo e flag no painel.
_Avoid_: vender, cotar ou falar com cliente (não há cliente no grupo); confirmação em 2 tempos por
venda (fricção); responder mensagem social; perguntar cadastro proativamente; reter registro por
falta de dado opcional.

## As entidades

**Venda registrada**:
Registro de um **serviço já realizado**, anunciado no Grupo financeiro em texto livre
("Atendimento no nosso local / Cliente Gabriel / Perfil bianca/yasmin / 700 1h"). Entidade
**própria**, distinta do **Atendimento** (ciclo comercial da IA de venda) — ver ADR-0043. Mínimo
para registrar: **modelo + valor + data** (data default = dia da mensagem); local, duração,
cliente e forma de pagamento entram se ditos. O **cliente é texto livre** — não cria linha em
`clientes` (Cliente = telefone E.164, invariante intocado). Venda com **duas modelos** ("1300 cada
uma, 2600 no total") vira **uma linha por modelo**, cada uma no valor dela, com **dedup
cross-grupo** (data+valor+modelos+cliente) para o caso de o mesmo anúncio aparecer no grupo da
outra. Mensagem-fonte apagada (gesto real de correção do grupo: apaga e reposta) anula o registro
quando o evento de deleção existir; o repost cai no dedup.
_Avoid_: confundir com **Atendimento** ou fabricar um Atendimento `Fechado` (exige cliente,
conversa, estado — ADR-0043); criar **Cliente** a partir do nome; exigir forma de pagamento para
registrar (ela chega depois — é **Pendência**); somar as duas modelos numa linha só.

**Nome de anúncio**:
O nome de perfil pelo qual a modelo se anuncia e o cliente a conhece — na grafia do grupo,
"Perfil bianca/yasmin" é **nome de anúncio / nome verdadeiro** da MESMA mulher (bianca = perfil,
Yasmin = ela). Uma modelo pode ter mais de um. O resolver é **closed-world** sobre o cadastro
(nome verdadeiro + nomes de anúncio); nome desconhecido → o agente **pergunta no grupo** ("'fran
loira' é quem?") e grava a resposta do gestor como nome novo.
A exceção é o **cadastro desmentir a grafia**: quando os dois lados da barra resolvem sozinhos
para mulheres **diferentes** e o anúncio diz "cada uma" ("Perfil lari/ juju / 600 cada uma",
16/08), são duas participantes escritas na mesma linha — a interseção vazia ali não é dúvida, é a
resposta. Typo ("bianca/yamin"), homônimo e apelido que resolve para a mesma pessoa continuam
sendo uma participante só. Quem decide isso é `rateio.planejar`, nunca a contagem de linhas.
_Avoid_: ler "X/Y" como duas modelos **por causa da barra** (é o cadastro que decide, e só quando
o "cada uma" já afirma duas); resolver por palpite/similaridade; confundir com a persona da IA de
venda.

**Cobrança da agência**:
Valor que a agência cobra da modelo pelo grupo (ex.: anúncio/site — "*3RJ Suporte/Anúncio:* 3 DIAS
| R$ 385,80"), pago pela modelo **para a empresa da agência** (3RJ). Entra no extrato dela como
débito próprio; o comprovante do pagamento **abate a cobrança, nunca as vendas** — sem essa
distinção o pix da cobrança poluiria o Fechamento.
_Avoid_: tratar como despesa da agência (`financeiro_despesas` é outro módulo); contar o
comprovante da cobrança como dinheiro de venda comprovado.

**Comprovante de transferência**:
Imagem de comprovante Pix enviada no grupo (tipicamente modelo → agência), lida por OCR: valor,
data, pagador, destino. Classificado pelo contexto/valor como **fechamento de vendas** (abate as
vendas pix abertas mais antigas) ou **pagamento de Cobrança da agência**. Destino fora da lista de
**chaves Pix conhecidas da casa** (cadastro) → registro segue, com sinalização ao gestor.
_Avoid_: confundir com o comprovante de **Pix de deslocamento** do cliente (outro fluxo, outro
grupo); travar algo por comprovante duvidoso (sinaliza e segue — mesma filosofia do Pix da venda).

**Entrada da modelo** (classe de comprovante):
O comprovante que aponta para o **lado contrário** — o cliente pagando a modelo, não ela pagando a
casa. Reconhecido por **quem recebeu ser ela** (chave cadastrada ou primeiro nome do titular) **e
quem pagou não ser ela**: as duas condições juntas, porque num fechamento legítimo a pagadora é
ela. Fica registrado como prova de que a venda foi paga e **não abate nada, não quita cobrança e
não gera pergunta** — o eixo do fechamento mede o que saiu da mão dela para a casa. É o caso real
de 06/08 no export da Yasmin: sem isso o agente perguntava "é de quê?" e disparava o alarme de
chave fora da lista apontando o nome da própria modelo.
_Avoid_: contar como transferência (com venda em pix aberta na fila, o abate dá por comprovado
dinheiro que a casa não recebeu); usar só o destino para decidir (uma casa cujo titular divida o
primeiro nome com a modelo pararia de abater os fechamentos dela, em silêncio).

## A conferência

**Fechamento**:
A conferência **vendido × comprovado** por modelo — a conta que hoje o gestor faz de cabeça
("confere: 600 pix, 600 pix / ficou com você"). ⚠️ REVISTO (ADR-0045): o saldo continua **corrente
e derivado**, mas passa a ser recortado por **Temporada** e a conferência virou um **razão
bilateral** — vendido × comprovado deixou de ser o número final; o final é o saldo com sinal (casa
deve a ela × ela deve à casa). Modelo de **saldo corrente contínuo**: cada Venda registrada soma; cada Comprovante de transferência abate as vendas
pix abertas mais antigas; "fechar" tira um retrato do aberto. O retrato tem **três colunas**:
vendido, comprovado (pix) e **em espécie**. ⚠️ REVISTO (ADR-0045): venda em dinheiro **debita a
modelo no razão**, como qualquer venda cujo dinheiro ficou na mão dela; "em espécie" sobrevive só
como recorte visual (o que não tem comprovante a cobrar), não como dinheiro fora da conta. Gatilhos: **sob comando** de qualquer gestor e **rotina diária de manhã** (cobra
pendências e posta o saldo quando há movimento). Divergência **nunca trava**: vira pergunta no
grupo e flag no painel. ⚠️ REVOGADO (ADR-0045): o repasse **entra** no sistema — comissão por
`modelos.percentual_repasse` com snapshot na venda, e o fechamento diz "falta ela pagar vocês" ou
"falta vocês pagarem ela". Só o repasse **entre modelos** (a que recebeu por todas acertando com as
outras) fica fora. A divergência que mais importa é a que **se esconde no extrato que fecha**:
venda já conciliada cujo valor foi corrigido para cima depois do Pix — as colunas continuam
batendo e faltam R$ X que ninguém procuraria (`venda_comprovada_a_menor`). O espelho dela é o
**Pix órfão** (`pix_sem_venda_em_pix`): a venda que o comprovante fechou virou dinheiro, encolheu
ou foi anulada, e o mesmo Pix passa a ser contado na conta da casa **e** como espécie na mão da
modelo. As duas comparam o transferido com o **eixo pix** (comprovado + falta comprovar), nunca com
o vendido total — o vendido não muda quando a forma muda, e é por isso que a conta velha não via.
Cada dinheiro rende **uma** pergunta: a sobra de um comprovante maior já é `credito_da_modelo` e
não volta a divergir como Pix órfão.
_Avoid_: modelar split **entre modelos**; períodos que congelam o cálculo e
rejeitam comprovante atrasado (a Temporada NÃO congela — ADR-0045); cobrar comprovante de venda em dinheiro; confundir com o
**Lembrete de fechamento** (cobrança do Valor final de UM atendimento da IA de venda, na
Coordenação por modelo).

**Pendência**:
O que falta para uma Venda registrada conciliar ou para o extrato fechar: **forma de pagamento não
dita** (a mais comum — o anúncio da venda precede o pagamento), **comprovante não enviado** (vendas
pix descobertas), **Cobrança da agência não paga**, **Nome de anúncio desconhecido**. Pendência
**bloqueia a conciliação daquela venda, nunca o registro** nem o resto do extrato. Cobrança de
pendência é **consolidada** (na rotina da manhã — uma mensagem, não uma pergunta por venda na
hora, porque o atendimento pode nem ter acontecido quando é anunciado).
_Avoid_: pendência virar trava de registro; metralhadora de perguntas em tempo real; cobrar do
cliente (o agente só fala com o grupo).

**Leitura da fala**:
Como o agente entende o que o grupo escreveu. Duas instâncias, nesta ordem: um **leitor LLM**
(DeepSeek direto) que recebe a mensagem e a **lista numerada das vendas abertas**, e a **allowlist
fechada**, que fica de rede quando não há provider. O leitor aponta por **índice da lista**, nunca
por id — resposta fora da lista simplesmente não existe, e é o mesmo closed-world do resolver de
nomes. Ele **lê; quem decide é a porta**: alvo único vira recibo, vários viram recibo coletivo,
nenhum (ou leitura hesitante) vira a pergunta de desempate. Medido em 14/08 sobre 27 falas reais:
allowlist 19, leitor 24 — e o ganho é todo na cauda que allowlist nenhuma cobre ("foi tudo no pix
menos o do Igor", "o de 650 foi pix", "os dois primeiros").
A precedência entre as duas é por **o que cada uma sabe**: o leitor assume o turno quando traz o
que a allowlist não tem — um alvo, com confiança. Hesitando ou sem alvo, decide a allowlist, que
sabe uma coisa que o texto sozinho não diz: que aquele "Pix" seco responde à pergunta feita logo
depois de UM anúncio, e é daquela venda. Medido no replay do export real: com o leitor sempre na
frente, "Dinheiro" caía na venda errada e "Sim" virava pergunta de desempate.
_Avoid_: deixar a LLM escrever direto sem a escada de conduta; mandar id de venda no prompt;
tratar resposta seca ("foi pix") como coletiva — sem o quantificador escrito, ela fala de UMA venda
que ninguém identificou, e a conduta é perguntar; deixar o leitor escolher entre várias vendas numa
resposta que é só a forma (quem sabe a qual pergunta ela responde é o agente, que a fez).

**Cancelamento dito em fala**:
"cancela esse atendimento do Denis, ele não veio" — o atendimento que não aconteceu, sem passar
por apagar a mensagem. Faz **o mesmo efeito** do gesto suportado (apagar o anúncio): anula a Venda
registrada e grava o evento. Três trancas, todas do módulo: **uma venda por vez**, apontada por
índice da lista que a porta ofereceu; **confiança baixa não apaga** (vira "❓ Cancelar qual?"); e
só entram na lista as vendas **sem forma de pagamento dita**. O recibo nomeia o que morreu
(cliente + valor + dia) e diz como desfazer — repostar o anúncio registra de novo, porque o índice
de dedup é parcial (`WHERE anulada_em IS NULL`).
_Avoid_: cancelar em lote por fala livre; resolver demonstrativo sozinho ("cancela esse aí")
escolhendo a venda mais provável — apagar a errada não deixa sintoma nenhum, a cobrança da manhã
simplesmente para de pedir; cancelar venda já fechada por comprovante sem dizer que o Pix ficou
sem par.

**Resposta coletiva**:
Uma fala que resolve **N pendências de uma vez** ("todos foram pix", "foi tudo no dinheiro"). É a
resposta natural à cobrança da manhã, que é consolidada por regra do domínio — ninguém responde a
uma lista de quatro com quatro mensagens. O recibo dela carrega **quantas vendas, quais (até três
nomes) e o total**, porque são esses três números que dizem se o "todos" do gestor bateu com o do
agente: uma venda anunciada depois da cobrança entra na conta sem ele saber.
_Avoid_: aplicar o coletivo sem recibo conferível; ler numeral ("os dois", "ambas") como universal
quando há mais de duas abertas — aí a frase fala de duas e não diz quais.

**Desempate de forma**:
A forma **já foi dita** e o agente não sabe em qual venda pendurar ("Pix", com três pendentes e
nada no contexto que aponte). Ele não adivinha — escrever na venda errada é o único erro que não
volta, porque a venda errada some do fechamento e a certa nunca mais é cobrada — mas também não
cala: devolve **uma** pergunta que um nome responde ("Foi pix em qual? …"), e não repete enquanto
ela estiver visível no grupo. Não confundir com **cobrar** a forma: isso é Pendência, e a cobrança
dela é consolidada, de manhã.

**Ficha de agendamento** (card do telefonista):
⚠️ REVISTO (ADR-0046). O card padronizado que o **telefonista** posta **antes** do serviço — e que
desde 20/08 são **três** documentos, não um: a **Ficha de atendimento individual**, a **Ficha de
atendimento de grupo** (`Modelo 1..N`) e o **Comunicado da modelo** (resumido, sem `( )`, com o
valor já escrito). Template em `docs/dominio/fichas-do-telefonista.md`. A ficha completa pode ser
postada num **Grupo de fichas** dedicado em vez do grupo individual, e por isso o alvo closed-world
é escopado **por modelo**, não por grupo. Campos: cliente (nome, WhatsApp — só em
videochamada), contratação (Nome de anúncio, **site** da plataforma, origem próprio × fake, **nome
real da modelo**, ou a lista quando há mais de uma), **data**, **hora**, duração,
local (próprio × saída + **tipo**: casa/hotel/motel/festa/passeio/jantar-almoço + endereço com
número e complemento), valores (total e o desta modelo), deslocamento (**antecipado** e
**transporte**), forma prevista (dinheiro/pix/débito/crédito/link) e observações. Entidade própria com estado
`aberta → confirmada → realizada | cancelada` (ADR-0044), gravada **calada** — o telefonista não
pediu confirmação de nada. Serve a dois donos: informar a modelo do combinado e ser a fonte
estruturada do registro. Quatro gestos mexem no estado dela: **reação emoji** (✅/❌), **repost** da
ficha alterada, **resposta por quote** e **edição** da mensagem. O ✅ do telefonista vem **depois**
de a modelo confirmar que recebeu, e por isso vale como **segunda porta do mesmo fato**: o que vier
primeiro promove a ficha a venda, o segundo não duplica.
_Avoid_: confundir com a **Venda registrada** (a ficha é o combinado, a venda é o fato); tratar
ficha como receita; responder a ficha com recibo; exigir card — texto livre continua válido e é o
que o backfill lê; assumir que a ficha chegou no grupo de quem vai pagar; confundir o **Comunicado
da modelo** com a ficha completa (ele não tem `( )` nem `Valor total`).

**Temporada**:
O período em que uma modelo trabalha numa cidade (7/10/14 dias), e a unidade de **pagamento** dela
("fecha pra mim a temporada da fulana, do dia tal ao dia tal"). Entidade própria: modelo, cidade,
início, fim, estado. **Não congela o cálculo** — o saldo segue derivado; o que a temporada guarda
como fato são os **pagamentos feitos**. Comprovante que chega depois recalcula o saldo, e a
diferença contra o já pago vira "falta pagar R$ X". Fechar é **ação do painel**, nunca frase no
grupo (move dinheiro, e a modelo está no grupo).
_Avoid_: tratar como período estanque que rejeita lançamento atrasado; criar snapshot de saldo
(dois números concorrentes para a mesma temporada); guardar o percentual de repasse aqui — ele é do
cadastro da modelo, com snapshot na venda.

**Razão da modelo**:
A conta corrente única entre a modelo e a casa (ADR-0045). Debita o **bruto** de toda venda cujo
dinheiro caiu na mão dela (Pix dela, dinheiro, cartão dela), as **Cobranças da agência**, os
**vales** e o deslocamento que ela recebeu e a casa pagou. Credita a **comissão** de toda venda
(inclusive as pagas no Pix da empresa) e cada **transferência** dela para a casa. Saldo positivo =
a casa deve a ela; negativo = ela deve à casa. ⚠️ REVISTO (ADR-0047): em que bolso o dinheiro caiu
é **fato da venda**, resolvido por evidência (comprovante > fala > `forma = dinheiro` > não dito),
**nunca** parâmetro de cadastro — o dono negou que exista padrão por modelo. Numa venda com N
modelos, `recebido_por_modelo_id` diz de quem é o débito.
_Avoid_: deixar espécie fora; descontar taxa de cartão (decisão do dono: bruto = valor do card);
tratar "não dito" como erro (é estado legítimo, e o default do razão é **dela**);
transformar "regime de repasse (inteiro × parte da casa)" em parâmetro de banco — o razão absorve
qualquer valor transferido, e o regime é só **conduta** (quanto pedir que ela envie).

**Origem do anúncio** (próprio × fake):
De qual anúncio veio o cliente: o **próprio** (com as fotos dela) ou o **fake** (anúncio genérico).
É atributo da **venda**, não do Nome de anúncio — a mesma "Bianca" vende pelos dois, e quem sabe a
origem é o telefonista que fechou. Em texto livre a palavra "fake" aparece colada ao nome ("fake
Bianca"): o resolver a remove e grava a origem. Existe para a métrica que o dono pediu — quanto o
fake fatura contra o original.
Desde 20/08 anda junto do **Site** — a plataforma por onde a venda entrou (Barra Vips, GSEX, Viva
Local, Garota com Local; e Instagram/Tinder). O site é mais fino e em geral **determina** a origem:
*"o fake só vai ser sites específicos"*.
_Avoid_: criar um Nome de anúncio separado para o fake (só funciona se o telefonista sempre
escrever a palavra, e no export real ele não escreve); tratar site e origem como o mesmo campo.

**Deslocamento**:
O Uber ida-e-volta da modelo, cobrado do cliente (tipicamente R$ 100, pagos por Pix ao telefonista).
⚠️ REVISTO (ADR-0046): são **dois** valores, e eles divergem — o **Valor antecipado** que o cliente
mandou (receita) e o **Valor do transporte** que o Uber custou (custo). *"Quando é muito perto, tipo
15 reais de Uber, eu pago"*: antecipado zero, transporte não.
Lançamento próprio ligado à venda, com os dois valores, **quem recebeu** (casa ×
modelo) e **quem pagou o Uber** (casa × modelo). Recebido por ela e pago pela casa → débito dela;
recebido e pago pela casa → não toca o razão dela. **Nunca entra na base de comissão** — é
reembolso de custo, não serviço.
_Avoid_: somar ao bruto; virar Cobrança da agência (isso é dívida, não reembolso); ignorar quem
pagou o Uber, que é o que faz R$ 100 sumirem do caixa; guardar um número só, que apaga a margem e
apaga o prejuízo.

**Vale**:
Adiantamento que a casa dá à modelo no meio da temporada ("tem que pagar uma conta de 500 reais, eu
adianto"), descontado no fechamento. Débito dela no razão. Entra por **duas portas**: lançamento no
painel e fala no grupo ("adiantei 500 pra ela"), esta com recibo corrigível.
_Avoid_: confundir com Cobrança da agência (aquilo é serviço vendido a ela — anúncio, site; isto é
dinheiro emprestado).

**Comunicado da modelo**:
A versão **resumida** da ficha, escrita para a modelo trabalhar e não para o sistema registrar
(ADR-0046). Sem `( )` para marcar — o valor já vem escrito (`Tipo: Hotel`). Traz cliente, perfil,
origem, duração, tipo e endereço do local, valor e forma; **não** traz WhatsApp do cliente, site,
nome real, valores de deslocamento nem **data e hora** — é prévia, e a hora ainda não se sabe.
Existe porque quem opera a rotina disse que a ficha completa não sobrevive ao dia de pico:
*"elas não vão ler, aí vão vir no privado e perguntar três, quatro vezes a mesma coisa"*.
_Avoid_: tratar como fonte de registro (é a ficha completa que registra); mostrar nele a conta da
festinha inteira — o valor que a modelo vê é **o dela**.

**Grupo de fichas**:
Grupo dedicado onde os telefonistas postam a **ficha completa**, enquanto o grupo individual da
modelo recebe só o **Comunicado**. Arranjo **em teste**, não decidido — por isso o código nunca
deduz a modelo pelo JID do grupo: ela vem do campo `Nome da modelo` do card, pelo resolver
closed-world.
_Avoid_: confundir com o **grupo central** (recado e conversa social, todas as modelos) e com o
**caixa dos telefonistas** (conferência, entra só em leitura); assumir que ele existe.

**Bolso da venda**:
Onde o dinheiro daquela venda caiu — na mão **dela** ou na conta da **empresa**. É **fato da
venda**, resolvido por evidência nesta ordem: comprovante dela → casa (dela) > comprovante do
cliente → casa (empresa) > fala explícita > `forma = dinheiro` (sempre dela) > **não dito**
(ADR-0047). "Não dito" é estado legítimo: entra na cobrança consolidada da manhã junto com a forma
que já é cobrada, e o razão o trata como **dela** — errar para esse lado é conservador, porque o
saldo mostra a modelo devendo e alguém confere; o erro oposto esconde dinheiro e ninguém procura.
_Avoid_: virar coluna do cadastro da modelo (`recebe_no_proprio_pix` **não existe** — o dono negou
que exista padrão: *"varia, não existe só um padrão"*); virar pergunta em tempo real; ser chutado.

**Comissão do telefonista**:
O que a casa paga ao **vendedor** que fechou a venda: percentual **por vendedor** (faixa operacional
1–10%, referência 7%), sobre o **faturamento bruto vendido**, sem deslocamento na base, calculado
**por projeção e sem snapshot** (ADR-0048). Quem é o telefonista da venda vem do **autor da
mensagem** (`vendedores.whatsapp_jid`); autor desconhecido → sem vendedor → sem comissão.
_Avoid_: confundir com a **comissão da modelo** (outra pessoa, outra conta, outra base — a dela é o
`percentual_repasse` com snapshot); mostrá-la no extrato da modelo, que ela lê no grupo dela;
calcular sobre "o que fica para a casa" — o dono fixou *"do valor da venda, valor total que ele
vendeu"*.

**Site** (da venda):
A plataforma por onde o cliente chegou: Barra Vips, GSEX, Viva Local, Garota com Local — e também
Instagram e Tinder. Campo da ficha e da venda, mais fino que a **Origem do anúncio**, que ele em
geral determina.
_Avoid_: confundir com **Nome de anúncio** (o nome fantasia, ex. "Sofia") e com a **fonte de
tráfego do cliente**, que hoje é indescobrível — *"ele só manda mensagem direto"*, e só um código de
origem na primeira mensagem resolveria.

## Ambiguidades sinalizadas

- **"atendimento"** no Grupo financeiro = **Venda registrada** (serviço realizado), não o
  **Atendimento** do ciclo comercial. Mesma palavra, entidades distintas; quando a IA de venda
  entrar em produção, as duas fontes coexistem no Módulo Financeiro (ADR-0043).
- **"perfil"** no grupo = **Nome de anúncio** da modelo; não confundir com **Perfil físico
  preferido** (atributo do cliente, painel-only).
- **"comprovante"** cobre dois destinos: fechamento de vendas × pagamento de cobrança — a
  classificação é do agente, não do humano.
- **"mandou de novo"** cobre dois fatos: a mesma MENSAGEM reentregue pelo router e a mesma FOTO
  reenviada como mensagem nova. Os dois têm o mesmo remédio (não contar duas vezes) e trancas
  diferentes no banco — a segunda é a que impede um Pix de fechar duas vendas com o extrato
  batendo.
- **"atendimento"** ganhou um terceiro sentido depois de 17/08: no card do telefonista ele é a
  **Ficha de agendamento** (combinado, ainda não aconteceu); na fala da modelo que recebeu, é a
  **Venda registrada**; no ciclo comercial da IA de venda, é o **Atendimento**. Três coisas, uma
  palavra.
- **"perfil"** cobre agora dois eixos independentes: **qual** Nome de anúncio (bianca × sophia) e
  **de qual anúncio** veio o cliente (próprio × fake). Confundir os dois mata a métrica.
- **"grupo"** cobre três: o **central** (todas as modelos, recado e conversa social), o
  **individual/financeiro** por modelo (onde a IA escreve) e o **caixa dos telefonistas** (todas as
  modelos num lugar só, onde a IA só lê).
- **"fechar"** cobre dois: postar o extrato do momento (leitura pura, não escreve nada) e **fechar
  a Temporada** (ação do painel, que registra pagamento).
- **"apagou"** cobre dois alvos, e cada um desfaz uma coisa diferente: apagar o **anúncio** anula a
  Venda registrada (e a Cobrança da agência); apagar a **foto do comprovante** desfaz o abate e
  devolve as vendas para "falta comprovar". O comprovante anulado sai da conferência mas continua
  no banco, e libera a foto para ser reenviada.
- **"ficha"** cobre agora **três** documentos com públicos opostos: a Ficha de atendimento
  individual, a de grupo e o **Comunicado da modelo**. O que os separa mecanicamente: o comunicado
  não tem `( )` e não tem `Valor total`.
- **"comissão"** cobre duas pessoas e duas bases: a da **modelo** (`percentual_repasse`, com
  snapshot na venda, ~50%) e a do **telefonista** (por vendedor, por projeção, 1–10%). Nunca
  aparecem no mesmo extrato.
- **"cartão"** deixou de ser uma forma e virou três — **débito**, **crédito** e **link**. Texto
  antigo que diga só "cartão" é do mundo pré-20/08.
- **"deslocamento"** cobre dois números que divergem: o que o **cliente antecipou** e o que o
  **transporte custou**.
- **"valor"** no Comunicado da modelo é o **dela**, não o total da festinha. ⚠️ A fala do dono foi
  ambígua nesse ponto e falta confirmar.
