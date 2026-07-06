"""No output_guard: ultima rede ANTES da bolha sair ao cliente (ADR 0016).

Roda no caminho normal de saida (depois do post_process). Recebe o texto final do turno e decide
se a bolha pode seguir:

- Estagio 0 (deterministico, transformacao): SANEIA raciocinio vazado/placeholder/tag de exemplo,
  mantendo a fala real.
- Gate pre-envio (deterministico + regen one-shot, producao assistida): scan de vazamento no TEXTO
  DE SAIDA -- auto-referencia de IA / nome de LLM, fragmento de system/persona, segredo da agenda
  (revelar estar com outro cliente) -- e detector de REPETICAO (bolha quase identica a uma bolha
  recente da propria IA, rastro de papagaio). Turno sujo -> REGENERA 1x (chamada direta ao chat,
  sem tools, com o rascunho descartado como feedback); persistiu -> fallback por gatilho: leak ->
  bloqueia (handoff); repeticao -> dropa as bolhas repetidas (silencio > papagaio, sem handoff);
  turno 100%-raciocinio -> mudo. Leak em LEGENDA de midia nao e regeneravel (ja persistida como
  arg de tool) -> bloqueia direto. (O scan deterministico cross-modelo foi removido -- supersede
  ADR 0016: a IA roda por modelo e nunca tem em contexto o nome/numero de OUTRA modelo; isolamento
  garantido no carregamento; backstop semantico = judge.)
- Etapa 2 (LLM-judge de AUP, vinculante): quando o gate passa e o texto NAO e uma negacao canned
  (pool curado pula a Etapa 2). Roda tambem sobre o texto REGENERADO -- a regen nao pula o judge.
  Prompt em `prompts/aup_saida.md` (fora do prefixo cacheado por-modelo). Violou -> bloqueia.
  Falha de infra do judge -> DEFAULT SEGURO: bloqueia+escala (sem regen: judge inseguro nao e
  garble consertavel, e sinal de risco).

Bloquear = abrir handoff p/ Fernando (ia_pausada=true, mesma porta do disclosure/jailbreak) E
zerar a bolha (mesmo id -> reducer substitui por vazia, igual post_process). O coordenador rele
ia_pausada apos o turno (cinto-suspensorio) e nao despacha. Roteamento SO por Command(goto=END)
-- sem aresta estatica de saida (armadilha do fan-out, graph.py).
"""

import logging
import re
from collections.abc import Callable, Sequence
from difflib import SequenceMatcher
from typing import Any, Literal

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.messages.ai import UsageMetadata
from langgraph.graph import END
from langgraph.runtime import Runtime
from langgraph.types import Command
from pydantic import BaseModel, Field

