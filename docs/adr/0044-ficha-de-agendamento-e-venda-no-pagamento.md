---
data: 2026-08-18
status: aceito
relaciona: ADR-0043 (Venda registrada fora de atendimentos), spec 0005, docs/dominio/grupo-financeiro.md
revisto_por: ADR-0046 (a ficha em duas vozes; onde ela e postada; o check do telefonista)
---

# ADR-0044 — Ficha de agendamento é entidade; a Venda registrada nasce no pagamento

> ⚠️ **Revisto pelo ADR-0046** (20/08/2026) em dois pontos, marcados abaixo: o card virou **três**
> documentos e pode não ser postado no grupo da modelo (§1, §3); e o ✅ do telefonista é a segunda
> porta do mesmo fato, não um estado anterior ao pagamento. O resto segue valendo.

## Contexto

A spec 0005 e o ADR-0043 modelaram a Venda registrada como **fato consumado**: a gestora anuncia
no Grupo financeiro, em texto livre, um serviço que **já aconteceu**, e o agente registra direto
com recibo corrigível. Foi o que o export real da Yasmin (06–13/08/2026) mostrava.

A reunião de 17/08/2026 com Rossi e Lula mudou o processo da operação, não o software:

- **Quem anuncia deixa de ser a modelo/gestora e passa a ser o telefonista**, num **card
  padronizado** (Ficha de agendamento) postado no Grupo financeiro individual de cada modelo
  participante. ⚠️ REVISTO (ADR-0046): são três documentos, e a ficha completa pode ir para um
  **Grupo de fichas** dedicado em vez do grupo individual.
- **O card nasce ANTES do serviço.** Ele é, primeiro, o jeito de a modelo saber o que foi
  combinado ("ela tem que saber de tudo que foi combinado e tudo que foi pago com antecedência").
- O combinado **muda**: o telefonista confirma, altera hora/valor/desconto, ou marca que não rolou.
  Os gestos observados são quatro — reação emoji (✅/❌), repost da ficha alterada, resposta por
  quote e edição da mensagem.
- **Só a modelo fecha o fato**, quando avisa que recebeu ("recebi, foi dinheiro") e/ou manda o
  comprovante. ⚠️ REVISTO (ADR-0046): o ✅ do telefonista é dado **depois** disso e vale como
  segunda porta do mesmo fato — o que vier primeiro promove a ficha.

Isso deixa o registro num limbo que a spec 0005 não tem nome para: entre o post do telefonista e o
pagamento existe um objeto que já carrega todo o dado (valor, cliente, duração, local, perfil) e
ainda não é receita.

O caso que decide: o telefonista posta a ficha do **Igor, R$ 700, 1h, local próprio** às 19h; às
22h a modelo escreve só **"recebi, foi dinheiro"**. Para a venda nascer com R$ 700 e cliente Igor,
o sistema precisa ter guardado a ficha. Sem isso a única saída é interrogar a modelo — exatamente
a metralhadora de perguntas que o domínio proíbe.

## Decisão

**1. Ficha de agendamento é entidade própria**, com estado: `aberta → confirmada → realizada`,
ou `cancelada`. Gravada **calada** (sem recibo — o telefonista não pediu confirmação de nada) a
partir do card, com a mensagem-fonte como origem.

**2. A Venda registrada continua sendo fato consumado e nasce no PAGAMENTO**, herdando da ficha
valor, cliente, duração, local, perfil e deslocamento. O que a modelo precisa dizer é a forma —
e mandar o comprovante quando houver.

**3. A ficha é o alvo, e o alvo é closed-world.** ⚠️ REVISTO (ADR-0046): o escopo é **por modelo**,
não por grupo. A ficha vive no grupo daquela modelo, então a
lista de fichas abertas do grupo é finita e numerada; a LLM aponta por **índice**, nunca por id —
o mesmo contrato que `leitura.py` já usa para vendas. Vale para o pagamento, para o ✅/❌ e para a
alteração.

**4. Os quatro gestos são suportados** (reação, repost, quote, edição), porque a operação não tem
disciplina de canal único: "você não pode contar com a organização das meninas, elas vão mandar de
qualquer forma". Reação e edição exigem abrir eventos que hoje morrem na borda do webhook
(`parser.py` descarta `reactionMessage` explicitamente).

**5. O card não substitui o texto livre.** O parser do card é determinístico (por rótulos, sem
LLM) e tem precedência; não casando, cai no leitor de texto livre que já existe. Duas razões: o
backfill histórico só existe em texto livre, e o telefonista vai esquecer o card.

**6. Comprovante sem ficha aberta não vira venda anônima** — fica retido com **uma** pergunta, o
comportamento que `comprovante.py` já tem.

## Alternativas rejeitadas

- **Ficha vira Venda registrada em estado `prevista`.** Uma tabela a menos, mas mistura combinado
  com recebido no mesmo lugar; toda consulta de receita passaria a depender de filtrar estado, e o
  primeiro `WHERE` esquecido soma dinheiro que não aconteceu.
- **Ficha é só contexto, relida do log de mensagens no pagamento.** As mensagens já são todas
  persistidas, então a informação existe — mas o ❌ fica sem alvo formal, o painel não consegue
  mostrar o que está previsto, e a rotina da manhã não consegue cobrar "a ficha do Igor rolou?".
- **Fabricar Atendimento de verdade** (revogando o ADR-0043). O cliente viu a tela de Atendimentos
  na demo, mas os três motivos do ADR-0043 seguem intactos: `atendimentos` exige `cliente_id` e
  `conversa_id` NOT NULL com Cliente = telefone E.164 (o card só tem nome, e o WhatsApp do cliente
  só é preenchido em videochamada), e proíbe duas modelos no mesmo atendimento — que é exatamente
  o caso da festinha.

## Consequências

- O webhook passa a tratar dois eventos novos (reação e edição), e **só para JIDs de Grupo
  financeiro** — o agente de venda continua descartando reação, que para ele é ruído.
- Existe um objeto que envelhece sem desfecho: ficha aberta há dias. Vira pendência da rotina da
  manhã ("o do Igor de ontem rolou?"), nunca trava nada.
- O parser do card e o leitor de texto livre são dois caminhos de leitura de anúncio para manter.
- A Venda registrada ganha `ficha_id` opcional: o backfill e o texto livre continuam produzindo
  venda sem ficha.
