---
data: 2026-08-12
status: aceito
supersedes: a escalada `outro` do ramo "você trazer uma amiga" do `<composicoes>` (que vivia em
  prosa, sem ADR próprio) e a leitura de CONTEXT.md "Composição, ramo (b) = sempre Escalada"
refina: ADR-0039 (o valor da dupla é a mesma conta da composição), ADR-0016 (a rede anti-Pix do
  output_guard ganha um carve-out nominal)
---

# ADR-0042 — Parceria entre modelos: encaminhamento cross-modelo e venda de dupla sem handoff

## Contexto

A Catarina tem uma parceira, a Yasmin: 19 anos, mesmo hotel, quatro fotos aprovadas, `inativa` no
cadastro, **zero programas e zero fetiches**. Duas coisas diferentes acontecem com ela, e o sistema
não sabia fazer nenhuma das duas:

1. **O cliente quer um ATO que a Catarina não faz** (anal). Hoje a IA recusa e a conversa morre ali
   — mesmo com uma mulher no quarto ao lado que faz exatamente aquilo. É venda perdida da casa
   inteira, não só dela.
2. **O cliente quer DUAS MULHERES.** Hoje o `<composicoes>` manda escalar: *"Deixa eu ver com ela e
   já te retorno amor"* + `escalar(outro)`. Isso devolve o cliente ao vácuo e faz a venda esperar um
   humano. O corpus já mostrou que o silêncio pós-cotação é o padrão de perda #1.

As duas partem da MESMA pessoa, na MESMA conversa, e **divergem em tudo**. Os modos de falha da
confusão são os piores que este produto tem:

- **passar o telefone da Yasmin numa conversa de dupla** → o cliente sai do canal, perde-se a venda
  das duas e queima-se o número;
- **cotar as duas em cima de um pedido de anal** → promete-se o que a Catarina não faz e o que a
  Yasmin nunca combinou.

Um discriminante por inferência da LLM não é aceitável para uma escolha com esse custo.

Havia ainda três armadilhas concretas na base de código:

- **não existia "quem é a parceira desta modelo"** em lugar nenhum;
- **`agente/ferramentas/midia.py` filtra por `modelo_id = ctx.modelo_id`** — não havia como mandar
  foto de outra modelo; e `marcar_book_enviado` carimba o book em QUALQUER envio de mídia, então a
  foto da Yasmin acenderia `<ja_enviou_book>` e bloquearia o book da própria Catarina;
- **`output_guard._RE_CHAVE_PIX` casa `\d{11,14}` e descarta a bolha inteira** (rede anti-vazamento
  de chave Pix). Um telefone E.164 tem 13 dígitos corridos: a bolha do contato morreria em silêncio
  pelo próprio guard.

## Decisão

### 1. Fonte única da parceira: `barravips.modelo_parcerias`, não `modelos.parceira_id`

Uma tabela de associação **direcional**, com atributos. Um FK escalar diria só *quem* é a parceira e
não teria onde guardar as três decisões que a operação toma **por par**:

| coluna | pergunta que ela responde |
|---|---|
| `encaminhamento_ativo` | este par pode ENCAMINHAR? |
| `encaminhamento_atos` | para QUAIS atos? (chaves de família de `_FAMILIAS_FETICHE`) |
| `dupla_ativa` | este par pode VENDER JUNTO? |

As duas autorizações são **independentes** (um par pode vender junto e não poder encaminhar), e a
relação é direcional: `(Catarina → Yasmin)` é uma decisão, `(Yasmin → Catarina)` é outra e hoje nem
existe (a Yasmin não tem canal). Um `parceira_id` em `modelos` obrigaria simetria ou a duplicaria.

**A whitelist de pares que o dono do produto pediu É esta tabela**: sem linha ativa, nenhum dos dois
fluxos existe. É a mesma disciplina closed-world do cardápio — a ausência é a recusa, sem exceção em
prosa.

Migrations: `20260812010000_parceria_de_modelos.sql` (schema — a tabela + os carimbos
`atendimentos.parceira_encaminhada_em` e `atendimentos.parceira_dupla_em`) e
`20260812010500_parceria_catarina_yasmin.sql` (o par). O segundo é **configuração, não seed**: a
linha do par É a whitelist, e um arquivo com `seed` no nome seria recusado em prod pelo
`aplicar_sql.py`/`guard_prod.py` e ficaria fora do `schema_migrations` — o ADR nasceria morto em
produção sem ninguém perceber. Aplicação manual, nunca `make migrate`.

