---
status: superseded em parte pelo ADR-0038 (a fórmula preço-hora saiu; o resto segue de pé)
supersedes: parte do ADR 0014 (preço cadastrado por modelo×fetiche)
amended: 2026-08-11 (o preço cadastrado por fetiche volta a ser a fonte de verdade do extra; o cálculo derivado deste ADR vira fallback)
superseded-by: ADR-0038 (2026-08-11 — o extra derivado passa a ser a linha de 1 HORA do mesmo programa, no patamar vigente)
---

> **Nota de 2026-08-11 (ADR-0038).** A fórmula central deste ADR — extra =
> `preco_tabela ÷ duracao_horas` — **não vale mais**. O extra derivado é o preço da linha de **1
> hora do mesmo programa**, no patamar de desconto vigente. O preço-hora coincidia por acidente
> em 1h e 2h (400/1 e 800/2 dão os mesmos 400) e divergia justamente onde a tabela deixa de ser
> linear: 3h a R$1.000 dava +R$333, pernoite a R$2.000 dava +R$333 — o mesmo ato mais barato para
> quem compra mais tempo. Leia este ADR pelo que ele decidiu e o **ADR-0038** pela conta. O que
> continua valendo daqui: o extra é derivado (não cadastrado por modelo) quando não há preço na
> coluna, soma uma vez por fetiche, não auto-soma o Valor final e o Desconto incide sobre o
> pacote. A promessa de "assinatura congelada" da Revisão abaixo também morreu no 0038 — a
> entrada mudou de natureza, e um chamador que compilasse igual estaria fazendo a conta errada.

# ADR-0030 — Preço do Fetiche calculado a partir do programa, não cadastrado

## Contexto

O ADR-0014 modelou `modelo_fetiches.preco` como um valor **livre**, digitado por modelo, com `NULL` = incluso e um número = extra pago. Na reunião de colocação da IA em produção (2026-07-20, grillada em `grill-with-docs`), o dono do domínio descreveu uma regra de precificação distinta: todo fetiche pago vale **o preço-hora efetivo do pacote que o cliente está comprando naquele atendimento** — não um valor fixo por modelo. Exemplo dado: completo a R$500/h + um extra = +R$500 (o extra "conta como mais uma hora"); "beijo grego" a R$600/h descrito como "o dobro" = base + 1h ao preço-hora, mesma aritmética.

## Decisão

- **`modelo_fetiches.preco` vira flag, não valor.** A tabela para de guardar um número; guarda só se o fetiche é **incluso** ou **pago** por aquela modelo (`booleano` ou `preco NULL`/`not NULL` sem uso do valor — detalhe de schema fica para o /to-spec).
- **Valor do extra é sempre calculado, nunca gravado por modelo:** `preco_extra = preco_tabela_do_programa_vendido ÷ duracao_horas_vendida` (preço-hora efetivo do pacote no atendimento), somado **uma vez por fetiche pedido**. Uniforme entre fetiches — nenhum fetiche vale mais que outro.
- **Multi-hora usa o preço-hora efetivo do pacote, não uma duração-base de 1h.** Pernoite (12h) a R$3.600 → cada fetiche soma +R$300, não o preço de uma combinação `programa×1h` separada. Consistente com upsell de pacote maior = preço/hora menor (ADR 0004).
- Mantém-se do ADR-0014: sem duração própria, snapshot no atendimento (`atendimento_fetiches`), **não auto-soma o Valor final** (segue manual, entra só no breakdown), **Desconto de fechamento** incide sobre o pacote (programa + extras).

## Alternativas rejeitadas

- **Preço absoluto cadastrado por modelo×fetiche (status quo do ADR-0014).** Rejeitado — não é o que o dono do domínio descreveu na reunião; a intenção é o valor variar com o programa/duração vendidos, não ficar fixo.
- **Multiplicador por fetiche (1x default, 2x para casos como "dobro").** Rejeitado por ora: todos os exemplos concretos da reunião reduzem à mesma aritmética (+1x o preço-hora do pacote). Adicionar um multiplicador por fetiche seria grau de liberdade não pedido — reabrir se aparecer um fetiche que realmente precise valer mais que os outros.

## Consequências

- Migration em `modelo_fetiches`: `preco` deixa de ser lido como valor monetário; vira flag incluso/pago (campo pode ser reaproveitado como booleano ou mantido `NULL`-vs-`NOT NULL` sem o número importar — decisão de schema no /to-spec).
- Cálculo do preço do extra passa a depender do programa/duração escolhidos no atendimento — precisa entrar na cotação da IA e no cálculo de piso/desconto (`_abaixo_do_piso`, ADR 0004) como valor derivado, não lido de coluna.
- `agente/nos/prepare_context` (BP3) não muda o que expõe (fetiche que a modelo faz, incluso/pago) — só o `+R$X` que a IA cota passa a ser calculado em vez de lido.

## Revisão 2026-08-11 — o preço cadastrado volta a ser a fonte de verdade

**Contexto.** O diagnóstico de input de 11/08/2026 (4 atendimentos, harness fiel, dumps em
`.scratch/diag-input-20260811/`) mostrou o custo do "preço decorativo": a modelo tinha Inversão
cadastrada a R$350 e o `<fetiches>` renderizado dizia `| Encontro (1 hora) | +R$400 | R$800 |` —
o extra derivado do preço-hora do pacote. A IA cotou "800 a 1h com a inversão"; o cliente
respondeu *"vc falou 400 a hora e 350 a inversao, nao era 750?"*. A conta da IA estava fiel ao
prompt, mas divergia do que o operador cadastrou — e o cadastro é o que a modelo combinou.

