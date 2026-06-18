# Elite Baby MVP

Linguagem de domínio da central inteligente de atendimento da operação Elite Baby — mantém consistentes os termos entre produto, operação e implementação.

> **Precedência:** reflete os ADRs vigentes (`docs/adr/`). Onde divergir de um ADR não-superseded, o ADR vence e este arquivo deve ser corrigido. Regra completa de fonte de verdade no `CLAUDE.md`.

## Language

**Modelo**:
A profissional cadastrada que opera no **próprio número de WhatsApp**, atendida pela **IA por modelo**. Tem `status` (`ativa`/`pausada`/`inativa`, liga/desliga a IA) e é o eixo das **"coisas dela"**: identidade (nome, idade, idiomas), **programas** e preços, **Disponibilidade**, tipos de atendimento aceitos, **Fetiches**, **tipo físico** (balde de venda, painel-only) e **Dados cadastrais** (ficha pessoal, painel-only). **Persona, voz e FAQ são gerais** — não variam por modelo. Tem um **Vendedor** responsável padrão e um acordo de repasse (`percentual_repasse`).
_Avoid_: confundir a entidade **Modelo** com o *model* do LLM ou com `modelos.py` (DTOs); customizar persona/voz/FAQ por modelo; expor à IA os **Dados cadastrais** ou o **tipo físico** como persona.

**Cliente**:
Pessoa que contata uma modelo pelo WhatsApp, identificada pelo **telefone** (E.164, único — dois números são dois clientes, sem dedup por pessoa). Entidade **global** (uma linha por número), mas o dado **operacional** — histórico, recorrência, observações — é **isolado por par cliente-modelo** na **Conversa cliente**, e a **IA por modelo** nunca o cruza entre modelos. Os poucos atributos **globais** (**Perfil físico preferido**, posição no **Mapa de clientes**) são **painel-only/Fernando**.
_Avoid_: tratar histórico/recorrência/observações como globais (são por par); deduplicar por pessoa (a chave é o telefone); expor atributos globais à IA.

**Operador**:
Quem opera o **painel** — **Fernando** e a **sócia**, **permissão idêntica** (sem RBAC no P0; ambos `papel='fernando'`). Por convenção escreve-se **"Fernando"** para qualquer operador. Distinto do **Vendedor** (sem login) e do **Responsável** de **Tarefa** (rótulo de execução, sem login).
_Avoid_: ler "Fernando" como exclusão da sócia; confundir com **Vendedor** ou **Responsável**; supor RBAC no P0.

**Conversa cliente**:
**Thread persistente** de um par cliente-modelo (uma por par) no número da modelo, onde a IA responde em nome dela até pausar para handoff e onde a modelo pode assumir manualmente. Guarda histórico, recorrência e observações; **sobrevive a vários atendimentos** ao longo do tempo. Continua gravando mesmo com IA pausada, sem alertar grupos nem criar indicador no painel.
_Avoid_: chamar de chat da modelo ou atendimento humano; confundir com o **Atendimento** (a thread não é o ciclo comercial).

**Atendimento**:
Ciclo comercial de uma negociação cliente-modelo: nasce em `Novo`, percorre os **Estados do atendimento** e encerra em `Fechado`/`Perdido`. **No máximo um aberto por par** (terminais não restringem); recorrência abre um **novo** dentro da mesma **Conversa cliente**. Identificado por **número curto sequencial por modelo** (`#N`, usado nos comandos do grupo). Carrega o eixo **interno/externo**, **Valor final**, **Vendedor**, o **bloqueio** de agenda e o estado de pausa da IA. Recebe **Registro de resultado**, **Handoff**, **Pix de deslocamento** e timeouts.
_Avoid_: confundir com a **Conversa cliente**; tratar como dado global do cliente (é por par e por ciclo); dois atendimentos abertos no mesmo par; reusar `#N` entre modelos.

