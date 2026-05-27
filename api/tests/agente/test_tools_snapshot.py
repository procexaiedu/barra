"""Snapshot do JSON canonico das tools — defesa contra drift silencioso.

`convert_to_anthropic_tool` (langchain-anthropic) ou o `model_json_schema()` do Pydantic podem
mudar a SHAPE do dict entre versoes minor sem nota — o cache de tools quebra em silencio
(write 100% em vez de read >90%). Este snapshot trava o JSON byte-a-byte; qualquer mudanca
(intencional ou nao) precisa passar por uma atualizacao explicita do .json.

Atualizar o snapshot intencionalmente:
    TOOLS_SNAPSHOT_UPDATE=1 uv run pytest tests/agente/test_tools_snapshot.py

Sem essa env var, o teste FALHA se houver divergencia — protege contra `uv sync` que sobe
langchain-anthropic e muda a shape sem deploy.
"""

import json
import os
from pathlib import Path

import pytest

from barra.agente.ferramentas import TOOLS
from barra.agente.llm import build_tools_para_bind

_SNAPSHOT = Path(__file__).parent / "snapshots" / "tools.json"


def _render_atual() -> str:
    """JSON canonico do array de tools com cache_control de 1h. `strict=False` reflete o default
    em prod — strict global ainda barrado por "Schema is too complex" mesmo com `SinaisQualificacao`
    fechado + `_desencapsular_anyof_null`. TTL fixo p/ determinismo."""
    out = build_tools_para_bind(TOOLS, ttl="1h", strict=False)
    # `sort_keys=True` p/ ordem alfabetica em TODOS os niveis (anula variacao do dict de
    # entrada — pydantic ja preserva ordem de fields mas o resto nao). `ensure_ascii=False`
    # mantem acentos legíveis no .json.
    return json.dumps(out, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def test_snapshot_existe() -> None:
    assert _SNAPSHOT.exists(), (
        f"snapshot ausente em {_SNAPSHOT}. Gere com TOOLS_SNAPSHOT_UPDATE=1 pytest ..."
    )


def test_tools_batem_com_snapshot() -> None:
    atual = _render_atual()
    if os.environ.get("TOOLS_SNAPSHOT_UPDATE") == "1":
        _SNAPSHOT.write_text(atual, encoding="utf-8")
        pytest.skip("snapshot regenerado (TOOLS_SNAPSHOT_UPDATE=1)")
    salvo = _SNAPSHOT.read_text(encoding="utf-8")
    assert atual == salvo, (
        "Tools mudaram (langchain-anthropic upgrade? schema Pydantic? tool nova?). "
        "Se intencional, regere: TOOLS_SNAPSHOT_UPDATE=1 uv run pytest "
        "tests/agente/test_tools_snapshot.py"
    )


def test_snapshot_contem_cache_control_na_ultima_tool() -> None:
    # Sanity adicional: alem do byte-equal, garante que a estrutura DO SNAPSHOT mantem o
    # invariante (cache_control so na ultima). Se alguem regerar com TOOLS=[], o teste pega.
    salvo = json.loads(_SNAPSHOT.read_text(encoding="utf-8"))
    assert isinstance(salvo, list) and len(salvo) >= 1
    for t in salvo[:-1]:
        assert "cache_control" not in t, f"cache_control vazou em tool nao-ultima: {t['name']}"
    assert salvo[-1].get("cache_control", {}).get("type") == "ephemeral"


def test_snapshot_strict_off_por_default() -> None:
    # Strict mode hoje e opt-in (settings.anthropic_strict_tools, default False) — strict global
    # ainda barrado pelo limite "Schema is too complex" da Anthropic. Quando descricoes/enums
    # forem encurtados (ou Anthropic relaxar), regerar o snapshot com strict on.
    salvo = json.loads(_SNAPSHOT.read_text(encoding="utf-8"))
    assert all("strict" not in t for t in salvo), "strict deve estar ausente (default off)"


def test_snapshot_sinais_qualificacao_e_schema_fechado() -> None:
    # Post-refactor: `sinais_qualificacao` virou `SinaisQualificacao(BaseModel)` com 5 booleans
    # fixos. Snapshot trava a forma — se alguem voltar pra `dict[str, bool]`, o teste pega.
    salvo = json.loads(_SNAPSHOT.read_text(encoding="utf-8"))
    extracao = next(t for t in salvo if t["name"] == "registrar_extracao")
    sq = extracao["input_schema"]["properties"]["payload"]["properties"]["sinais_qualificacao"]
    # Pode aparecer como ref ou como schema inline. Resolve $ref se houver.
    if "$ref" in sq:
        ref_name = sq["$ref"].rsplit("/", 1)[-1]
        sq = extracao["input_schema"]["properties"]["payload"]["$defs"][ref_name]
    props = sq.get("properties", {})
    esperado = {"informa_horario", "informa_local", "aceita_valor", "envia_pix", "responde_objetivamente"}
    assert set(props.keys()) == esperado, f"campos do SinaisQualificacao mudaram: {set(props.keys())}"
    assert sq.get("additionalProperties") is False, "SinaisQualificacao deve ser schema fechado"
