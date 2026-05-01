.PHONY: dev worker test lint format typecheck migrate sync

sync:
	uv sync

dev:
	uv run uvicorn barra.main:app --reload --host 0.0.0.0 --port 8000

worker:
	uv run arq barra.workers.settings.WorkerSettings

test:
	uv run pytest

lint:
	uv run ruff check .

format:
	uv run ruff format .

typecheck:
	uv run mypy src

migrate:
	@if [ -z "$$DATABASE_URL" ]; then echo "DATABASE_URL obrigatorio"; exit 1; fi
	@for f in ../infra/sql/*.sql; do psql "$$DATABASE_URL" -v ON_ERROR_STOP=1 -f "$$f"; done
