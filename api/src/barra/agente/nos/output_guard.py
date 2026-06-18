"""No output_guard: ultima rede ANTES da bolha sair ao cliente (ADR 0016).

Roda no caminho normal de saida (depois do post_process). Recebe o texto final do turno e, em
duas etapas, decide se a bolha pode seguir:

- Etapa 1 (deterministica, barata, sempre): scan de vazamento no TEXTO DE SAIDA -- auto-referencia
  de IA / nome de LLM, fragmento de system/persona, segredo da agenda (revelar estar com outro
  cliente / em outro atendimento, em vez da desculpa pessoal), e dado de OUTRA modelo (nome/numero
  de modelos que nao a do par). Match -> bloqueia.
- Etapa 2 (LLM-judge de AUP, vinculante): so quando a Etapa 1 passa e o texto NAO e uma negacao
  canned (pool curado pula a Etapa 2). Prompt em `prompts/aup_saida.md` (fora do prefixo cacheado
  por-modelo). Violou -> bloqueia. Falha de infra do judge -> DEFAULT SEGURO: bloqueia+escala.

Bloquear = abrir handoff p/ Fernando (ia_pausada=true, mesma porta do disclosure/jailbreak) E
zerar a bolha (mesmo id -> reducer substitui por vazia, igual post_process). O coordenador rele
ia_pausada apos o turno (cinto-suspensorio) e nao despacha. Roteamento SO por Command(goto=END)
-- sem aresta estatica de saida (armadilha do fan-out, graph.py).
"""

import logging
import re
from typing import Any, Literal

from langchain_core.messages import AIMessage
from langgraph.graph import END
from langgraph.runtime import Runtime
from langgraph.types import Command
from pydantic import BaseModel, Field

from barra.core.db import conexao
from barra.core.metrics import AUP_SAIDA_BLOQUEADO, OUTPUT_LEAK_DETECTADO
from barra.settings import get_settings

from .._canned import NEGACOES_CANNED
from .._defesa import escalar_defesa
from .._texto_turno import extrair_texto_do_turno, mensagens_do_turno
from ..contexto import ContextAgente
from ..estado import EstadoAgente
from ..persona import render_aup_saida

logger = logging.getLogger(__name__)

_RESUMO_LEAK = "Output-guard barrou a bolha (vazamento detectado antes do envio)."
_RESUMO_AUP = "Output-guard barrou a bolha (LLM-judge de AUP reprovou antes do envio)."


class _JudgeInseguro(RuntimeError):
    """Judge de AUP nao produziu veredito confiavel (refusal/truncado/parse) -> default seguro."""


# Etapa 1 -- auto-referencia de IA / nomes de LLM no TEXTO DE SAIDA (admissao, nao pergunta do
# cliente: o _classificador casa perguntas; aqui casamos a RESPOSTA vazando identidade).
_MARCADORES_IA = re.compile(
    r"\b(sou (uma? )?(ia|i\.a\.|intelig[êe]ncia artificial|bot|rob[ôo]|chatbot)"
    r"|modelo de linguagem|language model|sou (o|a|um|uma) (claude|gpt|chatgpt|gemini|llama)"
    r"|fui (treinad|program)|sou um (programa|software|assistente virtual)"
    r"|anthropic|openai)\b",
    re.IGNORECASE,
)
# Etapa 1 -- fragmento de system/persona/regras vazando na saida.
_MARCADORES_SYSTEM = re.compile(
    r"(</?persona>|<desconto>|</?regras?>|</?faq>|\[system\]"
    r"|prompt do sistema|system prompt|minhas instru[çc][õo]es|instru[çc][õo]es acima)",
    re.IGNORECASE,
)
# Etapa 1 -- segredo da agenda: a IA recusa horario em bloqueio com DESCULPA PESSOAL (salao,
# jantar, balada) e NUNCA revela que esta com outro cliente / em outro atendimento (CONTEXT.md
# "Agenda — comportamento da IA"). Os scans acima nao pegam essa admissao; aqui casamos as
# n-gramas inequivocas do vazamento. Conservador de proposito (so frases que so podem significar
# "com outro cliente"): a assimetria favorece barrar -- falso-positivo vira handoff (seguro),
# enquanto o vazamento e irreversivel uma vez enviado.
_MARCADORES_OUTRO_CLIENTE = re.compile(
    r"\b("
    r"outr[oa]s? clientes?"
    r"|com (um|uma|outr[oa]|mais um[a]?) cliente"
    r"|com (outr[oa]|mais um[a]?) pessoa"
    r"|(t[ôo]|estou|tenho|t[ôo] com|estou com) (um |uma |o |a |outr[oa] )?cliente"
    # "estou atendendo agora" -- atende ALGUEM. O lookahead protege "te/voce atendendo" (o
    # PROPRIO cliente, fala legitima): so vaza quando o objeto NAO e o interlocutor.
    r"|(t[ôo]|estou) atendendo(?!\s+(voc|vc|te\b|o senhor|a senhora))"
    r"|(em|num|no|noutro|outro|nesse|neste) atendimento"
    r"|no meio de (um |outro )?atendimento"
    r"|atendendo (outr[oa]|um|uma|mais um|algu[ée]m|outr[oa] pessoa|cliente)"
    r")\b",
    re.IGNORECASE,
)


