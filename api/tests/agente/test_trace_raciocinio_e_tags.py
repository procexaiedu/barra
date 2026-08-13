"""Observabilidade do turno: raciocinio (thinking), tags filtraveis e carimbo de regime.

O que estes testes seguram: o trace do turno so serve para investigar se responder as tres
perguntas que se faz olhando um caso — o que a IA PENSOU (thinking, agora default de prod), o que
ACONTECEU (tags de desfecho) e sob QUAL conduta (regime: modelo + thinking + hash dos prompts).
Cada uma delas ja quebrou em silencio antes: campo que o wrapper nao extrai, tag que so tem UUID,
trace indistinguivel entre duas versoes de prompt.
"""

from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from barra.agente._texto_turno import (
    desfecho_do_turno,
    extracao_do_turno,
    raciocinio_do_turno,
    tags_do_turno,
)
from barra.agente._versao import regime_do_turno, versao_prompts
from barra.agente.nos.output_guard import _zerar_turno

_USAGE = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}


def _ia(texto: str, *, raciocinio: str | None = None, **kw: Any) -> AIMessage:
    """AIMessage COMO SE gerada no turno (usage_metadata e o criterio de `mensagens_do_turno`)."""
    extras = {"reasoning_content": raciocinio} if raciocinio is not None else {}
    return AIMessage(content=texto, usage_metadata=_USAGE, additional_kwargs=extras, **kw)


# --- raciocinio -------------------------------------------------------------------------------


def test_raciocinio_do_turno_coleta_na_ordem_das_passagens() -> None:
    """Uma entrada por passagem do LLM: no ReAct o chat e chamado de novo depois da tool."""
    estado = {
        "messages": [
            _ia("", raciocinio="cliente pediu preco, checar a tabela"),
            ToolMessage(content="ok", tool_call_id="t1"),
            _ia("400 1h amor", raciocinio="a tabela diz 400; responder curto"),
        ]
    }
    assert raciocinio_do_turno(estado) == [
        "cliente pediu preco, checar a tabela",
        "a tabela diz 400; responder curto",
    ]


def test_raciocinio_ignora_historico_reinjetado_e_vazio() -> None:
    """Historico do banco vem SEM usage_metadata (nao e deste turno); rc vazio nao vira entrada.

    O `reasoning_content: ""` e placeholder legitimo do loop de tool aberto (core.llm), nao
    raciocinio — publicar isso no trace seria ruido com cara de dado.
    """
    estado = {
        "messages": [
            AIMessage(
                content="fala antiga", additional_kwargs={"reasoning_content": "de outro turno"}
            ),
            _ia("", raciocinio=""),
            _ia("oi amor"),
        ]
    }
    assert raciocinio_do_turno(estado) == []


def test_raciocinio_vazio_em_non_thinking() -> None:
    """Com `deepseek_thinking_chat=disabled` nao existe o campo — mesmo caminho, lista vazia."""
    assert raciocinio_do_turno({"messages": [_ia("400 1h amor")]}) == []


def test_raciocinio_sobrevive_ao_zeramento_do_turno() -> None:
    """O zeramento (output_guard no despacho da regen, post_process na pausa) preserva
    `additional_kwargs` MENOS o espelho cru dos tool_calls.

    Antes ele recriava a AIMessage sem o dict inteiro e o trace saia `raciocinio: null` em TODO
    turno com regen — a peca que explica a fala, apagada por tabela rasa e sem justificativa
    escrita (loop-massa r2). O descarte dos tool_calls continua (check 5c do coordenador)."""
    msg = AIMessage(
        content="400 1h amor",
        usage_metadata=_USAGE,  # type: ignore[arg-type]
        additional_kwargs={
            "reasoning_content": "a tabela diz 400",
            "tool_calls": [{"id": "c1", "function": {"name": "registrar_extracao"}}],
        },
    )
    zeradas = _zerar_turno([msg])
    assert zeradas[0].content == ""
    assert "tool_calls" not in zeradas[0].additional_kwargs
    assert raciocinio_do_turno({"messages": zeradas}) == ["a tabela diz 400"]


# --- tags ---------------------------------------------------------------------------------------


def test_tags_do_turno_marcam_intencao_e_o_que_aconteceu() -> None:
    estado = {
        "messages": [
            _ia(
                "",
                tool_calls=[
                    {
                        "name": "registrar_extracao",
                        "id": "c1",
                        "args": {"intencao": "agendamento"},
                        "type": "tool_call",
                    }
                ],
            ),
            ToolMessage(content="ERRO: horario cedo demais", tool_call_id="c1"),
            _ia("consigo as 21h amor"),
        ],
        "_reoferta_tentada": True,
    }
    tags = tags_do_turno(estado)
    assert "intencao:agendamento" in tags
    assert "erro_tool" in tags
    assert "reoferta" in tags
    assert "sem_resposta" not in tags


def test_tags_marcam_turno_mudo_e_sem_extracao() -> None:
    """`sem_resposta` e a tag mais cara do vocabulario: o cliente nao recebeu nada.

    E o estado em que o guard zerou a fala (ou o LLM devolveu vazio) — sem esta tag, achar esses
    turnos no painel exige abrir trace por trace.
    """
    tags = tags_do_turno({"messages": [_ia("")], "conversa_crua": [HumanMessage(content="oi")]})
    assert "sem_resposta" in tags
    assert "sem_extracao" in tags


def _extraiu(args: dict[str, Any]) -> AIMessage:
    return _ia(
        "",
        tool_calls=[{"name": "registrar_extracao", "id": "c1", "args": args, "type": "tool_call"}],
    )


