# Cancelamento automático de segurança do piloto de teste

> Issue: [procexaiedu/barra#97](https://github.com/procexaiedu/barra/issues/97)

## Problem Statement

O piloto de colocação da IA em produção roda sem uma modelo real (anúncio genérico, sem intenção de atender ninguém de verdade — decidido no grilling do plano de piloto). Sem uma salvaguarda, um cliente real que responde ao anúncio pode negociar até o **horário combinado** e, dali, até enviar o **Pix de deslocamento** — dinheiro real trocando de mãos por um encontro que a operação nunca pretende cumprir. Hoje não existe nenhum mecanismo que impeça isso: o funil segue normalmente até `Confirmado`/`Em_execucao` como se fosse um atendimento real.

## Solution

Um novo cron determinístico que, 10 minutos depois de um Atendimento entrar em `Aguardando_confirmacao` (horário combinado cravado, **antes** de qualquer Pix de deslocamento ser pedido), cancela automaticamente: manda uma desculpa genérica ao cliente (sorteada de um pool pequeno, para não criar um padrão idêntico repetido — risco de denúncia/bloqueio de WhatsApp), marca o Atendimento como `Perdido` (motivo `outro`, observação de auditoria) e pausa a IA para aquele Atendimento (reusa o Handoff manual). Controlado por uma flag de settings, ligada por padrão durante o piloto e desligável sem deploy quando ele evoluir para atendimento com modelo real.

## User Stories

1. Como Fernando, quero que todo atendimento do piloto que chega a combinar um horário seja cancelado automaticamente antes de qualquer Pix ser pedido, para nunca receber dinheiro real de um cliente de teste.
2. Como Fernando, quero que o cliente receba uma desculpa plausível e variada (não sempre a mesma), para não criar um padrão que pareça golpe e gere denúncia/bloqueio do número.
3. Como Fernando, quero que o atendimento cancelado fique registrado como `Perdido` com um motivo e observação claros, para diferenciar no histórico um cancelamento de segurança do piloto de uma perda comercial real.
4. Como Fernando, quero que a IA pare de responder aquele cliente específico depois do cancelamento automático, para ela não tentar remarcar o mesmo encontro na sequência.
5. Como Fernando, quero desligar esse comportamento por configuração, sem precisar de um deploy, quando o piloto evoluir para atendimento real com uma modelo de verdade.
6. Como desenvolvedor, quero que esse mecanismo siga o mesmo padrão dos outros crons determinísticos do domínio (Reengajamento, timeout interno), para não introduzir um caminho de código novo e desalinhado.
7. Como Fernando, quero que o timer de 10 minutos sempre dispare antes do horário combinado mais próximo possível, para nunca correr o risco de "cancelar" depois que o cliente já esperava a modelo aparecer.

## Implementation Decisions

- **Novo cron `cancelar_piloto_teste`** em `workers/timeouts.py`, mesmo padrão de `aplicar_timeout_interno`/`reengajar_silenciosos`: CTE atômico com `FOR UPDATE OF a SKIP LOCKED`, seleciona atendimentos em `Aguardando_confirmacao` cujo horário combinado foi cravado há mais de 10 minutos e que ainda não foram processados por este cron (idempotência via um novo timestamp, ex. `piloto_cancelado_em`, ou reuso do padrão de `fonte_decisao_ultima_transicao`).
- **Gate de settings:** nova flag (ex. `piloto_auto_cancela_ativo`, default `true` agora), checada no início da função — mesmo padrão do `reengajamento_ativo` em `reengajar_silenciosos`. `false` faz a função retornar sem fazer nada, sem precisar remover o cron job registrado.
- **Envio da desculpa:** novo pool de frases em `agente/_canned.py` (mesmo padrão de `REENGAJAMENTO_CANNED`/`escolher_reengajamento`), sorteado por `escolher_cancelamento_piloto()`. Envio via `enviar_turno` (ARQ), mesma mecânica de humanização/chunking já usada pelo Reengajamento — não é uma tool do agente, é canned direto do worker.
- **Transição de estado:** `UPDATE atendimentos SET estado='Perdido', motivo_perda='outro', observacao_perda='cancelamento automático — piloto de teste', fonte_decisao_ultima_transicao='auto_cancelamento_piloto'` — mesmo padrão de evento (`transicao_estado` + `perdido_registrado`) já usado pelos outros timeouts.
- **Pausa da IA:** chama `aplicar_comando(comando="pausar_ia", origem="cron", autor="sistema", ...)` — reusa o comando novo do spec de Handoff manual (`docs/specs/0003-handoff-manual-operador.md`). **Este spec depende daquele estar implementado.**
- **Registro do cron job:** `workers/settings.py::WorkerSettings.cron_jobs`, mesmo padrão de registro de `reengajar_silenciosos` (nome, função, intervalo — ex. a cada 1-2 min, já que a janela de disparo é estreita, 10min fixos).
- **Confirmação pendente:** o valor de 10 minutos assume que `agenda_buffer_min` real de produção garante folga suficiente antes do horário combinado mais próximo possível — checar o valor real configurado antes do go-live (ver Further Notes).

## Testing Decisions

- **Teste de integração (`needs_db`):** `cancelar_piloto_teste` — cobre: atendimento em `Aguardando_confirmacao` há >10min é cancelado (estado, motivo, observação corretos); atendimento há <10min não é tocado; atendimento já processado não é reprocessado (idempotência, mesmo padrão `FOR UPDATE SKIP LOCKED` dos outros timeouts); flag desligada não cancela nada. Prior art: testes existentes de `aplicar_timeout_interno`/`reengajar_silenciosos` em `api/tests/workers/`.
- **Teste do pool de desculpas:** `escolher_cancelamento_piloto` sorteia dentro do pool, cobertura mínima de que o pool tem mais de uma frase (evita regressão pro caso "desculpa única").
- **Módulos tocados:** `workers/timeouts.py` (função nova), `workers/settings.py` (registro do cron), `agente/_canned.py` (pool novo), `settings.py` (flag nova).

## Out of Scope

- Qualquer lógica de vision/anti-fraude para detectar se um Pix chegou a ser enviado antes do cancelamento — o desenho já evita isso pela ordem do gatilho (antes do Pix ser pedido), não por detecção.
- Cancelamento de atendimentos que já passaram de `Aguardando_confirmacao` (ex.: já em `Confirmado`) — fora de escopo; o piloto deve ser desenhado para nunca deixar chegar lá enquanto a flag estiver ligada (reforça a importância do timer disparar a tempo).
- UI/painel para configurar o pool de desculpas ou o tempo do timer — ambos ficam hardcoded/settings por enquanto, sem tela de administração.

## Further Notes

- **Ver ADR-0033** (`docs/adr/0033-cancelamento-automatico-piloto-teste.md`) para o histórico completo da decisão.
- **Depende do spec de Handoff manual** (`docs/specs/0003-handoff-manual-operador.md`, issue #96) para o comando `pausar_ia` — sequenciar a implementação depois daquele.
- **Confirmar `agenda_buffer_min` real de produção** antes do go-live — se for menor que ~15min, o timer de 10min pode não ter folga suficiente; ajustar o timer ou o buffer antes de ligar a flag em produção.