**Estados do atendimento**:
Máquina de estados linear (mecânica em `docs/mvp/03`); terminais `Fechado`/`Perdido`.
- `Novo` — primeiro contato, antes de triagem.
- `Triagem` — IA coletando intenção e dados mínimos.
- `Qualificado` — intenção real demonstrada (quer marcar) e **tipo definido**; a cotação já costuma ter sido apresentada (carimbada à parte em `cotacao_enviada_em`, ADR 0022, não é gate desta transição). O **horário ainda não está cravado** — é o que falta para `Aguardando_confirmacao`.
- `Aguardando_confirmacao` — **horário combinado** (gatilho desta transição; cria o **bloqueio prévio**) e aguarda **Pix de deslocamento** (externo), **Foto de portaria** (interno), o **horário do encontro** (externo-pickup, ADR 0020) ou o **horário da vídeo chamada** (remoto, ADR 0021). O **Aviso de saída** é informativo, não muda o estado.
- `Confirmado` — externo: **Pix recebido** (validado **ou** duvidoso — nunca trava por Pix); IA pausada (`modelo_em_atendimento`), modelo conduz.
- `Em_execucao` — modelo engajada: **Foto de portaria** recebida (interno) ou horário previsto chegou (externo).
- `Fechado` — convertido por **Registro de resultado** (exige **Valor final**).
- `Perdido` — não converteu, por registro explícito ou timeout determinístico (exige **Motivo de perda**).
_Avoid_: tratar revisão de Pix como estado (é `pix_status=em_revisao`, atendimento ainda em `Aguardando_confirmacao`/`Confirmado`); condicionar `Confirmado` a Pix sem dúvida; inventar estados intermediários no P0.

**Atendimento interno, externo ou remoto**:
Eixo (`tipo_atendimento`) que define quem se desloca — ou se ninguém se desloca:
- **interno** — o cliente vai até a modelo; o endereço é o **ponto de encontro na modelo**, não onde o cliente mora. A IA passa o **endereço completo (rua + número/complemento + referência) quando o horário fecha**, numa fase só, para o cliente chegar direto (ADR 0023; antes era em duas fases, com o número reservado para a portaria). Antes do horário fechar, no máximo a região. Confirma a chegada pela **Foto de portaria**. Fica **fora do Mapa de clientes**. Sem Pix de deslocamento.
- **externo** — a modelo se desloca; o **Pix de deslocamento** (valor fixo) antecipa o custo, e o endereço é a localização do cliente — geocodificada e plotada no **Mapa de clientes**. Subcaso: o **cliente busca a modelo** de carro (rolê/casa dele) — segue externo, mas **sem Pix de deslocamento** (não há Uber dela para antecipar); o endereço que a IA passa é o **ponto de encontro** dela (rua + referência, nunca porta/apartamento), informado quando o horário fecha. No pickup o atendimento avança sem `Confirmado`: a extração reserva o slot (`Aguardando_confirmacao`) e, na hora do encontro, a IA pausa com card "Cliente vem te buscar". Ver ADR 0020.
- **remoto** — ninguém se desloca: o serviço é uma **Vídeo chamada** ao vivo. Sem local físico, **fora do Mapa de clientes**, **sem Pix** e sem Foto de portaria. A extração reserva o slot (`Aguardando_confirmacao` + bloqueio prévio, como o interno, só pelo horário) e, na hora marcada, a IA pausa com o card "Hora da sua vídeo chamada"; pula `Confirmado`. Pagamento combinado manualmente pela modelo (P0). Ver ADR 0021.

A modelo declara os tipos que aceita (`tipo_atendimento_aceito[]`, pode ser mais de um); cada atendimento fixa exatamente um. A IA nunca negocia um tipo que a modelo não realiza.
_Avoid_: tratar interno como localização do cliente; revelar o endereço (mesmo a rua) antes do horário fechar (antes do fechamento, só a região); exigir Pix no interno/remoto ou Foto de portaria no externo/remoto; exigir Pix quando o cliente busca a modelo; plotar interno ou remoto no Mapa; misturar remoto e presencial no mesmo atendimento.

**Coordenação por modelo**:
Grupo persistente com **2 participantes** — o número da modelo (operado pela IA) e Fernando. A IA envia cards/resumos acionáveis a partir do número da modelo; a modelo lê no próprio celular, sem identidade separada. Mensagens manuais da modelo entram como `fromMe` do mesmo número que a IA opera; o sistema distingue IA de modelo pelo originador real do envio.
_Avoid_: grupo por atendimento; grupo de acompanhamento; identidade separada da modelo; grupo com IA + modelo + Fernando como três identidades.

**IA Admin (P1)**:
Grupo persistente entre IA e Fernando para alertas de exceção e comandos internos. Só no P1; no P0, decisões sensíveis chegam pelo painel e/ou pela **Coordenação por modelo**.
_Avoid_: grupo da modelo; handoff do vendedor; tratar como infra P0.

