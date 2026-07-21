# 02 — IA escala desconto em 2 rodadas na conversa

**What to build:** Numa negociação de fechamento, a IA pode oferecer primeiro um desconto no degrau intermediário; se o cliente insiste na mesma negociação, sobe até o teto — mas nunca uma terceira vez. Abaixo do teto, continua escalando para Fernando em vez de negociar mais.

**Blocked by:** Ticket 01 (precisa dos dois percentuais existirem em settings para interpolar no prompt).

**Status:** ready-for-agent

- [ ] O prompt de conduta comercial descreve a escalada de 2 rodadas, interpolando os dois percentuais (degrau na primeira contraproposta, teto na segunda e última).
- [ ] Existe uma forma determinística (não dependente da janela de mensagens visíveis) de contar quantas contrapropostas já foram feitas no atendimento atual — até 2.
- [ ] O contador reseta num atendimento novo (recorrência) do mesmo par cliente-modelo.
- [ ] Uma terceira insistência do cliente não gera nova oferta — escala (`fora_de_oferta`).
- [ ] Os gatilhos reativo (cliente pede) e proativo (reengajamento) continuam válidos para os dois degraus.

Ver spec: `docs/specs/0002-desconto-dois-degraus.md` (issue [#95](https://github.com/procexaiedu/barra/issues/95)) e ADR-0031.
