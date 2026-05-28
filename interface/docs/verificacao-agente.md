# Verificação agent-native

Padrão inspirado no workshop *"How we Claude Code"* (Fase 3): a verificação fica
**embutida no artefato**. Cada componente publica seu estado relevante no DOM como um
blob JSON, e um conjunto de **invariantes** (TS puro) roda sobre esse estado em três
superfícies que compartilham a mesma fonte de verdade.

## Peças

- **Contrato** (`src/lib/verify/contract.ts`): `emitirContrato(id, estado)` →
  `data-verify="<id>"` + `data-verificacao="<json>"`, espalhado na raiz do componente.
  Quem verifica lê `data-verificacao` em vez de raspar a UI.
- **Spec/invariantes** (`src/lib/verify/spec.ts` + `specs/*.ts`): funções puras sobre o
  estado parseado. Fonte de verdade única.
- **Manifesto** (`src/lib/verify/manifest.ts`): registro `{ id, url, selector, rodar }`.
- **Fixtures** (`/verificacao/*`, `/demo-mapa`): rotas públicas (liberadas no middleware)
  que montam o componente real com dados mock; `?quebrar=1` publica estado inconsistente.

## As três superfícies

1. **Headless / CI** — `pnpm verify` (project `verificacao` do Playwright,
   `tests/e2e/verificacao.spec.ts`): navega a cada `url` do manifesto, lê o contrato e
   asserta as invariantes. É o gate determinístico.
2. **Dashboard human-readable** — `/verificacao`: uma `<iframe>` por spec; "Rodar tudo"
   lê os contratos e mostra pass/fail por invariante. "Quebrar (demo)" recarrega com
   `?quebrar=1`.
3. **Agent-first (este protocolo)** — eu, via Playwright MCP.

## Protocolo agent-first (para o Claude)

Para verificar uma superfície sem rodar a suíte:

1. Garanta o dev server: `pnpm -C interface dev` (localhost:3000).
2. Para cada entrada do manifesto (`src/lib/verify/manifest.ts`):
   - `browser_navigate` → `http://localhost:3000<url>`.
   - `browser_evaluate` lendo o contrato e checando as invariantes daquela spec, ex.:
     ```js
     () => {
       const el = document.querySelector('[data-verify="funil"]')
       const e = JSON.parse(el.getAttribute('data-verificacao'))
       const soma = e.etapas.reduce((s, x) => s + x.perdas, 0)
       return { perdas_somam_total: e.perdidos_total === soma, e, soma }
     }
     ```
3. **Diagnóstico**: quando uma invariante falha, o estado publicado já contém os números
   — reporte o esperado vs. o obtido (ex.: `perdidos_total=99` vs `soma=45`). Não é
   preciso inferir da imagem.
4. **Evidência**: `browser_take_screenshot` (o "gravar clipe → S3" do vídeo; no P0 fica
   em screenshot, MinIO depois).

## Adicionar uma nova superfície

1. `emitirContrato("<id>", <estado>)` na raiz do componente.
2. `src/lib/verify/specs/<id>.ts` com `EstadoX` + invariantes.
3. Registrar no `manifest.ts`.
4. Fixture pública em `/verificacao/<id>` (ou reusar uma rota já liberada) com `?quebrar=1`.
5. `pnpm verify` verde.