**IA por modelo**:
Cada modelo opera no próprio número, atendida por uma IA cuja **persona (voz, jeito, conduta) e FAQ são gerais — compartilhadas entre todas**. Não se customiza a forma de responder por modelo: muda só **as coisas dela** (identidade óbvia, programas/preços, agenda, tipos aceitos). O dado do cliente (histórico, recorrência, observações) é **isolado por par** na **Conversa cliente**: a IA na modelo A nunca enxerga, cita ou se apoia em dado do cliente com a modelo B.
_Avoid_: perfil único do cliente entre IAs; IA citando profissional contratada por outra modelo; fundir histórico cross-modelo; customizar voz/persona/FAQ por modelo.

**Vendedor**:
Pessoa que hoje opera o WhatsApp da modelo respondendo o cliente em nome dela (se passando por ela) — o **respondente humano** do número, papel que a **IA por modelo** assume aos poucos. Sem login no painel; é cadastro gerido por Fernando/sócia, com um **nível** (iniciante/intermediário/avançado) que define a **Comissão de vendedor**. Cada modelo tem um vendedor padrão; o atendimento o herda e Fernando pode sobrescrever quando outro cobriu o turno. Atendimento conduzido pela IA não tem vendedor.
_Avoid_: tratar como login/usuário; confundir com a **modelo** (o vendedor se passa por ela); confundir com o papel `vendedor_read_only` (P1); atribuir vendedor a atendimento da IA.

**Comissão de vendedor**:
Percentual que o **Vendedor** recebe sobre os `Fechado` que conduziu, pelo seu **nível** (ref. 4/5/6%, configurável). Incide sobre o **valor líquido de taxa de cartão** (mesma base do repasse da modelo), nunca sobre o bruto inflado pela taxa; é custo **independente** do repasse (ambos saem do mesmo valor, não um do outro).
_Avoid_: confundir com o repasse; calcular sobre o **Valor final** bruto quando há taxa; comissionar `Perdido` ou atendimento da IA.

**Handoff**:
Pausa da IA para Fernando decidir ou a modelo assumir a conversa no mesmo número, sempre com resumo e próxima ação; a IA só retoma por **Devolução** explícita. Mensagens gravadas durante o handoff compõem resumo/auditoria mas não geram transição automática de estado.
_Avoid_: humano genérico.

**Card**:
Mensagem estruturada e acionável que a IA envia na **Coordenação por modelo**, a partir do número da modelo — **resumo + próxima ação** — referente a um **Atendimento**. Unidade visível do **Handoff** e dos avisos proativos ("saída confirmada", "cliente chegou", **Lembrete de fechamento**). Age-se **respondendo (quote) o card**: `IA assume`, `finalizado/fechado [valor]`, `perdido [motivo]`. Comando **sem `#N`** só vale como resposta direta a um card; fora disso `#N` é obrigatório. Idempotência por `card_message_id` (por owner). Quando abre handoff que aguarda decisão humana, o registro é uma **Escalada**; mas há cards meramente informativos.
_Avoid_: confundir com mensagem da **Conversa cliente** (o card vive no grupo interno); tratar todo card como Escalada/Handoff pendente; tratar como notificação passiva.

**Devolução para IA**:
Comando explícito que reativa a IA após handoff; registra autor, canal e horário. Formas: botão `Devolver para IA` no painel (Fernando); `IA assume` / `IA assume #N` no grupo (Fernando ou modelo); `finalizado [valor]` respondendo ao card, usado pela modelo ao encerrar — se há valor, registra `fechado valor` simultaneamente.
_Avoid_: retomada automática.

**Registro de resultado**:
Encerramento explícito de um atendimento como fechado ou perdido, por Fernando ou modelo no grupo, ou por Fernando no painel; fechamento exige valor final. No grupo, só Fernando ou a modelo comandam; o comando da modelo é **efetivo imediatamente** (Fernando corrige depois no painel, recalculando financeiro e ajustando só o bloqueio vinculado — pede confirmação para alterar bloqueio já `em_atendimento`/`concluido`). Comando válido recebe confirmação curta no grupo; inválido/incompleto/ambíguo recebe erro curto e não altera nada. `fechado` sem valor ou `perdido` sem motivo não encerram — o sistema pede complemento.
_Avoid_: inferência durante handoff.

