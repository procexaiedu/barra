"""Porta unica para comandos operacionais sensiveis."""

import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from psycopg import AsyncConnection

from barra.core.errors import ConflitoEstado, EntradaInvalida, NaoEncontrado
from barra.dominio.escaladas.modelos import TipoEscalada, rotulo_tipo_escalada
from barra.settings import get_settings

Origem = Literal["painel", "grupo_coordenacao", "pipeline_pix", "cron", "agente"]
Autor = Literal["IA", "Fernando", "modelo", "sistema"]


@dataclass(frozen=True)
class ResultadoComando:
    atendimento_id: UUID
    estado: str
    pix_status: str | None = None


async def aplicar_comando(
    conn: AsyncConnection[Any],
    *,
    origem: Origem,
    autor: Autor,
    atendimento_id: UUID,
    comando: str,
    payload: dict[str, Any],
) -> ResultadoComando:
    async with conn.transaction():
        atendimento = await _buscar_atendimento(conn, atendimento_id)
        if atendimento is None:
            raise NaoEncontrado("Atendimento")

        if comando == "devolver_para_ia":
            return await _devolver_para_ia(conn, atendimento, origem, autor, payload)
        if comando == "registrar_fechado":
            return await _registrar_fechado(conn, atendimento, origem, autor, payload)
        if comando == "registrar_perdido":
            return await _registrar_perdido(conn, atendimento, origem, autor, payload)
        if comando == "corrigir_registro":
            return await _corrigir_registro(conn, atendimento, origem, autor, payload)
        if comando == "atualizar_pix":
            return await _atualizar_pix(conn, atendimento, origem, autor, payload)
        if comando == "comando_invalido":
            await _evento(conn, atendimento_id, "comando_invalido", origem, autor, payload)
            return ResultadoComando(
                atendimento_id, atendimento["estado"], atendimento["pix_status"]
            )

        raise EntradaInvalida("COMANDO_INVALIDO", "Comando invalido.")


async def _buscar_atendimento(
    conn: AsyncConnection[Any], atendimento_id: UUID
) -> dict[str, Any] | None:
    result = await conn.execute(
        """
        SELECT a.*, m.percentual_repasse
          FROM barravips.atendimentos a
          JOIN barravips.modelos m ON m.id = a.modelo_id
         WHERE a.id = %s
         FOR UPDATE OF a
        """,
        (atendimento_id,),
    )
    return await result.fetchone()


async def _devolver_para_ia(
    conn: AsyncConnection[Any],
    atendimento: dict[str, Any],
    origem: Origem,
    autor: Autor,
    payload: dict[str, Any],
) -> ResultadoComando:
    if atendimento["estado"] in {"Fechado", "Perdido"}:
        raise ConflitoEstado("Atendimento ja esta finalizado.")
    if not atendimento["ia_pausada"]:
        raise ConflitoEstado("Atendimento nao esta pausado.")

    await conn.execute(
        """
        UPDATE barravips.atendimentos
           SET ia_pausada = false,
               ia_pausada_motivo = NULL,
               responsavel_atual = 'IA',
               proxima_acao_esperada = NULL,
               motivo_escalada = NULL,
               fonte_decisao_ultima_transicao = %s
         WHERE id = %s
        """,
        (_fonte(origem), atendimento["id"]),
    )
    await conn.execute(
        """
        UPDATE barravips.escaladas
           SET fechada_em = now(), fechada_por = %s, fechada_canal = %s
         WHERE atendimento_id = %s AND fechada_em IS NULL
        """,
        (payload.get("usuario_id"), _canal(origem), atendimento["id"]),
    )
    await _evento(conn, atendimento["id"], "devolucao_para_ia", origem, autor, payload)
    return ResultadoComando(atendimento["id"], atendimento["estado"], atendimento["pix_status"])


