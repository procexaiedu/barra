"""Aceite — build_system_messages monta BP_GERAL fundido (+ BP_MODELO opcional) com
cache_control em content blocks. Tambem cobre `build_tools_para_bind` (BP_TOOLS) e
`marcar_cache_na_penultima` (BP_JANELA).
"""

import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool
from pydantic import BaseModel, ConfigDict, Field

from barra.agente.llm import (
    _bloco_texto,
    build_system_messages,
    build_tools_para_bind,
    marcar_cache_na_penultima,
)

GERAL = "<persona>voz geral + faq fundidos pelo caller</persona>"


def test_geral_unico_com_cache_control_1h() -> None:
    # BP_GERAL fundido: 1 SystemMessage so (antes eram 2 separados — fusao libera 1 breakpoint
    # p/ o BP_JANELA). BP_MODELO so quando modelo_md e passado.
    msgs = build_system_messages(geral_md=GERAL, ttl_geral="1h")
    assert len(msgs) == 1
    assert msgs[0].content == [
        {
            "type": "text",
            "text": GERAL,
            "cache_control": {"type": "ephemeral", "ttl": "1h"},
        }
    ]


def test_byte_identico_para_mesma_entrada() -> None:
    a = build_system_messages(geral_md=GERAL, ttl_geral="1h")
    b = build_system_messages(geral_md=GERAL, ttl_geral="1h")
    assert [m.content for m in a] == [m.content for m in b]


def test_bloco_texto_5m_sem_campo_ttl() -> None:
    # "5m" é o default ephemeral → cache_control sem campo ttl (§5).
    assert _bloco_texto("x", "5m") == {
        "type": "text",
        "text": "x",
        "cache_control": {"type": "ephemeral"},
    }


def test_bloco_texto_none_sem_cache_control() -> None:
    assert _bloco_texto("x", None) == {"type": "text", "text": "x"}


def test_sem_modelo_md_emite_so_1_bloco() -> None:
    # Sem modelo_md (default None) → so BP_GERAL (1 system block).
    msgs = build_system_messages(geral_md=GERAL, ttl_geral="1h")
    assert len(msgs) == 1


def test_bp_modelo_emitido_quando_modelo_md() -> None:
    # Com modelo_md → 2º bloco BP_MODELO por-modelo, com cache_control de ttl_modelo.
    modelo = "<modelo>identidade</modelo>"
    msgs = build_system_messages(
        geral_md=GERAL,
        ttl_geral="1h",
        modelo_md=modelo,
        ttl_modelo="1h",
    )
    assert len(msgs) == 2
    assert msgs[1].content == [
        {"type": "text", "text": modelo, "cache_control": {"type": "ephemeral", "ttl": "1h"}}
    ]
    # BP_GERAL inalterado pelo BP_MODELO (prefixo geral intacto).
    assert msgs[0].content == [
        {"type": "text", "text": GERAL, "cache_control": {"type": "ephemeral", "ttl": "1h"}}
    ]


def test_ttl_geral_mais_curto_que_modelo_viola_ordenacao() -> None:
    # geral=5m antes de modelo=1h → 400 na Anthropic; a guarda rejeita antes de montar.
    with pytest.raises(ValueError):
        build_system_messages(
            geral_md=GERAL,
            ttl_geral="5m",
            modelo_md="<i>",
            ttl_modelo="1h",
        )


# ----- marcar_cache_na_penultima (BP_JANELA) -------------------------------------------------


def _janela_alternada(n: int) -> list:
    """Janela alternada cliente/IA com `n` HumanMessages no total. Termina sempre num
    HumanMessage (a msg atual)."""
    msgs: list = []
    for i in range(n):
        msgs.append(HumanMessage(content=f"cli {i}", id=f"h{i}"))
        if i < n - 1:
            msgs.append(AIMessage(content=f"ia {i}", id=f"a{i}"))
    return msgs


def test_marcar_cache_janela_vazia_no_op() -> None:
    assert marcar_cache_na_penultima([], ttl="1h") == []


def test_marcar_cache_janela_uma_msg_no_op() -> None:
    # Sem penultima — janela curta (cliente novo) nao tem o que cachear.
    janela = [HumanMessage(content="oi", id="h0")]
    assert marcar_cache_na_penultima(janela, ttl="1h") == janela


def test_marcar_cache_aplica_na_penultima_2_msgs() -> None:
    # 2 msgs: penultima = primeira; ultima preserva content original (volatil).
    janela = [HumanMessage(content="oi", id="h0"), AIMessage(content="ola", id="a0")]
    out = marcar_cache_na_penultima(janela, ttl="1h")
    assert out[0].content == [
        {"type": "text", "text": "oi", "cache_control": {"type": "ephemeral", "ttl": "1h"}}
    ]
    assert out[1].content == "ola"  # ultima intacta
    assert out[0].id == "h0"  # id preservado p/ idempotencia downstream


def test_marcar_cache_preserva_tipo_da_mensagem() -> None:
    # Penultima pode ser AIMessage (turno acabou com ai→user): cache vai nela igual.
    janela = [
        HumanMessage(content="x", id="h0"),
        AIMessage(content="y", id="a0"),
        HumanMessage(content="z", id="h1"),
    ]
    out = marcar_cache_na_penultima(janela, ttl="1h")
    assert isinstance(out[1], AIMessage)
    assert out[1].content[0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}  # type: ignore[index]


def test_marcar_cache_janela_cheia_so_a_penultima() -> None:
    # Janela tipica (20 msgs): so a penultima recebe cache_control; resto intacto.
    janela = _janela_alternada(10)  # 10 humans + 9 ais = 19 msgs
    out = marcar_cache_na_penultima(janela, ttl="1h")
    for i, m in enumerate(out):
        if i == len(out) - 2:
            assert isinstance(m.content, list)
            assert m.content[0]["cache_control"]["type"] == "ephemeral"
        else:
            assert isinstance(m.content, str)


