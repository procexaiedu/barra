# 02 — Objetivo, Princípios e Escopo do MVP

## 1. Objetivo do MVP

O MVP deve validar se um sistema simples, com IA controlada conduzindo o atendimento no WhatsApp, Fernando/equipe no loop como decisor e a modelo acionada apenas quando houver necessidade operacional dela, consegue melhorar o atendimento e a gestão operacional **com uma única modelo piloto**, sem prejudicar a qualidade que o cliente premium da Barra Vips exige.

### Objetivo principal

> Validar uma operação real com uma modelo piloto da Barra Vips, centralizando atendimento via WhatsApp, agenda, CRM básico e regras de escalada para Fernando/equipe nas decisões sensíveis, com acionamento da modelo apenas quando ela precisar agir operacionalmente.

### Objetivos secundários

- reduzir tempo de resposta inicial ao cliente que chega pelo BarraVips;
- padronizar o tom da conversa nos quatro atributos definidos por Fernando (objetiva, exclusiva, extrovertida, inocente/estrangeira);
- registrar informações comerciais que hoje somem (nome, horário desejado, profissional de interesse, motivo de perda);
- evitar conflito de agenda na modelo piloto;
- registrar sinais objetivos de qualificação na conversa, sem score contínuo de "fecha vs não fecha";
- escalar corretamente situações sensíveis para Fernando/equipe, com resumo operacional no grupo persistente, acionando a modelo apenas quando ela precisar se preparar, confirmar disponibilidade ou assumir uma etapa operacional;
- gerar os primeiros dados operacionais reais — primeiro relatório útil para Fernando;
- testar se o fluxo pode ser replicado para a próxima modelo sem grande retrabalho;
- validar que a IA respeita as restrições do WhatsApp e não causa banimento.

---

## 2. Princípios do Produto

### 2.1 IA conduz o previsível; Fernando/equipe decide o sensível

A IA não deve tomar decisões críticas sozinha.

Ela pode:

- responder dúvidas;
- conduzir triagem;
- consultar disponibilidade;
- registrar dados;
- sugerir próximo passo;
- resumir conversas;
- acionar Fernando/equipe no grupo persistente quando houver decisão sensível;
- acionar a modelo no grupo persistente quando houver necessidade operacional dela;
- alertar Fernando para revisão quando houver exceção.

Ela não deve:

- decidir sobre situações de risco;
- lidar sozinha com conflitos;
- confirmar algo sem informação do sistema;
- negociar exceções complexas;
- operar fora das regras definidas;
- responder com informações que não estejam cadastradas ou autorizadas.

### 2.2 O sistema deve registrar tudo

Cada atendimento deve virar dado.

No mínimo, o sistema deve registrar:

- horário do primeiro contato;
- nome do cliente, quando ele informar;
- telefone / WhatsApp do cliente;
- profissional de interesse;
- intenção do cliente;
- etapa do funil;
- tipo de atendimento:
  - local próprio;
  - saída;
  - pernoite;
  - outro, se aplicável;
- horário desejado;
- data desejada;
- duração desejada do atendimento;
- endereço do cliente, sempre que a modelo precisar se deslocar até algum lugar;
- bairro / região do atendimento;
- referência do local, quando o cliente informar;
- hotel, casa, apartamento ou outro tipo de local;
- status do atendimento;
- motivo de escalada;
- resultado final;
- motivo de perda, quando houver;
- cliente novo ou recorrente;
- nível de urgência:
  - quer agora;
  - quer agendar para outro dia ou horário futuro;
  - horário indefinido, quando o cliente diz que avisa depois;
  - horário estimado, quando o cliente informa uma janela aproximada;
- objeções do cliente:
  - preço;
  - horário;
  - localização;
  - forma de pagamento;
- forma de pagamento pretendida:
  - Pix;
  - dinheiro;
  - outro;
- comprovante enviado;
- status do Pix de deslocamento para saída:
  - `nao_solicitado`;
  - `aguardando`;
  - `enviado`;
  - `em_revisao`;
  - `validado`;
  - `invalido`;
- valor final;
- taxa de deslocamento, quando houver;
- sinais de cliente qualificado:
  - informa horário;
  - informa local;
  - aceita valor;
  - envia Pix de deslocamento, quando for saída;
  - responde objetivamente;
- resumo automático da conversa.

As funcionalidades do MVP que garantem esse conjunto de registros estão listadas na **§3.1**.

### 2.3 O MVP deve ser pequeno, controlado e mensurável, porém já pensado para multi-modelos

O primeiro erro a evitar é tentar construir o sistema completo de uma vez.

O MVP deve começar com:

- uma profissional;
- um canal principal;
- painel operacional;
- registros;
- modelo no loop operacional;
- Fernando no loop de revisão.

---

## 3. Escopo do MVP

### 3.1 Dentro do MVP

O MVP deve conter apenas o necessário para validar a operação principal.

