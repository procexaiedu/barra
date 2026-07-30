# 03 — A cauda para de proibir a abertura que a conduta prescreve

**What to build:** um cliente que manda só "oi" tem que receber as 2 bolhas curtas de cumprimento. Hoje o bloco de contexto do turno afirma, sem nenhuma condição, que ela já está no meio do atendimento e não deve recumprimentar — e como esse bloco é lido logo antes da fala do cliente, ele vence a conduta. No mesmo bloco, o próximo-passo injeta "entender o que ele procura", que é exatamente a sonda-de-balcão que a conduta proíbe com a dureza máxima do vocabulário.

Depois deste ticket: a instrução de não recumprimentar só aparece quando há mesmo conversa anterior no atendimento, e o léxico de sonda desaparece do próximo-passo.

**Blocked by:** 01 (sem a janela em ordem, o gate não distingue recumprimento legítimo de artefato de ordem)

**Status:** ready-for-agent

- [ ] "oi" seco no primeiro contato recebe cumprimento em 2 bolhas, sem informação e sem cardápio
- [ ] a instrução de não recumprimentar continua aparecendo quando o atendimento já tem histórico
- [ ] o texto do próximo-passo não contém mais nenhuma paráfrase de "o que ele procura"
- [ ] cenário de abertura e cenário de sonda do `conduta_gate` verdes, comparados ao baseline de 01

---

Diagnóstico de origem: `.scratch/prompt-refactor/auditoria-carga-instrucional.md` (com os anexos `inventario-turno.md` e `eixo-*.md`, que trazem as linhas citadas).

> Os anexos citam número de linha; este ticket cita bloco/tag de propósito — os números do `regras.md.j2` envelheceram em 40 min durante a própria auditoria.
