## Problem Statement

Um cliente chega no WhatsApp de uma modelo e não quer só ela — quer resolver a noite de um grupo. É o lead #36 (24/07, Wendell, `5511948769550`, modelo Tatiane), literalmente:

> **cliente:** tem mais amigas? estava precisando de mais 3
> **IA:** Só eu amor, não tenho amigas aqui não rs

A partir daí ele passou 40 minutos tentando encaixar os amigos de outro jeito (*"tem um amigo meu que está no quarto sozinho, você vai ficar com ele"*, *"eu tô vendo outras na condição que te falei"*, *"estamos em um evento"*), a IA leu tudo isso como pedido de trio e recusou repetidamente, e o `output_guard` acabou barrando uma das recusas como se fosse vazamento — `motivo_escalada = output_leak_outro_cliente`, `ia_pausada = true`. O cliente ainda perguntou *"qual seu local?"* e *"talvez eu já amanhã"*, e ninguém respondeu.

Três perdas empilhadas num lead só:

1. **O produto não existe.** Ele não queria 4 mulheres para si (menage) — ele era o **comprador** de 4 programas, um para cada homem do grupo. Isso vale ~4× o ticket de um atendimento e o sistema não sabe representar.
2. **A fala fecha a porta.** `"Só eu amor"` é a resposta correta para quem **pesca** outra mulher, mas é resposta errada para quem quer **somar** — e hoje a conduta trata os dois como a mesma coisa (`cross_modelo_fishing`).
3. **Nada disso é raro.** No corpus do vendedor humano (33.400 mensagens de cliente) o pedido aparece repetidamente e com o mesmo formato: *"tem umas amigas? estamos em uma despedida de solteiro"*, *"você atende com amiga? tem link dela"*, *"tem alguma amiga?"*, *"e sua amiga / vc conseguiu as fotos?"*. E quando a amiga aparece, ele avalia: *"não curti sua amiga não"*.

## Solution

Um **Combo de grupo**: o cliente negocia com uma única modelo — a **Modelo do canal** — e fecha, **na mesma conversa**, um Atendimento para cada mulher que o grupo dele precisa. As demais entram como **Modelo convidada**: nunca conversam com o cliente, têm a agenda reservada pela IA do canal e ficam sabendo pelo **Card** na sua **Coordenação por modelo**.

Do lado do cliente é uma porta só: ele pergunta, vê nome e foto de quem está disponível, ouve um preço por mulher e fecha tudo com a mesma pessoa com quem já estava falando. Do lado do sistema são N Atendimentos normais, cada um com seu `#N`, seu estado, seu valor e seu bloqueio — amarrados por um `combo_id`.

O princípio que governa a implementação: **a LLM fala, o determinístico decide**. A IA nunca escolhe quem está disponível, nunca calcula preço e nunca resolve agenda. Ela chama uma ferramenta que devolve o conjunto elegível já pronto e apenas o apresenta — mesma relação que ela já tem hoje com `<agenda>` e com o **Bloqueio**.

## User Stories

**O cliente (comprador do grupo)**

1. Como cliente que chegou no número de uma modelo, quero pedir "tem mais amigas?" e receber uma resposta que não feche a porta, para que eu não precise procurar outro anúncio.
2. Como cliente organizando a noite de um grupo, quero contratar todas as mulheres numa conversa só, para que eu não tenha que negociar quatro vezes com quatro desconhecidas.
3. Como cliente, quero ver o nome e uma foto de cada mulher oferecida, para que eu possa decidir se o grupo dela agrada aos meus amigos.
4. Como cliente, quero saber o preço de cada uma, para que eu saiba quanto vou gastar no total antes de topar.
5. Como cliente que pediu 3 e só tem 1 disponível, quero ouvir claramente que há 1, para que eu decida se isso resolve minha noite em vez de receber um "não tenho".
6. Como cliente, quero recusar uma das mulheres oferecidas sem perder as outras nem perder a modelo do canal, para que uma recusa não derrube a negociação inteira.
7. Como cliente, quero que o horário e o endereço combinados valham para todas, para que eu não tenha que coordenar quatro chegadas diferentes.
8. Como cliente hospedado em outro hotel, quero que elas venham até nós, para que o grupo não precise se deslocar.
9. Como cliente que topa ir até elas, quero que estejam todas no mesmo endereço, para que meu grupo não se separe entre prédios.
10. Como cliente, não quero perceber que estou falando com uma central, para que a experiência continue sendo a de conversar com uma mulher no WhatsApp dela.
11. Como cliente que só quer saber se o local é discreto ("atende sozinha?"), quero uma resposta sobre privacidade, para que eu não receba uma oferta comercial no lugar de um reasseguro de segurança.
12. Como cliente, quero que o preço de cada mulher seja dito um de cada vez, para que a conversa não vire uma tabela despejada.
13. Como cliente que pede desconto, quero negociar o valor da modelo com quem estou falando, e entender que o valor das outras não é dela para dar.

