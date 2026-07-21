# Migração para a Evolution GO (cutover em produção)

A barra migrou o cliente WhatsApp da Evolution v2/v3 (Baileys) para a **Evolution GO**
(whatsmeow, stack `evolution-go` no Portainer, `https://evogo.procexai.tech`). O **código** já
está na branch e verde no gate; este runbook cobre o **cutover em produção** — cada passo aqui
atinge produção (CLAUDE.md §0) e exige autorização explícita do Fernando, frase a frase.

## ✅ Variante ativa (21/07): `elitebaby01` direta, sem router

`elitebaby01` está conectada na Evolution GO (celular pareado fora do nosso fluxo). Voltamos ao
cutover **direto** original (barra seta o próprio webhook) — não mais via `procex-teste`
compartilhada. `EVOLUTION_INSTANCIA=elitebaby01`, `EVOLUTION_WEBHOOK_CALLBACK_URL` aponta direto
pra `https://api-barra.procexai.tech/webhook/evolution` (sem router no meio).

**Gotcha corrigido nesta rodada**: como `elitebaby01` já estava `open`/logged-in ANTES do nosso
banco saber (`modelos.evolution_instance_id` ainda NULL), o guard de idempotência do topo de
`conectar_whatsapp` não pegava esse caso — cairia em `conectar_instancia` (`immediate=True`),
que força nova sessão de pareamento e **desconectaria** o WhatsApp já linkado. Corrigido em
`dominio/modelos/routes.py`: antes de chamar `conectar_instancia`, checa `estado_conexao` ao
vivo; se já `open`, só reafirma o webhook (`definir_webhook`, `immediate=False`) e marca
`evolution_status='conectado'` direto, sem gerar QR. Ver `test_modelos_integration.py::
test_conectar_whatsapp_instancia_ja_conectada_nao_forca_repareamento`.

**Passo manual que só o operador faz** (não dá pra automatizar sem UI): o painel não expõe campo
pra setar `evolution_instance_id` num nome pré-existente — hoje só nasce vazio (cria
`modelo-{id}`) ou já vem preenchido do cadastro. Pra apontar pra `elitebaby01`, precisa de um
`UPDATE barravips.modelos SET evolution_instance_id='elitebaby01' WHERE id=...` (escrita em prod,
autorização §0) ANTES de clicar "Conectar WhatsApp" no painel — só depois disso o guard acima
entra em jogo e evita o re-pareamento.

### Histórico: variante anterior (`procex-teste` via router, encerrada)

Entre 13/07 e 21/07 o piloto rodou via **`procex-teste`** (já pareada, `5519997858650`), instância
**compartilhada** entre 6 projetos via `router.procexai.tech`, porque não havia celular disponível
pra parear a `elitebaby01` na época. Registro do que era diferente nessa variante (não se aplica
mais, mas fica de referência caso precise repetir o padrão pra outra instância compartilhada):

- **Inbound via router, não direto.** O webhook da `procex-teste` aponta para
  `https://router.procexai.tech/api/hook/procex-shared`, que faz fan-out para 6 destinos —
  o da barra é `https://api-barra.procexai.tech/webhook/evolution?token=<EVOLUTION_WEBHOOK_TOKEN>`.
- **`EVOLUTION_WEBHOOK_CALLBACK_URL` fica VAZIO.** Se a barra setasse o próprio webhook no
  `/instance/connect`, sobrescreveria o do router e derrubaria os outros 5 projetos. Com o
  callback vazio ela nunca reescreve o webhook. Corolário: **não clicar "Conectar WhatsApp"**
  nessa instância no painel (o `connect immediate=True` força re-pareamento e desconecta o número).
- **`EVOLUTION_WEBHOOK_TOKEN` = o token que o router anexa** ao encaminhar pra cá
  (o `?token=` configurado no destino Elitebaby da rota `procex-shared`; **segredo — vive só no
  Env do stack `barra-vips` no Portainer**, nunca aqui), ainda distinto da GLOBAL_API_KEY.
