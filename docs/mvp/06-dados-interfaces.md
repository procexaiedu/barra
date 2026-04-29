# 06 — Dados e Interfaces

## 0. Hierarquia de IDs (grilling 29/04 §2.1)


| Conceito          | Chave                           | Vida útil                                      |
| ----------------- | ------------------------------- | ---------------------------------------------- |
| `cliente_id`      | Pessoa real                     | Permanente                                     |
| `conversation_id` | `(cliente_phone, modelo_phone)` | Permanente — sobrevive entre atendimentos      |
| `atendimento_id`  | Ciclo de tentativa de fechar    | Curto (horas/dias), encerra em Fechado/Perdido |


**1 atendimento = 1 ciclo de tentativa.** Cliente que volta dias depois = novo atendimento, mesmo cliente, mesma `conversation`.

### Memória em duas camadas (grilling §2.3)

1. **Curto prazo** — full history por `conversation_id`.
2. **Médio prazo** — bloco estruturado do CRM injetado no prompt como contexto interno (último atendimento, status, motivos, observações Fernando). **Marcado como "nunca verbalizar"**.

### Identificação de cliente recorrente (grilling §2.2)

- Match primário por número WhatsApp.

---

## 1. Entidades de Dados

### 1.1 Profissional / Modelo


| Campo             | Tipo   | Observação                            |
| ----------------- | ------ | ------------------------------------- |
| id                | string | Identificador único                   |
| nome              | string | Nome operacional                      |
| status            | enum   | ativa, inativa, indisponível          |
| descrição interna | texto  | Informação visível apenas para equipe |
| horários padrão   | lista  | Disponibilidade base                  |
| observações       | texto  | Informações operacionais              |


**Entidades complementares (grilling §5):**

#### `modelo_perfil`


| Campo                | Tipo   | Observação                                                                                                                   |
| -------------------- | ------ | ---------------------------------------------------------------------------------------------------------------------------- |
| persona              | objeto | Estilo, atributos, tom                                                                                                       |
| localizacao          | objeto | Bairro, ponto de referência                                                                                                  |
| comercial            | objeto | Inclui `chave_pix`, `nome_titular_chave`, valor padrão e percentual opcional de repasse da agência                           |
| disponibilidade_base | objeto | Janelas típicas                                                                                                              |
| restricoes           | lista  | Restrições aprendidas no piloto                                                                                              |
| servicos             | flags  | `interno_apto`, `saida_residencia`, `saida_motel`, `saida_evento`, `pernoite` etc. (booleanos/enums; **IA nunca verbaliza**) |


#### `modelo_midia`


| Campo                        | Tipo     | Observação                                                                  |
| ---------------------------- | -------- | --------------------------------------------------------------------------- |
| id                           | string   | Identificador único                                                         |
| modelo_id                    | string   | Relação                                                                     |
| tipo                         | enum     | foto / vídeo                                                                |
| tags                         | lista    | rosto, corpo, vídeo curto etc.                                              |
| caminho_storage              | string   | **MinIO desde o MVP**                                                       |
| aprovada                     | boolean  | Pré-aprovada para envio pela IA                                             |
| visualizacao_unica_preferida | boolean  | Para vídeos que devem ser enviados como visualização única quando suportado |
| criada_em                    | datetime | Automático                                                                  |


#### `atendimento_midia_cliente`


| Campo           | Tipo     | Observação                                     |
| --------------- | -------- | ---------------------------------------------- |
| id              | string   | Identificador único                            |
| atendimento_id  | string   | Relação com o atendimento                      |
| tipo            | enum     | comprovante_pix / foto_portaria / outro        |
| caminho_storage | string   | MinIO                                          |
| retencao_ate    | datetime | 30 dias por padrão, salvo disputa ou auditoria |
| criada_em       | datetime | Automático                                     |


#### `modelo_faq`


| Campo             | Tipo  | Observação                             |
| ----------------- | ----- | -------------------------------------- |
| pergunta_canonica | texto | Forma normalizada da pergunta          |
| resposta_modelo   | texto | Resposta específica desta modelo       |
| resposta_global   | texto | Resposta default da agência (fallback) |
| *recuperação*     |       | Por embedding                          |


#### `modelo_perfil_log`

Audit trail simples: timestamp + origem da mudança. **Sem versionamento completo no MVP.**

---

### 1.2 Cliente


| Campo             | Tipo     | Observação                                     |
| ----------------- | -------- | ---------------------------------------------- |
| id (`cliente_id`) | string   | Identificador único permanente                 |
| nome              | string   | Se informado                                   |
| telefone/canal    | string   | Match primário para reidentificação            |
| origem            | string   | Canal de entrada                               |
| primeiro_contato  | datetime | Automático                                     |
| ultimo_contato    | datetime | Automático                                     |
| status            | enum     | novo, qualificado, fechado, perdido |
| tags              | lista    | Segmentação futura                             |
| observações       | texto    | Campo interno                                  |


---

