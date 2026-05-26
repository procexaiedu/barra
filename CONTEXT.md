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
Cada modelo opera no próprio número de WhatsApp, atendida por uma IA cuja **persona (voz, jeito de falar, comportamento, conduta) e FAQ são gerais — compartilhadas entre todas as modelos**. O sistema não customiza a forma de responder por modelo: todas respondem igual no WhatsApp, mudando só **as coisas dela** — identidade óbvia (nome, idade, etc.), programas/preços, agenda e tipos de atendimento aceitos. O que é **isolado por par cliente-modelo** é o dado do cliente: histórico, recorrência e observações vivem na **Conversa cliente** (par cliente, modelo). Quando um mesmo cliente conversa com modelos diferentes, esses dados são completamente isolados — a IA na modelo A não enxerga, cita ou se apoia em qualquer dado do cliente com a modelo B.
_Avoid_: perfil único do cliente compartilhado entre IAs, IA citando última profissional contratada por outra modelo, fundir histórico cross-modelo no contexto de uma conversa, customizar voz/persona/FAQ por modelo

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

**Preço de tabela**:
Preço cheio cadastrado de um programa da modelo (por duração); é o valor anunciado ao cliente e o teto da negociação.
_Avoid_: confundir com **Valor final**, tratar como valor inegociável

**Desconto de fechamento**:
Redução pontual sobre o **Preço de tabela** de um programa que a IA pode conceder para fechar a venda, até o **Piso de desconto** e em uma única contraproposta; cabe quando o cliente pede (reativo) ou no reengajamento (proativo).
_Avoid_: regateio/negociação livre, desconto recorrente por insistência, desconto sobre o **Pix de deslocamento**, mexer no **Valor final** já fechado

**Piso de desconto**:
Menor valor que a IA pode oferecer sozinha — um percentual único abaixo do **Preço de tabela**; abaixo dele a IA escala (`fora_de_oferta`) em vez de negociar.
_Avoid_: expor o valor ao cliente, tratar como mínimo cadastrado por programa (no P0 é teto percentual único)

**Pix de deslocamento**:
Pagamento antecipado, de **valor fixo**, do deslocamento de saída. O recebimento do comprovante sempre faz o atendimento avançar — **o fluxo nunca trava por Pix**: quando todas as checagens passam é validado em silêncio; quando há divergência ou suspeita o comprovante é marcado como duvidoso, o card à modelo sinaliza a duvidez (ela decide antes de pedir o Uber) e Fernando revisa depois numa fila assíncrona, sem bloquear.
_Avoid_: sinal, pagamento do atendimento, valor proporcional à distância ou ao programa, travar/pausar o fluxo por Pix duvidoso, handoff síncrono para Fernando por Pix

**Aviso de saída**:
Mensagem do cliente em atendimento interno (cliente vai à modelo) avisando que saiu de casa em direção ao endereço combinado. Primeiro aviso operacional da sequência de confirmação interna; prepara a modelo, mas não confirma o atendimento sozinho.
_Avoid_: equiparar a confirmação automática, equiparar a comprovante financeiro

**Foto de portaria**:
Imagem da portaria (ou local de encontro) do endereço combinado, enviada pelo cliente em atendimento interno. Comprova que o cliente realmente chegou ao local indicado e mitiga clientes que "zoam" sem aparecer; o recebimento da imagem dispara handoff implícito para a modelo: card "cliente chegou" no grupo de Coordenação por modelo com a imagem anexada, IA pausa (`ia_pausada=true`, motivo `modelo_em_atendimento`) e atendimento vai de `Aguardando_confirmacao` direto para `Em_execucao`, sem condicionar a transição a aprovação humana e sem vision automática.
_Avoid_: equiparar a Pix de deslocamento, equiparar a comprovante financeiro, validar por vision automática no P0, condicionar transição de estado a decisão da modelo ou de Fernando, manter IA respondendo o cliente após a chegada

**Horário desejado**:
Horário que o cliente pediu na conversa, ainda não confirmado pela operação.
_Avoid_: tratar como reserva firme, confundir com horário combinado

**Horário combinado**:
Horário efetivamente confirmado e reservado para o atendimento, distinto do horário apenas pedido pelo cliente.
_Avoid_: confundir com horário desejado, tratar pedido não confirmado como combinado

