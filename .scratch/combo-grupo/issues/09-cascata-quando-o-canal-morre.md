# 09 — Cascata quando o canal morre

**O que construir:** o combo tem uma assimetria que precisa estar no código, não na cabeça de quem estiver acordado às 2h.

- Um **Atendimento** de **Modelo convidada** que morre **não toca em ninguém**: um amigo desistiu, o **Bloqueio** dela cai, os outros seguem normais. É venda boa que não pode ser jogada fora.
- O **Atendimento da Modelo do canal** que morre por sumiço ou timeout **derruba o combo inteiro**: quem negociou evaporou, e ninguém mais responde por aquele grupo. As convidadas precisam ser avisadas **antes de sair de casa** — o pior desfecho possível é uma delas descendo para o uber rumo a um encontro que já não existe.

Vale para as mortes determinísticas que já existem (timeout de 24h sem resposta do cliente, `Perdido`/`sumiu`) e para o registro explícito. Não cria estado novo e não mexe na máquina de estados — a cascata é uma consequência aplicada sobre os irmãos pelo `combo_id`.

Atenção à interação com o **Cancelamento automático do piloto** (ADR 0033): enquanto o piloto estiver ligado, ele atinge os atendimentos do combo pelas regras por tipo dele. Na prática, combo e piloto são mutuamente exclusivos na operação — isso precisa ficar explícito, não descoberto em produção.

**Bloqueado por:** 07.

**Status:** ready-for-agent

- [ ] Perda de atendimento de convidada não altera nenhum irmão
- [ ] Perda do atendimento do canal por timeout/sumiço cancela os irmãos e libera os bloqueios
- [ ] Cada convidada afetada recebe aviso na Coordenação dela
- [ ] Atendimento de convidada já em `Em_execucao` não é cancelado pela cascata
- [ ] Interação com o cancelamento automático do piloto documentada e coberta
- [ ] Testes `needs_db` para os dois sentidos da assimetria
