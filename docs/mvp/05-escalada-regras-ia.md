# 05 — Escalada, Handoff e Regras da IA

Este documento define quando e como a IA escala para humano, qual a sintaxe canônica de comandos no grupo de Coordenação por modelo, e quais bloqueios e regras gerais a IA respeita durante o atendimento. A modelagem dos comandos como porta única vive em `03 §5.4`; aqui ficam as regras de produto e o detalhamento operacional.

## 1. Quando a IA escala

A IA não toma decisão sensível sozinha. Toda escalada usa a tool `escalar(responsavel, motivo, resumo_operacional, acao_esperada)` (`03 §5.3`), que aciona `aplicar_comando(...,'abrir_handoff')` em 5.4 e ativa `ia_pausada=true`.

### 1.1 Gatilhos canônicos para Fernando

A IA escala para Fernando quando há **decisão sensível** que ela não pode resolver dentro do prompt autorizado:

- **Pix em revisão** — pipeline OCR/vision falha em qualquer checagem (beneficiário, chave, valor, timestamp, plausibilidade). Disparo automático pelo pipeline (5.4 via `atualizar_pix(em_revisao)`); a IA não chama `escalar` neste caso, mas o efeito de pausa é o mesmo.
- **Sinal de risco** — cliente menciona local notoriamente perigoso, comportamento agressivo, ameaça, suspeita de golpe ou pedido de prática que viola política da modelo. IA chama `escalar(responsavel='Fernando', motivo='risco', ...)`.
- **Pedido fora da política comercial** — desconto não autorizado, valor abaixo do mínimo cadastrado, serviço não previsto na FAQ, troca de modelo sem motivo claro. IA escala em vez de negociar.
- **Conflito de agenda** — cliente insiste em horário já bloqueado e IA não consegue redirecionar para janela livre. IA escala antes de prometer algo que a agenda contradiz.
- **Dúvida operacional não coberta pela FAQ** — qualquer pedido cuja resposta exija decisão que não está na base de conhecimento da modelo (ex: nova localidade, nova forma de pagamento). IA escala em vez de improvisar.

### 1.2 Gatilhos canônicos para a modelo

Foto de portaria e Pix validado são **handoffs implícitos** disparados pelo coordenador (5.2) ou pelo pipeline (5.4), não pela tool `escalar` da IA, mas o efeito de pausa é o mesmo: `ia_pausada=true` com motivo `modelo_em_atendimento`, e a IA só volta a atender após `finalizado [valor]` da modelo no grupo (encerra como `Fechado` e libera `ia_pausada=false`) ou devolução manual de Fernando pelo painel.

- **Aviso de saída do cliente (interno)** — cliente avisou que saiu de casa. Coordenador envia card simples no grupo. **Não é handoff**: `ia_pausada` continua `false` e a IA segue respondendo o cliente.
- **Foto de portaria recebida (interno)** — webhook detecta imagem em `Aguardando_confirmacao` interno → card "cliente chegou" com a imagem anexada, `ia_pausada=true` (motivo `modelo_em_atendimento`), atendimento → `Em_execucao`. **É handoff implícito**: a modelo assume a partir daí (`04 §2.1`).
- **Pix validado (externo)** — pipeline valida o comprovante → card "saída confirmada" com endereço, horário e valor, `ia_pausada=true` (motivo `modelo_em_atendimento`), atendimento → `Confirmado`. **É handoff implícito**: a modelo se desloca, executa e finaliza pelo grupo (`04 §3.1`).

### 1.3 O que **não** dispara escalada no P0

- **Silêncio do cliente** — timeouts determinísticos de `04 §5` cuidam sozinhos.
- **Cliente fora de área genérico** — sem lista de bairros formal no MVP (`02 §3.2`); a IA segue tentando conduzir e só escala se houver sinal de risco.
- **Mensagens picotadas/áudios curtos** — debounce e transcrição não são gatilhos.
- **Erro de digitação ou linguagem confusa** — IA tenta interpretar normalmente; só escala se for impossível identificar intenção depois de pergunta de esclarecimento.

### 1.4 Limite de iterações sem fechar turno

Se a IA bater o teto de 10 iterações por turno sem produzir text content (`03 §5.3`), o coordenador escala automaticamente com `motivo='exaustao'` e `responsavel='Fernando'`. Não há mensagem ao cliente; Fernando vê o card e decide.

---

## 2. Card de handoff no grupo de Coordenação por modelo

Quando a IA chama `escalar`, o módulo 5.4 envia um card no grupo. Estrutura mínima:

