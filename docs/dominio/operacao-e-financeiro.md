# Domínio — operação humana, financeiro e Combo de grupo

Verbetes extraídos do `CONTEXT.md` para não pesarem no contexto de toda sessão. São os termos que a **IA conversacional não usa na venda** — vivem no painel, no grupo interno, na operação humana ou em feature ainda não implementada.

O `CONTEXT.md` mantém os ponteiros e os invariantes que tocam a conduta da IA; aqui fica a definição completa. **Mesma regra de precedência:** onde divergir de um ADR não-superseded, o ADR vence.

## Operação humana

**Operador**:
Quem opera o **painel** — **Fernando** e a **sócia**, **permissão idêntica** (sem RBAC no P0; ambos `papel='fernando'`). Por convenção escreve-se **"Fernando"** para qualquer operador. Distinto do **Vendedor** (sem login) e do **Responsável** de **Tarefa** (rótulo de execução, sem login).
_Avoid_: ler "Fernando" como exclusão da sócia; confundir com **Vendedor** ou **Responsável**; supor RBAC no P0.

**Vendedor**:
Pessoa que hoje opera o WhatsApp da modelo respondendo o cliente em nome dela (se passando por ela) — o **respondente humano** do número, papel que a **IA por modelo** assume aos poucos. Sem login no painel; é cadastro gerido por Fernando/sócia, com um **nível** (iniciante/intermediário/avançado) que define a **Comissão de vendedor**. Cada modelo tem um vendedor padrão; o atendimento o herda e Fernando pode sobrescrever quando outro cobriu o turno. Atendimento conduzido pela IA não tem vendedor.
_Avoid_: tratar como login/usuário; confundir com a **modelo** (o vendedor se passa por ela); confundir com o papel `vendedor_read_only` (P1); atribuir vendedor a atendimento da IA.

**Comissão de vendedor**:
Percentual que o **Vendedor** recebe sobre os `Fechado` que conduziu, pelo seu **nível** (ref. 4/5/6%, configurável). Incide sobre o **valor líquido de taxa de cartão** (mesma base do repasse da modelo), nunca sobre o bruto inflado pela taxa; é custo **independente** do repasse (ambos saem do mesmo valor, não um do outro).
_Avoid_: confundir com o repasse; calcular sobre o **Valor final** bruto quando há taxa; comissionar `Perdido` ou atendimento da IA.

## Grupo interno e comandos

**Coordenação por modelo**:
Grupo persistente com **2 participantes** — o número da modelo (operado pela IA) e Fernando. A IA envia cards/resumos acionáveis a partir do número da modelo; a modelo lê no próprio celular, sem identidade separada. Mensagens manuais da modelo entram como `fromMe` do mesmo número que a IA opera; o sistema distingue IA de modelo pelo originador real do envio.
_Avoid_: grupo por atendimento; grupo de acompanhamento; identidade separada da modelo; grupo com IA + modelo + Fernando como três identidades.

**Card**:
Mensagem estruturada e acionável que a IA envia na **Coordenação por modelo**, a partir do número da modelo — **resumo + próxima ação** — referente a um **Atendimento**. Unidade visível do **Handoff** e dos avisos proativos ("saída confirmada", "cliente chegou", **Lembrete de fechamento**). Age-se **respondendo (quote) o card**: `IA assume`, `finalizado/fechado [valor]`, `perdido [motivo]`. Comando **sem `#N`** só vale como resposta direta a um card; fora disso `#N` é obrigatório. Idempotência por `card_message_id` (por owner). Quando abre handoff que aguarda decisão humana, o registro é uma **Escalada**; mas há cards meramente informativos.
_Avoid_: confundir com mensagem da **Conversa cliente** (o card vive no grupo interno); tratar todo card como Escalada/Handoff pendente; tratar como notificação passiva.

**Devolução para IA**:
Comando explícito que reativa a IA após handoff; registra autor, canal e horário. Formas: botão `Devolver para IA` no painel (Fernando); `IA assume` / `IA assume #N` no grupo (Fernando ou modelo); `finalizado [valor]` respondendo ao card, usado pela modelo ao encerrar — se há valor, registra `fechado valor` simultaneamente.
_Avoid_: retomada automática.

