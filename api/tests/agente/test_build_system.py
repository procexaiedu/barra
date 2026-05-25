"""Aceite M0-T3 — build_system_messages monta BP1+BP2 com cache_control em content blocks."""

import pytest

from barra.agente.llm import _bloco_texto, build_system_messages

GERAL = "<persona>voz geral</persona>"
FAQ = "# faq\nconteudo geral"


def test_duas_mensagens_com_cache_control_1h() -> None:
    msgs = build_system_messages(geral_md=GERAL, faq_md=FAQ, ttl_geral="1h")
    assert len(msgs) == 2  # BP1 + BP2; BP3 só no M2
    for msg, esperado in zip(msgs, (GERAL, FAQ), strict=True):
        assert msg.content == [
            {
                "type": "text",
                "text": esperado,
                "cache_control": {"type": "ephemeral", "ttl": "1h"},
            }
        ]


def test_byte_identico_para_mesma_entrada() -> None:
    a = build_system_messages(geral_md=GERAL, faq_md=FAQ, ttl_geral="1h")
    b = build_system_messages(geral_md=GERAL, faq_md=FAQ, ttl_geral="1h")
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


def test_sem_modelo_md_emite_so_2_blocos() -> None:
    # sem modelo_md (default None) → só BP1+BP2 (prefixo geral).
    msgs = build_system_messages(geral_md=GERAL, faq_md=FAQ, ttl_geral="1h")
    assert len(msgs) == 2


def test_bp3_emitido_quando_modelo_md() -> None:
    # com modelo_md → 3º bloco BP3 por-modelo, com cache_control de ttl_modelo (M2-T1).
    modelo = "<modelo>identidade</modelo>"
    msgs = build_system_messages(
        geral_md=GERAL,
        faq_md=FAQ,
        ttl_geral="1h",
        modelo_md=modelo,
        ttl_modelo="1h",
    )
    assert len(msgs) == 3
    assert msgs[2].content == [
        {"type": "text", "text": modelo, "cache_control": {"type": "ephemeral", "ttl": "1h"}}
    ]
    # BP1+BP2 inalterados pelo BP3 (prefixo geral intacto).
    assert msgs[0].content == [
        {"type": "text", "text": GERAL, "cache_control": {"type": "ephemeral", "ttl": "1h"}}
    ]


def test_ttl_geral_mais_curto_que_modelo_viola_ordenacao() -> None:
    # geral=5m antes de modelo=1h → 400 na Anthropic; a guarda rejeita antes de montar.
    with pytest.raises(ValueError):
        build_system_messages(
            geral_md=GERAL,
            faq_md=FAQ,
            ttl_geral="5m",
            modelo_md="<i>",
            ttl_modelo="1h",
        )
