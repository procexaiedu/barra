# Barra Vips MVP

Linguagem de domínio para a central inteligente de atendimento da operação Barra Vips. Este contexto existe para manter consistentes os termos usados entre produto, operação e implementação.

## Language

**Conversa cliente**:
Canal de WhatsApp no próprio número da modelo, onde a IA responde em nome dela até pausar para handoff e onde a modelo pode assumir manualmente.
_Avoid_: chat da modelo, atendimento humano

**Coordenação por modelo**:
Grupo persistente com **2 participantes** — o número da modelo (operado pela IA) e Fernando. A IA envia cards/resumos acionáveis no grupo a partir do número da modelo; a modelo lê os cards no próprio celular porque o número dela está no grupo, sem ter identidade separada. Mensagens manuais da modelo no grupo entram como `fromMe` do mesmo número que a IA opera, e o sistema distingue IA de modelo pelo originador real do envio.
_Avoid_: grupo por atendimento, grupo de acompanhamento, identidade separada da modelo no grupo, grupo com IA + modelo + Fernando como três identidades

**IA Admin (P1)**:
Grupo persistente entre IA e Fernando para alertas de exceção e comandos internos por áudio/texto permitidos. Disponível apenas no P1; no P0, decisões sensíveis chegam a Fernando pelo painel e/ou pela **Coordenação por modelo**.
_Avoid_: grupo da modelo, handoff do vendedor, tratar como infraestrutura P0

**IA por modelo**:
Cada modelo opera no próprio número de WhatsApp e tem uma instância de IA dedicada com persona, FAQ e histórico próprios. Quando um mesmo cliente conversa com modelos diferentes, são instâncias completamente independentes — a IA da modelo A não enxerga, cita ou se apoia em qualquer dado do cliente com a modelo B. A unidade que carrega histórico, recorrência e observações é a **Conversa cliente** (par cliente, modelo), e a recorrência também é avaliada por par.
_Avoid_: perfil único do cliente compartilhado entre IAs, IA citando última profissional contratada por outra modelo, fundir histórico cross-modelo no contexto de uma conversa

**Handoff**:
Pausa da IA para que Fernando decida ou para que a modelo assuma a conversa no mesmo número, sempre com resumo e próxima ação esperada; a IA só retoma por devolução explícita.
_Avoid_: humano genérico

**Devolução para IA**:
Comando explícito que reativa a IA após handoff. Formas válidas: botão `Devolver para IA` no painel (Fernando); `IA assume` / `IA assume #N` no grupo (Fernando ou modelo); `finalizado [valor]` no grupo respondendo ao card, usado pela modelo ao encerrar o atendimento físico — se valor informado, registra `fechado valor` simultaneamente.
_Avoid_: retomada automática

**Registro de resultado**:
Encerramento explícito de um atendimento como fechado ou perdido, feito por Fernando ou modelo no grupo de coordenação, ou por Fernando no painel; fechamento exige valor final.
_Avoid_: inferência durante handoff

**Valor final**:
Valor total bruto pago pelo cliente no atendimento fechado.
_Avoid_: repasse da agência, comissão

**Motivo de perda**:
Razão padronizada para atendimento perdido: `preco`, `sumiu`, `risco`, `indisponibilidade`, `fora_de_area` ou `outro`.
_Avoid_: taxonomia aberta

**Pix de deslocamento**:
Pagamento antecipado do deslocamento de saída, validado automaticamente quando todas as checagens passam e escalado para Fernando quando houver falha ou dúvida.
_Avoid_: sinal, pagamento do atendimento

**Aviso de saída**:
Mensagem do cliente em atendimento interno (cliente vai à modelo) avisando que saiu de casa em direção ao endereço combinado. Primeiro aviso operacional da sequência de confirmação interna; prepara a modelo, mas não confirma o atendimento sozinho.
_Avoid_: equiparar a confirmação automática, equiparar a comprovante financeiro

**Foto de portaria**:
Imagem da portaria (ou local de encontro) do endereço combinado, enviada pelo cliente em atendimento interno. Comprova que o cliente realmente chegou ao local indicado e mitiga clientes que "zoam" sem aparecer; o recebimento da imagem dispara handoff implícito para a modelo: card "cliente chegou" no grupo de Coordenação por modelo com a imagem anexada, IA pausa (`ia_pausada=true`, motivo `modelo_em_atendimento`) e atendimento vai de `Aguardando_confirmacao` direto para `Em_execucao`, sem condicionar a transição a aprovação humana e sem vision automática.
_Avoid_: equiparar a Pix de deslocamento, equiparar a comprovante financeiro, validar por vision automática no P0, condicionar transição de estado a decisão da modelo ou de Fernando, manter IA respondendo o cliente após a chegada

## Relationships