#### Funcionalidades obrigatórias — P0


| Módulo         | Funcionalidade                      | Objetivo                                                                                                                                                                                                                                                                                                             |
| -------------- | ----------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Cadastro       | Cadastro de uma profissional piloto | Permitir que o sistema tenha uma entidade operacional inicial                                                                                                                                                                                                                                                        |
| Agenda         | Bloqueio e liberação de horários    | Controlar disponibilidade                                                                                                                                                                                                                                                                                            |
| Atendimentos   | Lista de conversas em andamento     | Centralizar a operação                                                                                                                                                                                                                                                                                               |
| Atendimentos   | Status do atendimento               | Saber em que etapa cada cliente está                                                                                                                                                                                                                                                                                 |
| Atendimentos   | Máquina de estados enxuta           | Operar `Novo`, `Triagem`, `Qualificado`, `Aguardando_confirmacao`, `Confirmado`, `Em_execucao`, `Fechado` e `Perdido`, sem automatizar exceções complexas                                                                                                                                                             |
| Atendimentos   | Fonte da decisão                    | Registrar se a transição veio da modelo, de Fernando/equipe, sistema, timeout determinístico ou revisão posterior                                                                                                                                                                                                     |
| Atendimentos   | Metadados do primeiro contato       | Registrar origem padrão BarraVips, identificação WhatsApp e horário do primeiro contato                                                                                                                                                                                                                              |
| IA             | Triagem                             | Organizar a conversa sem depender de Fernando/equipe ou modelo                                                                                                                                                                                                                                                       |
| IA             | Identificação de intenção           | Entender o que o cliente quer                                                                                                                                                                                                                                                                                        |
| IA             | Consulta de disponibilidade         | Responder com base na agenda                                                                                                                                                                                                                                                                                         |
| IA             | Humanização do canal                | Enviar respostas em chunks com `presence: composing`, delays, jitter e debounce quando o cliente mandar nova mensagem                                                                                                                                                                                                |
| IA             | Gatilhos de escalada                | Avisar Fernando/equipe quando houver decisão sensível e avisar a modelo quando ela precisar agir operacionalmente; enviar resumo do atendimento e registrar motivo de escalada                                                                                                                                       |
| IA             | Áudio recebido do cliente           | Transcrever áudios, usar a transcrição no contexto e responder em texto                                                                                                                                                                                                                                              |
| IA             | Extração estruturada para o CRM     | Atualizar a ficha do atendimento (§2.2) a partir da conversa: tipo de atendimento, janela desejada, local quando houver, urgência, objeções, forma de pagamento pretendida, sinais binários de qualificação, valor e taxa quando informados                                                                          |
| CRM            | Registro básico de cliente          | Nome se informado e telefone via sistema; profissional de interesse                                                                                                                                                                                                                                                  |
| CRM            | Ficha operacional do atendimento    | Persistir no registro todos os campos da §2.2 compatíveis com o produto (etapa do funil, tipo local/saída/pernoite, data/hora/duração desejadas, endereço e referência quando necessário para deslocamento, bairro/região, tipo de local, resultado final, comprovante vinculado, valor final, taxa de deslocamento) |
| CRM            | Status comercial                    | Saber se é novo, qualificado, fechado ou perdido                                                                                                                                                                                                                                                                     |
| CRM            | Marcação novo / recorrente          | Registrar com confirmação manual pelo operador (sem unificação automática)                                                                                                                                                                                                                                           |
| CRM            | Motivo de perda                     | Registrar motivo de perda padronizado (`preco`, `sumiu`, `risco`, `indisponibilidade`, `fora_de_area`, `outro`) para aprender por que clientes não convertem                                                                                                                                                         |
| CRM            | Edição manual da ficha §2.2         | Corrigir ou completar dados quando a IA ou o fluxo não preencherem                                                                                                                                                                                                                                                   |
| CRM            | Pix de deslocamento para saída      | Registrar comprovante enviado e `pix_status` do Uber/deslocamento quando a modelo precisar ir até o cliente; validar por OCR + vision com checagem de beneficiário, chave, valor e timestamp; dúvida mantém o atendimento em `Aguardando_confirmacao`, define `pix_status=em_revisao` e escala Fernando/equipe         |
| Operação       | Escalada para Fernando/equipe       | Quando houver saída com sinal sensível, Pix em revisão, risco, local a avaliar, negociação sensível ou exceção, notificar Fernando/equipe com contexto suficiente para decisão                                                                                                                                       |
| Operação       | Acionamento da modelo               | Quando for necessário a modelo se preparar ou assumir uma etapa operacional, notificar a modelo no grupo persistente com contexto suficiente (ex: agendamento 22:00 local:..)                                                                                                                                        |
| Operação       | Grupo persistente por modelo        | Manter um grupo por modelo com o número operado pela IA, a própria modelo e Fernando; sem criar grupo novo por atendimento                                                                                                                                                                                           |
| Operação       | Registro de fechado/perdido         | Gerar métricas básicas e registrar `valor_final` obrigatório em todo fechamento para alimentar o financeiro; `valor_final` é o valor total bruto pago pelo cliente                                                                                                                                                   |
| Mídia          | Biblioteca mínima da modelo         | Armazenar fotos e vídeos pré-aprovados em MinIO, com tags e vínculo com a modelo                                                                                                                                                                                                                                    |
| Administrativo | Bloqueio manual de agenda           | Permitir controle operacional rápido                                                                                                                                                                                                                                                                                 |
| Dashboard      | Relatório diário simples            | Dar visão de performance                                                                                                                                                                                                                                                                                             |
| Agenda         | Notificações internas               | Avisar mudanças relevantes                                                                                                                                                                                                                                                                                           |