def test_marcar_cache_5m_omite_campo_ttl() -> None:
    janela = [HumanMessage(content="x", id="h0"), AIMessage(content="y", id="a0")]
    out = marcar_cache_na_penultima(janela, ttl="5m")
    assert out[0].content[0]["cache_control"] == {"type": "ephemeral"}  # type: ignore[index]


def test_marcar_cache_idempotente_em_content_blocks() -> None:
    # Defesa: se chamado 2x, a 2a chamada nao redobra o cache_control nem perde estrutura.
    janela = [HumanMessage(content="x", id="h0"), AIMessage(content="y", id="a0")]
    uma_vez = marcar_cache_na_penultima(janela, ttl="1h")
    duas_vezes = marcar_cache_na_penultima(uma_vez, ttl="1h")
    assert uma_vez == duas_vezes


# ----- build_tools_para_bind -----------------------------------------------------------------
#
# Fixtures locais (3 tools fakes) p/ nao acoplar o teste do helper ao catalogo real de TOOLS.
# Catalogo de produção tem invariantes proprias (ordem congelada, schemas strict, etc.) e roda
# em outros gates; aqui validamos APENAS a forma do output do helper.


class _PayloadA(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x: str = Field(min_length=1)


class _PayloadB(BaseModel):
    model_config = ConfigDict(extra="forbid")
    y: int


@tool
def _tool_a(payload: _PayloadA) -> str:
    """Primeira tool fake (leitura)."""
    return payload.x


@tool
def _tool_b(payload: _PayloadB) -> str:
    """Tool intermediaria."""
    return str(payload.y)


@tool
def _tool_c(payload: _PayloadA) -> str:
    """Ultima tool fake — recebe o cache_control no helper."""
    return payload.x


def test_tools_vazias_devolve_lista_vazia() -> None:
    assert build_tools_para_bind([], ttl="1h") == []


def test_so_a_ultima_tool_recebe_cache_control() -> None:
    out = build_tools_para_bind([_tool_a, _tool_b, _tool_c], ttl="1h")
    assert len(out) == 3
    # Todas exceto a ultima sem cache_control (doc oficial: "Place ... on the last tool").
    assert "cache_control" not in out[0]
    assert "cache_control" not in out[1]
    assert out[2]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}


def test_ttl_5m_omite_campo_ttl_no_cache_control() -> None:
    # "5m" = default ephemeral → cache_control sem o campo ttl (espelha _bloco_texto).
    out = build_tools_para_bind([_tool_a, _tool_c], ttl="5m")
    assert out[-1]["cache_control"] == {"type": "ephemeral"}


def test_tool_unica_recebe_cache_control() -> None:
    # 1 tool → ela mesma é a "ultima"; precisa receber o cache_control p/ o segmento existir.
    out = build_tools_para_bind([_tool_a], ttl="1h")
    assert len(out) == 1
    assert out[0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}


def test_helper_e_deterministico() -> None:
    # Pre-req do cache: bytes estaveis entre invocacoes (agente/CLAUDE.md "Guard-rails").
    a = build_tools_para_bind([_tool_a, _tool_b, _tool_c], ttl="1h")
    b = build_tools_para_bind([_tool_a, _tool_b, _tool_c], ttl="1h")
    assert json.dumps(a, sort_keys=False) == json.dumps(b, sort_keys=False)


def test_forma_canonica_da_tool_convertida() -> None:
    # Sanity: dict tem as chaves que a Anthropic espera no tool object (nao input_schema).
    out = build_tools_para_bind([_tool_a], ttl="1h")
    tool_obj = out[0]
    assert "name" in tool_obj
    assert "input_schema" in tool_obj
    # cache_control vive no TOPO do tool object, nao dentro de input_schema.
    assert "cache_control" not in tool_obj.get("input_schema", {})
    assert tool_obj["cache_control"]["type"] == "ephemeral"


def test_strict_mode_opt_in_quando_strict_true() -> None:
    # strict=True (opt-in, default False) ativa constrained decoding nas tools.
    out = build_tools_para_bind([_tool_a, _tool_b, _tool_c], ttl="1h", strict=True)
    assert all(t.get("strict") is True for t in out), "todas as tools devem ter strict=True"


def test_strict_mode_default_off_no_helper() -> None:
    # Helper default `strict=False` (parametro). O `anthropic_strict_tools=True` do settings
    # vive no caller (`nos/llm.py:no_llm`). Aqui testamos a forma do helper isoladamente.
    out = build_tools_para_bind([_tool_a, _tool_b, _tool_c], ttl="1h")
    assert all("strict" not in t for t in out), "strict ausente quando helper recebe default"


def test_strict_requer_additional_properties_false_no_top_level() -> None:
    # Pre-req do strict mode (doc oficial `strict-tool-use`): additionalProperties:false no
    # TOP-LEVEL do input_schema. langchain envolve `payload: PydModel` em `{"payload": <schema>}`
    # e nao propaga o flag — o helper injeta no top-level p/ a Anthropic nao recusar com 400.
    out = build_tools_para_bind([_tool_a, _tool_b, _tool_c], ttl="1h", strict=True)
    for t in out:
        schema = t.get("input_schema", {})
        assert schema.get("additionalProperties") is False, (
            f"{t['name']}: additionalProperties top-level deve ser False"
        )
        # Pydantic com extra='forbid' tambem garante isso no nivel `payload` (defesa em camadas).
        payload_schema = schema.get("properties", {}).get("payload", {})
        assert payload_schema.get("additionalProperties") is False, (
            f"{t['name']}: payload schema deve ter additionalProperties:false (extra='forbid')"
        )
