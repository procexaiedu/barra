"""Integração do Dashboard — métricas financeiras (bruto, líquido, repasses)."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from barra.api.deps import get_conn
from barra.main import app

# ---------------------------------------------------------------------------
# Fake connection
# ---------------------------------------------------------------------------


class _Result:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows or []

    async def fetchone(self) -> dict[str, Any] | None:
        return self.rows[0] if self.rows else None

    async def fetchall(self) -> list[dict[str, Any]]:
        return self.rows


class FakeConn:
    """Conexão fake que devolve respostas determinísticas por padrão de query."""

    def __init__(
        self,
        atendimentos: list[dict[str, Any]] | None = None,
        modelos: list[dict[str, Any]] | None = None,
        custo_ia: float = 0.0,
        importados_sem_data: tuple[int, float] = (0, 0.0),
    ) -> None:
        self.atendimentos = atendimentos or []
        self.modelos = modelos or []
        self.custo_ia = custo_ia
        self.importados_sem_data = importados_sem_data
        self.last_queries: list[str] = []

    @asynccontextmanager
    async def transaction(self):
        yield

    async def execute(self, query: str, params: object = None) -> _Result:
        self.last_queries.append(query)
        params_seq: tuple[Any, ...]
        if params is None:
            params_seq = ()
        elif isinstance(params, (list, tuple)):
            params_seq = tuple(params)
        else:
            params_seq = (params,)
        modelo_filtro = self._extrair_modelo_filtro(query, params_seq)

        # _profissionais — CTE composta (precisa vir antes do match de _fechamentos
        # porque a CTE também contém "fechado_registrado" / "valor_liquido").
        if "WITH volume AS" in query:
            return _Result(self._linhas_profissionais(modelo_filtro))

        # Pix pendentes
        if "FROM barravips.comprovantes_pix" in query:
            return _Result([{"n": 0}])

        # _fechamentos (JOIN LATERAL: ancora dedupada de fechado_registrado — ADR 0011, exigir o
        # LATERAL aqui trava regressao do dedup que evita inflar os SUM sob correcao Perdido->Fechado)
        if (
            "FROM barravips.atendimentos a" in query
            and "JOIN LATERAL" in query
            and "fechado_registrado" in query
            and "valor_liquido" in query
        ):
            return _Result([self._agregar_fechamentos(modelo_filtro)])

        # _perdas (count puro)
        if (
            "FROM barravips.atendimentos a" in query
            and "JOIN barravips.eventos e" in query
            and "perdido_registrado" in query
            and "motivo_perda" not in query
            and "GROUP BY" not in query
        ):
            return _Result([{"contagem": self._contar_perdas(modelo_filtro)}])

        # _escaladas_contagem
        if "FROM barravips.escaladas e" in query and "GROUP BY" not in query:
            return _Result([{"n": 0}])

        # _funil_coorte
        if "FROM com_rank" in query:
            return _Result([self._funil_coorte(modelo_filtro)])

        # _norte_cotacao (coorte por cotacao_enviada_em)
        if "cotacao_enviada_em" in query:
            return _Result([self._agregar_norte(modelo_filtro)])

        # _perdas_por_motivo
        if "motivo_perda" in query and "GROUP BY a.motivo_perda" in query:
            return _Result([])

        # _motivos_escalada_top
        if "FROM barravips.escaladas e" in query and "GROUP BY e.motivo" in query:
            return _Result([])

        # _roi — custo de chat acumulado (atendimentos.custo_ia_brl)
        if "SUM(a.custo_ia_brl)" in query:
            return _Result([{"custo_ia": self.custo_ia}])

        # importados_sem_data (financeiro/repo) — Fechados sem evento fechado_registrado
        if "NOT EXISTS" in query and "fechado_registrado" in query:
            contagem, bruto = self.importados_sem_data
            return _Result([{"contagem": contagem, "valor_bruto": Decimal(str(bruto))}])

        return _Result([])

    # -----------------------------------------------------------------------
    # Helpers de agregação em memória (espelham o SQL)
    # -----------------------------------------------------------------------

    @staticmethod
    def _extrair_modelo_filtro(query: str, params: tuple[Any, ...]) -> set[UUID] | None:
        # Heurística: se o SQL filtra por modelo via ANY(%s), o parâmetro correspondente
        # é a lista de UUIDs selecionados (o código real passa list[UUID]).
        if "modelo_id = ANY(%s)" not in query:
            return None
        for p in reversed(params):
            if isinstance(p, (list, tuple)) and p and all(isinstance(x, UUID) for x in p):
                return set(p)
        return None

    def _fechados(self, modelo_filtro: set[UUID] | None) -> list[dict[str, Any]]:
        return [
            a
            for a in self.atendimentos
            if a["estado"] == "Fechado"
            and (modelo_filtro is None or a["modelo_id"] in modelo_filtro)
        ]

    def _perdidos(self, modelo_filtro: set[UUID] | None) -> list[dict[str, Any]]:
        return [
            a
            for a in self.atendimentos
            if a["estado"] == "Perdido"
            and (modelo_filtro is None or a["modelo_id"] in modelo_filtro)
        ]

    def _agregar_fechamentos(self, modelo_filtro: set[UUID] | None) -> dict[str, Any]:
        fechados = self._fechados(modelo_filtro)
        contagem = len(fechados)
        valor_bruto = Decimal("0")
        valor_liquido = Decimal("0")
        valor_repasse = Decimal("0")
        valor_sem_snapshot = Decimal("0")
        contagem_sem_snapshot = 0
        for a in fechados:
            valor = Decimal(str(a["valor_final"]))
            pct = a.get("percentual_repasse_snapshot")
            pct_dec = Decimal(str(pct)) if pct is not None else Decimal("0")
            valor_bruto += valor
            valor_liquido += valor * (Decimal("1") - pct_dec / Decimal("100"))
            valor_repasse += valor * pct_dec / Decimal("100")
            if pct is None:
                valor_sem_snapshot += valor
                contagem_sem_snapshot += 1
        return {
            "contagem": contagem,
            "valor_bruto": valor_bruto,
            "valor_liquido": valor_liquido,
            "valor_repasse_modelo": valor_repasse,
            "valor_sem_repasse_definido": valor_sem_snapshot,
            "contagem_sem_snapshot": contagem_sem_snapshot,
        }

    def _contar_perdas(self, modelo_filtro: set[UUID] | None) -> int:
        return len(self._perdidos(modelo_filtro))

    @staticmethod
    def _rank(a: dict[str, Any]) -> int:
        """Espelha o CASE de rank_max do SQL em _funil_coorte."""
        estado = a["estado"]
        if estado == "Perdido":
            return {
                "Aguardando_confirmacao": 2,
                "Confirmado": 2,
                "Em_execucao": 3,
                "Fechado": 3,
            }.get(a.get("de_estado"), 1)
        return {
            "Novo": 1,
            "Triagem": 1,
            "Qualificado": 1,
            "Aguardando_confirmacao": 2,
            "Confirmado": 2,
            "Em_execucao": 3,
            "Fechado": 4,
        }.get(estado, 1)

    def _funil_coorte(self, modelo_filtro: set[UUID] | None) -> dict[str, Any]:
        ats = [
            a for a in self.atendimentos if modelo_filtro is None or a["modelo_id"] in modelo_filtro
        ]
        ranks = [(a["estado"], self._rank(a)) for a in ats]
        return {
            "topo": len(ats),
            "coorte_aguardando": sum(1 for _, r in ranks if r >= 2),
            "coorte_execucao": sum(1 for _, r in ranks if r >= 3),
            "coorte_fechado": sum(1 for _, r in ranks if r >= 4),
            "perda_qualificando": sum(1 for e, r in ranks if e == "Perdido" and r == 1),
            "perda_aguardando": sum(1 for e, r in ranks if e == "Perdido" and r == 2),
            "perda_execucao": sum(1 for e, r in ranks if e == "Perdido" and r == 3),
        }

    def _agregar_norte(self, modelo_filtro: set[UUID] | None) -> dict[str, Any]:
        """Espelha o SQL de _norte_cotacao: coorte = atendimentos com cotacao_enviada_em setado."""
        cotadas = [
            a
            for a in self.atendimentos
            if a.get("cotacao_enviada_em") is not None
            and (modelo_filtro is None or a["modelo_id"] in modelo_filtro)
        ]
        fechadas = [a for a in cotadas if a["estado"] == "Fechado"]
        em_aberto = [a for a in cotadas if a["estado"] not in ("Fechado", "Perdido")]
        receita = sum(
            (Decimal(str(a["valor_final"])) for a in fechadas if a["valor_final"] is not None),
            Decimal("0"),
        )
        return {
            "cotadas": len(cotadas),
            "fechadas": len(fechadas),
            "em_aberto": len(em_aberto),
            "receita_bruta": receita,
        }

    def _linhas_profissionais(self, modelo_filtro: set[UUID] | None) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for m in self.modelos:
            if modelo_filtro is not None and m["id"] not in modelo_filtro:
                continue
            atendimentos_m = [a for a in self.atendimentos if a["modelo_id"] == m["id"]]
            fechados_m = [a for a in atendimentos_m if a["estado"] == "Fechado"]
            perdidos_m = [a for a in atendimentos_m if a["estado"] == "Perdido"]
            valor_bruto = Decimal("0")
            valor_liquido = Decimal("0")
            valor_repasse = Decimal("0")
            for a in fechados_m:
                valor = Decimal(str(a["valor_final"]))
                pct = a.get("percentual_repasse_snapshot")
                pct_dec = Decimal(str(pct)) if pct is not None else Decimal("0")
                valor_bruto += valor
                valor_liquido += valor * (Decimal("1") - pct_dec / Decimal("100"))
                valor_repasse += valor * pct_dec / Decimal("100")
            # fechamentos_periodo = fechados COM evento na janela (base da conversão);
            # `importado` (default False) marca os Fechado sem evento (histórico sem data),
            # que entram em fechamentos/valor mas não na conversão. Espelha fech + fech_imp.
            fech_periodo = [a for a in fechados_m if not a.get("importado", False)]
            rows.append(
                {
                    "modelo_id": m["id"],
                    "modelo_nome": m["nome"],
                    "volume": len(atendimentos_m),
                    "fechamentos_periodo": len(fech_periodo),
                    "fechamentos": len(fechados_m),
                    "valor_bruto": valor_bruto,
                    "valor_liquido": valor_liquido,
                    "valor_repasse_modelo": valor_repasse,
                    "perdas": len(perdidos_m),
                }
            )
        # Ordenação espelhada do SQL: volume DESC, valor_bruto DESC, nome ASC
        rows.sort(key=lambda r: (-r["volume"], -float(r["valor_bruto"]), r["modelo_nome"]))
        return rows


# ---------------------------------------------------------------------------
# Helpers de auth + override
# ---------------------------------------------------------------------------


def _token() -> dict[str, str]:
    return {"Authorization": f"Bearer test:{uuid4()}:fernando:true"}


def _instalar_override(conn: FakeConn) -> None:
    async def _override():
        yield conn

    app.dependency_overrides[get_conn] = _override


def _fechado(
    modelo_id: UUID,
    valor: str,
    pct: str | None,
    importado: bool = False,
) -> dict[str, Any]:
    return {
        "id": uuid4(),
        "modelo_id": modelo_id,
        "estado": "Fechado",
        "valor_final": Decimal(valor),
        "percentual_repasse_snapshot": Decimal(pct) if pct is not None else None,
        "created_at": datetime.now(UTC),
        # importado = Fechado sem evento `fechado_registrado` (histórico sem data): entra em
        # fechamentos/valor do ranking, mas não na base de conversão (fechamentos_periodo).
        "importado": importado,
    }


def _perdido(modelo_id: UUID, de_estado: str | None = None) -> dict[str, Any]:
    return {
        "id": uuid4(),
        "modelo_id": modelo_id,
        "estado": "Perdido",
        "de_estado": de_estado,  # estado de origem da transição → Perdido (None = origem ausente)
        "valor_final": None,
        "percentual_repasse_snapshot": None,
        "created_at": datetime.now(UTC),
    }


def _atend(modelo_id: UUID, estado: str) -> dict[str, Any]:
    """Atendimento em estado intermediário (não-terminal) para o funil de coorte."""
    return {
        "id": uuid4(),
        "modelo_id": modelo_id,
        "estado": estado,
        "valor_final": None,
        "percentual_repasse_snapshot": None,
        "created_at": datetime.now(UTC),
    }


def _cotado(modelo_id: UUID, estado: str, valor: str | None) -> dict[str, Any]:
    """Atendimento COTADO (cotacao_enviada_em setado) num estado dado — fixture do norte."""
    return {
        "id": uuid4(),
        "modelo_id": modelo_id,
        "estado": estado,
        "valor_final": Decimal(valor) if valor is not None else None,
        "percentual_repasse_snapshot": None,
        "created_at": datetime.now(UTC),
        "cotacao_enviada_em": datetime.now(UTC),
    }


# ---------------------------------------------------------------------------
# Testes
# ---------------------------------------------------------------------------


def test_fechamentos_calcula_liquido_e_repasse() -> None:
    """fechado com snapshot 40% + fechado com NULL + perdido (não entra)."""
    modelo_id = uuid4()
    conn = FakeConn(
        atendimentos=[
            _fechado(modelo_id, "1000.00", "40"),
            _fechado(modelo_id, "500.00", None),
            _perdido(modelo_id),
        ],
        modelos=[{"id": modelo_id, "nome": "Alice"}],
    )

    _instalar_override(conn)
    try:
        with TestClient(app) as client:
            response = client.get("/v1/dashboard", params={"periodo": "7d"}, headers=_token())
    finally:
        app.dependency_overrides.pop(get_conn, None)

    assert response.status_code == 200
    fech = response.json()["kpis_periodo"]["fechamentos"]

    # 1000 + 500 = 1500
    assert fech["valor_bruto_brl"] == 1500.00
    # 1000 * 0.6 + 500 * 1.0 = 600 + 500 = 1100
    assert fech["valor_liquido_brl"] == 1100.00
    # 1000 * 0.4 + 500 * 0.0 = 400
    assert fech["valor_repasse_modelo_brl"] == 400.00
    # Apenas o fechado com pct NULL: 500
    assert fech["valor_sem_repasse_definido_brl"] == 500.00
    # Invariante: bruto == liquido + repasse_modelo
    assert fech["valor_bruto_brl"] == round(
        fech["valor_liquido_brl"] + fech["valor_repasse_modelo_brl"], 2
    )
    assert fech["contagem"] == 2
    assert fech["contagem_sem_snapshot"] == 1


def test_profissionais_inclui_liquido_e_repasse() -> None:
    """Duas modelos com snapshots diferentes (50% e 30%) e fechados distintos."""
    alice = uuid4()
    bia = uuid4()
    conn = FakeConn(
        atendimentos=[
            _fechado(alice, "1000", "50"),
            _fechado(alice, "200", "50"),
            _fechado(bia, "800", "30"),
        ],
        modelos=[
            {"id": alice, "nome": "Alice"},
            {"id": bia, "nome": "Bia"},
        ],
    )

    _instalar_override(conn)
    try:
        with TestClient(app) as client:
            response = client.get("/v1/dashboard", params={"periodo": "7d"}, headers=_token())
    finally:
        app.dependency_overrides.pop(get_conn, None)

    assert response.status_code == 200
    profissionais = response.json()["profissionais"]
    por_nome = {p["modelo"]["nome"]: p for p in profissionais}

    alice_row = por_nome["Alice"]
    assert alice_row["valor_bruto_brl"] == 1200.00
    # 1200 * 0.5
    assert alice_row["valor_liquido_brl"] == 600.00
    assert alice_row["valor_repasse_modelo_brl"] == 600.00

    bia_row = por_nome["Bia"]
    assert bia_row["valor_bruto_brl"] == 800.00
    # 800 * 0.7
    assert bia_row["valor_liquido_brl"] == 560.00
    # 800 * 0.3
    assert bia_row["valor_repasse_modelo_brl"] == 240.00


def test_profissionais_inclui_fechados_importados_sem_data() -> None:
    """Fechado importado sem evento (histórico do caderno) entra em fechamentos/valor do
    ranking — antes ficava zerado porque a CTE ancorava no evento `fechado_registrado`. A
    conversão usa só o desfecho COM evento, então importado sem perda não infla a taxa."""
    nina = uuid4()
    conn = FakeConn(
        atendimentos=[
            _fechado(nina, "1000", None, importado=True),
            _fechado(nina, "500", None, importado=True),
        ],
        modelos=[{"id": nina, "nome": "Nina"}],
    )

    _instalar_override(conn)
    try:
        with TestClient(app) as client:
            response = client.get("/v1/dashboard", params={"periodo": "7d"}, headers=_token())
    finally:
        app.dependency_overrides.pop(get_conn, None)

    assert response.status_code == 200
    nina_row = next(p for p in response.json()["profissionais"] if p["modelo"]["nome"] == "Nina")
    # fechamentos e valor refletem os importados (não ficam zerados)
    assert nina_row["fechamentos"] == 2
    assert nina_row["valor_bruto_brl"] == 1500.00
    # sem snapshot de repasse → líquido = bruto, repasse = 0 (dado de repasse não existe)
    assert nina_row["valor_liquido_brl"] == 1500.00
    assert nina_row["valor_repasse_modelo_brl"] == 0.00
    # conversão não é inflada: sem desfecho COM evento, n_referencia = 0 e taxa = None
    assert nina_row["n_referencia"] == 0
    assert nina_row["taxa_conversao_pct"] is None


def test_dashboard_bloco_financeiro_top_level() -> None:
    """O payload deve conter `financeiro` top-level com somatórios e contagens."""
    modelo_id = uuid4()
    conn = FakeConn(
        atendimentos=[
            _fechado(modelo_id, "1000", "40"),
            _fechado(modelo_id, "500", None),
        ],
        modelos=[{"id": modelo_id, "nome": "Alice"}],
    )

    _instalar_override(conn)
    try:
        with TestClient(app) as client:
            response = client.get("/v1/dashboard", params={"periodo": "7d"}, headers=_token())
    finally:
        app.dependency_overrides.pop(get_conn, None)

    assert response.status_code == 200
    body = response.json()
    assert "financeiro" in body
    financeiro = body["financeiro"]

    chaves = {
        "valor_bruto_brl",
        "valor_liquido_brl",
        "valor_repasse_modelo_brl",
        "valor_sem_repasse_definido_brl",
        "fechamentos_total",
        "fechamentos_sem_snapshot",
    }
    assert chaves <= set(financeiro.keys())

    assert financeiro["valor_bruto_brl"] == 1500.00
    # 1000 * 0.6 + 500 * 1.0 = 1100
    assert financeiro["valor_liquido_brl"] == 1100.00
    # 1000 * 0.4
    assert financeiro["valor_repasse_modelo_brl"] == 400.00
    assert financeiro["valor_sem_repasse_definido_brl"] == 500.00
    assert financeiro["fechamentos_total"] == 2
    assert financeiro["fechamentos_sem_snapshot"] == 1

    # Período anterior também deve carregar bloco financeiro (mesmo zerado).
    assert "financeiro_periodo_anterior" in body
    assert body["financeiro_periodo_anterior"] is not None
    assert set(body["financeiro_periodo_anterior"].keys()) == chaves


def test_funil_coorte_por_etapa() -> None:
    """Coorte (rank ≥ K) por etapa + perda lateral (Perdido cujo rank = K)."""
    m = uuid4()
    conn = FakeConn(
        atendimentos=[
            _atend(m, "Novo"),
            _atend(m, "Novo"),
            _atend(m, "Qualificado"),  # 3 em rank 1 (Qualificando)
            _atend(m, "Aguardando_confirmacao"),
            _atend(m, "Aguardando_confirmacao"),  # 2 em rank 2 (Aguardando)
            _atend(m, "Em_execucao"),  # 1 em rank 3 (Em atendimento)
            _fechado(m, "1000", "40"),
            _fechado(m, "1000", "40"),
            _fechado(m, "1000", "40"),  # 3 em rank 4 (Fechado)
            _perdido(m),  # origem ausente → rank 1
            _perdido(m, "Confirmado"),  # rank 2
            _perdido(m, "Em_execucao"),  # rank 3
            _perdido(m, "Em_execucao"),  # rank 3
        ],
        modelos=[{"id": m, "nome": "Alice"}],
    )

    _instalar_override(conn)
    try:
        with TestClient(app) as client:
            response = client.get("/v1/dashboard", params={"periodo": "7d"}, headers=_token())
    finally:
        app.dependency_overrides.pop(get_conn, None)

    assert response.status_code == 200
    funil = response.json()["funil"]

    assert funil["topo"] == 13
    assert funil["perdidos_total"] == 4

    por_id = {e["id"]: e for e in funil["etapas"]}
    # Ordem preservada e 4 etapas de progressão (Perdido não é barra).
    assert [e["id"] for e in funil["etapas"]] == [
        "Qualificando",
        "Aguardando",
        "Em_execucao",
        "Fechado",
    ]
    # Coorte = quantos chegaram pelo menos até a etapa (inclui perdidos que passaram por ali).
    assert por_id["Qualificando"]["coorte"] == 13  # topo
    assert por_id["Aguardando"]["coorte"] == 9  # 2 ag + 1 exec + 3 fech + (1 perdido r2 + 2 r3)
    assert por_id["Em_execucao"]["coorte"] == 6  # 1 exec + 3 fech + 2 perdidos r3
    assert por_id["Fechado"]["coorte"] == 3  # só fechados; Perdido nunca chega a 4
    # Perda lateral por etapa de origem.
    assert por_id["Qualificando"]["perdas"] == 1
    assert por_id["Aguardando"]["perdas"] == 1
    assert por_id["Em_execucao"]["perdas"] == 2
    assert por_id["Fechado"]["perdas"] == 0


def test_dashboard_filtra_multiplas_modelos() -> None:
    """modelo_id repetido agrega só as modelos selecionadas (filtro = ANY)."""
    alice = uuid4()
    bia = uuid4()
    cris = uuid4()
    conn = FakeConn(
        atendimentos=[
            _fechado(alice, "1000", "0"),
            _fechado(bia, "500", "0"),
            _fechado(cris, "9999", "0"),  # fora da seleção — não pode entrar nos KPIs
        ],
        modelos=[
            {"id": alice, "nome": "Alice"},
            {"id": bia, "nome": "Bia"},
            {"id": cris, "nome": "Cris"},
        ],
    )

    _instalar_override(conn)
    try:
        with TestClient(app) as client:
            response = client.get(
                "/v1/dashboard",
                params={"periodo": "7d", "modelo_id": [str(alice), str(bia)]},
                headers=_token(),
            )
    finally:
        app.dependency_overrides.pop(get_conn, None)

    assert response.status_code == 200
    body = response.json()

    fech = body["kpis_periodo"]["fechamentos"]
    # Alice (1000) + Bia (500); Cris (9999) fica de fora.
    assert fech["valor_bruto_brl"] == 1500.00
    assert fech["contagem"] == 2

    # filtro_aplicado expõe a lista selecionada.
    assert set(body["filtro_aplicado"]["modelo_ids"]) == {str(alice), str(bia)}

    # O ranking de profissionais NÃO filtra — mostra todas (destaque é no frontend).
    nomes = {p["modelo"]["nome"] for p in body["profissionais"]}
    assert nomes == {"Alice", "Bia", "Cris"}


def test_roi_ia_expoe_custo_acumulado() -> None:
    # OBS go-live: o bloco roi_ia soma atendimentos.custo_ia_brl da janela (acumulado por turno
    # pelo coordenador). Sem Fechado da IA na janela, custo_por_fechado fica None.
    conn = FakeConn(custo_ia=12.345)
    _instalar_override(conn)
    try:
        with TestClient(app) as client:
            response = client.get("/v1/dashboard", params={"periodo": "7d"}, headers=_token())
    finally:
        app.dependency_overrides.pop(get_conn, None)

    assert response.status_code == 200
    roi = response.json()["roi_ia"]
    assert roi["custo_ia_brl"] == 12.35
    assert roi["custo_ia_por_fechado_brl"] is None
    assert "Sonnet" in roi["nota_custo_ia"]


def test_importados_sem_data_expoe_balde() -> None:
    # Fechados importados sem evento `fechado_registrado` (histórico do caderno do vendedor)
    # ficam fora do recorte por período (regime caixa, ADR 0011). O dashboard espelha o balde
    # do Financeiro para eles não somirem — aparecem no volume, não no financeiro do período.
    conn = FakeConn(importados_sem_data=(384, 235080.0))
    _instalar_override(conn)
    try:
        with TestClient(app) as client:
            response = client.get("/v1/dashboard", params={"periodo": "7d"}, headers=_token())
    finally:
        app.dependency_overrides.pop(get_conn, None)

    assert response.status_code == 200
    bloco = response.json()["importados_sem_data"]
    assert bloco["contagem"] == 384
    assert bloco["valor_bruto_brl"] == 235080.0


def test_norte_cotacao_conversao_e_receita_por_thread() -> None:
    """Norte: das threads cotadas, % que fechou + R$/thread cotada (denominador = cotadas)."""
    m = uuid4()
    conn = FakeConn(
        atendimentos=[
            _cotado(m, "Fechado", "400"),
            _cotado(m, "Fechado", "600"),
            _cotado(m, "Perdido", None),
            _cotado(m, "Qualificado", None),  # cotado, ainda em aberto
            _atend(m, "Triagem"),  # NÃO cotou → fora do denominador
        ],
        modelos=[{"id": m, "nome": "Alice"}],
    )

    _instalar_override(conn)
    try:
        with TestClient(app) as client:
            response = client.get("/v1/dashboard", params={"periodo": "7d"}, headers=_token())
    finally:
        app.dependency_overrides.pop(get_conn, None)

    assert response.status_code == 200
    norte = response.json()["norte_cotacao"]
    assert norte["cotadas"] == 4  # 2 fechado + 1 perdido + 1 qualificado (Triagem não cotou)
    assert norte["fechadas"] == 2
    assert norte["em_aberto"] == 1  # o Qualificado
    assert norte["conversao_cotada_para_fechado_pct"] == 50.0  # 2/4
    assert norte["receita_bruta_brl"] == 1000.00  # 400 + 600
    assert norte["r_por_thread_cotada_brl"] == 250.00  # 1000 / 4
