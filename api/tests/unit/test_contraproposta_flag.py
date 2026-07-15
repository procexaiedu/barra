"""Flag determinística <ja_fez_contraproposta> (padrão A2, agente/CLAUDE.md).

A disciplina "desconto é UMA contraproposta na conversa inteira" (regras.md.j2 <desconto> 3)
dependia da janela de 20 msgs: contraproposta fora da janela → LLM podia ofertar a segunda.
`_tem_contraproposta` detecta a forma canônica ("Consigo 500 se você vier hoje") sobre TODAS
as falas da IA do atendimento; o template injeta a tag instrutiva. Puro, sem DB.
"""

from barra.agente.nos.prepare_context import _tem_contraproposta
from barra.agente.persona import render_contexto_dinamico

# --- detector puro ------------------------------------------------------------------------------


def test_detecta_contraproposta_canonica() -> None:
    assert _tem_contraproposta(["Consigo 500 se você vier hoje 😊"])
    assert _tem_contraproposta(["Poxa amor\n\nConsigo 450 se fechar agora"])
    # acento/caixa não escondem ("CONSIGO", "consigo R$ 400")
    assert _tem_contraproposta(["CONSIGO 400 amor"])
    assert _tem_contraproposta(["consigo r$ 400 pra hoje"])


def test_nao_flaga_recusa_nem_horario_nem_cotacao() -> None:
    # recusa da escada ("não consigo") não é contraproposta
    assert not _tem_contraproposta(["Poxa amor não consigo"])
    # hora não é preço: 1-2 dígitos + h ficam fora do \d{3,}
    assert not _tem_contraproposta(["Consigo às 22h amor", "consigo 14h sim"])
    # confirmação sem número e cotação de tabela (sem "consigo") ficam fora
    assert not _tem_contraproposta(["Consigo sim amor", "600 1h no meu local"])
    assert not _tem_contraproposta([])


def test_uma_fala_com_contraproposta_no_meio_do_historico_flaga() -> None:
    historico = [
        "Oii",
        "600 1h no meu local",
        "Consigo 500 se você vier hoje 😊",
        "Poxa amor não consigo",
    ]
    assert _tem_contraproposta(historico)


# --- render do template -------------------------------------------------------------------------


def _render(**over: object) -> str:
    return render_contexto_dinamico(
        numero_curto=7,
        estado="Qualificado",
        slots_faltantes=[],
        proximo_passo="cravar o horário",
        pix_status="não aplicável",
        **over,
    )


def test_render_flag_injeta_tag_instrutiva() -> None:
    out = _render(ja_fez_contraproposta=True)
    assert "<ja_fez_contraproposta>" in out
    assert "ÚNICA contraproposta" in out
    assert "fora_de_oferta" in out


def test_render_sem_flag_nao_injeta() -> None:
    assert "<ja_fez_contraproposta>" not in _render(ja_fez_contraproposta=False)
    assert "<ja_fez_contraproposta>" not in _render()
