# Docs

Documentação viva do projeto. Portas de entrada do domínio: `CONTEXT.md` (raiz) e `mvp/00-indice.md`. Fonte de verdade segue a precedência do `CLAUDE.md` (ADRs vencem).

## Pastas

- `mvp/`: escopo, contexto de negócio, fluxos e interfaces do MVP.
- `adr/`: decisões arquiteturais numeradas (normativo; nunca apagar — `superseded`).
- `agente/`: design do agente LangGraph (arquitetura, estado, prompts, tools, evals). `agente/referencia/` guarda a doc de API da Anthropic usada como apoio.
- `specs/`: specs completas das 7 telas do painel (fundação + tela-01..07).
- `ux/`: guias UX por tela — jornada, blocos e dados, não implementação (complementa `specs/`).
- `design/`: ponte domínio → visual (`dominio-visual.md`); complementa o `DESIGN.md` da raiz.
- `backend/`: especificação de implementação do backend P0.
- `historico/`: atas, drafts e materiais de referência não-normativos (inclui `schema_barravips.md` e `seed_spec.md`).

## Arquivos

- `estrutura-codebase.md`: árvore e convenções completas do monorepo.

> Runbooks operacionais ficam em `infra/runbooks/`.
