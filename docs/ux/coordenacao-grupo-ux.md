# Coordenação por Modelo — Redesign de UX dos Cards (Proposta)

> Doc operacional para iterar a superfície de **cards do grupo de Coordenação por modelo**.
> Foca em jornada, UX, microcopy e gramática visual — não em implementação técnica.
> **Status:** proposta para revisão. Candidata a ADR (muda um contrato model-facing).
> Insumo: skill `ui-ux-pro-max` (regras de UX), ground-truth dos templates atuais em `api/src/barra/workers/_cards/` e `lembrete_valor.py`, parser em `webhook/parser.py`.

---

## 1. O insight central

A Coordenação por modelo é um **grupo de WhatsApp com 2 participantes** (o número da modelo, operado pela IA, e Fernando). A IA posta **Cards** ali. Não existe a tela de um app: **no WhatsApp não há botão — o texto do card É a interface inteira.**

Por isso cada card precisa resolver três coisas no **primeiro relance** da modelo (celular na mão, no meio de outra coisa):

1. **Sinalizar** urgência e tipo — só o emoji e o negrito fazem o papel de "cor" e "hierarquia".
2. **Dizer o que aconteceu e com quem** — em uma linha.
3. **Dizer exatamente o que digitar para agir** — porque não há botão; o comando é a única forma de ação.

**Diagnóstico:** hoje os cards estão escritos como **notificações**. Precisam ser escritos como **controles interativos renderizados em texto**. Só o `lembrete_valor` cumpre o item 3 — e o faz como frase corrida ("Responda este card com o valor…").

### Registro de voz (importante)

O card **não fala na persona do cliente**. Persona, voz e FAQ são gerais e voltadas ao cliente; o card é **voz operacional interna** — para a modelo e o Fernando, dentro do grupo. Pode ser direto e explícito (inclusive sobre "outro cliente", coisa que a IA jamais revela ao cliente). Registro: **caloroso, mas seco e acionável** — não é conversa, é um painel de controle em texto.

---

## 1.5 Usuários do grupo — quem lê, quem age

O grupo tem **2 participantes** (número da modelo operado pela IA + Operador). Mas isso esconde **dois leitores muito diferentes**, e a IA é a **emissora**, não leitora.

| Leitor | Quem | Contexto ao ler | O que quer do card | Onde age |
|---|---|---|---|---|
| **Modelo** | a profissional, no próprio celular | no meio do dia / de um atendimento; não-técnica; só vê **este** grupo e a conversa com o cliente | "o que tá rolando com **meu** cliente e o que eu faço **agora**" | responde o card (`finalizado/perdido/IA assume`) e/ou assume a conversa com o cliente |
| **Operador** ("Fernando" = Fernando ou a sócia, permissão idêntica, ADR 0012) | gestão | gerenciando **várias** modelos; tem o **painel** aberto | decidir exceções, corrigir, auditar | **painel** (principal) e também o grupo |

**Princípio de audiência:** todo card é **visto pelos dois**, mas o **`owner` da escalada diz quem deve _agir_**. O card precisa deixar o destinatário óbvio — um card "da modelo" fala com ela; um card de exceção de sistema é decisão do Operador.

| `owner = modelo` (operacional dela) | `owner = Fernando` (exceção de gestão/sistema) |
|---|---|
| `pix_validado`, `pix_duvidoso`, `foto_portaria`, `aviso_saida`, `fora_de_oferta`, `indisponibilidade` | `comportamento_atipico` (jailbreak, disclosure insistente), `outro` (política nova, exaustão de iterações, lembrete sem resposta) |

> **Decisão (§9.6): roteia por `owner`.** `owner=modelo` → card no grupo dela. `owner=Fernando` → **só painel/fila** em P0 (IA Admin no P1) — o grupo não recebe jailbreak/política/exaustão, que não são dela. **Exceção:** o **lembrete-sem-resposta** continua no grupo (é a mesma thread do lembrete que já vive lá). O grupo da modelo fica 100% sobre ela.

---

## 1.6 Quando — e por quê — chega um card (mapa de gatilhos)

Régua (anti-fadiga, §3.5): **todo card prova que muda o comportamento de quem o recebe.** Mapa do código real:

