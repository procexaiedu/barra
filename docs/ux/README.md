# docs/ux — Guias UX para Iteração

Docs operacionais para agentes de IA iterarem os módulos do painel. Cada arquivo foca em jornada, propósito, blocos visuais e dados — não em implementação técnica. As specs completas ficam em `docs/specs/`.

---

## Telas

| Tela | Rota | Arquivo | Propósito em uma linha |
|---|---|---|---|
| Painel Geral | `/` | [painel-geral-ux.md](painel-geral-ux.md) | Tela sempre aberta — mostra o que precisa de decisão humana agora |
| Central de Atendimentos | `/atendimentos` | [central-atendimentos-ux.md](central-atendimentos-ux.md) | Gerenciar ciclos comerciais em andamento e executar handoffs |
| Agenda Operacional | `/agenda` | [agenda-operacional-ux.md](agenda-operacional-ux.md) | Controlar disponibilidade da modelo e evitar conflitos de horário |
| CRM | `/crm` | [crm-ux.md](crm-ux.md) | Histórico e contexto por par cliente–modelo; observações internas |
| Pix de Deslocamento | `/pix` | [pix-ux.md](pix-ux.md) | Fila de triagem de Pix duvidosos e auditoria de aprovados |
| Modelos | `/modelos` | [modelos-ux.md](modelos-ux.md) | Cadastro, configuração da IA e operação (pausar/reativar) por modelo |
| Dashboard | `/dashboard` | [dashboard-ux.md](dashboard-ux.md) | Visão analítica do período — leitura pura, sem ações |

---

## Como usar estes docs

Cada doc segue a mesma estrutura:

- **Propósito no sistema** — por que a tela existe e como se encaixa no todo
- **Usuário e contexto de uso** — a pergunta que Fernando traz ao abrir a tela
- **Jornada do usuário** — fluxo principal em pseudocódigo visual
- **Blocos visuais** — cada componente, o que exibe e decisões de UX relevantes
- **Dados que alimentam a tela** — endpoints principais consumidos
- **Estados e variações importantes** — empty states, erros, loading, edge cases
- **Oportunidades de iteração** — pontos identificados para melhoria futura

---

## Particularidades por tela

| Tela | Detalhe relevante para iteração |
|---|---|
| Painel Geral | Único `button-primary` contextual (Devolver para IA); sem primary quando fila vazia |
| Central de Atendimentos | Split 360px/restante; deep links recebidos do Dashboard com filtros hidden |
| Agenda Operacional | Ordenação FIFO invertida na visão Dia; bloqueios criados automaticamente pela IA |
| CRM | Nenhum primary permanente — aparece só quando há edição dirty; refetch preserva dirty |
| Pix de Deslocamento | Ordenação FIFO para pendentes (ASC), DESC para histórico; validar dispara cascata no backend |
| Modelos | Duas primary coexistindo (exceção aprovada); única tela que exibe fotos/mídia das modelos |
| Dashboard | Sem nenhum primary (leitura pura); CTAs nunca propagam o período para as telas destino |
