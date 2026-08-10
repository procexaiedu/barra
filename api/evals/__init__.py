"""Harness de evals do agente (Camada 1 — gate de seguranca; Camada 2 — shadow head-to-head).

NAO e pacote de producao (fica fora de `src/barra/`). Importavel como `from evals.x import y`
porque o conftest insere `api/` no path (pytest) e os scripts de shadow fazem o mesmo insert.

- `harness.py` — seed parametrizado (DB real + rollback), NodesVisitedHandler, rodar_turno (cru:
  `graph.ainvoke` direto; sobrou p/ a sessao do rig e o shadow).
- `harness_fiel.py` — o MESMO turno pelo caminho de prod (processar_turno + enviar_turno).
  `rodar_turno_auditado` devolve o `ResultadoTurno` do harness cru: e o que o gate de seguranca e
  o runner e2e usam.
- `checks.py` — graders determinristicos puros (sem DB, sem rede): o veredito do gate, reusando os
  detectores de `src/` como fonte unica. Carrega tambem o corpus (`carregar_fixtures_seguranca`).
- `seguranca/` — fixtures JSONL da Camada 1, uma por arquivo, por familia de risco: `aup/`
  (identidade, jailbreak, extracao de prompt), `isolamento/` (canary cross-modelo nas duas
  direcoes, segredo da agenda), `maquina_estados/` (gate de pausa), `endereco/` (degraus do
  ADR-0026, unidade do interno, bairro inventado) e `venda/` (piso de desconto, tipo nao aceito,
  busca de carro, menage por pessoa, chave Pix). Cada fixture declara `needs_key`.
- `shadow/` — esqueleto da Camada 2 (geracao contra o corpus real, atras do gate da §0).

Ver docs/agente/08-evals.md, 08b, 11.
"""
