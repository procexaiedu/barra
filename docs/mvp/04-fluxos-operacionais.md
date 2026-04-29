# 04 — Fluxos Operacionais e Máquina de Estados

## 1. Fluxo Geral de Atendimento

```text
Cliente inicia contato
↓
Sistema cria ou atualiza registro no CRM
↓
IA faz saudação e triagem
↓
IA identifica intenção
↓
Sistema consulta agenda e contexto
↓
IA identifica tipo de atendimento e urgência
↓
Sistema decide próximo passo:
  ├── IA responde automaticamente
  ├── IA coleta mais informação
  ├── IA registra sinalização de interesse
  ├── IA faz handoff para Coordenação por modelo ou sinaliza Fernando/equipe no painel
  └── atendimento pode ser marcado como perdido por timeout determinístico antes da confirmação
```

---

## 2. Fluxo Interno — Cliente vai até a modelo (apartamento, flat, hotel)

Neste fluxo, o cliente se desloca até onde a modelo está. **Não há cobrança antecipada de Pix** — pedir Pix antes do encontro, neste cenário, parece golpe ("por que pagaria se vou te encontrar?") e queima o cliente. O pagamento acontece presencialmente no momento do encontro.

```text
Cliente demonstra interesse via WhatsApp (chegou pelo BarraVips)
↓
IA identifica horário desejado e tipo (imediato, agendado, indefinido, estimado)
↓
Sistema consulta agenda da modelo
↓
IA informa disponibilidade de forma velada
↓
Cliente confirma que vai
↓
IA pede: "me avisa quando você sair, pra eu me preparar pra te receber"
↓
Sistema marca como "aguardando confirmação"
↓
Cliente avisa que saiu de casa
  → Gatilho 1: notificar a modelo para se arrumar e ficar pronta
  → IA continua a conversa de forma calorosa enquanto cliente está a caminho
↓
Cliente avisa que chegou
↓
IA pede foto da portaria/fachada para confirmar endereço
↓
Cliente envia foto (qualquer imagem recebida em `Aguardando_confirmacao` interno é tratada como foto da portaria — sem validação por vision)
  → Gatilho 2: confirmação operacional do encontro real
↓
Atendimento entra em handoff: IA pausa, envia resumo + foto no grupo de coordenação. A modelo valida visualmente a foto no grupo e assume a conversa no mesmo WhatsApp.
↓
modelo assume e finaliza presencialmente
↓
Resultado é registrado explicitamente no CRM pela modelo/Fernando (`fechado valor` ou `perdido motivo`)
↓
Se `fechado valor`, bloqueio de agenda vinculado ao atendimento vira `concluido`
Se `perdido motivo`, bloqueio vinculado vira `cancelado` apenas se ainda não estiver `em_atendimento` nem `concluido`
```

### Por que a foto da portaria

Protege contra clientes que fingem estar chegando mas não estão (perda de tempo da modelo) e contra clientes que dão endereço falso. É um **filtro de comprometimento** com baixo custo para o cliente real e alto custo para o oportunista.

### Dados capturados nesse fluxo

- horário desejado;
- profissional de interesse;
- status de confirmação (intencionou, saiu, chegou);
- timestamp em que cliente disse que saiu;
- timestamp em que cliente chegou + foto da portaria;
- responsável (Fernando/equipe ou modelo) que assumiu;
- resultado final e motivo (se perdido).

---

## 3. Fluxo Externo (Saída) — Modelo se desloca até o cliente

Este fluxo cobre quando o cliente pede que a modelo vá até ele: residência, motel, festa, restaurante, hotel. **Toda saída envolve risco operacional e logístico** que pode exigir julgamento de Fernando/equipe quando o pipeline de Pix não confirmar automaticamente.

Para saídas, a Barra Vips cobra **antecipadamente o valor do Uber** (ida e volta) via Pix. Isso protege a modelo contra cliente que chama Uber e cancela.

> **Decisão operacional — handoff após Pix confirmado.** Não há lista de bairros nem perguntas estruturadas ("você mora em comunidade?"). A IA coleta o Pix do Uber; quando o comprovante é confirmado, o horário é bloqueado e a IA envia resumo no grupo de coordenação por modelo (IA + modelo + Fernando). Se houver dúvida ou decisão sensível, o resumo decisório fica disponível no painel para Fernando.

