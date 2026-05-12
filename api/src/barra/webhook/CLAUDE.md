# webhook/CLAUDE.md

Escopo: ingestão de eventos da Evolution API. Mentalidade: borda hostil, valida antes de aceitar — nunca tratar como endpoint aberto.

## Três gates obrigatórios em toda rota daqui

1. Token da Evolution válido (header configurado em `settings`).
2. JID do remetente está na allowlist da modelo correspondente.
3. Debounce passou — mensagem não é repetição de multi-device.

Faltou qualquer um: responda 401 (token) ou 403 (JID/debounce) e descarte. **Nunca 200 silencioso** — a Evolution interpreta 200 como ack e não reenvia.

## Schema fora do `/docs`

Nenhuma rota deste módulo aparece no OpenAPI público. Se for incluída por engano, marque `include_in_schema=False` na rota.

## `fromMe` é ambíguo

`fromMe=true` pode vir da IA **ou** da modelo digitando manualmente no mesmo número. O parsing/despacho deve distinguir pelo originador real do envio (id de mensagem que a própria stack gerou ao enviar via `core/evolution.py`), não confiar só na flag. Ver CONTEXT.md "Coordenação por modelo".

## Debounce existe pelo multi-device

WhatsApp Web + celular geram eventos duplicados. Mudou `debounce.py`? Teste com duplicatas reais (mesmo `messageId`, JIDs diferentes do mesmo participante) antes de mergear — unit test mockado não cobre.

## Concentre a ingestão aqui

Toda entrada de evento da Evolution passa por este módulo. Não duplique rota equivalente em `dominio/` nem em `api/v1.py`; validação de token/JID/debounce fica em um só lugar.
