"""Orquestracao do ciclo de vida de um atendimento aberto por par (cliente, modelo)."""

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, Literal, cast
from uuid import UUID
from zoneinfo import ZoneInfo

from psycopg import AsyncConnection
from psycopg.errors import ExclusionViolation

from barra.core.errors import ConflitoEstado
from barra.settings import get_settings

Origem = Literal["webhook", "painel_fernando"]


class CotacaoAusente(Exception):
    """Transicao para Aguardando_confirmacao barrada: o horario seria combinado sem o preco ter
    aparecido em nenhum turno (`cotacao_enviada_em IS NULL`) e sem cotar neste (finding onda 1 A).
    O cliente combinaria o encontro sem saber o valor -- <funil>: "encontro nunca fica combinado
    com preco nunca dito". Recuperavel: a casca da tool (extracao.py) instrui a IA a cotar antes de
    reservar o slot, no mesmo padrao de ConflitoAgenda/ForaDisponibilidade."""


class ParPrecoDuracaoInvalido(Exception):
    """Registro de `duracao_horas` barrado: a duracao mudou NESTE turno sem re-cotacao e o
    `valor_acordado` persistido (de outra duracao) ficaria abaixo do piso da tabela para a
    duracao nova -- a IA vendendo "3h" pelo preco da 1h (feedback piloto 21/07, atendimento #10
    da Tatiane). A guarda `_abaixo_do_piso` so roda quando o valor vem no payload; este e o furo
    complementar. Recuperavel: a casca da tool instrui a IA a re-cotar pela tabela ou limpar o
    valor, antes de a bolha sair."""