### 1.3 Atendimento


| Campo                      | Tipo          | Observação                                                                                                                                                                |
| -------------------------- | ------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| id (`atendimento_id`)      | string        | 1 atendimento = 1 ciclo de tentativa; cliente que volta = novo `atendimento_id`                                                                                           |
| `conversation_id`          | string        | `(cliente_phone, modelo_phone)`; permanente, sobrevive entre atendimentos                                                                                                 |
| cliente_id                 | string        | Relaciona com cliente                                                                                                                                                     |
| profissional_id            | string        | Relaciona com profissional                                                                                                                                                |
| status                     | enum          | `Novo`, `Triagem`, `Qualificado`, `Aguardando_confirmacao`, `Confirmado`, `Em_execucao`, `Fechado`, `Perdido`                                                              |
| tipo                       | enum          | interno, externo, indefinido                                                                                                                                              |
| horario_desejado           | datetime/null | Extraído da conversa                                                                                                                                                      |
| pix_status                 | enum          | `nao_solicitado`, `aguardando`, `enviado`, `em_revisao`, `validado`, `invalido`; revisão de Pix não muda `status` do atendimento                                         |
| responsavel                | enum          | `IA`, `Fernando/equipe`, `modelo`, `operador_autorizado`, `vendedor_read_only`                                                                                            |
| motivo_escalada            | string/null   | Quando houver                                                                                                                                                             |
| ia_pausada                 | boolean       | `true` quando houve handoff; bloqueia resposta automática da IA, mas não bloqueia registro de mensagens                                                                   |
| devolvido_para_ia_por      | string/null   | Identificador de Fernando, modelo ou operador que executou a devolução                                                                                                    |
| devolvido_para_ia_em       | datetime/null | Quando a IA foi reativada após handoff                                                                                                                                    |
| devolvido_para_ia_canal    | enum/null     | painel, grupo_coordenação, IA_Admin                                                                                                                                       |
| resultado                  | enum          | em andamento, fechado, perdido                                                                                                                                            |
| valor_final                | decimal/null  | Obrigatório para `resultado=fechado`; valor total bruto pago pelo cliente                                                                                                 |
| percentual_repasse_agencia | decimal/null  | Snapshot opcional do percentual acordado da modelo no momento do fechamento, quando cadastrado                                                                            |
| valor_repasse_agencia      | decimal/null  | Calculado quando `percentual_repasse_agencia` existir; não é o valor informado no comando `fechado`                                                                       |
| motivo_perda               | enum/null     | `preco`, `sumiu`, `risco`, `indisponibilidade`, `fora_de_area`, `outro`                                                                                                   |
| motivo_perda_observacao    | texto/null    | Obrigatório quando `motivo_perda=outro`; opcional nos demais motivos                                                                                                      |
| resultado_registrado_por   | string/null   | Fernando ou modelo que registrou fechado/perdido durante handoff; no painel, sempre Fernando no MVP                                                                       |
| resultado_registrado_em    | datetime/null | Quando o resultado foi registrado                                                                                                                                         |
| resultado_registrado_canal | enum/null     | painel, grupo_coordenação, IA_Admin, automacao                                                                                                                            |
| resultado_corrigido_por    | string/null   | Fernando, quando corrigir resultado/valor/motivo pelo painel                                                                                                              |
| resultado_corrigido_em     | datetime/null | Quando a correção foi feita                                                                                                                                               |
| resultado_correcao_motivo  | texto/null    | Observação curta da correção, quando informada                                                                                                                            |
| correcao_agenda_confirmada | boolean/null  | `true` quando Fernando confirmou alteração de bloqueio já `em_atendimento` ou `concluido`                                                                                 |
| resumo                     | texto         | Gerado pela IA                                                                                                                                                            |
| **fonte_decisao**          | enum          | P0: `modelo`, `fernando`, `sistema`, `auto_timeout`, `fernando_revisado`; P1 adiciona `classificador_alta`, `classificador_media`                                         |
| criado_em                  | datetime      | Automático                                                                                                                                                                |
| atualizado_em              | datetime      | Automático                                                                                                                                                                |


---

#### Mensagens da conversa

Toda mensagem recebida pelo webhook deve ser persistida, mesmo com `ia_pausada=true`.


| Campo           | Tipo        | Observação                              |
| --------------- | ----------- | --------------------------------------- |
| atendimento_id  | string/null | Vincula ao ciclo atual quando houver    |
| conversation_id | string      | Conversa permanente cliente-modelo      |
| direcao         | enum        | cliente, IA, modelo_manual              |
| from_me         | boolean     | Valor bruto do canal para auditoria     |
| conteudo        | texto/json  | Texto ou referência ao payload de mídia |
| criada_em       | datetime    | Timestamp do canal                      |


Mensagens `modelo_manual` e novas mensagens do cliente entram no histórico e no resumo posterior, mas não disparam resposta automática, alerta de grupo, badge, contador de não lidas, destaque no painel ou transição automática de estado enquanto `ia_pausada=true`.

