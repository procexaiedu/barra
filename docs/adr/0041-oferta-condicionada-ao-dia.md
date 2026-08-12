---
data: 2026-08-11
status: aceito
refina: ADR-0031 (a escada continua a mesma; muda COMO o primeiro número sai quando o dia falta), ADR-0004 (§"nunca oferece desconto sozinha" ganha um recorte), ADR-0040 (a precedência entre o número dele e a oferta condicionada fica explícita)
---

# ADR-0041 — Com o dia desconhecido, a condição viaja dentro da oferta (e não vira pergunta)

## Contexto

A escada de desconto depende do dia do encontro (decisão de 11/08, ADR-0031 + `ESCADA_POR_ENCONTRO`):
hoje = uma rodada, que já é o piso; outro dia = degrau e depois piso; **dia ainda não dito = nenhuma
oferta**. Nesse terceiro caso o `<escada_travada_sem_o_dia>` manda defender o valor e **perguntar o
dia**, e o degrau do `<desconto>` dizia, com todas as letras, que "o dia vem ANTES do número".

O dono do produto reprovou isso textualmente, com o exemplo dele:

> `"quanto para casal?"` → `"seria hoje ?"` é robótico.
> O certo é `"quanto para casal?"` → `"se vier hoje consigo fazer 600 uma hora"`.

E deu a regra geral, duas vezes no mesmo dia, sobre condutas diferentes: **"tem que acontecer de
forma natural, não um script"**.

Há evidência de produção do lado dele: `"Seria hoje ?"` já virou tique medido — foi preciso criar a
flag `dia_sondado_em` e o bloco `<ja_sondou_o_dia>` no contexto só para impedir a IA de recolar a
frase. Acrescentar mais um turno de interrogatório no ponto mais frágil da conversa (o cliente
acabou de ouvir um número que subiu) é o oposto do que a conduta precisa.

O que a pergunta buscava continua necessário: **a escada não sabe quantas rodadas tem sem o dia.**
A saída é não perguntar — é dizer os dois números.

## Decisão

**1. Com o dia desconhecido, a condição viaja DENTRO da oferta.** Em vez de defender + perguntar o
dia, a IA diz o valor de hoje amarrado a vir hoje e o de outro dia na mesma mensagem. A resposta
dele traz o dia do mesmo jeito — só que dentro de uma venda, não de um formulário.

**2. Os DOIS números vêm calculados, ou nenhum vem.** Site único:
`oferta_condicionada_ao_dia` em `dominio/atendimentos/service.py`, irmã da
`contraproposta_da_escada`, lendo a tabela pela mesma `_linhas_de_tabela` (`apenas_presenciais=True`)
e os valores pelos mesmos `piso_de_desconto`/`degrau_de_desconto` via `valor_no_patamar`. Devolve o
par `(piso, degrau)` — nessa ordem, porque o primeiro número que sai da boca dela é o de HOJE.

Meio par é proibido de propósito: dizer só o número de hoje e improvisar o outro depois faz a
resposta dele ("então outro dia") **parecer aumento de preço**, que é a única forma de essa conduta
destruir a venda em vez de salvá-la.

Fail-closed igual ao resto da família (sem duração fechada, sem programa nela, mais de um preço
presencial, linha não descontável) **mais um** que só o par tem: `piso == degrau` (o clamp do
`preco_minimo` colapsou os estágios) também devolve `None` — "hoje 380, outro dia 380" não
condiciona nada e parece concessão sem ser.

**3. Dizer o número CONSOME uma rodada da escada.** Dizer o número É a contraproposta; não há
"oferta condicional" fora do orçamento de rodadas. Sem isso a IA repete o piso indefinidamente e o
`patamar_da_mesa` desalinha do que ela já falou — e é dele que o extra de fetiche desce (ADR-0038).

A contabilidade dos dois caminhos, dita em voz alta:

- **Ele responde "hoje"**: o valor de pé é o piso, a rodada de hoje está gasta e a escada está
  **esgotada**. Pedido abaixo recebe "Poxa amor não consigo" e, na insistência, `fora_de_oferta`.
