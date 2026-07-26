# 11 — Combo externo

**O que construir:** o caso que originou tudo — o grupo está hospedado em outro hotel e **elas se deslocam** até ele. É o cenário do #36: quatro homens no `Hotel Vitória Express`, a modelo no `Vitória Hotel Residence Newport`.

Muda duas coisas em relação ao interno (ticket 06):

1. **Elegibilidade por região, não por endereço.** No interno o filtro é o mesmo endereço de encontro; no externo isso não faz sentido — o encontro é no local do cliente. O filtro passa a ser a região/geo (`latitude`/`longitude`/`place_id` já existem em `modelos`).
2. **Pix de deslocamento.** Esta é a parte travada.

**Pendência aberta — decisão do Fernando.** O código restringe as saídas, então isto não é preferência de UX: a chave Pix é **por modelo** (`modelos.chave_pix`) e o OCR do comprovante **valida a chave extraída contra a chave daquela modelo**. Logo, um Pix único somado na chave do canal **bate no atendimento dela e falha nos das convidadas** — os deles ficariam em revisão para sempre. As três saídas, com custos diferentes:

- **N Pix, uma chave por modelo** — trilho atual intacto, zero mudança no validador; o cliente recebe N chaves e paga N vezes, com atrito alto justo depois de ter topado tudo.
- **Pix único somado na chave do canal** — melhor UX; exige mudar o matching do OCR e definir como o dinheiro chega às outras, o que hoje não existe.
- **Um único deslocamento, elas indo no mesmo carro** — mais barato e bom argumento de venda; só se sustenta se saírem do mesmo lugar, o que **obriga o filtro a exigir mesma região de origem** e estreita o pool.

Nada aqui deve ser implementado antes da decisão. O ticket existe para que o externo não seja esquecido — e para deixar registrado que **o interno não depende disto** e pode ir ao ar primeiro.

**Bloqueado por:** 07 (materialização), 02 (worker não pode prometer Pix sem chave), e a decisão de Pix do Fernando.

**Status:** ready-for-agent

- [ ] Decisão de Pix registrada antes de qualquer código
- [ ] Elegibilidade externa filtra por região/geo em vez de mesmo endereço
- [ ] Combo externo cria os atendimentos com o tipo correto e o endereço do cliente
- [ ] Pix solicitado conforme a decisão, com o comprovante batendo no atendimento certo
- [ ] Nenhum atendimento do combo fica travado por Pix — o invariante "nunca trava por Pix" continua valendo
- [ ] Testes `needs_db` cobrindo o caminho externo ponta a ponta
