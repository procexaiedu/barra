# 08 — Cards de combo nas Coordenações

**O que construir:** as mulheres precisam saber o que foi combinado em nome delas. Dois cards distintos:

- Na **Coordenação por modelo** da **Modelo do canal**: o combo inteiro — quem vem, que horas, onde, quanto cada uma. É ela quem coordena as outras (a coordenação entre as mulheres é humana, fora do sistema), então ela precisa da visão completa.
- Na Coordenação de cada **Modelo convidada**: o atendimento **dela** — horário, endereço, valor — e quem é a modelo do canal, para ela saber com quem falar.

A convidada descobre o combo por esse card e por nenhum outro caminho: ela nunca conversa com o cliente e o contato dele não chega até ela.

Segue a gramática de cards já existente e a idempotência por `card_message_id`. Não cria estado novo — o card é informativo e o estado continua em cada **Atendimento**.

**Bloqueado por:** 07 (precisa haver combo) e 03 (enquanto as modelos dividirem o mesmo grupo, os dois cards caem no mesmo lugar e o card por convidada não existe de fato).

**Status:** ready-for-agent

- [ ] Card do combo entregue na Coordenação da modelo do canal, com todas as participantes, horário, endereço e valores
- [ ] Card individual entregue na Coordenação de cada convidada, com o atendimento dela e a identificação do canal
- [ ] Idempotência por `card_message_id` respeitada — reprocessar não duplica
- [ ] Card não vaza dado do cliente com outra modelo (só o necessário do encontro)
- [ ] Falha de envio de um card não impede os demais nem desfaz o combo
- [ ] Coberto por teste no molde de `test_enviar_card.py`
