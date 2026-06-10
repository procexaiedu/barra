# 04 — Fluxos Operacionais

Este documento descreve os fluxos de conversa, agenda e Pix do MVP. Não duplica modelagem de banco (`06-dados-interfaces.md`) nem regras de escalada/handoff em si (`05-escalada-regras-ia.md`); concentra a sequência operacional que a IA, o coordenador (5.2) e os humanos seguem em cada cenário.

## 1. Fluxo geral de atendimento

Aplica-se a todo cliente que chega pelo Elite Baby, antes de o tipo de atendimento (interno ou saída) estar definido.

### 1.1 Sequência canônica

1. **Primeira mensagem do cliente** — Evolution dispara webhook → Coordenador (5.2) persiste mensagem bruta, aplica debounce (~3–5s) e adquire lock da conversa.
2. **Resolução determinística** — Coordenador identifica `cliente_id` por telefone; reusa atendimento aberto para `(cliente_id, modelo_id)` se houver um em estado ∉ {`Fechado`, `Perdido`}, senão cria novo em `Novo`.
3. **Triagem pela IA** — IA de Atendimento (5.3) chama `consultar_cliente`, `consultar_agenda` e demais tools de leitura conforme necessário; resposta segue para Humanização (5.5).
4. **Identificação de intenção** — IA classifica intenção (curiosidade/cotação/agendamento) e tipo de atendimento (interno ou externo). Quando o sinal é ambíguo, a IA pergunta naturalmente (sem pergunta de triagem rígida).
5. **Coleta de dados mínimos** — horário desejado, urgência, profissional de interesse, local do atendimento. Coleta via conversa, não formulário.
6. **Qualificação** — quando intenção real está clara e os dados mínimos foram capturados, IA registra extração via `registrar_extracao`; coordenador aplica transição → `Qualificado`.
7. **Bifurcação por tipo** — fluxo segue para §2 (interno) ou §3 (externo), conforme a decisão da IA.
8. **Confirmação** — saída do estado `Aguardando_confirmacao` por evento próprio do tipo: Pix validado no externo move para `Confirmado` (com IA pausada, modelo conduz); foto de portaria no interno move direto para `Em_execucao` (com IA pausada, modelo já está com o cliente).
9. **Registro de resultado** — Fernando ou modelo registram `fechado valor` ou `perdido motivo` pelos comandos canônicos do grupo de Coordenação por modelo, ou Fernando pelo painel.

### 1.2 Princípios do fluxo geral

- A IA conduz sozinha até a confirmação ou até bater num gatilho de escalada de `05-escalada-regras-ia.md`.
- Toda transição de estado é registrada com `fonte_decisao` (extração da IA, evento de pipeline, comando humano ou timeout determinístico).
- `ia_pausada=true` só é ativada por `escalar` da IA ou por `pix_em_revisao` do pipeline; mensagens entrantes durante pausa são gravadas em 5.1 sem indicador no painel.
- Avaliação de local de saída é responsabilidade da modelo e de Fernando, fora do escopo da IA.

---

## 2. Fluxo interno (cliente vai à modelo)

Aplica-se quando a IA classifica o atendimento como interno: cliente se desloca até o endereço da modelo.

### 2.1 Sequência canônica

1. **Acordo do horário e local** — IA confirma horário e endereço acordado.
2. **Bloqueio prévio da agenda** — quando a IA registra extração com `tipo_atendimento=interno` e horário definido, coordenador cria bloqueio em `bloqueado` vinculado ao atendimento e move para `Aguardando_confirmacao`.
3. **Aviso de saída** — cliente avisa que saiu de casa em direção ao endereço. Coordenador grava `aviso_saida_em` e envia card simples no grupo de Coordenação por modelo para preparar a modelo. **A IA continua respondendo o cliente normalmente** e o estado permanece em `Aguardando_confirmacao`.
4. **Foto de portaria — cliente chegou** — cliente envia imagem da portaria/local de encontro. Webhook detecta imagem em `Aguardando_confirmacao` interno e dispara três efeitos atômicos:
   - card "cliente chegou — `#N`, [endereço], horário X" no grupo de Coordenação por modelo, com a imagem anexada;
   - `ia_pausada=true` com motivo `modelo_em_atendimento` (a IA para de responder o cliente);
   - atendimento vai direto de `Aguardando_confirmacao` para `Em_execucao` e o bloqueio vai a `em_atendimento`.

   Sem vision automática sobre a foto (`02 §3.2`, decisão grilling 29/04). A inspeção visual da modelo no grupo é proteção operacional antes de abrir a porta e não condiciona a transição.