async def _registrar_fechado(
    conn: AsyncConnection[Any],
    atendimento: dict[str, Any],
    origem: Origem,
    autor: Autor,
    payload: dict[str, Any],
) -> ResultadoComando:
    valor = payload.get("valor_final")
    if valor is None:
        raise EntradaInvalida(
            "VALOR_FINAL_OBRIGATORIO", "Valor final obrigatorio.", {"campo": "valor_final"}
        )
    if atendimento["estado"] in {"Fechado", "Perdido"}:
        raise ConflitoEstado("Atendimento ja esta finalizado.")

    # Taxa de cartão (ADR 0013): o backend carimba o snapshot a partir do default em settings
    # quando a forma confirmada no fechamento é cartão e a taxa não é isenta. Sem forma (comando
    # do grupo) ou pix/dinheiro/isento → sem taxa. forma_pagamento usa COALESCE para confirmar a
    # forma sem apagar a que já estava no atendimento quando o fechamento não a informa.
    forma = payload.get("forma_pagamento")
    isentar = bool(payload.get("isentar_taxa"))
    taxa = get_settings().taxa_cartao_padrao_pct if forma == "cartao" and not isentar else None

    await conn.execute(
        """
        UPDATE barravips.atendimentos
           SET estado = 'Fechado',
               valor_final = %s,
               percentual_repasse_snapshot = COALESCE(percentual_repasse_snapshot, %s),
               taxa_cartao_snapshot = %s,
               forma_pagamento = COALESCE(%s, forma_pagamento),
               ia_pausada = false,
               ia_pausada_motivo = NULL,
               responsavel_atual = 'Fernando',
               fonte_decisao_ultima_transicao = %s
         WHERE id = %s
        """,
        (
            Decimal(str(valor)),
            atendimento["percentual_repasse"],
            taxa,
            forma,
            _fonte(origem),
            atendimento["id"],
        ),
    )
    await _evento(
        conn,
        atendimento["id"],
        "fechado_registrado",
        origem,
        autor,
        {"valor_final": str(valor), **payload},
    )
    await _evento(
        conn,
        atendimento["id"],
        "transicao_estado",
        origem,
        autor,
        {"de": atendimento["estado"], "para": "Fechado"},
    )
    return ResultadoComando(atendimento["id"], "Fechado", atendimento["pix_status"])


async def _registrar_perdido(
    conn: AsyncConnection[Any],
    atendimento: dict[str, Any],
    origem: Origem,
    autor: Autor,
    payload: dict[str, Any],
) -> ResultadoComando:
    motivo = payload.get("motivo")
    observacao = payload.get("observacao")
    if motivo is None:
        raise EntradaInvalida("MOTIVO_OBRIGATORIO", "Motivo obrigatorio.", {"campo": "motivo"})
    if motivo == "outro" and not observacao:
        raise EntradaInvalida(
            "OBSERVACAO_OBRIGATORIA",
            "Observacao obrigatoria para motivo outro.",
            {"campo": "observacao"},
        )
    if atendimento["estado"] in {"Fechado", "Perdido"}:
        raise ConflitoEstado("Atendimento ja esta finalizado.")

    await conn.execute(
        """
        UPDATE barravips.atendimentos
           SET estado = 'Perdido',
               motivo_perda = %s,
               motivo_perda_obs = %s,
               ia_pausada = false,
               ia_pausada_motivo = NULL,
               responsavel_atual = 'Fernando',
               fonte_decisao_ultima_transicao = %s
         WHERE id = %s
        """,
        (motivo, observacao, _fonte(origem), atendimento["id"]),
    )
    await _evento(conn, atendimento["id"], "perdido_registrado", origem, autor, payload)
    await _evento(
        conn,
        atendimento["id"],
        "transicao_estado",
        origem,
        autor,
        {"de": atendimento["estado"], "para": "Perdido"},
    )
    return ResultadoComando(atendimento["id"], "Perdido", atendimento["pix_status"])


