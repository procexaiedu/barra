"""Nucleo PURO da rotulagem de calibracao: expansao .jsonl->falas e reconstrucao do golden.

Sem DB/LLM/rede -> roda no `make test`. Prova que `falas_de`/`montar_golden` produzem o shape
EXATO que `evals/calibracao/calibrar.py` consome (igual ao HTML legado evals-notas.html).
"""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from barra.api.deps import get_conn
from barra.calibracao.export import RotuloFala, montar_golden
from barra.calibracao.falas import falas_de, parse_jsonl
from barra.calibracao.service import resolver_rotulador
from barra.core.errors import ErroDominio
from barra.main import app

CONV = {
    "conversa_id": "c1",
    "cenario": "cen1",
    "turnos": [
        {"papel": "cliente", "texto": "oi"},
        {"papel": "ia", "texto": "oi amor", "idx": 0},
        {"papel": "cliente", "texto": "faz X?"},
        {"papel": "ia", "texto": "nao faço", "idx": 1},
        {"papel": "ato", "ato": "enviar_pix_valido"},
        {"papel": "ia", "texto": "recebi", "idx": 2},
    ],
}


def test_parse_jsonl_pula_header_vazias_e_malformadas():
    texto = (
        '{"_header": "template"}\n'
        "\n"
        '{"conversa_id": "c1", "cenario": "x", "turnos": []}\n'
        '{"falta": "conversa_id"}\n'
        '{"conversa_id": "c2", "turnos": "nao-eh-lista"}\n'
    )
    conversas = parse_jsonl(texto)
    assert [c["conversa_id"] for c in conversas] == ["c1"]


def test_falas_de_extrai_so_ia_com_fala_id_e_historico():
    falas = falas_de([CONV])
    assert [f.fala_id for f in falas] == ["c1::0", "c1::1", "c1::2"]
    assert [f.ordem for f in falas] == [0, 1, 2]

    f0, f1, f2 = falas
    assert f0.texto_resposta == "oi amor"
    assert f0.historico == ["cliente: oi"]
    # historico acumula turnos ANTES da fala, na ordem do array
    assert f1.historico == ["cliente: oi", "ia: oi amor", "cliente: faz X?"]
    # ato vira rotulo legivel entre colchetes (espelha ATO_LABEL/historicoAte do HTML)
    assert f2.historico == [
        "cliente: oi",
        "ia: oi amor",
        "cliente: faz X?",
        "ia: nao faço",
        "[💸 cliente enviou o comprovante de Pix (validado)]",
    ]


def test_falas_de_enumera_idx_quando_campo_ausente():
    conv = {
        "conversa_id": "semidx",
        "turnos": [
            {"papel": "ia", "texto": "a"},
            {"papel": "cliente", "texto": "b"},
            {"papel": "ia", "texto": "c"},
        ],
    }
    falas = falas_de([conv])
    assert [f.fala_id for f in falas] == ["semidx::0", "semidx::1"]
    # cenario default = conversa_id quando ausente
    assert falas[0].cenario == "semidx"


def _falas_dict(conv):
    return [
        {
            "fala_id": f.fala_id,
            "conversa_id": f.conversa_id,
            "cenario": f.cenario,
            "texto_resposta": f.texto_resposta,
            "historico": f.historico,
        }
        for f in falas_de([conv])
    ]


def test_montar_golden_inner_join_so_ambos_com_aviso():
    falas = _falas_dict(CONV)
    rot_f = {"c1::0": RotuloFala(True), "c1::1": RotuloFala(False, "tom ruim")}
    rot_s = {"c1::0": RotuloFala(True)}

    golden, avisos = montar_golden(falas, rot_f, rot_s)

    # so c1::0 foi rotulada pelos DOIS
    assert len(golden) == 1
    linha = golden[0]
    assert linha["id"] == "c1::0"
    assert linha["rotulo_humano_fernando"] is True
    assert linha["rotulo_humano_socia"] is True
    # shape que calibrar.py:_ler_golden exige
    assert set(linha) >= {
        "id",
        "conversa_id",
        "cenario",
        "texto_resposta",
        "historico",
        "rotulo_humano_fernando",
        "rotulo_humano_socia",
    }
    # sem observacao -> chave ausente
    assert "observacao_fernando" not in linha
    # c1::1 (so fernando) descartada com aviso; c1::2 (ninguem) silenciosa
    assert len(avisos) == 1
    assert "c1::1" in avisos[0]