#### Funcionalidades desejáveis após validação inicial — P1


| Módulo         | Funcionalidade                     | Objetivo                                                                                           |
| -------------- | ---------------------------------- | -------------------------------------------------------------------------------------------------- |
| IA             | Classificador automático de estado | Automatizar transições com base em conversa, estado, tempo e horário desejado após validar o fluxo |
| CRM            | Tags de cliente                    | Segmentar a base quando já houver dados suficientes do piloto                                      |
| Administrativo | IA Admin por áudio                 | Permitir comandos internos por áudio para agenda, comprovantes e ações administrativas depois que o fluxo manual estiver validado |
| Dashboard      | Filtros de auditoria               | Filtrar por `fonte_decisao` para revisar amostras de transições automáticas após classificador P1  |
| Atendimentos   | Fila de prioridade                 | Destacar conversas por urgência e importância quando houver volume suficiente                      |


### 3.2 Fora do MVP


| Item                                                  | Motivo para ficar fora do MVP                                                                                                                                                                        |
| ----------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Importação dos 15.000 contatos antigos                | Confirmado fora do MVP — entra em fase posterior                                                                                                                                                     |
| Remarketing em massa                                  | Depende da base antiga estar carregada e estratégia definida                                                                                                                                         |
| Gestão completa de vários vendedores                  | Só faz sentido após validar a primeira operação                                                                                                                                                      |
| Gestão simultânea de 10–15 profissionais              | Escalar cedo demais aumenta risco                                                                                                                                                                    |
| Dashboard avançado                                    | Primeiro é preciso gerar dados confiáveis                                                                                                                                                            |
| Análise avançada de conversas                         | Depende de volume e histórico                                                                                                                                                                        |
| Plataforma de turismo de luxo (visão)                 | Visão de longo prazo — só após operação base validada                                                                                                                                                |
| Ensaios fotográficos com IA generativa                | Visão de longo prazo                                                                                                                                                                                 |
| Gestão de consentimento para contato                  | Descartado como preocupação no MVP                                                                                                                                                                   |
| Triagem geográfica formal                             | Não haverá lista de bairros nem pergunta estruturada; saída segue com Pix de deslocamento aprovado pelo pipeline OCR/vision, e falha ou dúvida mantém `status=Aguardando_confirmacao`, define `pix_status=em_revisao` e escala Fernando/equipe |
| Filtro comportamental "fecha vs não fecha"            | Não haverá score contínuo; a IA trata todos com o mesmo comportamento comercial e registra apenas sinais objetivos                                                                                   |
| Reengajamento de curto prazo dentro da mesma conversa | Cliente em silêncio segue para timeout natural; reengajamento fica para fase futura                                                                                                                  |
| Aquecimento de número e número reserva pré-aquecido   | Decisão consciente do operador; o MVP mitiga risco com humanização do envio e testes internos                                                                                                        |
| Tabela de Uber por bairro                             | Valor único de R$ 100 no MVP                                                                                                                                                                         |
| Pix antecipado para atendimento interno               | Para interno, o pagamento é presencial; Pix antecipado no MVP fica restrito ao deslocamento de saída                                                                                                 |
| Unificação automática de cliente recorrente           | Sempre por confirmação manual de Fernando                                                                                                                                                            |
| Vendedor atuando no handoff                           | A decisão sensível vai para Fernando/equipe; a modelo só é acionada quando precisar agir operacionalmente                                                                                            |
| Áudio gerado por IA (TTS) para o cliente              | IA responde em texto; TTS fica fora por risco de quebra de persona                                                                                                                                   |
| IA Admin como interface genérica de edição            | Perfil, FAQ, comercial, mídia e observações livres ficam no painel web                                                                                                                               |


---

## 4. Versão Recomendada do MVP em Uma Frase

> Uma central simples, com agenda, CRM básico e IA de triagem, operando com uma profissional piloto, escalando decisões sensíveis para Fernando/equipe e acionando a modelo apenas quando ela precisar agir operacionalmente.