async def _corrigir_registro(
    conn: AsyncConnection[Any],
    atendimento: dict[str, Any],
    origem: Origem,
    autor: Autor,
    payload: dict[str, Any],
) -> ResultadoComando:
    novo = payload.get("novo_resultado")
    if novo == "Fechado" and payload.get("valor_final") is None:
        raise EntradaInvalida(
            "VALOR_FINAL_OBRIGATORIO", "Valor final obrigatorio.", {"campo": "valor_final"}
        )
    if novo == "Perdido" and payload.get("motivo") is None:
        raise EntradaInvalida("MOTIVO_OBRIGATORIO", "Motivo obrigatorio.", {"campo": "motivo"})

    bloqueio_id = atendimento.get("bloqueio_id")
    if bloqueio_id and not payload.get("confirmar_alteracao_bloqueio_finalizado"):
        row = await conn.execute(
            "SELECT estado::text AS estado FROM barravips.bloqueios WHERE id = %s",
            (bloqueio_id,),
        )
        bloqueio = await row.fetchone()
        if bloqueio and bloqueio["estado"] in {"em_atendimento", "concluido"}:
            raise ConflitoEstado(
                "Alteracao de bloqueio finalizado exige confirmacao.",
                {"campo": "confirmar_alteracao_bloqueio_finalizado"},
            )

    await conn.execute(
        """
        UPDATE barravips.atendimentos
           SET estado = %s,
               valor_final = %s,
               taxa_cartao_snapshot = %s,
               motivo_perda = %s,
               motivo_perda_obs = %s,
               fonte_decisao_ultima_transicao = %s
         WHERE id = %s
        """,
        (
            novo,
            payload.get("valor_final"),
            payload.get("taxa_cartao_snapshot"),
            payload.get("motivo"),
            payload.get("observacao"),
            _fonte(origem),
            atendimento["id"],
        ),
    )
    # Sincroniza o bloqueio vinculado. O trigger sync_bloqueio_estado so age em
    # bloqueio NAO-finalizado (guard NOT IN ('em_atendimento','concluido') no Perdido;
    # NOT IN ('cancelado') no Fechado). Numa correcao o bloqueio normalmente ja esta
    # concluido/cancelado de um registro anterior, entao o trigger nao o libera/reabre:
    # Fechado->Perdido deixaria o slot preso em 'concluido' e Perdido->Fechado deixaria
    # 'cancelado'. Forcamos a sincronia aqui (Fernando ja confirmou via
    # confirmar_alteracao_bloqueio_finalizado quando o bloqueio estava finalizado).
    if bloqueio_id:
        if novo == "Perdido":
            await conn.execute(
                "UPDATE barravips.bloqueios SET estado = 'cancelado' "
                "WHERE id = %s AND estado <> 'cancelado'",
                (bloqueio_id,),
            )
        elif novo == "Fechado":
            await conn.execute(
                "UPDATE barravips.bloqueios SET estado = 'concluido' "
                "WHERE id = %s AND estado <> 'concluido'",
                (bloqueio_id,),
            )
    await _evento(conn, atendimento["id"], "correcao_registro", origem, autor, payload)
    # Garante porta de entrada para o módulo Financeiro (ADR 0011): quando a
    # correção promove o atendimento para Fechado a partir de outro estado,
    # emite também `fechado_registrado` — caso contrário a receita ficaria
    # invisível no módulo (que filtra por esse evento como data-âncora).
    # Reciprocamente para Perdido, mantém simetria de auditoria.
    if novo == "Fechado" and atendimento["estado"] != "Fechado":
        await _evento(
            conn,
            atendimento["id"],
            "fechado_registrado",
            origem,
            autor,
            {"valor_final": str(payload.get("valor_final")), "via": "correcao_registro"},
        )
    elif novo == "Perdido" and atendimento["estado"] != "Perdido":
        await _evento(
            conn,
            atendimento["id"],
            "perdido_registrado",
            origem,
            autor,
            {"motivo": payload.get("motivo"), "via": "correcao_registro"},
        )
    return ResultadoComando(atendimento["id"], str(novo), atendimento["pix_status"])