**Disponibilidade**:
Conjunto de regras que define quando uma modelo aceita ser reservada — cada regra é um intervalo de datas (com fim opcional/aberto), um dia da semana e uma janela horária. A disponibilidade efetiva é a **união** das regras; um instante só é reservável se alguma regra o cobre. Modelo sem nenhuma regra é reservável sempre. Distinta do **status** da modelo (`ativa`/`pausada`/`inativa`, que liga/desliga a IA), do **bloqueio** (ocupação pontual *dentro* da disponibilidade) e do horário de operação global (quiet-hours do **Reengajamento**). Rótulo na UI: "Período de trabalho".
_Avoid_: confundir com status da modelo, confundir com bloqueio, materializar folga como bloqueio, tratar como horário de operação global

**Reengajamento**:
Reabertura proativa e única de um cliente que recebeu a cotação e silenciou — a IA manda uma mensagem curta e calorosa (sem desconto) ~30 min depois, dentro do horário de operação, para retomar a conversa.
_Avoid_: perseguir o cliente com múltiplos toques, reabrir quem não chegou à cotação, puxar desconto no toque de reabertura, confundir com o timeout de 24h (que encerra como Perdido)

**Lembrete de fechamento**:
Cobrança proativa e determinística do **Valor final** à modelo, no grupo de **Coordenação por modelo**, disparada quando o atendimento passou do fim previsto (`bloqueios.fim`) e ainda está em `Em_execucao`; reenvia em intervalos fixos até um número máximo de toques e, sem resposta, abre **Handoff** para Fernando. A modelo fecha respondendo o card com o valor — mesma porta do `finalizado/fechado [valor]` do **Registro de resultado**.
_Avoid_: cobrança do cliente, confundir com **Reengajamento** (que é voltado ao cliente), interpretar a resposta por IA (no P0 é regex determinístico; NLP de resposta livre é da **IA Admin** P1), confirmação dupla, criar estado novo, marcar `Perdido` automaticamente por silêncio

**Mídia exclusiva**:
Foto/vídeo da modelo enviado durante a venda com enquadramento de exclusividade — primeiro fotos, depois um vídeo apresentado como "gravado ao vivo só para o cliente"; quando a plataforma de envio permitir, o vídeo vai como visualização única (view-once) para proteger o conteúdo.
_Avoid_: enviar vídeo antes de foto, expor que o vídeo "ao vivo" é pré-gravado, prometer view-once sem suporte da plataforma

**Perfil físico preferido**:
Tipo físico que o cliente prefere nas modelos (loira, morena, ruiva, negra, asiática, outra). Dado **global do cliente** (não por par cliente-modelo) e **exclusivo do painel/Fernando**. Tem duas leituras: a **declarada** (Fernando marca uma ou mais no cadastro do cliente) e a **calculada** (breakdown derivado dos atendimentos `Fechado`, agrupados pelo `tipo_fisico` das modelos atendidas — "consumiu 6 ruivas e 2 loiras"), que expõe também quantos fechados são de modelos ainda não classificadas. No P0 só Fernando lê/escreve no painel; a IA conversacional por modelo nunca lê o breakdown (seria agregação cross-modelo, fura o isolamento por par) nem escreve a preferência — a leitura/escrita por linguagem natural é da **IA Admin** (P1). Eixo único: não separa cabelo/etnia/biotipo, e biotipo (sarada/plus) fica de fora. Ver ADR 0006.
_Avoid_: tratar como dado por par cliente-modelo, expor à IA conversacional por modelo, inferir um rótulo único ("prefere X") a partir do breakdown, materializar biotipo nesse eixo, customizar a persona da IA por preferência

## Relationships

