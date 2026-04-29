# 03 - Módulos do Sistema

Este documento define quais módulos compõem o sistema, qual é a responsabilidade de cada um e onde ficam as fronteiras entre produto, dados e operação.

Ele não deve descrever fluxos passo a passo, regras detalhadas de conversa, modelagem completa de banco, decisões históricas ou critérios de roadmap. Esses assuntos pertencem aos documentos específicos de fluxo, escalada, dados, decisões e execução.

## 1. Critério de Pertencimento

Este arquivo deve responder:

- quais módulos existem;
- se o módulo é P0 ou P1;
- qual problema operacional o módulo resolve;
- quais responsabilidades pertencem ao módulo;
- quais responsabilidades não pertencem ao módulo;
- quais dados o módulo consome ou produz em alto nível;
- quais outros módulos ele aciona ou consulta.

Este arquivo não deve conter:

- passo a passo de fluxo interno, externo, Pix ou agenda;
- prompts, regras finas de resposta ou exemplos de mensagem;
- tabelas completas de banco;
- heurísticas de classificador, timeout ou score;
- decisões de reunião, riscos ou histórico de mudanças;
- requisitos visuais detalhados de tela.

---

## 2. Camadas do Sistema

### 2.1 Produto e Operação

Camada usada por Fernando/equipe para acompanhar, revisar e operar o atendimento.

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
- bloqueios de agenda;
- comprovantes Pix;
- alertas;
- escaladas;
- logs e auditoria.

### 2.3 Serviços Operacionais e IA

Camada que recebe eventos, consulta dados, executa regras e grava decisões.

Inclui:

- Webhook de WhatsApp/Evolution;
- Orquestrador de Atendimento;
- IA de Atendimento;
- Escaladas e Alertas;
- Humanização de envio;
- IA Administrativa em P1;
- Classificador e Auditoria em P1;
- Mídia mínima da modelo em P0.

---

## 3. Mapa de Módulos


| Módulo                         | Camada              | P0  | Responsável operacional principal |
| ------------------------------ | ------------------- | --- | --------------------------------- |
| Painel Geral                   | Produto             | Sim | Fernando/equipe                   |
| Central de Atendimentos        | Produto + domínio   | Sim | Fernando/equipe                   |
| Conversas e Mensagens          | Dados + serviço     | Sim | Sistema                           |
| Agenda Operacional             | Produto + domínio   | Sim | Fernando/equipe                   |
| CRM                            | Produto + domínio   | Sim | Fernando/equipe                   |
| Modelos e Base de Conhecimento | Produto + domínio   | Sim | Fernando                          |
| Pix e Comprovantes             | Domínio + serviço   | Sim | Fernando/equipe                   |
| IA de Atendimento              | Serviço operacional | Sim | Sistema                           |
| Escaladas e Alertas            | Serviço + domínio   | Sim | Sistema/Fernando/equipe/modelo    |
| Webhook e Orquestrador         | Serviço operacional | Sim | Sistema                           |
| Dashboard                      | Produto             | Sim | Fernando                          |
| Mídia da Modelo                | Produto + serviço   | Sim | Fernando                          |
| IA Administrativa              | Serviço operacional | P1  | Fernando                          |
| Classificador e Auditoria      | Serviço + domínio   | P1  | Sistema/Fernando                  |


---

## 4. Módulos de Produto

### 4.1 Painel Geral

#### Objetivo

Dar uma visão operacional rápida do dia.

#### Responsabilidades

