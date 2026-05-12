# dominio/CLAUDE.md

Escopo: bounded contexts. Um diretório por contexto; **não existem** `models/` ou `services/` globais.

## Os 5 arquivos canônicos por contexto

| Arquivo | Papel | Restrição |
|---|---|---|
| `routes.py` | HTTP: Pydantic in/out, status codes, `Depends()` | Sem regra de negócio. |
| `service.py` | Orquestra `repo` + `redis` + chamadas a `agente/` | Recebe/retorna **entidades**, nunca DTOs. |
| `repo.py` | SQL puro psycopg3 | Sempre query parametrizada; nunca f-string com input. |
| `modelos.py` | Entidades + value objects (Pydantic v2) | Entidade de domínio, não DTO HTTP. |
| `schemas.py` | DTOs HTTP (entrada/saída do `routes.py`) | Vive só na borda HTTP. |

Exceção real: `modelos/programas_routes.py` agrega rotas do subdomínio "programas" dentro do contexto `modelos/`. Se for crescer, prefira virar subcontexto próprio em vez de inflar arquivos auxiliares.

## Armadilha de nomes

A pasta `dominio/modelos/` é o contexto da entidade **Modelo da agência** (a profissional). O arquivo `modelos.py` dentro de **qualquer** contexto é Pydantic local daquele contexto.

`from barra.dominio.X.modelos import ...` dentro de outro contexto Y quebra isolamento — se Y precisa do tipo, defina-o em Y ou suba um value object compartilhado para `core/`.

## Direção das dependências

`dominio/<x>` é chamado por `agente/` e por `api/v1.py`. **Nunca** importe `barra.agente` de dentro de `dominio/`. Se um service precisa de IA, recebe a função/cliente por parâmetro.

## Nomes em PT-BR

`Conversa`, `Atendimento`, `DirecaoMensagem`, `MotivoPerda`, etc. Vocabulário canônico em CONTEXT.md — não invente sinônimos nem traduza para EN.
