"""Chave de conteudo da Venda registrada — o dedup cross-grupo (spec 0005, ticket 04).

Uma venda com duas modelos e anunciada nos DOIS Grupos financeiros (cada gestora posta o mesmo
texto no grupo da sua modelo), e o gesto de correcao do grupo e apagar-e-repostar. Nos dois casos
chega uma mensagem NOVA — o dedup de entrega do ticket 01 (`chave_dedup` da mensagem) nao ve nada
de errado. Sem uma chave de CONTEUDO, o total da modelo simplesmente infla, e ninguem percebe:
duas linhas iguais no extrato parecem dois atendimentos.

A chave e `data | valor | modelo | cliente` (docs/dominio/grupo-financeiro.md, "dedup cross-grupo
(data+valor+modelos+cliente)"). O "modelos" do dominio aparece aqui como a modelo DA LINHA porque
a venda ja e uma linha por modelo: as duas linhas do mesmo anuncio se distinguem pela mulher, e o
repost no outro grupo produz exatamente as mesmas duas chaves. Ancorar a chave no conjunto de
participantes seria pior — o conjunto muda enquanto uma delas ainda e um Nome de anuncio
desconhecido, e a linha ja gravada ficaria com uma chave que o repost nao reproduz.

**Tradeoff aceito, igual ao do balde de 5 s da mensagem**: a mesma modelo, com o mesmo cliente,
pelo mesmo valor, no mesmo dia, atendendo DUAS vezes, entra uma vez so. Entre perder a segunda
metade de um caso raro (que o grupo corrige por quote, ticket 05) e inflar o extrato toda vez que
um anuncio e repostado — que e o gesto cotidiano da gestora — o dedup vale mais.

A chave e texto legivel, e nao hash: quando uma venda "sumir" no dedup, quem for investigar le a
chave no banco e ve na hora por que ela colidiu.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from barra.dominio.grupo_financeiro.anuncio import normalizar


def chave_de_conteudo(
    *,
    data: date,
    valor: Decimal,
    modelo_id: UUID,
    cliente: str | None,
) -> str:
    """ "2026-08-07|1300.00|<modelo>|igor e um amigo" — a identidade do FATO, nao da mensagem.

    O cliente entra normalizado (minusculo, sem acento, espacos colapsados) pela mesma funcao que
    o resolver de nomes usa: "Cliente Antônio" e "cliente antonio" sao o mesmo homem, e a grafia
    entre um grupo e outro nao pode decidir se a venda duplica.
    """
    return "|".join([f"{data:%Y-%m-%d}", f"{valor:.2f}", str(modelo_id), normalizar(cliente or "")])
