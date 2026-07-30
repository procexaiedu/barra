# 19 — NUNCA volta a ser sinal

**What to build:** a conduta tem 178 palavras integralmente em maiúscula e só 27 são proibição — as outras 151 são ênfase de contraste (ELE, VOCÊ, DELE, SUA, DENTRO, OFERECE…). O critério documentado reserva o caps para linha dura e failure-mode comprovado; os 13 NUNCA passam no critério, mas competem por saliência com 151 palavras que não são proibição.

Este ticket troca a ênfase de contraste por outro recurso, preservando intactos os NUNCA e os NÃO. Zero chars de ganho: é regravação, não corte.

**É um wide refactor** — toca linhas em todos os blocos do arquivo. Vem depois de todos os tickets cirúrgicos de propósito: vindo antes, conflitaria com cada um deles e tornaria ilegível o diff de todos. Passe único, fácil de reverter.

**Blocked by:** 03, 04, 05, 06, 07, 08, 09, 10, 11, 12, 13, 14, 15, 16, 17, 18

**Status:** ready-for-agent

- [ ] nenhuma palavra em caps que não seja proibição sobra no arquivo
- [ ] os NUNCA e NÃO existentes continuam idênticos, em número e em posição
- [ ] nenhuma regra muda de sentido — o diff é só de ênfase
- [ ] `conduta_gate` verde contra o baseline de 01
- [ ] A/B no simulador antes e depois, com o resultado anexado ao ticket (é o gate mais fraco da lista; registre o número, não só "passou")

---

Diagnóstico de origem: `.scratch/prompt-refactor/auditoria-carga-instrucional.md` (com os anexos `inventario-turno.md` e `eixo-*.md`, que trazem as linhas citadas).

> Os anexos citam número de linha; este ticket cita bloco/tag de propósito — os números do `regras.md.j2` envelheceram em 40 min durante a própria auditoria.