5. **Encerramento** — modelo registra `finalizado [valor]` no grupo respondendo ao card. Coordenador encerra como `Fechado`, libera `ia_pausada=false`, marca o bloqueio como `concluido` e registra financeiro. Fernando pode corrigir depois pelo painel.

### 2.2 Perda no fluxo interno

- **Antes do aviso de saída** — cliente para de responder e bate o timeout determinístico longo de §5.1 (24 h sem mensagem em estados pré-confirmação) → `Perdido` com `motivo_perda=sumiu`.
- **Após aviso de saída, sem foto de portaria** — quando passa o timeout interno curto de §5.2 (45 min do envio do Aviso de saída), coordenador marca `Perdido` com `motivo_perda=sumiu`, cancela o bloqueio vinculado e **não envia mensagem ao cliente**. A IA permanece ativa (`ia_pausada=false`); se o cliente voltar a falar depois, a próxima mensagem dispara um novo atendimento na regra de resolução determinística do coordenador (`03 §5.2`).
- **Cliente desistiu na portaria** — modelo registra `perdido [motivo]` no grupo respondendo ao card.

### 2.3 O que a IA não faz no fluxo interno

- Não pede Pix antecipado (Pix interno fica fora do MVP — `02 §3.2`).
- Não interpreta conteúdo da foto de portaria por vision automática.
- Não responde o cliente após a foto de portaria — quem assume é a modelo, manualmente no mesmo número.
- Não decide se o cliente é seguro com base no endereço dele.

---

## 3. Fluxo externo (saída) — cliente recebe a modelo

Aplica-se quando a IA classifica o atendimento como externo: a modelo se desloca até o cliente.

### 3.1 Sequência canônica

1. **Acordo do horário e endereço** — IA confirma horário, endereço de destino e bairro/região. Endereço é dado obrigatório no fluxo externo.
2. **Bloqueio prévio da agenda** — coordenador cria bloqueio em `bloqueado` vinculado ao atendimento e move para `Aguardando_confirmacao`. Apenas Pix validado libera a saída efetiva.
3. **Pedido de Pix de deslocamento** — IA chama `pedir_pix_deslocamento(valor=R$ 100, chave_pix, titular)`. Coordenador atualiza `pix_status=aguardando` e envia mensagem com chave/titular para o cliente. Valor único de R$ 100 no MVP (`02 §3.2` — sem tabela de Uber por bairro).
4. **Recebimento do comprovante** — cliente envia imagem do comprovante. Coordenador aciona pipeline OCR/vision do módulo Pix (4.6/5.6) com `pix_status=enviado`.
5. **Validação automática** — pipeline checa beneficiário, chave Pix, valor, timestamp e plausibilidade visual. Todas as checagens passam → `pix_status=validado`; falha ou dúvida → `pix_status=em_revisao`.
6. **Caminho A — Pix validado** — coordenador dispara três efeitos atômicos:
   - card "saída confirmada — `#N`, [endereço], horário X, valor combinado Y" no grupo de Coordenação por modelo;
   - `ia_pausada=true` com motivo `modelo_em_atendimento` (a IA não responde mais o cliente desse atendimento);
   - atendimento → `Confirmado` e bloqueio segue ativo aguardando o horário.

   A IA não envia mensagem confirmando o Pix ao cliente — quem assume a conversa daí em diante é a modelo, manualmente no mesmo número.
7. **Caminho B — Pix em revisão** — coordenador define `ia_pausada=true` com motivo `pix_em_revisao`, mantém atendimento em `Aguardando_confirmacao` e envia card para Fernando no grupo de Coordenação por modelo (e no painel, em `Pix e Comprovantes`). Fernando valida ou recusa; `atualizar_pix(validado)` cai no caminho A acima, `atualizar_pix(recusado)` segue para §3.2.
8. **Saída e atendimento físico** — modelo se desloca; bloqueio vai para `em_atendimento` quando o horário chega.
9. **Encerramento** — modelo registra `finalizado [valor]` no grupo respondendo ao card. Coordenador encerra como `Fechado`, libera `ia_pausada=false`, marca o bloqueio como `concluido` e registra financeiro. Fernando corrige depois pelo painel se necessário.

### 3.2 Pix recusado por Fernando

Fernando recusa pelo painel → `pix_status=invalido`. Atendimento continua em `Aguardando_confirmacao` com `ia_pausada=false` (Fernando pode escalar verbalmente para a IA pedir novo Pix ou para a modelo decidir descartar). No P0, a IA não pede automaticamente um segundo Pix; Fernando decide o próximo passo.

### 3.3 Perda no fluxo externo

