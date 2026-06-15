# CLAUDE.md

## 0. Segurança em Produção

**Nenhuma ação que atinja produção sem autorização explícita minha, frase a frase.**

São ações que **atingem produção** (lista não exaustiva):
- Mensagem real no WhatsApp (Evolution prod) ou qualquer envio que chegue a um cliente/grupo real.
- Gasto de crédito Anthropic real (`make test-llm`, rodar o agente ao vivo).
- Escrita no banco de produção: `ALTER`/`INSERT`/`UPDATE`/`DELETE`, migrations, `pg_execute_mutation`/`pg_execute_sql` mutável. **`make migrate` contra prod é proibido** (aplica seeds).
- Deploy/infra: `StackGitRedeploy`, `StackUpdate`, `service update --force`, qualquer coisa no Portainer que reinicie ou redeploye a stack `barra-vips` (⚠️ redeploy git sem `Env` zera os segredos e derruba prod).
- `git push`/`delete` em `origin`.

## 1. Pense Antes de Codificar

**Não presuma. Não esconda dúvidas. Exponha os tradeoffs.**

Antes de implementar:
- Declare suas suposições explicitamente. Se houver incerteza, pergunte.
- Se existirem múltiplas interpretações, apresente-as; não escolha uma em silêncio.
- Se houver uma abordagem mais simples, diga. Questione quando for justificável.
- Se algo estiver pouco claro, pare. Diga o que está confuso. Pergunte.

## 2. Simplicidade Primeiro

**O mínimo de código que resolve o problema. Nada especulativo.**

- Não implemente funcionalidades além do que foi pedido.
- Não crie abstrações para código de uso único.
- Não adicione "flexibilidade" ou "configurabilidade" que não foi solicitada.
- Não trate erros para cenários impossíveis.
- Se você escrever 200 linhas e poderia ser 50, reescreva.

Pergunte a si mesmo: "Um engenheiro sênior diria que isto está complexo demais?" Se sim, simplifique.

## 3. Mudanças Cirúrgicas

**Altere apenas o necessário. Limpe apenas a sujeira que você criou.**

Ao editar código existente:
- Não "melhore" código, comentários ou formatação adjacentes.
- Não refatore coisas que não estão quebradas.
- Siga o estilo existente, mesmo que você faria diferente.
- Se notar código morto não relacionado, mencione; não delete.

Quando suas mudanças criarem sobras:
- Remova imports, variáveis ou funções que AS SUAS mudanças tornaram inutilizados.
- Não remova código morto preexistente, a menos que seja solicitado.

O teste: toda linha alterada deve estar diretamente ligada ao pedido do usuário.

## 4. Execução Guiada por Objetivos

**Defina critérios de sucesso. Repita até verificar.**

Transforme tarefas em objetivos verificáveis:
- "Adicionar validação" -> "Escrever testes para entradas inválidas e depois fazê-los passar"
- "Corrigir o bug" -> "Escrever um teste que o reproduza e depois fazê-lo passar"
- "Refatorar X" -> "Garantir que os testes passem antes e depois"

Para tarefas com múltiplas etapas, declare um plano breve:
```
1. [Etapa] -> verificar: [checagem]
2. [Etapa] -> verificar: [checagem]
3. [Etapa] -> verificar: [checagem]
```

Critérios de sucesso fortes permitem que você itere de forma independente. Critérios fracos ("faça funcionar") exigem esclarecimentos constantes.

## 5. Verificação Agêntica e Skills do Claude Code

**Teste o trabalho de forma concreta. Use as ferramentas disponíveis.**

Antes de considerar uma tarefa concluída:
- Defina qual método de verificação comprova que a mudança funciona.
- Para backend, inicie o servidor e valide o fluxo de ponta a ponta quando aplicável.
- Para frontend, use o navegador controlado por automação, como Playwright ou Chromium, para verificar a interface real.
- Para aplicações desktop ou fluxos visuais, use ferramentas de controle da interface quando disponíveis.
- Para tarefas longas ou complexas, rode uma verificação completa antes de finalizar.
- Quando houver um skill apropriado, use-o para revisar, simplificar ou validar a solução.

Regra prática: toda tarefa não trivial deve terminar com uma verificação objetiva. Uma conclusão sem teste, execução ou inspeção concreta ainda é uma hipótese.

## 6. Worktree: Merge Local e Limpeza ao Concluir

**Trabalhou numa worktree? Encerre integrando e apagando — com critério, nunca cego.**

Ao terminar uma tarefa feita numa worktree (`.claude/worktrees/`), feche o ciclo localmente:

1. **Verifique e commite** — só prossiga com o critério de sucesso batido (testes/lint/o que aplicar) e tudo commitado. Trabalho incompleto ou quebrado **não** entra nesta etapa.
2. Capture o branch (`git branch --show-current`).
3. `ExitWorktree(action: keep)` — volte ao diretório original em `main`, com worktree e branch intactos. **Não use `action: remove` aqui:** ele é para *abandonar* trabalho — recusa commits não integrados e apaga o branch, justamente o que você quer mergear.
4. `git merge --no-ff <branch>` a partir do diretório original. **Conflito → pare e avise; nunca force.**
5. Limpe só depois do merge: `git worktree remove .claude/worktrees/<nome>` e `git branch -d <branch>` (o `-d` confirma que já está integrado).

