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
)

ESTRANGEIRA = IdentidadeModelo(
    nome="Ivanka",
    idade=29,
    idiomas=["pt-BR", "en-US"],
    localizacao_operacional=None,
    tipos_aceitos=["externo"],
)

PROGRAMAS: list[dict[str, Any]] = [
    {"nome": "Massagem Relaxante", "duracao_nome": "1 hora", "duracao_horas": 1, "preco": 800},
    {"nome": "Massagem Relaxante", "duracao_nome": "2 horas", "duracao_horas": 2, "preco": 1500},
    {"nome": "Programa Completo", "duracao_nome": "2 horas", "duracao_horas": 2, "preco": 2500},
]

# preco None = incluso; preenchido (qualquer valor, ignorado pelo cálculo — ADR-0030) = pago.
# cobra_por_pessoa (ADR-0035): False = ato (+preço-hora); True = casal/menage (dobra o pacote).
FETICHES: list[dict[str, Any]] = [
    {"nome": "Beijo na boca", "preco": None, "cobra_por_pessoa": False},
    {"nome": "Inversão", "preco": 1, "cobra_por_pessoa": False},
    {"nome": "Casal", "preco": 1, "cobra_por_pessoa": True},
]


def test_identidade_inclui_nome_e_idade() -> None:
    txt = render_identidade(CARIOCA)
    assert "Bia" in txt
    assert "26" in txt


def test_endereco_nunca_renderiza_no_bp_modelo() -> None:
    # Gate estrutural (análise prod 22/07): o ponto de encontro saiu do BP_MODELO — só entra via
    # <local_de_encontro> no contexto dinâmico, a partir de Qualificado. A região (1º contato)
    # continua aqui; endereço/ponto de encontro, nunca.
    txt = render_identidade(CARIOCA)
    assert "Barra da Tijuca" in txt  # região segue no BP_MODELO
    assert "ponto de encontro" not in txt
    assert "Endereço" not in txt
    assert "None" not in render_identidade(ESTRANGEIRA)


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
    txt = render_fetiches(FETICHES, PROGRAMAS)
    assert "Beijo na boca" in txt
    assert "Inclusos" in txt  # preco None
    assert "Inversão" in txt
    # ato pago (ADR-0030): tabela ÚNICA por pacote, extra = preço-hora efetivo (não lido de `preco`).
    assert "| Massagem Relaxante (1 hora) | +R$800 | R$1.600 |" in txt
    assert "| Massagem Relaxante (2 horas) | +R$750 | R$2.250 |" in txt  # 1500 / 2h
    assert "| Programa Completo (2 horas) | +R$1.250 | R$3.750 |" in txt  # 2500 / 2h


def test_fetiches_por_pessoa_dobra_o_pacote() -> None:
    # ADR-0035: casal/menage (cobra_por_pessoa=True) sai numa seção própria, dobrando o pacote —
    # nunca no regime "+Extra" dos atos.
    txt = render_fetiches(FETICHES, PROGRAMAS)
    assert "Por pessoa" in txt
    assert "Casal" in txt
    assert "| Massagem Relaxante (1 hora) | R$1.600 |" in txt  # 800 * 2
    assert "| Programa Completo (2 horas) | R$5.000 |" in txt  # 2500 * 2


def test_fetiches_pago_ignora_valor_cadastrado() -> None:
    # ADR-0030: o valor de `f.preco` nunca é lido no cálculo — só a presença (pago/incluso)
    # importa. Um sentinel "errado" (R$1) não vaza no valor calculado.
    txt = render_fetiches(FETICHES, PROGRAMAS)
    assert "+R$1 " not in txt
    assert "+R$1\n" not in txt


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


def test_fetiches_render_byte_identico_entre_modelos_com_mesmo_cadastro() -> None:
    # Ticket 03 (spec 0001-fetiche-calculado): o preço por-programa é calculado no render, não no
    # turno — duas modelos DISTINTAS (identidade diferente) com o MESMO cadastro de
    # fetiches/programas produzem o MESMO bloco <fetiches>, e a mesma modelo produz o mesmo bloco
    # em 2 renders sucessivos (não varia por turno/conversa).
    bloco_a = render_fetiches(FETICHES, PROGRAMAS)
    bloco_b = render_fetiches(FETICHES, PROGRAMAS)
    assert bloco_a == bloco_b

    bp3_carioca = render_bp3(CARIOCA, PROGRAMAS, FETICHES)
    bp3_estrangeira = render_bp3(ESTRANGEIRA, PROGRAMAS, FETICHES)
    fetiches_carioca = bp3_carioca.split("<fetiches>")[1]
    fetiches_estrangeira = bp3_estrangeira.split("<fetiches>")[1]
    assert fetiches_carioca == fetiches_estrangeira


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
