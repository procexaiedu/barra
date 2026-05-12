"""Regressao: metricas avancadas do CRM isoladas pelo par (cliente, modelo).

Conforme CONTEXT.md "IA por modelo" e docs/specs/tela-04-crm.md §3.3, as
metricas exibidas em uma conversa devem refletir apenas o par cliente-modelo
daquela conversa, sem agregar dados de outras modelos.
"""

from contextlib import asynccontextmanager
from datetime import UTC, datetime
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


class FakeConnConversaMetricas:
    """Fake conn que retorna metricas distintas conforme o modelo_id passado.

    Simula 2 conversas (cliente C, modelos M1 e M2). Cada par tem metricas
    proprias: programa, duracao e forma de pagamento diferentes por par.
    """

    def __init__(
        self,
        conversa_id: UUID,
        cliente_id: UUID,
        modelo_id: UUID,
        outras_modelos: dict[UUID, dict[str, Any]],
        metricas_par: dict[str, Any],
    ) -> None:
        self.conversa_id = conversa_id
        self.cliente_id = cliente_id
        self.modelo_id = modelo_id
        self.outras_modelos = outras_modelos
        self.metricas_par = metricas_par
        self.executes: list[tuple[str, object]] = []

    @asynccontextmanager
    async def transaction(self):
        yield

    async def execute(self, query: str, params: object = None) -> _Result:
        self.executes.append((query, params))

        # SELECT da conversa principal
        if "JOIN barravips.modelos m ON m.id = cv.modelo_id" in query and "WHERE cv.id = %s" in query:
            return _Result(
                [
                    {
                        "id": self.conversa_id,
                        "recorrente": False,
                        "observacoes_internas": None,
                        "ultimo_motivo_perda": None,
                        "ultima_mensagem_em": datetime.now(UTC),
                        "ultima_mensagem_direcao": "entrada",
                        "created_at": datetime.now(UTC),
                        "cliente_id": self.cliente_id,
                        "cliente_nome": "Cliente C",
                        "cliente_telefone": "5521999998888",
                        "cliente_created_at": datetime.now(UTC),
                        "primeiro_contato_modelo_nome": None,
                        "modelo_id": self.modelo_id,
                        "modelo_nome": self.metricas_par["modelo_nome"],
                    }
                ]
            )

        # atendimento_aberto e historico_atendimentos
        if "FROM barravips.atendimentos" in query and "conversa_id = %s" in query:
            return _Result([])

        # Queries de metricas: agora carregam (cliente_id, modelo_id)
        if "GROUP BY m.id, m.nome" in query:
            # modelo_preferida: deve ser a propria modelo do par
            return _Result(
                [{"id": self.modelo_id, "nome": self.metricas_par["modelo_nome"]}]
            )
        if "GROUP BY a.tipo_atendimento" in query:
            return _Result(
                [{"tipo_atendimento": self.metricas_par["tipo_atendimento"]}]
            )
        if "GROUP BY p.id, p.nome" in query:
            return _Result([self.metricas_par["programa"]])
        if "GROUP BY d.id, d.nome" in query:
            return _Result([self.metricas_par["duracao"]])
        if "GROUP BY a.forma_pagamento" in query:
            return _Result(
                [{"forma_pagamento": self.metricas_par["forma_pagamento"]}]
            )

        return _Result([])


def _token() -> dict[str, str]:
    return {"Authorization": f"Bearer test:{uuid4()}:fernando:true"}


def _metricas_para_par(modelo_nome: str, sufixo: str) -> dict[str, Any]:
    return {
        "modelo_nome": modelo_nome,
        "tipo_atendimento": f"interno_{sufixo}",
        "programa": {"id": uuid4(), "nome": f"Programa {sufixo}"},
        "duracao": {"id": uuid4(), "nome": f"Duracao {sufixo}"},
        "forma_pagamento": f"pix_{sufixo}",
    }


