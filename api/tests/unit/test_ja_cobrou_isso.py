"""`<ja_cobrou_isso>`: o carimbo determinístico do belief estacionário (campanha 13/08, FIX 2).

Defeito medido em 915 turnos com prompt capturado: quando a FSM trava, o belief reemite a MESMA
ordem byte-idêntica turno após turno (25% -> 93% de `<proximo_passo>` igual ao do turno anterior,
run máximo de 17) e o modelo obedece, porque a conversa é ~1% do prompt e o belief pesa 10x mais
que ela. O sintoma na bolha é a cobrança repetida — `c3-lote/eb02_139384791793838` pediu confirmação
em três turnos ("Fechamos 11h então ?", "Me confirma que eu te passo o endereço", "Me confirma que
eu já te passo o endereço") enquanto o cliente já tinha dito "Pode fechar".

O contador é DERIVADO da janela contígua, nunca inferido pelo modelo e nunca carimbado no State (o
grafo compila sem checkpointer: o State morre no fim do turno). Ele prova duas coisas, as duas
verificáveis: `<ainda_falta>` está cheio AGORA e os N últimos turnos DELA, seguidos, saíram pedindo.

Os dois lados do teste, que é o que a instrução nova precisa acertar:
  - repetição detectada -> o bloco aparece e manda mudar a FORMA;
  - primeira emissão -> o bloco NÃO aparece (senão vira tique, `conduta_nova_no_prompt_vira_tique`);
  - ele desconversou/sumiu -> o bloco aparece MAS o objetivo continua de pé (o `<ainda_falta>` não
    sai do prompt e o texto diz, com todas as letras, que o item continua devido).
"""

import dataclasses as dc
import re
from datetime import UTC, datetime, time, timedelta
from typing import Any

from jinja2 import meta

from barra.agente.nos._contexto_do_turno import ContextoDoTurno
from barra.agente.nos.prepare_context import (
    _e_cobranca,
    _falas_da_conversa_contigua,
    _turnos_cobrando_o_mesmo,
    _turnos_dela,
)
from barra.agente.persona import _env, render_contexto_dinamico
from barra.dominio.conversas.modelos import DirecaoMensagem

_AGORA = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)


def _dela(texto: str) -> tuple[bool, str]:
    return (True, texto)


def _dele(texto: str) -> tuple[bool, str]:
    return (False, texto)


def _conta(falas: list[tuple[bool, str]], **over: Any) -> int:
    kwargs: dict[str, Any] = {"ha_pendencia": True, "aguarda_confirmacao_da_hora": False}
    kwargs.update(over)
    return _turnos_cobrando_o_mesmo(falas, **kwargs)


# --------------------------------------------------------------------- agrupamento em turnos DELA


def test_bolhas_seguidas_dela_sao_UM_turno() -> None:
    """A janela é uma linha por bolha e ela emite 2-4 por turno: sem agrupar, um único turno de
    três bolhas já contaria como três cobranças."""
    falas = [_dele("oi"), _dela("Oii amor"), _dela("Consigo às 21h, fecha ?"), _dele("legal")]
    assert _turnos_dela(falas) == [["Oii amor", "Consigo às 21h, fecha ?"]]


def test_turnos_dela_saem_em_ordem_cronologica() -> None:
    falas = [_dela("a ?"), _dele("x"), _dela("b ?"), _dele("y"), _dela("c ?")]
    assert _turnos_dela(falas) == [["a ?"], ["b ?"], ["c ?"]]


# ------------------------------------------------------------------------------ o que é cobrança


def test_pergunta_e_cobranca() -> None:
    assert _e_cobranca(["400 1h então amor", "Consigo às 11h, fecha ?"]) is True


def test_pedido_imperativo_e_cobranca_mesmo_sem_interrogacao() -> None:
    """O par t11/t12 do caso real não tem `?` — "Me confirma que eu te passo o endereço" é pedido,
    e é justamente o que o detector de eco do guard deixa passar."""
    assert _e_cobranca(["Me confirma que eu te passo o endereço certinho"]) is True
    assert _e_cobranca(["Me passa o endereço do hotel amor"]) is True


