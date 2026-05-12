# Pareamento de WhatsApp por modelo (Evolution API)

Cada modelo tem uma instância Evolution dedicada. O painel oferece três
ações no perfil da modelo:

- **Conectar WhatsApp** — modelo ainda sem pareamento.
- **Trocar conexão** — modelo já conectada quer pareear outro celular.
- **Remover conexão** — desconecta a sessão sem apagar a instância na
  Evolution; reconectar depois é só pedir QR de novo.

## Máquina de estados (`barravips.modelos.evolution_status`)

```
desconectado ─(POST /conectar-whatsapp)─▶ pareando ─(webhook CONNECTION_UPDATE state=open)─▶ conectado
     ▲                                                                          │
     └──────────(POST /desparear-whatsapp ou webhook state=close)────────────────┘
```

- `desconectado` — sem instância associada (instance_id NULL).
- `pareando` — instância criada na Evolution, QR já entregue ao painel,
  aguardando o scan no celular.
- `conectado` — Evolution reporta `state=open`; mensagens fluem normalmente.

## Fluxo de pareamento

1. Painel chama `POST /v1/modelos/{id}/conectar-whatsapp`.
2. Backend chama `POST /instance/create` na Evolution (idempotente — segue se
   já existir). No body já incluímos o webhook apontado para nosso backend.
3. Backend chama `GET /instance/connect/{instance}` e retorna o QR ao painel.
4. Painel exibe o QR. Modelo escaneia no celular.
5. Evolution publica `CONNECTION_UPDATE` no nosso webhook
   (`POST /webhook/evolution`).
6. Handler atualiza `evolution_status='conectado'` e `evolution_pareado_em=now()`.
7. Supabase Realtime notifica o painel; modal fecha sozinho.

## Fallback sem webhook (dev local sem tunnel)

A Evolution hospedada em `https://evolution3.procexai.tech` não consegue
chamar `http://localhost:8000`. Sem um tunnel (ngrok / cloudflared), o
webhook `CONNECTION_UPDATE` não chega.

Para esse cenário, o painel mantém um **polling defensivo a cada 3s**:
enquanto o modal de QR está aberto, ele chama
`GET /v1/modelos/{id}/whatsapp/status`. Este endpoint faz auto-cure: se
`evolution_status='pareando'` e a Evolution responde `state=open` no
`/instance/connectionState/{instance}`, ele atualiza o DB para `conectado`.

Para habilitar o webhook em dev, exporte:

```bash
EVOLUTION_WEBHOOK_CALLBACK_URL=https://<seu-tunnel>.ngrok.app/webhook/evolution
EVOLUTION_WEBHOOK_TOKEN=<seu-token>
```

Tunnel sugerido: `ngrok http 8000` ou `cloudflared tunnel --url http://localhost:8000`.

## Endpoints Evolution v2 utilizados

| Ação                | HTTP   | URL                                                   |
| ------------------- | ------ | ----------------------------------------------------- |
| Criar instância     | POST   | `/instance/create`                                    |
| Pedir QR / reconectar | GET  | `/instance/connect/{instance}`                        |
| Estado da conexão   | GET    | `/instance/connectionState/{instance}`                |
| Logout (preserva)   | DELETE | `/instance/logout/{instance}`                         |

Todos com header `apikey: <EVOLUTION_API_KEY>`.

## Troubleshooting

**Modal fica em "Aguardando o scan" mesmo após escanear.**
Provavelmente o webhook não está chegando. Cheque:
- `EVOLUTION_WEBHOOK_CALLBACK_URL` apontando para uma URL pública alcançável
  pela Evolution.
- `EVOLUTION_WEBHOOK_TOKEN` consistente entre Evolution (passado em
  `webhook.headers.authorization`) e backend (`EVOLUTION_WEBHOOK_TOKEN`).
- Se o tunnel cair, o polling do painel resolve o pareamento em até 3s.

**Badge fica em "Pareando…" indefinidamente após fechar o modal.**
A modelo nunca escaneou. Operador pode clicar "Reabrir QR" no detalhe da
modelo — esse é o caminho idempotente; nenhuma instância nova é criada.

**`POST /conectar-whatsapp` retorna 503 EVOLUTION_INDISPONIVEL.**
`EVOLUTION_BASE_URL` está vazio. Veja `api/.env.example`.

**Mensagens de uma instância antiga (ex: `lucia`) param de chegar após o
deploy.** O webhook agora exige que `instance_id` esteja cadastrado em
`barravips.modelos.evolution_instance_id`. Use o utilitário CLI:

```bash
DATABASE_URL=$DATABASE_URL uv run python scripts/vincular_instance_legacy.py \
    --instance lucia \
    --numero +5521999999999
```

Alternativa por UUID: `--modelo-id <uuid>`. Adicione `--yes` para pular a
confirmação interativa. O script é idempotente: se a instância já está
vinculada, sai com 0 sem alterar nada.

Confirmar nos logs do backend: a primeira mensagem recebida da instância
parada deve aparecer como `received`, não mais `unknown_instance`.

## Migração 0029

`infra/sql/0029_modelos_evolution_status.sql` cria o ENUM
`evolution_pareamento_enum` e duas colunas em `barravips.modelos`. Modelos
com `evolution_instance_id NOT NULL` antes da migration recebem
`evolution_status='conectado'` no backfill, preservando o comportamento
anterior.
