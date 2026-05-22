# Supabase Realtime — auditoria e teste manual

Como o painel recebe atualizações ao vivo, o que está cabeado e como validar
fim-a-fim com **dois navegadores** logados como Fernando.

## Como funciona

O painel (Next.js) assina **Postgres Changes** do Supabase Realtime no schema
`barravips`. Cada hook chama `subscribeTabelas(...)` (`interface/src/lib/realtime.ts`),
que abre um `supabase.channel(...).on('postgres_changes', { event: '*', schema:
'barravips', table })` por tabela. Quando um INSERT/UPDATE/DELETE chega, o
callback dispara um **refetch debounced (250ms)** da lista/detalhe via REST — ou
seja, o Realtime é só o "sino": o dado em si vem do backend FastAPI.

Dois pontos críticos:

1. **Realtime herda RLS.** O subscribe só entrega linhas que o usuário logado
   pode ler. Tabela publicada sem policy de `SELECT` para `authenticated` =
   evento nunca chega. Por isso toda tabela na publication precisa de policy.
2. **Auth do canal.** O `@supabase/supabase-js` injeta o JWT da sessão no
   WebSocket automaticamente (o client é criado com `accessToken` resolvido a
   partir da sessão; em `TOKEN_REFRESHED`/`SIGNED_IN` o SDK chama
   `realtime.setAuth` sozinho). Os hooks ainda registram `setAuth` no
   `onAuthStateChange` de forma defensiva e redirecionam para `/login` em
   `SIGNED_OUT`. Sem JWT válido, o canal conecta como `anon`, `is_fernando()`
   retorna false e a RLS bloqueia tudo.

Pré-requisito de infra (config, não SQL): o schema `barravips` precisa estar em
**Project Settings → API → Exposed schemas** no dashboard do Supabase para
aparecer no Realtime/PostgREST.

## Matriz de auditoria (estado em 0040)

Publication = `supabase_realtime`. Policy = existe `SELECT` para `authenticated`
(as policies `FOR ALL` cobrem SELECT). Hook/refetch = quem assina e o que recarrega.

| Tabela | Na publication? | RLS + policy authenticated? | Hook que assina | Refetch no callback |
|---|---|---|---|---|
| `atendimentos` | ✓ 0001 | ✓ 0001 | useAtendimentos, useDashboard, usePainelResumo, usePix, useClientes | lista + detalhe |
| `mensagens` | ✓ 0001 | ✓ 0001 | useAtendimentos | lista + detalhe |
| `bloqueios` | ✓ 0001 | ✓ 0001 | useAgenda, usePainelResumo | agenda / resumo |
| `comprovantes_pix` | ✓ 0001 | ✓ 0001 | usePix, useAtendimentos, useDashboard, usePainelResumo | lista + detalhe |
| `eventos` | ✓ 0001 | ✓ 0001 | useAtendimentos, useAgenda, usePainelResumo | lista / detalhe / resumo |
| `conversas` | ✓ 0003 | ✓ 0001 | useClientes | lista `/v1/crm/clientes` + detalhe |
| `clientes` | ✓ 0003 | ✓ 0001 | useClientes | lista `/v1/crm/clientes` |
| `escaladas` | ✓ 0004 | ✓ 0001 | useDashboard | resumo + escaladas |
| `modelos` | ✓ 0005 | ✓ 0001 | useModelos | lista + detalhe |
| `modelo_midia` | ✓ 0005 | ✓ 0001 | useModelos | detalhe (mídia) |
| `modelo_servicos` | ✓ 0006 | ✓ 0006 | — (legado, não assinado) | — |
| `programas` | ✓ 0007 | ✓ 0007 | useModelos | detalhe |
| `modelo_programas` | ✓ 0007 | ✓ 0007 (`REPLICA IDENTITY FULL`) | useModelos | detalhe |
| `duracoes` | ✓ 0010 | ✓ **0040** (era gap — RLS sem policy) | — (não assinado) | — |

Observações:
- Toda tabela assinada em `interface/src/lib/realtime.ts` está na publication —
  não há `ADD TABLE` pendente.
- `modelo_servicos` e `duracoes` estão na publication mas nenhum hook assina; são
  mantidas publicadas por consistência. `duracoes` tinha RLS habilitada sem
  policy (0010), o que bloquearia o evento — corrigido em `0040`.
- `atendimento_servicos` (0011) e `atendimento_midias` (0032) **não** estão na
  publication e **não** são assinadas: mudam junto com o `atendimento` pai, cujo
  refetch de detalhe já traz `servicos`/`midias_internas`. Não precisam de
  Realtime próprio.
