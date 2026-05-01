# 03 - Módulos do Sistema

Este documento define quais módulos compõem o sistema, qual é a responsabilidade de cada um e onde ficam as fronteiras entre produto, dados e operação.

Ele não deve descrever fluxos passo a passo, regras detalhadas de conversa, modelagem completa de banco, decisões históricas ou critérios de roadmap. Esses assuntos pertencem aos documentos específicos de fluxo, escalada, dados, decisões e execução.

## 2. Camadas do Sistema

### 2.1 Produto e Operação

Camada usada por Fernando para acompanhar, revisar e operar o atendimento.

Inclui:

- Painel Geral;
- Central de Atendimentos;
- Agenda Operacional;
- CRM;
- Modelos e Base de Conhecimento;
- Pix e Comprovantes;
- Dashboard.

### 2.2 Dados

Camada de persistência e fonte de verdade operacional.

Inclui:

- clientes;
- conversas;
- mensagens;
- atendimentos;
- modelos;
- perfil e FAQ da modelo;
- mídia da modelo;
- bloqueios de agenda;
- comprovantes Pix;
- alertas;
- escaladas;
- logs e auditoria.

### 2.3 Serviços Operacionais e IA

Camada que recebe eventos, consulta dados, executa regras e grava decisões.

Inclui:

- Webhook de WhatsApp/Evolution;
- Coordenador de Turno;
- IA de Atendimento;
- Escaladas e Alertas;
- Humanização de envio;
- IA Administrativa em P1;
- Classificador e Auditoria em P1.

---

## 3. Mapa de Módulos

### Telas do painel (visíveis para Fernando)


| Módulo                         | Responsável |
| ------------------------------ | ----------- |
| Painel Geral                   | Fernando    |
| Central de Atendimentos        | Fernando    |
| Agenda Operacional             | Fernando    |
| CRM                            | Fernando    |
| Modelos e Base de Conhecimento | Fernando    |
| Pix e Comprovantes             | Fernando    |
| Dashboard                      | Fernando    |


### Serviços (rodam nos bastidores, sem tela)


| Módulo                          | Responsável                 |
| ------------------------------- | --------------------------- |
| Webhook e Coordenador de Turno  | Sistema                     |
| IA de Atendimento               | Sistema                     |
| Escaladas e Alertas             | Sistema / Fernando / modelo |
| Humanização de Envio            | Sistema                     |
| Conversas e Mensagens           | Sistema                     |


### P1 — fora do MVP


| Módulo                    | Tipo    | Responsável        |
| ------------------------- | ------- | ------------------ |
| IA Administrativa         | Serviço | Fernando           |
| Classificador e Auditoria | Serviço | Sistema / Fernando |


---

## 4. Módulos de Produto

### 4.1 Painel Geral

#### Objetivo

Dar uma visão operacional rápida do dia.

#### Responsabilidades

- mostrar atendimentos abertos;
- destacar atendimentos com `ia_pausada=true`; em P0 os três motivos que ativam `ia_pausada` são `pix_em_revisao`, `modelo_em_atendimento` (foto de portaria recebida no interno ou Pix validado no externo) e `handoff_ia` (escalada explícita da IA para Fernando via tool `escalar`);
- separar os destaques por tipo:
  - `pix_em_revisao`: Fernando valida ou recusa pelo painel;
  - `handoff_ia`: a IA escalou para Fernando (risco, política comercial, conflito de agenda, dúvida operacional ou exaustão de iterações); Fernando lê o card e age via grupo ou painel;
  - `modelo_em_atendimento`: a modelo está conduzindo o atendimento (interno após foto de portaria → `Em_execucao`, ou externo após Pix validado → `Confirmado`); Fernando monitora — a modelo já foi notificada pelo grupo de coordenação; o painel indica quando o tempo previsto do serviço expirou e oferece o botão `Devolver para IA`;
- exibir motivo do destaque, responsável atual e próxima ação esperada (gerados pela IA no handoff);
- mostrar agenda do dia;
- mostrar bloqueios ativos;
- mostrar Pix pendentes de validação;
- mostrar fechamentos e perdas do dia;
- permitir acesso rápido aos módulos operacionais.