No P0, a IA pode preencher campos estruturados, gerar resumos, detectar alertas e aplicar timeout determinístico antes da confirmação. Ela não infere `Fechado`, perda pós-confirmação ou transições sensíveis por classificador. Resultado final vem de registro explícito de Fernando ou da modelo, conforme `05-escalada-regras-ia.md`.

As regras de comando, confirmação e validação de `fechado`/`perdido` ficam em `05-escalada-regras-ia.md`. Este documento define os efeitos persistidos: `valor_final` é obrigatório para fechamento; ao fechar, o sistema copia o percentual vigente da modelo quando cadastrado e calcula `valor_repasse_agencia`; sem percentual cadastrado, o fechamento é permitido e os campos de repasse ficam nulos. Mudanças futuras no cadastro da modelo não recalculam atendimentos antigos. Motivo livre não mapeado vira `motivo_perda=outro` com `motivo_perda_observacao`.

Correções feitas por Fernando no painel recalculam campos financeiros e ajustam apenas o bloqueio de agenda vinculado. Correção para `fechado` move o bloqueio vinculado para `concluido`. Correção para `perdido` move para `cancelado` somente se o bloqueio ainda não estiver `em_atendimento` nem `concluido`; se estiver, o painel exige confirmação explícita antes de alterar a agenda.

### 1.4 Bloqueio de Agenda


| Campo           | Tipo        | Observação                                                  |
| --------------- | ----------- | ----------------------------------------------------------- |
| id              | string      | Identificador único                                         |
| profissional_id | string      | Profissional associada                                      |
| inicio          | datetime    | Início do bloqueio                                          |
| fim             | datetime    | Fim do bloqueio                                             |
| status          | enum        | sinalizado, bloqueado, em_atendimento, concluido, cancelado |
| origem          | enum        | manual, IA administrativa, atendimento, ajuste operacional  |
| atendimento_id  | string/null | Se vinculado a atendimento                                  |
| observação      | texto       | Campo interno                                               |


Quando um atendimento vinculado a bloqueio recebe `resultado=fechado`, o bloqueio correspondente muda automaticamente para `concluido`.

Quando recebe `resultado=perdido`, o bloqueio correspondente muda automaticamente para `cancelado` somente se o status atual ainda não for `em_atendimento` nem `concluido`.

Bloqueios sem `atendimento_id` ou vinculados a outro atendimento não são alterados.

---

## 2. Requisitos de Interface

### 2.1 Tela: Painel Geral

Deve mostrar:

- atendimentos abertos;
- atendimentos que aguardam intervenção fora da IA;
- destaque separado para `decisão Fernando/equipe` e `ação operacional da modelo`;
- motivo do destaque, responsável atual, tempo aguardando e próxima ação esperada;
- profissionais disponíveis;
- horários bloqueados;
- fechamentos do dia;
- perdas do dia;
- alertas importantes.

---

### 2.2 Tela: Central de Atendimentos

Deve permitir:

- visualizar conversas;
- filtrar por status;
- filtrar por profissional;
- filtrar por responsável;
- assumir atendimento;
- devolver atendimento para IA explicitamente com botão `Devolver para IA`;
- marcar como fechado;
- marcar como perdido com motivo quando conhecido;
- registrar observações;
- ver resumo da IA.

---

### 2.3 Tela: Agenda

Deve permitir:

- visualizar dia atual;
- selecionar profissional;
- criar bloqueio;
- liberar horário;
- ver conflitos;
- identificar origem de cada bloqueio;
- consultar disponibilidade rapidamente.

---

### 2.4 Tela: CRM

Deve permitir:

- buscar cliente;
- ver histórico;
- ver status comercial;
- ver atendimentos anteriores;
- adicionar tags em P1;
- registrar observações;

### 2.4.1 Tela: Modelo (perfil + base de conhecimento)

Decisão do grilling 29/04 — o painel é a interface estável (a IA Admin **não** edita perfil). Deve permitir:

- editar `modelo_perfil` (persona, localização, comercial — incluindo `chave_pix` e `nome_titular_chave`, disponibilidade base, restrições);
- gerenciar `modelo_midia` (upload, tags, aprovação) — armazenado em **MinIO**;
- gerenciar `modelo_faq` (pergunta canônica, resposta da modelo, resposta global);
- ver `modelo_perfil_log` (audit trail simples);
- **conectar WhatsApp da modelo via QR code** — gerar QR code no painel para a modelo escanear no celular dela e vincular o número ao Evolution.

---

### 2.5 Tela: Dashboard

Deve mostrar:

- volume de atendimentos;
- conversão;
- perdas;
- horários de pico;
- profissionais mais procuradas;
- motivos de perda;
- quantidade de escaladas;
- tempo médio de primeira resposta;
- **filtro por `fonte_decisao`** em P1 (`classificador_alta`, `classificador_media`, `auto_timeout`, `fernando_revisado`) para Fernando revisar amostras.