async def _atualizar_pix(
    conn: AsyncConnection[Any],
    atendimento: dict[str, Any],
    origem: Origem,
    autor: Autor,
    payload: dict[str, Any],
) -> ResultadoComando:
    decisao = payload.get("decisao")
    # Pix nunca trava (01 §6.1, 07 §5): validado E em_revisao avancam o atendimento para
    # Confirmado + ia_pausada (modelo_em_atendimento) — a mesma transicao do handoff de saida.
    # A duvidez de em_revisao e informativa: vai no card a modelo (sinaliza) e numa fila de
    # revisao de Fernando no painel (comprovantes_pix.decisao_final), sem pausar esperando ele.
    if decisao == "validado":
        # Guard defensivo: Pix de deslocamento so existe no fluxo externo.
        estado = (
            "Confirmado" if atendimento["tipo_atendimento"] == "externo" else atendimento["estado"]
        )
        await conn.execute(
            """
            UPDATE barravips.atendimentos
               SET pix_status = 'validado',
                   estado = %s,
                   ia_pausada = true,
                   ia_pausada_motivo = 'modelo_em_atendimento',
                   responsavel_atual = 'modelo',
                   fonte_decisao_ultima_transicao = %s
             WHERE id = %s
            """,
            (estado, _fonte(origem), atendimento["id"]),
        )
        await _evento(conn, atendimento["id"], "pix_status_mudado", origem, autor, payload)
        return ResultadoComando(atendimento["id"], estado, "validado")

    if decisao == "em_revisao":
        estado = (
            "Confirmado" if atendimento["tipo_atendimento"] == "externo" else atendimento["estado"]
        )
        await conn.execute(
            """
            UPDATE barravips.atendimentos
               SET pix_status = 'em_revisao',
                   estado = %s,
                   ia_pausada = true,
                   ia_pausada_motivo = 'modelo_em_atendimento',
                   responsavel_atual = 'modelo',
                   fonte_decisao_ultima_transicao = %s
             WHERE id = %s
            """,
            (estado, _fonte(origem), atendimento["id"]),
        )
        await _evento(conn, atendimento["id"], "pix_status_mudado", origem, autor, payload)
        return ResultadoComando(atendimento["id"], estado, "em_revisao")

    if decisao == "invalido":
        # Veredito assincrono de Fernando no painel (/rejeitar). A modelo ja agiu sobre o card
        # de em_revisao, entao 'invalido' e so registro financeiro/auditoria: NAO reverte estado
        # nem despausa a IA (decisao grilling 2026-05-23). decisao_final ja foi gravado na rota.
        await conn.execute(
            """
            UPDATE barravips.atendimentos
               SET pix_status = 'invalido'
             WHERE id = %s
            """,
            (atendimento["id"],),
        )
        await _evento(conn, atendimento["id"], "pix_status_mudado", origem, autor, payload)
        return ResultadoComando(atendimento["id"], atendimento["estado"], "invalido")

    raise EntradaInvalida("DECISAO_PIX_INVALIDA", "Decisao Pix invalida.")


# --- Camada de mapeamento motivo -> (tipo, responsavel) + bucket (M3f, 04 §3.4/§3.6, 09 §4.3) ---
# A tool `escalar` (e `escalar_por_exaustao`) falam um enum RICO de motivos; `abrir_handoff`
# fala os 8 valores de TipoEscalada. Estas funcoes puras adaptam um ao outro — o motivo LITERAL
# nunca some: o chamador o passa em `observacao` do `abrir_handoff`.

# Motivos cujo responsavel e a propria modelo (acao operacional dela). Todo o resto -> Fernando.
_RESP_MODELO: frozenset[str] = frozenset(
    {"fora_de_oferta", "horario_indisponivel", "reagendamento_pos_bloqueio"}
)

