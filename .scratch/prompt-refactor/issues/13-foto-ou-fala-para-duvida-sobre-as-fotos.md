# 13 — A dúvida sobre as fotos passa a ter um dono só

**What to build:** "é você mesma nas fotos?" aparece literalmente em dois lugares da conduta com respostas diferentes: um manda mandar o book, o outro manda responder com uma fala sem inventar nem confirmar detalhe. O desvio que deveria resolver isso se autoexclui.

Depois deste ticket há uma resposta só para essa pergunta, e o outro site referencia em vez de prescrever. A regra que precisa sobreviver intacta: teste de bot **não** ganha prova espontânea — queimar o book num teste deixa ela sem mídia na hora do fechamento.

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] "essas fotos são suas?" recebe uma conduta única e determinada
- [ ] "é bot?" continua recebendo negação em personagem, sem book e sem prova espontânea
- [ ] pergunta sobre detalhe físico que não está nos blocos continua sem número inventado
- [ ] roteiro cobrindo os três, verde

---

Diagnóstico de origem: `.scratch/prompt-refactor/auditoria-carga-instrucional.md` (com os anexos `inventario-turno.md` e `eixo-*.md`, que trazem as linhas citadas).

> Os anexos citam número de linha; este ticket cita bloco/tag de propósito — os números do `regras.md.j2` envelheceram em 40 min durante a própria auditoria.