**Valor final**:
Valor total bruto pago pelo cliente no atendimento fechado. Aceita formatos brasileiros no comando e é normalizado para decimal; valor ambíguo exige confirmação. O repasse da agência é calculado à parte pelo acordo da modelo (snapshot opcional no fechamento; se não cadastrado, fecha com repasse pendente/nulo).
_Avoid_: confundir com repasse da agência ou comissão.

**Taxa de cartão**:
Acréscimo percentual (ref. 10%, configurável) cobrado **por cima** do valor do serviço no pagamento por cartão, para cobrir a maquininha; **isentável** por atendimento. O **Valor final** passa a incluir a taxa; o valor do serviço (base de repasse e **Comissão de vendedor**) é o **Valor final** menos a taxa. O custo real do gateway vive fora do sistema no P0. Ver ADR 0013.
_Avoid_: incidir sobre o **Pix de deslocamento**; entrar na base de repasse/comissão; tratar a taxa como receita garantida.

**Motivo de perda**:
Razão padronizada: `preco`, `sumiu`, `risco`, `indisponibilidade`, `fora_de_area` ou `outro`. Perdido exige exatamente um; `outro` exige observação curta.
_Avoid_: taxonomia aberta.

**Programa e duração**:
Eixos do cardápio de venda. **Programa** = tipo de serviço (catálogo **global** curado, por *categoria* — ex. "Atendimento ao casal"); **Duração** = janela de tempo (catálogo **global**; **Pernoite** = 12h é a maior). A modelo monta o cardápio escolhendo combinações **programa × duração** e fixando o **Preço de tabela** de cada (`modelo_programas`). Vários serviços juntos → **duração sugerida = MAX** das horas, não soma.
_Avoid_: tratar o catálogo como dado por modelo (global; por modelo é só o preço e quais combinações ela oferece); somar durações; confundir programa (tem duração) com **Fetiche** (extra sem duração).

**Preço de tabela**:
Preço cheio cadastrado de um programa da modelo (por duração); valor anunciado ao cliente e teto da negociação.
_Avoid_: confundir com **Valor final**; tratar como inegociável.

**Fetiche**:
Ato/serviço íntimo que a modelo **realiza ou não** — cardápio da própria modelo, apresentado **dentro do campo de serviços** como extra **sem duração** e com **preço opcional**: sem preço = **incluso**; com preço = **extra pago** que a IA cota ("+R$X"). Catálogo **global** curado + vínculo por modelo (o que faz + preço); é "coisa dela" que a IA usa na venda para responder "você faz X?", cotar o extra e **recusar de forma aberta** o que não está na lista. Pode entrar na composição do atendimento (snapshot de preço), mas **não auto-soma o Valor final** (segue manual) — entra só no breakdown; o **Desconto de fechamento** incide sobre o **pacote** (programa + extras), nunca sobre o **Pix**. Ver ADR 0014.
_Avoid_: "feitiço" (use **Fetiche**); confundir com tipo de atendimento ou com a ficha cadastral (que a IA não lê); tratar como programa com duração; auto-somar o **Valor final**; tratar como dado de cliente (é da modelo).

**Desconto de fechamento**:
Redução pontual sobre o **Preço de tabela** que a IA concede para fechar, até o **Piso de desconto** e em **uma única** contraproposta (reativo quando o cliente pede, proativo no reengajamento). Oferecer pacote de duração maior com preço/hora menor (upsell, já na tabela) **não** é desconto — a IA faz livremente.
_Avoid_: regateio/negociação livre; desconto recorrente por insistência; desconto sobre o **Pix**; mexer no **Valor final** já fechado.

**Piso de desconto**:
Menor valor que a IA oferece sozinha — percentual único abaixo do **Preço de tabela**; abaixo dele escala (`fora_de_oferta`) em vez de negociar.
_Avoid_: expor o valor ao cliente; tratar como mínimo por programa (no P0 é teto percentual único).

**Pix de deslocamento**:
Pagamento antecipado, de **valor fixo**, do deslocamento de saída. Existe **apenas quando a modelo se desloca por conta própria** (Uber até o cliente); cliente que **busca a modelo** de carro é externo **sem Pix**, e a **Vídeo chamada** (remoto) é **sem Pix** — não há deslocamento dela para antecipar. O comprovante sempre faz o atendimento avançar — **nunca trava por Pix**: checagens OK validam em silêncio; divergência/suspeita marca o comprovante como duvidoso, o card à modelo sinaliza a duvidez (ela decide antes de pedir o Uber) e Fernando revisa depois numa fila assíncrona, sem bloquear.
_Avoid_: sinal; pagamento do atendimento; valor proporcional à distância/programa; cobrar quando o cliente busca a modelo; travar o fluxo por Pix duvidoso; handoff síncrono para Fernando por Pix.

