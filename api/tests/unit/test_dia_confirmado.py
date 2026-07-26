"""A2 — captura determinística do dia (abridor "seria hoje?" + afirmação → assume hoje no belief).

Unit puro (sem DB): exercita o detector `_confirmou_dia_hoje` e o aplicador in-memory
`_aplicar_dia_confirmado`. O objetivo é cortar a re-pergunta "seria hoje?" sem LLM/crédito —
ver o bloco A2 em nos/prepare_context.py.
"""

from dataclasses import replace
from datetime import date
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from barra.agente.contexto import ContextAgente
from barra.agente.nos._contexto_do_turno import ContextoDoTurno
from barra.agente.nos._janela_do_turno import _confirmou_dia_hoje, _ja_sondou_o_dia
from barra.agente.nos.prepare_context import _aplicar_dia_confirmado, _resolver_variaveis
from barra.agente.persona import render_contexto_dinamico

HOJE = date(2026, 6, 16)


class _FakeConnVazio:
    """Vazio em tudo: o atendimento chega por kwarg, nenhuma query precisa responder."""

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> Any:
        class _R:
            async def fetchone(self) -> None:
                return None

            async def fetchall(self) -> list[Any]:
                return []

        return _R()


def _ctx() -> ContextAgente:
    return ContextAgente(
        db_pool=None,  # type: ignore[arg-type]
        redis=None,  # type: ignore[arg-type]
        modelo_id="11111111-1111-1111-1111-111111111111",
        atendimento_id="22222222-2222-2222-2222-222222222222",
        cliente_id="33333333-3333-3333-3333-333333333333",
        turno_id="t",
    )


def _ia(texto: str) -> AIMessage:
    return AIMessage(content=texto)


def _cli(texto: str) -> HumanMessage:
    return HumanMessage(content=texto)


# --- _confirmou_dia_hoje: positivos ---


def test_abridor_seria_hoje_mais_sim():
    msgs = [_cli("oi"), _ia("oii amor 🥰 tudo bem? seria hoje? 😊"), _cli("sim")]
    assert _confirmou_dia_hoje(msgs) is True


def test_variantes_de_afirmacao():
    # "perfeito" entrou com a proveniência do horário (#34: "Posso confirmar às 18h" → "Perfeito")
    # e vale igual aqui — o conjunto de afirmações é compartilhado de propósito: é aceite, não recuo.
    for resp in (
        "isso",
        "pode ser",
        "claro",
        "aham",
        "uhum",
        "é",
        "sim sim",
        "Pode ser!",
        "perfeito",
    ):
        msgs = [_ia("seria hoje?"), _cli(resp)]
        assert _confirmou_dia_hoje(msgs) is True, resp


def test_variantes_do_probe():
    for probe in ("é pra hoje?", "pra hoje?", "é hoje?", "seria hoje amor?"):
        msgs = [_ia(probe), _cli("sim")]
        assert _confirmou_dia_hoje(msgs) is True, probe


def test_probe_na_variante_agora_confirma_o_dia():
    # #35 (24/07): "Seria agora ?" + "sim" é o mesmo par de correferência que "seria hoje ?" — o
    # cliente cravou o dia e o belief tem que trazê-lo em <ja_combinado>.
    for probe in ("Seria agora ?", "Vem agora ?"):
        assert _confirmou_dia_hoje([_ia(probe), _cli("sim")]) is True, probe


def test_afirmacao_com_vocativo():
    msgs = [_ia("seria hoje? 😊"), _cli("sim amor")]
    assert _confirmou_dia_hoje(msgs) is True


def test_par_no_meio_da_janela():
    # O "sim" é confirmado cedo; a re-pergunta acontece turnos depois (no preço).
    msgs = [
        _cli("oi"),
        _ia("oii tudo bem? seria hoje? 😊"),
        _cli("sim"),
        _ia("que delícia 🥰"),
        _cli("quanto é 1h?"),
    ]
    assert _confirmou_dia_hoje(msgs) is True