**A Modelo do canal**

14. Como modelo do canal, quero que a IA feche o combo inteiro pelo meu número, para que eu não perca a minha venda por não ter amiga para oferecer.
15. Como modelo do canal, quero receber um card que mostre o combo inteiro — quem vem, que horas, onde, quanto — para que eu consiga coordenar com as outras.
16. Como modelo do canal, quero continuar sendo a única a falar com o cliente, para que ele não perceba que há um sistema por trás de várias mulheres.
17. Como modelo do canal, quero que a minha venda sobreviva quando o cliente recusa uma convidada, para que a recusa dele não me custe o programa.
18. Como modelo do canal, quero que o meu **Desconto de fechamento** valha só sobre o meu pacote, para que eu não seja responsabilizada por um desconto no preço de outra.

**A Modelo convidada**

19. Como modelo convidada, quero receber um card na minha Coordenação avisando que fui incluída num combo, com horário, endereço, valor e quem é a modelo do canal, para que eu saiba o que foi combinado em meu nome.
20. Como modelo convidada, quero ser cobrada pelo **Preço de tabela** meu, não pelo da modelo do canal, para que eu não trabalhe por um valor que não é o meu.
21. Como modelo convidada, quero que a minha **Disponibilidade** e os meus **Bloqueios** sejam respeitados, para que eu nunca seja reservada num horário em que não trabalho ou já estou ocupada.
22. Como modelo convidada, quero que o buffer de preparo seja respeitado, para que eu não seja encaixada colada em outro compromisso.
23. Como modelo convidada, quero saber quando o combo caiu, para que eu não saia de casa para um encontro que não existe mais.
24. Como modelo convidada, quero que o meu atendimento siga o fluxo normal depois de criado, para que Pix, chegada e fechamento funcionem como em qualquer outro.
25. Como modelo convidada, não quero que o cliente tenha o meu contato por causa do combo, para que ele não me procure fora do que foi combinado.

**Fernando (operador)**

26. Como Fernando, quero ver no painel que aqueles quatro atendimentos são do mesmo combo, para que eu não os leia como quatro eventos soltos do mesmo cliente na mesma noite.
27. Como Fernando, quero que a receita e o repasse de cada atendimento do combo sejam calculados normalmente, para que o Módulo Financeiro não precise de caso especial.
28. Como Fernando, quero saber quando um cliente pediu mais mulheres do que conseguimos oferecer, para que eu entenda a demanda reprimida do cadastro.
29. Como Fernando, quero poder desligar a feature inteira sem deploy, para que eu possa parar de oferecer combo se a operação não der conta.
30. Como Fernando, quero que nenhum combo seja formado com modelo `pausada` ou `inativa`, para que o freio manual continue significando o que significa.

**A IA (conduta)**

31. Como IA, quero destravar a oferta apenas quando o cliente pede para **somar** mulheres, para que eu não ofereça amiga a quem só quer trocar de mulher.
32. Como IA, quero não ter nome nem foto de outra modelo em contexto quando ninguém pediu, para que eu não possa vazar a existência delas nas conversas comuns.
33. Como IA, quero responder "atende sozinha?" de um jeito que sirva tanto à leitura de segurança quanto à de sondagem, para que eu não feche a porta nem revele que há outra mulher no prédio.
34. Como IA, quero que a ferramenta me devolva o preço já calculado, para que eu nunca faça conta.
35. Como IA, quero receber um `ERRO:` quando a agenda da convidada foi tomada no meio da negociação, para que eu recue com desculpa de gente em vez de confirmar algo que o sistema recusou.
36. Como IA, quero registrar o combo na extração como qualquer outro fato, para que o estado do atendimento continue refletindo a realidade.
37. Como IA, quero continuar recusando **Menage** com outra modelo no mesmo quarto e escalando, para que o combo não vire uma porta lateral para o que ainda exige decisão do Fernando.

