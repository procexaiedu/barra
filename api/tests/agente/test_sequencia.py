"""Teste do validador de ordem (`evals.sequencia`) — puro, sem DB e sem credito.

Monta `ResultadoE2E` sinteticos (so os campos que o validador le) e cobre as duas regras v1 +
o caso de cotar-e-confirmar-no-mesmo-turno (nao deve violar). Roda na suite padrao (`make test`).
"""

from __future__ import annotations

from typing import Any

from evals.e2e.runner import ESTADO_INICIAL_PADRAO, ResultadoE2E
from evals.harness import ResultadoTurno
from evals.sequencia import avaliar_sequencia, derivar_eventos


def _turno(
    *,
    estado: str,
    pix_status: str = "nao_solicitado",
    tool_calls: list[str] | None = None,
    tool_args: list[dict[str, Any]] | None = None,
) -> ResultadoTurno:
    return ResultadoTurno(
        texto="",
        tool_calls=tool_calls or [],
        tool_args=tool_args or [],
        nodes=[],
        prompt_modelo=[],
        mensagens=[],
        estado_final={"estado": estado, "pix_status": pix_status, "ia_pausada": False},
    )


def _res(
    turnos: list[ResultadoTurno],
    *,
    estado_inicial: str = ESTADO_INICIAL_PADRAO,
    cotacao_inicial: bool = False,
) -> ResultadoE2E:
    return ResultadoE2E(
        perfil_nome="teste",
        trajetoria=[t.estado_final for t in turnos],
        turnos=turnos,
        estado_inicial=estado_inicial,
        cotacao_inicial=cotacao_inicial,
    )


def test_cota_depois_confirma_passa() -> None:
    """Cotou num turno e confirmou em turno posterior: sequencia valida."""
    res = _res(
        [
            _turno(
                estado="Qualificado",
                tool_calls=["registrar_extracao"],
                tool_args=[{"cotacao_apresentada": True}],
            ),
            _turno(
                estado="Aguardando_confirmacao",
                tool_calls=["registrar_extracao"],
                tool_args=[{"tipo_atendimento": "interno"}],
            ),
        ]
    )
    assert avaliar_sequencia(res) == []


def test_cota_e_confirma_no_mesmo_turno_passa() -> None:
    """Cotacao e transicao no MESMO turno: a extracao precede a transicao, nao viola."""
    res = _res(
        [
            _turno(
                estado="Aguardando_confirmacao",
                tool_calls=["registrar_extracao"],
                tool_args=[{"cotacao_apresentada": True, "tipo_atendimento": "interno"}],
            ),
        ]
    )
    assert avaliar_sequencia(res) == []


# --- estado SEEDADO nao e transicao da corrida ------------------------------------------------


def test_seedado_em_aguardando_confirmacao_nao_viola_r1() -> None:
    """Caso que NASCE na linha de chegada (cotacao antes da janela avaliada): a R1 nao se aplica.

    E o cenario `bloqueio_proprio_nao_recusa` — seedado em `Aguardando_confirmacao` com
    `valor_acordado`, o cliente so confirma a hora. Com `estado_anterior=None` o validador lia o
    estado semeado como transicao DA CORRIDA e acusava "confirmou sem ter cotado".
    """
    res = _res([_turno(estado="Aguardando_confirmacao")], estado_inicial="Aguardando_confirmacao")
    assert "estado:Aguardando_confirmacao" not in derivar_eventos(res)
    assert avaliar_sequencia(res) == []


def test_seedado_em_em_execucao_nao_emite_evento_espurio() -> None:
    """Qualquer estado seedado (aqui `Em_execucao`, do cenario foto_portaria) fica fora dos eventos."""
    res = _res([_turno(estado="Em_execucao")], estado_inicial="Em_execucao")
    assert derivar_eventos(res) == []


def test_seedado_sai_e_volta_emite_a_transicao() -> None:
    """Sair do estado seedado e VOLTAR a ele e transicao DA corrida — e a R1 volta a valer."""
    res = _res(
        [
            _turno(estado="Em_execucao"),
            _turno(estado="Aguardando_confirmacao"),
        ],
        estado_inicial="Aguardando_confirmacao",
    )
    eventos = derivar_eventos(res)
    assert eventos == ["estado:Em_execucao", "estado:Aguardando_confirmacao"]
    falhas = avaliar_sequencia(res)
    assert len(falhas) == 1
    assert "funil-vazamento" in falhas[0]


