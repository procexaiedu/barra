"""Aceite M2-T1 — BP3 por-modelo (identidade + programas) renderizado e cacheado.

DB-free e key-free: monta `IdentidadeModelo` à mão + programas mock e exercita
`render_identidade`/`render_programas`/`render_bp3`/`build_system_messages`. O carregamento
das queries do `prepare_context` é coberto em `test_contexto_dinamico.py` (needs_db).

Guard-rail #1 (agente/CLAUDE.md): BP1+BP2 e o bloco `tools` saem byte-idênticos entre 2
modelos distintas; só o BP3 difere. Vazar dado por-modelo em BP1/BP2 derruba o cache de TODAS.
"""

from typing import Any

from barra.agente.llm import build_system_messages
from barra.agente.persona import (
    IdentidadeModelo,
    render_bp3,
    render_identidade,
    render_programas,
)

GERAL = "<persona>voz geral</persona>"
FAQ = "# faq\nconteudo geral"

CARIOCA = IdentidadeModelo(
    nome="Bia",
    idade=26,
    idiomas=["pt-BR"],
    localizacao_operacional="Barra da Tijuca",
    tipos_aceitos=["interno", "externo"],
)

ESTRANGEIRA = IdentidadeModelo(
    nome="Ivanka",
    idade=29,
    idiomas=["pt-BR", "en-US"],
    localizacao_operacional=None,
    tipos_aceitos=["externo"],
)

PROGRAMAS: list[dict[str, Any]] = [
    {"nome": "Massagem Relaxante", "duracao_nome": "1 hora", "preco": 800},
    {"nome": "Massagem Relaxante", "duracao_nome": "2 horas", "preco": 1500},
    {"nome": "Programa Completo", "duracao_nome": "2 horas", "preco": 2500},
]


def test_identidade_inclui_nome_e_idade() -> None:
    txt = render_identidade(CARIOCA)
    assert "Bia" in txt
    assert "26" in txt


def test_carioca_nativa_nao_finge_sotaque() -> None:
    # idiomas == ["pt-BR"] → sem aura internacional / sotaque / desconhecimento de bairros.
    txt = render_identidade(CARIOCA)
    assert "sotaque" not in txt
    assert "internacional" not in txt
    # localizacao operacional presente aparece.
    assert "Barra da Tijuca" in txt


def test_estrangeira_menciona_aura_e_sotaque() -> None:
    # idiomas != ["pt-BR"] → aura internacional + sotaque (03 §2.1).
    txt = render_identidade(ESTRANGEIRA)
    assert "sotaque" in txt
    assert "internacional" in txt
    assert "en-US" in txt


def test_atendimento_reflete_tipos_aceitos() -> None:
    ambos = render_identidade(CARIOCA)  # interno + externo
    assert "dois jeitos" in ambos
    so_externo = render_identidade(ESTRANGEIRA)  # só externo
    assert "indo até o cliente" in so_externo
    assert "dois jeitos" not in so_externo


def test_programas_tabela_uma_linha_por_combinacao() -> None:
    # gotcha do for-loop grudado (M1-T2): cada combinação em SUA PRÓPRIA linha de tabela.
    txt = render_programas(PROGRAMAS)
    linhas_dados = [ln for ln in txt.splitlines() if ln.startswith("| ") and "R$" in ln]
    assert len(linhas_dados) == 3
    assert "Programa Completo" in txt
    assert "1 hora" in txt
    assert "R$ 2,500" in txt  # "{:,.0f}" — separador de milhar (03 §3.3)


def test_programas_vazio_orienta_escalar() -> None:
    txt = render_programas([])
    assert "ainda não tem programas" in txt
    # a linha do Pix fixo aparece nos dois ramos.
    assert "R$ 100 fixo" in txt


def test_render_bp3_concatena_identidade_e_programas() -> None:
    bp3 = render_bp3(CARIOCA, PROGRAMAS)
    assert "Bia" in bp3
    assert "# Programas e valores" in bp3
    assert "Programa Completo" in bp3


def test_build_system_messages_emite_3_blocos() -> None:
    msgs = build_system_messages(
        geral_md=GERAL,
        faq_md=FAQ,
        ttl_geral="1h",
        modelo_md=render_bp3(CARIOCA, PROGRAMAS),
        ttl_modelo="1h",
    )
    assert len(msgs) == 3
    bp3_texto = msgs[2].content[0]["text"]  # type: ignore[index]
    assert "Bia" in bp3_texto
    assert "26" in bp3_texto
    assert "Programa Completo" in bp3_texto


def test_guardrail_bp1_bp2_byte_identico_entre_modelos() -> None:
    # Guard-rail #1: BP1+BP2 byte-idênticos p/ 2 modelos distintas; só o BP3 difere.
    a = build_system_messages(
        geral_md=GERAL,
        faq_md=FAQ,
        ttl_geral="1h",
        modelo_md=render_bp3(CARIOCA, PROGRAMAS),
        ttl_modelo="1h",
    )
    b = build_system_messages(
        geral_md=GERAL,
        faq_md=FAQ,
        ttl_geral="1h",
        modelo_md=render_bp3(ESTRANGEIRA, []),
        ttl_modelo="1h",
    )
    assert a[0].content == b[0].content  # BP1 idêntico
    assert a[1].content == b[1].content  # BP2 idêntico
    assert a[2].content != b[2].content  # BP3 difere por-modelo
