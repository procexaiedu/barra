# 06 — O horário mínimo volta a ser piso, não a proposta obrigatória

**What to build:** a conduta afirma que o primeiro horário que ela oferece **é** o horário mínimo. Outra cláusula, e a cauda, mandam a proposta cair dentro da janela vaga que o cliente deu. Com mínimo às 14h e o cliente dizendo "de noite", ela propõe um horário que ele acabou de excluir.

O desempate correto — o mínimo é piso, não proposta — não está escrito em lugar nenhum: vive só no nome da variável. Depois deste ticket está escrito.

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] cliente que diz "de noite" com mínimo à tarde recebe proposta à noite
- [ ] cliente que não deu janela nenhuma continua recebendo o piso como primeiro horário
- [ ] nenhuma proposta cai abaixo do piso
- [ ] cenário de janela vaga do `conduta_gate` verde contra o baseline de 01

---

Diagnóstico de origem: `.scratch/prompt-refactor/auditoria-carga-instrucional.md` (com os anexos `inventario-turno.md` e `eixo-*.md`, que trazem as linhas citadas).

> Os anexos citam número de linha; este ticket cita bloco/tag de propósito — os números do `regras.md.j2` envelheceram em 40 min durante a própria auditoria.
