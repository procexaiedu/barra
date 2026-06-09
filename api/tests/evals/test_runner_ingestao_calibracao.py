"""Auto-ingestao do runner -> aba de calibracao: prova que as conversas GERADAS pelo gate saem no
formato que `calibracao.falas.parse_jsonl`/`falas_de` ingere (round-trip pelo contrato da aba).

PURO (sem DB/LLM) -> roda no `make test`. A escrita commitada no banco do painel (`ingerir_conversas`)
e provada separado pelo `needs_db` em `tests/integracao/test_runner_ingestao_calibracao_db.py`.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

from barra.calibracao.falas import falas_de, parse_jsonl

_RUNNER = Path(__file__).resolve().parents[1].parent / "evals" / "runners" / "runner.py"


def _carregar_runner() -> ModuleType:
    spec = importlib.util.spec_from_file_location("eval_runner", _RUNNER)
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = modulo
    spec.loader.exec_module(modulo)
    return modulo


runner = _carregar_runner()

# Turnos como `executar_fixture` os acumula: cliente + bolha GERADA (papel='ia'). A 'ia' roteirizada
# (historico, nao disparou o LLM) NAO entra -- so a bolha gerada e fala rotulavel.
_TURNOS = [
    {"papel": "cliente", "texto": "quanto e 1h?"},
    {"papel": "ia", "texto": "900 amor", "estado": "Qualificado", "tools": ["registrar_extracao"]},
    {"papel": "cliente", "texto": "fechado"},
    {"papel": "ia", "texto": "te espero amor", "estado": "Qualificado", "tools": []},
]


def test_serializar_conversa_atribui_idx_e_carimba_amostra():
    conv = runner.serializar_conversa("canonicos.venda.001", 3, _TURNOS)
    # K amostras viram conversas distintas -> Fernando/socia veem a variacao run-a-run.
    assert conv["conversa_id"] == "canonicos.venda.001#k3"
    assert conv["cenario"] == "canonicos.venda.001"
    # idx sequencial SO nas bolhas geradas (chave de rotulagem na UI).
    idxs = [t.get("idx") for t in conv["turnos"] if t["papel"] == "ia"]
    assert idxs == [0, 1]
    assert all("idx" not in t for t in conv["turnos"] if t["papel"] == "cliente")


def test_serializar_nao_muta_a_entrada():
    antes = [dict(t) for t in _TURNOS]
    runner.serializar_conversa("x.001", 0, _TURNOS)
    assert _TURNOS == antes  # serializar copia os turnos; nao escreve 'idx' no objeto original


def test_round_trip_pelo_contrato_da_aba_de_calibracao():
    """O .jsonl que o runner emite (`conversas_para_jsonl`) e lido por `parse_jsonl`/`falas_de`
    EXATAMENTE como o upload manual -- as bolhas geradas viram falas rotulaveis com historico fiel.
    """
    conv = runner.serializar_conversa("canonicos.venda.001", 0, _TURNOS)
    blob = runner.conversas_para_jsonl([conv])

    conversas = parse_jsonl(blob.decode("utf-8"))
    falas = falas_de(conversas)

    # 2 bolhas geradas -> 2 falas rotulaveis (a 'cliente' nunca vira fala).
    assert [f.fala_id for f in falas] == [
        "canonicos.venda.001#k0::0",
        "canonicos.venda.001#k0::1",
    ]
    assert [f.texto_resposta for f in falas] == ["900 amor", "te espero amor"]
    # historico = turnos ANTES da fala, na ordem do array (so cliente+ia geradas, sem ruido).
    assert falas[0].historico == ["cliente: quanto e 1h?"]
    assert falas[1].historico == [
        "cliente: quanto e 1h?",
        "ia: 900 amor",
        "cliente: fechado",
    ]


def test_conversas_para_jsonl_uma_linha_por_conversa():
    blob = runner.conversas_para_jsonl(
        [
            runner.serializar_conversa("x.001", 0, _TURNOS),
            runner.serializar_conversa("x.001", 1, _TURNOS),
        ]
    )
    linhas = [ln for ln in blob.decode("utf-8").splitlines() if ln.strip()]
    assert len(linhas) == 2  # K amostras = K linhas; cada uma uma conversa independente
