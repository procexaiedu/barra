# 16 — Ela para de calcular o teto que o sistema já calcula para julgá-la

**What to build:** hoje ela recebe o teto como percentual e tem que aplicá-lo sobre o preço de tabela do pacote em jogo — enquanto o sistema já calcula esse mesmo piso em número absoluto e o usa para julgar a resposta dela (abaixo do piso, escala). O número existe e não é mostrado a quem precisa dele.

Depois deste ticket o valor já vem calculado na cauda, dentro da tag de contraproposta que já sai. Aritmética sai do modelo e vai para onde já estava sendo feita.

Não muda nada do que o cliente vê: os percentuais continuam nunca sendo expostos, e a escada continua de duas rodadas.

**Blocked by:** 01, 08

**Status:** ready-for-agent

- [ ] a contraproposta de teto sai no valor exato que o sistema usaria para julgar, sem arredondamento divergente
- [ ] nenhum percentual e nenhuma menção a limite ou política aparece na fala
- [ ] segue valendo: duas rodadas, e abaixo do teto escala em vez de ofertar
- [ ] o teste de contrato das variáveis de contexto cobre o campo novo

---

Diagnóstico de origem: `.scratch/prompt-refactor/auditoria-carga-instrucional.md` (com os anexos `inventario-turno.md` e `eixo-*.md`, que trazem as linhas citadas).

> Os anexos citam número de linha; este ticket cita bloco/tag de propósito — os números do `regras.md.j2` envelheceram em 40 min durante a própria auditoria.
