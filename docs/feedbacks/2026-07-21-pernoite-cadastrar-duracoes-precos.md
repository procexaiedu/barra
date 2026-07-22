## Sintoma

Atendimento **#10** da Tatiane (cliente 5519989375454, 21/07 ~21:30). Cliente: "gostaria de ficar uma noite com você / tem a possibilidade? pernoite?". A IA negou o produto — e se contradisse entre bolhas por corrida de dois turnos concorrentes:

- trace `aba07506d268fbd5fde9d406014128dc` (21:30:50) → "Pernoite não tenho pacote fechado, **posso combinar 3h ou mais**"
- trace `aefe5577bf68e491b4727e83e7e956a8` (21:31:04, turno paralelo da rajada de msgs) → "Pernoite não tenho esse pacote / **Só 1h mesmo**"
- trace `61848101917b7449b983…` → "Consigo fazer até 3h no máximo / 21h às 02h são 5h, não consigo esse período não"

O cliente queria 21h–02h e chegou a oferecer "fecha 1500k 5 horas amor / dinheiro ou pix o que preferir" — demanda real por pernoite que a IA não tinha como vender.

## Esperado (Fernando, 21/07 21:38)

> "**Pernoite tem valor sim** / Normalmente o pernoite tem duração de **6, 8h / Ou 12h**"

Pernoite é produto vendível, nas durações 6h, 8h ou 12h.

**PERGUNTAS PRO FERNANDO:**
- Preços do pernoite da Tatiane (6h / 8h / 12h)? E as durações intermediárias (2h, 3h) — cadastramos também com que preços? (relacionado: piso de R$300/h da issue do "3h 800")
- O CONTEXT.md fixa "Pernoite = 12h é a maior" — com 6/8/12h, "pernoite" vira faixa, não uma duração única. Confirmar como fica o vocabulário.

## Contexto interno (trace)

- extração (`aba07506`/`aefe5577`): `intencao=agendamento, urgencia=indefinido, tipo_atendimento=interno` — a intenção de pernoite foi capturada, mas não havia produto na tabela.
- Catálogo real (banco de prod, 21/07): Tatiane só tem **Completo 1h R$800** e **Normal 1h R$400** em `modelo_programas`. Durações globais (`duracoes`): 1h, 2h, 3h, 4h, Pernoite(12h) e uma "12 horas" duplicada (ordem 999) — **não existem 6h nem 8h**.
- A contradição "3h ou mais" vs "Só 1h mesmo" saiu de dois traces concorrentes (debounce não segurou a rajada de 3 mensagens) — sintoma secundário, mas visível pro cliente.

## Hipótese de código (confirmar)

- ~ **Cadastro, não prompt**: criar durações globais 6h/8h (migration `infra/sql/` — atenção à "12 horas" duplicada da `duracoes`) e as combinações programa×duração da Tatiane com preço (painel ou `barra_definir_preco_programa`). O prompt (`<sobe_o_ticket>`, `girias_do_cliente` L58) já sabe vender pernoite "da sua tabela" — o que falta é a tabela.
- ~ Corrida de turnos concorrentes na rajada: dois turnos responderam a mesma sequência (`aba07506` responde "vamos marcar", `aefe5577` roda 14s depois) — investigar o debounce/cancel-on-new-message do worker.

trace_ids: `aba07506d268fbd5fde9d406014128dc`, `aefe5577bf68e491b4727e83e7e956a8`

<!-- feedback-rig: {"message_id": "3AF5C345EC8A5267B3E8", "remote_jid": "120363426757729499@g.us", "texto": "Pernoite tem valor sim"} -->

## Diagnóstico da corrida de turnos (sessão 22/07, traces completos)

Confirmado nos traces `aba07506…` (A) e `aefe5577…` (B):

- **A** (00:30:50Z) processou "vamos marcar"; grafo terminou 00:30:55; resposta em 3 bolhas
  ("Ficaria muito feliz" / "Pernoite não tenho pacote fechado, posso combinar 3h ou mais" /
  "Qual seria o horário que você pensou ?") saiu pelo `enviar_turno` com delays de
  reading/typing — entrega se estende por ~10-20s após o grafo.
- **B** (span 00:31:00.7, drain do coordenador pegando o pending "gostaria de ficar uma noite
  com você") rodou `prepare_context` às 00:31:04 — nesse instante **só a 1ª bolha de A estava
  persistida**, e o histórico de B a rotulou como `[mensagem manual da modelo]: Ficaria muito
  feliz` (não como fala da IA). B respondeu "Pernoite não tenho esse pacote amor / Só 1h mesmo"
  sem saber que A ainda ia entregar o "posso combinar 3h ou mais"; os envios de A e B
  intercalaram no WhatsApp (A2, B1, A3, B2) — a contradição que o cliente viu.

Dois defeitos distintos:
1. **O drain inicia o turno seguinte sem esperar o envio do anterior terminar.** O
   cancel-on-new-message (por chunk, `turno_atual`) não abortou A2/A3 — o set de
   `turno_atual=B` acontece dentro do processar_turno de B, e os chunks de A passaram na
   checagem antes disso. Mesmo quando aborta, B segue respondendo por cima de uma resposta
   que o cliente viu pela metade e que não está no contexto de B.
2. **Bolha da própria IA lida como "mensagem manual da modelo"** quando o histórico é montado
   no meio do envio — o classificador de originador (IA × modelo, pelo envio real) perde a
   corrida com o echo `fromMe` do webhook. Contamina a conduta do turno B (o modelo acha que a
   humana já interveio) e é provavelmente o mesmo mecanismo da "âncora torta" do achado (c).

Direção de fix sugerida (não implementado — mexe em concorrência do coordenador, pedir review
langgraph): antes de invocar o grafo para um novo turno da mesma conversa, o drain espera o
`enviar_turno` do turno anterior concluir (flag redis `envio_em_curso:{conversa_id}` com
timeout), garantindo histórico completo e envios serializados. Alternativa paliativa que estava
no working tree (defer_s 12→180 + TTLs) coalesce a rajada ao custo de +3min de latência em TODA
resposta — trade-off ruim pra venda quente; não recomendada como está.
