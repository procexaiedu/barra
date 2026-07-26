# 02 — Worker deixa de prometer Pix que não consegue mandar

**O que construir:** quando a modelo não tem chave Pix cadastrada, o cliente não pode ficar esperando uma chave que nunca chega. Hoje a IA diz *"o uber ida e volta fica 100 amor, já te mando o pix"*, o worker avalia a chave, encontra `NULL` e **simplesmente não anexa a bolha** — sem alerta, sem escalada, sem log de erro. O turno é dado como bem-sucedido e o **Pix de deslocamento** nunca é solicitado.

Isso é bug vivo em produção: a única modelo **ativa** (Tatiane) está sem `chave_pix`, e o #36 era **externo** — se o cliente tivesse topado, teria caído exatamente nesse buraco.

Duas frentes: o comportamento (falha silenciosa vira falha visível — alerta e/ou **Escalada** para Fernando, e a IA não deve afirmar que mandou algo que não saiu) e o cadastro (chave da Tatiane preenchida). O cadastro toca produção e precisa de autorização explícita.

Independente do **Combo de grupo** — só entra nesta lista porque bloqueia o ticket 11.

**Bloqueado por:** nenhum — pode começar imediatamente.

**Status:** ready-for-agent

- [ ] Turno que pede Pix com modelo sem `chave_pix` gera sinal visível (alerta/escalada), não silêncio
- [ ] O cliente não recebe afirmação de que a chave foi enviada quando ela não foi
- [ ] Caso coberto em teste, com a modelo semeada sem chave
- [ ] `chave_pix` e `titular_chave` da Tatiane cadastrados em produção (requer autorização)
- [ ] Verificado que nenhuma outra modelo ativa está sem chave