- mostrar atendimentos abertos;
- destacar atendimentos que saíram da condução automática da IA e aguardam intervenção;
- separar destaque de `decisão Fernando/equipe` e `ação operacional da modelo`;
- exibir motivo do destaque, responsável atual e próxima ação esperada;
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
- indicar responsável atual: `IA`, `Fernando/equipe`, `modelo`, `operador_autorizado` ou `vendedor_read_only`;
- exibir motivo de escalada, motivo de perda e resumo operacional;
- permitir correção manual da ficha operacional;
- permitir registro de fechado/perdido após handoff conforme as regras canônicas de comando e correção definidas em `05-escalada-regras-ia.md`.
- permitir devolução explícita para IA quando um atendimento em handoff puder voltar à condução automática (`Devolver para IA` no painel; `IA assume` ou `IA assume #N` no grupo).

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
| `Aguardando_confirmacao` | IA aguarda confirmação, Pix de deslocamento, aviso de saída ou imagem de portaria |
| `Confirmado`             | Pix aprovado ou imagem recebida no fluxo interno                                  |
| `Em_execucao`            | Atendimento confirmado chegou ao horário previsto                                 |
| `Fechado`                | Atendimento convertido por registro explícito                                     |
| `Perdido`                | Atendimento não converteu por registro explícito ou timeout determinístico         |


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
- substituir validação de Fernando/equipe;
- executar agenda por áudio no P0;
- bloquear horário externo apenas com Pix recebido.

#### Estados de agenda


| Estado           | Significado                       |
| ---------------- | --------------------------------- |
| `sinalizado`     | Existe interesse, mas não reserva |
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
- registrar novo/recorrente com confirmação manual quando necessário;
- registrar objeções, motivos de perda padronizados (`preco`, `sumiu`, `risco`, `indisponibilidade`, `fora_de_area`, `outro`) e observações internas;
- expor histórico resumido para operação e IA;
- manter dados que a IA pode consultar sem verbalizar.

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
- registrar chave Pix e titular quando necessário para saída.

#### Não é responsabilidade

- permitir que IA Admin edite perfil no MVP;
- verbalizar termos explícitos para o cliente;
- armazenar biblioteca completa de mídia no P0;
- gerenciar múltiplas modelos em escala no P0.

---

### 4.6 Pix e Comprovantes

#### Objetivo

Registrar Pix de deslocamento em saída, validar automaticamente quando todas as checagens passarem e encaminhar exceções para Fernando/equipe.

#### Responsabilidades P0

- registrar que Pix de deslocamento foi solicitado;
- registrar comprovante enviado pelo cliente;
- manter status do Pix;
- validar comprovante por OCR/vision com checagem de beneficiário, chave, valor, timestamp e plausibilidade visual;
- confirmar automaticamente quando todas as checagens passarem;
- escalar Fernando/equipe quando qualquer checagem falhar ou ficar duvidosa;
- registrar decisão de Fernando/equipe;
- impedir confirmação automática quando houver qualquer divergência no comprovante.

#### Não é responsabilidade P0

- aceitar comprovante com qualquer divergência;
- bloquear agenda automaticamente apenas com comprovante recebido;
- substituir avaliação de risco/local feita por Fernando/equipe.

#### Estados de Pix


| Estado           | Significado                  |
| ---------------- | ---------------------------- |
| `nao_solicitado` | Pix não faz parte do fluxo   |
| `aguardando`     | IA pediu Pix de deslocamento |
| `enviado`        | Cliente enviou comprovante   |
| `em_revisao`     | Aguardando Fernando/equipe   |
| `validado`       | Pipeline ou Fernando/equipe validou |
| `invalido`       | Recusado                     |


---

### 4.7 Dashboard

#### Objetivo

Dar visão gerencial simples da operação piloto.

#### Responsabilidades P0

- mostrar volume de atendimentos;
- mostrar leads qualificados;
- mostrar fechamentos;
- mostrar perdas;
- mostrar motivos de perda;
- mostrar Pix em revisão;
- mostrar atendimentos escalados;
- excluir atendimentos de teste das métricas por padrão.

#### Não é responsabilidade P0

- auditoria detalhada de classificador;
- análise avançada de conversas;
- métricas complexas por vendedor;
- relatórios de remarketing.

---

## 5. Módulos Operacionais

### 5.1 Conversas e Mensagens

#### Objetivo

Persistir o histórico bruto recebido pelo WhatsApp/Evolution.

#### Responsabilidades

