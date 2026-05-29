---
status: accepted
---

# Módulo de tarefas interno (estilo ClickUp)

O cliente estudava o ClickUp para organizar as tarefas da operação e aprovou trazer essa
função para dentro do sistema — para manter a informação privada (o ClickUp é público,
atrelado ao e-mail) e ter visibilidade do dia a dia. Decidimos um **MVP enxuto**: CRUD de
tarefas com status/prioridade/prazo e atribuição de responsável, **sem** RBAC, notificação,
time-tracking, comentários, histórico ou recorrência — todos deferidos. O ponto não-óbvio é
que o módulo é **desenhado** para um futuro multi-principal (modelos e vendedores logando
com permissões próprias e recebendo tarefas), mas **não o implementa** agora.

## Decisões

- **Sem RBAC no MVP.** Só Fernando e a sócia operam o painel, com permissão idêntica
  (ADR 0012; `core/auth.py:103` rejeita papel ≠ `fernando`). Quem loga vê **todas** as
  tarefas. As etapas da task sobre "admin vê todas / operador vê só as suas" e "esconder
  tarefas sensíveis" saem do escopo do MVP — não há para quem esconder hoje.
- **Ator polimórfico (`tarefa_ator_tipo`: `usuario` | `modelo` | `vendedor`).** `criado_por`
  e `atribuido` são pares `(tipo, id)`, **sem FK** (psycopg puro, integridade na app —
  ADR 0002). No MVP só se popula o que faz sentido: `criado_por` é sempre `usuario`
  (Fernando); o **seletor de responsável** já lista `usuarios` + `modelos` + `vendedores`
  existentes como **rótulo de execução** (sem login nem notificação deles). Quando
  modelos/vendedores ganharem login com permissões, "ver só as minhas" vira um filtro por
  `atribuido = principal logado` — **sem migration nova**.
- **Status mínimo de 3 estados** (`a_fazer` | `fazendo` | `feita`). Cobre "marcar concluída"
  e o filtro por status; habilita um board de 3 colunas sem virar Kanban complexo
  (risco da task: "sem Kanban complexo").
- **Prioridade** `baixa` | `media` | `alta`, default `media` (o ticket exibe "Média").
- **Prazo `date` opcional, sem hora.** Granularidade de dia basta para "tarefa do
  dia/turno" e evita a classe de bug de timezone (comparação naive × aware) que já mordeu o
  painel. Tarefa sem prazo é válida (backlog). "Tarefas de hoje" = `prazo = CURRENT_DATE`
  (+ atrasadas: `prazo < hoje` e não-`feita`).
- **Hard delete + edição livre.** Tarefa é dado interno de baixo risco; sem `deleted_at`
  nem filtros de soft-delete espalhados.
- **Duas visões sobre os mesmos dados:** lista com filtros (minhas / todas / status / prazo)
  e board Kanban de 3 colunas (arrastar entre colunas muda o status). Mais um **widget
  "Tarefas de hoje"** na seção *Hoje* do Painel.

## Considered Options

- **Construir RBAC/multi-login agora** (novo papel no enum, relaxar `auth.py:103`, criar
  usuários no Supabase Auth). Rejeitado para o MVP: contraria o P0 documentado (ADR 0012,
  "sem RBAC") e é escopo grande. O desenho polimórfico deixa esse passo barato depois.
- **`atribuido` como FK fixa para `usuarios`.** Rejeitado: garantiria migration + backfill
  quando modelos/vendedores entrarem — exatamente o refactor que o cliente pediu para evitar.
- **Tabela `membros`/`principals` unificando usuario/modelo/vendedor.** Rejeitado no MVP:
  exigiria tocar os três atores existentes agora (refactor grande). O par `(tipo, id)`
  entrega forward-compat com custo baixo.
- **Reusar `vendedores` como universo de responsáveis.** Rejeitado: vendedor é o respondente
  do WhatsApp se passando pela modelo (ADR 0012) — semântica diferente de "operador de
  plantão / quem executa a tarefa".
- **Seletor só com `usuarios`.** Rejeitado: como só Fernando está no banco, a atribuição
  viraria campo quase fixo; incluir modelos/vendedores como rótulo torna o módulo útil já.
- **Time-tracking, notificações, comentários/histórico, recorrência.** Deferidos: o ticket
  ("Iniciar Trabalho"/"Tempo Total") é da ferramenta que gerencia *esta* task, não requisito
  do módulo; notificar quem não loga é inócuo; os demais viram mini-ClickUp e contrariam
  "não reinventar a roda". Nada disso deixa dívida de schema bloqueante.

## Consequences

- **Tabela `barravips.tarefas`** (migration manual no prod self-hosted) com enums
  `tarefa_status_enum`, `tarefa_prioridade_enum`, `tarefa_ator_tipo`; PK `uuidv7()`, trigger
  `set_updated_at()`, RLS `ENABLE`+`FORCE` com policy `fernando_full_access` (`is_fernando()`),
  igual às demais tabelas painel-only.
- **Novo bounded context `dominio/tarefas/`** (routes/service/repo/modelos/schemas) registrado
  em `api/v1.py` sob `/tarefas`. Resolução de nome do ator é feita na leitura via LEFT JOIN
  condicional por `tipo` (usuario/modelo/vendedor) — ator removido aparece como `null`.
- **Frontend:** `tipos/tarefas.ts`, hook `useTarefas`, página `/tarefas` (lista + board),
  item na sidebar (grupo OPERAÇÃO) e widget "Tarefas de hoje" no Painel.
- **Painel-only por construção:** `agente/` nunca lê tarefas (sem relação com a IA por modelo);
  a atribuição a uma modelo/vendedor é rótulo de gestão, não entra em contexto/persona.
- **CONTEXT.md** não ganha termo novo agora (não é vocabulário de domínio de atendimento); a
  decisão fica registrada aqui.
- **Caminho de evolução para P1:** ao introduzir login de modelos/vendedores, relaxar a guarda
  de papel, popular o principal logado e filtrar tarefas por `atribuido` — o schema já suporta.
