"""O olho do Agente financeiro (spec 0005, ticket 07): imagem do grupo -> Comprovante lido.

Irmao de `transcricao.py` e pelas mesmas razoes: aqui mora so a IDA AO PROVIDER; o que fazer com
o que foi lido (abater, reter, perguntar, pedir reenvio) e da porta unica. Sincrono e sem MinIO —
enfileirar exigiria uma segunda entrada no modulo, e a foto do comprovante nao tem uso depois de
lida (o que se guarda dela e o dado, em `comprovantes_do_grupo`).

O trilho e o **mesmo do comprovante de Pix do agente de venda** (`core/vision.py`, extraido de
`workers/pix.py`): mesmo provider, mesmo json_schema estrito, mesma leitura de `finish_reason`.
O que muda e o documento e a pergunta que se faz a ele — la e "o cliente pagou o deslocamento
combinado?", aqui e "quanto a modelo transferiu, quando e para quem".

Desde o ticket 06 sao DOIS documentos na mesma chamada, e nao duas chamadas: transferencia (Pix,
TED) e **venda no cartao** (o print da maquininha que ela ja manda). Numa chamada so porque a foto
chega sem legenda e nada barato distingue as duas antes do vision — e porque a segunda pergunta e a
mesma da primeira com outro campo de resposta: la o destino e a chave, aqui e o nome do
ESTABELECIMENTO (ADR-0049 §6). Os dois nunca sao verdade juntos, e o desempate e no codigo, nao no
prompt (ver `ExtracaoDoComprovante.como_leitura`).

Duas escolhas de custo, porque toda imagem do grupo passa por aqui:

* **A triagem "isto e um comprovante?" e do proprio vision** (`e_comprovante`), e nao um passo
  barato antes dele. Nao ha classificador barato de imagem nesta casa: qualquer heuristica
  (tamanho, mimetype, caption) erraria justamente no comprovante sem legenda, que e como ele
  chega. O grupo posta poucas fotos por semana — o gasto e conhecido e pequeno.
* **A porta so chama isto para imagem de OUTRA pessoa e nao duplicada** (mesma ordem do audio):
  eco do proprio agente e segunda entrega do router morrem antes do provider.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import date, datetime
from typing import Any

from openai import AsyncOpenAI
from pydantic import BaseModel, ConfigDict, Field

from barra.agente._custo import calcular_custo_vision_brl
from barra.core.metrics import AGENTE_CUSTO_VISION_BRL
from barra.core.vision import (
    MODELO_VISION_PADRAO,
    ValorEmReais,
    VisionInconclusiva,
    detectar_mime_imagem,
    extrair_da_imagem,
)
from barra.dominio.grupo_financeiro.comprovante import LeituraDoComprovante
from barra.dominio.grupo_financeiro.modelos import ImagemDoGrupo

_logger = logging.getLogger(__name__)

LerComprovante = Callable[[ImagemDoGrupo], Awaitable[LeituraDoComprovante | None]]
"""Ler uma imagem do grupo. `None` = nao deu para ler (provider fora, resposta inconclusiva) —
distinto de `LeituraDoComprovante(e_comprovante=False)`, que e "li, e nao e comprovante"."""

_BASE_URL_OPENROUTER = "https://openrouter.ai/api/v1"

# O modelo de vision (e o porque da escolha) mora em `core/vision.py`: o Grupo financeiro e o
# agente de venda leem comprovante pelo MESMO trilho, e duas listas de default divergiriam no
# primeiro dia em que uma fosse atualizada e a outra nao.

# Teto de espera do provider. Mesmo raciocinio do STT da porta (`transcricao.py`): este caminho e
# sincrono dentro do webhook e um POST pendurado vira reentrega da Evolution — comprovante
# duplicado, nao comprovante lido.
_TIMEOUT_S = 20.0
_MAX_RETRIES = 1

PROMPT_COMPROVANTE = """Voce le comprovantes de pagamento brasileiros. Devolve SO o JSON do schema.

Sao DOIS documentos diferentes, e a primeira decisao e qual dos dois voce esta vendo:
(A) TRANSFERENCIA (Pix, TED, transferencia entre contas) -> e_comprovante=true, e_de_cartao=false.
(B) VENDA NO CARTAO (comprovante/recibo de maquininha: debito, credito, aproximacao; costuma
    trazer "COMPROVANTE DE VENDA", "VENDA APROVADA", bandeira do cartao, numero mascarado, NSU,
    AUT, "VIA CLIENTE"/"VIA ESTABELECIMENTO") -> e_de_cartao=true, e_comprovante=false.
NUNCA marque os dois true. Se nao for nem um nem outro (foto de pessoa, print de site, print de
anuncio, sticker, cardapio, documento), os dois sao false.

