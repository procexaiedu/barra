"""Testes dos scorers de conduta (evals.conduta) — deterministicos, sem DB/credito.

Baselines INJETADOS (sinteticos): nao dependem dos JSONs de prod (evals/baselines/*.json), que
sao gerados §0. Cobrem: detector de empurrao (inclui o caso 'seria hoje' que NAO conta), voz como
distancia relativa (parecido < diferente), forma como JSD relativo, e a degradacao graciosa do
avaliar_conduta quando o baseline de estilo esta ausente.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from evals.conduta import (
    CondutaScore,
    avaliar_conduta,
    empurrao_na_cotacao,
    estilo_dist,
    fluxo_jsd_populacao,
    tem_empurrao,
)
from evals.e2e.transcritos import salvar_transcritos
from evals.estilometria import perfil_de_bolhas

from barra.agente.fluxo import matriz_transicao


def _res(*textos: str) -> SimpleNamespace:
    """ResultadoE2E minimo duck-typed: os scorers so leem `res.turnos[i].texto`."""
    return SimpleNamespace(turnos=[SimpleNamespace(texto=t) for t in textos])


# --- DISCIPLINA: empurrao --------------------------------------------------------------------


def test_tem_empurrao_detecta_cta_colada() -> None:
    assert tem_empurrao("1h fica 400. vamos fechar?")
    assert tem_empurrao("400 a hora amor, bora?")
    assert tem_empurrao("so hoje esse valor, me confirma agora")


def test_tem_empurrao_ignora_sondagem_do_dia() -> None:
    # 'seria hoje?' e sondagem do DIA antes do preco — nao e empurrao (sim_deepseek.py:89).
    assert not tem_empurrao("seria hoje?")
    assert not tem_empurrao("1h fica 400 amor 😘")
    assert not tem_empurrao("te espero entao")


def test_empurrao_na_cotacao_olha_o_turno_do_preco() -> None:
    assert empurrao_na_cotacao(_res("oi tudo bem", "1h fica 400 amor")) == (True, False)
    assert empurrao_na_cotacao(_res("oi", "1h 400, vamos fechar?")) == (True, True)
    # sem turno de cotacao (nenhum preco) -> nao cotou, nao empurrou
    assert empurrao_na_cotacao(_res("oi amor", "que horas vc costuma")) == (False, False)


# --- VOZ: estilometria (distancia relativa) --------------------------------------------------


def test_estilo_dist_parecido_menor_que_diferente() -> None:
    perfil_ela = perfil_de_bolhas(
        ["oi amor 😘", "tudo bem? rs", "vem ca vida", "te espero amor", "que delicia rs"]
    )
    parecido = _res("oi vida 😘", "tudo joia? rs", "vem ca amor")
    diferente = _res(
        "Bom dia. Seguem os valores do meu atendimento conforme solicitado.",
        "Aguardo sua confirmacao para prosseguirmos com o agendamento.",
    )
    d_parecido = estilo_dist(parecido, perfil=perfil_ela)
    d_diferente = estilo_dist(diferente, perfil=perfil_ela)
    assert d_parecido is not None and d_diferente is not None
    assert d_parecido < d_diferente


def test_estilo_dist_sem_bolha_e_none() -> None:
    assert estilo_dist(_res("", "   "), perfil=perfil_de_bolhas(["oi amor"])) is None


# --- FORMA: fluxo do funil (JSD relativo) ----------------------------------------------------


def test_fluxo_jsd_mesma_forma_menor_que_divergente() -> None:
    # Baseline humano: saudacao -> sondagem -> cotacao -> logistica.
    baseline = matriz_transicao([["saudacao", "sondagem", "cotacao", "logistica"]] * 5)
    mesma_forma = [_res("oi tudo bem", "seria hoje?", "1h fica 400", "te espero, manda o pix")]
    divergente = [_res("blá", "blá blá", "que coisa", "hmm")]
    jsd_igual = fluxo_jsd_populacao(mesma_forma, baseline=baseline)
    jsd_diff = fluxo_jsd_populacao(divergente, baseline=baseline)
    assert jsd_igual < jsd_diff


# --- agregacao por-conversa ------------------------------------------------------------------


def test_avaliar_conduta_degrada_sem_baseline_de_estilo() -> None:
    # Sem evals/baselines/estilo_corpus.json, estilo_dist cai em None (nao quebra); voz/disciplina
    # seguem medidos. (Se o baseline JA existir localmente, estilo_dist vira float — ambos ok.)
    score = avaliar_conduta(_res("oi", "1h 400, vamos fechar?"))
    assert score.cotou is True
    assert score.empurrao is True
    assert score.estilo_dist is None or isinstance(score.estilo_dist, float)


# --- persistencia legivel dos transcripts (salvar_transcritos) -------------------------------


def _turno(texto: str, estado: str, *, pausada: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        texto=texto,
        estado_final={"estado": estado, "ia_pausada": pausada},
        tool_calls=[],
        metricas=SimpleNamespace(custo_brl=0.001),
    )


def _corrida() -> tuple[SimpleNamespace, SimpleNamespace, SimpleNamespace]:
    perfil = SimpleNamespace(nome="caso_X", eixo_comportamento="objetor")
    res = SimpleNamespace(
        turnos_cliente=["oi tem horario?", "ta caro"],
        turnos=[_turno("oi amor 😘", "Triagem"), _turno("1h fica 400 vida", "Qualificado")],
        desfecho_real="convertido",
        desfecho_conducao="conduziu",
        estado_final="Qualificado",
        n_turnos=2,
        custo_brl=0.002,
    )
    ver = SimpleNamespace(
        conduziu=True,
        violacoes=[],
        conduta=CondutaScore(cotou=True, empurrao=False, estilo_dist=0.01),
    )
    return perfil, res, ver


def test_salvar_transcritos_grava_html_e_jsonl(tmp_path: Path) -> None:
    destino = salvar_transcritos(tmp_path, [_corrida()], rel={"n_corridas": 1})

    # JSONL: 1 conversa, dialogo cliente x agente preservado em ordem.
    linhas = (destino / "transcritos.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(linhas) == 1
    reg = json.loads(linhas[0])
    assert reg["perfil"] == "caso_X" and reg["eixo"] == "objetor"
    assert [t["cliente"] for t in reg["turnos"]] == ["oi tem horario?", "ta caro"]
    assert reg["turnos"][1]["agente"] == "1h fica 400 vida"
    assert reg["conduta"]["cotou"] is True

    # HTML: auto-contido, com a fala do cliente e do agente (escapada) e o veredito.
    doc = (destino / "transcritos.html").read_text(encoding="utf-8")
    assert "oi tem horario?" in doc and "1h fica 400 vida" in doc
    assert "caso_X" in doc and "conduziu" in doc
    assert (destino / "resumo.json").exists()
