"""Orquestracao do ciclo de vida de um atendimento aberto por par (cliente, modelo)."""

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, Literal, cast
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.errors import ExclusionViolation

from barra.core.errors import ConflitoEstado
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
    "cliente_busca",
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
    # "drift" (diferenca <= tolerancia) NAO e pedido do cliente: a extração re-deriva horario
    # relativo ("daqui 1h") do `agora` de cada turno — descarta horario/data e segue o upsert.
    veredito_reagendamento = await _reagendamento_pos_bloqueio(conn, aid, payload)
    if veredito_reagendamento == "mudanca":
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
            "mensagem": "Valor abaixo do piso de desconto: escalado para a modelo, valor nao gravado.",
            "novo_estado": None,
        }

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
            "mensagem": "Tipo de atendimento que a modelo nao realiza: escalado, tipo nao gravado.",
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
            atendimento = await _refetch_para_bloqueio(conn, aid)
            # Interno, externo-pickup (cliente_busca, ADR 0020) e remoto (video chamada, ADR 0021)
            # criam o bloqueio previo aqui. O externo-Uber tambem promove agora, mas seu bloqueio
            # previo + Pix saem do bloco deterministico abaixo (_solicitar_pix_deslocamento_se_
            # aplicavel) — por isso nao casa esta condicao. O pin de endereco e so do interno (no
            # pickup o ponto de encontro vai por texto; remoto nao tem endereco algum).
            if (
                atendimento["tipo_atendimento"] in ("interno", "remoto")
                or atendimento["cliente_busca"]
            ):
                from barra.dominio.agenda.service import criar_bloqueio_previo

                await criar_bloqueio_previo(conn, atendimento=atendimento)
                if atendimento["tipo_atendimento"] == "interno":
                    resultado_extra["enviar_pin"] = True

    # 2b. Pix de deslocamento deterministico (externo-Uber): bloco independente da transicao deste
    #     turno — cobre a promocao direta E o pickup->Uber corrigido (ver docstring do helper).
    await _solicitar_pix_deslocamento_se_aplicavel(conn, aid, resultado_extra)

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


def _montar_upsert(payload: dict[str, Any], limpar: set[str]) -> tuple[list[str], list[Any]]:
    """Monta os pares SET do UPSERT. `limpar` forca NULL e vence o payload; demais campos so
    entram quando nao-nulos (COALESCE incremental). Os nomes vem de `_CAMPOS_UPSERT` (constante,
    nunca input do cliente) — f-string de coluna segue o padrao de dominio/agenda/routes.py."""
    sets: list[str] = []
    valores: list[Any] = []
    for campo in _CAMPOS_UPSERT:
        if campo in limpar:
            # `cliente_busca` e a unica coluna NOT NULL do upsert (default false): retratacao
            # via `limpar` volta ao default em vez de NULL (NotNullViolation derrubaria o turno).
            sets.append(f"{campo} = false" if campo == "cliente_busca" else f"{campo} = NULL")
        elif payload.get(campo) is not None:
            sets.append(f"{campo} = %s")
            valores.append(payload[campo])
    sinais = _sinais_qualificacao_derivados(payload, limpar)
    if sinais:
        sets.append("sinais_qualificacao = sinais_qualificacao || %s::jsonb")
        valores.append(json.dumps(sinais))
    return sets, valores


def _sinais_qualificacao_derivados(payload: dict[str, Any], limpar: set[str]) -> dict[str, Any]:
    """Sinais de qualificacao a mergear no JSONB (`||`). Parte do que o LLM passou e DERIVA
    deterministicamente os dois sinais redundantes com campo estruturado — `valor_acordado` =>
    `aceita_valor`, `horario_desejado` => `informa_horario` — que o LLM as vezes esquece de marcar
    (defasagem do diagnostico E2E #5, 2026-06-09). O campo estruturado e a fonte confiavel (o
    abaixo-do-piso nem grava `valor_acordado`; a docstring de `horario_desejado` so manda preencher
    com hora concreta); o boolean apenas o espelha. Nao deriva ao `limpar` o campo (cliente recuou)
    e o merge `||` so adiciona True — nunca rebaixa um sinal ja gravado."""
    sinais = dict(payload.get("sinais_qualificacao") or {})
    if "valor_acordado" not in limpar and payload.get("valor_acordado") is not None:
        sinais["aceita_valor"] = True
    if "horario_desejado" not in limpar and payload.get("horario_desejado") is not None:
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
# TODO tipo com horario combinado promove a Aguardando_confirmacao (cliente_busca NAO e condicao
# — a reserva/Pix do externo-Uber sai do bloco de Pix, nao daqui).
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
                "se você vai até ele, ele vem até você ou é vídeo chamada",
            ),
        ],
    ),
    "Qualificado": (
        "Aguardando_confirmacao",
        [
            (lambda *, horario_desejado, **_: horario_desejado is not None, "que horas ele quer"),
            (
                lambda *, tipo_atendimento, **_: tipo_atendimento is not None,
                "se você vai até ele, ele vem até você ou é vídeo chamada",
            ),
        ],
    ),
}