### 2.1 Conteúdo obrigatório do card

- **#N** — identificador curto do atendimento (ex: `#142`).
- **Cliente** — nome quando disponível, senão telefone mascarado.
- **Tipo de atendimento** — `interno` ou `externo`, quando já definido.
- **Estado atual** — estado do atendimento e `pix_status` se aplicável.
- **Motivo da escalada** — texto curto da IA (ex: `risco — cliente mencionou bairro X`).
- **Resumo operacional** — 1–3 frases com o que aconteceu na conversa (gerado pela IA na chamada de `escalar`).
- **Próxima ação esperada** — o que Fernando ou a modelo devem decidir/fazer.
- **Responsável atual** — `Fernando` ou `modelo`, conforme parâmetro da escalada.

### 2.2 Anexo de mídia

Quando a escalada envolve mídia recebida do cliente (imagem de comprovante, foto de portaria), o card inclui o anexo. No P0 a IA não interpreta o conteúdo — apenas encaminha.

### 2.3 Confirmações curtas no grupo

Toda ação aplicada via comando do grupo (registro de resultado, devolução para IA, atualização de Pix) recebe confirmação curta no próprio grupo (`CONTEXT.md`). Cards e confirmações são enviados direto pelo Evolution sem passar pela Humanização (5.5) — não precisam de cadência humanizada.

---

## 3. Sintaxe canônica de comandos

A modelo e Fernando operam por **mensagens-texto no grupo de Coordenação por modelo**, ou por botões no painel (Fernando). O parser do módulo 5.4 reconhece a sintaxe abaixo.

### 3.1 Comandos válidos

| Comando | Forma | Quem | Onde |
|---------|-------|------|------|
| Devolver para IA | `IA assume` (quote ao card) ou `IA assume #N` | Fernando ou modelo | Grupo |
| Devolver para IA | botão `Devolver para IA` | Fernando | Painel |
| Encerrar atendimento físico | `finalizado [valor]` (quote ao card; valor opcional) | Modelo | Grupo |
| Registrar fechamento | `fechado [valor] #N` ou `fechado [valor]` (quote ao card) | Fernando ou modelo | Grupo |
| Registrar fechamento | botão `Fechar` + valor | Fernando | Painel |
| Registrar perda | `perdido [motivo] [obs?] #N` ou `perdido [motivo] [obs?]` (quote ao card) | Fernando ou modelo | Grupo |
| Registrar perda | botão `Perder` + motivo | Fernando | Painel |

### 3.2 Regras do parser

- **`#N` obrigatório** quando o comando não é quote do card. Sem `#N` em mensagem livre, comando é inválido.
- **Quote do card dispensa `#N`** — o atendimento é inferido pelo card respondido.
- **`finalizado` é exclusivo da modelo no grupo** — usado ao encerrar o atendimento físico. Se valor informado, registra `fechado valor` simultaneamente; se omitido, encerra apenas o atendimento físico (estado `Em_execucao` → `Fechado` continua dependendo de comando explícito).
- **Valor aceito** — formatos brasileiros comuns (`1.000`, `1000`, `R$ 1.000`, `1k`); valor ambíguo pede confirmação.
- **Motivo de perda** — exatamente um dos valores do enum: `preco`, `sumiu`, `risco`, `indisponibilidade`, `fora_de_area`, `outro`. `outro` exige observação curta.
- **Comando inválido** — campo faltando, taxonomia errada, `#N` ambíguo. Resposta: erro curto no canal de origem; **estado, agenda e financeiro não mudam**.

### 3.3 Quem pode operar

| Origem | Comandos permitidos no P0 |
|--------|---------------------------|
| Fernando (grupo ou painel) | Todos |
| Modelo (grupo) | `IA assume`, `finalizado`, `fechado`, `perdido` |
| Vendedor (Chatwoot) | Nenhum — vendedor é read-only no MVP (`01 §6`) |
| IA Admin | Nenhum no P0 — agenda por áudio é P1 (`03 §5.6`) |

### 3.4 Correção de registro

Fernando corrige registro pelo painel quando a modelo registrar errado:

- Recalcula financeiro automaticamente.
- Ajusta apenas o bloqueio vinculado.
- **Pede confirmação** se precisar alterar bloqueio já em `em_atendimento` ou `concluido` (`CONTEXT.md`).
- Registro corrigido fica auditado em `eventos`.

---

## 4. Devolução para IA

Comando explícito que reativa a IA após handoff (`CONTEXT.md`).