- **`EVOLUTION_INSTANCIA=procex-teste`** e a modelo-piloto em prod precisa de
  `modelos.evolution_instance_id = 'procex-teste'` — é o que casa o inbound (eventos de outra
  instância chegam pelo número compartilhado mas são descartados como `unknown_instance`).
- O resto (GLOBAL_API_KEY em `EVOLUTION_API_KEY`, `EVOLUTION_MEDIA_HOSTS`, smoke) segue igual.

## O que mudou no código (referência)

- **Auth por instância**: operação (`/send/*`, `/message/*`, `/group/*`) é escopada pelo **token
  da instância** no header `apikey`, resolvido nome→token via `GET /instance/all` (global key) e
  cacheado. `EVOLUTION_API_KEY` passa a ser a **GLOBAL_API_KEY** da EvoGo.
- **Endpoints**: `/send/text`, `/send/media` (`type`, mídia por URL), `/message/markread`,
  `/message/presence`, `/group/info`; webhook setado no `/instance/connect` (`webhookUrl` +
  `subscribe[]`) — sem `/webhook/set`.
- **Webhook**: eventos whatsmeow (CamelCase `Message`/`Connection`, envelope `data.Info`/
  `data.Message`) convertidos para o shape v2 por `adaptar_webhook_go` (webhook/parser.py) e
  reusam todo o pipeline. Auth do webhook via `webhookUrl?token=` (a EvoGo não manda header).
- `modelos.evolution_instance_id` continua sendo o **nome** da instância (identidade estável, é o
  que casa no webhook). Sem schema novo.

## Env do stack `barra-vips` (Portainer) — trocar no cutover

> ⚠️ Redeploy git do stack ZERA o Env (ver `stackgitredeploy_apaga_env`). Aplique o Env e faça
> `service update --force` do worker+api; nunca `StackGitRedeploy` sem reinjetar o Env inteiro.

| Var | Valor v2 (antes) | Valor EvoGo (depois) |
|---|---|---|
| `EVOLUTION_BASE_URL` | (Evolution v2) | `https://evogo.procexai.tech` |
| `EVOLUTION_API_KEY` | chave v2 | **GLOBAL_API_KEY** da EvoGo (stack `evolution-go`) |
| `EVOLUTION_WEBHOOK_TOKEN` | token (== api_key na v2) | **token dedicado e DISTINTO da `EVOLUTION_API_KEY`** — ver aviso abaixo |
| `EVOLUTION_WEBHOOK_CALLBACK_URL` | URL do /webhook | URL pública do `/webhook/evolution` da barra |
| `EVOLUTION_MEDIA_HOSTS` | (inexistente) | `["minioback.procexai.tech"]` (host do MinIO da EvoGo p/ o anti-SSRF do download de mídia inbound) |
| `EVOLUTION_INSTANCIA` | `lucia` | **nome de uma instância EvoGo real** conectada (canal de alerta DEV); senão o relay Alertmanager dá 502 |

> 🔐 **`EVOLUTION_WEBHOOK_TOKEN` DEVE ser distinto da `EVOLUTION_API_KEY`.** A EvoGo não repassa
> header de auth no webhook, então o token viaja em `webhookUrl?token=` e a query aparece no
> access log do uvicorn. Como a `EVOLUTION_API_KEY` agora é a **GLOBAL_API_KEY** (cria/deleta
> instâncias na EvoGo), reusá-la como token do webhook vazaria a chave de admin no log. Use um
> segredo dedicado, sem privilégio de gestão, e rotacione-o à parte.

## Passos do cutover (ordem) — estado em 21/07: `elitebaby01` JÁ conectada, passos 1-2 pendentes

1. **Deploy do código** (branch `feat/evolution-go-elitebaby01`) no worker + api via
   `service update --force` (não `restart`, por causa de worker órfão no Swarm).
