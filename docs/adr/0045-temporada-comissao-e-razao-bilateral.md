---
data: 2026-08-18
status: aceito
relaciona: ADR-0043 (revoga o "repasse/split ficam fora do sistema"), ADR-0011/0013 (repasse da modelo), ADR-0044, docs/dominio/grupo-financeiro.md
revisto_por: ADR-0047 (revoga a decisao 4), ADR-0046 (revisa a decisao 5), ADR-0048 (comissao do telefonista)
---

# ADR-0045 — Temporada, comissão e o razão bilateral da modelo

> ⚠️ A decisão **4** foi **revogada** pelo ADR-0047 (o bolso é fato da venda, não cadastro da
> modelo) e a **5** foi **revista** pelo ADR-0046 (deslocamento guarda dois valores). O razão, a
> Temporada e a comissão da modelo seguem intactos — e a reunião de 20/08 confirmou os 50%.

## Contexto

O ADR-0043 e o `docs/dominio/grupo-financeiro.md` dizem, com todas as letras, que **repasse e
split ficam fora do sistema**: "o módulo garante que os números batem, não distribui dinheiro". O
Fechamento é a conferência **vendido × comprovado**, em **saldo corrente contínuo, sem períodos
estanques**, e venda em dinheiro fica "em espécie com a modelo", **fora** da conta ("o acerto do
cash, como o repasse, é da operação").

A reunião de 17/08/2026 desfaz os três pontos:

- **Repasse dentro**: "vai ter o repasse já automático de vocês, e já vai falando se falta ela
  pagar vocês ou falta vocês pagarem ela"; "a conta mais maliciosa é a comissão de todas as
  pessoas, porque não pode ter [erro]".
- **Período existe e tem nome**: **Temporada**. A modelo viaja para uma cidade e trabalha 7/10/14
  dias; o pagamento é **por temporada**, não por atendimento ("começou a ter muita desistência no
  meio do caminho, aí eu falei: vou combinar uma data"). Existe **vale** adiantado no meio, que é
  descontado no fim. O comando do dono é literalmente "fecha pra mim a temporada da fulana, do dia
  tal ao dia tal".
- **Espécie não pode ficar fora**: se dinheiro em espécie não debita, uma modelo que fez a
  temporada inteira em cash aparece com a casa devendo o líquido inteiro, quando ela já está com o
  bruto na mão.

O regime de recebimento também é duplo e depende de confiança: modelo nova recebe **no Pix da
empresa**; modelo antiga recebe **no Pix dela** e transfere depois. E o quanto ela transfere
varia — o valor inteiro, ou só a parte da casa.

**Evidência empírica** (export real, 12/08/2026): vendas de `600 pix` + `600 pix` = R$ 1.200; a
gestora escreve "Ficou com você" e passa a chave; o comprovante anexado é de **R$ 1.200,00**
(Yasmin → Erick, chave `cb890e5a…`). Confirma que o valor do card é o **bruto** e que o regime
dela é **valor inteiro** — a casa passou a dever R$ 600 a ela.

## Decisão

**1. Conta corrente única por modelo** (o "razão"), em vez de eixos separados:

| Lançamento | Débito dela | Crédito dela |
|---|---|---|
| Venda cujo dinheiro caiu na mão dela (Pix dela, dinheiro, cartão dela) | bruto | — |
| Comissão da venda (qualquer venda) | — | `percentual_repasse` × bruto |
| Venda paga no Pix/cartão da empresa | — | — |
| Transferência dela → casa (comprovante) | — | valor transferido |
| Cobrança da agência (3RJ, site) | valor | — |
| Vale adiantado | valor | — |
| Deslocamento recebido por ela e pago pela casa | valor | — |

Saldo positivo = a casa deve a ela; negativo = ela deve à casa. Os quatro cenários reais fecham:
transferiu tudo → +600; não transferiu → −600; tudo dinheiro → −600; Pix da empresa → +600.

**2. Espécie entra no razão** como qualquer venda cujo dinheiro ficou com ela. A coluna "em
espécie" do Fechamento sobrevive como **recorte visual** (o que não tem comprovante a cobrar),
não como dinheiro fora da conta.

**3. A comissão reusa `modelos.percentual_repasse`** (que já existe, ADR-0011/0013), com
**snapshot na venda** — mesma disciplina do `percentual_repasse_snapshot` do Atendimento. 50% é
default de cadastro, não constante de código. ✅ CONFIRMADO em 20/08: *"todas são 50%, por regra"* —
e o anúncio é **sempre 50% pago pela modelo**, na hora ou descontado ao longo da temporada. **Taxa de cartão não é descontada** (decisão do dono
do produto): bruto = valor do card.

**4.** ⚠️ **REVOGADO pelo ADR-0047** — o Rossi negou o pressuposto em 20/08: *"varia, não existe só
um padrão"*. Texto original: **Em que bolso o dinheiro caiu é `modelos.recebe_no_proprio_pix` +
snapshot na venda.** É
decisão de confiança, muda raramente, e promover uma modelo não pode reescrever temporada passada
em silêncio. O comprovante confirma ou desmente: pagador = cliente e destino = casa significa que
o snapshot estava errado, e a IA pergunta.

**5. Deslocamento é lançamento próprio, fora da base de comissão.** ⚠️ REVISTO (ADR-0046): são
**dois** valores — o antecipado que o cliente mandou e o que o transporte custou. Guarda valor
cobrado do cliente, **quem recebeu** (casa × modelo) e **quem pagou o Uber** (casa × modelo). Recebido por ela
e pago pela casa → débito dela; recebido e pago pela casa → não toca o razão dela.

**6. Numa venda com N modelos, `recebido_por_modelo_id` diz de quem é o débito.** Na festinha em
que uma recebe por todas, as N vendas apontam para ela: ela carrega o débito do bruto total, e as
outras ficam só com o crédito da comissão delas. O repasse entre modelos fica fora do sistema — a
casa fecha com cada uma, e ninguém precisa "fazer cálculo" (que a ata diz que elas não fazem).

**7. Temporada é entidade** (modelo, cidade, início, fim, estado) e **não congela o cálculo**. O
saldo segue **derivado** — o princípio do `fechamento.py` fica intacto. O que a temporada guarda
como fato são os **pagamentos feitos**. Um comprovante que chega depois de "fechada" recalcula o
saldo; a diferença contra o já pago aparece como "falta pagar R$ X" (ou crédito, se pagou a mais).
Não existe reabertura, porque nunca houve congelamento.

**8. Fechar a temporada é ação do painel**, nunca frase solta no grupo — move dinheiro de verdade,
e o grupo tem a modelo dentro. O **vale**, ao contrário, é dito no grupo o tempo todo ("adiantei
500 pra ela") e o agente aprende a lê-lo lá, com recibo corrigível, além da entrada pelo painel.

## Alternativas rejeitadas

- **Manter repasse fora e o gestor acertar de cabeça.** Preserva o domínio como está, mas quebra a
  promessa central da reunião justamente na forma de pagamento mais comum do negócio.
- **50% como constante de domínio.** Diverge de um campo que já existe no cadastro e obriga
  migration no dia — provável — em que uma modelo negociar outro split.
- **Percentual na Temporada.** Mais fiel ao negócio, mas cria segunda fonte de verdade ao lado de
  `modelos.percentual_repasse`, que a IA de venda já usa.
- **Regime de repasse (inteiro × parte da casa) como parâmetro de banco.** Desnecessário: o razão
  absorve qualquer valor transferido. Ele sobrevive apenas como **conduta** da IA — quanto pedir
  que ela envie.
- **Temporada congelando um snapshot de fechamento.** Foi a proposta inicial e o dono do produto a
  rejeitou com o argumento certo: se ela já recebeu, recebe a diferença; se não, o valor inteiro.
  Congelar criaria dois números concorrentes para a mesma temporada.

## Consequências

- O `docs/dominio/grupo-financeiro.md` precisa revogar três frases: "repasse/split ficam fora",
  "sem períodos estanques" e "em espécie … fora da expectativa".
- O Fechamento postado no grupo passa a poder conter número de comissão — a modelo lê. A conduta de
  quanto expor no grupo × quanto deixar só no painel fica como decisão de produto por cima disto.
- `forma_pagamento` da Venda registrada passa a aceitar **cartão** (print da venda), que não é
  comprovante Pix e não passa pelo mesmo OCR.
- O Módulo Financeiro passa a ter, além das duas fontes de receita do ADR-0043, uma terceira classe
  de dado: os lançamentos do razão (vale, ajuste, pagamento de temporada).
