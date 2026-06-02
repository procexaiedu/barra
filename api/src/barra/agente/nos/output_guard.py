"""No output_guard: ultima rede ANTES da bolha sair ao cliente (ADR 0016).

Roda no caminho normal de saida (depois do post_process). Recebe o texto final do turno e, em
duas etapas, decide se a bolha pode seguir:

- Etapa 1 (deterministica, barata, sempre): scan de vazamento no TEXTO DE SAIDA -- auto-referencia
  de IA / nome de LLM, fragmento de system/persona, e dado de OUTRA modelo (nome/numero de modelos
  que nao a do par). Match -> bloqueia.
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
from uuid import UUID

from langchain_core.messages import AIMessage
from langgraph.graph import END
from langgraph.runtime import Runtime
from langgraph.types import Command
from pydantic import BaseModel, Field

from barra.core.db import conexao
from barra.core.metrics import AGENTE_ESCALADA, AUP_SAIDA_BLOQUEADO, OUTPUT_LEAK_DETECTADO
from barra.dominio.escaladas.modelos import TipoEscalada
from barra.dominio.escaladas.service import abrir_handoff, mapear_bucket
from barra.settings import get_settings

from .._canned import NEGACOES_CANNED
from ..contexto import ContextAgente
from ..estado import EstadoAgente
from ..persona import render_aup_saida

logger = logging.getLogger(__name__)

_ACAO_ASSUMIR = "Assumir a conversa com o cliente."
_RESUMO_LEAK = "Output-guard barrou a bolha (vazamento detectado antes do envio)."
_RESUMO_AUP = "Output-guard barrou a bolha (LLM-judge de AUP reprovou antes do envio)."

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


class _VeredictoAup(BaseModel):
    """Saida estruturada da Etapa 2 (judge de AUP vinculante)."""

    viola: bool = Field(description="true se a bolha deve ser BARRADA (viola a AUP)")
    motivo: str = Field(
        description="rotulo curto: ia_self|system_leak|cross_modelo|aup_dura|nenhum"
    )


def _ultima_ai_com_texto(state: EstadoAgente) -> AIMessage | None:
    """A AIMessage que iria ao cliente (a bolha). None se nao ha texto a guardar."""
    for m in reversed(state["messages"]):
        if isinstance(m, AIMessage):
            return m
    return None


def _texto_de(msg: AIMessage) -> str:
    conteudo = msg.content
    if isinstance(conteudo, str):
        return conteudo
    if isinstance(conteudo, list):
        return "".join(
            b.get("text", "") for b in conteudo if isinstance(b, dict) and b.get("type") == "text"
        )
    return ""


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


def tem_marcador_ia(texto: str) -> bool:
    """True se o texto contem auto-referencia de IA / nome de LLM (PURO).

    Usado pela Etapa 1 do guard e reusado pelo eval online de non_disclosure (EVAL-11) como
    rubrica deterministica barata (sem custo de LLM por turno amostrado).
    """
    return bool(_MARCADORES_IA.search(texto))


def _scan_vazamento(texto: str, termos_cross: list[str]) -> str | None:
    """Etapa 1 (PURA): devolve o motivo do vazamento ou None. Ordem: ia_self > system > cross."""
    if tem_marcador_ia(texto):
        return "ia_self"
    if _MARCADORES_SYSTEM.search(texto):
        return "system"
    alvo = texto.lower()
    for termo in termos_cross:
        if re.search(rf"\b{re.escape(termo.lower())}\b", alvo):
            return "cross_modelo"
    return None


async def _julgar_aup(texto: str, settings: Any) -> _VeredictoAup:
    """Etapa 2: LLM-judge de AUP (Sonnet, structured output). Prompt em aup_saida.md."""
    from barra.core.llm import criar_chat_anthropic

    chat = criar_chat_anthropic(settings).with_structured_output(_VeredictoAup)
    mensagens = [
        {"role": "system", "content": render_aup_saida()},
        {"role": "user", "content": f"MENSAGEM A AVALIAR:\n{texto}"},
    ]
    veredito = await chat.ainvoke(mensagens)
    assert isinstance(veredito, _VeredictoAup)
    return veredito


async def _bloquear(ctx: ContextAgente, *, observacao: str, resumo: str) -> None:
    """Abre handoff p/ Fernando (ia_pausada=true) e contabiliza a escalada (bucket=defesa).

    Sem atendimento_id (webhook fino) nao ha o que pausar: so loga -- a bolha ja sera zerada.
    """
    if ctx.atendimento_id is None:
        logger.warning("output_guard bloqueou sem atendimento_id (%s)", observacao)
        return
    async with conexao(ctx.db_pool) as conn:
        await abrir_handoff(
            conn,
            atendimento_id=UUID(ctx.atendimento_id),
            responsavel="Fernando",
            tipo=TipoEscalada.comportamento_atipico,
            resumo_operacional=resumo,
            acao_esperada=_ACAO_ASSUMIR,
            origem="agente",
            autor="sistema",
            observacao=observacao,
        )
    motivo_metric = "aup_saida" if observacao.startswith("aup_saida") else "output_leak"
    AGENTE_ESCALADA.labels(mapear_bucket(motivo_metric), motivo_metric).inc()


async def output_guard(
    state: EstadoAgente, runtime: Runtime[ContextAgente]
) -> Command[Literal["__end__"]]:
    """Etapa 1 + Etapa 2 antes da bolha. Bloqueia -> handoff + bolha vazia. Sempre vai p/ END."""
    settings = get_settings()
    ctx = runtime.context
    if not settings.output_guard_habilitado:
        return Command(goto=END)  # type: ignore[arg-type]

    ultima = _ultima_ai_com_texto(state)
    if ultima is None:
        return Command(goto=END)  # type: ignore[arg-type]
    texto = _texto_de(ultima)
    if not texto.strip():
        # post_process ja zerou (pausa concorrente) ou turno sem bolha -- nada a guardar.
        return Command(goto=END)  # type: ignore[arg-type]

    vazia = AIMessage(id=ultima.id, content="")  # bloqueio = substitui a bolha por vazia

    # Etapa 1: scan deterministico (incl. negativa cross-modelo do banco).
    async with conexao(ctx.db_pool) as conn:
        termos_cross = await _nomes_outras_modelos(conn, ctx.modelo_id)
    motivo = _scan_vazamento(texto, termos_cross)
    if motivo:
        OUTPUT_LEAK_DETECTADO.labels(motivo).inc()
        await _bloquear(ctx, observacao=f"output_leak_{motivo}", resumo=_RESUMO_LEAK)
        return Command(goto=END, update={"messages": [vazia]})  # type: ignore[arg-type]

    # Negacao canned (pool curado): pula a Etapa 2 (texto ja confiavel).
    if texto.strip() in NEGACOES_CANNED:
        return Command(goto=END)  # type: ignore[arg-type]

    if not settings.output_guard_judge_habilitado:
        return Command(goto=END)  # type: ignore[arg-type]

    # Etapa 2: LLM-judge de AUP vinculante. Falha de infra -> default seguro (bloqueia+escala).
    try:
        veredito = await _julgar_aup(texto, settings)
    except Exception:
        logger.exception("output_guard judge falhou (turno_id=%s) -> default seguro", ctx.turno_id)
        AUP_SAIDA_BLOQUEADO.labels("judge_falhou").inc()
        await _bloquear(ctx, observacao="aup_saida_judge_falhou", resumo=_RESUMO_AUP)
        return Command(goto=END, update={"messages": [vazia]})  # type: ignore[arg-type]

    if veredito.viola:
        AUP_SAIDA_BLOQUEADO.labels("violou").inc()
        await _bloquear(ctx, observacao=f"aup_saida_{veredito.motivo}", resumo=_RESUMO_AUP)
        return Command(goto=END, update={"messages": [vazia]})  # type: ignore[arg-type]

    return Command(goto=END)  # type: ignore[arg-type]
