# Docs

Documentação viva do projeto. Porta de entrada do domínio: `CONTEXT.md` (raiz) + `adr/` — ver `agents/domain.md`. Fonte de verdade segue a precedência do `CLAUDE.md` (ADRs vencem).

## Pastas

- `adr/`: decisões arquiteturais numeradas (normativo; nunca apagar — `superseded`).
- `dominio/`: o resto do glossário que não coube no `CONTEXT.md`, carregado sob demanda.
- `agente/`: design do agente LangGraph (arquitetura, estado, prompts, tools, humanização, mídia, coordenador, corpus).
- `agents/`: como as skills consomem este repo (domínio, issue tracker, labels de triagem, mapa do repo).
- `mvp/`: plano original do MVP — contexto de negócio, escopo, módulos e fluxos operacionais.
- `specs/`: specs (PRDs) numeradas de feature.
- `feedbacks/`: feedback cru do Fernando sobre o agente, datado.
- `patches/`: patches aplicados em dependências de terceiros (Evolution API).

## Arquivos

- `evolution-view-once.md`: suporte a `viewOnce` na Evolution self-host (ver `patches/`).

> Runbooks operacionais ficam em `infra/runbooks/`. Árvore e convenções do monorepo em `agents/repo-map.md`.
