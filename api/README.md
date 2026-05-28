# API

Backend Python da Elite Baby.

## Estrutura

- `src/barra/core/`: infraestrutura compartilhada.
- `src/barra/dominio/`: bounded contexts do dominio.
- `src/barra/agente/`: orquestracao LangGraph.
- `src/barra/webhook/`: entrada Evolution API.
- `src/barra/workers/`: tarefas ARQ.
- `tests/`: testes unitarios, integracao e conversas.

## Comandos

```powershell
uv sync
uv run pytest
uv run ruff check
```
