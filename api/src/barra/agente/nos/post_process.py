"""No post_process.

M0: refetch de ia_pausada (cinto-suspensorio, 04 §3.5); se a IA foi pausada por um pipeline
    sem lock (Pix/foto portaria) no meio do turno, descarta o texto das AIMessages do turno
    (conteudo "") -- o coordenador detecta a resposta vazia e nao despacha humanizacao.
    Excecoes: bolha pre-`escalar` preservada, e toda escalada que sairia MUDA ao cliente ganha
    uma canned de espera no lugar do texto descartado -- a de GUARDA do registrar_extracao
    (escalada silenciosa, prod 22/07) e a que a propria IA decide sem escrever a bolha que o
    <quando_usar_escalar> pede. Excecao da excecao: `motivo=conteudo_ilegal`, onde a espera nao
    existe (a recusa seca fica sozinha).
M3+: extrai tambem a lista de midias dos tool_calls. Humanizacao real (chunking, presence,
    jitter, dedupe) entra em M4 como worker ARQ separado.

Fusao do turno do BOOK (campanha 13/08): quando o turno envia o book (>= 2 `enviar_midia`
    executadas) o <midia> manda o texto sair em UMA bolha ("essa e a UNICA bolha do turno") —
    e a alavanca de prompt FALHOU 0/5 (cenario duvida_das_fotos: 5/5 corridas com 2-3 bolhas
    mesmo com a instrucao explicita). A garantia vira deterministica aqui: as bolhas de texto
    do turno sao FUNDIDAS numa so, antes do output_guard (que re-escaneia a bolha fundida
    normalmente). Ver `_fundir_bolhas_do_book` para o criterio e a excecao de cotacao.
"""

import logging
import re
from collections.abc import Sequence
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langgraph.runtime import Runtime

from barra.core.db import conexao
from barra.dominio.atendimentos.service import MENSAGENS_GUARD_ESCALADA, extrair_precos_citados

from .._canned import escolher_espera_escalada
from .._texto_turno import (
    _tool_use_ids,
    extrair_texto_do_turno,
    kwargs_preservados,
    mensagens_do_turno,
    texto_da_mensagem,
)
from ..contexto import ContextAgente
from ..estado import EstadoAgente
from ..ferramentas.escalada import ESCALADA_ABERTA_PREFIXO

# Estagio 0 do guard reusado ANTES da fusao (ver `_fundir_bolhas_do_book`): a dependencia e de
# post_process -> output_guard e nunca o inverso (o guard nao importa nada daqui), entao nao ha
# ciclo; `nos/__init__` ja carrega o output_guard antes deste modulo.
from .output_guard import _limpar_bolhas

logger = logging.getLogger(__name__)


