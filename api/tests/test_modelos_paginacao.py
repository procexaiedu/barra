"""GET /v1/modelos — paginação por keyset consistente com a ordenação composta.

A lista ordena por situação (ativa, pausada, resto) e só depois por antiguidade. Enquanto o
cursor era só `created_at`, a segunda página pulava modelos (as de situação pior têm
`created_at` menor) e podia repetir outras: sumir uma modelo da lista da agência é um bug
operacional silencioso. Aqui o cursor carrega a tupla inteira que ordena.
"""

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from psycopg import AsyncConnection
from psycopg.rows import dict_row
from starlette.requests import Request

from barra.core.errors import EntradaInvalida
from barra.dominio.modelos.routes import _keyset_modelos, listar_modelos
from barra.main import app

BASE = datetime(2026, 1, 1, tzinfo=UTC)


# =============================================================================
# Cursor: formato e validação
# =============================================================================


def test_keyset_compara_a_tupla_inteira_que_ordena() -> None:
    sql, params = _keyset_modelos(f"1|{BASE.isoformat()}|{'0' * 8}-0000-0000-0000-000000000001")
    assert "m.created_at, m.id) > (%s, %s, %s)" in sql
    assert params[0] == 1
    assert params[1] == BASE
    assert isinstance(params[2], UUID)


def test_keyset_aceita_cursor_legado_so_com_created_at() -> None:
    sql, params = _keyset_modelos(BASE.isoformat())
    assert sql == "m.created_at > %s"
    assert params == [BASE]


@pytest.mark.parametrize(
    "cursor",
    ["banana", "1|banana|" + str(uuid4()), f"1|{BASE.isoformat()}|nao-e-uuid", "1|2|3|4"],
)
def test_keyset_recusa_cursor_invalido_sem_estourar_500(cursor: str) -> None:
    with pytest.raises(EntradaInvalida) as exc:
        _keyset_modelos(cursor)
    assert exc.value.code == "CURSOR_INVALIDO"


# =============================================================================
# Travessia da fronteira de situação (sem banco: FakeConn ordena/filtra como o Postgres)
# =============================================================================


def _linha(nome: str, status: str, minutos: int, sufixo: int) -> dict[str, Any]:
    return {
        "id": UUID(f"00000000-0000-0000-0000-{sufixo:012d}"),
        "nome": nome,
        "numero_whatsapp": f"5521999{sufixo:06d}",
        "status": status,
        "evolution_instance_id": None,
        "evolution_status": None,
        "evolution_pareado_em": None,
        "coordenacao_chat_id": None,
        "foto_perfil_object_key": None,
        "created_at": BASE + timedelta(minutes=minutos),
        "ordem_status": {"ativa": 0, "pausada": 1}.get(status, 2),
        "atendimentos_abertos": 0,
        "conversas_ia_pausada": 0,
        "ultimo_handoff_em": None,
    }


# `created_at` deliberadamente anticorrelacionado com a situação: as pausadas/inativa são as
# mais antigas, então elas só aparecem se o cursor souber em que faixa de situação parou.
DATASET = [
    _linha("Ana", "ativa", 50, 1),
    _linha("Bia", "ativa", 60, 2),
    _linha("Cris", "pausada", 10, 3),
    _linha("Dani", "pausada", 20, 4),  # empate de created_at com a Eva: desempata por id
    _linha("Eva", "pausada", 20, 5),
    _linha("Fran", "inativa", 0, 6),
]
ORDEM_ESPERADA = ["Ana", "Bia", "Cris", "Dani", "Eva", "Fran"]


class _Result:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    async def fetchall(self) -> list[dict[str, Any]]:
        return self._rows