def test_tags_leem_o_carimbo_do_state_e_nao_a_mensagem_que_o_guard_reescreveu() -> None:
    """A extracao roda ANTES do guard; no despacho da regen o `_zerar_turno` troca as AIMessages do
    turno por vazias e a varredura de `tool_calls` nao acha mais nada — o trace saia
    `extracao: null` + `sem_extracao` num turno que gravou intencao, valor e duracao (loop-massa
    r2, eixos externo t6 / explorador t7). Com o carimbo no State, o zeramento nao mente mais."""
    args = {"intencao": "cotacao", "valor_acordado": 400, "duracao_horas": 1}
    estado = {
        "messages": _zerar_turno([_extraiu(args)]) + [_ia("400 1h no meu local amor")],
        "_extracao_registrada": args,
    }
    tags = tags_do_turno(estado)
    assert "intencao:cotacao" in tags
    assert "sem_extracao" not in tags


def test_extracao_revertida_nao_ressuscita_pela_varredura() -> None:
    """O ramo de ERRO do `extrair` (ConflitoAgenda etc.) reverte a transacao mas ANEXA ao State a
    AIMessage forcada com o tool_call cru — a varredura-fallback devolvia esse payload como
    "extracao do turno" e o trace publicava intencao/valor que nunca foram gravados (revisao da r2).

    O carimbo negativo (`_extracao_registrada: None`) resolve por PRESENCA da chave: quem passou
    pelo `extrair` decidiu, inclusive quando decidiu "nada"."""
    args = {"intencao": "agendamento", "horario_desejado": "22:00"}
    estado = {
        "messages": [
            _extraiu(args),
            ToolMessage(content="ERRO: horario indisponivel", tool_call_id="c1"),
        ],
        "_extracao_registrada": None,
        "_mute_por_erro_de_tool": True,
    }
    assert extracao_do_turno(estado) is None
    assert desfecho_do_turno(estado).get("extracao") is None
    tags = tags_do_turno(estado)
    assert "sem_extracao" in tags
    assert "intencao:agendamento" not in tags
    # e a varredura segue valendo p/ quem NAO passou pelo `extrair` (State montado a mao)
    assert extracao_do_turno({"messages": [_extraiu(args)]}) == args


def test_sem_extracao_so_quando_nao_houve_registro_nenhum() -> None:
    """A pergunta e sobre o REGISTRO, nao sobre o subset acionavel do desfecho: um payload 100%
    fora da whitelist (`proxima_acao_esperada` + `motivo_perda_candidato`) e extracao normal e
    fazia a tag mentir (loop-massa r2, eixo objetor t1/t4 — extensao do fix F2 da r1)."""
    fora_da_whitelist = {
        "proxima_acao_esperada": "aguardar o dia",
        "motivo_perda_candidato": "preco",
    }
    estado = {"messages": [_ia("poxa amor")], "_extracao_registrada": fora_da_whitelist}
    assert "sem_extracao" not in tags_do_turno(estado)
    # e o turno que de fato nao registrou nada segue tagueado
    assert "sem_extracao" in tags_do_turno({"messages": [_ia("poxa amor")]})


# --- regime -------------------------------------------------------------------------------------


class _SettingsFake:
    deepseek_model_chat = "deepseek-v4-flash"
    deepseek_thinking_chat = "low"


def test_regime_do_turno_carimba_modelo_thinking_e_prompts() -> None:
    regime = regime_do_turno(_SettingsFake())
    assert regime["modelo_llm"] == "deepseek-v4-flash"
    assert regime["thinking"] == "low"
    assert regime["prompts"] == versao_prompts()


def test_regime_tolera_settings_incompleto() -> None:
    """Fakes de Settings dos testes definem so o que usam: carimbo nunca derruba o turno."""
    assert "thinking" not in regime_do_turno(object())


def test_versao_prompts_e_estavel_e_curta() -> None:
    """Hash da arvore: mesmo processo -> mesmo valor (cacheado), 12 hex p/ caber numa tag."""
    v = versao_prompts()
    assert v == versao_prompts()
    assert len(v) == 12


# --- metrica de tokens de raciocinio ------------------------------------------------------------


def test_instrumentar_conta_tokens_de_raciocinio_em_serie_propria() -> None:
    """Serie `reasoning` separada — o peso do raciocinio e a variavel que decide se o thinking paga.

    Nao e parcela extra de custo: ela ja esta dentro de `output_tokens` (o provider a contabiliza
    la), e `calcular_custo_brl` continua lendo o output cheio. Aqui so a visibilidade.
    """
    from uuid import uuid4

    from prometheus_client import REGISTRY

    from barra.agente._instrumentar import instrumentar_tokens

    modelo = f"test-thinking-{uuid4().hex}"
    resp = AIMessage(
        content="400 1h amor",
        usage_metadata={
            "input_tokens": 25,
            "output_tokens": 270,
            "total_tokens": 295,
            "output_token_details": {"reasoning": 256},
        },
    )
    instrumentar_tokens(resp, modelo)
    amostra = lambda tipo: REGISTRY.get_sample_value(  # noqa: E731
        "agente_turno_tokens_total", {"modelo": modelo, "tipo": tipo}
    )
    assert amostra("reasoning") == 256.0
    assert amostra("output") == 270.0  # inclui o raciocinio: nao ha dupla contagem no custo


def test_instrumentar_sem_thinking_nao_cria_serie_reasoning() -> None:
    from uuid import uuid4

    from prometheus_client import REGISTRY

    from barra.agente._instrumentar import instrumentar_tokens

    modelo = f"test-nonthinking-{uuid4().hex}"
    instrumentar_tokens(
        AIMessage(content="oi", usage_metadata=dict(_USAGE)),
        modelo,
    )
    assert (
        REGISTRY.get_sample_value(
            "agente_turno_tokens_total", {"modelo": modelo, "tipo": "reasoning"}
        )
        is None
    )
