# Mídia de visualização única (view-once)

Referência: **Mídia exclusiva** (CONTEXT.md), `docs/agente/01 §6.13`.

## Situação (verificada no código-fonte, jul/2026)

Nenhuma das plataformas **oficiais** expõe view-once no envio de mídia:

- **EvoGo** (`evolution-foundation/evolution-go`, o que roda em prod hoje): `MediaStruct`
  (`pkg/sendMessage/service/send_service.go`) não tem `viewOnce`, e o `/send/media` monta
  `ImageMessage`/`VideoMessage` sem marcar view-once. Mandar o campo no body é **ignorado** no bind
  do Gin. Confirmado também no **swagger vivo de prod** (`https://evogo.procexai.tech/swagger/doc.json`):
  o `MediaStruct` publicado não tem o campo, nenhum dos 62 bodies de request menciona `viewOnce`, e
  não há endpoint de mensagem crua que permita contornar por fora.
- **Evolution v2** (histórico, antes do cutover): `SendMediaDto` também não tem o campo e a
  [issue #1651](https://github.com/evolution-foundation/evolution-api/issues/1651) foi fechada sem
  implementação.

## Por que dá para resolver

A **whatsmeow** (lib por baixo da EvoGo) expõe tudo o que o protocolo precisa: `ViewOnce *bool` em
`ImageMessage`/`VideoMessage`/`AudioMessage` e o envelope `ViewOnceMessageV2 *FutureProofMessage`
(`proto/waE2E`). Falta só a EvoGo aceitar o flag e aplicar — patch pequeno e isolado.

## Patch da EvoGo (pronto)

Dois arquivos, ambos aplicáveis com `git am` e ambos verificados com `go build ./...` +
`go test ./pkg/sendMessage/...` verdes (inclui o `view_once_test.go`, novo):

| Patch | Base | Para quê |
|---|---|---|
| `docs/patches/evolution-go-view-once-0.7.1.patch` | tag `0.7.1` | **é o que vai pra prod** |
| `docs/patches/evolution-go-view-once-0.7.2.patch` | HEAD `9337afc` (0.7.2) | PR upstream |

**Por que 0.7.1**: comparando o swagger vivo de prod com o de cada tag, prod é **exatamente a
0.7.1** (77 paths, diff vazio nos dois sentidos; a 0.7.2 tem 88 e a 0.7.0, 60). Buildar de `main`
embutiria um upgrade 0.7.1→0.7.2 junto com o patch, nas três instâncias — risco que não faz parte
do pedido. Note que a 0.7.1 ainda usa o **fork do whatsmeow da EvolutionAPI como submódulo**
(`whatsmeow-lib`, `replace` no go.mod, e o Dockerfile copia esse diretório): clonar **sem**
`--recurse-submodules` quebra o build. A 0.7.2 já migrou para o whatsmeow upstream.

O que ele faz:

1. `MediaStruct` ganha `ViewOnce bool \`json:"viewOnce,omitempty"\`` — o `/send/media` passa a
   aceitar o campo em JSON; o handler também lê `viewOnce` no caminho multipart.
2. `SendDataStruct` carrega o flag até o `SendMessage` centralizado.
3. `applyViewOnce` marca o `viewOnce` interno **e** envolve em `ViewOnceMessageV2` (clientes atuais
   renderizam o badge "1" pelo envelope; o campo interno é o que clientes antigos leem).

Detalhe que importa: o wrap acontece **depois** do `ContextInfo` (quote, menções, forward), que o
`SendMessage` resolve olhando `msg.ImageMessage`/`msg.VideoMessage` pelo `messageType`. Envolver
antes deixaria esses ponteiros nil e mataria a citação. Tipos não-mídia e newsletter ignoram o flag.

Aplicar (é o que o `infra/scripts/build-evogo-viewonce.sh` faz, já com o `docker build`):

```bash
git clone --recurse-submodules --branch 0.7.1 \
  https://github.com/evolution-foundation/evolution-go.git evogo-fork
cd evogo-fork && git am < <caminho>/docs/patches/evolution-go-view-once-0.7.1.patch
go build ./... && go test ./pkg/sendMessage/...
```

Ideal é mandar o de 0.7.2 como PR upstream — se entrar, o fork some e basta subir a tag nova.

## Build e deploy da imagem patchada (runbook)

Prod hoje: serviço Swarm **`evolution-go_evolution_go`**, imagem **`evoapicloud/evolution-go:latest`**,
stack **`evolution-go`** — **separada** da `barra-vips`. As sessões vivem no Postgres da própria
stack (`evolution-go_evogo_postgres`), não em volume de arquivos.

> ⚠️ **A stack é compartilhada.** A mesma EvoGo serve `elitebaby01` (Barra), `procex-teste` e `wgr6`
> — outros projetos. Reiniciar o serviço derruba as 3 instâncias por alguns segundos. Todo o deploy
> recai na regra §0 do CLAUDE.md: autorização explícita, frase a frase, e janela combinada.
> Os passos 1–3 (build/push) não tocam prod; 4–6 tocam.

1. **Reconferir a versão de prod** antes de buildar — `latest` é tag móvel. Método: baixar
   `https://evogo.procexai.tech/swagger/doc.json` e comparar o conjunto de paths com o
   `docs/swagger.json` de cada tag do repo; a que der diff vazio é a versão. Em 21/07 deu **0.7.1**
   (77 paths). Se tiver mudado, rebasear o patch na tag nova.
2. **Buildar na própria VPS** (Swarm de 1 nó ⇒ imagem local basta, sem registry):
   ```bash
   ./infra/scripts/build-evogo-viewonce.sh docs/patches/evolution-go-view-once-0.7.1.patch
   ```
3. Só se um dia o Swarm tiver mais de um nó: push para um registry alcançável por todos.
4. **Trocar a imagem do serviço** — ⚠️ **NÃO** usar `StackGitRedeploy` (zera o Env da stack) nem
   `docker restart` (deixa task órfã no Swarm):
   ```bash
   docker service update --image evolution-go:0.7.1-viewonce1 --force evolution-go_evolution_go
   ```
   Confirmar `1/1` replicas e as 3 instâncias reconectadas (`GET /instance/all` → `connected`).
   O stack file segue apontando `latest`: um `StackUpdate` futuro reverteria a imagem — realinhar
   o compose quando o patch virar definitivo.
5. **Ligar o toggle no Barra**: `EVOLUTION_VIEW_ONCE=true` no Env da stack `barra-vips` (api +
   worker) e `service update --force` nos dois — o worker é quem envia a mídia
   (ver [[deploy_agente_roda_no_worker]]).
6. **Verificar ao vivo**: mandar foto e vídeo pelo agente num chat de teste e confirmar no celular
   que abrem como visualização única; conferir `envios_evolution` e o trace do turno.

Rollback: `EVOLUTION_VIEW_ONCE=false` (instantâneo, sem tocar na EvoGo) e, se preciso, voltar a
imagem para `evoapicloud/evolution-go:latest`.

**Custo recorrente**: rebase do fork a cada upgrade da EvoGo — some se o PR entrar upstream.

## Lado Barra (pronto)

- `settings.evolution_view_once` (**default `False`**).
- `EvolutionClient.enviar_midia` injeta `body["viewOnce"] = True` **só** quando
  `view_once and settings.evolution_view_once` (`core/evolution.py`); teste
  `test_enviar_midia_view_once_sob_toggle`.
- O worker `_enviar_midias` passa `view_once=True` para **toda mídia — foto e vídeo**
  (`workers/envio.py`; decisão 2026-07-10: a foto exclusiva também vai view-once).

Com o toggle off nada muda — a mídia vai normal (fallback P0). Com ele ligado sobre a EvoGo
**oficial**, o campo é ignorado (também inócuo): só a imagem patchada muda o comportamento.

Fontes: [evolution-go](https://github.com/evolution-foundation/evolution-go) ·
[whatsmeow](https://pkg.go.dev/go.mau.fi/whatsmeow) ·
[issue #1651 (Evolution v2)](https://github.com/evolution-foundation/evolution-api/issues/1651).
