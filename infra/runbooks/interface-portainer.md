# Runbook — migrar a interface da Vercel para o Portainer

Tira o painel Next.js da Vercel (conta `procexais-projects`, projeto `barra`, domínio
`elitebaby.procexai.tech` — **pausado por falha de pagamento**) e sobe como o serviço
`barra-interface` na stack git-backed `barra-vips`. Definição da stack: ADR 0018 +
`infra/runbooks/stack-git-backed.md`. O serviço já está commitado em
`infra/compose/stack.barra-portainer.yml`; este runbook é o **cutover do operador**.

> ✅ **Executado em 2026-07-08.** Interface no ar em `https://elitebaby.procexai.tech` pelo
> Portainer (cert Let's Encrypt válido), login OK (Supabase `db.procexai.tech`), chamadas à
> `api-barra.procexai.tech` 200 sem erro de CORS. Detalhes reais divergentes do plano abaixo:
> o DNS ficou como **CNAME `elitebaby` → `api-barra.procexai.tech`** (a Cloudflare não troca o
> tipo de um registro inline, então manteve-se CNAME em vez de virar A → IP); e
> **Google Maps (08/07) — causa raiz corrigida.** A `AIzaSy...bwPs` do `.env` de dev era do
> projeto Google Cloud **`barravips`, que NÃO tem billing** → `ApiNotActivatedMapError`. A key
> de **produção** é outra: **"EliteBaby - Places API (GMaps)"** (`AIzaSyCRhU...`) no projeto
> **`procexai-interno`** (COM billing, "My Billing Account"; referrer `elitebaby.procexai.tech/*`).
> Correções aplicadas: (a) adicionada a **Maps JavaScript API** a essa key (só tinha Places
> API New — por isso o autocomplete funcionava na Vercel mas o mapa não); (b) criado um Map ID
> `225d14cba5e607e320f9f214` em `procexai-interno`; (c) trocadas `NEXT_PUBLIC_GOOGLE_MAPS_API_KEY`
> (→ EliteBaby) e `NEXT_PUBLIC_GOOGLE_MAPS_MAP_ID` (→ o novo) no Env do stack + redeploy. O
> `ApiNotActivatedMapError` **sumiu** e os scripts do Google Maps carregam 200 com a key de
> prod. **Mapa RESOLVIDO (08/07):** era mesmo **propagação lenta do Google** da adição da Maps
> JS API à key EliteBaby + dos Map IDs novos. Depois de propagar, os tiles pintam normalmente
> em `/demo-mapa` (base + pins, zero erro) e em `/clientes` (mapa do Brasil completo). Sintoma
> de warmup: no 1º load da sessão os tiles demoram ~30–40s (cache frio) e o fundo fica bege
> nesse intervalo — não é bug, só esperar. Rede confirmou `mapConfigs:batchGet` (map_id raster
> `225d14cba5e607e3cb888254`) e `GetViewportInfo` retornando 200. **Nada de config foi refeito
> — estava certa desde a correção; só faltava propagar.** Map ID `750c...`/vetorial e o do
> projeto `barravips` (sem billing) ficaram órfãos — ignorar.
>
> **Nota de dados (não é bug):** na aba Mapa de `/clientes`, prod mostra "0 clientes localizados
> · 403 sem endereço" — os 403 clientes reais vieram do import de corpus **sem endereço externo
> geocodificado** (sem lat/lng), então não há pins (só atendimento externo geocodificado plota,
> ADR 0008). O motor do mapa funciona (provado no `/demo-mapa`, que usa pontos sintéticos).
> Popular pins reais exige geocodificar os atendimentos externos — trabalho de dados à parte.
>
> Pendência restante: cancelar o billing/projeto na Vercel.

## Como funciona (o que foi commitado)

- **Mesmo padrão de api/worker (git-clone-no-boot):** imagem `node:22-bookworm-slim`, clona o
  `main`, `pnpm install --frozen-lockfile` + `pnpm build` + `pnpm start` no boot. Sem imagem
  versionada por ora — o cutover para GHCR é o DEPLOY-03, junto com api/worker.
- **Boot lento (~3–5 min):** o `next build` roda a cada subida. Novo código de front só entra
  com **`docker service update --force barra-vips_barra-interface`** (idêntico a redeploy de
  prompt no worker) — push de código sozinho **não** recria o serviço (spec não muda).
- **Traefik:** `Host(elitebaby.procexai.tech)`, porta 3000, `certresolver le`. Rede
  `traefik_public` (a interface fala com api/Supabase por HTTPS público, não precisa de
  `supabase_default`).
- **`NEXT_PUBLIC_*` são baked no build:** `API_URL` e `SUPABASE_URL` ficam versionados no
  compose (config não-sensível, espírito do ADR 0018); as chaves são `${VAR}` do Env do stack.

## Pré-requisitos

1. **Env vars do stack no Portainer** (stack `barra-vips` → Editor → seção Env). Copiar os
   valores da Vercel: projeto `barra` → **Environment Variables** → scope **Production**.

   | Env var (Portainer)              | Origem (Vercel, Production)        | Segredo? |
   |----------------------------------|-----------------------------------|----------|
   | `NEXT_PUBLIC_SUPABASE_ANON_KEY`  | `NEXT_PUBLIC_SUPABASE_ANON_KEY`   | sim      |
   | `NEXT_PUBLIC_GOOGLE_MAPS_API_KEY`| `NEXT_PUBLIC_GOOGLE_MAPS_API_KEY` | sim      |
   | `NEXT_PUBLIC_GOOGLE_MAPS_MAP_ID` | `NEXT_PUBLIC_GOOGLE_MAPS_MAP_ID`  | não      |

   `GITHUB_PAT` já existe (usado por api/worker para o clone) — reaproveitado, não recriar.

   > ⚠️ **Conferir o par `SUPABASE_URL` + `ANON_KEY`.** O compose versiona
   > `NEXT_PUBLIC_SUPABASE_URL=https://db.procexai.tech` (Supabase self-hosted de prod, igual
   > à `SUPABASE_URL` da api). A `ANON_KEY` copiada da Vercel **tem que ser a dessa mesma
   > instância**. Se a Vercel-prod apontava para outra URL de Supabase, alinhe as duas (edite
   > o compose por PR **e** a `ANON_KEY` no Env) — senão o login quebra por chave/instância
   > incompatível. O `sb_publishable_...` do `.env.example` é do Supabase **cloud** (dev), não
   > serve para prod.

2. **CORS já cobre o domínio:** `CORS_ORIGINS` da api já inclui
   `https://elitebaby.procexai.tech` e o regex `*.procexai.tech` é rede de segurança. Nada a
   mudar no backend.

## Cutover

1. **Setar as 3 Env vars** do passo 1 no Env do stack `barra-vips` (Portainer). Salvar.
2. **Redeploy da stack** para materializar o serviço novo. Preferir o **webhook do GitHub**
   (preserva o `Env` guardado). Se redeployar pela UI do Portainer, também preserva o `Env`.
   **Nunca** disparar `StackGitRedeploy`/`StackUpdateGit` pela API/MCP sem repassar o array
   `Env` completo — zera os 12 segredos e derruba a stack (ver aviso em
   `stack-git-backed.md`).
3. **Acompanhar o boot** (~3–5 min): `docker service logs -f barra-vips_barra-interface` —
   esperar `pnpm install` → `next build` (`✓ Compiled`) → `next start` (`Ready`).
   O Traefik emite o cert LE de `elitebaby.procexai.tech` no primeiro request.
4. **Verificar antes do DNS** (o domínio ainda aponta pra Vercel): validar pelo IP do Swarm
   com o Host forçado —
   `curl -k -H 'Host: elitebaby.procexai.tech' https://<ip-do-traefik>/` → 200 + HTML do
   painel.
5. **Cortar o DNS:** em `procexai.tech`, repontar `elitebaby` do CNAME da Vercel
   (`cname.vercel-dns.com`) para o **mesmo alvo dos outros `*.procexai.tech`** (registro
   A/CNAME que `api-barra`/`grafana-barra` usam para chegar no Traefik). Propagação: minutos.
6. **Remover o domínio da Vercel:** projeto `barra` → Domains → remover `elitebaby.procexai.tech`
   (evita conflito de verificação e libera o domínio). Não apagar o projeto ainda — serve de
   rollback rápido enquanto o piloto estabiliza.

## Verificação (pós-cutover)

- `https://elitebaby.procexai.tech` carrega o painel; **login funciona** (prova o par
  `SUPABASE_URL`+`ANON_KEY`).
- Chamadas do painel batem em `https://api-barra.procexai.tech` sem erro de CORS (console
  limpo).
- Autocomplete de endereço e Mapa de clientes renderizam (prova a `GOOGLE_MAPS_API_KEY` +
  `MAP_ID`).
- `docker service ps barra-vips_barra-interface` → 1 task `Running`.
- **Imagens (`next/image`):** o lightbox de mídia e o histórico de mensagens usam `next/image`.
  O `pnpm` 10+ **ignora o build script do `sharp`** (dep transitiva do Next) — o build passa
  igual, mas a otimização de imagem dessas duas telas pode cair no fallback não-otimizado.
  Não derruba o painel. Se as imagens falharem em prod, mitigar adicionando `sharp` como
  dependency explícita no `interface/package.json` + `onlyBuiltDependencies: [sharp]` no
  `pnpm-workspace.yaml` (fecha o gap do `allowBuilds` placeholder atual).

## Rollback

- **DNS:** repontar `elitebaby` de volta para o CNAME da Vercel e re-adicionar o domínio no
  projeto (a Vercel volta a servir assim que o pagamento normalizar). Enquanto a conta Vercel
  estiver pausada, este caminho **não** é confiável — priorizar consertar o serviço no
  Portainer.
- **Serviço:** `docker service logs` para diagnosticar; corrigir Env/compose e
  `docker service update --force barra-vips_barra-interface`. **Nunca** `docker restart` no
  Swarm.

## Depois (quando estabilizar)

- Adicionar `barra-interface` ao cutover de imagem versionada (DEPLOY-03) junto com api/worker
  — elimina o `next build` no boot e dá rollback por tag.
- Cancelar/encerrar o projeto na Vercel.
