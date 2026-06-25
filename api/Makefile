.PHONY: dev worker test test-llm lint format typecheck migrate sync evals gate-conduta

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
# EVALS_K=5 no gate de cutover; default 1. Ver docs/agente/08-evals.md, api/evals/.
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
