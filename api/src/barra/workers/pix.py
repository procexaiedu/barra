"""Job ARQ `validar_pix` (06 §2.2 + §0 emendas grilling 2026-05-23).

Pipeline: baixa o comprovante do MinIO -> OpenRouter vision com response_format json_schema
-> compara plausibilidade/valor/chave/titular -> persiste em `comprovantes_pix` -> aplica
`atualizar_pix` pela porta unica de `escaladas.service` (que avanca o atendimento para
`Confirmado` + `ia_pausada` em ambos os branches) -> enfileira o card no grupo de
Coordenacao por modelo.

O fluxo **nunca trava por Pix** (01 §6.1): validado E em_revisao levam o atendimento adiante;
a duvidez de em_revisao e informativa (sinaliza no card a modelo e cai na fila de revisao
assincrona de Fernando no painel).

Sem `timestamp` (emenda §0 item 11: skew BRT/UTC marca falso quase tudo, e sendo nao-bloqueante
so gerava ruido). Sem fallback a `media_url` da Evolution (emenda §0 item 2: a URL expira; a
midia ja foi subida pro MinIO pelo webhook fino).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Literal, cast
from uuid import UUID

from openai import AsyncOpenAI
from psycopg import AsyncConnection
from pydantic import BaseModel, ConfigDict, Field

from barra.agente._custo import calcular_custo_vision_brl
from barra.core.metrics import (
    AGENTE_CUSTO_VISION_BRL,
    PIX_DIVERGENCIA,
    PIX_VALIDACAO_DECISAO,
    PIX_VALIDACAO_DURACAO,
)
from barra.core.vision import (
    MODELO_VISION_PADRAO,
    ValorEmReais,
    VisionInconclusiva,
    detectar_mime_imagem,
    extrair_da_imagem,
)
from barra.dominio.escaladas.service import aplicar_comando
from barra.dominio.grupo_financeiro.comprovante import (
    ChaveComDono,
    MotivoDeSuspeita,
    marcar_suspeita,
    normalizar_chave,
)
from barra.dominio.grupo_financeiro.repo import registro_de_chaves
from barra.settings import get_settings

logger = logging.getLogger(__name__)


# Alias de modulo (posicao de valor): mantem as aspas dos membros do Literal — em anotacao,
# com `from __future__ import annotations`, o autofix UP do ruff as removeria (F821).
Confianca = Literal["alta", "media", "baixa"]

# `VisionInconclusiva` mudou de casa (spec 0005, ticket 07: o Agente financeiro le comprovante
# pelo MESMO trilho, `core/vision.py`) e continua exportada daqui: e a mesma classe, entao quem
# ja capturava `workers.pix.VisionInconclusiva` segue capturando. Pix NUNCA trava (01 §6.1) —
# `validar_pix` a captura e marca o comprovante DUVIDOSO em vez de propagar.


# --- Schema de saida do vision -----------------------------------------------
# `extra="forbid"` <-> JSON Schema `additionalProperties:false` (06 §0 ressalva 4a +
# cruzamento doc oficial 24-05): sem isso o roteamento dinamico do OpenRouter pode aceitar
# campos extras silenciosamente.
class ExtracaoPix(BaseModel):
    model_config = ConfigDict(extra="forbid")

    valor: ValorEmReais = Field(None, description='Valor pago em BRL, texto: "100.00".')
    chave_pix_destinatario: str | None = Field(
        None, description="Chave Pix do beneficiario (CPF, email, telefone, aleatoria)."
    )
    titular_destinatario: str | None = Field(None, description="Nome do titular do beneficiario.")
    banco_origem: str | None = Field(None, description="Banco emissor do pagamento.")
    plausibilidade_visual: bool = Field(
        description=(
            "True se a imagem parece um comprovante real; False se suspeita "
            "(montagem, screenshot de outro app, recibo manuscrito)."
        )
    )
    motivo_se_implausivel: str | None = Field(
        None,
        description="Motivo curto quando plausibilidade_visual=False; vazio caso contrario.",
    )
    confianca: Confianca = Field(
        description=(
            "Confianca na LEGIBILIDADE da extracao (distinto de plausibilidade, que e fraude): "
            "'alta' = campos lidos com clareza; 'media' = algum campo borrado/parcial mas legivel; "
            "'baixa' = imagem cortada, desfocada ou valor/chave ilegiveis. 'baixa' cai em revisao."
        )
    )


PROMPT_PIX = """Voce e um extrator de dados de comprovantes Pix brasileiros. Devolve SO o JSON do schema.

