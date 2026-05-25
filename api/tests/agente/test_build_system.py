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


def test_bp3_reservado_nao_emitido_no_m0() -> None:
    # modelo_md/ttl_modelo são reservados; o 3º bloco entra no M2, não agora.
    msgs = build_system_messages(
        geral_md=GERAL,
        faq_md=FAQ,
        ttl_geral="1h",
        modelo_md="<identidade>nome</identidade>",
        ttl_modelo="1h",
    )
    assert len(msgs) == 2


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