def test_fala_sem_pedido_nao_e_cobranca() -> None:
    assert (
        _e_cobranca(["Sou sua no período combinado rs", "Vem pra cá que você vai gostar"]) is False
    )


# --------------------------------------------------------------------------------- a contagem


def test_primeira_emissao_nao_chega_no_limiar() -> None:
    """UM turno cobrando é a conduta normal (o empurrão do fechamento) — o bloco não pode acender."""
    falas = [_dele("oi"), _dela("Consigo às 21h, fecha ?"), _dele("vou ver")]
    assert _conta(falas) == 1


def test_dois_turnos_seguidos_cobrando_acendem_o_carimbo() -> None:
    falas = [
        _dele("oi"),
        _dela("Consigo às 21h, fecha ?"),
        _dele("Tem estacionamento?"),
        _dela("Me confirma que eu te passo o endereço"),
        _dele("Certo"),
    ]
    assert _conta(falas) == 2


def test_turno_dela_sem_cobranca_quebra_o_run() -> None:
    """O contador ZERA sozinho quando ela muda de jogada — senão o carimbo vira outro latch,
    que é exatamente o defeito que ele corrige."""
    falas = [
        _dele("oi"),
        _dela("Consigo às 21h, fecha ?"),
        _dele("Tem estacionamento?"),
        _dela("Isso eu confirmo quando chegar rs"),
        _dele("Certo"),
    ]
    assert _conta(falas) == 0


def test_sem_pendencia_no_belief_nao_ha_nada_a_carimbar() -> None:
    """`<ainda_falta>` vazio = o pedido foi atendido: a repetição acabou, o bloco some."""
    falas = [
        _dele("oi"),
        _dela("Consigo às 21h, fecha ?"),
        _dele("pode ser"),
        _dela("Me confirma que eu te passo o endereço"),
        _dele("fechado"),
    ]
    assert _conta(falas, ha_pendencia=False) == 0


def test_pausa_de_6h_zera_a_conversa_contigua() -> None:
    """A régua é a MESMA do piso de horário (`_GAP_PAUSA`): o que ela cobrou antes de um sumiço de
    seis horas não é "cobrança repetida" na conversa que recomeçou."""
    base = _AGORA

    def _linha(direcao: DirecaoMensagem, texto: str, minutos: int) -> dict[str, Any]:
        return {
            "direcao": direcao,
            "conteudo": texto,
            "created_at": base + timedelta(minutes=minutos),
        }

    linhas = [
        _linha(DirecaoMensagem.cliente, "oi", 0),
        _linha(DirecaoMensagem.ia, "Consigo às 21h, fecha ?", 1),
        _linha(DirecaoMensagem.cliente, "vou ver", 2),
        _linha(DirecaoMensagem.ia, "Me confirma que eu te passo o endereço", 3),
        # sete horas depois: outra conversa, do ponto de vista da janela
        _linha(DirecaoMensagem.cliente, "oi de novo", 7 * 60),
    ]
    assert _conta(_falas_da_conversa_contigua(linhas)) == 0


# --------------------------------------- teto: ela não cobra confirmação de hora que não existia


def test_confirmacao_da_hora_conta_so_depois_de_a_hora_entrar() -> None:
    """`horario_desejado` gravado e não evidenciado é a pré-condição que trava a FSM em
    `Qualificado`. Sem o teto, o carimbo herdaria a conversa inteira e diria "você já pediu isto
    quatro vezes" no primeiro turno em que a hora aparece."""
    falas = [
        _dele("oi"),
        _dela("Quer ficar 1h ou 2h comigo ?"),
        _dele("1h"),
        _dela("400 1h então amor"),
        _dela("Consigo às 11h, fecha ?"),
        _dele("Legal"),
    ]
    # dois turnos dela cobrando, mas a hora só entrou no segundo
    assert _conta(falas, aguarda_confirmacao_da_hora=True) == 1
    # sem o gate da hora, o run cheio vale
    assert _conta(falas) == 2


