# Cards do grupo de Coordenação — gramática canônica

Spec de formatação de **tudo que a IA envia no grupo de Coordenação por modelo**
(cards proativos + digest de pendências + respostas de confirmação/erro).
Decidido em sabatina (15/06/2026). Mexeu num `.md.j2` desta pasta? Siga isto.

## O grupo, em uma frase

Grupo de **2 números**: a modelo (operada pela IA) e o Fernando. O card sai **do
número da própria modelo** — ela o lê como mensagem dela mesma (`fromMe`), o
Fernando lê como mensagem vinda dela. Os dois leem tudo.

**Invariante de destinatário:** todo card que chega no grupo é para a **MODELO
agir**. As escaladas que são decisão do Fernando vão para a fila do **painel**, não
para o grupo (`card_escalada_vai_ao_grupo`, `dominio/escaladas/service.py`). Logo:
**todo card fala "você" = modelo, em 2ª pessoa**; o Fernando é sempre backstop.

## Gramática

```
{emoji} *{título}* · {cliente} · #{N}      ← cabeçalho (sempre)
{subtítulo/resumo opcional, 1 linha}

📍 {local}                                  ← corpo: emoji-rótulo = bullet,
🕒 {hora}                                      1 fato por linha,
💰 {valor}                                     campo ausente = linha some

👉 {ação em 2ª pessoa}                       ← só quando há ação do humano
```

- **Cabeçalho:** `emoji + título + nome do cliente + #N`. A modelo sabe que é o
  grupo dela; o Fernando vê pelo nome do grupo qual modelo. Não repetir a modelo.
- **Corpo:** lista enxuta. Cada fato numa linha começada pelo emoji-rótulo. Campo
  sem valor **não vira linha** (mantém `| select` nas templates).
- **Marcador final — gramática visual deliberada:**
  - `👉` = **sua vez** (tem ação do humano). Reservado para isso.
  - **Sem `👉`** = só acompanhe. Card informativo termina nos fatos com um rodapé
    leve `Info · …`, sem `👉`.
- **Tamanho:** card típico ~5 linhas. O Pix é o mais denso (até 4 campos de dados,
  um por linha → ~7-8 linhas) — é a exceção aceita. O único campo de texto livre
  (`resumo_operacional` do Handoff) tem **limite duro de 1 linha** (colapsa `\n` +
  `truncate(120, …)` no próprio template — cobre todas as origens da escalada).

## Léxico fixo (um emoji = sempre a mesma coisa)

| Cabeçalho (tipo do card)        | Rótulo de campo (corpo)      | Marcador            |
| ------------------------------- | ---------------------------- | ------------------- |
| 🔔 Handoff                      | 📍 local                     | 👉 sua vez (ação)   |
| ✅ Saída confirmada             | 🕒 hora                      | (sem marcador) info |
| ⚠️ Pix duvidoso                 | 💰 valor do programa         |                     |
| 🚪 Cliente chegou               | 💸 deslocamento (Pix)        |                     |
| 🚗 Cliente saiu de casa         |                              |                     |
| 🎥 Hora da vídeo chamada        |                              |                     |
| 💵 Fechar atendimento           |                              |                     |
| 📋 Pendências                   |                              |                     |

O card proativo 🎥 vídeo chamada é "go-time": dispara quando chega a hora do encontro
(`timeouts.confirmar_em_execucao`, ADR 0021), como 🚪/✅ — **não é Handoff**. Ele é hospedado
numa escalada `video_chamada` (owner=modelo) só para guardar o `card_message_id`, mas renderiza
pelo template próprio (`reconciliacao._CARD_POR_TIPO_ESCALADA`), nunca o 🔔 genérico. Desde o
ADR 0029 ele traz o status do Pix antecipado (💸 recebido / ⚠️ duvidoso / ❗ não recebido) —
a modelo decide a chamada informada; o Pix **nunca gateia** a transição.

O comprovante Pix do **remoto** (ADR 0029: antecipação do **valor da chamada**, não
deslocamento) renderiza pelo template `pix_remoto.md.j2` — mesmos ✅/⚠️ do léxico, sem
📍 endereço e sem falar de Uber/saída.

## Os 8 tipos, no formato canônico

```
🔔 *Handoff* · João · #42
Cliente pediu valor fora da tabela
{resumo em 1 linha}
👉 {ação} — ou responda *IA assume*

✅ *Saída confirmada* · João · #42
📍 Av. Atlântica 1500, Copacabana
🕒 22:00
💰 Combinado R$ 1.500,00
💸 Deslocamento R$ 80,00
👉 Pix ok, pode se preparar

⚠️ *Pix duvidoso* · João · #42
{motivo}
📍 Av. Atlântica 1500, Copacabana
🕒 22:00
💰 Combinado R$ 1.500,00
💸 Recebido R$ 80,00
👉 Você decide o Uber — o Fernando confere depois, sem travar

🚪 *Cliente chegou* · João · #42
📍 Av. Atlântica 1500
🕒 22:00
👉 Confere a foto antes de abrir   (a foto vai anexada à mídia do card)

🚗 *Cliente saiu de casa* · João · #42
🕒 chega ~22h
Info · a IA segue conversando

✅ *Pix da vídeo chamada* · João · #42
🕒 22:00
💰 Combinado R$ 300,00
💸 Recebido R$ 300,00
👉 Pix ok, chamada de pé pro horário

⚠️ *Pix duvidoso (vídeo chamada)* · João · #42
{motivo}
🕒 22:00
💰 Combinado R$ 300,00
💸 Recebido R$ 150,00
👉 Você decide se faz a chamada — o Fernando confere depois, sem travar

🎥 *Hora da vídeo chamada* · João · #42
🕒 22:00
💸 Pix recebido
👉 Hora de chamar o cliente no vídeo

💵 *Fechar atendimento* · João · #42
Como foi? Me manda o valor final.
👉 Responda só o valor (ex.: *1500*) — ou *perdido <motivo>*

📋 *Pendências* · 3 aguardando você
🔔 #1001 Cliente A — handoff
💵 #1002 Cliente B — falta o valor
⚠️ #1003 Cliente C — Pix a conferir
👉 Responda no número, ex.: *fechado #1001 1500*
```

Respostas de confirmação/erro (em `webhook/respostas.py`) já seguem a gramática
(`✅ #N + fato` / `❓ + causa + como consertar`) — ficaram **inalteradas**. Forma real:

```
✅ #42 fechado · R$ 1.500,00 registrado
✅ #42 marcado como perdido · motivo: sumiu
✅ #42 devolvido para a IA
❓ Faltou o valor. Responda com o valor cobrado, ex.: *1500*
```
