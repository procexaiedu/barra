"""Agenda ocupada + relogio injetado no rig e2e, contra o DB real (needs_db, SEM needs_key).

Cobre o instrumento que a matriz de cenarios de producao (13/08) exige antes de qualquer cenario
de agenda:

- `seedar` semeia `cenario["bloqueios"]` na agenda da modelo, com as horas ancoradas no `agora`
  injetado, e o bloqueio PROPRIO faz o back-link `atendimentos.bloqueio_id`;
- o atendimento nasce parametrizado alem do `estado` (hora combinada, `aviso_saida_em`,
  `horario_evidenciado`) — o estado inicial dos cenarios de remarcacao;
- `rodar_e2e` ancora o SEED e CADA TURNO no mesmo relogio. A armadilha (memoria
  `rig_relogio_injetado_finge_7_dias`): ancorar so um lado deixa o historico no `now()` do banco
  enquanto o turno acontece no relogio fixo, e a distancia vira tempo decorrido fantasma e uma
  MARCA DE PAUSA sintetica (`_GAP_PAUSA`, prepare_context) numa conversa que nunca teve pausa. O
  ultimo teste e o CONTROLE: com o historico desancorado a marca aparece de verdade — e o que
  prova que o teste anterior estaria medindo alguma coisa.

O LLM e um chat fake roteirizado (mesmo padrao de `test_e2e_conducao`) e o judge de AUP do
output-guard fica desligado no teste: ele resolve `criar_chat_deepseek` de `barra.core.llm` na hora
da chamada, entao o fake do grafo NAO o cobre e um `.env` com chave faria este teste gastar credito
(memoria `teste_marcado_sem_chave_chama_o_judge`).
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from evals.e2e.cliente import ClienteRoteirizado
from evals.e2e.perfil import PerfilCaso
from evals.e2e.runner import rodar_e2e
from evals.harness import _inserir_mensagem, seedar
from langchain_core.messages import AIMessage
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from barra.agente.nos.prepare_context import carregar_mensagens, traduzir_mensagens

pytestmark = pytest.mark.needs_db

_BRT = ZoneInfo("America/Sao_Paulo")
# Ancora fixa e distante do relogio real: se o `agora` NAO fosse injetado, tudo aqui mudaria de
# sentido conforme a hora em que alguem roda o eval (que e exatamente o que estes testes proibem).
_AGORA = datetime(2026, 3, 15, 17, 0, tzinfo=UTC)  # 14:00 BRT
_USAGE = {"input_tokens": 10, "output_tokens": 8, "total_tokens": 18}

_MODELO: dict[str, Any] = {
    "nome": "Manu",
    "tipo_atendimento_aceito": ["interno", "externo"],
    "programas": [{"nome": "Encontro", "duracao_nome": "1 hora", "horas": 1, "preco": 400}],
}


@pytest_asyncio.fixture
async def conn() -> AsyncIterator[AsyncConnection[dict[str, Any]]]:
    connection = await AsyncConnection.connect(
        os.environ["TEST_DATABASE_URL"],
        autocommit=False,
        row_factory=dict_row,
        prepare_threshold=None,
    )
    try:
        yield connection
    finally:
        try:
            await connection.rollback()
        finally:
            await connection.close()


# --- chat fake (nenhuma chamada real ao provider, §0) ----------------------------------------


def _bolha(texto: str) -> AIMessage:
    return AIMessage(
        content=texto,
        usage_metadata=_USAGE,  # type: ignore[arg-type]
        response_metadata={"stop_reason": "end_turn"},
        tool_calls=[],
    )


def _extracao() -> AIMessage:
    return AIMessage(
        content="",
        usage_metadata=_USAGE,  # type: ignore[arg-type]
        response_metadata={"stop_reason": "tool_use"},
        tool_calls=[
            {
                "name": "registrar_extracao",
                "args": {"intencao": "agendamento", "proxima_acao_esperada": "conduzir horario"},
                "id": uuid4().hex,
                "type": "tool_call",
            }
        ],
    )


class _BoundFake:
    def __init__(self, chat: _ChatFake) -> None:
        self._chat = chat

    async def ainvoke(self, _messages: Any) -> AIMessage:
        return self._chat.proxima()


class _ChatFake:
    """Bolha + extracao forcada por turno (o `extrair` binda `registrar_extracao` com tool_choice).

    Esgotada a fila, REPETE a ultima em vez de estourar: o numero de chamadas por turno depende de
    quantos nos do grafo falam com o modelo, e este teste mede relogio/agenda, nao a fila."""

    model = "deepseek-test-relogio"

    def __init__(self, sequencia: list[AIMessage]) -> None:
        self._fila = list(sequencia)
        self._ultima = sequencia[-1]

    def proxima(self) -> AIMessage:
        if self._fila:
            self._ultima = self._fila.pop(0)
        return self._ultima

    def bind_tools(self, _tools: Any, *, tool_choice: Any = None, **_kw: Any) -> _BoundFake:
        return _BoundFake(self)


def _graph_fake(monkeypatch: pytest.MonkeyPatch, turnos: int) -> Any:
    from barra.agente import graph as graph_mod
    from barra.settings import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "output_guard_judge_habilitado", False)
    sequencia: list[AIMessage] = []
    for i in range(turnos):
        sequencia += [_bolha(f"oii amor 😊 bolha {i}"), _extracao()]
    monkeypatch.setattr(graph_mod, "criar_chat_deepseek", lambda *a, **k: _ChatFake(sequencia))
    return graph_mod.build_graph()


def _perfil() -> PerfilCaso:
    return PerfilCaso(
        nome="relogio_agenda",
        abertura="oi, quanto e 1h?",
        modelo=_MODELO,
        roteiro_cliente=["e que horas voce tem?", "fechado"],
    )


async def _bloqueios_da_modelo(
    conn: AsyncConnection[dict[str, Any]], modelo_id: UUID
) -> list[dict[str, Any]]:
    res = await conn.execute(
        "SELECT id, atendimento_id, inicio, fim, estado, origem, observacao, created_at "
        "FROM barravips.bloqueios WHERE modelo_id = %s ORDER BY inicio",
        (modelo_id,),
    )
    return [dict(r) for r in await res.fetchall()]


# --- G-INS-1: a fixture semeia agenda ocupada ------------------------------------------------


async def test_bloqueios_da_fixture_nascem_ancorados_no_agora(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """As tres formas relativas da fixture (hora BRT, timedelta, minutos) viram bloqueios ATIVOS
    da modelo, com `created_at` no relogio injetado — nunca no `now()` do banco."""
    cen = await seedar(
        conn,
        {
            "cenario": {
                "modelo": _MODELO,
                "atendimento": {"estado": "Novo"},
                "bloqueios": [
                    {"inicio": timedelta(hours=2), "fim": timedelta(hours=3)},
                    {"inicio": "hoje 21:00", "duracao_min": 90, "origem": "ia"},
                    {"inicio": -30, "duracao_min": 60, "observacao": "em curso"},
                ],
            },
            "historico": [],
        },
        agora=_AGORA,
    )

    assert len(cen.bloqueios) == 3
    assert cen.agora == _AGORA
    linhas = await _bloqueios_da_modelo(conn, cen.modelo_id)
    assert [ln["inicio"] for ln in linhas] == [
        _AGORA - timedelta(minutes=30),  # bloqueio em curso (inicio < agora < fim)
        _AGORA + timedelta(hours=2),
        datetime(2026, 3, 15, 21, 0, tzinfo=_BRT),
    ]
    assert linhas[1]["fim"] == _AGORA + timedelta(hours=3)
    assert linhas[2]["fim"] == datetime(2026, 3, 15, 22, 30, tzinfo=_BRT)
    # defaults: bloqueio ATIVO e manual (o que a agenda enxerga); origem so muda quando a fixture pede
    assert {ln["estado"] for ln in linhas} == {"bloqueado"}
    assert [ln["origem"] for ln in linhas] == ["manual", "manual", "ia"]
    assert all(ln["created_at"] == _AGORA for ln in linhas)
    # avulso: sem atendimento_id (nao e a reserva do cliente do cenario)
    assert all(ln["atendimento_id"] is None for ln in linhas)


async def test_bloqueio_proprio_escreve_o_back_link_do_atendimento(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """`{"atendimento": true}` = a reserva DELE: o bloqueio aponta para o atendimento e o
    atendimento aponta de volta (`bloqueio_id`) — o par que faz o `prepare_context` esconder o
    bloqueio proprio da lista de ocupacao (ela nao pode recusar a propria reserva)."""
    cen = await seedar(
        conn,
        {
            "cenario": {
                "modelo": _MODELO,
                "atendimento": {
                    "estado": "Aguardando_confirmacao",
                    "tipo_atendimento": "interno",
                    "data_desejada": "hoje",
                    "horario_desejado": "21:00",
                    "duracao_horas": 1,
                    "horario_evidenciado": True,
                },
                "bloqueios": [
                    {"inicio": "hoje 21:00", "duracao_min": 60, "atendimento": True},
                    {"inicio": "hoje 18:00", "duracao_min": 60},  # avulso, de outro cliente
                ],
            },
            "historico": [],
        },
        agora=_AGORA,
    )

    linhas = await _bloqueios_da_modelo(conn, cen.modelo_id)
    proprio = next(ln for ln in linhas if ln["atendimento_id"] is not None)
    avulso = next(ln for ln in linhas if ln["atendimento_id"] is None)
    assert proprio["atendimento_id"] == cen.atendimento_id
    assert proprio["inicio"] == datetime(2026, 3, 15, 21, 0, tzinfo=_BRT)
    assert avulso["inicio"] == datetime(2026, 3, 15, 18, 0, tzinfo=_BRT)

    res = await conn.execute(
        "SELECT bloqueio_id, data_desejada, horario_desejado, duracao_horas, horario_evidenciado "
        "FROM barravips.atendimentos WHERE id = %s",
        (cen.atendimento_id,),
    )
    at = await res.fetchone()
    assert at is not None
    assert at["bloqueio_id"] == proprio["id"]
    assert at["data_desejada"] == date(2026, 3, 15)  # "hoje" e o dia DELA (BRT), nao o do UTC
    assert at["horario_desejado"] == time(21, 0)
    assert float(at["duracao_horas"]) == 1.0
    assert at["horario_evidenciado"] is True


async def test_atendimento_acionado_nasce_com_aviso_de_saida(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """`aviso_saida_em` e o que separa remarcacao SEGURA (a IA resolve) de remarcacao que escala
    (`_modelo_ainda_nao_acionada`, dominio/atendimentos/service) — o estado inicial do cenario
    `remarcacao_pos_acionamento`. `True` = o proprio `agora`; qualquer forma relativa tambem vale."""
    cen = await seedar(
        conn,
        {
            "cenario": {
                "modelo": _MODELO,
                "atendimento": {
                    "estado": "Aguardando_confirmacao",
                    "pix_status": "aguardando",
                    "aviso_saida_em": True,
                },
            }
        },
        agora=_AGORA,
    )
    res = await conn.execute(
        "SELECT aviso_saida_em, pix_status FROM barravips.atendimentos WHERE id = %s",
        (cen.atendimento_id,),
    )
    at = await res.fetchone()
    assert at is not None
    assert at["aviso_saida_em"] == _AGORA
    assert at["pix_status"] == "aguardando"


async def test_cenario_sem_bloqueios_segue_com_agenda_vazia(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Compatibilidade dos 22 cenarios existentes: sem a chave nova, nenhum bloqueio nasce e o
    atendimento continua cru (todos os campos de agenda NULL/false)."""
    cen = await seedar(conn, {"cenario": {"modelo": _MODELO, "atendimento": {"estado": "Novo"}}})
    assert cen.bloqueios == []
    assert cen.agora is None
    assert await _bloqueios_da_modelo(conn, cen.modelo_id) == []
    res = await conn.execute(
        "SELECT bloqueio_id, data_desejada, horario_desejado, aviso_saida_em, horario_evidenciado "
        "FROM barravips.atendimentos WHERE id = %s",
        (cen.atendimento_id,),
    )
    at = await res.fetchone()
    assert at is not None
    assert at["bloqueio_id"] is None
    assert at["data_desejada"] is None
    assert at["horario_desejado"] is None
    assert at["aviso_saida_em"] is None
    assert at["horario_evidenciado"] is False


