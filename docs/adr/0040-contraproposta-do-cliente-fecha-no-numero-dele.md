---
data: 2026-08-11
status: aceito
refina: ADR-0031 (a escada continua de duas rodadas; deixa de ser a única fonte do número), ADR-0037, ADR-0038 (emendado)
---

# ADR-0040 — A contraproposta do CLIENTE acima do piso fecha no número dele, e consome uma rodada

## Contexto

Um vendedor humano exemplar cotou 2h por 800, ouviu **"Faz 700"** e fechou em **700**. Na tabela
da Catarina, a 2h é 800 com `preco_minimo` (ADR-0037) de 600 — o **Piso de desconto** é, portanto,
600, e o degrau é 700.

O agente, na mesma conversa, responde **600**.

O caminho é este: `"faz por X"` é reconhecido — `_RE_CONTRAPROPOSTA_VERBAL`
(`agente/nos/prepare_context.py`) casa `faz|faço|fecha|pago|topa|aceita|…` + número desde a
validação ao vivo de 11/08. Mas o número dele é usado só para **inferir a duração da linha em
negociação** (`_horas_da_linha_contraproposta`) e depois **jogado fora**. O que sobra é o gatilho:
a escada dispara, `ESCADA_POR_ENCONTRO["hoje"] = ("piso",)`, e o `<escada_disponivel>` injeta o
piso. Em nenhum lugar do sistema existia a comparação `valor_proposto >= piso`.

Ou seja: **em toda negociação em que o cliente nomeia um valor, damos um desconto que ele não
pediu.** O prejuízo é a diferença entre o que ele ofereceu e o piso, e ela aparece exatamente nas
conversas que já estavam ganhas.

O ADR-0031 desenhou a escada como o instrumento da negociação, e implicitamente assumiu que **todo
número na mesa sai da IA**. O ADR-0037 já tinha quebrado uma parte dessa premissa (o piso deixou de
ser só a conta percentual da casa). Aqui cai a outra: o cliente também põe número na mesa, e o dele
é informação — é o teto da concessão que ele mesmo declarou.

## Decisão

**1. Número que o cliente nomeia dentro de `[piso, valor da mesa)` fecha a venda no número DELE, na
hora.** Sem defender antes, sem contraproposta própria, sem "deixa eu ver". `valor da mesa` é o
`valor_acordado` do atendimento quando existe, senão o `preco` da linha única da duração.

Site único: `aceite_do_valor_dele` em `dominio/atendimentos/service.py`, irmã da
`contraproposta_da_escada`, lendo a tabela pela mesma `_linhas_de_tabela` (`apenas_presenciais=True`)
e o piso pelo mesmo `piso_de_desconto`. Devolve `(Decimal | None, motivo)`.

**2. O aceite CONSUME uma rodada da escada.** Sem isso a regra vira leilão — 700 aceito, depois 650
(≥ 600, aceito), depois 620. O orçamento de rodadas do ADR-0031 é a única coisa que segura isso, e
ele já existe: com `encontro="hoje"` (uma rodada) aceitar 700 esgota a escada, e o pedido seguinte
recebe "Poxa amor não consigo" e, na insistência, `fora_de_oferta`.

`dia_desconhecido` é o buraco desse orçamento (`ESCADA_POR_ENCONTRO` vazia → `estado_da_escada`
devolve `sem_dia` para qualquer `n`, o contador nunca esgota): ali a regra é explícita, **um aceite
só** (`n_contrapropostas == 0`).

**3. Aceitar o número dele independe do dia.** No template o bloco `<valor_dele_serve>` é o
**primeiro** ramo da mesma cadeia `{% if %}/{% elif %}` do `<escada_disponivel>` e vem **antes** do
ramo `sem_dia`. O dia decide quanto ELA desce, não quanto ELE ofereceu. A cadeia única é o que faz
a coexistência dos dois blocos **impossível por construção** — dois números na mesma mensagem
seriam duas ofertas, e a segunda desfaria a venda que a primeira fechou.

**4. Fail-closed em tudo o mais**, sempre caindo na escada de hoje, sem mudança de comportamento:
número não detectado; mais de um número novo no burst; duração não fechada; dois pacotes
presenciais na duração; linha não descontável; abaixo do piso; acima ou igual à mesa; escada
esgotada. Cada um vira um label da métrica `agente_aceite_do_cliente_total{encontro,decisao}`,
porque o caminho novo é silencioso por construção e sem série não dá para distinguir "ele não
propôs número" de "o detector não viu o número dele".

