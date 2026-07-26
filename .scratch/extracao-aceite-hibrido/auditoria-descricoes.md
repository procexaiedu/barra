# Auditoria das descrições de campo da extração — referência órfã

Item do issue `.scratch/extracao-revisao/issues/08-descricao-autocontida-do-aceite.md`. Data:
25/07/2026.

**O defeito procurado:** a descrição delega uma regra para um bloco de prompt que a chamada da
extração não recebe. Quem lê essas descrições é a chamada **barata** (`nos/extrair.py`), com janela
mínima: system curto + `conversa_crua` + âncora `<agenda hoje= agora=>` + `<ja_registrado>`. O
BP_GERAL **não** entra. Toda referência a bloco do `regras.md.j2` chega órfã.

Varredura: todas as `_DESC_*` de `api/src/barra/agente/ferramentas/extracao.py`, os campos de
`SinaisQualificacao` e a docstring da tool (que também vai no schema).

| site | o que referencia | chega à janela? | veredito |
|---|---|---|---|
| `aceita_valor` | `<desconto>` do BP_GERAL | **não** | **corrigido** neste ticket |
| `_DESC_TIPO_ATENDIMENTO` | "sua conduta redireciona e, se ele insistir, escala" | **não** | **fica** — ver abaixo |
| `_DESC_MOTIVO_PERDA` | "NÃO encerra o atendimento nem muda sua conduta" | n/a | **fica** — ver abaixo |
| `_DESC_HORARIO`, `_DESC_DATA` | tag `<agenda hoje="…" agora="HH:MM">` | **sim** (`ancora_extracao.md.j2`) | referência viva, nada a fazer |
| docstring da tool | "responda ao cliente normalmente neste mesmo turno, em personagem"; "chame UMA vez por turno" | n/a | texto morto, não regra órfã — ver abaixo |
| demais campos (`_DESC_VALOR`, `_DESC_DURACAO`, `_DESC_COTACAO`, `_DESC_AVISO_SAIDA`, `_DESC_LIMPAR`, `_DESC_ENDERECO`, `_DESC_BAIRRO`, `_DESC_TIPO_LOCAL`, `_DESC_FORMA_PAGAMENTO`, `_DESC_URGENCIA`, `_DESC_INTENCAO`, `_DESC_PROXIMA_ACAO`) | nenhuma | — | limpos |

## Por que o `_DESC_TIPO_ATENDIMENTO` fica

A referência é: cliente quer buscar a modelo de carro → "não classifique como 'externo'; deixe o
campo de fora (sua conduta redireciona e, se ele insistir, escala)".

Diferente do aceite: **a instrução acionável está dita inteira** ("deixe o campo de fora"). O que a
referência acrescenta é o que **outro** ator fará com o caso — informação de contexto, não a regra
que decide o preenchimento. O extrator não perde nada por não ler o bloco. É reescrever a conduta
de redirecionamento aqui que seria o erro (duplicação + drift, categoria 2 do `agente/CLAUDE.md`).

Removê-la é possível, mas "dedup não é deleção grátis" (mesma seção do `agente/CLAUDE.md`) e
mexeria num segundo eixo dentro da mesma medição — o efeito da autocontida deixaria de ser
isolável. Se valer, é ticket separado com medida própria.

## Por que o `_DESC_MOTIVO_PERDA` fica

"NÃO encerra o atendimento nem muda sua conduta; continue conduzindo normalmente" não delega regra
nenhuma: é fronteira **negativa** ("este campo é só um candidato interno"), que impede o extrator de
tratar o campo como terminal. A cauda ("continue conduzindo") é dirigida a quem conduz e é inerte
para o extrator, mas não esconde regra faltando.

## O achado da docstring da tool

A docstring diz "registrar NÃO envia nada ao cliente — você ainda precisa responder ao cliente
normalmente neste mesmo turno, em personagem" e "Chame UMA vez por turno, perto do fim".

As duas frases foram escritas quando o chat #1 chamava a tool. Hoje `registrar_extracao` **saiu de
`TOOLS`**: o único chamador é o nó `extrair`, com `tool_choice` forçado, e esse leitor não responde
ao cliente nem escolhe quando chamar. Não é referência órfã (nenhuma regra falta) — é **instrução
inaplicável** ocupando o topo do schema.

Não corrigido aqui **de propósito**: é o texto que o extrator lê, e mudá-lo no mesmo commit da
descrição autocontida confundiria a medição que este ticket precisa publicar. Fica registrado como
candidato a ticket próprio, medido pela mesma bancada.