### 4.1 Formas válidas

- Botão `Devolver para IA` no painel (Fernando).
- `IA assume` ou `IA assume #N` no grupo (Fernando ou modelo).
- `finalizado [valor]` no grupo respondendo ao card — usado pela modelo ao encerrar o atendimento físico; se valor informado, registra `fechado valor` simultaneamente. Não requer comando separado de devolução.

### 4.2 Comportamento da IA na devolução

- `ia_pausada=false`, registra autor, canal e horário em `eventos`.
- **A IA não envia nada proativamente** (decisão grilling 29/04, opção D).
- IA absorve o backlog de mensagens (cliente + modelo manual) no contexto interno do próximo turno.
- IA aguarda a próxima mensagem do cliente para responder.
- Mensagens da modelo durante o handoff entram no histórico marcadas como `direcao=modelo_manual`; promessas/combinações da modelo são vinculantes para a IA.

### 4.3 Pix validado e foto de portaria não acionam devolução

Pix validado (externo, `04 §3.1`) e foto de portaria (interno, `04 §2.1`) **pausam a IA** com motivo `modelo_em_atendimento` em vez de devolvê-la. A IA permanece pausada até a modelo registrar `finalizado [valor]` no grupo (encerra como `Fechado` e libera `ia_pausada=false`) ou Fernando devolver manualmente pelo painel. Não há turno automático após Pix validado nem após foto de portaria — quem assume a conversa é a modelo, manualmente no mesmo número.

### 4.4 Re-escalada por exceção

Descartada como edge case (decisão grilling 29/04). Se a modelo prometeu algo que a IA acharia errado, vale a promessa da modelo — não há mecanismo de re-escalada automática.

---

## 5. Disciplina operacional da modelo

Confirmada em 2026-04-29 como regra dura.

### 5.1 Modelo no grupo de coordenação

- Lê cards e responde com comandos canônicos (§3).
- Decide visualmente sobre foto de portaria antes de abrir a porta — proteção operacional; a transição para `Em_execucao` e a pausa da IA já foram automáticas no webhook.
- Registra `finalizado [valor]` ao encerrar o atendimento físico.
- Pode chamar `IA assume #N` para devolver conversas que a modelo havia assumido.

### 5.2 Modelo na conversa cliente

- **Não envia mensagens enquanto a IA está conduzindo** (`ia_pausada=false`). Mensagem espontânea da modelo nesse cenário é caso anômalo, não fluxo normal.
- Quando a IA estiver em handoff (`ia_pausada=true`), a modelo pode escrever para o cliente no mesmo número.
- Mensagens manuais da modelo são gravadas com `direcao=modelo_manual`.

### 5.3 Salvaguarda de fromMe espontâneo

Debounce de 60s no envio quando aparece `fromMe` espontâneo do número da modelo fora de handoff oficial. Funciona como segurança técnica para não pisar em mensagem manual; não é fluxo de handoff implícito (decisão grilling 29/04 — não treinar a modelo para "interromper a IA quando achar útil").

### 5.4 Identidade da modelo no grupo

A modelo **não tem identidade separada** no grupo de Coordenação por modelo (decisão grilling 29/04). Grupo tem 2 participantes: número da modelo (operado pela IA) e Fernando. Mensagens manuais da modelo no grupo entram como `fromMe` no mesmo número que a IA opera; o sistema distingue IA de modelo pelo originador real do envio (Evolution API call vs `fromMe` espontâneo).

---

## 6. Regras gerais de comportamento da IA

Vive como bloco fixo no system prompt, marcado com `cache_control` (`07 §7.10`).

### 6.1 Persona

- Quatro atributos inegociáveis: **objetiva, exclusiva, extrovertida, inocente/estrangeira** (`01 §5`).
- IA fala **em nome da modelo**, sem nunca revelar que é IA.
- Nada apagado, nada corrigido bruscamente — credibilidade é crítica e qualquer inconsistência mata a venda.

### 6.2 O que a IA pode fazer

- Responder dúvidas com base na FAQ cadastrada.
- Conduzir triagem e qualificação (`02 §2.1`).
- Consultar agenda, cliente, FAQ, status de Pix, mídia (tools de leitura, `03 §5.3`).
- Registrar extração estruturada uma vez por turno (`registrar_extracao`).
- Pedir Pix de deslocamento na saída (`pedir_pix_deslocamento`).
- Enviar mídia pré-aprovada (`enviar_midia`).
- Escalar para Fernando ou acionar a modelo (`escalar`).
- Resumir conversa para o card de handoff.

