"""Export da temporada em planilha (ticket 18, spec 0006 US 46) — /v1/financeiro/temporadas*/export.

Sem DB: `razao_repo.obter_temporada`, `razao_service.montar_extrato` e
`razao_service.montar_temporadas` sao substituidos, porque o que este arquivo prova NAO e a
leitura do banco (isso e do ticket 04) e sim as duas promessas do ticket:

1. **os numeros do arquivo batem com os da tela, sem arredondamento divergente** — cada celula sai
   do mesmo DTO que a tela renderiza, e o saldo ACUMULADO linha a linha termina exatamente no
   `saldo_brl` do DTO;
2. **abre no Excel e no Google Sheets sem tratamento manual** — BOM UTF-8, delimitador `;` e
   planilha RETANGULAR (toda linha preenchida ate a largura maxima, para o detector de separador
   do Sheets nao decidir que o arquivo tem uma coluna so).
"""

import csv
import io
import unicodedata
from collections.abc import AsyncIterator, Iterator
from datetime import date
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from barra.api.deps import get_conn
from barra.dominio.financeiro import razao_repo, razao_service, routes
from barra.dominio.financeiro.razao_repo import TemporadaLida
from barra.dominio.financeiro.schemas import (
    ConferenciaFormaLinha,
    ConferenciaPorFormaResponse,
    ExtratoDaModeloResponse,
    LinhaDoExtrato,
    PagamentoDaModeloLinha,
    SaldoDoRazao,
    SinalizacaoDoExtrato,
    TemporadaLinha,
    TemporadasListaResponse,
)
from barra.main import app

MODELO_ID = UUID("11111111-1111-1111-1111-111111111111")
TEMPORADA_ID = UUID("22222222-2222-2222-2222-222222222222")


def _token() -> dict[str, str]:
    return {"Authorization": f"Bearer test:{uuid4()}:fernando:true"}


def _temporada() -> TemporadaLida:
    return TemporadaLida(
        id=TEMPORADA_ID,
        modelo_id=MODELO_ID,
        modelo_nome="Yasmin",
        cidade="Balneario Camboriu",
        data_inicio=date(2026, 8, 1),
        data_fim=date(2026, 8, 15),
        estado="aberta",
        observacao=None,
        fechada_em=None,
    )


def _saldo() -> SaldoDoRazao:
    """R$ 1.200 de venda no bolso dela a 50%: debito 1200, credito 600 -> saldo -600 ("ela deve").

    E o caso real do export de 12/08 citado no ADR-0045 §3. Com R$ 200 ja pagos ao lado, para
    provar que `pago` NAO entra no saldo e que `falta_pagar` e a diferenca (ADR-0045 §7).
    """
    return SaldoDoRazao(
        debitos_brl=1200.00,
        creditos_brl=600.00,
        saldo_brl=-600.00,
        a_casa_deve_brl=0.00,
        ela_deve_brl=600.00,
        pago_brl=200.00,
        falta_pagar_brl=-800.00,
    )


def _extrato() -> ExtratoDaModeloResponse:
    return ExtratoDaModeloResponse(
        modelo_id=MODELO_ID,
        modelo_nome="Yasmin",
        percentual_repasse=50.0,
        de=date(2026, 8, 1),
        ate=date(2026, 8, 15),
        temporada_id=TEMPORADA_ID,
        temporada_cidade="Balneario Camboriu",
        temporada_estado="aberta",
        saldo=_saldo(),
        conferencia=ConferenciaPorFormaResponse(
            de=date(2026, 8, 1),
            ate=date(2026, 8, 15),
            formas=[ConferenciaFormaLinha(forma="pix", vendas=2, valor_brl=1200.00)],
            vendas=2,
            vendido_brl=1200.00,
        ),
        linhas=[
            LinhaDoExtrato(
                tipo="venda",
                origem="venda_registrada",
                origem_id=uuid4(),
                data=date(2026, 8, 2),
                descricao="Cliente Joao; com ponto e virgula e acento",
                debito_brl=1200.00,
                credito_brl=0.00,
            ),
            LinhaDoExtrato(
                tipo="comissao",
                origem="venda_registrada",
                origem_id=uuid4(),
                data=date(2026, 8, 2),
                descricao=None,
                debito_brl=0.00,
                credito_brl=600.00,
            ),
        ],
        pagamentos=[
            PagamentoDaModeloLinha(
                id=uuid4(),
                data=date(2026, 8, 16),
                valor_brl=200.00,
                forma_pagamento="pix",
                observacao=None,
                temporada_id=TEMPORADA_ID,
            )
        ],
        pendencias=[
            SinalizacaoDoExtrato(tipo="venda_com_bolso_nao_dito", quantidade=1, valor_brl=600.00)
        ],
        divergencias=[],
    )


def _linha_temporada() -> TemporadaLinha:
    return TemporadaLinha(
        id=TEMPORADA_ID,
        modelo_id=MODELO_ID,
        modelo_nome="Yasmin",
        cidade="Balneario Camboriu",
        data_inicio=date(2026, 8, 1),
        data_fim=date(2026, 8, 15),
        estado="aberta",
        observacao=None,
        fechada_em=None,
        vendas=2,
        vendido_brl=1200.00,
        saldo=_saldo(),
        pendencias=1,
    )


