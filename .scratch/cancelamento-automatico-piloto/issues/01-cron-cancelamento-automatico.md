# 01 — Cron de cancelamento automático de segurança do piloto

**What to build:** 10 minutos depois de um Atendimento entrar em `Aguardando_confirmacao` (horário combinado cravado, antes de qualquer Pix ser pedido), o sistema cancela automaticamente: manda uma desculpa genérica variada ao cliente, marca o Atendimento como `Perdido` com motivo e observação de auditoria, e pausa a IA para aquele Atendimento. Controlado por uma flag de settings, desligável sem deploy.

**Blocked by:** `handoff-manual-operador` ticket 01 (comando `pausar_ia` na porta única de comandos operacionais) — este ticket chama esse comando para pausar a IA após o cancelamento.

**Status:** ready-for-agent

- [ ] Novo cron determinístico segue o mesmo padrão dos crons de timeout já existentes (seleção atômica com trava contra execução concorrente, idempotente entre execuções).
- [ ] Seleciona atendimentos em `Aguardando_confirmacao` com horário combinado cravado há mais de 10 minutos, ainda não processados por este cron.
- [ ] Envia ao cliente uma desculpa genérica sorteada de um pool de pelo menos 3 frases distintas (nunca sempre a mesma).
- [ ] Marca o atendimento como `Perdido`, com motivo `outro` e uma observação identificando que foi um cancelamento automático do piloto (distinguível de uma perda comercial real no histórico).
- [ ] Pausa a IA para aquele atendimento específico via o comando `pausar_ia`.
- [ ] Flag de settings liga/desliga o mecanismo inteiro sem precisar de deploy; desligada, o cron não faz nada.
- [ ] Cron registrado no worker com um intervalo curto o suficiente para não perder a janela dos 10 minutos.
- [ ] Testes cobrindo: atendimento processado corretamente após 10min; atendimento com menos de 10min não é tocado; atendimento já processado não é reprocessado; flag desligada não cancela nada.

Ver spec: `docs/specs/0004-cancelamento-automatico-piloto.md` (issue [#97](https://github.com/procexaiedu/barra/issues/97)) e ADR-0033.

**Nota:** confirmar o valor real de `agenda_buffer_min` em produção antes do go-live — os 10 minutos do timer assumem folga suficiente antes do menor horário combinado possível.
