# Plano — de quem é essa chave? A atribuição do dinheiro

> Origem: reunião de alinhamento de 20/08/2026 (`reuniaoalinhamento.txt`) + o export real do grupo
> da Yasmin. Relaciona: ADR-0047 (o bolso é fato da venda), ADR-0046, spec 0006.
> Decisão: **ADR-0049**. Tickets: `.scratch/chaves-e-atribuicao/issues/` (7).

## 1. O problema, dito com precisão

O dinheiro de **um** atendimento pode cair em pelo menos **seis** lugares, e a operação não registra
em qual:

| # | Onde cai | O que a ata diz |
|---|---|---|
| 1 | Pix da casa | *"a gente pode padronizar o atendimento pra receber com uma forma de pagamento nossa que não vai ser uma, **a gente pode ter umas cinco**"* |
| 2 | Pix da modelo | *"quando a mina tem a conta e a mina é de confiança, ela recebe no dela"* — e **varia por atendimento** |
| 3 | Dinheiro | sempre na mão dela |
| 4 | Maquininha da casa | *"o ideal é ser na nossa conta"* |
| 5 | Maquininha da modelo | *"a mina tem a máquina no celular dela, que é aquele PagBank/InfinitePay"*; *"se o cara tiver só aproximação, aí ela recebe no dela"* |
| 6 | Link / gateway | não existe ainda; a forma já entrou no schema |

Mais o **deslocamento**, que tem destino próprio e igualmente indefinido: *"ele sempre manda pra
conta da empresa? — vai depender."*

O ADR-0047 já concluiu, corretamente, que **isso não é parâmetro de cadastro da modelo** — o dono
negou que exista padrão por pessoa. Mas concluir "é fato da venda" só move o problema: alguém tem
que **observar** o fato. Hoje ninguém observa, e toda venda nasce `nao_dito`.

## 2. O que o sistema tem hoje — e por que não resolve

Existem **três cadastros de chave Pix** e **duas validações**, que não se falam:

| Onde | O quê | Estado real |
|---|---|---|
| `barravips.chaves_pix_conhecidas` | lista plana da casa (`chave`, `titular`, `descricao`, `ativo`) | **1 linha** no `barra_test` |
| `modelos.chave_pix` + `titular_chave` | a chave que a IA **entrega ao cliente** para o Pix de deslocamento | **0 modelos preenchidos** |
| `comprovante.py::chave_e_conhecida()` | devolve **`bool`** — "está na lista da casa ou não" | usado no grupo financeiro |
| `workers/pix.py::_chaves_compativeis()` | compara com **a chave daquela modelo** | usado no Pix de deslocamento |

O próprio código já reconhece a duplicação — `comprovante.py:69` diz, com todas as letras:
*"`workers/pix.py::_chaves_compativeis` — comparar chave Pix é o mesmo problema nos dois lugares."*

Três consequências concretas:

1. **A resposta é um booleano quando a pergunta tem três respostas.** "Não está na lista da casa"
   engloba *a chave da própria modelo* (informação valiosa) e *a chave de um terceiro qualquer*
   (ruído). O aviso `⚠️ Esse Pix foi pra uma chave fora da lista da casa` dispara igual nos dois.
2. **O `bolso.py` está pronto e sem chamador** porque não tem entrada confiável. Nenhum caminho de
   produção grava `bolso = 'empresa'`. A venda que o cliente pagou direto na conta da casa fica
   `nao_dito`, o razão a trata como `dela` pelo default conservador, e **debita dela um bruto que
   ela nunca teve**.
3. **O Pix de deslocamento valida contra a chave errada — e o bug está DORMENTE.**
   `workers/pix.py:341-348` confere o destino contra `modelos.chave_pix` e marca *"chave
   divergente"*. Mas a checagem é guardada por `chave_modelo and ...`, e **nenhuma modelo tem a
   chave preenchida (0 de 0) — ela nunca disparou**. Preencher o cadastro, que é o que a Fase 1
   pede ao dono, **acorda** a checagem: todo deslocamento que legitimamente foi para a conta da
   casa passa a cair em revisão manual. ⚠️ **A regressão é disparada por dado, não por deploy** —
   por isso o ticket 01 vem antes de qualquer coleta de chave.

## 3. A ideia central

**A chave deixa de ser uma lista e passa a ser um mapa de papéis.** O comprovante já carrega o
destino; o que falta é o destino significar alguém.

```
chave_e_conhecida(chave) -> bool          ❌ hoje
papel_da_chave(chave)    -> PapelDaChave  ✅ proposto
```

`PapelDaChave = casa | modelo(<quem>) | telefonista(<quem>) | terceiro | desconhecida`

Com isso, a classificação do comprovante — que o `comprovante.py` já organiza pelas duas perguntas
certas, **quem pagou × quem recebeu** — deixa de depender de heurística de nome e passa a sair de
uma tabela. E `bolso.py` ganha a entrada que está esperando.

**Isto é o que o pedido "mapear qual chave é padrão da casa e quais são das modelos" vira em
software** — mais o terceiro caso, que a ata mostra e que ninguém tinha nomeado.

