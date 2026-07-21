# Pausar o piloto (freio manual da IA de uma modelo)

Procedimento para **parar a IA de responder clientes** no número de uma modelo, em produção, às 3h da manhã e sem pensar. É o freio que os gatilhos de rollback do piloto de produção assistida existem para acionar — e a decisão de puxá-lo é **humana**, nunca automática.

## Quando usar

Três gatilhos objetivos, avaliados todo dia às 05:00 UTC pelo `barra-worker` (`api/src/barra/workers/rollback_watch.py`), janela deslizante de 7 dias — o alerta chega no WhatsApp do dev via Alertmanager (`PilotoGatilhoRollback`):

| Gatilho | Limiar | O que significa |
|---|---|---|
| `nao_contidos` | ≥ 2 / semana | Turnos **já enviados** em que o judge pós-envio viu rastro de LLM — o gate pré-envio não segurou. |
| `acusacoes` | ≥ 3 conversas / semana | Clientes acusando ("é robô?") ou pedindo prova impossível. |
| `taxa_gate` | > 20% dos turnos | O sistema de saída está abortando turno demais (a IA está falando errado com frequência). |

Mais o **freio manual**: qualquer coisa que você veja e não goste. Não precisa de gatilho para pausar.

⚠️ Antes de agir num alerta de `taxa_gate`, cheque se o judge não estava caído na janela — judge indisponível distorce os números. O próprio alerta traz os julgados; e há a regra `JudgePosEnvioDegradado` avisando disso à parte.

## O que a pausa faz — e o que NÃO faz

`POST /v1/modelos/{modelo_id}/pausar` (`api/src/barra/dominio/modelos/routes.py`), numa transação só:

- `modelos.status` → `pausada`;
- todos os atendimentos **abertos** da modelo (estado ≠ `Fechado`/`Perdido`) ganham `ia_pausada = true`, `ia_pausada_motivo = 'modelo_em_atendimento'`, `responsavel_atual = 'modelo'`;
- envia um **card de pausa** no grupo de Coordenação da modelo (a modelo precisa saber que agora é ela quem responde);
- registra o evento `modelo_pausada`.

Atendimento que **nascer** com a modelo pausada já nasce pausado (gate em `resolver_atendimento`) — cliente novo e recorrência não escapam do freio.

**Não faz:** não desliga o WhatsApp, não apaga nada, não fecha atendimento. A **conversa continua gravando** normalmente (mensagem do cliente entra no banco); o que para é a IA responder. O cliente não recebe aviso nenhum — quem assume a conversa é a modelo/o vendedor de plantão, no mesmo número.

**Recusa** se a modelo não estiver `ativa` (HTTP de conflito, `ConflitoEstado`) — pausar duas vezes não é possível nem necessário.

## 1. Caminho primário — painel

Painel → **Modelos** → a modelo → botão **"Pausar atendimentos"** (`interface/src/components/modelos/DetalheModelo.tsx`). É o mesmo endpoint do passo 2, com a sessão já autenticada. Use este caminho sempre que o painel estiver de pé.

## 2. Caminho alternativo — curl

Se o painel estiver fora, a API ainda atende. Todas as rotas `/v1` exigem **Bearer JWT do Supabase** (`get_user`); o token é o `access_token` da sessão do painel — pegue no DevTools do navegador (storage do Supabase) ou faça login pelo GoTrue self-hosted.

```bash
MODELO_ID=...              # uuid da modelo (passo 3 mostra como achar)
TOKEN=...                  # access_token JWT

curl -X POST "https://api-barra.procexai.tech/v1/modelos/$MODELO_ID/pausar" \
  -H "Authorization: Bearer $TOKEN"
```

Resposta (200): `{"modelo_id": ..., "status": "pausada", "conversas_pausadas": N, "em_execucao_em_curso": M, "card_enviado": true|false}`.

`em_execucao_em_curso` > 0 = há atendimento **acontecendo agora**; avise a modelo por fora, não confie só no card.

## 3. Verificação pós-pausa (read-only)

```sql
-- a modelo saiu de 'ativa'?
SELECT id, nome, status FROM barravips.modelos WHERE id = '<MODELO_ID>';

-- sobrou algum atendimento aberto com a IA ainda respondendo? (esperado: 0 linhas)
SELECT id, estado, ia_pausada, ia_pausada_motivo
  FROM barravips.atendimentos
 WHERE modelo_id = '<MODELO_ID>'
   AND estado NOT IN ('Fechado', 'Perdido')
   AND ia_pausada = false;

-- o evento ficou registrado?
SELECT tipo, payload, created_at FROM barravips.eventos
 WHERE tipo = 'modelo_pausada' ORDER BY created_at DESC LIMIT 5;
```

Para achar o `modelo_id` sem o painel: `SELECT id, nome, numero_whatsapp, status FROM barravips.modelos WHERE status = 'ativa';`

## 4. Reversão

`POST /v1/modelos/{modelo_id}/ativar` (painel: **"Reativar atendimentos"**) devolve `modelos.status = 'ativa'`.

⚠️ **A reativação NÃO devolve as conversas para a IA.** Os atendimentos pausados continuam pausados de propósito — a resposta traz `conversas_pausadas_pendentes` com quantos são. Cada um volta pela **Devolução para IA** normal (botão no painel ou `IA assume #N` no grupo), conversa a conversa, quando quem está conduzindo decidir soltar. Atendimento novo, depois da reativação, já nasce com a IA ativa.

Modelo `inativa` não volta por aqui (recusa explícita) — é outro fluxo de cadastro.
