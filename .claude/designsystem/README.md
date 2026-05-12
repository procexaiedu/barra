# Design System — Barra Vips

Fonte canônica do visual da `interface/`. Tudo aqui reflete o estado real em `interface/src/app/globals.css` e `interface/src/components/ui/`. Quando o código mudar, este diretório muda junto. Quando este diretório contradisser o código, **o código vence** — abra um issue ou atualize aqui antes de propagar.

## Para quem é

- `codificador-interface` consulta `padroes.md` e `componentes.md` antes de criar tela.
- `planejador-barra` consulta `dominio.md` ao decidir variante/cor para estado de negócio.
- `revisor-barra` checa `padroes.md` contra o diff para reprovar prop boolean proliferation, falta de `data-slot`, mistura de tokens.

## Arquivos

| Arquivo | Conteúdo |
|---|---|
| [tokens.md](tokens.md) | Cores (ink/gold/estado), tipografia (Inter/Cormorant/JetBrains), espaçamento, raios, sombras, focus ring |
| [componentes.md](componentes.md) | Inventário de `components/ui/` com variantes, tamanhos e quando usar cada um |
| [padroes.md](padroes.md) | Composição (data-slot), layouts de página, estados (loading/empty/error), acessibilidade, motion |
| [dominio.md](dominio.md) | Mapa termo de domínio → token visual (Pix em revisão, Handoff, urgência, Motivo de perda) |

## Princípios

1. **Tokens primeiro, valores hardcoded nunca.** Se uma cor não está em `tokens.md`, ela não entra em código. Cor nova → adicionar primeiro em `globals.css` (`:root`) e em `@theme inline`, depois aqui, depois usar.
2. **Domínio em PT-BR, primitivos em EN.** `Card`, `Button`, `Dialog` permanecem em inglês (vem do shadcn/ui). Tudo construído por cima (`CardDestaque`, `TileMetrica`, `BadgeEstadoAtendimento`) em português.
3. **shadcn/ui data-slot é regra dura.** Toda primitiva nova em `components/ui/` precisa de `data-slot="<nome>"` no root e nas partes nomeadas (ver `padroes.md`).
4. **Tema único: dark.** O `html` já entra com classe `dark` em `app/layout.tsx`. Não escrever variantes `dark:` por defeito — só quando a primitiva shadcn original já trazia. Não introduzir light mode sem decisão arquitetural.
5. **Mobile bloqueado, desktop livre.** A `interface/` é desktop-only (`MobileBlocker`). Não otimizar para telas < `lg` (1024 px). Tudo abaixo disso vê o blocker.
6. **Estados de domínio têm cor fixa.** Pix em revisão é sempre `danger-500` borda, `handoff` sempre `warn-500`, `modelo_em_atendimento` sempre `info-500`. Não inventar variação para "destacar mais" — ver `dominio.md`.

## Convenções não negociáveis

- **Nunca** usar Tailwind color utilities cru (`bg-yellow-500`, `text-red-600`). Sempre token (`bg-warn-500`, `text-danger-500`).
- **Nunca** redefinir radius local. Usar `rounded-md`, `rounded-lg`, `rounded-xl` mapeados a `--radius` (0.5rem).
- **Nunca** criar componente novo em `components/ui/` sem variant via `cva` quando houver >1 estado visual.
- **Sempre** adicionar `focus-visible:ring-ring focus-visible:ring-2` (ou variante shadcn equivalente) em qualquer elemento interativo custom.
- **Sempre** anotar `aria-label` em botões só-ícone.

## Como propor mudança

1. Edite `interface/src/app/globals.css` (tokens) ou `interface/src/components/ui/` (primitivas).
2. Atualize o arquivo correspondente aqui no mesmo PR.
3. Marque no PR: "design-system: <token|componente|padrão> alterado — `tokens.md`/`componentes.md`/`padroes.md` atualizado".
