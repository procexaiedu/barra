---
data: 2026-08-11
status: aceito
supersedes: ADR-0035 (o regime "por pessoa dobra o pacote", inteiro)
refina: ADR-0038 (composição passa a ser mais um caso da linha de 1h), ADR-0030 (preço cadastrado
  de composição é o TOTAL do extra — o `× 2` deixa de existir)
---

# ADR-0039 — Composição (casal/ménage) segue exatamente o regime do extra de fetiche

## Contexto

O ADR-0035 deu a casal/ménage um regime de preço PRÓPRIO: `cobra_por_pessoa` no catálogo global e,
com a flag ligada, o extra é o **pacote inteiro** (o pacote dobra). O ADR-0038, ao trocar a fórmula
do extra dos atos (preço-hora → linha de 1 HORA do mesmo programa, no patamar vigente), declarou
explicitamente que o 0035 ficava **intocado**.

Ficaram então dois regimes de preço sobre a mesma superfície, e o dono do produto revisou os dois
juntos em 11/08/2026, sobre a tabela real da Catarina (programa Normal: 30min 250 · 1h 400/min 300
· 2h 800/min 600 · 3h 1.000/min 900 · pernoite 2.000/min 2.000). Três problemas:

1. **O dobro não é um preço; é um multiplicador do pacote.** Ele herda a curva do pacote, que é
   desenhada para CAIR por hora (ADR-0004). A segunda pessoa custava R$800 na 2h, R$1.000 na 3h e
   R$2.000 no pernoite — pelo mesmo "produto". É o mesmo defeito que o ADR-0038 removeu do lado dos
   atos, sobrevivendo do outro lado do `if`.
2. **A coluna `modelo_fetiches.preco` tinha DUAS regras.** Para um ato, o número cadastrado era o
   extra; para uma composição, era o valor "de uma pessoa" e o sistema dobrava. Bug real e
   previsível: *cadastrei 700 e saiu 1400*. Uma coluna com duas semânticas depende de o operador
   lembrar de qual linha ele está olhando.
3. **O `preco_pacote` mantinha vivo um acoplamento que já não servia a mais nada.** Ele era
   parâmetro de `extra_de_fetiche`/`calcular_preco_extra_fetiche` só para alimentar o dobro. Com o
   dobro fora, o extra deixa de depender do preço do pacote em qualquer regime.

## Decisão

**Composição segue exatamente a regra dos fetiches-ato do ADR-0038.** O extra da segunda pessoa é o
**preço da linha de 1 HORA do mesmo programa, no patamar de desconto vigente**, somado uma vez e
**fixo em relação à duração** do pacote.

Os números que isso produz na tabela da Catarina (total para os dois, por patamar):

| pacote | cheio | degrau | piso | (regime revogado, cheio) |
|---|---|---|---|---|
| 1h | 800 | 700 | 600 | 800 |
| 2h | 1.200 | 1.050 | 900 | 1.600 |
| 3h | 1.400 | 1.250 | 1.200 | 2.000 |
| Pernoite | 2.400 | 2.350 | 2.300 | 4.000 |

A **1h não muda** — os dois regimes coincidem lá (o pacote É a linha de 1h). É o que torna esta
mudança barata de reverter e o que obriga todo cenário de eval de ménage a ancorar em 2h ou mais.

### O que NÃO muda

- **A coluna `barravips.fetiches.cobra_por_pessoa` continua existindo e continua sendo lida.** Ela
  deixa de ser regime de PREÇO e passa a ser **CLASSIFICAÇÃO**: é ela que abre a seção "Por pessoa"
  do `<fetiches>`, que sustenta o `casal_em_pauta` do `<foco_do_turno>` e que decide o gate
  `<sem_menage>` do bloco por-modelo. Nenhuma migration; nenhum dado tocado.
- **A seção "Por pessoa" continua separada no prompt.** Não porque o número é outro — é o mesmo —,
  mas porque a FALA é outra: a coluna dela é "Total com a 2ª pessoa" (uma), e não "+1 fetiche /
  +2 fetiches". Fundir as seções faria a IA oferecer "duas segundas pessoas".
- **A conduta de escalada do `<menage>`** (o ramo "ele pede que você traga uma amiga sua") não é
  tocada aqui: é decisão de produto separada.

### O que muda

- **Preço CADASTRADO de uma composição passa a ser o TOTAL do extra.** O `× 2` morre. Uma coluna,
  uma regra. Risco de dado zero: `atendimento_fetiches` e `atendimento_servicos` estão vazias em
  prod e toda composição cadastrada carrega o sentinel `1.00` ou `NULL` — não existe número de
  verdade gravado sob a semântica velha.
- **`preco_pacote` e `cobra_por_pessoa` saem da assinatura das duas funções de conta.** Não é
  cosmética: enquanto os parâmetros existirem, existe um caminho para o pacote dobrar de novo. O
  tipo é o que obriga cada chamador a se declarar — e foi assim que os quatro apareceram.
- **Composição passou a DEPENDER da linha de 1h.** O regime velho era o único que funcionava sem
  ela (o pacote inteiro sempre existe). Agora ela cai no mesmo `None` fail-closed dos atos: o render
  OMITE a linha, o guard não legitima o total, o painel devolve 409
  (`sem_linha_de_uma_hora_para_o_extra`) e o fechamento descarta com warning. É a única
  **regressão de cobertura** da mudança, e é deliberada: sem a 1h não há de onde derivar, e inventar
  uma base a partir do pacote é exatamente o que o ADR-0038 removeu.
