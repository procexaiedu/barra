"""Gate estrutural do endereço (análise prod 22/07, caso #12): o ponto de encontro da modelo
só entra no contexto do turno (<local_de_encontro>) a partir de Qualificado e em atendimento
interno — em Novo/Triagem a IA literalmente não tem o endereço para vazar, e no externo/remoto
o bloco não se aplica (endereço é do cliente / não há local).

Segundo degrau (issue 05): dentro do gate o endereço ainda chega em dois níveis — em Qualificado
SEM o número da rua, com o número entrando só de Aguardando_confirmacao em diante. O prompt pedia
que a IA cortasse o número sozinha e o DeepSeek não segurou; o que ela não recebe, ela não vaza."""

from datetime import UTC, datetime
from typing import Any

import pytest

from barra.agente.contexto import ContextAgente
from barra.agente.nos.prepare_context import (
    _endereco_do_degrau_sem_numero,
    _endereco_sem_numero,
    _interesse_demonstrado,
    _libera_local_de_encontro,
    _libera_numero_do_endereco,
    _ponto_de_encontro_no_prompt,
    _resolver_variaveis,
)
from barra.agente.persona import render_contexto_dinamico

_ENDERECO = "Av. Aquidabã, 130 - Centro, Campinas-SP"
_ENDERECO_SEM_NUMERO = "Av. Aquidabã - Centro, Campinas-SP"
_HOTEL = "Hotel Sirius"


def test_gate_por_estado_e_tipo() -> None:
    # Libera: Qualificado em diante, só interno.
    for estado in ("Qualificado", "Aguardando_confirmacao", "Confirmado", "Em_execucao"):
        assert _libera_local_de_encontro(estado, "interno")
    # Trava: pré-Qualificado (mesmo interno), tipo indefinido, externo/remoto, terminais.
    for estado in ("Novo", "Triagem", None, "Fechado", "Perdido"):
        assert not _libera_local_de_encontro(estado, "interno")
    for tipo in ("externo", "remoto", None):
        assert not _libera_local_de_encontro("Qualificado", tipo)


class _Result:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    async def fetchone(self) -> dict[str, Any] | None:
        return self.rows[0] if self.rows else None

    async def fetchall(self) -> list[dict[str, Any]]:
        return self.rows


class _FakeConn:
    """Vazio em tudo: atendimento e o local CRU (endereco_formatado/nome_local) chegam por kwarg —
    o local é lido junto da identidade em _carregar_bp3 (fusão da leitura de `modelos`)."""

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> _Result:
        return _Result([])


def _ctx() -> ContextAgente:
    return ContextAgente(
        db_pool=None,  # type: ignore[arg-type]  # não usado por _resolver_variaveis
        redis=None,  # type: ignore[arg-type]
        modelo_id="11111111-1111-1111-1111-111111111111",
        atendimento_id="22222222-2222-2222-2222-222222222222",
        cliente_id="33333333-3333-3333-3333-333333333333",
        turno_id="t",
        agora_utc=datetime(2026, 7, 22, 23, 0, tzinfo=UTC),
    )


async def _resolver(atendimento: dict[str, Any], endereco: str = _ENDERECO) -> dict[str, Any]:
    # O local CRU é SEMPRE passado (é lido junto da identidade); o gate por estado/tipo decide se
    # ele entra no contexto. Provamos que o gate — não a ausência do dado — é o que protege.
    return await _resolver_variaveis(
        _FakeConn(),  # type: ignore[arg-type]
        _ctx(),
        atendimento=atendimento,
        local_endereco_raw=endereco,
        local_nome_raw=_HOTEL,
    )


def test_gate_do_numero_por_estado() -> None:
    # O número entra quando o encontro está de pé: horário combinado (Aguardando_confirmacao) em
    # diante. O aviso de saída não precisa de teste próprio — ele só é carimbado em interno +
    # Aguardando_confirmacao (`_aviso_saida_aplicavel`), então já cai dentro deste degrau.
    for estado in ("Aguardando_confirmacao", "Confirmado", "Em_execucao"):
        assert _libera_numero_do_endereco(estado)
    for estado in ("Novo", "Triagem", "Qualificado", None):
        assert not _libera_numero_do_endereco(estado)


