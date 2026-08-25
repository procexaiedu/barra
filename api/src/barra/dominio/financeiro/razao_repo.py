"""SQL do razao da modelo **para o painel** (ticket 04) — o leitor que faltava ao ticket 02.

`dominio/grupo_financeiro/razao.py` e a funcao pura que soma: recebe `Lancamento` e devolve o
saldo com sinal. Ele nao le banco e nao tem periodo, por decisao (ADR-0045 §7). Este modulo e o
outro lado: **traduz linhas do banco em `Lancamento`**, ja recortadas pela modelo e, quando o
painel pedir, pela Temporada. Nada aqui soma dinheiro — quem soma e `razao.apurar`.

O recorte por data mora AQUI e nao la de proposito: a Temporada nao congela calculo nenhum, ela
so escolhe quais fatos entram na leitura de hoje.

De onde vem cada linha da tabela canonica do ADR-0045 §1:

| Linha do razao | Tabela |
|---|---|
| Venda no bolso dela (debito) + comissao (credito) | `vendas_registradas` |
| Transferencia dela -> casa (credito) | `comprovantes_do_grupo` (`fechamento`, `cobranca`) |
| Cobranca da agencia (debito) | `cobrancas_da_agencia` |
| Vale / ajuste | `razao_lancamentos_manuais` |
| Deslocamento | `deslocamentos_da_venda` |

⚠️ **`financeiro_repasses_pagos` NAO entra em `apurar`.** O pagamento da casa a modelo e lido
aqui (`pagamentos_da_modelo`) e exposto separado, como o ADR-0045 §7 fala dele: o saldo e
derivado, "a diferenca contra o **ja pago** aparece como 'falta pagar R$ X'". Nao ha
`PagamentoNoRazao` no vocabulario de `razao.py` e inventar um lancamento de tipo alheio para
somar o pagamento dentro do saldo esconderia justamente o numero que o gestor pede.

⚠️ **`grupos_financeiros.papel`**: toda juncao com o grupo filtra `papel = 'modelo'`. Depois da
migration `20260820120000` existem grupos SEM modelo (Grupo de fichas, caixa dos telefonistas) e
`grupos_financeiros.modelo_id` e NULL neles; juntar sem o filtro traria comprovante de grupo que
nao e de modelo nenhuma.

⚠️ Este modulo le tabelas e colunas da onda `20260820*`, que estao **escritas e nao aplicadas**.
Sem a migration, as rotas do painel respondem erro de SQL — nao ha caminho degradado, porque
adivinhar coluna que nao existe e pior do que falhar.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from psycopg import AsyncConnection

from barra.dominio.grupo_financeiro.razao import (
    ZERO,
    Bolso,
    CobrancaNoRazao,
    DeslocamentoNoRazao,
    Lancamento,
    TransferenciaNoRazao,
    ValeNoRazao,
    VendaNoRazao,
)

# As cinco formas que a operacao usa de fato (ADR-0046 §4): "cartao" deixou de ser uma forma so.
# `sem_forma` nao e forma nenhuma — e a venda cuja forma ninguem disse ainda, e ela precisa
# aparecer na conferencia, senao o vendido do painel nao fecha com o vendido do grupo.
FORMAS_DA_CONFERENCIA: tuple[str, ...] = ("pix", "dinheiro", "debito", "credito", "link")
SEM_FORMA = "sem_forma"

OrigemDoLancamento = Literal[
    "venda_registrada",
    "comprovante_do_grupo",
    "cobranca_da_agencia",
    "razao_lancamento_manual",
    "deslocamento_da_venda",
]

RotuloDaLinha = Literal[
    "venda", "comissao", "transferencia", "cobranca", "vale", "ajuste", "deslocamento"
]

TipoDePendencia = Literal[
    "venda_sem_forma_de_pagamento",
    "venda_com_bolso_nao_dito",
    "cobranca_em_aberto",
    "comprovante_retido",
]

TipoDeDivergencia = Literal[
    "venda_sem_snapshot_de_comissao",
    "comprovante_com_sobra",
]


@dataclass(frozen=True)
class Recorte:
    """Qual fatia da vida da modelo o painel esta olhando.

    `de`/`ate` nulos = a vida inteira (o saldo corrente continuo do `docs/dominio`).
    `temporada_id` nao filtra fato nenhum sozinho — ele so muda de onde vem o `de`/`ate` e
    quais PAGAMENTOS contam como "ja pagos desta temporada".
    """

    modelo_id: UUID
    de: date | None = None
    ate: date | None = None
    temporada_id: UUID | None = None


@dataclass(frozen=True)
class LancamentoLido:
    """Um `Lancamento` do razao com a procedencia que o extrato do painel mostra.

    `rotulo` existe por uma falta declarada: `razao.TipoDeLinha` nao tem `ajuste`, entao o ajuste
    manual e somado com o lancamento cujo SINAL esta certo (debito -> vale, credito ->
    transferencia) e reetiquetado aqui. O numero sai do razao; o nome sai daqui.
    """

    lancamento: Lancamento
    origem: OrigemDoLancamento
    origem_id: UUID
    data: date
    descricao: str | None = None
    rotulo: RotuloDaLinha | None = None


@dataclass(frozen=True)
class PagamentoLido:
    """Um repasse ja pago a modelo (`financeiro_repasses_pagos`). Fora do `apurar` — ver o topo."""

    id: UUID
    data: date
    valor: Decimal
    forma_pagamento: str
    observacao: str | None
    temporada_id: UUID | None


@dataclass(frozen=True)
class TemporadaLida:
    id: UUID
    modelo_id: UUID
    modelo_nome: str
    cidade: str
    data_inicio: date
    data_fim: date
    estado: Literal["aberta", "fechada", "cancelada"]
    observacao: str | None
    fechada_em: datetime | None


@dataclass(frozen=True)
class ContagemComValor:
    tipo: str
    quantidade: int
    valor: Decimal


@dataclass(frozen=True)
class TotalPorForma:
    forma: str
    vendas: int
    valor: Decimal


# =============================================================================
# Os lancamentos
# =============================================================================


async def lancamentos_do_razao(
    conn: AsyncConnection[Any], recorte: Recorte
) -> list[LancamentoLido]:
    """Todos os fatos do recorte ja traduzidos para o vocabulario de `razao.py`, por data.

    A ordem e cronologica porque o extrato e lido de cima para baixo; o saldo nao depende dela.
    """
    lidos: list[LancamentoLido] = []
    lidos.extend(await _vendas(conn, recorte))
    lidos.extend(await _deslocamentos(conn, recorte))
    lidos.extend(await _transferencias(conn, recorte))
    lidos.extend(await _cobrancas(conn, recorte))
    lidos.extend(await _manuais(conn, recorte))
    return sorted(lidos, key=lambda lido: (lido.data, str(lido.origem_id)))


async def _vendas(conn: AsyncConnection[Any], recorte: Recorte) -> list[LancamentoLido]:
    """As vendas em que ela trabalhou E as que ela RECEBEU por outra (ADR-0045 §6).

    Sao dois papeis diferentes numa venda so, e a festinha os separa:
    * `modelo_id` = quem trabalhou -> **credito da comissao**, sempre;
    * `COALESCE(recebido_por_modelo_id, modelo_id)` = quem ficou com o dinheiro -> **debito do
      bruto**.

    Como `VendaNoRazao` acopla os dois, cada papel vira um lancamento com o outro lado neutro:
    quem so tem comissao entra com `bolso="empresa"` (que para o razao DELA significa "o dinheiro
    nao caiu no meu bolso"), e quem so recebeu entra com `percentual=None` (sem snapshot -> sem
    comissao). Ninguem conta o mesmo dinheiro duas vezes.
    """
    cur = await conn.execute(
        """
        SELECT v.id,
               v.data,
               v.valor,
               v.bolso,
               v.percentual_repasse_snapshot,
               v.cliente_nome,
               v.modelo_id,
               v.recebido_por_modelo_id
          FROM barravips.vendas_registradas v
         WHERE v.anulada_em IS NULL
           AND (v.modelo_id = %(modelo)s OR v.recebido_por_modelo_id = %(modelo)s)
           AND (%(de)s::date IS NULL OR v.data >= %(de)s::date)
           AND (%(ate)s::date IS NULL OR v.data <= %(ate)s::date)
         ORDER BY v.data, v.id
        """,
        _params(recorte),
    )
    lidos: list[LancamentoLido] = []
    for row in await cur.fetchall():
        trabalhou = row["modelo_id"] == recorte.modelo_id
        recebeu = (row["recebido_por_modelo_id"] or row["modelo_id"]) == recorte.modelo_id
        bolso: Bolso = row["bolso"] if recebeu else "empresa"
        if recebeu and not trabalhou:
            # Recebeu por outra: o dinheiro caiu na mao dela por definicao, independente do que a
            # coluna `bolso` diga sobre a venda da colega.
            bolso = "dela"
        lidos.append(
            LancamentoLido(
                lancamento=VendaNoRazao(
                    valor=row["valor"],
                    bolso=bolso,
                    percentual_repasse_snapshot=(
                        row["percentual_repasse_snapshot"] if trabalhou else None
                    ),
                    origem_id=row["id"],
                    descricao=row["cliente_nome"],
                ),
                origem="venda_registrada",
                origem_id=row["id"],
                data=row["data"],
                descricao=row["cliente_nome"],
            )
        )
    return lidos


async def _deslocamentos(conn: AsyncConnection[Any], recorte: Recorte) -> list[LancamentoLido]:
    """O Uber em dois valores (ADR-0046 §6). `modelo` no enum = quem ficou com o dinheiro da venda.

    Nao ha coluna de modelo em `deslocamentos_da_venda` de proposito (uma verdade so sobre de quem
    e o lancamento), entao a dona vem da venda: `COALESCE(recebido_por_modelo_id, modelo_id)`.
    """
    cur = await conn.execute(
        """
        SELECT d.id,
               d.valor_antecipado,
               d.valor_transporte,
               d.recebedor_do_antecipado,
               d.pagador_do_transporte,
               v.data,
               v.cliente_nome
          FROM barravips.deslocamentos_da_venda d
          JOIN barravips.vendas_registradas v ON v.id = d.venda_id
         WHERE d.anulado_em IS NULL
           AND v.anulada_em IS NULL
           AND COALESCE(v.recebido_por_modelo_id, v.modelo_id) = %(modelo)s
           AND (%(de)s::date IS NULL OR v.data >= %(de)s::date)
           AND (%(ate)s::date IS NULL OR v.data <= %(ate)s::date)
         ORDER BY v.data, d.id
        """,
        _params(recorte),
    )
    return [
        LancamentoLido(
            lancamento=DeslocamentoNoRazao(
                valor_antecipado=row["valor_antecipado"],
                recebido_por_ela=row["recebedor_do_antecipado"] == "modelo",
                valor_transporte=row["valor_transporte"],
                pago_por_ela=row["pagador_do_transporte"] == "modelo",
                origem_id=row["id"],
                descricao=row["cliente_nome"],
            ),
            origem="deslocamento_da_venda",
            origem_id=row["id"],
            data=row["data"],
            descricao=row["cliente_nome"],
        )
        for row in await cur.fetchall()
    ]


async def _transferencias(conn: AsyncConnection[Any], recorte: Recorte) -> list[LancamentoLido]:
    """Comprovante dela -> casa: credito.

    Sao as duas classificacoes que movem dinheiro NA DIRECAO da casa: `fechamento` (abateu venda)
    e `cobranca` (quitou uma Cobranca da agencia). `entrada_da_modelo` fica de fora — ali o
    CLIENTE pagou A modelo, o dinheiro entrou no bolso dela e a venda ja debitou isso; credita-lo
    aqui zeraria o debito e faria a espécie sumir da conta. `nao_classificado` e `ilegivel`
    tambem ficam fora, e aparecem como pendencia.

    A data e a do comprovante; sem ela, o dia em que a foto chegou (`created_at`) — nunca `NULL`,
    porque o extrato ordena por data.
    """
    cur = await conn.execute(
        """
        SELECT c.id,
               c.valor,
               COALESCE(c.data_transferencia, (c.created_at AT TIME ZONE 'UTC')::date) AS data,
               c.classificacao,
               c.titular_destino
          FROM barravips.comprovantes_do_grupo c
          JOIN barravips.grupos_financeiros g ON g.id = c.grupo_id
         WHERE c.anulado_em IS NULL
           AND c.valor IS NOT NULL
           AND c.classificacao IN ('fechamento', 'cobranca')
           AND g.papel = 'modelo'
           AND g.modelo_id = %(modelo)s
           AND (%(de)s::date IS NULL
                OR COALESCE(c.data_transferencia, (c.created_at AT TIME ZONE 'UTC')::date)
                   >= %(de)s::date)
           AND (%(ate)s::date IS NULL
                OR COALESCE(c.data_transferencia, (c.created_at AT TIME ZONE 'UTC')::date)
                   <= %(ate)s::date)
         ORDER BY data, c.id
        """,
        _params(recorte),
    )
    return [
        LancamentoLido(
            lancamento=TransferenciaNoRazao(
                valor=row["valor"],
                origem_id=row["id"],
                descricao=row["titular_destino"],
            ),
            origem="comprovante_do_grupo",
            origem_id=row["id"],
            data=row["data"],
            descricao=row["titular_destino"],
        )
        for row in await cur.fetchall()
    ]


async def _cobrancas(conn: AsyncConnection[Any], recorte: Recorte) -> list[LancamentoLido]:
    """Cobranca da agencia (3RJ, site): debito dela, quitada ou nao.

    A quitada continua debitando porque o comprovante que a quitou ja creditou o mesmo valor
    acima — as duas linhas se anulam, e sumir com uma delas quebraria a conta.
    """
    cur = await conn.execute(
        """
        SELECT c.id, c.valor, c.data, c.descricao
          FROM barravips.cobrancas_da_agencia c
         WHERE c.anulada_em IS NULL
           AND c.modelo_id = %(modelo)s
           AND (%(de)s::date IS NULL OR c.data >= %(de)s::date)
           AND (%(ate)s::date IS NULL OR c.data <= %(ate)s::date)
         ORDER BY c.data, c.id
        """,
        _params(recorte),
    )
    return [
        LancamentoLido(
            lancamento=CobrancaNoRazao(
                valor=row["valor"], origem_id=row["id"], descricao=row["descricao"]
            ),
            origem="cobranca_da_agencia",
            origem_id=row["id"],
            data=row["data"],
            descricao=row["descricao"],
        )
        for row in await cur.fetchall()
    ]


async def _manuais(conn: AsyncConnection[Any], recorte: Recorte) -> list[LancamentoLido]:
    """Vale adiantado e ajuste (`razao_lancamentos_manuais`), a unica linha sem fato proprio.

    O valor e SEMPRE positivo e a direcao mora em `sentido` — o ajuste de credito entra como
    `TransferenciaNoRazao` porque e o lancamento de credito puro do vocabulario, e o `rotulo`
    corrige o nome no extrato.
    """
    cur = await conn.execute(
        """
        SELECT r.id, r.tipo, r.sentido, r.valor, r.data, r.descricao
          FROM barravips.razao_lancamentos_manuais r
         WHERE r.anulado_em IS NULL
           AND r.modelo_id = %(modelo)s
           AND (%(de)s::date IS NULL OR r.data >= %(de)s::date)
           AND (%(ate)s::date IS NULL OR r.data <= %(ate)s::date)
         ORDER BY r.data, r.id
        """,
        _params(recorte),
    )
    lidos: list[LancamentoLido] = []
    for row in await cur.fetchall():
        debito = row["sentido"] == "debito"
        lancamento: Lancamento = (
            ValeNoRazao(valor=row["valor"], origem_id=row["id"], descricao=row["descricao"])
            if debito
            else TransferenciaNoRazao(
                valor=row["valor"], origem_id=row["id"], descricao=row["descricao"]
            )
        )
        lidos.append(
            LancamentoLido(
                lancamento=lancamento,
                origem="razao_lancamento_manual",
                origem_id=row["id"],
                data=row["data"],
                descricao=row["descricao"],
                rotulo="vale" if row["tipo"] == "vale" else "ajuste",
            )
        )
    return lidos


# =============================================================================
# Pagamentos ja feitos (fora do `apurar` — ver o topo do modulo)
# =============================================================================


async def pagamentos_da_modelo(conn: AsyncConnection[Any], recorte: Recorte) -> list[PagamentoLido]:
    """O que a casa JA pagou a ela no recorte.

    Com Temporada, o recorte e por `temporada_id` e nao por data: o pagamento de uma temporada
    pode sair depois do fim dela, e e exatamente esse pagamento que o gestor quer ver abatido.
    """
    if recorte.temporada_id is not None:
        sql = """
            SELECT p.id, p.data_pagamento, p.valor, p.forma_pagamento, p.observacao,
                   p.temporada_id
              FROM barravips.financeiro_repasses_pagos p
             WHERE p.modelo_id = %(modelo)s
               AND p.temporada_id = %(temporada)s
             ORDER BY p.data_pagamento, p.id
        """
    else:
        sql = """
            SELECT p.id, p.data_pagamento, p.valor, p.forma_pagamento, p.observacao,
                   p.temporada_id
              FROM barravips.financeiro_repasses_pagos p
             WHERE p.modelo_id = %(modelo)s
               AND (%(de)s::date IS NULL OR p.data_pagamento >= %(de)s::date)
               AND (%(ate)s::date IS NULL OR p.data_pagamento <= %(ate)s::date)
             ORDER BY p.data_pagamento, p.id
        """
    cur = await conn.execute(sql, _params(recorte))
    return [
        PagamentoLido(
            id=row["id"],
            data=row["data_pagamento"],
            valor=row["valor"],
            forma_pagamento=row["forma_pagamento"],
            observacao=row["observacao"],
            temporada_id=row["temporada_id"],
        )
        for row in await cur.fetchall()
    ]


# =============================================================================
# Conferencia por forma de pagamento
# =============================================================================


async def conferencia_por_forma(
    conn: AsyncConnection[Any],
    *,
    de: date | None,
    ate: date | None,
    modelo_ids: list[UUID] | None = None,
) -> list[TotalPorForma]:
    """Vendido por forma: pix, dinheiro, debito, credito, link — e `sem_forma` (ADR-0046 §4).

    Conta pela modelo que TRABALHOU (`modelo_id`), nao por quem recebeu: aqui a pergunta e
    faturamento, nao bolso. As cinco formas aparecem sempre, mesmo zeradas — uma conferencia que
    esconde a coluna vazia obriga o gestor a lembrar do que faltou.
    """
    cur = await conn.execute(
        """
        SELECT COALESCE(v.forma_pagamento, %(sem_forma)s) AS forma,
               COUNT(*)::int AS vendas,
               COALESCE(SUM(v.valor), 0)::numeric AS valor
          FROM barravips.vendas_registradas v
         WHERE v.anulada_em IS NULL
           AND (%(modelos)s::uuid[] IS NULL OR v.modelo_id = ANY(%(modelos)s::uuid[]))
           AND (%(de)s::date IS NULL OR v.data >= %(de)s::date)
           AND (%(ate)s::date IS NULL OR v.data <= %(ate)s::date)
         GROUP BY 1
        """,
        {
            "sem_forma": SEM_FORMA,
            "modelos": list(modelo_ids) if modelo_ids else None,
            "de": de,
            "ate": ate,
        },
    )
    lidos = {row["forma"]: (int(row["vendas"]), row["valor"]) for row in await cur.fetchall()}
    ordem = (*FORMAS_DA_CONFERENCIA, SEM_FORMA)
    conhecidas = [
        TotalPorForma(
            forma=forma, vendas=lidos.get(forma, (0, ZERO))[0], valor=lidos.get(forma, (0, ZERO))[1]
        )
        for forma in ordem
    ]
    # Forma fora do vocabulario (dado velho, escrito sob o CHECK anterior) nao pode sumir da
    # soma: a conferencia existe para o vendido bater, e um termo desconhecido escondido faria
    # exatamente o contrario. Aparece no fim, com o nome cru.
    estranhas = [
        TotalPorForma(forma=forma, vendas=dados[0], valor=dados[1])
        for forma, dados in sorted(lidos.items())
        if forma not in ordem
    ]
    return conhecidas + estranhas


# =============================================================================
# Pendencias e divergencias (aparecem, nunca travam a leitura)
# =============================================================================


async def pendencias_do_extrato(
    conn: AsyncConnection[Any], recorte: Recorte
) -> list[ContagemComValor]:
    """O que esta faltando dizer, contado — nao e erro, e fila.

    `bolso = 'nao_dito'` e estado legitimo (ADR-0047 §3): entra na cobranca consolidada da manha,
    nao trava a venda e nao vira palpite. Aparece aqui porque o saldo o le como `dela`, e quem
    confere merece saber quantas linhas estao apoiadas nesse default.
    """
    cur = await conn.execute(
        """
        SELECT 'venda_sem_forma_de_pagamento' AS tipo,
               COUNT(*)::int AS quantidade,
               COALESCE(SUM(v.valor), 0)::numeric AS valor
          FROM barravips.vendas_registradas v
         WHERE v.anulada_em IS NULL
           AND v.forma_pagamento IS NULL
           AND v.modelo_id = %(modelo)s
           AND (%(de)s::date IS NULL OR v.data >= %(de)s::date)
           AND (%(ate)s::date IS NULL OR v.data <= %(ate)s::date)
         UNION ALL
        SELECT 'venda_com_bolso_nao_dito',
               COUNT(*)::int,
               COALESCE(SUM(v.valor), 0)::numeric
          FROM barravips.vendas_registradas v
         WHERE v.anulada_em IS NULL
           AND v.bolso = 'nao_dito'
           AND v.modelo_id = %(modelo)s
           AND (%(de)s::date IS NULL OR v.data >= %(de)s::date)
           AND (%(ate)s::date IS NULL OR v.data <= %(ate)s::date)
         UNION ALL
        SELECT 'cobranca_em_aberto',
               COUNT(*)::int,
               COALESCE(SUM(c.valor), 0)::numeric
          FROM barravips.cobrancas_da_agencia c
         WHERE c.anulada_em IS NULL
           AND c.quitada_em IS NULL
           AND c.modelo_id = %(modelo)s
           AND (%(de)s::date IS NULL OR c.data >= %(de)s::date)
           AND (%(ate)s::date IS NULL OR c.data <= %(ate)s::date)
         UNION ALL
        SELECT 'comprovante_retido',
               COUNT(*)::int,
               COALESCE(SUM(COALESCE(cp.valor, 0)), 0)::numeric
          FROM barravips.comprovantes_do_grupo cp
          JOIN barravips.grupos_financeiros g ON g.id = cp.grupo_id
         WHERE cp.anulado_em IS NULL
           AND cp.classificacao IN ('nao_classificado', 'ilegivel')
           AND g.papel = 'modelo'
           AND g.modelo_id = %(modelo)s
           AND (%(de)s::date IS NULL
                OR COALESCE(cp.data_transferencia, (cp.created_at AT TIME ZONE 'UTC')::date)
                   >= %(de)s::date)
           AND (%(ate)s::date IS NULL
                OR COALESCE(cp.data_transferencia, (cp.created_at AT TIME ZONE 'UTC')::date)
                   <= %(ate)s::date)
        """,
        _params(recorte),
    )
    return [
        ContagemComValor(tipo=row["tipo"], quantidade=int(row["quantidade"]), valor=row["valor"])
        for row in await cur.fetchall()
        if int(row["quantidade"]) > 0
    ]


async def divergencias_do_extrato(
    conn: AsyncConnection[Any], recorte: Recorte
) -> list[ContagemComValor]:
    """O que o saldo esta contando de um jeito que alguem precisa olhar.

    * `venda_sem_snapshot_de_comissao`: sem `percentual_repasse_snapshot` a comissao e ZERO
      (`razao._comissao`), nunca 50% chutado. O saldo erra para o lado conservador — e o valor
      aqui e o BRUTO cuja comissao nao foi creditada.
    * `comprovante_com_sobra`: ela transferiu mais do que as vendas abatidas; a sobra e credito
      dela, e o valor aqui e `valor - valor_abatido`.
    """
    cur = await conn.execute(
        """
        SELECT 'venda_sem_snapshot_de_comissao' AS tipo,
               COUNT(*)::int AS quantidade,
               COALESCE(SUM(v.valor), 0)::numeric AS valor
          FROM barravips.vendas_registradas v
         WHERE v.anulada_em IS NULL
           AND v.percentual_repasse_snapshot IS NULL
           AND v.modelo_id = %(modelo)s
           AND (%(de)s::date IS NULL OR v.data >= %(de)s::date)
           AND (%(ate)s::date IS NULL OR v.data <= %(ate)s::date)
         UNION ALL
        SELECT 'comprovante_com_sobra',
               COUNT(*)::int,
               COALESCE(SUM(cp.valor - cp.valor_abatido), 0)::numeric
          FROM barravips.comprovantes_do_grupo cp
          JOIN barravips.grupos_financeiros g ON g.id = cp.grupo_id
         WHERE cp.anulado_em IS NULL
           AND cp.classificacao = 'fechamento'
           AND cp.valor IS NOT NULL
           AND cp.valor > cp.valor_abatido
           AND g.papel = 'modelo'
           AND g.modelo_id = %(modelo)s
           AND (%(de)s::date IS NULL
                OR COALESCE(cp.data_transferencia, (cp.created_at AT TIME ZONE 'UTC')::date)
                   >= %(de)s::date)
           AND (%(ate)s::date IS NULL
                OR COALESCE(cp.data_transferencia, (cp.created_at AT TIME ZONE 'UTC')::date)
                   <= %(ate)s::date)
        """,
        _params(recorte),
    )
    return [
        ContagemComValor(tipo=row["tipo"], quantidade=int(row["quantidade"]), valor=row["valor"])
        for row in await cur.fetchall()
        if int(row["quantidade"]) > 0
    ]


# =============================================================================
# Temporadas
# =============================================================================


async def listar_temporadas(
    conn: AsyncConnection[Any],
    *,
    estado: str | None,
    modelo_ids: list[UUID] | None,
    limit: int,
) -> list[TemporadaLida]:
    """As temporadas, da mais recente para a mais antiga. `estado=None` = todas."""
    cur = await conn.execute(
        """
        SELECT t.id, t.modelo_id, m.nome AS modelo_nome, t.cidade,
               t.data_inicio, t.data_fim, t.estado, t.observacao, t.fechada_em
          FROM barravips.temporadas t
          JOIN barravips.modelos m ON m.id = t.modelo_id
         WHERE (%(estado)s::text IS NULL OR t.estado::text = %(estado)s::text)
           AND (%(modelos)s::uuid[] IS NULL OR t.modelo_id = ANY(%(modelos)s::uuid[]))
         ORDER BY t.data_inicio DESC, t.id DESC
         LIMIT %(limit)s
        """,
        {
            "estado": estado,
            "modelos": list(modelo_ids) if modelo_ids else None,
            "limit": limit,
        },
    )
    return [
        TemporadaLida(
            id=row["id"],
            modelo_id=row["modelo_id"],
            modelo_nome=row["modelo_nome"],
            cidade=row["cidade"],
            data_inicio=row["data_inicio"],
            data_fim=row["data_fim"],
            estado=row["estado"],
            observacao=row["observacao"],
            fechada_em=row["fechada_em"],
        )
        for row in await cur.fetchall()
    ]


async def obter_temporada(conn: AsyncConnection[Any], temporada_id: UUID) -> TemporadaLida | None:
    cur = await conn.execute(
        """
        SELECT t.id, t.modelo_id, m.nome AS modelo_nome, t.cidade,
               t.data_inicio, t.data_fim, t.estado, t.observacao, t.fechada_em
          FROM barravips.temporadas t
          JOIN barravips.modelos m ON m.id = t.modelo_id
         WHERE t.id = %s
        """,
        (temporada_id,),
    )
    row = await cur.fetchone()
    if row is None:
        return None
    return TemporadaLida(
        id=row["id"],
        modelo_id=row["modelo_id"],
        modelo_nome=row["modelo_nome"],
        cidade=row["cidade"],
        data_inicio=row["data_inicio"],
        data_fim=row["data_fim"],
        estado=row["estado"],
        observacao=row["observacao"],
        fechada_em=row["fechada_em"],
    )


async def identidade_da_modelo(
    conn: AsyncConnection[Any], modelo_id: UUID
) -> tuple[str, Decimal | None] | None:
    """(nome, percentual_repasse) — o percentual de CADASTRO, que e o default do proximo
    snapshot, nunca o que ja foi congelado nas vendas antigas."""
    cur = await conn.execute(
        "SELECT nome, percentual_repasse FROM barravips.modelos WHERE id = %s",
        (modelo_id,),
    )
    row = await cur.fetchone()
    if row is None:
        return None
    return row["nome"], row["percentual_repasse"]


def _params(recorte: Recorte) -> dict[str, Any]:
    return {
        "modelo": recorte.modelo_id,
        "de": recorte.de,
        "ate": recorte.ate,
        "temporada": recorte.temporada_id,
    }