#### Não é responsabilidade

- decidir fluxo de conversa;
- validar Pix automaticamente;
- alterar histórico bruto de mensagens;
- substituir a Central de Atendimentos;
- funcionar como fila genérica de prioridade ou score de cliente.

---

### 4.2 Central de Atendimentos

#### Objetivo

Centralizar os ciclos comerciais em andamento e permitir operação assistida.

#### Responsabilidades

- listar atendimentos abertos;
- exibir status atual do atendimento;
- exibir cliente, canal, modelo de interesse e tipo de atendimento;
- exibir urgência: `imediato`, `agendado`, `indefinido` ou `estimado`;
- exibir motivo de escalada, motivo de perda e resumo operacional;
- permitir registro de fechado/perdido conforme as regras canônicas de comando e correção definidas em `05-escalada-regras-ia.md`;
- oferecer botão `Devolver para IA` para atendimentos em handoff que podem retornar à condução automática da IA.

#### Não é responsabilidade

- guardar a lógica completa dos fluxos;
- inferir fechamento automaticamente no P0;
- executar regra de Pix sozinha;
- editar conteúdo bruto das mensagens.

#### Estados P0


| Estado                   | Significado                                                                       |
| ------------------------ | --------------------------------------------------------------------------------- |
| `Novo`                   | Primeiro contato recebido                                                         |
| `Triagem`                | IA coletando intenção e dados mínimos                                             |
| `Qualificado`            | Cliente demonstrou intenção real                                                  |
| `Aguardando_confirmacao` | IA aguarda Pix de deslocamento (externo) ou foto de portaria (interno); aviso de saída do cliente é evento informativo e não muda estado |
| `Confirmado`             | Pix de deslocamento validado no fluxo externo; IA pausada (`modelo_em_atendimento`) e modelo conduz a partir daqui                       |
| `Em_execucao`            | Modelo engajada operacionalmente: foto de portaria recebida (interno, entrada direta) ou horário previsto chegou (externo)               |
| `Fechado`                | Atendimento convertido por registro explícito                                     |
| `Perdido`                | Atendimento não converteu por registro explícito ou timeout determinístico        |


Estados inferidos ou mais granulares ficam fora do P0. Revisão de Pix não é estado do atendimento; fica em `pix_status=em_revisao` enquanto o atendimento permanece em `Aguardando_confirmacao`.

---

### 4.3 Agenda Operacional

#### Objetivo

Controlar disponibilidade da modelo piloto e evitar conflitos de horário.

#### Responsabilidades

- criar bloqueios manuais;
- liberar horários;
- consultar disponibilidade;
- registrar origem do bloqueio;
- apontar conflitos;
- vincular bloqueio a atendimento quando aplicável;
- marcar automaticamente como `concluido` o bloqueio vinculado ao atendimento quando o resultado for registrado como fechado;
- marcar automaticamente como `cancelado` o bloqueio vinculado ao atendimento quando o resultado for registrado como perdido, desde que o bloqueio ainda não esteja `em_atendimento` nem `concluido`;
- permitir observação operacional curta.

#### Não é responsabilidade

- decidir se uma saída é segura;
- substituir validação de Fernando;
- executar agenda por áudio no P0;
- bloquear horário externo apenas com Pix recebido.

#### Estados de agenda


| Estado           | Significado                       |
| ---------------- | --------------------------------- |
| `bloqueado`      | Horário reservado ou indisponível |
| `em_atendimento` | Modelo em atendimento             |
| `concluido`      | Bloqueio encerrado                |
| `cancelado`      | Bloqueio cancelado                |


---

### 4.4 CRM

#### Objetivo

Transformar conversas em histórico comercial consultável.

#### Responsabilidades

- registrar cliente e telefone/canal;
- registrar origem padrão do lead;
- registrar modelo de interesse;
- identificar cliente pelo telefone (entidade global) e calcular recorrência **por par (cliente, modelo)** com base no histórico da conversa atual; cada modelo tem IA e histórico isolados (`04 §4.1`);
- registrar motivo de perda padronizado (`preco`, `sumiu`, `risco`, `indisponibilidade`, `fora_de_area`, `outro`) ao encerrar atendimento como Perdido;
- registrar observações internas em texto livre, incluindo objeções capturadas durante a conversa;
- expor histórico resumido para operação e IA.

