# 05 — Regras de Escalada Humana e Regras da IA

## 1. Regras de Escalada Humana

A escalada humana é um dos pontos mais importantes do sistema.

### 1.1 Escalada obrigatória

A IA deve escalar obrigatoriamente quando:

- o atendimento envolver deslocamento externo (saída), depois de validar o pix;
- houver informação que a IA não consiga validar;
- o cliente confirmar chegada (em fluxo interno) e enviar qualquer imagem (qualquer imagem recebida em `Aguardando_confirmacao` interno é tratada como foto da portaria, sem validação por vision).

### 1.2 Mecânica do handoff — canais persistentes (grilling 29/04)

> **Decisão do grilling:** **NÃO criar grupo por atendimento** — risco de banimento + ruído na lista da modelo.

Dois canais persistentes de operação, mais a conversa do cliente e Chatwoot em modo read-only:


| Canal                      | Participantes                                                          | Propósito                                                                                                                 |
| -------------------------- | ---------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| **Conversa cliente**       | Cliente ↔ número da modelo existente, operado pela IA                  | IA responde em nome da modelo; no handoff, a IA continua processando e registrando mensagens, mas não responde até devolução explícita |
| **Coordenação por modelo** | número da modelo (+IA) + Fernando — 1 grupo fixo por modelo            | IA envia resumos/cards para a modelo acompanhar sem ler todas as conversas; Fernando vê o contexto operacional da modelo |
| **IA Admin (P1)**          | Fernando + IA Admin                                                    | Grupo interno para Fernando falar com uma IA administrativa, editar agenda, consultar comprovantes e executar ações internas |
| **Chatwoot (read-only)**   | Vendedor                                                               | Câmera de segurança, sem ação                                                                                             |


Quando a IA decide escalar, ela aciona a modelo via grupo de **coordenação** quando houver ação operacional dela. Em P1, exceções administrativas e comandos internos de Fernando podem ir para o **grupo IA Admin**.

> **Vulgaridade do cliente não é gatilho de escalada.** A IA trata cliente vulgar como cliente comum, sem mudança especial de tratamento nem escalada por vulgaridade.


| Tipo de exceção                             | Para onde                                                                              |
| ------------------------------------------- | -------------------------------------------------------------------------------------- |
| Saída confirmada (Pix OK)                   | Coordenação por modelo → modelo se prepara; Fernando/equipe decide pelo painel quando houver decisão sensível |
| Pix em revisão                              | Painel → Fernando/equipe aceita/recusa; IA Admin em P1                                        |
| Conflito CRM/agenda vs cliente              | Painel → Fernando/equipe decide; IA Admin em P1                                               |
| Agressividade / pedido fora do padrão       | Painel → Fernando/equipe decide; IA Admin em P1                                               |
| Cliente confirma chegada (foto da portaria) | Coordenação por modelo → modelo se prepara                                             |
| Cliente avisa que saiu (rumo à modelo)      | Coordenação por modelo → modelo se arruma                                              |
| Modelo offline (timeout de coordenação)     | Painel → Fernando/equipe notificado; IA Admin em P1                                           |


### 1.3 Protocolo de coordenação IA → modelo (grilling §1.3)

- IA manda **card estruturado** no grupo de coordenação: *"[Atendimento #N] Cliente, tipo, endereço, horário; confirma?"*
- O card contém o resumo operacional necessário para a ação da modelo, sem exigir que ela acompanhe a conversa inteira.
- Fernando está no grupo de coordenação para enxergar o contexto operacional da modelo.
- Quando o caso exigir decisão sensível de Fernando/equipe, o resumo decisório fica disponível no painel; em P1, também pode ir para o IA Admin.
- Modelo confirma ✅ / ❌ / ⏰.
- **Timeouts:**
  - 10 min sem resposta → IA reenvia com aviso;
  - 20 min sem resposta → notifica Fernando/equipe no painel; em P1, também no IA Admin;
  - 30 min sem resposta → IA "esfria" o cliente.
- Modelo offline → sistema entra em standby para essa modelo, alerta Fernando/equipe.

### 1.4 Debounce multi-device (grilling §1.4)

Esta seção é a fonte canônica para comandos de handoff, devolução para IA, registro de resultado e correção operacional.

