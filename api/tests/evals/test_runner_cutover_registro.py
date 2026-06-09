"""F3.2: registro de CUTOVER de uma corrida verde das canonicas (PURO, sem DB/LLM).

O criterio do F3.2 (roadmap): "ao menos 1 corrida verde das canonicas registrada como cutover;
regressao reprova". O runner so emitia exit-code -- nada PERSISTIA que uma corrida verde da suite
de regressao (as 24 canonicas) virou o baseline de cutover. Estes testes trancam a maquina que
falta: `montar_registro_cutover` (puro) le as avaliacoes JA agregadas e decide se a corrida e um
cutover verde; `escrever_registro_cutover` so grava o baseline quando VERDE -- uma regressao NUNCA
vira cutover (reprova, nada e escrito). Espelha a divisao regressao-bloqueante / capability-advisory
do gate (`gate_split`/`particionar_gate`), incl. o vinculo de custo (F3.7).

Roda no `make test`/CI sem credenciais. A corrida ao vivo (grafo real + Sonnet sobre as canonicas)
e ★API e fica fora daqui -- aqui prova-se a LOGICA de registro/reprova, deterministica.
"""

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

_RUNNER = Path(__file__).resolve().parents[1].parent / "evals" / "runners" / "runner.py"


def _carregar_runner() -> ModuleType:
    spec = importlib.util.spec_from_file_location("eval_runner", _RUNNER)
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = modulo
    spec.loader.exec_module(modulo)
    return modulo


runner = _carregar_runner()

_CARIMBO = "2026-06-08T20:00:00-03:00"  # injetado -> registro deterministico (sem now() interno)


def _canonicas(n: int, *, falham: int = 0) -> list:
    """n fixtures canonicas (gate=regressao); as primeiras `falham` reprovam."""
    return [
        runner.Avaliacao(
            id=f"canonicos/c{i}",
            passou=i >= falham,
            falhas=[] if i >= falham else [f"grader x falhou em c{i}"],
            categoria="canonicos",
            gate="regressao",
        )
        for i in range(n)
    ]


# --- corrida VERDE das canonicas -> registra como cutover ---------------------------------------


def test_corrida_verde_das_canonicas_registra_cutover(tmp_path):
    avaliacoes = _canonicas(24)
    reg = runner.montar_registro_cutover(avaliacoes, k=2, threshold=1.0, carimbo=_CARIMBO)
    assert reg.verde is True
    assert reg.tipo == "cutover"
    assert reg.k == 2
    assert reg.n_regressao == 24
    assert reg.n_pass == 24
    assert reg.reprovadas == {}
    assert len(reg.fixtures) == 24

    caminho = tmp_path / "registros" / "cutover.json"
    runner.escrever_registro_cutover(reg, caminho)
    assert caminho.exists()
    gravado = json.loads(caminho.read_text(encoding="utf-8"))
    assert gravado["verde"] is True
    assert gravado["tipo"] == "cutover"
    assert gravado["carimbo"] == _CARIMBO
    assert gravado["k"] == 2


# --- regressao REPROVA -> nao vira cutover ------------------------------------------------------


def test_regressao_reprova_e_nao_registra(tmp_path):
    avaliacoes = _canonicas(24, falham=1)  # 1 canonica falha
    reg = runner.montar_registro_cutover(avaliacoes, k=2, threshold=1.0, carimbo=_CARIMBO)
    assert reg.verde is False
    assert reg.n_pass == 23
    assert "canonicos/c0" in reg.reprovadas

    caminho = tmp_path / "registros" / "cutover.json"
    try:
        runner.escrever_registro_cutover(reg, caminho)
        raise AssertionError("escrever_registro_cutover deveria recusar uma regressao")
    except ValueError as exc:
        assert "canonicos/c0" in str(exc)
    assert not caminho.exists()  # nada gravado: o cutover REPROVOU


# --- as 46 adversariais (capability) sao ADVISORY -> nao bloqueiam o cutover --------------------


def test_adversarial_advisory_nao_bloqueia_cutover(tmp_path):
    avaliacoes = _canonicas(24) + [
        runner.Avaliacao(
            id="adversariais/jailbreak1",
            passou=False,
            falhas=["nao escalou"],
            categoria="adversariais",
            gate="capability",
        )
    ]
    reg = runner.montar_registro_cutover(avaliacoes, k=2, threshold=1.0, carimbo=_CARIMBO)
    # advisory falhou, mas a suite de regressao (canonicas) esta verde -> cutover registra.
    assert reg.verde is True
    assert reg.n_regressao == 24  # a adversarial NAO entra na contagem de regressao
    caminho = tmp_path / "cutover.json"
    runner.escrever_registro_cutover(reg, caminho)
    assert caminho.exists()


# --- custo estourado (F3.7) e VINCULANTE mesmo numa capability -> reprova o cutover -------------


def test_custo_estourado_bloqueia_cutover_mesmo_capability(tmp_path):
    avaliacoes = _canonicas(24) + [
        runner.Avaliacao(
            id="adversariais/cara",
            passou=False,
            falhas=["estourou max_custo_brl"],
            categoria="adversariais",
            gate="capability",
            custo_estourado=True,
        )
    ]
    reg = runner.montar_registro_cutover(avaliacoes, k=2, threshold=1.0, carimbo=_CARIMBO)
    assert reg.verde is False  # guardrail de custo bloqueia mesmo a capability sendo advisory
    assert "adversariais/cara" in reg.reprovadas
    caminho = tmp_path / "cutover.json"
    try:
        runner.escrever_registro_cutover(reg, caminho)
        raise AssertionError("custo estourado deveria reprovar o cutover")
    except ValueError:
        pass
    assert not caminho.exists()


# --- suite de regressao VAZIA nao registra cutover (anti-vacuo) ---------------------------------


def test_suite_regressao_vazia_nao_registra(tmp_path):
    # so capability -> nao ha canonica provada -> gate_split=1 -> NAO e um cutover verde.
    avaliacoes = [
        runner.Avaliacao(
            id="adversariais/a", passou=True, categoria="adversariais", gate="capability"
        )
    ]
    reg = runner.montar_registro_cutover(avaliacoes, k=2, threshold=1.0, carimbo=_CARIMBO)
    assert reg.verde is False
    assert reg.n_regressao == 0
    caminho = tmp_path / "cutover.json"
    try:
        runner.escrever_registro_cutover(reg, caminho)
        raise AssertionError("suite de regressao vazia nao pode registrar cutover")
    except ValueError:
        pass
    assert not caminho.exists()


# --- rotulo nightly: mesma maquina, outro tipo --------------------------------------------------


def test_registro_nightly_propaga_tipo(tmp_path):
    reg = runner.montar_registro_cutover(
        _canonicas(24), k=2, threshold=1.0, carimbo=_CARIMBO, tipo="nightly"
    )
    assert reg.verde is True
    assert reg.tipo == "nightly"
    caminho = tmp_path / "nightly.json"
    runner.escrever_registro_cutover(reg, caminho)
    assert json.loads(caminho.read_text(encoding="utf-8"))["tipo"] == "nightly"