CAMPOS:
- e_comprovante: true SOMENTE no caso (A) — transferencia bancaria ou Pix.
- e_de_cartao: true SOMENTE no caso (B) — venda passada em maquininha/cartao.
- legivel: true se der para ler o valor. false se a imagem estiver cortada, desfocada, escura ou
  o valor ilegivel.
- valor: total em BRL, como TEXTO e SEMPRE com 2 casas decimais (ex.: "1200.00"). Sem "R$", sem
  separador de milhar: mil e duzentos reais e "1200.00". NULL se ilegivel.
- data: data no formato AAAA-MM-DD. NULL se nao aparecer.
- pagador: nome de quem FEZ a transferencia (quem pagou). NULL se nao aparecer. Em comprovante de
  cartao (B) quase nunca aparece — se so houver o numero mascarado do cartao, e NULL.
- chave_destino: a chave Pix de quem RECEBEU, copiada como aparece (CPF/CNPJ so digitos, e-mail,
  telefone, ou aleatoria em UUID). NULL se nao aparecer, e SEMPRE NULL no caso (B).
- titular_destino: nome de quem RECEBEU a transferencia. NULL se nao aparecer.
- estabelecimento: SO no caso (B) — o nome do estabelecimento que recebeu a venda, copiado como
  aparece (costuma ficar no topo do comprovante, ou junto do CNPJ). NULL no caso (A).

Nao invente nenhum campo: o que nao estiver na imagem e NULL.