# Colapso do motivo nos 8 valores de TipoEscalada. O que nao consta cai em `outro`
# (politica_nova_necessaria, exaustao_iteracoes, timeout_grafo, modelo_recusou, outro).
_TIPO_POR_MOTIVO: dict[str, TipoEscalada] = {
    "disclosure_insistente": TipoEscalada.comportamento_atipico,
    "disclosure_explicito": TipoEscalada.comportamento_atipico,
    "jailbreak_attempt": TipoEscalada.comportamento_atipico,
    "pedido_explicito_repetido": TipoEscalada.comportamento_atipico,
    "prova_humanidade_persistente": TipoEscalada.comportamento_atipico,
    "cross_modelo_fishing": TipoEscalada.comportamento_atipico,
    "fora_de_oferta": TipoEscalada.fora_de_oferta,
    "horario_indisponivel": TipoEscalada.indisponibilidade,
    "reagendamento_pos_bloqueio": TipoEscalada.indisponibilidade,
}

# Bucket da metrica agente_escalada_total (08 §3.2): familia AUP + modelo_recusou = defesa
# (ataque/safety; spike -> alerta); todo o resto = capacidade.
_BUCKET_DEFESA: frozenset[str] = frozenset(
    {
        "disclosure_insistente",
        "disclosure_explicito",
        "jailbreak_attempt",
        "pedido_explicito_repetido",
        "prova_humanidade_persistente",
        "cross_modelo_fishing",
        "modelo_recusou",
        # AGENTE-OG (ADR 0016): output-guard bloqueou a bolha antes do envio — defesa ativa.
        "output_leak",
        "aup_saida",
        # Rede final do enviar_turno (SEC-OUT-01) e reincidência por telefone (SEC-JB-02).
        "envio_leak",
        "reincidencia_seguranca",
    }
)

# Bucket infra: falha de plataforma (5xx/timeout persistente da API do LLM, ou resposta truncada
# com tool_use incompleto -- STOP-03/06), nao capacidade de negociacao.
_BUCKET_INFRA: frozenset[str] = frozenset({"modelo_indisponivel", "modelo_truncado"})


def mapear_motivo(motivo: str) -> tuple[TipoEscalada, str]:
    """Adapta o motivo rico da tool `escalar` a `abrir_handoff` (09 §4.3).

    Devolve `(tipo, responsavel)`: `tipo` colapsa o motivo nos 8 valores de ``TipoEscalada``
    (chave de agregacao do dashboard) e `responsavel` decide o destino do handoff
    (``Fernando`` por padrao seguro; ``modelo`` so para acoes operacionais dela).
    """
    tipo = _TIPO_POR_MOTIVO.get(motivo, TipoEscalada.outro)
    responsavel = "modelo" if motivo in _RESP_MODELO else "Fernando"
    return tipo, responsavel


def mapear_bucket(motivo: str) -> str:
    """Bucket da metrica `agente_escalada_total` (08 §3.2): ``infra``/``defesa``/``capacidade``."""
    if motivo in _BUCKET_INFRA:
        return "infra"
    return "defesa" if motivo in _BUCKET_DEFESA else "capacidade"


# Observacao canonica da escalada de lembrete-sem-resposta (espelha
# `workers/lembrete_valor.OBS_ESCALADA`, que a importa daqui). Vive no dominio porque a regra de
# audiencia abaixo precisa dela e `dominio/` nao pode depender de `workers/` (direcao das deps).
OBS_LEMBRETE_SEM_RESPOSTA = "valor_final_nao_confirmado"