**5. Quem alarga é o DETECTOR, nunca a fala.** Duas guardas dependiam de reconhecer o número na
fala: o contador de rodadas (`_disciplina._RE_CONTRAPROPOSTA`, write-time em `workers/envio.py`) e
a guarda de **valor fantasma** (`_valores_ja_ofertados`, que só aceita como `valor_acordado` o que
está na tabela ou saiu da boca dela). 700 não está na tabela; se a IA aceitasse dizendo "Fechado
amor", o valor seria **descartado**, `aceita_valor` cairia junto e a venda não seria registrada.

Ambos os detectores ganharam um **ramo de fechamento** (token de aceite —
`fechado|fechamos|combinado|tabom|fecho|faço|topo` — colado no número, ou o número seguido de
`então|fechado|fechamos|combinado`), com o número seguido de duração barrado por lookahead para não
confundir aceite com cotação ("400 1h no meu local"). A cláusula negada continua barrando os dois
("não consigo fechar 700").

**6. O bloco do prompt prescreve INTENÇÃO, não frase.** Ele diz: aceite na hora, no valor dele, com
o horário na mesma mensagem, e o número precisa aparecer na bolha. Os exemplos vêm marcados como
ilustração, em três formas diferentes, com variação obrigatória — e o par correspondente das
`<armadilhas_de_voz>` da persona foi emendado para não mandar defender quando o contexto traz
`<valor_dele_serve>`.

## Alternativas rejeitadas

- **Defender uma vez e aceitar na repetição** (`"apos_defesa"`), com um setting alternando as duas.
  Rejeitada pelo dono do produto: o vendedor exemplar não fez isso, e o cliente que já disse "faz
  700 / aí eu vou" recebe um "não" e some. Também é estritamente mais difícil de calibrar, porque a
  defesa colide com o degrau 1 do `<desconto>`, que manda defender **e** tem a escada logo atrás.

- **Prescrever a fala canônica do aceite no prompt** (`"Consigo 700 sim amor"`). Era a solução
  barata: essa forma já faz o contador incrementar, o scanner reconhecer e os evals lerem o número,
  tudo sem tocar código. **Rejeitada pelo dono do produto.** Conduta prescrita como frase vira
  tique — o `"Seria hoje ?"` já é um tique medido em produção — e uma frase com **carga funcional**
  é pior, porque o sistema pune toda variação: a IA seria obrigada a repetir a mesma bolha em toda
  venda para que a venda fosse registrada. A regra geral que fica: **nenhum comportamento do sistema
  pode depender de uma frase específica**; quando um detector não enxerga a fala natural, o detector
  é que muda.

- **Relaxar `_valores_ja_ofertados` para "qualquer número do cliente acima do piso".** Reabriria o
  bug de 11/08 que criou a guarda: a IA **recusou** 300 e o extrator gravou 300 — e 300 estava acima
  do piso. "Acima do piso" nunca foi prova de aceite.

- **Reusar `_piso_do_pacote`.** Ele responde a pergunta da venda JÁ FEITA e lê a tabela com
  `apenas_presenciais=False` (traz a vídeo chamada junto). Aqui a pergunta é a da **oferta**, e é a
  razão pela qual `_linhas_de_tabela` existe separada.

- **Ignorar propostas dentro de X% da mesa** (aceitar 799 sobre 800 queima a única rodada de hoje
  por um real). Barato, mas é um limiar novo sem dado que o sustente; fica anotado como dívida, a
  ser aberta se a série `decisao="aceito"` mostrar aceites colados no preço cheio.

## Consequências

- O agente para de dar desconto não pedido na família mais comum de objeção. O ganho por conversa é
  `valor_proposto − piso` (no caso da Catarina, R$100 na 2h).
- A escada dela passa a ser o caminho da objeção **sem número** ("tá caro demais"), não o caminho de
  toda objeção. Os cenários de eval foram partidos nessas duas famílias
  (`desconto_valor_dele_serve` e `desconto_entre_degrau_teto`).
- O contador de rodadas anda em mais situações. O risco residual conhecido: a IA fechando uma venda
  **sem desconto** com o preço repetido na bolha ("Combinado 400 amor") também incrementa. O custo é
  uma rodada de desconto a menos numa conversa cujo valor já foi aceito — e com valor aceito
  `preco_na_mesa` é falso e nenhum bloco da escada renderiza.
- A relação entre `n_contrapropostas` e o patamar do valor deixou de valer, porque a rodada passou a
  poder ser consumida por um número que não é dela. Ver a emenda do ADR-0038.