## 4. As fases

### Fase 1 — o cadastro tipado (a base de tudo)

`chaves_pix_conhecidas` ganha `papel`, `modelo_id` / `vendedor_id` (quando o papel os pede), e
`padrao boolean` — **uma só chave padrão da casa**, que é o *"vou botar a Pix, que normalmente é o
padrão que a gente mais recebe"* do Rossi.

⚠️ **Uma armadilha a decidir antes de codar.** "Chave da modelo" tem **dois sentidos** que hoje
colidem no mesmo campo `modelos.chave_pix`:

- **de onde o dinheiro do cliente cai** (evidência de bolso), e
- **para onde a casa manda o repasse dela** (destino de pagamento).

Se ficarem no mesmo lugar, um repasse da casa **para** ela pode ser lido como uma venda **dela**, e
o razão dobra. Proposta: `chaves_pix_conhecidas` passa a ser o registro (uma modelo pode ter várias
— CPF, telefone, aleatória, e ela troca de banco), e `modelos.chave_pix` sobrevive apenas como *a
chave preferida para receber repasse*, com o comentário dizendo isso.

### Fase 2 — a leitura vira decisiva, e o `bolso.py` liga

`papel_da_chave` substitui `chave_e_conhecida` no grupo financeiro. As quatro classes de comprovante
passam a sair de (papel do pagador × papel do destino). O `bolso` da venda deixa de ser `nao_dito`
sempre que houver comprovante — que é a maioria dos casos que importam.

Ganho medível: a proporção de vendas com `bolso` resolvido. Hoje é ~0% para `empresa`.

### Fase 3 — chave desconhecida vira aprendizado, não alarme

Hoje toda chave fora da lista gera o mesmo aviso, e o gestor aprende a ignorá-lo. Proposta: chave
desconhecida **recorrente** vira sugestão de cadastro no painel — *"esta chave apareceu 4 vezes em 3
semanas, sempre recebendo da Yasmin — de quem é?"* — com um botão que a classifica. O cadastro se
preenche sozinho pelo uso, sem ninguém inventar.

O alarme imediato fica só para o caso que merece alarme: **chave desconhecida recebendo valor de
venda pela primeira vez**.

### Fase 4 — cartão pelo mesmo mecanismo

Cartão não tem chave, então o registro não ajuda — mas o **print da maquininha** que a modelo já
manda carrega o **nome do estabelecimento**. É a mesma evidência, noutro campo. Um registro de
estabelecimentos (`casa | modelo`) resolve débito, crédito e aproximação com a mesma lógica, sem
inventar campo novo na ficha e sem virar cadastro de confiança — que o ADR-0047 proíbe.

### Fase 5 — o Pix duvidoso, que já existe pela metade

O Rossi levantou duas vezes: *"pra ver se o cliente talvez não mandou o Pix zoando"* e *"a gente tem
uma forma de identificar se o Pix foi duvidoso"*. O `workers/pix.py` já extrai
`plausibilidade_visual` + `motivo_se_implausivel` do OCR, e `MotivoRejeicao` já tem
`valor_incorreto`, `conta_destino_errada`, `duplicado`. Falta unificar isso com o comprovante do
grupo financeiro, que hoje tem o próprio caminho e a própria dedup por foto.

### Fase 6 — o gateway próprio (endgame)

*"O ideal seria a gente ter o pagamento direto no WhatsApp — fechou, já manda pro cara o QR Code do
Pix na conversa."* É a única fase que **elimina** a ambiguidade em vez de reconciliá-la depois: toda
chave nasce cadastrada, e o pagamento chega já atribuído. As cinco formas da casa viram cinco
contas conhecidas de nascença.

Não faz sentido começar por aqui — mas faz sentido que as fases 1 e 2 sejam desenhadas para que ele
entre como mais um papel, não como reescrita.

## 5. O que precisa do Rossi, e é pequeno

A fase 1 não anda sem dado, e o dado é curto:

1. **As chaves da casa** — ele disse que podem ser cinco. Quais são hoje, e **qual é a padrão**.
2. **A chave de cada modelo ativa** — já está na lista de cadastro faltante da spec 0006.
3. **A chave de cada telefonista**, se o deslocamento cai na conta deles.
4. **A maquininha**: de quem é, hoje, para cada modelo ativa — e o nome que aparece no print.

O item 4 ele já disse que não sabe (*"não sei te responder"*). Tudo bem: a fase 3 aprende pelo uso.

## 6. O que este plano NÃO resolve

- **Dinheiro vivo** não tem evidência nenhuma, e nunca terá. Continua `dela` por regra (ADR-0047), e
  isso está certo.
- **Chave de terceiro legítimo** (o agiota do exemplo, um fornecedor) continua exigindo julgamento
  humano na primeira vez. O registro só evita perguntar de novo.
- **A confiança na palavra da modelo.** Se ela disser "foi pix" e não mandar comprovante, o bolso
  segue `nao_dito`. O canal continua sendo a cobrança consolidada da manhã.
