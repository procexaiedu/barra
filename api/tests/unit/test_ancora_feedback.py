"""Testes puros da âncora do rig de feedback (`barra.ancora_feedback`, issue #91).

De mesa, sem MCP/rede: alimenta listas de traces fabricadas e verifica que a âncora casa o
turno certo, tolera ruído de OCR, e — o ponto-chave do spec — **sinaliza ambiguidade em vez de
escolher em silêncio** (empate, nada plausível, fora da janela).
"""

from datetime import UTC, datetime, timedelta

from barra.core.ancora_feedback import (
    TraceCandidato,
    escolher_de_payload,
    escolher_trace_candidato,
)

TS_FEEDBACK = datetime(2026, 7, 13, 15, 0, 0, tzinfo=UTC)


def _trace(trace_id: str, saida: str, minutos_antes: float) -> TraceCandidato:
    return TraceCandidato(
        trace_id=trace_id,
        saida_agente=saida,
        timestamp=TS_FEEDBACK - timedelta(minutes=minutos_antes),
    )


def test_match_limpo_escolhe_turno_unico() -> None:
    """Um turno claramente correspondente é escolhido; nada de ambiguidade."""
    traces = [
        _trace("t1", "oi amor, aqui é no meu apê mesmo, você vem até mim 🥰", 3),
        _trace("t2", "quanto tempo você quer ficar comigo?", 10),
    ]
    r = escolher_trace_candidato(
        traces, "oi amor, aqui é no meu apê mesmo, você vem até mim", TS_FEEDBACK
    )
    assert r.ambiguo is False
    assert r.trace_id == "t1"
    assert r.motivo == "match"


def test_ocr_ruidoso_ainda_casa_o_turno_certo() -> None:
    """Print sem acentos e com typo de OCR ainda casa por similaridade aproximada."""
    traces = [
        _trace("t1", "oi amor, aqui é no meu apê mesmo, você vem até mim 🥰", 3),
        _trace("t2", "posso te mandar uma foto minha agora", 8),
    ]
    # Sem acentos, "ape" por "apê", "voce" por "você" — como a vision costuma recortar.
    r = escolher_trace_candidato(
        traces, "oi amor, aqui e no meu ape mesmo, voce vem ate mim", TS_FEEDBACK
    )
    assert r.ambiguo is False
    assert r.trace_id == "t1"


def test_empate_retorna_ambiguo_sem_escolher() -> None:
    """Dois turnos quase idênticos na janela → empate; não desempata sozinho."""
    traces = [
        _trace("t1", "vem que te espero amor", 4),
        _trace("t2", "vem que te espero amor", 6),
    ]
    r = escolher_trace_candidato(traces, "vem que te espero amor", TS_FEEDBACK)
    assert r.ambiguo is True
    assert r.trace_id is None
    assert r.motivo == "empate"
    assert r.candidatos == ("t1", "t2")


def test_fora_da_janela_retorna_ambiguo() -> None:
    """Turno plausível mas velho demais (fora da janela) não é match espúrio."""
    traces = [_trace("t1", "oi amor, aqui é no meu apê mesmo", 90)]
    r = escolher_trace_candidato(traces, "oi amor, aqui é no meu apê mesmo", TS_FEEDBACK)
    assert r.ambiguo is True
    assert r.trace_id is None
    assert r.motivo == "sem_candidato_na_janela"


def test_nenhum_match_abaixo_do_limiar() -> None:
    """Na janela, mas nada parecido com o texto do print → nenhum_match, não chuta."""
    traces = [
        _trace("t1", "quanto tempo você quer ficar?", 5),
        _trace("t2", "posso te mandar um pix da chave", 7),
    ]
    r = escolher_trace_candidato(
        traces, "adorei como ela conduziu o fechamento do valor", TS_FEEDBACK
    )
    assert r.ambiguo is True
    assert r.trace_id is None
    assert r.motivo == "nenhum_match"


def test_lista_vazia_retorna_ambiguo() -> None:
    """Sem candidatos, sem match — não levanta, sinaliza ambiguidade."""
    r = escolher_trace_candidato([], "qualquer texto", TS_FEEDBACK)
    assert r.ambiguo is True
    assert r.motivo == "sem_candidato_na_janela"


def test_desempate_deterministico() -> None:
    """Mesma entrada → mesma saída; o candidato mais próximo do texto vence sem empate."""
    traces = [
        _trace("t1", "oi amor tudo bem, como posso te ajudar hoje", 5),
        _trace("t2", "oi amor, aqui é no meu apê mesmo, você vem até mim 🥰", 4),
        _trace("t3", "quer marcar pra que horas então", 6),
    ]
    alvo = "oi amor, aqui é no meu apê mesmo, você vem até mim"
    r1 = escolher_trace_candidato(traces, alvo, TS_FEEDBACK)
    r2 = escolher_trace_candidato(traces, alvo, TS_FEEDBACK)
    assert r1 == r2
    assert r1.ambiguo is False
    assert r1.trace_id == "t2"


def test_payload_json_casa_o_turno() -> None:
    """Adaptador JSON→JSON (o que a skill chama via `python -m`) parseia ISO e escolhe o trace."""
    payload = {
        "texto_agente_print": "oi amor, aqui e no meu ape mesmo, voce vem ate mim",
        "ts_feedback": TS_FEEDBACK.isoformat(),
        "traces": [
            {
                "trace_id": "t1",
                "saida_agente": "oi amor, aqui é no meu apê mesmo, você vem até mim 🥰",
                "timestamp": (TS_FEEDBACK - timedelta(minutes=3)).isoformat(),
            },
            {
                "trace_id": "t2",
                "saida_agente": "quanto tempo você quer ficar comigo?",
                "timestamp": (TS_FEEDBACK - timedelta(minutes=9)).isoformat(),
            },
        ],
    }
    r = escolher_de_payload(payload)
    assert r["ambiguo"] is False
    assert r["trace_id"] == "t1"
    assert r["motivo"] == "match"
    assert isinstance(r["score"], float)


def test_payload_json_sinaliza_ambiguo() -> None:
    """Ambiguidade sobrevive à serialização JSON: sem trace escolhido, candidatos listados."""
    payload = {
        "texto_agente_print": "vem que te espero amor",
        "ts_feedback": TS_FEEDBACK.isoformat(),
        "traces": [
            {
                "trace_id": "t1",
                "saida_agente": "vem que te espero amor",
                "timestamp": (TS_FEEDBACK - timedelta(minutes=4)).isoformat(),
            },
            {
                "trace_id": "t2",
                "saida_agente": "vem que te espero amor",
                "timestamp": (TS_FEEDBACK - timedelta(minutes=6)).isoformat(),
            },
        ],
    }
    r = escolher_de_payload(payload)
    assert r["ambiguo"] is True
    assert r["trace_id"] is None
    assert r["motivo"] == "empate"
    assert r["candidatos"] == ["t1", "t2"]