- **O `output_guard` ESTREITA o conjunto de valores legítimos.** `base * 2` sai de
  `_valores_legitimos`: "1.600" numa 2h de 800 passa a ser preço fantasma. É o único ponto desta
  mudança que BLOQUEIA fala em vez de só trocá-la. **Conversa em andamento não quebra**: o conjunto
  já inclui todo preço que a própria IA citou em turno anterior (o ramo das `AIMessage`s do
  histórico, via `extrair_precos_citados`, que não consulta tabela nenhuma) mais os degraus/piso
  computados sobre ele. Uma conversa que já ouviu "1.600" continua podendo repetir 1.600; o que o
  guard passa a impedir é a IA INVENTAR o dobro numa conversa nova.

### Onde vive

`dominio/atendimentos/service.py`, site único como antes:

- `extra_de_fetiche(linha_de_uma_hora, duracao_horas, *, patamar="cheio", preco_cadastrado=None)
  -> Decimal | None` — resolve cadastro → derivado;
- `calcular_preco_extra_fetiche(linha_de_uma_hora, duracao_horas, *, patamar="cheio")
  -> Decimal | None` — o derivado.

`BaseDoPacote.preco` foi removido junto (era consumido só pelo dobro); o fail-closed de preço
AMBÍGUO em `_base_do_pacote` fica, porque ele não existe para achar um número e sim para saber se dá
para dizer QUAL pacote foi vendido.

Os quatro chamadores do site único, e como cada um se declarou depois que o tipo os obrigou:

| chamador | como se declarou |
|---|---|
| `agente/persona.py:_grupos_de_extra` | perdeu o kwarg `por_pessoa`: as duas seções passam pela MESMA chamada, e o que as separa é só o template |
| `agente/nos/output_guard.py:_valores_legitimos` | dois sites — o derivado perdeu `preco_pacote`; o cadastrado perdeu o par `(unitário, por_pessoa)` e virou uma lista de `Decimal` |
| `dominio/atendimentos/routes.py:adicionar_fetiche` | perdeu o `preco_tabela` somado dos serviços e o `JOIN fetiches` que só trazia a flag |
| `dominio/atendimentos/service.py:registrar_fetiches_do_fechamento` | passou a resolver a base só pela linha de 1h; o `cobra_por_pessoa` sobreviveu apenas dentro do `extra` do warning de descarte |

(Um quinto chamador nasceu depois do ADR-0038 e entra na mesma conta:
`agente/nos/prepare_context.py:_total_com_fetiche`, o total pré-computado do `<servico_em_pauta>`.)

## Alternativas rejeitadas

- **Remover a coluna `cobra_por_pessoa`.** Rejeitado: ela não é só preço. Sem ela morrem o
  `casal_em_pauta`, o gate `<sem_menage>` e a própria seção "Por pessoa" — a IA perderia a distinção
  entre "faço ménage" e "não faço", que é conduta, não aritmética.
- **Manter o `× 2` só para o preço CADASTRADO** (dobrar o cadastro, derivar o resto como ato).
  Rejeitado: é exatamente a duas-regras-numa-coluna que produziu o "cadastrei 700 e saiu 1400". Se a
  agência quiser cobrar mais pela segunda pessoa, o lugar é o campo de preço, com o número inteiro.
- **Um multiplicador numérico por fetiche (×N).** Já rejeitado pelo ADR-0035 e continua rejeitado
  pelo motivo oposto ao de lá: agora não há multiplicador nenhum a parametrizar.

## Consequências

- Prompt: `fetiches.md.j2` (seção "Por pessoa" reescrita — a prosa passa a NEGAR o dobro),
  `regras.md.j2` (`<cotacao>` e a parte aritmética do `<menage>`).
- **Pendente, em arquivo de outra frente:** `foco_do_turno.md.j2` (`<item status="por_pessoa">` e
  `<casal_em_pauta>`) ainda diz que o total sai da tabela "Por pessoa" *"(ela já é o valor para 2)"*
  — a tabela continua sendo o número certo a copiar, mas o parêntese descreve o regime revogado.
  `bloco_da_modelo.md.j2` (`<sem_menage>`) ainda proíbe "dobrar pacote nenhum", proibição que agora
  fala de uma conta que não existe mais.
- Painel: o aviso "digite o valor de UMA — são duas, e a IA cobra em dobro" virou instrução ERRADA
  e foi trocado em `ProgramasModelo.tsx` e `PainelFetiches.tsx`.
- Eval: o cenário e2e `menage_com_secao` inverte (o certo passa de 1.400 para 1.100 = 700+400; o
  proibido passa a ser 1.400) e a fixture de segurança `005` foi renomeada — ela cadastrava Ménage a
  700 e afirmava 1.400, número que o regime velho NÃO produzia (produzia 2.100); sob esta regra ela
  ficou correta, e o proibido dela passou a ser 2.100.
- **Reversão barata**: a 1h é idêntica nos dois regimes, então nenhuma conversa de 1h muda de
  número — e 1h é o pacote que mais vende.
