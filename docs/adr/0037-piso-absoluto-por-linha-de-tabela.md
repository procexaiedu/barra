---
data: 2026-08-11
status: aceito
refina: ADR-0004, ADR-0031 (o piso continua percentual; ganha um clamp por linha)
---

# ADR-0037 — Piso absoluto por linha de tabela (`preco_minimo`), acima do percentual global

## Contexto

O **Piso de desconto** nasceu como percentual global sobre o **Preço de tabela** (ADR-0004) e
virou dois percentuais globais na escalada de duas rodadas (ADR-0031): `desconto_degrau_pct`
(~12,5%) e `desconto_teto_pct` (~25%). O ADR-0031 rejeitou explicitamente "valores absolutos
cadastrados por (modelo, programa, duração)" com o argumento de que os números da reunião
(R$50/R$100 sobre o Normal de 400) eram *proporcionais*, e a fórmula percentual generalizava
sozinha.

Ao subir a **Catarina** (11/08/2026), Fernando descreveu a tabela dela em três linhas:

> "400 1h / Com desconto 300 1h / Mínimo 250 30min"

As duas primeiras o percentual já entregava por acidente aritmético — 400 × (1 − 0,25) = 300. A
terceira quebrou o modelo de duas maneiras:

1. **Não havia duração de 30min** em `barravips.duracoes` (só 1h/2h/3h/4h/6h/8h/12h), então o
   pacote não era cadastrável. Sem ele na tabela, o `<girias_do_cliente>` manda a IA **negar**
   meia hora ("30min não tenho amor, mínimo 1h 400") — o cliente de bolso curto era recusado em
   vez de comprar, e o passo 2 do `<desconto>` ("desça o tempo, não o preço") não tinha para onde
   descer, apesar de o próprio exemplo do prompt ser, literalmente, "250 30minutos amor".
2. **"Mínimo" não é um conceito que o percentual saiba expressar.** Cadastrar 250 sozinho faria a
   escada descontar sobre ele: 219 no degrau, 188 no teto. Um mínimo que desconta não é mínimo.

O caso (2) é a refutação da premissa do ADR-0031: um pacote curto não é uma linha proporcional
como as outras, é o **fundo da tabela** — existe justamente para ser o menor número que ela faz.

## Decisão

- **Nova coluna `modelo_programas.preco_minimo` (nullable)**: piso ABSOLUTO daquele par
  programa × duração. Preenchido, clampa as duas contas da escada:
  `oferta = max(preço × (1 − pct), preco_minimo)`. `preco_minimo = preco` = linha **não
  descontável**. NULL preserva o comportamento anterior — só o percentual manda —, então a coluna
  nasce inerte para todo o cadastro existente.
- **O percentual global continua sendo a regra padrão.** O mínimo é exceção por linha: regra da
  CASA vs regra DESTA modelo neste pacote, e a mais apertada vence. Não há mínimo global.
- **Linha sem desconto a dar não vira contraproposta**: quando a conta clampada devolve o próprio
  preço de tabela, a cauda não injeta número nenhum (`teto_de_contraproposta` /
  `degrau_de_contraproposta` → None) e o feedback do gatilho `preco` cai na mensagem estática.
  Mostrar "consigo 250" sobre uma tabela de 250 ensinaria a IA a apresentar o próprio preço como
  concessão.
- **O mínimo nunca é renderizado no prompt** — mantém o ADR-0004 §Decisão item 5 ao pé da letra
  (expor o piso ensina a IA a ancorar nele ou a vazá-lo). Ele só clampa os números que o código
  calcula e injeta.
- **Duração de 30min entra no catálogo global** (`duracoes`, `horas = 0.5`, `ordem = 0`), não como
  seed por modelo. Os preços por modelo seguem entrando por painel/MCP.

## Alternativas rejeitadas

- **Flag booleana `descontavel`.** Resolve o caso da Catarina (250 não desconta) com menos
  superfície, mas não expressa "400 desce até 300 e não menos" sem depender do percentual global —
  e era justamente a dependência que se queria cortar: hoje mexer em `desconto_teto_pct` mexeria no
  piso da Catarina junto, em silêncio.
- **Mínimo por modelo (uma coluna em `modelos`).** Mais barato de cadastrar, mas o mínimo é
  propriedade do PACOTE, não da pessoa: os 250 são o mínimo dos 30min, não da Catarina — na 1h o
  mínimo dela é 300.
- **Piso derivado ("nunca abaixo do menor pacote da tabela").** Não resolve nada: o pacote de 250
  É o menor da tabela, e descontar sobre ele desceria abaixo dele.
- **Preço-hora mínimo global (R$300/h, o pedido do feedback de 21/07).** Continua em aberto como
  rede de segurança para período que a IA improvisa, mas é ortogonal a este ADR: aqui a duração
  existe na tabela e o número está cadastrado — não há improviso a barrar.

## Consequências

**Positivas**
- O "com desconto 300" da Catarina vira **dado cadastrado**, não coincidência do percentual.
- O pacote de resgate (250/30min) passa a ser vendável, ativando o passo 2 do `<desconto>` que já
  existia no prompt e não tinha lastro no cadastro.
- Reversível por dado: limpar a coluna devolve o comportamento de antes, sem deploy.

**Negativas / a acompanhar**
- Terceiro lugar onde uma "regra de preço" mora (percentual global em `settings`, preço em
  `modelo_programas.preco`, piso em `modelo_programas.preco_minimo`). O clamp vive nos dois sites
  únicos (`piso_de_desconto`/`degrau_de_desconto`) de propósito — qualquer conta nova de desconto
  tem que passar por eles ou o piso fura.
- A tabela da Catarina passa a ter **duas linhas de "Normal"** (30min e 1h). Isso re-ancorou a
  primeira cotação: `_menu_primeira_cotacao` pegava "a primeira duração da ordem" e passaria a
  abrir em "250 na 30 minutos". Corrigido para ancorar na **1h**, que é o que o `<cotacao>` manda
  ("o programa mais em conta da sua tabela, na 1h") — mas é o tipo de acoplamento que volta a
  morder se outra modelo cadastrar um pacote curto e alguém mexer nessa função.
- Duração fracionária estreou na tabela: os templates concatenavam "h" na variável crua e o
  pacote sairia como "(0.5h)" na cauda. Resolvido com o filtro `duracao_de_pacote` ("30min").