@pytest.mark.parametrize(
    ("formatado", "esperado"),
    [
        # Google formattedAddress completo (cadastro da Tatiane em prod).
        (
            "R. Santos Dumont, 291 - Cambuí, Campinas - SP, 13024-020, Brasil",
            "R. Santos Dumont - Cambuí, Campinas - SP, 13024-020, Brasil",
        ),
        # Sem CEP nem país.
        (_ENDERECO, _ENDERECO_SEM_NUMERO),
        # Número com complemento: some o número, o resto do campo fica.
        (
            "R. Santos Dumont, 291A - Cambuí, Campinas - SP",
            "R. Santos Dumont - Cambuí, Campinas - SP",
        ),
        (
            "R. Santos Dumont, 291-A - Cambuí, Campinas - SP",
            "R. Santos Dumont - Cambuí, Campinas - SP",
        ),
        # Separador de milhar: o número inteiro sai, não só o "1".
        (
            "Av. Brasil, 1.200 - Centro, Campinas - SP",
            "Av. Brasil - Centro, Campinas - SP",
        ),
        (
            "Av. Brasil, 1200 - Bloco B - Centro, Campinas - SP",
            "Av. Brasil - Bloco B - Centro, Campinas - SP",
        ),
        # Só logradouro e número.
        ("R. Santos Dumont, 291", "R. Santos Dumont"),
        # Endereço SEM número: nada a tirar (inclui o legado de texto livre, sem vírgula).
        ("Chácara da Barra, Campinas-SP", "Chácara da Barra, Campinas-SP"),
        ("Chácara da Barra", "Chácara da Barra"),
        # O CEP no lugar do número não é número de rua — não pode ser comido.
        (
            "Chácara da Barra, 13024-020, Campinas - SP",
            "Chácara da Barra, 13024-020, Campinas - SP",
        ),
    ],
)
def test_remocao_do_numero_preserva_rua_bairro_e_cidade(formatado: str, esperado: str) -> None:
    assert _endereco_sem_numero(formatado) == esperado
    # O que a IA de fato recebe no degrau de baixo: o mesmo texto, porque o número saiu.
    assert _endereco_do_degrau_sem_numero(formatado) == esperado


@pytest.mark.parametrize(
    "formatado",
    [
        # Texto livre legado (`0028_modelos_endereco_geo.sql`): número sem a vírgula do Google.
        "Av Aquidabã 130 - Centro, Campinas - SP",
        # Nome do estabelecimento prefixado — o número deixa de ser o 2º campo.
        "Vitória Hotel, R. Santos Dumont, 291 - Cambuí, Campinas - SP",
    ],
)
def test_endereco_que_nao_da_pra_podar_nao_chega_a_IA(formatado: str) -> None:
    # Fail-CLOSED: entregar o endereço intacto seria pior que antes — o bloco afirmaria "SEM o
    # número" com o número dentro. Sem endereço entregável, a IA cai no degrau da região.
    assert _endereco_do_degrau_sem_numero(formatado) is None


async def test_qualificado_interno_injeta_local_de_encontro() -> None:
    variaveis = await _resolver(
        {"numero_curto": 1, "estado": "Qualificado", "tipo_atendimento": "interno"}
    )
    # Primeiro degrau dentro do gate: hotel + rua, SEM o número — a IA não recebe o que não pode
    # falar ainda (o prompt pedindo que ela cortasse sozinha não segurou o DeepSeek).
    assert variaveis.local_endereco == _ENDERECO_SEM_NUMERO
    assert variaveis.local_nome == _HOTEL
    assert variaveis.numero_liberado is False

    saida = render_contexto_dinamico(**variaveis.como_variaveis())
    assert "<local_de_encontro>" in saida
    assert _ENDERECO_SEM_NUMERO in saida
    assert _ENDERECO not in saida and ", 130" not in saida
    assert _HOTEL in saida
    # A instrução acompanha o degrau: o que fazer quando ele pede o número, não "esconda o número".
    assert "pedir o número" in saida


async def test_cadastro_impodavel_derruba_o_bloco_no_degrau_de_baixo() -> None:
    # Fail-closed até o fim: sem endereço entregável, nem o nome do hotel sai — o bloco inteiro
    # some e a IA fica no degrau da região. No degrau de cima o MESMO cadastro entra inteiro.
    legado = "Av Aquidabã 130 - Centro, Campinas - SP"
    variaveis = await _resolver(
        {"numero_curto": 1, "estado": "Qualificado", "tipo_atendimento": "interno"}, legado
    )
    assert variaveis.local_endereco is None
    assert variaveis.local_nome is None
    assert "<local_de_encontro>" not in render_contexto_dinamico(**variaveis.como_variaveis())

    variaveis = await _resolver(
        {"numero_curto": 1, "estado": "Aguardando_confirmacao", "tipo_atendimento": "interno"},
        legado,
    )
    assert variaveis.local_endereco == legado