def test_robusto_a_chunking_de_bolhas():
    # A IA quebra em bolhas: a sondagem e a saudação saem em mensagens separadas.
    msgs = [_ia("oii amor 🥰"), _ia("tudo bem? seria hoje? 😊"), _cli("sim")]
    assert _confirmou_dia_hoje(msgs) is True


def test_burst_do_cliente_tudobem_depois_sim():
    # Caso REAL (trace 4837d789): o cliente responde a pergunta composta "tudo bem? seria hoje?"
    # em DUAS bolhas — "tudobem" e "sim". A afirmação vem precedida da PRÓPRIA bolha anterior do
    # cliente, não da sondagem da IA; o walk-back tem que pular a salva do cliente p/ achar o probe.
    msgs = [
        _cli("oi"),
        _ia("Oii boa noite 🥰"),
        _ia("tudo bem? seria hoje?"),
        _cli("tudobem"),
        _cli("sim"),
    ]
    assert _confirmou_dia_hoje(msgs) is True


# --- _confirmou_dia_hoje: negativos ---


def test_cliente_cita_outro_dia():
    for resp in ("sim, mas amanhã", "pode ser sexta", "isso, semana que vem", "sim dia 20"):
        msgs = [_ia("seria hoje?"), _cli(resp)]
        assert _confirmou_dia_hoje(msgs) is False, resp


def test_burst_que_cita_outro_dia_nao_assume_hoje():
    # Outro dia numa bolha ANTERIOR do burst (não na própria afirmação) → não confirma hoje.
    msgs = [_ia("seria hoje?"), _cli("amanhã"), _cli("sim")]
    assert _confirmou_dia_hoje(msgs) is False


def test_ia_nao_sondou_o_dia():
    msgs = [_ia("quer que eu te mande uma foto? 😊"), _cli("sim")]
    assert _confirmou_dia_hoje(msgs) is False


def test_resposta_nao_e_afirmacao():
    msgs = [_ia("seria hoje?"), _cli("quanto custa?")]
    assert _confirmou_dia_hoje(msgs) is False


def test_afirmacao_sem_sondagem_anterior_do_dia():
    # "sim" responde a IA, mas a bolha anterior não sondou o dia.
    msgs = [_ia("seria hoje?"), _cli("não sei ainda"), _ia("tranquilo, me avisa 😊"), _cli("sim")]
    assert _confirmou_dia_hoje(msgs) is False


def test_janela_vazia_ou_so_cliente():
    assert _confirmou_dia_hoje([]) is False
    assert _confirmou_dia_hoje([_cli("sim")]) is False


# --- _aplicar_dia_confirmado: corrige o contexto do turno só quando deve ---


async def _contexto(**over) -> ContextoDoTurno:
    """Contexto do turno pela fábrica REAL (`_resolver_variaveis` com o conn vazio), ajustado nos
    campos do caso. Construir o dataclass à mão aqui congelaria 40 campos que o teste não usa."""
    base = await _resolver_variaveis(
        _FakeConnVazio(),  # type: ignore[arg-type]
        _ctx(),
        atendimento={"estado": "Triagem"},
    )
    return replace(base, **{"data_desejada": None, "data_atual": HOJE, **over})


async def test_aplica_assume_hoje_quando_confirma():
    v = _aplicar_dia_confirmado(await _contexto(), [_ia("seria hoje?"), _cli("sim")])
    assert v.data_desejada == HOJE


async def test_nao_aplica_se_data_desejada_ja_setada():
    futuro = date(2026, 6, 20)
    v = _aplicar_dia_confirmado(
        await _contexto(data_desejada=futuro), [_ia("seria hoje?"), _cli("sim")]
    )
    assert v.data_desejada == futuro


async def test_nao_aplica_apos_confirmacao():
    v = _aplicar_dia_confirmado(
        await _contexto(estado="Aguardando_confirmacao"), [_ia("seria hoje?"), _cli("sim")]
    )
    assert v.data_desejada is None


async def test_nao_aplica_sem_evidencia():
    v = _aplicar_dia_confirmado(await _contexto(), [_ia("quer uma foto?"), _cli("sim")])
    assert v.data_desejada is None


