"""Prova os extratores de observabilidade de DIAGNOSTICO (C5a do flywheel) -- puros, sem DB/LLM/rede.

`prompt_montado`/`thinking`/`tool_io` enriquecem cada fala da IA no `conversas.jsonl` para o
root-cause do flywheel (aditivos: a UI de rotulagem e o `calibrar.py` ignoram). O ponto central e o
`tool_io`: ele carrega o MOTIVO da escalada (args de `escalar`), que o classificador E2E (C1) le
para distinguir escalada LEGITIMA (`fora_de_oferta`/AUP) de ESPURIA (bug de prompt). Duck-typing
sobre `.type`/`.content`/`.tool_calls` -- nao depende de imports de langchain (igual ao loop.py).
"""

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

_API = Path(__file__).resolve().parents[2]  # api/
if str(_API) not in sys.path:
    sys.path.insert(0, str(_API))

loop = importlib.import_module("evals.sim.loop")


def _sys(content):
    return SimpleNamespace(type="system", content=content, tool_calls=[])


def _human(text):
    return SimpleNamespace(type="human", content=text, tool_calls=[])


def _ai(content, tool_calls=None):
    return SimpleNamespace(type="ai", content=content, tool_calls=tool_calls or [])


def _tool(content, tool_call_id):
    return SimpleNamespace(type="tool", content=content, tool_call_id=tool_call_id, tool_calls=[])


# --- prompt_montado --------------------------------------------------------------------------------


def test_prompt_montado_pega_primeiro_system():
    msgs = [_sys("PERSONA + CARDAPIO"), _human("oi"), _ai("oi amor")]
    assert loop._extrair_prompt_montado(msgs) == "PERSONA + CARDAPIO"


def test_prompt_montado_concatena_blocos_text():
    # o system real e montado como lista de blocos {type:text, text, cache_control} pelo prepare_context
    msgs = [
        _sys([{"type": "text", "text": "A", "cache_control": {}}, {"type": "text", "text": "B"}])
    ]
    assert loop._extrair_prompt_montado(msgs) == "A\nB"


def test_prompt_montado_none_sem_system():
    assert loop._extrair_prompt_montado([_human("oi"), _ai("oi")]) is None


# --- thinking --------------------------------------------------------------------------------------


def test_thinking_pega_blocos_apos_ultimo_human():
    msgs = [
        _human("oi"),
        _ai([{"type": "thinking", "thinking": "vou cotar"}, {"type": "text", "text": "900"}]),
    ]
    assert loop._extrair_thinking_do_turno(msgs) == "vou cotar"


def test_thinking_none_quando_desabilitado():
    # P0: thinking desabilitado -> content e str pura, sem blocos thinking
    assert loop._extrair_thinking_do_turno([_human("oi"), _ai("900")]) is None


def test_thinking_ignora_historico_antes_do_ultimo_human():
    msgs = [_ai([{"type": "thinking", "thinking": "antigo"}]), _human("oi"), _ai("900")]
    assert loop._extrair_thinking_do_turno(msgs) is None


# --- tool_io (o coracao: motivo da escalada visivel) ----------------------------------------------


def test_tool_io_casa_args_e_resultado_por_id():
    msgs = [
        _human("quero fechar por 400"),
        _ai(
            "", tool_calls=[{"name": "escalar", "id": "tc1", "args": {"motivo": "fora_de_oferta"}}]
        ),
        _tool("escalada aberta", "tc1"),
        _ai("vou verificar com a equipe"),
    ]
    assert loop._extrair_tool_io_do_turno(msgs) == [
        {"tool": "escalar", "args": {"motivo": "fora_de_oferta"}, "resultado": "escalada aberta"}
    ]


def test_tool_io_motivo_da_escalada_legivel_pelo_classificador():
    # o ponto central de C5a: sem isto, C1 nao distingue escalada legitima de espuria
    msgs = [
        _human("x"),
        _ai("", tool_calls=[{"name": "escalar", "id": "a", "args": {"motivo": "fora_de_oferta"}}]),
    ]
    io = loop._extrair_tool_io_do_turno(msgs)
    assert io[0]["args"]["motivo"] == "fora_de_oferta"


def test_tool_io_vazio_sem_tools():
    assert loop._extrair_tool_io_do_turno([_human("oi"), _ai("oi")]) == []


def test_tool_io_ignora_tools_de_turnos_anteriores():
    msgs = [
        _ai("", tool_calls=[{"name": "consultar_agenda", "id": "old", "args": {}}]),
        _human("agora"),
        _ai("resposta"),
    ]
    assert loop._extrair_tool_io_do_turno(msgs) == []
