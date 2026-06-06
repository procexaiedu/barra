---
description: Verifica end-to-end o que mudou, roda /simplify e abre o PR (inspirado no /go do Boris Cherny)
---

# /go — fechar o ciclo: verificar → simplificar → PR

Anexe `/go` ao fim de um pedido (ex.: "implementa X /go") ou rode sozinho sobre o diff atual.
O objetivo é: quando você voltar à tarefa, **saber que o código funciona** — sem aceitar o primeiro rascunho.

Execute as fases **em ordem**. Pare e reporte se uma fase falhar; não siga para a próxima com o gate vermelho.

## Fase 0 — Branch

- Se estiver na `main`, crie uma branch antes de qualquer commit (`git switch -c <nome-curto-kebab>`).
- Nunca commite direto na `main`.

## Fase 1 — Detectar o que mudou

Rode `git status --porcelain` + `git diff --name-only` (inclua staged e unstaged).
Classifique os caminhos tocados:

- toca `api/` → **fase backend** liga
- toca `interface/` → **fase frontend** liga
- toca `infra/sql/` → **lembrete migration** (não aplique nada; só avise que precisa aplicar manual via psycopg em prod — `make migrate` é proibido contra prod)

Se nada mudou, diga isso e pare.

## Fase 2 — Verificação

Rode só os gates das áreas tocadas. A partir de `api/`:

```
make lint
make typecheck
make test
```

A partir de `interface/`:

```
pnpm lint
pnpm verify
```

`pnpm verify` é o gate agent-native (Playwright, projeto `verificacao`). Se a mudança for visual/comportamental numa superfície real, verifique de fato (browser/Playwright), não só rode o lint.

Se algum gate falhar: corrija a causa e re-rode **só aquele gate** até passar. Não desligue teste nem afrouxe gate pra ficar verde.

## Fase 3 — /simplify

Com os gates verdes, rode o skill `/simplify` sobre o diff (reuso, simplificação, eficiência, altitude — qualidade, não caça-bug).
Depois de aplicar simplificações, **re-rode os gates da Fase 2** das áreas tocadas (simplify pode mexer no código).

## Fase 4 — PR

1. Commit com mensagem no padrão do repo (domínio em PT-BR), terminando com:
   ```
   Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
   ```
2. Push exige a conta `procexaiedu` (com `farjallatt` o origin dá 403):
   ```
   gh auth switch --user procexaiedu && gh auth setup-git
   git push -u origin HEAD
   gh pr create --fill
   gh auth switch --user farjallatt   # voltar ao default ao terminar
   ```
   Sempre volte para `farjallatt` no fim, mesmo se o push falhar.
3. Corpo do PR termina com:
   ```
   🤖 Generated with [Claude Code](https://claude.com/claude-code)
   ```

## Ao terminar

Reporte numa linha: branch, gates que passaram, o que o /simplify mudou e o link do PR.
