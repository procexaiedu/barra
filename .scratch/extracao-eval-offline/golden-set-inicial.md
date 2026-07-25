# Golden set inicial — rotulagem humana

Status: ready-for-agent

Semente do golden set da bancada offline (`spec.md`). Rotulado à mão em 25/07 a partir das conversas
reais de produção (banco `barravips`, tráfego de 21–24/07, uma modelo, piloto com cancelamento
automático ligado).

O que está aqui é **o que o sistema deveria ter registrado**, não o que ele registrou. A coluna
"gravado" preserva o comportamento observado para servir de baseline.

## Aceite de valor

Fala do cliente imediatamente anterior ao turno em que o extrator marcou o aceite.

| Atendimento | última(s) fala(s) do cliente antes do carimbo | gravado | rótulo | por quê |
|---|---|---|---|---|
| #41 | "quanto PG \| obrigado" | true | **false** | cortesia; a própria descrição do campo já dizia que agradecer não é aceitar |
| #38 | falas sobre fetiche, nenhuma menção a preço | true | **false** | nada relativo a valor na mesa |
| #34 | "Tipo 18h, 18h15" (após "Consigo às 17:30") | true | **true** | está marcando o encontro sobre o valor cotado |
| #27 | "Hoje não consigo, te mando msg mais pra frente" | true | **false** | adiamento explícito |
| #24 | "Tem fotos \| E liberal? \| Aonde atende" | true | **false** | sondagem; não houve proposta recusada antes que tornasse pergunta de logística um sim |
| #21 | "Le de novo com calma gata \| Acho que é melhor" | true | **false** | não trata de valor |
| #20 | "Quero muito ir mas nao quero te ofender... tenho que esperar começo do mês" | true | **false** | adiamento explícito |
| #19 | "Hummm \| Pretendo...mais para o final do dia" | true | **false** | hesitação; depois o cliente responde "Não" ao pedido de confirmação |
| #9 | "É o mesmo vl \| O normal o que seria" | true | **false** | pergunta sobre preço |
| #8 | "Rua gata seria do seu local dlc ?" | true | **false** | pergunta de logística sem proposta recusada antes |

Baseline: **1 verdadeiro em 10**.

## Recuo (rebaixamento esperado do aceite)

| Atendimento | fala do cliente | classe | rebaixa? |
|---|---|---|---|
| #19 | IA: "Podemos confirmar 18h ?" → cliente: "Não" | negativa correferenciada | **sim** |
| #20 | "tenho que esperar começo do mês. Pode ser?" | recuo autônomo | **sim** |
| #27 | "Hoje não consigo, te mando msg mais pra frente" | recuo autônomo | **sim** |
| #34 | "Perfeito, vou te avisando então" | lista negativa — quer, só não manda no relógio | **não** |
| #24 | IA: "Campinas?" → cliente: "Não conheço" | negativa sem correferência de fechamento | **não** |

## Horário evidenciado

| Atendimento | evidência na conversa | valor gravado | origem do número | rótulo |
|---|---|---|---|---|
| #34 | "Você tem horário amanhã? / No final de tarde" → IA "Consigo às 17:30" → "Tipo 18h, 18h15" → IA "Posso confirmar às 18h" → "Perfeito" | 18:00 | extrator | **evidenciado** |
| #24 | IA: "Que horas você pensa em vir amor ?" → "Umas 16 horas" | 16:00 | extrator | **evidenciado** |
| #35 | IA: "Seria agora ?" → cliente: "sim" | 02:25 | fallback de tempo imediato | **evidenciado** (número sintético, intenção real) |
| #25 | IA: "Seria agora ?" → cliente muda de assunto ("Atende mas de um?") | 02:00 | fallback, depois ecoado pelo extrator em 3 turnos | **não evidenciado** |

## Intenção

| Atendimento | estado dos campos | gravado | rótulo |
|---|---|---|---|
| #34 | tipo interno, horário 18:00 evidenciado, aceite real | cotacao | **agendamento** |
| #24 | tipo interno, horário 16:00 evidenciado | agendamento | agendamento |
| #35 | tipo interno, horário evidenciado via sondagem aceita | cotacao | **agendamento** |
| #25 | horário não evidenciado; cliente nunca respondeu a sondagem | cotacao | cotacao |
| #19 | sem horário; cliente recuou | cotacao | cotacao |

## Eco (campo reafirmado sem evidência no turno)

| Atendimento | campo | turnos em que foi reenviado | fala do cliente nesses turnos |
|---|---|---|---|
| #41 | tipo_atendimento = interno | todos | "quanto PG \| obrigado", "não vou não obrigado", "vc melhora no valor eu vou", "atendimento so oral penetração ou com anal também" |
| #34 | tipo_atendimento = interno | todos | "Você faz chamada de vídeo também ?", "Caso eu tenha 30min rola também ?" |
| #25 | horario_desejado = 02:00 | 3 turnos após o fallback gravar | nenhuma menção a horário |

Rótulo para todos: **não reenviar** (nenhum par novo no turno).

## Medidas de baseline no banco (24/07)

Para comparação depois das mudanças:

- redundância por campo: tipo 81%, data 81%, horário 78%, duração 77%, valor 73%, intenção 71%
- extrações sem nenhum par novo em relação à anterior: 35%
- gravações de valor cujo número não aparece em nenhuma mensagem dos 20 min anteriores: 16 de 44
- Atendimentos com aceite marcado e intenção abaixo de agendamento: 9
- Atendimentos com `intencao = 'agendamento'`: 4 de 44

## Comments

Rotulagem produzida durante a revisão de arquitetura do nó `extrair` (25/07), a partir da leitura
integral das Conversas cliente dos Atendimentos #8, #9, #19, #20, #21, #24, #25, #27, #34, #35, #38
e #41. Falta completar com amostra aleatória de turnos decisivos que não estão nos modos de falha
conhecidos, para o conjunto não medir apenas o que já se sabe estar quebrado.
