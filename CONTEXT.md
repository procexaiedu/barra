# Elite Baby MVP

Linguagem de domínio da central inteligente de atendimento da operação Elite Baby — mantém consistentes os termos entre produto, operação e implementação.

> **Precedência:** reflete os ADRs vigentes (`docs/adr/`). Onde divergir de um ADR não-superseded, o ADR vence e este arquivo deve ser corrigido. Regra completa de fonte de verdade no `CLAUDE.md`.
>
> **Escopo deste arquivo:** o vocabulário **quente** — o que a IA usa e erra na conversa com o cliente. O resto do glossário mora em `docs/dominio/`, carregado sob demanda:
> - `docs/dominio/operacao-e-financeiro.md` — **Operador**, **Vendedor**, **Comissão de vendedor**, **Coordenação por modelo**, **Card**, **Devolução para IA**, **Registro de resultado**, **Lembrete de fechamento**, **Valor final**, **Taxa de cartão**, **Combo de grupo**, **Modelo do canal**/**convidada**.
> - `docs/dominio/painel-e-p1.md` — **Perfil físico preferido**, **Dados cadastrais da modelo**, **Mapa de clientes**, **Tarefa**, **IA Admin** (P1), **Reativação** (P1).

## Language

**Modelo**:
A profissional cadastrada que opera no **próprio número de WhatsApp**, atendida pela **IA por modelo**. Tem `status` (`ativa`/`pausada`/`inativa`, liga/desliga a IA) e é o eixo das **"coisas dela"**: identidade (nome, idade, idiomas), **programas** e preços, **Disponibilidade**, tipos de atendimento aceitos, **Fetiches**, **tipo físico** (balde de venda, painel-only) e **Dados cadastrais** (ficha pessoal, painel-only). **Persona, voz e FAQ são gerais** — não variam por modelo. Tem um **Vendedor** responsável padrão e um acordo de repasse (`percentual_repasse`).
_Avoid_: confundir a entidade **Modelo** com o *model* do LLM ou com `modelos.py` (DTOs); customizar persona/voz/FAQ por modelo; expor à IA os **Dados cadastrais** ou o **tipo físico** como persona.

**Cliente**:
Pessoa que contata uma modelo pelo WhatsApp, identificada pelo **telefone** (E.164, único — dois números são dois clientes, sem dedup por pessoa). Entidade **global** (uma linha por número), mas o dado **operacional** — histórico, recorrência, observações — é **isolado por par cliente-modelo** na **Conversa cliente**, e a **IA por modelo** nunca o cruza entre modelos. Os poucos atributos **globais** (**Perfil físico preferido**, posição no **Mapa de clientes**) são **painel-only/Fernando**.
_Avoid_: tratar histórico/recorrência/observações como globais (são por par); deduplicar por pessoa (a chave é o telefone); expor atributos globais à IA.

**Conversa cliente**:
**Thread persistente** de um par cliente-modelo (uma por par) no número da modelo, onde a IA responde em nome dela até pausar para handoff e onde a modelo pode assumir manualmente. Guarda histórico, recorrência e observações; **sobrevive a vários atendimentos** ao longo do tempo. Continua gravando mesmo com IA pausada, sem alertar grupos nem criar indicador no painel.
_Avoid_: chamar de chat da modelo ou atendimento humano; confundir com o **Atendimento** (a thread não é o ciclo comercial); confundir com a **Coordenação por modelo** (grupo interno — ver `docs/dominio/operacao-e-financeiro.md`).

**Atendimento**:
Ciclo comercial de uma negociação cliente-modelo: nasce em `Novo`, percorre os **Estados do atendimento** e encerra em `Fechado`/`Perdido`. **No máximo um aberto por par** (terminais não restringem); recorrência abre um **novo** dentro da mesma **Conversa cliente**. Identificado por **número curto sequencial por modelo** (`#N`, usado nos comandos do grupo). Carrega o eixo **interno/externo**, **Valor final**, **Vendedor**, o **bloqueio** de agenda e o estado de pausa da IA. Recebe **Registro de resultado**, **Handoff**, **Pix de deslocamento** e timeouts.
_Avoid_: confundir com a **Conversa cliente**; tratar como dado global do cliente (é por par e por ciclo); dois atendimentos abertos no mesmo par; reusar `#N` entre modelos.

**Estados do atendimento**:
Máquina de estados linear (mecânica em `docs/mvp/03`); terminais `Fechado`/`Perdido`.
- `Novo` — primeiro contato, antes de triagem.
- `Triagem` — IA coletando intenção e dados mínimos.
- `Qualificado` — intenção real demonstrada (quer marcar) e **tipo definido**; a cotação já costuma ter sido apresentada (carimbada à parte em `cotacao_enviada_em`, ADR 0022, não é gate desta transição). O **horário ainda não está cravado** — é o que falta para `Aguardando_confirmacao`.
- `Aguardando_confirmacao` — **horário combinado** (gatilho desta transição; cria o **bloqueio prévio**) e aguarda **Pix de deslocamento** (externo), **Foto de portaria** (interno) ou o **horário da vídeo chamada** (remoto, ADR 0021; o **Pix antecipado da chamada** também chega aqui, sem gatear — ADR 0029). O **Aviso de saída** é informativo, não muda o estado.
- `Confirmado` — externo: **Pix recebido** (validado **ou** duvidoso — nunca trava por Pix); IA pausada (`modelo_em_atendimento`), modelo conduz.
- `Em_execucao` — modelo engajada: **Foto de portaria** recebida (interno) ou horário previsto chegou (externo).
- `Fechado` — convertido por **Registro de resultado** (exige **Valor final**).
- `Perdido` — não converteu, por registro explícito ou timeout determinístico (exige **Motivo de perda**). Terminal, com **uma exceção** (ADR 0027): um `Perdido` por `auto_timeout_interno` volta a `Em_execucao` se a **Foto de portaria** chega dentro do slot ainda livre (ver verbete **Foto de portaria**).
_Avoid_: tratar revisão de Pix como estado (é `pix_status=em_revisao`, atendimento ainda em `Aguardando_confirmacao`/`Confirmado`); condicionar `Confirmado` a Pix sem dúvida; inventar estados intermediários no P0.

**Atendimento interno, externo ou remoto**:
Eixo (`tipo_atendimento`) que define quem se desloca — ou se ninguém se desloca:
- **interno** — o cliente vai até a modelo; o endereço é o **ponto de encontro na modelo**, não onde o cliente mora. O local se vende como **hotel elegante, seguro e discreto** (nunca "prédio"/"sala" na fala com o cliente — emenda ADR 0026, 22/07). O endereço tem **2 níveis** (ADR 0026): **(a)** o nível-prédio, em degraus — no 1º contato/sondagem, só a **região** (o endereço nem entra no contexto da IA antes de `Qualificado` — gate estrutural `<local_de_encontro>`); com intenção real (`Qualificado`+), **nome do hotel + rua SEM número** — e o número **nem entra no contexto** nesse degrau (2º degrau do mesmo gate, emenda ADR 0026 25/07); o **número** entra com o **horário combinado** (`Aguardando_confirmacao`+), que é o que "confirmar que vai" produz. **(b)** a **unidade** (apartamento/quarto) — dada pela **modelo (humana)** quando a **Foto de portaria** chega (IA já pausada); a **IA nunca emite a unidade**. Confirma a chegada pela **Foto de portaria**. Fica **fora do Mapa de clientes**. Sem Pix de deslocamento.
- **externo** — a modelo se desloca; o **Pix de deslocamento** (valor fixo) antecipa o custo, e o endereço é a localização do cliente — geocodificada e plotada no **Mapa de clientes**. O cliente **buscar a modelo de carro** não é um subcaso suportado (descartado — ADR 0020): a IA redireciona para os tipos que existem (ele vem no local dela, ou ela vai de Uber com Pix) e, se ele insistir em buscá-la, escala.
- **remoto** — ninguém se desloca: o serviço é uma **Vídeo chamada** ao vivo. Sem local físico, **fora do Mapa de clientes**, **sem Pix de deslocamento** e sem Foto de portaria. A extração reserva o slot (`Aguardando_confirmacao` + bloqueio prévio, como o interno, só pelo horário) e, na hora marcada, a IA pausa com o card "Hora da sua vídeo chamada"; pula `Confirmado`. O **valor da chamada é antecipado via Pix** (ADR 0029): com valor e horário combinados o sistema solicita e anexa a chave, e o comprovante **não gateia nem pausa** — só registra e sinaliza nos cards. Ver ADR 0021/0029.

A modelo declara os tipos que aceita (`tipo_atendimento_aceito[]`, pode ser mais de um); cada atendimento fixa exatamente um. A IA nunca negocia um tipo que a modelo não realiza.
_Avoid_: tratar interno como localização do cliente; a IA revelar a **unidade** (apto/quarto) do interno (só a modelo passa, pós-Foto de portaria); passar rua+número do prédio antes de haver intenção real (no 1º contato/sondagem, só a região); exigir Pix de deslocamento no interno/remoto ou Foto de portaria no externo/remoto; travar o remoto pelo Pix antecipado (não gateia — ADR 0029); negociar o cliente buscando a modelo de carro (caso descartado — redirecionar e, na insistência, escalar); plotar interno ou remoto no Mapa; misturar remoto e presencial no mesmo atendimento.

**IA por modelo**:
Cada modelo opera no próprio número, atendida por uma IA cuja **persona (voz, jeito, conduta) e FAQ são gerais — compartilhadas entre todas**. Não se customiza a forma de responder por modelo: muda só **as coisas dela** (identidade óbvia, programas/preços, agenda, tipos aceitos). O dado do cliente (histórico, recorrência, observações) é **isolado por par** na **Conversa cliente**: a IA na modelo A nunca enxerga, cita ou se apoia em dado do cliente com a modelo B.
_Avoid_: perfil único do cliente entre IAs; IA citando profissional contratada por outra modelo **fora do Combo de grupo** (única exceção, e só sob pedido do cliente — ver `docs/dominio/operacao-e-financeiro.md`); fundir histórico cross-modelo; customizar voz/persona/FAQ por modelo.

**Handoff**:
Pausa da IA para Fernando decidir ou a modelo assumir a conversa no mesmo número, sempre com resumo e próxima ação; a IA só retoma por **Devolução** explícita. Disparado por gatilho **automático** do state machine (Pix, Foto de portaria, Lembrete de fechamento sem resposta) ou por **gatilho manual do operador** (Fernando/modelo decide pausar a IA para aquele cliente a qualquer momento, sem esperar um evento do domínio — ex.: resposta ruim da IA). Escopo sempre o **Atendimento** aberto no momento (não a Conversa cliente inteira); atendimento seguinte do mesmo par nasce com IA ativa de novo. Mensagens gravadas durante o handoff compõem resumo/auditoria mas não geram transição automática de estado.
_Avoid_: humano genérico; tratar o gatilho manual como mudança de escopo (continua por Atendimento, não pausa a Conversa cliente inteira); a IA inferir resultado ou valor durante o handoff.

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
Ato/serviço íntimo que a modelo **realiza ou não** — cardápio da própria modelo, apresentado **dentro do campo de serviços** como extra **sem duração**, marcado por modelo como **incluso** ou **pago** (flag, não mais um preço cadastrado — ver ADR 0030): incluso = a modelo faz sem custo extra; pago = a IA cota, mas o valor **é sempre calculado**, nunca gravado por modelo, em **dois regimes** (ADR 0035): **ato** (default) = **preço-hora efetivo do pacote vendido no atendimento** (Preço de tabela do programa ÷ horas vendidas), somado uma vez por fetiche pedido, uniforme entre atos; **por pessoa** (casal/menage, flag `cobra_por_pessoa` no catálogo global) = **dobra o pacote** (2 pessoas). Em 1h os dois coincidem; divergem de 2h em diante. Catálogo **global** curado + vínculo por modelo (o que faz, incluso ou pago); é "coisa dela" que a IA usa na venda para responder "você faz X?", cotar o extra e **recusar de forma aberta** o que não está na lista. Pode entrar na composição do atendimento (snapshot do valor calculado no momento), mas **não auto-soma o Valor final** (segue manual) — entra só no breakdown; o **Desconto de fechamento** incide sobre o **pacote** (programa + extras), nunca sobre o **Pix**. Ver ADR 0014, ADR 0030.
_Avoid_: "feitiço" (use **Fetiche**); confundir com tipo de atendimento ou com a ficha cadastral (que a IA não lê); tratar como programa com duração; auto-somar o **Valor final**; tratar como dado de cliente (é da modelo); cadastrar um preço absoluto por fetiche (o valor é sempre calculado a partir do programa vendido no atendimento, não gravado por modelo).

**Menage**:
Fetiche **"por pessoa"** (flag `cobra_por_pessoa`): ambas as leituras são cobradas como o **dobro do pacote** — 2 pessoas, não o preço-hora dos fetiches-ato (ADR 0035, reabre o multiplicador que o ADR 0030 deixou em aberto) — **sem exceção "incluso"** apesar de hoje existir modelo cadastrada assim (cadastro a corrigir): **(a) cliente traz uma segunda pessoa** — acompanhante, namorada, ou outro homem (amigo, primo — confirmado Fernando 22/07: cobra-se por duas pessoas, não é restrito a "casal", e a fala da IA espelha "vocês dois", nunca rotula de casal quando não é); a segunda pessoa **não vira dado no sistema**; é só regra de preço sobre o mesmo par (Cliente, Modelo) de sempre. **(b) modelo traz uma amiga (outra modelo)** — **fora do sistema no P0**: a IA pode oferecer/cotar, mas fechar e coordenar com a segunda modelo é sempre **Escalada** para Fernando; o Atendimento continua sendo só (Cliente, Modelo principal) e o rateio do valor entre as duas é manual, fora do Módulo Financeiro.
_Avoid_: registrar a acompanhante do tipo (a) como Cliente; modelar Atendimento com duas Modelos no P0; deixar o sistema ratear automaticamente entre as duas modelos do tipo (b); tratar como incluso por padrão.

**Desconto de fechamento**:
Redução pontual sobre o **Preço de tabela** que a IA concede para fechar (reativo, quando o cliente pede — o toque de **Reengajamento** vai **sem** desconto), em **até duas rodadas de escalada** na mesma negociação: primeiro o **degrau** (~12,5% de desconto); só se o cliente insiste, o **teto** (ver **Piso de desconto**, ~25%). Uma terceira insistência não gera nova oferta. Oferecer pacote de duração maior com preço/hora menor (upsell, já na tabela) **não** é desconto — a IA faz livremente. Ver ADR 0004, ADR 0031.
_Avoid_: mais de duas rodadas de escalada (regateio livre); desconto recorrente além do teto; desconto sobre o **Pix**; mexer no **Valor final** já fechado.

**Piso de desconto**:
Menor valor que a IA oferece sozinha — **dois percentuais globais** (degrau intermediário e teto) sobre o **Preço de tabela** do pacote vendido, escalando automaticamente com o preço de qualquer programa×duração (não é valor absoluto cadastrado por combinação); abaixo do teto escala (`fora_de_oferta`) em vez de oferecer mais. Ver ADR 0031.
_Avoid_: expor os percentuais ao cliente; tratar como valor absoluto cadastrado por programa; permitir rodada além do teto.

**Pix de deslocamento**:
Pagamento antecipado, de **valor fixo**, do deslocamento — o uber **ida e volta** da modelo (decisão Fernando 10/07). Existe **apenas quando a modelo se desloca por conta própria** (Uber até o cliente; se o **cliente** chama o próprio uber ida e volta, não há Pix — nunca os dois juntos); a **Vídeo chamada** (remoto) não tem Pix de **deslocamento** — o que ela tem é o **Pix antecipado do valor da chamada** (ADR 0029), que roda no mesmo trilho (solicitação determinística, chave anexada pelo sistema, nunca trava) mas é coisa distinta deste verbete: antecipa o **serviço**, não deslocamento. O comprovante sempre faz o atendimento avançar — **nunca trava por Pix**: checagens OK validam em silêncio; divergência/suspeita marca o comprovante como duvidoso, o card à modelo sinaliza a duvidez (ela decide antes de pedir o Uber) e Fernando revisa depois numa fila assíncrona, sem bloquear.
_Avoid_: sinal; pagamento do atendimento; valor proporcional à distância/programa; travar o fluxo por Pix duvidoso; handoff síncrono para Fernando por Pix.

**Aviso de saída**:
Mensagem do cliente em atendimento interno avisando que saiu de casa rumo ao endereço combinado. Primeiro aviso operacional da sequência interna; prepara a modelo (card simples) mas não confirma o atendimento, e a IA continua respondendo o cliente normalmente (estado segue em `Aguardando_confirmacao`).
_Avoid_: equiparar a confirmação automática ou a comprovante financeiro.

**Foto de portaria**:
Imagem da portaria/local de encontro, enviada pelo cliente em atendimento interno; comprova que chegou e mitiga quem "zoa". O recebimento dispara handoff implícito: card "cliente chegou" na **Coordenação por modelo** com a imagem, `ia_pausada=true` (motivo `modelo_em_atendimento`) e transição automática `Aguardando_confirmacao` → `Em_execucao`, sem aprovação humana e **sem vision automática no P0** (qualquer imagem em `Aguardando_confirmacao` interno é tratada como Foto de portaria). A inspeção visual da modelo é proteção operacional, não gatilha nem bloqueia transição. **Ressuscita o interno auto-timed-out** (ADR 0027): uma foto que chega **depois** de o timeout interno (ADR 0024) ter marcado `Perdido`/`sumiu` e cancelado o bloqueio reconecta esse atendimento — volta a `Em_execucao` com o mesmo handoff (card "cliente chegou", `ia_pausada`, bloqueio reativado) — **se e só se** a morte foi `auto_timeout_interno`, o slot segue livre (sem sobreposição) e ainda dentro do `bloqueio.fim`; fora disso a volta é recorrência legítima (novo `#N`). É exceção explícita ao invariante "`Perdido` é terminal".
_Avoid_: equiparar a Pix ou comprovante financeiro; vision automática no P0; condicionar a transição à decisão de modelo/Fernando; manter IA respondendo após a chegada; ressuscitar `Perdido` humano, slot já reocupado ou fora do `bloqueio.fim`.

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
_Avoid_: múltiplos toques; reabrir quem não chegou à cotação; desconto no toque; confundir com o timeout de 24h; confundir com a **Reativação** (campanha manual de cliente dormente, P1 — ver `docs/dominio/painel-e-p1.md`).

**Mídia exclusiva**:
Foto/vídeo da modelo enviado na venda com enquadramento de exclusividade — primeiro fotos, depois um vídeo "gravado ao vivo só para o cliente". Quando a plataforma (Evolution self-host) permitir, **a mídia (foto e vídeo) vai como view-once** (decisão 2026-07-10 — a foto exclusiva também é protegida, não só o vídeo); sem suporte, vai normal e a proteção fica para o P1. Habilitar em prod exige o toggle `evolution_view_once` ligado sobre um build da Evolution com o patch de `viewOnce`.
_Avoid_: vídeo antes de foto; expor que o vídeo "ao vivo" é pré-gravado; prometer view-once sem suporte da plataforma.

**Vídeo chamada**:
Serviço da modelo (programa em `modelo_programas`, com preço/duração) entregue como uma **chamada de vídeo ao vivo** que a **modelo (humana)** faz na hora marcada — é o único serviço **remoto** (ver **Atendimento … remoto**). A IA cota e combina como qualquer programa (valor, horário), reserva o slot, pede o **Pix antecipado do valor da chamada** (ADR 0029 — o sistema anexa a chave; comprovante não gateia) e pausa no horário com o card "Hora da sua vídeo chamada"; **não abre chamada no chat**. Distinta da **Mídia exclusiva** (foto/vídeo pré-gravado enviado por `enviar_midia`): vídeo chamada é interação ao vivo, não mídia. View-once/gravação não se aplicam. Ver ADR 0021.
_Avoid_: confundir com **Mídia exclusiva** (mandar vídeo); a IA conduzir/abrir a chamada (quem faz é a modelo); tratar como interno/externo; cobrar Pix de **deslocamento** (o Pix do remoto antecipa o **valor da chamada** — ADR 0029); travar a chamada por Pix pendente; plotar no Mapa.

## Relationships

Só o que **não** é derivável das definições acima.

**Hierarquia e isolamento**
- cliente → **Conversa cliente** (1 por par) → **Atendimentos** (numerados `#N` por modelo). Cada conversa tem no máximo um atendimento aberto e acumula vários (recorrência).
- O **Fetiche** é a única "coisa dela" que entra no contexto da IA na venda; **nível** do vendedor, ficha cadastral e **Perfil físico preferido** a IA nunca lê.
- O **Perfil físico preferido** vive no nível do cliente (cross-modelo), ao contrário de histórico/recorrência/observações (por par) — por isso é painel-only.

**Pix e fluxo interno (gatilhos de transição)**
- Comprovante de **Pix** (validado ou duvidoso) → card "saída confirmada", `ia_pausada=true` (`modelo_em_atendimento`), atendimento → `Confirmado`. Duvidoso: card sinaliza a duvidez + fila assíncrona de revisão de Fernando; sem handoff síncrono nem pausa esperando Fernando.
- **Aviso de saída** sem **Foto de portaria** em **45 min** (contados do **mais tarde** entre o aviso, `aviso_saida_em`, e o **horário combinado**, `bloqueios.inicio` — `GREATEST`, ADR 0024) → timeout determinístico → `Perdido` (`sumiu`), sem mensagem ao cliente; a IA segue ativa para conversas futuras. Avisar antes do horário não penaliza: o relógio só corre 45 min depois do horário combinado (ou 45 min após o aviso, quando este vem depois).

**Agenda — comportamento da IA (contraste-chave)**
- Horário pedido cai em **bloqueio**: a IA recusa com **desculpa pessoal** coerente (salão, me arrumando, jantar, balada) e oferece outra janela; **nunca revela que está com outro cliente**, nunca para de responder.
- Horário pedido cai **fora da Disponibilidade** (folga/viagem/ainda não começou): a IA **revela a volta e ancora** — assume que está fora, informa quando volta, oferece a primeira data disponível.
- Bloqueio fora da **Disponibilidade**: a IA nunca cria nem sugere (trava dura); Fernando vê aviso e pode forçar (override explícito).
- Salvar **Disponibilidade** que deixa bloqueios futuros fora dela: salva e emite alerta não-bloqueante listando-os; nunca deleta/cancela bloqueio automaticamente.

## Flagged ambiguities

- **"grupo da modelo"**: conversa com cliente = **Conversa cliente**; grupo interno = **Coordenação por modelo**.
- **"Pix confirmado"** ≠ revisão humana obrigatória nem bloqueio: o fluxo sempre avança; divergência marca `pix_status` (informativo) + fila assíncrona de Fernando.
- **horário combinado vs desejado**: desejado = pedido não confirmado; combinado = confirmado e reservado.
- **timeout interno** conta do **mais tarde** entre o envio do **Aviso de saída** (`aviso_saida_em`) e o **horário combinado** (`bloqueios.inicio`) — `GREATEST`, ADR 0024; avisar cedo não antecipa o `Perdido`.
- **"reengajamento"** (termo solto) cobre dois conceitos distintos de propósito: o **Reengajamento** (P0, automático, toque único dentro de um atendimento aberto que silenciou ~30 min após a cotação) e a **Reativação** (P1, campanha manual de Fernando que reabre cliente dormente para um segundo atendimento). Automático×manual, por-atendimento×por-cliente.
- **"desconto"**: deixou de ser sempre escalada — a IA concede **Desconto de fechamento** até o **Piso de desconto** numa única oferta; "escala em vez de negociar" vale só abaixo do piso.
- **"Fernando"** = convenção para qualquer **Operador** (Fernando ou a sócia, permissão idêntica — ADR 0012). Sem RBAC no P0.