| Evento que dispara (condição real) | Card | Transição de estado | Quem age | Por que interrompe o grupo |
|---|---|---|---|---|
| Pix recebido e **validado** (vision + chave/titular/valor OK) | **Saída confirmada** ✅ | → `Confirmado`, IA pausa | modelo se prepara | ela pode se arrumar / pedir o Uber |
| Pix recebido mas **duvidoso** (mídia ausente, vision off, valor < piso, chave/titular divergem) | **Pix duvidoso** ⚠️ | → `Confirmado`, IA pausa | **modelo decide** o Uber; Fernando revisa no painel (fila) | decisão dela antes de gastar; **nunca trava** |
| Cliente manda foto em **interno/`Aguardando_confirmacao`** | **Cliente chegou** 🚪 +foto | → `Em_execucao` | modelo confere e abre | ela vai abrir a porta agora |
| IA detecta "tô indo" (interno/`Aguardando_confirmacao`) | **Cliente avisou que saiu** 🚗 | sem transição (IA segue) | modelo se prepara | prepara, mas **não** confirma |
| `valor_acordado` abaixo do **piso de desconto** | **Handoff · fora da tabela** 🔔 | IA pausa | modelo/Operador decide preço | negociação saiu do que a IA pode |
| Horário pedido sem **bloqueio** disponível (interno/`Qualificado`) | **Handoff · sem agenda** 🔔 | — | modelo/Operador | IA não tem slot; humano resolve |
| `Em_execucao` + `bloqueio.fim` vencido (+tolerância) | **Lembrete de fechamento** 💵 | — | modelo manda o **Valor final** | cobrar o fechamento dela |
| Comportamento atípico / jailbreak / output-guard | **Handoff · comportamento atípico** 🔔 | IA pausa | **Operador** decide | (audiência: grupo da modelo? ver decisão) |
| Motivo não mapeado / política / exaustão / **lembrete sem resposta após N toques** | **Handoff · outro** 🔔 | — | **Operador** | silêncio/exceção → humano assume |

Três famílias caem disso: **operacionais da modelo** (linhas 1–4, 7), **exceções de venda que ela pode resolver** (5–6), **exceções de sistema/gestão do Operador** (8–9).

---

## 1.7 Vocabulário padronizado — termo do card = termo da operação

O dict `_ROTULOS` (`dominio/escaladas/modelos.py`) e o CONTEXT.md **são** a voz da operação. Auditoria do que rascunhei vs. canônico:

| Conceito | Rascunho meu (§5) | Canônico (CONTEXT / `_ROTULOS`) | Decisão |
|---|---|---|---|
| Pix em revisão | "Pix a conferir" | "duvidoso" (CONTEXT); "Pix duvidoso aguardando decisão" | **corrigir → "Pix duvidoso"** |
| Aviso de saída | "Cliente saiu de casa" | "Cliente avisou que saiu de casa"; termo **Aviso de saída** | **corrigir → "Cliente avisou que saiu"** (o "avisou" preserva que **não** é confirmação) |
| Pix validado | "Saída confirmada" | CONTEXT: card **"saída confirmada"** | ✅ mantém |
| Foto de portaria | "Cliente chegou" | CONTEXT: card **"cliente chegou"** | ✅ mantém |
| Handoff | "Handoff" + rótulo por tipo | **Handoff** (termo de domínio) + `_ROTULOS` | ✅ mantém; subtítulo = rótulo canônico do tipo |
| Lembrete | "Fechar atendimento" | **Lembrete de fechamento**; pede o **Valor final** | título plain "Fechar atendimento", mas corpo pede o **"valor final"** (termo canônico), não "valor" genérico |
| valor combinado | "Combinado" | `valor_acordado` (≠ **Valor final**) | manter "Combinado"; **nunca** chamar de "valor final" (são coisas distintas) |
| deslocamento | "Deslocamento" | **Pix de deslocamento** | ✅ campo "Deslocamento" ok |

**Regra geral:** o **título** do card usa o termo canônico do conceito; o **corpo** pode ser plain, mas **nunca renomeia** um termo de domínio (Valor final ≠ valor combinado ≠ Pix de deslocamento). Os 8 subtítulos de handoff saem **direto do `_ROTULOS`** — fonte única.

---

## 2. Problemas concretos (do código real)