Apenas **local** — sem `push`, a menos que o usuário peça. Se a tarefa ficou inacabada ou os testes falharam, **não** faça o merge: relate o estado e deixe a worktree para retomada (`ExitWorktree(action: keep)`).

---

## Contexto do projeto

Central inteligente de atendimento da agência Elite Baby. Cada modelo opera em seu próprio WhatsApp; uma IA dedicada (LangGraph) atende clientes em nome dela, pausa para handoff e escala decisões para Fernando ou para a modelo via grupo de **Coordenação por modelo**. Estamos no P0 (MVP).

**Porta de entrada do domínio:** @CONTEXT.md (vocabulário, termos da operação Elite Baby e o que evitar). 

### Issue tracker

Issues e PRDs vivem como GitHub issues em `procexaiedu/barra`, via `gh` CLI.

### Triage labels

Cinco papéis canônicos de triagem mapeados 1:1 para labels do GitHub (defaults).

### Domain docs

Single-context: `CONTEXT.md` + `docs/adr/` na raiz do repo.

## Gate de verificação

Antes de empurrar, nesta ordem (comandos detalhados em "Comandos comuns"):

1. **Lint** — api e interface.
2. **Build/typecheck** — `pnpm build` no front; `make typecheck` no back.
3. **Testes** — `make test`; quando a mudança tocar código de banco, rode também os `needs_db` contra o DB real (`TEST_DATABASE_URL`), não só o subconjunto que roda no CI.

Só empurra com **tudo verde**. Falhou um passo → pare, relate a saída, não empurre. (`make test-llm` consome crédito e cai na regra de prod da seção 0 — pede autorização à parte.)

## Mapa do repositório e stack

Monorepo plano. Árvore detalhada por pasta: `docs/agents/repo-map.md`.

- `api/` — Python 3.12 + uv, FastAPI 0.136, LangGraph 1.1 (compila **sem checkpointer** no P0 — ver `agente/graph.py`; `AsyncPostgresSaver` reservado p/ P1), ARQ workers, psycopg3 puro (sem ORM — ver ADR 0002), langchain-anthropic 1.4 (ChatAnthropic) sobre Anthropic SDK 0.97, com prompt caching.
- `interface/` — Next.js 16.2 (App Router), Tailwind v4, shadcn/ui (data-slot pattern), pnpm.
- `infra/` — Supabase self-hosted (Postgres + Auth), MinIO + Redis + Evolution API self-host via Portainer 2.39, Traefik; compose, runbooks e `sql/` (migrations sequenciais).
- `docs/` (`adr/`, `mvp/`), `scripts/`.

Migrations são SQL sequencial em `infra/sql/NNNN_*.sql`, aplicado via `psql` ou Supabase Studio. **Sem migration framework.**

> ⚠️ **`make migrate` é proibido contra produção.** Ele aplica *tudo* de `infra/sql/`, incluindo os seeds descartáveis (`00NN_seed_*.sql`), injetando dados de teste no banco de produção (self-hosted). Em produção, aplique apenas as migrations de **schema** manualmente via psycopg, nunca os seeds.

## Comandos comuns

Backend (a partir de `api/`):
- `make dev` — sobe a FastAPI (`python -m barra`; seta `WindowsSelectorEventLoopPolicy` antes do loop). **No Windows não use `uvicorn` cru** — pendura no ProactorEventLoop (500 no que toca o banco).
- `make worker` — ARQ worker
- `make test` — pytest
- `make test-llm` — testes que batem na API real (consome crédito Anthropic; ver gate)
- `make lint` / `make format` — ruff
- `make typecheck` — mypy src
- `make migrate` — aplica `infra/sql/` (⚠️ proibido em prod — ver "Mapa do repositório e stack")
- `uv sync` — instala/atualiza deps

Frontend (a partir de `interface/`):
- `pnpm dev` / `pnpm build` / `pnpm lint` / `pnpm verify` (gate de verificação agent-native)

Tipos do FastAPI → frontend: `scripts/gera_tipos_openapi.sh` (planejado).

## Convenções não óbvias

- **Idioma**: domínio em PT-BR (`dominio/conversas/`, `Conversa`, `DirecaoMensagem`); infra em EN (`build_app`, `lifespan`, `router`). No frontend, `src/lib/` em EN (convenção da comunidade), `src/tipos/` em PT-BR.
- **Backend src layout**: pacote em `api/src/barra/`. Sempre importar `from barra.x import y`.
- **Feature-first em `dominio/`**: cada bounded context tem seu próprio `{routes,service,repo,modelos,schemas}.py`. **Não existem `models/` ou `services/` globais.**
- **Colisão de nomes a evitar**: `dominio/modelos/` (entidade "Modelo da agência") ≠ `modelos.py` (Pydantic v2 dentro de cada contexto). Nunca importar `modelos.py` entre contextos.
- **Camadas internas de cada contexto**:
  - `routes.py` — só HTTP (Pydantic in/out, status codes, `Depends()`).
  - `service.py` — orquestra repo + agente + redis. Recebe/retorna entidades, não DTOs.
  - `repo.py` — SQL puro psycopg3.
  - `modelos.py` — entidades + value objects (Pydantic v2).
  - `schemas.py` — DTOs HTTP.
- **Direção das dependências**: `agente/` chama `dominio/*/service.py`, **nunca o inverso**. `webhook/` ≠ `api/` — webhook tem token + JID allowlist + debounce, não é REST público.
- **Frontend route groups**: `(auth)/` e `(interface)/` separam contextos sem aparecer na URL.
