"""A comissão do telefonista: percentual por vendedor, sobre o bruto (ADR-0048, ticket 22).

Sem banco de propósito — a migration `20260820126000` (as colunas `percentual_comissao` e
`whatsapp_jid`) ainda **não** foi aplicada em lugar nenhum, e o que precisa de prova aqui não é
que o Postgres aceita o comando: é que a conta e as guardas são as que o dono ditou. Cada uma
delas, se cair, produz dinheiro errado no bolso de alguém sem um único erro no log:

- **a base é o bruto** (§2): *"do valor da venda, valor total que ele vendeu (…) faturamento
  bruto"*. Descontar a taxa de cartão paga a menos toda venda no crédito;
- **o percentual é do vendedor** (§1), não do nível: `financeiro_comissao_niveis` virou default de
  cadastro e não pode voltar ao cálculo;
- **deslocamento não entra na base** (§3): é reembolso de custo. Ele nem é coluna da venda, e o
  jeito de errar isso é somar `deslocamentos_da_venda` na projeção;
- **autor desconhecido → sem vendedor → sem comissão** (§5), e nunca por nome de exibição;
- **projeção, sem snapshot** (§6): o número sai da leitura, não de uma coluna congelada na venda.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest

from barra.dominio.financeiro.calculos import (
    comissao_sobre_o_bruto,
    comissao_sql,
    comissao_vendedor,
)
from barra.dominio.grupo_financeiro import repo

RAFAEL = UUID("1e1e1e1e-0000-0000-0000-000000000001")
JID_DO_RAFAEL = "5511988887777@s.whatsapp.net"
DE = date(2026, 8, 1)
ATE = date(2026, 8, 31)


class _Cursor:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    async def fetchone(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None

    async def fetchall(self) -> list[dict[str, Any]]:
        return self._rows


class FakeConn:
    """Grava (query, params) e devolve as linhas que o teste mandou. Nenhum banco envolvido."""

    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.binds: list[tuple[str, Any]] = []
        self._rows = rows or []

    async def execute(self, query: str, params: Any = None) -> _Cursor:
        self.binds.append((query, params))
        return _Cursor(self._rows)

    @property
    def query(self) -> str:
        return self.binds[-1][0]

    @property
    def params(self) -> tuple[Any, ...]:
        return tuple(self.binds[-1][1] or ())


def _linha_do_telefonista(**extra: Any) -> dict[str, Any]:
    linha: dict[str, Any] = {
        "id": RAFAEL,
        "nome": "Rafael",
        "percentual_comissao": Decimal("7.00"),
        "ativo": True,
    }
    linha.update(extra)
    return linha


def _linha_da_comissao(**extra: Any) -> dict[str, Any]:
    linha: dict[str, Any] = {
        "vendedor_id": RAFAEL,
        "vendedor_nome": "Rafael",
        "percentual_comissao": Decimal("7.00"),
        "vendas": 3,
        "faturamento_bruto": Decimal("3000.00"),
        "comissao": Decimal("210.00"),
    }
    linha.update(extra)
    return linha


# --- a conta: bruto, e a taxa fica de fora por decisão -------------------------------------------


def test_a_comissao_incide_sobre_o_bruto_com_a_taxa_dentro() -> None:
    """Venda de R$ 1.100 no crédito (taxa 10%): 7% de 1.100, não de 1.000 (ADR-0048 §2)."""
    assert comissao_sobre_o_bruto(1100.0, 7.0) == pytest.approx(77.0)


def test_o_caminho_novo_e_o_antigo_dao_numeros_diferentes_e_e_esse_o_ponto() -> None:
    """Se os dois coincidissem, a decisão de 20/08 não teria mudado nada — e mudou R$ 7 aqui."""
    novo = comissao_sobre_o_bruto(1100.0, 7.0)
    antigo = comissao_vendedor(1100.0, 10.0, 7.0)  # base líquida do ADR-0013

    assert novo == pytest.approx(77.0)
    assert antigo == pytest.approx(70.0)
    assert novo > antigo


def test_o_parametro_de_taxa_sobrevive_para_o_historico_pre_agosto() -> None:
    """A função continua sabendo comissionar sobre o serviço: é como os meses antigos foram pagos.

    Reprojetar aquele período com base bruta reescreveria comissão já paga — por isso o parâmetro
    não foi removido, e por isso `comissao_sobre_o_bruto` existe como nome da decisão nova.
    """
    assert comissao_vendedor(1100.0, 10.0, 7.0) == pytest.approx(
        comissao_sobre_o_bruto(1000.0, 7.0)
    )
    # E o caminho novo é literalmente "a mesma conta com a taxa ignorada de propósito".
    assert comissao_sobre_o_bruto(1100.0, 7.0) == comissao_vendedor(1100.0, None, 7.0)


def test_sem_vendedor_nao_ha_comissao_e_nao_ha_chute() -> None:
    """Autor desconhecido / IA conduzindo (§5): zero, nunca a referência de 7% por default."""
    assert comissao_sobre_o_bruto(1000.0, None) == pytest.approx(0.0)


def test_o_percentual_e_por_pessoa_e_nao_tem_faixa_travada() -> None:
    """1% a 10% é faixa operacional, não invariante — o CHECK do banco é 0..100 (ADR-0048)."""
    assert comissao_sobre_o_bruto(1000.0, 4.0) == pytest.approx(40.0)
    assert comissao_sobre_o_bruto(1000.0, 10.0) == pytest.approx(100.0)
    assert comissao_sobre_o_bruto(1000.0, 12.5) == pytest.approx(125.0)


def test_deslocamento_fora_da_base_muda_o_numero() -> None:
    """R$ 100 de Uber somados ao "valor total" pagariam R$ 7 a mais por atendimento (§3).

    A tranca real é estrutural (o deslocamento mora em `deslocamentos_da_venda` e a projeção não
    junta com ela); este teste é o preço do erro, para ninguém "arredondar" a decisão.
    """
    so_a_venda = comissao_sobre_o_bruto(1000.0, 7.0)
    com_o_uber = comissao_sobre_o_bruto(1100.0, 7.0)

    assert so_a_venda == pytest.approx(70.0)
    assert com_o_uber - so_a_venda == pytest.approx(7.0)


def test_a_expressao_sql_e_a_mesma_conta_da_funcao_pura() -> None:
    """Divergir das duas é o bug que `VALOR_SERVICO_SQL` já ensinou a evitar."""
    assert comissao_sql("v.valor", "ven.percentual_comissao") == (
        "(v.valor * COALESCE(ven.percentual_comissao, 0) / 100)"
    )


# --- quem vendeu: o autor da mensagem, closed-world ----------------------------------------------


@pytest.mark.asyncio
async def test_o_telefonista_e_achado_pelo_jid_do_autor() -> None:
    conn = FakeConn([_linha_do_telefonista()])

    achado = await repo.telefonista_por_jid(conn, JID_DO_RAFAEL)  # type: ignore[arg-type]

    assert achado is not None
    assert achado.id == RAFAEL
    assert achado.percentual_comissao == Decimal("7.00")
    assert conn.params == (JID_DO_RAFAEL,)


@pytest.mark.asyncio
async def test_o_casamento_nunca_passa_pelo_nome_de_exibicao() -> None:
    """`autor_nome` é escolhido por quem fala, muda sozinho e se repete: casar por ele é palpite."""
    conn = FakeConn([_linha_do_telefonista()])

    await repo.telefonista_por_jid(conn, JID_DO_RAFAEL)  # type: ignore[arg-type]

    assert "whatsapp_jid" in conn.query
    assert "autor_nome" not in conn.query
    assert "nome =" not in conn.query


@pytest.mark.asyncio
async def test_autor_desconhecido_nao_vira_vendedor() -> None:
    """Closed-world (§5): não achou, não atribui — e a venda fica sem comissão, sem erro."""
    conn = FakeConn([])

    assert await repo.telefonista_por_jid(conn, "5511000000000@s.whatsapp.net") is None  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_mensagem_sem_autor_nem_consulta_o_banco() -> None:
    conn = FakeConn([_linha_do_telefonista()])

    assert await repo.telefonista_por_jid(conn, None) is None  # type: ignore[arg-type]
    assert await repo.telefonista_por_jid(conn, "   ") is None  # type: ignore[arg-type]
    assert conn.binds == []


@pytest.mark.asyncio
async def test_dois_cadastros_para_a_mesma_chave_nao_desempatam_no_limit() -> None:
    """O UNIQUE do banco é sobre o texto cru: `...@s.whatsapp.net` e `...:2@s.whatsapp.net`
    convivem lá e normalizam para a mesma chave aqui. Desempatar por `LIMIT 1` faria a comissão
    trocar de dono sem ninguém mexer em nada."""
    conn = FakeConn([_linha_do_telefonista(), _linha_do_telefonista(id=UUID(int=2))])

    assert await repo.telefonista_por_jid(conn, JID_DO_RAFAEL) is None  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_telefonista_inativo_continua_dono_da_venda_que_ele_postou() -> None:
    """Desativar tira dos seletores; não reescreve quem vendeu — e não apaga a comissão dele."""
    conn = FakeConn([_linha_do_telefonista(ativo=False)])

    achado = await repo.telefonista_por_jid(conn, JID_DO_RAFAEL)  # type: ignore[arg-type]

    assert achado is not None and achado.ativo is False
    assert "ativo" not in conn.query.split("WHERE", 1)[1]


def test_o_sufixo_de_aparelho_no_jid_nao_derruba_o_casamento() -> None:
    """`...:12@s.whatsapp.net` é o mesmo telefonista de outro aparelho. Sem isso, o cadastro certo
    para de casar um dia e o sintoma é o pior: comissão que some calada."""
    assert repo.chave_do_jid(" 5511988887777:12@S.Whatsapp.net ") == JID_DO_RAFAEL
    assert repo.chave_do_jid(JID_DO_RAFAEL) == JID_DO_RAFAEL


def test_o_lid_opaco_casa_literalmente_e_nunca_vira_telefone() -> None:
    """Se o gestor cadastrou o `@lid`, é por ele que se acha. Traduzir um no outro é o palpite
    que este ticket proíbe."""
    assert repo.chave_do_jid("27492834928374@lid") == "27492834928374@lid"
    assert repo.chave_do_jid(None) is None
    assert repo.chave_do_jid("") is None


# --- a projeção: o que ele vendeu, o que ele leva -------------------------------------------------


@pytest.mark.asyncio
async def test_a_projecao_multiplica_o_percentual_do_vendedor_pelo_bruto() -> None:
    conn = FakeConn([_linha_da_comissao()])

    linhas = await repo.comissao_dos_telefonistas(conn, de=DE, ate=ATE)  # type: ignore[arg-type]

    assert [(linha.vendedor_nome, linha.faturamento_bruto, linha.comissao) for linha in linhas] == [
        ("Rafael", Decimal("3000.00"), Decimal("210.00"))
    ]
    assert linhas[0].vendas == 3
    assert conn.params == (DE, ATE)
    assert comissao_sql("v.valor", "ven.percentual_comissao") in conn.query


@pytest.mark.asyncio
async def test_a_projecao_nao_consulta_a_tabela_de_niveis() -> None:
    """§1: `financeiro_comissao_niveis` sobrevive como default de CADASTRO e saiu do cálculo."""
    conn = FakeConn([_linha_da_comissao()])

    await repo.comissao_dos_telefonistas(conn, de=DE, ate=ATE)  # type: ignore[arg-type]

    assert "financeiro_comissao_niveis" not in conn.query
    assert "ven.percentual_comissao" in conn.query


@pytest.mark.asyncio
async def test_a_projecao_nao_junta_deslocamento_na_base() -> None:
    """§3: o Uber é reembolso de custo. A tranca é não existir a junção — este teste é o alarme."""
    conn = FakeConn([_linha_da_comissao()])

    await repo.comissao_dos_telefonistas(conn, de=DE, ate=ATE)  # type: ignore[arg-type]

    assert "deslocamentos_da_venda" not in conn.query
    assert "valor_antecipado" not in conn.query
    assert "valor_transporte" not in conn.query
    assert "SUM(v.valor)" in conn.query


@pytest.mark.asyncio
async def test_venda_anulada_nao_paga_comissao() -> None:
    """Anulação é rastro (ticket 05): comissionar rastro paga duas vezes a venda corrigida."""
    conn = FakeConn([_linha_da_comissao()])

    await repo.comissao_dos_telefonistas(conn, de=DE, ate=ATE)  # type: ignore[arg-type]

    assert "v.anulada_em IS NULL" in conn.query


@pytest.mark.asyncio
async def test_venda_sem_vendedor_nao_aparece_em_linha_nenhuma() -> None:
    """JOIN e não LEFT JOIN: uma linha "sem dono" é uma linha que alguém acaba pagando."""
    conn = FakeConn([_linha_da_comissao()])

    await repo.comissao_dos_telefonistas(conn, de=DE, ate=ATE)  # type: ignore[arg-type]

    assert "JOIN barravips.vendedores ven ON ven.id = v.vendedor_id" in conn.query
    assert "LEFT JOIN barravips.vendedores" not in conn.query


@pytest.mark.asyncio
async def test_o_recorte_e_a_data_da_venda_e_nao_o_created_at() -> None:
    """O anúncio de ontem postado hoje é faturamento de ontem — e de quem o vendeu."""
    conn = FakeConn([_linha_da_comissao()])

    await repo.comissao_dos_telefonistas(conn, de=DE, ate=ATE)  # type: ignore[arg-type]

    assert "v.data >= %s AND v.data <= %s" in conn.query
    assert "created_at" not in conn.query


@pytest.mark.asyncio
async def test_o_filtro_por_vendedor_e_opcional_e_entra_como_parametro() -> None:
    conn = FakeConn([_linha_da_comissao()])

    await repo.comissao_dos_telefonistas(
        conn,  # type: ignore[arg-type]
        de=DE,
        ate=ATE,
        vendedor_ids=[RAFAEL],
    )

    assert "AND v.vendedor_id = ANY(%s)" in conn.query
    assert conn.params == (DE, ATE, [RAFAEL])


@pytest.mark.asyncio
async def test_a_comissao_e_arredondada_uma_vez_no_fim() -> None:
    """Arredondar venda a venda e somar dá outro centavo — e o telefonista confere no centavo."""
    conn = FakeConn([_linha_da_comissao()])

    await repo.comissao_dos_telefonistas(conn, de=DE, ate=ATE)  # type: ignore[arg-type]

    assert conn.query.count("round(") == 1
    assert "round(COALESCE(SUM(" in conn.query


# --- o extrato da modelo é outra conta, de outra pessoa ------------------------------------------


def test_o_razao_da_modelo_nao_tem_por_onde_receber_a_comissao_do_telefonista() -> None:
    """ "O extrato da temporada da modelo não mostra comissão de telefonista" (ADR-0048): a tranca
    é estrutural — nenhum lançamento do razão dela carrega vendedor ou percentual dele, então não
    há como somar essa conta no extrato por engano."""
    from dataclasses import fields

    from barra.dominio.grupo_financeiro.razao import VendaNoRazao

    nomes = {f.name for f in fields(VendaNoRazao)}

    assert "percentual_repasse_snapshot" in nomes  # o percentual DELA, com snapshot
    assert not {n for n in nomes if "vendedor" in n or "telefonista" in n}
    assert not {n for n in nomes if "comissao" in n}
