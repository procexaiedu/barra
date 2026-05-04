# Dashboard — Guia UX para Iteração

> Doc operacional para agentes de IA iterarem o módulo. Foca em jornada, UX, propósito e dados — não em implementação técnica.

---

## Propósito no sistema

O Dashboard é a tela de **retrospectiva e análise**. Enquanto o Painel Geral responde "o que precisa de mim agora?", o Dashboard responde "como a operação está se saindo?".

É a única tela do sistema inteiramente de leitura — nenhuma ação de Fernando muda dados aqui. Todos os CTAs são navegação contextual que leva Fernando para as telas operacionais com filtros pré-aplicados.

Fernando usa o Dashboard para entender padrões: onde os clientes estão se perdendo no funil, por qual motivo mais se perde, quais escaladas aparecem com mais frequência, qual o valor médio dos fechamentos. Esses dados alimentam ajustes na operação (mudar FAQ, reorientar a IA, identificar gargalos).

---

## Usuário e contexto de uso

**Único usuário:** Fernando. Acessa o Dashboard de forma analítica — não está resolvendo algo urgente, está entendendo o estado da operação.

**Pergunta que Fernando traz:** "Como foi essa semana?" ou "Por que as perdas aumentaram?" ou "Quanto a Júlia faturou esse mês?"

**Sessão típica:** Fernando abre o Dashboard, lê os KPIs, faz drill-down num número que chamou atenção (clica numa etapa do funil ou numa linha de perda), vai para a Central com o filtro já aplicado, resolve ou apenas observa, volta ao Dashboard.

**Critério de sucesso:** Fernando identifica o padrão relevante e navega para a tela certa em menos de 20 segundos.

---

## Jornada do usuário

```
Abrir /dashboard
    → Skeletons em todos os blocos enquanto carrega
    → Snapshot chega: filtro padrão 7 dias, todas as modelos

Ler os KPIs
    → "No período" — 4 tiles com os números principais
    → Taxa de conversão: % dos decididos que fecharam
    → Fechamentos: contagem + valor bruto + ticket médio
    → Perdas: contagem + % do volume
    → Atendimentos escalados: contagem + % do volume
    → Cada KPI mostra seta de tendência vs período anterior

Explorar o funil
    → "Volume por estado" — funil SVG com 7 etapas (Novo → Fechado)
    → Onde está acumulando? As etapas estreitam mostrando o fluxo
    → Botão "Saídas perdidas" abaixo com contagem e % de Perdido
    → Clicar em qualquer etapa ou no botão vai para Central filtrada

Investigar perdas
    → "Perdas por motivo" — donut chart + lista
    → Qual motivo aparece mais?
    → Clicar navega para Central com estado=Perdido + motivo filtrado

Investigar escaladas
    → "Motivos de escalada" — texto do motivo + barra proporcional
    → Top 5 + "Outros (N)" que abre dialog com a lista completa
    → Clicar navega para Central com IA pausada + motivo filtrado

Ver desempenho por modelo
    → "Profissionais mais procuradas" — tabela por modelo
    → Volume com barra visual dourada + fechamentos + valor bruto + conversão
    → Clicar numa linha vai para a página da modelo em /modelos

Ajustar período
    → 4 chips preset: Hoje / 7 dias (default) / 30 dias / Tudo
    → "Personalizado…" → dialog com date pickers (limite 90 dias, sem futuro)
    → Filtro de modelo no lado direito da toolbar
    → URL atualiza via query string — deep link funciona
```

---

## Blocos visuais

### 1. Cabeçalho
**Arquivo:** `components/dashboard/HeaderDashboard.tsx`

Título "Dashboard" em serif 40px. À direita, exibe o range do período **somente quando `de` e `ate` estão presentes** — ou seja, apenas quando o período custom está ativo. Para presets (hoje/7d/30d/tudo), o header mostra só o título sem nenhum rótulo de período.

Quando visível: label "PERÍODO" (uppercase tracking) + range em mono — ex.: `12 abr – 30 abr 2026`.

---