- receber texto, imagem, áudio e vídeo quando aplicável;
- transcrever áudio recebido do cliente e disponibilizar a transcrição no contexto;
- detectar mensagens enviadas pelo próprio sistema;
- distinguir mensagens enviadas pela IA de mensagens `fromMe` escritas manualmente pela modelo no mesmo WhatsApp;
- criar ou atualizar conversa;
- persistir mensagem bruta;
- persistir mensagens da modelo e do cliente mesmo quando `ia_pausada=true`;
- preservar histórico sem edição manual;
- acionar o orquestrador.

#### Não é responsabilidade

- decidir resposta da IA;
- classificar cliente;
- editar conteúdo de conversa;
- resolver conflitos de atendimento.

---

### 5.2 Webhook e Orquestrador de Atendimento

#### Objetivo

Coordenar a entrada de eventos e acionar os serviços corretos.

#### Responsabilidades

- receber evento do canal;
- identificar cliente, conversa e atendimento aberto;
- criar atendimento quando necessário;
- montar contexto operacional;
- manter captação e extração de histórico quando `ia_pausada=true`;
- consultar agenda, CRM e base da modelo;
- chamar IA de Atendimento;
- aplicar extrações estruturadas;
- registrar decisões;
- disparar alertas;
- respeitar locks por conversa.
- não chamar a IA para responder quando `ia_pausada=true`, exceto após devolução explícita.
- não disparar alerta por novas mensagens do cliente enquanto `ia_pausada=true`.
- não criar badge, contador de não lidas ou destaque no painel por novas mensagens do cliente enquanto `ia_pausada=true`.

#### Não é responsabilidade

- conter regra detalhada de conversa;
- decidir exceções de risco;
- validar Pix sozinho;
- fazer análise avançada de performance.

---

### 5.3 IA de Atendimento

#### Objetivo

Conduzir o atendimento previsível no WhatsApp dentro da persona autorizada.

#### Responsabilidades P0

- saudar dentro da persona;
- identificar intenção;
- consultar disponibilidade;
- responder com base em perfil, FAQ e dados cadastrados;
- conduzir triagem;
- registrar dados estruturados;
- pedir Pix de deslocamento quando for saída;
- gerar resumo operacional;
- escalar para Fernando/equipe quando houver decisão sensível;
- acionar a modelo quando houver necessidade operacional dela;
- pausar cordialmente quando não puder continuar.

#### Não é responsabilidade

- decidir risco ou local de saída;
- negociar exceções complexas;
- confirmar saída quando o Pix não estiver validado ou houver sinal sensível sem decisão de Fernando/equipe;
- verbalizar serviços explícitos;
- inventar dados;
- unificar cliente recorrente automaticamente;
- reengajar cliente silencioso no P0.

---

### 5.4 Escaladas e Alertas

#### Objetivo

Entregar a pessoa certa no canal certo com contexto suficiente para ação.

#### Responsabilidades

- criar alerta quando a IA não puder continuar;
- diferenciar decisão de Fernando/equipe de ação operacional da modelo;
- registrar motivo da escalada;
- incluir resumo operacional;
- indicar ação esperada;
- registrar quem assumiu ou decidiu.
- manter a IA pausada após handoff até devolução explícita por Fernando/equipe ou modelo.
- ao devolver para IA, registrar autor, canal, horário e atendimento afetado.
- registrar resultado explícito durante handoff e correções posteriores seguindo a fonte canônica de comandos em `05-escalada-regras-ia.md`.
- aplicar os efeitos de dados definidos em `06-dados-interfaces.md`: financeiro, auditoria e ajuste apenas do bloqueio de agenda vinculado.

#### Responsáveis válidos

- `Fernando/equipe`: decisão sensível, como saída, risco, Pix, exceções, conflitos, cancelamentos, bloqueio/ajuste de agenda e negociação fora da regra;
- `modelo`: ação física ou operacional, como preparo, confirmação de disponibilidade, chegada, saída, recebimento do cliente ou etapa final;
- `operador_autorizado`: registro de decisão ou ação operacional autorizada;
- `IA`: triagem e condução previsível;
- `vendedor_read_only`: acompanhamento sem ação no MVP.

Valores genéricos como `humano` não são válidos para responsabilidade operacional.

---

### 5.5 Humanização de Envio

#### Objetivo

Enviar respostas com cadência compatível com WhatsApp e reduzir risco operacional de banimento.