**Registro de resultado**:
Encerramento explícito de um atendimento como fechado ou perdido, por Fernando ou modelo no grupo, ou por Fernando no painel; fechamento exige valor final. No grupo, só Fernando ou a modelo comandam; o comando da modelo é **efetivo imediatamente** (Fernando corrige depois no painel, recalculando financeiro e ajustando só o bloqueio vinculado — pede confirmação para alterar bloqueio já `em_atendimento`/`concluido`). Comando válido recebe confirmação curta no grupo; inválido/incompleto/ambíguo recebe erro curto e não altera nada. `fechado` sem valor ou `perdido` sem motivo não encerram — o sistema pede complemento.
_Avoid_: inferência durante handoff.

**Lembrete de fechamento**:
Cobrança proativa e determinística do **Valor final** à modelo, na **Coordenação por modelo**, quando o atendimento passou de `bloqueios.fim` e segue em `Em_execucao`. Reenvia em intervalos fixos até um máximo de toques; sem resposta, abre **Handoff** para Fernando (nunca marca `Perdido` por silêncio; permanece em `Em_execucao` até fechamento manual). A modelo fecha respondendo o card com o valor — mesma porta do `finalizado/fechado [valor]`, efetivo imediatamente. Não respeita quiet-hours.
_Avoid_: cobrança do cliente; confundir com **Reengajamento** (que é voltado ao cliente); interpretar a resposta por IA (no P0 é regex; NLP livre é **IA Admin** P1); confirmação dupla; criar estado novo; marcar `Perdido` automaticamente.

## Financeiro

**Valor final**:
Valor total bruto pago pelo cliente no atendimento fechado. Aceita formatos brasileiros no comando e é normalizado para decimal; valor ambíguo exige confirmação. O repasse da agência é calculado à parte pelo acordo da modelo (snapshot opcional no fechamento; se não cadastrado, fecha com repasse pendente/nulo).
_Avoid_: confundir com repasse da agência ou comissão.

**Taxa de cartão**:
Acréscimo percentual (ref. 10%, configurável) cobrado **por cima** do valor do serviço no pagamento por cartão, para cobrir a maquininha; **isentável** por atendimento. O **Valor final** passa a incluir a taxa; o valor do serviço (base de repasse e **Comissão de vendedor**) é o **Valor final** menos a taxa. O custo real do gateway vive fora do sistema no P0. Ver ADR 0013.
_Avoid_: incidir sobre o **Pix de deslocamento**; entrar na base de repasse/comissão; tratar a taxa como receita garantida.

**`Fechado` é a base**:
- Repasse da modelo e **Comissão de vendedor** são custos **independentes** sobre o mesmo valor líquido de taxa de cartão; nenhum desconta o outro; só `Fechado` contam (igual à receita do Módulo Financeiro).
- Cada modelo tem **Vendedor** padrão (`modelos.vendedor_id`); o atendimento o herda e Fernando pode sobrescrever. Quando a IA assume a modelo, o padrão fica nulo e os atendimentos dela não geram comissão.

## Combo de grupo (vocabulário; não implementado no P0)

