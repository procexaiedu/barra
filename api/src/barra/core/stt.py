"""O trilho de STT do Barra: bytes de audio -> texto, num lugar so.

Nasceu extraido de `workers/media.py` (06 §1.3), que ate aqui era o unico dono da transcricao.
O Agente financeiro (spec 0005, ticket 06) precisa OUVIR o mesmo tipo de audio de WhatsApp por
outro caminho — sincrono, dentro da porta unica, sem MinIO e sem `mensagens` — e a alternativa
seria um segundo prompt, um segundo modelo default e um segundo mapa de formato vivendo em
paralelo. Prompt de STT divergindo entre dois modulos e o tipo de coisa que ninguem percebe:
os dois transcrevem, so que um passa a traduzir ou a comentar o audio.

O que fica AQUI e o que e verdade sobre o provider (como se pede, o que se manda, o que conta
como "sem fala"). O que fica FORA e de cada chamador: de onde vem o byte, o que fazer com a
falha, e o retry — as tres coisas em que o job do agente de venda (fila ARQ, MinIO, canal Redis)
e a porta do Grupo financeiro (inline, best-effort, silencio) sao deliberadamente diferentes.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any, cast

from openai import AsyncOpenAI

# Modelo de STT quando o Env nao diz qual (o compose repassa a var e ela chega VAZIA se o
# Portainer nao a define) — mesmo padrao do vision em pix.py.
# Gemini 3.1 Flash Lite escolhido por bancada com os 2 audios reais do piloto (24/07), 3 rodadas
# por modelo: R$0,0016/audio, 1,7s e saida IDENTICA nas 3 rodadas. Os dois eixos que decidiram:
#  - fidelidade em entidade nomeada: capta o vocativo "Tati" (o cliente chamando a modelo, que se
#    chama Tatiane) onde a familia 2.5 ouve "ta" — proxy do que mais importa em audio de venda
#    (nome, valor, horario). A referencia forte diverge no ponto (2.5-pro le "ta", 3.1-pro le
#    "Tati"), mas o contexto da conversa decide a favor de "Tati".
#  - ESTABILIDADE: 3.5-flash-lite devolveu 3 transcricoes DIFERENTES em 3 rodadas do mesmo audio
#    ("Claudi"/"Claudio I"/"Claudio ai") mesmo com temperature=0 — descartado apesar de barato.
# Descartados tambem: 3.5-flash e 3.6-flash (4,5s, ~R$0,033 — 20x mais caro por ganho nenhum),
# gpt-audio-mini e voxtral (recusam ogg/opus, 400 do provider).
MODELO_STT_PADRAO = "google/gemini-3.1-flash-lite"

# O modelo de STT do OpenRouter e' um chat multimodal, nao um endpoint de transcricao: sem
# instrucao firme ele COMENTA o audio ("o audio diz que...") ou traduz. O marcador de silencio
# evita que ele invente fala onde nao ha (audio mudo/ruido) -- vira falha definitiva no caller.
SEM_FALA = "(sem fala)"
PROMPT_STT = (
    "Transcreva literalmente este audio em portugues do Brasil. "
    "Responda APENAS com a transcricao, sem aspas, sem comentarios, sem traduzir. "
    f"Se nao houver fala audivel, responda exatamente: {SEM_FALA}"
)

# `format` do content part `input_audio` (o WhatsApp manda ogg/opus; mp3/m4a aparecem em audio
# encaminhado). Desconhecido -> ogg, o caso dominante.
FORMATO_PADRAO = "ogg"
_FORMATOS = ("ogg", "mp3", "m4a", "wav")
_FORMATO_POR_EXTENSAO: dict[str, str] = {f".{f}": f for f in _FORMATOS}
# Os mimetypes que a Evolution/EvoGo carimba no audio de WhatsApp. `audio/mpeg` e mp3 pelo nome
# errado (o mimetype padrao de MP3), e `audio/mp4`/`audio/x-m4a` sao o audio encaminhado do iOS.
_FORMATO_POR_MIMETYPE: dict[str, str] = {
    "audio/ogg": "ogg",
    "audio/opus": "ogg",
    "audio/oga": "ogg",
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/mp4": "m4a",
    "audio/m4a": "m4a",
    "audio/x-m4a": "m4a",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/wave": "wav",
}


def formato_por_nome(nome: str) -> str:
    """Formato derivado da extensao do arquivo/objeto (`conversas/…/MSG1.ogg`)."""
    _, _, ext = nome.rpartition(".")
    return _FORMATO_POR_EXTENSAO.get(f".{ext.lower()}", FORMATO_PADRAO)


def formato_por_mimetype(mimetype: str | None) -> str:
    """Formato derivado do content-type entregue com os bytes.

    Quem baixa a midia do webhook tem o mimetype na mao e nao tem nome de arquivo (o audio nao
    passa pelo MinIO no Grupo financeiro). Parametro de codec (`audio/ogg; codecs=opus`) e ruido
    do WhatsApp: so o tipo/subtipo decide, e o que nao esta na tabela vira ogg — errar o rotulo
    e barato (o provider sniffa o container), fingir que nao ha audio nao e.
    """
    if not mimetype:
        return FORMATO_PADRAO
    base = mimetype.split(";")[0].strip().lower()
    return _FORMATO_POR_MIMETYPE.get(base, FORMATO_PADRAO)


@dataclass(frozen=True)
class Transcricao:
    """O que o provider devolveu. `texto=None` = audio sem fala (ou recusa/vazio do modelo).

    `usage` vem junto porque transcricao vazia TAMBEM queimou tokens: quem mede custo precisa
    dele mesmo no caminho em que nao ha texto (CUSTO-02).
    """

    texto: str | None
    usage: Any | None


async def transcrever(
    client: AsyncOpenAI, audio: bytes, *, formato: str, modelo: str = MODELO_STT_PADRAO
) -> Transcricao:
    """Transcreve os bytes via OpenRouter. NAO trata erro: `APIError` sobe para o chamador.

    E deliberado — a politica de falha e de quem chama: o job do agente de venda deixa o ARQ
    retentar, a porta do Grupo financeiro engole e segue calada. Uma politica embutida aqui
    serviria a um dos dois e atrapalharia o outro.
    """
    # `cast`: o TypedDict do SDK tipa `input_audio.format` como Literal["wav","mp3"] (o que a
    # OpenAI aceita), mas o OpenRouter aceita ogg/opus — o formato do WhatsApp. O wire e' JSON:
    # o campo viaja igual; so a anotacao do SDK e' estreita demais para este provider.
    conteudo = cast(
        Any,
        [
            {"type": "text", "text": PROMPT_STT},
            {
                "type": "input_audio",
                "input_audio": {
                    "data": base64.standard_b64encode(audio).decode("ascii"),
                    "format": formato,
                },
            },
        ],
    )
    resposta = await client.chat.completions.create(
        model=modelo,
        messages=[{"role": "user", "content": conteudo}],
        temperature=0,
    )
    escolhas = getattr(resposta, "choices", None) or []
    texto = (escolhas[0].message.content or "").strip() if escolhas else ""
    usage = getattr(resposta, "usage", None)
    if not texto or SEM_FALA in texto.lower():
        return Transcricao(texto=None, usage=usage)
    return Transcricao(texto=texto, usage=usage)
