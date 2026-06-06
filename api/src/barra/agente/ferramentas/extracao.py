"""Tool de escrita registrar_extracao (04 §3.1).

Wrapper fino: idempotencia (`_executar_idempotente`) + delega a regra de dominio para
`dominio/atendimentos/service.py:registrar_extracao_ia` (UPSERT do snapshot + transicao de
estado + bloqueio previo interno + guarda do piso de desconto). O pin de endereco e o pin de
side-effect: enfileirado APOS o commit, simetrico ao card do escalar (Notas, 04 §3.1).
"""

from datetime import date, time
from decimal import Decimal
from typing import Literal

from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime
from pydantic import BaseModel, ConfigDict, Field

from barra.core.metrics import AGENTE_TOOL_ERRO_RECUPERAVEL
from barra.dominio.agenda.service import ConflitoAgenda
from barra.dominio.atendimentos.service import registrar_extracao_ia

from ..contexto import ContextAgente
from ._idempotencia import _executar_idempotente


class SinaisQualificacao(BaseModel):
    """Sinais booleanos detectados; inclua só os True."""

    model_config = ConfigDict(extra="forbid")

    informa_horario: bool = Field(False, description="cliente disse um horário concreto que quer")
    informa_local: bool = Field(False, description="cliente informou bairro/endereço/tipo de local")
    aceita_valor: bool = Field(
        False, description="cliente concordou com o valor cotado (não apenas perguntou o preço)"
    )
    envia_pix: bool = Field(
        False, description="cliente alegou ter enviado o Pix ou mandou comprovante"
    )
    responde_objetivamente: bool = Field(
        False,
        description="cliente responde direto às perguntas, sem enrolar — sinal de intenção real",
    )


class ExtracaoPayload(BaseModel):
    """Snapshot estruturado do que a IA aprendeu nesta conversa.

    Todos os campos opcionais — registre o que está claro; deixe NULL o que ainda não.
    O domínio faz UPSERT: campos não-nulos sobrescrevem; campos nulos preservam o anterior.
    """

    # extra="forbid" => additionalProperties:false (strict tool use §7); nenhum dado de cliente
    # entra em nome de campo/enum (a grammar do strict e cacheada fora das protecoes, §7).
    model_config = ConfigDict(extra="forbid")

    intencao: Literal["curiosidade", "cotacao", "agendamento"] | None = None
    urgencia: Literal["imediato", "agendado", "indefinido", "estimado"] | None = None
    tipo_atendimento: Literal["interno", "externo"] | None = None
    data_desejada: date | None = None
    horario_desejado: time | None = Field(
        None,
        description=(
            "Horário de relógio do encontro (HH:MM). PREENCHA na PRIMEIRA vez que o cliente der o "
            "horário — não re-pergunte algo que ele já disse. Cravou uma hora ('22h', 'meio-dia') → "
            "use-a. Disse tempo RELATIVO/imediato → calcule a partir da hora atual (vem em "
            "<agenda agora=\"HH:MM\"> no contexto): 'agora/já/imediato' = a hora atual; 'daqui N "
            "min/horas' = hora atual + N (ex.: agora=22:30 e cliente diz 'daqui 1h' → preencha "
            "23:30; data_desejada=hoje, virando o dia se passar da meia-noite). É o que faz o "
            "atendimento AVANÇAR para Aguardando_confirmacao e te pausar na chegada. NÃO preencha em "
            "horário vago/aberto ('depois das 21h', 'à noite'): aí siga qualificando até cravar."
        ),
    )
    duracao_horas: Decimal | None = Field(None, ge=0, le=48)
    endereco: str | None = None
    bairro: str | None = None
    tipo_local: Literal["hotel", "casa", "apartamento", "outro"] | None = None
    forma_pagamento: Literal["pix", "dinheiro", "outro"] | None = None
    valor_acordado: Decimal | None = Field(
        None,
        ge=0,
        description=(
            "Valor total acordado com o cliente. SEMPRE grave JUNTO com duracao_horas (a duração do "
            "programa cotado) — sem a duração o sistema não consegue conferir o piso de desconto e "
            "escala à toa uma oferta que era válida."
        ),
    )
    sinais_qualificacao: SinaisQualificacao = Field(
        default_factory=SinaisQualificacao,
        description="Passe só os True; defaults False são excluídos do dump (não sobrescrevem).",
    )
    motivo_perda_candidato: (
        Literal["preco", "sumiu", "risco", "indisponibilidade", "fora_de_area", "outro"] | None
    ) = None
    aviso_saida_detectado: bool = Field(
        default=False,
        description=(
            "Cliente avisou que saiu de casa em direção ao endereço combinado "
            "(texto livre tipo 'sai', 'tô indo', 'estou indo', 'sai agora'). "
            "Sinalize True SÓ em atendimento interno em Aguardando_confirmacao; "
            "ignore em outros contextos. NÃO pausa a IA — segue a conversa normal."
        ),
    )
    limpar: list[str] = Field(
        default_factory=list,
        description=(
            "Campos a ZERAR (NULL) quando o cliente RECUA/desmarca — ex.: disse um horário "
            "e depois 'não sei o dia ainda'. Nomes dos campos acima (ex.: "
            "['data_desejada','horario_desejado']). Só o que o cliente retratou; tem "
            "precedência sobre o payload. Zerar um campo apaga o valor anterior e pode "
            "reverter a qualificação do atendimento — na dúvida, não liste."
        ),
    )
    proxima_acao_esperada: str = Field(min_length=3, max_length=240)