| # | Problema | Evidência |
|---|----------|-----------|
| 1 | **Sem anatomia compartilhada.** Handoff tem header + corpo + `👉 ação`; Pix/chegada/saída são FYI soltos; lembrete é frase corrida sem header nem emoji. | `escalada.md.j2` vs `lembrete_valor.py:145` |
| 2 | **A ação é invisível.** A modelo precisa *aprender* que se responde ao card. Handoff diz `👉 {acao_esperada}` mas nunca diz o **comando** a digitar. | `escalada.md.j2:6` |
| 3 | **Erros são becos sem saída.** `"Valor ambiguo."`, `"Informe #N."` — sem exemplo, sem caminho de recuperação. | motivos de erro em `parser.py` |
| 4 | **Card de Pix duvidoso enterra a decisão.** É o card mais crítico (ela decide chamar o Uber antes do Fernando revisar), mas o comparativo financeiro fica em linhas *opcionais* embaixo do motivo. | `pix.md.j2:9-12` |
| 5 | **Thread plana.** Cards disparam um-por-job, sem pausa nem agrupamento; ao abrir o grupo depois de um tempo, não há "o que aguarda minha ação" vs "FYI". | cards burlam a humanização (`envio.py`) |
| 6 | **`#N` é a chave de comando, mas não é uma pessoa.** Atrito de mapear número ↔ cliente. | header `#{numero_curto}` |
| 7 | **Moeda em formato errado.** `R$ {{ '%.2f' \| format(v) }}` → `R$ 1500.00` (ponto, sem milhar). Não é BR. | `pix.md.j2:11-12` |

---

## 3. Princípios (regras da skill `ui-ux-pro-max`, traduzidas ao canvas de texto)

As regras de UX da skill foram pensadas para web/app, mas os princípios transferem direto. As aplicáveis, por severidade:

| Regra (skill) | Sev. | Tradução para o card de WhatsApp |
|---|---|---|
| **Error Recovery** — nunca erro sem caminho de saída | Média | Todo erro do parser vira card com **exemplo + o que fazer** |
| **Confirmation Messages** — nunca sucesso silencioso | Média | Todo comando válido recebe **eco de confirmação** curto |
| **Error Feedback near problem** | Alta | A resposta de erro/confirmação cita o **#N** do card |
| **Empty States** — guiar quando não há conteúdo | Média | O digest de pendências tem estado "tudo em dia" |
| **Color-not-only** — não comunicar só por cor | **Alta** | Emoji **sempre pareado com rótulo de texto** em negrito |
| **Progressive disclosure** — não despejar tudo | Média | Essencial primeiro; campos secundários só quando existem |
| **One primary action per screen** | Alta | **No máximo uma** ação primária por card |
| **Font Size Scale / Visual hierarchy** | Média | Única ferramenta de hierarquia: `*negrito*`, quebras de linha, posição do emoji — usadas de forma **consistente** |

### A regra que quebramos de propósito: "No emoji as icons"

A skill manda usar ícones vetoriais (SVG), nunca emoji. **No WhatsApp isso é impossível** — não há sistema de ícone; o emoji é a única iconografia. Então invertemos a regra com disciplina:

- **Vocabulário fixo** — cada emoji tem **um** significado, nunca reaproveitado.
- **Sempre pareado com texto** (satisfaz `color-not-only`): `⚠️ *Pix a conferir*`, nunca só `⚠️`.
- **Posição estável** — emoji de tipo abre a linha 1; emojis de campo abrem as linhas de detalhe.

---

## 3.5 Validação contra o mercado (pesquisa web, jun/2026)

A skill `ui-ux-pro-max` é web/app — só o domínio `ux` transferiu. Para fechar as melhores práticas, cruzei a proposta com fontes do canal (notificações, alertas operacionais, UI conversacional, microcopy). **O núcleo da proposta é confirmado**; em três pontos o mercado puxa além.

### O que confirma

