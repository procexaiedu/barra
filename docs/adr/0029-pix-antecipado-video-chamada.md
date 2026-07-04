---
status: accepted
---

# Pix antecipado da vídeo chamada, no trilho do Pix de deslocamento (emenda ao ADR 0021)

> **Nota (2026-07-04):** decisão tomada pelo dev na sessão do BP_GERAL v2; **ratificação do
> Fernando pendente** — o ADR 0021 registrava o pagamento antecipado como "adiado para P1,
> decisão financeira do Fernando". Se Fernando divergir, esta emenda é revertida (a mudança é
> concentrada: gate no service, branch no `_atualizar_pix`, valor esperado no conferidor,
> 2 cards e a conduta no prompt).

O ADR 0021 deixou a vídeo chamada **sem fluxo financeiro no P0**: "a modelo combina e recebe o
pagamento do jeito dela. Sem Pix, sem antecipação". A conduta do BP_GERAL v2, porém, vende o
degrau pago do anti-golpe com **"pix primeiro"** — e a IA não tinha como cumprir a promessa: o
sistema só anexa chave Pix no fluxo de deslocamento externo. Um cliente que topasse pagar não
tinha para onde pagar; a IA travaria ou inventaria chave. Prompt e mecânica precisam andar
juntos: ou o "pix primeiro" saía do prompt, ou o sistema passava a mandar o Pix. Decidiu-se o
segundo — o remoto passa a **antecipar o valor da chamada** pelo mesmo trilho determinístico do
Pix de deslocamento.

## Decisões

- **Solicitação determinística no trilho existente** (`_solicitar_pix_deslocamento_se_aplicavel`,
  `dominio/atendimentos/service.py`): o gate estende de `externo` para `externo | remoto`, com a
  condição extra `valor_acordado IS NOT NULL` no remoto — sem valor acordado não há o que pedir;
  como o bloco roda **todo turno** (independente de transição), a solicitação sai no turno em que
  a extração gravar o valor. **Valor do Pix = `valor_acordado`** (o preço da chamada), não o fixo
  de deslocamento.

- **A chave continua fora do LLM.** Mecânica idêntica ao deslocamento: `pix_solicitado=True` +
  `pix_valor` no resultado da tool; o coordenador anexa a bolha determinística com chave/titular
  lidos fresh do cadastro. Zero mudança no coordenador (ele já lê `pix_valor` do resultado).

- **Comprovante NÃO transiciona nem pausa.** `_atualizar_pix` para remoto só grava `pix_status`
  (+ evento). `Confirmado` continua significando "Pix de deslocamento recebido" (externo); o
  remoto segue `Aguardando_confirmacao → Em_execucao` **pelo cron na hora da chamada** (ADR 0021,
  intocado) — o cliente segue conversando com a IA até lá. **Nunca trava por Pix**: o cron
  dispara na hora mesmo sem comprovante; a modelo decide fazer a chamada olhando o card.

- **Roteador de mídia: sem mudança.** O branch de comprovante já chaveia por
  `Aguardando_confirmacao + pix_status='aguardando'`, tipo-agnóstico.

- **Conferidor OCR: valor esperado por atendimento.** `valor_acordado` quando remoto; o fixo de
  `settings.pix_deslocamento_valor` no externo (comparação de "valor menor que o esperado" vira
  divergência `em_revisao`, como hoje).

- **Cards adaptados.** Comprovante do remoto ganha template próprio (`pix_remoto.md.j2` — sem
  "saída"/Uber/endereço, fala do pagamento da chamada); o card "Hora da vídeo chamada"
  (`video_chamada.md.j2`) passa a exibir o `pix_status` (recebido / duvidoso / não recebido)
  para a modelo decidir a chamada informada.

- **Sem migration.** `pix_status`, `valor_acordado` e `comprovantes_pix` já cobrem o fluxo.

## Considered Options

- **Transicionar remoto para `Confirmado` no comprovante (paridade total com externo).**
  Rejeitado: pausaria a IA antes da hora (o cliente ainda conversa até a chamada) e diluiria o
  significado de `Confirmado`; a pausa do remoto pertence ao cron do horário (ADR 0021).

- **Valor fixo, como o deslocamento.** Rejeitado: o Pix do remoto **é o pagamento do serviço**;
  valor fixo descolaria da tabela da modelo e criaria reconciliação manual em todo fechamento.

- **Aguardar o P1 / a decisão do Fernando (manter ADR 0021).** Rejeitado nesta emenda: o
  BP_GERAL v2 já vende "pix primeiro" no anti-golpe; deixar o prompt prometendo o que o sistema
  não cumpre é pior que antecipar a decisão com reversão barata (ver nota).

- **Tirar o "pix primeiro" do prompt (sem prova paga funcional).** Rejeitado: o degrau pago é a
  resposta padrão da operação a "é golpe?" — sem ele, sobra só foto e inversão de risco.

## Consequences

- **CONTEXT.md atualizado**: remoto deixa de ser "sem Pix" e passa a "sem Pix de
  **deslocamento**; o **valor da chamada** é antecipado via Pix, sem gatear transição".
- O comprovante do remoto entra na **mesma fila assíncrona** de revisão de Fernando quando
  duvidoso, sem travar (paridade com o deslocamento).
- `Fechado` do remoto continua nascendo do **Registro de resultado** (Valor final); o Pix
  antecipado não fecha sozinho — se o valor final divergir do antecipado, a reconciliação é
  manual no painel (mesma regra de qualquer `Fechado`).
- O degrau anti-golpe ("video chamada, pix primeiro") passa a ser executável de ponta a ponta:
  a extração registra `remoto` + horário + valor, o sistema anexa a chave e o cron pausa na hora.
- **Ratificação do Fernando pendente** (ver nota do topo); até lá o piloto observa o fluxo.
