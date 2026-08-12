"""A2 da pergunta de horário: contar as bolhas em que a IA PERGUNTA a hora sem propor nenhuma.

Quando o cliente desconversa (emoji, elogio, "que bom rs"), a IA reperguntava "que horas ?" turno
após turno — e a mesma pergunta em loop é o que mais afasta nessa fase. A disciplina era prosa no
<conducao_da_venda> e dependia de o LLM contar as próprias perguntas dentro da janela; contador é
justamente o que ele não faz bem. O detector alimenta `n_perguntas_de_horario`, e a conduta tem
DOIS degraus (por isso contador, não timestamp): na 1ª ela propõe um horário concreto em vez de
reperguntar; da 2ª em diante não pergunta mais.

Os dois cortes que o detector precisa acertar:
 - a PROPOSTA que já carrega hora ("Consigo às 22h, fecha ?", "Podemos combinar 21h amor ?") não é
   pergunta — `contem_hora_na_mesa` estende a leitura de hora explícita da proveniência do horário,
   e o write-time ainda a mede sobre o TURNO (o chunker parte proposta e pergunta em duas bolhas);
 - a sondagem do DIA ("seria hoje ?", "seria agora ?") tem flag própria (`dia_sondado_em`) e não
   pode dobrar aqui.
"""

from typing import Any

from barra.agente._disciplina import (
    contem_hora_na_mesa,
    contem_hora_na_mesa_no_turno,
    contem_pergunta_de_horario,
    contem_sondagem_dia,
)
from barra.agente.contexto import ContextAgente
from barra.agente.nos.prepare_context import _resolver_variaveis
from barra.agente.persona import render_contexto_dinamico

# --- a pergunta, nas formas do prompt -----------------------------------------------------------


def test_pergunta_canonica_do_prompt_e_pega() -> None:
    # <conducao_da_venda> e os <exemplos>: o empurrão de horário sai assim.
    assert contem_pergunta_de_horario("Seria que horas amor ?")


def test_variantes_da_pergunta_sao_pegas() -> None:
    assert contem_pergunta_de_horario("Qual horário amor ?")
    assert contem_pergunta_de_horario("Que horas você pode vir ?")
    assert contem_pergunta_de_horario("Que horário fica melhor pra você ?")
    assert contem_pergunta_de_horario("Pra que horas seria ?")


def test_proposta_com_hora_nao_e_pergunta() -> None:
    # O que a tag manda fazer no lugar da re-pergunta: propor. Contá-la faria a disciplina se
    # gastar exatamente no turno em que a IA acertou.
    assert not contem_pergunta_de_horario("Consigo às 22h, fecha ?")
    assert not contem_pergunta_de_horario("Podemos combinar 21h amor ?")
    assert not contem_pergunta_de_horario("Posso confirmar às 18h ?")


def test_proposta_com_hora_na_mesma_bolha_da_pergunta_nao_conta() -> None:
    # Bolha que já põe um horário na mesa é proposta, mesmo emendando a pergunta. A segunda forma é
    # a que o prompt manda usar NO LUGAR da re-pergunta ("Podemos combinar 21h amor ?"): a hora vem
    # SEM marcador temporal, fora do alcance de `contem_hora_explicita` — contá-la queimaria o
    # degrau justamente no turno em que a IA acertou.
    assert not contem_pergunta_de_horario("Consigo às 21h amor, ou prefere que horas ?")
    assert not contem_pergunta_de_horario("Podemos combinar 21h amor, ou prefere que horas ?")


def test_hora_na_mesa_cobre_as_formas_da_proposta_e_ignora_o_resto() -> None:
    # O veto que o write-time também mede sobre o TURNO inteiro (workers/envio.py), porque o
    # chunker parte proposta e pergunta em duas bolhas.
    assert contem_hora_na_mesa("Consigo às 21h amor")
    assert contem_hora_na_mesa("Podemos combinar 21h amor ?")
    assert contem_hora_na_mesa("Posso confirmar 17:30 ?")
    assert not contem_hora_na_mesa("Seria que horas amor ?")
    assert not contem_hora_na_mesa("Qual horário amor ?")


