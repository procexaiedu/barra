"""Diagnóstico do flywheel de iteração do agente (Fase 0).

Maquinaria GRÁTIS (Claude Code, zero API Anthropic) que lê as conversas E2E já geradas
(`evals/calibracao/conversas*.jsonl`) e o corpus real, para classificar onde o agente conclui ou
trava, verificar os 5 invariantes e guiar a iteração. Separado de `runners/` (gate), `sim/` (geração)
e `calibracao/` (judge). Ver `flywheel_iteracao_agente_decisoes` (memória) e o plano da Fase 0.
"""
