# Mídia de visualização única (view-once)

Referência: **Mídia exclusiva** (CONTEXT.md), `docs/agente/01 §6.13`.

## Situação (verificada no código-fonte, jul/2026)

Nenhuma das plataformas **oficiais** expõe view-once no envio de mídia:

- **EvoGo** (`evolution-foundation/evolution-go`, o que roda em prod hoje): `MediaStruct`
  (`pkg/sendMessage/service/send_service.go`) não tem `viewOnce`, e o `/send/media` monta
  `ImageMessage`/`VideoMessage` sem marcar view-once. Mandar o campo no body é **ignorado** no bind
  do Gin. Não há endpoint de mensagem crua que permita contornar por fora.
- **Evolution v2** (histórico, antes do cutover): `SendMediaDto` também não tem o campo e a
  [issue #1651](https://github.com/evolution-foundation/evolution-api/issues/1651) foi fechada sem
  implementação.

## Por que dá para resolver

A **whatsmeow** (lib por baixo da EvoGo) expõe tudo o que o protocolo precisa: `ViewOnce *bool` em
`ImageMessage`/`VideoMessage`/`AudioMessage` e o envelope `ViewOnceMessageV2 *FutureProofMessage`
(`proto/waE2E`). Falta só a EvoGo aceitar o flag e aplicar — patch pequeno e isolado.

## Patch da EvoGo (pronto)

**`docs/patches/evolution-go-view-once.patch`** — aplicável com `git am` sobre
`evolution-foundation/evolution-go`. Escrito e verificado sobre o HEAD `9337afc` (0.7.2):
`go build ./...` e `go test ./pkg/sendMessage/...` verdes (inclui `view_once_test.go`, novo).

O que ele faz:

1. `MediaStruct` ganha `ViewOnce bool \`json:"viewOnce,omitempty"\`` — o `/send/media` passa a
   aceitar o campo em JSON; o handler também lê `viewOnce` no caminho multipart.
2. `SendDataStruct` carrega o flag até o `SendMessage` centralizado.
3. `applyViewOnce` marca o `viewOnce` interno **e** envolve em `ViewOnceMessageV2` (clientes atuais
   renderizam o badge "1" pelo envelope; o campo interno é o que clientes antigos leem).

Detalhe que importa: o wrap acontece **depois** do `ContextInfo` (quote, menções, forward), que o
`SendMessage` resolve olhando `msg.ImageMessage`/`msg.VideoMessage` pelo `messageType`. Envolver
antes deixaria esses ponteiros nil e mataria a citação. Tipos não-mídia e newsletter ignoram o flag.

Aplicar:

```bash
git clone https://github.com/evolution-foundation/evolution-go.git evogo-fork
cd evogo-fork && git am < <caminho>/docs/patches/evolution-go-view-once.patch
go build ./... && go test ./pkg/sendMessage/...
```

Ideal é mandar como PR upstream — se entrar, o fork some e basta subir a tag nova.

## Build e deploy da imagem patchada (runbook)

Prod hoje: serviço Swarm **`evolution-go_evolution_go`**, imagem **`evoapicloud/evolution-go:latest`**,
stack **`evolution-go`** — **separada** da `barra-vips`. As sessões vivem no Postgres da própria
stack (`evolution-go_evogo_postgres`), não em volume de arquivos.

> ⚠️ **A stack é compartilhada.** A mesma EvoGo serve `elitebaby01` (Barra), `procex-teste` e `wgr6`
> — outros projetos. Reiniciar o serviço derruba as 3 instâncias por alguns segundos. Todo o deploy
> recai na regra §0 do CLAUDE.md: autorização explícita, frase a frase, e janela combinada.
> Os passos 1–3 (build/push) não tocam prod; 4–6 tocam.

1. **Conferir a versão real de prod** antes de buildar — `latest` é tag móvel; parear com o commit
   correspondente do upstream (o patch foi feito sobre 0.7.2) e rebasear se divergir.
2. **Buildar** com tag própria e versionada pelo patch:
   ```bash
   docker build -t <registry>/evolution-go:0.7.2-viewonce1 .
   ```
3. **Push** para um registry alcançável pelos nós do Swarm (sem isso o Swarm não faz pull).
4. **Trocar a imagem do serviço** — ⚠️ **NÃO** usar `StackGitRedeploy` (zera o Env da stack) nem
   `docker restart` (deixa task órfã no Swarm):
   ```bash
   docker service update --image <registry>/evolution-go:0.7.2-viewonce1 --force evolution-go_evolution_go
   ```
   Confirmar `1/1` replicas e as 3 instâncias reconectadas (`GET /instance/all` → `connected`).
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
