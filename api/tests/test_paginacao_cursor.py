"""Paginação por cursor de Pix e Conversas — o cursor tem de carregar a tupla que ordena.

Os dois endpoints ordenavam por uma coisa e paginavam por outra. No Pix, a ordem é só
`created_at` e a comparação é estrita: comprovantes gravados no mesmo instante (lote,
reenvio) desapareciam da paginação, e a ordem entre eles nem era estável. Em Conversas
("recente"), além do mesmo empate, uma página que terminasse na faixa das conversas sem
mensagem devolvia `next_cursor=None` e a lista acabava com conversa por mostrar.

Sumir um comprovante é pior do que parece: ele fica preso em `em_revisao` com a IA pausada
naquele atendimento, e ninguém no painel consegue alcançá-lo.

Sem banco: o FakeConn ordena e aplica o keyset como o Postgres faria.
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from barra.dominio.conversas.routes import listar_conversas
from barra.dominio.pix.routes import listar_pix

BASE = datetime(2026, 1, 1, tzinfo=UTC)


def _id(sufixo: int) -> UUID:
    return UUID(f"00000000-0000-0000-0000-{sufixo:012d}")


class _Result:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    async def fetchall(self) -> list[dict[str, Any]]:
        return self._rows


# =============================================================================
# Pix
# =============================================================================


def _pix(nome: str, minutos: int, sufixo: int) -> dict[str, Any]:
    return {
        "id": _id(sufixo),
        "decisao_pipeline": "em_revisao",
        "decisao_final": None,
        "motivo_em_revisao": "valor_divergente",
        "valor_extraido": None,
        "created_at": BASE + timedelta(minutes=minutos),
        "cliente_id": _id(900 + sufixo),
        "cliente_nome": nome,
        "cliente_telefone": "5521999000000",
        "modelo_id": _id(800),
        "modelo_nome": "Modelo",
        "atendimento_id": _id(700 + sufixo),
        "numero_curto": 1000 + sufixo,
        "atendimento_estado": "Em_execucao",
    }


# Três comprovantes no MESMO created_at: é a rajada de um reenvio, o caso que sumia.
PIX_DATASET = [
    _pix("Ana", 0, 1),
    _pix("Bia", 10, 2),
    _pix("Cris", 10, 3),
    _pix("Dani", 10, 4),
    _pix("Eva", 20, 5),
]
PIX_ORDEM = ["Ana", "Bia", "Cris", "Dani", "Eva"]


class FakeConnPix:
    """ORDER BY (created_at, id) ASC + keyset — o caminho de `status='pendentes'`."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    async def execute(self, query: str, params: list[Any] | None = None) -> _Result:
        params = list(params or [])
        limite = params[-1]
        rows = sorted(self._rows, key=lambda r: (r["created_at"], r["id"]))
        if "p.created_at = %s::timestamptz AND p.id > %s::uuid" in query:
            ts, _, ident = params[-4], params[-3], params[-2]
            chave = (datetime.fromisoformat(ts), UUID(ident))
            rows = [r for r in rows if (r["created_at"], r["id"]) > chave]
        elif "p.created_at > %s::timestamptz" in query:
            rows = [r for r in rows if r["created_at"] > datetime.fromisoformat(params[-2])]
        return _Result(rows[:limite])


async def test_pix_nao_perde_comprovante_do_mesmo_instante() -> None:
    conn = FakeConnPix(PIX_DATASET)
    vistos: list[str] = []
    cursor: str | None = None
    for _ in range(len(PIX_DATASET) + 1):
        pagina = await listar_pix(conn=conn, limit=2, cursor=cursor)  # type: ignore[arg-type]
        vistos.extend(item["cliente"]["nome"] for item in pagina["items"])
        cursor = pagina["next_cursor"]
        if cursor is None:
            break
    assert cursor is None
    assert vistos == PIX_ORDEM


async def test_pix_aceita_cursor_legado_so_com_timestamp() -> None:
    conn = FakeConnPix(PIX_DATASET)
    pagina = await listar_pix(  # type: ignore[arg-type]
        conn=conn, limit=10, cursor=(BASE + timedelta(minutes=10)).isoformat()
    )
    assert [item["cliente"]["nome"] for item in pagina["items"]] == ["Eva"]