async def post_process(state: EstadoAgente, runtime: Runtime[ContextAgente]) -> dict[str, Any]:
    """Refetch ia_pausada; se pausou durante o turno, zera o texto da resposta."""
    # Webhook fino (atendimento_id None): nada a pausar — espelha o gate do prepare_context.
    if runtime.context.atendimento_id is None:
        return {}
    async with conexao(runtime.context.db_pool) as conn:
        result = await conn.execute(
            "SELECT ia_pausada FROM barravips.atendimentos WHERE id = %s",
            (runtime.context.atendimento_id,),
        )
        row = await result.fetchone()

    if not (row and row["ia_pausada"]):
        # Turno normal (nao pausado, nao zerado): unica intervencao possivel e a fusao das
        # bolhas do turno do book. Nos demais turnos ela e no-op e o retorno segue `{}`.
        return _fundir_bolhas_do_book(state)

    # Zera TODAS as AIMessages geradas no turno (mesmo id -> o reducer add_messages substitui por
    # vazia), nao so a ultima: na reentrada pos-tools o `[-1]` e uma ToolMessage, e quando ja houve
    # texto na 1a passagem (extracao/resposta inline) zerar so o ultimo deixaria essa fala viva p/ o
    # coordenador despachar APOS a pausa. Mesmo criterio (`mensagens_do_turno`) do output_guard.
    mensagens = mensagens_do_turno(state["messages"])

    # Excecao: quando a pausa e do PROPRIO turno (`escalar`), o prompt manda deixar uma bolha de
    # espera antes de chamar a tool -- zerar tudo faria toda escalada virar silencio ao cliente. O
    # corte fica DEPOIS da AIMessage que carrega o tool_call: o que a IA escrever pos-escalar (a
    # desobediencia que 04 §3.5 barra) continua descartado.
    corte = next(
        (
            i
            for i, m in enumerate(mensagens)
            if any(tc.get("name") == "escalar" for tc in (m.tool_calls or []))
        ),
        None,
    )
    alvo = mensagens if corte is None else mensagens[corte + 1 :]
    # PRESERVA usage_metadata + response_metadata, mesma invariante do `_zerar_turno` do
    # output_guard: `add_messages` SUBSTITUI a mensagem de mesmo id (nao faz merge), entao recriar
    # sem o usage apagava os tokens do turno do State. `custo_chat_turno_brl` soma justamente por
    # `usage_metadata` -> dava 0 -> `acumular_custo_atendimento` virava no-op (exige custo > 0) e o
    # turno pausado queimava DeepSeek sem entrar em `atendimentos.custo_ia_brl`. De quebra, sem o
    # usage essas mensagens sumiam de `mensagens_do_turno` e o trace perdia desfecho/raciocinio.
    # Pelo mesmo motivo o `additional_kwargs` vem junto (menos o espelho cru dos tool_calls): e
    # onde mora o `reasoning_content`, que o trace publica e que nunca vai ao cliente
    # (loop-massa r2 — a mesma perda foi medida do lado do output_guard).
    vazias: list[AIMessage] = [
        AIMessage(
            id=m.id,
            content="",
            usage_metadata=m.usage_metadata,
            response_metadata=m.response_metadata,
            additional_kwargs=kwargs_preservados(m),
        )
        for m in alvo
    ]

    if corte is None:
        # Escalada silenciosa (analise prod 22/07): quando a pausa nasce de uma GUARDA dentro do
        # registrar_extracao (piso de desconto, tipo nao aceito, reagendamento pos-bloqueio), nao
        # houve bolha de espera do `escalar` — zerar tudo deixaria o cliente no vacuo. Solta uma
        # canned de espera no lugar (usage_metadata zerado marca como gerada NESTE turno, mesmo
        # padrao da negacao do intercept_disclosure). Pausa de pipeline externo (Pix/foto portaria)
        # nao casa com as mensagens de guarda e segue silenciosa, como antes.
        #
        # A escalada por TOOL tambem entra por aqui quando o tool_call ja nao esta mais nas
        # AIMessages (qualquer zeramento anterior os descarta por design — `_KWARGS_DE_TOOL_CALL`)
        # e o `corte` nao tem como acha-lo: o rastro que sobrevive e a ToolMessage de sucesso do
        # `escalar` (ToolMessages nunca sao reescritas). Sem esta uniao, a escalada saia MUDA ao
        # cliente (campanha 13/08, eb02:21123135741957 t12). O caso `conteudo_ilegal` nao regride:
        # quando ha recusa seca escrita antes da tool, o corte ACHA o tool_call e decide no ramo de
        # baixo; este fallback so vale quando o rastro por tool_call ja se perdeu.
        precisa_espera = any(
            isinstance(m, ToolMessage)
            and (
                str(m.content) in MENSAGENS_GUARD_ESCALADA
                or str(m.content).startswith(ESCALADA_ABERTA_PREFIXO)
            )
            for m in state["messages"]
        )
    else:
        # Escalada decidida pela IA: a bolha de espera do <quando_usar_escalar> era SO prosa, e
        # quando a IA chama a tool sem escrever nada o turno sai mudo com a IA pausada — o mesmo
        # vacuo da escalada de guarda. O canned entra so quando o turno sairia mudo; a excecao vem
        # do arg `motivo` da propria tool_call (enum fechado, `ferramentas/escalada.py`): em
        # conteudo_ilegal "um momento" leria como "deixa eu ver se consigo", entao a recusa seca
        # fica sozinha — e a prosa segue sendo o unico site que cobre esse caso.
        motivos = {
            (tc.get("args") or {}).get("motivo")
            for tc in (mensagens[corte].tool_calls or [])
            if tc.get("name") == "escalar"
        }
        # O texto de antes do corte passa pelo MESMO filtro do coordenador
        # (`extrair_texto_do_turno`): o rascunho de uma passagem cuja tool ERROU nao chega ao
        # cliente, e conta-lo como bolha deixaria o vacuo de pe. As ToolMessages entram so para
        # esse conjunto de erros — a ordem delas nao afeta o texto agregado.
        texto_antes = extrair_texto_do_turno(
            [*mensagens[: corte + 1], *(m for m in state["messages"] if isinstance(m, ToolMessage))]
        )
        precisa_espera = "conteudo_ilegal" not in motivos and not texto_antes.strip()

    if precisa_espera:
        espera = AIMessage(
            content=escolher_espera_escalada(seed=runtime.context.turno_id),
            usage_metadata={"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        )
        return {"messages": [*vazias, espera]}
    return {"messages": vazias}


# ---------------------------------------------------------------------------------------------
# Fusao das bolhas do turno do BOOK
# ---------------------------------------------------------------------------------------------

# Mesmo piso do eval (`_mandou_o_book`, evals/e2e/massa.py): 1 midia e foto avulsa, nao book —
# o <midia> manda "2 ou 3 fotos, sempre foto antes de video" numa tacada so.
_BOOK_MIN_MIDIAS = 2
# Mesma gramatica de bolha do projeto: `workers/_chunking.chunk_texto` (split por linha em branco)
# e o check `_book_em_uma_bolha` do eval usam exatamente este separador.
_RE_SPLIT_BOLHAS = re.compile(r"\n\s*\n")
# Marker de quote no INICIO de uma bolha (mesma forma de `workers/_chunking._QUOTE_PREFIX`). Na
# fusao, o marker de uma bolha nao-inicial deixaria de abrir bloco e viraria texto cru no meio da
# bolha enviada; o da 1a bolha sobrevive (segue abrindo o bloco), os das seguintes sao descartados.
_RE_QUOTE_PREFIXO = re.compile(r"^\s*\[quote\s*(?::\s*[^\]]*?)?\]\s*", re.IGNORECASE)


def _ids_de_tool_com_erro(messages: Sequence[BaseMessage]) -> set[str]:
    """`tool_call_id`s cujo ToolMessage errou — mesmo criterio do `extrair_texto_do_turno`
    (o texto dessas passagens e rascunho superado e NUNCA vai ao cliente)."""
    return {
        m.tool_call_id
        for m in messages
        if isinstance(m, ToolMessage)
        and (m.status == "error" or str(m.content).startswith("ERRO:"))
        and m.tool_call_id
    }


def _turno_enviou_book(mensagens: Sequence[AIMessage], ids_com_erro: set[str]) -> bool:
    """True quando o turno ENVIOU o book: >= `_BOOK_MIN_MIDIAS` chamadas de `enviar_midia` que
    EXECUTARAM (tool_call sem ToolMessage de erro — midia que errou nao chegou ao cliente).

    A identificacao e pelo rastro que o turno normal carrega: os `tool_calls` das AIMessages
    geradas agora (`mensagens_do_turno`). So o zeramento descarta esse rastro por design
    (`_KWARGS_DE_TOOL_CALL`), e turno zerado nao passa por aqui."""
    enviadas = sum(
        1
        for m in mensagens
        for tc in m.tool_calls or []
        if tc.get("name") == "enviar_midia" and tc.get("id") not in ids_com_erro
    )
    return enviadas >= _BOOK_MIN_MIDIAS


def _tem_rastro_de_escalada(
    messages: Sequence[BaseMessage], mensagens: Sequence[AIMessage]
) -> bool:
    """Turno de escalada (tool `escalar` chamada, ou guarda de dominio que escala por dentro da
    extracao): o zeramento e a canned de espera sao quem manda — fundir interferiria no rastro."""
    if any(tc.get("name") == "escalar" for m in mensagens for tc in m.tool_calls or []):
        return True
    return any(
        isinstance(m, ToolMessage)
        and (
            str(m.content) in MENSAGENS_GUARD_ESCALADA
            or str(m.content).startswith(ESCALADA_ABERTA_PREFIXO)
        )
        for m in messages
    )


def _concatenar_bolhas(bolhas: Sequence[str]) -> str:
    """Concatena as bolhas numa so, preservando a ordem do conteudo.

    Gramatica da emenda: se a bolha da esquerda termina em palavra ("...nas fotos rs"), entra um
    ponto antes da proxima; terminando em pontuacao/emoji ("...pra voce 🥰", "...amor ?"), so o
    espaco. `\\n` SIMPLES dentro de uma bolha sobrevive (continua a mesma bolha p/ o chunking).

    O emoji NAO ganha ponto de proposito, e isso e contrato de VOZ, nao descuido: o texto fundido
    vai literal ao cliente (o chunking so re-parte por `\\n\\n`), e bolha da persona nao termina em
    pontuacao. Quem precisa da fronteira que o emoji nao da e o output_guard, que julga por FRASE
    em quatro sitios — la ela e reconstruida no split (`_COSTURA_DE_BOLHA`), sem tocar no texto."""
    fundida = bolhas[0].strip()
    for bruto in bolhas[1:]:
        bolha = _RE_QUOTE_PREFIXO.sub("", bruto).strip()
        if not bolha:
            continue
        separador = ". " if fundida and fundida[-1].isalnum() else " "
        fundida = f"{fundida}{separador}{bolha}" if fundida else bolha
    return fundida


def _reescrita_de_conteudo(m: AIMessage, content: str) -> AIMessage:
    """Reescrita de CONTEUDO — nao e zeramento. Preserva id (o reducer `add_messages` substitui a
    mensagem de mesmo id), `tool_calls` (o rastro das midias do turno; o check 5c do coordenador
    continua lendo exatamente o que leria), usage/response_metadata (custo e tarifa do turno) e o
    `additional_kwargs` INTEIRO — inclusive o espelho cru dos tool_calls, porque a mensagem SEGUE
    tendo os tool_calls (o descarte do espelho e exclusivo do caminho de zeramento,
    `_KWARGS_DE_TOOL_CALL`), e o `reasoning_content` do trace viaja junto."""
    return AIMessage(
        id=m.id,
        content=content,
        tool_calls=m.tool_calls,
        usage_metadata=m.usage_metadata,
        response_metadata=m.response_metadata,
        additional_kwargs=m.additional_kwargs,
    )


def _fundir_bolhas_do_book(state: EstadoAgente) -> dict[str, Any]:
    """Funde numa UNICA bolha o texto do turno que enviou o book (alavanca deterministica).

    O <midia> ja manda ("o envio do book e um ato unico ... essa e a UNICA bolha do turno") e o
    modelo desobedece com consistencia (duvida_das_fotos 0/5 na alavanca de prompt). Roda ANTES do
    output_guard, que re-escaneia a bolha fundida normalmente; roda SO em turno normal (o caminho
    de pausa/zeramento retorna antes) e nunca em turno com rastro de escalada ou mute.

    Excecao documentada no proprio <midia> ("so o turno que ainda precisa cotar tem as bolhas a
    mais do trilho acima"): o turno que COTA junto com o book sai no trilho de 3 bolhas
    (reconhecimento / valor / linha do book), com o preco em bolha propria. O detector e o mesmo
    scanner de preco do dominio (`extrair_precos_citados`, o que o output_guard usa no
    preco-fantasma): preco citado nas bolhas => a cotacao saiu NESTE turno => nao funde. E o
    mesmo contrato que o eval mede (`_book_em_uma_bolha`, evals/e2e/massa.py): o check so olha o
    turno da duvida das fotos, onde o preco ja estava na mesa e nenhuma bolha carrega numero."""
    if state.get("_mute_por_erro_de_tool"):
        return {}
    messages = state["messages"]
    mensagens = mensagens_do_turno(messages)
    ids_com_erro = _ids_de_tool_com_erro(messages)
    if not _turno_enviou_book(mensagens, ids_com_erro):
        return {}
    if _tem_rastro_de_escalada(messages, mensagens):
        return {}

    # O MESMO texto agregado que o coordenador despacha e o guard escaneia (rascunho de passagem
    # com tool errada ja excluido) — fonte unica, `_texto_turno.extrair_texto_do_turno`.
    texto = extrair_texto_do_turno(messages)
    # Estagio 0 do guard ANTES da fusao, por bolha (ciclo 8). A fusao apaga a fronteira entre
    # bolhas, e o guard julga POR BOLHA: fundir uma bolha que ele descartaria inteira (narracao de
    # mecanica do 2o passe, placeholder, promessa sem limite) contamina a fala boa e o guard passa
    # a derrubar as duas — foi assim que o turno "Sou eu mesma amor 🥰" + narracao saiu zerado.
    # Filtrar aqui e literalmente o invariante que o guard promete: fundir(guard(a), guard(b)) em
    # vez de guard(fundir(a, b)). `_limpar_bolhas` e distributivo sobre o `\n\n`, entao aplica-lo
    # por bolha e o mesmo que aplica-lo no agregado — e evita o descasamento de separador entre o
    # `\n\n` exato dele e o `\n\s*\n` daqui. Sobrando menos de duas bolhas nao ha o que fundir: o
    # turno segue intocado e o guard limpa como sempre (nao ha caminho em que o lixo escape).
    bolhas = [limpa for b in _RE_SPLIT_BOLHAS.split(texto) if (limpa := _limpar_bolhas(b).strip())]
    if len(bolhas) < 2:
        return {}
    if extrair_precos_citados(texto):
        return {}

    # Quem contribui texto ao agregado (mesmo filtro do extrair_texto_do_turno): a 1a leva a bolha
    # fundida, as demais esvaziam — a ordem do conteudo ja esta preservada dentro da fundida.
    contribuintes = [
        m
        for m in mensagens
        if texto_da_mensagem(m) and not (ids_com_erro and (_tool_use_ids(m) & ids_com_erro))
    ]
    if not contribuintes:
        return {}
    fundida = _concatenar_bolhas(bolhas)
    logger.info("book_bolhas_fundidas n_bolhas=%d n_mensagens=%d", len(bolhas), len(contribuintes))
    return {
        "messages": [
            _reescrita_de_conteudo(m, fundida if i == 0 else "")
            for i, m in enumerate(contribuintes)
        ]
    }