def test_veto_do_turno_ignora_a_duracao_da_cotacao() -> None:
    """P1-4c (diagnóstico 11/08): o veto era medido sobre o turno CONCATENADO, e o "1h" da cotação
    ("400 1h no meu local") casava a hora crua — como todo turno de cotação carrega duração, o
    contador ficou vetado para sempre (0 em 21 turnos medidos) e a disciplina anti-loop de horário
    nunca existiu em produção."""
    turno = ["400 1h no meu local", "Seria que horas hoje ?"]
    assert not contem_hora_na_mesa_no_turno(turno)
    # ... e a bolha da pergunta, por si, conta.
    assert contem_pergunta_de_horario(turno[1])


def test_veto_do_turno_preserva_a_proposta_partida_em_duas_bolhas() -> None:
    # O que o veto por turno existe para proteger: o molde do <conducao_da_venda> sai partido pelo
    # chunker e a 2ª bolha sozinha contaria a pergunta que a 1ª já respondeu com um horário.
    assert contem_hora_na_mesa_no_turno(["Consigo às 21h amor", "ou prefere que horas ?"])
    assert contem_hora_na_mesa_no_turno(["Podemos combinar 21h amor ?"])
    # Cotação + proposta no mesmo turno: a duração some, o horário fica.
    assert contem_hora_na_mesa_no_turno(["400 1h no meu local", "Consigo às 21h amor"])


def test_afirmacao_sem_interrogacao_nao_conta() -> None:
    # O empurrão de horário SEMPRE acaba em "?" (<conducao_da_venda>); sem ele a bolha é outra
    # coisa (mesmo corte do `_PEDE_FECHAMENTO`).
    assert not contem_pergunta_de_horario("Me avisa que horas você sai amor")


# --- a fronteira com a sondagem do DIA, que tem flag própria ------------------------------------


def test_sondagem_do_dia_nao_conta_como_pergunta_de_horario() -> None:
    # "seria hoje ?"/"seria agora ?" é a MESMA sondagem do <ja_sondou_o_dia> (persona <voz>): uma
    # vez na conversa inteira, com coluna própria (`dia_sondado_em`). Contar aqui dobraria a
    # disciplina e gastaria a pergunta de horário antes de ela ser feita.
    assert contem_sondagem_dia("Seria agora amor ?")
    assert not contem_pergunta_de_horario("Seria agora amor ?")

    assert contem_sondagem_dia("Seria hoje ?")
    assert not contem_pergunta_de_horario("Seria hoje ?")


def test_pergunta_de_horario_nao_conta_como_sondagem_do_dia() -> None:
    # O outro lado da fronteira: a hora não é o dia.
    assert contem_pergunta_de_horario("Seria que horas amor ?")
    assert not contem_sondagem_dia("Seria que horas amor ?")


def test_pergunta_de_dia_nao_conta() -> None:
    # Nem toda pergunta de agenda é de HORA — "que dia" segue livre.
    assert not contem_pergunta_de_horario("Seria que dia amor ?")


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


async def test_n_perguntas_le_coluna_e_reseta_na_recorrencia() -> None:
    perguntou = await _resolver({"n_perguntas_de_horario": 2})
    novo = await _resolver({})  # atendimento novo do mesmo par nasce zerado

    assert perguntou.n_perguntas_de_horario == 2
    assert novo.n_perguntas_de_horario == 0


def _render(**over: object) -> str:
    return render_contexto_dinamico(
        numero_curto=7,
        estado="Qualificado",
        slots_faltantes=[],
        proximo_passo="cravar o horário",
        pix_status="não aplicável",
        **over,
    )


def test_render_primeira_pergunta_manda_propor() -> None:
    out = _render(n_perguntas_de_horario=1)
    assert '<ja_perguntou_o_horario n="1">' in out
    assert "proponha VOCÊ um horário" in out


def test_render_segunda_pergunta_proibe_reperguntar() -> None:
    out = _render(n_perguntas_de_horario=2)
    assert '<ja_perguntou_o_horario n="2">' in out
    assert "NÃO pergunte o horário de novo" in out


def test_render_sem_pergunta_nao_injeta_tag() -> None:
    assert "<ja_perguntou_o_horario" not in _render(n_perguntas_de_horario=0)
    assert "<ja_perguntou_o_horario" not in _render()
