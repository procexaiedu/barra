# Mídia de visualização única (view-once) via Evolution

Referência: **Mídia exclusiva** (CONTEXT.md), `docs/agente/01 §6.13`.

## Situação (verificada no código-fonte, jul/2026)

A Evolution API v2 **oficial** (branch `main`, v2.3.7, `baileys@7.0.0-rc.9`) **não expõe**
`viewOnce` no endpoint `POST /message/sendMedia`:

- `SendMediaDto` não tem o campo (`src/api/dto/sendMessage.dto.ts`).
- O handler `mediaMessage()` → `prepareMediaMessage()` monta `{ imageMessage }` / `{ videoMessage }`
  via `generateWAMessageFromContent` **sem** passar view-once
  (`src/api/integrations/channel/whatsapp/whatsapp.baileys.service.ts`).
- `gh search code "viewOnce"` no repo → só usos de **recebimento** (`ExtendedIMessageKey.isViewOnce`)
  e o wrapper `viewOnceMessage` usado como **truque de renderização de botões** (PIX/nativos) —
  nada de mídia efêmera de envio.
- A feature ([issue #1651](https://github.com/evolution-foundation/evolution-api/issues/1651)) foi
  **fechada sem implementação**.

Logo: mandar `"viewOnce": true` no body do `sendMedia` na Evolution oficial é **ignorado**.

## Por que dá para resolver

A **Baileys** (lib por baixo da Evolution) **suporta** view-once nativamente: quando o content tem
`viewOnce: true`, ela envolve a mensagem em `{ viewOnceMessage: { message: m } }`
(`Baileys/src/Utils/messages.ts:614`). Como a Evolution usa `generateWAMessageFromContent`
(e **não** `generateWAMessageContent`, que é onde mora aquela lógica), o wrapper precisa ser
aplicado manualmente. É um patch de ~2 pontos num **fork/build próprio da Evolution**.

## Patch do fork da Evolution

### 1. `src/api/dto/sendMessage.dto.ts`

Adicionar o campo em `MediaMessage` **e** em `SendMediaDto` (o handler passa um `SendMediaDto`
para `prepareMediaMessage`, tipado como `MediaMessage`):

```diff
 export class MediaMessage {
   mediatype: MediaType;
   mimetype?: string;
   caption?: string;
   // for document
   fileName?: string;
   // url or base64
   media: string;
+  // envia como visualização única (WhatsApp view-once)
+  viewOnce?: boolean;
 }
```

```diff
 export class SendMediaDto extends Metadata {
   mediatype: MediaType;
   mimetype?: string;
   caption?: string;
   // for document
   fileName?: string;
   // url or base64
   media: string;
+  // envia como visualização única (WhatsApp view-once)
+  viewOnce?: boolean;
 }
```

### 2. `src/api/integrations/channel/whatsapp/whatsapp.baileys.service.ts`

Em `prepareMediaMessage`, envolver o content no wrapper `viewOnceMessage` quando pedido —
replicando exatamente o que a Baileys faz no `generateWAMessageContent`:

```diff
-      return generateWAMessageFromContent(
-        '',
-        { [mediaType]: { ...prepareMedia[mediaType] } },
-        { userJid: this.instance.wuid },
-      );
+      const mediaContent = { [mediaType]: { ...prepareMedia[mediaType] } };
+      const finalContent = mediaMessage.viewOnce
+        ? { viewOnceMessage: { message: mediaContent } }
+        : mediaContent;
+      return generateWAMessageFromContent('', finalContent, { userJid: this.instance.wuid });
```

> Só image/video/audio aceitam view-once no WhatsApp. Documento não. Para o nosso uso
> (foto e vídeo da Mídia exclusiva — decisão 2026-07-10) isso basta; se quiser barrar document,
> condicione também por `type`.

### 3. Build e deploy da imagem patchada (runbook)

Prod hoje roda `atendai/evolution-api:v2.3.7` (`infra/compose/stack.barra.yml:52`), como **serviço Swarm**
na stack `barra-vips`, com `env_file: ./env/evolution.env` e volume `evolution_data:/evolution/instances`
(sessões das instâncias — preservar o path e a major version, senão corrompe as sessões conectadas).

**Todo o deploy recai na regra §0 — autorização explícita, frase a frase. Os passos 1–4 (build/push)
não tocam prod; os passos 5–8 tocam.**

1. **Clonar na tag exata de prod** (paridade — não usar `main`):
   ```bash
   git clone --branch v2.3.7 --depth 1 https://github.com/EvolutionAPI/evolution-api.git evo-fork
   cd evo-fork
   ```
2. **Aplicar o patch** das seções 1 e 2 acima (3 pontos: 2 no DTO, 1 no service). Confira que os
   alvos batem com a tag; se divergirem, aplique nos mesmos pontos lógicos (`prepareMediaMessage`
   e `SendMediaDto`/`MediaMessage`).
3. **Buildar a imagem** com tag própria e versionada pelo patch:
   ```bash
   docker build -t <registry>/evolution-api:v2.3.7-viewonce1 .
   ```
4. **Push para um registry acessível pelos nós do Swarm** (Docker Hub privado, GHCR, ou registry
   próprio). Sem registry alcançável, o Swarm não faz pull em todos os nós.
   ```bash
   docker push <registry>/evolution-api:v2.3.7-viewonce1
   ```
5. **Trocar a imagem no compose** — `infra/compose/stack.barra.yml:52`:
   ```yaml
   image: <registry>/evolution-api:v2.3.7-viewonce1
   ```
6. **Redeploy do serviço** — ⚠️ **NÃO** usar `StackGitRedeploy` (zera o Env da stack e derruba prod)
   nem `docker restart` (cria task órfã no Swarm). Usar update forçado do serviço com a nova imagem:
   ```bash
   docker service update --image <registry>/evolution-api:v2.3.7-viewonce1 --force barra-vips_evolution
   ```
   A instância reconecta do volume `evolution_data` (sessão preservada). Confirmar `1/1` replicas.
7. **Ligar o toggle no Barra**: `EVOLUTION_VIEW_ONCE=true` no Env da stack (api + worker) e
   `service update --force` nos dois serviços (o worker é quem envia a mídia — ver
   [[deploy_agente_roda_no_worker]]).
8. **Verificar ao vivo**: mandar uma foto (e um vídeo) pelo agente num chat de teste e confirmar no
   celular que abre como visualização única; conferir o `envios_evolution`/trace do turno.
   Rollback = voltar a `image: atendai/evolution-api:v2.3.7` + `EVOLUTION_VIEW_ONCE=false`.

**Custo recorrente**: rebase do fork a cada upgrade da Evolution (o patch é pequeno e isolado).

## Lado Barra (já pronto)

O código do Barra já consome isto atrás de um toggle:

- `settings.evolution_view_once` (**default `False`**).
- `EvolutionClient.enviar_midia` injeta `body["viewOnce"] = True` **só** quando
  `view_once and settings.evolution_view_once` (`core/evolution.py`).
- O worker `_enviar_midias` passa `view_once=True` para **toda mídia — foto e vídeo**
  (`workers/envio.py`; decisão 2026-07-10: a foto exclusiva também vai view-once). `image`/`video`
  aceitam view-once no WhatsApp, então o patch cobre os dois.

**Para ligar quando o fork estiver em prod:** setar `EVOLUTION_VIEW_ONCE=true` no Env da stack.
Com o toggle off, nada muda — a mídia vai normal (fallback P0).

Fontes: [SendMediaDto / Evolution](https://github.com/EvolutionAPI/evolution-api) ·
[Baileys `viewOnce`](https://baileys.wiki/docs/api/type-aliases/AnyMediaMessageContent/) ·
[Baileys wrapper `messages.ts`](https://github.com/WhiskeySockets/Baileys/blob/master/src/Utils/messages.ts).
