# 08 — Descrição autocontida do aceite de valor

**Spec:** `.scratch/extracao-aceite-hibrido/spec.md`

**O que construir:** a descrição do campo de aceite manda o extrator "seguir a sua conduta de
`<desconto>`" — um bloco que vive no prompt geral, que é exatamente o que a chamada de extração
remove ao rodar com janela mínima. **O leitor da descrição não recebe a conduta referenciada.** Pior,
a conduta é contextual: o prompt afirma que pergunta não é aceite, e também que pergunta de
logística é sim ao valor da mesa — a segunda regra vale só depois de a IA ter recusado desconto,
distinção que o extrator não tem como aplicar sem o estado da negociação. Dois dos falsos positivos
auditados (#24 "Aonde atende", #8 "seria do seu local dlc?") são exatamente esse padrão.

Depois deste ticket a regra chega inteira a quem precisa dela.

**Bloqueado por:** 07 — aresta de disciplina, não técnica: a mudança compila sozinha, mas subir sem
medir seria trocar uma hipótese por outra, que é justamente o que motivou toda esta revisão.

**Status:** resolved

- [x] A descrição do campo de aceite passa a carregar a regra inteira, sem referência a bloco de prompt: inclui a distinção de que pergunta de horário ou logística vale como sim **apenas depois** de a IA ter recusado desconto, e mantém cortesia e reconhecimento explicitamente fora
- [x] Emenda registrada no CLAUDE.md do agente: a fronteira "conduta client-facing mora no prompt; a descrição referencia, não reescreve" foi escrita para o chat principal, que recebe o prompt inteiro — para a chamada de extração com janela mínima ela se inverte, porque o único texto que chega é a descrição
- [x] Auditoria das demais descrições de campo da extração em busca do mesmo defeito (a de tipo do encontro também delega para "sua conduta"), com o resultado registrado — corrigir ou justificar por que fica
- [x] Medição na bancada, comparando descrição autocontida contra a referenciada sobre o mesmo golden set, com o resultado publicado
- [x] Gate verde: lint, typecheck e testes

## O que a entrega mudou

- `SinaisQualificacao.aceita_valor` (`ferramentas/extracao.py`) carrega a regra inteira; a condição
  contextual que só existia no prompt ("pergunta de logística vale como sim **depois** de você ter
  recusado baixar o preço") entrou no campo.
- Na bancada o eixo inverteu: a autocontida virou a `base` (é o que prod roda) e a variante
  `aceite-referenciado` congela a descrição órfã para a comparação continuar existindo.
- Auditoria: `.scratch/extracao-aceite-hibrido/auditoria-descricoes.md`. Dois achados ficam com
  justificativa (`_DESC_TIPO_ATENDIMENTO`, `_DESC_MOTIVO_PERDA`) e um vira candidato a ticket
  próprio: a **docstring da tool** ainda manda "responda ao cliente em personagem" e "chame uma vez
  por turno" — instruções mortas desde que `registrar_extracao` saiu de `TOOLS`.

## O que a medição deixou aberto

Rodada em `.scratch/extracao-eval-offline/rodada-2026-07-25-aceite.md` (108 chamadas, autorizada).
**Sem regressão**, mas o ganho não é medível neste golden set: os dois falsos positivos que
motivaram o ticket (#24, #8) não existem nele com o contexto que os discrimina, e o único item
positivo de `aceita_valor` é falso negativo nas duas variantes por artefato do recorte. Falta o
mesmo que a rodada anterior pediu — turnos de cotação rotulados e janela fiel do replay —, agora
com um caso a mais: **itens de pergunta-de-logística com preço na mesa**.

## O que a revisão de código mudou

- A condição de logística nasceu **mais estreita que o canônico**: exigia recusa, e o `<desconto>`
  não exige — depois de um degrau concedido a pergunta também é sim ao valor da mesa. O texto que
  subiu diz os dois ramos (recusando **ou** com a contraproposta).
- O bullet de eco multi-site no `agente/CLAUDE.md` afirmava que o `<desconto>` traz essa condição.
  Não traz: no prompt ela é **posicional**. O bullet agora avisa isso a quem for traduzir o
  parágrafo de novo.
- Abriu o issue **09** — a condição está dita mas não é verificável: `n_contrapropostas` chega à IA
  (`<ja_fez_contraproposta>`) e não ao extrator (`<ja_registrado>`), e a janela desliza. Modo de
  falha é o benigno (não marca aceite), por isso não bloqueia este ticket.