| Movimento da proposta | Prática de mercado que confirma | Fonte |
|---|---|---|
| Rodapé com o comando literal a digitar | "Todo alerta deve ser acionável: inclua os passos de remediação / runbook no próprio alerta." O rodapé **é** o runbook. | oneuptime |
| Distinguir card acionável (rodapé) de FYI (sem rodapé) | "Separe claramente notificações acionáveis das informativas; case tratamento visual e tom à urgência." | Smashing |
| Comando específico (`fechado`/`perdido`/`IA assume`) | "Botões devem dizer o que acontece; CTA específica bate genérica." (`Send invoice` +18% vs `Submit`) | Mobisoft / Justinmind |
| Título nomeia o efeito ("Saída confirmada") | "Nomeie a função com clareza; evite termo vago/branding." | NN/G |
| Erros com causa + exemplo + caminho | "Erro como mão amiga, não bronca": *"Opa! Essa senha não confere. Quer ajuda pra redefinir?"* | Justinmind |
| Digest de pendências | "Ofereça modos-resumo que agrupam em digest diário/semanal." + "Agrupe/deduplique alertas relacionados num resumo." | Smashing / oneuptime |
| `#N` + cliente como starter de resposta | "Ofereça conversation starters / hints; reduza a barreira de articulação." | NN/G |

### O que o mercado puxa além (3 ajustes incorporados)

1. **Restrição / fadiga de alerta.** Regra dura do on-call: *"Se um alerta dispara e ninguém pode tomar uma ação específica, ele não deveria existir."* (oneuptime) + *"Menos notificações melhoram a satisfação; comece com baixa frequência."* (Smashing). Isso **questiona os cards de FYI puro** (Pix validado, cliente saiu de casa). Defesa: no nosso domínio eles **preparam a modelo para agir** (se arrumar, conferir foto) — não são ruído gratuito. Mas a régua passa a ser: **todo card prova que muda o comportamento dela; se não muda, vira linha no digest, não mensagem própria.** (Vira decisão na §9.)

2. **Severidade formalizada em 3 níveis** (Smashing e oneuptime convergem: Alta/Média/Baixa). Mapeamento explícito da coluna "Temperatura" do §4:
   - **Alta — precisa de você** (🔴): handoff (🔔), lembrete de fechamento (💵). *Ação humana pendente.*
   - **Média — confira, fluxo segue** (🟡): Pix a conferir (⚠️), cliente chegou (🚪). *Julgamento sem bloqueio.*
   - **Baixa — info/feito** (🟢🔵): Pix validado/saída confirmada (✅), cliente saiu (🚗). *Candidatos a só-digest.*

3. **Dedup / agrupamento de cards consecutivos** (oneuptime: *"Alert group: 50 ocorrências"* em vez de 50 mensagens). Além do digest, cards seguidos do **mesmo `#N`** num curto intervalo deveriam encadear em vez de empilhar soltos. Faseável junto do digest (Fase 4).

### O que NÃO se aplica a nós (e por que importa)

- **Aprovação/categorização de template do WhatsApp** (Customer.io, Twilio, CleverTap): é regra da **WhatsApp Business API oficial** (Meta aprova cada template). Nós rodamos **Evolution self-host (Baileys/WhatsApp Web), mensagem de sessão livre** → **sem aprovação de template, liberdade total de copy**. O preço dessa liberdade: **não temos os botões/listas interativos da API oficial** — daí o comando-em-texto ser obrigatório, não escolha. (Ver §8.)

---

## 4. A gramática única do card

Toda mensagem da IA no grupo segue esta anatomia. **Mudou o conteúdo, não a forma.**

```
{EMOJI} *{TÍTULO}* · {cliente} · #{N}
{linha-essência: o que aconteceu / o que decidir — 1 linha}

{bloco de detalhe opcional — 1 campo por linha, com emoji-rótulo}

👉 {rótulo da ação}: responda *{comando literal}*      ← só em cards acionáveis
```

### Regras da gramática

1. **Linha 1 sempre:** `emoji + *título* + cliente + #N`, nessa ordem. O **`#N` está sempre presente e em formato `#42`** (regex-safe — ver §8).
2. **Uma linha-essência**, texto plano, sem enfeite. É o que ela lê se ler só uma linha.
3. **Bloco de detalhe** opcional: cada campo é `{emoji} {rótulo} {valor}`, com tokens reaproveitados (tabela abaixo). Some quando o dado não existe (progressive disclosure). **Junção:** dois campos curtos por linha com ` · ` (ex.: `💰 Combinado … · 💸 Deslocamento …`); valor longo (endereço) ocupa linha própria. Nunca 3+ campos numa linha (quebra em tela de 375px).
4. **Rodapé de ação** com `👉` **só quando uma resposta é esperada** — e enuncia o **comando literal em negrito**. O card vira um botão autodocumentado.
5. **Uma ação primária por card.** Alternativas vão na mesma linha, subordinadas ("— ou …").
6. **Valores em formato BR:** `R$ 1.500,00` (milhar com ponto, decimal com vírgula).