### 2. Toolbar de filtros
**Arquivo:** `components/dashboard/ToolbarDashboard.tsx` + `FiltroPeriodo.tsx` + `FiltroModelo.tsx`

Flex row com `justify-between`:

**Esquerda — chips de período:**
Quatro botões preset: **Hoje · 7 dias · 30 dias · Tudo** + botão "Personalizado…". Ativo = `bg-ink-300 text-gold-500`; inativo = `bg-ink-200 text-text-secondary`.

Quando custom ativo, o botão "Personalizado…" exibe o range aplicado em mono: `01 abr – 15 abr 2026`.

**Direita — filtro de modelo:** dropdown de seleção. Trocar qualquer filtro atualiza a URL (`router.replace`) e refaz o fetch — sem skeleton, dados antigos ficam visíveis até o novo resultado chegar.

**Dialog de range custom (`DialogRangeCustom`):**
Dois date pickers com validação inline antes de habilitar "Aplicar":
- Início ≤ Fim
- Fim não pode ser no futuro
- Janela máxima de 90 dias

---

### 3. KPIs do período
**Arquivo:** `components/dashboard/TileKpi.tsx` + `IndicadorTendencia.tsx`

Seção com header "**No período**" (h2). Grid de 4 tiles `lg:grid-cols-4`.

| Tile | Ícone | Valor | Linha auxiliar |
|---|---|---|---|
| Taxa de conversão | `TrendingUp` gold | `N%` ou `—` | "N fechado / M decididos" |
| Fechamentos | `CheckCircle2` success | contagem em `text-success-500` | "{valor bruto} bruto · ticket médio {ticket}" |
| Perdas | `XCircle` danger | contagem em `text-danger-500` | "N% do volume" (ou `—`) |
| Atendimentos escalados | `AlertTriangle` warn | contagem | "N% do volume" (ou `—`) |

Todos os tiles têm um ícone `Info` com tooltip descritivo. A linha auxiliar fica em 13px muted.

**Footer do tile** (só aparece quando há dados anteriores): `IndicadorTendencia` à esquerda + `"vs {range}"` mono 11px à direita.

**`IndicadorTendencia`:**

| Situação | Visual |
|---|---|
| atual = 0 e anterior = 0 | `—` muted |
| anterior = 0 (qualquer atual) | `—` muted |
| delta < 0.05 | `=` (Minus) muted — variação irrisória |
| delta > 0 (direta) | ArrowUp verde (conversão, fechamentos) |
| delta > 0 (invertida) | ArrowUp vermelho (perdas, escaladas) |
| delta < 0 (direta) | ArrowDown vermelho |
| delta < 0 (invertida) | ArrowDown verde |

Taxa de conversão usa `unidade="pp"` (pontos percentuais); demais usam `unidade="%"`.

---

### 4. Funil de estados
**Arquivo:** `components/dashboard/FunilEstados.tsx` + `FunilPipeline.tsx`

Seção com header "**Volume por estado**" (h2) + "{total} atendimentos no período" à direita.

**Quando há atendimentos**, exibe dois blocos:

**Funil SVG (`FunilPipeline`)** — label "CAMINHO ATÉ FECHAMENTO":
Visualização trapezoidal SVG com 7 etapas, cada uma mais estreita que a anterior:

| Estado backend | Label no funil |
|---|---|
| `Novo` | Novo |
| `Triagem` | Triagem |
| `Qualificado` | Qualificado |
| `Aguardando_confirmacao` | Aguardando |
| `Confirmado` | Confirmado |
| `Em_execucao` | Em atendimento |
| `Fechado` | Fechado |

Cada etapa mostra: label (esquerda) · contagem (mono, direita) · % do total. Cada etapa é clicável → `/atendimentos?estado={estado}`. `Perdido` **não** aparece no funil.

**Botão "Saídas perdidas"** abaixo do funil: ícone `TrendingDown` danger + label + "Atendimentos encerrados antes do fechamento" + contagem (2xl danger) + %. Navega para `/atendimentos?estado=Perdido`.