from barra.core.db import conexao
from barra.core.metrics import (
    AUP_SAIDA_BLOQUEADO,
    OUTPUT_LEAK_DETECTADO,
    OUTPUT_RACIOCINIO_SANEADO,
    OUTPUT_REGEN,
    OUTPUT_REPETICAO_DETECTADA,
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
    # adverbio opcional entre o pronome e o verbo: "ele JA falou" escapava (o regex exigia
    # adjacencia). "ele vai te receber"/"ela e minha amiga" seguem NAO casando (verbo fora da lista).
    r"|(ele|ela) (?:j[áa] |ainda |mesmo |s[óo] |tamb[ée]m )?(perguntou|respondeu|disse|falou|mencionou|comentou)"
    # jargao de TIPO narrado ao cliente (rotulo interno de dominio): "que e interno", "externo entao".
    # Bolha real ao cliente nunca classifica o atendimento por esses rotulos (handoff 2026-07-01).
    r"|que [ée] (interno|externo|remoto)|(interno|externo|remoto) ent[ãa]o"
    r"|vou continuar respondendo|acabou de chegar no meio|vou responder (normal|o valor|agora)"
    r"|em triagem|triagem avan[çc]ou|a (situa[çc][ãa]o|conversa) (mostra|fluiu)"
    # fragmento de scratchpad: planejamento em voz alta / auto-correcao quebrada. Combos unicos
    # (nao "faz sentido" solto, que e fala legitima): "faz sentido na sequencia", a run-on
    # "entao.opa devagar", "preparado, entao".
    r"|faz sentido na sequ[êe]ncia|ent[ãa]o\.?\s*opa|preparado,? ent[ãa]o"
    # meta de espera pos-cotacao vazada (rodada de eval 2026-07-03): "Agora e esperar ele reagir
    # ao valor" saiu como bolha ao cliente. Conservador: exige o combo esperar+reagir ou a forma
    # "agora e (so) esperar"; "vou te esperar"/"te espero" (fala legitima) NAO casam.
    r"|esperar (ele|ela) reagir|agora [ée] (s[óo] )?esperar"
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


# Delimitador de EXEMPLO vazando na bolha: os few-shots de `regras.md.j2`/`persona.md` moldam a fala
# ideal com tags de papel (`<ela>...</ela>`, `<cliente>...</cliente>`, `<exemplo>`) e os pares de
# contraste (`<certo>/<errado>/<par>/<porque>`). Sob decodificacao estocastica (temp 0.7) o chat as
# vezes COPIA o delimitador de fechamento colado a uma fala boa ("tudo bem, e voce?</ela>"). Ao
# contrario de raciocinio/placeholder (bolha inteira descartavel) e das tags de SECAO pesadas de
# `_MARCADORES_SYSTEM` (que barram o turno -> handoff), aqui a bolha e fala legitima com um residuo de
# molde no fim/inicio: strippa-se SO a substring da tag e mantem-se a fala. Angle-bracket + palavra de
# molde nunca aparece em mensagem real de cliente, entao o strip nao tem colateral.
_RE_TAG_EXEMPLO = re.compile(r"</?(?:ela|cliente|exemplo|certo|errado|par|porque)>", re.IGNORECASE)


def _bolha_descartavel(b: str) -> bool:
    """Bolha que o Estagio 0 strippa: raciocinio vazado OU placeholder de template nao preenchido.
    As duas entregam a IA e nunca sao fala valida ao cliente."""
    return tem_marcador_raciocinio(b) or tem_placeholder_template(b)


def _limpar_bolhas(texto: str) -> str:
    """Estagio 0 (transformacao pura de um agregado): descarta as bolhas de raciocinio/placeholder e
    strippa o delimitador de exemplo (`_RE_TAG_EXEMPLO`) das que sobram, mantendo a fala.

    Distributivo sobre o `\\n\\n` (bolha nao cruza fronteira de mensagem): aplicar isto no agregado do
    turno OU no content de cada AIMessage e rejuntar rende o mesmo texto -- o que preserva o invariante
    do `_sanear_raciocinio` (o coordenador re-deriva o texto das mensagens). Sem leak/tag -> devolve o
    texto identico (no-op, curto-circuito la em cima). Bolha que era SO a tag (`</ela>` sozinha) some
    de vez -- so a substring da tag e removida, mas a bolha vazia resultante nao vai ao cliente."""
    saidas: list[str] = []
    for b in texto.split("\n\n"):
        if _bolha_descartavel(b):
            continue
        limpa = _RE_TAG_EXEMPLO.sub("", b)
        if limpa.strip():
            saidas.append(limpa)
    return "\n\n".join(saidas)


# Detector de REPETICAO (rastro de papagaio): bolha do turno quase identica a uma bolha recente da
# propria IA -- o padrao classico e o cliente silenciar e a IA re-perguntar a MESMA coisa. Humano
# nao repete verbatim: reformula ("como te falei...") ou fica quieto. Limiares conservadores: so
# bolhas com >= _REPETICAO_MIN chars normalizados (cumprimento curto -- "oi amor", "kkk" -- repete
# legitimamente) e similaridade >= _REPETICAO_LIMIAR; uma reformulacao real ("como te falei: <o
# endereco>") ja cai abaixo do limiar. Janela = ultimas _REPETICAO_JANELA bolhas ja enviadas.
_REPETICAO_LIMIAR = 0.90
_REPETICAO_MIN = 25  # piso p/ match FUZZY (reformulacao parcial: "como te falei: <endereco>")
# Piso menor p/ reenvio EXATO (ratio 1.0): a bolha de preco curta ("400 1h no meu local", 19 chars
# normalizados) passava sob o piso fuzzy de 25 e o papagaio literal ia ao cliente (onda 1, finding
# C). Ainda isenta saudacao/gracejo curto ("oi amor" 7, "boa tarde amor" 14) que repete legitimamente.
_REPETICAO_MIN_VERBATIM = 15
_REPETICAO_JANELA = 12

_RE_NAO_PALAVRA = re.compile(r"[^\w\s]+")
_RE_ESPACOS = re.compile(r"\s+")


def _normalizar_bolha(b: str) -> str:
    """Normaliza p/ comparacao de repeticao: minusculas, sem pontuacao/emoji, espacos colapsados."""
    return _RE_ESPACOS.sub(" ", _RE_NAO_PALAVRA.sub(" ", b.lower())).strip()


def _bolhas_historicas(messages: Sequence[BaseMessage]) -> list[str]:
    """Ultimas bolhas que a IA JA ENVIOU nesta conversa -- AIMessages historicas re-injetadas pelo
    prepare_context (sem usage_metadata; inverso exato de `mensagens_do_turno`)."""
    bolhas = [
        b
        for m in messages
        if isinstance(m, AIMessage) and m.usage_metadata is None
        for b in texto_da_mensagem(m).split("\n\n")
        if b.strip()
    ]
    return bolhas[-_REPETICAO_JANELA:]


def bolhas_repetidas(texto: str, historicas: Sequence[str]) -> list[str]:
    """Bolhas do turno quase identicas a uma bolha recente da propria IA -- ou a outra bolha
    anterior do MESMO turno (PURA; devolve as bolhas originais, nao normalizadas, p/ o drop).

    Reenvio EXATO (ratio 1.0) conta ja no piso menor (_REPETICAO_MIN_VERBATIM) -- pega a bolha de
    preco curta que passava sob o piso fuzzy; match FUZZY segue exigindo _REPETICAO_MIN p/ nao
    flagar saudacao curta reformulada. Negacao canned repetida nao e rastro (pool curado) -> isenta."""
    vistas = [n for b in historicas if len(n := _normalizar_bolha(b)) >= _REPETICAO_MIN_VERBATIM]
    repetidas: list[str] = []
    for b in texto.split("\n\n"):
        if b.strip() in NEGACOES_CANNED:
            continue
        n = _normalizar_bolha(b)
        if len(n) < _REPETICAO_MIN_VERBATIM:
            continue
        exato = n in vistas
        fuzzy = len(n) >= _REPETICAO_MIN and any(
            SequenceMatcher(None, n, v).ratio() >= _REPETICAO_LIMIAR for v in vistas
        )
        if exato or fuzzy:
            repetidas.append(b)
        vistas.append(n)
    return repetidas


def _drop_bolhas(texto: str, remover: set[str]) -> str:
    """Remove do agregado as bolhas repetidas (fallback da repeticao: silencio > papagaio)."""
    return "\n\n".join(b for b in texto.split("\n\n") if b not in remover)


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


def _reescrever_turno(
    msgs_turno: list[AIMessage], transformar: Callable[[str], str]
) -> list[AIMessage]:
    """Reescreve as AIMessages do turno cujo content muda sob `transformar`, preservando
    id/usage/response_metadata/tool_calls (o reducer troca pelo id). O coordenador RE-deriva o
    texto via `extrair_texto_do_turno(messages)` -- nao le um output do guard -- entao qualquer
    limpeza precisa viver NAS mensagens. `transformar` deve ser distributiva sobre o `\\n\\n`
    (bolha nao cruza fronteira de mensagem): aplicada por-mensagem e rejuntada, rende o mesmo
    agregado que aplicada no texto do turno."""
    reescritas: list[AIMessage] = []
    for m in msgs_turno:
        original = texto_da_mensagem(m)
        if not original:
            continue
        limpo = transformar(original)
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
    return reescritas


def _sanear_raciocinio(msgs_turno: list[AIMessage], texto: str) -> tuple[str, list[AIMessage]]:
    """Estagio 0: strippa o RACIOCINIO vazado e o DELIMITADOR DE EXEMPLO do texto do turno, mantendo
    a fala real.

    O texto ao cliente e o agregado do turno separado por `\\n\\n` (`extrair_texto_do_turno`), e o
    chunker quebra na mesma marca -- entao cada `\\n\\n` e uma bolha. `_limpar_bolhas` descarta as
    bolhas de meta-fala/placeholder (`_bolha_descartavel`) E strippa a substring da tag de exemplo
    (`_RE_TAG_EXEMPLO`, ex.: `</ela>`) das que sobram; devolve (texto_saneado, AIMessages reescritas
    via `_reescrever_turno`). Turno limpo -> (texto, []) (no-op, comportamento de hoje).
    """
    texto_saneado = _limpar_bolhas(texto)
    if texto_saneado == texto:
        return texto, []
    return texto_saneado, _reescrever_turno(msgs_turno, _limpar_bolhas)


def _zerar_turno(msgs: Sequence[AIMessage]) -> list[AIMessage]:
    """Zera as AIMessages (mesmo id -> reducer troca), PRESERVANDO usage_metadata +
    response_metadata: o coordenador acumula o custo do turno lendo `usage_metadata` (turno barrado
    queimou tokens) e precifica pela tabela do modelo (`response_metadata.model_name`). O content
    vazio -> nenhuma bolha sai; sem tool_calls copiados, o check de truncamento (coordenador 5c,
    exige tool_calls) nao re-dispara."""
    return [
        AIMessage(
            id=m.id,
            content="",
            usage_metadata=m.usage_metadata,
            response_metadata=m.response_metadata,
        )
        for m in msgs
    ]


# Regeneracao one-shot (producao assistida): cap do rascunho descartado no feedback (nao inflar o
# prompt da regen com um turno-monstro) e a razao por gatilho, na 2a pessoa da persona.
_RASCUNHO_MAX = 1200
_FEEDBACK_GATILHO = {
    "leak": (
        "ela deixava escapar fala interna (raciocinio, instrucao de sistema ou detalhe da sua "
        "operacao que voce nunca diria a um cliente)"
    ),
    "repeticao": "ela repetia quase igual algo que voce ja tinha mandado antes nesta conversa",
    "mudo": "ela era so raciocinio interno, sem nenhuma fala de verdade ao cliente",
}
_EXTRA_REPETICAO = (
    " Se tiver algo novo a dizer, diga de outro jeito (pode fazer referencia ao que ja falou); se "
    "nao tiver nada novo a acrescentar, devolva vazio -- silencio e melhor que repetir."
)


async def _regenerar(
    messages: Sequence[BaseMessage],
    msgs_turno: list[AIMessage],
    *,
    rascunho: str,
    gatilho: str,
    settings: Any,
) -> AIMessage | None:
    """Regeneracao one-shot do turno sujo: re-pede a resposta ao chat #1 SEM tools, sobre a janela
    ate ANTES deste turno + um `<lembrete_silencioso>` com o rascunho descartado e o motivo.

    Chamada direta de proposito (nao volta ao no llm): re-entrar no grafo re-rodaria o loop ReAct
    e poderia re-executar tool com efeito colateral (enviar_midia, bloqueio de agenda); a extracao
    deste turno ja persistiu. Sem tools bindadas o modelo so pode responder texto. Falha de
    qualquer natureza (excecao, recusa, truncamento) -> None e o caller cai no fallback
    (handoff/drop/mudo) -- a regen e so o caminho feliz, nunca a rede de seguranca.
    """
    from barra.core.llm import (
        PARADA_RECUSA,
        PARADA_TRUNCADA,
        criar_chat_deepseek,
        motivo_parada,
    )

    corte = messages.index(msgs_turno[0]) if msgs_turno else len(messages)
    janela = list(messages[:corte])
    extra = _EXTRA_REPETICAO if gatilho == "repeticao" else ""
    feedback = (
        "<lembrete_silencioso>Sua ultima resposta foi descartada antes do envio: "
        f"{_FEEDBACK_GATILHO[gatilho]}.\n"
        f"Rascunho descartado:\n{rascunho[:_RASCUNHO_MAX]}\n"
        "Escreva agora, no seu jeito de sempre, a mensagem que vai ao cliente -- curta e natural, "
        f"sem o problema acima.{extra} Responda somente com a mensagem.</lembrete_silencioso>"
    )
    chat = criar_chat_deepseek(settings, temperature=settings.chat_temperature)
    try:
        resp = await chat.ainvoke([*janela, HumanMessage(content=feedback)])
    except Exception:
        logger.exception("output_guard regen indisponivel (gatilho=%s)", gatilho)
        return None
    instrumentar_tokens(resp, settings.deepseek_model_chat)
    parada = motivo_parada(getattr(resp, "response_metadata", None))
    if parada in PARADA_RECUSA or parada in PARADA_TRUNCADA:
        logger.warning("output_guard regen parada=%s (gatilho=%s) -> fallback", parada, gatilho)
        return None
    return resp if isinstance(resp, AIMessage) else None


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
    """Estagio 0 + gate pre-envio (leak/repeticao, regen one-shot) + Etapa 2 (judge de AUP).
    Bloqueia -> handoff + bolha vazia. Sempre vai p/ END."""
    settings = get_settings()
    ctx = runtime.context
    if not settings.output_guard_habilitado:
        return Command(goto=END)  # type: ignore[arg-type]

    # Mesmo agregado que o coordenador despacha (`extrair_texto_do_turno`): TODAS as AIMessages
    # geradas neste turno, nao so a ultima — no ReAct o texto ao cliente costuma sair na 1a
    # passagem (texto + tool_call) e a ultima vem vazia (ou e o tool_use da extracao forcada);
    # guardar so a ultima deixava o texto real passar sem scan/judge.
    msgs_turno = mensagens_do_turno(state["messages"])
    texto_cru = extrair_texto_do_turno(state["messages"])

    # Estagio 0 (non-disclosure, tolerancia-zero): SANEIA o raciocinio vazado -- strippa as bolhas de
    # meta-fala (que entregam a IA) e mantem a fala real. O texto saneado segue p/ o gate/judge (scan
    # + judge rodam no que VAI ao cliente). `msgs_saneadas` (AIMessages reescritas) viaja nos returns
    # de passagem: o coordenador re-deriva o texto das mensagens, entao o strip precisa estar nelas.
    # Turno 100%-raciocinio -> gatilho `mudo` do gate (regenera 1x; persistiu -> silencio, como
    # antes). NAO escala (leak saneado nao e brecha como ia_self).
    texto, msgs_saneadas = _sanear_raciocinio(msgs_turno, texto_cru)
    saneou_tudo = bool(msgs_saneadas) and not texto.strip()
    update_final: dict[str, Any] = {"messages": msgs_saneadas} if msgs_saneadas else {}
    if msgs_saneadas:
        OUTPUT_RACIOCINIO_SANEADO.labels("saneado" if texto.strip() else "mudo").inc()

    # A legenda da midia (arg `legenda` de enviar_midia) sai ao cliente como caption FORA da bolha
    # de texto -- precisa passar pelo MESMO scan/judge, senao escaparia do guard (A1). Coletada
    # ANTES do early-return de texto vazio p/ cobrir tambem turno so-midia.
    async with conexao(ctx.db_pool) as conn:
        legendas = await _legendas_do_turno(conn, ctx.turno_id)

    if not texto.strip() and not legendas and not saneou_tudo:
        # post_process ja zerou (pausa concorrente) ou turno sem texto/midia: nada a guardar.
        return Command(goto=END, update=update_final)  # type: ignore[arg-type]

    # bloqueio = substitui TODAS as AIMessages do turno por vazias (mesmo id -> reducer troca);
    # zerar so a ultima deixaria o texto da 1a passagem vivo p/ o coordenador despachar.
    vazias = _zerar_turno(msgs_turno)

    # Leak em LEGENDA e NAO-regeneravel: a legenda ja esta persistida como arg da tool (o
    # coordenador a despacha do DB, nao do content das mensagens) -- regenerar o texto nao a
    # consertaria. Barra o turno inteiro, comportamento pre-regen.
    if legendas:
        motivo_leg = _scan_vazamento("\n".join(legendas))
        if motivo_leg:
            OUTPUT_LEAK_DETECTADO.labels(motivo_leg).inc()
            await _bloquear(
                ctx,
                observacao=f"output_leak_{motivo_leg}",
                resumo=_RESUMO_LEAK,
                metric_key="output_leak",
            )
            return Command(goto=END, update={"messages": vazias})  # type: ignore[arg-type]

    # Gate pre-envio (producao assistida): scan de leak + detector de repeticao sobre o TEXTO, com
    # UMA regeneracao antes do fallback. A regen tambem passa pelo Estagio 0 e re-entra neste scan
    # (tentativa 2); persistiu -> fallback por gatilho: leak -> handoff (irreversivel se enviado);
    # repeticao -> dropa as bolhas repetidas (silencio > papagaio, sem handoff); mudo -> silencio.
    historicas = _bolhas_historicas(state["messages"])
    nova_msg: AIMessage | None = None
    gatilho_regen: str | None = None

    def _zeradas_todas() -> list[AIMessage]:
        """Bloqueio zera TODAS as AIMessages do turno -- inclusive a regenerada, se houver."""
        if nova_msg is None:
            return vazias
        return [*vazias, *_zerar_turno([nova_msg])]

    for tentativa in (1, 2):
        motivo = _scan_vazamento(texto) if texto.strip() else None
        repetidas: list[str] = []
        if not motivo and settings.output_guard_repeticao_habilitada and texto.strip():
            repetidas = bolhas_repetidas(texto, historicas)
        if motivo:
            gatilho = "leak"
        elif repetidas:
            gatilho = "repeticao"
        elif not texto.strip() and (saneou_tudo or nova_msg is not None):
            # turno 100%-raciocinio (t1) ou regen que devolveu vazio / foi toda saneada (t2).
            # Texto vazio SEM saneamento (turno so-midia) nao e mudo: cai no break e segue
            # direto p/ o judge das legendas.
            gatilho = "mudo"
        else:
            if nova_msg is not None:
                OUTPUT_REGEN.labels(gatilho_regen or "", "limpou").inc()
                # INFO de proposito (nao warning): e o caminho feliz do gate, mas o piloto de
                # producao assistida grepa isto no log do worker p/ medir quanto a regen segura.
                logger.info(
                    "output_guard regen limpou (gatilho=%s turno_id=%s)",
                    gatilho_regen,
                    ctx.turno_id,
                )
            break  # limpo (ou turno so-midia)

        if tentativa == 1 and settings.output_guard_regen_habilitado:
            gatilho_regen = gatilho
            nova = await _regenerar(
                state["messages"],
                msgs_turno,
                rascunho=texto if texto.strip() else texto_cru,
                gatilho=gatilho,
                settings=settings,
            )
            if nova is not None:
                # O texto final vive na PROPRIA nova_msg (id novo, usage proprio): o coordenador
                # re-deriva via `mensagens_do_turno` (usage != None) e acumula o custo dela.
                texto = _limpar_bolhas(texto_da_mensagem(nova))
                nova_msg = AIMessage(
                    id=nova.id,
                    content=texto,
                    usage_metadata=nova.usage_metadata
                    or UsageMetadata(input_tokens=0, output_tokens=0, total_tokens=0),
                    response_metadata=nova.response_metadata,
                )
                continue
            OUTPUT_REGEN.labels(gatilho, "indisponivel").inc()
        elif nova_msg is not None:
            OUTPUT_REGEN.labels(gatilho_regen or gatilho, "persistiu").inc()

        # Fallback (regen desligada/indisponivel ou o problema persistiu na 2a tentativa):
        if gatilho == "leak":
            assert motivo is not None
            OUTPUT_LEAK_DETECTADO.labels(motivo).inc()
            await _bloquear(
                ctx,
                observacao=f"output_leak_{motivo}",
                resumo=_RESUMO_LEAK,
                metric_key="output_leak",
            )
            return Command(goto=END, update={"messages": _zeradas_todas()})  # type: ignore[arg-type]
        if gatilho == "repeticao":
            conjunto = set(repetidas)
            texto = _drop_bolhas(texto, conjunto)
            OUTPUT_REPETICAO_DETECTADA.labels("dropada" if texto.strip() else "mudo").inc()
            if nova_msg is not None:
                nova_msg = AIMessage(
                    id=nova_msg.id,
                    content=texto,
                    usage_metadata=nova_msg.usage_metadata,
                    response_metadata=nova_msg.response_metadata,
                )
            else:

                def _limpa_e_dropa(t: str, _rep: set[str] = conjunto) -> str:
                    return _drop_bolhas(_limpar_bolhas(t), _rep)

                update_final = {"messages": _reescrever_turno(msgs_turno, _limpa_e_dropa)}
            break  # o que sobrou (se sobrou) ainda passa pelo judge
        # gatilho == "mudo": nada util a enviar -- silencio > raciocinio/papagaio. Com midia no
        # turno as legendas ainda precisam do judge (break); sem midia fecha mudo aqui.
        if legendas:
            break
        return Command(
            goto=END,  # type: ignore[arg-type]
            update={"messages": _zeradas_todas()} if nova_msg is not None else update_final,
        )

    if nova_msg is not None:
        # Despacho da regen: zera as AIMessages originais do turno e anexa a regenerada.
        update_final = {"messages": [*vazias, nova_msg]}

    # Negacao canned (pool curado): pula a Etapa 2 (texto ja confiavel). So sem midia -- uma
    # legenda precisa sempre passar pela Etapa 2, mesmo que a bolha de texto seja canned.
    if not legendas and texto.strip() in NEGACOES_CANNED:
        return Command(goto=END, update=update_final)  # type: ignore[arg-type]

    if not settings.output_guard_judge_habilitado:
        return Command(goto=END, update=update_final)  # type: ignore[arg-type]

    texto_guard = "\n".join(p for p in (texto, *legendas) if p.strip())
    if not texto_guard.strip():
        # tudo dropado pela repeticao e sem legenda: nada a julgar, fecha mudo.
        return Command(goto=END, update=update_final)  # type: ignore[arg-type]

    # Etapa 2: LLM-judge de AUP vinculante sobre texto + legendas (inclusive texto REGENERADO --
    # a regen nao pula o judge). Falha de infra -> default seguro.
    try:
        veredito = await _julgar_aup(texto_guard, settings)
    except Exception:
        logger.exception("output_guard judge falhou (turno_id=%s) -> default seguro", ctx.turno_id)
        AUP_SAIDA_BLOQUEADO.labels("judge_falhou").inc()
        await _bloquear(
            ctx, observacao="aup_saida_judge_falhou", resumo=_RESUMO_AUP, metric_key="aup_saida"
        )
        return Command(goto=END, update={"messages": _zeradas_todas()})  # type: ignore[arg-type]

    if veredito.viola:
        AUP_SAIDA_BLOQUEADO.labels("violou").inc()
        await _bloquear(
            ctx,
            observacao=f"aup_saida_{veredito.motivo}",
            resumo=_RESUMO_AUP,
            metric_key="aup_saida",
        )
        return Command(goto=END, update={"messages": _zeradas_todas()})  # type: ignore[arg-type]

    return Command(goto=END, update=update_final)  # type: ignore[arg-type]