def test_sem_hora_nenhuma_na_janela_o_carimbo_da_confirmacao_nao_acende() -> None:
    """Fail-closed: horário gravado que não aparece em bolha nenhuma da janela contígua (veio do
    painel, ou já deslizou pra fora) não sustenta a afirmação "você já cobrou isto N vezes"."""
    falas = [
        _dele("oi"),
        _dela("Fecha comigo ?"),
        _dele("talvez"),
        _dela("Me confirma amor"),
        _dele("hm"),
    ]
    assert _conta(falas, aguarda_confirmacao_da_hora=True) == 0


def test_caso_real_c3_lote_eb02_139384791793838() -> None:
    """O caso do M5 do diagnóstico, com as falas literais: no turno em que ela repetiu "Me confirma
    que eu já te passo o endereço" o carimbo já valia 3."""
    falas = [
        _dela("400 1h então amor"),
        _dela("Consigo às 11h, fecha ?"),
        _dele("Legal"),
        _dele("Duas finalizações?"),
        _dela("Sou sua no período combinado rs"),
        _dela("Vem pra cá que você vai gostar"),
        _dele("Está disponível ?"),
        _dela("Estou sim"),
        _dele("Chegaria em quanto tempo?"),
        _dela("Assim que você confirmar eu já chamo o uber amor"),
        _dela("Fechamos 11h então ?"),
        _dele("Pode fechar"),
        _dele("Qual o hotel?"),
        _dela("Me passa o endereço do hotel amor"),
        _dele("Não"),
        _dela("Me confirma que eu te passo o endereço certinho"),
        _dele("Certo"),
        _dele("Tem estacionamento?"),
    ]
    assert _conta(falas, aguarda_confirmacao_da_hora=True) == 3


# ------------------------------------------------------------------------------ o bloco no prompt

_NEUTRO: dict[str, Any] = {
    "agora": _AGORA,
    "data_atual": "2026-08-14",
    "hora_atual": "12:00",
    "escada_estado": "inteira",
    "estado": "Qualificado",
    "pix_status": "ainda não pedido",
}


def _contexto(**over: Any) -> ContextoDoTurno:
    valores: dict[str, Any] = {}
    for campo in dc.fields(ContextoDoTurno):
        if campo.default is not dc.MISSING or campo.default_factory is not dc.MISSING:
            continue
        if campo.name in _NEUTRO:
            valores[campo.name] = _NEUTRO[campo.name]
        elif campo.name in over:
            continue
        else:
            tipo = campo.type
            valores[campo.name] = (
                False
                if tipo is bool
                else 0
                if tipo in (int, float)
                else []
                if getattr(tipo, "__origin__", None) is list
                else None
            )
    return ContextoDoTurno(**{**valores, **over})


def _render(**over: Any) -> str:
    return render_contexto_dinamico(**_contexto(**over).como_variaveis())


_FALTA = ["ele confirmar o horário que ficou na mesa"]


def test_bloco_ausente_na_primeira_emissao() -> None:
    assert "<ja_cobrou_isso" not in _render(slots_faltantes=_FALTA, turnos_cobrando_o_mesmo=1)
    assert "<ja_cobrou_isso" not in _render(slots_faltantes=_FALTA, turnos_cobrando_o_mesmo=0)


def test_bloco_presente_na_segunda_repeticao() -> None:
    bloco = _render(slots_faltantes=_FALTA, turnos_cobrando_o_mesmo=2)
    assert '<ja_cobrou_isso turnos="2">' in bloco
    assert "</ja_cobrou_isso>" in bloco


def test_o_bloco_proibe_repetir_a_cobranca_e_prescreve_o_avanco() -> None:
    """Diz o que NÃO fazer e o que fazer no lugar — e prescreve a INTENÇÃO, nunca uma fala pronta
    (`conduta_nova_no_prompt_vira_tique`): nenhuma frase de exemplo entre aspas na voz dela."""
    bloco = _render(slots_faltantes=_FALTA, turnos_cobrando_o_mesmo=3)
    assert "MESMA cobrança" in bloco  # o que não fazer
    assert "atenda o que ele acabou de trazer" in bloco  # o que fazer no lugar
    assert "<agenda>" in bloco  # de onde o avanço concreto sai
    # o bloco não entrega FALA: as únicas coisas entre aspas são as duas que ela NÃO deve dizer
    trecho = bloco.split('<ja_cobrou_isso turnos="3">')[1].split("</ja_cobrou_isso>")[0]
    assert re.findall(r'"([^"]+)"', trecho) == ["já te perguntei", "de novo"]


