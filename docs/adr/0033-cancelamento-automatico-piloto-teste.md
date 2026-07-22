---
status: accepted
---

# ADR-0033 — Cancelamento automático de segurança do piloto de teste

## Contexto

O piloto de colocação da IA em produção (reunião 2026-07-20) roda sem uma modelo real: tráfego de anúncio genérico cai num WhatsApp de teste, e nenhum encontro físico deve de fato acontecer (ver ADR sobre o piloto sem modelo específica — decidido em grilling, a modelo cadastrada é fictícia/de teste). Sem uma salvaguarda, um cliente real poderia negociar até o horário combinado — e potencialmente enviar o **Pix de deslocamento** — para um encontro que a operação nunca pretende cumprir. Risco real de dinheiro trocando de mãos por um serviço inexistente, e de má experiência (cliente real deixado esperando).

## Decisão

> **Emenda 2026-07-22 (feedback do Fernando no 1º dia real do piloto, 21/07 21:36):** cancelar 10min
> após o crava matava o sinal que o piloto existe pra medir — "assim não dá pra saber se realmente
> iria marcar; tem que marcar o horário e deixar chegar próximo, quando o cliente falar que estiver
> a caminho aí você cancela". O gatilho passa a ser **por tipo**:
>
> - **interno** (sem Pix em jogo): deixa o agendamento consolidar; cancela no **Aviso de saída**
>   ("estou indo") OU perto do horário combinado (`bloqueios.inicio − piloto_cancela_antes_min`,
>   ref. 15min, configurável sem deploy) — o que vier primeiro. Como o Aviso de saída é opcional e
>   a **Foto de portaria** transiciona automático para `Em_execucao`, o cron também cancela
>   `Em_execucao` interno ainda não processado (a desculpa sai na hora, mesmo com IA já pausada).
> - **externo/remoto**: mantém o timer original de 10min pós-`Aguardando_confirmacao`, porque
>   nesses tipos o crava dispara a solicitação de Pix (deslocamento no externo, valor da chamada no
>   remoto) e o invariante é cancelar antes de dinheiro trocar de mãos. **Pendência aberta com o
>   Fernando:** suprimir a solicitação de Pix durante o piloto (permitindo cancelar perto do horário
>   também no externo) ou manter o cancelamento cedo. Nota de honestidade: a solicitação sai NO
>   crava, então mesmo o timer de 10min dispara com o pedido de Pix já enviado — o que o timer
>   garante é cancelar antes do fluxo avançar (comprovante → `Confirmado`); cliente que paga em
>   <10min escapa do funil (furo pré-existente, aceito no piloto).
>
> O restante do ADR (ao disparar, escopo, reversibilidade) permanece.

- **Gatilho (original, superseded pela emenda acima):** quando o Atendimento entra em `Aguardando_confirmacao` (horário combinado cravado) — **antes** de qualquer Pix de deslocamento ser solicitado. Não espera `Confirmado`.
- **Timer (original, superseded pela emenda acima):** 10 minutos a partir do gatilho (worker agendado, mesmo padrão de outros timeouts determinísticos do domínio — Reengajamento, timeout interno ADR-0024). Com a antecedência mínima de agenda (`agenda_buffer_min`, ref. 30min, ADR-0025), o timer dispara antes de qualquer horário combinado legítimo chegar — a confirmar contra o valor real de produção antes do go-live.
- **Ao disparar:**
  1. Envia ao cliente uma desculpa genérica de cancelamento, sorteada de um pool pequeno (evita padrão idêntico repetido — mesmo risco de denúncia/bloqueio de WhatsApp por número não aquecido, discutido na reunião).
  2. Registra o Atendimento como `Perdido`, motivo `outro`, observação "cancelamento automático — piloto de teste".
  3. Pausa a IA para aquele Atendimento (Handoff manual, ADR-0032) — evita a IA remarcar com o mesmo cliente na mesma janela.
- **Escopo:** vale para todo Atendimento do piloto enquanto a flag estiver ligada — não é opt-in por atendimento.
- **Reversibilidade:** controlado por flag de settings, ligada por padrão agora, desligável sem deploy quando o piloto evoluir para atendimento real com modelo de verdade.

## Alternativas rejeitadas

- **Cancelar só depois de `Confirmado` (pós-Pix).** Rejeitada — expõe a operação ao risco de receber (e ter que devolver) dinheiro real de um cliente de teste.
- **Desculpa fixa única.** Rejeitada — cria um padrão idêntico detectável, mesmo risco de denúncia levantado na reunião sobre aquecimento de número.
- **Mecanismo permanente, sem flag de desligar.** Rejeitada — só faz sentido durante a fase de teste; manter ligado em produção real cancelaria todo atendimento legítimo.

## Consequências

- Novo worker/cron análogo aos já existentes (Reengajamento, Lembrete de fechamento) — dispara a partir da entrada em `Aguardando_confirmacao`, checa a flag de settings antes de agir.
- Reusa o mecanismo de Handoff manual (ADR-0032, comando `pausar_ia`) e a taxonomia de Motivo de perda já existente (`outro` + observação livre).
- CONTEXT.md ganha o termo **Cancelamento automático do piloto**.
- O valor de 10 minutos assume que `agenda_buffer_min` real de produção é ≥10min de folga — checar antes do go-live, não travar como garantido só pela documentação.