### Vocabulário de emoji (fixo)

**Tipo / status (abre a linha 1):**

| Emoji | Significado | Temperatura |
|---|---|---|
| 🔔 | Handoff — decisão pendente | 🔴 precisa de você |
| 💵 | Lembrete de fechamento — falta o valor | 🔴 precisa de você |
| ⚠️ | Pix duvidoso (em revisão) | 🟡 confira, mas o fluxo segue |
| 🚪 | Cliente chegou (foto de portaria) | 🟡 confira a foto |
| ✅ | Confirmação positiva / Pix validado / saída confirmada | 🟢 FYI / feito |
| 🚗 | Cliente avisou que saiu | 🔵 info |
| 📋 | Pendências (digest) | — índice |
| ❓ | Não entendi (erro com recuperação) | — recuperação |

**Campo (abre linhas de detalhe):**

| Emoji | Campo |
|---|---|
| 📍 | endereço / ponto de encontro |
| 🕒 | horário |
| 💰 | valor combinado |
| 💸 | Pix de deslocamento |
| 💵 | valor final |

---

## 5. Cards existentes — antes / depois

### 5.1 Handoff (`escalada.md.j2`)

**Antes**
```
🔔 *Handoff #42* — Marina
Pix de deslocamento validado

{resumo_operacional}

👉 {acao_esperada}
```

**Depois**
```
🔔 *Handoff* · Marina · #42
{tipo_rotulo}

{resumo_operacional}

👉 {acao_esperada} — para devolver à IA, responda *IA assume*
```
- `#N` sai do título e vira sufixo padronizado (consistência com os demais).
- O rodapé passa a enunciar o comando literal (`IA assume`) além da ação humana esperada.

---

### 5.2 Pix validado (`pix.md.j2`, ramo `validado`)

**Antes**
```
✅ *Pix recebido #42* — Marina
Saída confirmada.

📍 {endereco}
🕒 {horario}
💰 Combinado R$ 1500.00
💸 Deslocamento R$ 80.00
```

**Depois**
```
✅ *Saída confirmada* · Marina · #42
Pix ok — pode se preparar.

📍 {endereco}  ·  🕒 {horario}
💰 Combinado R$ 1.500,00  ·  💸 Deslocamento R$ 80,00
```
- Título passa a nomear o **efeito** ("Saída confirmada"), não o objeto ("Pix recebido").
- Detalhe compactado em 2 linhas (menos scroll). FYI: sem rodapé de ação.
- Moeda em BR.

---

### 5.3 Pix duvidoso (`pix.md.j2`, ramo `em_revisao`) — **o card mais crítico**

**Antes**
```
⚠️ *Pix recebido #42* — Marina
Confira antes de sair: {motivo_em_revisao}

📍 {endereco}
🕒 {horario}
💰 Combinado R$ 1500.00
💸 Deslocamento R$ 80.00
```

**Depois**
```
⚠️ *Pix duvidoso* · Marina · #42
{motivo_em_revisao}.
💸 Recebido R$ 80,00  ·  💰 Combinado R$ 1.500,00
📍 {endereco}  ·  🕒 {horario}

👉 Você decide chamar o Uber agora — Fernando confere depois, sem travar.
```
- O **comparativo financeiro** (recebido vs combinado) sobe para logo abaixo do motivo — é o dado da decisão.
- O rodapé carrega a **invariante de domínio**: o fluxo **nunca trava por Pix**; a decisão é dela; Fernando revisa na fila assíncrona. Sem comando de parser (a "ação" é operacional, não um comando).

---

### 5.4 Cliente chegou (`chegada.md.j2`, + foto)

**Antes**
```
🚪 *Cliente chegou #42* — Marina
📍 {endereco}
🕒 {horario}

👉 Confira a foto antes de abrir a porta.
```

**Depois**
```
🚪 *Cliente chegou* · Marina · #42
📍 {endereco}  ·  🕒 {horario}

👉 Confira a foto antes de abrir.
```
- A foto segue como imagem com este texto de legenda (canal inalterado).
- **Não** insinuar que o sistema validou a foto (no P0 não há vision — invariante).