### 2. O discriminante é determinístico e devolve NO MÁXIMO UM fluxo

`agente/_parceria.py:fluxo_da_parceira` é uma função pura sobre três entradas, nenhuma delas
inferida pelo modelo:

- as **famílias** que o burst mencionou (`fetiches_no_burst`, regex);
- o **status de cada família contra o cadastro DELA** (`_resolver_fetiches_em_pauta`);
- a **autorização do par** (`modelo_parcerias`).

```
família de COMPOSIÇÃO com outra modelo (dupla_de_modelos, dois_casais)
  + dupla_ativa + o item ESTÁ no cardápio dela           → fluxo DUPLA
família de ATO fora do cardápio dela + em encaminhamento_atos → fluxo ENCAMINHAMENTO
senão                                                     → nenhum
```

"Nunca os dois no mesmo turno" **não é uma convenção: é a assinatura**. Não existe valor de retorno
que carregue os dois, e o contexto do turno lê um único campo (`parceira_fluxo`), então o prompt
recebe uma única tag.

**Composição vence ato** no burst misto ("vocês duas fazem anal?"), por assimetria de dano: a dupla
nunca emite telefone, e o ato fora do cardápio continua recebendo a recusa closed-world dentro do
encontro que ela está vendendo. O caminho inverso mandaria o contato da parceira para quem estava
comprando as duas.

Os dois ramos consultam o cardápio **em sentidos opostos**, e é isso que os mantém coerentes com o
resto do sistema: a dupla exige a composição DENTRO do cardápio (é de lá que sai o número das duas);
o encaminhamento exige o ato FORA dele (é o que ela não faz).

Consequência: `dupla_de_modelos`/`dois_casais` **deixam de ser famílias sem resolução**. Elas eram
exceção porque um `fora` ("você não faz") contradiria a escalada que a IA devia fazer — e a escalada
morreu aqui.

### 3. Fluxo A — ENCAMINHAMENTO: a IA não cota nada

Ela recusa em personagem, conta que tem uma amiga aí que faz e **pergunta**. Nada dela sai antes do
sim. Com o sim, a tool `envolver_parceira(modo="encaminhar")` registra o encaminhamento e o sistema
anexa a bolha com o telefone. **Daí em diante o envolvimento acaba**: preço, local e horário são com
a parceira, e a IA **não cota valor nenhum** — nem o dela, nem o da parceira.

Três travas de write-time, na tool, cobrindo a conversa inteira (o turno o discriminante já cobre):
par na whitelist; `amiga_ofertada_em` já carimbado (o carimbo é write-time do ENVIO, então só existe
num turno ANTERIOR — o contato nunca sai na mesma resposta da oferta); e uma vez por atendimento.

### 4. Fluxo B — DUPLA: a Catarina conduz e fecha, e isso REVOGA a escalada

Ela apresenta o valor das duas juntas, manda fotos da parceira e **nunca** passa o telefone. O preço
sai da tabela DELA pela regra de composição do ADR-0039 — o extra é a linha de 1h do mesmo programa,
no patamar vigente. Na tabela da Catarina (1h 400/mín 300, 2h 800/mín 600):

| pacote | patamar | conta | total das duas |
|---|---|---|---|
| 1h | cheio | 400 + 400 | **800** |
| 1h | piso ("hoje") | 300 + 300 | **600** |
| 2h | cheio | 800 + 400 | **1.200** |

A Yasmin **não tem tabela e não precisa ter**. O rateio entre as duas é manual, fora do sistema.

Ela está `inativa` e sem disponibilidade cadastrada, e mesmo assim a Catarina **fecha e crava
horário**: `envolver_parceira(modo="dupla")` dispara um **card NÃO-BLOQUEANTE** no grupo de
Coordenação pedindo ao Fernando que confirme a parceira. Nada nesse card trava a venda — não abre
escalada, não pausa a IA, não muda estado.

### 5. O telefone: bolha determinística, e um carve-out nominal na rede anti-Pix

