.PHONY: dev worker test test-llm lint format typecheck migrate sync evals gate-conduta ab-thinking bancada-extracao graduacao

sync:
	uv sync

dev:
	uv run python -m barra

worker:
	uv run arq barra.workers.settings.WorkerSettings

test:
	uv run pytest -m "not needs_key"

test-llm:
	RUN_LLM_TESTS=1 uv run pytest -m needs_key

# Gate de seguranca (Camada 1, BLOCKING): isolamento/AUP/maquina de estados sobre o grafo real.
# Custa credito (so a fixture de isolamento chama o modelo) + exige TEST_DATABASE_URL -> §0.
# EVALS_K=5 no gate de cutover; default 1. Ver api/evals/ (README/docstrings).
evals:
	RUN_LLM_TESTS=1 uv run pytest tests/agente/test_gate_seguranca.py -v

# Dashboard de regressao do gate: serie historica (pass-rate/custo/write-rate/p95 por execucao).
evals-tendencia:
	uv run python -m evals.relatorio

# Gate de CONDUTA (Camada 2): o agente conduz a venda como o Vendedor (forma+voz+disciplina) e
# chega a confirmacao? Roda o nucleo estratificado contra o grafo real e afirma a pass bar.
# `make gate-conduta ARGS="--fake"` valida o encanamento sem credito; real exige E2E_AUTORIZADO=1
# + TEST_DATABASE_URL + baselines gerados (evals/baselines/README.md) -> §0.
gate-conduta:
	uv run python -m evals.e2e.conduta_gate $(ARGS)

# A/B de thinking no chat #1 (.scratch/ab-thinking-chat): DUAS corridas do gate de conduta —
# braco A disabled (prod) e braco B DEEPSEEK_THINKING_CHAT=high — para comparar conduta/voz/
# empurrao/latencia/custo lado a lado nos relatorios. O `-` segue para o braco B mesmo se a
# pass bar do A reprovar (o A/B compara relatorios, nao aborta). Mesmo regime do gate-conduta:
# `ARGS="--fake"` valida o encanamento sem credito; real exige E2E_AUTORIZADO=1 +
# TEST_DATABASE_URL (§0).
ab-thinking:
	-uv run python -m evals.e2e.conduta_gate $(ARGS)
	-DEEPSEEK_THINKING_CHAT=high uv run python -m evals.e2e.conduta_gate $(ARGS)

# BANCADA da extracao (medicao, nao gate): roda o extrator sobre turnos historicos rotulados e
# relata precisao/recall por campo + trajetoria. Sem ARGS = baseline `gravado` (o que a producao
# registrou) — deterministico, sem credito e sem banco.
# `ARGS="--real"` bate no DeepSeek e gasta credito -> exige EXTRACAO_AUTORIZADA=1 (§0);
# `ARGS="--trajetoria"` exige TEST_DATABASE_URL (seed com ROLLBACK). Ver evals/extracao/.
bancada-extracao:
	uv run python -m evals.extracao.bancada $(ARGS)

# Relatorio de GRADUACAO do piloto (ADR-0034): os 4 criterios computados a partir do banco --
# conversas completas, incidentes nao-contidos, tendencia da taxa do gate e conversao vs baseline
# do vendedor. READ-ONLY (so SELECT + ROLLBACK) e sem credito de LLM; exige DATABASE_URL.
# `ARGS="--desde 2026-08-01"` recorta a janela; `ARGS="--json"` imprime o DTO cru.
graduacao:
	uv run python -m barra.dominio.graduacao $(ARGS)

lint:
	uv run ruff check .

format:
	uv run ruff format .

typecheck:
	uv run mypy src

migrate:
	@if [ -z "$$DATABASE_URL" ]; then echo "DATABASE_URL obrigatorio"; exit 1; fi
	@for f in ../infra/sql/*.sql; do \
		case "$$(basename "$$f" | tr '[:upper:]' '[:lower:]')" in \
			*seed*) if [ "$$AMBIENTE" = "producao" ] || [ "$$MIGRATE_SKIP_SEEDS" = "1" ]; then echo "PULANDO seed: $$f"; continue; fi;; \
		esac; \
		psql "$$DATABASE_URL" -v ON_ERROR_STOP=1 -f "$$f"; \
	done