**Empty state** (total = 0): "Nenhum atendimento no período selecionado." + "Ajuste o período no topo da página."

---

### 5. Perdas por motivo
**Arquivo:** `components/dashboard/BlocoPerdasPorMotivo.tsx` + `DonutPerdas.tsx`

Seção com header "**Perdas por motivo**" (h2). Card com layout `sm:flex-row`:
- **Esquerda:** donut chart (`DonutPerdas`) — cada motivo é um arco colorido com opacidade variando por ranking
- **Direita:** lista de botões na ordem canônica: Sumiu · Preço · Risco · Indisponibilidade · Fora da área · Outro (motivos com 0 ocorrências ficam ocultos)

Cada linha da lista: color dot (vermelho com opacidade variável) + label + contagem (mono) + percentual (mono muted). Clique → `/atendimentos?estado=Perdido&motivo_perda={motivo}`.

**Empty state:** ícone `CheckCircle2` success + "Sem perdas no período."

---

### 6. Motivos de escalada
**Arquivo:** `components/dashboard/BlocoMotivosEscalada.tsx` + `DialogTodasEscaladas.tsx`

Seção com header "**Motivos de escalada**" (h2) + "{total} no período" à direita. Mostra o top 5 dos textos de motivo de escalada + linha "Outros (N)" quando há mais.

**Cada linha:** texto do motivo (truncate) + **barra de progresso** (linha horizontal cinza com linha warn-500 + ponto circular warn-500 no final, proporcional ao máximo) + contagem (mono).

**Motivos são texto livre, agrupados por string exata** — sem clustering. Fernando precisa ver o vocabulário real que a IA está usando.

Click em motivo navega para `/atendimentos?ia_pausada=true&motivo_escalada={texto}`.

"Outros (N)" abre `DialogTodasEscaladas` — modal read-only com a lista completa. Cada linha no dialog é clicável para a mesma navegação.

**Empty state:** "Sem atendimentos escalados no período." (texto simples, sem ícone).

---

### 7. Profissionais mais procuradas
**Arquivo:** `components/dashboard/ProfissionaisRanking.tsx`

Seção com header "**Profissionais mais procuradas**" (h2). Tabela com uma linha por modelo, ordenada por volume.

| Coluna | O que mostra |
|---|---|
| Modelo | `#{idx+1}` mono muted + nome UPPERCASE semibold |
| Volume | Contagem + barra visual dourada proporcional ao maior |
| Fechamentos | Contagem em `text-success-500` |
| Valor bruto | BRL formatado |
| Conversão | `N%` ou `—` |
| → | `ChevronRight` muted |

Linha inteira clicável → `/modelos?modelo={id}&aba=perfil`.

**Empty state:** "Nenhuma modelo cadastrada." + botão "Cadastrar modelo →" (secondary, navega para `/modelos`).

> **Nota:** `TilePixRevisao.tsx` existe como componente mas **não é renderizado** na página atual. O dado `pix_em_revisao_pendentes_total` chega na resposta do endpoint mas não há bloco visual para ele no Dashboard.

---

## Dados que alimentam a tela

Um endpoint de leitura principal + um lazy para o dialog de escaladas:

| Chamada | O que retorna |
|---|---|
| `GET /v1/dashboard?periodo=7d` | snapshot: filtro_aplicado, janela_comparacao, pix_em_revisao_pendentes_total, kpis_periodo, kpis_periodo_anterior, funil_estados, perdas_por_motivo, motivos_escalada (top5), profissionais |
| `GET /v1/dashboard/escaladas?periodo=7d` | lista completa de motivos (só carrega ao abrir o dialog) |

Parâmetros: `periodo` (hoje/7d/30d/tudo/custom) + `de` + `ate` (para custom) + `modelo_id`.

**Realtime:** assina `atendimentos`, `comprovantes_pix` e `escaladas`. Qualquer mudança dispara refetch debounced de 250ms — sem skeleton, dados antigos ficam visíveis até o novo resultado chegar.