- A modelo mantém acesso ao celular com o próprio WhatsApp/número, mas **não precisa acompanhar as mensagens que a IA envia**. Ela acompanha o grupo de coordenação para receber resumos e cards operacionais.
- No handoff, a IA para de responder e a modelo pode escrever ao cliente no mesmo WhatsApp; para o cliente, a conversa sempre parece ser com a modelo.
- Depois do handoff, a IA **não retoma automaticamente** a conversa por tempo, timeout ou mudança de estado. Ela só volta a responder quando Fernando ou a modelo devolver explicitamente o atendimento para a IA no grupo ou painel.
- No grupo, a devolução explícita usa `IA assume` quando for resposta ao card do atendimento, ou `IA assume #N` quando não houver contexto de resposta.
- No painel, a devolução explícita usa o botão `Devolver para IA`.
- Toda devolução registra quem devolveu, quando devolveu e de qual canal veio o comando.
- Enquanto `ia_pausada=true`, o sistema continua registrando todas as mensagens da conversa cliente, incluindo mensagens manuais da modelo e respostas do cliente; apenas a resposta automática da IA fica bloqueada.
- Mensagens novas do cliente durante `ia_pausada=true` **não geram alerta automático** no grupo de coordenação nem no IA Admin. Também não geram badge, contador de não lidas ou destaque no painel; durante handoff, presume-se que a modelo acompanha o cliente pelo próprio WhatsApp.
- Resultado durante handoff é registrado explicitamente por quem assumiu. No grupo, usar `fechado valor` / `perdido motivo` como resposta ao card, ou `fechado #N valor` / `perdido #N motivo` fora do contexto do card.
- Comando sem `#N` só é válido quando for resposta direta ao card do atendimento. Fora do contexto do card, o comando precisa trazer `#N`.
- O sistema não tenta inferir atendimento quando houver comando sem `#N` fora de resposta ao card, mesmo que pareça haver apenas um atendimento provável.
- No grupo de coordenação, apenas Fernando ou a modelo podem executar comandos de resultado.
- Comando de resultado válido vindo da modelo é aceito diretamente; não exige confirmação prévia de Fernando.
- Fernando pode corrigir resultado, valor ou motivo posteriormente pelo painel, com auditoria.
- Correção de resultado pelo painel recalcula campos financeiros e ajusta apenas o bloqueio de agenda vinculado.
- Se a correção mudar para `fechado`, o bloqueio vinculado vira `concluido`.
- Se a correção mudar para `perdido`, o bloqueio vinculado vira `cancelado` somente se ainda não estiver `em_atendimento` nem `concluido`; caso contrário, o painel pede confirmação explícita de Fernando antes de alterar a agenda.
- No painel, apenas Fernando usa `Marcar fechado` ou `Marcar perdido`. Perda exige motivo padronizado; `outro` cobre casos fora da lista.
- Fechamento exige `valor_final`, porque alimenta o financeiro. `valor_final` é o valor total bruto pago pelo cliente, não o repasse da agência. `fechado` sem valor não encerra o atendimento; o sistema pede complemento de valor no grupo ou painel.
- O valor no comando pode vir em formatos comuns brasileiros, como `1000`, `1.000`, `R$ 1.000`, `1000,00` ou `1.000,00`; o sistema normaliza para decimal.
- Se o valor for ambíguo, como `1,5`, o sistema não encerra e pede confirmação do valor.
- Quando `fechado valor` é registrado, o bloqueio de agenda vinculado ao atendimento vira `concluido` automaticamente. Bloqueios não vinculados ao atendimento não são alterados.
- Quando `perdido motivo` é registrado, o bloqueio de agenda vinculado ao atendimento vira `cancelado` automaticamente apenas se ainda não estiver `em_atendimento` nem `concluido`. Bloqueios não vinculados ao atendimento não são alterados.
- Após aceitar um comando de resultado no grupo, o sistema sempre responde no grupo com confirmação curta contendo `atendimento_id`, resultado, valor ou motivo e efeito na agenda. Ex.: `Fechado #123 registrado: R$ 1.000. Agenda concluída.`
- Comando de resultado inválido, incompleto ou ambíguo também recebe resposta curta no grupo, sem alterar atendimento, agenda ou financeiro. A resposta deve dizer o que faltou e o formato esperado.
- Exemplos: `Não registrei #123: falta valor. Use fechado #123 1000.`; `Não registrei: motivo inválido. Use preco, sumiu, risco, indisponibilidade, fora_de_area ou outro.`
- No fechamento, o sistema copia o percentual de repasse vigente no cadastro da modelo quando ele estiver cadastrado; se não estiver, o fechamento continua permitido e o repasse fica pendente/nulo. Atendimentos antigos não são recalculados se o acordo da modelo mudar depois.
- Motivos de perda aceitos no MVP: `preco`, `sumiu`, `risco`, `indisponibilidade`, `fora_de_area`, `outro`.
- Quando o motivo for `outro`, registrar observação curta.
- Se o grupo receber `perdido` sem motivo, o sistema não encerra o atendimento ainda; responde pedindo complemento com a lista curta de motivos aceitos.
- Se o motivo vier em texto livre e não encaixar na lista, registrar `motivo_perda=outro` e salvar o texto como observação.
- Se ninguém registrar resultado durante handoff, o atendimento permanece aberto; o sistema não infere fechamento/perda com `ia_pausada=true`.
- Se mensagem `fromMe` da modelo entra no Evolution durante a IA compor resposta, **cancela qualquer envio em fila** para esse `conversation_id` por **60s**.

### 1.5 Conteúdo da mensagem de handoff

Quando escalar, o sistema deve entregar no canal apropriado:

- resumo da conversa;
- intenção do cliente;
- profissional de interesse;
- horário desejado;
- motivo da escalada;
- risco percebido;
- histórico recente.

---

## 2. Regras da IA

### 2.1 Regras gerais

- A IA deve responder apenas dentro de fluxos permitidos.
- A IA deve consultar agenda antes de falar sobre disponibilidade.
- A IA deve registrar dados relevantes no CRM.
- A IA deve manter tom profissional e seguro.
- A IA deve evitar improvisar.
- A IA deve escalar quando houver risco, dúvida ou ambiguidade.
- A IA não deve retomar um atendimento em handoff sem devolução explícita de Fernando ou da modelo.
- A IA deve respeitar limites legais, éticos e operacionais definidos.

### 2.2 Regras de resposta

A IA pode responder sobre:

- saudação;
- disponibilidade;
- horários;
- informações previamente cadastradas;
- próximos passos;
- confirmação de interesse;
- encaminhamento para Fernando/equipe ou modelo.

### 2.3 Regras de bloqueio

A IA não deve:

- inventar informações;
- prometer disponibilidade sem consultar agenda;
- tomar decisão de risco (saída sem escalada, valor fora do padrão);
- pressionar cliente de forma abusiva;
- conduzir situações sensíveis sem Fernando/equipe; a modelo só entra quando houver ação operacional dela;
- improvisar quando faltar dado cadastrado.
