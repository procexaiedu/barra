"""A janela da agenda é UM número; guarda contra ele voltar a viver em oito lugares.

O contexto do turno traz a agenda pronta das próximas N horas e a tool `consultar_agenda` existe
para o que passa disso. Enquanto N era literal em cada site, mudar a query sem mudar os textos
fazia o prompt e a descrição da tool MENTIREM em silêncio -- o aviso já estava escrito em
prepare_context, sem nada que o garantisse.
"""

from pathlib import Path

from barra.agente.ferramentas.leitura import consultar_agenda
from barra.agente.persona import (
    JANELA_AGENDA_HORAS,
    render_bloco_da_modelo,
    render_prefixo_geral,
)

_PROMPTS = Path("src/barra/agente/prompts")


def test_prompts_nao_carregam_a_janela_hardcoded() -> None:
    """Os templates leem o global do Jinja; um `48` literal reaparecendo é a regressão."""
    for nome in ("regras.md.j2", "bloco_da_modelo.md.j2", "contexto_dinamico.md.j2"):
        texto = (_PROMPTS / nome).read_text(encoding="utf-8")
        assert "48h" not in texto, f"{nome} voltou a cravar a janela em vez de ler o global"
        assert "{{ janela_agenda_horas }}h" in texto


def test_prefixo_renderiza_a_janela_vigente() -> None:
    assert f"próximas {JANELA_AGENDA_HORAS}h" in render_prefixo_geral()


def test_bloco_da_modelo_renderiza_a_janela_vigente() -> None:
    # sem regra de disponibilidade -> cai no <sem_restricao>, que é onde a janela aparece
    assert f"próximas {JANELA_AGENDA_HORAS}h" in render_bloco_da_modelo(periodo_de_trabalho=None)


def test_descricao_da_tool_concorda_com_a_janela() -> None:
    """A DESC dos args é f-string (acompanha sozinha); a DOCSTRING não pode ser (viraria
    expressão e `__doc__` sumiria, deixando a tool sem a descrição que o LLM lê). Então a
    docstring segue literal e a concordância é garantida AQUI."""
    desc = consultar_agenda.description or ""
    args = str(consultar_agenda.args)

    assert f"próximas {JANELA_AGENDA_HORAS}h" in desc
    assert f"próximas {JANELA_AGENDA_HORAS}h" in args