**Combo de grupo**:
Conjunto de **Atendimentos irmãos** nascidos de uma única negociação: **um mesmo cliente** contrata, na mesma janela e no mesmo endereço, **modelos distintas** — uma para cada homem do grupo dele (evento, despedida de solteiro, viagem a negócios). Não é um Atendimento: é o **laço** entre vários, e cada um deles segue com seu próprio estado, `#N`, valor e agenda. O cliente registrado em **todos** é o **comprador** (quem negociou); os outros homens que de fato encontram as convidadas **não viram dado no sistema** — mesma leitura do **Menage** caso (a), invertida. A negociação inteira acontece num único WhatsApp, o da **Modelo do canal**. Vale nos dois tipos presenciais, com uma restrição no **interno**: só compõem o combo convidadas que dividem o **mesmo endereço de encontro** do canal (o hotel, em unidades diferentes) — grupo espalhado por endereços distintos não é combo. Nunca no **remoto**. Morte de um irmão **não** derruba os outros (um amigo desistiu, os demais seguem); a exceção é o atendimento **do canal**, cuja perda cascateia o combo inteiro — quem negociou evaporou.
_Avoid_: confundir com **Menage** (lá são 2+ pessoas com a MESMA modelo, um atendimento e preço dobrado; aqui é 1 modelo por pessoa, N atendimentos e N preços); registrar os amigos como Clientes; tratar o combo como um Atendimento com várias modelos; supor estado agregado próprio (o estado vive em cada Atendimento).

**Modelo do canal** / **Modelo convidada**:
Os dois papéis dentro de um **Combo de grupo**. A **Modelo do canal** é aquela cujo número o cliente procurou: é a única que conversa com ele, e a **IA por modelo** dela conduz a venda do combo inteiro — cota, fecha e reserva também as convidadas. A **Modelo convidada** é cada outra modelo incluída: **nunca fala com o cliente**, tem a agenda reservada pela IA do canal e fica sabendo pelo **Card** na sua própria **Coordenação por modelo**. Papel é por combo, não atributo da modelo: a mesma mulher é canal numa noite e convidada na outra. Cada convidada cobra o **Preço de tabela dela** (nunca o do canal), e a **Comissão de vendedor**/repasse seguem por atendimento, como sempre.
_Avoid_: a convidada conversar com o cliente ou receber o contato dele; a IA do canal dar **Desconto de fechamento** sobre o preço da convidada (autoridade de preço é de cada uma); tratar canal/convidada como cadastro fixo da modelo; achar que o cliente vira dado da convidada além do próprio par.

## Salvaguarda do piloto (temporária)

**Cancelamento automático do piloto** (REMOVIDO em 2026-08-07, ADR-0036):
Salvaguarda **temporária** do piloto de teste que, depois de o cliente confirmar o horário, matava o Atendimento antes de ele virar encontro real — desculpa genérica ao cliente, `Perdido` (`outro`) e IA pausada. Revogada: nenhum atendimento é cancelado automaticamente, o freio é humano (**Handoff** manual). Mecânica do que existiu: ADR 0033 + `docs/specs/0004`.
_Avoid_: tratar como mecanismo vivo (não existe mais código nem flag); reintroduzir sem novo ADR.

## Ambiguidades sinalizadas (destes verbetes)

- **"Fernando"** = convenção para qualquer **Operador** (Fernando ou a sócia, permissão idêntica — ADR 0012); menções específicas seguem válidas onde o contexto deixa claro. Sem RBAC no P0.
- **Perfil físico preferido** por linguagem natural pela IA: no P0 é painel-only (Fernando); a parte calculada é cross-modelo e furaria o isolamento por par — leitura/escrita por NL fica para a **IA Admin** (P1). É global do cliente; não confundir com as **observações** (por par).
- **confirmação de valor pós-atendimento**: canal é a **Coordenação por modelo** (a modelo não tem DM separada), interpretação determinística (regex de `finalizado/fechado [valor]`); NLP livre é **IA Admin** (P1). Gatilho = `bloqueios.fim` + tolerância, não a entrada em `Em_execucao`. Ver **Lembrete de fechamento**.
- **"a IA atende o cliente"** descreve o papel do agente (em construção), não nega o **Vendedor** humano de hoje — ambos ocupam o mesmo assento (respondente do número), um hoje, a outra no futuro. A comissão existe para a operação humana e some no atendimento da IA. Ver ADR 0012.

## Example dialogue

> **Dev:** "Quando o cliente manda o comprovante, a modelo precisa ler a conversa para entender?"
> **Domain expert:** "Não. A IA está no número da modelo e responde o cliente. No handoff, ela para, manda o resumo no grupo, e a modelo escreve para o cliente no mesmo WhatsApp."