- A **Conversa cliente** pertence a um par cliente-modelo e é conduzida pela IA até o handoff.
- A **IA por modelo** compartilha persona/voz/FAQ entre todas as modelos, mas isola os dados do cliente (histórico, recorrência, observações) pelo par cliente-modelo: a IA de uma modelo não acessa dados do mesmo cliente com outra modelo.
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
- O recebimento do comprovante de **Pix de deslocamento** sempre dispara handoff implícito para a modelo: card "saída confirmada" no grupo de **Coordenação por modelo**, `ia_pausada=true` com motivo `modelo_em_atendimento` e atendimento → `Confirmado` — tanto para Pix validado quanto duvidoso (**o fluxo nunca trava por Pix**). Quando o comprovante é duvidoso, o card à modelo **sinaliza a duvidez** (ela decide antes de pedir o Uber) e o caso entra numa **fila assíncrona de revisão de Fernando** no painel; não há handoff síncrono nem pausa esperando decisão de Fernando.
- O **Aviso de saída** prepara a modelo no atendimento interno via card simples, mas a IA continua respondendo o cliente normalmente — o estado segue em `Aguardando_confirmacao`.
- O recebimento da **Foto de portaria** dispara handoff implícito no fluxo interno: card "cliente chegou" no grupo de **Coordenação por modelo**, `ia_pausada=true` com motivo `modelo_em_atendimento` e transição automática de `Aguardando_confirmacao` para `Em_execucao`, sem condicionar a transição a aprovação humana. A inspeção visual da modelo é proteção operacional (antes de abrir a porta) e não gatilha nem bloqueia transição de estado.
- Quando o cliente do fluxo interno enviou **Aviso de saída** mas não enviou **Foto de portaria** dentro de 45 minutos do envio do Aviso de saída, o atendimento entra em timeout determinístico e é marcado `Perdido` com `motivo_perda=sumiu`, sem mensagem ao cliente; a IA permanece ativa para futuras conversas.
- No P0, a IA não roda vision automática sobre a **Foto de portaria** recebida do cliente; qualquer imagem recebida em `Aguardando_confirmacao` interno é tratada como Foto de portaria sem inspeção de conteúdo.
- O **Desconto de fechamento** incide só sobre o **Preço de tabela** do programa, nunca sobre o **Pix de deslocamento** (valor fixo).
- A IA concede **Desconto de fechamento** no máximo uma vez por atendimento: oferece o **Piso de desconto** enquadrado como final e, se o cliente recusa ou insiste por menos, escala (`fora_de_oferta`) em vez de baixar mais.
- Oferecer pacote de duração maior com preço/hora menor (upsell, já no **Preço de tabela**) não é **Desconto de fechamento** — não reduz abaixo da tabela e a IA faz livremente.
- O **Reengajamento** dispara uma única vez por atendimento, só em `Triagem`/`Qualificado` com a cotação já apresentada; se o cliente responde, segue a conversa normal e, se travar no preço, aí entra o **Desconto de fechamento** reativo.
- O **Reengajamento** não reseta o relógio do timeout de 24h (que conta da última mensagem do **cliente**): sem resposta após a reabertura, o atendimento ainda vira `Perdido` (`motivo_perda=sumiu`).
- No P0 o **Reengajamento** é desligável por configuração e começa o piloto desligado, ligando quando a persona e a reputação do número estiverem calibradas.
- A **Mídia exclusiva** entrega a narrativa de exclusividade no P0; o view-once real depende de a plataforma de envio (Evolution) expor o campo na versão self-host — sem suporte, o vídeo vai normal e a proteção fica para o P1.
- Quando o horário pedido cai num bloqueio da agenda, a IA recusa com uma desculpa pessoal coerente com o horário (salão, me arrumando, jantar, balada) e oferece outra janela; **nunca revela que está com outro cliente** (preserva a exclusividade percebida) e nunca para de responder.
- A **Disponibilidade** é gate de criação de **bloqueio**: o sistema valida que o **início** do bloqueio cai numa janela disponível (data ∈ período ∧ dia-da-semana ∧ hora ∈ janela); o fim pode estender além (Pernoite dura 12h e estoura janelas menores).
- Bloqueio fora da **Disponibilidade**: a IA nunca cria nem sugere (trava dura); Fernando vê aviso no painel e pode forçar mesmo assim (override explícito, igual ao confirmar de cancelar bloqueio `em_atendimento`).
- Diferente do bloqueio (onde a IA mente com desculpa pessoal), quando o horário pedido cai **fora da Disponibilidade** (folga/viagem/ainda não começou) a IA **revela a volta e ancora**: assume que está fora, informa quando volta e oferece a primeira data disponível — não há outro cliente a esconder.
- Configurar uma **Disponibilidade** que deixa bloqueios futuros já existentes fora dela salva normalmente e emite alerta não-bloqueante listando-os; nunca deleta nem cancela bloqueio automaticamente.
- O **Perfil físico preferido** vive no nível do cliente (cross-modelo), diferente do histórico/recorrência/observações que são isolados por par cliente-modelo; por isso é exclusivo do painel/Fernando e a **IA por modelo** nunca o acessa (nem a declarada, nem o breakdown calculado).
- A parte **calculada** do **Perfil físico preferido** conta só atendimentos `Fechado`, agrupando pelo `tipo_fisico` das modelos atendidas; modelos sem `tipo_fisico` aparecem como "não classificadas" no breakdown, nunca somem em silêncio, e nenhum rótulo único ("prefere X") é inferido.
- Classificar a modelo por `tipo_fisico` é pré-condição da parte **calculada**: sem classificação o breakdown é parcial mas válido (a parte conhecida + a contagem de não classificadas); modelos existentes nascem sem `tipo_fisico` (sem backfill).
- O filtro de clientes por **Perfil físico preferido** usa só a parte **declarada**, com semântica OR (cliente cujo conjunto declarado contém qualquer um dos selecionados).
- O **Lembrete de fechamento** atua só sobre atendimentos em `Em_execucao` com `bloqueios.fim` no passado (mais a tolerância); reaproveita a porta de **Registro de resultado** (`finalizado/fechado [valor]`) e não cria estado nem transição própria.
- O **Lembrete de fechamento** nunca marca o atendimento como **Perdido** por ausência de resposta: sem confirmação após o máximo de toques, abre **Handoff** para Fernando e o atendimento permanece em `Em_execucao` até fechamento manual.
- Diferente do **Reengajamento** (cliente, toque único, dentro do horário de operação), o **Lembrete de fechamento** fala com a modelo no grupo interno, repete em toques fixos e não respeita quiet-hours.
- A modelo confirma o **Valor final** respondendo (quote) o card do **Lembrete de fechamento** com o valor; é **efetivo imediatamente** (como todo **Registro de resultado** da modelo) e Fernando corrige depois no painel se necessário — não há confirmação dupla.