### 6.3 O que a IA não pode fazer

- Decidir sobre situações de risco.
- Lidar sozinha com conflitos.
- Confirmar algo sem informação do sistema.
- Negociar exceções comerciais complexas.
- Operar fora das regras definidas.
- Responder com informações que não estejam cadastradas ou autorizadas.
- Verbalizar termos explícitos sobre o serviço.
- Inventar dados (preço, endereço, política, FAQ).
- Reengajar cliente silencioso no P0 (`02 §3.2`).
- Interpretar imagem por vision (exceto via pipeline OCR para Pix, fora do agente).
- Despedir-se ou comentar a escalada após chamar `escalar` — turno encerra imediatamente (`03 §5.3`).
- Fundir atendimentos antigos com o atual — cada atendimento é entidade separada na conversa (cliente, modelo) atual; histórico de outras modelos não é acessível à IA (`04 §4.1`).

### 6.4 Restrições do canal

- Respostas em texto (sem TTS no P0 — `02 §3.2`).
- Cadência humanizada via 5.5 (chunks, presence composing, delays, jitter, debounce).
- Mídia anexada após texto, no mesmo turno.
- IA não envia áudio gerado por IA.

### 6.5 Idempotência

- Tools de escrita são idempotentes via `turno_id` (`03 §5.3`).
- `registrar_extracao` chamada apenas uma vez por turno.
- `escalar` encerra o turno imediatamente — chamadas posteriores na mesma iteração são descartadas.

---

## 7. Bloqueios duros

Casos em que a IA **nunca** atua, mesmo dentro de uma conversa aparentemente normal.

### 7.1 Vetos absolutos

- **Sem Pix validado, sem confirmação de saída** — fluxo externo só vai a `Confirmado` por pipeline ou Fernando.
- **Sem cadastro, sem informação** — qualquer dado não cadastrado vira escalada ou pergunta de esclarecimento; IA não improvisa.
- **Sem autorização, sem desconto** — política comercial cadastrada é o teto; IA não negocia abaixo.
- **Sem identidade revelada** — IA nunca admite ser IA, nem encerra dizendo "vou passar para humano". Quando escala, simplesmente para de responder; conversa volta pela modelo manualmente, por Fernando devolvendo pelo painel ou por evento de pipeline que libere `ia_pausada` (ex.: Pix recusado, que volta o atendimento para `Aguardando_confirmacao` ativo).
- **Sem mídia não cadastrada** — IA não envia foto recebida do cliente, não monta colagem, não gera imagem.
- **Sem mensagem do cliente, sem turno automático** — Pix validado e foto de portaria pausam a IA em vez de invocá-la; não há nenhuma exceção que dispare turno sem mensagem entrante do cliente.

### 7.2 Bloqueios em `ia_pausada=true`

- IA não é convocada — coordenador não dispara turno.
- Mensagens entrantes são gravadas em 5.1 sem indicador no painel.
- Classificador P1 ignora aplicação/sugestão de transição enquanto pausada (`03 §5.7`).

### 7.3 Bloqueios pós-`Fechado` ou pós-`Perdido`

- Atendimento encerrado não recebe novo turno da IA. Próxima mensagem do cliente que chegar dispara criação de **novo atendimento** em `Novo` (regra de resolução determinística do coordenador, `03 §5.2`).
- Correção de registro fica em Fernando pelo painel; IA não atua.

---

## 8. Auditoria de escalada

Toda escalada e devolução fica auditada.

### 8.1 Tabela `eventos`

Registra autor, canal, horário, motivo e contexto operacional para cada:
- `abrir_handoff` (origem `agente` ou `pipeline_pix`);
- `atualizar_pix` (estados `em_revisao`, `validado`, `recusado`);
- `devolver_para_ia` (origem `grupo_coordenacao` ou `painel`);
- `registrar_fechado` e `registrar_perdido`.

Modelagem completa em `06-dados-interfaces.md`. Checkpointer LangGraph não substitui esta tabela — é registro humano-legível separado (`07 §2.2`).

### 8.2 Dashboard

Volume de escaladas e motivos agregados aparece no Dashboard P0 (`03 §4.7`). Filtro por `fonte_decisao` é P1 (`02 §3.1`).

### 8.3 Trace LangSmith

Cada turno da IA, incluindo a chamada `escalar`, vira trace em LangSmith. Tags por `conversa_id` e `modelo_id` (`07 §7.5`). Útil para revisão de prompt e calibração; não substitui audit log humano-legível.
