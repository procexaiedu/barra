.PHONY: dev worker test test-llm lint format typecheck migrate sync evals massa cutover veredito

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

# --- rodada de go-live (passos do operador; ver evals/README.md) -------------------------------
# RODADA resolve para a ultima por carimbo; sobrescreva com RODADA=<nome> se preciso.
RODADA ?= $(shell ls -1 evals/registros/rodadas 2>/dev/null | tail -1)

massa:
	@echo "AVISO: gera ~52 jornadas E2E AO VIVO (agente + cliente-LLM) -- CUSTA CREDITO Anthropic."
	@echo "       teto default R\$$50 (--teto-brl em MASSA_ARGS); exige autorizacao explicita (CLAUDE.md secao 0)."
	uv run python -m evals.sim.massa --usar-database-url $(MASSA_ARGS)

# pipefail: sem ele o tee engoliria o exit code do gate (vermelho sairia 0).
cutover: SHELL := /bin/bash
cutover:
	@if [ -z "$(RODADA)" ]; then echo "nenhuma rodada em evals/registros/rodadas -- rode 'make massa' antes"; exit 2; fi
	set -o pipefail; uv run python evals/runners/runner.py --subdir canonicos --subdir adversariais --k 5 \
		--registrar-cutover evals/registros/rodadas/$(RODADA)/cutover.json $(EVALS_ARGS) \
		2>&1 | tee evals/registros/rodadas/$(RODADA)/gate.log

veredito:
	@if [ -z "$(RODADA)" ]; then echo "nenhuma rodada em evals/registros/rodadas -- rode 'make massa' antes"; exit 2; fi
	uv run python -m evals.diagnostico.veredito evals/registros/rodadas/$(RODADA)