# Mesmo fuso que prepare_context usa: o horario_minimo chega aware (UTC) e o horario_desejado é
# gravado como hora LOCAL (prepare_context combina com tzinfo=_FUSO_BR ao reler).
_FUSO_BR = ZoneInfo("America/Sao_Paulo")


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

    # Herda o vendedor padrão da modelo (ADR 0012): subquery em vez de SELECT prévio para
    # nascer atômico com o INSERT. modelos.vendedor_id NULL (IA conduz) → vendedor_id NULL
    # (sem comissão). Coluna criada na migration 20260601090000.
    novo = await _one(
        conn,
        """
        INSERT INTO barravips.atendimentos (cliente_id, modelo_id, conversa_id, vendedor_id)
        VALUES (
          %s, %s, %s,
          (SELECT vendedor_id FROM barravips.modelos WHERE id = %s)
        )
        RETURNING id, numero_curto, estado::text AS estado, cliente_id, modelo_id, conversa_id
        """,
        (cliente_id, modelo_id, conversa_id, modelo_id),
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
# Digest de pendencias por modelo (UX §6.4) — o que aguarda a modelo no grupo dela
# -----------------------------------------------------------------------------


@dataclass(frozen=True)
class Pendencia:
    """Uma linha do digest de pendencias da modelo. `categoria` escolhe o emoji/copy no card."""

    numero_curto: int
    cliente_nome: str
    categoria: Literal["handoff", "falta_valor", "pix"]
    detalhe: str | None  # handoff: motivo curto da escalada
    encerrado_em: datetime | None  # falta_valor: bloqueios.fim ja em America/Sao_Paulo


async def listar_pendencias_modelo(
    conn: AsyncConnection[Any],
    modelo_id: UUID,
    *,
    tolerancia_min: int,
) -> list[Pendencia]:
    """Atendimentos da modelo que aguardam acao DELA, agrupados por tipo (UX §6.4).

    Tres origens, todas escopadas a `modelo_id` (isolamento por par):
      - **handoff**: escalada aberta com `responsavel='modelo'` (so as dela; jailbreak/politica/
        exaustao sao `responsavel='Fernando'` e ficam no painel — UX §9.6);
      - **falta_valor**: `Em_execucao` com `bloqueios.fim` vencido (+ tolerancia) — a mesma
        condicao que o Lembrete de fechamento cobra (espelha `workers/lembrete_valor`);
      - **pix**: comprovante `em_revisao` ainda nao resolvido por Fernando.

    Um atendimento pode cair em mais de uma origem; deduplica por `numero_curto` mantendo a de
    maior prioridade (handoff > falta_valor > pix), ja garantida pelo `ORDER BY` da query.
    `bloqueios.fim` ja vem convertido para America/Sao_Paulo (naive), pronto p/ `strftime` no card.
    """
    res = await conn.execute(
        """
        SELECT numero_curto, cliente_nome, categoria, detalhe, encerrado_em
          FROM (
            SELECT a.numero_curto, c.nome AS cliente_nome, 'handoff' AS categoria,
                   e.motivo AS detalhe, NULL::timestamp AS encerrado_em,
                   0 AS prioridade, e.aberta_em AS ord
              FROM barravips.escaladas e
              JOIN barravips.atendimentos a ON a.id = e.atendimento_id
              JOIN barravips.clientes c ON c.id = a.cliente_id
             WHERE a.modelo_id = %(modelo_id)s
               AND e.fechada_em IS NULL
               AND e.responsavel = 'modelo'
               AND a.estado NOT IN ('Fechado', 'Perdido')
            UNION ALL
            SELECT a.numero_curto, c.nome, 'falta_valor',
                   NULL, (b.fim AT TIME ZONE 'America/Sao_Paulo'),
                   1, b.fim
              FROM barravips.atendimentos a
              JOIN barravips.bloqueios b ON b.id = a.bloqueio_id
              JOIN barravips.clientes c ON c.id = a.cliente_id
             WHERE a.modelo_id = %(modelo_id)s
               AND a.estado = 'Em_execucao'
               AND b.fim < now() - make_interval(mins => %(tolerancia)s)
            UNION ALL
            SELECT a.numero_curto, c.nome, 'pix',
                   NULL, NULL, 2, a.updated_at
              FROM barravips.atendimentos a
              JOIN barravips.clientes c ON c.id = a.cliente_id
             WHERE a.modelo_id = %(modelo_id)s
               AND a.pix_status = 'em_revisao'
               AND a.estado NOT IN ('Fechado', 'Perdido')
          ) q
         ORDER BY prioridade, numero_curto
        """,
        {"modelo_id": modelo_id, "tolerancia": tolerancia_min},
    )
    vistos: set[int] = set()
    pendencias: list[Pendencia] = []
    for row in await res.fetchall():
        if row["numero_curto"] in vistos:
            continue  # ja listado por origem de maior prioridade
        vistos.add(row["numero_curto"])
        pendencias.append(
            Pendencia(
                numero_curto=row["numero_curto"],
                cliente_nome=row["cliente_nome"] or "cliente",
                categoria=row["categoria"],
                detalhe=row["detalhe"],
                encerrado_em=row["encerrado_em"],
            )
        )
    return pendencias


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

# Mensagens devolvidas pelas guardas de `registrar_extracao_ia` que ESCALAM (abrem handoff e
# pausam a IA) dentro da extracao — a "escalada silenciosa": a pausa faz o post_process descartar
# o texto do turno, e sem tratamento o cliente fica no vacuo (caso do 1500/5h, prod 22/07). O
# post_process (agente/nos) reconhece estas mensagens por igualdade EXATA para soltar uma bolha
# canned de espera; mudou um texto de retorno abaixo, atualize o frozenset junto.
_MSG_GUARD_REAGENDAMENTO = "Horario ja reservado: mudanca escalada para a modelo."
_MSG_GUARD_PISO = "Valor abaixo do piso de desconto: escalado para a modelo, valor nao gravado."
_MSG_GUARD_TIPO = "Tipo de atendimento que a modelo nao realiza: escalado, tipo nao gravado."
MENSAGENS_GUARD_ESCALADA = frozenset({_MSG_GUARD_REAGENDAMENTO, _MSG_GUARD_PISO, _MSG_GUARD_TIPO})


async def registrar_extracao_ia(
    conn: AsyncConnection[Any],
    atendimento_id: str,
    payload: dict[str, Any],
    *,
    agora: datetime | None = None,
    horario_minimo: datetime | None = None,
    horario_evidenciado: bool = False,
    recuo_detectado: bool = False,
) -> dict[str, Any]:
    """UPSERT do snapshot da IA + transicao de estado + bloqueio previo, na transacao do chamador.

    `horario_evidenciado` e o veredito do detector deterministico do TURNO (prepare_context): a
    janela tem fala do cliente que sustenta o horario. Nunca vem do payload — o payload e o canal
    contaminado pelo eco do belief (ver `_marca_horario_evidenciado`).

    `recuo_detectado` e o veredito do OUTRO detector do turno (mesma origem, mesmo motivo): o
    cliente retratou o aceite. Rebaixa `aceita_valor` no merge dos sinais (ver
    `_sinais_qualificacao_do_turno`); nao toca o `valor_acordado`, que segue gravado.

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
    # "drift" (diferenca <= tolerancia) NAO e pedido do cliente: a extração re-deriva horario
    # relativo ("daqui 1h") do `agora` de cada turno — descarta horario/data e segue o upsert.
    veredito_reagendamento = await _reagendamento_pos_bloqueio(conn, aid, payload)
    if veredito_reagendamento == "mudanca":
        await _escalar_modelo(
            conn,
            aid,
            motivo="reagendamento_pos_bloqueio",
            resumo="Cliente quer mudar ou desmarcar o horario de um atendimento ja reservado.",
            acao="Realocar ou cancelar o bloqueio conforme o cliente.",
        )
        return {
            "mensagem": _MSG_GUARD_REAGENDAMENTO,
            "novo_estado": None,
        }
    if veredito_reagendamento == "drift":
        descartado = {
            k: payload[k] for k in ("horario_desejado", "data_desejada") if payload.get(k)
        }
        payload = {
            k: v for k, v in payload.items() if k not in ("horario_desejado", "data_desejada")
        }
        # Auditoria do descarte (revisão de domínio): o evento extracao_registrada carrega o que
        # foi ignorado — divergência conversa vs bloqueio fica rastreável no histórico do painel.
        payload["drift_descartado"] = descartado

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
            "mensagem": _MSG_GUARD_PISO,
            "novo_estado": None,
        }

    # Guarda do par preco x duracao (feedback piloto 21/07): a duracao mudou neste turno SEM o
    # valor vir junto -- o `valor_acordado` persistido e de outra duracao, e a guarda acima nao
    # roda (so olha o payload). Sem isto a IA estica o periodo por cima do preco antigo ("3h 800"
    # com tabela so de 1h) e o par nunca e conferido. Erro recuperavel (nao escalada): a bolha
    # ainda nao saiu -- a IA corrige a fala e registra o par certo no mesmo turno.
    if (
        not _registra_valor(payload, limpar)
        and payload.get("duracao_horas") is not None
        and "duracao_horas" not in limpar
        and "valor_acordado" not in limpar
        and await _par_persistido_abaixo_do_piso(conn, aid, payload)
    ):
        raise ParPrecoDuracaoInvalido

    # Guarda do tipo de atendimento (CONTEXT.md "Atendimento interno vs externo",
    # defesa-em-profundidade sobre o prompt do BP3): tipo que a modelo nao aceita NAO e gravado
    # e dispara escalada fora_de_oferta — a IA nunca negocia tipo que a modelo nao realiza.
    # Mesmo padrao da guarda do piso acima; array vazio = cadastro incompleto, nao trava.
    tipo_pedido = payload.get("tipo_atendimento")
    if (
        tipo_pedido
        and "tipo_atendimento" not in limpar
        and not await _tipo_aceito(conn, aid, tipo_pedido)
    ):
        await _escalar_modelo(
            conn,
            aid,
            motivo="fora_de_oferta",
            resumo=f"Cliente pediu atendimento {tipo_pedido} e a modelo nao realiza esse tipo.",
            acao="Decidir com o cliente como seguir ou recusar.",
        )
        return {
            "mensagem": _MSG_GUARD_TIPO,
            "novo_estado": None,
        }

    # Flip de tipo com horario ja cravado (#41, 24/07): o tipo combinado nao muda por um PEDIDO do
    # cliente. Descarta o campo e audita — depois da guarda de tipo-aceito acima, que segue
    # escalando o tipo que a modelo nao realiza (o cliente pedir algo impossivel merece escalada
    # tenha horario cravado ou nao); o descarte cobre so o flip entre tipos que ela FAZ, que
    # passava reto e disparava o Pix de deslocamento (e o cancelamento do piloto, ADR-0033).
    tipo_mantido = await _flip_de_tipo_pos_crava(conn, aid, payload)
    if tipo_mantido is not None:
        payload = {k: v for k, v in payload.items() if k != "tipo_atendimento"}
        payload["tipo_descartado"] = {"pedido": tipo_pedido, "mantido": tipo_mantido}

    # Fallback de tempo imediato (#4): a extração às vezes grava urgencia=imediato SEM
    # `horario_desejado` (o LLM hesita num condicional tipo "agora mesmo se der"), e sem horário a
    # FSM não cria o bloqueio prévio -> fica Qualificado -> Perdido. Assume o `horario_minimo` (o
    # cedo agenda-coerente que a IA já oferece: arredonda_acima(now + antecedência), respeitando
    # bloqueios/Disponibilidade) — NÃO o `now` cru, que a guarda estrita de antecedência rejeitaria
    # (inicio < now). Age sobre o `urgencia` estruturado, não lê texto do cliente. Gates:
    #  (a) `horario_minimo` None (now+antecedência fora da Disponibilidade) -> não força; a IA cai
    #      na conduta de período de trabalho.
    #  (b) só destrava a reserva INICIAL — se já há bloqueio prévio, NÃO injeta: sobrescrever
    #      orfanaria o bloqueio sem escalar (a branch 12 / _reagendamento_pos_bloqueio cobre o
    #      reagendamento real, com horário explícito do cliente).
    #  (c) só SEM-deslocamento (interno/remoto): no externo-Uber, auto-cravar horário a
    #      partir de um "imediato" condicional dispararia uma cobrança de Pix sem o cliente
    #      confirmar — esse fica na trilha reoferta(horario_minimo)->confirma->Pix. Tipo efetivo =
    #      o deste turno (payload) ou o já gravado.
    # horario_minimo chega aware (UTC); grava-se a hora LOCAL (BRT). Resta uma race rara (~lat/30min)
    # quando o turno cruza um boundary :30: cai em AntecedenciaInsuficiente, recuperável (reoferta).
    if (
        payload.get("urgencia") == "imediato"
        and payload.get("horario_desejado") is None
        and "horario_desejado" not in limpar
        and horario_minimo is not None
    ):
        res = await conn.execute(
            "SELECT bloqueio_id, tipo_atendimento FROM barravips.atendimentos WHERE id = %s",
            (aid,),
        )
        row = await res.fetchone()
        if row is not None and row["bloqueio_id"] is None:
            tipo_ef = payload.get("tipo_atendimento") or row["tipo_atendimento"]
            if tipo_ef in ("interno", "remoto"):
                payload["horario_desejado"] = horario_minimo.astimezone(_FUSO_BR).time()

    # 1. UPSERT por COALESCE: so campos nao-nulos sobrescrevem; `limpar` forca NULL e tem
    #    PRECEDENCIA sobre o payload (cliente recuou). `sinais_qualificacao` faz merge jsonb.
    sets, valores = _montar_upsert(payload, limpar, recuo_detectado=recuo_detectado)
    _marca_horario_evidenciado(sets, valores, payload, limpar, horario_evidenciado)
    if not sets:
        return {"mensagem": "Nenhum campo novo para registrar.", "novo_estado": None}
    valores.append(aid)
    await conn.execute(
        f"UPDATE barravips.atendimentos SET {', '.join(sets)}, "
        "fonte_decisao_ultima_transicao = 'extracao_ia' WHERE id = %s",
        valores,
    )

    # 1b. Promocao da intencao por EVIDENCIA, ANTES da FSM ler a linha.
    await _promover_intencao_por_evidencia(conn, aid, limpar)

    # 2. Transicao de estado (02 §11) + side-effects deterministicos. MULTI-HOP: itera ate o
    #    ponto-fixo, aplicando cada hop + seu side-effect. Quando intencao+tipo+horario chegam no
    #    mesmo turno, Triagem->Qualificado->Aguardando_confirmacao ocorrem juntos e o bloqueio
    #    previo nasce no proprio turno do horario (sem a janela de um turno do single-hop). Termina
    #    sempre: cada hop avanca o estado e Aguardando_confirmacao+ nao tem transicao automatica.
    resultado_extra: dict[str, Any] = {}
    novo_estado: str | None = None
    while True:
        hop = await _decidir_transicao(conn, aid)
        if hop is None:
            break
        novo_estado = hop
        await conn.execute(
            "UPDATE barravips.atendimentos SET estado = %s WHERE id = %s",
            (hop, aid),
        )
        await _registrar_evento(conn, aid, "transicao_estado", {"para": hop})
        if hop == "Aguardando_confirmacao":
            # Ancora do cron cancelar_piloto_teste (ADR-0033): carimba a ENTRADA no estado
            # (first-write-wins), distinta de bloqueios.inicio (o horario do encontro em si).
            await conn.execute(
                "UPDATE barravips.atendimentos SET aguardando_confirmacao_em = now() "
                "WHERE id = %s AND aguardando_confirmacao_em IS NULL",
                (aid,),
            )
            # Guard deterministico (finding onda 1 A): reservar o slot exige o preco ja dito.
            # Combinar horario/endereco com cotacao_enviada_em NULL e sem cotar NESTE turno deixaria
            # o cliente sair de casa sem saber o valor (<funil>: "encontro nunca fica combinado com
            # preco nunca dito"). Barra a transicao (rollback, como ConflitoAgenda) e a casca da
            # tool instrui a IA a cotar antes. Cotar-e-combinar no mesmo turno (cotacao_apresentada
            # marca cotacao_enviada_em logo abaixo, bloco 4) e permitido: e o caso abencoado pelo
            # proprio <funil> ("diga o valor junto da confirmacao").
            if not payload.get("cotacao_apresentada") and not await _cotacao_ja_enviada(conn, aid):
                raise CotacaoAusente
            atendimento = await _refetch_para_bloqueio(conn, aid)
            # Interno e remoto (video chamada, ADR 0021) criam o bloqueio previo aqui. O
            # externo-Uber tambem promove agora, mas seu bloqueio previo + Pix saem do bloco
            # deterministico abaixo (_solicitar_pix_deslocamento_se_aplicavel) — por isso nao
            # casa esta condicao. O pin de endereco e so do interno (remoto nao tem endereco).
            if atendimento["tipo_atendimento"] in ("interno", "remoto"):
                from barra.dominio.agenda.service import criar_bloqueio_previo

                await criar_bloqueio_previo(conn, atendimento=atendimento, agora=agora)
                if atendimento["tipo_atendimento"] == "interno":
                    resultado_extra["enviar_pin"] = True

    # 2b. Pix de deslocamento deterministico (externo-Uber): bloco independente da transicao
    #     deste turno — cobre tambem a promocao ja ocorrida em turno anterior (ver docstring).
    await _solicitar_pix_deslocamento_se_aplicavel(conn, aid, resultado_extra, agora=agora)

    # 3. Aviso de saida (06 §5 + emenda §0 item 10): detectado pelo agente, nao por regex.
    #    So em interno em Aguardando_confirmacao e guardado por aviso_saida_em IS NULL
    #    (segunda mensagem de "to indo" do mesmo cliente nao reenfileira card). NAO pausa
    #    a IA — segue conduzindo a conversa textualmente.
    if payload.get("aviso_saida_detectado"):
        if await _aviso_saida_aplicavel(conn, aid):
            if await marcar_aviso_saida(conn, aid):
                resultado_extra["enviar_aviso_saida"] = True

    # 4. Cotacao apresentada (ADR 0022): carimba cotacao_enviada_em (first-write-wins) quando a IA
    #    sinaliza que apresentou o preco. Ancora o reengajamento proativo (cron reengajar_silenciosos);
    #    sem transicao nem pausa — so o marcador. O guard IS NULL preserva o primeiro carimbo.
    if payload.get("cotacao_apresentada"):
        await marcar_cotacao_enviada(conn, aid)

    await _registrar_evento(conn, aid, "extracao_registrada", payload)
    return {"mensagem": "Extracao registrada.", "novo_estado": novo_estado, **resultado_extra}


async def _tipo_aceito(conn: AsyncConnection[Any], atendimento_id: UUID, tipo: str) -> bool:
    """True se a modelo do atendimento aceita `tipo` (`modelos.tipo_atendimento_aceito[]`).

    Array vazio/NULL = aceita ambos: cadastro incompleto nao trava a venda (mesmo espirito de
    "modelo sem regra de Disponibilidade e reservavel sempre")."""
    res = await conn.execute(
        """
        SELECT m.tipo_atendimento_aceito::text[] AS aceitos
          FROM barravips.atendimentos a
          JOIN barravips.modelos m ON m.id = a.modelo_id
         WHERE a.id = %s
        """,
        (atendimento_id,),
    )
    row = await res.fetchone()
    if row is None:
        return True
    # ::text[] no SELECT: sem o cast o psycopg devolve o enum-array custom como STRING
    # ("{interno,externo}") e o `in` viraria substring-match (array vazio "{}" seria truthy).
    aceitos = row["aceitos"] or []
    return not aceitos or tipo in aceitos


async def _aviso_saida_aplicavel(conn: AsyncConnection[Any], atendimento_id: UUID) -> bool:
    """True se o atendimento esta em interno + Aguardando_confirmacao (contexto onde aviso
    de saida faz sentido, 06 §5). Refetch porque o UPSERT pode ter acabado de promover o
    atendimento para Aguardando_confirmacao no MESMO turno."""
    res = await conn.execute(
        "SELECT estado::text AS estado, tipo_atendimento::text AS tipo_atendimento "
        "FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    if a is None:
        return False
    return bool(a["estado"] == "Aguardando_confirmacao" and a["tipo_atendimento"] == "interno")


def _montar_upsert(
    payload: dict[str, Any], limpar: set[str], *, recuo_detectado: bool = False
) -> tuple[list[str], list[Any]]:
    """Monta os pares SET do UPSERT. `limpar` forca NULL e vence o payload; demais campos so
    entram quando nao-nulos (COALESCE incremental). Os nomes vem de `_CAMPOS_UPSERT` (constante,
    nunca input do cliente) — f-string de coluna segue o padrao de dominio/agenda/routes.py."""
    sets: list[str] = []
    valores: list[Any] = []
    for campo in _CAMPOS_UPSERT:
        if campo in limpar:
            sets.append(f"{campo} = NULL")
        elif campo == "intencao" and payload.get(campo) is not None:
            # `intencao` e MONOTONICA: o COALESCE incremental deixaria o extrator barato REBAIXAR
            # 'agendamento' -> 'cotacao' num turno seguinte (foi o que manteve o #35 preso em
            # Triagem, 24/07), e com ele volta o slot "ele querer mesmo marcar" no belief. Quem
            # desqualifica e o RECUO explicito do cliente, que ja tem canal proprio: `limpar`
            # (ramo acima, tem precedencia) — a DESC do campo inclusive avisa que zerar "pode
            # reverter a qualificacao". Mesmo principio do merge de `sinais_qualificacao`, que so
            # adiciona True e nunca rebaixa um sinal ja gravado.
            sets.append("intencao = CASE WHEN intencao = 'agendamento' THEN intencao ELSE %s END")
            valores.append(payload[campo])
        elif payload.get(campo) is not None:
            sets.append(f"{campo} = %s")
            valores.append(payload[campo])
    sinais = _sinais_qualificacao_do_turno(payload, limpar, recuo_detectado=recuo_detectado)
    if sinais:
        sets.append("sinais_qualificacao = sinais_qualificacao || %s::jsonb")
        valores.append(json.dumps(sinais))
    return sets, valores


def _marca_horario_evidenciado(
    sets: list[str],
    valores: list[Any],
    payload: dict[str, Any],
    limpar: set[str],
    evidenciado: bool,
) -> None:
    """Anexa ao UPSERT a transicao da marca `horario_evidenciado` (spec proveniencia-do-horario).
    Muta `sets`/`valores` in-place; nada a anexar => nao toca a coluna.

        false -> true : SEMPRE que o detector do turno achou evidencia, mesmo com o VALOR igual
                        (o cliente confirmando depois o palpite do sistema conta — #25 -> "pode
                        ser 2h entao");
        true  -> false: so quando o VALOR muda sem evidencia nova (fallback de tempo imediato,
                        eco do belief, ou o horario sendo limpo);
        true  -> true : valor muda COM evidencia (o `evidenciado` vence, primeiro ramo).

    A comparacao e com o valor JA PERSISTIDO (`IS DISTINCT FROM`, dentro do proprio UPDATE): o eco
    do belief regrava o mesmo horario, e regravar o mesmo numero nao e mudanca — nao derruba a
    marca nem se auto-valida.
    """
    if evidenciado:
        sets.append("horario_evidenciado = true")
    elif "horario_desejado" in limpar:
        # Horario apagado (cliente recuou): nao ha valor a sustentar, a marca cai junto.
        sets.append("horario_evidenciado = false")
    elif payload.get("horario_desejado") is not None:
        sets.append(
            "horario_evidenciado = CASE WHEN horario_desejado IS DISTINCT FROM %s::time "
            "THEN false ELSE horario_evidenciado END"
        )
        valores.append(payload["horario_desejado"])


async def _promover_intencao_por_evidencia(
    conn: AsyncConnection[Any], atendimento_id: UUID, limpar: set[str]
) -> None:
    """Horario desejado presente E evidenciado => `intencao` sobe p/ 'agendamento'
    (spec extracao-promocao-intencao).

    `intencao` e o campo mais subjetivo do snapshot e quem o preenche e o extrator barato, que erra
    sistematicamente PARA BAIXO: em producao, 9 atendimentos tinham o cliente com aceite de valor e
    a intencao abaixo de agendamento, contra 4 com 'agendamento' gravado. O #34 e o retrato — tipo
    interno, 18:00 combinado, aceite real, e preso em `Triagem`; e ficar em Triagem nao e rotulo,
    porque o <local_de_encontro> so entra no contexto a partir de `Qualificado` (o #27 mostra o
    custo: sem o endereco cadastrado, a IA respondeu "onde e?" com um bairro inventado).

    Derivar de FATO em vez de julgamento e o mesmo padrao que `_sinais_qualificacao_do_turno` ja
    aplica ao espelhar `horario_desejado` em `informa_horario`. O gatilho e a EVIDENCIA (nao o
    aceite de valor, ruidoso demais: 1 verdadeiro em 10 no corpus) justamente porque sem ela um
    horario fantasma — o palpite que o fallback de tempo imediato gravou no #25 — viraria reserva.
    Absorve o piso pontual que vivia no no `extrair`: o aceite da sondagem passa a ser so mais uma
    fonte de evidencia de horario, nao regra propria.

    Roda DEPOIS do UPSERT e ANTES da FSM, sobre a linha JA atualizada: o predicado le o horario e a
    marca como ficaram, sem reimplementar em Python a transicao que `_marca_horario_evidenciado`
    expressa em SQL. Por ler a MARCA (e nao so a evidencia deste turno), tambem promove o
    atendimento cujo horario o operador carimbou pelo painel e o que ja nascera evidenciado num
    turno anterior — a cada turno o predicado e reavaliado.

    As pre-condicoes da FSM NAO mudam (fonte unica com o belief-state); muda so como a intencao
    chega ate elas. `limpar` vence, como no resto do UPSERT: com a retratacao explicita do cliente
    no turno, a promocao nao desfaz a desqualificacao que ele acabou de pedir.
    """
    if "intencao" in limpar:
        return
    await conn.execute(
        "UPDATE barravips.atendimentos SET intencao = 'agendamento' "
        "WHERE id = %s AND horario_desejado IS NOT NULL AND horario_evidenciado "
        "AND intencao IS DISTINCT FROM 'agendamento'",
        (atendimento_id,),
    )


def _sinais_qualificacao_do_turno(
    payload: dict[str, Any], limpar: set[str], *, recuo_detectado: bool = False
) -> dict[str, Any]:
    """Sinais de qualificacao a mergear no JSONB (`||`). Parte do que o LLM passou, DERIVA
    `horario_desejado` => `informa_horario` (que o LLM as vezes esquece de marcar — defasagem do
    diagnostico E2E #5, 2026-06-09) e REBAIXA o que o cliente retratou. O campo estruturado e a
    fonte confiavel (a docstring de `horario_desejado` so manda preencher com hora concreta); o
    boolean o espelha.

    Os dois campos sao ASSIMETRICOS de proposito, e por isso nao viram um mapa campo->sinal:
    `horario_desejado` espelha nos dois sentidos, `valor_acordado` so rebaixa.

    `valor_acordado` NAO deriva `aceita_valor` (atendimento #41, 24/07). A derivacao nasceu quando
    `valor_acordado` significava "valor fechado", mas na pratica ele e gravado JA NA COTACAO (e o
    guard do piso depende disso) — entao derivar aceite dele marcava "valor ja combinado" no MESMO
    turno em que a IA cotou. Efeito medido: o belief passava a mandar "nao re-cote nem renegocie",
    a escada do <desconto> nunca engatava (`n_contrapropostas` ficou em 0 com o cliente pedindo
    desconto 7x) e o horario era cravado sobre um valor que o cliente nunca topou. Quem separa
    cotado de aceito e so o sinal EXPLICITO do extrator.

    `limpar` REBAIXA o sinal a False em vez de omiti-lo, e tem precedencia sobre o payload (mesmo
    principio do UPSERT). Omitir deixava o merge `||` como latch de mao unica: um `aceita_valor`
    True gravado por engano nunca mais saia, e nem o Recuo pos-objecao (`<conducao_da_venda>`, que
    manda `limpar` o `valor_acordado`) reabria a escada do desconto.

    `recuo_detectado` (detector deterministico do turno; o porque mora em agente/_disciplina)
    rebaixa pelo MESMO motivo, sem depender de o extrator emitir `limpar`. Ele VENCE o aceite
    marcado no mesmo turno: falso positivo do detector so reabre a escada do desconto, enquanto o
    aceite falso trava a venda. Rebaixa SO o sinal — o `valor_acordado` fica gravado (e a base que
    o guard do piso confere), e o belief volta a apresenta-lo como cotado."""
    sinais = dict(payload.get("sinais_qualificacao") or {})
    # So rebaixa: `valor_acordado` e gravado na cotacao, entao presenca dele nunca prova aceite.
    if "valor_acordado" in limpar or recuo_detectado:
        sinais["aceita_valor"] = False
    # Espelha nos dois sentidos.
    if "horario_desejado" in limpar:
        sinais["informa_horario"] = False
    elif payload.get("horario_desejado") is not None:
        sinais["informa_horario"] = True
    return sinais


@dataclass(frozen=True)
class BeliefState:
    """Estado explicito do dialogo derivado da FSM, reinjetado no contexto a cada turno para
    cortar a re-pergunta multi-turn (state-update prompting). Fonte unica de regra com
    `_proxima_transicao`: ambos consomem `_PRECONDICOES_TRANSICAO`."""

    proxima_transicao: str | None
    slots_faltantes: list[str]
    proximo_passo: str


# Pre-condicoes de cada transicao automatica da extracao (02 §11). FONTE UNICA: alimenta tanto
# `_proxima_transicao` (a FSM real, lida no UPSERT) quanto o belief-state (o que falta + proximo
# passo no prompt). Cada predicado recebe os campos do atendimento por keyword; quando falso, seu
# rotulo entra em `slots_faltantes`, na ordem de cobranca.
#
# O HORARIO e o limiar de `Aguardando_confirmacao` (= reserva do slot), NAO de `Qualificado`:
# Triagem->Qualificado pede intencao+tipo (intencao real + "dado minimo" do tipo); o horario
# combinado e quem promove Qualificado->Aguardando_confirmacao e cria o bloqueio previo. Antes
# o horario gateava as DUAS transicoes, o que fundia os estados (saida de Qualificado era
# subconjunto da entrada) e, com a FSM single-hop, atrasava o bloqueio um turno quando
# intencao+tipo+horario chegavam juntos. `registrar_extracao_ia` agora itera ate o ponto-fixo
# (multi-hop), entao Triagem->Qualificado->Aguardando_confirmacao ocorrem no MESMO turno.
# TODO tipo com horario combinado promove a Aguardando_confirmacao (a reserva/Pix do
# externo-Uber sai do bloco de Pix, nao daqui).
_PRECONDICOES_TRANSICAO: dict[str, tuple[str, list[tuple[Callable[..., bool], str]]]] = {
    "Novo": (
        "Triagem",
        [(lambda *, intencao, **_: intencao is not None, "o que ele procura")],
    ),
    "Triagem": (
        "Qualificado",
        [
            (lambda *, intencao, **_: intencao == "agendamento", "ele querer mesmo marcar"),
            (
                lambda *, tipo_atendimento, **_: tipo_atendimento is not None,
                "o tipo do encontro (padrão: ele vem no seu local; só uber/vídeo se ELE sinalizar — não pergunte o formato)",
            ),
        ],
    ),
    "Qualificado": (
        "Aguardando_confirmacao",
        [
            (lambda *, horario_desejado, **_: horario_desejado is not None, "que horas ele quer"),
            (
                lambda *, tipo_atendimento, **_: tipo_atendimento is not None,
                "o tipo do encontro (padrão: ele vem no seu local; só uber/vídeo se ELE sinalizar — não pergunte o formato)",
            ),
        ],
    ),
}

# Frase-guia de conduta por estado (o "para onde ir"); os itens concretos que faltam vao em
# `slots_faltantes`. Estados sem transicao automatica (Aguardando_confirmacao+) recebem so a
# frase informativa do que se espera ali.
#
# A frase tambem ROTEIA: ela nomeia a(s) fase(s) do `<conducao_da_venda>` que valem agora — e, no
# `Aguardando_confirmacao`, o `<tipos_de_encontro>`, que e onde a logistica da chegada (pedir a foto
# da portaria, o Pix, o horario) esta escrita; a partir dali a conduta e logistica, nao funil, e o
# proprio `<fechamento>` ja manda pra la. O bloco
# inteiro continua no BP_GERAL (prefixo cacheado) — fatiar de verdade nao da, porque o `extrair`
# roda DEPOIS do `llm` (graph.py) e este `estado` e o do turno ANTERIOR: um prompt cortado por fase
# chegaria sempre um turno atrasado e o cliente que pula o funil ("quanto e?" no primeiro oi) cairia
# num prompt sem a fase que ele abriu. O que a cauda faz e apontar, nao amputar — por isso o
# preambulo do bloco diz explicitamente que o funil nao e trilho.
#
# ECO MULTI-SITE (agente/CLAUDE.md): as tags citadas aqui TEM que existir em `regras.md.j2`.
# Apontar pra uma tag que nao existe nao falha — o modelo so ignora, em silencio. Quem amarra e
# `tests/unit/test_contrato_variaveis_contexto.py`.
_PROXIMO_PASSO: dict[str, str] = {
    # `Novo` e o unico estado em que o ponteiro pode ficar um turno atras do cliente: e a primeira
    # fala dele, e o mais comum fora do trilho e ela ja vir pedindo preco ("oi, quanto custa ?").
    # Dai a condicional: a `<abertura>` segue sendo a conduta, mas a pergunta dele abre a fase.
    # O objetivo da fase e a intencao dele, mas a frase NAO pode nomea-lo com o lexico da sonda
    # ("entender o que ele procura"): a `<abertura>` proibe a sonda-de-balcao "em nenhuma parafrase"
    # (NUNCA em caps, agente/CLAUDE.md "Escala lexica de dureza") e esta e a fala que a cauda poe
    # mais perto da resposta — descrever o alvo com o lexico proibido virava o probe na boca dela.
    # Aqui a frase nomeia a ACAO da fase (parar e deixar ele abrir), nao o dado que falta; o dado
    # continua dito uma vez, no <ainda_falta>, que e onde ele pertence.
    "Novo": "deixar ele abrir o assunto e puxar pro encontro — sua conduta agora é <abertura>; se a fala dele já pede preço, <cotacao> junto",
    # A volta depois do sumico e ortogonal a FSM (nenhum `estado` a marca), mas ela acontece nestes
    # dois: a perda tipica e o silencio DEPOIS da cotacao, e e ai que ele reaparece. Ponteiro
    # condicional, na forma que o `Novo` ja usa — a cauda aponta, nao amputa. Sem ele a
    # `<retomada_pos_silencio>` nao era enderecada por nada (nem cross-ref interna, nem cauda).
    "Triagem": "fechar o que falta pra combinar o encontro — sua conduta agora é <apresentacao> e <cotacao>; se ele sumiu e voltou agora, <retomada_pos_silencio> junto",
    "Qualificado": "confirmar os detalhes e seguir pro próximo passo do encontro — sua conduta agora é <cotacao> e <fechamento>; se ele sumiu e voltou agora, <retomada_pos_silencio> junto",
    # A espera pela chegada saiu do BP_GERAL: a flag A2 `<ja_pediu_a_foto_da_portaria>` carrega as
    # mesmas falas de presenca e as mesmas proibicoes de cobranca, e so aparece quando ja houve
    # pedido. O que restava aqui era o ponteiro pro trilho da chegada — que aponta direto pro site
    # onde ele mora, o `<tipos_de_encontro>`.
    "Aguardando_confirmacao": "conduzir a confirmação (pix, foto de portaria ou o horário combinado) — sua conduta agora é <fechamento> e <tipos_de_encontro>",
    "Confirmado": "a modelo assume daqui; não reabra a negociação",
    "Em_execucao": "encontro em andamento; não reabra a negociação",
}


def _avaliar_precondicoes(
    *,
    estado: str | None,
    intencao: str | None,
    tipo_atendimento: str | None,
    horario_desejado: Any,
) -> tuple[str | None, list[str]]:
    """Avalia as pre-condicoes do estado UMA vez: devolve (transicao-alvo ou None, rotulos
    faltantes). Avaliacao unica consumida por `_proxima_transicao` (a FSM) e `derivar_belief_state`
    (o belief) — a transicao dispara exatamente quando nao falta nada, entao a consistencia entre
    FSM e belief e estrutural, nao so testada."""
    entrada = _PRECONDICOES_TRANSICAO.get(estado or "")
    if entrada is None:
        return None, []
    alvo, predicados = entrada
    valores = {
        "intencao": intencao,
        "tipo_atendimento": tipo_atendimento,
        "horario_desejado": horario_desejado,
    }
    faltantes = [rotulo for pred, rotulo in predicados if not pred(**valores)]
    return (alvo if not faltantes else None), faltantes


def _proxima_transicao(
    *,
    estado: str | None,
    intencao: str | None,
    tipo_atendimento: str | None,
    horario_desejado: Any,
) -> str | None:
    """Proximo estado da FSM da extracao, ou None. Substitui os if/elif inline com comportamento
    identico ao historico; fonte unica via `_avaliar_precondicoes`."""
    alvo, _ = _avaliar_precondicoes(
        estado=estado,
        intencao=intencao,
        tipo_atendimento=tipo_atendimento,
        horario_desejado=horario_desejado,
    )
    return alvo


def derivar_belief_state(
    *,
    estado: str | None,
    intencao: str | None,
    tipo_atendimento: str | None,
    horario_desejado: Any,
    cotacao_enviada: bool = True,
) -> BeliefState:
    """Belief-state do turno: o que falta pra avancar + a frase-guia, das MESMAS pre-condicoes da
    FSM (fonte unica com `_proxima_transicao`). Reinjetado no contexto dinamico a cada turno para
    cortar a re-pergunta multi-turn. `estado=None` (gate/webhook fino) -> belief neutro.

    `cotacao_enviada`: a cotacao (preco do programa) NAO e uma pre-condicao da FSM em
    `_PRECONDICOES_TRANSICAO` (ela e enforcada REATIVAMENTE no gate `CotacaoAusente` da transicao
    Qualificado->Aguardando_confirmacao, service ~L434). Sem ela o belief ficava mudo sobre o preco
    e a IA, em externo com horario ja escolhido, saltava pra logistica do uber/Pix sem nunca cotar
    o programa (conduta #4, grupo de testes 10/07). Aqui a expomos como slot em Triagem/Qualificado
    quando ainda nao foi dita — alinhando o belief ao que o guard ja enforça, e liderando a ordem de
    cobranca (funil: cotar antes de fechar/logistica). Default True = neutro (nao cobra a toa)."""
    alvo, faltantes = _avaliar_precondicoes(
        estado=estado,
        intencao=intencao,
        tipo_atendimento=tipo_atendimento,
        horario_desejado=horario_desejado,
    )
    if estado in ("Triagem", "Qualificado") and not cotacao_enviada:
        faltantes = ["dizer o preço do programa", *faltantes]
    return BeliefState(
        proxima_transicao=alvo,
        slots_faltantes=faltantes,
        proximo_passo=_PROXIMO_PASSO.get(estado or "", "conduzir o atendimento"),
    )


async def _decidir_transicao(conn: AsyncConnection[Any], atendimento_id: UUID) -> str | None:
    """Transicoes da extracao (02 §11 — fonte unica do lado do agente). Le o estado JA atualizado
    pelo UPSERT e delega a `_proxima_transicao` (mesma tabela que alimenta o belief-state). TODO
    tipo com horario combinado promove a Aguardando_confirmacao: interno (Foto de portaria),
    remoto (video chamada, ADR 0021) e externo-Uber. A reserva de slot + Pix do externo-Uber sai
    do bloco deterministico de Pix, nao aqui."""
    res = await conn.execute(
        "SELECT estado::text AS estado, intencao::text AS intencao, "
        "tipo_atendimento::text AS tipo_atendimento, horario_desejado "
        "FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    assert a is not None
    return _proxima_transicao(
        estado=a["estado"],
        intencao=a["intencao"],
        tipo_atendimento=a["tipo_atendimento"],
        horario_desejado=a["horario_desejado"],
    )


# Transicoes manuais permitidas pelo painel (kanban): so avanco linear, uma etapa por vez.
# Nunca regride e nunca PULA Aguardando_confirmacao — essa etapa e gatilhada/controlada pelo
# agente (Pix de deslocamento no externo, foto de portaria no interno) e o operador nao deve
# saltar por cima dela. Fechado/Perdido nao tem destino manual aqui: entram pelas rotas de
# registro de resultado (/fechar, /perder), que exigem valor_final / motivo. Em_execucao,
# Fechado e Perdido nao sao origem de nenhuma transicao manual.
_TRANSICOES_PAINEL: dict[str, frozenset[str]] = {
    "Novo": frozenset({"Qualificado", "Aguardando_confirmacao"}),
    "Triagem": frozenset({"Qualificado", "Aguardando_confirmacao"}),
    "Qualificado": frozenset({"Aguardando_confirmacao"}),
    "Aguardando_confirmacao": frozenset({"Em_execucao"}),
    "Confirmado": frozenset({"Em_execucao"}),
}


def validar_transicao_painel(estado_atual: str, estado_destino: str) -> None:
    """Levanta ConflitoEstado (409) se a transicao manual de estado_atual para estado_destino
    nao for permitida pelo painel. Defesa de servidor: o kanban ja bloqueia regressao e salto
    de coluna na UI, mas a regra de negocio vive aqui para que uma chamada direta a API nao a
    contorne (02 §11 — fonte unica do lado do agente; aqui e a fonte do lado do painel)."""
    if estado_destino not in _TRANSICOES_PAINEL.get(estado_atual, frozenset()):
        raise ConflitoEstado(
            f"Transicao de '{estado_atual}' para '{estado_destino}' nao e permitida pelo painel.",
            details={"estado_atual": estado_atual, "estado_destino": estado_destino},
        )


_TOLERANCIA_DRIFT_HORARIO = timedelta(minutes=15)


async def _reagendamento_pos_bloqueio(
    conn: AsyncConnection[Any], atendimento_id: UUID, payload: dict[str, Any]
) -> Literal["mudanca", "drift"] | None:
    """Classifica a tentativa de mudar horario/data de um atendimento que ja esta em
    Aguardando_confirmacao COM bloqueio previo (branch 12). None = payload nao mexe em
    horario/data (ou nao ha bloqueio); "drift" = diferenca dentro da tolerancia (re-derivacao
    do horario relativo a partir do `agora` do turno, nao e pedido do cliente — descartar);
    "mudanca" = reagendamento real -> escalar."""
    novo_horario = payload.get("horario_desejado")
    nova_data = payload.get("data_desejada")
    # `limpar` (recuo do cliente: "nao sei o dia ainda") tambem desfaz o horario combinado — sem
    # isto o snapshot zerava e o bloqueio previo ficava orfao travando a agenda, exatamente o que
    # a branch 12 existe pra impedir. Nao ha valor novo p/ medir drift: e sempre "mudanca".
    limpando_horario = bool(
        {"horario_desejado", "data_desejada"} & set(payload.get("limpar") or [])
    )
    if novo_horario is None and nova_data is None and not limpando_horario:
        return None
    res = await conn.execute(
        "SELECT estado::text AS estado, bloqueio_id, horario_desejado, data_desejada "
        "FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    if a is None or a["estado"] != "Aguardando_confirmacao" or a["bloqueio_id"] is None:
        return None
    if limpando_horario:
        return "mudanca"
    if not (_difere(a["horario_desejado"], novo_horario) or _difere(a["data_desejada"], nova_data)):
        return None
    if _dentro_da_tolerancia(a["data_desejada"], a["horario_desejado"], nova_data, novo_horario):
        return "drift"
    return "mudanca"


async def _flip_de_tipo_pos_crava(
    conn: AsyncConnection[Any], atendimento_id: UUID, payload: dict[str, Any]
) -> str | None:
    """Tipo do payload que CONTRARIA o tipo ja combinado de um atendimento com o horario cravado —
    devolve o tipo persistido (o que continua valendo); None quando nao ha conflito.

    Irma da branch 12 (`_reagendamento_pos_bloqueio`), no outro eixo: la o horario, aqui o tipo.
    Reservado o slot, o tipo esta combinado — ele decide quem se desloca, se ha Pix, qual endereco
    e como o atendimento fecha. O extrator, porem, gradua o PEDIDO do cliente como se fosse o
    combinado: no #41 (24/07 10:19) o cliente insistiu que ela fosse ate ele e o payload veio
    `tipo_atendimento=externo` com a propria prosa dizendo "estou recusando". O flip so precisava
    ser gravado para `_solicitar_pix_deslocamento_se_aplicavel` (bloco independente da transicao)
    cobrar um Pix de deslocamento de R$100 num encontro que seguia sendo no local dela.

    O Pix nao era o unico dano: o mesmo flip vira o gatilho do cancelamento automatico do piloto
    (ADR-0033) de braco. Fora do interno o cron mede 10min desde `aguardando_confirmacao_em` — no
    #41 um carimbo de ~2h antes, ja vencido —, entao o tipo virar externo satisfaz a condicao
    RETROATIVAMENTE e o cancelamento sai no tick seguinte, sem folga nenhuma: a desculpa canned
    caiu na conversa 8s depois do flip, no meio da negociacao de preco.

    Descarta em vez de escalar: a IA estava conduzindo certo (recusando), e escalar a pausaria no
    meio da recusa. Mudanca real de tipo com horario cravado e renegociacao — sai pela conduta dela
    (redireciona; na insistencia, `escalar`), nao por um campo de extracao.

    Vale com bloqueio previo OU em `Aguardando_confirmacao` sem ele: o estado ja significa horario
    combinado (o bloqueio e o efeito, nao a definicao), e e justamente o atendimento sem bloqueio
    que o cron do piloto cancela na hora — o LEFT JOIN dele so exige o bloqueio no braco interno."""
    novo_tipo = payload.get("tipo_atendimento")
    if not novo_tipo or "tipo_atendimento" in set(payload.get("limpar") or []):
        return None
    res = await conn.execute(
        "SELECT bloqueio_id, estado::text AS estado, tipo_atendimento::text AS tipo_atendimento "
        "FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    if a is None or a["tipo_atendimento"] is None:
        return None
    if a["bloqueio_id"] is None and a["estado"] != "Aguardando_confirmacao":
        return None
    tipo_atual: str = a["tipo_atendimento"]
    return tipo_atual if novo_tipo != tipo_atual else None


def _dentro_da_tolerancia(data_atual: Any, hora_atual: Any, nova_data: Any, nova_hora: Any) -> bool:
    """Diferenca pedida fica dentro de _TOLERANCIA_DRIFT_HORARIO? Compara o datetime combinado
    (data + hora); campo ausente no payload herda o valor atual. Sem referencia completa para
    medir o drift, devolve False (escala, comportamento anterior)."""
    nova_hora_t = _como_time(nova_hora) if nova_hora is not None else hora_atual
    nova_data_d = _como_date(nova_data) if nova_data is not None else data_atual
    if hora_atual is None or nova_hora_t is None or data_atual is None or nova_data_d is None:
        return False
    delta = datetime.combine(nova_data_d, nova_hora_t) - datetime.combine(data_atual, hora_atual)
    return abs(delta) <= _TOLERANCIA_DRIFT_HORARIO


def _como_time(v: Any) -> time:
    return v if isinstance(v, time) else time.fromisoformat(str(v))


def _como_date(v: Any) -> date:
    return v if isinstance(v, date) else date.fromisoformat(str(v))


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
    """Piso = preco_de_tabela x (1 - desconto_teto_pct) (ADR-0031, teto da escalada de 2 rodadas).
    Sem programa correspondente a duracao, trata como abaixo do piso (escala). `desconto_teto_pct=0`
    => piso = preco de tabela."""
    valor = Decimal(str(payload["valor_acordado"]))
    res = await conn.execute(
        "SELECT modelo_id, duracao_horas FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    row = await res.fetchone()
    assert row is not None
    # COALESCE da duracao: o payload deste turno tem precedencia (cliente pode ter mudado a
    # duracao agora); senao usa a ja persistida na cotacao. Sem isso, um turno que registra so o
    # `valor_acordado` sem reenviar a duracao (remoto/ADR 0029 no commit, ou o happy-path de
    # desconto interno/externo) caia em duracao=None -> preco=None -> escala fora_de_oferta espurio.
    # O guard roda ANTES do UPSERT deste turno, entao a leitura pega a duracao de turnos anteriores.
    duracao = payload.get("duracao_horas")
    if duracao is None:
        duracao = row["duracao_horas"]
    preco_tabela = await _preco_tabela_min(conn, row["modelo_id"], duracao)
    if preco_tabela is None:
        return True
    return valor < piso_de_desconto(preco_tabela)


async def _par_persistido_abaixo_do_piso(
    conn: AsyncConnection[Any], atendimento_id: UUID, payload: dict[str, Any]
) -> bool:
    """Confere o par (valor_acordado JA persistido, duracao_horas do payload) contra o piso da
    tabela. Sem valor persistido nao ha par a conferir (False). Reusa `_abaixo_do_piso` com um
    payload sintetico -- mesma regra: sem programa na duracao nova, trata como abaixo (a IA nao
    vende periodo fora da tabela)."""
    res = await conn.execute(
        "SELECT valor_acordado FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    row = await res.fetchone()
    assert row is not None
    if row["valor_acordado"] is None:
        return False
    return await _abaixo_do_piso(
        conn,
        atendimento_id,
        {"valor_acordado": row["valor_acordado"], "duracao_horas": payload["duracao_horas"]},
    )


def piso_de_desconto(preco_tabela: Decimal) -> Decimal:
    """Menor valor que a IA oferta sozinha sobre um preco de tabela: `preco x (1 -
    desconto_teto_pct)` (ADR-0031, teto da escalada de 2 rodadas). `desconto_teto_pct=0` =>
    piso = preco de tabela.

    SITE UNICO da conta, de proposito: quem JULGA a oferta da IA (`_abaixo_do_piso`) e quem
    MOSTRA o numero a ela (o `<ja_fez_contraproposta n="1">` da cauda, via
    `teto_de_contraproposta`) saem daqui. Duas implementacoes que concordam hoje divergem no
    arredondamento amanha, e a divergencia aparece como escalada `fora_de_oferta` a toa em cima
    de uma oferta que a propria cauda mandou fazer."""
    return preco_tabela * (Decimal("1") - Decimal(str(get_settings().desconto_teto_pct)))


async def teto_de_contraproposta(
    conn: AsyncConnection[Any], modelo_id: Any, duracao_horas: Any
) -> Decimal | None:
    """Valor ABSOLUTO da segunda e ultima contraproposta (ADR-0031) para a duracao em jogo — o
    numero que a cauda mostra a IA em vez do percentual que ela multiplicava de cabeca.

    `None` (a cauda nao injeta numero nenhum e a IA cai no percentual do `<desconto>`) quando:
    - a duracao nao esta fechada, ou nao ha programa dela nessa duracao — nao ha preco de tabela;
    - a duracao tem MAIS DE UM preco na tabela dela (ex.: "Padrao 1h 400" e "Casal 1h 700"). O
      piso que o guard usa e o do programa mais BARATO de proposito (ADR-0004 §Decisao item 5:
      minimiza falso-positivo de escalada), mas o teto que ela pode ofertar e sobre o "Preco de
      tabela do pacote VENDIDO" (CONTEXT.md, Piso de desconto) — e o pacote nao esta gravado no
      atendimento (`atendimento_servicos` so o painel escreve). Mostrar o piso do mais barato
      como se fosse o teto dela mandaria a IA dar 25% em cima do pacote errado. Com um preco so
      na duracao, as duas leituras sao o MESMO numero e a ambiguidade nao existe."""
    if duracao_horas is None:
        return None
    precos = await _precos_tabela(conn, modelo_id, duracao_horas)
    if precos is None or precos[0] != precos[1]:
        return None
    return piso_de_desconto(precos[0])


async def _preco_tabela_min(
    conn: AsyncConnection[Any], modelo_id: Any, duracao_horas: Any
) -> Decimal | None:
    """Menor preco de tabela dos programas da modelo na duracao acordada (`duracoes.horas`).
    Usa o MENOR preco como base do piso (ADR-0004 §Decisao item 5): piso mais baixo => so escala
    quem esta abaixo ate do programa mais barato, minimizando falso-positivo."""
    precos = await _precos_tabela(conn, modelo_id, duracao_horas)
    return precos[0] if precos is not None else None


async def _precos_tabela(
    conn: AsyncConnection[Any], modelo_id: Any, duracao_horas: Any
) -> tuple[Decimal, Decimal] | None:
    """`(menor, maior)` preco de tabela dos programas da modelo na duracao acordada
    (`duracoes.horas`), ou None sem nenhum programa nessa duracao. O menor e a base do piso
    (`_preco_tabela_min`); os dois juntos dizem se a duracao tem UM preco so, que e o que
    `teto_de_contraproposta` precisa saber."""
    if duracao_horas is None:
        return None
    res = await conn.execute(
        """
        SELECT min(mp.preco) AS menor, max(mp.preco) AS maior
          FROM barravips.modelo_programas mp
          JOIN barravips.duracoes d ON d.id = mp.duracao_id
         WHERE mp.modelo_id = %s AND d.horas = %s
        """,
        (modelo_id, Decimal(str(duracao_horas))),
    )
    row = await res.fetchone()
    # Agregado sem GROUP BY devolve SEMPRE uma linha: sem programa na duracao ela vem com NULL.
    if row is None or row["menor"] is None:
        return None
    return row["menor"], row["maior"]


def calcular_preco_extra_fetiche(
    preco_tabela: Decimal, duracao_horas: Decimal, *, cobra_por_pessoa: bool = False
) -> Decimal:
    """Preco do extra de um fetiche pago (ADR-0030): preco-hora efetivo do pacote vendido no
    atendimento (preco de tabela / horas), somado uma vez por fetiche. Multi-hora usa esse
    preco-hora, nao uma duracao-base de 1h (Pernoite 12h a R$3.600 -> +R$300, nao +R$3.600).

    `cobra_por_pessoa` (flag do catalogo global de fetiches, casal/menage) muda o regime: o
    fetiche eh cobrado POR PESSOA -- 2 pessoas fixas -> DOBRA o pacote, entao o extra eh o
    pacote INTEIRO (+preco_tabela), nao o preco-hora. Reabre o multiplicador que o ADR-0030
    deixou em aberto ("reabrir se aparecer um fetiche que precise valer mais que os outros" --
    ADR-0035). Em 1h os dois regimes coincidem (pacote == preco-hora); divergem de 2h em diante."""
    if cobra_por_pessoa:
        return preco_tabela
    return preco_tabela / duracao_horas


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


async def _solicitar_pix_deslocamento_se_aplicavel(
    conn: AsyncConnection[Any],
    atendimento_id: UUID,
    resultado_extra: dict[str, Any],
    *,
    agora: datetime | None = None,
) -> None:
    """Solicitacao deterministica do Pix (substitui a tool `pedir_pix_deslocamento`).

    Externo (Uber) pede o Pix de deslocamento (valor fixo) assim que esta em
    Aguardando_confirmacao com pix_status ainda 'nao_solicitado'. Remoto (ADR 0029) pede o Pix
    antecipado do VALOR DA CHAMADA (`valor_acordado`) no mesmo gate — com a condicao extra de
    ja haver valor acordado (sem ele nao ha o que pedir). Roda como bloco INDEPENDENTE da
    transicao deste turno (nao aninhado no `if novo_estado`): cobre tanto a promocao direta —
    a transicao acabou de levar a Aguardando_confirmacao — quanto o atendimento que ja estava
    la sem Pix solicitado (no remoto, isso inclui o turno em que a extracao finalmente grava o
    `valor_acordado`). Paridade com a tool antiga, cujo `WHERE pix_status='nao_solicitado'` +
    guard `bloqueio_id is None` davam o mesmo efeito.

    A chave Pix (string critico) NUNCA entra aqui (guard-rail de dado sensivel): so o valor;
    o coordenador anexa a chave fresh do cadastro apos o texto da IA. `ConflitoAgenda`/
    `ForaDisponibilidade` de `criar_bloqueio_previo` propagam — a casca da tool (extracao.py) as
    converte em erro recuperavel e a transacao reverte tudo atomicamente.
    """
    res = await conn.execute(
        "SELECT id, modelo_id, estado::text AS estado, "
        "tipo_atendimento::text AS tipo_atendimento, "
        "pix_status::text AS pix_status, bloqueio_id, "
        "data_desejada, horario_desejado, duracao_horas, valor_acordado "
        "FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    assert a is not None
    if not (
        a["estado"] == "Aguardando_confirmacao"
        and a["tipo_atendimento"] in ("externo", "remoto")
        and a["pix_status"] == "nao_solicitado"
    ):
        return
    if a["tipo_atendimento"] == "remoto" and a["valor_acordado"] is None:
        return
    # Bloqueio previo do externo-Uber: reserva o slot ao solicitar o Pix (simetrico aos demais
    # tipos). Guard `is None` para nao recriar bloqueio existente (estouraria a EXCLUDE
    # `bloqueios_sem_sobreposicao` com ConflitoAgenda espurio).
    if a["bloqueio_id"] is None:
        from barra.dominio.agenda.service import criar_bloqueio_previo

        await criar_bloqueio_previo(conn, atendimento=a, agora=agora)
    # Externo antecipa o custo FIXO do deslocamento; remoto antecipa o VALOR DA CHAMADA
    # (valor_acordado) — ADR 0029.
    valor = (
        a["valor_acordado"]
        if a["tipo_atendimento"] == "remoto"
        else get_settings().pix_deslocamento_valor
    )
    await conn.execute(
        "UPDATE barravips.atendimentos SET pix_status = 'aguardando' "
        "WHERE id = %s AND pix_status = 'nao_solicitado'",
        (atendimento_id,),
    )
    await _registrar_evento(conn, atendimento_id, "pix_solicitado", {"valor": str(valor)})
    resultado_extra["pix_solicitado"] = True
    resultado_extra["pix_valor"] = str(valor)


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


# -----------------------------------------------------------------------------
# Handoff foto de portaria + aviso de saida (M5d, docs/agente/06 §4/§5)
# -----------------------------------------------------------------------------


async def _inserir_escalada_chegada(conn: AsyncConnection[Any], atendimento_id: UUID) -> None:
    """Abre a escalada owner do card 'chegada' (idempotencia por owner do card, 06 §9).

    Copy compartilhada entre o handoff do interno vivo e a ressurreicao (ADR 0027) — ambos
    alimentam o mesmo card `tipo='chegada'`, entao a copy mora num lugar so.
    """
    await conn.execute(
        """
        INSERT INTO barravips.escaladas (
          atendimento_id, responsavel, tipo, motivo,
          resumo_operacional, acao_esperada
        )
        VALUES (
          %s, 'modelo', 'foto_portaria', 'Cliente chegou (foto de portaria)',
          'Cliente chegou no endereco combinado.',
          'Conferir a foto antes de abrir a porta.'
        )
        """,
        (atendimento_id,),
    )


async def handoff_foto_portaria_ia(
    conn: AsyncConnection[Any],
    *,
    atendimento_id: UUID,
    mensagem_id: UUID,
    media_object_key: str | None,
) -> None:
    """Handoff implicito disparado por foto de portaria em interno (06 §4).

    Quatro efeitos atomicos:
      1. UPDATE atendimento: estado=Em_execucao, ia_pausada=true,
         ia_pausada_motivo=modelo_em_atendimento, responsavel_atual=modelo,
         foto_portaria_em=now(), fonte_decisao_ultima_transicao=webhook_imagem.
      2. UPDATE bloqueio vinculado: estado='em_atendimento' (guard estado='bloqueado').
      3. INSERT escalada (tipo=foto_portaria, responsavel=modelo) para hospedar o
         card_message_id (idempotencia por owner do card 'chegada', 06 §9).
      4. Evento `transicao_estado` com gatilho='foto_portaria'.

    A transicao NAO depende de aprovacao humana — chegada da foto e o gatilho
    (CONTEXT.md "Foto de portaria"). O chamador (workers/media.py) enfileira o
    card 'chegada' depois do commit.

    Ressalva: NAO usamos `escaladas.service.abrir_handoff` porque ela seta
    ia_pausada_motivo='handoff_ia'; aqui o motivo correto e 'modelo_em_atendimento'
    (a IA pausa porque a modelo entrou em atendimento fisico, nao porque pediu
    decisao a Fernando).
    """
    async with conn.transaction():
        await conn.execute(
            """
            UPDATE barravips.atendimentos
               SET estado = 'Em_execucao',
                   ia_pausada = true,
                   ia_pausada_motivo = 'modelo_em_atendimento',
                   responsavel_atual = 'modelo',
                   foto_portaria_em = now(),
                   fonte_decisao_ultima_transicao = 'webhook_imagem'
             WHERE id = %s
            """,
            (atendimento_id,),
        )
        await conn.execute(
            """
            UPDATE barravips.bloqueios
               SET estado = 'em_atendimento'
             WHERE atendimento_id = %s AND estado = 'bloqueado'
            """,
            (atendimento_id,),
        )
        await _inserir_escalada_chegada(conn, atendimento_id)
        await conn.execute(
            "INSERT INTO barravips.eventos (atendimento_id, tipo, origem, autor, payload) "
            "VALUES (%s, 'transicao_estado', 'agente', 'sistema', %s::jsonb)",
            (
                atendimento_id,
                json.dumps(
                    {
                        "de": "Aguardando_confirmacao",
                        "para": "Em_execucao",
                        "gatilho": "foto_portaria",
                        "mensagem_id": str(mensagem_id),
                        "media_object_key": media_object_key,
                    }
                ),
            ),
        )


async def ressuscitar_interno_foto_portaria(
    conn: AsyncConnection[Any],
    *,
    conversa_id: UUID,
    mensagem_id: UUID,
    media_object_key: str | None,
) -> UUID | None:
    """Ressuscita um interno auto_timeout_interno pela foto de portaria tardia (ADR 0027).

    A foto chegou DEPOIS de o timeout (ADR 0024) marcar o #1 interno como Perdido/sumiu e
    cancelar o bloqueio. Se o cliente literalmente chegou ao local, orfanar a prova de
    chegada e fragmentar num novo #N seria errado operacionalmente.

    Reconecta o atendimento — volta a Em_execucao, ia_pausada=true (modelo_em_atendimento),
    reativa o bloqueio cancelado e abre a escalada owner do card 'chegada' — SE E SO SE:
      - a morte foi `auto_timeout_interno` (Perdido humano se respeita);
      - o slot segue livre (nenhum bloqueio ativo ocupou a janela);
      - ainda dentro do `bloqueio.fim` (o horario reservado nao acabou).
    Fora disso devolve None e o chamador segue fora-fluxo: a volta e recorrencia legitima
    (novo #N por mensagem). Excecao explicita ao invariante "Perdido e terminal", registrada
    no ADR 0027.

    Devolve o `atendimento_id` ressuscitado ou None (sem candidato).
    """
    try:
        async with conn.transaction():
            res = await conn.execute(
                """
                SELECT a.id, a.estado::text AS estado_anterior, b.id AS bloqueio_id
                  FROM barravips.atendimentos a
                  JOIN barravips.bloqueios b ON b.id = a.bloqueio_id
                 WHERE a.conversa_id = %s
                   AND a.tipo_atendimento = 'interno'
                   AND a.estado = 'Perdido'
                   AND a.fonte_decisao_ultima_transicao = 'auto_timeout_interno'
                   AND b.estado = 'cancelado'
                   AND b.fim > now()
                   AND NOT EXISTS (
                     SELECT 1
                       FROM barravips.bloqueios x
                      WHERE x.modelo_id = b.modelo_id
                        AND x.id <> b.id
                        AND x.estado IN ('bloqueado', 'em_atendimento')
                        AND tstzrange(x.inicio, x.fim, '[)') && tstzrange(b.inicio, b.fim, '[)')
                   )
                 ORDER BY a.created_at DESC
                 LIMIT 1
                 FOR UPDATE OF a SKIP LOCKED
                """,
                (conversa_id,),
            )
            alvo = await res.fetchone()
            if alvo is None:
                return None

            atendimento_id = alvo["id"]
            await conn.execute(
                """
                UPDATE barravips.atendimentos
                   SET estado = 'Em_execucao',
                       motivo_perda = NULL,
                       ia_pausada = true,
                       ia_pausada_motivo = 'modelo_em_atendimento',
                       responsavel_atual = 'modelo',
                       foto_portaria_em = now(),
                       fonte_decisao_ultima_transicao = 'webhook_imagem'
                 WHERE id = %s
                """,
                (atendimento_id,),
            )
            # Reativa o bloqueio cancelado. O NOT EXISTS acima ja descarta slot ocupado, mas
            # outro bloqueio ativo pode correr a janela entre o SELECT e este UPDATE (o
            # FOR UPDATE tranca `a`, nao o concorrente `x`): a EXCLUDE constraint
            # `bloqueios_sem_sobreposicao` barra a colisao e o except abaixo trata como slot
            # tomado — mesma defesa que `criar_bloqueio_previo` da no INSERT.
            await conn.execute(
                """
                UPDATE barravips.bloqueios
                   SET estado = 'em_atendimento'
                 WHERE id = %s AND estado = 'cancelado'
                """,
                (alvo["bloqueio_id"],),
            )
            await _inserir_escalada_chegada(conn, atendimento_id)
            await conn.execute(
                "INSERT INTO barravips.eventos (atendimento_id, tipo, origem, autor, payload) "
                "VALUES (%s, 'transicao_estado', 'agente', 'sistema', %s::jsonb)",
                (
                    atendimento_id,
                    json.dumps(
                        {
                            "de": alvo["estado_anterior"],
                            "para": "Em_execucao",
                            "gatilho": "foto_portaria_ressurreicao",
                            "mensagem_id": str(mensagem_id),
                            "media_object_key": media_object_key,
                        }
                    ),
                ),
            )
            return cast(UUID, atendimento_id)
    except ExclusionViolation:
        # Corrida: o slot foi reocupado entre a checagem e a reativacao do bloqueio. Mesmo
        # desfecho do NOT EXISTS — nao ressuscita (recorrencia vira novo #N), sem job fatal.
        return None


async def marcar_aviso_saida(conn: AsyncConnection[Any], atendimento_id: UUID) -> bool:
    """Marca `aviso_saida_em=now()` com guard IS NULL (helper leve, 06 §5 + emenda §0 item 8).

    Diferente do handoff de foto de portaria, NAO ha transicao de estado nem pausa de IA:
    o aviso de saida prepara a modelo via card simples (06 §5), mas a IA segue conduzindo
    a conversa. Devolve True se setou (o chamador enfileira o card), False (no-op
    silencioso) se ja estava setado — segunda mensagem de "to indo" do mesmo cliente
    nao reenfileira card.
    """
    result = await conn.execute(
        """
        UPDATE barravips.atendimentos
           SET aviso_saida_em = now()
         WHERE id = %s AND aviso_saida_em IS NULL
        """,
        (atendimento_id,),
    )
    return result.rowcount > 0


async def _cotacao_ja_enviada(conn: AsyncConnection[Any], atendimento_id: UUID) -> bool:
    """True se `cotacao_enviada_em` ja esta setado -- o preco apareceu em algum turno (ADR 0022).
    Guard da transicao para Aguardando_confirmacao (ver CotacaoAusente)."""
    res = await conn.execute(
        "SELECT cotacao_enviada_em IS NOT NULL AS ok FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    row = await res.fetchone()
    return bool(row and row["ok"])


async def marcar_cotacao_enviada(conn: AsyncConnection[Any], atendimento_id: UUID) -> bool:
    """Marca `cotacao_enviada_em=now()` com guard IS NULL (first-write-wins, ADR 0022).

    Ancora do reengajamento proativo: registra o instante em que a IA apresentou o preco pela
    primeira vez. Sem transicao de estado nem pausa de IA — so o marcador. Devolve False (no-op
    silencioso) se ja estava setado, preservando o primeiro carimbo (turnos seguintes nao
    re-carimbam, mesmo que a IA reenvie o flag).
    """
    result = await conn.execute(
        """
        UPDATE barravips.atendimentos
           SET cotacao_enviada_em = now()
         WHERE id = %s AND cotacao_enviada_em IS NULL
        """,
        (atendimento_id,),
    )
    return result.rowcount > 0


# Backstop deterministico do ADR 0022: carimba `cotacao_enviada_em` quando o texto que a IA enviou
# tem cara de cotacao, cobrindo o LLM que esquece de marcar `cotacao_apresentada`. Dois caminhos:
#  - "R$" seguido de digito ("a hora fica R$800 amor") -- inequivoco.
#  - numero seco (o formato REAL da persona, que fala o valor puro e ate strippa o cifrao do Pix):
#    "600 1h no meu local", "250 30minutos", "2h 900 + uber". Aqui exige-se um VALOR de 3-4
#    digitos JUNTO de um marcador de duracao/local -- os DOIS -- pra nao casar numero de endereco
#    ("rua ... 880", sem duracao/"no meu local"). Carimbar a toa satisfaria o guard de
#    CotacaoAusente e dispararia reengajamento sem cotacao real. Caminhos canned/reengajamento
#    passam por aqui sem preco no texto, entao nao disparam falso carimbo.
_RE_PRECO_RS = re.compile(r"R\$\s?\d")
_RE_PRECO_VALOR = re.compile(r"\b\d{3,4}\b")
_RE_PRECO_CONTEXTO = re.compile(
    r"\b\d{1,2}\s?h\b|\b\d{1,2}\s?min|\bpernoite\b|no\s+(?:meu|seu)\s+local", re.I
)


def texto_tem_cotacao(texto: str) -> bool:
    """True se o texto enviado tem cara de cotacao (R$+digito, ou valor 3-4 dig. + duracao/local).

    Regra pura do backstop acima. Publica porque o harness e2e (`evals/`) reaplica EXATAMENTE esta
    regra: o worker de envio nao roda la, e uma segunda copia do regex divergiria com o tempo.
    """
    if _RE_PRECO_RS.search(texto):
        return True
    return bool(_RE_PRECO_VALOR.search(texto) and _RE_PRECO_CONTEXTO.search(texto))


async def carimbar_cotacao_por_texto_enviado(
    conn: AsyncConnection[Any], atendimento_id: UUID, texto: str
) -> bool:
    """Aplica o backstop do ADR 0022 sobre UMA bolha que a IA enviou: decide pelo texto e carimba.

    Ponto unico do par (decidir, carimbar) — chamado pelo worker de envio em prod e pelo caminho de
    persistencia do harness e2e. Idempotente (o UPDATE tem guard IS NULL + gate de estado), entao
    repetir entre chunks/retries e no-op. Devolve True so quando ESTE texto criou o carimbo.
    """
    if not texto_tem_cotacao(texto):
        return False
    return await marcar_cotacao_enviada_por_texto(conn, atendimento_id)


async def marcar_cotacao_enviada_por_texto(
    conn: AsyncConnection[Any], atendimento_id: UUID
) -> bool:
    """Carimba `cotacao_enviada_em=now()` quando a IA de fato enviou um texto COM preco.

    Rede deterministica do ADR 0022: complementa o flag `cotacao_apresentada` da extracao, que
    depende do LLM lembrar de marca-lo (e nao marca quando lista a tabela inteira e trata como
    "aguardando escolha do programa"). Alem do guard IS NULL (first-write-wins), exige estado
    `Triagem`/`Qualificado`: so a cotacao da fase de venda ancora o reengajamento; um `R$` que
    aparece depois (ex.: reconfirmar valor em Aguardando_confirmacao) nao cria ancora espuria.
    """
    result = await conn.execute(
        """
        UPDATE barravips.atendimentos
           SET cotacao_enviada_em = now()
         WHERE id = %s AND cotacao_enviada_em IS NULL
           AND estado IN ('Triagem', 'Qualificado')
        """,
        (atendimento_id,),
    )
    return result.rowcount > 0


# --- Flags de disciplina conversacional (padrão A2), carimbadas no write-time ------------------
# Writers PUROS (sem regex): quem decide SE carimbar é workers/envio.py, com os detectores de
# agente/_disciplina.py — dominio/ não importa barra.agente (dominio/CLAUDE.md). Materializam em
# barravips.atendimentos o que prepare_context antes derivava relendo TODAS as falas da IA do
# atendimento (LIMIT 500) e reaplicando regex a cada turno.


async def incrementar_contrapropostas(conn: AsyncConnection[Any], atendimento_id: UUID) -> None:
    """+1 no contador de contrapropostas de desconto (ADR-0031: até 2 por atendimento).

    Chamado só quando o INSERT da bolha em `mensagens` de fato inseriu (RETURNING no ON CONFLICT
    DO NOTHING, workers/envio.py) — assim um retry de envio não dobra o contador. Uma bolha ≈ uma
    oferta (o chunker não parte nem repete a frase canônica dentro do turno)."""
    await conn.execute(
        """
        UPDATE barravips.atendimentos
           SET n_contrapropostas = n_contrapropostas + 1
         WHERE id = %s
        """,
        (atendimento_id,),
    )


async def incrementar_perguntas_de_horario(
    conn: AsyncConnection[Any], atendimento_id: UUID
) -> None:
    """+1 no contador de perguntas de horário SEM proposta ("Seria que horas ?").

    Mesmo contrato de idempotência do contador de contrapropostas: só é chamado quando o INSERT da
    bolha em `mensagens` de fato inseriu (RETURNING no ON CONFLICT DO NOTHING, workers/envio.py),
    então o retry do envio não dobra a contagem. Contador, e não timestamp, porque a conduta tem
    dois degraus (<ja_perguntou_o_horario>: propor na 1ª, não perguntar mais da 2ª em diante)."""
    await conn.execute(
        """
        UPDATE barravips.atendimentos
           SET n_perguntas_de_horario = n_perguntas_de_horario + 1
         WHERE id = %s
        """,
        (atendimento_id,),
    )


async def marcar_dia_sondado(conn: AsyncConnection[Any], atendimento_id: UUID) -> None:
    """Carimba `dia_sondado_em=now()` na 1ª sondagem do dia ("seria hoje?"). Guard IS NULL
    (first-write-wins): repetir entre bolhas/retries é no-op, preserva o 1º instante."""
    await conn.execute(
        """
        UPDATE barravips.atendimentos
           SET dia_sondado_em = now()
         WHERE id = %s AND dia_sondado_em IS NULL
        """,
        (atendimento_id,),
    )


async def marcar_endereco_enviado(conn: AsyncConnection[Any], atendimento_id: UUID) -> None:
    """Carimba `endereco_enviado_em=now()` na 1a bolha em que a IA passa o ponto de encontro.
    Guard IS NULL (first-write-wins): repetir entre bolhas/retries e no-op, preserva o 1o instante."""
    await conn.execute(
        """
        UPDATE barravips.atendimentos
           SET endereco_enviado_em = now()
         WHERE id = %s AND endereco_enviado_em IS NULL
        """,
        (atendimento_id,),
    )


async def marcar_amiga_ofertada(conn: AsyncConnection[Any], atendimento_id: UUID) -> None:
    """Carimba `amiga_ofertada_em=now()` na 1a oferta da amiga (<menage>: uma vez por negociacao).
    Guard IS NULL (first-write-wins): repetir entre bolhas/retries e no-op, preserva o 1o instante."""
    await conn.execute(
        """
        UPDATE barravips.atendimentos
           SET amiga_ofertada_em = now()
         WHERE id = %s AND amiga_ofertada_em IS NULL
        """,
        (atendimento_id,),
    )


async def marcar_foto_portaria_pedida(conn: AsyncConnection[Any], atendimento_id: UUID) -> None:
    """Carimba `foto_portaria_pedida_em=now()` no 1o pedido do print da chegada ("Quando chegar me
    manda uma foto da portaria amor"). Guard IS NULL (first-write-wins): repetir entre bolhas/
    retries e no-op, preserva o 1o instante."""
    await conn.execute(
        """
        UPDATE barravips.atendimentos
           SET foto_portaria_pedida_em = now()
         WHERE id = %s AND foto_portaria_pedida_em IS NULL
        """,
        (atendimento_id,),
    )


async def marcar_motivo_resgate_perguntado(
    conn: AsyncConnection[Any], atendimento_id: UUID
) -> None:
    """Carimba `motivo_resgate_perguntado_em=now()` na 1ª pergunta do motivo da despedida ("Poxa,
    não gostou de mim ?" — o resgate do <desconto>, que é uma vez por negociação). Guard IS NULL
    (first-write-wins): repetir entre bolhas/retries é no-op, preserva o 1º instante."""
    await conn.execute(
        """
        UPDATE barravips.atendimentos
           SET motivo_resgate_perguntado_em = now()
         WHERE id = %s AND motivo_resgate_perguntado_em IS NULL
        """,
        (atendimento_id,),
    )


async def marcar_book_enviado(conn: AsyncConnection[Any], atendimento_id: UUID) -> None:
    """Carimba `book_enviado_em=now()` no 1º envio de mídia (book) da negociação. Guard IS NULL
    (first-write-wins): o guard já torna idempotente sem checar rowcount do INSERT."""
    await conn.execute(
        """
        UPDATE barravips.atendimentos
           SET book_enviado_em = now()
         WHERE id = %s AND book_enviado_em IS NULL
        """,
        (atendimento_id,),
    )