## Implementation Decisions

**1. O produto é grupo, não menage.** O cliente é o **comprador**; os outros homens que encontram as convidadas **não viram dado no sistema**. É o espelho do **Menage** caso (a) do glossário ("a segunda pessoa não vira dado"). Todos os Atendimentos do combo têm o **mesmo Cliente** (quem negociou) e **Modelos distintas** — o invariante "no máximo um Atendimento aberto por par" continua intacto, porque os pares são diferentes.

**2. Porta única.** A negociação inteira acontece no WhatsApp da **Modelo do canal**. A convidada nunca conversa com o cliente e o contato dela nunca é passado. Isso elimina, por construção, o cenário de quatro conversas paralelas com a mesma persona e a mesma voz (persona e FAQ são gerais — CONTEXT.md), que seria o pior risco de disclosure já criado no produto.

**3. Gate por ferramenta, não por prompt.** O contexto padrão do agente **não muda**: nenhuma modelo além da própria entra no prompt. Uma nova tool de leitura (irmã de `consultar_agenda`, em `agente/ferramentas/leitura.py`) devolve o conjunto elegível **apenas quando chamada**. Mesmo padrão estrutural do `<local_de_encontro>`, que não entra no contexto antes de `Qualificado` — se o cliente nunca pede, a IA literalmente não tem o dado para vazar.

**4. Elegibilidade é 100% determinística.** A tool filtra, em SQL:
- `status = 'ativa'` (nunca `pausada`/`inativa` — o freio manual é soberano);
- **mesma região** da modelo do canal, por geo (`latitude`/`longitude`/`place_id` já existem em `modelos`);
- **interno**: além da região, exige o **mesmo endereço de encontro** do canal (o hotel, unidades diferentes — hoje é o caso real: as duas modelos ativas dividem `Vitória Hotel Residence Newport`, R. Santos Dumont 291);
- **Disponibilidade** cobrindo a janela pedida e nenhum **Bloqueio** ativo sobrepondo, respeitando o buffer (`agenda_buffer_min`, ADR 0025);
- o cliente **não pode já ter Atendimento aberto** com aquela convidada;
- ordenação e teto de itens no retorno, como o `_MAX_BLOQUEIOS` de `consultar_agenda`.

**5. Preço por convidada, calculado pelo sistema.** A tool devolve o valor do programa equivalente já resolvido a partir de `modelo_programas` **de cada convidada** — a IA nunca calcula nem converte. O **Desconto de fechamento** (ADR 0031) permanece restrito ao pacote da **Modelo do canal**; pedido abaixo do preço de uma convidada não gera contraproposta e escala `fora_de_oferta`. A **Taxa de cartão** e o repasse seguem por Atendimento, sem caso especial.

**6. Apresentação: uma foto de perfil por convidada.** A oferta sai com nome + `foto_perfil_object_key` de cada elegível, no mesmo turno. O **book** completo (2-3 fotos + vídeo, `<midia>`) continua exclusivo da modelo do canal. Justificativa: a regra atual "foto é fechamento, não vitrine" se apoia em o cliente **já ter visto o anúncio** dela; para a convidada isso não existe — ele nunca a viu, e o corpus mostra que ele pede a foto de qualquer jeito e recusa quando não gosta.

**7. Reserva firme, mas só no sim.** A oferta **não** reserva nada. Quando o cliente fecha horário e valor, o combo é materializado de uma vez: N Atendimentos + N Bloqueios, pela mesma porta de serviço que já cria o **bloqueio prévio** hoje (`dominio/atendimentos/service.py`), com toda a validação de Disponibilidade/sobreposição/buffer que já existe. Se uma convidada foi tomada no meio da negociação, a operação falha para aquela e a tool devolve `ERRO:` — a conduta já sabe tratar (`<ferramentas>`: *"nunca confirme ao cliente algo que o sistema recusou"*, e a falha *"não existe pra ele"*). Nenhuma agenda alheia é travada por curiosidade.