async def test_aguardando_confirmacao_libera_o_numero() -> None:
    for estado in ("Aguardando_confirmacao", "Confirmado", "Em_execucao"):
        variaveis = await _resolver(
            {"numero_curto": 1, "estado": estado, "tipo_atendimento": "interno"}
        )
        assert variaveis.local_endereco == _ENDERECO
        assert variaveis.numero_liberado is True

        saida = render_contexto_dinamico(**variaveis.como_variaveis())
        assert _ENDERECO in saida
        assert "pedir o número" not in saida


async def test_triagem_nao_renderiza_endereco() -> None:
    # Mesmo com o local CRU disponível (lido em _carregar_bp3), o gate o mantém FORA do contexto
    # antes de Qualificado: a IA nunca o vê renderizado, então não há o que vazar.
    variaveis = await _resolver(
        {"numero_curto": 1, "estado": "Triagem", "tipo_atendimento": "interno"}
    )
    assert variaveis.local_endereco is None
    assert "<local_de_encontro>" not in render_contexto_dinamico(**variaveis.como_variaveis())


async def test_externo_qualificado_nao_injeta_endereco_da_modelo() -> None:
    variaveis = await _resolver(
        {"numero_curto": 1, "estado": "Qualificado", "tipo_atendimento": "externo"}
    )
    assert variaveis.local_endereco is None
    assert "<local_de_encontro>" not in render_contexto_dinamico(**variaveis.como_variaveis())


async def test_status_diz_que_o_endereco_ainda_nao_foi_passado() -> None:
    # #41 (24/07 10:03): a IA disse "Já sabe onde é" — e o endereço só saiu 7 min DEPOIS. O bloco
    # trazia o endereço mas nunca dizia se ele já tinha sido entregue.
    variaveis = await _resolver(
        {"numero_curto": 41, "estado": "Qualificado", "tipo_atendimento": "interno"}
    )
    assert variaveis.endereco_ja_enviado is False
    saida = render_contexto_dinamico(**variaveis.como_variaveis())
    assert "AINDA NÃO passou este endereço" in saida
    assert "não fale como se ele já soubesse onde é" in saida


async def test_status_reconhece_o_endereco_ja_passado() -> None:
    variaveis = await _resolver(
        {
            "numero_curto": 41,
            "estado": "Qualificado",
            "tipo_atendimento": "interno",
            "endereco_enviado_em": datetime(2026, 7, 24, 13, 10, tzinfo=UTC),
        }
    )
    assert variaveis.endereco_ja_enviado is True
    saida = render_contexto_dinamico(**variaveis.como_variaveis())
    assert "JÁ passou este endereço" in saida
    assert "AINDA NÃO" not in saida


# ---------------------------------------------------------------------------
# Degrau por interesse demonstrado (rodada 6): a segurança não vem do estágio fixo,
# vem da cotação na mesa + sinal de avanço — quem pergunta cedo demais segue sem o número.


def test_interesse_demonstrado_exige_cotacao_na_mesa() -> None:
    # Sem preço na mesa NENHUM sinal libera — pedido cedo nunca recebe o endereço completo.
    assert not _interesse_demonstrado(
        preco_na_mesa=False,
        estado="Qualificado",
        aceitou_no_burst=True,
        pediu_endereco_no_burst=True,
        horario_em_pauta=True,
    )
    # Com preço na mesa, cada sinal de avanço libera sozinho.
    base: dict[str, Any] = {
        "estado": "Triagem",
        "aceitou_no_burst": False,
        "pediu_endereco_no_burst": False,
        "horario_em_pauta": False,
    }
    for sinal in (
        {"estado": "Qualificado"},
        {"aceitou_no_burst": True},
        {"pediu_endereco_no_burst": True},
        {"horario_em_pauta": True},
    ):
        assert _interesse_demonstrado(preco_na_mesa=True, **{**base, **sinal})
    # Preço na mesa SEM nenhum sinal de avanço: comportamento atual, nada libera.
    assert not _interesse_demonstrado(preco_na_mesa=True, **base)


