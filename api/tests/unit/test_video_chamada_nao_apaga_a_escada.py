"""A vídeo chamada divide duração com o pacote presencial — e não pode apagar a escada.

Regressão de 11/08/2026 (verificada em prod): ao subir a vídeo chamada da Catarina (serviço
REMOTO, R$10/minuto, `preco_minimo = preco`), a 0.5h e a 1h passaram a ter DUAS linhas de tabela.
Todo mundo que exige "um preço só" caiu no fail-closed: `contraproposta_da_escada` parou de
devolver número na 1h (o pacote que mais vende) e `_base_no_patamar` parou de montar o total com
fetiche no patamar negociado.

O conserto é a leitura de tabela do domínio distinguir presencial de remoto — `_linhas_da_duracao`
com `apenas_presenciais` explícito. Este arquivo fixa os dois lados dela: o da OFERTA (que filtra)
e o do JULGAMENTO de uma venda já feita (que não filtra, senão uma chamada vendida abaixo do
mínimo dela deixaria de escalar). E fixa o TERCEIRO site da mesma regressão, do lado do prompt: o
`precos_por_horas` de `_carregar_bp3`, que alimenta o `<pacote_em_pauta>` do foco do turno e
sumia na 1h e nos 30min pelo mesmo motivo. Fixture, sem DB, sem crédito.
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from langchain_core.messages import HumanMessage

from barra.agente.contexto import ContextAgente
from barra.agente.nos.prepare_context import (
    _anexar_contexto_dinamico,
    _base_no_patamar,
    _carregar_bp3,
)
from barra.agente.persona import e_video_chamada as e_video_chamada_da_persona
from barra.agente.persona import render_foco_do_turno
from barra.core.catalogo import e_video_chamada
from barra.dominio.atendimentos.service import (
    _piso_do_pacote,
    contraproposta_da_escada,
)

_ATENDIMENTO = UUID("33333333-3333-3333-3333-333333333333")
_NORMAL = "prog-normal"
_CHAMADA = "prog-video-chamada"


def _linha(programa_id: str, nome: str, preco: str, minimo: str) -> dict[str, Any]:
    return {
        "programa_id": programa_id,
        "nome": nome,
        "preco": Decimal(preco),
        "preco_minimo": Decimal(minimo),
    }


# A tabela REAL da Catarina em prod (11/08/2026), linha a linha. A vídeo chamada ocupa 0.25/0.5/
# 0.75/1h e todas as linhas dela são NÃO descontáveis (`preco_minimo == preco`); o presencial só
# começa em 0.5h. As duas colisões (0.5h e 1h) são a regressão.
_TABELA_DA_CATARINA: dict[str, list[dict[str, Any]]] = {
    "0.25": [_linha(_CHAMADA, "Vídeo chamada", "150", "150")],
    "0.50": [
        _linha(_NORMAL, "Normal", "250", "250"),
        _linha(_CHAMADA, "Vídeo chamada", "300", "300"),
    ],
    "0.75": [_linha(_CHAMADA, "Vídeo chamada", "450", "450")],
    "1.00": [
        _linha(_NORMAL, "Normal", "400", "300"),
        _linha(_CHAMADA, "Vídeo chamada", "600", "600"),
    ],
    "2.00": [_linha(_NORMAL, "Normal", "800", "600")],
    "3.00": [_linha(_NORMAL, "Normal", "1000", "900")],
    "6.00": [_linha(_NORMAL, "Normal", "2000", "2000")],
}


class _FakeConnDaCatarina:
    """Serve a tabela da Catarina às queries do domínio: as linhas da duração, a linha de 1h de um
    programa (base do extra de fetiche), o serviço vendido e as falas da IA (preço COTADO)."""

    def __init__(
        self,
        *,
        servicos: list[dict[str, Any]] | None = None,
        falas: list[str] | None = None,
    ) -> None:
        self.servicos = servicos or []
        self.falas = falas or []

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> Any:
        payload: list[dict[str, Any]]
        if "atendimento_servicos" in sql:
            payload = self.servicos
        elif "mp.programa_id = %s" in sql:  # linha_de_uma_hora: (modelo, programa, 1h)
            programa = params[1]
            payload = [ln for ln in _TABELA_DA_CATARINA["1.00"] if ln["programa_id"] == programa]
        elif "modelo_programas" in sql:
            payload = _TABELA_DA_CATARINA.get(f"{Decimal(str(params[1])):.2f}", [])
        elif "mensagens" in sql:
            payload = [{"conteudo": fala} for fala in self.falas]
        else:
            payload = [
                {"modelo_id": "catarina", "duracao_horas": Decimal("1"), "conversa_id": "c1"}
            ]

        class _R:
            async def fetchall(self) -> list[dict[str, Any]]:
                return payload

            async def fetchone(self) -> dict[str, Any] | None:
                return payload[0] if payload else None

        return _R()


async def _oferta(duracao: str, *, encontro: str = "outro_dia", n: int = 0) -> Decimal | None:
    return await contraproposta_da_escada(
        _FakeConnDaCatarina(),  # type: ignore[arg-type]
        "catarina",
        Decimal(duracao),
        encontro=encontro,  # type: ignore[arg-type]
        n_contrapropostas=n,
    )


# --- o predicado é um só ------------------------------------------------------------------------


def test_o_predicado_de_servico_remoto_tem_site_unico() -> None:
    """Desceu para `core/` porque `dominio/` não importa `barra.agente` (dominio/CLAUDE.md) e a
    leitura de tabela precisa dele. `persona` reexporta o MESMO objeto — não uma cópia."""
    assert e_video_chamada_da_persona is e_video_chamada
    assert e_video_chamada("Vídeo chamada")
    assert not e_video_chamada("Normal")


# --- a OFERTA: a escada volta a existir na 1h ----------------------------------------------------


async def test_a_escada_da_1h_volta_com_a_video_chamada_cadastrada() -> None:
    """O caso que quebrou: 1h da Catarina = Normal 400 (mínimo 300) + Vídeo chamada 600. Filtrada
    a linha remota, a duração tem UM preço presencial de novo e a escada devolve degrau e piso."""
    assert await _oferta("1.00", n=0) == Decimal("350")
    assert await _oferta("1.00", n=1) == Decimal("300")
    assert await _oferta("1.00", encontro="hoje", n=0) == Decimal("300")


async def test_a_1h_nao_muda_de_numero_por_causa_do_filtro() -> None:
    """Guarda de regra de preço: o degrau/piso da 1h são os da linha Normal, os mesmos de antes de
    a vídeo chamada existir. O conserto mexe em QUAIS linhas entram, nunca em quanto custa."""
    tabela = _TABELA_DA_CATARINA["1.00"]
    normal = next(ln for ln in tabela if ln["programa_id"] == _NORMAL)
    assert (normal["preco"], normal["preco_minimo"]) == (Decimal("400"), Decimal("300"))


async def test_os_30min_continuam_sem_contraproposta() -> None:
    """A 0.5h tem a MESMA colisão (Normal 250 + chamada 300), mas o Normal de 250 é não
    descontável (`preco_minimo == preco`): a conta clampada devolve o próprio preço de tabela e a
    cauda continua calada. O conserto não pode passar a oferecer desconto onde não há."""
    for n in (0, 1):
        assert await _oferta("0.50", n=n) is None
    assert await _oferta("0.50", encontro="hoje", n=0) is None


async def test_duracao_so_de_video_chamada_nao_desconta() -> None:
    """15min e 45min só existem como chamada. Filtradas, sobram ZERO linhas presenciais — sem
    preço de tabela para descontar, e nunca o preço da chamada (que é o mínimo dela)."""
    for duracao in ("0.25", "0.75"):
        for n in (0, 1):
            assert await _oferta(duracao, n=n) is None


async def test_duas_linhas_presenciais_continuam_ambiguas() -> None:
    """O filtro não afrouxa o fail-closed que importa: com Normal e Completo na mesma duração o
    pacote continua ambíguo e a escada continua calada."""
    _TABELA_DA_CATARINA["1.00"].append(_linha("prog-completo", "Completo", "800", "600"))
    try:
        assert await _oferta("1.00", n=0) is None
    finally:
        _TABELA_DA_CATARINA["1.00"].pop()


# --- o JULGAMENTO: a venda remota é julgada contra o piso DELA -----------------------------------


async def _piso(
    *, valor: str, servicos: list[dict[str, Any]] | None = None, falas: list[str] | None = None
) -> tuple[Decimal | None, str]:
    return await _piso_do_pacote(
        _FakeConnDaCatarina(servicos=servicos, falas=falas),  # type: ignore[arg-type]
        _ATENDIMENTO,
        "catarina",
        Decimal("1"),
        valor=Decimal(valor),
        conversa_id="c1",
        fala_da_ia_no_turno=None,
    )


async def test_venda_de_video_chamada_e_julgada_contra_o_piso_dela() -> None:
    """Uma chamada de 1h fechada em 550 (tabela 600, mínimo 600) TEM de escalar. Se a leitura que
    julga filtrasse a linha remota, o piso viria do Normal (300) e a venda passaria — o furo do
    ADR-0037 reaberto pelo lado remoto. Por isso `_piso_do_pacote` lê a duração inteira."""
    assert await _piso(valor="550", servicos=[{"programa_id": _CHAMADA}]) == (
        Decimal("600"),
        "programa_vendido",
    )
    # Sem serviço registrado (o caminho da IA), o preço COTADO na conversa identifica o pacote.
    assert await _piso(valor="550", falas=["a vídeo chamada de 1h fica 600 amor"]) == (
        Decimal("600"),
        "preco_cotado",
    )


async def test_venda_presencial_na_mesma_duracao_segue_com_o_piso_do_normal() -> None:
    """O outro lado da mesma leitura: cotado 400, o pacote é o Normal e o piso é 300 — fechar em
    300 continua passando, sem escalada nova por causa da chamada morando na mesma duração."""
    assert await _piso(valor="300", falas=["fica 400 amor"]) == (Decimal("300"), "preco_cotado")


# --- a base do patamar volta a montar na 1h ------------------------------------------------------


async def test_base_no_patamar_volta_a_produzir_numero_na_1h() -> None:
    """O bloco que dá à IA o total com fetiche JÁ no patamar negociado (ADR-0038) exige uma linha
    só na duração. Com o filtro, a 1h da Catarina volta a ter uma — no degrau, o pacote é 350 e a
    linha de 1h que serve de base ao extra é a do Normal (400/300)."""
    base = await _base_no_patamar(
        _FakeConnDaCatarina(),  # type: ignore[arg-type]
        "catarina",
        Decimal("1"),
        "degrau",
    )

    assert base is not None
    assert base.pacote == Decimal("350")
    assert base.horas == Decimal("1")
    assert base.linha_de_uma_hora == (Decimal("400"), Decimal("300"))


# --- o PROMPT: o <pacote_em_pauta> do foco do turno ----------------------------------------------
#
# Terceiro lado da MESMA regressão, achado depois: `_carregar_bp3` montava o `precos_por_horas`
# sobre TODOS os programas e o consumidor exige `len(precos) == 1`, então a chamada morando em
# 0.5h e 1h APAGAVA o bloco justamente nos dois pacotes que mais vendem. A divisória é a mesma da
# `_linhas_da_duracao(apenas_presenciais=True)`: os consumidores do dicionário são todos de OFERTA.


class _ConnBp3DaCatarina:
    """As três queries de `_carregar_bp3`, na ordem: `modelos`, programas, fetiches."""

    def __init__(self) -> None:
        self._respostas: list[list[dict[str, Any]]] = [
            [
                {
                    "nome": "Catarina",
                    "idade": 25,
                    "idiomas": [],
                    "tipo_atendimento_aceito": ["interno"],
                }
            ],
            [
                {
                    "nome": ln["nome"],
                    "duracao_nome": f"{horas}h",
                    "duracao_horas": Decimal(horas),
                    "preco": ln["preco"],
                }
                for horas, linhas in _TABELA_DA_CATARINA.items()
                for ln in linhas
            ],
            [],
        ]

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> Any:
        payload = self._respostas.pop(0)

        class _R:
            async def fetchall(self) -> list[dict[str, Any]]:
                return payload

            async def fetchone(self) -> dict[str, Any] | None:
                return payload[0] if payload else None

        return _R()


class _ConnVazio:
    """O foco não faz query própria: preços e atendimento chegam por kwarg."""

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> Any:
        class _R:
            async def fetchall(self) -> list[Any]:
                return []

            async def fetchone(self) -> None:
                return None

        return _R()


def _ctx_do_agente() -> ContextAgente:
    return ContextAgente(
        db_pool=None,  # type: ignore[arg-type]
        redis=None,  # type: ignore[arg-type]
        modelo_id="catarina",
        atendimento_id="22222222-2222-2222-2222-222222222222",
        cliente_id="33333333-3333-3333-3333-333333333333",
        turno_id="t",
        agora_utc=datetime(2026, 8, 11, 17, 30, tzinfo=UTC),
    )


async def _precos_por_horas() -> dict[float, list[Decimal]]:
    return (await _carregar_bp3(_ConnBp3DaCatarina(), "catarina"))[9]  # type: ignore[arg-type]


async def _cardapio() -> dict[str, list[dict[str, Any]]]:
    """O cardápio da MESMA leitura que dá os preços (índice 10 do BP3), e não um dict inventado:
    o ponto do arquivo é a tabela real da Catarina — a vídeo chamada cadastrada na mesma duração
    do presencial —, então o cardápio que acompanha os preços tem de ser o dela também."""
    return (await _carregar_bp3(_ConnBp3DaCatarina(), "catarina"))[10]  # type: ignore[arg-type]


async def _foco_da_duracao(horas: str) -> tuple[dict[str, str] | None, str]:
    """(`pacote_em_pauta` resolvido, o <foco_do_turno> renderizado) para a duração em discussão."""
    _msgs, contexto, _pecas = await _anexar_contexto_dinamico(
        _ConnVazio(),  # type: ignore[arg-type]
        _ctx_do_agente(),
        [HumanMessage(content="quanto fica?", id="h1")],
        atendimento={"estado": "Triagem", "duracao_horas": Decimal(horas)},
        precos_por_horas=await _precos_por_horas(),
        cardapio_rows=await _cardapio(),
    )
    return contexto.pacote_em_pauta, render_foco_do_turno(**contexto.como_variaveis())


async def test_precos_por_horas_do_foco_so_tem_linha_presencial() -> None:
    """A tabela real da Catarina vista pelo foco: uma linha por duração presencial e NENHUMA
    entrada para as durações que só existem como chamada (15min e 45min)."""
    assert await _precos_por_horas() == {
        0.5: [Decimal("250")],
        1.0: [Decimal("400")],
        2.0: [Decimal("800")],
        3.0: [Decimal("1000")],
        6.0: [Decimal("2000")],
    }


async def test_o_pacote_em_pauta_volta_na_1h_e_nos_30min() -> None:
    """Os dois pacotes que mais vendem, e os dois que a chamada apagava: 1h = 400, 30min = 250."""
    pauta, bloco = await _foco_da_duracao("1")
    assert pauta == {"horas": "1", "preco": "400"}
    assert "<pacote_em_pauta>" in bloco
    assert "1h" in bloco and "400" in bloco

    pauta, bloco = await _foco_da_duracao("0.5")
    assert pauta == {"horas": "0.5", "preco": "250"}
    assert "30min" in bloco and "250" in bloco


async def test_duas_linhas_presenciais_continuam_sem_bloco() -> None:
    """O filtro não afrouxa o fail-closed: Normal 400 + Completo 800 na 1h continua AMBÍGUO — dois
    pacotes presenciais, número errado é pior que nenhum bloco."""
    _TABELA_DA_CATARINA["1.00"].append(_linha("prog-completo", "Completo", "800", "600"))
    try:
        pauta, bloco = await _foco_da_duracao("1")
    finally:
        _TABELA_DA_CATARINA["1.00"].pop()

    assert pauta is None
    assert "<pacote_em_pauta>" not in bloco


async def test_duracao_so_de_video_chamada_nao_produz_bloco_presencial() -> None:
    """15min e 45min só existem como chamada: sem linha presencial, o bloco não sai — e nunca com
    o preço da chamada (150/450), que o filtro tirou da mesa."""
    for horas, preco_da_chamada in (("0.25", "150"), ("0.75", "450")):
        pauta, bloco = await _foco_da_duracao(horas)
        assert pauta is None
        assert "<pacote_em_pauta>" not in bloco
        assert preco_da_chamada not in bloco