- Cliente não envia Pix dentro do timeout determinístico de §5 → `Perdido` com `motivo_perda=sumiu`.
- Cliente envia Pix divergente e Fernando recusa → Fernando registra `perdido [motivo]` pelo painel.
- Cliente cancela após Pix validado → modelo ou Fernando registram `perdido [motivo]`; bloqueio vinculado é cancelado se ainda não estiver `em_atendimento` nem `concluido`.

### 3.4 O que a IA não faz no fluxo externo

- Não confirma saída ao cliente sem Pix validado pelo pipeline ou por Fernando.
- Não envia mensagem confirmando o Pix validado — o handoff para a modelo é silencioso do ponto de vista da IA (§3.1, caminho A).
- Não interpreta conteúdo do comprovante por conta própria — pipeline OCR/vision é a porta única de validação automática.
- Não negocia valor de deslocamento (R$ 100 fixo no MVP).
- Não avalia segurança do bairro ou local — essa verificação é responsabilidade da modelo e de Fernando.

---

## 4. Tipologia de cliente e ajustes na conversa

A IA trata todos os clientes com o mesmo comportamento comercial. Não há score contínuo "fecha vs não fecha" no MVP (`02 §3.2`). O que muda é o tom, baseado em sinais objetivos do histórico **daquele par (cliente, modelo)**.

### 4.1 Histórico isolado por modelo

Cada modelo opera no próprio número de WhatsApp e tem **uma IA dedicada**, com persona e histórico próprios. Quando um mesmo cliente conversa com modelos diferentes (números diferentes), são instâncias completamente independentes:

- a IA da modelo A nunca acessa, cita ou se apoia no histórico do cliente com a modelo B;
- não existe "perfil único do cliente" usado por múltiplas IAs no MVP;
- cada conversa cliente↔modelo (`06 §2.6`) é a unidade que carrega histórico, recorrência e observações;
- recorrência é por par: cliente que voltou a falar com a modelo A é "recorrente" do ponto de vista de A, mesmo que nunca tenha falado com B.

Esta regra vale para todos os documentos do MVP que mencionarem "cliente recorrente", "histórico do cliente" ou "perfil do cliente".

### 4.2 Cliente novo

- Não há atendimento anterior **com esta modelo** registrado para o telefone do cliente (a conversa cliente↔modelo é nova ou nunca passou de `Triagem`).
- IA conduz triagem completa (saudação, qualificação, coleta de dados).
- Não assume histórico ou preferências.

### 4.3 Cliente recorrente (com a mesma modelo)

- Já houve atendimento(s) anterior(es) entre **este cliente e esta modelo**, registrados na mesma conversa.
- IA usa tom de retomada: saudação curta, evita repetir dados que já constam na conversa.
- IA não funde atendimento atual com atendimentos antigos no mesmo registro — cada atendimento é entidade separada na mesma conversa.
- IA nunca menciona, infere ou compara com atendimentos do cliente com outras modelos.

### 4.4 Sinais de cliente qualificado

A IA registra na extração os sinais objetivos definidos em `02 §2.2`:
- informa horário;
- informa local;
- aceita valor;
- envia Pix de deslocamento (saída);
- responde objetivamente.

Esses sinais alimentam o dashboard e podem orientar regras P1, mas no P0 não disparam comportamento diferenciado da IA.

---

## 5. Perda por timeout determinístico

Únicos caminhos de fechamento automático no P0. Cobrem cliente que para de responder e cliente do fluxo interno que avisou saída mas não chegou.

### 5.1 Timeout longo — silêncio pré-confirmação

- Cron worker (ARQ) percorre atendimentos em estados pré-confirmação (`Novo`, `Triagem`, `Qualificado`, `Aguardando_confirmacao`) sem mensagem do cliente há mais de **24 horas**.
- Marca como `Perdido` com `motivo_perda=sumiu` e `fonte_decisao=auto_timeout`.
- Cancela bloqueio de agenda vinculado se ainda não estiver `em_atendimento` nem `concluido`.
- Não envia mensagem para o cliente — apenas registra.

### 5.2 Timeout interno curto — saída sem chegada

- Aplica-se ao atendimento interno em `Aguardando_confirmacao` que tem `aviso_saida_em` registrado e ainda não recebeu foto de portaria.
- Quando passa **45 minutos do envio do Aviso de saída** sem foto recebida, coordenador marca `Perdido` com `motivo_perda=sumiu` e `fonte_decisao=auto_timeout_interno`.
- Cancela o bloqueio vinculado.
- **Não envia mensagem ao cliente** e **não pausa a IA** — `ia_pausada` continua `false`. Se o cliente voltar a falar depois, a próxima mensagem dispara um novo atendimento na regra de resolução determinística do coordenador (`03 §5.2`).