**8. `combo_id` nullable em `atendimentos`.** Uma coluna, nula em 100% dos atendimentos normais; os irmãos compartilham o mesmo valor. Sem tabela nova e sem estado agregado — o estado continua vivendo em cada Atendimento, onde já vive. Migration sequencial em `infra/sql/`, schema-only (nunca seed).

**9. Cards.** Um card de combo na Coordenação da **Modelo do canal** (o combo inteiro: quem vem, horário, endereço, valores) e um card por **Modelo convidada** na Coordenação dela (o atendimento dela + quem é o canal). Novo template em `workers/_cards/`, seguindo a gramática de `CARDS.md` e a idempotência por `card_message_id`.
> ⚠️ **Bloqueado hoje:** Tatiane e Lucia compartilham o mesmo `coordenacao_chat_id` (`120363407815206369@g.us`) — provável resíduo do cutover EvoGo de 21/07. Enquanto for um grupo só, o card por modelo é impossível e qualquer card de uma já é visível para a outra. Precisa ser corrigido antes da feature ir ao ar.

**10. Execução: nada muda na pausa.** Cada Atendimento pausa a IA quando é a hora dele (`modelo_em_atendimento`), como hoje. A **Modelo do canal humana** vira a coordenadora do combo — ela fala com as outras mulheres fora do sistema. Nenhuma alteração no state machine nem no coordenador.

**11. Cascata assimétrica.** Perder um Atendimento de convidada não toca nos irmãos (um amigo desistiu; os outros seguem). Perder o Atendimento **do canal** por sumiço/timeout cascateia o combo inteiro — quem negociou evaporou, e as convidadas precisam ser avisadas antes de sair de casa.

**12. Conduta: `cross_modelo_fishing` sai; a distinção passa a ser somar × substituir.**
- **Somar** (*"tem mais amigas?"*, *"preciso de mais 3"*, *"somos 4 aqui"*, *"meu amigo quer uma também"*) → destrava a tool.
- **Substituir** (*"me indica outra"*, *"tem uma mais nova?"*) → não destrava; segue a recusa de sempre, sem motivo de escalada próprio. Existe no corpus (*"Alguma amiga do seu perfil pra indicar pra hoje?"*) mas é ~1 ocorrência clara em 33k — não justifica um motivo dedicado.
- **Segurança** (*"atende sozinha?"*, *"tem mais gente aí?"*) → **nunca** destrava. O corpus mostra que o sentido está no complemento, não na palavra: as ocorrências reais são todas ancoradas no local (*"vc atende na sua casa sozinha??"*, *"você atende sozinha no local?"*), enquanto os pedidos de amiga **sempre nomeiam a amiga**. A fala muda de `"Só eu amor rs"` para **`"Só eu e você amor"` / `"Bem discreto rs"`** (decidida 25/07): o objeto da afirmação sai do prédio e vai para o encontro, respondendo o medo real (armação, terceiro) sem afirmar nem negar a existência de outra mulher — se ele queria amiga, ele emenda e aí sim destrava. A ocorrência de `"Só eu amor rs"` em `<fora_do_cardapio>` (pedido de indicação) **permanece como está**; as duas não se unificam.
- **Pool zero ou parcial** → oferece o que tem e nunca promete o resto; com zero, uma fala que mantém a conversa viva e segue vendendo o programa da modelo. Nunca `"não tenho amigas"`.
- `<menage>` permanece intacto: amiga **no mesmo quarto** continua sendo escalada (`outro`). O combo é uma mulher **por pessoa**, não duas para o mesmo homem.

**13. Escopo por tipo.** Interno (com mesmo endereço) e externo. **Nunca remoto** — vídeo chamada em grupo não é o produto.

**14. Flag de settings.** A feature nasce desligável sem deploy, como o **Reengajamento** e o **Cancelamento automático do piloto**. Enquanto o piloto (ADR 0033) estiver ligado, o cancelamento automático atinge os Atendimentos do combo pelas mesmas regras por tipo — o que na prática torna combo e piloto mutuamente exclusivos na operação.

