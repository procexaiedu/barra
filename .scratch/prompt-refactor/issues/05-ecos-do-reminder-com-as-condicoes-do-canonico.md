# 05 — Os ecos do lembrete param de afirmar versão mais estreita que a conduta

**What to build:** dois ecos de recency afirmam sem condição o que a conduta afirma com condição — e por estarem perto do fim, ganham.

Primeiro: "pergunta dele não é aceite". Verdade antes de qualquer negociação de preço; falso depois dela, quando uma pergunta de horário ou logística é justamente o sim ao valor na mesa. A condição existe no site canônico apenas por posição (o parágrafo mora dentro da escada de desconto), então o eco precisa dizê-la com todas as letras — e pelos dois ramos: depois de ter recusado baixar **ou** de ter feito contraproposta.

Segundo: "o padrão é ele vir até você". Falso para a modelo que não recebe. Ela nunca deve oferecer um local que não tem.

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] depois de recusa de desconto, "que horas?" avança o fechamento em vez de virar pergunta a responder
- [ ] depois de contraproposta, o mesmo — os dois ramos valem
- [ ] antes de qualquer negociação de preço, pergunta dele continua sendo pergunta a responder
- [ ] modelo que só se desloca não recebe eco dizendo que o padrão é ele ir até ela
- [ ] `conduta_gate` verde contra o baseline de 01

---

Diagnóstico de origem: `.scratch/prompt-refactor/auditoria-carga-instrucional.md` (com os anexos `inventario-turno.md` e `eixo-*.md`, que trazem as linhas citadas).

> Os anexos citam número de linha; este ticket cita bloco/tag de propósito — os números do `regras.md.j2` envelheceram em 40 min durante a própria auditoria.
