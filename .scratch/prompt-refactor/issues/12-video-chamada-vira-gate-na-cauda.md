# 12 — Vídeo chamada deixa de ser negada em quatro lugares diferentes

**What to build:** a regra "a vídeo chamada só existe se estiver na sua tabela" está afirmada em quatro pontos da conduta, três deles como condicional negativa pendurada em outro assunto (prova de humanidade, mídia, pedido de conteúdo). Mesmo padrão do menage: o gate vira tag na cauda para quem não tem o programa, e a prosa fica em um site só.

O comportamento a preservar dos dois lados: quem não tem o programa nunca oferece chamada nenhuma, e o pedido de prova se resolve com foto; quem tem, cota a menor da tabela e o valor é adiantado.

**Atenção:** o cenário de eval que existe roda uma modelo **com** o programa. O ramo sem o programa precisa de roteiro novo, e ele é parte deste ticket.

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] roteiro novo cobre modelo sem vídeo chamada na tabela, e passa contra a conduta atual antes da edição
- [ ] modelo sem o programa recusa chamada e redireciona para foto, e não a oferece como saída em nenhum contexto
- [ ] modelo com o programa continua cotando a menor da tabela, com o valor adiantado e comprovante só em imagem
- [ ] pedido de "chamada rapidinha de graça pra provar" continua não existindo nos dois casos
- [ ] roteiros verdes depois da mudança

---

Diagnóstico de origem: `.scratch/prompt-refactor/auditoria-carga-instrucional.md` (com os anexos `inventario-turno.md` e `eixo-*.md`, que trazem as linhas citadas).

> Os anexos citam número de linha; este ticket cita bloco/tag de propósito — os números do `regras.md.j2` envelheceram em 40 min durante a própria auditoria.
