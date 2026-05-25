"""Orquestracao do ciclo de vida de um atendimento aberto por par (cliente, modelo)."""

import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal, cast
from uuid import UUID

from psycopg import AsyncConnection

from barra.settings import get_settings

Origem = Literal["webhook", "painel_fernando"]


@dataclass(frozen=True)
class Atendimento:
    id: UUID
    numero_curto: int
    estado: str
    cliente_id: UUID
    modelo_id: UUID
    conversa_id: UUID
    ja_existia: bool


async def garantir_conversa(
    conn: AsyncConnection[Any],
    *,
    cliente_id: UUID,
    modelo_id: UUID,
    evolution_chat_id: str | None = None,
) -> UUID:
    """Faz upsert da conversa do par (cliente_id, modelo_id) e devolve o conversa_id.

    Caminho fino do webhook: persistir a mensagem do cliente precisa do conversa_id
    (NOT NULL) sem criar atendimento — quem resolve/cria o atendimento e o coordenador
    (`workers/coordenador.py`), sob `lock:conv`.
    """
    if evolution_chat_id is None:
        conversa = await _one(
            conn,
            """
            INSERT INTO barravips.conversas (cliente_id, modelo_id)
            VALUES (%s, %s)
            ON CONFLICT (cliente_id, modelo_id)
            DO UPDATE SET cliente_id = EXCLUDED.cliente_id
            RETURNING id
            """,
            (cliente_id, modelo_id),
        )
    else:
        conversa = await _one(
            conn,
            """
            INSERT INTO barravips.conversas (cliente_id, modelo_id, evolution_chat_id)
            VALUES (%s, %s, %s)
            ON CONFLICT (cliente_id, modelo_id)
            DO UPDATE SET evolution_chat_id = EXCLUDED.evolution_chat_id
            RETURNING id
            """,
            (cliente_id, modelo_id, evolution_chat_id),
        )
    assert conversa is not None
    return cast(UUID, conversa["id"])


async def garantir_atendimento_aberto(
    conn: AsyncConnection[Any],
    *,
    cliente_id: UUID,
    modelo_id: UUID,
    origem: Origem,
    evolution_chat_id: str | None = None,
) -> Atendimento:
    """Garante exatamente um atendimento aberto no par (cliente_id, modelo_id).

    Faz upsert da conversa do par e devolve o atendimento aberto existente,
    criando um novo apenas quando nao existe. `origem` registra quem disparou
    a criacao (webhook ingerindo mensagem vs. POST manual no painel).
    """
    del origem  # mantido na assinatura para auditoria futura, sem uso atual.
    conversa_id = await garantir_conversa(
        conn,
        cliente_id=cliente_id,
        modelo_id=modelo_id,
        evolution_chat_id=evolution_chat_id,
    )

    existente = await _one(
        conn,
        """
        SELECT id, numero_curto, estado::text AS estado, cliente_id, modelo_id, conversa_id
          FROM barravips.atendimentos
         WHERE cliente_id = %s AND modelo_id = %s
           AND estado NOT IN ('Fechado', 'Perdido')
        """,
        (cliente_id, modelo_id),
    )
    if existente is not None:
        return Atendimento(
            id=existente["id"],
            numero_curto=existente["numero_curto"],
            estado=existente["estado"],
            cliente_id=existente["cliente_id"],
            modelo_id=existente["modelo_id"],
            conversa_id=existente["conversa_id"],
            ja_existia=True,
        )

    novo = await _one(
        conn,
        """
        INSERT INTO barravips.atendimentos (cliente_id, modelo_id, conversa_id)
        VALUES (%s, %s, %s)
        RETURNING id, numero_curto, estado::text AS estado, cliente_id, modelo_id, conversa_id
        """,
        (cliente_id, modelo_id, conversa_id),
    )
    assert novo is not None
    return Atendimento(
        id=novo["id"],
        numero_curto=novo["numero_curto"],
        estado=novo["estado"],
        cliente_id=novo["cliente_id"],
        modelo_id=novo["modelo_id"],
        conversa_id=novo["conversa_id"],
        ja_existia=False,
    )


async def _one(
    conn: AsyncConnection[Any],
    query: str,
    params: tuple[Any, ...],
) -> dict[str, Any] | None:
    result = await conn.execute(query, params)
    return await result.fetchone()