def test_default_novo_nao_engole_transicoes_da_corrida() -> None:
    """Nao-regressao: caso que nasce no default (`Novo`) segue emitindo tudo que transita."""
    res = _res([_turno(estado="Novo"), _turno(estado="Qualificado")])
    assert derivar_eventos(res) == ["estado:Qualificado"]


def test_confirma_sem_cotar_viola() -> None:
    """R1: chegou em Aguardando_confirmacao sem nenhum cotacao_apresentada."""
    res = _res(
        [
            _turno(estado="Qualificado", tool_calls=["registrar_extracao"], tool_args=[{}]),
            _turno(
                estado="Aguardando_confirmacao",
                tool_calls=["registrar_extracao"],
                tool_args=[{"tipo_atendimento": "interno"}],
            ),
        ]
    )
    falhas = avaliar_sequencia(res)
    assert len(falhas) == 1
    assert "funil-vazamento" in falhas[0]


def test_pix_sem_externo_viola() -> None:
    """R2: pix saiu de nao_solicitado sem tipo_atendimento=externo visto antes."""
    res = _res(
        [
            _turno(
                estado="Aguardando_confirmacao",
                pix_status="aguardando",
                tool_calls=["registrar_extracao"],
                tool_args=[{"cotacao_apresentada": True, "tipo_atendimento": "interno"}],
            ),
        ]
    )
    falhas = avaliar_sequencia(res)
    assert any("pix solicitado sem" in f for f in falhas)


def test_pix_com_externo_passa() -> None:
    """Pix apos tipo=externo: valido (e cotacao antes de confirmar)."""
    res = _res(
        [
            _turno(
                estado="Aguardando_confirmacao",
                pix_status="aguardando",
                tool_calls=["registrar_extracao"],
                tool_args=[{"cotacao_apresentada": True, "tipo_atendimento": "externo"}],
            ),
        ]
    )
    assert avaliar_sequencia(res) == []


def test_pix_com_remoto_passa() -> None:
    """Pix apos tipo=remoto: valido — remoto antecipa o valor da chamada pelo mesmo gate
    deterministico do externo (ADR 0029); a regra R2 aceita qualquer um dos dois tipos."""
    res = _res(
        [
            _turno(
                estado="Aguardando_confirmacao",
                pix_status="aguardando",
                tool_calls=["registrar_extracao"],
                tool_args=[{"cotacao_apresentada": True, "tipo_atendimento": "remoto"}],
            ),
        ]
    )
    assert avaliar_sequencia(res) == []


def test_cotacao_seedada_nao_acusa_funil_vazamento() -> None:
    """Cenario de remarcacao: nasce COTADO em `Aguardando_confirmacao` (`cotacao_enviada` no seed),
    a remarcacao aberta regride para `Qualificado` e o dia novo reserva de volta. A volta a
    `Aguardando_confirmacao` E uma transicao da corrida, mas a cotacao ja tinha acontecido antes da
    janela — e re-cotar aqui seria justamente o erro (`nao_deve_recotar`). Sem `cotacao_inicial` a
    R1 acusava `remarcacao_aberta_e_volta_atras` e `piso_que_andou` em c12cen_v2_20260814."""
    res = _res(
        [
            _turno(estado="Qualificado"),
            _turno(
                estado="Aguardando_confirmacao",
                tool_calls=["registrar_extracao"],
                tool_args=[{"tipo_atendimento": "interno"}],
            ),
        ],
        estado_inicial="Aguardando_confirmacao",
        cotacao_inicial=True,
    )
    assert avaliar_sequencia(res) == []
    assert derivar_eventos(res)[0] == "cotacao_apresentada"


def test_sem_cotacao_seedada_a_mesma_trajetoria_acusa() -> None:
    """CONTROLE: a MESMA corrida sem cotacao pre-existente continua sendo funil-vazamento — o que
    isenta e o fato seedado, nao o formato da trajetoria."""
    res = _res(
        [
            _turno(estado="Qualificado"),
            _turno(
                estado="Aguardando_confirmacao",
                tool_calls=["registrar_extracao"],
                tool_args=[{"tipo_atendimento": "interno"}],
            ),
        ],
        estado_inicial="Aguardando_confirmacao",
    )
    assert any("confirmou sem ter cotado" in f for f in avaliar_sequencia(res))
