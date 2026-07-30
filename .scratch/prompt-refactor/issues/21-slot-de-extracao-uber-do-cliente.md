# 21 — Quando o uber é do cliente, o Pix não deveria ser pedido

**What to build:** a conduta diz que, se o cliente chama o uber ida e volta dele, quem paga é ele e o Pix não entra — é um ou outro, nunca os dois. Mas o Pix é solicitado deterministicamente em todo atendimento externo, e não existe campo na extração que registre "o uber é dele". A conduta manda uma coisa e o sistema faz outra, e o cliente pode receber um pedido de Pix por um uber que ele já está pagando.

**Não é conserto de prompt** — é campo que falta. Por isso está fora do plano de reescrita.

**Decisão que falta:** o caso é frequente o bastante para virar campo de extração e condição no trilho do Pix, ou o certo é a conduta parar de oferecer essa alternativa e escalar? A segunda opção é bem mais barata e pode ser o certo no P0.

**Blocked by:** None — mas precisa da decisão antes de virar trabalho.

**Status:** needs-triage

---

Diagnóstico de origem: `.scratch/prompt-refactor/auditoria-carga-instrucional.md` (com os anexos `inventario-turno.md` e `eixo-*.md`, que trazem as linhas citadas).

> Os anexos citam número de linha; este ticket cita bloco/tag de propósito — os números do `regras.md.j2` envelheceram em 40 min durante a própria auditoria.