CAMPOS:
- valor: total pago em BRL, como TEXTO e SEMPRE com 2 casas decimais (ex.: "100.00"). Sem "R$",
  sem separador de milhar: mil e duzentos reais e "1200.00". NULL se ilegivel.
- chave_pix_destinatario: a chave do BENEFICIARIO (quem RECEBE). Os 4 formatos BR:
  - CPF/CNPJ (so digitos, ex.: 12345678900),
  - e-mail (ex.: nome@dominio.com),
  - telefone E.164 (ex.: +5511987654321),
  - aleatoria (UUID, ex.: 123e4567-e89b-12d3-a456-426614174000).
  Copie como aparece, sem inventar. NULL se nao aparecer.
- titular_destinatario: nome de quem RECEBE (nao de quem paga). NULL se ilegivel.
- banco_origem: banco emissor do pagamento. NULL se nao aparecer.
- plausibilidade_visual: false se imagem editada, screenshot de app que nao e banco/Pix,
  recibo manuscrito ou montagem digital evidente; true caso contrario.
- motivo_se_implausivel: motivo curto quando plausibilidade_visual=false; senao NULL.
- confianca: 'alta' se leu tudo com clareza; 'media' se algum campo borrado/parcial mas legivel;
  'baixa' se imagem cortada/desfocada ou valor/chave ilegiveis.