**15. Pendência aberta — Pix de deslocamento no combo externo.** Em decisão com o Fernando. O código amarra a escolha: a chave Pix é **por modelo** (`modelos.chave_pix`) e o OCR **valida a chave extraída contra a chave daquela modelo** (`dominio/pix/routes.py`). Um Pix único somado na chave do canal **bate no atendimento dela e falha nos das convidadas**. As três saídas — N Pix (uma chave por modelo, trilho atual intacto), Pix único somado (exige mudar matching e distribuição) ou deslocamento único com elas indo no mesmo carro (exige mesma região de origem no filtro) — têm custos diferentes de implementação. **O interno não depende disso e pode ser entregue primeiro.**

## Testing Decisions

Um bom teste aqui prova **comportamento externo**: dado o estado do banco e a mensagem do cliente, quais Atendimentos/Bloqueios/cards existem depois e o que a tool devolveu. Nada de asserção sobre estrutura interna da tool, ordem de chamadas ou forma do prompt.

**Seam 1 — grafo + tools reais + Postgres real (`needs_db`, sem crédito).** Prior art direta: `tests/integracao/test_extrair_inline.py` e `tests/integracao/test_registrar_extracao.py` — grafo mínimo, tool **real**, conexão de `TEST_DATABASE_URL`, `ROLLBACK` sempre no teardown, fake-pool de uma conexão. É o seam mais alto que ainda prova SQL, e é onde a feature quase inteira vive:
- elegibilidade: convidada `pausada`/`inativa` não aparece; fora da região não aparece; fora da **Disponibilidade** não aparece; com **Bloqueio** sobreposto não aparece; dentro do buffer não aparece; cliente com Atendimento já aberto com ela não aparece;
- interno exige mesmo endereço; remoto nunca forma combo;
- preço devolvido é o da tabela **da convidada**;
- no sim: N Atendimentos criados com o mesmo `combo_id`, N Bloqueios, numeração `#N` por modelo correta;
- corrida: convidada ocupada entre a oferta e o sim → `ToolException`/`ERRO:` e **nada** persistido (mesma prova de transação revertida que `test_extrair_inline.py` já faz com `ConflitoAgenda`);
- cascata: perda do canal derruba os irmãos; perda de convidada não toca em ninguém;
- cards enfileirados nos grupos certos.

**Seam 2 — canário de isolamento (estende o existente).** `tests/agente/test_f0_3_canary_cross_modelo.py` semeia um token sentinela no par (cliente, modelo B) e prova que ele não aparece no contexto nem no retorno de `consultar_agenda`. O canário **continua válido sem afrouxamento**: ele protege dado **do cliente com a modelo B** (mensagens, `observacoes_internas`, histórico), enquanto a tool nova lê dado **da modelo B** (nome, foto, preço, agenda) — categorias diferentes. Acrescentar o irmão: a nova tool devolve disponibilidade da convidada e **nunca** o sentinela do par. As âncoras anti-vácuo (`_MARCO_A`) do rig existente valem igual — sem elas um verde pode ser vazio.

**Seam 3 — conduta (fixtures, LLM).** Prior art: `tests/agente/test_conduta.py` e `test_conduta_fiel_llm.py`. Cobre só o que é decisão do LLM:
- "somar" destrava a tool; "substituir" não; **"atende sozinha?" nunca destrava**;
- pool zero não produz `"não tenho amigas"` nem fecha a porta;
- um preço por vez continua valendo com múltiplas convidadas na mesa;
- desconto pedido sobre o valor de convidada não vira contraproposta.

**Regressão obrigatória.** O `output_guard` precisa de caso de teste para o padrão que matou o #36: recusa legítima contendo *"com outra pessoa"* **não** pode ser barrada como `output_leak_outro_cliente`, e a admissão (*"tô com outra pessoa"*) **precisa** continuar barrada. O fix do regex já existe no working tree (`agente/nos/output_guard.py`) e ainda **não está commitado nem deployado** — deve entrar antes ou junto, com teste em `tests/agente/test_output_guard.py`.

