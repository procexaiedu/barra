# 15 — A conduta de cardápio encolhe para quem não tem fetiche cadastrado

**What to build:** o bloco de fora-do-cardápio inteiro pende do bloco de fetiches da modelo — a mecânica de extra cotado, de item incluso, de recusa por item. Modelo sem nenhum fetiche cadastrado carrega esse aparato em cada turno sem ter como aplicá-lo.

Mesmo padrão dos tickets 11 e 12: a condição vira tag na cauda, a prosa encolhe. Este vem depois do 07 porque o guard de saída construído lá é a metade determinística desta mesma regra — sem ele, encolher a prosa é tirar a única rede.

O que **não** encolhe em nenhuma hipótese: camisinha não é item de lista, é como ela trabalha, e nunca sai como "incluso". Essa cláusula nasceu de falha real, o judge deu nota cheia nela e nenhum guard a pega.

**Blocked by:** 07

**Status:** ready-for-agent

- [ ] modelo sem fetiches recusa pedido de ato com recusa curta de mulher, sem moralizar, e sem desmarcar o encontro
- [ ] a recusa continua cobrindo só o item pedido, nunca o programa nem os itens vizinhos
- [ ] "só faço com camisinha" continua saindo como afirmação direta, nunca como item incluso
- [ ] insistência com mais dinheiro continua sem precificar e escalando
- [ ] `conduta_gate` verde contra o baseline de 01

---

Diagnóstico de origem: `.scratch/prompt-refactor/auditoria-carga-instrucional.md` (com os anexos `inventario-turno.md` e `eixo-*.md`, que trazem as linhas citadas).

> Os anexos citam número de linha; este ticket cita bloco/tag de propósito — os números do `regras.md.j2` envelheceram em 40 min durante a própria auditoria.
