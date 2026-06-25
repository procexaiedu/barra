"""Aceite — build_system_messages monta BP_GERAL fundido (+ BP_MODELO opcional) como
SystemMessages de string pura (formato que roda em prod sob DeepSeek, cache automático).
"""

from barra.agente.llm import build_system_messages

GERAL = "<persona>voz geral + faq fundidos pelo caller</persona>"


def test_geral_unico_string_pura() -> None:
    # BP_GERAL fundido: 1 SystemMessage de string pura. BP_MODELO só quando modelo_md é passado.
    msgs = build_system_messages(geral_md=GERAL)
    assert len(msgs) == 1
    assert msgs[0].content == GERAL


def test_byte_identico_para_mesma_entrada() -> None:
    a = build_system_messages(geral_md=GERAL)
    b = build_system_messages(geral_md=GERAL)
    assert [m.content for m in a] == [m.content for m in b]


def test_sem_modelo_md_emite_so_1_bloco() -> None:
    # Sem modelo_md (default None) → so BP_GERAL (1 system block).
    msgs = build_system_messages(geral_md=GERAL)
    assert len(msgs) == 1


def test_bp_modelo_emitido_quando_modelo_md() -> None:
    # Com modelo_md → 2º bloco BP_MODELO por-modelo (string pura). Ordem estável: geral antes.
    modelo = "<modelo>identidade</modelo>"
    msgs = build_system_messages(geral_md=GERAL, modelo_md=modelo)
    assert len(msgs) == 2
    assert msgs[0].content == GERAL  # BP_GERAL inalterado pelo BP_MODELO
    assert msgs[1].content == modelo  # string pura, sem content blocks
