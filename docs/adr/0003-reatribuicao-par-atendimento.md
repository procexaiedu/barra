---
data: 2026-05-12
status: aceito
---

# ADR-0003 — Reatribuição de cliente/modelo em atendimento via cancelar+recriar

## Contexto

Operadores do painel ocasionalmente precisam corrigir o cliente ou a modelo vinculados a um atendimento já criado — tipicamente quando Fernando registrou o atendimento errado e percebe antes do trabalho começar. A task original (`73e540c0`) pediu que os campos Cliente e Modelo virassem editáveis no modal de edição, da mesma forma que tipo, urgência, endereço e valor já são.

O conflito surge contra a invariante **"IA por modelo isola por par (cliente, modelo)"** declarada em `CONTEXT.md`. Cada par cliente-modelo carrega histórico próprio, recorrência própria, e instância de IA dedicada. Trocar `cliente_id` ou `modelo_id` em um atendimento existente quebra essa invariante em múltiplos pontos:

1. **Isolamento por par**: histórico do par antigo passa a ser visto pela IA da modelo destino, contaminando o contexto.
2. **Coerência financeira**: `atendimento_servicos.preco_snapshot` foi capturado no acordo da modelo origem, não da destino.
3. **Bloqueio de agenda**: `bloqueio_id` aponta para a agenda da modelo antiga.
4. **Conversa**: `conversa_id` é do par antigo; trocar exige reatribuir ou recriar.
5. **Coordenação por modelo**: cards já enviados ao grupo da modelo antiga ficariam órfãos.

Três opções foram consideradas para resolver a necessidade do operador sem quebrar a invariante.

## Decisão

Adotar a opção **(c) cancelar+recriar**, frontend-only.

Comportamento da UI:

- `ModalEdicao` exibe Cliente e Modelo em campos **read-only** (com tooltip explicando o caminho de alteração).
- Junto a esses campos, botão secundário **"Reatribuir atendimento"**.
- Click no botão abre wizard de dois passos:
  1. Confirma cancelamento do atendimento atual (com motivo opcional).
  2. Abre `ModalNovoAtendimento` pré-preenchido com os campos operacionais do atendimento antigo (tipo, urgência, endereço, valor, data sugerida), **exceto** cliente e modelo, que ficam em branco para nova seleção.
- Quando o operador completa o `ModalNovoAtendimento`, o backend (já existente) cancela o antigo e cria o novo via endpoints já disponíveis (`POST /atendimentos` e cancelamento). **Nenhuma mudança de backend é necessária.**

Restrições operacionais P0:

- Permissão **Fernando-only** (no P0 só ele opera o painel).
- Cliente arquivado como destino é recusado com **409 igual `POST /atendimentos`** (reusa a regra existente).
- Mensagens trocadas no atendimento antigo **permanecem no par antigo** — não migram. O atendimento novo começa limpo, com sua própria conversa atrelada ao par novo.

## Alternativas rejeitadas

### (a) Edição livre — `UPDATE atendimentos SET modelo_id/cliente_id = ...`

Quebra a invariante de isolamento por par. Contamina IA cross-par, deixa financeiro inconsistente, gera conversa híbrida onde a modelo destino enxerga histórico que não é dela. **Rejeitada.**

### (b) Endpoint dedicado de reatribuição com guardas

Adicionar `POST /v1/atendimentos/{id}/reatribuir` no backend que aceita troca apenas para atendimentos em estados iniciais sem laços (zero mensagens, zero serviços fechados, zero bloqueio firmado, zero escaladas, zero comprovantes). Tecnicamente viável e preserva o atendimento como entidade única.

Rejeitada porque:

- Adiciona complexidade backend permanente (endpoint, service, schema, teste, regras de invariante encoded em código) para um caso de uso raro.
- Ainda deixa a conversa ambígua: mesma `conversa_id` reapontada para par diferente é violação semântica do CONTEXT.md, mesmo com filtros.
- A opção (c) entrega o mesmo resultado operacional sem mudar backend.

## Consequências

**Positivas**

- Alinhada com a invariante de isolamento por par do CONTEXT.md sem exceção.
- Frontend-only — único codificador (`codificador-interface`), sem migration, sem novo endpoint.
- Reusa fluxos existentes (`POST /atendimentos`, cancelamento). Zero superfície nova de API.
- Auditoria limpa: cancelamento + criação ficam registrados como dois eventos distintos.

**Negativas**

- Dois cliques em vez de um para o operador. Em fluxos rápidos pode parecer verboso.
- Perde-se a noção de "atendimento contínuo" — o atendimento antigo vira `Cancelado` (com motivo `reatribuicao`) e o novo nasce do zero. Para análise histórica, conectar os dois exige metadado explícito (campo `atendimento_origem_id` no novo, se necessário no futuro).

**Reversíveis**

- Migrar para opção (b) é aditivo (endpoint novo) sem quebrar a UI atual. Custo baixo se padrão real de uso justificar.
- Adicionar campo `atendimento_origem_id` para rastreabilidade da reatribuição é migration simples (`ALTER TABLE ADD COLUMN IF NOT EXISTS`), fica como caminho aberto se a operação pedir.