```text
Cliente solicita que a modelo vá até ele (saída)
↓
IA identifica que é fluxo externo
↓
IA explica que precisa do Uber antecipado (ida e volta) — R$ 100 padrão — e envia chave Pix
↓
IA aguarda comprovante de Pix
↓
Pipeline de validação (ver §3.2 abaixo)
  → tudo OK → `status=Confirmado`, `pix_status=validado`, agenda bloqueada, handoff/resumo no grupo de coordenação
  → qualquer falha → mantém `status=Aguardando_confirmacao`, `pix_status=em_revisao`, IA pausa cordialmente, alerta Fernando/equipe no painel
↓
Modelo ou Fernando/equipe assumem conforme o resumo enviado no canal persistente correto
↓
Atendimento entra em `Em_execucao` ao bater o `horario_desejado`
↓
Resultado é registrado explicitamente durante handoff (`fechado valor` / `perdido motivo`). Classificação automática de resultado fica fora do P0.
↓
Se `fechado valor`, bloqueio de agenda vinculado ao atendimento vira `concluido`
Se `perdido motivo`, bloqueio vinculado vira `cancelado` apenas se ainda não estiver `em_atendimento` nem `concluido`
```

### 3.1 Política do Pix


| Item                                 | Decisão (grilling §6)                                                                         |
| ------------------------------------ | --------------------------------------------------------------------------------------------- |
| Beneficiário                         | **A modelo recebe.** Chave Pix obrigatoriamente associada a nome operacional ou nome ambíguo. |
| Cadastro obrigatório                 | `chave_pix` e `nome_titular_chave` no `modelo_perfil.comercial`.                              |
| Valor padrão                         | **R$ 100** fixo no MVP. Sem tabela por bairro.                                                |
| Cliente pede valor diferente / acima | Escala Fernando/equipe manualmente.                                                           |


### 3.2 Pipeline de validação do Pix


| Checagem                                   | Como                           | Falha resulta em |
| ------------------------------------------ | ------------------------------ | ---------------- |
| OCR consegue ler o comprovante             | OCR + vision                   | Pede outra foto  |
| Beneficiário bate com `nome_titular_chave` | Match fuzzy                    | Escala Fernando/equipe |
| Chave Pix bate com cadastro                | Match exato                    | Escala Fernando/equipe |
| Valor exato                                | Tolerância R$ 0                | Escala Fernando/equipe |
| Timestamp ≤ 30 min do pedido               | Comparação direta              | Escala Fernando/equipe |
| Comprovante visualmente plausível          | LLM vision (score < 0.7 falha) | Escala Fernando/equipe |


- Tudo passa → `status=Confirmado`, `pix_status=validado`, agenda bloqueada, handoff/resumo no grupo de coordenação.
- Qualquer falha → atendimento permanece em `Aguardando_confirmacao`, `pix_status=em_revisao`. IA cordialmente pausa o cliente: *"deixa eu confirmar pra você"*. Alerta no painel com a imagem + motivo + última mensagem do cliente. Fernando/equipe decide pelo painel; em P1, Fernando pode responder por áudio via IA Admin.

> Como o Pix só é cobrado dentro de uma janela de atendimento ativo da modelo, **não existe o caso "Pix recebido fora do horário"**.

---

## 4. Fluxo de Agenda por Comando Interno (P1 — IA Admin)

```text
Fernando manda áudio no grupo da IA Administrativa
↓
IA transcreve o áudio
↓
IA interpreta a intenção (bloqueio, liberação, consulta)
↓
Sistema identifica profissional, data e horário
↓
Sistema verifica conflito
↓
Se ambíguo → IA pede confirmação no grupo antes de executar
↓
Se não houver conflito, confirma bloqueio e responde no grupo
↓
Agenda é atualizada
↓
Atendimentos futuros passam a considerar o bloqueio
```

---

## 5. Tipologia de Cliente por Urgência

Fernando identificou quatro perfis distintos de cliente baseados na disponibilidade e urgência. **Cada perfil exige uma cadência de conversa diferente** e a IA precisa classificar o cliente o mais cedo possível.


| Tipo                             | Perfil                                                                                              | Comportamento esperado da IA                                                                                       |
| -------------------------------- | --------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| **1. Imediato**                  | Quer agora. Está disponível, mora perto, pode chegar em 10–15 min.                                  | Para internos, dispensa o Pix; confirma disponibilidade, pede aviso quando sair, notifica modelo.                  |
| **2. Agendado com antecedência** | Combina serviço para outro dia ou horário futuro. Ex.: contato na terça, atendimento quarta às 16h. | Para saídas, cobra Pix do Uber; bloqueia agenda após Pix validado; confirmação 1–2h antes fica para P1/manual.      |
| **3. Horário indefinido**        | "Quando eu sair do trabalho eu te aviso." Pode aparecer a qualquer momento.                         | Mantém conversa quente com toques leves; não bloqueia agenda firme; pronta para reagir quando o cliente sinalizar. |
| **4. Horário estimado**          | "Saio do trabalho às 6." Sabe aproximadamente quando estará disponível.                             | Mantém conversa natural quando o cliente responde; automação de reativação no horário esperado fica fora do P0.     |