# --- G-INS-2: o `agora` vai aos DOIS lados ---------------------------------------------------


async def _created_at_das_mensagens(
    conn: AsyncConnection[dict[str, Any]], conversa_id: UUID
) -> list[tuple[str, datetime]]:
    res = await conn.execute(
        "SELECT direcao, conteudo, created_at FROM barravips.mensagens "
        "WHERE conversa_id = %s ORDER BY created_at, id",
        (conversa_id,),
    )
    return [(str(r["direcao"]), r["created_at"]) for r in await res.fetchall()]


async def test_ancora_unica_no_seed_e_nos_turnos_nao_fabrica_pausa(
    conn: AsyncConnection[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A armadilha do instrumento: historico e turnos ancorados no MESMO relogio -> a janela que o
    agente le nao ganha marca de pausa nem tempo decorrido fantasma, e o relogio avanca o passo
    declarado (nem mais, nem menos)."""
    perfil = _perfil()
    cen = await seedar(
        conn,
        {
            "cenario": {"modelo": _MODELO, "atendimento": {"estado": "Novo"}},
            "historico": [
                {"direcao": "cliente", "texto": "oi"},
                {"direcao": "ia", "texto": "oii amor 😊"},
            ],
        },
        agora=_AGORA,
    )

    res = await rodar_e2e(
        conn,
        perfil,
        ClienteRoteirizado(perfil.roteiro_cliente),
        graph=_graph_fake(monkeypatch, turnos=3),
        max_turnos=3,
        cen=cen,
        agora=_AGORA,
        passo_min=5,
    )

    assert res.n_turnos >= 2, res.trajetoria
    # as falas do cliente entraram no relogio injetado, uma por turno, com o passo declarado
    do_cliente = [
        criada
        for direcao, criada in await _created_at_das_mensagens(conn, cen.conversa_id)
        if direcao == "cliente"
    ]
    assert do_cliente[:3] == [_AGORA, _AGORA, _AGORA + timedelta(minutes=5)]

    # a janela traduzida (o que o prompt carrega) nao tem marca de pausa
    janela = traduzir_mensagens(
        await carregar_mensagens(conn, str(cen.cliente_id), str(cen.modelo_id))
    )
    textos = [str(m.content) for m in janela]
    assert not any("[pausa de" in t for t in textos), textos


async def test_historico_desancorado_fabrica_a_marca_de_pausa(
    conn: AsyncConnection[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """CONTROLE do teste acima: com o historico 8h atras do turno (o que acontece quando so um lado
    e ancorado), a MESMA janela ganha `[pausa de 8h na conversa]` — a conversa que nunca teve
    pausa. Se este teste parar de ver a marca, o teste anterior virou verde vazio."""
    perfil = _perfil()
    cen = await seedar(
        conn,
        {"cenario": {"modelo": _MODELO, "atendimento": {"estado": "Novo"}}, "historico": []},
        agora=_AGORA,
    )
    for direcao, texto in (("cliente", "oi"), ("ia", "oii amor 😊")):
        await _inserir_mensagem(
            conn,
            conversa_id=cen.conversa_id,
            direcao=direcao,
            texto=texto,
            created_at=_AGORA - timedelta(hours=8),
        )

    await rodar_e2e(
        conn,
        perfil,
        ClienteRoteirizado(perfil.roteiro_cliente),
        graph=_graph_fake(monkeypatch, turnos=1),
        max_turnos=1,
        cen=cen,
        agora=_AGORA,
    )

    janela = traduzir_mensagens(
        await carregar_mensagens(conn, str(cen.cliente_id), str(cen.modelo_id))
    )
    assert any("[pausa de 8h" in str(m.content) for m in janela), [str(m.content) for m in janela]