#### Não é responsabilidade

- importar a base antiga de 15.000 contatos no P0;
- fazer remarketing;
- unificar cliente automaticamente;
- criar score contínuo de “fecha vs não fecha”;
- manter tags avançadas no P0.

---

### 4.5 Modelos e Base de Conhecimento

#### Objetivo

Concentrar as informações autorizadas que a IA pode usar sobre a modelo piloto.

#### Responsabilidades

- cadastrar modelo piloto;
- manter nome operacional, status e disponibilidade base;
- manter persona, localização operacional e dados comerciais;
- manter valor padrão, percentual opcional de repasse da agência e política comercial autorizada;
- manter FAQ operacional;
- manter uma base global inicial de 20 a 30 FAQs revisadas por Fernando, com especialização por modelo apenas quando houver diferença real;
- manter restrições e respostas permitidas;
- registrar chave Pix e titular quando necessário para saída;
- armazenar mídia pré-aprovada em MinIO (mínimo 10 por modelo antes do piloto);
- marcar mídia aprovada;
- classificar por tipo e tag simples;
- permitir seleção simples pela IA a partir de tag.

#### Responsabilidades P1

- ranking de mídia por contexto da conversa;
- biblioteca completa com curadoria avançada;
- métricas de uso e resposta por mídia;
- gestão avançada de tags.

#### Não é responsabilidade

- permitir que IA Admin edite perfil no MVP;
- verbalizar termos explícitos para o cliente;
- gerenciar múltiplas modelos em escala no P0.

---

### 4.6 Pix e Comprovantes

#### Objetivo

Registrar Pix de deslocamento em saída, validar automaticamente quando todas as checagens passarem e encaminhar exceções para Fernando.

#### Responsabilidades P0

- registrar que Pix de deslocamento foi solicitado;
- registrar comprovante enviado pelo cliente;
- manter status do Pix;
- validar comprovante por OCR/vision com checagem de beneficiário, chave, valor, timestamp e plausibilidade visual;
- confirmar automaticamente quando todas as checagens passarem;
- escalar Fernando quando qualquer checagem falhar ou ficar duvidosa;
- registrar decisão de Fernando;

#### Não é responsabilidade P0

- aceitar comprovante com qualquer divergência;
- bloquear agenda automaticamente apenas com comprovante recebido;
- substituir avaliação de risco/local feita por Fernando.

#### Estados de Pix


| Estado           | Significado                  |
| ---------------- | ---------------------------- |
| `nao_solicitado` | Pix não faz parte do fluxo   |
| `aguardando`     | IA pediu Pix de deslocamento |
| `enviado`        | Cliente enviou comprovante   |
| `em_revisao`     | Aguardando Fernando          |
| `validado`       | Pipeline ou Fernando validou |
| `invalido`       | Recusado por Fernando        |


---

### 4.7 Dashboard

#### Objetivo

Dar visão gerencial simples da operação piloto.

#### Responsabilidades P0

- mostrar volume de atendimentos;
- mostrar atendimentos por estado, incluindo `Qualificado`, `Fechado` e `Perdido`;
- mostrar taxa de conversão;
- mostrar fechamentos;
- mostrar perdas;
- mostrar motivos de perda;
- mostrar profissionais mais procuradas;
- mostrar Pix em revisão;
- mostrar atendimentos escalados;

#### Não é responsabilidade P0

- auditoria detalhada de classificador;
- análise avançada de conversas;
- métricas complexas por vendedor;
- relatórios de remarketing.

---

## 5. Módulos Operacionais

> **Nota de nomenclatura.** "Coordenador de Turno" (5.2) gerencia o ciclo de processamento de uma mensagem; "orquestrador de agentes" (LangGraph), interno à IA de Atendimento (5.3), gerencia o loop ReAct. Os termos não são intercambiáveis.

### 5.1 Conversas e Mensagens

#### Objetivo

Persistir o histórico bruto e disponibilizar mensagens ao Coordenador de Turno.

