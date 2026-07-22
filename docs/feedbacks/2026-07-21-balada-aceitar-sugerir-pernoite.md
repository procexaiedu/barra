## Sintoma

Atendimento **#10** da Tatiane (cliente 5519989375454, 21/07 ~21:28). Cliente perguntou "acompanha em balada?" e depois detalhou: "terá um happy hour na minha empresa esse final de semana, vamos em um restaurante e depois sairemos para um barzinho… gostaria que me acompanhasse". A IA recusou duas vezes:

- trace `a0a68a43cd6e33e4e55e…` → "Não costumo acompanhar em balada não amor / Só encontro no meu local mesmo"
- trace `be0c36fe4b2da0c2179ac3509b4c594e` → "Poxa amor não acompanho em balada nem restaurante não / Só recebo no meu local mesmo"

O cliente aceitou a recusa ("tudo bem") e a conversa seguiu — mas era exatamente o perfil de ticket alto (mesmo cliente depois pediu pernoite e ofereceu R$1.500 por 5h).

## Esperado (Fernando, 21/07 21:38)

> "**Vai pra balada sim**, quando o cliente der essa opção, você sugere o **pernoite**"

Conduta nova: convite social (balada/restaurante/evento) não é recusa — é sinal de compra de período longo; a IA aceita e converte em pernoite.

**PERGUNTAS PRO FERNANDO** (o domínio hoje não modela isso — decidir antes de implementar):
- O encontro que começa em balada/restaurante é **externo** (ela se desloca → Pix de deslocamento/uber)? Ou o Pix não se aplica quando o cliente leva ela pro evento?
- O preço é o do pernoite normal da tabela, ou acompanhamento social tem valor próprio?
- Vale pra toda modelo ou é "coisa dela" (flag por modelo de aceita/não aceita acompanhamento)?

## Contexto interno (trace)

- extração no turno da recusa (`be0c36fe`): `intencao=curiosidade, urgencia=indefinido, tipo_atendimento=interno` — o convite social nem virou sinal de intenção/upsell.
- estado: `Triagem` → depois `Aguardando_confirmacao` na sequência do pernoite; hoje `Perdido` (cancelamento do piloto).
- Tatiane não tem pernoite nem nenhuma duração >1h em `modelo_programas` (só Completo 1h/800 e Normal 1h/400) — sem pacote na tabela, o modelo recusou coerentemente com `<sobe_o_ticket>` ("pernoite **da sua tabela**").

## Hipótese de código (confirmar)

- ~ `agente/prompts/regras.md.j2` `<sobe_o_ticket>` (L62-70): já trata "quer companhia pra jantar/beber" como sinal de período maior/pernoite, mas **não existe conduta pra convite social explícito** (balada/evento/restaurante) — o modelo caiu no default "só recebo no meu local". Falta a regra: convite social → aceita + sugere pernoite.
- ~ Dependência dura do cadastro: sem pernoite em `modelo_programas` (ver issue do pernoite), qualquer regra de prompt continua recusando ou, pior, inventando preço.
- ~ Possível toque no domínio (`tipo_atendimento`/Pix): se acompanhamento social = externo com deslocamento, o fluxo de Pix precisa se aplicar; hoje o eixo interno/externo/remoto não descreve "cliente leva a modelo pra evento" (CONTEXT.md).

trace_ids: `be0c36fe4b2da0c2179ac3509b4c594e` (âncora), `a0a68a43…`

<!-- feedback-rig: {"message_id": "3A9CA821D112DBCBD8E3", "remote_jid": "120363426757729499@g.us", "texto": "Vai pra balada sim , quando o cliente der essa opção, você sugere o pernoite"} -->
