"""Integração da rota /v1/crm/clientes/mapa — cor por desfecho (MAPA-3) +
última data / recorrência (MAPA-5) + filtro desfecho/motivo (MAPA-8), ADR 0008."""

from contextlib import asynccontextmanager
from datetime import date as _date
from typing import Any
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from barra.api.deps import get_conn
from barra.main import app


class _Result:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows or []

    async def fetchone(self) -> dict[str, Any] | None:
        return self.rows[0] if self.rows else None

    async def fetchall(self) -> list[dict[str, Any]]:
        return self.rows


class FakeConnMapa:
    """Mock do `mapa_clientes`: responde a query do endpoint com as linhas configuradas.
    Guarda a última query/params para inspeção dos filtros aplicados (MAPA-8)."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.last_query: str | None = None
        self.last_params: object = None

    @asynccontextmanager
    async def transaction(self):
        yield

    async def execute(self, query: str, params: object = None) -> _Result:
        # Casa tanto a query "agregada" padrão quanto a do modo comparar (UNION ALL
        # de dois SELECTs com o mesmo shape — só muda o `%s::text AS recorte`).
        if "FROM barravips.clientes" in query and "LATERAL" in query and "geo.estado" in query:
            self.last_query = query
            self.last_params = params
            return _Result(self.rows)
        return _Result([])


def _token() -> dict[str, str]:
    return {"Authorization": f"Bearer test:{uuid4()}:fernando:true"}


def _ponto(
    estado: str,
    cliente_id: UUID | None = None,
    ultima_data: str = "2026-05-20T10:00:00",
    total_fechados: int = 0,
    motivo_perda: str | None = None,
) -> dict[str, Any]:
    return {
        "id": cliente_id or uuid4(),
        "nome": f"Cliente {estado}",
        "perfis_preferidos": [],
        "latitude": -22.97,
        "longitude": -43.18,
        "bairro": "Copacabana",
        "endereco_formatado": "Av. Atlântica, 1000",
        "estado": estado,
        "motivo_perda": motivo_perda,
        "ultima_data": ultima_data,
        "total_atendimentos": 1,
        "total_fechados": total_fechados,
        "valor_total": 0,
    }


def test_mapa_clientes_propaga_estado_fechado() -> None:
    async def _override():
        yield FakeConnMapa([_ponto("Fechado")])

    app.dependency_overrides[get_conn] = _override
    try:
        with TestClient(app) as client:
            response = client.get("/v1/crm/clientes/mapa", headers=_token())
        assert response.status_code == 200
        pontos = response.json()["pontos"]
        assert len(pontos) == 1
        assert pontos[0]["estado"] == "Fechado"
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_mapa_clientes_propaga_estado_perdido() -> None:
    async def _override():
        yield FakeConnMapa([_ponto("Perdido")])

    app.dependency_overrides[get_conn] = _override
    try:
        with TestClient(app) as client:
            response = client.get("/v1/crm/clientes/mapa", headers=_token())
        assert response.status_code == 200
        pontos = response.json()["pontos"]
        assert len(pontos) == 1
        assert pontos[0]["estado"] == "Perdido"
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_mapa_clientes_propaga_estado_em_andamento() -> None:
    # "em andamento" não é um valor único do enum: qualquer estado não-terminal
    # cabe (Triagem/Qualificado/Aguardando_confirmacao/Confirmado/Em_execucao).
    # MAPA-3 colore esses três grupos como verde/vermelho/âmbar — basta garantir
    # que o estado bruto chega ao payload para o frontend mapear a cor.
    async def _override():
        yield FakeConnMapa([_ponto("Em_execucao")])

    app.dependency_overrides[get_conn] = _override
    try:
        with TestClient(app) as client:
            response = client.get("/v1/crm/clientes/mapa", headers=_token())
        assert response.status_code == 200
        pontos = response.json()["pontos"]
        assert len(pontos) == 1
        assert pontos[0]["estado"] == "Em_execucao"
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_mapa_clientes_propaga_ultima_data() -> None:
    async def _override():
        yield FakeConnMapa([_ponto("Fechado", ultima_data="2026-04-15T08:30:00")])

    app.dependency_overrides[get_conn] = _override
    try:
        with TestClient(app) as client:
            response = client.get("/v1/crm/clientes/mapa", headers=_token())
        assert response.status_code == 200
        pontos = response.json()["pontos"]
        assert len(pontos) == 1
        assert pontos[0]["ultima_data"] == "2026-04-15T08:30:00"
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_mapa_clientes_recorrente_com_dois_ou_mais_fechados() -> None:
    async def _override():
        yield FakeConnMapa([_ponto("Fechado", total_fechados=3)])

    app.dependency_overrides[get_conn] = _override
    try:
        with TestClient(app) as client:
            response = client.get("/v1/crm/clientes/mapa", headers=_token())
        assert response.status_code == 200
        pontos = response.json()["pontos"]
        assert len(pontos) == 1
        assert pontos[0]["recorrente"] is True
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_mapa_clientes_nao_recorrente_com_um_fechado() -> None:
    async def _override():
        yield FakeConnMapa([_ponto("Fechado", total_fechados=1)])

    app.dependency_overrides[get_conn] = _override
    try:
        with TestClient(app) as client:
            response = client.get("/v1/crm/clientes/mapa", headers=_token())
        assert response.status_code == 200
        pontos = response.json()["pontos"]
        assert len(pontos) == 1
        assert pontos[0]["recorrente"] is False
    finally:
        app.dependency_overrides.pop(get_conn, None)


# ---------------------------------------------------------------------------
# MAPA-8: filtro por desfecho + motivo de perda
# O FakeConn devolve as linhas configuradas sem aplicar o filtro do SQL — os
# testes verificam (a) que o filtro foi inserido no WHERE corretamente e (b)
# que `motivo_perda` chega ao payload.


def test_mapa_clientes_filtra_por_desfecho_perdido() -> None:
    fake = FakeConnMapa([_ponto("Perdido", motivo_perda="fora_de_area")])

    async def _override():
        yield fake

    app.dependency_overrides[get_conn] = _override
    try:
        with TestClient(app) as client:
            response = client.get(
                "/v1/crm/clientes/mapa?desfecho=Perdido", headers=_token()
            )
        assert response.status_code == 200
        assert fake.last_query is not None
        assert "geo.estado = 'Perdido'" in fake.last_query
        pontos = response.json()["pontos"]
        assert len(pontos) == 1
        assert pontos[0]["estado"] == "Perdido"
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_mapa_clientes_filtra_por_motivo_perda_or() -> None:
    fake = FakeConnMapa(
        [
            _ponto("Perdido", motivo_perda="fora_de_area"),
            _ponto("Perdido", motivo_perda="indisponibilidade"),
        ]
    )

    async def _override():
        yield fake

    app.dependency_overrides[get_conn] = _override
    try:
        with TestClient(app) as client:
            response = client.get(
                "/v1/crm/clientes/mapa?desfecho=Perdido"
                "&motivo_perda=fora_de_area&motivo_perda=indisponibilidade",
                headers=_token(),
            )
        assert response.status_code == 200
        assert fake.last_query is not None
        assert (
            "geo.motivo_perda = ANY(%s::barravips.motivo_perda_enum[])"
            in fake.last_query
        )
        # OR é representado pelo array passado como parâmetro do ANY.
        assert isinstance(fake.last_params, list)
        assert ["fora_de_area", "indisponibilidade"] in fake.last_params
        pontos = response.json()["pontos"]
        motivos = {p["motivo_perda"] for p in pontos}
        assert motivos == {"fora_de_area", "indisponibilidade"}
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_mapa_clientes_motivo_perda_no_payload() -> None:
    async def _override():
        yield FakeConnMapa(
            [
                _ponto("Fechado", motivo_perda=None),
                _ponto("Perdido", motivo_perda="preco"),
            ]
        )

    app.dependency_overrides[get_conn] = _override
    try:
        with TestClient(app) as client:
            response = client.get("/v1/crm/clientes/mapa", headers=_token())
        assert response.status_code == 200
        pontos = response.json()["pontos"]
        assert len(pontos) == 2
        # Ordem preservada do mock: Fechado primeiro, Perdido depois.
        assert pontos[0]["motivo_perda"] is None
        assert pontos[1]["motivo_perda"] == "preco"
    finally:
        app.dependency_overrides.pop(get_conn, None)


# ---------------------------------------------------------------------------
# MAPA-9: lente "Demanda não atendida"
# A lente é UI-only (no frontend, sobrescreve desfecho/motivo no fetch). No
# backend ela vira a mesma querystring do MAPA-8 — este teste deixa explícito o
# vínculo de aceite da lente ao endpoint: a querystring acordada retorna apenas
# Perdidos com motivos `indisponibilidade` ou `fora_de_area`.


def test_mapa_clientes_lente_demanda_nao_atendida() -> None:
    """Cenário da lente MAPA-9: 5 rows variados; o FakeConn devolve só as 2 que
    o WHERE da MAPA-8 deixaria passar (Perdido + indisp/fora_de_area). Verifica
    que a querystring da lente bate no SQL e que motivos não-oportunidade não
    vazam para o payload."""
    fake = FakeConnMapa(
        [
            _ponto("Perdido", motivo_perda="indisponibilidade"),
            _ponto("Perdido", motivo_perda="fora_de_area"),
        ]
    )

    async def _override():
        yield fake

    app.dependency_overrides[get_conn] = _override
    try:
        with TestClient(app) as client:
            response = client.get(
                "/v1/crm/clientes/mapa"
                "?desfecho=Perdido"
                "&motivo_perda=indisponibilidade"
                "&motivo_perda=fora_de_area",
                headers=_token(),
            )
        assert response.status_code == 200
        assert fake.last_query is not None
        assert "geo.estado = 'Perdido'" in fake.last_query
        assert (
            "geo.motivo_perda = ANY(%s::barravips.motivo_perda_enum[])"
            in fake.last_query
        )
        # OR via ANY: o array passa exatamente os 2 motivos da lente, na ordem da UI.
        assert isinstance(fake.last_params, list)
        assert ["indisponibilidade", "fora_de_area"] in fake.last_params
        pontos = response.json()["pontos"]
        assert len(pontos) == 2
        motivos = {p["motivo_perda"] for p in pontos}
        assert motivos == {"indisponibilidade", "fora_de_area"}
        # Nenhum Fechado/em andamento/Perdido por outro motivo no payload.
        assert all(p["estado"] == "Perdido" for p in pontos)
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_mapa_clientes_desfecho_andamento_exclui_perdido_e_fechado() -> None:
    fake = FakeConnMapa([_ponto("Em_execucao")])

    async def _override():
        yield fake

    app.dependency_overrides[get_conn] = _override
    try:
        with TestClient(app) as client:
            response = client.get(
                "/v1/crm/clientes/mapa?desfecho=andamento", headers=_token()
            )
        assert response.status_code == 200
        assert fake.last_query is not None
        assert "geo.estado NOT IN ('Fechado', 'Perdido')" in fake.last_query
        pontos = response.json()["pontos"]
        assert len(pontos) == 1
        assert pontos[0]["estado"] == "Em_execucao"
    finally:
        app.dependency_overrides.pop(get_conn, None)


# ---------------------------------------------------------------------------
# MAPA-11: faixa de R$ fechado por cliente + recência (ativos vs dormentes)
# Mesma estratégia dos testes do MAPA-8: o FakeConn não aplica o filtro, mas
# guarda a query/params para inspeção. O fato do filtro entrar no WHERE é o
# que importa — a semântica do SQL é responsabilidade do Postgres.


def test_mapa_clientes_filtra_por_valor_min() -> None:
    fake = FakeConnMapa([_ponto("Fechado", total_fechados=2)])

    async def _override():
        yield fake

    app.dependency_overrides[get_conn] = _override
    try:
        with TestClient(app) as client:
            response = client.get("/v1/crm/clientes/mapa?valor_min=500", headers=_token())
        assert response.status_code == 200
        assert fake.last_query is not None
        assert "ag.valor_total >= %s" in fake.last_query
        assert isinstance(fake.last_params, list)
        assert 500.0 in fake.last_params
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_mapa_clientes_filtra_por_valor_max() -> None:
    fake = FakeConnMapa([_ponto("Fechado", total_fechados=1)])

    async def _override():
        yield fake

    app.dependency_overrides[get_conn] = _override
    try:
        with TestClient(app) as client:
            response = client.get("/v1/crm/clientes/mapa?valor_max=2000", headers=_token())
        assert response.status_code == 200
        assert fake.last_query is not None
        assert "ag.valor_total <= %s" in fake.last_query
        assert isinstance(fake.last_params, list)
        assert 2000.0 in fake.last_params
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_mapa_clientes_filtra_por_recencia_ativos() -> None:
    fake = FakeConnMapa([_ponto("Fechado")])

    async def _override():
        yield fake

    app.dependency_overrides[get_conn] = _override
    try:
        with TestClient(app) as client:
            response = client.get("/v1/crm/clientes/mapa?recencia=ativos", headers=_token())
        assert response.status_code == 200
        assert fake.last_query is not None
        assert "geo.ultima_data >= NOW() - INTERVAL '90 days'" in fake.last_query
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_mapa_clientes_filtra_por_recencia_dormentes() -> None:
    fake = FakeConnMapa([_ponto("Fechado")])

    async def _override():
        yield fake

    app.dependency_overrides[get_conn] = _override
    try:
        with TestClient(app) as client:
            response = client.get("/v1/crm/clientes/mapa?recencia=dormentes", headers=_token())
        assert response.status_code == 200
        assert fake.last_query is not None
        assert "geo.ultima_data < NOW() - INTERVAL '90 days'" in fake.last_query
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_mapa_clientes_valor_min_negativo_e_no_op() -> None:
    # Defesa contra querystring adulterada: negativos não viram cláusula no SQL.
    fake = FakeConnMapa([_ponto("Fechado")])

    async def _override():
        yield fake

    app.dependency_overrides[get_conn] = _override
    try:
        with TestClient(app) as client:
            response = client.get("/v1/crm/clientes/mapa?valor_min=-100", headers=_token())
        assert response.status_code == 200
        assert fake.last_query is not None
        assert "ag.valor_total >= %s" not in fake.last_query
        assert "ag.valor_total <= %s" not in fake.last_query
    finally:
        app.dependency_overrides.pop(get_conn, None)


# ---------------------------------------------------------------------------
# MAPA-14: comparar dois recortes (lift de campanha)
# Cenários do briefing:
#  (i) cliente só com externo em A → devolve só em A;
#  (ii) cliente com externos em A e B → devolve nos dois (1 ponto por recorte,
#       com `valor_total`/`total_atendimentos` daquele recorte);
#  (iii) range vazio → resposta válida com 0 pontos no recorte.
# O FakeConn não aplica o WHERE — os testes verificam que o SQL é UNION ALL,
# que `recorte` chega ao payload e que agregados são preservados por recorte.


def _ponto_recorte(
    recorte: str,
    cliente_id: UUID | None = None,
    valor_total: int = 0,
    total_atendimentos: int = 1,
) -> dict[str, Any]:
    """`_ponto` + campo `recorte`. cliente_id explícito quando o mesmo cliente
    aparece em A e B (caso ii)."""
    base = _ponto(
        "Fechado",
        cliente_id=cliente_id,
        total_fechados=1 if valor_total > 0 else 0,
    )
    base["recorte"] = recorte
    base["valor_total"] = valor_total
    base["total_atendimentos"] = total_atendimentos
    return base


def test_mapa_clientes_comparar_cliente_so_em_a() -> None:
    """(i): cliente só com externo no recorte A — devolve 1 ponto, recorte='A'."""
    fake = FakeConnMapa([_ponto_recorte("A", valor_total=1500)])

    async def _override():
        yield fake

    app.dependency_overrides[get_conn] = _override
    try:
        with TestClient(app) as client:
            response = client.get(
                "/v1/crm/clientes/mapa"
                "?comparar=true"
                "&a_inicio=2026-01-01&a_fim=2026-03-31"
                "&b_inicio=2026-04-01&b_fim=2026-05-31",
                headers=_token(),
            )
        assert response.status_code == 200
        assert fake.last_query is not None
        # UNION ALL marca o modo comparar — duas SELECTs no SQL fundido.
        assert "UNION ALL" in fake.last_query
        pontos = response.json()["pontos"]
        assert len(pontos) == 1
        assert pontos[0]["recorte"] == "A"
        assert pontos[0]["valor_total"] == 1500
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_mapa_clientes_comparar_cliente_em_a_e_b() -> None:
    """(ii): cliente com externos em A e B — 2 pontos, agregados daquele recorte."""
    cliente_id = uuid4()
    fake = FakeConnMapa(
        [
            _ponto_recorte("A", cliente_id=cliente_id, valor_total=800, total_atendimentos=1),
            _ponto_recorte("B", cliente_id=cliente_id, valor_total=2400, total_atendimentos=3),
        ]
    )

    async def _override():
        yield fake

    app.dependency_overrides[get_conn] = _override
    try:
        with TestClient(app) as client:
            response = client.get(
                "/v1/crm/clientes/mapa"
                "?comparar=true"
                "&a_inicio=2026-01-01&a_fim=2026-03-31"
                "&b_inicio=2026-04-01&b_fim=2026-05-31",
                headers=_token(),
            )
        assert response.status_code == 200
        pontos = response.json()["pontos"]
        assert len(pontos) == 2
        por_recorte = {p["recorte"]: p for p in pontos}
        assert set(por_recorte) == {"A", "B"}
        # Mesmo cliente_id nos dois pontos — par (cliente, recorte) é único.
        assert por_recorte["A"]["cliente_id"] == por_recorte["B"]["cliente_id"]
        # Agregados são do recorte (não cross-tempo).
        assert por_recorte["A"]["valor_total"] == 800
        assert por_recorte["A"]["total_atendimentos"] == 1
        assert por_recorte["B"]["valor_total"] == 2400
        assert por_recorte["B"]["total_atendimentos"] == 3
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_mapa_clientes_comparar_recorte_sem_atividade() -> None:
    """(iii): ranges válidos, mas o mock devolve 0 rows — resposta válida com 0 pontos."""
    fake = FakeConnMapa([])

    async def _override():
        yield fake

    app.dependency_overrides[get_conn] = _override
    try:
        with TestClient(app) as client:
            response = client.get(
                "/v1/crm/clientes/mapa"
                "?comparar=true"
                "&a_inicio=2026-01-01&a_fim=2026-03-31"
                "&b_inicio=2099-01-01&b_fim=2099-03-31",  # B no futuro = sem atividade
                headers=_token(),
            )
        assert response.status_code == 200
        body = response.json()
        assert body["pontos"] == []
        # total_sem_localizacao zerado por design (semântica ambígua entre recortes).
        assert body["total_sem_localizacao"] == 0
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_mapa_clientes_comparar_range_invertido_422() -> None:
    """Validação: `fim < inicio` em A ou B → 422 EntradaInvalida (não chega na conn)."""
    fake = FakeConnMapa([])

    async def _override():
        yield fake

    app.dependency_overrides[get_conn] = _override
    try:
        with TestClient(app) as client:
            response = client.get(
                "/v1/crm/clientes/mapa"
                "?comparar=true"
                "&a_inicio=2026-03-31&a_fim=2026-01-01"
                "&b_inicio=2026-04-01&b_fim=2026-05-31",
                headers=_token(),
            )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "COMPARAR_RECORTE_VAZIO"
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_mapa_clientes_comparar_ignora_periodo_e_recencia() -> None:
    """`comparar=true` ignora `periodo`/`recencia` — não viram cláusula no SQL final."""
    fake = FakeConnMapa([_ponto_recorte("A")])

    async def _override():
        yield fake

    app.dependency_overrides[get_conn] = _override
    try:
        with TestClient(app) as client:
            response = client.get(
                "/v1/crm/clientes/mapa"
                "?comparar=true&periodo=7d&recencia=ativos"
                "&a_inicio=2026-01-01&a_fim=2026-03-31"
                "&b_inicio=2026-04-01&b_fim=2026-05-31",
                headers=_token(),
            )
        assert response.status_code == 200
        assert fake.last_query is not None
        # `INTERVAL '7 days'`/`INTERVAL '90 days'` são marcas únicas das cláusulas
        # de periodo/recencia — não devem aparecer no SQL do modo comparar.
        assert "INTERVAL '7 days'" not in fake.last_query
        assert "INTERVAL '90 days'" not in fake.last_query
    finally:
        app.dependency_overrides.pop(get_conn, None)


# ---------------------------------------------------------------------------
# Task 9: "Período personalizado" no filtro simples (data_inicio/data_fim).
# Mesma estratégia dos testes do MAPA-8/11: o FakeConn não aplica o WHERE, mas
# guarda a query/params para inspeção. Verifica que a janela explícita entra no
# WHERE, tem precedência sobre `periodo`, valida `fim < inicio` e combina com os
# demais filtros (modelo/perfil) no mesmo WHERE.


def test_mapa_clientes_periodo_custom_filtra_intervalo() -> None:
    fake = FakeConnMapa([_ponto("Fechado")])

    async def _override():
        yield fake

    app.dependency_overrides[get_conn] = _override
    try:
        with TestClient(app) as client:
            response = client.get(
                "/v1/crm/clientes/mapa?data_inicio=2026-04-01&data_fim=2026-04-30",
                headers=_token(),
            )
        assert response.status_code == 200
        assert fake.last_query is not None
        # Janela `[inicio, fim+1 day)` em `created_at` no EXISTS de atendimentos.
        assert "a.created_at >= %s::date" in fake.last_query
        assert "a.created_at < (%s::date + INTERVAL '1 day')" in fake.last_query
        assert isinstance(fake.last_params, list)
        assert _date(2026, 4, 1) in fake.last_params
        assert _date(2026, 4, 30) in fake.last_params
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_mapa_clientes_periodo_custom_tem_precedencia_sobre_preset() -> None:
    """Com `data_inicio`/`data_fim`, o preset `periodo` é ignorado (sem dupla cláusula)."""
    fake = FakeConnMapa([_ponto("Fechado")])

    async def _override():
        yield fake

    app.dependency_overrides[get_conn] = _override
    try:
        with TestClient(app) as client:
            response = client.get(
                "/v1/crm/clientes/mapa"
                "?periodo=7d&data_inicio=2026-04-01&data_fim=2026-04-30",
                headers=_token(),
            )
        assert response.status_code == 200
        assert fake.last_query is not None
        # O preset NÃO entra quando há janela custom.
        assert "INTERVAL '7 days'" not in fake.last_query
        assert "a.created_at < (%s::date + INTERVAL '1 day')" in fake.last_query
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_mapa_clientes_periodo_custom_range_invertido_422() -> None:
    """`data_fim < data_inicio` → 422 (espelha a validação do modo Comparar)."""
    fake = FakeConnMapa([])

    async def _override():
        yield fake

    app.dependency_overrides[get_conn] = _override
    try:
        with TestClient(app) as client:
            response = client.get(
                "/v1/crm/clientes/mapa?data_inicio=2026-04-30&data_fim=2026-04-01",
                headers=_token(),
            )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "COMPARAR_RECORTE_VAZIO"
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_mapa_clientes_periodo_custom_incompleto_422() -> None:
    """Só uma das datas → 422 (a UI sempre manda as duas; defesa em profundidade)."""
    fake = FakeConnMapa([])

    async def _override():
        yield fake

    app.dependency_overrides[get_conn] = _override
    try:
        with TestClient(app) as client:
            response = client.get(
                "/v1/crm/clientes/mapa?data_inicio=2026-04-01",
                headers=_token(),
            )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "COMPARAR_RECORTE_INCOMPLETO"
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_mapa_clientes_periodo_custom_combina_com_modelo_e_perfil() -> None:
    """A janela custom convive com os filtros de modelo e perfil no mesmo WHERE."""
    fake = FakeConnMapa([_ponto("Fechado")])
    modelo_id = uuid4()

    async def _override():
        yield fake

    app.dependency_overrides[get_conn] = _override
    try:
        with TestClient(app) as client:
            response = client.get(
                "/v1/crm/clientes/mapa"
                f"?data_inicio=2026-04-01&data_fim=2026-04-30&modelo_id={modelo_id}&perfis=loira",
                headers=_token(),
            )
        assert response.status_code == 200
        assert fake.last_query is not None
        # As três cláusulas coexistem no WHERE.
        assert "a.created_at < (%s::date + INTERVAL '1 day')" in fake.last_query
        assert "cv.modelo_id = %s" in fake.last_query
        assert "c.perfis_preferidos && %s::barravips.perfil_fisico_enum[]" in fake.last_query
        assert isinstance(fake.last_params, list)
        assert ["loira"] in fake.last_params
    finally:
        app.dependency_overrides.pop(get_conn, None)
