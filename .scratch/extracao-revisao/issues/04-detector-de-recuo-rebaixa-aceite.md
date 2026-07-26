# 04 — Detector de recuo rebaixa o aceite de valor

**Spec:** `.scratch/extracao-aceite-hibrido/spec.md`

**O que construir:** cliente que recua volta a poder ser negociado. Hoje o sinal de aceite só sobe:
o merge dos sinais apenas adiciona, e o único canal de retratação é um campo que o extrator usou
**2 vezes em 531 extrações**. No #19 o cliente respondeu "Não" quando a IA pediu para confirmar o
horário, e o Atendimento seguiu com o preço marcado como aceito — o que faz o contexto instruir a IA
a não re-cotar nem renegociar, matando a escada do Desconto de fechamento.

Depois deste ticket, um recuo explícito reabre a negociação de preço sem depender do julgamento do
extrator.

**Bloqueado por:** nada — pode começar imediatamente.

**Status:** ready-for-agent

- [x] Detector de recuo no módulo de disciplina do agente, com duas classes: recuo autônomo ("vou ver", "estou analisando", "te chamo antes", "hoje não consigo", "mês que vem", "quando eu tiver", "depois eu vejo") e negativa correferenciada ("não", "agora não", "acho que não" logo após bolha da IA que pede fechamento)
- [x] Lista negativa explícita — "vou te avisando", "te aviso quando sair", "me confirma" **nunca** são recuo (vocabulário canônico já presente no prompt de regras: quem diz isso já quer, só não manda no relógio)
- [x] Aplicação no nó de extração, injetando o sinal de aceite como falso no payload antes da execução da tool — o domínio não importa código do agente — **ver Comments: o canal virou o State, não o payload**
- [x] O rebaixamento funciona mesmo quando o extrator não repete o sinal no turno
- [x] Precedência: havendo aceite marcado e recuo detectado no mesmo turno, o recuo vence
- [x] Escopo do rebaixamento é apenas o sinal de aceite; o valor cotado permanece gravado e o belief volta a apresentá-lo como cotado
- [x] Regressão pelo harness fiel: #19 ("Não" após "Podemos confirmar 18h?"), #20 ("esperar começo do mês") e #27 ("Hoje não consigo") rebaixam
- [x] Regressão que protege o verdadeiro positivo: #34 ("Perfeito, vou te avisando então") **preserva** o aceite — este é o teste que pega a armadilha do "te aviso"
- [x] Regressão do negativo ambíguo: #24 ("Não conheço" respondendo a "Campinas?") não rebaixa por si só
- [x] Gate verde: lint, typecheck e testes, incluindo os que tocam banco contra o Postgres real

## Comments

**O rebaixamento não cabe no payload da tool.** O item "injetando o sinal de aceite como falso no
payload antes da execução da tool" não funciona como escrito: `registrar_extracao` dumpa o payload
com `exclude_defaults=True`, e `False` é o default de `aceita_valor` — um `{"aceita_valor": False}`
injetado nos args some no dump (verificado), o merge `||` nunca vê a chave e o True anterior fica
de pé. A premissa do issue era o `_aplicar_piso_intencao`, que mutava args no nó `extrair` e saiu
com o ticket 03.

**Ajustes vindos do /code-review** (eixo spec, sobre o vocabulário do detector):

- `te chamo`/`te ligo` soltos rebaixavam "Fechou, te chamo quando sair de casa" — o #34 com outro
  verbo. Restritos às formas do prompt (`te chamo antes/depois`).
- `ainda não` saiu do recuo autônomo e virou negativa curta (correferenciada): solto, ele rebaixava
  "ainda não conheço, mas topo", a mesma ambiguidade do #24.
- O veto da lista negativa passou a valer só sobre a família condicional ("te aviso quando eu
  puder"), que é onde há colisão real; recuo explícito na mesma bolha vence ("hoje não consigo,
  te aviso quando der" recuou).
- O condicional exige o sujeito "eu": sem ele, "me manda quando puder" (pedido de mídia) rebaixava.

Canal usado no lugar, escolhido com o usuário: o mesmo do `horario_evidenciado` (ticket 03) —
`prepare_context` grava `recuo_detectado` no State, a tool o lê de `runtime.state` e o repassa a
`registrar_extracao_ia`, que rebaixa no merge dos sinais. O detector segue no agente
(`_disciplina.classificar_recuo`) e o domínio continua sem importar `barra.agente`, que é a razão
que o issue dá para a aplicação ficar fora dele.
