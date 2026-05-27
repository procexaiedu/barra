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

from barra.dominio.agenda.service import ConflitoAgenda
from barra.dominio.atendimentos.service import registrar_extracao_ia

from ..contexto import ContextAgente
from ._idempotencia import _executar_idempotente


class ExtracaoPayload(BaseModel):
    """Snapshot estruturado do que a IA aprendeu nesta conversa.

    Todos os campos opcionais — registre o que esta claro; deixe NULL o que ainda nao.
    O dominio faz UPSERT: campos nao-nulos sobrescrevem; campos nulos preservam o anterior.
    """

    # extra="forbid" => additionalProperties:false (strict tool use §7); nenhum dado de cliente
    # entra em nome de campo/enum (a grammar do strict e cacheada fora das protecoes, §7).
    model_config = ConfigDict(extra="forbid")

    intencao: Literal["curiosidade", "cotacao", "agendamento"] | None = None
    urgencia: Literal["imediato", "agendado", "indefinido", "estimado"] | None = None
    tipo_atendimento: Literal["interno", "externo"] | None = None
    data_desejada: date | None = None
    horario_desejado: time | None = None
    duracao_horas: Decimal | None = Field(None, ge=0, le=48)
    endereco: str | None = None
    bairro: str | None = None
    tipo_local: Literal["hotel", "casa", "apartamento", "outro"] | None = None
    forma_pagamento: Literal["pix", "dinheiro", "outro"] | None = None
    valor_acordado: Decimal | None = Field(None, ge=0)
    sinais_qualificacao: dict[str, bool] = Field(
        default_factory=dict,
        description=(
            "Sinais bool {informa_horario, informa_local, aceita_valor, envia_pix, "
            "responde_objetivamente}. Inclua so os True."
        ),
    )
    motivo_perda_candidato: (
        Literal["preco", "sumiu", "risco", "indisponibilidade", "fora_de_area", "outro"] | None
    ) = None
    aviso_saida_detectado: bool = Field(
        default=False,
        description=(
            "Cliente avisou que saiu de casa em direcao ao endereco combinado "
            "(texto livre tipo 'sai', 'tô indo', 'estou indo', 'sai agora'). "
            "Sinalize True SO em atendimento interno em Aguardando_confirmacao; "
            "ignore em outros contextos. NAO pausa a IA — segue a conversa normal."
        ),
    )
    limpar: list[str] = Field(
        default_factory=list,
        description=(
            "Campos a ZERAR (NULL) quando o cliente RECUA/desmarca — ex.: disse um horario "
            "e depois 'nao sei o dia ainda'. Nomes dos campos acima (ex.: "
            "['data_desejada','horario_desejado']). So o que o cliente retratou; tem "
            "precedencia sobre o payload."
        ),
    )
    proxima_acao_esperada: str = Field(min_length=3, max_length=240)


@tool
async def registrar_extracao(
    payload: ExtracaoPayload,
    runtime: ToolRuntime[ContextAgente],
) -> str:
    """Registre o snapshot do que aprendeu nesta conversa. Chame UMA vez por turno, perto do fim.

    Esta tool dispara transicoes de estado:
    - intencao=curiosidade/cotacao/agendamento + estado=Novo -> Triagem
    - intencao=agendamento + dados minimos (horario_desejado, tipo_atendimento) + Triagem -> Qualificado
    - tipo_atendimento=interno + horario_desejado + Qualificado -> Aguardando_confirmacao
      (cria bloqueio previo E dispara o pin de endereco — side-effect, nao tool)
    - externo NAO e promovido aqui: so pedir_pix_deslocamento leva externo a Aguardando_confirmacao

    O campo proxima_acao_esperada (obrigatorio) e exibido no painel para Fernando.
    Use `limpar` para ZERAR campos que o cliente retratou (ex.: desmarcou o horario) —
    o snapshot e incremental (COALESCE), entao sem `limpar` um valor antigo nunca some.
    """
    pool = runtime.context.db_pool
    atendimento_id = runtime.context.atendimento_id
    turno_id = runtime.context.turno_id

    dados = payload.model_dump(mode="json")
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
            return (
                "ERRO: o horario escolhido ja esta reservado para a modelo. "
                "Ofereca outro horario ao cliente e registre de novo."
            )

    # Pin de endereco (interno): enfileirado APOS o commit (simetrico ao card do escalar). Replay
    # e inofensivo — o worker do pin e idempotente por atendimento_id (_job_id estavel).
    if resultado.get("enviar_pin"):
        await runtime.context.redis.enqueue_job(
            "enviar_card",
            tipo="loc_pin",
            atendimento_id=atendimento_id,
            _job_id=f"card:loc_pin:{atendimento_id}",
        )
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