Rodar os `needs_db` contra o banco real (`TEST_DATABASE_URL`), não só o subconjunto do CI, conforme o gate de verificação do `CLAUDE.md`. Usar `-m "needs_db and not needs_key"` para não gastar crédito.

## Out of Scope

- **Menage com outra modelo no mesmo quarto** — continua sendo Escalada (`outro`), como no `<menage>` e no CONTEXT.md. Combo é uma mulher **por pessoa**.
- **Passar o contato de qualquer modelo ao cliente** — rejeitado explicitamente: destrói a porta única e cria conversas paralelas com voz idêntica.
- **Aceite da convidada antes da reserva** — rejeitado: insere latência humana no caminho crítico de 1h da manhã. A reserva é firme e ela é avisada pelo card.
- **Escalada como caminho normal** — rejeitada: a feature precisa ser autônoma.
- **Tabela `combos` com estado agregado** — rejeitada: criaria uma segunda máquina de estados ao lado da existente.
- **Combo remoto** (vídeo chamada em grupo).
- **Segunda pessoa/amigo como Cliente** — os homens do grupo não viram dado.
- **Comissão de indicação entre modelos** — não existe e não é criada aqui.
- **Reativação/campanha em cima de grupos** — P1.
- **Regra do Pix no combo externo** — pendência do Fernando (ver decisão 15); o interno não depende dela.

## Further Notes

**Pré-condições de cadastro que hoje impedem a feature de rodar** (nenhuma é da feature; todas precisam ser resolvidas antes):

1. **Grupo de Coordenação compartilhado.** Tatiane e Lucia apontam para o mesmo `coordenacao_chat_id`. Enquanto for assim, o card por modelo (decisão 9) não é entregável e o isolamento operacional entre as duas já está furado hoje, independentemente do combo.
2. **Tatiane sem `chave_pix`.** A única modelo **ativa** em produção não tem chave cadastrada. Isso é **bug vivo**, não da feature: o #36 era externo e a IA prometeu *"100 o deslocamento"* — se o cliente tivesse topado, o sistema não teria chave para anexar.
3. **Nenhuma modelo tem `foto_perfil_object_key`.** A decisão 6 não tem dado para rodar.

**Cadastro atual:** 1 modelo `ativa` (Tatiane), 1 `pausada` (Lucia), 14 `inativa` (seed do import, sem localização). Ambas as não-inativas ficam em `Cambuí, Campinas`, no **mesmo prédio**, e trabalham 10h–04h quase todos os dias — na prática o gargalo de elegibilidade nunca será **Disponibilidade**, e sim **Bloqueio** e `status`. Com o pool efetivo de hoje sendo zero, a feature precisa degradar bem no caminho vazio desde o primeiro dia (decisão 12).

**Colisão de nomes a observar:** o cliente do #36 estava no **"Hotel Vitória Express"** e a modelo fica no **"Vitória Hotel Residence Newport"** — hotéis diferentes, nomes quase iguais. Quando a IA disse *"To no centro, perto do vitória express"* ela chutou geografia (proibido na persona: *"não afirma proximidade que não está no seu dado"*) em cima de um nome colidente. Risco real de confusão no dia em que o endereço for passado, e independente do combo.

**Emendas ao glossário já aplicadas** nesta sessão (`CONTEXT.md`): verbete **Combo de grupo**; verbete **Modelo do canal / Modelo convidada**; e emenda no `_Avoid_` de **IA por modelo**, onde "IA citando profissional contratada por outra modelo" passou a ter o combo como exceção explícita — antes o glossário contradizia frontalmente o que esta feature faz.

**ADR recomendado.** A decisão bate os três critérios: é difícil de reverter (a IA de uma modelo passa a **escrever na agenda de outra**), é surpreendente (contradiz o `"Só eu amor"` da conduta e o `_Avoid_` histórico do glossário), e é resultado de trade-offs reais — passar contato, escalar e exigir aceite da convidada foram todos considerados e rejeitados, cada um por um motivo específico que ninguém reconstrói daqui a três meses.

**Origem:** sessão de `grill-with-docs` sobre o lead #36 (atendimento `019f9226-c745-7600-bd8b-30333bd7a193`, cliente `019f9224-06eb-7c0e-9fdc-12d69caf1a53`), 24/07/2026.
