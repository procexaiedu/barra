"""O trilho de vision do Barra: bytes de imagem -> JSON tipado, num lugar so.

Nasceu extraido de `workers/pix.py` (06 §2.2), ate aqui o unico dono do OCR. O Agente financeiro
(spec 0005, ticket 07) precisa LER outro comprovante — o **Comprovante de transferencia** que a
modelo posta no Grupo financeiro — por outro caminho: sincrono, dentro da porta unica, sem MinIO
e sem `atendimentos`. A alternativa seria uma segunda chamada de vision vivendo em paralelo, com
as mesmas quatro sutilezas para acertar de novo:

* `provider.require_parameters=true` — sem isso o roteamento dinamico do OpenRouter pode cair num
  provider que IGNORA o `json_schema` e devolve prosa;
* `additionalProperties:false` (via `extra="forbid"` no modelo Pydantic) pelo mesmo motivo;
* **imagem ANTES do texto** no `content` (ordem que o provider recomenda para OCR);
* `finish_reason` chega em **200 OK**: `length`/`content_filter` nao sao excecao de rede, sao um
  sucesso HTTP com JSON truncado ou recusa — quem nao olha, tenta parsear e explode em
  `ValidationError` no lugar errado.

O que fica AQUI e o que e verdade sobre o provider. O que fica FORA e de cada chamador: de onde
vem o byte, qual e o prompt/schema do documento, o que fazer com a falha e quem observa o custo —
as coisas em que o job do agente de venda (fila ARQ, MinIO, atendimento que nao pode travar) e a
porta do Grupo financeiro (inline, best-effort, silencio) sao deliberadamente diferentes.
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any

from openai import AsyncOpenAI
from pydantic import BaseModel, BeforeValidator, WithJsonSchema

_logger = logging.getLogger(__name__)

# Teto de saida de uma extracao de comprovante. O JSON de um comprovante cabe em ~110 tokens; o
# resto do teto e o colchao do raciocinio invisivel, que num comprovante ambiguo (um QR, uma foto
# torta) chega a ~700 antes de o modelo escrever a primeira chave. Com 800 isso truncava 1 leitura
# a cada ~50 e o comprovante inteiro se perdia; com 1600, 0 em 32 nas fotos reais. O teto NAO e o
# que se paga: cobra-se o que foi gerado, e a leitura tipica continua custando os mesmos ~110.
MAX_TOKENS_PADRAO = 1600

# O modelo de vision quando o Env nao diz qual. Medido em 14/08/2026 sobre as fotos reais do Grupo
# financeiro (4 comprovantes de 2 bancos + negativos, cada um em 4 degradacoes de WhatsApp):
#
#   gemini-3.1-flash-lite-preview   99,8% dos campos   p50 1,8s   US$0,0007/img   0 truncadas
#   gemini-3.5-flash-lite           94,8%              p50 1,7s   US$0,0007/img
#   gemini-3-flash-preview (antigo) 94,6%              p50 2,6s   US$0,0014/img   3 truncadas
#
# O `-preview` no fim NAO e descuido: `google/gemini-3.1-flash-lite` (sem sufixo) e outro
# roteamento no OpenRouter — "Google" (Vertex) em vez de "Google AI Studio" — e le PIOR o mesmo
# comprovante: 74,3% dos campos, com o valor devolvido em centavos ("65807" para R$ 658,07). Ao
# trocar de modelo, remeça: no OpenRouter o nome nao determina quem serve.
MODELO_VISION_PADRAO = "google/gemini-3.1-flash-lite-preview"

PADRAO_VALOR_EM_REAIS = r"^\d{1,9}\.\d{2}$"
"""Como o valor e pedido ao provider: TEXTO com duas casas, nunca `number`. Ver `ValorEmReais`."""


def _como_decimal(bruto: Any) -> Any:
    """O que o provider mandou -> `Decimal`, sem NUNCA levantar.

    Levantar aqui trocaria um comprovante legivel por um `ValidationError` no meio da porta —
    a mesma fronteira que ja custou turno neste projeto. Formato torto vira `None`, que os dois
    chamadores ja sabem tratar ("nao deu para ler").

    **Numero inteiro, sem centavos, e recusado** — e a unica regra severa daqui. Um provider que
    ignora o padrao devolve "65807" para R$ 658,07 (medido no roteamento Vertex do
    gemini-3.1-flash-lite), e "65807" tambem e a grafia legitima de R$ 65.807. Nao da para
    decidir, e os dois erros nao se pagam: perder a leitura custa um "reenvia?", e aceitar custa
    um comprovante 100x maior abatendo venda que ninguem pagou.
    """
    if bruto is None or isinstance(bruto, Decimal):
        return bruto
    if isinstance(bruto, int | float):
        return Decimal(str(bruto))
    if not isinstance(bruto, str):
        return None
    texto = bruto.strip().removeprefix("R$").replace(" ", "").replace("\xa0", "")
    if "," in texto:  # "1.200,00" -> "1200.00" (o provider ignorou o padrao e escreveu em BR)
        texto = texto.replace(".", "").replace(",", ".")
    if texto and "." not in texto:
        _logger.warning("vision_valor_sem_centavos bruto=%r", bruto)
        return None
    try:
        return Decimal(texto)
    except InvalidOperation:
        return None


ValorEmReais = Annotated[
    Decimal | None,
    BeforeValidator(_como_decimal),
    WithJsonSchema(
        {"anyOf": [{"type": "string", "pattern": PADRAO_VALOR_EM_REAIS}, {"type": "null"}]}
    ),
]
"""Dinheiro lido de uma imagem: `Decimal` para quem usa, **texto** para quem gera.