### 5.3 Exclusões

- Atendimentos com `ia_pausada=true` por escalada ou Pix em revisão **não** são afetados pelo timeout — Fernando ou modelo precisam agir manualmente.
- Atendimentos em `Confirmado` ou `Em_execucao` não entram no timeout (já houve confirmação ou modelo já está engajada; perda exige registro explícito).
- Atendimentos em `Fechado` ou `Perdido` ficam fora por estar fora dos estados-alvo.

### 5.4 Cadência do worker

Sugestão inicial: rodar a cada **5 minutos** para dar granularidade ao timeout curto de §5.2; o timeout longo de §5.1 é avaliado na mesma passada.

---

## 6. Mídia da modelo

Cobre como a IA decide enviar fotos/vídeos pré-aprovados durante a conversa.

### 6.1 Catálogo

- Mídia armazenada em MinIO no bucket `media`, vinculada à `modelo_id`.
- Mínimo de 10 mídias pré-aprovadas por modelo antes do piloto (`03 §4.5`).
- Cada mídia tem tipo (`foto`, `video`) e tag simples (`apresentacao`, `corpo`, `lifestyle`, `evento`).

### 6.2 Seleção pela IA

- IA chama `consultar_midia(tag)` para listar mídias disponíveis para uma tag.
- IA escolhe uma e chama `enviar_midia(midia_id, legenda?)` no turno corrente; pode chamar múltiplas vezes.
- Coordenador anexa as mídias à resposta do turno e Humanização (5.5) envia após o texto.

### 6.3 Limites no P0

- Sem ranking por contexto (P1).
- Sem métricas de uso/resposta por mídia (P1).
- Sem geração de mídia por IA (fora do MVP — `02 §3.2`).
- IA não envia mídia não cadastrada no MinIO; nunca encaminha foto recebida do cliente.

### 6.4 Mídia recebida do cliente

Comprovantes, foto de portaria e demais imagens entram em 5.1 vinculadas ao atendimento. No P0 a IA não interpreta conteúdo visual (`03 §5.3`); o pipeline OCR/vision do Pix é a única exceção, e roda fora da IA, em ARQ.

---

## 7. Agenda por áudio (P1)

Reservado para a IA Administrativa (`03 §5.6`). Fora do P0.

### 7.1 Comandos previstos em P1

- Bloquear horário: "bloqueia das 14 às 18 amanhã para Bia".
- Liberar horário: "libera o bloqueio das 20 de hoje".
- Consultar agenda: "como está a agenda da Bia hoje".
- Consultar comprovantes: "tem Pix pendente?".
- Registrar observação curta: "anota que a Bia avisou que não atende quarta-feira de manhã".

### 7.2 Princípios em P1

- IA Admin pede confirmação quando o comando for ambíguo.
- Não edita perfil, FAQ, política comercial ou mídia (essas operações ficam no painel, mesmo em P1 — `02 §3.2`).
- Toda ação registra autor, canal e horário.

### 7.3 Fora do escopo P0

No P0, qualquer bloqueio/liberação/consulta administrativa é feito pelo painel em `Agenda Operacional` (`03 §4.3`). A IA Admin não opera; o grupo IA Admin descrito em `CONTEXT.md` só é instanciado em P1.

---

## 8. Máquina de estados do atendimento

Estado canônico do atendimento no P0. Detalhamento dos estados em `03 §4.2`; este §8 documenta apenas as **transições** e suas fontes.

### 8.1 Estados

`Novo` → `Triagem` → `Qualificado` → `Aguardando_confirmacao` → `Confirmado` → `Em_execucao` → `Fechado` (sucesso) **ou** `Perdido` (em qualquer ponto até `Em_execucao`).

### 8.2 Tabela de transições