def test_o_objetivo_sobrevive_quando_ele_desconversa_ou_some() -> None:
    """Efeito colateral que o bloco NÃO pode ter: se a repetição existe porque ele não respondeu,
    o próximo passo continua devido — o bloco muda a forma, não o alvo."""
    bloco = _render(slots_faltantes=_FALTA, turnos_cobrando_o_mesmo=4)
    assert "OBJETIVO não muda" in bloco
    assert "desconversou, respondeu outra coisa ou sumiu" in bloco
    # e o item continua listado no prompt, no lugar de sempre
    assert "<item>ele confirmar o horário que ficou na mesa</item>" in bloco


def test_sem_pendencia_o_bloco_nao_sai_nem_com_o_contador_alto() -> None:
    """Blindagem do render contra um contador que sobreviva ao fim da pendência: sem
    `<ainda_falta>` o texto do bloco ("o que está em ainda falta continua faltando") seria falso."""
    bloco = _render(slots_faltantes=[], turnos_cobrando_o_mesmo=5)
    assert "<nada>tudo desta etapa já está combinado</nada>" in bloco
    assert "<ja_cobrou_isso" not in bloco


# ------------------------------------- <hora>: aceite provável só MODULA A REDAÇÃO (14/08) -------
# O detector (`aceite_provavel_sem_confirmacao`, nos/_janela_do_turno) e a medição que o separou do
# gatilho de ESTADO são território do agente do detector — aqui só se testa o que ele faz ao TEXTO.
# O latch não se quebra pelo detector (171 de 180 turnos travados continuam travados); o que muda é
# que o belief para de AFIRMAR "espere o sim" nos turnos em que o cliente já ficou de fato.

_CATEGORICO = "ofereça esta hora e espere o sim"
_SUAVE = "trate como provavelmente combinada"


def _com_hora(**over: Any) -> str:
    base: dict[str, Any] = {
        "horario_desejado": time(21, 0),
        "horario_evidenciado": False,
        "horario_ja_combinado": False,
        "slots_faltantes": _FALTA,
    }
    return _render(**{**base, **over})


def test_sem_o_sinal_o_texto_de_hoje_continua_identico() -> None:
    """`aceite_provavel_da_hora` False é o default e é a maioria dos turnos: onde ele não deu sinal
    nenhum, cobrar continua certo e nada muda."""
    bloco = _com_hora(aceite_provavel_da_hora=False)
    assert _CATEGORICO in bloco
    assert _SUAVE not in bloco


def test_com_o_sinal_o_status_para_de_mandar_esperar_o_sim() -> None:
    bloco = _com_hora(aceite_provavel_da_hora=True)
    assert _SUAVE in bloco
    assert _CATEGORICO not in bloco
    assert "não peça confirmação de novo" in bloco
    assert "21:00" in bloco


def test_o_status_suave_prescreve_intencao_e_nao_entrega_fala() -> None:
    """Mesma lei do `<ja_cobrou_isso>`: manda a INTENÇÃO (andar pelo próximo passo, a hora entrando
    de passagem) e não uma bolha pronta — nada entre aspas na voz dela."""
    status = _com_hora(aceite_provavel_da_hora=True).split('<hora status="')[1].split('">')[0]
    assert '"' not in status
    assert "o turno anda pelo próximo passo concreto do encontro" in status.lower()
    assert "se ele corrigir a hora, manda o que ele disser" in status.lower()


def test_o_status_suave_nao_narra_mecanica_do_sistema() -> None:
    """`mecanica_do_sistema_no_prompt_vira_narracao`: a ressalva de que isto NÃO promove estado é
    para o próximo DEV (comentário Jinja + docstrings), nunca para o modelo — ela narraria."""
    status = _com_hora(aceite_provavel_da_hora=True).split('<hora status="')[1].split('">')[0]
    for mecanica in ("sistema", "registro", "gravad", "reserva", "detector", "estado"):
        assert mecanica not in status.lower(), mecanica