async def test_nao_aplica_com_data_atual_nula():
    v = _aplicar_dia_confirmado(await _contexto(data_atual=None), [_ia("seria hoje?"), _cli("sim")])
    assert v.data_desejada is None


# --- _ja_sondou_o_dia: guard anti-repetição da sondagem (fix da re-pergunta "seria hoje?") ---


def test_ja_sondou_detecta_probe_da_ia():
    msgs = [_cli("oi"), _ia("oii amor 🥰 tudo bem? seria hoje? 😊"), _cli("tudobem")]
    assert _ja_sondou_o_dia(msgs) is True


def test_ja_sondou_variantes_do_probe():
    for probe in ("é pra hoje?", "pra hoje?", "é hoje?", "seria hoje amor?"):
        assert _ja_sondou_o_dia([_ia(probe), _cli("oi")]) is True, probe


def test_ja_sondou_variante_agora():
    # Regressão do atendimento #35 (24/07): a IA sondou "Seria agora ?" e nunca disse "hoje" — o
    # regex só via "hoje", o guard nunca ligou e ela recolou o empurrão 3x ("Vem agora ?").
    for probe in ("Seria agora ?", "Vem agora ?", "Pode vir agora amor", "seria pra agora?"):
        assert _ja_sondou_o_dia([_ia(probe), _cli("oi")]) is True, probe


def test_ja_sondou_ignora_contraproposta_com_hoje():
    # "vier hoje" é a contraproposta do <desconto>, não a sondagem: `\bvir\b` não casa "vier".
    assert _ja_sondou_o_dia([_ia("Consigo 500 se você vier hoje 😊"), _cli("oi")]) is False


def test_ja_sondou_falso_no_turno_de_abertura():
    # Turno 1: a janela só tem a msg do cliente; a sondagem ainda não foi emitida → abertura livre.
    assert _ja_sondou_o_dia([_cli("oi")]) is False


def test_ja_sondou_ignora_probe_do_cliente():
    # Só conta sondagem da IA (AIMessage): o cliente escrever "hoje?" não é a sondagem dela.
    assert _ja_sondou_o_dia([_cli("é pra hoje?")]) is False


def test_ja_sondou_falso_sem_sondagem():
    msgs = [_cli("oi"), _ia("oii amor, tudo bem? 😊"), _cli("quanto é 1h?")]
    assert _ja_sondou_o_dia(msgs) is False


def test_ja_sondou_janela_vazia():
    assert _ja_sondou_o_dia([]) is False


# --- render: guard anti-repetição entra no contexto dinâmico só depois da sondagem feita ---


def _render_vars(**over):
    base = dict(
        numero_curto=1,
        estado="Triagem",
        tipo_atendimento=None,
        data_desejada=HOJE,
        horario_desejado=None,
        endereco=None,
        bairro=None,
        urgencia=None,
        pix_status="não aplicável",
        slots_faltantes=["ele querer mesmo marcar", "que horas ele quer"],
        proximo_passo="fechar o que falta pra combinar o encontro",
        cliente_nome=None,
        recorrente=False,
        historico_anteriores=None,
        ultimo_motivo_perda=None,
        observacoes_internas=None,
        data_atual=HOJE,
        hora_atual="00:27",
        bloqueios=[],
        disponibilidade=[],
    )
    base.update(over)
    return base


def test_render_injeta_guard_quando_ja_sondou():
    # Reproduz o turno 3 do atendimento 019ece77 (trace prod 9db632c7): dia combinado, sondagem
    # já feita → o contexto dinâmico tem que instruir a NÃO recolar "seria hoje?".
    com = render_contexto_dinamico(dia_ja_sondado=True, **_render_vars())
    assert "ja_sondou_o_dia" in com
    assert "seria hoje" in com.lower()


def test_render_sem_guard_no_turno_de_abertura():
    sem = render_contexto_dinamico(dia_ja_sondado=False, **_render_vars(data_desejada=None))
    assert "ja_sondou_o_dia" not in sem