# =============================================================================
# Conversas ("recente")
# =============================================================================


def _conversa(nome: str, minutos: int | None, sufixo: int) -> dict[str, Any]:
    return {
        "id": _id(sufixo),
        "recorrente": False,
        "ultimo_motivo_perda": None,
        "ultima_mensagem_em": None if minutos is None else BASE + timedelta(minutes=minutos),
        "ultima_mensagem_direcao": None,
        "created_at": BASE,
        "cliente_id": _id(900 + sufixo),
        "cliente_nome": nome,
        "cliente_telefone": "5521999000000",
        "modelo_id": _id(800),
        "modelo_nome": "Modelo",
        "ult_id": None,
        "ult_numero_curto": None,
        "ult_estado": None,
        "ult_created_at": None,
        "ult_valor_final": None,
        "ult_motivo_perda": None,
        "tem_atendimento_aberto": False,
        "ultimo_fechamento_em": None,
    }


# Duas conversas empatadas no mesmo instante e duas SEM mensagem (a faixa NULL, que vem por
# último e onde a paginação parava cedo).
CONVERSAS_DATASET = [
    _conversa("Ana", 30, 1),
    _conversa("Bia", 20, 2),
    _conversa("Cris", 20, 3),
    _conversa("Dani", 10, 4),
    _conversa("Eva", None, 5),
    _conversa("Fran", None, 6),
]
CONVERSAS_ORDEM = ["Ana", "Cris", "Bia", "Dani", "Fran", "Eva"]


class FakeConnConversas:
    """ORDER BY (ultima_mensagem_em DESC NULLS LAST, id DESC) + keyset."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    async def execute(self, query: str, params: list[Any] | None = None) -> _Result:
        params = list(params or [])
        limite = params[-1]
        # NULLS LAST em DESC: os sem-mensagem ficam depois de todos os datados.
        rows = sorted(
            self._rows,
            key=lambda r: (
                r["ultima_mensagem_em"] is not None,
                r["ultima_mensagem_em"] or BASE,
                r["id"],
            ),
            reverse=True,
        )
        if "cv.ultima_mensagem_em = %s::timestamptz AND cv.id < %s::uuid" in query:
            ts, ident = datetime.fromisoformat(params[-4]), UUID(params[-2])
            rows = [
                r
                for r in rows
                if r["ultima_mensagem_em"] is None
                or r["ultima_mensagem_em"] < ts
                or (r["ultima_mensagem_em"] == ts and r["id"] < ident)
            ]
        elif "cv.ultima_mensagem_em IS NULL AND cv.id < %s::uuid" in query:
            ident = UUID(params[-2])
            rows = [r for r in rows if r["ultima_mensagem_em"] is None and r["id"] < ident]
        elif "cv.ultima_mensagem_em < %s::timestamptz" in query:
            ts = datetime.fromisoformat(params[-2])
            rows = [
                r
                for r in rows
                if r["ultima_mensagem_em"] is not None and r["ultima_mensagem_em"] < ts
            ]
        return _Result(rows[:limite])


async def test_conversas_recente_atravessa_empate_e_faixa_sem_mensagem() -> None:
    conn = FakeConnConversas(CONVERSAS_DATASET)
    vistos: list[str] = []
    cursor: str | None = None
    for _ in range(len(CONVERSAS_DATASET) + 1):
        pagina = await listar_conversas(conn=conn, limit=2, cursor=cursor)  # type: ignore[arg-type]
        vistos.extend(item["cliente"]["nome"] for item in pagina["items"])
        cursor = pagina["next_cursor"]
        if cursor is None:
            break
    assert cursor is None
    assert vistos == CONVERSAS_ORDEM


async def test_conversas_cursor_legado_so_com_timestamp_continua_valendo() -> None:
    conn = FakeConnConversas(CONVERSAS_DATASET)
    pagina = await listar_conversas(  # type: ignore[arg-type]
        conn=conn, limit=10, cursor=(BASE + timedelta(minutes=20)).isoformat()
    )
    assert [item["cliente"]["nome"] for item in pagina["items"]] == ["Dani"]