#### Responsabilidades

- persistir mensagem bruta (texto/imagem/áudio) quando invocado pelo Coordenador de Turno, antes de qualquer decisão operacional;
- criar ou atualizar conversa;
- enfileirar job de transcrição de áudio (ARQ) e gravar a transcrição quando concluída;
- aceitar atualização posterior de `atendimento_id` na mensagem/mídia depois que o coordenador resolver/criar o atendimento;
- persistir mensagens da modelo e do cliente mesmo quando `ia_pausada=true`;
- ao gravar mensagem nova do cliente com `ia_pausada=true`, marcar como já consumida (sem badge, sem contador de não lidas, sem destaque no painel);
- preservar histórico sem edição manual.

#### Mídia do Cliente

Comprovantes, foto de portaria e demais imagens enviadas pelo cliente ficam vinculadas ao atendimento. Política de retenção fora do escopo do MVP.

#### Não é responsabilidade

- receber webhook do Evolution diretamente (entrada é via 5.2);
- decidir resposta da IA;
- classificar cliente;
- editar conteúdo de conversa;
- resolver conflitos de atendimento.

---

### 5.2 Webhook e Coordenador de Turno

#### Objetivo

Receber eventos do Evolution, gerenciar o ciclo de processamento de cada mensagem e coordenar os demais módulos.

#### Responsabilidades

- expor o endpoint HTTP que recebe webhook do Evolution e validar payload;
- invocar 5.1 para persistir a mensagem bruta;
- aplicar **debounce de entrada** (~3–5s, configurável): aguarda novas mensagens picotadas do cliente antes de disparar turno; se chegar nova, reinicia janela;
- adquirir lock de conversa (`lock:conv:{conversa_id}`, Redis SETNX, TTL 15s); mensagens entrantes durante lock vão para `pending:conv:{conversa_id}`;
- identificar cliente, conversa e atendimento de forma **determinística**: reusa atendimento aberto para `(cliente_id, modelo_id)` cujo estado ∉ {`Fechado`, `Perdido`}; senão cria novo em `Novo`. Sem LLM nesta etapa;
- vincular mensagem persistida ao `atendimento_id` resolvido;
- montar contexto operacional em **dois blocos**:
  - **estático (cacheável via `cache_control` Anthropic):** persona, restrições, regras de domínio fixas, catálogo descritivo das tools, FAQ, valor padrão e política comercial;
  - **dinâmico (`messages`):** histórico recente, atendimento atual, cliente, agenda resumida das próximas 48h, status de Pix se aplicável;
- chamar IA de Atendimento (5.3) **uma vez por turno**;
- persistir extração estruturada retornada via tool `registrar_extracao`;
- delegar comandos operacionais (vindos do grupo de Coordenação por modelo ou do painel) ao módulo 5.4, que é a porta única;
- entregar a resposta da IA (`[texto, lista_de_midias]`) à Humanização de Envio (5.5) e liberar o lock após enfileirar; drenar `pending:conv:{conversa_id}` antes de soltar;
- não chamar a IA para responder quando `ia_pausada=true`;
- **não disparar turno automático** após devolução para IA — espera próxima mensagem do cliente. Pix validado e foto de portaria recebida não devolvem para a IA — escalam para a modelo (5.4); a IA só volta a atender quando a modelo registra `finalizado` (encerra como `Fechado` e libera `ia_pausada=false`) ou Fernando devolve manualmente.

#### Não é responsabilidade

- conter regra detalhada de conversa;
- parsear comandos do grupo (delegado a 5.4);
- decidir exceções de risco;
- validar Pix sozinho.

---

### 5.3 IA de Atendimento

#### Objetivo

Conduzir o atendimento previsível dentro da persona autorizada, como agente ReAct com tools.

#### Arquitetura

Agente **ReAct single-thread** com tools, implementado em LangGraph 0.4 sobre Anthropic Claude. O agente alterna iterações de raciocínio (LLM call) e ação (tool call) até decidir responder. Single-agent no P0; supervisor + sub-agentes ficam como porta aberta P1, sem mudança na interface 5.2 ↔ 5.3.

#### Catálogo de tools (P0)