#### Responsabilidades

- controlar presença de digitação;
- enviar respostas em partes curtas;
- aplicar pequenos atrasos;
- cancelar envio pendente se o cliente mandar nova mensagem;
- manter geração de resposta separada do envio.

#### Não é responsabilidade

- decidir conteúdo da conversa;
- mascarar conteúdo proibido depois de gerado;
- garantir que não haverá banimento;
- substituir regras de segurança textual da IA.

---

### 5.6 Mídia da Modelo

#### Objetivo

Gerenciar biblioteca estruturada de fotos e vídeos aprovados.

#### Responsabilidades P0

- armazenar mídia mínima por modelo em MinIO;
- exigir pelo menos 10 mídias pré-aprovadas por modelo antes do piloto;
- marcar mídia aprovada;
- classificar por tipo e tag simples;
- permitir seleção simples pela IA a partir de tag;
- registrar preferência de visualização única para vídeos;
- bloquear envio automático de vídeo e escalar Fernando/equipe quando o canal não suportar visualização única.

#### Responsabilidades P1

- ranking de mídia por contexto da conversa;
- biblioteca completa com curadoria avançada;
- métricas de uso e resposta por mídia;
- gestão avançada de tags.

#### Mídia do Cliente

Comprovantes e fotos enviadas pelo cliente ficam vinculados ao atendimento e retidos por 30 dias, salvo disputa ou auditoria.

---

### 5.7 IA Administrativa (P1)

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

### 5.8 Classificador e Auditoria (P1)

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

## 6. P0 vs P1

### 6.1 P0 Obrigatório

- uma modelo piloto;
- WhatsApp/Evolution;
- clientes;
- conversas;
- mensagens;
- atendimentos;
- estados enxutos;
- agenda com bloqueio, liberação e conflito;
- IA de Atendimento;
- humanização de envio;
- extração estruturada para CRM;
- transcrição de áudio recebido do cliente;
- base de conhecimento da modelo;
- biblioteca mínima de mídia em MinIO;
- Pix de deslocamento com registro de comprovante, validação automática quando todas as checagens passarem e revisão de Fernando/equipe nas exceções;
- escaladas e alertas;
- dashboard simples;
- modo de atendimento de teste para Fernando.

### 6.2 P1 / Depois da Validação Inicial

- importação dos 15.000 contatos antigos;
- remarketing em massa;
- dashboard avançado;
- classificador automático;
- biblioteca completa de mídia e curadoria avançada;
- IA Admin por áudio;
- filtros avançados de auditoria;
- fila de prioridade;
- gestão simultânea de muitas modelos;
- vendedor atuando no handoff;
- IA Admin como interface genérica;
- TTS/voz gerada por IA;
- ensaios fotográficos com IA generativa;
- aquecimento de número e número reserva;
- tabela de Uber por bairro;
- redirecionamento para outra modelo;
- unificação automática de cliente recorrente.

---

## 7. Fronteiras Críticas

### 7.1 Saída

Pix de deslocamento confirma saída automaticamente no P0 apenas quando o pipeline OCR/vision passa em todas as checagens. Qualquer falha ou dúvida mantém o atendimento em `Aguardando_confirmacao`, define `pix_status=em_revisao` e escala Fernando/equipe. Confirmação automática por Pix bloqueia agenda e gera handoff/resumo; avaliação de risco/local continua sendo decisão de Fernando/equipe quando houver sinal sensível.

### 7.2 Interno

Aviso de saída do cliente prepara a modelo e pode manter sinalização. Foto de portaria ou decisão de Fernando/equipe permite confirmação operacional.

### 7.3 Responsabilidade Operacional

O sistema não deve usar `humano` como responsável genérico.

Valores válidos:

- `IA`;
- `Fernando/equipe`;
- `modelo`;
- `operador_autorizado`;
- `vendedor_read_only`.

### 7.4 Fonte de Verdade

PostgreSQL é a fonte de verdade operacional. A IA pode preencher e sugerir dados, mas decisões, estados, agenda, Pix, escaladas e registros comerciais precisam ficar persistidos.