class _VeredictoAup(BaseModel):
    """Saida estruturada da Etapa 2 (judge de AUP vinculante)."""

    viola: bool = Field(description="true se a bolha deve ser BARRADA (viola a AUP)")
    motivo: str = Field(
        description="rotulo curto: ia_self|system_leak|cross_modelo|aup_dura|nenhum"
    )


async def _nomes_outras_modelos(conn: Any, modelo_id: str) -> list[str]:
    """Nomes/numeros de OUTRAS modelos (negativa cross-modelo) -- montada do banco, nao do prompt.

    So nomes com >=4 chars (evita falso-positivo de nome curto/comum em texto coloquial).
    """
    res = await conn.execute(
        "SELECT nome, numero_whatsapp FROM barravips.modelos WHERE id <> %s",
        (modelo_id,),
    )
    termos: list[str] = []
    for r in await res.fetchall():
        nome = (r.get("nome") or "").strip()
        if len(nome) >= 4:
            termos.append(nome)
        numero = (r.get("numero_whatsapp") or "").strip()
        if len(numero) >= 6:
            termos.append(numero)
    return termos


async def _legendas_do_turno(conn: Any, turno_id: str) -> list[str]:
    """Legendas das midias anexadas neste turno (arg `legenda` de enviar_midia, em tool_calls).

    A legenda vai ao cliente como caption FORA da bolha de texto (o coordenador a despacha do
    `tool_calls`, nao do content da AIMessage) -- por isso precisa entrar no scan/judge do guard
    junto com o texto. Escopada por `turno_id` (deterministico): nao traz legenda de turno
    anterior. Espelha `ferramentas.midia._midias_do_turno`.
    """
    res = await conn.execute(
        "SELECT payload->>'legenda' AS legenda FROM barravips.tool_calls "
        "WHERE turno_id = %s AND tool_name = 'enviar_midia'",
        (turno_id,),
    )
    return [leg for r in await res.fetchall() if (leg := (r.get("legenda") or "").strip())]


def tem_marcador_ia(texto: str) -> bool:
    """True se o texto contem auto-referencia de IA / nome de LLM (PURO).

    Usado pela Etapa 1 do guard e reusado pelo eval online de non_disclosure (EVAL-11) como
    rubrica deterministica barata (sem custo de LLM por turno amostrado).
    """
    return bool(_MARCADORES_IA.search(texto))


def tem_marcador_system(texto: str) -> bool:
    """True se o texto vaza fragmento de system/persona/regras (PURO). Mesmo regex da Etapa 1;
    reusado pelo eval online (`online_system_leak`, EVAL-11) — fonte unica do detector."""
    return bool(_MARCADORES_SYSTEM.search(texto))