## Example dialogue

> **Dev:** "Quando o cliente manda o comprovante, a modelo precisa ler a conversa para entender?"
> **Domain expert:** "Não. A IA está no número da modelo e responde o cliente. No handoff, ela para, manda o resumo no grupo, e a modelo escreve para o cliente no mesmo WhatsApp."

## Flagged ambiguities

- "grupo da modelo" pode significar o número usado na conversa com o cliente ou a **Coordenação por modelo**; resolvido: conversa com cliente é **Conversa cliente**, grupo interno é **Coordenação por modelo**.
- "Pix confirmado" não significa revisão humana obrigatória nem bloqueio; resolvido: o fluxo sempre avança — checagens OK validam em silêncio; divergência/suspeita marca o comprovante como duvidoso (`pix_status` informativo, não bloqueante), com sinalização no card à modelo e fila assíncrona de revisão de Fernando, sem travar o atendimento.
- "horário combinado" vs "horário desejado" eram usados como sinônimos; resolvido: **horário desejado** é o pedido não confirmado do cliente; **horário combinado** é o horário confirmado e reservado.
- Referência do timeout interno: o prazo conta a partir do **envio do Aviso de saída** (`aviso_saida_em`), não do horário combinado nem do desejado.
- "desconto" era sempre motivo de escalada ("a IA não negocia", `mvp/05 §14`); resolvido: a IA pode conceder **Desconto de fechamento** até o **Piso de desconto** numa única oferta, escalando só abaixo disso — a regra "escala em vez de negociar" passa a valer apenas para pedidos **abaixo do piso**.
- O plano de reunião pedia "a IA lê/escreve o perfil físico do cliente em linguagem natural"; resolvido: no P0 é painel-only (Fernando), porque a parte calculada é cross-modelo e exporia dados de outras modelos à IA conversacional, furando o isolamento por par; a leitura/escrita por linguagem natural fica para a **IA Admin** (P1). "**Perfil físico preferido**" é global do cliente; não confundir com as **observações**, que são por par cliente-modelo.
- A task de confirmação de valor pós-atendimento falava em "mensagem para a modelo via WhatsApp da modelo" e "IA administrativa processa a resposta"; resolvido: o canal é a **Coordenação por modelo** (a modelo não tem identidade/DM separada) e a interpretação é determinística (regex de `finalizado/fechado [valor]`), não IA — NLP de resposta livre fica para a **IA Admin** (P1). O gatilho é o fim previsto do atendimento (`bloqueios.fim` + tolerância), não a entrada em `Em_execucao`. Ver **Lembrete de fechamento**.
