# 07 — A IA para de declarar incluso um serviço que a modelo não tem

**What to build:** é a única falha desta auditoria com dano medido em trace. Com a modelo sem nenhum fetiche cadastrado, a IA disse que beijo na boca e oral sem camisinha estão inclusos — copiando palavra por palavra a fala de um exemplo da própria conduta. Três cláusulas proibiam exatamente isso e todas perderam para o exemplo concreto.

Duas metades, e as duas neste ticket porque juntas é que entregam o comportamento:
1. a fala ilustrativa dos exemplos deixa de ser um item de cardápio plausível — o problema não é ser exemplo, é ser um item que existe no catálogo real e passa por cotação válida. A forma da fala se mantém; a cópia utilizável sai.
2. um guard de saída, na família dos que já existem para sonda e região: declarar item incluso sem que ele esteja nominalmente na linha "Inclusos" do bloco da modelo é fail. É o padrão que o repo já usa quando a prosa falha.

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] modelo sem linha "Inclusos" recebe apresentação só com estilo, sem lista de incluso
- [ ] modelo com linha "Inclusos" continua apresentando os itens dela, nominalmente
- [ ] o guard reprova a bolha que declara incluso um item ausente do bloco, e a resposta é recomposta
- [ ] o exemplo da conduta não contém mais uma fala de incluso copiável como cotação válida
- [ ] o cenário que reproduz a falha de hoje passa a falhar antes do envio, não depois

---

Diagnóstico de origem: `.scratch/prompt-refactor/auditoria-carga-instrucional.md` (com os anexos `inventario-turno.md` e `eixo-*.md`, que trazem as linhas citadas).

> Os anexos citam número de linha; este ticket cita bloco/tag de propósito — os números do `regras.md.j2` envelheceram em 40 min durante a própria auditoria.