- **Ele responde "outro dia"**: o valor de pé é o degrau, que era a rodada 1 do regime de dois dias
  — e **o piso continua disponível como última**. Ou seja: insistindo, ele CHEGA ao mesmo número de
  quem viria hoje.

Isso é aceito, e por duas razões: o número é o **piso** (nunca abaixo dele, a guarda continua a
mesma) e ele **já ouviu esse número** — negá-lo depois seria pior do que concedê-lo. O que a
conduta troca é o desconto por uma informação (o dia) que a venda precisa de qualquer forma.

**4. Escopo: só no SALTO, e só depois de objeção.** A oferta condicionada vale quando o valor que
entra agora é **maior do que o que ele já ouviu** — composição (casal/menage), fetiche pago, ou
pacote de duração maior. `_SaltoNaMesa`/`_salto_na_mesa` em `nos/prepare_context.py`.

Ela **não** vale para toda primeira cotação. Prometer "se vier hoje sai por X" a quem nunca reclamou
de preço entrega ~25% de desconto a todo cliente que passar pela porta — a erosão que o ADR-0004
mandou monitorar. Fora do salto, o `<escada_travada_sem_o_dia>` continua exatamente como estava, com
a defesa do valor e a sonda do dia.

**5. Com extra pago no salto, o par é o TOTAL, não a linha.** O exemplo do dono é composição: 1h da
Catarina é 400 (piso 300, degrau 350) e a segunda pessoa soma o mesmo extra dos atos (ADR-0039, a
linha de 1h no mesmo patamar) — o par é `(300+300, 350+350) = (600, 700)`, que é exatamente o "600"
da fala dele. Mandar a IA somar o par do pacote com o extra é a conta de cabeça que o ADR-0038
proíbe, então `_par_condicionado_ao_dia` já entrega somado, reusando `_base_no_patamar` e
`extra_de_fetiche` — nenhuma conta nova.

**6. Precedência, explícita, quando as regras disputam o mesmo turno:**

1. **O número DELE** (ADR-0040, `<valor_dele_serve>`) — vence tudo. Se ele nomeou um valor que
   serve, não há salto a condicionar nem valor a defender: a venda está fechada.
2. **Subir o TEMPO** — a jogada anterior à escada (ver abaixo). Não desce preço nenhum.
3. **Defender o valor / condicionar ao dia** — o degrau 1 e a exceção deste ADR são o mesmo
   movimento: o degrau 1 segura o número, e no salto sem dia o número que ele segura sai
   condicionado em vez de sozinho.

No template, (1) e (3) são ramos da MESMA cadeia `{% if %}/{% elif %}` (`<valor_dele_serve>` →
`<oferta_condicionada_ao_dia>` → `<escada_travada_sem_o_dia>` → `<escada_disponivel>`): a
coexistência é impossível por construção, não por convenção. (2) é uma tag de dado, não de oferta,
e por isso pode conviver com qualquer uma delas.

**7. Quem alarga é o DETECTOR, nunca a fala** (mesma regra do ADR-0040). O contador de rodadas
(`_disciplina._RE_CONTRAPROPOSTA`, write-time em `workers/envio.py`) exigia o número **colado** em
"consigo" — e a fala que o dono ditou, `"se vier hoje consigo fazer 600 uma hora"`, **não casava**.
Medido em 11/08 no regex de então: `"consigo fazer 600"`, `"consigo te fazer por 600"` e
`"consigo deixar em 600"` davam `False`; só `"consigo 600"` dava `True`. Com o furo aberto, o
contador não anda, a escada nunca esgota e a IA **repete a mesma oferta para sempre**.

O ramo ganhou um elo opcional e fechado entre "consigo" e o número (verbo de concessão com "te"
opcional, e/ou preposição). As fronteiras que não caíram, testadas nominalmente
(`tests/unit/test_contraproposta_flag.py`): a recusa (`"não consigo fazer 600"`) continua barrada
pelo mesmo lookbehind, que morde no "consigo", antes do elo; a cotação (`"400 1h no meu local"`,
`"Podemos combinar 2h 1000"`) nunca teve "consigo"; e o upsell de subir o tempo
(`"consigo fazer 2h por 800"`) **não** casa, porque entre o elo e o número de 3+ dígitos entra a
duração — subir o ticket é venda, não desconto, e não pode gastar rodada.

