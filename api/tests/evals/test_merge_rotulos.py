"""Prova o INNER JOIN puro do merge dos dois exports de rotulo (EVAL-10 / ADR 0015).

Nao toca DB/LLM/rede -- roda no `make test`/CI. `merge_rotulos.py` mora em evals/ (fora do pacote
`barra`) e e stdlib puro (sem import relativo), entao carrega por caminho (igual test_judge.py).
"""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

_MERGE = Path(__file__).resolve().parents[1].parent / "evals" / "calibracao" / "merge_rotulos.py"


def _carregar() -> ModuleType:
    spec = importlib.util.spec_from_file_location("eval_merge_rotulos", _MERGE)
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = modulo
    spec.loader.exec_module(modulo)
    return modulo


merge = _carregar()


def _f(id_, rotulo, **extra):
    return {
        "id": id_,
        "conversa_id": id_.split("::")[0],
        "cenario": "cen",
        "texto_resposta": "oi amor",
        "historico": ["cliente: oi"],
        "rotulo_humano_fernando": rotulo,
        **extra,
    }


def _s(id_, rotulo, **extra):
    return {
        "id": id_,
        "conversa_id": id_.split("::")[0],
        "cenario": "cen",
        "texto_resposta": "oi amor",
        "historico": ["cliente: oi"],
        "rotulo_humano_socia": rotulo,
        **extra,
    }


def test_inner_join_une_as_duas_colunas():
    merged, avisos = merge.merge_golden(
        [_f("c::0", True), _f("c::1", False)],
        [_s("c::0", True), _s("c::1", True)],
    )
    assert len(merged) == 2
    # cada linha tem AS DUAS colunas que calibrar.py exige
    for linha in merged:
        assert "rotulo_humano_fernando" in linha
        assert "rotulo_humano_socia" in linha
        assert "texto_resposta" in linha and "historico" in linha
    by_id = {m["id"]: m for m in merged}
    assert by_id["c::0"]["rotulo_humano_fernando"] is True
    assert by_id["c::0"]["rotulo_humano_socia"] is True
    assert by_id["c::1"]["rotulo_humano_fernando"] is False
    assert by_id["c::1"]["rotulo_humano_socia"] is True
    assert avisos == []


def test_descarta_falas_so_de_um_rotulador_com_aviso():
    # c::1 so foi rotulada por Fernando; c::2 so pela socia -> ambas FORA do golden (com aviso).
    merged, avisos = merge.merge_golden(
        [_f("c::0", True), _f("c::1", True)],
        [_s("c::0", False), _s("c::2", True)],
    )
    assert [m["id"] for m in merged] == ["c::0"]
    texto = "\n".join(avisos)
    assert "c::1" in texto and "Fernando" in texto
    assert "c::2" in texto and "socia" in texto


def test_avisa_quando_campo_compartilhado_diverge():
    lf = _f("c::0", True)
    ls = _s("c::0", True)
    ls["texto_resposta"] = "outra fala"  # nao deviam divergir (mesmo conversas.jsonl)
    merged, avisos = merge.merge_golden([lf], [ls])
    assert len(merged) == 1
    assert merged[0]["texto_resposta"] == "oi amor"  # usa o de Fernando
    assert any("texto_resposta" in a and "difere" in a for a in avisos)


def test_carrega_observacoes_dos_dois():
    merged, _ = merge.merge_golden(
        [_f("c::0", True, observacao_fernando="formal demais")],
        [_s("c::0", False, observacao_socia="quebrou persona")],
    )
    assert merged[0]["observacao_fernando"] == "formal demais"
    assert merged[0]["observacao_socia"] == "quebrou persona"


def test_golden_vazio_quando_nao_ha_interseccao():
    merged, avisos = merge.merge_golden([_f("a::0", True)], [_s("b::0", True)])
    assert merged == []
    assert avisos  # avisa que cada um ficou de fora (no silent cap)
