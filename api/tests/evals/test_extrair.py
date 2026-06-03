"""Prova o extrator de conversa (evals/diagnostico/extrair.py) -- PURO, roda em `make test`.

O extrator é o que torna o fan-out de root-cause do Loop A viável sem estourar contexto: o transcrito
NUNCA carrega o `prompt_montado` (~24k chars/turno); ele só sai sob `--prompt-do-turno IDX`. Estes
testes cravam exatamente isso (omissão por padrão, acesso pontual por idx) + o veredito no cabeçalho.
"""

import importlib
import sys
from pathlib import Path

_API = Path(__file__).resolve().parents[2]  # api/
if str(_API) not in sys.path:
    sys.path.insert(0, str(_API))

ext = importlib.import_module("evals.diagnostico.extrair")


def _cli(texto):
    return {"papel": "cliente", "texto": texto}


def _ia(texto, idx, **kw):
    return {"papel": "ia", "texto": texto, "idx": idx, **kw}


_PROMPT_GORDO = "X" * 24097  # ~tamanho real do SystemMessage montado


def _conv():
    return {
        "conversa_id": "fixo_zz",
        "cenario": "fixo_zz",
        "turnos": [
            _cli("oi quanto e 1h?"),
            _ia(
                "oi amor, meu cache 800 1h",
                0,
                estado="Triagem",
                ia_pausada=False,
                tools=["consultar_cardapio"],
                escalou=False,
                extracao={"duracao_horas": 1},
                prompt_montado=_PROMPT_GORDO,
                tool_io=[{"tool": "consultar_cardapio", "args": {}, "resultado": "800"}],
            ),
            _cli("faz por 400?"),
            _ia(
                "isso nao da amor",
                1,
                estado="Qualificado",
                ia_pausada=False,
                escalou=True,
                prompt_montado=_PROMPT_GORDO,
                tool_io=[{"tool": "escalar", "args": {"motivo": "fora_de_oferta"}}],
            ),
        ],
    }


def test_transcrito_omite_prompt_montado():
    """O transcrito tem as falas e o tool_io, mas NUNCA o prompt_montado (~24k chars)."""
    t = ext.transcrito(_conv())
    assert "oi amor, meu cache 800 1h" in t
    assert "isso nao da amor" in t
    assert "fora_de_oferta" in t  # tool_io aparece (é pequeno e diagnóstico)
    assert _PROMPT_GORDO not in t  # o gordo NUNCA entra no transcrito
    assert "XXXXXXXXXX" not in t


def test_transcrito_traz_veredito_e_flags():
    """O cabeçalho expõe o veredito determinístico -- terminal/motivo/flags guiam o root-cause."""
    t = ext.transcrito(_conv())
    assert "fixo_zz" in t
    assert "escalada_capacidade" in t  # fora_de_oferta -> capacidade
    assert "escalada_fp_possivel:fora_de_oferta" in t  # o FP do piso vira flag


def test_prompt_do_turno_pontual():
    """`prompt_do_turno` devolve o prompt SÓ do idx pedido; None p/ idx inexistente."""
    c = _conv()
    assert ext.prompt_do_turno(c, 0) == _PROMPT_GORDO
    assert ext.prompt_do_turno(c, 1) == _PROMPT_GORDO
    assert ext.prompt_do_turno(c, 99) is None


def test_achar_por_id_ou_cenario():
    c = _conv()
    assert ext._achar([c], "fixo_zz") is c
    assert ext._achar([c], "inexistente") is None