def test_montar_golden_inclui_observacao_nao_vazia():
    falas = _falas_dict(CONV)
    rot_f = {"c1::0": RotuloFala(True, "  boa  ")}
    rot_s = {"c1::0": RotuloFala(False, "")}

    golden, _ = montar_golden(falas, rot_f, rot_s)
    linha = golden[0]
    assert linha["observacao_fernando"] == "boa"  # strip aplicado
    assert "observacao_socia" not in linha  # vazia -> omitida


def _settings(fernando: str | None, socia: str | None):
    return SimpleNamespace(calibracao_email_fernando=fernando, calibracao_email_socia=socia)


def test_resolver_rotulador_mapeia_emails():
    st = _settings("fer@x.com", "soc@x.com")
    assert resolver_rotulador("fer@x.com", st) == "fernando"
    assert resolver_rotulador("SOC@x.com", st) == "socia"  # case-insensitive
    assert resolver_rotulador("  fer@x.com ", st) == "fernando"  # trim


def test_resolver_rotulador_email_desconhecido_403():
    st = _settings("fer@x.com", "soc@x.com")
    with pytest.raises(ErroDominio) as ei:
        resolver_rotulador("outro@x.com", st)
    assert ei.value.status_code == 403


def test_resolver_rotulador_sem_email_ou_config_nao_casa_vazio():
    # email vazio nao deve casar com config vazia (evita autorizar por string vazia)
    with pytest.raises(ErroDominio):
        resolver_rotulador(None, _settings(None, None))
    with pytest.raises(ErroDominio):
        resolver_rotulador("", _settings("", ""))


# --- Wiring HTTP (FakeConn, sem DB real) ---------------------------------------


class _Result:
    def __init__(self, rows: list[dict] | None = None) -> None:
        self.rows = rows or []

    async def fetchone(self) -> dict | None:
        return self.rows[0] if self.rows else None

    async def fetchall(self) -> list[dict]:
        return self.rows


def _token() -> dict[str, str]:
    return {"Authorization": f"Bearer test:{uuid4()}:fernando:true"}


def _override(conn: object):
    async def _gen():
        yield conn

    return _gen


def test_listar_rodadas_monta_rota_e_serializa() -> None:
    rid = uuid4()

    class _Conn:
        async def execute(self, query: str, params: object = None) -> _Result:
            return _Result(
                [{"id": rid, "nome": "r1", "created_at": datetime.now(UTC), "total_falas": 3}]
            )

    app.dependency_overrides[get_conn] = _override(_Conn())
    try:
        with TestClient(app) as client:
            r = client.get("/v1/calibracao/rodadas", headers=_token())
        assert r.status_code == 200
        rodada = r.json()["rodadas"][0]
        assert rodada["nome"] == "r1"
        assert rodada["total_falas"] == 3
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_falas_sem_rotulador_configurado_retorna_403() -> None:
    # ambiente de teste nao mapeia 'fernando@example.com' -> resolver_rotulador nega (independencia)
    class _Conn:
        async def execute(self, query: str, params: object = None) -> _Result:
            return _Result([])

    app.dependency_overrides[get_conn] = _override(_Conn())
    try:
        with TestClient(app) as client:
            r = client.get(f"/v1/calibracao/rodadas/{uuid4()}/falas", headers=_token())
        assert r.status_code == 403
    finally:
        app.dependency_overrides.pop(get_conn, None)