**Decisão do dono do produto (via dev, 11/08/2026).** O que o painel cadastra por fetiche é o
extra: `modelo_fetiches.preco` preenchido com um valor real passa a ser o extra cobrado, **fixo,
independente da duração do pacote**. O cálculo deste ADR (preço-hora efetivo) vira **fallback**,
para fetiche pago sem preço cadastrado. ~~`cobra_por_pessoa` (ADR-0035) continua valendo por cima
do unitário.~~ **Revogado pelo ADR-0039**: o `× 2` sobre o cadastro deixou de existir — o número
cadastrado é o TOTAL do extra, seja de um ato ou de uma composição (uma coluna, uma regra).
Incluso × pago segue sendo `preco` NULL × NOT NULL — a distinção não muda.

**Onde vive.** `dominio/atendimentos/service.py`: `extra_de_fetiche` (site único da conta,
resolve cadastro → fallback) e `preco_cadastrado_de_fetiche` (separa número real de flag).
`calcular_preco_extra_fetiche` fica com **a assinatura congelada** — é o que o
`_valores_legitimos` do `output_guard` chama direto, e é ele que mantém render e guard
consistentes enquanto o guard não souber ler o preço cadastrado.

**Sentinel — a razão do piso.** Ao implementar o ADR-0030 a API do painel deixou de aceitar preço
de fetiche (`VincularFeticheBody.pago: bool`) e passou a gravar um sentinel truthy
(`_PRECO_PAGO_SENTINEL = Decimal("1")`, `dominio/modelos/routes.py`; a migration
`20260720233000` gravou o mesmo `1` no Menage de prod). Ler isso como valor cotaria "+R$1", então a
resolução tem um piso (`PRECO_FETICHE_CADASTRADO_MINIMO = Decimal("10")`): abaixo dele a coluna
está dizendo "pago", não um valor.

**Estado medido em prod (11/08/2026, leitura de `barravips.modelo_fetiches`):** 7 vínculos com
`preco` NULL (inclusos), 9 com o sentinel `1.00` — e **2 com preço real**, ambos da **Lucia**
(`status=pausada`, a instância do rig de testes): Beijo Grego e Chuva dourada a R$400. Ou seja, a
mudança é inerte para as modelos ativas, mas **não** para a Lucia: com Normal 400/1h e Completo
800/1h, o extra dela sai de "derivado" (+400 no Normal, +800 no Completo) para "+400 fixo" — o
total do Completo cai de R$1.600 para R$1.200. O `output_guard` já reconhece esse número —
a pendência 2 foi fechada no mesmo dia (ver abaixo).

**Pendências que esta revisão abre** (fora da posse desta mudança):
1. **Painel/API** — **FECHADA em 11/08/2026**: `VincularFeticheBody`/`AtualizarFeticheBody` aceitam
   `preco: Decimal | None` (`ge=0`; `null`/ausente = incluso), `_preco_da_flag`/
   `_PRECO_PAGO_SENTINEL` saíram (`_preco_a_gravar` normaliza `0` → `NULL`, porque um zero
   gravado ficaria NOT NULL mas falsy no `{% if f.preco %}` do render), o GET dos fetiches da
   modelo devolve `preco` (com `pago` derivado, para as superfícies que só mostram a pílula) e o
   sub-bloco de fetiches do perfil (`interface/src/components/modelos/ProgramasModelo.tsx`) trocou
   o toggle incluso/pago por um campo em R$ — vazio = incluso. A **leitura** não mudou: o piso
   `PRECO_FETICHE_CADASTRADO_MINIMO` segue sendo a rede das linhas legadas com o sentinel `1`.
2. **output_guard** — **FECHADA em 11/08/2026**: `_cardapio_da_modelo` leva os preços
   cadastrados (`extras_cadastrados`; era pares `(preco, cobra_por_pessoa)`, virou só os `preco`
   com o ADR-0039) ao `_valores_legitimos`,
   somados aos totais legítimos via `extra_de_fetiche` — render e guard consistentes nos dois
   regimes; direção aditiva (o total derivado continua no conjunto).
3. **Snapshot do painel**: `dominio/atendimentos/routes.py:adicionar_fetiche` ainda chama
   `calcular_preco_extra_fetiche` — trocar por `extra_de_fetiche(..., preco_cadastrado=mf["preco"])`
   para o `preco_snapshot` bater com o que a IA cotou.
4. **Rastro do extra no fechamento** (achado 10c do diagnóstico 11/08): `valor_acordado=800` com
   `duracao_horas=1` chega ao painel sem dizer que R$350 eram a Inversão. Não há caminho de
   escrita da IA para `atendimento_fetiches` — a tabela só é escrita pelo painel
   (`POST /atendimentos/{id}/fetiches`), que exige `atendimento_servicos` já registrado (também
   painel-only) e recebe o `fetiche_id` a dedo; e a tool de extração **não tem slot de fetiche**.
   Desenho proposto, sem migration: (a) a extração ganha `fetiches_em_pauta: list[str]` (nomes
   como o cliente falou); (b) no fechamento, `service.py` resolve cada nome contra
   `modelo_fetiches` reusando o `_resolver_fetiches_em_pauta` do `prepare_context` (mesmo
   closed-world, sem inventar item) e grava `atendimento_fetiches` com
   `preco_snapshot = extra_de_fetiche(...)`, tolerando a ausência de `atendimento_servicos`
   (snapshot do extra cotado, não do pacote). Custo real está em (a) — mexe no schema da tool e
   no contrato de extração, fora da posse desta mudança.
5. **Prosa de conduta**: `regras.md.j2:255` (`<menage>`) diz "o total dobrado" — correto só no
   regime sem cadastro. Com preço cadastrado a seção "Por pessoa" nomeia o valor, e a frase
   precisa apontar a linha da tabela em vez de descrever a aritmética.
