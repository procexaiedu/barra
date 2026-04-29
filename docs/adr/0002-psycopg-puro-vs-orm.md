---
data: 2026-04-29
status: aceito
---

# ADR-0002 — psycopg3 puro em vez de ORM (SQLModel/SQLAlchemy)

## Contexto

Stack já decidiu psycopg3 + AsyncConnectionPool contra Supavisor (porta 6543, transaction mode). LangGraph usa `AsyncPostgresSaver` que opera diretamente em SQL. Schema do MVP tem coluna `eventos` semi-estruturada (audit log) e Supabase Auth com **RLS** ativa em todas as tabelas.

## Decisão

Cada bounded context tem `repo.py` com SQL puro psycopg3 (`AsyncConnection`/`AsyncCursor`). Sem SQLModel, sem SQLAlchemy. Migrações via Alembic com revisões SQL escritas à mão.

## Consequências

**Positivas**
- Compatibilidade direta com transaction mode do Supavisor (ORMs frequentemente assumem session mode).
- Controle explícito de RLS — cada query enxerga as policies como elas são.
- Sem camada de tradução entre objeto e tabela; menos surpresa.

**Negativas**
- Sem geração automática de migrations (precisa redigir cada uma).
- Mais boilerplate para CRUD trivial.

**Reversíveis**
- Trocar para SQLModel é viável; envolveria reescrever cada `repo.py` mantendo a interface pública. Registrar novo ADR se acontecer.
