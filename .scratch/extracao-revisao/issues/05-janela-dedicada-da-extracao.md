# 05 — Janela dedicada da extração

**Spec:** `.scratch/extracao-janela-dedicada/spec.md`

**O que construir:** o extrator para de copiar o próprio belief-state. Hoje a janela da extração é
derivada por subtração (remove as mensagens de sistema), mas tudo o que importa está dentro da
última mensagem do cliente, que o strip preserva — então o extrator lê, como se fosse conversa, os
valores dos campos que deve preencher. Em produção o tipo do encontro foi reafirmado em **todos** os
turnos do #34 e do #41, inclusive quando o cliente falava de fetiche ou dizia "não vou não
obrigado"; e no #25 o horário sintetizado pelo sistema voltou no payload por três turnos.

Depois deste ticket a chamada de extração recebe conversa crua, âncora temporal e um bloco de estado
rotulado na cauda, com instrução de registrar apenas o que mudou.

**Bloqueado por:** 01 (as peças do contexto precisam estar no estado do grafo), 02 (o bloco precisa
rotular o horário como palpite quando não há evidência — sem isso ele recria o eco do #25).

**Status:** in-review

- [x] A montagem da janela de extração passa a ser construtiva (system mínimo + conversa crua + âncora + bloco de estado), não subtrativa
- [x] O lembrete de persona e os blocos de conduta (o que falta, próximo passo, disciplina de fala, ponto de encontro, dados do cliente) **não** chegam ao extrator
- [x] O bloco de estado vai na **cauda** da chamada, preservando o prefixo estável (system + conversa append-only)
- [x] O bloco rotula o horário como palpite quando não evidenciado e o valor como cotado enquanto não houver aceite
- [x] O bloco carrega a instrução de delta: registrar um campo só se ele mudou nesta conversa
- [x] O campo de próxima ação esperada fica fora do delta (é obrigatório e tem consumidores no painel)
- [x] Regressão pelo harness fiel — eco de tipo: conversa com tipo já combinado e fala do cliente sobre outro assunto **não** reenvia o tipo
- [x] Regressão pelo harness fiel — mudança real: cliente pedindo outro horário registra normalmente e a mudança chega ao Atendimento
- [x] Regressão pelo harness fiel — #25: depois de o fallback gravar o palpite, o turno seguinte **não** reafirma o horário
- [x] Regressão pelo harness fiel — conversa acima do limiar do lembrete de persona se comporta como conversa curta
- [ ] Verificação no banco após a mudança: a redundância por campo e a proporção de extrações sem nenhum par novo caem frente ao baseline registrado no golden set (tipo 81%, data 81%, horário 78%, duração 77%, valor 73%, intenção 71%; 35% sem par novo)
- [x] Gate verde: lint, typecheck e testes, incluindo os que tocam banco contra o Postgres real

**Notas da implementação (2026-07-25).**

Os quatro casos de regressão vivem em `api/tests/integracao/test_janela_extracao.py` (harness fiel,
`needs_db`, chat fake — sem crédito). Com o chat roteirizado, o que eles afirmam é a **entrada** que
chega ao extrator (o belief não vem como fala; o horário vem rotulado como palpite; o lembrete não
chega em conversa longa) mais o que o Atendimento passa a valer. O que o modelo *faz* com essa
entrada é medição de LLM, e mora na bancada offline (06) e na rodada real (07). Verificado que os
quatro ficam vermelhos com a montagem antiga.

O último item **fica aberto de propósito**: a redundância por campo só se remede com tráfego real
depois do deploy — é exatamente o issue 07, bloqueado pelo 06. Nada a fazer aqui além de deployar.

Peças novas: `conversa_crua` no State (a janela do par antes da anexação — a fusão do contexto
dinâmico na cauda é irreversível) e `render_ancora_extracao` + `prompts/ancora_extracao.md.j2` (a
tag `<agenda hoje= agora=>` que as descrições dos campos citam nominalmente). A dieta vale nos dois
caminhos da extração: o kill-switch `extracao_no_modelo_barato` volta a mandar o BP_GERAL, não o
belief colado.

Três desvios conscientes, todos declarados:

1. **A frase do system mínimo mudou** (a spec o declara out of scope, l.102). A antiga dizia que "a
   hora atual e o período de trabalho vêm no contexto da última mensagem" — depois da dieta isso é
   falso. Trocada a frase, não o papel do system.
2. **No kill-switch (`extracao_no_modelo_barato=false`) o BP_GERAL volta**, como sempre voltou — é o
   que o flag significa. O que a dieta corta nos dois caminhos é o contexto dinâmico e o lembrete.
3. **A conversa crua é a janela do BANCO; o que o turno produziu depois dela entra logo após.** Sem
   isso a auto-reoferta morreria: na 2ª passagem (`extrair` → `llm` → `extrair`) o extrator não
   veria o `ToolMessage` do `ConflitoAgenda`, repetiria o mesmo horário e o turno fecharia mudo.
   Achado do `/code-review`; coberto por teste.
