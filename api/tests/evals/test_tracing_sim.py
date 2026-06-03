"""Guard de segurança do tracing LangSmith-sim (C5b do flywheel).

O `setup_tracing_sim` traça SEM anonymizer (conteúdo legível p/ root-cause) -- só pode ser usado com
dados sintéticos. Os guards: (1) não liga sem `langchain_api_key`; (2) FORÇA o sufixo `-sim` no
projeto, para o simulador nunca escrever no projeto de produção (onde o tracing é o `setup_tracing`
com anonymizer hard-gate).
"""

import importlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace

_API = Path(__file__).resolve().parents[2]  # api/
if str(_API) not in sys.path:
    sys.path.insert(0, str(_API))

tracing = importlib.import_module("barra.core.tracing")


def _settings(key=None):
    return SimpleNamespace(
        langchain_api_key=key,
        langchain_tracing_v2=True,
        langchain_project="barra-vips-dev",
        ambiente="dev",
    )


def test_sim_sem_key_nao_liga():
    # sem key -> None, sem tocar o ambiente (diagnóstico cai no conversas.jsonl enriquecido).
    assert tracing.setup_tracing_sim(_settings(key=None)) is None


def test_sim_forca_sufixo_sim_nunca_escreve_em_producao(monkeypatch):
    import langsmith.run_trees as rt

    monkeypatch.setattr(rt, "_CLIENT", None, raising=False)
    monkeypatch.setenv("LANGCHAIN_PROJECT", "x")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")
    client = tracing.setup_tracing_sim(
        _settings(key="lsv2_pt_fake_para_teste"), projeto="barra-vips"
    )
    assert client is not None
    # mesmo pedindo "barra-vips" (projeto de prod), vira "barra-vips-sim".
    assert os.environ["LANGCHAIN_PROJECT"] == "barra-vips-sim"


def test_sim_projeto_default_tem_sufixo():
    monkeypatch_default = tracing.setup_tracing_sim(_settings(key=None))
    assert monkeypatch_default is None  # default path sem key segue None (não liga)