**O telefone nunca entra no prompt e nunca sai da boca da LLM.** `Parceria` não tem campo de
telefone; a tool não devolve o número; o `contato_da_parceira` é lido *fresh* pelo
`workers/coordenador.py`, depois do turno, e colado como última bolha — **exatamente o trilho da
chave Pix**, e pelo mesmo motivo (string crítica fora do LLM).

A colisão com `_RE_CHAVE_PIX` foi resolvida **sem afrouxar o regex**, que protege a chave de toda
modelo. `_bolha_descartavel` ganhou um carve-out de **uma forma exata**: `fullmatch` da bolha
inteira contra o formato que só o sistema produz (`contato da <Nome>: +DDDDDDDDDDDD`). Chave Pix de
verdade — e-mail, EVP, CPF, número solto, número no meio de uma frase — continua sendo derrubada, e
o carve-out não vale para nenhum dos outros três gatilhos do Estágio 0.

### 6. Mídia da parceira não é o book dela

`enviar_midia` ganhou `de: "eu" | "parceira"`, que troca o dono da query. O payload carrega o `de`
até `workers/envio.py`, onde `midia_conta_como_book` decide o carimbo: **foto da parceira não
carimba `book_enviado_em`**. Sem isso, mandar as fotos da Yasmin acenderia `<ja_enviou_book>` e
bloquearia o book da própria Catarina pelo resto da negociação — justamente nos dois fluxos em que a
foto da parceira sai cedo.

## Consequências

**Revogado.** O ramo "ele pede pra você trazer uma amiga sua" do `<composicoes>` não escala mais;
`<quando_usar_escalar>` perdeu o gatilho de composição no motivo `outro`; o `<ja_ofereceu_a_amiga>`
do contexto dinâmico não manda mais "Deixa eu ver com ela amor" e escale.

**Mantido.** `_ESCALADA_AMIGA` (`agente/_disciplina.py`) continua vetando o carimbo de
`amiga_ofertada_em`, e por um motivo que sobreviveu à revogação: *"deixa eu ver com ela"* promete um
retorno, não CONVIDA — e é `amiga_ofertada_em` que destrava o contato no fluxo A. Sem o veto, um
turno de promessa vazia liberaria o telefone. A fala em si virou **regressão de prompt**, com par em
`<armadilhas_de_voz>`.

**Mantido.** `_Avoid_: modelar Atendimento com duas Modelos no P0`. Nada muda no schema do
atendimento: continua o par (Cliente, Catarina). A parceira é regra de preço + um card.

**`<fora_do_cardapio>`** passa a ter **duas exceções legítimas** ao `cross_modelo_fishing`, ambas
chegando como bloco de contexto — nunca por conta própria da IA.

**Custo.** Uma query a mais por turno, só quando o burst pôs alguma família em pauta. `TOOLS` foi de
3 para 4 tools: o segmento de tools do prefixo muda de bytes e o cache de prefixo do DeepSeek
invalida **uma vez** (esperado, mesmo efeito da saída da `registrar_extracao`).

**Risco residual.** A bolha do contato, uma vez enviada, é persistida em `mensagens` e volta como
histórico da IA na janela dos turnos seguintes — o telefone reentra no prompt por essa porta,
exatamente como a chave Pix já reentra hoje. Não foi tratado aqui (seria uma redação de histórico,
que vale para os dois casos juntos); a trava "uma vez por atendimento" limita a exposição.

## Alternativas descartadas

- **`modelos.parceira_id`** — não comporta as três autorizações por par nem a direcionalidade.
- **Relaxar `_RE_CHAVE_PIX`** para não casar telefone — abriria a porta que a rede existe para
  fechar, em toda modelo, para ganhar uma bolha.
- **Formatar o telefone com espaços** para escapar do `\d{11,14}` — funcionaria por acidente, e
  qualquer mudança de formatação futura reintroduziria a falha em silêncio.
- **Deixar a LLM escolher o fluxo pela conversa** — o custo do erro é perder as duas vendas ou
  prometer o que ela não faz.
- **Bloquear a venda da dupla até o Fernando confirmar a parceira** — devolveria o cliente ao vácuo,
  que é o que este ADR existe para eliminar.
