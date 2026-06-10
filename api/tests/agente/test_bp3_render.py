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
    render_fetiches,
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
    endereco_formatado="Av. das Américas, 500 - Barra da Tijuca, Rio de Janeiro - RJ",
)

ESTRANGEIRA = IdentidadeModelo(
    nome="Ivanka",
    idade=29,
    idiomas=["pt-BR", "en-US"],
    localizacao_operacional=None,
    tipos_aceitos=["externo"],
)

PAULISTA = IdentidadeModelo(
    nome="Lara",
    idade=27,
    idiomas=["pt-BR", "en-US"],  # dispara o bloco internacional onde a localização é citada
    localizacao_operacional="São Paulo",
    tipos_aceitos=["externo"],
)

PROGRAMAS: list[dict[str, Any]] = [
    {"nome": "Massagem Relaxante", "duracao_nome": "1 hora", "preco": 800},
    {"nome": "Massagem Relaxante", "duracao_nome": "2 horas", "preco": 1500},
    {"nome": "Programa Completo", "duracao_nome": "2 horas", "preco": 2500},
]

# preco None = incluso (faz sem custo); preenchido = extra pago (a IA cota "+R$X").
FETICHES: list[dict[str, Any]] = [
    {"nome": "Beijo na boca", "preco": None},
    {"nome": "Inversão", "preco": 200},
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
    # Idiomas são renderizados pelo filtro `idioma_humano` (persona.py): `en-US` -> `inglês`.
    txt = render_identidade(ESTRANGEIRA)
    assert "sotaque" in txt
    assert "internacional" in txt
    assert "inglês" in txt


def test_localizacao_operacional_interpolada_sem_rio_hardcoded() -> None:
    # localizacao_operacional de SP no bloco internacional: render não vaza "Rio" hardcoded.
    txt = render_identidade(PAULISTA)
    assert "Rio" not in txt
    assert "São Paulo" in txt


def test_endereco_formatado_exposto_como_ponto_de_encontro() -> None:
    # ADR 0020: no pickup a IA precisa passar o endereço de atendimento (ponto de encontro).
    # Endereço presente → renderiza; ausente (ESTRANGEIRA) → linha some, sem "None" vazado.
    txt = render_identidade(CARIOCA)
    assert "Av. das Américas, 500 - Barra da Tijuca, Rio de Janeiro - RJ" in txt
    assert "ponto de encontro" in txt
    sem_endereco = render_identidade(ESTRANGEIRA)
    assert "ponto de encontro" not in sem_endereco
    assert "None" not in sem_endereco


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
    # filtro `brl` (persona.py): persona exige R$1.500 (sem espaço, ponto como separador).
    assert "R$2.500" in txt


def test_programas_vazio_orienta_escalar() -> None:
    # Cadastro incompleto no painel (estado anormal): não inventar valor + escalar p/ Fernando.
    txt = render_programas([])
    assert "cadastro incompleto" in txt
    assert 'escalar(motivo="politica_nova_necessaria")' in txt


def test_fetiches_lista_extra_e_incluso() -> None:
    txt = render_fetiches(FETICHES)
    assert "Beijo na boca" in txt
    assert "incluso" in txt  # preco None
    assert "Inversão" in txt
    assert "+R$200" in txt  # preco preenchido, filtro brl


def test_fetiches_vazio_orienta_recusa() -> None:
    txt = render_fetiches([])
    assert "ainda não tem fetiches" in txt


def test_render_bp3_concatena_identidade_programas_e_fetiches() -> None:
    bp3 = render_bp3(CARIOCA, PROGRAMAS, FETICHES)
    assert "Bia" in bp3
    assert "<programas>" in bp3
    assert "Programa Completo" in bp3
    assert "<fetiches>" in bp3
    assert "Inversão" in bp3


def test_build_system_messages_emite_2_blocos() -> None:
    # Pos-fusao BP_GERAL: 2 blocos system (geral fundido + por-modelo), antes eram 3.
    msgs = build_system_messages(
        geral_md=f"{GERAL}\n\n{FAQ}",
        ttl_geral="1h",
        modelo_md=render_bp3(CARIOCA, PROGRAMAS, FETICHES),
        ttl_modelo="1h",
    )
    assert len(msgs) == 2
    modelo_texto = msgs[1].content[0]["text"]  # type: ignore[index]
    assert "Bia" in modelo_texto
    assert "26" in modelo_texto
    assert "Programa Completo" in modelo_texto


def test_guardrail_bp_geral_byte_identico_entre_modelos() -> None:
    # Guard-rail #1: BP_GERAL fundido byte-idêntico p/ 2 modelos distintas; só o BP_MODELO difere.
    a = build_system_messages(
        geral_md=f"{GERAL}\n\n{FAQ}",
        ttl_geral="1h",
        modelo_md=render_bp3(CARIOCA, PROGRAMAS, FETICHES),
        ttl_modelo="1h",
    )
    b = build_system_messages(
        geral_md=f"{GERAL}\n\n{FAQ}",
        ttl_geral="1h",
        modelo_md=render_bp3(ESTRANGEIRA, [], []),
        ttl_modelo="1h",
    )
    assert a[0].content == b[0].content  # BP_GERAL idêntico
    assert a[1].content != b[1].content  # BP_MODELO difere por-modelo
