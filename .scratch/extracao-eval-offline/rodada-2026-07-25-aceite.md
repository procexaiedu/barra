# Descrição do aceite: autocontida × referenciada — 25/07/2026

Relatório do item de medição do issue
`.scratch/extracao-revisao/issues/08-descricao-autocontida-do-aceite.md`.
Dado bruto: `rodada-2026-07-25-aceite.json` (ao lado).

**Veredito curto:** **sem regressão** — a descrição autocontida não perdeu nada em nenhum dos seis
campos. Mas o ganho que ela existe para dar **não é medível neste golden set**, pela mesma razão que
travou a pergunta 2 da rodada anterior: falta turno de cotação e a janela é recorte, não a janela
fiel. O que a rodada acrescenta a favor da autocontida é indireto (zero eco contra 8,3%), e a n=3
com temperatura 1.0 isso não é atribuível à mudança.

## Configuração

| item | valor |
|---|---|
| data | 2026-07-25, ~22h BRT |
| modelo | `deepseek-v4-flash` (endpoint direto, alias do `.env` sobrescrito na linha de comando) |
| golden set | 18 itens, `api/evals/extracao/golden_set.json` |
| repetições | 3 por item, por variante |
| chamadas | 18 × 3 × 2 = **108** |
| comando | `EXTRACAO_AUTORIZADA=1 DEEPSEEK_MODEL_CHAT=deepseek-v4-flash uv run python -m evals.extracao.bancada --real --variantes base,aceite-referenciado --repeticoes 3` |

Variantes — o que muda entre elas é **uma string**, a descrição inteira do campo `aceita_valor`; o
resto do schema e da janela é byte-idêntico. O eixo **não** é uma cláusula isolada: a autocontida
reescreve a regra toda (condição de logística, adiamento, o horário cravado após a cotação). Quem
ler a tabela como "o efeito da condição de logística" está lendo mais do que a rodada mediu.

> ⚠️ **Atenção ao comparar com `rodada-2026-07-25.md`:** lá a `base` era a descrição **referenciada**
> (o que prod rodava então). Aqui a `base` é a **autocontida**. O nome é o mesmo, o baseline não —
> números de `aceita_valor` não são comparáveis entre os dois relatórios.

> ⚠️ **A `base` medida não é byte-idêntica ao que subiu.** A revisão de código, posterior à rodada,
> mostrou que "só vale como sim depois de você já ter recusado baixar o preço" ficava mais estreita
> que o canônico do `<desconto>` — que não exige recusa: depois de um degrau **concedido**, a
> pergunta de logística também é sim ao valor da mesa. O texto que subiu diz os dois ramos
> ("recusando… ou com a sua contraproposta…"). Como `aceita_valor` empatou em 0/0/1/8 nas duas
> variantes — nenhum item do golden set discrimina esse campo —, a correção não muda nada do que
> esta rodada conseguiu medir; mas o gate de regressão vale, à risca, para o texto medido.

- **`base`** — a descrição **autocontida**, que este ticket subiu para produção: a regra do
  avanço-que-equivale-a-sim escrita no campo, com a condição contextual ("pergunta de horário ou de
  logística só vale como sim depois de você já ter recusado baixar o preço") e o adiamento
  explicitamente fora.
- **`aceite-referenciado`** — a descrição que rodava até hoje, com a delegação órfã: "o avanço que
  equivale a sim (siga a sua conduta de `<desconto>`)" — bloco que a chamada barata não recebe.

## Resultado

| campo | manda | base (autocontida) | aceite-referenciado |
|---|---|---|---|
| `aceita_valor` | precisão | recall 0.000 ±0.000 — 0/0/1/8 | recall 0.000 ±0.000 — 0/0/1/8 |
| `intencao` | recall | **1.000 ±0.000** | 0.889 ±0.157 [0.667–1.000] |
| `horario_desejado` | ambos | 1.000 ±0.000 | 1.000 ±0.000 |
| `horario_evidenciado` | ambos | 1.000 ±0.000 | 1.000 ±0.000 |
| `tipo_atendimento` | precisão | sem positivo previsto (0/0/0/2) | sem positivo previsto (0/0/0/2) |
| `recuo` | ambos | 1.000 ±0.000 | 1.000 ±0.000 |
| eco (campo reenviado sem nada novo) | — | **0.0%** | 8.3% (1 em 12) |

## Leitura

**No campo que a mudança ataca, as duas empatam — e o empate é do gabarito, não do modelo.** Dos 9
itens rotulados em `aceita_valor`, 8 não têm valor nenhum na janela: não marcar aceite é
trivialmente correto nos dois lados, e nenhuma das descrições produziu falso positivo. O nono
(`34-aceite`) é o falso negativo que aparece nas duas: o recorte da conversa é
`ia: "Consigo às 17:30" || cliente: "Tipo 18h, 18h15"`, e a cotação que sustenta o rótulo humano
`true` está **fora** da janela. Sem preço à vista, não marcar "aceitou o valor" é a leitura certa do
que foi mostrado — nas duas variantes.

Ou seja: os dois falsos positivos que motivaram o ticket (#24 "Aonde atende", #8 "seria do seu local
dlc?") **não estão no golden set com o contexto que os torna discrimináveis**. A regra nova — a que
diz que pergunta de logística só vale como sim depois da recusa de desconto — não teve um único item
onde pudesse mudar o veredito.

**A diferença medida está fora do campo do eixo**, e é a assinatura conhecida do sampling: a
variante referenciada reenviou um campo já registrado em 1 de 12 oportunidades e, em 1 das 3
repetições, deixou uma intenção escapar. A rodada de temperatura (25/07) já tinha mostrado eco em 3
de 10 repetições com temperatura 1.0 e 0 de 5 com zero. Atribuir isso à descrição do aceite, com
n=3, seria ler ruído como sinal. O que dá para dizer com honestidade: **o lado autocontido não
perdeu em nada**, e o único movimento observado foi a favor dele.

## Por que a mudança sobe assim mesmo

O argumento que sustenta a troca não é este número — é estrutural, e independe de corpus: a chamada
barata **não recebe** o `<desconto>`. A descrição antiga mandava seguir uma conduta que o leitor
nunca lê. Uma referência órfã não fica melhor por não ter aparecido no golden set; ela fica sem
teste. A bancada aqui cumpre o papel de **gate de regressão** — a descrição maior não degradou
nenhum dos campos que já estavam bons — e não o de prova de melhoria, que este corpus não pode dar.

## O que falta (o mesmo de sempre, agora com um caso a mais)

1. **Turnos de cotação rotulados** e, principalmente, **itens de pergunta-de-logística com preço na
   mesa** — o padrão do #24 e do #8. Sem eles não há como medir a regra nova.
2. **Janela fiel em vez de recorte** (`replay.py`, exige `TEST_DATABASE_URL`): enquanto o rótulo
   humano vê a conversa inteira e o extrator vê quatro falas, `aceita_valor` não é mensurável com
   justiça.
3. **Nível trajetória** — não rodado aqui, pelo mesmo motivo.
4. **A recusa de desconto no bloco de estado** (issue 09, aberto pela revisão deste ticket): a
   condição que a descrição agora enuncia depende de o extrator ver a negociação de preço, e a
   janela é deslizante. Sem `n_contrapropostas` no `<ja_registrado>`, a regra vale só enquanto a
   escada couber na janela.
