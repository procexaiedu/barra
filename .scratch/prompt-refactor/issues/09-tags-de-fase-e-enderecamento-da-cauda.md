# 09 — As tags de fase passam a ser todas endereçadas pela cauda

**What to build:** duas pontas soltas na estrutura do funil, e vale resolver juntas porque as duas mexem em quem nomeia as fases.

A tag da espera pela chegada do cliente foi superseded: a flag de disciplina que já existe carrega as mesmas falas e as mesmas proibições, e só aparece quando é aplicável. A tag na conduta não tem resíduo instrucional próprio, mas o texto do próximo-passo a cita — então tirar a tag sem ajustar o próximo-passo quebra o teste de contrato, e é assim que se sabe que não sobrou referência.

A tag da retomada depois do silêncio é endereçada por nada: nenhuma referência interna, nenhum ponteiro na cauda. Ela ganha endereço — ou um ponteiro no próximo-passo, ou é absorvida pela abertura como o caso "ele volta".

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] cliente que avisou que saiu e ainda não chegou continua recebendo presença curta, sem cobrança repetida
- [ ] cliente que volta depois de silêncio é retomado do ponto exato, sem recumprimento e sem desconto de boas-vindas
- [ ] o teste de contrato das variáveis de contexto passa, sem citar tag que não existe mais
- [ ] `make test` verde e `conduta_gate` contra o baseline de 01

---

Diagnóstico de origem: `.scratch/prompt-refactor/auditoria-carga-instrucional.md` (com os anexos `inventario-turno.md` e `eixo-*.md`, que trazem as linhas citadas).

> Os anexos citam número de linha; este ticket cita bloco/tag de propósito — os números do `regras.md.j2` envelheceram em 40 min durante a própria auditoria.