**Leitura (sem efeito colateral):**

- `consultar_agenda(data_inicio, data_fim)` — bloqueios + janelas livres da modelo;
- `consultar_cliente(telefone)` — dados do par (cliente, modelo) atual no CRM (novo/recorrente nesta conversa, observações desta conversa, último motivo de perda do cliente com esta modelo); IA não acessa histórico de outras modelos (`04 §4.1`);
- `consultar_faq(query)` — busca na FAQ da modelo;
- `consultar_pix_status(atendimento_id)` — estado atual do Pix do atendimento corrente;
- `consultar_midia(tag)` — lista mídias pré-aprovadas para a tag.

**Escrita / efeito operacional:**

- `registrar_extracao(intencao, urgencia, tipo_atendimento, motivo_perda_candidato?, valor_sinalizado?, proxima_acao_esperada)` — uma vez por turno;
- `pedir_pix_deslocamento(valor, chave_pix, titular)` — solicita Pix; coordenador atualiza `pix_status=aguardando` e atendimento → `Aguardando_confirmacao`;
- `escalar(responsavel, motivo, resumo_operacional, acao_esperada)` — única porta de handoff; envia card no grupo de Coordenação por modelo e ativa `ia_pausada=true`. `responsavel ∈ {Fernando, modelo}`; canal e efeito de pausa são os mesmos;
- `enviar_midia(midia_id, legenda?)` — anexa mídia pré-aprovada à resposta do turno corrente; pode ser chamada múltiplas vezes.

Tools são **funções síncronas** no processo do coordenador. Tools de escrita são idempotentes via `turno_id`.

#### Saída do turno

- A IA encerra o turno emitindo **text content** ao final da iteração corrente, sem tool terminal;
- O coordenador captura `[texto, lista_de_midias]` para entregar à Humanização (5.5);
- Quando `escalar` é chamada, **o turno encerra imediatamente**: text content emitido na mesma iteração ou em iterações posteriores é descartado, e a IA não é convocada novamente. Do ponto de vista do cliente, a conversa simplesmente para; a próxima mensagem virá da modelo (manual no mesmo número via Coordenação por modelo) ou — para sair da pausa — de evento de devolução para IA (`05 §4`). Pix validado (externo) e foto de portaria (interno) pausam a IA pelo mesmo mecanismo de `ia_pausada=true` (motivo `modelo_em_atendimento`) sem passar por `escalar`, e a IA só volta a atender após `finalizado` da modelo ou devolução manual.

#### Limites e checkpoint

- Teto de **10 iterações** por turno. Critério de fim: (a) text content sem nova tool call, (b) `escalar` (turno aborta), (c) exaustão (escala automaticamente, sem mensagem ao cliente);
- `AsyncPostgresSaver` grava checkpoint **ao fim de cada turno completo**; iterações intermediárias ficam apenas no LangSmith.

#### System prompt

Ordem fixa, marcada com `cache_control`:

1. Persona da modelo;
2. Restrições e respostas permitidas;
3. Regras de domínio fixas (sequência de confirmação interna, regra de Pix, vedações);
4. Catálogo descritivo das tools (quando usar cada uma);
5. FAQ da modelo;
6. Valor padrão e política comercial.

Inclui regra explícita: *ao chamar `escalar`, parar — não tentar despedir-se nem comentar a escalada*. Mudança em qualquer item invalida o cache da modelo afetada.

#### Pré-carregado vs lazy via tool

Pré-carregado no contexto: o que é usado em ≥80% dos turnos (estado do atendimento, resumo do cliente, agenda das próximas 48h). Tools cobrem o resto (datas distantes, FAQ por busca, mídia por tag, status detalhado de Pix).

#### Modalidade de mensagem entrante

Metadado por mensagem: `texto`, `audio` (texto transcrito + nota `(originalmente áudio, X segundos)`), `imagem` (URL + classificação prévia se houver). No P0 a IA não interpreta imagem; reage ao estado do atendimento, não ao conteúdo visual.

#### Cliente recorrente

