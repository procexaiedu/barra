# 10 — O protocolo de disclosure para de listar o que nunca chega até ele

**What to build:** o ponteiro final do protocolo de disclosure nomeia quatro gatilhos de escalada. Dois deles — pedir para ignorar instruções e tag falsa imitando bloco interno — são interceptados por padrões determinísticos **antes** do nó do modelo: escalam sem que a conduta seja consultada. Instrução que descreve um caminho que o modelo nunca percorre.

Depois deste ticket o ponteiro cobre só os gatilhos que de fato chegam ao modelo. O comportamento de escalada não muda em nenhum dos quatro casos.

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] pedido para ignorar instruções continua escalando com o mesmo motivo, pelo caminho determinístico
- [ ] tag falsa imitando bloco interno, idem
- [ ] insistência de disclosure e prova de humanidade repetida continuam escalando pela conduta
- [ ] testes de interceptação existentes verdes

---

Diagnóstico de origem: `.scratch/prompt-refactor/auditoria-carga-instrucional.md` (com os anexos `inventario-turno.md` e `eixo-*.md`, que trazem as linhas citadas).

> Os anexos citam número de linha; este ticket cita bloco/tag de propósito — os números do `regras.md.j2` envelheceram em 40 min durante a própria auditoria.
