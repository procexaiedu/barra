# 14 — O book vai com o enquadramento na bolha e a legenda vazia

**What to build:** a conduta manda mandar foto e vídeo no mesmo turno, manda a legenda das mídias ficar vazia (o mesmo texto na bolha e na legenda chega duplicado ao cliente) e manda o vídeo ir enquadrado como exclusividade. Como o enquadramento é texto e a legenda é vazia, não está dito onde o enquadramento sai.

Depois deste ticket está dito: o enquadramento vive na bolha, junto da linha que acompanha o book, e a legenda continua vazia. O backstop de saída que já valida legenda vazia não muda.

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] book de 2-3 fotos + vídeo sai com uma bolha de texto e legendas vazias
- [ ] o enquadramento de exclusividade aparece na bolha, e o vídeo nunca é revelado como acervo
- [ ] pergunta de quando gravou continua sem data
- [ ] backstop de legenda verde

---

Diagnóstico de origem: `.scratch/prompt-refactor/auditoria-carga-instrucional.md` (com os anexos `inventario-turno.md` e `eixo-*.md`, que trazem as linhas citadas).

> Os anexos citam número de linha; este ticket cita bloco/tag de propósito — os números do `regras.md.j2` envelheceram em 40 min durante a própria auditoria.