def test_gates_com_interesse() -> None:
    # Interesse abre o BLOCO mesmo com o estado atrás — mas nunca no externo/remoto, e nunca o
    # NÚMERO: o número é degrau ESTRUTURAL (Aguardando_confirmacao+, emenda 25/07 do ADR-0026);
    # antecipá-lo por interesse é decisão de produto pendente (nota 11/08 no ADR-0026).
    assert _libera_local_de_encontro("Triagem", "interno", interesse=True)
    assert not _libera_local_de_encontro("Triagem", "externo", interesse=True)
    assert not _libera_local_de_encontro("Qualificado", "remoto", interesse=True)
    assert not _libera_numero_do_endereco("Qualificado", interesse=True)
    assert _libera_numero_do_endereco("Aguardando_confirmacao", interesse=True)
    # Default False = degrau por estágio, intacto (fail-closed p/ chamador sem o sinal).
    assert not _libera_local_de_encontro("Triagem", "interno")
    assert not _libera_numero_do_endereco("Qualificado")


def test_tipo_indefinido_entra_com_interesse_demonstrado() -> None:
    """P0-1 (diagnóstico 11/08): interno é o default de negócio — o próprio <ainda_falta> diz
    "padrão: ele vem no seu local" — e a extração só promove NULL→interno DEPOIS de o prompt já
    ter sido montado. Exigir o tipo GRAVADO tirava o bloco justo no turno em que o cliente escolhe
    o local e pede o endereço (trace 648d7f6f: o modelo inventou a rua). Com interesse demonstrado
    o tipo indefinido entra; sem interesse, nada muda."""
    assert _libera_local_de_encontro("Qualificado", None, interesse=True)
    assert _libera_local_de_encontro("Triagem", None, interesse=True)
    assert not _libera_local_de_encontro("Qualificado", None)
    assert not _libera_local_de_encontro("Aguardando_confirmacao", None)


async def test_pos_cotacao_com_avanco_libera_o_bloco_sem_numero_em_qualificado() -> None:
    # Interesse antecipa o BLOCO; o número segue estrutural (Aguardando_confirmacao+, ADR-0026 —
    # antecipação em Qualificado é decisão de produto pendente, nota 11/08 no ADR).
    variaveis = await _resolver_variaveis(
        _FakeConn(),  # type: ignore[arg-type]
        _ctx(),
        atendimento={"numero_curto": 1, "estado": "Qualificado", "tipo_atendimento": "interno"},
        local_endereco_raw=_ENDERECO,
        local_nome_raw=_HOTEL,
        interesse_no_endereco=True,
    )
    assert variaveis.local_endereco is not None
    assert variaveis.numero_liberado is False


def test_carimbo_do_prompt_espelha_o_bloco_renderizado() -> None:
    """O carimbo que o State publica (`local_endereco_no_prompt`) é o MESMO texto do bloco — é ele
    que o output_guard lê p/ decidir se cobra a entrega, e que a regen cola literalmente."""

    class _Fake:
        def __init__(self, endereco: str | None, nome: str | None) -> None:
            self.local_endereco = endereco
            self.local_nome = nome

    assert _ponto_de_encontro_no_prompt(_Fake(None, _HOTEL)) is None  # type: ignore[arg-type]
    assert (
        _ponto_de_encontro_no_prompt(_Fake(_ENDERECO_SEM_NUMERO, _HOTEL))  # type: ignore[arg-type]
        == f"{_HOTEL} — {_ENDERECO_SEM_NUMERO}"
    )
    # Sem nome de local, só o endereço — e sempre o do DEGRAU vigente (aqui, sem o número).
    assert (
        _ponto_de_encontro_no_prompt(_Fake(_ENDERECO_SEM_NUMERO, None))  # type: ignore[arg-type]
        == _ENDERECO_SEM_NUMERO
    )


async def test_pos_cotacao_sem_sinal_de_avanco_mantem_o_degrau() -> None:
    # `interesse_no_endereco` default False: Qualificado segue no degrau sem número, como sempre.
    variaveis = await _resolver(
        {"numero_curto": 1, "estado": "Qualificado", "tipo_atendimento": "interno"}
    )
    assert variaveis.local_endereco == _ENDERECO_SEM_NUMERO
    assert variaveis.numero_liberado is False
