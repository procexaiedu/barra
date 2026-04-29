"""SQL puro psycopg3. Sem ORM (vide docs/adr/0002).

Convenções:
- Funções recebem `conn: AsyncConnection` (do pool, gerenciado pelo caller).
- Retornam dataclasses/Pydantic, não Row.
"""