@tool
async def registrar_extracao(
    payload: ExtracaoPayload,
    runtime: ToolRuntime[ContextAgente],
) -> str:
    """Registre o snapshot do que aprendeu nesta conversa. Chame UMA vez por turno, perto do fim.

    IMPORTANTE: registrar NÃO envia nada ao cliente — é uma nota interna. Você ainda precisa
    responder ao cliente normalmente neste mesmo turno, em personagem, como se já soubesse.

    O snapshot é incremental (COALESCE): campos não-nulos sobrescrevem, nulos preservam o
    anterior. Para apagar um dado que o cliente retratou de fato, use o campo `limpar`.

    `proxima_acao_esperada` (obrigatório) é uma nota interna exibida no painel para Fernando —
    não é texto para o cliente.
    """
    # Transicoes de estado disparadas por esta tool (regra em registrar_extracao_ia):
    # - intencao=curiosidade/cotacao/agendamento + estado=Novo -> Triagem
    # - intencao=agendamento + horario_desejado + tipo_atendimento + Triagem -> Qualificado
    # - tipo_atendimento=interno + horario_desejado + Qualificado -> Aguardando_confirmacao
    #   (cria bloqueio previo E dispara o pin de endereco — side-effect, nao tool)
    # - externo NAO e promovido aqui: so pedir_pix_deslocamento o leva a Aguardando_confirmacao
    pool = runtime.context.db_pool
    atendimento_id = runtime.context.atendimento_id
    turno_id = runtime.context.turno_id

    # exclude_defaults: campos nao explicitamente fornecidos pelo LLM ficam fora do dict. Critico
    # pro `sinais_qualificacao` (schema fechado pos-refactor): garante que so chaves True sejam
    # mergeadas no JSONB acumulado (`||` em service.py). Campos opcionais com default None ja
    # sao omitidos. Strict mode pre-req — schema fechado libera `anthropic_strict_tools=True`.
    dados = payload.model_dump(mode="json", exclude_defaults=True)
    async with pool.connection() as conn:
        try:
            resultado = await _executar_idempotente(
                conn,
                turno_id,
                "registrar_extracao",
                0,
                dados,
                executor=lambda c, p: registrar_extracao_ia(c, atendimento_id, p),
            )
        except ConflitoAgenda:
            # Erro recuperavel (04 §6): a transacao reverteu; instrua a IA a reofertar outro
            # horario. Sai como status=success de proposito (e o loop funcionando, nao falha).
            AGENTE_TOOL_ERRO_RECUPERAVEL.labels("registrar_extracao", "agenda_conflito").inc()
            return (
                "ERRO: o horário escolhido já está reservado para a modelo. "
                "Ofereça outro horário ao cliente e registre de novo."
            )

    # Pin de endereco (interno): NAO enfileirado enquanto o renderer `_card_loc_pin`
    # (workers/envio.py) ainda levanta NotImplementedError — o job so falharia 5x (M3d, 09 §4.3).
    # O dominio segue setando `enviar_pin`; o enqueue volta junto com o renderer.
    # Aviso de saida (06 §5): card 'cliente saiu de casa' sem owner — SETNX no renderer
    # garante idempotencia inter-turnos; o _job_id aqui evita re-enfileirar no mesmo ARQ.
    if resultado.get("enviar_aviso_saida"):
        await runtime.context.redis.enqueue_job(
            "enviar_card",
            tipo="aviso_saida",
            atendimento_id=atendimento_id,
            _job_id=f"card:aviso_saida:{atendimento_id}",
        )
    mensagem: str = resultado["mensagem"]
    return mensagem