---

### 5.5 Cliente avisou que saiu (`aviso_saida.md.j2`)

**Antes**
```
🚗 *Cliente saiu de casa #42* — Marina
🕒 previsto 21:30
```

**Depois**
```
🚗 *Cliente avisou que saiu* · Marina · #42
🕒 previsto {horario}
```
- "**avisou**" (não "saiu") preserva a invariante: é **Aviso de saída**, não confirmação — a IA segue respondendo.
- Só padroniza o header. FYI puro, sem rodapé. (A IA segue respondendo o cliente — estado segue `Aguardando_confirmacao`.)

---

### 5.6 Lembrete de fechamento (`lembrete_valor.py:145` — hoje sem template) — **a maior melhoria**

**Antes** (frase corrida, sem header, sem emoji)
```
#42 — atendimento com Marina encerrado. Qual foi o valor final cobrado? Responda este card com o valor (ex.: 1500). Se não rolou: perdido <motivo>.
```

**Depois**
```
💵 *Fechar atendimento* · Marina · #42
Como foi? Me manda o valor final pra registrar.

👉 responda só o valor (ex.: *1500*) — ou *perdido <motivo>*
```
- Ganha header, emoji e a gramática. A instrução de ação sai do meio da frase e vira o rodapé.
- "**valor final**" (termo canônico), não "valor" genérico — é o `Valor final` do `Registro de resultado`.
- Migrar para um template `.j2` como os outros (hoje é string hard-coded).

---

## 6. Novas superfícies

### 6.1 Confirmações de comando (hoje: sucesso silencioso ou inconsistente)

Regra `Confirmation Messages`: todo comando válido recebe **eco curto**. Uma linha, mesmo `#N`, sem rodapé.

```
✅ #42 fechado · R$ 1.500,00 registrado
✅ #42 marcado como perdido · motivo: sumiu
✅ #42 devolvido para a IA
```
- Curto e factual. Quando houver snapshot de repasse, anexar: `· repasse R$ X`.
- **Sem diálogo de confirmação bloqueante** ("tem certeza?"). O domínio já desenhou o *undo* como **Corrigir no painel** (comando da modelo é efetivo imediatamente; Fernando recalcula depois). Aplicamos a regra "Confirmation Dialogs" como **eco + undo posterior**, não como gate síncrono — coerente com `Registro de resultado`.

### 6.2 Erros com recuperação (substitui os motivos sequinhos do parser)

Regra `Error Recovery`: cada erro diz **a causa + como consertar**, com exemplo.

| Situação | Antes | Depois |
|---|---|---|
| Falta `#N` | `Informe #N do atendimento.` | `❓ Não sei qual atendimento. Responda direto no card — ou inclua o número: *fechado #42 1500*` |
| Valor ambíguo | `Valor ambiguo.` | `❓ Vi mais de um número aqui. Me manda só o valor final, ex.: *1500*` |
| `fechado` sem valor | `Valor final obrigatorio.` | `❓ Faltou o valor. Responda com o valor cobrado, ex.: *1500*` |
| `perdido` sem motivo | `Motivo perda obrigatorio.` | `❓ Por que foi perdido? Responda *perdido* + motivo: preço, sumiu, risco, indisponibilidade, fora_de_area ou outro` |
| Não reconhecido | (evento `comando_invalido`) | `❓ Não entendi. Fechar: *fechado 1500* · Perder: *perdido sumiu* · Devolver à IA: *IA assume*` |

### 6.3 Forgiveness no parser (determinístico — sem LLM)

**Escopo:** ampliar o que o regex aceita, mantendo as invariantes. **Fora de escopo:** NLP livre (é IA Admin, P1) e reação/emoji-ack (Evolution v2.3.6 self-host **não suporta** reactions — ver §8).

Aceitar a mais:
- **Sinônimos de fechamento:** `fechado` / `finalizado` / `fechei` / `fechamos`.
- **Sinônimos de perda:** `perdido` / `perdi` / `não rolou` / `nao rolou` → se sem motivo, cai no erro 6.2 que pede o motivo.
- **Valor solto** (sem prefixo) **continua válido só em resposta-quote ao lembrete** (`aguardando_valor=true`) — preserva a invariante "fora de resposta direta, `#N` é obrigatório".
- Formatos de valor já cobertos (`R$`, BR, US, sufixo `k`) — manter.