- A **Conversa cliente** pertence a um par cliente-modelo e é conduzida pela IA até o handoff.
- A **IA por modelo** isola persona, histórico, recorrência e observações pelo par cliente-modelo: cada modelo tem IA própria, e a IA de uma modelo não acessa dados do mesmo cliente com outra modelo.
- A **Coordenação por modelo** recebe ações para exatamente uma modelo e inclui Fernando.
- O **IA Admin** (P1) recebe decisões sensíveis para Fernando; no P0 essas decisões chegam pelo painel e/ou pela **Coordenação por modelo**.
- Um **Handoff** aciona a **Coordenação por modelo** no P0; no P1 pode acionar também o **IA Admin**.
- Um **Handoff** deixa a IA pausada até Fernando ou a modelo devolver explicitamente a conversa.
- A **Devolução para IA** muda a responsabilidade de volta para a IA e precisa registrar autor, canal e horário.
- A **Conversa cliente** continua sendo gravada mesmo quando a IA está pausada, sem alertar grupos e sem criar indicador no painel por novas mensagens do cliente.
- Mensagens gravadas durante **Handoff** podem compor resumo e auditoria, mas não geram transição automática de estado.
- O **Registro de resultado** durante **Handoff** usa comandos `fechado valor`/`perdido motivo` no grupo ou botões no painel.
- Comando de **Registro de resultado** sem `#N` só é válido como resposta direta ao card do atendimento; fora disso, `#N` é obrigatório.
- No MVP, comandos de **Registro de resultado** no grupo são aceitos apenas de Fernando ou da modelo; no painel, apenas Fernando opera.
- Comando de **Registro de resultado** válido vindo da modelo é efetivo imediatamente; Fernando corrige depois no painel se necessário.
- Correção de **Registro de resultado** por Fernando recalcula financeiro e ajusta apenas o bloqueio vinculado, pedindo confirmação se precisar alterar bloqueio já `em_atendimento` ou `concluido`.
- Todo **Registro de resultado** aceito por comando no grupo recebe confirmação curta no próprio grupo.
- Comando de **Registro de resultado** inválido, incompleto ou ambíguo recebe erro curto no grupo e não altera atendimento, agenda ou financeiro.
- O valor em `fechado valor` é o **Valor final** bruto; o repasse da agência é calculado separadamente pelo acordo da modelo.
- O **Valor final** aceita formatos comuns brasileiros no comando e é normalizado para decimal; valor ambíguo exige confirmação.
- O percentual de repasse usado no fechamento é um snapshot opcional do acordo da modelo naquele momento; se não estiver cadastrado, o fechamento continua permitido com repasse pendente/nulo.
- Um **Registro de resultado** perdido deve ter exatamente um **Motivo de perda**; `outro` exige observação curta.
- Comando `perdido` sem **Motivo de perda** não encerra o atendimento; o sistema pede complemento.
- Comando `fechado` sem valor final não encerra o atendimento; o sistema pede complemento.
- Quando um **Registro de resultado** fechado é aceito, o bloqueio de agenda vinculado ao atendimento vira `concluido`.
- Quando um **Registro de resultado** perdido é aceito, o bloqueio vinculado vira `cancelado` somente se ainda não estiver `em_atendimento` nem `concluido`.
- Um **Pix de deslocamento** aprovado dispara handoff implícito para a modelo: card "saída confirmada" no grupo de **Coordenação por modelo**, `ia_pausada=true` com motivo `modelo_em_atendimento` e atendimento → `Confirmado`. Um Pix duvidoso gera handoff para Fernando pelo painel e pela **Coordenação por modelo** no P0 (e adicionalmente para o **IA Admin** no P1).
- O **Aviso de saída** prepara a modelo no atendimento interno via card simples, mas a IA continua respondendo o cliente normalmente — o estado segue em `Aguardando_confirmacao`.
- O recebimento da **Foto de portaria** dispara handoff implícito no fluxo interno: card "cliente chegou" no grupo de **Coordenação por modelo**, `ia_pausada=true` com motivo `modelo_em_atendimento` e transição automática de `Aguardando_confirmacao` para `Em_execucao`, sem condicionar a transição a aprovação humana. A inspeção visual da modelo é proteção operacional (antes de abrir a porta) e não gatilha nem bloqueia transição de estado.
- Quando o cliente do fluxo interno enviou **Aviso de saída** mas não enviou **Foto de portaria** dentro de 30 minutos do horário combinado, o atendimento entra em timeout determinístico e é marcado `Perdido` com `motivo_perda=sumiu`, sem mensagem ao cliente; a IA permanece ativa para futuras conversas.
- No P0, a IA não roda vision automática sobre a **Foto de portaria** recebida do cliente; qualquer imagem recebida em `Aguardando_confirmacao` interno é tratada como Foto de portaria sem inspeção de conteúdo.

## Example dialogue

> **Dev:** "Quando o cliente manda o comprovante, a modelo precisa ler a conversa para entender?"
> **Domain expert:** "Não. A IA está no número da modelo e responde o cliente. No handoff, ela para, manda o resumo no grupo, e a modelo escreve para o cliente no mesmo WhatsApp."

## Flagged ambiguities

- "grupo da modelo" pode significar o número usado na conversa com o cliente ou a **Coordenação por modelo**; resolvido: conversa com cliente é **Conversa cliente**, grupo interno é **Coordenação por modelo**.
- "Pix confirmado" não significa revisão humana obrigatória; resolvido: passa automaticamente quando todas as checagens passam, senão vira `pix_em_revisão`.
