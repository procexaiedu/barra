# 08 — A escada de desconto diz o teto uma vez, não três

**What to build:** mudança sem efeito de comportamento: a regra "depois do teto não há oferta nova" está escrita três vezes em seis linhas do bloco de desconto, e o primeiro item da escada termina com três formulações da mesma coisa — a do meio sendo uma linha do núcleo repetida. Sai texto, a escada fica idêntica.

Verificação é o ponto: os dois gates de desconto que já existem precisam ficar verdes sem nenhuma alteração de expectativa.

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] duas rodadas de contraproposta, degrau e depois teto, seguem exatamente como hoje
- [ ] terceira insistência continua recebendo a recusa e escalando na insistência
- [ ] pedido que já começa abaixo do teto continua sem oferta nova
- [ ] gates de desconto (dentro do degrau e abaixo do teto) verdes sem mudar expectativa

---

Diagnóstico de origem: `.scratch/prompt-refactor/auditoria-carga-instrucional.md` (com os anexos `inventario-turno.md` e `eixo-*.md`, que trazem as linhas citadas).

> Os anexos citam número de linha; este ticket cita bloco/tag de propósito — os números do `regras.md.j2` envelheceram em 40 min durante a própria auditoria.
