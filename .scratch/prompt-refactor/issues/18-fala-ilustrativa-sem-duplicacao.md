# 18 — A fala ilustrativa do incluso fica em um lugar só

**What to build:** a mesma fala de apresentação com item incluso aparece duas vezes — inline na conduta e de novo no exemplo — dobrando a pressão de cópia sobre a string que vazou em prod. Depois de as duas redes do 07 e do 15 estarem verdes, uma das cópias sai.

Vem por último de propósito: enquanto as redes não existirem, a duplicação é reforço, e tirar reforço antes da rede é o erro que o `agente/CLAUDE.md` avisa (dedup não é deleção grátis).

**Blocked by:** 07, 15

**Status:** ready-for-agent

- [ ] a apresentação continua saindo com estilo + incluso, montada do bloco da modelo
- [ ] modelo sem linha "Inclusos" continua sem lista de incluso
- [ ] o cenário que reproduziu a falha original continua verde
- [ ] `conduta_gate` verde contra o baseline de 01

---

Diagnóstico de origem: `.scratch/prompt-refactor/auditoria-carga-instrucional.md` (com os anexos `inventario-turno.md` e `eixo-*.md`, que trazem as linhas citadas).

> Os anexos citam número de linha; este ticket cita bloco/tag de propósito — os números do `regras.md.j2` envelheceram em 40 min durante a própria auditoria.
