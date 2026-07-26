"""A2 do resgate: detectar a bolha em que a IA pergunta o MOTIVO da despedida.

O <desconto> manda resgatar a despedida educada ("obrigado, fica pra próxima") perguntando o
motivo — e perguntar duas vezes é o oposto do que o resgate quer: vira cobrança. A pergunta sai no
FIM da negociação e, quando ele volta depois de um silêncio, ela já deslizou pra fora da janela de
20 msgs — que é exatamente quando a IA repete. O detector alimenta `motivo_resgate_perguntado_em`,
a memória durável que a janela não consegue ser.

O corte que ele precisa acertar: a pergunta do motivo conta; a recusa de desconto ("Poxa amor não
consigo") e o empurrão de fechamento ("Podemos confirmar 21h ?") NÃO — as três moram no mesmo
trecho da conversa, e carimbar qualquer uma das outras calaria um resgate que nunca aconteceu.
"""

from datetime import UTC, datetime
from typing import Any

from barra.agente._disciplina import contem_pergunta_do_motivo_do_resgate
from barra.agente.contexto import ContextAgente
from barra.agente.nos.prepare_context import _resolver_variaveis
from barra.agente.persona import render_contexto_dinamico

_TS = datetime(2026, 7, 26, 4, 0, tzinfo=UTC)  # instante qualquer: presença = flag ligada

# --- a pergunta do motivo, nas formas do prompt --------------------------------------------------


def test_pergunta_canonica_do_prompt_e_pega() -> None:
    assert contem_pergunta_do_motivo_do_resgate("Poxa, não gostou de mim?")


def test_variantes_da_pergunta_sao_pegas() -> None:
    # Formas que o modelo produz em volta da canônica — mesma família: ou ele "não gostou", ou ela
    # pede o motivo com todas as letras, ou pergunta o que ela fez.
    assert contem_pergunta_do_motivo_do_resgate("Não gostou de mim amor ?")
    assert contem_pergunta_do_motivo_do_resgate("Não gostou mais de mim ?")
    assert contem_pergunta_do_motivo_do_resgate("Posso saber o motivo amor ?")
    assert contem_pergunta_do_motivo_do_resgate("Qual o motivo ?")
    assert contem_pergunta_do_motivo_do_resgate("Desistiu de mim amor ?")
    assert contem_pergunta_do_motivo_do_resgate("Foi alguma coisa que eu falei ?")


# --- as vizinhas de trecho, que NÃO são o resgate ------------------------------------------------


def test_recusa_de_desconto_nao_conta_como_pergunta_do_motivo() -> None:
    # <desconto> 5: mesma fase da conversa e o MESMO "Poxa amor" da forma canônica do resgate.
    assert not contem_pergunta_do_motivo_do_resgate("Poxa amor não consigo")
    assert not contem_pergunta_do_motivo_do_resgate(
        "Poxa amor não consigo, esse é meu melhor valor"
    )


def test_contraproposta_com_a_negacao_dentro_nao_conta() -> None:
    # A contraproposta cabe numa bolha com a negação E o "?": "não gostou" solto casaria e queimaria
    # o resgate no turno em que ela está justamente vendendo. O corte é o "de mim" — o resgate
    # pergunta por ELA, a contraproposta fala do valor.
    assert not contem_pergunta_do_motivo_do_resgate(
        "Poxa amor, se você não gostou do valor consigo 500, fecha ?"
    )


def test_negacao_do_objeto_nao_conta_como_resgate() -> None:
    # Pós-book, "Não curtiu as fotos ?" mede a reação à mídia — é venda, não o resgate da despedida;
    # e a cobrança da espera ("Desistiu de vir ?") é outra fase inteira. Carimbar qualquer uma
    # calaria a pergunta que o <desconto> ainda vai precisar fazer.
    assert not contem_pergunta_do_motivo_do_resgate("Não curtiu as fotos ?")
    assert not contem_pergunta_do_motivo_do_resgate("Desistiu de vir amor ?")


def test_empurrao_de_fechamento_nao_conta_como_pergunta_do_motivo() -> None:
    # <conducao_da_venda>: pergunta, na mesma fase, e não é resgate nenhum.
    assert not contem_pergunta_do_motivo_do_resgate("Podemos confirmar 21h ?")
    assert not contem_pergunta_do_motivo_do_resgate("Seria que horas amor ?")
    assert not contem_pergunta_do_motivo_do_resgate("Vem hoje ?")


def test_perguntar_se_ele_gostou_nao_conta() -> None:
    # <midia>: depois do book ela pergunta se ele gostou — é venda, não resgate. O corte é a
    # NEGAÇÃO; carimbar aqui gastaria o resgate antes de a despedida existir.
    assert not contem_pergunta_do_motivo_do_resgate("Gostou do que viu amor ?")
    assert not contem_pergunta_do_motivo_do_resgate("Gostou de mim ?")


def test_desculpa_pessoal_de_indisponibilidade_nao_conta() -> None:
    # Conduta de indisponibilidade, o outro "Poxa amor" do prompt.
    assert not contem_pergunta_do_motivo_do_resgate("Poxa amor às 20h estou jantando")


# --- read-time: a coluna vira campo do turno e tag no contexto ----------------------------------


class _FakeConnVazio:
    """Vazio em tudo: a flag chega por kwarg (coluna do atendimento), não por query."""

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> Any:
        class _R:
            async def fetchone(self) -> None:
                return None

            async def fetchall(self) -> list[Any]:
                return []

        return _R()


def _ctx() -> ContextAgente:
    return ContextAgente(
        atendimento_id="22222222-2222-2222-2222-222222222222",
        db_pool=None,  # type: ignore[arg-type]
        redis=None,  # type: ignore[arg-type]
        modelo_id="11111111-1111-1111-1111-111111111111",
        cliente_id="33333333-3333-3333-3333-333333333333",
        turno_id="t",
    )


async def _resolver(atendimento: dict[str, Any]) -> Any:
    return await _resolver_variaveis(
        _FakeConnVazio(),  # type: ignore[arg-type]
        _ctx(),
        atendimento=atendimento,
    )


async def test_motivo_ja_perguntado_le_coluna_e_reseta_na_recorrencia() -> None:
    perguntou = await _resolver({"motivo_resgate_perguntado_em": _TS})
    nao_perguntou = await _resolver({})  # atendimento novo do mesmo par nasce sem a flag

    assert perguntou.motivo_resgate_ja_perguntado is True
    assert nao_perguntou.motivo_resgate_ja_perguntado is False


def _render(**over: object) -> str:
    return render_contexto_dinamico(
        numero_curto=7,
        estado="Qualificado",
        slots_faltantes=[],
        proximo_passo="fechar o horário",
        pix_status="não aplicável",
        **over,
    )


def test_render_motivo_perguntado_injeta_tag() -> None:
    out = _render(motivo_resgate_ja_perguntado=True)
    assert "<ja_perguntou_o_motivo>" in out
    assert "não repita" in out


def test_render_sem_pergunta_nao_injeta_tag() -> None:
    assert "<ja_perguntou_o_motivo>" not in _render(motivo_resgate_ja_perguntado=False)
    assert "<ja_perguntou_o_motivo>" not in _render()
