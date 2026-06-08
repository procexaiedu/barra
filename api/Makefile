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

evals:
	uv run python evals/runners/runner.py $(EVALS_ARGS)