## Riscos aceitos

**A ilustração pode virar tique.** É o risco de toda fala literal no prompt, e o `"Seria hoje ?"` é
a prova. Mitigação: os dois exemplos do bloco vêm marcados como ilustração com variação
obrigatória, e ganharam o par correspondente em `<armadilhas_de_voz>` proibindo a repetição da
mesma bolha — inclusive a do próprio exemplo.

**O contador pode não ver uma variante nova.** O detector é um regex e a fala é livre: uma forma
fora da família ("hoje sai por 600") não incrementa `n_contrapropostas`, e a IA poderia reofertar.
O dano é limitado por construção: a resposta dele à oferta condicionada quase sempre **nomeia o
dia**, e com o dia na mesa a conversa sai de `sem_dia` — o bloco deixa de renderizar e quem passa a
mandar é a escada normal, com o número que sobrou. Não é razão para prescrever uma frase com carga
funcional: fazer a fala carregar o contador pune toda variação, que é exatamente o que o dono do
produto recusou.

## Alternativas descartadas

**Manter a sonda e só suavizar a frase.** Não resolve: o problema não é a redação, é haver um turno
de pergunta entre o salto e o número.

**Deixar a IA calcular o segundo número.** É a conta de cabeça que o ADR-0038 já proibiu, e aqui
custaria caro: um segundo número errado transforma a resposta dele num aumento de preço.

**Valer para toda cotação.** É desconto universal disfarçado de condição (ADR-0004).

**ADR próprio para as outras duas condutas do mesmo dia.** Descartado, com justificativa:

- **Subir o tempo antes de descer o preço** (vender o pacote maior antes de conceder) não cria
  invariante nova nem número novo — é o `<sobe_o_ticket>`, que já existe e já diz que pacote maior
  **não é desconto**, ganhando uma POSIÇÃO na fila do `<desconto>` e o dado de contexto que faltava
  (`<pacote_maior_na_sua_tabela>`). Nada no domínio muda: os valores são os de tabela, cheios.
- **Cartão ativo e sem taxa** é conduta de fala, não de preço: o valor da mesa não se move, nenhuma
  rodada é consumida e nenhuma conta muda. A parte que tinha lastro de decisão — a **Taxa de cartão**
  — já é o ADR-0013, e o que mudou aqui é só que ela **não sai da boca da IA**; o registro
  operacional continua onde estava.

Se qualquer uma das duas ganhar aritmética própria (um preço "especial" que não seja o de tabela;
um acréscimo de cartão calculado na conversa), aí sim vira ADR.

## Consequências

- `oferta_condicionada_ao_dia` (domínio) e o par formatado (`_par_condicionado_ao_dia`, cauda) são
  os dois únicos sites do número; nenhuma conta nova entrou.
- Quatro campos novos no `ContextoDoTurno`: `oferta_se_hoje`, `oferta_se_outro_dia`, `pacote_maior`,
  `tempo_dele_desconhecido` — amarrados pelo contrato de variáveis
  (`tests/unit/test_contrato_variaveis_contexto.py`), sem o qual um rename apagaria o bloco do
  prompt em silêncio.
- O `<desconto>` passou de 5 para 6 degraus, nesta ordem: defender → **subir o tempo** → descer o
  tempo → o dia decide o preço (**com a exceção do salto**) → segunda rodada (outro dia) → recusa,
  **cartão** e escalada. A leitura de cima a baixo é a maior venda primeiro, a menor depois, o
  desconto por último e a escalada no fim.
- `desconto_entre_degrau_teto` (e2e) media uma escada de duas rodadas com o dia nunca dito —
  impossível desde 11/08. O dia entrou no roteiro e o caso sem-dia virou cenário próprio
  (`desconto_condicionado_ao_dia`).