class FakeConn:
    """Aplica ORDER BY (ordem_status, created_at, id) + o keyset recebido, como o Postgres."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    async def execute(self, query: str, params: list[Any] | None = None) -> _Result:
        params = list(params or [])
        limite = params[-1]
        rows = sorted(self._rows, key=lambda r: (r["ordem_status"], r["created_at"], r["id"]))
        if "m.created_at, m.id) > (%s, %s, %s)" in query:
            chave = tuple(params[:3])
            rows = [r for r in rows if (r["ordem_status"], r["created_at"], r["id"]) > chave]
        elif "m.created_at > %s" in query:
            rows = [r for r in rows if r["created_at"] > params[0]]
        return _Result(rows[:limite])


def _request() -> Request:
    return Request(
        {"type": "http", "method": "GET", "path": "/v1/modelos", "headers": [], "app": app}
    )


async def test_paginacao_atravessa_a_fronteira_de_situacao_sem_pular_nem_repetir() -> None:
    conn = FakeConn(DATASET)
    vistos: list[str] = []
    cursor: str | None = None
    for _ in range(len(DATASET) + 1):
        pagina = await listar_modelos(_request(), limit=2, cursor=cursor, conn=conn)  # type: ignore[arg-type]
        vistos.extend(item["nome"] for item in pagina["items"])
        cursor = pagina["next_cursor"]
        if cursor is None:
            break
    assert cursor is None
    assert vistos == ORDEM_ESPERADA


async def test_cursor_legado_de_created_at_continua_aceito() -> None:
    """Página em voo no deploy não pode virar erro — o formato antigo ainda responde."""
    pagina = await listar_modelos(
        _request(),
        limit=10,
        cursor=(BASE + timedelta(minutes=20)).isoformat(),
        conn=FakeConn(DATASET),  # type: ignore[arg-type]
    )
    assert [item["nome"] for item in pagina["items"]] == ["Ana", "Bia"]


# =============================================================================
# Postgres real (needs_db): a mesma travessia contra a ordenação de verdade
# =============================================================================


@pytest_asyncio.fixture
async def conn_real() -> AsyncIterator[AsyncConnection[dict[str, Any]]]:
    connection = await AsyncConnection.connect(
        os.environ["TEST_DATABASE_URL"],
        autocommit=False,
        row_factory=dict_row,
        prepare_threshold=None,
    )
    try:
        yield connection
    finally:
        try:
            await connection.rollback()
        finally:
            await connection.close()


@pytest.mark.needs_db
async def test_paginacao_real_nao_perde_modelo_na_virada_de_situacao(
    conn_real: AsyncConnection[dict[str, Any]],
) -> None:
    prefixo = f"keyset{uuid4().hex[:8]}"
    plano = [
        ("ativa", 50),
        ("ativa", 60),
        ("pausada", 10),
        ("pausada", 20),
        ("pausada", 20),
        ("inativa", 0),
    ]
    for indice, (status, minutos) in enumerate(plano):
        await conn_real.execute(
            """
            INSERT INTO barravips.modelos
                (nome, idade, numero_whatsapp, valor_padrao, tipo_atendimento_aceito,
                 status, created_at)
            VALUES (%s, %s, %s, %s, %s::barravips.tipo_atendimento_enum[],
                    %s::barravips.modelo_status_enum, %s)
            """,
            (
                f"{prefixo} {indice}",
                28,
                f"test-wpp-{uuid4().hex}",
                500,
                ["interno"],
                status,
                BASE + timedelta(minutes=minutos),
            ),
        )

    vistos: list[str] = []
    cursor: str | None = None
    for _ in range(len(plano) + 1):
        pagina = await listar_modelos(
            _request(),
            q=prefixo,
            limit=2,
            cursor=cursor,
            conn=conn_real,
        )
        vistos.extend(item["nome"] for item in pagina["items"])
        cursor = pagina["next_cursor"]
        if cursor is None:
            break

    assert cursor is None
    assert len(vistos) == len(plano)
    assert len(set(vistos)) == len(plano)
    assert [nome.split()[-1] for nome in vistos[:2]] == ["0", "1"]
    assert vistos[-1].endswith("5")