EXEMPLO de saida (valores ficticios, so para mostrar o FORMATO — nunca copie nada daqui):
{"e_comprovante": true, "e_de_cartao": false, "legivel": true, "valor": "1200.00", "data": "2026-08-12", "pagador": "Fulana de Tal", "chave_destino": "00000000-0000-0000-0000-000000000000", "titular_destino": "Fulano de Tal", "estabelecimento": null}
"""
# O exemplo e deliberadamente FICTICIO, e nao o comprovante real que motivou o ticket. Dois
# motivos, e o segundo e o que morde:
#   1. o prompt sobe para o provider em TODA imagem postada em qualquer Grupo financeiro — chave
#      Pix viva e nome civil da casa nao tem por que viajar junto (nem morar no git);
#   2. o unico exemplo do prompt e o valor que o modelo tende a emitir quando o campo esta
#      ilegivel. Com a chave real ali, um comprovante ruim voltaria com a chave da casa,
#      `papel_da_chave()` diria "casa" e o aviso "destino fora da lista da casa" — a defesa
#      antifraude da user story 11 — deixaria de disparar exatamente no comprovante suspeito.
# A chave real da casa mora onde cadastro mora: `barravips.chaves_pix_conhecidas`.
#
# ⚠️ Pela MESMA razao o exemplo do estabelecimento e `null` e o prompt NAO cita PagBank nem
# InfinitePay, que sao os nomes que a reuniao de 20/08 diz esperar no print da maquininha dela. O
# estabelecimento e o campo que decide o BOLSO da venda (ADR-0049 §6): um nome real no prompt e o
# nome que volta quando o topo do cupom esta ilegivel, e a maquininha dela viraria a da casa (ou o
# contrario) sem que nada no sistema acusasse. O registro de quem e cada maquininha mora em
# `barravips.estabelecimentos_conhecidos`, e ele se preenche pela fila de sugestoes (ticket 05).


class ExtracaoDoComprovante(BaseModel):
    """Schema de saida do vision. `extra="forbid"` <-> `additionalProperties:false` no JSON Schema
    (sem isso o roteamento dinamico do OpenRouter pode aceitar campo extra em silencio)."""

    model_config = ConfigDict(extra="forbid")

    e_comprovante: bool = Field(description="A imagem e um comprovante de transferencia/Pix?")
    legivel: bool = Field(description="Da para ler o valor da transferencia?")
    e_de_cartao: bool = Field(
        False, description="A imagem e um comprovante de venda em maquininha (cartao)?"
    )
    valor: ValorEmReais = Field(None, description='Valor transferido em BRL, texto: "1200.00".')
    data: str | None = Field(None, description="Data da transferencia, AAAA-MM-DD.")
    pagador: str | None = Field(None, description="Nome de quem fez a transferencia.")
    chave_destino: str | None = Field(None, description="Chave Pix de quem recebeu.")
    titular_destino: str | None = Field(None, description="Nome de quem recebeu.")
    estabelecimento: str | None = Field(
        None, description="Nome do estabelecimento, so em comprovante de cartao."
    )

    def como_leitura(self) -> LeituraDoComprovante:
        """Converte para o tipo do dominio — e e aqui que a data vira `date` ou desaparece.

        Data invalida (o modelo escreveu "12/08/2026" ou inventou "2026-13-40") vira `None` em vez
        de derrubar a leitura: o comprovante ainda vale pelo VALOR, que e o que abate venda. Um
        `ValidationError` aqui transformaria um recibo legivel em pedido de reenvio.

        **Cartao desliga transferencia, aqui e nao no prompt** (ticket 06). O prompt manda nunca
        marcar os dois, mas quem paga o preco de o modelo desobedecer e o dinheiro: um print de
        maquininha com `e_comprovante=True` entra no abate FIFO e da por comprovada uma
        transferencia que a modelo nunca fez — a venda sai da fila de cobranca e ninguem descobre
        olhando o grupo. O lado seguro do desempate e o cartao: ele nao abate nada, e uma
        transferencia lida como cartao no maximo deixa de abater (que o proximo comprovante, ou o
        gestor, resolve).

        Pelo mesmo motivo a chave de destino cai junto: comprovante de venda no cartao NAO tem
        chave Pix, entao um destino lido ali e alucinacao — e ele entraria na fila de sugestoes de
        chave como um fantasma que ninguem consegue classificar.
        """
        e_de_cartao = self.e_de_cartao
        return LeituraDoComprovante(
            e_comprovante=self.e_comprovante and not e_de_cartao,
            legivel=self.legivel,
            valor=self.valor,
            data=_como_data(self.data),
            pagador=_limpo(self.pagador),
            chave_destino=None if e_de_cartao else _limpo(self.chave_destino),
            titular_destino=_limpo(self.titular_destino),
            e_de_cartao=e_de_cartao,
            estabelecimento=_limpo(self.estabelecimento) if e_de_cartao else None,
        )


def _como_data(texto: str | None) -> date | None:
    if not texto:
        return None
    try:
        return datetime.strptime(texto.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def _limpo(texto: str | None) -> str | None:
    limpo = (texto or "").strip()
    return limpo or None


_cliente_cache: dict[str, AsyncOpenAI] = {}


def _cliente(api_key: str) -> AsyncOpenAI:
    """Um cliente por chave, reusado pelo processo (o da API nao tem `ctx` de worker onde morar)."""
    cliente = _cliente_cache.get(api_key)
    if cliente is None:
        cliente = AsyncOpenAI(
            api_key=api_key,
            base_url=_BASE_URL_OPENROUTER,
            timeout=_TIMEOUT_S,
            max_retries=_MAX_RETRIES,
        )
        _cliente_cache[api_key] = cliente
    return cliente


def leitor_de_comprovante(settings: Any) -> LerComprovante | None:
    """Monta o leitor que a porta usa, ou `None` quando nao ha provider configurado.

    `None` explicito em vez de um leitor que sempre falha: e a MESMA distincao do ouvido (ticket
    06) e ela ja custou caro nesta casa — `OPENROUTER_API_KEY` sumiu num redeploy e o OCR do Pix
    passou dias marcando tudo `em_revisao` sem ninguem entender por que (24/07). Configuracao
    faltando e um problema nosso; provider com dia ruim e outro.
    """
    api_key = getattr(settings, "openrouter_api_key", None)
    if not api_key:
        return None
    modelo = getattr(settings, "openrouter_model_vision_pix", None) or MODELO_VISION_PADRAO
    cotacao = getattr(settings, "usd_brl_cotacao", 0.0)
    cliente = _cliente(api_key)

    async def ler(imagem: ImagemDoGrupo) -> LeituraDoComprovante | None:
        try:
            leitura = await extrair_da_imagem(
                imagem.conteudo,
                # Pelos BYTES, nunca pelo `mimetype` do envelope: a EvoGo entrega vazio e a
                # Evolution as vezes mente na extensao.
                media_type=detectar_mime_imagem(imagem.conteudo),
                client=cliente,
                modelo=modelo,
                prompt=PROMPT_COMPROVANTE,
                esquema=ExtracaoDoComprovante,
            )
        except VisionInconclusiva as exc:
            # CUSTO-02: a chamada truncada/recusada tambem queimou tokens.
            _observar_custo(modelo, exc.usage, cotacao)
            _logger.warning(
                "grupo_financeiro_comprovante_inconclusivo motivo=%s bytes=%d",
                exc.motivo,
                len(imagem.conteudo),
            )
            return None
        _observar_custo(modelo, leitura.usage, cotacao)
        return leitura.dados.como_leitura()

    return ler


def _observar_custo(modelo: str, usage: Any | None, cotacao: float) -> None:
    AGENTE_CUSTO_VISION_BRL.labels(modelo).observe(calcular_custo_vision_brl(usage, cotacao))
