# 11 — Menage deixa de ocupar o prompt de quem não oferece menage

**What to build:** o bloco de menage inteiro depende de a modelo ter a seção "Por pessoa" no cardápio. O gate está escrito em prosa, então toda modelo que não tem a seção lê e descarta o bloco em cada turno — é o maior pedaço de conduta inaplicável por cadastro do prompt.

O caminho é o que já funcionou para período longo: a condição vira tag na cauda (que aparece só para quem não oferece) e a prosa no prompt geral encolhe para uma linha. É o padrão que acertou 9 em 9 onde três reformulações de prosa haviam falhado.

Vai junto uma redundância do próprio bloco: a regra recota o dobro do pacote duas linhas depois de já tê-lo definido.

**Atenção:** nenhum eval hoje exercita menage. O roteiro faz parte deste ticket e tem que existir e passar **antes** da mudança, senão não há como saber que ela não regrediu.

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] roteiro novo cobre modelo COM e modelo SEM a seção "Por pessoa", e passa contra a conduta atual antes de qualquer edição
- [ ] modelo sem a seção recusa menage como qualquer pedido fora do cardápio, sem cotar, sem dobrar e sem prometer amiga
- [ ] modelo com a seção continua cobrando por duas pessoas, dobrando o pacote, e espelhando quem ele disse que vem
- [ ] o pedido para ela trazer uma amiga continua escalando em vez de fechar sozinha
- [ ] roteiro verde depois da mudança

---

Diagnóstico de origem: `.scratch/prompt-refactor/auditoria-carga-instrucional.md` (com os anexos `inventario-turno.md` e `eixo-*.md`, que trazem as linhas citadas).

> Os anexos citam número de linha; este ticket cita bloco/tag de propósito — os números do `regras.md.j2` envelheceram em 40 min durante a própria auditoria.