def test_obter_conversa_passa_modelo_id_em_todas_metricas() -> None:
    """Cada query de metrica deve receber (cliente_id, modelo_id) como params."""
    conversa_id = uuid4()
    cliente_id = uuid4()
    modelo_id = uuid4()
    fake = FakeConnConversaMetricas(
        conversa_id,
        cliente_id,
        modelo_id,
        outras_modelos={},
        metricas_par=_metricas_para_par("Modelo M1", "m1"),
    )

    async def _override():
        yield fake

    app.dependency_overrides[get_conn] = _override
    try:
        with TestClient(app) as client:
            response = client.get(f"/v1/crm/conversas/{conversa_id}", headers=_token())
        assert response.status_code == 200

        # Confere que cada uma das 5 queries de metricas filtrou por cv.modelo_id
        metricas_executadas = [
            (q, p)
            for q, p in fake.executes
            if "ORDER BY COUNT(*) DESC" in q and "LIMIT 1" in q
        ]
        assert len(metricas_executadas) == 5, (
            f"Esperava 5 queries de metricas, obteve {len(metricas_executadas)}"
        )
        for query, params in metricas_executadas:
            assert "cv.modelo_id = %s" in query, (
                "Query de metrica sem filtro por modelo_id:\n" + query
            )
            assert params == (cliente_id, modelo_id), (
                f"Params devem ser (cliente_id, modelo_id); recebido {params}"
            )
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_obter_conversa_metricas_isoladas_por_par_m1() -> None:
    """Conversa do par (C, M1) retorna metricas baseadas apenas no proprio par."""
    conversa_id = uuid4()
    cliente_id = uuid4()
    modelo_id = uuid4()
    metricas_m1 = _metricas_para_par("Modelo M1", "m1")
    fake = FakeConnConversaMetricas(
        conversa_id, cliente_id, modelo_id, outras_modelos={}, metricas_par=metricas_m1
    )

    async def _override():
        yield fake

    app.dependency_overrides[get_conn] = _override
    try:
        with TestClient(app) as client:
            response = client.get(f"/v1/crm/conversas/{conversa_id}", headers=_token())
        assert response.status_code == 200
        body = response.json()
        assert body["cliente"]["modelo_preferida"]["nome"] == "Modelo M1"
        assert body["cliente"]["tipo_atendimento_mais_frequente"] == "interno_m1"
        assert body["cliente"]["programa_preferido"]["nome"] == "Programa m1"
        assert body["cliente"]["duracao_preferida"]["nome"] == "Duracao m1"
        assert body["cliente"]["forma_pagamento_preferida"] == "pix_m1"
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_obter_conversa_metricas_isoladas_por_par_m2() -> None:
    """Conversa do par (C, M2) retorna metricas distintas, sem contaminacao de M1."""
    conversa_id = uuid4()
    cliente_id = uuid4()
    modelo_id = uuid4()
    metricas_m2 = _metricas_para_par("Modelo M2", "m2")
    fake = FakeConnConversaMetricas(
        conversa_id, cliente_id, modelo_id, outras_modelos={}, metricas_par=metricas_m2
    )

    async def _override():
        yield fake

    app.dependency_overrides[get_conn] = _override
    try:
        with TestClient(app) as client:
            response = client.get(f"/v1/crm/conversas/{conversa_id}", headers=_token())
        assert response.status_code == 200
        body = response.json()
        assert body["cliente"]["modelo_preferida"]["nome"] == "Modelo M2"
        assert body["cliente"]["tipo_atendimento_mais_frequente"] == "interno_m2"
        assert body["cliente"]["programa_preferido"]["nome"] == "Programa m2"
        assert body["cliente"]["duracao_preferida"]["nome"] == "Duracao m2"
        assert body["cliente"]["forma_pagamento_preferida"] == "pix_m2"
    finally:
        app.dependency_overrides.pop(get_conn, None)
