"""Bancada offline de avaliacao do extrator (spec `.scratch/extracao-eval-offline/spec.md`).

Responde "essa mudanca no extrator melhorou?" antes de a mudanca chegar ao cliente: roda o
extrator sobre turnos historicos reconstruidos e compara com rotulo HUMANO. Sem LLM-judge — a
saida e estruturada e a metrica e igualdade.

Entrada pela CLI: `python -m evals.extracao.bancada` (alvo `make bancada-extracao`).
"""