# Frase-guia de conduta por estado (o "para onde ir"); os itens concretos que faltam vao em
# `slots_faltantes`. Estados sem transicao automatica (Aguardando_confirmacao+) recebem so a
# frase informativa do que se espera ali.
_PROXIMO_PASSO: dict[str, str] = {
    "Novo": "entender o que ele procura e puxar pro encontro",
    "Triagem": "fechar o que falta pra combinar o encontro",
    "Qualificado": "confirmar os detalhes e seguir pro próximo passo do encontro",
    "Aguardando_confirmacao": "conduzir a confirmação (pix, foto de portaria ou o horário combinado)",
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
) -> BeliefState:
    """Belief-state do turno: o que falta pra avancar + a frase-guia, das MESMAS pre-condicoes da
    FSM (fonte unica com `_proxima_transicao`). Reinjetado no contexto dinamico a cada turno para
    cortar a re-pergunta multi-turn. `estado=None` (gate/webhook fino) -> belief neutro."""
    alvo, faltantes = _avaliar_precondicoes(
        estado=estado,
        intencao=intencao,
        tipo_atendimento=tipo_atendimento,
        horario_desejado=horario_desejado,
    )
    return BeliefState(
        proxima_transicao=alvo,
        slots_faltantes=faltantes,
        proximo_passo=_PROXIMO_PASSO.get(estado or "", "conduzir o atendimento"),
    )


async def _decidir_transicao(conn: AsyncConnection[Any], atendimento_id: UUID) -> str | None:
    """Transicoes da extracao (02 §11 — fonte unica do lado do agente). Le o estado JA atualizado
    pelo UPSERT e delega a `_proxima_transicao` (mesma tabela que alimenta o belief-state). TODO
    tipo com horario combinado promove a Aguardando_confirmacao: interno (Foto de portaria),
    externo-pickup (ADR 0020), remoto (video chamada, ADR 0021) e externo-Uber. A reserva de slot +
    Pix do externo-Uber sai do bloco deterministico de Pix, nao aqui."""
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
    if novo_horario is None and nova_data is None:
        return None
    res = await conn.execute(
        "SELECT estado::text AS estado, bloqueio_id, horario_desejado, data_desejada "
        "FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    if a is None or a["estado"] != "Aguardando_confirmacao" or a["bloqueio_id"] is None:
        return None
    if not (_difere(a["horario_desejado"], novo_horario) or _difere(a["data_desejada"], nova_data)):
        return None
    if _dentro_da_tolerancia(a["data_desejada"], a["horario_desejado"], nova_data, novo_horario):
        return "drift"
    return "mudanca"


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


async def _solicitar_pix_deslocamento_se_aplicavel(
    conn: AsyncConnection[Any], atendimento_id: UUID, resultado_extra: dict[str, Any]
) -> None:
    """Solicitacao deterministica do Pix de deslocamento (substitui a tool `pedir_pix_deslocamento`).

    Externo-Uber (externo sem cliente_busca) pede o Pix assim que esta em Aguardando_confirmacao
    com pix_status ainda 'nao_solicitado'. Roda como bloco INDEPENDENTE da transicao deste turno
    (nao aninhado no `if novo_estado`): cobre tanto (a) a promocao direta — a transicao acabou de
    levar a Aguardando_confirmacao — quanto (b) o pickup->Uber corrigido — cliente_busca vira false
    num atendimento JA em Aguardando_confirmacao, sem nova transicao. Paridade com a tool antiga,
    cujo `WHERE pix_status='nao_solicitado'` + guard `bloqueio_id is None` davam o mesmo efeito.

    A chave Pix (string critico) NUNCA entra aqui (guard-rail de dado sensivel): so o valor fixo;
    o coordenador anexa a chave fresh do cadastro apos o texto da IA. `ConflitoAgenda`/
    `ForaDisponibilidade` de `criar_bloqueio_previo` propagam — a casca da tool (extracao.py) as
    converte em erro recuperavel e a transacao reverte tudo atomicamente.
    """
    res = await conn.execute(
        "SELECT id, modelo_id, estado::text AS estado, "
        "tipo_atendimento::text AS tipo_atendimento, cliente_busca, "
        "pix_status::text AS pix_status, bloqueio_id, "
        "data_desejada, horario_desejado, duracao_horas "
        "FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    assert a is not None
    if not (
        a["estado"] == "Aguardando_confirmacao"
        and a["tipo_atendimento"] == "externo"
        and not a["cliente_busca"]
        and a["pix_status"] == "nao_solicitado"
    ):
        return
    # Bloqueio previo do externo-Uber: reserva o slot ao solicitar o Pix (simetrico aos demais
    # tipos). Guard `is None` porque o pickup->Uber ja tem bloqueio (criado quando era pickup) —
    # recriar estouraria a EXCLUDE `bloqueios_sem_sobreposicao` com ConflitoAgenda espurio.
    if a["bloqueio_id"] is None:
        from barra.dominio.agenda.service import criar_bloqueio_previo

        await criar_bloqueio_previo(conn, atendimento=a)
    valor = get_settings().pix_deslocamento_valor
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
        "SELECT id, modelo_id, tipo_atendimento::text AS tipo_atendimento, cliente_busca, "
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