2. **Aplicar o Env** acima no stack `barra-vips` (`EVOLUTION_API_KEY` = GLOBAL_API_KEY da EvoGo,
   `EVOLUTION_INSTANCIA=elitebaby01`, `EVOLUTION_WEBHOOK_CALLBACK_URL` direto — ver compose).
3. **`UPDATE barravips.modelos SET evolution_instance_id='elitebaby01' WHERE id=<modelo>`** — só
   depois disso o painel enxerga a instância certa (sem esse passo "Conectar WhatsApp" criaria
   `modelo-{id}`, um nome novo, não `elitebaby01`).
4. **"Conectar WhatsApp" no painel** — como `elitebaby01` já está `open`/logged-in na EvoGo (número
   pareado fora do nosso fluxo, ~20/07), o fix desta rodada detecta isso via `estado_conexao` e
   **pula `conectar_instancia`** (que forçaria novo QR e desconectaria o número já linkado) — só
   reafirma o webhook. Não deve aparecer QR nem pedir novo pareamento. Se aparecer QR, PARAR: algo
   mudou (instância desconectou) e reconectar aqui geraria um pareamento novo de verdade.
5. **Smoke ao vivo** (grupo de teste interno, dentro do `JID_PERMITIDO` — NÃO abrir pra cliente
   real nesta etapa): mensagem de teste → a IA responde; confere `envios_evolution`/`mensagens`
   incrementando.

## Gaps que SÓ a verificação ao vivo fecha

Estes pontos foram implementados de forma defensiva a partir do playbook validado da ProcexAI
(vault DevContext), mas dependem de um payload/resposta real da EvoGo para cravar:

- **Mídia inbound (WEBHOOK_FILES)**: como a EvoGo entrega a mídia decifrada — base64 inline vs.
  URL do MinIO dela. O adaptador copia `data.base64` para dentro da `message`; se vier por URL, o
  `EVOLUTION_MEDIA_HOSTS` precisa listar o host. **Capturar um webhook de imagem real e conferir.**
- **Evento `Connection`**: o shape exato (campo de estado) não é documentado; `_estado_conexao_go`
  lê `state`/`status`/`Connected` defensivamente. Conferir com um pareamento real.
- **Resposta do `/send/*`**: o swagger devolve `gin.H` (não tipado); `_extrair_message_id` varre
  vários shapes (`id`/`key.id`/`Info.ID`, PascalCase). Confirmar o campo real do id no 1º envio.
- **`state` da presença**: mapeamos `composing`/`recording`→`{state, isAudio}`; confirmar que a
  EvoGo aceita esses valores.
- **`Info.Sender` em evento de GRUPO**: o adaptador prefere o JID `@s.whatsapp.net` real (entre
  Sender/SenderAlt) para `participant`, que alimenta o reconhecimento de Fernando (`_autor_grupo`,
  igualdade exata em `evolution_fernando_jids`). Confirmar ao vivo que o JID entregue casa o
  formato de `evolution_fernando_jids` (sem sufixo `:device`); se vier com `:device`, alinhar
  `evolution_fernando_jids` ou o match. Falha é fail-safe (comando ignorado, nunca misatribuído).
- **Contato frio → erro 463** (`NackCallerReachoutTimelocked`): o whatsmeow dá 463 no 1º disparo a
  contato que nunca falou com a instância. Não é bug da barra; o cliente esquenta ao mandar a 1ª
  msg. Relevante para reengajamento/reativação a frio — monitorar.
- **view-once (Mídia exclusiva)**: o `/send/media` da EvoGo oficial não expõe `viewOnce`, então a
  mídia vai normal e o campo enviado sob o toggle é ignorado. O patch da EvoGo que habilita está
  pronto em `docs/patches/evolution-go-view-once.patch` (build/deploy pendentes, §0) —
  ver `docs/evolution-view-once.md`.

## Rollback

Reverter o Env do `barra-vips` para os valores v2 e `service update --force`. O código é
compatível com os dois durante a transição (o adaptador Go→v2 só ativa em payload Go; payload v2
passa reto), então não exige reverter o deploy — só o Env e re-pareamento na v2.
