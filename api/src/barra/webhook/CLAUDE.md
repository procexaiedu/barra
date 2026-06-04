# webhook/CLAUDE.md

Escopo: ingestão de eventos da Evolution API. Mentalidade: borda hostil, valida antes de aceitar — nunca tratar como endpoint aberto.

## A borda real (token + instância + dedupe)

A proteção **não** vive num `filtro.py` central (esse arquivo é placeholder vazio) — está distribuída e é esta:

1. **Token da Evolution** (`x-webhook-token` ou `Bearer`), comparado por `hmac.compare_digest` em `routes.py`. Falhou → **401** e descarta. Em produção o segredo é fail-closed (`main.py` recusa subir sem ele).
2. **Instância cadastrada**: no ramo de cliente, `instance` precisa existir em `barravips.modelos.evolution_instance_id` (`_instance_cadastrada`). Desenho do produto: **uma instância Evolution por modelo**, garantido pelo índice UNIQUE parcial em `evolution_instance_id` (1 instance = 1 modelo — é o eixo do isolamento cross-modelo). Instância desconhecida → `200 {status: unknown_instance}`.
3. **Dedupe + coalescência**: dedupe inbound por `evolution_message_id` (`_mensagem_ja_persistida`); o "debounce" não é um gate 403 e sim coalescência de turno first-wins (`despacho.py`/`debounce.py`, `_job_id` SET NX).

`settings.jid_permitido` **não** é defesa de produção: é flag de **teste da Fase 1.5** (default `None` = desligado; restringe a um único JID global, não é allowlist por modelo). Clientes não são pré-cadastrados — qualquer JID que fala com o número da modelo é cliente legítimo (`_persistir_cliente` faz upsert incondicional).

**Descartes intencionais usam 200 de propósito** (`unknown_instance`, `duplicate`, `ignored`): a Evolution trata 200 como ack e não reenvia — devolver erro provocaria reentrega em loop. Só o token (401) e o teto de corpo (413) rejeitam com status de erro.

## Schema fora do `/docs`

Nenhuma rota deste módulo aparece no OpenAPI público. Se for incluída por engano, marque `include_in_schema=False` na rota.

## `fromMe` é ambíguo

`fromMe=true` pode vir da IA **ou** da modelo digitando manualmente no mesmo número. O parsing/despacho deve distinguir pelo originador real do envio (id de mensagem que a própria stack gerou ao enviar via `core/evolution.py`), não confiar só na flag. Ver CONTEXT.md "Coordenação por modelo".

## Debounce existe pelo multi-device

WhatsApp Web + celular geram eventos duplicados. Mudou `debounce.py`? Teste com duplicatas reais (mesmo `messageId`, JIDs diferentes do mesmo participante) antes de mergear — unit test mockado não cobre.

## Concentre a ingestão aqui

Toda entrada de evento da Evolution passa por este módulo. Não duplique rota equivalente em `dominio/` nem em `api/v1.py`; validação de token/JID/debounce fica em um só lugar.
