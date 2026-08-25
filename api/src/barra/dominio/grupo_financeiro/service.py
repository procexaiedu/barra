"""Orquestracao de leitura do Grupo financeiro: repo + dominio, sem nenhuma escrita.

Existe por causa do ticket 11. O Fechamento e derivado (`fechamento.py::montar_extrato` e puro) e
ate aqui a composicao "le as vendas + le os comprovantes + monta o extrato" morava dentro da porta
do agente. O painel precisa do MESMO extrato que o grupo ve sob comando — e um segundo caminho ate
o saldo seria um segundo jeito de a conta divergir, exatamente o que a docstring de
`fechamento_da_modelo` proibia.

Como `dominio/` nunca importa a camada de agente (dominio/CLAUDE.md, "Direcao das dependencias"),
a composicao desceu para ca: `agente_financeiro.porta.fechamento_da_modelo` continua sendo a porta
publica do modulo e delega para este arquivo, e o painel chama daqui. Um caminho so, dois
chamadores.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any
from uuid import UUID

from psycopg import AsyncConnection

from barra.dominio.grupo_financeiro.conferencia import (
    ConferenciaDoCaixa,
    conferir,
    ler_caixa,
)
from barra.dominio.grupo_financeiro.fechamento import Extrato, montar_extrato
from barra.dominio.grupo_financeiro.repo import (
    carregar_cadastro_de_nomes,
    cobrancas_abertas_da_modelo,
    comprovantes_da_modelo,
    mensagens_do_caixa,
    vendas_da_modelo,
    vendas_vivas_no_periodo,
)


async def extrato_da_modelo(conn: AsyncConnection[Any], modelo_id: UUID) -> Extrato:
    """O Fechamento da modelo AGORA — vendido x comprovado x em especie, o debito e o que nao bate.

    Tres leituras e nenhuma escrita: o extrato e derivado, nao materializado — nada aqui "fecha"
    um periodo (docs/dominio, "Fechamento"). Sem recorte de janela de proposito: o saldo e
    corrente e continuo, entao o filtro de periodo do painel recorta a LISTA de vendas, nunca a
    conferencia.

    A terceira leitura sao as Cobrancas da agencia ABERTAS (ticket 08). Ela entra aqui, e nao no
    chamador, porque a coluna de debito e parte do mesmo retrato: um extrato montado sem ela diria
    "tudo conciliado" a uma modelo que ainda deve o anuncio.
    """
    return montar_extrato(
        modelo_id=modelo_id,
        vendas=await vendas_da_modelo(conn, modelo_id),
        comprovantes=await comprovantes_da_modelo(conn, modelo_id),
        cobrancas=await cobrancas_abertas_da_modelo(conn, modelo_id),
    )


async def extratos_das_modelos(
    conn: AsyncConnection[Any], modelo_ids: Sequence[UUID]
) -> dict[UUID, Extrato]:
    """Um extrato por modelo — o que o painel precisa para marcar a linha divergente.

    Tres consultas por modelo, em serie, e o suficiente: ha **um Grupo financeiro por modelo** e a
    casa tem dezenas de modelos, nao milhares. Uma consulta unica agregando todas devolveria SUMs
    e o extrato nao se deriva de SUM — ele precisa da venda inteira (ver `vendas_da_modelo`).

    **Onde isto deixa de servir.** O chamador do painel passa as modelos DA PAGINA (ate `limit`
    distintas), entao o custo e 2 x (modelos distintas na pagina) e `vendas_da_modelo` nao tem
    recorte de data por design do Fechamento (saldo corrente continuo). Em dezenas de modelos com
    historico de meses isso e barato; em centenas, ou quando o historico de uma modelo passar de
    alguns milhares de vendas, esta funcao vira o custo da tela e a saida e materializar o extrato
    (tabela de saldo por modelo, atualizada pela porta) — nao um SUM aqui. A leitura de cobrancas
    abertas nao muda essa conta: ela e coberta por indice parcial e devolve unidades de linhas.
    """
    return {
        modelo_id: await extrato_da_modelo(conn, modelo_id)
        for modelo_id in dict.fromkeys(modelo_ids)
    }


async def conferencia_do_caixa(
    conn: AsyncConnection[Any], *, de: date, ate: date
) -> ConferenciaDoCaixa:
    """As duas fontes do dia lado a lado: o que o caixa dos telefonistas conta x o que o sistema
    registrou (ticket 17).

    Tres leituras e **nenhuma escrita** — a IA entra no caixa em leitura apenas (spec 0006). Como
    o Fechamento, a conferencia e derivada na hora e nao materializada: nao existe tabela de
    "linha do caixa", e e por isso que rodar isto duas vezes devolve a mesma coisa e nao cria
    nada.

    A janela e a MESMA para as duas fontes de proposito. O caixa escrito na manha seguinte ainda
    casa (o par por `(modelo, valor)` de `conferir` cobre o desencontro de data DENTRO da janela),
    mas a conferencia de um dia so, pedida antes de o gestor escrever, sai com `bate is None` —
    "ninguem conferiu ainda", que e a verdade, e nao "bateu".

    Quem chama e o painel. O agente NAO chama: ele nunca posta no caixa, e um numero que ele nao
    pode dizer em lugar nenhum nao precisa passar pela porta dele.
    """
    cadastro = await carregar_cadastro_de_nomes(conn)
    leitura = ler_caixa(await mensagens_do_caixa(conn, de=de, ate=ate), cadastro=cadastro)
    return conferir(
        linhas_do_caixa=leitura.linhas,
        vendas=await vendas_vivas_no_periodo(conn, de=de, ate=ate),
        de=de,
        ate=ate,
        nao_lidas=leitura.nao_lidas,
    )
