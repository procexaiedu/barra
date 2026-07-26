# 09 — A recusa de desconto não chega ao extrator

**Spec:** `.scratch/extracao-aceite-hibrido/spec.md`

**O que construir:** o ticket 08 escreveu no campo `aceita_valor` a condição que faltava —
"pergunta de horário ou de logística só vale como sim depois de ele ter pedido desconto e você ter
respondido (recusando ou com a contraproposta)". A condição está **dita**, mas o extrator não tem
como **verificá-la** de forma estável: a única evidência de que houve negociação de preço são as
falas na janela, e a janela é deslizante (20 mensagens em `prepare_context.py`). Numa negociação com
escada — exatamente a única em que a regra morde — a recusa sai da janela e o extrator decide no
escuro.

O estado já existe materializado: `n_contrapropostas`, que o `contexto_dinamico.md.j2` renderiza
como `<ja_fez_contraproposta>` para a **IA**. O eco que o **extrator** lê (`ja_registrado.md.j2`,
via `PecasDoTurno`) não recebe esse campo — a assimetria que o `agente/CLAUDE.md` proíbe na seção
de ecos multi-site ("campo novo no belief entra nos dois, senão a IA e o extrator passam a ver
estados diferentes").

Enquanto isso não existir, o modo de falha é o benigno (falso negativo: não marca aceite, a
negociação segue aberta) — por isso não bloqueia o 08.

**Bloqueado por:** nada. Independente do 04.

**Status:** ready-for-agent

- [ ] O bloco `<ja_registrado>` carrega se já houve negociação de preço nesta conversa (a
      contraproposta feita ou a recusa), pelo mesmo dicionário de variáveis do `<ja_combinado>`
- [ ] O terceiro site do eco entra junto: `evals/extracao/janela.py`, senão a bancada mede o
      extrator contra um bloco que prod nunca mostrou
- [ ] A descrição do `aceita_valor` passa a apontar para o bloco de estado em vez de depender só
      das falas da janela
- [ ] Golden set ganha o caso que hoje não existe: pergunta de logística **com preço na mesa**,
      antes e depois da recusa — é o item que torna a regra do 08 medível
- [ ] Gate verde: lint, typecheck e testes