def tem_marcador_outro_cliente(texto: str) -> bool:
    """True se o texto admite "estou com outro cliente" (segredo da agenda, CONTEXT.md). Mesmo
    regex da Etapa 1; reusado pelo eval online (`online_segredo_agenda`, EVAL-11)."""
    return bool(_MARCADORES_OUTRO_CLIENTE.search(texto))


def _scan_vazamento(texto: str, termos_cross: list[str]) -> str | None:
    """Etapa 1 (PURA): devolve o motivo do vazamento ou None.

    Ordem: ia_self > system > outro_cliente > cross.
    """
    if tem_marcador_ia(texto):
        return "ia_self"
    if tem_marcador_system(texto):
        return "system"
    if tem_marcador_outro_cliente(texto):
        return "outro_cliente"
    alvo = texto.lower()
    for termo in termos_cross:
        if re.search(rf"\b{re.escape(termo.lower())}\b", alvo):
            return "cross_modelo"
    return None


async def _julgar_aup(texto: str, settings: Any) -> _VeredictoAup:
    """Etapa 2: LLM-judge de AUP (Haiku/OpenRouter, structured output). Prompt em aup_saida.md.

    Provider por settings.output_guard_provider: `anthropic` (default, Haiku via ChatAnthropic) ou
    `openrouter` (ChatOpenAI). No ChatOpenAI o structured output usa function-calling explicito
    (`method`), mais robusto que json_schema no roteamento dinamico do OpenRouter.

    SO-03: `include_raw` expoe o motivo de parada da PROPRIA resposta do judge. Recusa
    (refusal/content_filter), truncamento (max_tokens/length) ou falha de parse nao produzem
    veredito confiavel -> levanta `_JudgeInseguro`, e o caller cai no DEFAULT SEGURO (bloqueia+
    escala), em vez de aceitar um `viola=False` espurio. `motivo_parada`/`PARADA_INSEGURA` unificam
    os vocabularios Anthropic (stop_reason) e OpenAI/OpenRouter (finish_reason).
    """
    from barra.core.llm import (
        PARADA_INSEGURA,
        criar_chat_anthropic,
        criar_chat_openrouter,
        motivo_parada,
    )

    if settings.output_guard_provider == "openrouter":
        assert settings.openrouter_model_judge is not None  # garantido pelo model_validator
        # method="function_calling" explicito: mais robusto que json_schema no roteamento OpenRouter.
        chat = criar_chat_openrouter(
            settings, modelo=settings.openrouter_model_judge
        ).with_structured_output(_VeredictoAup, include_raw=True, method="function_calling")
    else:
        chat = criar_chat_anthropic(
            settings, modelo=settings.output_guard_modelo, com_effort=False
        ).with_structured_output(_VeredictoAup, include_raw=True)
    mensagens = [
        {"role": "system", "content": render_aup_saida()},
        {"role": "user", "content": f"MENSAGEM A AVALIAR:\n{texto}"},
    ]
    resultado = await chat.ainvoke(mensagens)
    assert isinstance(resultado, dict)
    bruto = resultado.get("raw")
    parada = motivo_parada(getattr(bruto, "response_metadata", None))
    if resultado.get("parsing_error") is not None or parada in PARADA_INSEGURA:
        raise _JudgeInseguro(f"judge sem veredito confiavel (parada={parada})")
    veredito = resultado.get("parsed")
    assert isinstance(veredito, _VeredictoAup)
    return veredito


async def _bloquear(ctx: ContextAgente, *, observacao: str, resumo: str, metric_key: str) -> None:
    """Abre handoff p/ Fernando (ia_pausada=true) e contabiliza a escalada (bucket=defesa).

    `observacao` e o motivo granular persistido; `metric_key` e o rotulo grosso da metrica
    (`output_leak`/`aup_saida`), passado pelo caller que ja sabe qual etapa barrou.

    Sem atendimento_id (webhook fino) nao ha o que pausar: so loga -- a bolha ja sera zerada.
    """
    if ctx.atendimento_id is None:
        logger.warning("output_guard bloqueou sem atendimento_id (%s)", observacao)
        return
    async with conexao(ctx.db_pool) as conn:
        await escalar_defesa(
            conn, ctx.atendimento_id, resumo=resumo, observacao=observacao, metric_key=metric_key
        )


