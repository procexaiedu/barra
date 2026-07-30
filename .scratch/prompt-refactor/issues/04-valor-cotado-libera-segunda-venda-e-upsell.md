# 04 — Preço cotado e não aceito deixa de travar a segunda venda

**What to build:** quando ela já cotou um preço e o cliente ainda não aceitou, a cauda hoje diz para não cotar outro número nem repetir o atual. Isso proíbe três condutas que a própria conduta manda fazer: cotar o Completo como segunda venda, oferecer o pacote maior quando ele pede mais tempo, e repetir o preço com outras palavras quando ele repergunta.

Depois deste ticket, com um valor cotado e não aceito na mesa, ela ainda: cota o Completo se ele perguntar por ele (ou pedir algo que só existe nele), sobe para o pacote maior quando ele reclama do preço ou pede mais tempo, e responde de novo o mesmo preço com outra redação se ele repergunta. O que continua proibido é o que a regra queria proibir: repetir o número solto, sem avanço, e tratar o valor como fechado.

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] com valor cotado e não aceito, pergunta por "completo" recebe o valor do Completo sozinho na bolha
- [ ] com valor cotado e não aceito, "e 2h?" recebe o pacote maior da tabela
- [ ] com valor cotado e não aceito, repergunta de preço recebe o mesmo dado com outra frase
- [ ] o valor cotado continua não sendo tratado como combinado, e o horário não se crava sobre ele
- [ ] `conduta_gate` verde contra o baseline de 01

---

Diagnóstico de origem: `.scratch/prompt-refactor/auditoria-carga-instrucional.md` (com os anexos `inventario-turno.md` e `eixo-*.md`, que trazem as linhas citadas).

> Os anexos citam número de linha; este ticket cita bloco/tag de propósito — os números do `regras.md.j2` envelheceram em 40 min durante a própria auditoria.
