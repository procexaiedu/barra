"""Estatistica PURA de calibracao do LLM-judge contra golden humano (EVAL-10 / ADR 0015).

Sem DB, sem LLM, sem rede: opera sobre listas de rotulos BINARIOS (passou=True / falhou=False)
pareados humano-vs-judge. E o nucleo testavel do portao de promocao do judge a blocker
(`JUDGE_VINCULANTE=True` em runners/judge.py).

Convencao de rotulo: True = a resposta PASSA no criterio (atende a rubrica). O "positivo" da
matriz de confusao e o judge dizendo True; o "verdadeiro" e o humano dizendo True. Assim TPR =
recall do judge em concordar com o humano nos PASSA, TNR = especificidade nos FALHA.

Refino 08b §3.1 (no roadmap EVAL-10): em rubricas de prevalencia ASSIMETRICA (persona/tom, onde
quase tudo passa) o kappa de Cohen sofre o "paradoxo do kappa" (cai mesmo com acordo alto).
Por isso reportamos tambem o Gwet AC2, robusto a prevalencia. O acordo HUMANO-HUMANO
(Fernando x socia) e medido PRIMEIRO: ele e o TETO da meta -- exigir kappa_judge>=0.6 quando os
humanos so concordam a 0.7 e fragil. O threshold de um judge binario sai do Youden's J.
"""

from __future__ import annotations


def _validar_pareado(a: list[bool], b: list[bool]) -> None:
    """Exige listas nao-vazias e de mesmo tamanho (rotulos pareados sobre os mesmos itens)."""
    if len(a) != len(b):
        raise ValueError(f"listas pareadas precisam do mesmo tamanho: {len(a)} != {len(b)}")
    if not a:
        raise ValueError("listas de rotulos vazias")


def matriz_confusao(humano: list[bool], judge: list[bool]) -> dict[str, int]:
    """Matriz de confusao judge-vs-humano (PURO). Positivo = True (resposta passa no criterio).

    tp: humano True  e judge True   | fp: humano False e judge True
    fn: humano True  e judge False  | tn: humano False e judge False
    """
    _validar_pareado(humano, judge)
    tp = fp = tn = fn = 0
    for h, j in zip(humano, judge, strict=True):
        if h and j:
            tp += 1
        elif h and not j:
            fn += 1
        elif (not h) and j:
            fp += 1
        else:
            tn += 1
    return {"tp": tp, "fp": fp, "tn": tn, "fn": fn}


def tpr(humano: list[bool], judge: list[bool]) -> float:
    """True positive rate (recall/sensibilidade): tp / (tp + fn). 1.0 se nao ha positivo real."""
    m = matriz_confusao(humano, judge)
    denom = m["tp"] + m["fn"]
    return 1.0 if denom == 0 else m["tp"] / denom


def tnr(humano: list[bool], judge: list[bool]) -> float:
    """True negative rate (especificidade): tn / (tn + fp). 1.0 se nao ha negativo real."""
    m = matriz_confusao(humano, judge)
    denom = m["tn"] + m["fp"]
    return 1.0 if denom == 0 else m["tn"] / denom


def _acordo_observado(a: list[bool], b: list[bool]) -> float:
    """Proporcao de itens em que os dois rotuladores concordam (Po)."""
    return sum(1 for x, y in zip(a, b, strict=True) if x == y) / len(a)


def _kappa(a: list[bool], b: list[bool]) -> float:
    """Kappa de Cohen entre dois rotuladores binarios quaisquer (acordo corrigido por acaso).

    kappa = (Po - Pe) / (1 - Pe), Pe = soma sobre as classes de p_a(c)*p_b(c). Quando ambos os
    rotuladores degeneram na MESMA classe unica, Pe=1: por convencao retorna 1.0 (acordo perfeito).
    """
    _validar_pareado(a, b)
    n = len(a)
    po = _acordo_observado(a, b)
    pa_true = sum(a) / n
    pb_true = sum(b) / n
    pe = pa_true * pb_true + (1 - pa_true) * (1 - pb_true)
    if pe >= 1.0:
        return 1.0
    return (po - pe) / (1 - pe)


def kappa_cohen(humano: list[bool], judge: list[bool]) -> float:
    """Kappa de Cohen humano-vs-judge (PURO). >=0.6 e um dos limiares de promocao (ADR 0015)."""
    return _kappa(humano, judge)


def gwet_ac2(humano: list[bool], judge: list[bool]) -> float:
    """Gwet AC2 humano-vs-judge (PURO) -- robusto ao paradoxo do kappa em prevalencia assimetrica.

    Refino 08b §3.1: em rubricas como persona/tom quase tudo passa; o kappa despenca mesmo com Po
    alto. O Gwet AC2 substitui Pe pela chance de acordo de Gwet: Pe_gwet = 2*q*(1-q), onde q e a
    prevalencia MEDIA da classe positiva entre os dois rotuladores. Para 2 categorias o "AC2"
    (ponderado) coincide com o AC1 (pesos identidade), entao implementamos a forma binaria.
    """
    _validar_pareado(humano, judge)
    n = len(humano)
    po = _acordo_observado(humano, judge)
    q = (sum(humano) + sum(judge)) / (2 * n)  # prevalencia media da classe positiva
    pe = 2 * q * (1 - q)
    if pe >= 1.0:
        return 1.0
    return (po - pe) / (1 - pe)


def youden_j(tpr_valor: float, tnr_valor: float) -> float:
    """Youden's J = TPR + TNR - 1 (PURO). Threshold otimo de um judge binario; J=1 e perfeito."""
    return tpr_valor + tnr_valor - 1.0


def acordo_humano_humano(a: list[bool], b: list[bool]) -> float:
    """Kappa entre os DOIS humanos (Fernando x socia) -- o TETO da meta (PURO).

    Refino 08b §3.1: medir ISSO primeiro. Exigir kappa_judge>=0.6 quando os humanos so concordam
    a 0.7 (e fragil) e irrealista; o `kappa_humano` ancora o que e atingivel pelo judge.
    """
    return _kappa(a, b)


def promove_a_blocker(
    tpr_valor: float,
    tnr_valor: float,
    kappa: float,
    *,
    min_tpr: float = 0.9,
    min_tnr: float = 0.85,
    min_kappa: float = 0.6,
) -> bool:
    """Portao de promocao do judge a blocker (ADR 0015): so True se PASSA os tres limiares (PURO).

    TPR>=0.9 (vazamento/quebra de persona), TNR>=0.85, kappa>=0.6 contra o humano. Abaixo de
    qualquer um, o judge permanece ADVISORY (loga+flag, nao bloqueia). E o predicado que decide
    flipar `JUDGE_VINCULANTE` em runners/judge.py.
    """
    return tpr_valor >= min_tpr and tnr_valor >= min_tnr and kappa >= min_kappa