Quando o filtro muda durante um refetch em andamento, a resposta anterior é descartada (AbortController).

---

## CTAs de saída nunca propagam o período

Os links do Dashboard para outras telas **nunca levam o período selecionado**. A Central de Atendimentos e o módulo de Pix são telas de estado atual — não filtram por `created_at` da mesma forma.

Os CTAs propagam apenas filtros **lógicos** (estado, motivo de perda, motivo de escalada, ia_pausada) que fazem sentido nas telas destino.

---

## Estados e variações importantes

| Situação | Comportamento |
|---|---|
| Carregando inicial | 4 KPI skeletons h-[116px] + funil 8 linhas skeleton + 2 blocos h-[260px] + ranking h-[120px] |
| Erro na primeira carga | `BannerErro` com retry; dados existentes não aparecem |
| 0 atendimentos no período | Funil mostra empty state; KPIs mostram 0/R$0/—% |
| Funil sem atendimentos | "Nenhum atendimento no período selecionado. Ajuste o período." |
| Sem perdas no período | ícone check verde + "Sem perdas no período." |
| Sem escaladas no período | "Sem atendimentos escalados no período." (muted, sem ícone) |
| Sem modelos cadastradas | Ranking mostra "Nenhuma modelo cadastrada." + CTA para /modelos |
| anterior = 0 no IndicadorTendencia | `—` muted (sem chip "novo") |
| Range custom inválido no dialog | "Aplicar" bloqueado com mensagem inline |
| Mudança de filtro | refetch sem skeleton; dados antigos ficam visíveis durante transição |
| Realtime com novo atendimento/Pix/escalada | blocos atualizam silenciosamente |
| Período "Tudo" | inclui todos os atendimentos sem corte de data |

---

## Relação com as outras telas

| O que Fernando vê no Dashboard | Para onde vai | O que faz lá |
|---|---|---|
| Etapa "Perdido" / "Saídas perdidas" | `/atendimentos?estado=Perdido` | Revisa atendimentos perdidos |
| Etapa "Triagem" ou outra | `/atendimentos?estado=Triagem` | Vê atendimentos naquele estado |
| Linha "Preço" em perdas | `/atendimentos?estado=Perdido&motivo_perda=preco` | Entende o contexto das perdas por preço |
| Linha de motivo de escalada | `/atendimentos?ia_pausada=true&motivo_escalada=...` | Vê conversas que geraram aquele motivo |
| Linha de modelo no ranking | `/modelos?modelo={id}&aba=perfil` | Revisa a configuração da modelo |

---

## Oportunidades de iteração identificadas

1. **`TilePixRevisao` não integrado** — o componente existe e a API retorna `pix_em_revisao_pendentes_total`, mas não há bloco visual no Dashboard. Quando há Pix pendentes, Fernando só descobre no Painel Geral.
2. **Funil sem indicação de gargalo** — Fernando precisa identificar onde o volume cai mais entre etapas. Realçar a maior queda percentual entre dois estados consecutivos daria o gargalo imediatamente.
3. **Taxa de conversão sem contexto de meta** — 73% é bom? Sem benchmark ou meta, o número é difícil de interpretar. Uma linha de referência ou meta configurável daria contexto.
4. **Motivos de escalada sem agrupamento semântico** — a decisão de usar string exata é correta para auditoria, mas pode dificultar a identificação de padrões em operações maiores. Um campo de "motivo canônico" ao lado do texto livre resolveria sem perder a auditoria.
5. **Ranking sem histórico de posição** — Fernando não sabe se a Júlia subiu ou desceu em relação à semana anterior. Um chip de tendência na posição (como `IndicadorTendencia`) daria esse contexto.
6. **Ticket médio sem segmentação por tipo** — atendimentos internos e externos têm valores muito diferentes; o ticket médio agregado esconde essa distinção.
7. **Período "Tudo" sem âncora temporal** — quando Fernando seleciona "Tudo", o header não exibe range (pois só exibe quando há `de` e `ate`). Fernando não sabe qual é o início do histórico da operação.