EXEMPLO de saida:
{"valor": "100.00", "chave_pix_destinatario": "modelo@pix.com", "titular_destinatario": "Maria Silva", "banco_origem": "Nubank", "plausibilidade_visual": true, "motivo_se_implausivel": null, "confianca": "alta"}
"""


# --- Helpers ----------------------------------------------------------------
# Mime por magic bytes: mora em `core/vision.py` desde o ticket 07 da spec 0005. O alias mantem
# o nome interno que `comprovante_fechamento.py` e os testes ja importam daqui.
_detectar_mime_imagem = detectar_mime_imagem


def _chaves_compativeis(extraida: str, esperada: str) -> bool:
    """Compara chaves Pix com tolerancia (espacos, pontuacao) (06 §2.4).

    A normalizacao e `comprovante.normalizar_chave` e nao uma copia do regex — era a duplicacao que
    o proprio codigo denunciava em `comprovante.py:69`, e o ticket 03 a encerrou. Duas copias da
    mesma comparacao sao duas politicas de aceitacao esperando divergir no primeiro caractere novo.
    """
    return normalizar_chave(extraida) == normalizar_chave(esperada)


def _titulares_compativeis(extraido: str, esperado: str) -> bool:
    """Match parcial: primeiro nome + ultimo sobrenome (06 §2.4)."""
    e_tokens = extraido.lower().split()
    es_tokens = esperado.lower().split()
    if not e_tokens or not es_tokens:
        return False
    return e_tokens[0] == es_tokens[0] and e_tokens[-1] == es_tokens[-1]


# --- Chaves conhecidas da operacao (ADR-0049) --------------------------------
@dataclass(frozen=True)
class ChavesDaOperacao:
    """Para onde o Pix de deslocamento deste atendimento pode legitimamente ter ido.

    ADR-0049: divergencia deixa de ser *"nao bate com a chave DELA"* e passa a ser *"nao bate com
    NENHUMA chave conhecida da operacao"* (casa, modelo daquele atendimento, telefonista). O dono
    descreve os dois destinos como legitimos — *"ele sempre manda pra conta da empresa? — vai
    depender"* —, entao conferir so contra `modelos.chave_pix` reprova o deslocamento que foi para
    a conta da casa, que e o caso comum.

    `chave_da_modelo` / `titular_da_modelo` sao o que a IA ENTREGOU ao cliente neste atendimento, e
    por isso a unica fonte de EXPECTATIVA: sem eles a operacao nao sabe para onde este Pix deveria
    ter ido, e nao ha o que divergir. Esse guard e o que mantem o comportamento IDENTICO ao de hoje
    enquanto o cadastro das modelos estiver vazio (medido 20/08/2026: 0 de 0) — e o que impede a
    checagem de acordar sozinha, por dado, quando o ticket 02 pedir as chaves ao dono.
    """

    chaves: tuple[str, ...] = ()
    """Toda chave que pode receber este Pix, como cadastrada (casa, telefonista, a da modelo)."""
    titulares: tuple[str, ...] = ()
    """Todo titular que pode aparecer no comprovante, como cadastrado."""
    chave_da_modelo: str | None = None
    titular_da_modelo: str | None = None

    def aceita_chave(self, extraida: str) -> bool:
        """A chave lida pelo OCR e de alguem da operacao?"""
        return any(_chaves_compativeis(extraida, conhecida) for conhecida in self.chaves)

    def aceita_titular(self, extraido: str) -> bool:
        """O titular lido pelo OCR e de alguem da operacao?"""
        return any(_titulares_compativeis(extraido, conhecido) for conhecido in self.titulares)


def _recebe_por_esta_operacao(cadastrada: ChaveComDono, *, modelo_id: UUID | None) -> bool:
    """Uma chave do registro pode legitimamente receber o Pix DESTE atendimento?

    Duas perguntas, e as duas sao do papel:

    * **`ativo`** — inativar nunca deletar, mas a chave desligada explica comprovante antigo sem
      autorizar destino novo (`test_chave_inativa_nao_conta_como_conhecida`). Autorizacao e do
      presente; autoria e do cadastro inteiro.
    * **o papel** — `casa` e `telefonista` recebem por qualquer atendimento; `modelo` so recebe
      pelo atendimento DELA (a chave da Yasmin nao autoriza o deslocamento da Bianca, e ate o
      ticket 03 autorizava, porque a lista era plana); `terceiro` nao recebe por nenhum — e
      exatamente o papel que existe para dizer "conheco esta chave E ela nao e da operacao".
    """
    if not cadastrada.ativo:
        return False
    if cadastrada.papel in ("casa", "telefonista"):
        return True
    if cadastrada.papel == "modelo":
        return modelo_id is not None and cadastrada.dono_id == modelo_id
    return False


async def carregar_chaves_da_operacao(
    conn: AsyncConnection[Any], *, atendimento_id: UUID
) -> ChavesDaOperacao:
    """Le as chaves conhecidas da operacao, **pelo papel** (ADR-0049 §1, ticket 03).

    Duas fontes, e elas respondem perguntas diferentes:

    * **quem pode receber** vem do registro tipado (`repo.registro_de_chaves`), filtrado por
      `_recebe_por_esta_operacao`. Ate o ticket 03 vinha da lista PLANA, que nao sabia de quem era
      a chave: a chave de outra modelo autorizava este atendimento e a chave de um terceiro
      cadastrado tambem. Agora o papel decide, e a aceitacao encolheu para o que a operacao de
      fato autoriza.
    * **qual e a expectativa** continua vindo de `modelos.chave_pix` / `titular_chave` da modelo
      deste atendimento, e SO de la — e o que a IA entregou ao cliente. Nao vem do registro de
      proposito: cadastrar a chave dela na aba nova nao pode acordar a checagem de divergencia,
      que e a regressao por DADO que o ticket 01 desarmou (ADR-0049, "consequencia que dita a
      ordem de entrega").

    Com o cadastro vazio (estado de 20/08/2026) o resultado e o de sempre: nada aceita, nada
    diverge.
    """
    cur = await conn.execute(
        """
        SELECT mo.id AS modelo_id, mo.chave_pix AS chave, mo.titular_chave AS titular
          FROM barravips.atendimentos a
          JOIN barravips.modelos     mo ON mo.id = a.modelo_id
         WHERE a.id = %s
        """,
        (atendimento_id,),
    )
    linha = await cur.fetchone()
    modelo_id: UUID | None = linha["modelo_id"] if linha is not None else None
    chave_da_modelo: str | None = linha["chave"] if linha is not None else None
    titular_da_modelo: str | None = linha["titular"] if linha is not None else None

    chaves: list[str] = []
    titulares: list[str] = []
    for cadastrada in await registro_de_chaves(conn):
        if not _recebe_por_esta_operacao(cadastrada, modelo_id=modelo_id):
            continue
        chaves.append(cadastrada.chave)
        if cadastrada.titular:
            titulares.append(cadastrada.titular)
    if chave_da_modelo:
        chaves.append(chave_da_modelo)
    if titular_da_modelo:
        titulares.append(titular_da_modelo)
    return ChavesDaOperacao(
        chaves=tuple(chaves),
        titulares=tuple(titulares),
        chave_da_modelo=chave_da_modelo,
        titular_da_modelo=titular_da_modelo,
    )


async def _baixar_minio(minio: Any, bucket: str, key: str) -> bytes:
    """`minio.get_object` e sincrono — roda em executor (mesmo padrao de `_upload_minio`)."""
    loop = asyncio.get_running_loop()

    def _ler() -> bytes:
        resp = minio.get_object(bucket, key)
        try:
            return cast(bytes, resp.read())
        finally:
            resp.close()
            resp.release_conn()

    return await loop.run_in_executor(None, _ler)


async def _extrair_via_openrouter(
    bytes_img: bytes,
    *,
    media_type: str,
    client: AsyncOpenAI,
    modelo: str,
) -> ExtracaoPix:
    """OpenRouter via SDK OpenAI-compativel + response_format json_schema (06 §0 item 4).

    `provider.require_parameters=true` (ressalva 4a): sem isso o roteamento dinamico pode
    cair num provider que ignora o json_schema. Imagem ANTES do texto (ressalva ordem
    image-then-text + cruzamento vision.md 24-05).

    `reasoning.effort=low`: o modelo default (Gemini 3 Flash) e "thinking" — extrair recibo
    nao precisa raciocinio profundo, e a duvidez ja e tratada deterministicamente abaixo. Low
    segura latencia e tokens de output (que custam como reasoning). Modelos sem thinking ignoram.

    A ida ao provider (json_schema estrito, imagem-antes-do-texto, `finish_reason` no 200 OK)
    mora em `core/vision.py` desde o ticket 07 da spec 0005 — aqui ficam o prompt, o schema e a
    politica de custo, que sao do Pix.
    """
    try:
        leitura = await extrair_da_imagem(
            bytes_img,
            media_type=media_type,
            client=client,
            modelo=modelo,
            prompt=PROMPT_PIX,
            esquema=ExtracaoPix,
        )
    except VisionInconclusiva as exc:
        # CUSTO-02: um vision truncado/recusado TAMBEM queimou tokens — por isso o `usage` viaja
        # na excecao e o custo e observado nos dois caminhos.
        _observar_custo(modelo, exc.usage)
        raise
    _observar_custo(modelo, leitura.usage)
    return leitura.dados


def _observar_custo(modelo: str, usage: Any | None) -> None:
    """`usage` pode faltar em fakes de teste; a funcao pura trata None -> 0.0. Label = o modelo."""
    AGENTE_CUSTO_VISION_BRL.labels(modelo).observe(
        calcular_custo_vision_brl(usage, get_settings().usd_brl_cotacao)
    )


# --- Job principal ----------------------------------------------------------
async def validar_pix(
    ctx: dict[str, Any],
    *,
    mensagem_id: str,
    atendimento_id: str,
) -> None:
    """Valida o comprovante de uma mensagem ja persistida no MinIO.

    Assinatura enxuta (06 §0 item 2): nada de `media_url` — a midia ja esta no MinIO via
    webhook fino; o worker le `media_object_key` em `mensagens` e baixa de la.
    """
    pool = ctx["db_pool"]
    minio = ctx["minio"]
    settings = ctx["settings"]
    vision_client: AsyncOpenAI | None = ctx["vision_client"]

    inicio = perf_counter()
    try:
        # 1. busca object_key da mensagem + o valor esperado. As expectativas de chave/titular
        #    NAO vem daqui: elas sao a operacao inteira (ADR-0049) e moram em
        #    `carregar_chaves_da_operacao`, lida so quando ha o que comparar.
        async with pool.connection() as conn:
            res = await conn.execute(
                """
                SELECT m.media_object_key,
                       a.tipo_atendimento::text AS tipo_atendimento,
                       a.valor_acordado
                  FROM barravips.mensagens m
                  JOIN barravips.atendimentos a ON a.id = %s
                 WHERE m.id = %s
                """,
                (UUID(atendimento_id), UUID(mensagem_id)),
            )
            ctx_row = await res.fetchone()
        if ctx_row is None:
            # Sem linha: a mensagem nao existe (anomalia). `comprovantes_pix.mensagem_id` e FK,
            # entao sem mensagem_id valido nao da pra gravar o comprovante -- so registra e sai.
            logger.error(
                "validar_pix sem contexto mensagem_id=%s atendimento_id=%s",
                mensagem_id,
                atendimento_id,
            )
            return

        object_key: str | None = ctx_row["media_object_key"]
        # Valor esperado do comprovante: externo antecipa o deslocamento FIXO; remoto antecipa
        # o valor da chamada (`valor_acordado`, ADR 0029). Fallback no fixo se o remoto chegar
        # sem valor acordado (nao deve ocorrer: a solicitacao do remoto exige valor_acordado).
        valor_esperado = (
            ctx_row["valor_acordado"]
            if ctx_row["tipo_atendimento"] == "remoto" and ctx_row["valor_acordado"] is not None
            else settings.pix_deslocamento_valor
        )

        # A duvida deste comprovante, no vocabulario UNICO dos dois caminhos (ADR-0049 §5,
        # ticket 07): `suspeita` e o motivo canonico (agrupavel, virou o label da metrica e o
        # prefixo da coluna) e `motivo_em_revisao` e ele mais a prosa que o revisor le. Ate aqui
        # existiam DUAS palavras por duvida — o bucket da metrica ("chave", "valor") e a prosa —,
        # e o painel tipava a coluna como um terceiro conjunto de slugs que o backend nunca
        # escreveu.
        motivo_em_revisao: str | None = None
        suspeita: MotivoDeSuspeita | None = None
        extracao: ExtracaoPix | None = None

        if not object_key:
            # REL-06: o upload do comprovante ao MinIO falhou no webhook (a mensagem caiu como
            # 'texto' sem media_object_key). Pix NUNCA trava nem some (01 §6.1): em vez de o
            # atendimento estagnar em Aguardando_confirmacao ate virar Perdido no timeout-24h,
            # marcamos DUVIDOSO (em_revisao) -> o atendimento avanca para Confirmado e Fernando
            # revisa na fila assincrona. Sem imagem nao ha download nem vision.
            logger.warning(
                "validar_pix midia ausente -> em_revisao mensagem_id=%s atendimento_id=%s",
                mensagem_id,
                atendimento_id,
            )
            suspeita = "sem_leitura"
            motivo_em_revisao = marcar_suspeita(
                suspeita, "midia ausente: upload do comprovante falhou"
            )
        elif vision_client is None:
            # Pix NUNCA trava (01 §6.1): sem credencial de vision (OPENROUTER_API_KEY ausente) nao
            # da pra fazer OCR -> em_revisao (DUVIDOSO), o atendimento avanca para Confirmado e
            # Fernando revisa na fila assincrona, em vez de o job crashar (AttributeError no client
            # None) e o atendimento estagnar ate o timeout de 24h.
            logger.warning(
                "validar_pix sem vision_client -> em_revisao atendimento_id=%s", atendimento_id
            )
            suspeita = "sem_leitura"
            motivo_em_revisao = marcar_suspeita(
                suspeita, "vision indisponivel: credencial de OCR ausente"
            )
        else:
            # 2. baixa do MinIO + detecta mime real (nao confiar na extensao da URL Evolution)
            bytes_img = await _baixar_minio(minio, settings.minio_bucket_media, object_key)
            media_type = _detectar_mime_imagem(bytes_img)

            # 3. vision. finish_reason=max_tokens/refusal -> VisionInconclusiva: Pix NUNCA trava
            #    (01 §6.1), cai em em_revisao (DUVIDOSO) com extracao vazia, sem propagar.
            try:
                extracao = await _extrair_via_openrouter(
                    bytes_img,
                    media_type=media_type,
                    client=vision_client,
                    modelo=settings.openrouter_model_vision_pix or MODELO_VISION_PADRAO,
                )
            except VisionInconclusiva as exc:
                logger.warning(
                    "validar_pix vision inconclusivo atendimento_id=%s finish_reason=%s",
                    atendimento_id,
                    exc,
                )
                extracao = None
                suspeita = "sem_leitura"
                motivo_em_revisao = marcar_suspeita(
                    suspeita, f"vision inconclusivo: finish_reason={exc}"
                )
            except Exception as exc:
                # Pix NUNCA trava (01 §6.1): falha inesperada de OCR (rede, APIError, provider)
                # -> em_revisao + avanca, em vez de propagar pro ARQ e deixar o atendimento preso.
                logger.warning(
                    "validar_pix vision falhou atendimento_id=%s erro=%s",
                    atendimento_id,
                    type(exc).__name__,
                )
                extracao = None
                suspeita = "sem_leitura"
                motivo_em_revisao = marcar_suspeita(
                    suspeita, f"vision falhou: {type(exc).__name__}"
                )

        # 4. comparacoes (sem timestamp, emenda §0 item 11). So quando houve extracao -- sem
        #    ela ja esta em em_revisao pelo branch acima.
        if extracao is not None:
            if not extracao.plausibilidade_visual:
                suspeita = "imagem_implausivel"
                motivo_em_revisao = marcar_suspeita(
                    suspeita,
                    f"plausibilidade visual: {extracao.motivo_se_implausivel or 'imagem suspeita'}",
                )
            elif extracao.confianca == "baixa":
                # Legibilidade baixa (imagem cortada/desfocada): os campos extraidos nao sao
                # confiaveis o bastante para validar em silencio -> em_revisao. Distinto de
                # plausibilidade (fraude): aqui a imagem e crivel, so esta ilegivel.
                suspeita = "imagem_ilegivel"
                motivo_em_revisao = marcar_suspeita(
                    suspeita, "legibilidade baixa: imagem cortada/desfocada ou campos ilegiveis"
                )
            elif extracao.valor is None or extracao.valor < valor_esperado:
                suspeita = "valor_abaixo_do_esperado"
                motivo_em_revisao = marcar_suspeita(
                    suspeita, f"valor extraido {extracao.valor} < esperado R${valor_esperado}"
                )
            elif extracao.chave_pix_destinatario or extracao.titular_destinatario:
                # ADR-0049: a pergunta e "esse destino e de alguem da operacao?" — casa, modelo
                # deste atendimento ou telefonista —, nunca "e a chave DELA?". Sem a chave da
                # modelo cadastrada nao ha expectativa nenhuma e nada diverge: e o estado de hoje
                # (0 modelos preenchidas), preservado ao pe da letra.
                async with pool.connection() as conn:
                    conhecidas = await carregar_chaves_da_operacao(
                        conn, atendimento_id=UUID(atendimento_id)
                    )
                if (
                    conhecidas.chave_da_modelo
                    and extracao.chave_pix_destinatario
                    and not conhecidas.aceita_chave(extracao.chave_pix_destinatario)
                ):
                    suspeita = "destino_desconhecido"
                    motivo_em_revisao = marcar_suspeita(
                        suspeita,
                        f"chave divergente: extraida {extracao.chave_pix_destinatario}, "
                        f"esperada {conhecidas.chave_da_modelo} ou outra das "
                        f"{len(conhecidas.chaves)} chaves conhecidas da operacao",
                    )
                elif (
                    conhecidas.titular_da_modelo
                    and extracao.titular_destinatario
                    and not conhecidas.aceita_titular(extracao.titular_destinatario)
                ):
                    suspeita = "titular_divergente"
                    motivo_em_revisao = marcar_suspeita(
                        suspeita,
                        f"titular divergente: extraido {extracao.titular_destinatario}, "
                        f"esperado {conhecidas.titular_da_modelo} ou outro titular conhecido "
                        f"da operacao",
                    )

        decisao_pipeline = "validado" if motivo_em_revisao is None else "em_revisao"

        # 5. persiste comprovante + aplica via porta unica de `escaladas.service`. timestamp_extraido
        # gravado como NULL (drop §0 item 11). aplicar_comando avanca o atendimento EXTERNO para
        # Confirmado + ia_pausada=true em ambos os branches (07 §5); no remoto so grava pix_status
        # (ADR 0029 — a transicao/pausa do remoto pertence ao cron da hora da chamada).
        async with pool.connection() as conn, conn.transaction():
            inserido = await conn.execute(
                """
                INSERT INTO barravips.comprovantes_pix
                  (atendimento_id, mensagem_id, valor_extraido, chave_extraida, titular_extraido,
                   timestamp_extraido, decisao_pipeline, motivo_em_revisao)
                VALUES (%s, %s, %s, %s, %s, NULL, %s, %s)
                RETURNING id
                """,
                (
                    UUID(atendimento_id),
                    UUID(mensagem_id),
                    extracao.valor if extracao else None,
                    extracao.chave_pix_destinatario if extracao else None,
                    extracao.titular_destinatario if extracao else None,
                    decisao_pipeline,
                    motivo_em_revisao,
                ),
            )
            row_id = await inserido.fetchone()
            comprovante_id = row_id["id"]

            await aplicar_comando(
                conn,
                origem="pipeline_pix",
                autor="sistema",
                atendimento_id=UUID(atendimento_id),
                comando="atualizar_pix",
                payload={"decisao": decisao_pipeline, "motivo": motivo_em_revisao},
            )

        # 6. metricas + card
        PIX_VALIDACAO_DECISAO.labels(decisao_pipeline).inc()
        if suspeita is not None:
            # O label E o motivo canonico (ticket 07). Ate aqui era um vocabulario proprio da
            # metrica ("plausibilidade", "legibilidade", "valor", "chave", "titular", "midia",
            # "vision"), que ninguem conseguia cruzar com a prosa da coluna nem com o comprovante
            # do Grupo financeiro. Nenhum dashboard ou alerta referencia
            # `agente_pix_divergencia_total` (medido 20/08/2026), entao a troca nao quebra
            # painel nenhum — e a serie antiga simplesmente para de receber amostra.
            PIX_DIVERGENCIA.labels(suspeita).inc()

        redis = ctx["redis"]
        await redis.enqueue_job(
            "enviar_card",
            tipo="pix_validado" if decisao_pipeline == "validado" else "pix_em_revisao",
            atendimento_id=str(atendimento_id),
            comprovante_id=str(comprovante_id),
            _job_id=f"card:pix:{atendimento_id}",
        )
        # PII: motivo_em_revisao interpola chave Pix/titular (dados da modelo, painel-only).
        # Loga so o bucket nao-PII; o detalhe fica na coluna comprovantes_pix.motivo_em_revisao.
        logger.info(
            "validar_pix decisao=%s atendimento_id=%s motivo_tipo=%s",
            decisao_pipeline,
            atendimento_id,
            suspeita,
        )
    finally:
        PIX_VALIDACAO_DURACAO.observe(perf_counter() - inicio)


__all__ = [
    "ChavesDaOperacao",
    "ExtracaoPix",
    "_chaves_compativeis",
    "_detectar_mime_imagem",
    "_titulares_compativeis",
    "carregar_chaves_da_operacao",
    "validar_pix",
]
