# As fichas do telefonista

> Fonte: reunião de alinhamento de 20/08/2026 com Rossi e Lula (`reuniaoalinhamento.txt`),
> que refina o card definido na reunião de 17/08 (`ata.txt`). Decisão: **ADR-0046**.
> Vocabulário: `docs/dominio/grupo-financeiro.md`.

São **três** documentos, não um. A reunião de 17/08 tratou "o card" como peça única; a de 20/08
descobriu que ele tem dois públicos com necessidades opostas, e que forçar um só formato quebra
os dois.

| Documento | Para quem | Onde | Forma |
|---|---|---|---|
| **Ficha de atendimento — individual** | o sistema | grupo de fichas (a definir; ver ADR-0046) | completa, com `( )` para marcar |
| **Ficha de atendimento — grupo** | o sistema | idem, quando há mais de uma modelo | idem + `Modelo 1..N` |
| **Comunicado da modelo** | a modelo | grupo financeiro individual dela | resumido, **sem** `( )`, valor já preenchido |

O porquê da separação, na voz da Lula: *"na hora que tem quatro clientes subindo isso não vai ser
tão fácil"* e *"elas não vão ler, entendeu? Aí elas vão vir no privado e vão perguntar as
informações três, quatro vezes a mesma coisa. E olha que a gente resume"*. A ficha completa existe
**para o sistema**; o comunicado existe **para a modelo trabalhar**.

---

## 1. Ficha de atendimento — individual

```
📋 *FICHA DE ATENDIMENTO*

👤 *CLIENTE*
Nome:
WhatsApp:

📝 *CONTRATAÇÃO*
Nome do perfil/anúncio:
Site:
Origem: ( ) Próprio  ( ) Fake
Nome da modelo:

🕒 *HORÁRIO*
Data:
Hora:
Duração:

📍 *LOCAL*
( ) Local próprio  ( ) Saída
Tipo: ( ) Casa  ( ) Hotel  ( ) Motel  ( ) Festa  ( ) Passeio  ( ) Jantar/Almoço
Endereço:
Número / bloco / complemento:

💰 *VALORES*
Valor total: R$
Valor desta modelo: R$
Valor do transporte: R$
Valor antecipado: R$
Forma do antecipado: ( ) Pix  ( ) Link

💳 *PAGAMENTO*
( ) Dinheiro  ( ) Pix  ( ) Débito  ( ) Crédito  ( ) Link

✏️ *OBSERVAÇÕES*
```

## 2. Ficha de atendimento — grupo

Idêntica à individual, trocando `Nome da modelo` pela lista e `Valor desta modelo` pelo valor de
cada uma:

```
📝 *CONTRATAÇÃO*
Nome do perfil/anúncio:
Site:
Origem: ( ) Próprio  ( ) Fake
Modelo 1:
Modelo 2:
Modelo 3:
(Modelo 4:  Modelo 5:  Modelo 6: — se houver)

💰 *VALORES*
Valor total: R$
Valor de cada modelo: R$
...
```

Não tem campo "quantidade de modelos": *"você colocando o nome delas, acho que já é suficiente"*.
A contagem sai da lista.

## 3. Comunicado da modelo

O que vai no grupo financeiro individual dela. **Sem parênteses para marcar** — o telefonista já
escreve o valor: `Tipo: Hotel`, não `( ) Hotel`. *"Pras meninas eu acho que esse xzinho assim e
tal, toda essa informação não seria interessante."*

```
👤 *CLIENTE*
Nome:

📝 *CONTRATAÇÃO*
Nome do perfil/anúncio:
Origem:

🕒 *HORÁRIO*
Duração:

📍 *LOCAL DO JOB*
Tipo:
Endereço:

💰 *VALOR DO JOB*
Valor: R$
Forma de pagamento:

✏️ *OBSERVAÇÕES*
```

**Não entram**: WhatsApp do cliente (*"o número já não entra"*), site, nome real da modelo, valor
total da festinha, valores de deslocamento, data e hora. A hora fica de fora por ser **prévia** —
*"a hora não precisa porque é uma prévia, ainda não sabe a hora"*.

O `Valor do job` que a modelo vê é **o valor dela**, não o total da festinha — regra herdada da
spec 0006 (cada uma vê o que é dela sem ver a conta da outra). ⚠️ Confirmar com o Rossi: a fala
dele na reunião foi ambígua entre "valor do job" e "valor total".

---

## Campos e o que cada um significa

| Campo | Vem de onde | Observação |
|---|---|---|
| `Nome do perfil/anúncio` | o anúncio | o nome fantasia sob o qual o cliente comprou (ex.: Sofia) |
| `Site` | a plataforma | Barra Vips, GSEX, Viva Local, Garota com Local… também Instagram e Tinder |
| `Origem` | próprio × fake | *"o fake só vai ser sites específicos"* — o site quase sempre já diz |
| `Nome da modelo` | cadastro | o nome **real**; distinto do perfil. Vem depois do perfil, *"porque vem do anúncio depois pra modelo"* |
| `Data` / `Hora` | o atendimento | decididos nesta reunião; a spec 0006 não os tinha |
| `Tipo` de local | enum | casa, hotel, motel, festa, passeio, jantar/almoço |
| `Valor total` | a venda | o bruto que o cliente paga por tudo |
| `Valor desta modelo` | rateio | numa festinha de R$ 2.000 com três modelos, R$ 800 para a que recebe esta ficha |
| `Valor do transporte` | custo | quanto o Uber ida-e-volta custou de fato |
| `Valor antecipado` | receita | quanto o cliente mandou pelo transporte (tipicamente R$ 100). Padrão Pix |
| `Pagamento` | enum | **cartão foi desmembrado** em `Débito`, `Crédito` e `Link` |
| `Observações` | o cliente | *"o cliente pediu para não passar perfume"* — tudo que ela tem que saber para não chegar boiando |

## Sobre a origem do cliente

Ficou registrado e **não entrou** na ficha: saber de que fonte o cliente veio (Instagram, Tinder,
site) não é possível hoje — *"ele só manda mensagem direto"*. Só passa a ser possível com código de
origem na primeira mensagem, o que é campanha de marketing, não campo de ficha.
