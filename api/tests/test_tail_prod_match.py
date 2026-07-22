"""Casamento mensagem↔trace do `scripts/tail_prod.py` (funções puras, offline).

O risco desta ferramenta é o match SILENCIOSO: atribuir a um turno a mecânica de outro e o dev
diagnosticar em cima do trace errado. Os testes abaixo travam o contrato de que o motivo do match
(`texto`/`tempo`/`ausente`) sempre acompanha o resultado.
"""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

_RAIZ = Path(__file__).resolve().parents[2]
_SCRIPT = _RAIZ / "scripts" / "tail_prod.py"

_spec = importlib.util.spec_from_file_location("tail_prod", _SCRIPT)
assert _spec is not None and _spec.loader is not None
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
casar_trace = _mod.casar_trace
montar_turnos = _mod.montar_turnos

T0 = datetime(2026, 7, 21, 12, 0, tzinfo=UTC)


def _msg(**kw: Any) -> dict[str, Any]:
    base = {
        "id": "m1",
        "created_at": T0,
        "direcao": "ia",
        "tipo": "texto",
        "conteudo": "2h fica 1.400, amor",
        "conversa_id": "c1",
        "atendimento_id": "a1",
    }
    return {**base, **kw}


def _trace(**kw: Any) -> dict[str, Any]:
    base = {
        "trace_id": "t1",
        "timestamp": T0 - timedelta(seconds=8),
        "session_id": "a1",
        "resposta_ia": "2h fica 1.400, amor 🥰",
        "desfecho": {},
    }
    return {**base, **kw}


def test_casa_por_texto_quando_a_bolha_e_substring_da_resposta() -> None:
    """O agente quebra a fala em bolhas: o conteúdo gravado é PARTE do `resposta_ia` do trace."""
    trace, motivo = casar_trace(_msg(), [_trace()])
    assert motivo == "texto"
    assert trace is not None and trace["trace_id"] == "t1"


def test_texto_vence_proximidade_temporal() -> None:
    """Um trace mais perto no tempo, mas de outra fala, não pode roubar o match."""
    intruso = _trace(trace_id="t2", timestamp=T0 - timedelta(seconds=1), resposta_ia="oii amor 😊")
    trace, motivo = casar_trace(_msg(), [intruso, _trace()])
    assert motivo == "texto"
    assert trace is not None and trace["trace_id"] == "t1"


def test_texto_curto_nao_casa_por_substring() -> None:
    """ "ok"/"sim" aparecem em qualquer resposta — cair para tempo é honesto, casar seria sorte."""
    _, motivo = casar_trace(_msg(conteudo="ok"), [_trace(resposta_ia="ok, ok amor")])
    assert motivo == "tempo"


def test_sem_trace_na_janela_e_ausente() -> None:
    """Trace velho demais não é reaproveitado — a ausência é reportada, não mascarada."""
    trace, motivo = casar_trace(_msg(), [_trace(timestamp=T0 - timedelta(hours=2))])
    assert (trace, motivo) == (None, "ausente")


def test_trace_de_outro_atendimento_nao_e_escolhido() -> None:
    """Isolamento: um turno de outro atendimento na mesma janela não pode virar a mecânica deste."""
    outro = _trace(trace_id="t9", session_id="a2", resposta_ia="2h fica 1.400, amor 🥰")
    trace, motivo = casar_trace(_msg(), [outro, _trace()])
    assert trace is not None and trace["trace_id"] == "t1"
    assert motivo == "texto"


def test_marca_mensagem_do_cliente_sem_resposta() -> None:
    """O buraco que motivou a ferramenta: cliente falou, IA não respondeu."""
    agora = T0 + timedelta(minutes=6)
    mensagens = [_msg(id="m1", direcao="cliente", conteudo="e amanhã 20h?", atendimento_id=None)]
    (turno,) = montar_turnos(mensagens, [], agora)
    assert turno["sem_resposta_s"] == 360


def test_nao_marca_quando_a_ia_respondeu_depois() -> None:
    mensagens = [
        _msg(id="m1", direcao="cliente", conteudo="e amanhã 20h?"),
        _msg(id="m2", direcao="ia", created_at=T0 + timedelta(seconds=10)),
    ]
    cliente, _ia = montar_turnos(mensagens, [], T0 + timedelta(minutes=6))
    assert cliente["sem_resposta_s"] is None
