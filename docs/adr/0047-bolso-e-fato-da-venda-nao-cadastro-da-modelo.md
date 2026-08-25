---
data: 2026-08-20
status: aceito
relaciona: ADR-0045 (revoga a decisão 4 — `modelos.recebe_no_proprio_pix`), ADR-0046, spec 0006
---

# ADR-0047 — Em que bolso o dinheiro caiu é fato da venda, não cadastro da modelo

## Contexto

O ADR-0045 §4 decidiu: *"em que bolso o dinheiro caiu é `modelos.recebe_no_proprio_pix` + snapshot
na venda. É decisão de confiança, muda raramente, e promover uma modelo não pode reescrever
temporada passada em silêncio."*

A premissa — "muda raramente" — está errada. Perguntado diretamente na reunião de 20/08 sobre as
quatro modelos ativas, o Rossi respondeu:

> *"Varia. Não existe só um padrão. Às vezes elas vão receber no dela e vão repassar. Às vezes elas
> vão ficar com uma quantidade de valor que já está na conta dela e a gente só vai pagar o restante.
> E assim vai."*

E, sobre a maquininha de cartão: *"o ideal é ser na nossa conta"*, mas para essas quatro *"não sei
te responder"* — porque às vezes *"a mina tem a máquina no celular dela"*.

Um parâmetro de cadastro que varia por atendimento não é parâmetro: é um palpite que vai estar
errado metade das vezes, e o snapshot só congela o palpite errado dentro da temporada.

A mesma reunião entregou a regra que **de fato** governa isso, e ela não é de cadastro:

> *"Atendimento na conta da modelo? Nesse caso ela deve o valor cheio, ela tem que mandar o valor
> cheio. O repasse é depois, no fechamento da temporada."*
>
> *"Então o certo vai ser ela receber e enviar pra gente."* — *"Tá, perfeito."*

E a exceção, que é **declarada, nunca inferida**:

> *"Ela recebeu uma ligação, o agiota (…). Aí ela vai falar: deixa eu pegar esse dinheiro aqui pra
> pagar. 'Beleza, fica com esse dinheiro, depois eu desconto.' (…) Eu falo assim pra IA: esse valor
> da Ingrid de 1.200, 2 horas, ela ficou pra ela. Aí ela já vai contabilizar que aquilo ali foi um
> vale."*

## Decisão

**1. `modelos.recebe_no_proprio_pix` não existe.** O bolso é campo da **Venda registrada**,
preenchido pelo que foi dito ou provado naquela venda — nunca herdado do cadastro.

**2. A fonte do bolso, em ordem de precedência:**

| Evidência | Bolso |
|---|---|
| Comprovante da modelo → casa, casando com a venda | dela (e a transferência credita) |
| Comprovante do cliente → casa | empresa |
| Fala explícita ("caiu na minha conta", "ficou com você") | o que foi dito |
| Forma = dinheiro | dela, sempre (espécie não tem outro bolso) |
| Nada disso | **não dito** |

**3. "Não dito" é estado legítimo, não erro.** Ele entra na cobrança consolidada da manhã, ao lado
da forma de pagamento que já entra hoje — mesmo mecanismo, mesma frase, sem pergunta nova. Nunca
trava a venda, nunca vira palpite.

**4. O default do razão para "não dito" é `dela`**, porque é o que o dono descreve como o certo
(*"o certo vai ser ela receber e enviar pra gente"*) e porque errar para esse lado é conservador: o
saldo mostra a modelo devendo, alguém confere, e o comprovante corrige. Errar para o outro lado
esconde dinheiro na mão dela e ninguém procura.

**5. "Ficou com ela" é vale, e é o mesmo lançamento do ticket 15.** Quando o gestor declara que a
modelo ficou com o dinheiro, isso não é um bolso diferente — é a venda com bolso `dela` **mais** a
ausência da transferência. O razão já produz o resultado certo sem conceito novo. A palavra "vale"
na fala do gestor vira o lançamento de vale só quando houver adiantamento **fora** de uma venda.

**6. O mesmo vale para o cartão.** Débito, crédito e link seguem a mesma tabela de evidência. Não
há `maquininha_da_modelo` no cadastro.

## Alternativas rejeitadas

- **Manter o parâmetro como default e deixar o comprovante corrigir** (o desenho do ADR-0045). É
  quase isto, mas com um campo a mais que mente com convicção: o painel mostraria "recebe no Pix
  dela" para uma modelo que naquele mês recebeu tudo na conta da casa, e o operador acreditaria.
- **Perguntar o bolso em toda venda.** Uma pergunta a mais por venda, num módulo cujo princípio é
  perguntar o mínimo. A cobrança consolidada da manhã já é o canal, e ela já cobra a forma.
- **Deduzir o bolso do regime de repasse da modelo.** Não existe regime estável — é exatamente o que
  o Rossi negou.

## Consequências

- O ADR-0045 §4 fica **revogado**; a disciplina de snapshot que ele defendia continua valendo para
  o **percentual de comissão**, que é de cadastro de verdade.
- Some uma migration de cadastro e some um seletor do painel de modelos.
- A história 28 da spec 0006 ("quero definir por modelo se ela recebe no Pix dela") é **retirada**;
  a 29 (o comprovante desmente) vira a regra principal, não a exceção.
- O ticket 14 (comprovante cliente → empresa desmente o bolso) deixa de ser correção de um cadastro
  errado e passa a ser uma das linhas normais da tabela de evidência.
