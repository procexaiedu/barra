## Sintoma

Atendimento **#9** da Tatiane (cliente 5519992202383, 21/07). O cliente sondou "Posso te procurar aí amanhã de dia / Vou umas 13 / Pode ser / **Te chamo antes**" — e fechou com "O normal o que seria / **Ainda não** / **Estou analisando**". A IA tratou como fechado e insistiu 3 turnos seguidos:

- trace `97bc5c11f0913b552682bfa364d0a029` → "Fechamos o completo então amor / 13h amanhã confirmado"
- trace `e8bc8e1a924b603a6366cdbabf5524ed` → "**Sim amor, fechamos o completo 800**" (contradizendo o "Ainda não" explícito)
- trace `dbf1e1f56134ea1892c4bf5043e00bd7` → "Então tá amor / 13h amanhã confirmado, me chama quando sair"

O cliente foi embora irritado ("Não fechei, disse que chamo por aqui. Bjsss. Tiau" às 20:33). O atendimento já estava em `Aguardando_confirmacao`, e **7 min depois** (20:41) o cancelamento automático do piloto (ADR-0033) disparou a desculpa "amor desculpa, surgiu um imprevisto aqui e não vou conseguir hoje te chamo outro dia?" — para um cliente que já tinha declarado que NÃO fechou.

## Esperado (Fernando, 21/07 21:38)

> "Surgiu um imprevisto sem antes ter realmente fechado. Assim não dá pra saber se realmente iria marcar.. tem que marcar o horário e deixar chegar próximo, quando o cliente falar que estiver a caminho aí você cancela. **Não cancelar antes de realmente marcar.**"

Ou seja, dois pedidos:
1. **Não insistir num fechamento que o cliente negou** — "Ainda não"/"Estou analisando" é retração: a IA deveria recuar ("tranquilo amor, me avisa 🥰"), não reafirmar "fechamos".
2. **Mudar o gatilho do cancelamento do piloto**: deixar o agendamento se consolidar e cancelar só **perto do horário / quando o cliente avisar que está a caminho** (Aviso de saída) — o objetivo do piloto é medir se o cliente iria marcar de verdade, e cancelar 10 min depois do crava mata o sinal.

**PERGUNTAS PRO FERNANDO** (não inventar — decidir antes de implementar):
- No **externo**, o Pix de deslocamento é pedido assim que o horário crava. O invariante do ADR-0033 é "cancelar ANTES de qualquer Pix ser pedido/pago". Mantém o cancelamento cedo só no externo, ou suprime a solicitação de Pix no piloto e cancela perto do horário também?
- No **interno**, se o cliente nunca manda o "estou indo": cancela em que momento? (no horário combinado? X min antes?)

## Contexto interno (trace)

- extração dos turnos de insistência: `intencao=agendamento, urgencia=agendado, data_desejada=2026-07-22, horario_desejado=13:00, valor_acordado=800, duracao_horas=1` — o "Ainda não / Estou analisando" **não reverteu** nenhum slot; o belief seguiu dizendo "combinado" e a conduta seguiu o belief.
- estado: `Aguardando_confirmacao` desde ~20:31 (`aguardando_confirmacao_em` carimbado); cancelado às 20:41 → `Perdido` (`outro`, "cancelamento automático — piloto de teste"), `ia_pausada=true`.
- `extracao_forcada=true` em todos os turnos.

## Hipótese de código (confirmar)

- ~ `workers/timeouts.py::cancelar_piloto_teste` (L262-270): gatilho é `aguardando_confirmacao_em < now() - 10 minutes`. Trocar o gatilho para perto de `bloqueios.inicio` e/ou o evento de Aviso de saída, respeitando o invariante do Pix no externo (ver PERGUNTA).
- ~ extração/belief (`agente/ferramentas/extracao.py` + prompt de extração): não há tratamento de **retração** — "Ainda não/Estou analisando" depois de um crava deveria limpar `horario_desejado`/`valor_acordado` (ou ao menos impedir a transição pra `Aguardando_confirmacao` / reverter a conduta de "confirmado").
- ~ `agente/prompts/regras.md.j2` (empurrão de fechamento em L41): o empurrão sim/não não cobre o caso "cliente disse que ainda não fechou" — falta instrução explícita de recuo pós-objeção (não reafirmar "fechamos" após um "não fechei").

trace_ids: `97bc5c11f0913b552682bfa364d0a029`, `e8bc8e1a924b603a6366cdbabf5524ed`, `dbf1e1f56134ea1892c4bf5043e00bd7`

<!-- feedback-rig: {"message_id": "3A84FB041B61ACDE01FE", "remote_jid": "120363426757729499@g.us", "texto": "Surgiu um imprevisto sem antes ter realmente fechado."} -->
