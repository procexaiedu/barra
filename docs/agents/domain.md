# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

## Before exploring, read these

- **`CONTEXT.md`** at the repo root — the domain glossary (vocabulário Elite Baby).
- **`docs/adr/`** — read ADRs that touch the area you're about to work in (numeradas; `status: superseded` quando substituídas, nunca apagadas).

If any of these files don't exist, **proceed silently**. Don't flag their absence; don't suggest creating them upfront. The producer skill (`/grill-with-docs`) creates them lazily when terms or decisions actually get resolved.

> Precedência neste repo: onde `CONTEXT.md` divergir de um ADR não-superseded, o ADR vence (ver `CLAUDE.md`).

## File structure

Single-context repo:

```
/
├── CONTEXT.md
├── docs/adr/
│   ├── 0001-estrutura-monorepo.md
│   ├── 0002-psycopg-puro-vs-orm.md
│   └── …
└── api/, interface/, infra/
```

## Use the glossary's vocabulary

When your output names a domain concept (in an issue title, a refactor proposal, a hypothesis, a test name), use the term as defined in `CONTEXT.md`. Don't drift to synonyms the glossary explicitly avoids (cada termo tem uma seção `_Avoid_`).

If the concept you need isn't in the glossary yet, that's a signal — either you're inventing language the project doesn't use (reconsider) or there's a real gap (note it for `/grill-with-docs`).

## Flag ADR conflicts

If your output contradicts an existing ADR, surface it explicitly rather than silently overriding:

> _Contradicts ADR-0007 (dados cadastrais da modelo) — but worth reopening because…_