**Aviso de saída**:
Mensagem do cliente em atendimento interno avisando que saiu de casa rumo ao endereço combinado. Primeiro aviso operacional da sequência interna; prepara a modelo (card simples) mas não confirma o atendimento, e a IA continua respondendo o cliente normalmente (estado segue em `Aguardando_confirmacao`).
_Avoid_: equiparar a confirmação automática ou a comprovante financeiro.

**Foto de portaria**:
Imagem da portaria/local de encontro, enviada pelo cliente em atendimento interno; comprova que chegou e mitiga quem "zoa". O recebimento dispara handoff implícito: card "cliente chegou" na **Coordenação por modelo** com a imagem, `ia_pausada=true` (motivo `modelo_em_atendimento`) e transição automática `Aguardando_confirmacao` → `Em_execucao`, sem aprovação humana e **sem vision automática no P0** (qualquer imagem em `Aguardando_confirmacao` interno é tratada como Foto de portaria). A inspeção visual da modelo é proteção operacional, não gatilha nem bloqueia transição.
_Avoid_: equiparar a Pix ou comprovante financeiro; vision automática no P0; condicionar a transição à decisão de modelo/Fernando; manter IA respondendo após a chegada.

**Horário desejado**:
Horário que o cliente pediu, ainda não confirmado.
_Avoid_: tratar como reserva firme; confundir com horário combinado.

**Horário combinado**:
Horário efetivamente confirmado e reservado.
_Avoid_: confundir com horário desejado; tratar pedido não confirmado como combinado.

**Bloqueio**:
Reserva pontual da agenda — intervalo (`inicio`–`fim`) que torna a modelo indisponível. Pode ser **vinculado a um Atendimento** (reserva do horário combinado, criada pela IA na qualificação — *bloqueio prévio*, antes do Pix) ou **avulso** (`atendimento_id` nulo: compromisso pessoal, indisponibilidade manual). Dois bloqueios **ativos** (`bloqueado`/`em_atendimento`) não podem se sobrepor para a mesma modelo. Além da não-sobreposição, há um **buffer de preparo/intervalo** (`agenda_buffer_min`, ref. 30 min, ADR 0025): a IA nunca reserva dentro do buffer a partir de **agora** (antecedência mínima — casa com o `horario_minimo` que ela oferece) nem **colado** num bloqueio vizinho (gap ≥ buffer; adjacência `fim == inicio` deixa de ser reservável). É **invisível** (checagem na criação, não materializa blocos). A IA trava (reoferece); **Fernando força no painel** (`confirmar_buffer`, alerta não-bloqueante, como o override fora da Disponibilidade). Ciclo: `bloqueado` → `em_atendimento` → `concluido`/`cancelado`. O **Registro de resultado** sincroniza o vinculado: `Fechado` → `concluido`; `Perdido` → `cancelado` (só se ainda não `em_atendimento`/`concluido`). Criado **dentro** da **Disponibilidade** (gate), coisa distinta dela.
_Avoid_: confundir com **Disponibilidade** ou com o `status` da modelo; materializar folga recorrente como bloqueio (folga = ausência de regra); sobrepor bloqueios ativos; materializar o buffer como bloco visível de preparo/descanso.

**Disponibilidade**:
Regras que definem quando a modelo aceita ser reservada — cada regra é um intervalo de datas (fim opcional/aberto), um dia da semana e uma janela horária. A efetiva é a **união** das regras; um instante só é reservável se alguma regra o cobre. Modelo sem nenhuma regra é reservável sempre. É **gate de criação de bloqueio**: valida que o **início** cai numa janela disponível (data ∈ período ∧ dia-da-semana ∧ hora ∈ janela); o fim pode estender além (Pernoite estoura janelas menores). Distinta do `status` da modelo, do **bloqueio** e do horário de operação global (quiet-hours do **Reengajamento**). Rótulo na UI: "Período de trabalho". Ver ADR 0005.
_Avoid_: confundir com status, bloqueio ou horário de operação global; materializar folga como bloqueio.