Não fazer:
- Tolerância a typo no conjunto de motivos (mantém os 6 fixos; o erro 6.2 já os lista).
- Interpretar texto livre ("acho que foi uns mil e quinhentos") — P1.

### 6.4 Digest de pendências (superfície nova — maior peça)

Resolve o problema da **thread plana** (#5). É um índice "o que aguarda você".

**Gatilho** (a decidir — ver §9): comando sob demanda no grupo (`pendências` / `status`, sem `#N`) e/ou card matinal agendado (cron por modelo, dentro do horário de operação).

```
📋 *Pendências* · 3 aguardando você
🔔 #58 Lia — handoff: cliente pedindo desconto
💵 #42 Marina — falta o valor (encerrou 14:30)
⚠️ #51 Bia — Pix a conferir

👉 responda no número, ex.: *fechado #42 1500*
```

**Estado vazio** (regra `Empty States`):
```
📋 *Pendências* · tudo em dia ✨
Nenhum card aguardando você agora.
```

**Mecanismo (alto nível):** consultar atendimentos da modelo com flag de pendência — IA pausada com escalada aberta; `Em_execucao` passado de `bloqueios.fim` aguardando valor; Pix `em_revisao` não resolvido. Reúsa os emojis de tipo. **Custo:** uma query de repo nova + rota de comando no grupo (+ cron opcional). É a peça que mais agrega escopo — faseável por último.

---

## 7. Invariantes de domínio respeitadas (checklist)

- [x] **Pix nunca trava** — card 5.3 reforça a decisão dela + revisão assíncrona do Fernando; sem handoff síncrono.
- [x] **Foto de portaria sem vision no P0** — card 5.4 só pede "confira a foto", não afirma validação.
- [x] **Comando da modelo é efetivo imediatamente** — confirmação é eco, não gate; undo = Corrigir no painel.
- [x] **`#N` obrigatório fora de resposta-quote** — forgiveness não afrouxa isso; valor solto só no lembrete.
- [x] **Interpretação determinística (regex) no P0** — forgiveness é regex; NLP é P1.
- [x] **Cards são voz operacional, não persona** — registro interno; podem ser explícitos.
- [x] **Card a partir do número da modelo** — canal inalterado; só muda o texto.

---

## 8. Restrições de plataforma (Evolution v2.3.6 self-host) que moldam o design

- **Mensagem de sessão livre, sem aprovação de template.** Diferente da WhatsApp Business API oficial (Meta aprova cada template e oferece botões/listas), o Evolution self-host manda texto livre. **Vantagem:** liberdade total de copy, iteramos sem pedir aprovação. **Custo:** não há os componentes interativos da API oficial.
- **Sem botões / list messages / templates interativos** — por isso o comando-em-texto é obrigatório (é a consequência direta do ponto acima, não uma escolha de design).
- **Limite de tamanho não é restrição** — texto de sessão aceita ~4096 caracteres; nossos cards têm dezenas. O inimigo é o **scroll/atenção**, não o limite técnico.
- **Sem reactions / polls / stickers** — descarta ack por reação 👍 (parte do "forgiveness" pedido fica inviável na plataforma).
- **Quote-reply não faz lookup por ID** — o balão de citação só mostra `quoted.message.conversation`; o parser extrai o `#N` do **texto do card citado** (`_numero_curto`, regex `#(\d+)\b`). **Consequência dura:** o `#N` precisa estar sempre presente e em formato `#42` puro (negrito ao redor, `*#42*`, é tolerado pelo regex; evitar separar o `#` do número).
- **Formatação disponível:** `*negrito*`, `_itálico_`, `~tachado~`, monospace, quebras de linha, emoji. Nada além disso.
- **Cards burlam a humanização** (sem "digitando", sem pausa, 1 chamada Evolution por card) — ok para resultados assíncronos; o digest é o que mitiga o acúmulo.

---

## 9. Decisões resolvidas

| # | Decisão | Veredito | Por quê |
|---|---------|----------|---------|
| 0 | Cards de FYI puro merecem mensagem própria? | **Manter todos os cards atuais.** A régua anti-fadiga vira **guardrail para o futuro**, não remoção agora. | Os 3 FYI de hoje (saída confirmada, cliente saiu, cliente chegou) **preparam ação real** da modelo — passam no teste "muda o comportamento dela". Não há FYI redundante hoje; cada atendimento gera 1–2 deles, não há storm. O controle de volume real é o **dedup + digest** (Fase 4), não cortar card que prepara ação. |
| 1 | Gatilho do digest | **Só sob demanda** (`pendências` / `status`) no P0. Cron matinal **diferido**. | Sob demanda não precisa de cron, não tem quiet-hours, não corre risco de virar mais uma notificação automática (contra a própria regra anti-fadiga). O matinal agendado só se a operação pedir — vira item de backlog, não de P0. |
| 2 | Separador da linha de detalhe | **`·` como junção, no máximo 2 campos por linha.** Endereço longo ganha linha própria. | `·` compacta e lê bem no celular. Mas 3+ campos numa linha quebram feio em tela estreita (375px). Regra: pareie campos **curtos** (combinado·deslocamento; horário·data); valor longo (endereço) sozinho. |
| 3 | Sufixo de repasse na confirmação de `fechado` | **Mostrar `· repasse R$ X` quando há snapshot;** omitir quando nulo/pendente. | Quando o repasse foi calculado, é o dado que a modelo quer ver na hora. Quando não há acordo cadastrado, mostrar "pendente" é ruído — `Registro de resultado` já fecha com repasse nulo sem alarde. |
| 4 | `👉` vs `↳` no rodapé | **`👉`.** | Já em uso no handoff (consistência), reconhecível, e o registro caloroso-mas-seco do card combina mais com `👉` do que com o `↳` (técnico demais para a modelo). |
| 5 | Migrar o lembrete para `.j2` | **Migrar.** | A gramática **exige** template (header + rodapé estruturados); manter string hard-coded seria a única exceção entre 5 cards. Uniformiza a manutenção e o filtro de moeda BR. |
| 6 | Onde aparecem cards `owner=Fernando` (§1.5) | **Roteia por `owner`:** modelo→grupo, Fernando→painel/fila (P0). Exceção: lembrete-sem-resposta fica no grupo. | Usa o campo `owner` que já existe no código. Mantém o grupo da modelo limpo e sobre ela; jailbreak/política/exaustão são decisão do Operador e vivem no painel (IA Admin no P1). **Implica auditar `_card_escalada`:** se hoje ele posta todo tipo no grupo, passa a filtrar por `owner`. |

> Decisões 0 e 1 são as únicas com cara de produto (mudam o que a modelo vivencia / o escopo). Resolvi pelo caminho de **menor risco e menor ruído**; se a operação quiser o digest matinal ou rebaixar algum FYI, é trocar a linha — nada na arquitetura trava isso.

---

## 10. Mapa de implementação (faseável — não faz parte desta proposta escrever código)

| Fase | Escopo | Arquivos |
|---|---|---|
| **1 — Gramática nos templates** | Reescrever os 4 `.j2` + migrar lembrete para `.j2`; filtro de moeda BR | `workers/_cards/{escalada,pix,chegada,aviso_saida}.md.j2`, `lembrete_valor.py:145`, helper de formatação |
| **1b — Roteamento por owner** | `_card_escalada` filtra: `owner=modelo` → grupo; `owner=Fernando` → não posta no grupo (vai pro painel/fila), exceto lembrete-sem-resposta | `workers/envio.py:_card_escalada`, `dominio/escaladas/` (campo `owner`/`responsavel`) |
| **2 — Confirmações + erros** | Eco de confirmação padronizado (CONTEXT pede; código está "silencioso" hoje); erros com recuperação | localizar/criar o emissor de confirmação (`webhook/routes.py:_processar_grupo` → `aplicar_comando`); `webhook/parser.py` (mensagens de erro) |
| **3 — Forgiveness** | Sinônimos de comando, mantendo invariantes | `webhook/parser.py:parse_comando_grupo` (96-144), `_VALOR_RE`, conjunto de motivos (213-215) |
| **4 — Digest de pendências** | Comando `pendências` + query de repo + (opcional) cron | rota de comando no grupo, repo novo de "pendências por modelo", `workers/` (cron opcional) |

Cada fase entrega valor isolada. A Fase 1 já resolve a maior parte do diagnóstico (#1, #2, #4, #7).
