# 02 — A escalada que a IA decide deixa de largar o cliente no vácuo

**What to build:** quando a IA decide escalar, ela deve deixar uma bolha curta de espera antes de chamar a ferramenta. Hoje isso é só instrução em prosa: se ela não escreve nada, o cliente fica sem resposta com a IA pausada, esperando alguém que não vai falar. A bolha de espera passa a ser garantida pelo sistema (canned no post-process), como já acontece na escalada disparada pelo guard da extração.

Exceção que precisa continuar valendo: em `conteudo_ilegal` **não** existe bolha de espera — "um momento" depois de um pedido desses lê como "deixa eu ver se consigo". O motivo vem no argumento da própria chamada da ferramenta, então o canned pode distinguir sem depender do texto do modelo.

A prosa da conduta sobre isso **fica** — ela cobre o caso do `conteudo_ilegal`, que o canned não cobre.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] escalada decidida pela IA sem nenhuma bolha no turno passa a sair com uma bolha de espera do pool canned
- [ ] escalada com motivo `conteudo_ilegal` sai sem bolha de espera, com a recusa seca como única bolha
- [ ] escalada em que a IA já escreveu a bolha de espera não ganha uma segunda
- [ ] teste cobrindo os três casos
- [ ] `make test` verde

---

Diagnóstico de origem: `.scratch/prompt-refactor/auditoria-carga-instrucional.md` (com os anexos `inventario-turno.md` e `eixo-*.md`, que trazem as linhas citadas).

> Os anexos citam número de linha; este ticket cita bloco/tag de propósito — os números do `regras.md.j2` envelheceram em 40 min durante a própria auditoria.
