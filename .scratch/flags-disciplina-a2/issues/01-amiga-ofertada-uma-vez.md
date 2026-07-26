# 01 — A amiga só é oferecida uma vez

**What to build:** Depois que a IA convida o cliente para conhecer a amiga ("Tenho uma amiga aqui no mesmo hotel, no apartamento dela rs, quer conhecer as duas ?"), ela não reoferece nessa negociação — nem quando o convite já saiu da janela deslizante. Hoje a disciplina ("você PODE oferecer uma vez, como quem convida") é só prosa no `<menage>`, e o evento fica fora da janela justamente no fim da negociação, que é quando a regra vale.

**Blocked by:** None — pode começar imediatamente.

**Status:** ready-for-agent

- [ ] Coluna nova em `atendimentos` (timestamptz, first-write-wins), no molde de `book_enviado_em`, com migration em `infra/sql/` e `COMMENT ON COLUMN` explicando a disciplina. Não aplicar em prod.
- [ ] Detector de fala isolada em `_disciplina.py` que casa a **oferta proativa** da amiga. A resposta de escalada ("Deixa eu ver com ela e já te retorno amor"), que a IA dá quando é o CLIENTE quem pede a dupla, NÃO conta como oferta — teste cobrindo os dois casos.
- [ ] Carimbo no write-time do envio, na mesma transação do INSERT em `mensagens` e só na primeira inserção da bolha, junto dos carimbos A2 existentes.
- [ ] Campo no `ContextoDoTurno` e tag no `contexto_dinamico.md.j2` instruindo a não reoferecer e a seguir o encontro com ela; segue o padrão das tags irmãs ("vale mesmo que a oferta não apareça nas últimas mensagens").
- [ ] O parágrafo da amiga no `<menage>` encolhe para o resíduo — o convite continua permitido e continua sendo pós-venda, some a mecânica de "uma vez". **Não tocar** a parte da pergunta de segurança ("Só eu e você amor"): ela responde outro medo do cliente e já custou um incidente.
- [ ] `make gate-conduta` e `make evals` verdes; `make lint`, `make typecheck`, `make test` verdes.
