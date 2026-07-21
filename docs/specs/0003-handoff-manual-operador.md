# Handoff manual por operador: pausar a IA para um cliente específico a qualquer momento

> Issue: [procexaiedu/barra#96](https://github.com/procexaiedu/barra/issues/96)

## Problem Statement

O plano de colocar a IA em produção (piloto assistido) depende de monitoramento em tempo real: se a IA responder algo ruim a um cliente, Fernando ou a modelo precisam poder assumir a conversa imediatamente — "já pode desabilitar essa IA para a gente assumir o atendimento humanizado". Hoje isso não existe. Todo `Handoff` nasce de um gatilho **automático** do state machine (Pix recebido, Foto de portaria, Lembrete de fechamento sem resposta) — não existe uma ação para o operador pausar a IA por decisão livre, no meio de uma conversa, sem que o domínio já tenha disparado o evento. A única alternativa hoje é pausar a `Modelo` inteira (`status=pausada`), o que desliga a IA para **todos** os clientes dela — grosso demais para o caso de "essa resposta específica não ficou boa".

## Solution

Um novo comando de handoff **manual**, disparável por Fernando (painel ou grupo de Coordenação) ou pela própria modelo (grupo), que pausa a IA para o **Atendimento aberto no momento** — mesmo mecanismo/escopo de qualquer outro Handoff, só que com um gatilho novo (decisão humana, não evento do state machine). Reativação segue exatamente o fluxo já existente de **Devolução** (`IA assume` no grupo, botão no painel). Quando esse atendimento fecha e um novo nasce por recorrência, a IA volta ativa por padrão — a pausa não persiste além do atendimento.

## User Stories

1. Como Fernando, quero pausar a IA de um cliente específico a qualquer momento, sem esperar um Pix ou uma Foto de portaria disparar isso automaticamente, para intervir assim que perceber uma resposta ruim.
2. Como a modelo, quero poder assumir a conversa com um cliente específico a qualquer momento pelo grupo de Coordenação, sem depender de um evento do sistema, para agir rápido quando algo me incomodar.
3. Como Fernando, quero que essa pausa manual valha só para o atendimento aberto agora, e não bloqueie permanentemente a IA para esse cliente, para não ter que lembrar de reativar manualmente depois que o atendimento fechar.
4. Como Fernando, quero reativar a IA depois de uma pausa manual do mesmo jeito que já reativo qualquer handoff hoje (`IA assume` / botão Devolver), para não aprender um fluxo novo.
5. Como Fernando, quero registrar por que pausei manualmente (motivo/observação livre), para ter rastro do que motivou a intervenção quando eu revisar depois.
6. Como desenvolvedor, quero que o comando manual reuse a porta única de comandos operacionais (`aplicar_comando`) já existente, para não criar um caminho paralelo de mutação de estado do atendimento.
7. Como desenvolvedor, quero que a pausa manual grave um motivo (`ia_pausada_motivo`) diferente dos motivos automáticos já existentes (`modelo_em_atendimento`, etc.), para diferenciar no dashboard/observabilidade uma pausa por decisão humana de uma pausa determinística do state machine.
8. Como Fernando, quero acionar essa pausa tanto pelo painel quanto pelo grupo de Coordenação por modelo, para não depender de estar numa tela específica no momento em que percebo o problema.

## Implementation Decisions

- **Novo comando em `aplicar_comando`** (`dominio/escaladas/service.py`, a "porta única para comandos operacionais sensíveis" já existente): `comando="pausar_ia"`, espelhando a estrutura de `_devolver_para_ia` só que na direção inversa — seta `ia_pausada=true`, `ia_pausada_motivo=<novo motivo>`, sem exigir que o atendimento esteja em nenhum estado específico (diferente dos gatilhos automáticos, que nascem de transições concretas).
- **Novo `TipoEscalada`** (`dominio/escaladas/modelos.py`): não reaproveitar `comportamento_atipico` (já usado para comportamento **do cliente** — disclosure, jailbreak, conteúdo ilegal — semântica diferente de "operador não gostou da resposta da IA"). Adicionar um valor novo, ex. `pausa_manual_operador`, com rótulo próprio no dashboard.
- **Endpoint no painel:** `POST /atendimentos/{atendimento_id}/pausar` em `dominio/atendimentos/routes.py`, espelhando exatamente o `/devolver` existente (mesmo padrão de `Depends(get_user)`, chama `aplicar_comando` com `origem="painel"`, `autor="Fernando"`).
- **Comando no grupo de Coordenação:** novo comando de texto (ex. `IA pausa` / `IA pausa #N`), reaproveitando o parser de comandos do grupo já usado para `IA assume`/`finalizado`/`perdido` (mesma porta de entrada, `origem="grupo_coordenacao"`, `autor` = "Fernando" ou "modelo" conforme o originador real do envio — CONTEXT.md **Coordenação por modelo**).
- **Escopo = Atendimento** (não a `Conversa cliente`): reaproveita as colunas já existentes `atendimentos.ia_pausada`/`ia_pausada_motivo`. O campo `conversas.ia_pausada` (definido no schema, nunca lido/escrito hoje) **não** é usado por este spec — fica órfão, decisão deliberada (ver ADR-0032).
- **Card/notificação:** ao pausar manualmente, nenhum card novo é necessário na Coordenação (quem pausou já está no grupo/painel e sabe que pausou) — mas o card padrão de "cliente aguardando" (se já existir um mecanismo de listagem de atendimentos com IA pausada) deve refletir esse atendimento como pausado, igual a qualquer outro handoff.

## Testing Decisions

- **Teste de integração (`needs_db`):** `aplicar_comando` com `comando="pausar_ia"` — cobre: atendimento vira `ia_pausada=true` com o motivo novo; idempotência (pausar um atendimento já pausado não quebra); `Devolução` depois de uma pausa manual reativa normalmente (`ia_pausada=false`); atendimento novo do mesmo par (recorrência) nasce com `ia_pausada=false` independente da pausa manual do atendimento anterior. Prior art: testes existentes de `_devolver_para_ia`/`aplicar_comando` em `api/tests/dominio/escaladas/`.
- **Teste do endpoint painel:** `POST /atendimentos/{id}/pausar` — mesmo padrão de teste HTTP já usado para `/devolver`.
- **Teste do comando de grupo:** parser reconhece `IA pausa`/`IA pausa #N` com a mesma disciplina de idempotência/autor já coberta para `IA assume`/`finalizado`.
- **Módulos tocados:** `dominio/escaladas/service.py` (`aplicar_comando`, novo comando), `dominio/escaladas/modelos.py` (novo `TipoEscalada`), `dominio/atendimentos/routes.py` (novo endpoint), o parser de comandos do grupo de Coordenação (mesmo módulo que já trata `IA assume`/`finalizado`/`perdido` — localizar via grep por esses comandos).

## Out of Scope

- Pausa persistente no nível da `Conversa cliente` (atravessando múltiplos atendimentos) — deliberadamente fora; reabrir só se o piloto mostrar necessidade real (ver ADR-0032).
- Qualquer granularidade nova além de Atendimento (ex.: pausar só um tipo de mensagem, ou por período de tempo).
- Card específico de "pausado manualmente" na Coordenação além do que já existe para qualquer atendimento com IA pausada.
- Automação: nada neste spec decide **quando** pausar automaticamente por qualidade de resposta — é sempre uma decisão humana explícita.

## Further Notes

- **Ver ADR-0032** (`docs/adr/0032-handoff-manual-por-operador.md`) para o histórico da decisão e as alternativas rejeitadas (escopo por Conversa cliente, e o on/off global de `Modelo.status` como paliativo insuficiente).
- Este spec é parte do plano de monitoramento em tempo real do piloto de produção assistida (reunião 2026-07-20) — é o pré-requisito técnico mínimo para o "monitoramento a cada instante" que Fernando/Rafa descreveram fazer nos primeiros dias.
