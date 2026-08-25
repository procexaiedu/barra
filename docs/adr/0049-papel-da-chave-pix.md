---
data: 2026-08-20
status: aceito
relaciona: ADR-0047 (o bolso é fato da venda — este ADR dá a ele a evidência), ADR-0046, spec 0005 (ticket 07, chaves conhecidas), docs/produto/plano-chaves-e-atribuicao-do-dinheiro.md
---

# ADR-0049 — A chave Pix tem papel, não um booleano

## Contexto

O ADR-0047 concluiu que **em que bolso o dinheiro caiu é fato da venda**, resolvido por evidência —
e nomeou o comprovante como a evidência de maior precedência. Concluir isso, porém, só move o
problema: alguém precisa **observar** o fato. Hoje ninguém observa, e toda venda nasce `nao_dito`.

A reunião de 20/08/2026 mostra por que a observação é difícil. O dinheiro de um atendimento cai em
seis lugares diferentes, e o dono descreve todos como legítimos: o Pix da casa — *"a gente pode
padronizar o atendimento pra receber com uma forma de pagamento nossa que não vai ser uma, **a gente
pode ter umas cinco**"* —, o Pix da modelo (*"quando a mina tem a conta e a mina é de confiança, ela
recebe no dela"*), dinheiro, a maquininha da casa, a maquininha dela (*"a mina tem a máquina no
celular dela, que é aquele PagBank/InfinitePay"*; *"se o cara tiver só aproximação, aí ela recebe no
dela"*) e o link do gateway que ainda não existe. O deslocamento tem destino próprio e igualmente
indefinido: *"ele sempre manda pra conta da empresa? — vai depender."*

O comprovante **já carrega o destino**. O que falta é o destino significar alguém.

Hoje existem **três cadastros de chave** e **duas validações**, que não se falam:

| Onde | O quê | Estado real medido |
|---|---|---|
| `barravips.chaves_pix_conhecidas` | lista plana da casa | **1 linha** |
| `modelos.chave_pix` + `titular_chave` | a chave que a IA entrega ao cliente no Pix de deslocamento | **0 modelos preenchidos** |
| `comprovante.py::chave_e_conhecida()` | devolve **`bool`** | grupo financeiro |
| `workers/pix.py::_chaves_compativeis()` | compara com a chave **daquela modelo** | Pix de deslocamento |

O próprio código já registrou a duplicação, em `comprovante.py:69`: *"`workers/pix.py::
_chaves_compativeis` — comparar chave Pix é o mesmo problema nos dois lugares."*

## Decisão

**1. `papel_da_chave(chave) -> PapelDaChave` substitui `chave_e_conhecida(chave) -> bool`.**

```
PapelDaChave = casa | modelo(<quem>) | telefonista(<quem>) | terceiro | desconhecida
```

O booleano é a raiz da confusão operacional: *"não está na lista da casa"* engloba **a chave da
própria modelo** — informação valiosa, que resolve o bolso — e **a chave de um terceiro qualquer** —
ruído. O aviso `⚠️ Esse Pix foi pra uma chave fora da lista da casa` dispara igual nos dois, e o
gestor aprende a ignorá-lo.

**2. `chaves_pix_conhecidas` passa a ser o registro único**, com `papel`, o dono quando o papel o
pede (`modelo_id` / `vendedor_id`), e `padrao boolean` — **uma só chave padrão da casa**, que é o
*"vou botar a Pix, que normalmente é o padrão que a gente mais recebe"* do dono. Uma modelo pode ter
**várias** chaves: CPF, telefone, aleatória, e ela troca de banco.

**3. `modelos.chave_pix` deixa de ser registro e vira uma coisa só: a chave preferida para
RECEBER repasse.** "Chave da modelo" tem dois sentidos que hoje colidem no mesmo campo — *de onde o
dinheiro do cliente cai* (evidência de bolso) e *para onde a casa manda o dinheiro dela* (destino de
pagamento). Juntos, um repasse da casa **para** ela pode ser lido como uma venda **dela**, e o razão
dobra. O comentário da coluna passa a dizer isso.

**4. A classificação do comprovante sai de (papel do pagador × papel do destino)**, não de
heurística de nome. É a mesma tabela de duas perguntas que `comprovante.py` já organiza — *quem
pagou* e *quem recebeu* — agora com respostas de cadastro em vez de palpite. É o que liga o
`bolso.py`, hoje uma ilha sem chamador em produção.

**5. Chave desconhecida RECORRENTE vira sugestão de cadastro, não alarme repetido.** *"Esta chave
apareceu 4 vezes em 3 semanas, sempre recebendo da Yasmin — de quem é?"*, com um botão que
classifica. O cadastro se preenche pelo uso, sem ninguém inventar. O alarme imediato fica só para o
caso que merece: **chave desconhecida recebendo valor de venda pela primeira vez**.

**6. Cartão entra pelo mesmo mecanismo, sem campo novo na ficha.** Cartão não tem chave, mas o
**print da maquininha** que a modelo já manda carrega o **nome do estabelecimento**. Um registro de
estabelecimentos (`casa | modelo`) resolve débito, crédito e aproximação com a mesma lógica — e
evita virar cadastro de confiança por modelo, que o ADR-0047 proíbe.

## Consequência que dita a ORDEM DE ENTREGA

⚠️ **Existe um bug dormente que a Fase 1 deste plano acorda.**

`workers/pix.py:341-348` marca o Pix de deslocamento como `em_revisao` com *"chave divergente"*
quando o destino extraído não bate com `modelos.chave_pix`. A checagem é **guardada por
`chave_modelo and ...`** — e como **nenhuma modelo tem a chave preenchida**, ela nunca dispara hoje.

No instante em que alguém preencher o cadastro (que é exatamente o que este ADR pede ao dono), todo
Pix de deslocamento que legitimamente foi para a conta da **casa** — e a ata diz que isso acontece —
passa a cair em revisão manual.

**Portanto: o ticket que corrige `workers/pix.py` para validar contra o PAPEL entra ANTES de o
cadastro ser preenchido.** Não é preferência de sequência; é evitar uma regressão em produção
disparada por dado, não por deploy.

## Alternativas rejeitadas

- **Manter o booleano e acrescentar uma segunda lista "chaves das modelos".** Duas listas planas em
  vez de uma tipada; a pergunta "de quem é esta chave?" continuaria respondida em dois lugares, que
  é o defeito que este ADR conserta.
- **Bolso por cadastro de confiança da modelo.** Já revogado pelo ADR-0047 — o dono negou que exista
  padrão por pessoa.
- **Pedir ao telefonista um campo "onde caiu" na ficha.** Mais um campo num card que a Lula já disse
  que não sobrevive ao dia de pico, para uma informação que o comprovante entrega de graça.
- **Resolver tudo pelo gateway próprio primeiro.** É o endgame certo (toda chave nasce cadastrada, o
  pagamento chega atribuído), mas não reconcilia nada do que já existe, e o compromisso de agosto
  depende do histórico.

## Consequências

- Migration em `chaves_pix_conhecidas` (papel, dono, padrão) e comentário novo em `modelos.chave_pix`.
- `workers/pix.py` e `dominio/grupo_financeiro/comprovante.py` passam a compartilhar **uma** função
  de papel, encerrando a duplicação que o próprio código já denunciava.
- O painel ganha a tela de chaves — é onde o dono classifica o que a Fase 3 sugerir.
- Métrica que diz se funcionou: **proporção de vendas com `bolso` resolvido**. Hoje é ~0% para
  `empresa`, por ausência de chamador.
