"""No output_guard: ultima rede ANTES da bolha sair ao cliente (ADR 0016).

Roda no caminho normal de saida (depois do post_process). Recebe o texto final do turno e, em
duas etapas, decide se a bolha pode seguir:

- Etapa 1 (deterministica, barata, sempre): scan de vazamento no TEXTO DE SAIDA -- auto-referencia
  de IA / nome de LLM, fragmento de system/persona, e segredo da agenda (revelar estar com outro
  cliente / em outro atendimento, em vez da desculpa pessoal). Match -> bloqueia. (O scan
  determinístico cross-modelo foi removido -- supersede ADR 0016: a IA roda por modelo e nunca tem
  em contexto o nome/numero de OUTRA modelo, entao a blocklist so podia casar por coincidencia de
  homonimo (FP). Isolamento garantido no carregamento; backstop semantico = Etapa 2.)
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
from barra.core.metrics import (
    AUP_SAIDA_BLOQUEADO,
    OUTPUT_LEAK_DETECTADO,
    OUTPUT_RACIOCINIO_SANEADO,
)
from barra.settings import get_settings

from .._canned import NEGACOES_CANNED
from .._defesa import escalar_defesa
from .._instrumentar import instrumentar_tokens
from .._texto_turno import extrair_texto_do_turno, mensagens_do_turno, texto_da_mensagem
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


# Vazamento de RACIOCINIO: o chat #1 (thinking disabled, temp 1.3) as vezes derrama a cadeia de
# raciocinio no canal `content` em vez de conversar -- meta-fala que entrega a IA. Marcas (handoff
# 2026-06-26): planejamento em 1a pessoa ("meu proximo passo"), 3a pessoa sobre o cliente ("o
# cliente demonstrou"), vocab de maquina de estado ("em triagem", "avancou"), lista de analise ("a
# situacao mostra: -"). Conservador no que casa -- na duvida o judge (Etapa 2) e a rede fail-closed.
# Ampliado (shadow 300, 2026-06-30): narracao meta em 3a pessoa reportando a fala do cliente ("Ele
# perguntou 'X'", "o cliente acabou de responder com 'Y'") e meta do proprio processamento ("vou
# continuar respondendo", "acabou de chegar no meio do texto") escapavam do Estagio 0. Padroes
# testados contra 250 respostas validas (zero falso-positivo) + falas legitimas de 3o ("ele vai te
# receber", "ela e minha amiga", "vou te responder rapidinho") que continuam NAO casando.
_MARCADORES_RACIOCINIO = re.compile(
    r"\b("
    r"meu pr[óo]ximo passo|minha (resposta|interven[çc][ãa]o|fala) (suavizou|sobre)"
    r"|o cliente (demonstrou|quer saber|menciona|pediu|respondeu|acabou de)|claro interesse dele"
    r"|(ele|ela) (perguntou|respondeu|disse|falou|mencionou|comentou)"
    r"|vou continuar respondendo|acabou de chegar no meio|vou responder (normal|o valor|agora)"
    r"|em triagem|triagem avan[çc]ou|a (situa[çc][ãa]o|conversa) (mostra|fluiu)"
    # fragmento de scratchpad: planejamento em voz alta / auto-correcao quebrada. Combos unicos
    # (nao "faz sentido" solto, que e fala legitima): "faz sentido na sequencia", a run-on
    # "entao.opa devagar", "preparado, entao".
    r"|faz sentido na sequ[êe]ncia|ent[ãa]o\.?\s*opa|preparado,? ent[ãa]o"
    r")\b",
    re.IGNORECASE,
)


def tem_marcador_raciocinio(texto: str) -> bool:
    """True se o texto e meta-fala/raciocinio vazado (planejamento, 3a pessoa sobre o cliente,
    vocab de maquina de estado, lista de analise) em vez de fala client-facing (PURO)."""
    return bool(_MARCADORES_RACIOCINIO.search(texto))


# Placeholder de template nao preenchido: o chat as vezes cospe a chave literal do exemplo do prompt
# ("{valor} 1h no meu local") em vez de interpolar o dado real. Uma bolha com `{token}` ASCII nunca e
# fala valida ao cliente -- e entrega a IA na cara. Escopo estreito (so {minusculas_e__}) p/ nao pegar
# emoji/acento nem texto legitimo com chave.
_RE_PLACEHOLDER = re.compile(r"\{[a-z_]+\}")


def tem_placeholder_template(texto: str) -> bool:
    """True se a bolha contem um placeholder de template nao preenchido (ex.: `{valor}`, `{horario}`)."""
    return bool(_RE_PLACEHOLDER.search(texto))


def _bolha_descartavel(b: str) -> bool:
    """Bolha que o Estagio 0 strippa: raciocinio vazado OU placeholder de template nao preenchido.
    As duas entregam a IA e nunca sao fala valida ao cliente."""
    return tem_marcador_raciocinio(b) or tem_placeholder_template(b)


class _VeredictoAup(BaseModel):
    """Saida estruturada da Etapa 2 (judge de AUP vinculante)."""

    viola: bool = Field(description="true se a bolha deve ser BARRADA (viola a AUP)")
    motivo: str = Field(
        description="rotulo curto: ia_self|system_leak|cross_modelo|aup_dura|reasoning_leak|nenhum"
    )


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


def _sanear_raciocinio(msgs_turno: list[AIMessage], texto: str) -> tuple[str, list[AIMessage]]:
    """Estagio 0: strippa as bolhas de RACIOCINIO vazado do texto do turno, mantendo a fala real.

    O texto ao cliente e o agregado do turno separado por `\\n\\n` (`extrair_texto_do_turno`), e o
    chunker quebra na mesma marca -- entao cada `\\n\\n` e uma bolha. Descarta as bolhas que sao
    meta-fala (`tem_marcador_raciocinio`) e devolve (texto_saneado, AIMessages reescritas).

    O coordenador RE-deriva o texto via `extrair_texto_do_turno(messages)` -- nao le um output do
    guard -- entao o saneamento precisa viver NAS mensagens. Reescreve so as AIMessages cujo content
    tinha bolha de raciocinio (split/strip/rejoin do proprio content), preservando id/usage/
    response_metadata/tool_calls: o reducer troca pelo id, o `extrair` junta os contents limpos e
    rende exatamente o texto_saneado (bolha nao cruza fronteira de mensagem -> strip e distributivo).
    Turno sem raciocinio -> (texto, []) (no-op, comportamento de hoje).
    """
    texto_saneado = "\n\n".join(b for b in texto.split("\n\n") if not _bolha_descartavel(b))
    if texto_saneado == texto:
        return texto, []
    reescritas: list[AIMessage] = []
    for m in msgs_turno:
        original = texto_da_mensagem(m)
        if not original:
            continue
        limpo = "\n\n".join(b for b in original.split("\n\n") if not _bolha_descartavel(b))
        if limpo != original:
            reescritas.append(
                AIMessage(
                    id=m.id,
                    content=limpo,
                    tool_calls=m.tool_calls,
                    usage_metadata=m.usage_metadata,
                    response_metadata=m.response_metadata,
                )
            )
    return texto_saneado, reescritas


def _scan_vazamento(texto: str) -> str | None:
    """Etapa 1 (PURA): devolve o motivo do vazamento ou None.

    Ordem: ia_self > system > outro_cliente > raciocinio. Cobre so o que a IA PODE de fato emitir
    (sabe que e IA, tem o system no contexto, conhece a propria agenda). O scan determinístico
    cross-modelo foi removido (supersede ADR 0016): a IA roda por modelo e nunca tem em contexto o
    nome/numero de OUTRA modelo (`prepare_context` carrega `WHERE id = %s`; isolamento garantido no
    carregamento por `(cliente_id, modelo_id)` + `evolution_instance_id` UNIQUE), entao a blocklist
    de nomes so podia casar por coincidencia de homonimo (FP). O backstop semantico e a Etapa 2.

    `raciocinio` aqui e a rede para a LEGENDA de midia (que o Estagio 0 nao saneia -- ela e arg de
    tool no DB, nao content de mensagem reescrivivel): legenda com meta-fala -> barra o turno, igual
    a qualquer outro leak em legenda. O texto ja chega aqui SANEADO (Estagio 0 strippou as bolhas de
    raciocinio com o mesmo regex), entao esta checagem nunca re-barra o texto -- so a legenda.
    """
    if tem_marcador_ia(texto):
        return "ia_self"
    if tem_marcador_system(texto):
        return "system"
    if tem_marcador_outro_cliente(texto):
        return "outro_cliente"
    if tem_marcador_raciocinio(texto):
        return "raciocinio"
    return None


async def _julgar_aup(texto: str, settings: Any) -> _VeredictoAup:
    """Etapa 2: LLM-judge de AUP no DeepSeek V4 Flash direto (structured output). Prompt em aup_saida.md.

    DeepSeek-only (igual ao chat #1 e a extracao): ChatOpenAI direto na API DeepSeek, com thinking
    travado em disabled (o thinking mode do V4 corromperia o structured output — vllm#41132) e o
    structured output por function-calling explicito (`method="function_calling"`). Cacheia o prefixo
    aup_saida.md (o mesmo system antes de CADA bolha).

    SO-03: `include_raw` expoe o motivo de parada da PROPRIA resposta do judge. Recusa
    (refusal/content_filter), truncamento (max_tokens/length) ou falha de parse nao produzem
    veredito confiavel -> levanta `_JudgeInseguro`, e o caller cai no DEFAULT SEGURO (bloqueia+
    escala), em vez de aceitar um `viola=False` espurio. `motivo_parada`/`PARADA_INSEGURA` unificam
    os vocabularios Anthropic (stop_reason) e OpenAI/OpenRouter (finish_reason).
    """
    from barra.core.llm import PARADA_INSEGURA, criar_chat_deepseek, motivo_parada

    # DeepSeek-only (V4 Flash, thinking travado em disabled): cacheia o prefixo aup_saida.md (o mesmo
    # system antes de CADA bolha) e crava modelo/quant — sem roleta do pool nem risco de thinking
    # corromper o veredito (vllm#41132). method="function_calling" explicito (mais robusto que json_schema).
    modelo_judge = settings.deepseek_model_chat
    chat = criar_chat_deepseek(settings).with_structured_output(
        _VeredictoAup, include_raw=True, method="function_calling"
    )
    mensagens = [
        {"role": "system", "content": render_aup_saida()},
        {"role": "user", "content": f"MENSAGEM A AVALIAR:\n{texto}"},
    ]
    # callbacks=[] corta a propagacao do CallbackHandler (Langfuse) herdado via contextvar do no:
    # o sub-chain do `with_structured_output` (RunnableParallel<raw,parsed> + PydanticToolsParser +
    # RunnableAssign + a generation do judge) seria ~8 spans de ruido NO TRACE, multiplicados pelo
    # nº de bolhas (o judge roda antes de CADA bolha). Mantemos o trace legivel; os tokens do judge
    # seguem instrumentados via Prometheus (abaixo, le do `bruto`, independe de callbacks) e o caso
    # inseguro continua logado + metrica. Nao afeta o parsing (callbacks sao so telemetria).
    # Retry 1x SO no parsing_error (parse transitorio, temp default do judge): PARADA_INSEGURA
    # (refusal/truncamento) e sinal de seguranca real -> default-seguro imediato, sem retry (a 2a
    # tentativa nao reverteria um filtro do provider). O log distingue os dois gatilhos: a msg
    # antiga so citava `parada` e culpava o `tool_calls` (finish_reason normal de function-calling),
    # mascarando que o gatilho real era o `parsing_error`.
    parada: str | None = None
    for tentativa in (1, 2):
        resultado = await chat.ainvoke(mensagens, config={"callbacks": []})
        assert isinstance(resultado, dict)
        bruto = resultado.get("raw")
        # CUSTO: o judge roda antes de CADA bolha e queima tokens (DeepSeek V4 Flash). Instrumenta
        # sob o label do PROPRIO modelo do judge, ANTES do check de parada e em CADA tentativa -- o
        # token gastou mesmo no veredito inseguro (refusal/truncado/parse) e no retry.
        if bruto is not None:
            instrumentar_tokens(bruto, modelo_judge)
        parada = motivo_parada(getattr(bruto, "response_metadata", None))
        if parada in PARADA_INSEGURA:
            raise _JudgeInseguro(
                f"judge sem veredito confiavel (parsing_error=False, parada={parada})"
            )
        if resultado.get("parsing_error") is None:
            veredito = resultado.get("parsed")
            assert isinstance(veredito, _VeredictoAup)
            return veredito
        if tentativa == 1:
            logger.warning(
                "output_guard judge parse falhou (tentativa 1, parada=%s) -> retry", parada
            )
    raise _JudgeInseguro(f"judge sem veredito confiavel (parsing_error=True, parada={parada})")


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

    # Estagio 0 (non-disclosure, tolerancia-zero): SANEIA o raciocinio vazado -- strippa as bolhas de
    # meta-fala (que entregam a IA) e mantem a fala real. O texto saneado segue p/ a Etapa 1/2 (scan
    # + judge rodam no que VAI ao cliente). `msgs_saneadas` (AIMessages reescritas) viaja nos returns
    # de passagem: o coordenador re-deriva o texto das mensagens, entao o strip precisa estar nelas.
    # Turno 100%-raciocinio -> texto vazio -> mudo (silencio > disclosure). NAO escala (leak saneado
    # nao e brecha como ia_self): se algo com cara de raciocinio SOBREVIVER, a Etapa 2 fecha.
    texto, msgs_saneadas = _sanear_raciocinio(msgs_turno, texto)
    update_saneamento: dict[str, Any] = {"messages": msgs_saneadas} if msgs_saneadas else {}
    if msgs_saneadas:
        OUTPUT_RACIOCINIO_SANEADO.labels("saneado" if texto.strip() else "mudo").inc()

    # A legenda da midia (arg `legenda` de enviar_midia) sai ao cliente como caption FORA da bolha
    # de texto -- precisa passar pelo MESMO scan/judge, senao escaparia do guard (A1). Coletada
    # ANTES do early-return de texto vazio p/ cobrir tambem turno so-midia.
    async with conexao(ctx.db_pool) as conn:
        legendas = await _legendas_do_turno(conn, ctx.turno_id)
        texto_guard = "\n".join(p for p in (texto, *legendas) if p.strip())
        if not texto_guard.strip():
            # post_process ja zerou (pausa concorrente), turno sem texto/midia, OU o Estagio 0 saneou
            # o turno inteiro (mudo): nada a guardar. Carrega `msgs_saneadas` p/ o coordenador nao
            # re-derivar o texto cru (com o raciocinio) das mensagens originais.
            return Command(goto=END, update=update_saneamento)  # type: ignore[arg-type]

    # bloqueio = substitui TODAS as AIMessages do turno por vazias (mesmo id -> reducer troca);
    # zerar so a ultima deixaria o texto da 1a passagem vivo p/ o coordenador despachar.
    # PRESERVA usage_metadata + response_metadata: o reducer troca o objeto pelo id, e o coordenador
    # le `resultado["messages"]` para acumular o custo do turno (`custo_chat_turno_brl`, que filtra por
    # usage_metadata != None) e precificar pela tabela do modelo (response_metadata.model_name). Sem
    # isso, um turno BARRADO pelo guard queimou tokens mas entrava no custo_ia_brl como ZERO. O content
    # segue vazio -> nenhuma bolha sai; sem tool_calls copiados, o check de truncamento (coordenador
    # 5c, exige tool_calls) nao re-dispara.
    vazias = [
        AIMessage(
            id=m.id,
            content="",
            usage_metadata=m.usage_metadata,
            response_metadata=m.response_metadata,
        )
        for m in msgs_turno
    ]

    # Etapa 1: scan deterministico (ia_self/system/segredo-da-agenda) sobre texto + legendas.
    motivo = _scan_vazamento(texto_guard)
    if motivo:
        OUTPUT_LEAK_DETECTADO.labels(motivo).inc()
        await _bloquear(
            ctx, observacao=f"output_leak_{motivo}", resumo=_RESUMO_LEAK, metric_key="output_leak"
        )
        return Command(goto=END, update={"messages": vazias})  # type: ignore[arg-type]

    # Negacao canned (pool curado): pula a Etapa 2 (texto ja confiavel). So sem midia -- uma
    # legenda precisa sempre passar pela Etapa 2, mesmo que a bolha de texto seja canned.
    if not legendas and texto.strip() in NEGACOES_CANNED:
        return Command(goto=END, update=update_saneamento)  # type: ignore[arg-type]

    if not settings.output_guard_judge_habilitado:
        return Command(goto=END, update=update_saneamento)  # type: ignore[arg-type]

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

    return Command(goto=END, update=update_saneamento)  # type: ignore[arg-type]