A IA usa o status de recorrência **da conversa atual com esta modelo** (do CRM) para tom (saudação, evitar repetir dados). Cada modelo tem IA e histórico isolados (`04 §4.1`); a IA nunca acessa, cita ou se apoia no histórico do cliente com outra modelo. Atendimentos antigos da mesma conversa não são fundidos com o atual.

#### Não é responsabilidade

- criar atendimento (responsabilidade determinística do coordenador);
- decidir risco ou local de saída;
- negociar exceções complexas;
- confirmar saída sem Pix validado;
- verbalizar serviços explícitos;
- inventar dados;
- reengajar cliente silencioso no P0.

---

### 5.4 Escaladas e Alertas

#### Objetivo

Centralizar a aplicação de comandos operacionais (de qualquer origem) e o ciclo de pausa/devolução da IA.

#### Porta única

Função `aplicar_comando(origem, autor, atendimento_id?, comando, payload)` chamada por **quatro fontes**:

- **agente** — tool `escalar` da IA (5.3) → `abrir_handoff`;
- **grupo_coordenacao** — texto/quote no grupo, parseado pelo módulo;
- **painel** — REST de Fernando;
- **pipeline_pix** — pipeline OCR (4.6/5.6) → `atualizar_pix`.

Nenhum outro módulo escreve diretamente em `ia_pausada`, estado de atendimento, agenda vinculada ou financeiro decorrente de comando.

#### Comandos canônicos (P0)

- `abrir_handoff(responsavel, motivo, resumo, acao_esperada)` — pausa IA, cria card no grupo, registra alerta;
- `atualizar_pix(atendimento_id, status, motivo?)` — `status ∈ {em_revisao, validado, recusado}`; cuida de `ia_pausada` e estado do atendimento conforme o status;
- `devolver_para_ia(atendimento_id)` — libera `ia_pausada=false`, registra autor/canal/horário, **não dispara turno**;
- `registrar_fechado(atendimento_id, valor, corrigindo?)` — estado → `Fechado`, bloqueio vinculado → `concluido`, registra financeiro;
- `registrar_perdido(atendimento_id, motivo, observacao?)` — motivo ∈ `{preco, sumiu, risco, indisponibilidade, fora_de_area, outro}`; cancela bloqueio se ainda não estiver `em_atendimento` ou `concluido`.

Comando inválido (campo faltando, taxonomia errada, `#N` ambíguo) responde com erro curto no canal de origem e **não altera estado**.

Sintaxe canônica do grupo (parser interno): `IA assume [#N]`, `finalizado [valor] [#N]`, `fechado [valor] #N`, `perdido [motivo] [obs?] #N`. Sem `#N` exige ser quote ao card. Detalhamento e exemplos em `05-escalada-regras-ia.md`.

#### Cards e confirmações no grupo

Enviados **direto pelo Evolution** (bypass de 5.5 — sem necessidade de cadência humanizada). Persistidos em 5.1 com `tipo=card|confirmacao` para auditoria.

#### Pix validado escala para a modelo

`pix_validado` aplica três efeitos atômicos: card "saída confirmada" no grupo de Coordenação por modelo (com endereço, horário e valor combinado), `ia_pausada=true` com motivo `modelo_em_atendimento`, e atendimento → `Confirmado`. A IA não envia mensagem ao cliente confirmando o Pix; quem assume a conversa daí em diante é a modelo, manualmente no mesmo número. A IA só volta a atender após `finalizado` da modelo no grupo (encerra como `Fechado`) ou devolução manual de Fernando.

A foto de portaria (interno) usa o mesmo mecanismo de pausa: webhook detecta imagem em `Aguardando_confirmacao` interno → card "cliente chegou", `ia_pausada=true` com motivo `modelo_em_atendimento`, atendimento → `Em_execucao` (`04 §2.1`).

#### Motivo de handoff

Campo livre. Dashboard agrega por contagem se necessário.

#### Responsáveis válidos no P0

- `Fernando` — decisão sensível;
- `modelo` — ação física/operacional;
- `IA` — rótulo de responsabilidade ativa (default).

`vendedor_read_only` fica para P1. Valores genéricos como `humano` não são válidos.

---

### 5.5 Humanização de Envio

#### Objetivo

Enviar respostas em cadência compatível com WhatsApp.