@pytest.fixture
def cliente(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    async def _obter(conn: Any, temporada_id: UUID) -> TemporadaLida | None:
        return _temporada() if temporada_id == TEMPORADA_ID else None

    async def _montar_extrato(conn: Any, recorte: Any) -> ExtratoDaModeloResponse:
        return _extrato()

    async def _montar_temporadas(conn: Any, **kwargs: Any) -> TemporadasListaResponse:
        return TemporadasListaResponse(
            items=[_linha_temporada()],
            total_a_casa_deve_brl=0.00,
            total_ela_deve_brl=600.00,
            total_falta_pagar_brl=-800.00,
        )

    async def _conn() -> AsyncIterator[object]:
        yield object()

    monkeypatch.setattr(razao_repo, "obter_temporada", _obter)
    monkeypatch.setattr(razao_service, "montar_extrato", _montar_extrato)
    monkeypatch.setattr(razao_service, "montar_temporadas", _montar_temporadas)
    app.dependency_overrides[get_conn] = _conn
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.pop(get_conn, None)


def _planilha(corpo: bytes) -> list[list[str]]:
    return list(csv.reader(io.StringIO(corpo.decode("utf-8-sig")), delimiter=";"))


def _sem_acento(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")


def _da_temporada(cliente: TestClient) -> list[list[str]]:
    r = cliente.get(f"/v1/financeiro/temporadas/{TEMPORADA_ID}/export", headers=_token())
    assert r.status_code == 200, r.text
    return _planilha(r.content)


def test_planilha_da_temporada_tem_bom_separador_ascii_no_nome_e_e_retangular(
    cliente: TestClient,
) -> None:
    r = cliente.get(f"/v1/financeiro/temporadas/{TEMPORADA_ID}/export", headers=_token())
    assert r.status_code == 200, r.text

    # BOM UTF-8: e o que faz o Excel BR abrir "Comissao"/"Cobranca" acentuadas sem assistente.
    assert r.content.startswith(b"\xef\xbb\xbf")
    # Nome de arquivo sem acento: `Content-Disposition` sem RFC 5987 nao o carrega com seguranca.
    assert (
        'filename="temporada_yasmin_balneario-camboriu_2026-08-01.csv"'
        in r.headers["content-disposition"]
    )

    larguras = {len(linha) for linha in _planilha(r.content)}
    assert len(larguras) == 1, f"planilha nao retangular: {sorted(larguras)}"


def test_planilha_da_temporada_traz_lancamentos_conferencia_pagamentos_e_saldo(
    cliente: TestClient,
) -> None:
    linhas = _da_temporada(cliente)
    primeiras = [_sem_acento(linha[0]) for linha in linhas]
    for secao in (
        "Lancamentos",
        "Conferencia por forma de pagamento",
        "Pagamentos ja feitos a modelo",
        "Saldo",
        "Pendencias abertas",
        "Divergencias",
    ):
        assert secao in primeiras, f"faltou a secao {secao}"

    # A venda e a comissao sao DUAS linhas — e sao elas que explicam o saldo.
    rotulos = [linha[1] for linha in linhas if len(linha) > 1]
    assert "Venda no bolso dela" in rotulos
    assert "Comissão" in rotulos


def test_saldo_acumulado_fecha_no_saldo_da_tela(cliente: TestClient) -> None:
    """Sem arredondamento divergente: a ultima linha do razao bate com o `saldo_brl` do DTO."""
    linhas = _da_temporada(cliente)
    totais = next(linha for linha in linhas if len(linha) > 3 and linha[3] == "Totais")
    assert (totais[4], totais[5], totais[6]) == ("1200,00", "600,00", "-600,00")
    assert linhas[linhas.index(totais) - 1][6] == totais[6]

    rotulado = {linha[0]: linha[1] for linha in linhas if len(linha) > 1}
    assert rotulado["Total pago"] == "200,00"
    assert rotulado["Ela deve à casa"] == "600,00"
    assert rotulado["Já pago"] == "200,00"
    # `pago` fica FORA do saldo (ADR-0045 §7); `falta pagar` e a diferenca.
    assert rotulado["Falta pagar"] == "-800,00"


def test_planilha_da_lista_espelha_os_totais_da_tela(cliente: TestClient) -> None:
    r = cliente.get("/v1/financeiro/temporadas/export", headers=_token())
    assert r.status_code == 200, r.text
    linhas = _planilha(r.content)
    assert {len(linha) for linha in linhas} == {len(routes._COLUNAS_DA_LISTA)}

    total = next(linha for linha in linhas if linha[0] == "Total")
    # As mesmas tres somas que o cabecalho de `ListaTemporadas` mostra na tela.
    assert total[10] == "0,00"
    assert total[11] == "600,00"
    assert total[13] == "-800,00"


def test_temporada_inexistente_e_404(cliente: TestClient) -> None:
    r = cliente.get(f"/v1/financeiro/temporadas/{uuid4()}/export", headers=_token())
    assert r.status_code == 404
