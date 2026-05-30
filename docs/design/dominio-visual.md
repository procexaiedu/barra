# Domínio → Visual

Mapeia os termos do `CONTEXT.md` para a representação visual canônica do painel. Esta é a tradução obrigatória: alterar a cor de "Pix em revisão" ou inventar variante para "Handoff" sem atualizar este arquivo é regressão.

Complementa o `DESIGN.md` (raiz), que é a fonte canônica de tokens e regras visuais. O DESIGN.md cobre o sistema visual; este arquivo cobre o vínculo estado-de-negócio → token. Quando o código mudar, este arquivo muda junto; quando contradisser o código, o código vence (ver `CLAUDE.md` §0).

## Estados de atendimento

| Termo (CONTEXT.md) | Badge `variant` | Borda esquerda | Cor texto | Ícone (lucide) |
|---|---|---|---|---|
| Ativo / Em execução | `active` | — | `text-state-active` (gold) | — |
| IA pausada (genérico) | `paused` | — | `text-state-paused` (ink-600) | — |
| Handoff aguardando humano | `handoff` | `border-l-warn-500` | `text-state-handoff` | `Clock` |
| Pix em revisão | `revisao` | `border-l-danger-500` | `text-state-handoff` (mesmo amarelo da pílula, mas borda vermelha indica gravidade) | `AlertCircle` |
| Modelo em atendimento | `info` | `border-l-info-500` | `text-state-info` | `ClockAlert` |
| Registro de resultado fechado | `closed` | — | `text-state-closed` (success) | — |
| Registro de resultado perdido | `lost` | — | `text-state-lost` (danger) | — |

Fonte canônica: `CardDestaque.tsx` (`BADGE_MAP`). Quando adicionar novo `IaPausadaMotivo`, atualizar aqui e o mapa lá juntos.

## Urgência temporal

Pattern em `CardDestaque.tsx` (`urgenciaClasse`):

| Tempo desde IA pausada | Token | Sinal visual |
|---|---|---|
| ≤ 30 min | `text-text-muted` | Neutro — operador tem tempo |
| 31 min – 2 h | `text-warn-500` | Atenção — entrar logo |
| > 2 h | `text-danger-500` | Crítico — risco de perda |

Esta escala se aplica a **qualquer** tempo "aguardando ação humana", não só Pix. Reutilize a função; não duplique thresholds em outro arquivo.

## Tendência (delta)

Pattern em `TileMetrica.tsx` (`TendenciaTag`).

| Delta | Cor | Ícone | Quando `inverso=true` |
|---|---|---|---|
| `> 0` | `text-success-500` | `TrendingUp` | Inverte: positivo vira ruim (ex: motivos de perda subindo é negativo) |
| `< 0` | `text-danger-500` | `TrendingDown` | Inverte: negativo vira bom (ex: tempo de resposta caindo) |
| `= 0` | `text-text-muted` | `Minus` | — |

Use `inverso` quando "menos é melhor": perdas, tempo médio, abandono. Default é "mais é melhor": fechamentos, valor final, ativos.

## Motivo de perda

Taxonomia fechada (CONTEXT.md). Cor: sempre `text-state-lost` (danger). **Não tentar diferenciar visualmente** os motivos por cor: são todos perda.

| Motivo | Label exibido |
|---|---|
| `preco` | Preço |
| `sumiu` | Sumiu |
| `risco` | Risco |
| `indisponibilidade` | Indisponibilidade |
| `fora_de_area` | Fora de área |
| `outro` | Outro (com observação) |

Ordenação canônica em filtros: `preco`, `sumiu`, `indisponibilidade`, `fora_de_area`, `risco`, `outro`. Não alfabético, operacional (mais frequentes primeiro).

## Pix de deslocamento

Estados visuais distintos:

| Estado | Borda | Badge | Onde aparece |
|---|---|---|---|
| `aprovado` | — (sem borda especial) | `closed` | Histórico |
| `pendente` / em validação | `border-l-info-500` | `handoff` | Toolbar de revisão |
| `em_revisao` | `border-l-danger-500` | `revisao` | Topo do painel — prioridade máxima |
| `recusado` | — | `lost` | Histórico |

Pix em revisão **sempre** abre handoff e gera card no Painel: não é decisão visual, é regra de negócio. O design só reflete.

## Coordenação por modelo (grupo)

Identificada por:
- Nome da modelo + chip `#numero_curto` em `font-mono text-xs` no rodapé do card.
- Nunca abreviar nome da modelo em card de painel. Em lista densa, truncar com `truncate`.
- Ícone padrão para "ação na coordenação": `MessagesSquare` (lucide).

## IA Admin (P1)

**Ainda não tem UI no P0.** Não criar componente especulativo. Quando entrar, terá pasta própria `components/iaadmin/`.

## Aviso de saída / Foto de portaria

Eventos do fluxo interno. Mostrados no `HistoricoMensagens` (`components/atendimentos/HistoricoMensagens.tsx`) e no Painel quando geram handoff.

| Evento | Ícone | Cor de linha | Card no painel? |
|---|---|---|---|
| Aviso de saída | `Bell` ou `MapPin` | `text-text-secondary` (normal — IA continua ativa) | Não — card simples na Coordenação por modelo, sem handoff |
| Foto de portaria | `Camera` ou `ImageIcon` | `text-info-500` (info — handoff implícito) | Sim — borda `border-l-info-500`, variante `info` ("Modelo atendendo") |

Imagem da Foto de portaria abre em `ImageLightbox` ao clicar. **Não** rodar inspeção visual no P0: só armazenar e exibir.

## Devolução para IA

Botão `variant="default"` com texto literal **"Devolver para IA"** (com I+A maiúsculos). Não mudar para "Retomar IA", "Reativar IA": o termo do CONTEXT.md é fixo.

Aparece em card quando `ia_pausada_motivo === "modelo_em_atendimento"` (pattern em `CardDestaque.tsx`). Confirmação via `AlertDialog`.

## Conversa cliente

Avatar padrão: inicial do nome em círculo `rounded-full bg-ink-300 text-text-primary`. Quando há foto do cliente (raro), `next/image` em `rounded-full`.

Número do cliente: `font-mono`, formatado pelo `formatTelefone()`. Quando há nome cadastrado, nome primeiro, telefone abaixo em `text-xs text-text-muted`.

**Isolamento por par (cliente, modelo)** é regra de negócio (CONTEXT.md): a IA da modelo A nunca cita histórico do cliente com modelo B. Visualmente isso significa: na rota `/clientes/<id>`, a aba mostra **uma `ListaConversas`**, e cada conversa abre **somente** o histórico daquele par. Não inventar tela "perfil unificado do cliente".

## Símbolos de identidade

| Símbolo | Significado |
|---|---|
| `#<numero_curto>` | Atendimento — sempre prefixo `#`, sempre `font-mono` |
| `@<modelo_slug>` | (P1) referência a modelo — ainda não em uso |
| Inicial em círculo | Cliente sem foto |
| Gold dot | Item de marca / favorito (raro) |

## Quando o domínio cresce

Antes de criar variante visual nova:
1. Verificar se o termo já está em `CONTEXT.md`. Se não, **parar**: pedir ao planejador para registrar primeiro.
2. Verificar se o estado mapeia a algum `state-*` existente. Reutilizar.
3. Só criar token novo se for genuinamente novo significado. Adicionar em `globals.css` `:root` + `.dark` + `@theme inline`, atualizar o `DESIGN.md`, e aqui: tudo no mesmo PR.