### Filtro comportamental "fecha vs não fecha"

> **Removido pelo grilling 29/04.** Sem score contínuo, sem cooling gradual. A IA trata todos os clientes com o mesmo comportamento (calor, mídia, fechamento ativo).

Mantidas **apenas** as escaladas pontuais já existentes em `05-escalada-regras-ia.md`:

- ameaça/agressividade → escalada imediata;
- pedido fora do padrão (ex.: desconto além de 10%) → escalada.

Essas escaladas são proteções de canal e segurança, não classificação de cliente. Vulgaridade do cliente não é gatilho especial: a IA trata cliente vulgar como cliente comum, sem mudança especial de tratamento nem escalada por vulgaridade.

---

## 6. Indisponibilidade Contextual da Modelo

Quando uma modelo está em atendimento (agenda bloqueada), a IA **não para de responder** outros clientes que chegam pelo mesmo número. Ela informa indisponibilidade com **desculpas contextuais** consistentes com a persona e com o horário, e tenta reagendar.


| Horário do bloqueio           | Desculpa típica                                     |
| ----------------------------- | --------------------------------------------------- |
| Manhã / início da tarde       | "Estou no salão agora, te respondo em breve."       |
| Fim de tarde / antes de saída | "Estou me arrumando, posso te ver mais tarde?"      |
| Noite                         | "Estou na balada, amanhã consigo te receber?"       |
| Madrugada                     | "Já estou recolhida hoje, vamos marcar pra amanhã?" |


Essas desculpas precisam ser **coerentes com o que a modelo "diria"** — quebra de persona aqui também queima o cliente. O sistema seleciona a desculpa baseado no horário do bloqueio.

---

## 7. Gestão de Mídia no Atendimento

O envio de fotos e vídeos é parte central do fechamento. A estratégia é progressiva:

1. **Foto primeiro** — IA envia foto pré-aprovada da modelo quando o cliente pede.
2. **Se cliente quer mais prova** — IA envia **vídeo curto em modo "visualização única"**, com narrativa de "estou gravando agora pra você" (mesmo sendo pré-gravado). A visualização única protege o conteúdo de circulação indevida.
3. **Foto da portaria** — em fluxo interno, **o cliente envia uma foto** quando chega, e a IA precisa receber e processar a imagem.

Requisitos do sistema:

- biblioteca de mídias **pré-aprovadas por modelo**, com tags (foto rosto, foto corpo, vídeo curto, etc.);
- biblioteca mínima P0 em MinIO, com pelo menos 10 mídias pré-aprovadas por modelo;
- envio em modo de visualização única quando o canal suportar;
- se o canal não suportar visualização única, vídeo não é enviado automaticamente e o caso escala para Fernando/equipe;
- recebimento de imagens enviadas pelo cliente e armazenamento associado ao atendimento por 30 dias, salvo disputa ou auditoria.

---

## 8. Máquina de Estados do Atendimento

> P0 usa estados canônicos simples e auditáveis. Estados inferidos ficam para P1; detalhes de Pix ficam em `pix_status`, não em `status`.

```text
Novo → Triagem → Qualificado → Aguardando_confirmacao
      ↓                                ↓
   Perdido                         Confirmado (Pix OK | imagem recebida)
                                       ↓
                          Em_execucao (a partir do horario_desejado)
                                       ↓
                              Fechado | Perdido
```

### 8.1 Estados e disparadores


| Transição                                | Disparador                                                                 |
| ---------------------------------------- | -------------------------------------------------------------------------- |
| `Novo` → `Triagem`                       | Primeira mensagem do cliente                                               |
| `Triagem` → `Qualificado`                | IA extrai intenção real da conversa                                        |
| `Qualificado` → `Aguardando_confirmacao` | IA pediu Pix, aviso de saída ou imagem de portaria                         |
| `Aguardando_confirmacao` → `Confirmado`  | OCR/vision valida Pix ou imagem é recebida no fluxo interno                |
| `Confirmado` → `Em_execucao`             | Relógio bate `horario_desejado`                                            |
| `Aguardando_confirmacao` → `Perdido`     | Timeout determinístico antes da confirmação, com `motivo_perda=sumiu`      |
| `Em_execucao` → `Fechado`                | Registro explícito por Fernando ou modelo                                  |
| `Em_execucao` → `Perdido`                | Registro explícito por Fernando ou modelo                                  |