#### Responsabilidades

- receber `[texto, lista_de_midias]` do Coordenador de Turno via job ARQ;
- partir o texto em blocos curtos por quebra natural (parágrafo/frase);
- ligar presence `composing` antes de cada bloco com delay curto;
- enviar mídias após o texto;
- garantir idempotência via `dedupe_key = (conversa_id, turno_id, chunk_idx)`.

#### Falha de envio

Log + Sentry. Retry default do ARQ, sem lógica custom.

#### Não é responsabilidade

- decidir conteúdo da conversa;
- mascarar conteúdo proibido depois de gerado;
- enviar cards no grupo de Coordenação por modelo (responsabilidade de 5.4, direto via Evolution);
- garantir que não haverá banimento.

---

### 5.6 IA Administrativa (P1)

#### Objetivo

Permitir comandos internos por áudio ou mensagem para agenda, comprovantes e exceções.

#### Responsabilidades P1

- bloquear horário por comando;
- liberar horário;
- consultar agenda;
- consultar comprovantes e status de Pix;
- registrar observação curta;
- tratar exceções disparadas pela IA;
- pedir confirmação quando o comando for ambíguo.

#### P0

No P0, bloqueios e decisões sensíveis devem ser registrados por painel ou operação manual assistida.

---

### 5.7 Classificador e Auditoria (P1)

#### Objetivo

Automatizar transições de estado e apoiar auditoria quando houver dados suficientes.

#### Responsabilidades P1

- analisar conversa, estado e sinais operacionais;
- sugerir ou aplicar transição conforme confiança apenas após validação do piloto;
- ignorar aplicação/sugestão de transição quando `ia_pausada=true`, preservando o uso das mensagens apenas para histórico, resumo e auditoria;
- registrar evidência da decisão;
- permitir revisão posterior;
- apoiar fechamento/perda inferidos em P1, nunca durante `ia_pausada=true`.

#### P0

No P0, a IA extrai dados e sinaliza alertas, mas não decide fechamento, perda pós-confirmação ou transições sensíveis. Timeout determinístico pré-confirmação pode marcar `Perdido` com `motivo_perda=sumiu` e `fonte_decisao=auto_timeout`.

---

## 7. Fronteiras Críticas

### 7.1 Saída

Pix de deslocamento confirma saída automaticamente no P0 apenas quando o pipeline OCR/vision passa em todas as checagens. Qualquer falha ou dúvida mantém o atendimento em `Aguardando_confirmacao`, define `pix_status=em_revisao` e escala Fernando. Pix validado dispara handoff direto para a modelo: card "saída confirmada" no grupo, `ia_pausada=true` com motivo `modelo_em_atendimento`, atendimento → `Confirmado` (`04 §3.1`). Avaliação de risco/local continua sendo decisão de Fernando quando houver sinal sensível antes do Pix.

### 7.2 Interno

Aviso de saída do cliente é evento informativo: prepara a modelo via card simples no grupo de Coordenação por modelo e a IA continua respondendo o cliente normalmente. O atendimento permanece em `Aguardando_confirmacao`. O recebimento da Foto de portaria dispara três efeitos atômicos no webhook: card "cliente chegou" no grupo com a imagem anexada, `ia_pausada=true` com motivo `modelo_em_atendimento`, e atendimento → `Em_execucao` (sem condicionar a transição a aprovação humana, sem vision automática — `04 §2.1`). A inspeção visual da modelo é proteção operacional antes de abrir a porta e não bloqueia a transição. Quando o cliente não manda foto, o atendimento entra no timeout interno curto de `04 §5.2` (30 min após o horário combinado) e é marcado como `Perdido` com `motivo_perda=sumiu` automaticamente.

### 7.3 Responsabilidade Operacional

O sistema não deve usar `humano` como responsável genérico.

Valores válidos:

- `IA`;
- `Fernando`;
- `modelo`;
- `vendedor_read_only`.

### 7.4 Fonte de Verdade

PostgreSQL é a fonte de verdade operacional. A IA pode preencher e sugerir dados, mas decisões, estados, agenda, Pix, escaladas e registros comerciais precisam ficar persistidos.