- `eventos`/`mensagens` usam `REPLICA IDENTITY` default (PK). Como o painel só
  reage a INSERT (append-only) e refetcha tudo, não precisam de `FULL`.

## Teste manual com 2 navegadores (Fernando em ambos)

Setup comum:

1. `cd interface && pnpm install && pnpm dev` (porta padrão 3000). A API pode já
   apontar para o backend hospedado — confira `NEXT_PUBLIC_API_URL` no
   `interface/.env`.
2. Abra **duas janelas** (ou uma normal + uma anônima) em
   `http://localhost:3000`. Faça login em ambas como Fernando
   (`contato@procexai.tech`).
3. Em cada módulo: **janela A faz a mudança**, **janela B só observa**. O
   esperado é a janela B atualizar sozinha em ~0,3s, **sem F5**.
4. Console (DevTools) da janela B em dev mostra logs `[<modulo>] refetch
   coalescido por N eventos` quando o Realtime dispara — bom sinal de que o
   canal está ativo. Nenhum erro de WebSocket / `CHANNEL_ERROR` deve aparecer.

### Painel / Interface (`usePainelResumo`, `useAtendimentos`)
- Tela: `/interface`.
- Janela A: arraste um atendimento de coluna no kanban (muda estado) ou
  feche/perca um atendimento.
- Janela B: o card muda de coluna e os contadores do resumo atualizam sozinhos.

### Atendimentos (`useAtendimentos`)
- Tela: `/atendimentos`.
- Janela A: abra um atendimento e edite dados (ex.: valor acordado) ou registre
  fechado/perdido.
- Janela B (mesmo atendimento aberto): lista e detalhe refletem a mudança;
  timeline de eventos ganha a nova entrada.

### Agenda (`useAgenda`)
- Tela: `/agenda`.
- Janela A: crie, mova (drag) ou cancele um bloqueio.
- Janela B (mesma semana/dia visível): o bloqueio aparece/move/some sozinho.

### CRM / Clientes (`useClientes`)
- Tela: `/crm`.
- Janela A: crie um cliente, edite o nome, ou arquive/desarquive.
- Janela B: a lista (`/v1/crm/clientes`) atualiza. Atenção ao caso refatorado:
  a tela lista via `/v1/crm/clientes` (não mais `/conversas`); o hook assina
  `conversas`, `clientes` e `atendimentos` e refaz a busca da lista correta.
  Para validar `conversas`: gere uma nova mensagem no WhatsApp de um par
  cliente-modelo (ou simule via backend) — a conversa sobe na lista do cliente.

### Modelos (`useModelos`)
- Tela: `/modelos`.
- Janela A: pause/ative uma modelo, edite o perfil, vincule um programa, ou
  conclua um pareamento de WhatsApp (status `conectado`).
- Janela B (mesma modelo selecionada): badge de status, dados do perfil e lista
  de programas atualizam; o modal de QR fecha sozinho ao conectar.

### PIX (`usePix`)
- Tela: `/pix`.
- Janela A: aprove, rejeite ou reabra um comprovante.
- Janela B: o item sai/entra da fila de pendentes e o detalhe muda de status.

### Dashboard (`useDashboard`)
- Tela: `/dashboard`.
- Janela A: feche um atendimento (mexe em conversão/líquido/fechamentos) ou
  abra/feche uma escalada.
- Janela B: métricas e sparklines recarregam; o painel de escaladas atualiza.

## Troubleshooting

**Janela B não atualiza, mas F5 mostra o dado novo.**
O canal não está recebendo eventos. Verifique, em ordem:
1. Console: erro `CHANNEL_ERROR` ou WebSocket fechando → JWT não chegou.
   Confirme que está logado (não expirado) e que `NEXT_PUBLIC_SUPABASE_URL`/
   `ANON_KEY` estão setados.
2. A tabela está na publication? `SELECT * FROM pg_publication_tables WHERE
   pubname='supabase_realtime' AND schemaname='barravips';`
3. A tabela tem policy de SELECT para `authenticated`? Sem policy, RLS bloqueia
   o evento mesmo publicado (foi o caso de `duracoes` antes da 0040).
4. O schema `barravips` está em **Exposed schemas** no dashboard do Supabase?

**Atualiza em uma tela mas não em outra.**
Confirme na matriz acima que o hook daquela tela assina a tabela alterada. Se a
mudança é numa tabela que aquele módulo não assina, é comportamento esperado
(ex.: mudança em `modelo_midia` não mexe no Dashboard).

**Eventos em rajada derrubam a UI.**
Não devem — cada hook coalesce eventos num único refetch a cada 250ms
(`debouncedRefetch`). Se ver flicker, cheque se o cleanup do `useEffect`
(`cleanupRealtime()` + `clearTimeout`) está rodando ao desmontar.