def test_o_sinal_nao_mexe_no_status_quando_a_hora_ja_esta_combinada() -> None:
    """Depois de `Aguardando_confirmacao` o `<hora>` sai sem status nenhum — o sinal fraco não
    reabre o que a FSM já fechou."""
    bloco = _com_hora(
        aceite_provavel_da_hora=True, horario_ja_combinado=True, horario_evidenciado=True
    )
    assert "<hora>21:00</hora>" in bloco


# ------------------------------------------------- composição: exatamente UM bloco diz "não cobre"


def test_o_status_suave_cala_o_ja_cobrou_isso() -> None:
    """Bicondicional, não terceira cópia da condição: quando o status suave sai, ele já diz "não
    peça confirmação de novo" — e diz melhor, nomeando a hora e o próximo passo. Empilhar o outro
    bloco poria duas instruções no mesmo turno, uma dizendo que o item continua devido e a outra
    mandando tratá-lo como combinado."""
    bloco = _com_hora(aceite_provavel_da_hora=True, turnos_cobrando_o_mesmo=3)
    assert _SUAVE in bloco
    assert "<ja_cobrou_isso" not in bloco


def test_sem_o_status_suave_o_ja_cobrou_isso_continua_acendendo() -> None:
    bloco = _com_hora(aceite_provavel_da_hora=False, turnos_cobrando_o_mesmo=3)
    assert _CATEGORICO in bloco
    assert '<ja_cobrou_isso turnos="3">' in bloco


def test_hora_ainda_nao_gravada_deixa_o_ja_cobrou_isso_de_pe() -> None:
    """Medido no corpus: em 8 dos 21 turnos com aceite provável a hora nem chegou ao belief (a FSM
    não promoveu), então o status suave NÃO sai. Calar os dois deixaria o turno sem instrução
    nenhuma sobre a repetição."""
    bloco = _render(
        slots_faltantes=["que horas ele quer"],
        horario_desejado=None,
        aceite_provavel_da_hora=True,
        turnos_cobrando_o_mesmo=3,
    )
    assert "<hora" not in bloco
    assert '<ja_cobrou_isso turnos="3">' in bloco


def test_a_bicondicional_vale_na_matriz_inteira() -> None:
    """Amarra os dois blocos de uma vez: com o contador aceso, `<ja_cobrou_isso>` aparece se e
    somente se o status suave do `<hora>` NÃO apareceu."""
    for tem_hora in (True, False):
        for provavel in (True, False):
            for evidenciado in (True, False):
                bloco = _render(
                    slots_faltantes=_FALTA,
                    horario_desejado=time(21, 0) if tem_hora else None,
                    horario_evidenciado=evidenciado,
                    horario_ja_combinado=False,
                    aceite_provavel_da_hora=provavel,
                    turnos_cobrando_o_mesmo=3,
                )
                caso = f"{tem_hora=} {provavel=} {evidenciado=}"
                assert (_SUAVE in bloco) == (tem_hora and provavel and not evidenciado), caso
                assert ("<ja_cobrou_isso" in bloco) == (_SUAVE not in bloco), caso


# ---------------------------------------------------------------- o sinal NÃO chega ao extrator


def test_o_sinal_fraco_nao_entra_no_bloco_que_o_extrator_le() -> None:
    """A trava contra "melhorar" isto promovendo estado. O `<ja_registrado>` é o que o EXTRATOR lê,
    e é a extração que grava `horario_evidenciado` / promove a FSM / reserva agenda. Se alguém
    passar o sinal fraco para lá, a redação vira registro — e um falso positivo custa a agenda da
    modelo bloqueada por quem não combinou nada."""
    fonte = _env.loader.get_source(_env, "ja_registrado.md.j2")[0]
    lidas = meta.find_undeclared_variables(_env.parse(fonte))
    assert "aceite_provavel_da_hora" not in lidas
    assert "turnos_cobrando_o_mesmo" not in lidas