Medido em 14/08/2026 com as fotos reais do Grupo financeiro: com o campo declarado como
`number` (o que `Decimal | None` gera sozinho), o Gemini 3 Flash truncava **4 de 10** leituras —
e nao por raciocinio, mas por um LOOP DE DIGITOS do decodificador restrito:

    {"valor": 1200.000000000000227373675443232059478759765625e00000000000000000...

A gramatica de `number` aceita digito para sempre; a saida bate no `max_tokens`, volta
`finish_reason=length` e o comprovante inteiro se perde. Como texto com padrao, a gramatica
TERMINA: 0 em 40 leituras truncaram, com os mesmos ~100 tokens de saida.

O modo de falha e o pior possivel — 200 OK, sem excecao, e some so uma parte das leituras: no
agente de venda vira `em_revisao` sem motivo aparente, e no Grupo financeiro vira silencio.
"""


class VisionInconclusiva(Exception):
    """Vision terminou sem extracao utilizavel (max_tokens/refusal/content vazio), em 200 OK.

    Carrega o `usage` porque a chamada inconclusiva TAMBEM queimou tokens (CUSTO-02): quem mede
    custo precisa dele justamente no caminho em que nao ha resultado. Sem isso, o gasto do
    comprovante ilegivel — o mais caro em tentativas repetidas — sumiria da conta.
    """

    def __init__(self, motivo: str, *, usage: Any | None = None) -> None:
        super().__init__(motivo)
        self.motivo = motivo
        self.usage = usage


@dataclass(frozen=True)
class LeituraDaImagem[T: BaseModel]:
    """O que o provider devolveu: os dados ja validados pelo schema do chamador + o `usage`."""

    dados: T
    usage: Any | None


def detectar_mime_imagem(dados: bytes) -> str:
    """Mime por magic bytes (06 §2.4). Cobre os 4 formatos que o vision aceita.

    Pelos BYTES e nao pela extensao/`mimetype` do envelope: a URL da Evolution mente (`.jpeg` em
    webp) e a EvoGo entrega mimetype vazio. Desconhecido -> jpeg, o caso dominante do WhatsApp.
    """
    if dados[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if dados[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if dados[:4] == b"RIFF" and dados[8:12] == b"WEBP":
        return "image/webp"
    if dados[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return "image/jpeg"


async def extrair_da_imagem[T: BaseModel](
    imagem: bytes,
    *,
    media_type: str,
    client: AsyncOpenAI,
    modelo: str,
    prompt: str,
    esquema: type[T],
    max_tokens: int = MAX_TOKENS_PADRAO,
) -> LeituraDaImagem[T]:
    """OCR estruturado via OpenRouter. NAO trata erro de rede: `APIError` sobe para o chamador.

    Deliberado, mesma escolha de `core/stt.py`: a politica de falha e de quem chama (o job do Pix
    marca `em_revisao` e segue; a porta do Grupo financeiro pede reenvio e cala). Uma politica
    embutida aqui serviria a um dos dois e atrapalharia o outro.

    `reasoning.effort=low`: os modelos default de vision sao "thinking" — ler um recibo nao pede
    raciocinio profundo, e a duvida e tratada deterministicamente por quem chama. Modelos sem
    thinking ignoram o campo.
    """
    b64 = base64.standard_b64encode(imagem).decode("ascii")
    resposta = await client.chat.completions.create(
        model=modelo,
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": esquema.__name__,
                "schema": esquema.model_json_schema(),
                "strict": True,
            },
        },
        extra_body={
            "provider": {"require_parameters": True},
            "reasoning": {"effort": "low"},
        },
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{media_type};base64,{b64}"},
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ],
        max_tokens=max_tokens,
    )
    usage = getattr(resposta, "usage", None)
    escolha = resposta.choices[0]
    # `getattr` porque fakes de teste podem nao expor `finish_reason` (o provider real sempre expoe).
    finish_reason = getattr(escolha, "finish_reason", None)
    conteudo = escolha.message.content
    if finish_reason in ("length", "content_filter") or not conteudo:
        raise VisionInconclusiva(finish_reason or "content_vazio", usage=usage)
    return LeituraDaImagem(dados=esquema.model_validate_json(conteudo), usage=usage)
