# 17 — Só o sim que crava licencia o verbo confirmar

**What to build:** a conduta usa "confirmar" com dois gatilhos diferentes: um site libera "Posso confirmar às 22h ?" depois do sim ao **valor**, outro proíbe "confirmar" antes do sim ao **horário**. São dois sins distintos licenciando o mesmo verbo, e um dos exemplos modela o lado oposto do que a regra do verbo prescreve — o que é grave, porque a auditoria mostrou que exemplo concreto vence prosa.

Depois deste ticket está dito qual sim licencia o quê, e o exemplo deixa de modelar o contrário. A regra que não pode se perder: proposta de horário sempre termina em "?", senão ele lê promessa de retorno e o encontro morre esperando.

**Blocked by:** 01, 06

**Status:** ready-for-agent

- [ ] aceitou o valor e ainda não deu hora: ela oferece o horário, não o dá por confirmado
- [ ] aceitou o horário: aí sim o verbo de confirmação, e ela pede o nome
- [ ] o exemplo da conduta modela o mesmo verbo que a regra prescreve
- [ ] toda proposta de horário sai com "?"
- [ ] `conduta_gate` verde contra o baseline de 01

---

Diagnóstico de origem: `.scratch/prompt-refactor/auditoria-carga-instrucional.md` (com os anexos `inventario-turno.md` e `eixo-*.md`, que trazem as linhas citadas).

> Os anexos citam número de linha; este ticket cita bloco/tag de propósito — os números do `regras.md.j2` envelheceram em 40 min durante a própria auditoria.