**Reengajamento**:
Reabertura proativa **única** de um cliente que recebeu a cotação e silenciou — mensagem curta e calorosa (sem desconto) ~30 min depois, dentro do horário de operação. Gatilho ancorado no **evento real da cotação** (`cotacao_enviada_em`, carimbado quando a IA apresenta o preço): só em `Triagem`/`Qualificado`, com cotação apresentada e **nenhuma resposta do cliente desde então** — o relógio conta da cotação, não de proxy de intenção (ADR 0022). Não reseta o timeout de 24h (que conta da última msg do **cliente**): sem resposta, vira `Perdido` (`sumiu`). No P0 é desligável e começa o piloto **desligado**.
_Avoid_: múltiplos toques; reabrir quem não chegou à cotação; desconto no toque; confundir com o timeout de 24h; confundir com a **Reativação** (campanha manual de cliente dormente, P1).

**Reativação (P1)**:
Disparo em massa **iniciado por Fernando** no painel que reabre clientes **dormentes** de uma modelo para buscar um **segundo atendimento** — toque quente e curto (**sem desconto**), enviado pelo número da própria modelo (IA), só a clientes que **já tiveram atendimento com ELA** e não voltaram. **Respeita o isolamento por par**: a IA da modelo X só toca clientes do par (cliente, X), **nunca cross-modelo** (ao contrário do **Mapa de clientes**/**Perfil físico preferido**, painel-only). Fernando escolhe o segmento (só `Fechado`, ou incluir `Perdido`/`sumiu`); quando o cliente responde, a IA conduz um **novo Atendimento** (recorrência) nas regras normais — qualquer desconto sai da negociação da IA, não da campanha. **No P0 não existe; planejada para P1.**
_Avoid_: confundir com **Reengajamento** (automático, por atendimento aberto silenciado pós-cotação, vs. campanha manual por cliente dormente); disparo cross-modelo (fura o isolamento por par); promo/desconto autônomo da IA no toque; tratar o toque como abertura de **Atendimento** (o atendimento nasce quando o cliente engaja).

**Lembrete de fechamento**:
Cobrança proativa e determinística do **Valor final** à modelo, na **Coordenação por modelo**, quando o atendimento passou de `bloqueios.fim` e segue em `Em_execucao`. Reenvia em intervalos fixos até um máximo de toques; sem resposta, abre **Handoff** para Fernando (nunca marca `Perdido` por silêncio; permanece em `Em_execucao` até fechamento manual). A modelo fecha respondendo o card com o valor — mesma porta do `finalizado/fechado [valor]`, efetivo imediatamente. Não respeita quiet-hours.
_Avoid_: cobrança do cliente; confundir com **Reengajamento** (que é voltado ao cliente); interpretar a resposta por IA (no P0 é regex; NLP livre é **IA Admin** P1); confirmação dupla; criar estado novo; marcar `Perdido` automaticamente.

**Mídia exclusiva**:
Foto/vídeo da modelo enviado na venda com enquadramento de exclusividade — primeiro fotos, depois um vídeo "gravado ao vivo só para o cliente". Quando a plataforma (Evolution self-host) permitir, o vídeo vai como view-once; sem suporte, vai normal e a proteção fica para o P1.
_Avoid_: vídeo antes de foto; expor que o vídeo "ao vivo" é pré-gravado; prometer view-once sem suporte da plataforma.

**Vídeo chamada**:
Serviço da modelo (programa em `modelo_programas`, com preço/duração) entregue como uma **chamada de vídeo ao vivo** que a **modelo (humana)** faz na hora marcada — é o único serviço **remoto** (ver **Atendimento … remoto**). A IA cota e combina como qualquer programa (valor, horário), reserva o slot e pausa no horário com o card "Hora da sua vídeo chamada"; **não abre chamada no chat**. Distinta da **Mídia exclusiva** (foto/vídeo pré-gravado enviado por `enviar_midia`): vídeo chamada é interação ao vivo, não mídia. View-once/gravação não se aplicam. Ver ADR 0021.
_Avoid_: confundir com **Mídia exclusiva** (mandar vídeo); a IA conduzir/abrir a chamada (quem faz é a modelo); tratar como interno/externo; cobrar Pix; plotar no Mapa.

**Perfil físico preferido**:
Tipo físico que o cliente prefere (loira, morena, ruiva, negra, asiática, outra). Dado **global do cliente** e **painel-only/Fernando**, com duas leituras: a **declarada** (Fernando marca uma ou mais) e a **calculada** (breakdown dos `Fechado` agrupados pelo `tipo_fisico` das modelos atendidas — "6 ruivas, 2 loiras", expondo também quantos fechados são de modelos não classificadas). A IA conversacional nunca lê o breakdown (seria agregação cross-modelo, fura o isolamento por par) nem escreve a preferência — isso é **IA Admin** (P1). Eixo único (não separa cabelo/etnia/biotipo; biotipo fica de fora). O filtro de clientes usa só a parte **declarada**, semântica OR. Classificar `tipo_fisico` é pré-condição da parte calculada (sem ela o breakdown é parcial mas válido; modelos existentes nascem sem `tipo_fisico`, sem backfill). Ver ADR 0006.
_Avoid_: tratar como dado por par; expor à IA conversacional; inferir um rótulo único ("prefere X") do breakdown; materializar biotipo; customizar a persona por preferência.

**Dados cadastrais da modelo**:
Ficha pessoal para gestão — RG, CPF, endereço residencial (distinto do operacional), cor de pele, cor de cabelo, altura, tamanho do pé. Descreve **quem a pessoa é**, diferente do **tipo físico** (balde de venda, que alimenta a parte calculada do **Perfil físico preferido**) e do **Perfil físico preferido** (preferência do cliente). **Painel-only/Fernando**; RG, CPF e endereço residencial são **PII sensível**. A IA nunca lê nem usa esses campos. Cor de pele/cabelo são eixos próprios da ficha, separados do tipo físico e podendo divergir dele de propósito. Ver ADR 0007.
_Avoid_: confundir com **tipo físico** ou **Perfil físico preferido**; expor à IA / interpolar na persona; tratar RG/CPF/endereço residencial como dado não sensível.

**Mapa de clientes**:
Visão agregada do painel (exclusiva de Fernando) que plota cada cliente como um pin no mapa do Brasil pela coordenada (`latitude`/`longitude`) do **atendimento externo** mais recente — para ler a concentração geográfica da demanda. Atendimentos **internos** ficam de fora (o endereço é o ponto de encontro na modelo); cliente sem externo geocodificado entra num contador "sem localização" em vez de sumir. Cross-modelo por natureza, por isso painel-only e nunca acessado pela IA. Os totais por pin (nº de atendimentos e **Valor final** somado dos `Fechado`) agregam todas as modelos do cliente. Ver ADR 0008.
_Avoid_: plotar interno como localização do cliente; mapa por cliente individual; expor à IA; tratar pin ausente como erro.

**Tarefa**:
Item de gestão interna (estilo ClickUp enxuto), **painel-only/Fernando** e **desconexo do domínio de atendimento** (sem cliente, IA ou agenda). Tem **status** (`a_fazer`/`fazendo`/`feita`), **prioridade** (`baixa`/`media`/`alta`) e **prazo** (`date` opcional, sem hora); aparece como lista filtrável, board Kanban de 3 colunas e widget "Tarefas de hoje". O **Responsável** é um **ator polimórfico** (`usuario` | `modelo` | `vendedor`) usado só como **rótulo de execução** — sem login, permissão ou notificação (forward-compat para um multi-principal que o MVP não implementa). Ver ADR 0017.
_Avoid_: confundir o **Responsável** com o **Vendedor** do atendimento ou supor que ele loga/é notificado; confundir com o **Card**; atribuir RBAC no P0.

## Relationships

Só o que **não** é derivável das definições acima.

**Hierarquia e isolamento**
- cliente → **Conversa cliente** (1 por par) → **Atendimentos** (numerados `#N` por modelo). Cada conversa tem no máximo um atendimento aberto e acumula vários (recorrência).
- O **Perfil físico preferido** vive no nível do cliente (cross-modelo), ao contrário de histórico/recorrência/observações (por par) — por isso é painel-only.

**Pix e fluxo interno (gatilhos de transição)**
- Comprovante de **Pix** (validado ou duvidoso) → card "saída confirmada", `ia_pausada=true` (`modelo_em_atendimento`), atendimento → `Confirmado`. Duvidoso: card sinaliza a duvidez + fila assíncrona de revisão de Fernando; sem handoff síncrono nem pausa esperando Fernando.
- **Aviso de saída** sem **Foto de portaria** em **45 min** (contados do **mais tarde** entre o aviso, `aviso_saida_em`, e o **horário combinado**, `bloqueios.inicio` — `GREATEST`, ADR 0024) → timeout determinístico → `Perdido` (`sumiu`), sem mensagem ao cliente; a IA segue ativa para conversas futuras. Avisar antes do horário não penaliza: o relógio só corre 45 min depois do horário combinado (ou 45 min após o aviso, quando este vem depois).

**Agenda — comportamento da IA (contraste-chave)**
- Horário pedido cai em **bloqueio**: a IA recusa com **desculpa pessoal** coerente (salão, me arrumando, jantar, balada) e oferece outra janela; **nunca revela que está com outro cliente**, nunca para de responder.
- Horário pedido cai **fora da Disponibilidade** (folga/viagem/ainda não começou): a IA **revela a volta e ancora** — assume que está fora, informa quando volta, oferece a primeira data disponível.
- Bloqueio fora da **Disponibilidade**: a IA nunca cria nem sugere (trava dura); Fernando vê aviso e pode forçar (override explícito).
- Salvar **Disponibilidade** que deixa bloqueios futuros fora dela: salva e emite alerta não-bloqueante listando-os; nunca deleta/cancela bloqueio automaticamente.

**Financeiro (`Fechado` é a base)**
- Repasse da modelo e **Comissão de vendedor** são custos **independentes** sobre o mesmo valor líquido de taxa de cartão; nenhum desconta o outro; só `Fechado` contam (igual à receita do Módulo Financeiro).
- Cada modelo tem **Vendedor** padrão (`modelos.vendedor_id`); o atendimento o herda e Fernando pode sobrescrever. Quando a IA assume a modelo, o padrão fica nulo e os atendimentos dela não geram comissão.
- O **Fetiche** é a única "coisa dela" que entra no contexto da IA na venda; **nível**, ficha cadastral e **Perfil físico preferido** a IA nunca lê.

## Example dialogue

> **Dev:** "Quando o cliente manda o comprovante, a modelo precisa ler a conversa para entender?"
> **Domain expert:** "Não. A IA está no número da modelo e responde o cliente. No handoff, ela para, manda o resumo no grupo, e a modelo escreve para o cliente no mesmo WhatsApp."

## Flagged ambiguities

- **"Fernando"** = convenção para qualquer **Operador** (Fernando ou a sócia, permissão idêntica — ADR 0012); menções específicas seguem válidas onde o contexto deixa claro. Sem RBAC no P0.
- **"grupo da modelo"**: conversa com cliente = **Conversa cliente**; grupo interno = **Coordenação por modelo**.
- **"Pix confirmado"** ≠ revisão humana obrigatória nem bloqueio: o fluxo sempre avança; divergência marca `pix_status` (informativo) + fila assíncrona de Fernando.
- **horário combinado vs desejado**: desejado = pedido não confirmado; combinado = confirmado e reservado.
- **timeout interno** conta do **mais tarde** entre o envio do **Aviso de saída** (`aviso_saida_em`) e o **horário combinado** (`bloqueios.inicio`) — `GREATEST`, ADR 0024; avisar cedo não antecipa o `Perdido`.
- **"reengajamento"** (termo solto) cobre dois conceitos distintos de propósito: o **Reengajamento** (P0, automático, toque único dentro de um atendimento aberto que silenciou ~30 min após a cotação) e a **Reativação** (P1, campanha manual de Fernando que reabre cliente dormente para um segundo atendimento). Automático×manual, por-atendimento×por-cliente.
- **"desconto"**: deixou de ser sempre escalada — a IA concede **Desconto de fechamento** até o **Piso de desconto** numa única oferta; "escala em vez de negociar" vale só abaixo do piso.
- **Perfil físico preferido** por linguagem natural pela IA: no P0 é painel-only (Fernando); a parte calculada é cross-modelo e furaria o isolamento por par — leitura/escrita por NL fica para a **IA Admin** (P1). É global do cliente; não confundir com as **observações** (por par).
- **confirmação de valor pós-atendimento**: canal é a **Coordenação por modelo** (a modelo não tem DM separada), interpretação determinística (regex de `finalizado/fechado [valor]`); NLP livre é **IA Admin** (P1). Gatilho = `bloqueios.fim` + tolerância, não a entrada em `Em_execucao`. Ver **Lembrete de fechamento**.
- **"a IA atende o cliente"** descreve o papel do agente (em construção), não nega o **Vendedor** humano de hoje — ambos ocupam o mesmo assento (respondente do número), um hoje, a outra no futuro. A comissão existe para a operação humana e some no atendimento da IA. Ver ADR 0012.