def card_escalada_vai_ao_grupo(responsavel: str, observacao: str | None) -> bool:
    """Decide se uma escalada gera Card no grupo de Coordenacao da modelo (UX §1.5/§9.6).

    Roteia por owner: ``responsavel='modelo'`` (acao operacional dela) -> grupo. ``responsavel=
    'Fernando'`` (excecao de gestao/sistema: jailbreak, politica, exaustao) -> NAO posta no grupo,
    vai so pro painel/fila no P0 (IA Admin no P1). Unica excecao: o lembrete-sem-resposta, que
    continua no grupo por ser a mesma thread do Lembrete de fechamento que ja vive la.
    """
    if responsavel == "modelo":
        return True
    return observacao == OBS_LEMBRETE_SEM_RESPOSTA


async def abrir_handoff(
    conn: AsyncConnection[Any],
    *,
    atendimento_id: UUID,
    responsavel: str,
    tipo: TipoEscalada,
    resumo_operacional: str,
    acao_esperada: str,
    origem: Origem,
    autor: Autor,
    observacao: str | None = None,
    card_message_id: str | None = None,
) -> None:
    motivo_texto = observacao or rotulo_tipo_escalada(tipo)
    async with conn.transaction():
        # Idempotencia (REL-02): nao abre escalada duplicada quando o turno e reprocessado
        # (re-drain do ARQ sem checkpointer; ou caminhos que chamam abrir_handoff direto sem
        # _executar_idempotente, ex.: intercept_disclosure re-incrementando o contador). Uma
        # escalada aberta (fechada_em IS NULL) ja deixou a IA pausada — o handoff esta de pe,
        # nada a refazer. Mesmo guard de lembrete_valor._buscar_alvos.
        cur = await conn.execute(
            """
            INSERT INTO barravips.escaladas (
              atendimento_id, responsavel, tipo, motivo, observacao,
              resumo_operacional, acao_esperada, card_message_id
            )
            SELECT %s, %s, %s, %s, %s, %s, %s, %s
             WHERE NOT EXISTS (
               SELECT 1 FROM barravips.escaladas
                WHERE atendimento_id = %s AND fechada_em IS NULL
             )
            """,
            (
                atendimento_id,
                responsavel,
                tipo.value,
                motivo_texto,
                observacao,
                resumo_operacional,
                acao_esperada,
                card_message_id,
                atendimento_id,
            ),
        )
        if cur.rowcount == 0:
            return  # escalada ja aberta — handoff idempotente, nada a refazer
        await conn.execute(
            """
            UPDATE barravips.atendimentos
               SET ia_pausada = true,
                   ia_pausada_motivo = 'handoff_ia',
                   responsavel_atual = %s,
                   motivo_escalada = %s,
                   proxima_acao_esperada = %s
             WHERE id = %s
            """,
            (responsavel, motivo_texto, acao_esperada, atendimento_id),
        )
        await _evento(
            conn,
            atendimento_id,
            "handoff_aberto",
            origem,
            autor,
            {
                "responsavel": responsavel,
                "tipo": tipo.value,
                "motivo": motivo_texto,
                "observacao": observacao,
                "acao_esperada": acao_esperada,
            },
        )


async def _evento(
    conn: AsyncConnection[Any],
    atendimento_id: UUID,
    tipo: str,
    origem: Origem,
    autor: Autor,
    payload: dict[str, Any],
) -> None:
    await conn.execute(
        """
        INSERT INTO barravips.eventos (atendimento_id, tipo, origem, autor, payload)
        VALUES (%s, %s, %s, %s, %s::jsonb)
        """,
        (atendimento_id, tipo, _origem_evento(origem), autor, json.dumps(payload, default=str)),
    )


def _fonte(origem: Origem) -> str:
    return {
        "painel": "painel_fernando",
        "grupo_coordenacao": "comando_grupo",
        "pipeline_pix": "pipeline_pix",
        "cron": "cron_em_execucao",
        "agente": "extracao_ia",
    }[origem]


def _origem_evento(origem: Origem) -> str:
    return "grupo_coordenacao" if origem == "grupo_coordenacao" else origem


def _canal(origem: Origem) -> str:
    return "grupo_coordenacao" if origem == "grupo_coordenacao" else "painel"
