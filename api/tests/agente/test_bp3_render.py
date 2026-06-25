"""Aceite M2-T1 — BP3 por-modelo (identidade + programas) renderizado e cacheado.

DB-free e key-free: monta `IdentidadeModelo` à mão + programas mock e exercita
`render_identidade`/`render_programas`/`render_bp3`/`build_system_messages`. O carregamento
das queries do `prepare_context` é coberto em `test_contexto_dinamico.py` (needs_db).

Guard-rail #1 (agente/CLAUDE.md): BP_GERAL sai byte-idêntico entre 2 modelos distintas; só o
BP_MODELO difere. Vazar dado por-modelo no BP_GERAL derruba o cache de TODAS.
"""

from typing import Any

from barra.agente.llm import build_system_messages
from barra.agente.persona import (
    IdentidadeModelo,
    render_bp3,
    render_fetiches,
    render_identidade,
    render_programas,
)

GERAL = "<persona>voz geral</persona>"

CARIOCA = IdentidadeModelo(
    nome="Bia",
    idade=26,
    idiomas=["pt-BR"],
    localizacao_operacional="Barra da Tijuca",
    tipos_aceitos=["interno", "externo"],
    endereco_formatado="Av. das Américas, 500 - Barra da Tijuca, Rio de Janeiro - RJ",
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

# preco None = incluso; preenchido = extra pago.
FETICHES: list[dict[str, Any]] = [
    {"nome": "Beijo na boca", "preco": None},
    {"nome": "Inversão", "preco": 200},
]


def test_identidade_inclui_nome_e_idade() -> None:
    txt = render_identidade(CARIOCA)
    assert "Bia" in txt
    assert "26" in txt


def test_endereco_formatado_exposto_como_ponto_de_encontro() -> None:
    # ADR 0020: no pickup a IA precisa passar o endereço de atendimento (ponto de encontro).
    # Endereço presente → renderiza; ausente (ESTRANGEIRA) → linha some, sem "None" vazado.
    txt = render_identidade(CARIOCA)
    assert "Av. das Américas, 500 - Barra da Tijuca, Rio de Janeiro - RJ" in txt
    assert "ponto de encontro" in txt
    sem_endereco = render_identidade(ESTRANGEIRA)
    assert "ponto de encontro" not in sem_endereco
    assert "None" not in sem_endereco


def test_programas_tabela_uma_linha_por_combinacao() -> None:
    # gotcha do for-loop grudado (M1-T2): cada combinação em SUA PRÓPRIA linha de tabela.
    txt = render_programas(PROGRAMAS)
    linhas_dados = [ln for ln in txt.splitlines() if ln.startswith("| ") and "R$" in ln]
    assert len(linhas_dados) == 3
    assert "Programa Completo" in txt
    assert "1 hora" in txt
    # filtro `brl` (persona.py): persona exige R$1.500 (sem espaço, ponto como separador).
    assert "R$2.500" in txt


def test_fetiches_lista_extra_e_incluso() -> None:
    txt = render_fetiches(FETICHES)
    assert "Beijo na boca" in txt
    assert "incluso" in txt  # preco None
    assert "Inversão" in txt
    assert "+R$200" in txt  # preco preenchido, filtro brl


def test_render_bp3_concatena_identidade_programas_e_fetiches() -> None:
    bp3 = render_bp3(CARIOCA, PROGRAMAS, FETICHES)
    assert "Bia" in bp3
    assert "<programas>" in bp3
    assert "Programa Completo" in bp3
    assert "<fetiches>" in bp3
    assert "Inversão" in bp3


def test_build_system_messages_emite_2_blocos() -> None:
    # BP_GERAL: 2 blocos system (geral + por-modelo), strings puras.
    msgs = build_system_messages(
        geral_md=GERAL,
        modelo_md=render_bp3(CARIOCA, PROGRAMAS, FETICHES),
    )
    assert len(msgs) == 2
    modelo_texto = msgs[1].content
    assert isinstance(modelo_texto, str)  # string pura (formato DeepSeek), não content-blocks
    assert "Bia" in modelo_texto
    assert "26" in modelo_texto
    assert "Programa Completo" in modelo_texto


def test_guardrail_bp_geral_byte_identico_entre_modelos_string_pura() -> None:
    # Guard-rail #1 no formato que RODA em prod (string pura, DeepSeek): o cache automático do
    # DeepSeek só dá hit se o BP_GERAL sair byte-idêntico entre modelos. Pega regressão se alguém
    # interpolar dado por-modelo no prefixo geral.
    a = build_system_messages(
        geral_md=GERAL,
        modelo_md=render_bp3(CARIOCA, PROGRAMAS, FETICHES),
    )
    b = build_system_messages(
        geral_md=GERAL,
        modelo_md=render_bp3(ESTRANGEIRA, [], []),
    )
    assert isinstance(a[0].content, str)  # string pura (formato DeepSeek), não content-blocks
    assert a[0].content == b[0].content  # BP_GERAL byte-idêntico entre modelos
    assert a[1].content != b[1].content  # BP_MODELO difere por-modelo
