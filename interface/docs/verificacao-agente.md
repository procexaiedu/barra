# Verificação agent-native

Padrão inspirado no workshop *"How we Claude Code"* (Fase 3): a verificação fica
**embutida no artefato**. Cada componente publica seu estado relevante no DOM como um
blob JSON, e quem verifica lê esse blob em vez de raspar a UI renderizada.

> **Mudança de escopo (auditoria de segurança).** As **fixtures públicas**
> (`/verificacao/*`, `/demo-mapa`, `/painel-preview`) eram bypass de autenticação no
> middleware e ficaram expostas em produção — uma delas renderizava o chrome completo do
> painel. Foram **removidas**, e com elas as duas superfícies que dependiam delas: o
> **gate headless** (`pnpm verify` / `tests/e2e/verificacao.spec.ts`) e o **dashboard**
> `/verificacao`. As invariantes (`src/lib/verify/spec.ts` + `specs/*.ts`) e o manifesto
> foram removidos junto, por terem ficado órfãos. Sobrou o **contrato**, que é a peça que
> o código de produção usa.

## O que sobrou

- **Contrato** (`src/lib/verify/contract.ts`): `emitirContrato(id, estado)` →
  `data-verify="<id>"` + `data-verificacao="<json>"`, espalhado na raiz do componente.
  Continua emitido, hoje, por quatro componentes reais do painel:
  `FunilVendas` (`funil`), `BlocoNorteCotacao` (`norte`), `KanbanBoard` (`kanban`) e
  `MapaClientes` (`mapa`).
- **Leitura** — `lerContrato(el)` parseia o blob de um elemento.

## Protocolo agent-first (para o Claude)

Sem fixture pública, a leitura acontece na **rota autenticada real**:

1. Suba o dev server (`pnpm -C interface dev`) e autentique — via o project `authed` do
   Playwright (`tests/e2e/auth.setup.ts` grava `tests/e2e/.auth/state.json`).
2. Navegue à página que monta o componente (ex.: `/dashboard` para `funil`/`norte`,
   `/atendimentos` para `kanban`, `/clientes` para `mapa`).
3. Leia o contrato e cheque a invariante que interessa, ex.:
   ```js
   () => {
     const el = document.querySelector('[data-verify="funil"]')
     const e = JSON.parse(el.getAttribute('data-verificacao'))
     const soma = e.etapas.reduce((s, x) => s + x.perdas, 0)
     return { perdas_somam_total: e.perdidos_total === soma, e, soma }
   }
   ```
4. **Diagnóstico**: o estado publicado já contém os números — reporte esperado vs. obtido
   (ex.: `perdidos_total=99` vs `soma=45`), sem inferir da imagem.

## Se o gate determinístico for reconstruído

Não reintroduza rota pública. As opções sem bypass de auth são:

- **vitest** sobre as invariantes puras, alimentadas por fixtures em memória (não precisa
  de browser nem de rota) — cobre a regra, não a renderização; ou
- **Playwright no project `authed`**, lendo o contrato nas rotas reais já autenticadas —
  cobre ponta a ponta, mas as asserções passam a depender dos dados do ambiente.
