"""Harness de evals do agente (Camada 1 — gate de seguranca; Camada 2 — shadow head-to-head).

NAO e pacote de producao (fica fora de `src/barra/`). Importavel como `from evals.x import y`
porque o conftest insere `api/` no path (pytest) e os scripts de shadow fazem o mesmo insert.

- `harness.py` — seed parametrizado (DB real + rollback), NodesVisitedHandler, rodar_turno.
- `checks.py` — graders determinristicos puros (sem DB, sem rede): o veredito do gate.
- `seguranca/` — fixtures JSONL da Camada 1 (isolamento, aup, maquina de estados).
- `shadow/` — esqueleto da Camada 2 (geracao contra o corpus real, atras do gate da §0).

Ver docs/agente/08-evals.md, 08b, 11.
"""
