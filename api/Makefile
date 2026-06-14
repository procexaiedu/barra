.PHONY: dev worker test test-llm lint format typecheck migrate sync evals

sync:
	uv sync

dev:
	uv run python -m barra

worker:
	uv run arq barra.workers.settings.WorkerSettings

test:
	uv run pytest -m "not needs_key"

test-llm:
	uv run pytest -m needs_key

# Gate de seguranca (Camada 1, BLOCKING): isolamento/AUP/maquina de estados sobre o grafo real.
# Custa credito (so a fixture de isolamento chama o modelo) + exige TEST_DATABASE_URL -> §0.
# EVALS_K=5 no gate de cutover; default 1. Ver docs/agente/08-evals.md, api/evals/.
evals:
	uv run pytest tests/agente/test_gate_seguranca.py -v

# Dashboard de regressao do gate: serie historica (pass-rate/custo/write-rate/p95 por execucao).
evals-tendencia:
	uv run python -m evals.relatorio

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
