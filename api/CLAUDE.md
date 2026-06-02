# api/CLAUDE.md

Escopo: tudo abaixo de `api/`. Complementa o CLAUDE.md raiz; não repete.

## Src layout e imports

Pacote vive em `api/src/barra/`. Use sempre `from barra.<modulo> import …` — nunca caminhos relativos profundos nem `sys.path` hack. Testes e scripts só funcionam via `uv run` porque o src layout não está exposto no `python` do sistema.

Estrutura confirmada: `barra/{core, agente, dominio, webhook, workers, api}` + `main.py` e `settings.py`.

## Gerenciador: uv (nunca pip)

- `uv sync` para instalar/atualizar a partir de `uv.lock`. `pip install` quebra o lock.
- Para adicionar dep: `uv add <pkg>` — não editar `pyproject.toml` à mão para gerenciar versões.
- Python `>=3.12,<3.13` é hard-requirement do projeto.

## Alvos do Makefile (raiz de `api/`)

| Alvo | O que roda |
|---|---|
| `make dev` | `python -m barra` (seta WindowsSelectorEventLoopPolicy antes do loop; reload off no Windows) |
| `make worker` | `arq barra.workers.settings.WorkerSettings` |
| `make test` | `pytest -m "not needs_key"` — suíte padrão, **não** chama a API Anthropic (mesmo com `.env` de prod presente) |
| `make test-llm` | `pytest -m needs_key` — só os testes que batem na API real; **custa crédito**, rode de propósito |
| `make lint` / `make format` | `ruff check` / `ruff format` |
| `make typecheck` | `mypy src` — rode antes de PR |
| `make migrate` | aplica `../infra/sql/*.sql` em ordem; exige `DATABASE_URL` |

`make typecheck` não está no CLAUDE.md raiz e existe — não pule.

## Persistência (ADR-0002)

psycopg3 puro com `AsyncConnectionPool` contra Supavisor em **transaction mode** (porta 6543). Não troque para session mode nem introduza ORM sem novo ADR substituindo o 0002.

## Configuração

`.env` é carregado por `pydantic-settings` em `barra/settings.py`. Acesse via `settings.X`; nunca `os.environ.get(...)` espalhado pelo código.
