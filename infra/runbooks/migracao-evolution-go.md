# Migração para a Evolution GO (cutover em produção)

A barra migrou o cliente WhatsApp da Evolution v2/v3 (Baileys) para a **Evolution GO**
(whatsmeow, stack `evolution-go` no Portainer, `https://evogo.procexai.tech`). O **código** já
está na branch e verde no gate; este runbook cobre o **cutover em produção** — cada passo aqui
atinge produção (CLAUDE.md §0) e exige autorização explícita do Fernando, frase a frase.

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

## Passos do cutover (ordem)

1. **Deploy do código** (branch mergeada) no worker + api via `service update --force` (não
   `restart`, por causa de worker órfão no Swarm).
2. **Aplicar o Env** acima no stack `barra-vips`.
3. **Provisionar a instância da modelo-piloto** na EvoGo. A `elitebaby01` já existe
   (desconectada). No painel da barra, no perfil da modelo, garanta
   `evolution_instance_id = 'elitebaby01'` e use **Conectar WhatsApp** → o backend chama
   `/instance/connect` (seta webhook+subscribe) + `/instance/qr`.
4. **Re-parear o número** — a modelo escaneia o QR no celular (passo FÍSICO; ninguém automatiza).
   Confirmar `Connected`/`LoggedIn` (o webhook `Connection` promove para `conectado`).
5. **Smoke ao vivo** (rig, número de teste): cliente manda "oi" → a IA responde; confere
   `envios_evolution`/`mensagens` incrementando e o card no grupo de Coordenação.

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
- **view-once (Mídia exclusiva)**: o `/send/media` da EvoGo não expõe `viewOnce`; a mídia vai
  normal (mesmo comportamento do toggle-off na v2). Proteção fica para quando/se a EvoGo suportar.

## Rollback

Reverter o Env do `barra-vips` para os valores v2 e `service update --force`. O código é
compatível com os dois durante a transição (o adaptador Go→v2 só ativa em payload Go; payload v2
passa reto), então não exige reverter o deploy — só o Env e re-pareamento na v2.
