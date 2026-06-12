# Decisões de produto — o que o loop NÃO pode reverter (C3 do flywheel)

> Invariante #4 do envelope. São decisões **do Fernando**, não bugs a "consertar". Um loop que
> otimiza conversão tenderia a revertê-las (recusar videocall parece perder venda; não parcelar
> parece perder venda; o piso parece perder venda) — e estaria errado. Qualquer fix do loop que
> mude o comportamento abaixo é **bloqueante**: reverte. A fonte (file:line) é a autoridade; se uma
> decisão mudar, muda-se a fonte primeiro, não o loop.

## Núcleo (as que um loop de conversão tentaria reverter)

### D1 — Videocall: a IA recusa
- **Decisão:** a IA **não faz videochamada**. Responde a FAQ negativa ("video chamada eu nao faço,
  mas mando fotos se quiser") e redireciona para o presencial. **Não cota, não pede Pix de R$250,
  não escala** — é resposta direta de FAQ.
- **Fonte:** `api/src/barra/agente/prompts/faq.md:40-41`; decisão 2026-05-27.
- **Sinal de reversão (proibido):** a IA cotar valor de videocall, pedir Pix de videocall, escalar
  por videocall, ou prometer/detalhar o que "rola na vídeo". A modelo real cobra R$250 off-IA; **a
  IA não vende**.
- **Verificado por:** cenário `fixo_004_videocall_cartao` (sim) + juiz/grader no corpus.

### D2 — Cartão: oferece com taxa, sem parcelamento
- **Decisão:** a IA **oferece cartão** (a modelo leva a maquininha), informa a **taxa de ~10%** da
  maquininha; pix/dinheiro saem sem taxa. **Parcelamento NÃO é oferecido/cotado** (deferido ao P1).
- **Fonte:** `api/src/barra/agente/prompts/faq.md:35-36`; decisão 2026-06-02 que reverte a de
  2026-05-27; ADR 0013 (taxa de cartão).
- **Sinal de reversão (proibido):** a IA oferecer/cotar **parcelamento**; ou cobrar a taxa de cartão
  sobre o **Pix de deslocamento**; ou entrar a taxa na base de repasse/comissão; ou (regressão à
  decisão antiga) recusar cartão ("só pix amor").

### D3 — Piso de desconto: abaixo do piso escala, não negocia
- **Decisão:** a IA concede **um único** Desconto de fechamento até o **Piso de desconto**; abaixo
  do piso (ou quando não concede), `escalar(motivo="fora_de_oferta")` — **não regateia, não baixa
  mais**. Oferecer pacote maior com preço/hora menor (upsell de tabela) **não** é desconto.
- **Fonte:** `api/src/barra/agente/prompts/regras.md.j2:184,187,294`; ADR 0004; CONTEXT.md
  "Desconto de fechamento" / "Piso de desconto".
- **Sinal de reversão (proibido):** a IA negociar abaixo do piso para fechar; conceder mais de um
  desconto por conversa; ou expor o valor do piso ao cliente.

## Relacionadas (máquina de estados / conduta — também invariantes)

### D4 — Nunca trava por Pix
- **Decisão:** o comprovante de Pix **sempre** faz o atendimento avançar; divergência marca
  `pix_status` (informativo) + fila assíncrona de Fernando, nunca bloqueio.
- **Fonte:** CONTEXT.md "Pix de deslocamento"; também invariante de máquina de estados (C3 #3).
- **Sinal de reversão (proibido):** condicionar a confirmação à validação do Pix; handoff síncrono
  esperando Fernando por Pix duvidoso.

### D5 — Não revela bloqueio de agenda
- **Decisão:** horário em bloqueio → recusa com **desculpa pessoal** coerente (salão, jantar), oferece
  outra janela; **nunca revela que está com outro cliente**. (Fora da Disponibilidade é diferente:
  aí revela a volta e ancora.)
- **Fonte:** CONTEXT.md "Agenda — comportamento da IA"; `regras.md.j2`.
- **Sinal de reversão (proibido):** a IA dizer/insinuar que está com outro cliente, ou parar de
  responder em vez de oferecer outra janela.