> No fluxo interno, quando o cliente avisa que saiu de casa, o sistema notifica a modelo para se arrumar e ficar pronta. A modelo não precisa mandar "voltei". Durante handoff, a conversa continua alimentando histórico e resumo, mas não muda estado automaticamente.

### 8.2 Auditabilidade e reversibilidade

- Cada atendimento tem `fonte_decisao` P0 em `{modelo, fernando, sistema, auto_timeout, fernando_revisado}`. Valores de classificador (`classificador_alta`, `classificador_media`) só entram em P1.
- Dashboard avançado em P1 começa filtrando decisões automáticas para Fernando revisar amostras.
- Fernando pode reverter pelo painel. Em P1, pode reverter por áudio: *"abre o atendimento do João de ontem"* → o sistema volta para `Em_execucao` ou `Qualificado` e marca `fonte_decisao = "fernando_revisado"`.

---

## 9. Concorrência — múltiplos clientes, uma modelo

Decisão do grilling 29/04 (§9):

- A IA atende clientes B/C/D em paralelo enquanto cliente A está em encontro.
- Usa **desculpas contextuais** (tabela do §6 deste arquivo).
- **Não bloqueia agenda firme** para B/C/D durante o encontro de A.
- Quando A fecha → notifica B/C/D que estavam em espera (*"agora consigo, ainda tá de pé?"*).
- Cliente B "imediato" insistindo → vira `Perdido` com motivo adequado (`sumiu` ou `indisponibilidade`). **No MVP com 1 modelo, não há redirecionamento para outra.**

---

## 10. Conflito CRM/agenda vs cliente

Quando cliente alega acordo prévio que não bate com CRM:

- IA **não confronta** (*"você está enganado"*) nem **concorda** (*"ah é, lembrei"*).
- Resposta de stall: *"deixa eu confirmar uma coisa aqui, te respondo já já"*.
- Em paralelo, alerta no painel com transcrição da reivindicação + registro relevante do CRM (último atendimento, valor padrão, observações).
- Fernando/equipe decide pelo painel. Em P1, Fernando pode decidir por áudio via IA Admin.

**Trigger:** extração/alerta por IA detecta padrão *"você disse / marcamos / combinamos / tinha falado"* + tool de busca no CRM cruza com histórico. No P0 isso gera alerta; não muda estado sensível sozinho.

---

## 11. Cliente envia áudio

Decisão do grilling 29/04 (§13):

- **Transcrever sempre.** Transcrição entra no contexto como `[áudio do cliente]: "<transcrição>"`.
- IA **responde em texto**, sem citar a transcrição literal.
- **Áudio gerado por IA (TTS) NÃO no MVP** — TTS é detectável e quebra persona pior. Voice cloning fica para fase pós-piloto.
- Áudio impossível de transcrever → IA pede texto cordialmente.
- Áudio com conteúdo explícito → mesmas regras textuais e de escalada, sem mudança especial de tratamento. **Áudio bruto não preservado >24h** pós-transcrição.

**Caso de borda:** quando a única evidência de número/horário vem de transcrição, a IA confirma com o cliente parafraseando (*"entendi 200 pelo Uber, certo?"*) para mitigar erro de transcrição.

---

## 12. Ambiente de teste pré-piloto (Fase 1.5)

A Fase 1.5 não usa conversa cliente real. O time tech provisiona um número de WhatsApp de teste (chamado aqui de "número X") e o conecta ao Evolution. Lucas e o número X formam um **grupo de teste** — apenas dois participantes — cujo `JID` fica configurado no sistema.

Regras do ambiente de teste:

- a IA só responde dentro do `JID` do grupo de teste durante a Fase 1.5;
- mensagens vindas de qualquer outra origem são ignoradas até a Fase 2;
- Lucas digita no grupo simulando o cliente; a IA responde como se ele fosse cliente real;
- não há flag `is_test` em cliente ou atendimento — o isolamento vem do `JID` configurado, não de marcação por entidade.

Quando a Fase 2 começar, a modelo piloto escaneia um QR code gerado no painel para vincular o número dela ao Evolution e a IA passa a operar conversas cliente reais. O grupo de teste continua existindo apenas se o time precisar recalibrar.