async def output_guard(
    state: EstadoAgente, runtime: Runtime[ContextAgente]
) -> Command[Literal["__end__"]]:
    """Etapa 1 + Etapa 2 antes da bolha. Bloqueia -> handoff + bolha vazia. Sempre vai p/ END."""
    settings = get_settings()
    ctx = runtime.context
    if not settings.output_guard_habilitado:
        return Command(goto=END)  # type: ignore[arg-type]

    # Mesmo agregado que o coordenador despacha (`extrair_texto_do_turno`): TODAS as AIMessages
    # geradas neste turno, nao so a ultima — no ReAct o texto ao cliente costuma sair na 1a
    # passagem (texto + tool_call) e a ultima vem vazia (ou e o tool_use da extracao forcada);
    # guardar so a ultima deixava o texto real passar sem scan/judge.
    msgs_turno = mensagens_do_turno(state["messages"])
    texto = extrair_texto_do_turno(state["messages"])

    # A legenda da midia (arg `legenda` de enviar_midia) sai ao cliente como caption FORA da bolha
    # de texto -- precisa passar pelo MESMO scan/judge, senao escaparia do guard (A1). Coletada
    # ANTES do early-return de texto vazio p/ cobrir tambem turno so-midia.
    async with conexao(ctx.db_pool) as conn:
        legendas = await _legendas_do_turno(conn, ctx.turno_id)
        texto_guard = "\n".join(p for p in (texto, *legendas) if p.strip())
        if not texto_guard.strip():
            # post_process ja zerou (pausa concorrente) ou turno sem texto nem midia: nada a guardar.
            return Command(goto=END)  # type: ignore[arg-type]
        termos_cross = await _nomes_outras_modelos(conn, ctx.modelo_id)

    # bloqueio = substitui TODAS as AIMessages do turno por vazias (mesmo id -> reducer troca);
    # zerar so a ultima deixaria o texto da 1a passagem vivo p/ o coordenador despachar.
    vazias = [AIMessage(id=m.id, content="") for m in msgs_turno]

    # Etapa 1: scan deterministico (incl. negativa cross-modelo do banco) sobre texto + legendas.
    motivo = _scan_vazamento(texto_guard, termos_cross)
    if motivo:
        OUTPUT_LEAK_DETECTADO.labels(motivo).inc()
        await _bloquear(
            ctx, observacao=f"output_leak_{motivo}", resumo=_RESUMO_LEAK, metric_key="output_leak"
        )
        return Command(goto=END, update={"messages": vazias})  # type: ignore[arg-type]

    # Negacao canned (pool curado): pula a Etapa 2 (texto ja confiavel). So sem midia -- uma
    # legenda precisa sempre passar pela Etapa 2, mesmo que a bolha de texto seja canned.
    if not legendas and texto.strip() in NEGACOES_CANNED:
        return Command(goto=END)  # type: ignore[arg-type]

    if not settings.output_guard_judge_habilitado:
        return Command(goto=END)  # type: ignore[arg-type]

    # Etapa 2: LLM-judge de AUP vinculante sobre texto + legendas. Falha de infra -> default seguro.
    try:
        veredito = await _julgar_aup(texto_guard, settings)
    except Exception:
        logger.exception("output_guard judge falhou (turno_id=%s) -> default seguro", ctx.turno_id)
        AUP_SAIDA_BLOQUEADO.labels("judge_falhou").inc()
        await _bloquear(
            ctx, observacao="aup_saida_judge_falhou", resumo=_RESUMO_AUP, metric_key="aup_saida"
        )
        return Command(goto=END, update={"messages": vazias})  # type: ignore[arg-type]

    if veredito.viola:
        AUP_SAIDA_BLOQUEADO.labels("violou").inc()
        await _bloquear(
            ctx,
            observacao=f"aup_saida_{veredito.motivo}",
            resumo=_RESUMO_AUP,
            metric_key="aup_saida",
        )
        return Command(goto=END, update={"messages": vazias})  # type: ignore[arg-type]

    return Command(goto=END)  # type: ignore[arg-type]