# -----------------------------------------------------------------------------
# Extracao da IA (registrar_extracao / M3d, docs/agente/04 §3.1, 02 §11)
# -----------------------------------------------------------------------------

# Campos do ExtracaoPayload que mapeiam 1:1 para colunas de atendimentos. O payload tambem
# carrega `motivo_perda_candidato` e `sinais_qualificacao`: o primeiro NAO tem coluna (so existe
# `motivo_perda`, setado no Registro de resultado), entao fica preservado apenas no evento
# `extracao_registrada` (auditoria) — divergencia do pseudocodigo 04 §3.1, que listava uma coluna
# inexistente; o segundo faz merge jsonb. `intencao` ganhou coluna+enum (migration M3d).
_CAMPOS_UPSERT = (
    "intencao",
    "urgencia",
    "tipo_atendimento",
    "data_desejada",
    "horario_desejado",
    "duracao_horas",
    "endereco",
    "bairro",
    "tipo_local",
    "forma_pagamento",
    "valor_acordado",
    "proxima_acao_esperada",
)


async def registrar_extracao_ia(
    conn: AsyncConnection[Any],
    atendimento_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """UPSERT do snapshot da IA + transicao de estado + bloqueio previo, na transacao do chamador.

    Roda SEM abrir transacao propria: a tool ja envelopa esta chamada em `_executar_idempotente`
    (uma transacao), entao snapshot + transicao + bloqueio sao atomicos (o advisory lock + a
    EXCLUDE de `bloqueios` nao toleram janela). Devolve `{"mensagem", "novo_estado", "enviar_pin"?}`
    (tudo JSON-serializavel — o helper de idempotencia persiste o dict). `ConflitoAgenda` propaga
    (a tool converte em erro recuperavel; gotcha M3d).
    """
    aid = UUID(str(atendimento_id))
    limpar = set(payload.get("limpar") or [])

    # Branch 12 (04 §3.1): cliente muda horario de atendimento que JA tem bloqueio previo em
    # Aguardando_confirmacao -> nao sobrescreve (deixaria o bloqueio orfao); escala p/ a modelo.
    if await _reagendamento_pos_bloqueio(conn, aid, payload):
        await _escalar_modelo(
            conn,
            aid,
            motivo="reagendamento_pos_bloqueio",
            resumo="Cliente quer mudar o horario de um atendimento ja reservado.",
            acao="Realocar o bloqueio para o novo horario ou recusar com o cliente.",
        )
        return {
            "mensagem": "Horario ja reservado: reagendamento escalado para a modelo.",
            "novo_estado": None,
        }

    # Guarda do piso de desconto (ADR-0004, defesa-em-profundidade sobre o prompt geral): valor
    # abaixo do piso NAO e gravado e dispara escalada fora_de_oferta para a modelo.
    if _registra_valor(payload, limpar) and await _abaixo_do_piso(conn, aid, payload):
        await _escalar_modelo(
            conn,
            aid,
            motivo="fora_de_oferta",
            resumo="Cliente pediu valor abaixo do piso de desconto (ADR-0004).",
            acao="Negociar manualmente com o cliente ou recusar.",
        )
        return {
            "mensagem": "Valor abaixo do piso de desconto: escalado para a modelo, valor nao gravado.",
            "novo_estado": None,
        }

    # 1. UPSERT por COALESCE: so campos nao-nulos sobrescrevem; `limpar` forca NULL e tem
    #    PRECEDENCIA sobre o payload (cliente recuou). `sinais_qualificacao` faz merge jsonb.
    sets, valores = _montar_upsert(payload, limpar)
    if not sets:
        return {"mensagem": "Nenhum campo novo para registrar.", "novo_estado": None}
    valores.append(aid)
    await conn.execute(
        f"UPDATE barravips.atendimentos SET {', '.join(sets)}, "
        "fonte_decisao_ultima_transicao = 'extracao_ia' WHERE id = %s",
        valores,
    )

    # 2. Transicao de estado (02 §11) + side-effects deterministicos.
    resultado_extra: dict[str, Any] = {}
    novo_estado = await _decidir_transicao(conn, aid)
    if novo_estado is not None:
        await conn.execute(
            "UPDATE barravips.atendimentos SET estado = %s WHERE id = %s",
            (novo_estado, aid),
        )
        await _registrar_evento(conn, aid, "transicao_estado", {"para": novo_estado})
        if novo_estado == "Aguardando_confirmacao":
            atendimento = await _refetch_para_bloqueio(conn, aid)
            # Externo NAO chega aqui (so pedir_pix_deslocamento promove externo, M3e); este ramo
            # e o interno: cria o bloqueio previo e sinaliza o pin de endereco (side-effect, nao
            # tool — o wrapper enfileira o card loc_pin apos o commit).
            if atendimento["tipo_atendimento"] == "interno":
                from barra.dominio.agenda.service import criar_bloqueio_previo

                await criar_bloqueio_previo(conn, atendimento=atendimento)
                resultado_extra["enviar_pin"] = True

    await _registrar_evento(conn, aid, "extracao_registrada", payload)
    return {"mensagem": "Extracao registrada.", "novo_estado": novo_estado, **resultado_extra}


def _montar_upsert(payload: dict[str, Any], limpar: set[str]) -> tuple[list[str], list[Any]]:
    """Monta os pares SET do UPSERT. `limpar` forca NULL e vence o payload; demais campos so
    entram quando nao-nulos (COALESCE incremental). Os nomes vem de `_CAMPOS_UPSERT` (constante,
    nunca input do cliente) — f-string de coluna segue o padrao de dominio/agenda/routes.py."""
    sets: list[str] = []
    valores: list[Any] = []
    for campo in _CAMPOS_UPSERT:
        if campo in limpar:
            sets.append(f"{campo} = NULL")
        elif payload.get(campo) is not None:
            sets.append(f"{campo} = %s")
            valores.append(payload[campo])
    if payload.get("sinais_qualificacao"):
        sets.append("sinais_qualificacao = sinais_qualificacao || %s::jsonb")
        valores.append(json.dumps(payload["sinais_qualificacao"]))
    return sets, valores


async def _decidir_transicao(conn: AsyncConnection[Any], atendimento_id: UUID) -> str | None:
    """Transicoes da extracao (02 §11 — fonte unica do lado do agente). Le o estado JA atualizado
    pelo UPSERT. Externo nao e promovido aqui (invariante: externo em Aguardando_confirmacao =>
    Pix solicitado; so pedir_pix_deslocamento promove, 01 §6.1)."""
    res = await conn.execute(
        "SELECT estado::text AS estado, intencao::text AS intencao, "
        "tipo_atendimento::text AS tipo_atendimento, horario_desejado "
        "FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    assert a is not None
    if a["estado"] == "Novo" and a["intencao"] is not None:
        return "Triagem"
    if (
        a["estado"] == "Triagem"
        and a["intencao"] == "agendamento"
        and a["horario_desejado"] is not None
        and a["tipo_atendimento"] is not None
    ):
        return "Qualificado"
    if (
        a["estado"] == "Qualificado"
        and a["tipo_atendimento"] == "interno"
        and a["horario_desejado"] is not None
    ):
        return "Aguardando_confirmacao"
    return None


async def _reagendamento_pos_bloqueio(
    conn: AsyncConnection[Any], atendimento_id: UUID, payload: dict[str, Any]
) -> bool:
    """True quando o payload tenta mudar horario/data de um atendimento que ja esta em
    Aguardando_confirmacao COM bloqueio previo (branch 12)."""
    novo_horario = payload.get("horario_desejado")
    nova_data = payload.get("data_desejada")
    if novo_horario is None and nova_data is None:
        return False
    res = await conn.execute(
        "SELECT estado::text AS estado, bloqueio_id, horario_desejado, data_desejada "
        "FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    if a is None or a["estado"] != "Aguardando_confirmacao" or a["bloqueio_id"] is None:
        return False
    return _difere(a["horario_desejado"], novo_horario) or _difere(a["data_desejada"], nova_data)


def _difere(atual: Any, novo: Any) -> bool:
    """Compara um valor temporal do banco (date/time) com o do payload (ISO string, modo JSON).
    None no payload = campo nao mexido -> nao difere."""
    if novo is None:
        return False
    if atual is None:
        return True
    atual_s = atual.isoformat() if hasattr(atual, "isoformat") else str(atual)
    novo_s = novo.isoformat() if hasattr(novo, "isoformat") else str(novo)
    return atual_s != novo_s


def _registra_valor(payload: dict[str, Any], limpar: set[str]) -> bool:
    return payload.get("valor_acordado") is not None and "valor_acordado" not in limpar


async def _abaixo_do_piso(
    conn: AsyncConnection[Any], atendimento_id: UUID, payload: dict[str, Any]
) -> bool:
    """Piso = preco_de_tabela x (1 - desconto_max_pct) (ADR-0004). Sem programa correspondente a
    duracao, trata como abaixo do piso (escala). `desconto_max_pct=0` => piso = preco de tabela."""
    valor = Decimal(str(payload["valor_acordado"]))
    res = await conn.execute(
        "SELECT modelo_id FROM barravips.atendimentos WHERE id = %s", (atendimento_id,)
    )
    row = await res.fetchone()
    assert row is not None
    preco_tabela = await _preco_tabela_min(conn, row["modelo_id"], payload.get("duracao_horas"))
    if preco_tabela is None:
        return True
    fator = Decimal("1") - Decimal(str(get_settings().desconto_max_pct))
    return valor < preco_tabela * fator


async def _preco_tabela_min(
    conn: AsyncConnection[Any], modelo_id: Any, duracao_horas: Any
) -> Decimal | None:
    """Menor preco de tabela dos programas da modelo na duracao acordada (`duracoes.horas`).
    Usa o MENOR preco como base do piso (ADR-0004 §Decisao item 5): piso mais baixo => so escala
    quem esta abaixo ate do programa mais barato, minimizando falso-positivo."""
    if duracao_horas is None:
        return None
    res = await conn.execute(
        """
        SELECT mp.preco
          FROM barravips.modelo_programas mp
          JOIN barravips.duracoes d ON d.id = mp.duracao_id
         WHERE mp.modelo_id = %s AND d.horas = %s
         ORDER BY mp.preco ASC
         LIMIT 1
        """,
        (modelo_id, Decimal(str(duracao_horas))),
    )
    row = await res.fetchone()
    return row["preco"] if row is not None else None


async def _escalar_modelo(
    conn: AsyncConnection[Any],
    atendimento_id: UUID,
    *,
    motivo: str,
    resumo: str,
    acao: str,
) -> None:
    """Abre handoff para a modelo (ia_pausada=true). Mapping LOCAL motivo->tipo enquanto o
    `mapear_motivo` compartilhado nao existe; espelha workers/coordenador.py:escalar_por_exaustao.
    TODO(M3f): adotar mapear_motivo (escaladas/service) quando ele existir."""
    from barra.dominio.escaladas.modelos import TipoEscalada
    from barra.dominio.escaladas.service import abrir_handoff

    tipo = {
        "fora_de_oferta": TipoEscalada.fora_de_oferta,
        # indisponibilidade e o tipo mais proximo no enum; o motivo literal vai em observacao.
        "reagendamento_pos_bloqueio": TipoEscalada.indisponibilidade,
    }[motivo]
    await abrir_handoff(
        conn,
        atendimento_id=atendimento_id,
        responsavel="modelo",
        tipo=tipo,
        resumo_operacional=resumo,
        acao_esperada=acao,
        origem="agente",
        autor="IA",
        observacao=motivo,
    )


async def _refetch_para_bloqueio(
    conn: AsyncConnection[Any], atendimento_id: UUID
) -> dict[str, Any]:
    res = await conn.execute(
        "SELECT id, modelo_id, tipo_atendimento::text AS tipo_atendimento, "
        "data_desejada, horario_desejado, duracao_horas "
        "FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a: dict[str, Any] | None = await res.fetchone()
    assert a is not None
    return a


async def _registrar_evento(
    conn: AsyncConnection[Any], atendimento_id: UUID, tipo: str, payload: dict[str, Any]
) -> None:
    """Audit log (eventos) da extracao. origem='agente'/autor='IA' fixos. json.dumps porque
    psycopg3 nao adapta dict cru para jsonb (memoria jsonb_param_psycopg)."""
    await conn.execute(
        "INSERT INTO barravips.eventos (atendimento_id, tipo, origem, autor, payload) "
        "VALUES (%s, %s, 'agente', 'IA', %s::jsonb)",
        (atendimento_id, tipo, json.dumps(payload, default=str)),
    )