| De | Para | Disparo | Fonte |
|----|------|---------|-------|
| (criação) | `Novo` | Primeira mensagem do cliente, sem atendimento aberto reusável | Coordenador (5.2), determinístico |
| `Novo` | `Triagem` | IA registra extração com sinais mínimos de intenção | IA (5.3) via `registrar_extracao` |
| `Triagem` | `Qualificado` | IA registra extração com intenção real e dados mínimos | IA via `registrar_extracao` |
| `Qualificado` | `Aguardando_confirmacao` | IA define horário e tipo (interno cria bloqueio; externo dispara `pedir_pix_deslocamento`) | IA via tool |
| `Aguardando_confirmacao` | `Em_execucao` (interno) | Webhook recebe imagem em `Aguardando_confirmacao` interno → IA pausa (`modelo_em_atendimento`), card "cliente chegou" no grupo, bloqueio vai a `em_atendimento` | Coordenador (5.2), determinístico |
| `Aguardando_confirmacao` | `Confirmado` (externo) | Pipeline OCR valida Pix → `pix_status=validado` → IA pausa (`modelo_em_atendimento`), card "saída confirmada" no grupo | Pipeline (5.4 via `atualizar_pix`) |
| `Confirmado` | `Em_execucao` (externo) | Horário previsto chega e bloqueio vai a `em_atendimento` | Cron/coordenador, determinístico |
| `Em_execucao` | `Fechado` | Comando `fechado valor` ou `finalizado valor` | Modelo/Fernando via grupo ou painel |
| qualquer | `Perdido` | Comando `perdido motivo` | Modelo/Fernando via grupo ou painel |
| pré-confirmação | `Perdido` | Timeout determinístico longo de §5.1 (24 h sem mensagem do cliente) | Cron worker, `fonte_decisao=auto_timeout` |
| `Aguardando_confirmacao` (interno) | `Perdido` | Timeout interno curto de §5.2 (45 min do Aviso de saída sem foto) | Cron worker, `fonte_decisao=auto_timeout_interno` |
| `Aguardando_confirmacao` | (sem mudança) | Pix em revisão, aviso de saída, imagem fora do interno | Eventos colaterais; estado preserva |

### 8.3 Pix como sub-estado, não estado do atendimento

`pix_status` é campo do atendimento, não estado. Atendimento permanece em `Aguardando_confirmacao` enquanto `pix_status ∈ {aguardando, enviado, em_revisao}` (`03 §4.2`). Apenas `pix_status=validado` move para `Confirmado` no fluxo externo.

### 8.4 Bloqueio de agenda acompanha resultado

| Resultado do atendimento | Bloqueio vinculado |
|--------------------------|--------------------|
| `Fechado` | → `concluido` automaticamente |
| `Perdido` (antes de `em_atendimento`) | → `cancelado` automaticamente |
| `Perdido` (já em `em_atendimento` ou `concluido`) | preserva estado; correção exige confirmação manual de Fernando (`CONTEXT.md`) |

### 8.5 `ia_pausada` é flag, não estado

`ia_pausada=true` é flag ortogonal ao estado do atendimento. Pode coexistir com qualquer estado pré-fechamento. Casos canônicos no P0:
- `pix_em_revisao` (atendimento em `Aguardando_confirmacao`);
- `modelo_em_atendimento` (atendimento em `Em_execucao`);
- handoff explícito da IA para Fernando.

Devolução para IA libera `ia_pausada=false` e **não dispara turno automático**: a IA aguarda a próxima mensagem do cliente para responder (`05 §4`). Pix validado (§3.1) e foto de portaria (§2.1) **não devolvem para a IA** — escalam para a modelo e a IA permanece pausada com motivo `modelo_em_atendimento` até `finalizado` da modelo no grupo (encerra como `Fechado`) ou devolução manual de Fernando pelo painel.

---

## 9. Sinais transversais

### 9.1 `fonte_decisao`

Toda transição persistida grava `fonte_decisao` para auditoria. Valores no P0:

- `extracao_ia` — IA registrou extração e isso disparou transição (Novo→Triagem, Triagem→Qualificado, Qualificado→Aguardando_confirmacao);
- `webhook_imagem` — recebimento de imagem em `Aguardando_confirmacao` interno (foto de portaria → `Em_execucao`);
- `pipeline_pix` — pipeline OCR validou Pix (`Aguardando_confirmacao` → `Confirmado`);
- `comando_grupo` — comando da modelo ou Fernando no grupo de Coordenação por modelo;
- `painel_fernando` — ação de Fernando pelo painel;
- `auto_timeout` — timeout determinístico longo, §5.1 (24 h sem mensagem);
- `auto_timeout_interno` — timeout interno curto, §5.2 (45 min do Aviso de saída sem foto);
- `cron_em_execucao` — horário previsto disparou `Em_execucao` no fluxo externo.

P1 introduz `classificador_p1` para transições inferidas por LLM (`03 §5.7`) — não usado no P0.

### 9.2 Audit log

Cada transição relevante gera entrada na tabela `eventos` (ver `06-dados-interfaces.md` e `07 §2.2`). Checkpointer LangGraph não substitui este log — é registro humano-legível separado.

### 9.3 Mensagens durante `ia_pausada=true`

Persistidas em 5.1 sem indicador no painel, badge ou contador de não lidas. Servem apenas para histórico, resumo automático do próximo turno e auditoria. Não disparam transição.
