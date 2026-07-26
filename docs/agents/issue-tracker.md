# Issue tracker: markdown local

Issues e specs (PRDs) deste repo vivem como arquivos markdown em `.scratch/`. Não use `gh issue` — o GitHub do `procexaiedu/barra` guarda código, não a fila de trabalho.

## Convenções

- Uma feature por diretório: `.scratch/<feature-slug>/`
- A spec é `.scratch/<feature-slug>/spec.md`
- Issues de implementação são um arquivo por ticket em `.scratch/<feature-slug>/issues/<NN>-<slug>.md`, numerados a partir de `01` — nunca um único arquivo combinado de tickets
- O estado de triagem é uma linha `Status:` no topo do arquivo (as strings de papel estão em `triage-labels.md`)
- Comentários e histórico de conversa vão no fim do arquivo, sob um heading `## Comments`
- Slugs em PT-BR, como o resto do domínio (`combo-grupo`, `desconto-dois-degraus`, `cancelamento-automatico-piloto`)

## Quando uma skill diz "publish to the issue tracker"

Crie um arquivo novo em `.scratch/<feature-slug>/` (criando o diretório se preciso).

## Quando uma skill diz "fetch the relevant ticket"

Leia o arquivo no caminho referenciado. Normalmente o usuário passa o caminho ou o número do issue direto.

## Operações de wayfinding

Usadas pelo `/wayfinder`. O **mapa** é um arquivo com um arquivo **filho** por ticket.

- **Mapa**: `.scratch/<esforco>/map.md` — corpo com Notes / Decisions-so-far / Fog.
- **Ticket filho**: `.scratch/<esforco>/issues/NN-<slug>.md`, numerado a partir de `01`, com a pergunta no corpo. Uma linha `Type:` registra o tipo (`research`/`prototype`/`grilling`/`task`); uma linha `Status:` registra `claimed`/`resolved`.
- **Bloqueio**: linha `Blocked by: NN, NN` perto do topo. Um ticket está desbloqueado quando todo arquivo listado está `resolved`.
- **Fronteira**: varra `.scratch/<esforco>/issues/` por arquivos abertos, desbloqueados e não reivindicados; o menor número vence.
- **Reivindicar**: marque `Status: claimed` e salve antes de qualquer trabalho.
- **Resolver**: acrescente a resposta sob um heading `## Answer`, marque `Status: resolved` e adicione um ponteiro de contexto ao Decisions-so-far do `map.md`.
