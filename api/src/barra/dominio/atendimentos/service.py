"""Orquestracao do ciclo de vida de um atendimento aberto por par (cliente, modelo)."""

import json
import logging
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Literal, cast
from uuid import UUID
from zoneinfo import ZoneInfo

from psycopg import AsyncConnection
from psycopg.errors import ExclusionViolation

from barra.core.catalogo import e_video_chamada
from barra.core.errors import ConflitoEstado
from barra.core.metrics import AGENTE_EXTRACAO_VALOR_FANTASMA, AGENTE_PISO_PACOTE
from barra.settings import get_settings

logger = logging.getLogger(__name__)

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
    fala_da_ia_no_turno: str | None = None,
) -> dict[str, Any]:
    """UPSERT do snapshot da IA + transicao de estado + bloqueio previo, na transacao do chamador.

    `horario_evidenciado` e o veredito do detector deterministico do TURNO (prepare_context): a
    janela tem fala do cliente que sustenta o horario. Nunca vem do payload — o payload e o canal
    contaminado pelo eco do belief (ver `_marca_horario_evidenciado`). Aqui ele ainda passa por uma
    conferencia que so o consumidor pode fazer: hora que a IA RECUSOU nesta fala nao evidencia
    (`_hora_recusada_pela_ia`, e o comentario do passo 0b).

    `recuo_detectado` e o veredito do OUTRO detector do turno (mesma origem, mesmo motivo): o
    cliente retratou o aceite. Rebaixa `aceita_valor` no merge dos sinais (ver
    `_sinais_qualificacao_do_turno`); nao toca o `valor_acordado`, que segue gravado.

    `fala_da_ia_no_turno` e o texto que a IA acabou de escrever (ainda NAO esta em `mensagens`) —
    entra como fonte (c) da guarda do valor fantasma, junto com o historico persistido. Vem do
    State pela mesma porta dos dois detectores acima, e pelo mesmo motivo: o payload nao sabe o
    que a IA falou no turno.

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
    # "realoca"/"descarta": o horario reservado era PALPITE (nunca evidenciado por ele) — ver
    # `_reagendamento_pos_bloqueio`.
    veredito_reagendamento = await _reagendamento_pos_bloqueio(
        conn, aid, payload, evidenciado_no_turno=horario_evidenciado
    )
    if veredito_reagendamento == "descarta":
        payload = {
            k: v for k, v in payload.items() if k not in ("horario_desejado", "data_desejada")
        }
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

    # Numero pequeno demais para SER um preco: nao e o cliente pedindo barato, e a extracao lendo
    # OUTRA coisa como valor — o caso vivo (12/08, `outro_dia`) foi "seria amanha a noite, umas 21h"
    # virando `valor_acordado=21`. Sem este corte o numero cai na guarda do piso, que escala
    # `fora_de_oferta` e PAUSA a IA: o cliente marcando o encontro recebeu "Deixa eu ver certinho e
    # já te falo" e a conversa morreu ali. Descarte silencioso, como o valor fantasma — nao ha nada
    # para a modelo decidir num numero que ninguem disse como preco.
    #
    # O corte e mais BAIXO que o `PRECO_MINIMO_SCAN` (100) do scanner da fala de proposito: aqui o
    # falso positivo custa uma escalada legitima a menos, entao a regua fica onde nenhum programa
    # cabe e toda hora do relogio cabe (0-24). Lowball de verdade ("faz 50?") segue escalando.
    if _registra_valor(payload, limpar) and Decimal(str(payload["valor_acordado"])) < Decimal(
        _VALOR_MINIMO_PLAUSIVEL
    ):
        logger.warning(
            "valor_acordado implausivel descartado no atendimento %s: %s (< %s)",
            aid,
            payload["valor_acordado"],
            _VALOR_MINIMO_PLAUSIVEL,
        )
        AGENTE_EXTRACAO_VALOR_FANTASMA.inc()
        payload = {k: v for k, v in payload.items() if k != "valor_acordado"}

    # Guarda do CARDAPIO de duracao — VEREDITO, calculado UMA vez (a leitura do cardapio e uma
    # query) e aplicado em DOIS pontos. O porque das duas aplicacoes esta no sitio tardio, junto do
    # bloco; aqui fica a parte que precisa acontecer ANTES do gate do piso.
    #
    # A DISJUNCAO que torna isso seguro: as duas guardas que este descarte pode atrapalhar sao
    # mutuamente exclusivas por construcao. O gate do piso (logo abaixo) so roda com
    # `_registra_valor(payload, limpar)` **True**; a guarda do par preco x duracao so roda com ele
    # **False** ("a duracao mudou SEM o valor vir junto" e literalmente a condicao dela). Nunca as
    # duas no mesmo turno. Entao descartar cedo no ramo COM valor nao pode encobrir a guarda do par
    # — ela nao teria rodado de qualquer jeito — e e exatamente o ramo em que o silencio importa:
    # `_abaixo_do_piso` faz `duracao = payload["duracao_horas"] or row[...]`, e uma duracao sem
    # linha vira `sem_linha` -> `piso is None` -> `abaixo=True`, escalando `fora_de_oferta` sobre um
    # valor que era exatamente o piso (o `objetor_a` #6).
    #
    # Caso de borda, nomeado: o valor pode ser descartado DEPOIS deste ponto (pelo proprio piso ou
    # pelo valor fantasma), e ai a guarda do par passaria a caber num turno que entrou com valor.
    # Nao ha perda de sinal — o turno ja volta com o aviso do piso/fantasma, que e corretivo pelo
    # mesmo motivo que o `ParPrecoDuracaoInvalido` e —, e nada foi persistido.
    duracao_off_menu = (
        payload.get("duracao_horas") is not None
        and "duracao_horas" not in limpar
        and await _duracao_fora_do_cardapio(conn, aid, payload["duracao_horas"])
    )
    if duracao_off_menu and _registra_valor(payload, limpar):
        payload = _sem_duracao_off_menu(payload, aid)

    # Guarda do piso de desconto (ADR-0004, defesa-em-profundidade sobre o prompt geral): valor
    # abaixo do piso NUNCA e gravado. O que a INSISTENCIA decide e se ele tambem escala.
    #
    # Ate a r3 escalava sempre, ja na RODADA 0 da escada — e a escalada pausa a IA, o `post_process`
    # zera as AIMessages do turno e a contraproposta que o modelo tinha acabado de escrever morre
    # sem ser jogada (`negociacao_dura_a` t6: a contraproposta CERTA de 300 perdida sobre um pedido
    # de 200). O gate pre-emptava exatamente a jogada que ele deveria vir DEPOIS de esgotar: ADR-0031
    # ("uma terceira insistencia nao gera nova oferta — escala"), o degrau 6 de `regras.md.j2` e o
    # `<escada_disponivel>` do proprio turno poem a escalada no FIM da sequencia.
    #
    # Com a escada intacta o pedido baixo e o PRIMEIRO lance dele, nao insistencia: descarte
    # silencioso (mesmo tratamento do valor fantasma logo abaixo), a escada segue viva e a IA
    # responde com a contraproposta que o contexto ja lhe deu. Insistencia = rodada JOGADA, lida do
    # `n_contrapropostas` (ver `_insistiu_apos_a_escada`).
    if _registra_valor(payload, limpar):
        insistiu = await _insistiu_apos_a_escada(conn, aid)
        if await _abaixo_do_piso(conn, aid, payload, fala_da_ia_no_turno, insistiu=insistiu):
            if insistiu:
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
            logger.info(
                "valor abaixo do piso descartado sem escalar no atendimento %s (escada intacta): %s",
                aid,
                payload["valor_acordado"],
            )
            # O `aceita_valor` do MESMO payload cai junto, pela simetria com `_sem_valor_fantasma`:
            # o sinal foi inferido do mesmo evento ("fecho por 250 as 21h"), e o numero acabou de
            # ser recusado -- ninguem aceitou nada. Deixa-lo vivo alimentava o backstop do pacote
            # fechado (`_preco_cotado_do_pacote_fechado` le `aceita_valor` do turno), que gravaria
            # o preco CHEIO da tabela como venda combinada logo depois de a guarda ter recusado o
            # numero dele. Os outros sinais ficam.
            payload = {k: v for k, v in payload.items() if k != "valor_acordado"}
            sinais_sem_aceite = {
                k: v
                for k, v in (payload.get("sinais_qualificacao") or {}).items()
                if k != "aceita_valor"
            }
            if sinais_sem_aceite:
                payload["sinais_qualificacao"] = sinais_sem_aceite
            else:
                payload.pop("sinais_qualificacao", None)

    # Guarda do VALOR FANTASMA (validacao ao vivo 11/08; o porque inteiro esta em
    # `_valores_ja_ofertados`): valor que a IA nunca ofertou nao e gravado. DEPOIS da guarda do
    # piso de proposito — valor abaixo do piso continua ESCALANDO (ADR-0004: o cliente insistindo
    # num numero baixo merece a modelo decidir), e so o que passa do piso mas nunca saiu da boca
    # dela cai aqui. Descarte, nao escalada: nao ha nada para a modelo decidir, e a instrucao no
    # retorno ensina o caminho certo (ofertar antes de fechar) ja no proximo turno.
    aviso_fantasma = ""
    if _registra_valor(payload, limpar):
        legitimos = await _valores_ja_ofertados(conn, aid, fala_da_ia_no_turno)
        fantasma = (
            _valor_fora_do_conjunto(payload["valor_acordado"], legitimos) if legitimos else None
        )
        if fantasma is not None:
            AGENTE_EXTRACAO_VALOR_FANTASMA.inc()
            # Excecao do TOTAL anunciado: quando o numero descartado e a soma programa + Pix que a
            # PROPRIA IA disse ("500 no total"), o "fechou" do cliente e real — so o numero e que
            # nao pode ser gravado como preco de programa. O aceite fica, o preco de tabela entra
            # pelo backstop do pacote fechado logo abaixo.
            total_anunciado = await _total_anunciado_pela_ia(
                conn, aid, fantasma, fala_da_ia_no_turno
            )
            logger.warning(
                "valor_acordado fantasma descartado no atendimento %s: proposto=%s legitimos=%s "
                "total_anunciado=%s",
                aid,
                fantasma,
                sorted(legitimos),
                total_anunciado,
            )
            payload = _sem_valor_fantasma(
                payload, fantasma, legitimos, preservar_aceite=total_anunciado
            )
            aviso_fantasma = " " + (
                _AVISO_TOTAL_NAO_E_PRECO if total_anunciado else _AVISO_VALOR_FANTASMA
            ).format(fantasma=fantasma)

    # Fechamento SEM preco (medido ao vivo 12/08: 6 de 35 conversas): a extracao marca o aceite e
    # grava a duracao, mas deixa `valor_acordado` NULL — o encontro chega ao painel marcado, com
    # hora e pacote, e sem ninguem saber quanto custa. O preco nao e inventado aqui: e o da TABELA
    # para a duracao fechada, e so vale se a IA de fato o COTOU nesta conversa (mesma fonte da
    # guarda do valor fantasma logo acima). Sem negociacao no meio (`n_contrapropostas == 0`) nao
    # ha ambiguidade possivel entre o preco cheio e um degrau ofertado — com ela, nao se preenche:
    # quem decide qual numero ficou de pe e a conversa, nao um default.
    if not _registra_valor(payload, limpar) and "valor_acordado" not in limpar:
        preenchido = await _preco_cotado_do_pacote_fechado(conn, aid, payload, fala_da_ia_no_turno)
        if preenchido is not None:
            payload = {**payload, "valor_acordado": preenchido}

    # Fechamento SEM preco (medido ao vivo 12/08: 6 de 35 conversas): a extracao marca o aceite e
    # grava a duracao, mas deixa `valor_acordado` NULL — o encontro chega ao painel marcado, com
    # hora e pacote, e sem ninguem saber quanto custa. O preco nao e inventado aqui: e o da TABELA
    # para a duracao fechada, e so vale se a IA de fato o COTOU nesta conversa (mesma fonte da
    # guarda do valor fantasma logo acima). Sem negociacao no meio (`n_contrapropostas == 0`) nao
    # ha ambiguidade possivel entre o preco cheio e um degrau ofertado — com ela, nao se preenche:
    # quem decide qual numero ficou de pe e a conversa, nao um default.
    if not _registra_valor(payload, limpar) and "valor_acordado" not in limpar:
        preenchido = await _preco_cotado_do_pacote_fechado(conn, aid, payload, fala_da_ia_no_turno)
        if preenchido is not None:
            payload = {**payload, "valor_acordado": preenchido}

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
        and await _par_persistido_abaixo_do_piso(conn, aid, payload, fala_da_ia_no_turno)
    ):
        # Antes de reverter: o upgrade de pacote em que a IA JA re-cotou na fala do turno ("2h fica
        # 700") e o par so nao chega junto porque a extracao registra a duracao e esquece o valor.
        # Medido ao vivo 12/08 (roteiro sobe_o_pacote, 4 de 5): a guarda revertia o turno, a
        # auto-reoferta batia no mesmo erro e o cliente que estava DOBRANDO o ticket recebia
        # silencio. O numero nao e escolhido aqui: precisa ser a unica linha da tabela para a
        # duracao nova E ter saido da boca da IA nesta conversa (mesma fonte do valor fantasma).
        recotado = await _preco_de_tabela_ja_cotado(conn, aid, payload, fala_da_ia_no_turno)
        if recotado is None:
            raise ParPrecoDuracaoInvalido
        logger.info(
            "par preco x duracao recotado pela tabela no atendimento %s: duracao=%s valor=%s",
            aid,
            payload["duracao_horas"],
            recotado,
        )
        payload = {**payload, "valor_acordado": recotado}

    # Guarda do CARDAPIO de duracao (loop-massa r3, achado 2 da refutacao de extracao): duracao sem
    # linha na tabela DESTA modelo nao entra no snapshot. O caso vivo foi `objetor_a t2` — o cliente
    # PERGUNTOU 30 min, a IA RECUSOU, e a extracao gravou `duracao_horas=0.5` mesmo assim. Dai em
    # diante todo consumidor procura um pacote que nao existe: `_abaixo_do_piso` faz
    # `duracao = payload["duracao_horas"] or row[...]` -> `_piso_do_pacote` -> `_linhas_da_duracao`
    # vazio -> `(None, "sem_linha")` -> `abaixo = piso is None or ...` **True por `piso is None`**,
    # e um 300 que era exatamente o piso vira escalada `fora_de_oferta`. A `contraproposta_da_escada`
    # cala pelo mesmo motivo, essa em silencio (sem metrica nem tag).
    #
    # O defeito NAO e "0.5 e invalido" — meia hora e pacote legitimo (Catarina, `preco_minimo=250`,
    # pinado em `test_piso_absoluto_da_linha_vence_o_percentual`). E "duracao sem linha na tabela
    # DESTA modelo". Por isso o descarte le o cardapio dela, e nao uma lista fixa.
    #
    # Descarte SILENCIOSO (log, sem escalada): nao ha o que a modelo decidir sobre um pacote que ela
    # nao vende, e quem recusa a duracao para o cliente e a conduta closed-world do prompt. O valor
    # do turno segue seu caminho e passa a ser julgado contra a duracao PERSISTIDA, que e a que a
    # cotacao de verdade usou.
    #
    # ORDEM (adjudicada na finalizacao da r3): no ramo SEM valor no payload, este descarte roda
    # DEPOIS da guarda do par preco x duracao logo acima. Ele nasceu no topo da funcao e engolia a
    # duracao nova ANTES de o par ser conferido — a IA esticava 1h -> 3h sem re-cotar, o `3` sumia
    # em silencio e o `ParPrecoDuracaoInvalido` (erro RECUPERAVEL, que faz a IA re-cotar no MESMO
    # turno) nunca era levantado. O descarte existe para impedir que duracao off-menu FLIPE
    # cotacao/estado, nao para suprimir correcao: silenciar a duracao antes da guarda deixava a IA
    # seguir com pauta velha sem saber que o cliente mudou de pacote — a familia de "duracao e a
    # chave da escada". Com a guarda primeiro, par invalido levanta o erro recuperavel e NADA
    # persiste (o objetivo do descarte e atingido por outra via); passando a guarda, o off-menu cai
    # aqui como sempre.
    #
    # No ramo COM valor o descarte ja aconteceu la em cima, antes do gate do piso — ver o veredito
    # `duracao_off_menu` e a DISJUNCAO documentada la. Este `if` e o segundo ponto de aplicacao do
    # MESMO veredito, nao uma segunda leitura do cardapio: `"duracao_horas" in payload` e o que
    # impede o descarte de rodar duas vezes.
    if duracao_off_menu and "duracao_horas" in payload:
        payload = _sem_duracao_off_menu(payload, aid)

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

    # 0b. Hora RECUSADA nao evidencia (loop-massa r3, eixo retomada_pos_silencio t6). O detector de
    #     janela prova que a hora saiu da BOCA DELE — e so isso. No t6 o cliente pediu 9h, a IA
    #     respondeu "Poxa amor, 9h nao consigo / Pode ser as 10h ?" e o sistema carimbou evidencia,
    #     promoveu o atendimento, reservou o slot as 09:00 e abriu o gate estrutural do numero do
    #     endereco (ADR-0026) um turno cedo. O sinal media "ele pronunciou uma hora", nao "existe
    #     horario combinado".
    #
    #     Mora AQUI, no consumidor, e nao na DESC do produtor: a DESC do `horario_desejado` manda
    #     anotar a hora COMO ELA FOI DITA ("aqui voce anota o que foi dito, nao julga") e isso e
    #     desenho — o VALOR continua gravado, e o snapshot segue dizendo o que o cliente pediu. O
    #     que cai e so a MARCA, que e o que a tabela de pre-condicoes consulta para nao reservar
    #     palpite. Tambem nao cabe no detector de janela (`_horario_evidenciado_no_turno`): a
    #     recusa nasce na fala DELA, que so existe DEPOIS de o detector ter rodado.
    #
    #     Escopo deliberado: `_reagendamento_pos_bloqueio` (acima) segue com o veredito CRU do
    #     turno. Rebaixa-lo la trocaria "realoca" por "mudanca" na remarcacao segura (decisao do
    #     operador, 12/08) — escalada e IA pausada no turno do fechamento, o modo de falha que
    #     matou 5 de 5 conversas do roteiro `remarcou`. Quem recusa hora fora da agenda dela na
    #     realocacao continua sendo `realocar_bloqueio_previo` (ForaDisponibilidade, recuperavel).
    if horario_evidenciado and _hora_recusada_pela_ia(payload, fala_da_ia_no_turno):
        horario_evidenciado = False

    # 1. UPSERT por COALESCE: so campos nao-nulos sobrescrevem; `limpar` forca NULL e tem
    #    PRECEDENCIA sobre o payload (cliente recuou). `sinais_qualificacao` faz merge jsonb.
    sets, valores = _montar_upsert(payload, limpar, recuo_detectado=recuo_detectado)
    _marca_horario_evidenciado(sets, valores, payload, limpar, horario_evidenciado)
    if not sets:
        return {
            "mensagem": "Nenhum campo novo para registrar." + aviso_fantasma,
            "novo_estado": None,
        }
    valores.append(aid)
    await conn.execute(
        f"UPDATE barravips.atendimentos SET {', '.join(sets)}, "
        "fonte_decisao_ultima_transicao = 'extracao_ia' WHERE id = %s",
        valores,
    )

    # 1b. Promocao da intencao por EVIDENCIA, ANTES da FSM ler a linha.
    await _promover_intencao_por_evidencia(conn, aid, limpar)

    # 1c. Realocacao da reserva feita sobre PALPITE (ver `_reagendamento_pos_bloqueio`): o estado ja
    #     e Aguardando_confirmacao, entao a FSM abaixo nao tem hop nenhum e nao criaria o bloqueio —
    #     a reserva precisa ser movida aqui, com o snapshot ja gravado (a hora dele).
    if veredito_reagendamento == "realoca":
        from barra.dominio.agenda.service import realocar_bloqueio_previo

        await realocar_bloqueio_previo(
            conn, atendimento=await _refetch_para_bloqueio(conn, aid), agora=agora
        )

    # 1d. Remarcacao ABERTA (ver `_reagendamento_pos_bloqueio`): ele desmarcou sem dizer quando
    #     remarca, o `limpar` acabou de zerar horario/data no snapshot e a reserva ficaria ORFA —
    #     um encontro que ninguem tem travando a agenda da modelo. Solta a reserva aqui, com o
    #     snapshot ja vazio, e REGRIDE o estado: `Aguardando_confirmacao` significa horario
    #     combinado, e nao ha mais nenhum. A regressao nao e cosmetica — e o que reabre o hop da
    #     FSM: sem ela o atendimento fica num estado sem transicao automatica e a hora que ele
    #     cravar no proximo turno seria gravada SEM reserva nova (encontro marcado, slot livre pra
    #     outra conversa). De `Qualificado` o caminho de sempre reserva de novo.
    #
    #     Regressao de estado e excecao no projeto (a FSM da extracao so avanca e o painel proibe
    #     regredir por `validar_transicao_painel`): ela vale aqui porque a pre-condicao que
    #     PROMOVEU o atendimento — a hora combinada — acabou de ser desfeita pelo proprio cliente.
    #     O evento fica no audit log com o motivo.
    libera_reserva = veredito_reagendamento == "libera"
    if libera_reserva:
        from barra.dominio.agenda.service import liberar_bloqueio_previo

        await liberar_bloqueio_previo(conn, atendimento_id=aid)
        await conn.execute(
            "UPDATE barravips.atendimentos SET estado = 'Qualificado', "
            "fonte_decisao_ultima_transicao = 'extracao_ia' "
            "WHERE id = %s AND estado = 'Aguardando_confirmacao'",
            (aid,),
        )
        await _registrar_evento(
            conn, aid, "transicao_estado", {"para": "Qualificado", "motivo": "remarcacao_aberta"}
        )

    # 2. Transicao de estado (02 §11) + side-effects deterministicos. MULTI-HOP: itera ate o
    #    ponto-fixo, aplicando cada hop + seu side-effect. Quando intencao+tipo+horario chegam no
    #    mesmo turno, Triagem->Qualificado->Aguardando_confirmacao ocorrem juntos e o bloqueio
    #    previo nasce no proprio turno do horario (sem a janela de um turno do single-hop). Termina
    #    sempre: cada hop avanca o estado e Aguardando_confirmacao+ nao tem transicao automatica.
    resultado_extra: dict[str, Any] = {}
    # A soltura da reserva JA e uma transicao com efeito irreversivel neste turno: publica-la em
    # `novo_estado` e o que marca o turno como CRITICO no coordenador (`_SQL_TURNO_CRITICO`) — um
    # turno que liberou slot nao pode ser cancelado nem perdido. Um hop abaixo sobrescreve.
    novo_estado: str | None = "Qualificado" if libera_reserva else None
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

    # 2a-bis. Fechamento sem preco, SEGUNDO tempo: quando a promocao para Aguardando_confirmacao
    #     acontece NESTE turno, o backstop do bloco 1 rodou cedo demais — o estado ainda era
    #     Triagem e o extrator nao marcou `aceita_valor` no turno do "isso, fechado" (medido ao
    #     vivo 12/08, roteiro outro_dia). Reavaliar depois do hop e a unica chance: o proximo
    #     turno ja nao registra nada e o encontro fica marcado sem preco no painel. Mesmo criterio
    #     de sempre (tabela com UMA linha para a duracao fechada, preco cotado pela IA, sem
    #     contraproposta no meio) — o UPDATE tem guard IS NULL, entao nunca sobrescreve numero
    #     combinado.
    if novo_estado == "Aguardando_confirmacao":
        preenchido = await _preco_cotado_do_pacote_fechado(conn, aid, payload, fala_da_ia_no_turno)
        if preenchido is not None:
            await conn.execute(
                "UPDATE barravips.atendimentos SET valor_acordado = %s "
                "WHERE id = %s AND valor_acordado IS NULL",
                (preenchido, aid),
            )

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

    # A soltura da reserva viaja no retorno da tool: o ToolMessage fica no historico do grafo e e o
    # que a IA le no turno seguinte, quando ele volta com o dia novo. NAO entra em
    # `MENSAGENS_GUARD_ESCALADA` de proposito — isto e o oposto de uma escalada (nada pausa, nada
    # vira card); a frase diz o ESTADO ("nao esta mais marcado") e a intencao, nunca a fala.
    # `novo_estado` na condicao: se ele desmarcou E ja cravou o dia novo no MESMO turno, a FSM
    # abaixo ja reservou de volta (o hop sobrescreveu "Qualificado") — dizer "nao esta mais
    # marcado" ali seria falso.
    aviso_reserva = (
        " Reserva liberada: o encontro nao esta mais marcado — combine o dia novo com ele."
        if libera_reserva and novo_estado == "Qualificado"
        else ""
    )
    await _registrar_evento(conn, aid, "extracao_registrada", payload)
    return {
        "mensagem": "Extracao registrada." + aviso_reserva + aviso_fantasma,
        "novo_estado": novo_estado,
        **resultado_extra,
    }


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


async def retirar_horario_palpite(
    conn: AsyncConnection[Any], atendimento_id: UUID | str, *, motivo: str
) -> bool:
    """A agenda RECUSOU o horario gravado e ele era PALPITE do sistema: apaga-o do snapshot.

    Nasceu do P0 da prova r3 (`diagnostico_externo_a.md` Q3): o fallback de tempo imediato gravou
    `horario_desejado=21:00` (palpite ancorado no `<horario_minimo>`), o cliente flipou o tipo para
    externo, o piso subiu e a reserva passou a devolver `AntecedenciaInsuficiente`. O texto do erro
    manda a IA NAO registrar a hora que vai ofertar — e obedecer e exatamente o que preserva o
    veneno, porque o UPSERT e incremental por `COALESCE`: campo omitido mantem o valor velho. Seis
    turnos re-tentaram a mesma reserva invalida. Um palpite do sistema que se torna invalido tem de
    MORRER, nao travar a conversa.

    Tres condicoes, todas necessarias:
      - `horario_evidenciado IS NOT TRUE` — so palpite morre. Hora que saiu da BOCA do cliente
        continua gravada (o snapshot tem de dizer o que ele pediu; quem a recusa e a conduta da
        fala, nao um apagamento silencioso);
      - `bloqueio_id IS NULL` — apagar a hora de um atendimento com reserva de pe deixaria o
        bloqueio ORFAO (o mesmo medo que `liberar_bloqueio_previo` resolve na remarcacao aberta);
      - `horario_desejado IS NOT NULL` — senao nao ha o que retirar (no-op idempotente).

    NAO abre transacao: quem chama decide o escopo. No caminho real (a tool de extracao) ela roda
    DEPOIS do rollback da tentativa, numa transacao propria — senao o proprio rollback que o erro
    provoca desfaria a retirada. Devolve True quando de fato apagou.
    """
    aid = UUID(str(atendimento_id))
    res = await conn.execute(
        """
        UPDATE barravips.atendimentos
           SET horario_desejado = NULL,
               horario_evidenciado = false,
               fonte_decisao_ultima_transicao = 'extracao_ia'
         WHERE id = %s
           AND horario_desejado IS NOT NULL
           AND horario_evidenciado IS NOT TRUE
           AND bloqueio_id IS NULL
        RETURNING id
        """,
        (aid,),
    )
    if await res.fetchone() is None:
        return False
    await _registrar_evento(
        conn, aid, "correcao_registro", {"campo": "horario_desejado", "motivo": motivo}
    )
    return True


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
                # Freio da spec extracao-proveniencia-horario (US2: "slot só reservado a partir de
                # horário evidenciado"): horário presente mas NÃO evidenciado é palpite do sistema
                # (a hora que a IA ofertou, o fallback de imediatismo, o eco do belief) — não
                # promove nem reserva. O extrator escrevendo `intencao=agendamento` direto
                # contornava a promoção-por-evidência e o palpite virava reserva + Pix
                # (loop-massa r1, eixo objetor). Ausente o horário, o predicado é neutro (True):
                # o que falta é a hora em si, cobrada pelo predicado acima.
                lambda *, horario_desejado, horario_evidenciado, **_: (
                    horario_desejado is None or bool(horario_evidenciado)
                ),
                "ele confirmar o horário que ficou na mesa",
            ),
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
    # Issue 17: aqui o que falta e a HORA (e ela que promove a Aguardando_confirmacao), e ate ele
    # aceita-la o verbo dela e o de oferta (`<cotacao>`, "o verbo diz a fase"). "confirmar os
    # detalhes" punha justamente o verbo proibido na fase que o proibe, no ponto de recency maxima.
    "Qualificado": "combinar o horário com ele e seguir pro próximo passo do encontro — sua conduta agora é <cotacao> e <fechamento>; se ele sumiu e voltou agora, <retomada_pos_silencio> junto",
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
    horario_evidenciado: bool,
) -> tuple[str | None, list[str]]:
    """Avalia as pre-condicoes do estado UMA vez: devolve (transicao-alvo ou None, rotulos
    faltantes). Avaliacao unica consumida por `_proxima_transicao` (a FSM) e `derivar_belief_state`
    (o belief) — a transicao dispara exatamente quando nao falta nada, entao a consistencia entre
    FSM e belief e estrutural, nao so testada.

    `horario_evidenciado` e kw-only SEM default de proposito: um caller esquecido falha alto em
    vez de reabrir em silencio o caminho do horario-palpite virando reserva (spec proveniencia)."""
    entrada = _PRECONDICOES_TRANSICAO.get(estado or "")
    if entrada is None:
        return None, []
    alvo, predicados = entrada
    valores = {
        "intencao": intencao,
        "tipo_atendimento": tipo_atendimento,
        "horario_desejado": horario_desejado,
        "horario_evidenciado": horario_evidenciado,
    }
    faltantes = [rotulo for pred, rotulo in predicados if not pred(**valores)]
    return (alvo if not faltantes else None), faltantes


def _proxima_transicao(
    *,
    estado: str | None,
    intencao: str | None,
    tipo_atendimento: str | None,
    horario_desejado: Any,
    horario_evidenciado: bool,
) -> str | None:
    """Proximo estado da FSM da extracao, ou None. Substitui os if/elif inline com comportamento
    identico ao historico; fonte unica via `_avaliar_precondicoes`."""
    alvo, _ = _avaliar_precondicoes(
        estado=estado,
        intencao=intencao,
        tipo_atendimento=tipo_atendimento,
        horario_desejado=horario_desejado,
        horario_evidenciado=horario_evidenciado,
    )
    return alvo


def derivar_belief_state(
    *,
    estado: str | None,
    intencao: str | None,
    tipo_atendimento: str | None,
    horario_desejado: Any,
    horario_evidenciado: bool,
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
        horario_evidenciado=horario_evidenciado,
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
        "tipo_atendimento::text AS tipo_atendimento, horario_desejado, horario_evidenciado "
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
        horario_evidenciado=bool(a["horario_evidenciado"]),
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
    conn: AsyncConnection[Any],
    atendimento_id: UUID,
    payload: dict[str, Any],
    *,
    evidenciado_no_turno: bool = False,
) -> Literal["mudanca", "drift", "realoca", "descarta", "libera"] | None:
    """Classifica a tentativa de mudar horario/data de um atendimento que ja esta em
    Aguardando_confirmacao COM bloqueio previo (branch 12). None = payload nao mexe em
    horario/data (ou nao ha bloqueio); "drift" = diferenca dentro da tolerancia (re-derivacao
    do horario relativo a partir do `agora` do turno, nao e pedido do cliente — descartar);
    "mudanca" = reagendamento real -> escalar.

    PROVENIENCIA (12/08, medido ao vivo): reagendamento pressupoe que havia um horario COMBINADO, e
    o que estava reservado nem sempre foi combinado com ninguem. Duas fontes enchem o
    `horario_desejado` sem o cliente dizer hora: o fallback de tempo imediato (grava `horario_minimo`
    quando `urgencia=imediato` chega sem hora) e a hora que a PROPRIA IA ofereceu e ele nao
    respondeu. Nesses casos a marca `horario_evidenciado` fica false — e a primeira hora que ele
    crava ("pode ser 21h hoje") caia aqui como "mudanca": escalada, IA pausada e a venda morrendo
    em "Só um minutinho amor, já te falo" no turno do fechamento (3 de 5 conversas do roteiro de
    escada, 12/08). Com o palpite reservado, entao:

        ele evidenciou a hora nova E a modelo ainda nao foi acionada -> "realoca" (a reserva vai
            para a hora DELE, sem escalar; acionada, vira "mudanca" — remarcacao segura vale
            igual para o palpite);
        so a DATA mudou, sem hora evidenciada -> "realoca" tambem, pelo mesmo criterio (data nao
            tem marca de proveniencia; "melhor amanha" e fala DELE, entao a reserva-palpite
            acompanha o dia dele — descarta-la a deixaria no dia velho, e escalar pausava a IA);
        ninguem evidenciou nada -> "descarta" (a IA trocando o proprio palpite de turno em turno
            nao move a agenda — e nao acorda a modelo por ruido dela).

    REMARCACAO SEGURA (decisao do operador, 12/08): mesmo com a hora antiga COMBINADA por ele,
    ele mudar de ideia enquanto a modelo ainda nao foi acionada e' ajuste de agenda, nao evento que
    mereca acordar ninguem — escalar ali matava 5 de 5 conversas do roteiro `remarcou` ("Só um
    minutinho amor, já te falo") e a hora nova nem era gravada. Realoca quando os TRES valem: a
    hora nova saiu da boca DELE neste turno, o encontro ainda nao foi acionado (sem aviso de saida,
    sem Pix em andamento/validado) e o atendimento nao passou de `Aguardando_confirmacao` (a partir
    de `Confirmado` a modelo ja disse sim; dai muda so com ela). Cabimento na agenda nao e checado
    aqui: quem recusa e' `criar_bloqueio_previo`, com ConflitoAgenda/ForaDisponibilidade — erros
    recuperaveis que fazem a IA reofertar em vez de escalar.

    Palpite so existe ANTES do primeiro sim; depois que ele confirma, `horario_evidenciado` fica
    true — e ai vale a remarcacao segura acima, ou a escalada quando ela nao se aplica.

    REMARCACAO ABERTA ("libera", prova r3 do loop de massa): ele desmarca SEM dizer quando remarca
    ("hoje nao consigo mais linda, marco outro dia"), e o horario sai do snapshot pelo `limpar`.
    Ate a r3 isso curto-circuitava em "mudanca" pelo medo — legitimo — de zerar o snapshot deixando
    o bloqueio ORFAO travando a agenda. Mas escalar tambem nao remarca nada: pausa a IA, e no turno
    seguinte o cliente volta com o dia novo ("me marca amanha 21h") e fala no vazio (eixo
    `remarcacao`, t6->t7). O medo se resolve soltando a reserva JUNTO com o snapshot, nao acordando
    a modelo: "libera" cancela o bloqueio explicitamente (`liberar_bloqueio_previo`) e devolve o
    atendimento a `Qualificado`, de onde a FSM reserva de novo quando ele cravar o dia. Mesmo
    criterio de sempre — com a modelo JA acionada (aviso de saida, Pix andando) a hora do card ja
    organizou o lado dela e o recuo continua sendo evento dela: "mudanca"."""
    novo_horario = payload.get("horario_desejado")
    nova_data = payload.get("data_desejada")
    # `limpar` (recuo do cliente: "nao sei o dia ainda") tambem desfaz o horario combinado — sem
    # isto o snapshot zerava e o bloqueio previo ficava orfao travando a agenda, exatamente o que
    # a branch 12 existe pra impedir. Nao ha valor novo p/ medir drift: cai direto no veredito
    # da remarcacao ABERTA (ver docstring), sem passar pelos ramos de comparacao.
    limpando_horario = bool(
        {"horario_desejado", "data_desejada"} & set(payload.get("limpar") or [])
    )
    if novo_horario is None and nova_data is None and not limpando_horario:
        return None
    res = await conn.execute(
        "SELECT estado::text AS estado, bloqueio_id, horario_desejado, data_desejada, "
        "horario_evidenciado, aviso_saida_em, pix_status::text AS pix_status "
        "FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    if a is None or a["estado"] != "Aguardando_confirmacao" or a["bloqueio_id"] is None:
        return None
    if limpando_horario:
        return "libera" if _modelo_ainda_nao_acionada(a) else "mudanca"
    if not (_difere(a["horario_desejado"], novo_horario) or _difere(a["data_desejada"], nova_data)):
        return None
    if _dentro_da_tolerancia(a["data_desejada"], a["horario_desejado"], nova_data, novo_horario):
        return "drift"
    if not a["horario_evidenciado"]:
        # Reserva-PALPITE. So a hora que ELE cravou neste turno move a reserva — e mesmo assim
        # apenas enquanto a modelo nao foi acionada: com aviso de saida ou Pix andando, a hora do
        # card ja pode ter organizado o lado dela, e mover em silencio dessincroniza os dois.
        if evidenciado_no_turno:
            return "realoca" if _modelo_ainda_nao_acionada(a) else "mudanca"
        # Data nova sem hora evidenciada NAO e ruido da IA por padrao: "melhor amanha" sai da boca
        # do cliente e data nao tem marca de proveniencia — descarta-la deixaria a reserva no dia
        # velho com ele certo de que remarcou. Mas escalar (o comportamento pre-palpite) matava a
        # conversa no fechamento: no eixo `explorador_ambiguo_a` da prova r3 a hora reservada era
        # palpite da IA (21:30 proposto 2x, nunca aceito), ele pediu "amanha da?" e levou
        # "Horario ja reservado: mudanca escalada para a modelo" + pausa. Mover uma reserva que
        # NINGUEM combinou para o dia que ele pediu e ajuste de agenda — o mesmo criterio do ramo
        # de cima decide: modelo ainda nao acionada realoca, acionada escala.
        if _difere(a["data_desejada"], nova_data):
            return "realoca" if _modelo_ainda_nao_acionada(a) else "mudanca"
        return "descarta"
    if evidenciado_no_turno and _modelo_ainda_nao_acionada(a):
        return "realoca"
    return "mudanca"


# Pix em andamento OU resolvido: qualquer um deles significa que o encontro saiu do papel — a
# modelo (ou o Fernando) ja mexeu nele. `nao_solicitado` e `invalido` nao acionaram ninguem.
_PIX_ACIONADO = frozenset({"aguardando", "enviado", "em_revisao", "validado"})


def _modelo_ainda_nao_acionada(atendimento: dict[str, Any]) -> bool:
    """A remarcacao pode ser resolvida pela IA sozinha? (parte da REMARCACAO SEGURA acima)"""
    return (
        atendimento["aviso_saida_em"] is None
        and atendimento["pix_status"] not in _PIX_ACIONADO
        and atendimento["estado"] == "Aguardando_confirmacao"
    )


def tipo_atendimento_congelado(*, bloqueio_id: Any, estado: str | None) -> bool:
    """O `tipo_atendimento` ja esta COMBINADO e nao muda mais por pedido do cliente?

    Reserva previa criada OU `Aguardando_confirmacao` sem ela: o estado ja significa horario
    combinado (o bloqueio e o efeito, nao a definicao). Dai em diante `_flip_de_tipo_pos_crava`
    (abaixo) DESCARTA o tipo novo do payload.

    Publico porque o `prepare_context` consulta o MESMO predicado para decidir se o
    `<horario_minimo>` do prompt pode usar o piso de antecedencia do tipo gravado ou tem de usar o
    conservador (prova r3, `diagnostico_externo_a.md` Q2: o tipo flipou DENTRO do turno e a reserva
    recusou a hora que o proprio prompt tinha liberado). Duas definicoes de "tipo congelado" em
    dois arquivos e como a regua de antecedencia estava — divergem por construcao.

    Recebe os DOIS campos soltos (e nao o row): o chamador tem de escrever
    `atendimento.get("bloqueio_id")` na cara, senao o `test_contrato_select_atendimento` nao ve a
    leitura e a coluna pode sumir do SELECT em silencio (a armadilha que aquele teste fecha).
    """
    return bloqueio_id is not None or estado == "Aguardando_confirmacao"


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

    Descarta em vez de escalar: a IA estava conduzindo certo (recusando), e escalar a pausaria no
    meio da recusa. Mudanca real de tipo com horario cravado e renegociacao — sai pela conduta dela
    (redireciona; na insistencia, `escalar`), nao por um campo de extracao.

    Vale com bloqueio previo OU em `Aguardando_confirmacao` sem ele: o estado ja significa horario
    combinado (o bloqueio e o efeito, nao a definicao)."""
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
    if not tipo_atendimento_congelado(bloqueio_id=a["bloqueio_id"], estado=a["estado"]):
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


def _sem_duracao_off_menu(payload: dict[str, Any], atendimento_id: UUID) -> dict[str, Any]:
    """Payload sem a `duracao_horas` que a modelo nao vende, com o log do descarte.

    Existe porque o descarte tem DOIS pontos de aplicacao em `registrar_extracao_ia` (antes do gate
    do piso, no ramo COM valor; depois da guarda do par, no ramo sem) e o veredito e um so. Duas
    copias do strip + log divergiriam no dia em que uma delas ganhasse metrica ou auditoria."""
    logger.warning(
        "duracao fora do cardapio descartada no atendimento %s: %s",
        atendimento_id,
        payload["duracao_horas"],
    )
    return {k: v for k, v in payload.items() if k != "duracao_horas"}


async def _duracao_fora_do_cardapio(
    conn: AsyncConnection[Any], atendimento_id: UUID, duracao_horas: Any
) -> bool:
    """A duracao nao tem NENHUMA linha na tabela desta modelo — e a modelo TEM tabela.

    Le o cardapio pela `_linhas_da_duracao` (site unico), com `apenas_presenciais=False`: a
    pergunta aqui e "esta duracao existe pra ela?", e a vídeo chamada conta como linha que existe.

    O segundo teste e o que evita transformar CADASTRO INCOMPLETO em bloqueio: sem nenhuma linha
    cadastrada nao ha menu contra o que julgar, e descartar ali travaria toda modelo em cadastro
    pela metade — mesmo principio do "array vazio nao trava" da guarda de tipo."""
    if duracao_horas is None:
        return False
    res = await conn.execute(
        "SELECT modelo_id FROM barravips.atendimentos WHERE id = %s", (atendimento_id,)
    )
    row = await res.fetchone()
    if row is None:
        return False
    if await _linhas_da_duracao(conn, row["modelo_id"], duracao_horas, apenas_presenciais=False):
        return False
    res = await conn.execute(
        "SELECT 1 FROM barravips.modelo_programas WHERE modelo_id = %s LIMIT 1",
        (row["modelo_id"],),
    )
    return await res.fetchone() is not None


async def _insistiu_apos_a_escada(conn: AsyncConnection[Any], atendimento_id: UUID) -> bool:
    """O cliente esta INSISTINDO — a IA ja JOGOU ao menos uma rodada da escada nesta conversa?

    A distincao que faltava ao gate do piso (loop-massa r3, achado 2c). O comentario que justifica
    a ordem piso-antes-de-fantasma invoca "o cliente insistindo num numero baixo merece a modelo
    decidir" — mas nada checava a insistencia, e a escalada disparava na RODADA 0. Em
    `negociacao_dura_a` t6 o modelo tinha gerado a contraproposta CERTA (300, amarrada a hoje) e a
    guarda escalou sobre o pedido de 200: o `post_process` zerou a fala e a unica rodada da escada
    morreu antes de ser jogada.

    Todos os documentos vigentes poem a escalada no FIM da sequencia, nao no comeco: ADR-0031 ("uma
    terceira insistencia nao gera nova oferta — escala"), o degrau 6 de `regras.md.j2` ("depois da
    sua ultima contraproposta … se mesmo com o cartao ele insistir") e o proprio
    `<escada_disponivel>` do turno ("na insistencia, escalada com fora_de_oferta").

    `n_contrapropostas` e o contador certo porque conta rodada **JOGADA**: so
    `workers/envio.py:1203` o incrementa, e so quando a bolha de fato entrou em `mensagens` —
    rodada zerada pelo `post_process`, dropada pelo `output_guard`, barrada pelo guard de saida ou
    perdida num replay que caiu no `ON CONFLICT` NAO andam com ele. Rodada rascunhada nao e
    insistencia de ninguem."""
    res = await conn.execute(
        "SELECT n_contrapropostas FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    row = await res.fetchone()
    return row is not None and int(row["n_contrapropostas"] or 0) >= 1


async def _abaixo_do_piso(
    conn: AsyncConnection[Any],
    atendimento_id: UUID,
    payload: dict[str, Any],
    fala_da_ia_no_turno: str | None = None,
    *,
    insistiu: bool = True,
) -> bool:
    """True quando o `valor_acordado` do payload fura o piso do PACOTE em jogo (=> escala
    `fora_de_oferta`). O piso sai de `_piso_do_pacote` (par programa x duracao); sem piso
    resolvido, escala -- fail-closed.

    `fala_da_ia_no_turno` (a bolha que a IA acabou de escrever, ainda fora de `mensagens`) entra
    porque a deducao do pacote le os precos COTADOS: o `valor_acordado` e gravado JA NA COTACAO,
    entao no caso mais comum a unica cotacao existente e a deste turno.

    `insistiu` NAO muda o veredito -- a pergunta desta funcao e so sobre o NUMERO. Ele entra para o
    ROTULO da metrica: quem escala e o chamador, e com a escada intacta o valor abaixo do piso vira
    descarte silencioso, nao escalada (`_insistiu_apos_a_escada`). Default `True` de proposito: quem
    chama sem dizer nada esta perguntando so pelo numero e recebe o rotulo historico.

    Contabiliza SEMPRE em `AGENTE_PISO_PACOTE`: era justamente esta guarda que decidia em silencio
    (o furo do piso por duracao nao deixava escalada, log nem metrica), entao a origem do piso e o
    veredito viram serie -- e `origem="duracao_ambigua"` e o alarme de cadastro que o painel
    precisa preencher. Tres valores em `resultado` desde a r3: `aceito` (passou do piso),
    `escalado` (furou COM insistencia) e `descartado` (furou na rodada 0 da escada)."""
    valor = Decimal(str(payload["valor_acordado"]))
    res = await conn.execute(
        "SELECT modelo_id, duracao_horas, conversa_id FROM barravips.atendimentos WHERE id = %s",
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
    piso, origem = await _piso_do_pacote(
        conn,
        atendimento_id,
        row["modelo_id"],
        duracao,
        valor=valor,
        conversa_id=row["conversa_id"],
        fala_da_ia_no_turno=fala_da_ia_no_turno,
    )
    abaixo = piso is None or valor < piso
    # Labels POSICIONAIS: o fallback sem `prometheus_client` (core/metrics) so aceita *args.
    if not abaixo:
        resultado = "aceito"
    else:
        resultado = "escalado" if insistiu else "descartado"
    AGENTE_PISO_PACOTE.labels(origem, resultado).inc()
    if abaixo and origem == "duracao_ambigua":
        logger.warning(
            "piso ambiguo no atendimento %s: valor=%s piso mais alto da duracao %s=%s "
            "(nenhum servico vendido registrado)",
            atendimento_id,
            valor,
            duracao,
            piso,
        )
    return abaixo


# De onde saiu o piso que julgou o valor -- label da `AGENTE_PISO_PACOTE` e, antes disso, o
# vocabulario de quanto o sistema sabia do PACOTE na hora de julgar.
OrigemDoPiso = Literal[
    "programa_vendido", "preco_cotado", "duracao_unica", "duracao_ambigua", "sem_linha"
]


async def _piso_do_pacote(
    conn: AsyncConnection[Any],
    atendimento_id: UUID,
    modelo_id: Any,
    duracao_horas: Any,
    *,
    valor: Decimal | None = None,
    conversa_id: Any = None,
    fala_da_ia_no_turno: str | None = None,
) -> tuple[Decimal | None, OrigemDoPiso]:
    """O piso que vale para o pacote em jogo, amarrado ao par PROGRAMA x DURACAO, e de onde ele saiu.

    O piso era o `piso_de_desconto` da linha MAIS BARATA da duracao (ADR-0004 §Decisao item 5,
    escolhido para minimizar falso-positivo de escalada). Com um programa so por duracao as duas
    leituras coincidem; com dois (Normal 400 / Completo 800 na 1h -- o cadastro da Lucia e da
    Tatiane) o piso de QUALQUER pacote de 1h virava o do mais barato, e o Completo de 800 ficava
    vendavel a 300. Duas camadas falhavam abertas juntas: 300 e um valor REAL da tabela, entao o
    conjunto legitimo do output_guard tambem o aceitava -- venda abaixo do piso sem escalada,
    sem log e sem metrica.

    Inverter para o MAIS ALTO fechava esse furo, mas comprava um falso-positivo caro demais: com
    piso ambiguo em 600, fechar o Normal pelo preco CHEIO de 400 escalava `fora_de_oferta`. Nao e
    o caso raro -- e toda venda do pacote mais barato da duracao, o caso comum. Escalada em falso
    a modelo resolve numa mensagem, sim, mas nao uma por venda normal: a modelo para de ler o
    canal de escalada, e ai o furo volta por outra porta.

    O desempate certo estava na conversa: a IA COTA antes de fechar (e so cota valor da tabela --
    `<sobe_o_ticket>`), entao o preco que ela falou identifica o pacote. A escolha do piso, em
    ordem de forca da evidencia:

    1. **Programa VENDIDO** (`atendimento_servicos`, o unico lugar onde a identidade do pacote
       esta gravada -- e so o painel escreve la): piso da linha (modelo x programa x duracao). Sem
       linha para o par, `None` -- o pacote vendido nao existe nessa duracao.
    2. **Duracao com um piso so**: nao ha o que deduzir e a deducao nao poderia mudar o numero --
       curto-circuito antes de ler a conversa (e o cadastro da Catarina, a maioria das vendas:
       nenhuma escalada nova e nenhuma query a mais).
    3. **Preco COTADO** (`_piso_deduzido_do_cotado`): entre os precos que a IA ja falou nesta
       conversa, os que casam com o `preco` de uma linha desta duracao apontam o pacote. Cotou 400
       => Normal => piso 300 (fechar 400 passa, fechar 250 escala); cotou 800 => Completo => piso
       600 (fechar 800 passa, fechar 300 escala -- o furo original, fechado).
    4. **Fallback rigoroso**: deducao ambigua (cotou precos de mais de um pacote) ou nenhum preco
       cotado que case -> o piso MAIS ALTO da duracao, valido para QUALQUER uma das linhas. Aqui o
       fail-closed e barato porque o caso e raro, e e coerente com a cauda: a
       `contraproposta_da_escada` tambem cala na duracao ambigua, entao a IA nunca RECEBEU o
       desconto do pacote barato -- valor abaixo do piso mais alto ali e desconto de cabeca, nao
       oferta que o sistema mandou fazer.

    `None` (sem tabela para o par) sempre escala, como antes.

    Le a duracao INTEIRA (`apenas_presenciais=False`), incluindo a vídeo chamada: aqui a pergunta
    e sobre um atendimento que ja existe e que PODE ser a chamada. Uma chamada de 1h fechada em
    550 (tabela 600, `preco_minimo` 600) tem de escalar; com a linha remota filtrada o piso viria
    do Normal (300) e a venda passaria. A contrapartida -- a duracao fica ambigua quando a modelo
    tem a chamada na mesma duracao -- e o fail-closed de sempre, e os itens 1/3 (servico vendido,
    preco cotado) desfazem a ambiguidade nos casos que importam.
    """
    linhas = await _linhas_da_duracao(conn, modelo_id, duracao_horas, apenas_presenciais=False)
    if not linhas:
        return None, "sem_linha"
    programa_id = await _programa_vendido(conn, atendimento_id)
    if programa_id is not None:
        vendida = [ln for ln in linhas if ln["programa_id"] == programa_id]
        if not vendida:
            return None, "sem_linha"
        return piso_de_desconto(vendida[0]["preco"], vendida[0]["preco_minimo"]), "programa_vendido"
    pisos = [piso_de_desconto(ln["preco"], ln["preco_minimo"]) for ln in linhas]
    if len(set(pisos)) == 1:
        return pisos[0], "duracao_unica"
    cotados = await _precos_cotados_pela_ia(conn, conversa_id, fala_da_ia_no_turno)
    deduzido = _piso_deduzido_do_cotado(linhas, cotados, valor)
    if deduzido is not None:
        return deduzido, "preco_cotado"
    return max(pisos), "duracao_ambigua"


def _piso_deduzido_do_cotado(
    linhas: list[dict[str, Any]], cotados: set[int], valor: Decimal | None
) -> Decimal | None:
    """O piso da linha que os precos COTADOS identificam, ou `None` quando eles nao identificam
    uma (o chamador cai no fallback rigoroso).

    Candidata = linha cujo `preco` de tabela a IA cotou nesta conversa. Casa por INTEIRO, como o
    resto do dominio faz com preco falado (`_valor_fora_do_conjunto`): o scanner da fala so devolve
    inteiro, e centavos nao mudam a identidade do numero na conversa.

    Duas candidatas de mesmo piso nao sao ambiguidade (dois programas de 400 na 1h): o numero e o
    mesmo. Pisos divergentes entre candidatas = a IA cotou os dois pacotes na mesma conversa (o
    cliente perguntou o preco dos dois). Ai a identidade do pacote so volta pelo valor FECHADO: se
    ele e exatamente o `preco` de tabela de uma das candidatas, e essa linha vendida no CHEIO --
    fechamento sem desconto nenhum, que uma guarda de piso de DESCONTO nao tem o que julgar. Fora
    isso, ambiguo de verdade -> `None`.

    O que a deducao NAO cobre, de proposito: preco cotado para OUTRA duracao que por coincidencia
    e o `preco` de uma linha desta (tabelas em que o Normal de 2h custa o mesmo que o Completo de
    1h). Ela erra para o lado permissivo so quando a coincidencia aponta a linha barata; o
    desempate pelo valor cheio cobre o caso simetrico, e o painel gravando o servico vendido
    (item 1) resolve os dois em definitivo."""
    candidatas = [ln for ln in linhas if int(ln["preco"]) in cotados]
    if not candidatas:
        return None
    pisos = {piso_de_desconto(ln["preco"], ln["preco_minimo"]) for ln in candidatas}
    if len(pisos) == 1:
        return pisos.pop()
    no_cheio = {
        piso_de_desconto(ln["preco"], ln["preco_minimo"])
        for ln in candidatas
        if valor is not None and ln["preco"] == valor
    }
    # Mesmo preco de tabela com minimos diferentes: vale o piso mais apertado, como em toda
    # ambiguidade residual desta familia (ver `contraproposta_da_escada`).
    return max(no_cheio) if no_cheio else None


async def _programa_vendido(conn: AsyncConnection[Any], atendimento_id: UUID) -> Any | None:
    """O `programa_id` do pacote vendido, quando o atendimento tem UM servico registrado.

    `atendimento_servicos` e a unica materializacao da identidade do pacote (mesma base que o
    `_base_do_pacote` do extra de fetiche prefere), e so o painel escreve nela -- o fechamento
    conduzido pela IA nao passa por aqui. Mais de um servico = pacote que e a soma de dois: nao ha
    "o programa" a que amarrar o piso, e quem chama cai na regra da duracao.
    """
    res = await conn.execute(
        "SELECT programa_id FROM barravips.atendimento_servicos WHERE atendimento_id = %s",
        (atendimento_id,),
    )
    linhas = await res.fetchall()
    return linhas[0]["programa_id"] if len(linhas) == 1 else None


def _e_remoto(payload: dict[str, Any], tipo_persistido: str | None) -> bool:
    """O atendimento em jogo e REMOTO (vídeo chamada, ADR-0021)? Le o tipo deste TURNO primeiro --
    o pivo para remoto costuma chegar no mesmo payload que fecha o pacote.

    Existe por causa dos dois backstops de preco (`_preco_cotado_do_pacote_fechado` e
    `_preco_de_tabela_ja_cotado`): os dois resolvem a linha pela `_linhas_de_tabela`, que e
    `apenas_presenciais=True` FIXO e por desenho (a docstring de la diz "quem julga uma venda ja
    feita nao passa por aqui"). Num cadastro com Normal 1h 400 e vídeo chamada 1h 150, a leitura
    presencial devolve UMA linha -- a de 400 -- e o backstop gravaria 400 numa chamada de 150; dai
    o `_solicitar_pix_deslocamento_se_aplicavel` cobra o Pix ANTECIPADO da chamada por 400.

    Fail-closed, nao troca de fonte: no remoto o backstop simplesmente nao preenche. Com
    `valor_acordado` NULL o pedido de Pix ja se segura sozinho (o proprio
    `_solicitar_pix_deslocamento_se_aplicavel` volta sem cobrar), e quem grava o valor certo e a
    extracao do turno seguinte. Trocar para `apenas_presenciais=False` seria o contrario: faria a
    duracao com presencial + chamada virar ambigua para TODO mundo, apagando o backstop tambem no
    caso presencial que ele existe para cobrir."""
    return (payload.get("tipo_atendimento") or tipo_persistido) == "remoto"


async def _preco_de_tabela_ja_cotado(
    conn: AsyncConnection[Any],
    atendimento_id: UUID,
    payload: dict[str, Any],
    fala_da_ia_no_turno: str | None,
) -> Decimal | None:
    """O preco a gravar junto da duracao NOVA quando ela sobe sem valor — ou `None` (nao salvar).

    Irmao de `_preco_cotado_do_pacote_fechado`, no outro momento do funil: la o pacote fecha sem
    preco nenhum; aqui o cliente TROCA de pacote e o valor gravado e do pacote antigo. As duas
    condicoes que fazem disto uma leitura, e nao um chute: a tabela tem UMA linha para a duracao
    nova (sem ambiguidade de programa) e esse preco JA SAIU DA BOCA DA IA nesta conversa
    (`_precos_cotados_pela_ia`, incluindo a fala deste turno). Sem os dois, a guarda segue
    revertendo — vender periodo por preco improvisado e o prejuizo que ela existe para impedir.
    """
    res = await conn.execute(
        "SELECT modelo_id, conversa_id, tipo_atendimento::text AS tipo_atendimento "
        "FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    if a is None:
        return None
    if _e_remoto(payload, a["tipo_atendimento"]):
        return None
    precos = {
        preco
        for preco, _ in await _linhas_de_tabela(conn, a["modelo_id"], payload["duracao_horas"])
    }
    if len(precos) != 1:
        return None
    preco = next(iter(precos))
    cotados = await _precos_cotados_pela_ia(conn, a["conversa_id"], fala_da_ia_no_turno)
    if _valor_fora_do_conjunto(preco, cotados) is not None:
        return None
    return Decimal(preco)


async def _par_persistido_abaixo_do_piso(
    conn: AsyncConnection[Any],
    atendimento_id: UUID,
    payload: dict[str, Any],
    fala_da_ia_no_turno: str | None = None,
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
        fala_da_ia_no_turno,
    )


# --- Valor fantasma: o numero que a IA nunca ofertou (validacao ao vivo 11/08, escada_val2) -----
#
# O extrator gravou `valor_acordado=300` (+ `aceita_valor`) no turno em que a IA RECUSOU os 300 do
# cliente ("Poxa amor, nao consigo por 300 nao"): o cliente "aceitou" o numero DELE MESMO. E o
# extrator nao tem como saber da recusa — a janela da extracao exclui por contrato a fala da IA do
# turno corrente (nos/extrair.py). No turno seguinte o belief mostrou "<valor status='aceito por
# ele'>300</valor>" e a IA capitulou ("Isso amor, fechado nos 300"). O piso nao pegou: 300 era
# exatamente o teto de 25% sobre a tabela de 400 (ADR-0031) — oferta valida, so que nunca ofertada.
#
# A `_DESC_VALOR` ja proibia em prosa ("nem um numero que o cliente PROPOS e voce NAO aceitou"). A
# regra vira estrutural: so e `valor_acordado` aceitavel o numero que
#   (a) esta na tabela da modelo (`modelo_programas.preco`/`preco_minimo`), ou
#   (c) JA SAIU DA BOCA DA IA nesta conversa (falas persistidas + a fala DESTE turno).
# Degrau/teto (ADR-0031) NAO entram por si: eles so valem depois de a IA os ter FALADO, o que ja
# cai em (c) — e no caso vivo o proprio teto era o numero fantasma. (a) U (c) basta.
#
# Duas decisoes finas, as duas custaram o bug:
#  - a fala do turno CORRENTE conta (ela vem do State, nao do banco). Sem ela, o fluxo normal
#    quebraria: `valor_acordado` e gravado JA NA COTACAO (ver `_sinais_qualificacao_do_turno`), e o
#    total com extra de fetiche (400 do pacote + 400 do extra = 800, ADR-0030) nao esta na tabela —
#    so na bolha que acabou de ser escrita.
#  - preco dentro de uma clausula NEGADA nao e oferta ("nao consigo por 300 nao"). Sem isso a
#    recusa se legitimaria a si mesma no turno corrente e, pior, ficaria no banco legitimando o
#    mesmo 300 nos turnos seguintes. E a licao do ven_004 pelo avesso: regex cego a negacao pune a
#    resposta certa la, e aqui premiaria a errada. Por clausula (nao por janela de N chars) porque
#    a negacao aparece dos DOIS lados em pt-BR ("nao consigo 300" e "consigo 300 nao").
#
# Fora do conjunto => o campo NAO e gravado (o resto do payload segue), `aceita_valor` do MESMO
# payload cai junto (foi inferido do mesmo evento falso) e a tool devolve o descarte ao LLM.

# Scanner de preco CITADO — mudou de casa (vinha de agente/nos/output_guard.py, que hoje o importa
# daqui): o mesmo criterio que julga a BOLHA na saida julga aqui se o numero saiu da boca da IA.
# ESTREITO de proposito — falso-positivo derruba cotacao boa. So conta o numero em CONTEXTO
# monetario: "R$ 600", "600 reais", a cotacao canonica "600 1h"/"600 30min", a contraproposta
# "consigo 500" e "por/fica/sai 600". Numero solto ("Av. Aquidaba 130"), horario ("18h", "17:30") e
# duracao ("1h") nao casam. Piso de 100: taxa de uber/valores pequenos ficam fora (falso-negativo
# aceito — o guard mira o preco de PROGRAMA).
#
# Ramo de FECHAMENTO (11/08/2026, ADR-0040): quando quem nomeia o numero e o CLIENTE e ela so diz
# sim, a fala natural do aceite ("Fechado 700 amor", "Tabom, 700 entao") nao tem "R$", nem "por",
# nem duracao colada — e sem ela o `_valores_ja_ofertados` descartava a venda inteira como valor
# fantasma. A alternativa era prescrever no prompt UMA frase que o scanner ja lesse ("Consigo 700
# sim amor"); foi recusada pelo dono do produto: conduta prescrita como frase vira tique (o "Seria
# hoje ?" ja virou tique medido em prod) e uma frase com carga funcional pune toda variacao. Entao
# o detector e que alarga — a fala fica livre, o token de fechamento e que precisa estar colado no
# numero. Continua ESTREITO: o token de aceite e obrigatorio e o piso de 100 segue valendo.
_RE_PRECO_CITADO = re.compile(
    r"r\$\s*(\d[\d.]{2,6})"
    r"|\b(\d[\d.]{2,6})\s*(?:reais|conto)\b"
    r"|\b(\d{3,4})\s+(?:\d{1,2}\s*h(?:\d{2})?\b|\d{1,2}\s*(?:hora|hr)|meia hora|\d{2}\s*min)"
    r"|\bconsigo\s+(?:r\$\s*)?(\d{1,2}\.\d{3}|\d{3,4})\b"
    r"|\b(?:por|fica|sai)\s+(?:r\$\s*)?(\d{1,2}\.\d{3}|\d{3,4})\b"
    r"|\b(?:fechado|fechados|fechamos|combinado|tabom|t[áa] bom|fecho|fa[çc]o|topo)[,!]?\s+"
    r"(?:por\s+|em\s+|r\$\s*)?(\d{1,2}\.\d{3}|\d{3,4})\b"
    r"|\b(\d{1,2}\.\d{3}|\d{3,4})\s+(?:ent[ãa]o|fechado|fechamos|combinado)\b"
    # "500 no total" NAO entra aqui (ramo revertido na revisao da r2, ver `totais_ditos_na_fala`):
    # o total e programa + Pix do deslocamento, e o Pix NUNCA compoe o valor do programa
    # (CONTEXT.md §Pix de deslocamento; a base de repasse dos ADR-0011/0012/0013 e o programa).
    # Legitimar a soma aqui fazia o aceite seguinte gravar `valor_acordado=500` sobre uma tabela de
    # 400 — inflando o repasse por dentro do proprio detector que existe p/ barrar numero inventado.
)
PRECO_MINIMO_SCAN = 100
# Piso de plausibilidade do `valor_acordado` extraido: abaixo disto o numero nao e preco de
# programa nenhum — e a hora do relogio (0-24) lida como valor. Ver o uso em `registrar_extracao_ia`.
_VALOR_MINIMO_PLAUSIVEL = 30
# Fim de clausula: pontuacao que NAO esteja ENTRE digitos ("1.000", "400,00" seguem inteiros; o
# "300, mas consigo 350" continua sendo duas clausulas). Sem essa guarda o split partiria o proprio
# numero e o "1.000" sumiria do conjunto; com ela estreita demais, a recusa contaminaria a oferta
# que vem logo depois dela na mesma bolha.
_RE_FIM_DE_CLAUSULA = re.compile(r"(?<!\d)[.,]|[.,](?!\d)|[;:!?\n]")
_RE_NEGACAO_NA_CLAUSULA = re.compile(r"\b(?:n[aã]o|nunca|nem|jamais)\b")
# Falas da modelo lidas do historico. 50 e a mesma ordem de grandeza da janela do turno: negociacao
# de preco vive nas ultimas trocas, e varrer a conversa inteira so encareceria a query.
_JANELA_FALAS_DA_MODELO = 50


def extrair_precos_citados(texto: str) -> set[int]:
    """Valores monetarios que o texto CITA como preco (PURO; contexto monetario exigido).

    Normalizar o texto no caller nao e usado aqui de proposito: o regex e case-insensitive por
    construcao (digitos) e o "R$" precisa do cifrao cru. Separador de milhar ("1.000") e
    colapsado antes do parse."""
    valores: set[int] = set()
    for grupos in _RE_PRECO_CITADO.findall(texto.lower()):
        for bruto in grupos:
            if not bruto:
                continue
            try:
                valor = int(bruto.replace(".", ""))
            except ValueError:
                continue
            if valor >= PRECO_MINIMO_SCAN:
                valores.add(valor)
    return valores


def precos_ofertados_na_fala(texto: str) -> set[int]:
    """Precos que a fala da modelo/IA OFERTA (PURO): `extrair_precos_citados` menos o que aparece
    em clausula negada — "nao consigo por 300 nao" cita 300 e nao oferta nada."""
    valores: set[int] = set()
    for clausula in _RE_FIM_DE_CLAUSULA.split(texto.lower()):
        if not _RE_NEGACAO_NA_CLAUSULA.search(clausula):
            valores |= extrair_precos_citados(clausula)
    return valores


# Hora do relogio dentro de uma clausula ("9h", "as 22h", "9 horas"). Escrito aqui, e nao reusado
# de `agente/_disciplina`, porque `dominio/` nao pode importar `barra.agente` (dominio/CLAUDE.md).
_RE_HORA_NA_CLAUSULA = re.compile(r"\b(?:[àa]s\s+)?([01]?\d|2[0-3])\s*(?:h|hs|hrs|horas?)\b")
# Recusa da modelo, no vocabulario do prompt ("Poxa amor, 9h nao consigo").
_RE_RECUSA_DE_HORA = re.compile(
    r"\b(?:n[ãa]o|nunca)\s+(?:consigo|posso|d[áa]|vai\s+dar|rola|tenho\s+como|atendo)\b"
    r"|\bimposs[íi]vel\b"
)
# Mesmo veto do lado do agente (`_disciplina._RE_CONTEXTO_DE_PRECO`): com preco na clausula, o "Nh"
# e DURACAO vendida e nao relogio — "nao consigo 250 na 1h" recusa o desconto, nao a 01:00.
_RE_PRECO_NA_CLAUSULA = re.compile(r"\b\d{3,4}\b")


def horas_recusadas_na_fala(texto: str) -> set[int]:
    """Horas do relogio que a fala da modelo/IA RECUSA ("Poxa amor, 9h nao consigo") (PURO).

    Irma de `precos_ofertados_na_fala` e com a MESMA mecanica de clausula: e o corte por
    `_RE_FIM_DE_CLAUSULA` que impede a hora OFERTADA logo depois ("Pode ser as 10h ?") de entrar
    junto com a recusada — as duas moram na mesma fala do turno, e uma janela de N caracteres
    fundiria as duas."""
    horas: set[int] = set()
    for clausula in _RE_FIM_DE_CLAUSULA.split(texto.lower()):
        if _RE_RECUSA_DE_HORA.search(clausula) and not _RE_PRECO_NA_CLAUSULA.search(clausula):
            horas |= {int(h) for h in _RE_HORA_NA_CLAUSULA.findall(clausula)}
    return horas


def _hora_recusada_pela_ia(payload: dict[str, Any], fala_da_ia_no_turno: str | None) -> bool:
    """A hora que este payload grava foi RECUSADA pela IA na fala DESTE turno?

    Consumidor do detector acima. O `horario_desejado` chega como `time` (fallback de tempo
    imediato) ou como string ISO ("09:00:00", `model_dump(mode="json")` da tool)."""
    horario = payload.get("horario_desejado")
    if horario is None or not fala_da_ia_no_turno:
        return False
    if isinstance(horario, time):
        hora = horario.hour
    else:
        try:
            hora = int(str(horario).split(":")[0])
        except ValueError:
            return False
    return hora in horas_recusadas_na_fala(fala_da_ia_no_turno)


# "500 no total": a SOMA que o cliente pede na cotacao externa ("Quanto fica no total ?") — programa
# + Pix do deslocamento. Fica FORA do `_RE_PRECO_CITADO` de proposito (o total nao e preco de
# programa, e legitima-lo como tal inflaria o repasse); mora aqui para o unico uso legitimo dele:
# reconhecer que o `valor_acordado` descartado veio da soma que ELA anunciou — nesse caso o aceite
# do cliente e REAL, so o numero e que esta errado. Mesmo piso de 100 do scanner de preco.
_RE_TOTAL_DITO = re.compile(r"\b(\d{1,2}\.\d{3}|\d{3,4})\s+no total\b")


def totais_ditos_na_fala(texto: str) -> set[int]:
    """Somas que a fala anuncia como TOTAL do encontro (PURO) — programa + Pix do deslocamento.

    NAO sao precos ofertados: o Pix do deslocamento nunca compoe o valor do programa (CONTEXT.md),
    entao "500 no total" com a 1h a 400 nao autoriza gravar 400+100 como `valor_acordado`. Serve so
    a `_sem_valor_fantasma`: o numero cai, o ACEITE fica. Clausula negada nao anuncia total nenhum
    ("nao fecho 500 no total nao"), mesma regra do `precos_ofertados_na_fala`."""
    valores: set[int] = set()
    for clausula in _RE_FIM_DE_CLAUSULA.split(texto.lower()):
        if _RE_NEGACAO_NA_CLAUSULA.search(clausula):
            continue
        for bruto in _RE_TOTAL_DITO.findall(clausula):
            valor = int(bruto.replace(".", ""))
            if valor >= PRECO_MINIMO_SCAN:
                valores.add(valor)
    return valores


async def _preco_cotado_do_pacote_fechado(
    conn: AsyncConnection[Any],
    atendimento_id: UUID,
    payload: dict[str, Any],
    fala_da_ia_no_turno: str | None,
) -> Decimal | None:
    """O preco a gravar quando o aceite chega sem `valor_acordado` — ou `None` (nao preencher).

    Condicoes, todas necessarias (ver o chamador): o cliente ACEITOU (sinal deste turno ou ja
    gravado), o pacote esta fechado (`duracao_horas`), o valor ainda e NULL, a tabela tem UMA linha
    para essa duracao, NAO houve contraproposta na conversa e o preco dessa linha saiu de fato da
    boca da IA aqui. E o mesmo criterio da guarda do valor fantasma, na direcao oposta: la o numero
    que ela nunca falou nao entra; aqui o que ela falou, e que ele topou, nao fica de fora.
    """
    sinais = payload.get("sinais_qualificacao") or {}
    aceite_no_turno = bool(sinais.get("aceita_valor")) if isinstance(sinais, dict) else False
    res = await conn.execute(
        "SELECT modelo_id, conversa_id, duracao_horas, valor_acordado, n_contrapropostas, "
        "estado::text AS estado, tipo_atendimento::text AS tipo_atendimento, "
        "COALESCE((sinais_qualificacao->>'aceita_valor')::boolean, false) AS aceite_gravado "
        "FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    a = await res.fetchone()
    if a is None or a["valor_acordado"] is not None or a["n_contrapropostas"]:
        return None
    if _e_remoto(payload, a["tipo_atendimento"]):
        return None
    # `Aguardando_confirmacao` entra junto com o sinal explicito: o encontro so chega a esse estado
    # com hora cravada e tipo definido — ninguem crava hora sobre um preco que nao topou, e o
    # extrator as vezes simplesmente nao marca o sinal no turno do "isso, fechado".
    if not (aceite_no_turno or a["aceite_gravado"] or a["estado"] == "Aguardando_confirmacao"):
        return None
    duracao = payload.get("duracao_horas") or a["duracao_horas"]
    if duracao is None:
        return None
    precos = {preco for preco, _ in await _linhas_de_tabela(conn, a["modelo_id"], duracao)}
    if len(precos) != 1:
        return None
    preco = next(iter(precos))
    cotados = await _precos_cotados_pela_ia(conn, a["conversa_id"], fala_da_ia_no_turno)
    if _valor_fora_do_conjunto(preco, cotados) is not None:
        return None
    logger.info(
        "valor_acordado preenchido pelo preco cotado do pacote fechado (atendimento %s): %s",
        atendimento_id,
        preco,
    )
    return Decimal(preco)


async def _valores_ja_ofertados(
    conn: AsyncConnection[Any], atendimento_id: UUID, fala_do_turno: str | None
) -> set[int]:
    """Conjunto legitimo de `valor_acordado`: tabela da modelo U precos que ela/a IA ja ofertou.

    Vazio = detector DESLIGADO (mesma convencao do `bolhas_preco_fantasma`): modelo sem nenhum
    preco cadastrado nao tem "fora da tabela", e descartar tudo travaria a venda de um cadastro
    incompleto. `modelo_manual` conta junto com `ia` — numero que o Fernando/a modelo digitou no
    painel saiu da boca da modelo do mesmo jeito."""
    res = await conn.execute(
        "SELECT modelo_id, conversa_id FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    row = await res.fetchone()
    if row is None:
        return set()
    res = await conn.execute(
        "SELECT preco, preco_minimo FROM barravips.modelo_programas WHERE modelo_id = %s",
        (row["modelo_id"],),
    )
    legitimos = {
        int(Decimal(str(r[coluna])))
        for r in await res.fetchall()
        for coluna in ("preco", "preco_minimo")
        if r[coluna] is not None
    }
    if not legitimos:
        return set()
    return legitimos | await _precos_cotados_pela_ia(conn, row["conversa_id"], fala_do_turno)


async def _precos_cotados_pela_ia(
    conn: AsyncConnection[Any], conversa_id: Any, fala_do_turno: str | None
) -> set[int]:
    """Precos que sairam da BOCA da IA/modelo nesta conversa: janela de falas persistidas +, se
    veio, a bolha deste turno (que ainda nao esta em `mensagens`).

    E a metade "falada" do conjunto legitimo do valor fantasma -- `_valores_ja_ofertados` une isto
    com a tabela da modelo. O piso do pacote precisa dela SOZINHA: unir a tabela ali equivaleria a
    dizer que a IA cotou todos os pacotes, e a deducao do pacote (`_piso_deduzido_do_cotado`)
    nunca identificaria nenhum. Sem `conversa_id` (chamador que nao a tem) sobra so a fala do
    turno.

    Oferta, nao citacao: `precos_ofertados_na_fala` ja tira o numero em clausula negada -- "nao
    consigo por 300 nao" nao cota pacote nenhum."""
    cotados: set[int] = set()
    for fala in await _falas_da_modelo(conn, conversa_id, fala_do_turno):
        cotados |= precos_ofertados_na_fala(fala)
    return cotados


async def _falas_da_modelo(
    conn: AsyncConnection[Any], conversa_id: Any, fala_do_turno: str | None
) -> list[str]:
    """A janela de falas da IA/modelo nesta conversa: as persistidas + a bolha DESTE turno (que
    ainda nao esta em `mensagens`).

    Fonte unica da janela p/ os dois scanners que julgam o que saiu da boca dela
    (`_precos_cotados_pela_ia`, `_total_anunciado_pela_ia`) -- duas copias da mesma query divergem
    no `LIMIT`/na direcao amanha e passam a julgar a mesma fala de formas diferentes."""
    falas: list[str] = []
    if conversa_id is not None:
        res = await conn.execute(
            """
            SELECT conteudo FROM barravips.mensagens
             WHERE conversa_id = %s AND direcao IN ('ia', 'modelo_manual') AND conteudo <> ''
             ORDER BY created_at DESC, id DESC
             LIMIT %s
            """,
            (conversa_id, _JANELA_FALAS_DA_MODELO),
        )
        falas.extend(m["conteudo"] for m in await res.fetchall())
    if fala_do_turno:
        falas.append(fala_do_turno)
    return falas


async def _total_anunciado_pela_ia(
    conn: AsyncConnection[Any], atendimento_id: UUID, valor: int, fala_do_turno: str | None
) -> bool:
    """O valor descartado e o TOTAL que a PROPRIA IA anunciou ("500 no total") nesta conversa?

    Quando e, o aceite do cliente e REAL -- ele topou a soma que ela disse; o que esta errado e so
    o numero, porque o Pix do deslocamento nao compoe o valor do programa (CONTEXT.md). Por isso
    `_sem_valor_fantasma` preserva o `aceita_valor` neste caso, e o preco do programa entra pelo
    backstop (`_preco_cotado_do_pacote_fechado`), que so grava preco de TABELA de fato cotado.

    Rodada 2 do loop de massa: a resposta anterior a este sintoma foi alargar o scanner de preco
    p/ "N no total" -- e ela legitimava a soma como preco de programa, gravando 500 sobre uma
    tabela de 400 (revisao de dominio). O aceite e que precisava sobreviver, nao o numero."""
    res = await conn.execute(
        "SELECT conversa_id FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    row = await res.fetchone()
    conversa_id = row["conversa_id"] if row is not None else None
    return any(
        valor in totais_ditos_na_fala(fala)
        for fala in await _falas_da_modelo(conn, conversa_id, fala_do_turno)
    )


def _valor_fora_do_conjunto(valor: Any, legitimos: set[int]) -> int | None:
    """O valor como INTEIRO quando ele nao pertence ao conjunto legitimo; None quando pertence.

    Case pelo inteiro: centavos nao mudam a identidade do numero na conversa ("350,00" e o 350 que
    a IA falou). Chao e arredondamento entram os dois — 349,50 casa com 350 ofertado, e 349,49
    casa com 349 (nenhum dos dois vale a pena escalar por um centavo)."""
    try:
        numero = Decimal(str(valor))
    except (InvalidOperation, ValueError, TypeError):
        return None
    candidatos = {int(numero), int(numero.to_integral_value(rounding=ROUND_HALF_UP))}
    return None if candidatos & legitimos else int(numero)


def _sem_valor_fantasma(
    payload: dict[str, Any], fantasma: int, legitimos: set[int], *, preservar_aceite: bool = False
) -> dict[str, Any]:
    """Payload sem o `valor_acordado` descartado: o resto segue gravando normalmente.

    `aceita_valor` do MESMO payload cai junto — ele foi inferido do mesmo evento falso (o cliente
    "aceitando" o proprio numero). Os outros sinais ficam. O `valor_descartado` viaja no evento
    `extracao_registrada`, mesma auditoria do `drift_descartado`/`tipo_descartado`.

    `preservar_aceite` e a EXCECAO do total anunciado (`_total_anunciado_pela_ia`): o numero
    descartado e a soma programa + Pix que ela mesma disse, entao o "fechou" do cliente aconteceu
    de verdade — cai so o valor (o Pix nunca compoe o programa), e o preco entra pelo backstop do
    pacote fechado. Sem isso, a venda dita com todas as letras saia sem valor E sem aceite."""
    limpo = {k: v for k, v in payload.items() if k != "valor_acordado"}
    sinais = {k: v for k, v in (payload.get("sinais_qualificacao") or {}).items()}
    if not preservar_aceite:
        sinais.pop("aceita_valor", None)
    if sinais:
        limpo["sinais_qualificacao"] = sinais
    else:
        limpo.pop("sinais_qualificacao", None)
    limpo["valor_descartado"] = {"proposto": fantasma, "legitimos": sorted(legitimos)}
    return limpo


_AVISO_VALOR_FANTASMA = (
    "AVISO: valor_acordado {fantasma} DESCARTADO — esse numero nunca foi ofertado por voce nesta "
    "conversa (so vale preco da sua tabela ou valor que voce mesma falou), entao o sistema nao "
    "gravou o valor nem o aceite. Se voce decidir aceitar esse valor, OFERTE-O na sua fala ao "
    "cliente e registre no proximo turno."
)
# Aviso do caso TOTAL (programa + Pix do deslocamento): o aceite FOI gravado, so o numero caiu.
_AVISO_TOTAL_NAO_E_PRECO = (
    "AVISO: valor_acordado {fantasma} DESCARTADO — esse e o TOTAL que voce anunciou (o programa "
    "MAIS o Pix do deslocamento), e o Pix nunca entra no valor do programa. O aceite do cliente "
    "FOI gravado; o valor a registrar e so o do programa. Se ele topou um preco de programa "
    "diferente da sua tabela, registre esse numero sozinho no proximo turno."
)


def piso_de_desconto(preco_tabela: Decimal, preco_minimo: Decimal | None = None) -> Decimal:
    """Menor valor que a IA oferta sozinha sobre um preco de tabela: `preco x (1 -
    desconto_teto_pct)` (ADR-0031, teto da escalada de 2 rodadas), NUNCA abaixo do
    `preco_minimo` cadastrado na linha. `desconto_teto_pct=0` => piso = preco de tabela.

    SITE UNICO da conta, de proposito: quem JULGA a oferta da IA (`_abaixo_do_piso`) e quem
    MOSTRA o numero a ela (o bloco da escada na cauda, via `contraproposta_da_escada`) saem daqui. Duas implementacoes que concordam hoje divergem no
    arredondamento amanha, e a divergencia aparece como escalada `fora_de_oferta` a toa em cima
    de uma oferta que a propria cauda mandou fazer.

    `preco_minimo` (11/08/2026, ao subir a Catarina) e o piso ABSOLUTO da linha, cadastrado em
    `modelo_programas.preco_minimo`: o percentual global e uma regra da CASA, o minimo e uma
    regra DESTA modelo neste pacote, e a regra mais apertada vence. Sem ele, um pacote curto
    cadastrado justamente como "o minimo que eu faco" (Catarina: 250 nos 30min) seria descontado
    pelos mesmos 25% e viraria 188 — o minimo que desconta nao e minimo. NULL preserva o
    comportamento de antes: so o percentual manda."""
    return _clampado(
        preco_tabela * (Decimal("1") - Decimal(str(get_settings().desconto_teto_pct))),
        preco_minimo,
    )


def degrau_de_desconto(preco_tabela: Decimal, preco_minimo: Decimal | None = None) -> Decimal:
    """Valor da PRIMEIRA contraproposta sobre um preco de tabela: `preco x (1 -
    desconto_degrau_pct)` (ADR-0031, degrau da escalada de 2 rodadas), NUNCA abaixo do
    `preco_minimo` da linha (mesma regra do `piso_de_desconto`, ver docstring dele).
    `desconto_degrau_pct=0` => degrau = preco de tabela.

    SITE UNICO da conta do degrau, irmao do `piso_de_desconto`: quem LEGITIMA o numero na saida
    (`_valores_legitimos`, output_guard) e quem o MOSTRA a IA (o bloco da escada na cauda, via
    `contraproposta_da_escada`) saem daqui — mesma razao do piso: duas contas que concordam hoje
    divergem no arredondamento amanha, e o guard derruba a oferta que a cauda mandou fazer."""
    return _clampado(
        preco_tabela * (Decimal("1") - Decimal(str(get_settings().desconto_degrau_pct))),
        preco_minimo,
    )


def _clampado(valor: Decimal, preco_minimo: Decimal | None) -> Decimal:
    """Nao deixa a conta percentual furar o piso absoluto da linha. Sem minimo, passa direto."""
    if preco_minimo is None:
        return valor
    return max(valor, Decimal(str(preco_minimo)))


# Uma LINHA de tabela e o par `(preco, preco_minimo)` de `modelo_programas` (o piso absoluto da
# linha, ADR-0037, pode ser NULL). Tudo que precifica um pacote trafega esse par junto -- preco
# sem o minimo dele volta a permitir desconto por baixo do que a modelo cadastrou como minimo.
LinhaDeTabela = tuple[Decimal, Decimal | None]

# ESTAGIO da escada de desconto em que um valor esta -- discreto, nunca um percentual livre.
# Sao os tres valores que a IA pode dizer sobre uma linha (ADR-0031 + ADR-0037): o preco cheio,
# o degrau (primeira contraproposta) e o piso (a ultima). Existe como TIPO porque o extra de
# fetiche acompanha o patamar do pacote (ADR-0038) e "acompanhar" tinha que ser uma escolha
# entre tres valores, nao um fator multiplicativo -- ver `valor_no_patamar`.
Patamar = Literal["cheio", "degrau", "piso"]
PATAMARES: tuple[Patamar, ...] = ("cheio", "degrau", "piso")


def valor_no_patamar(
    preco_tabela: Decimal, preco_minimo: Decimal | None, patamar: Patamar
) -> Decimal:
    """O valor de UMA linha de tabela no estagio `patamar` da escada -- despacho, nao conta nova.

    Os numeros saem dos sites unicos de sempre (`degrau_de_desconto`/`piso_de_desconto`, com o
    clamp do `preco_minimo`); aqui so se escolhe QUAL deles. Existe para que "no mesmo patamar"
    seja uma operacao nomeada: o extra de fetiche (ADR-0038) e o pacote precisam descer pela
    MESMA escada, e a alternativa -- multiplicar o extra pelo fator `valor_negociado/preco` --
    da numeros que nao existem em tabela nenhuma (na 3h da Catarina, com piso absoluto de 900
    sobre 1000, o fator 0,9 faria o extra virar R$360; o patamar faz dele R$300, que e o piso da
    1h dela).
    """
    if patamar == "degrau":
        return degrau_de_desconto(preco_tabela, preco_minimo)
    if patamar == "piso":
        return piso_de_desconto(preco_tabela, preco_minimo)
    return preco_tabela


def patamar_do_valor(
    preco_tabela: Decimal, preco_minimo: Decimal | None, valor_da_mesa: Decimal
) -> Patamar:
    """Em que patamar da escada um VALOR ja esta -- o inverso do `valor_no_patamar`, e a emenda do
    ADR-0038 (11/08/2026): o patamar deixa de ser deduzido so do contador de rodadas.

    `n_contrapropostas` carrega dois fatos que ate hoje coincidiam: quantas rodadas a IA gastou, e
    em que estagio o valor da mesa esta. Eles deixam de coincidir quando o numero na mesa veio do
    CLIENTE (ADR-0040): com tabela 800 e piso 600, aceitar os 700 DELE consome a rodada de hoje --
    `patamar_vigente(hoje, 1)` diria `piso` e o extra de fetiche sairia a 600 em cima de um pacote
    de 700. Aqui a resposta sai do proprio valor: `degrau`.

    Definicao: o patamar MAIS RASO cujo valor e `<= valor_da_mesa`. Discreto e monotonico, nunca um
    fator multiplicativo -- e exatamente o que o ADR-0038 rejeitou (multiplicar o extra por
    `valor_negociado/preco` da numeros que nao existem em tabela nenhuma). Os numeros continuam
    saindo dos sites unicos, via `valor_no_patamar`.

    Em 800/600 (degrau 700, piso 600): 800 -> cheio; 750 -> degrau; 700 -> degrau; 650 -> piso;
    600 -> piso. Valor abaixo do piso (nao deveria existir; a guarda `_abaixo_do_piso` escala)
    devolve `piso`, que e o mais fundo que a escada conhece."""
    for patamar in PATAMARES:
        if valor_no_patamar(preco_tabela, preco_minimo, patamar) <= valor_da_mesa:
            return patamar
    return "piso"


# O DIA do encontro, como a escada de desconto o enxerga (decisao do dono do produto, 11/08/2026).
# Nao e uma data: e a unica distincao que muda a conduta comercial.
Encontro = Literal["hoje", "outro_dia", "dia_desconhecido"]

# A escada de desconto POR ENCONTRO -- os patamares que ela pode ofertar, em ordem.
#
# Agenda de hoje e ociosidade que nao volta: vale o desconto cheio de imediato, entao a primeira
# (e unica) contraproposta ja e o PISO. Para outro dia nao ha pressa e ela negocia devagar: degrau,
# depois piso, a escalada de 2 rodadas do ADR-0031. Enquanto o dia nao esta na mesa NAO se
# desconta — nao ha "quantas rodadas" a decidir sem saber a qual regime a conversa pertence, e o
# degrau 1 do `<desconto>` ja manda defender o valor e perguntar "Seria hoje ?": o fluxo natural
# produz o dado de que a escada precisa.
#
# A ARITMETICA nao muda (`degrau_de_desconto`/`piso_de_desconto` seguem sites unicos); o que este
# mapa decide e QUAL patamar a escada oferece primeiro, e quantas vezes.
ESCADA_POR_ENCONTRO: dict[Encontro, tuple[Patamar, ...]] = {
    "hoje": ("piso",),
    "outro_dia": ("degrau", "piso"),
    "dia_desconhecido": (),
}

# Em que ponto a escada esta, para a cauda escolher o bloco (e o prompt parar de afirmar "duas
# contrapropostas" incondicionalmente -- com encontro hoje existe UMA).
EstadoDaEscada = Literal["sem_dia", "aberta", "ultima", "esgotada"]


def estado_da_escada(encontro: Encontro, n_contrapropostas: int) -> EstadoDaEscada:
    """Onde a negociacao esta na escada deste encontro -- SITE UNICO do gating por rodada.

    `sem_dia` = o dia nao esta na mesa: nenhum numero desce, a jogada e defender o valor e
    descobrir o dia. `aberta` = ainda ha mais de uma contraproposta pela frente. `ultima` = a que
    esta disponivel e a ultima. `esgotada` = acabou (aceite ou recusa; abaixo dela, escalada).
    """
    patamares = ESCADA_POR_ENCONTRO[encontro]
    if not patamares:
        return "sem_dia"
    restantes = len(patamares) - max(n_contrapropostas, 0)
    if restantes <= 0:
        return "esgotada"
    return "ultima" if restantes == 1 else "aberta"


def patamar_da_contraproposta(encontro: Encontro, n_contrapropostas: int) -> Patamar | None:
    """O patamar da PROXIMA contraproposta, ou None quando nao ha nenhuma a fazer."""
    patamares = ESCADA_POR_ENCONTRO[encontro]
    if not 0 <= n_contrapropostas < len(patamares):
        return None
    return patamares[n_contrapropostas]


def patamar_vigente(encontro: Encontro, n_contrapropostas: int) -> Patamar:
    """O patamar em que o valor na mesa JA esta -- o da ultima contraproposta feita, `cheio` antes
    da primeira. E o que o extra de fetiche precisa para descer junto com o pacote (ADR-0038)."""
    patamares = ESCADA_POR_ENCONTRO[encontro]
    if n_contrapropostas <= 0 or not patamares:
        return "cheio"
    return patamares[min(n_contrapropostas, len(patamares)) - 1]


# O veredito da `aceite_do_valor_dele` -- label da `AGENTE_ACEITE_DO_CLIENTE` e, antes disso, o
# vocabulario de POR QUE o numero dele nao serviu. Tudo que nao e `aceito` cai na escada de sempre.
MotivoDoAceite = Literal[
    "aceito",
    "abaixo_do_piso",
    "acima_da_mesa",
    "ambiguo",
    "sem_valor",
    "esgotada",
    "condicionado",
]


async def aceite_do_valor_dele(
    conn: AsyncConnection[Any],
    modelo_id: Any,
    duracao_horas: Any,
    *,
    valor_proposto: int | None,
    valor_da_mesa: Decimal | None,
    encontro: Encontro,
    n_contrapropostas: int,
    condicionado: bool = False,
) -> tuple[Decimal | None, MotivoDoAceite]:
    """O valor que o CLIENTE nomeou, quando ele serve -- ou `None` e o motivo (ADR-0040).

    A regra: numero DELE que cai em `[piso, valor_da_mesa)` fecha a venda NO NUMERO DELE, na hora.
    O vendedor humano exemplar cotou 800, ouviu "faz 700" e fechou em 700; a escada respondia 600
    (o piso), porque "faz por X" era so o GATILHO dela e o X era jogado fora. Dar desconto que o
    cliente nao pediu, em toda negociacao em que ele nomeia um valor, e o prejuizo que esta funcao
    fecha -- e ela nao inventa numero nenhum: o numero e o dele.

    Irma da `contraproposta_da_escada` e com a mesma cascata fail-closed: le a tabela pela
    `_linhas_de_tabela` (`apenas_presenciais=True`) e o piso pelo `piso_de_desconto`, exatamente
    como a `_contraproposta_da_tabela`. NAO reusa o `_piso_do_pacote`: ele responde a pergunta da
    venda JA FEITA (e traz a vídeo chamada junto, `apenas_presenciais=False`); aqui a pergunta e a
    da OFERTA, e e a mesma razao pela qual `_linhas_de_tabela` existe separada.

    `valor_da_mesa` = o `valor_acordado` do atendimento quando existe; `None` cai no `preco` da
    linha unica (a cotacao em aberto). Depois de um aceite a mesa e o valor aceito, e um pedido
    ainda mais baixo volta a ser candidato -- quem impede o leilao (700 -> 650 -> 620) NAO e o
    piso, e o ORCAMENTO DE RODADAS: o aceite CONSUME uma rodada da escada (o chamador incrementa
    `n_contrapropostas` pelo write-time, `_disciplina.contem_contraproposta`), entao com encontro
    HOJE (uma rodada so) aceitar 700 esgota a escada e o proximo pedido recebe "Poxa amor nao
    consigo".

    `dia_desconhecido` e o buraco desse orcamento: `ESCADA_POR_ENCONTRO` e vazia e o
    `estado_da_escada` devolve `sem_dia` para QUALQUER `n`, entao o contador nunca esgota. Ali a
    regra e explicita: um aceite so (`n_contrapropostas == 0`). Aceitar o numero dele independe do
    dia -- o dia decide quanto ELA desce, nao quanto ELE ofereceu.

    `condicionado` (loop-massa r3, achado 10) e o unico sinal que nao vem de numero: True quando o
    burst pendurou uma condicao de SERVICO no valor ("por 300? Com 2 finalizacoes"). O `int` sozinho
    nao carrega ressalva, e o bloco que este retorno injeta manda aceitar "na hora, no valor DELE" e
    sem ressalva -- entao a condicao entraria no belief como parte da venda fechada, sem nunca ter
    sido conferida contra `<programas>`/`<fetiches>`. Fail-closed como o resto da cascata: o numero
    dele so fecha sozinho quando vem sozinho. Quem detecta e `_ressalva_de_servico_no_burst`
    (`agente/nos/prepare_context.py`), que le a janela crua -- o dominio nao a tem.
    """
    esgotada = estado_da_escada(encontro, n_contrapropostas) == "esgotada" or (
        encontro == "dia_desconhecido" and n_contrapropostas > 0
    )
    if esgotada:
        return None, "esgotada"
    if valor_proposto is None:
        return None, "sem_valor"
    # DEPOIS do `sem_valor` de proposito: sem numero nao ha proposta a condicionar, e `sem_valor`
    # continua medindo so o detector de fala (`AGENTE_ACEITE_DO_CLIENTE`).
    if condicionado:
        return None, "condicionado"
    linhas = await _linhas_de_tabela(conn, modelo_id, duracao_horas)
    precos = {preco for preco, _ in linhas}
    if len(precos) != 1:
        return None, "ambiguo"
    preco = next(iter(precos))
    # Mesmo criterio da `_contraproposta_da_tabela` para duas linhas com o mesmo preco e minimos
    # diferentes: vale o piso MAIS ALTO, o unico valido para qualquer uma delas.
    piso = max(piso_de_desconto(preco, preco_minimo) for _, preco_minimo in linhas)
    mesa = valor_da_mesa if valor_da_mesa is not None else preco
    proposto = Decimal(valor_proposto)
    if proposto >= mesa:
        return None, "acima_da_mesa"
    if proposto < piso:
        return None, "abaixo_do_piso"
    return proposto, "aceito"


async def patamar_da_mesa_na_tabela(
    conn: AsyncConnection[Any], modelo_id: Any, duracao_horas: Any, valor_da_mesa: Decimal | None
) -> Patamar | None:
    """O patamar do valor que esta na mesa, lido da TABELA (emenda do ADR-0038, ver
    `patamar_do_valor`). `None` sem valor na mesa ou com a duracao ambigua -- o chamador cai no
    `patamar_vigente`, que deriva do contador de rodadas.

    Devolver `cheio` NAO significa "a negociacao esta no cheio": significa "a mesa nao se moveu"
    (`valor_acordado` e gravado ja na cotacao e nao acompanha a contraproposta ainda nao aceita).
    Quem le trata `cheio` como ausencia de resposta e fica com o contador -- ver o chamador."""
    if valor_da_mesa is None:
        return None
    linhas = await _linhas_de_tabela(conn, modelo_id, duracao_horas)
    precos = {preco for preco, _ in linhas}
    if len(precos) != 1:
        return None
    preco = next(iter(precos))
    # Duas linhas com o mesmo preco e minimos diferentes: o patamar mais RASO entre elas -- o extra
    # nao pode descer mais do que a linha mais restritiva permite.
    return min(
        (patamar_do_valor(preco, preco_minimo, valor_da_mesa) for _, preco_minimo in linhas),
        key=PATAMARES.index,
    )


async def contraproposta_da_escada(
    conn: AsyncConnection[Any],
    modelo_id: Any,
    duracao_horas: Any,
    *,
    encontro: Encontro,
    n_contrapropostas: int,
) -> Decimal | None:
    """Valor ABSOLUTO da proxima contraproposta -- o numero que a cauda mostra a IA em vez do
    percentual que ela multiplicava de cabeca (trace 11/08: 12,5% sobre 400 saiu "320", que nao e
    degrau nem teto, e o guard derrubou a venda).

    Encontro HOJE devolve o piso ja na primeira rodada e None na segunda (nao existe); outro dia
    devolve degrau e depois piso; dia desconhecido nunca devolve numero.

    `None` (a cauda nao injeta numero nenhum e vale a prosa do `<desconto>`) tambem quando:
    - a duracao nao esta fechada, ou nao ha programa dela nessa duracao — nao ha preco de tabela;
    - a duracao tem MAIS DE UM preco na tabela dela (ex.: "Normal 1h 400" e "Completo 1h 800"): a
      oferta e sobre o "Preco de tabela do pacote VENDIDO" (CONTEXT.md, Piso de desconto) e o
      pacote nao esta gravado no atendimento (`atendimento_servicos` so o painel escreve). Um
      numero sobre o pacote errado e pior que nenhum — e o mesmo fail-closed que o
      `_piso_do_pacote` aplica do lado de quem JULGA a oferta.
    """
    patamar = patamar_da_contraproposta(encontro, n_contrapropostas)
    if patamar is None:
        return None
    return await _contraproposta_da_tabela(conn, modelo_id, duracao_horas, patamar)


async def oferta_condicionada_ao_dia(
    conn: AsyncConnection[Any], modelo_id: Any, duracao_horas: Any
) -> tuple[Decimal, Decimal] | None:
    """O PAR `(se for hoje, se for outro dia)` da MESMA linha — irma da `contraproposta_da_escada`.

    E a mesma escada de sempre lida de uma vez em vez de rodada a rodada: `ESCADA_POR_ENCONTRO`
    ja diz que hoje vale o `piso` e outro dia comeca no `degrau`, entao o par e
    `(piso, degrau)` — nesta ordem, porque o primeiro numero e o de HOJE.

    Existe porque a conduta mudou (ADR-0041): com o dia ainda desconhecido, a IA parou de
    interrogar ("Seria hoje ?") e passou a fazer a CONDICAO viajar dentro da oferta ("se vier
    hoje X, outro dia Y"). Dizer os dois numeros exige ter os dois numeros: sem o par, o segundo
    sairia de cabeca e a resposta dele ("entao outro dia") pareceria AUMENTO de preco.

    Mesmo fail-closed do resto da familia — sem duracao fechada, sem programa nela, com mais de um
    preco presencial na duracao ou com a linha nao descontavel devolve `None`, e a cauda cala.
    Alem desses, um a mais que so este par tem: `piso == degrau` (o clamp do `preco_minimo`
    colapsou os dois estagios) tambem devolve `None` — a oferta condicional com um numero so nao
    condiciona nada, e prometer "hoje 380, outro dia 380" e teatro de desconto.
    """
    if duracao_horas is None:
        return None
    linhas = await _linhas_de_tabela(conn, modelo_id, duracao_horas)
    precos = {preco for preco, _ in linhas}
    if len(precos) != 1:
        return None
    preco = next(iter(precos))
    # Mesmo criterio da `_contraproposta_da_tabela` para linhas de mesmo preco e minimos
    # diferentes: vale a oferta MAIS ALTA, a unica valida para qualquer uma delas.
    se_hoje = max(valor_no_patamar(preco, minimo, "piso") for _, minimo in linhas)
    se_outro_dia = max(valor_no_patamar(preco, minimo, "degrau") for _, minimo in linhas)
    if not se_hoje < se_outro_dia < preco:
        return None
    return se_hoje, se_outro_dia


async def _contraproposta_da_tabela(
    conn: AsyncConnection[Any], modelo_id: Any, duracao_horas: Any, patamar: Patamar
) -> Decimal | None:
    """A UNICA linha de tabela da duracao, no patamar pedido (fail-closed — sem duracao fechada,
    sem programa nela ou com mais de um preco devolve None). A conta sai de `valor_no_patamar`,
    que despacha para os sites unicos; as rodadas diferem SO no patamar.

    Linha NAO DESCONTAVEL (`preco_minimo` = `preco`, ou percentual zerado) tambem devolve None:
    a conta clampada devolveria o proprio preco de tabela, e mostra-lo a IA como contraproposta
    a mandaria "oferecer" um desconto de zero real ("consigo 250 se fechar agora" em cima de uma
    tabela de 250) — pior que nao ter numero, porque parece concessao e nao e. Sem numero, a
    cauda cala e o <desconto> manda o que ja mandava: "Poxa amor nao consigo"."""
    if duracao_horas is None:
        return None
    linhas = await _linhas_de_tabela(conn, modelo_id, duracao_horas)
    precos = {preco for preco, _ in linhas}
    if len(precos) != 1:
        return None
    preco = next(iter(precos))
    # Mesmo preco em duas linhas (dois programas de 400 na 1h) nao e ambiguidade de VALOR — e o
    # caso que o `min == max` de antes ja liberava. Ambiguidade de MINIMO, sim: sem saber qual
    # dos dois ele leva, vale a oferta mais alta entre as linhas, que e a unica valida para
    # QUALQUER uma delas.
    valor = max(valor_no_patamar(preco, preco_minimo, patamar) for _, preco_minimo in linhas)
    return valor if valor < preco else None


async def _linhas_de_tabela(
    conn: AsyncConnection[Any], modelo_id: Any, duracao_horas: Any
) -> list[LinhaDeTabela]:
    """Pares `(preco, preco_minimo)` dos programas PRESENCIAIS da modelo na duracao acordada, do
    mais barato ao mais caro -- a `_linhas_da_duracao` sem a identidade do programa, para quem so
    precifica.

    Linha, nao agregado, porque o `preco_minimo` (piso absoluto do par programa x duracao) so faz
    sentido colado ao preco dele: um `min(preco), min(preco_minimo)` misturaria o piso de um
    pacote com o preco de outro.

    `apenas_presenciais=True` fixo (nao e parametro) porque esta leitura tem UM proposito: montar
    a OFERTA da escada de desconto, onde o pacote ainda esta sendo negociado. Quem julga uma venda
    ja feita nao passa por aqui -- vai direto na `_linhas_da_duracao`, com `False` (ver a docstring
    de la). Se um dia esta funcao ganhar um segundo consumidor com a outra semantica, o parametro
    sobe para ca em vez de o `True` virar `False` para os dois."""
    return [
        (ln["preco"], ln["preco_minimo"])
        for ln in await _linhas_da_duracao(conn, modelo_id, duracao_horas, apenas_presenciais=True)
    ]


async def _linhas_da_duracao(
    conn: AsyncConnection[Any], modelo_id: Any, duracao_horas: Any, *, apenas_presenciais: bool
) -> list[dict[str, Any]]:
    """Linhas de tabela da modelo naquela duracao (`duracoes.horas`), do mais barato ao mais caro:
    `{programa_id, preco, preco_minimo}` ja em `Decimal`. Lista vazia sem programa na duracao (ou
    sem duracao fechada) -- a query nem roda.

    SITE UNICO da leitura de tabela por duracao. A identidade do programa entrou junto quando o
    extra passou a ser a linha de 1h DELE (ADR-0038) e virou obrigatoria quando o PISO passou a
    ser o do par programa x duracao (`_piso_do_pacote`): preco sem saber de qual pacote e foi
    exatamente o furo.

    `apenas_presenciais` e OBRIGATORIO e nao tem default de proposito: a resposta certa depende da
    PERGUNTA de quem le, e as duas familias de chamador querem coisas opostas. Sem ele (estado ate
    11/08/2026) a vídeo chamada da Catarina, cadastrada nas MESMAS duracoes dos pacotes
    presenciais (0.5h: Normal 250 e chamada 300; 1h: Normal 400 e chamada 600), fez toda a familia
    "exige um preco so" cair no fail-closed e a escada de desconto MORREU na 1h.

    - `True` -- "qual e O pacote PRESENCIAL desta duracao?". Pergunta da OFERTA, feita antes de
      existir venda: a escada (`_linhas_de_tabela` -> `contraproposta_da_tabela`) e a base do
      patamar (`nos/prepare_context._base_no_patamar`). Nao existe negociar desconto de vídeo
      chamada -- ela e R$10/minuto com `preco_minimo = preco` (migration 20260811214743), nao
      descontavel por construcao --, entao a linha dela nunca e a resposta e a presenca dela so
      apagava a resposta certa. Filtrar aqui NAO afrouxa nada: as duracoes com dois pacotes
      PRESENCIAIS (Normal + Completo) continuam ambiguas e continuam devolvendo None.
    - `False` -- "quais linhas esta duracao tem, ponto". Pergunta de quem JULGA/REGISTRA um
      atendimento que JA aconteceu e pode SER a vídeo chamada: `_piso_do_pacote` (o piso que julga
      o `valor_acordado`) e `_base_do_pacote` (o snapshot do extra de fetiche do fechamento).
      Filtrar aqui julgaria uma chamada de 600 contra o piso do Normal (300) e deixaria de escalar
      uma venda remota abaixo do minimo dela -- exatamente o furo do ADR-0037, reaberto pelo lado
      remoto.
    """
    if duracao_horas is None:
        return []
    res = await conn.execute(
        """
        SELECT mp.programa_id, p.nome, mp.preco, mp.preco_minimo
          FROM barravips.modelo_programas mp
          JOIN barravips.duracoes d ON d.id = mp.duracao_id
          JOIN barravips.programas p ON p.id = mp.programa_id
         WHERE mp.modelo_id = %s AND d.horas = %s
         ORDER BY mp.preco ASC
        """,
        (modelo_id, Decimal(str(duracao_horas))),
    )
    linhas = [
        {
            "programa_id": r["programa_id"],
            "preco": Decimal(str(r["preco"])),
            "preco_minimo": (
                None if r["preco_minimo"] is None else Decimal(str(r["preco_minimo"]))
            ),
            # `or ""` = linha sem nome conta como PRESENCIAL, o lado que MANTEM a linha na leitura.
            # Manter linha a mais so pode deixar a leitura mais fail-closed (duracao ambigua ->
            # nenhum numero); descartar linha a mais e que inventaria oferta ou piso errado.
            "nome": r.get("nome") or "",
        }
        for r in await res.fetchall()
        if r["preco"] is not None
    ]
    if not apenas_presenciais:
        return linhas
    return [ln for ln in linhas if not e_video_chamada(ln["nome"])]


# Piso do que conta como PRECO CADASTRADO em `modelo_fetiches.preco` (revisao de 2026-08-11 do
# ADR-0030). A coluna foi reaproveitada como FLAG incluso/pago e o painel ainda grava um sentinel
# truthy nela quando `pago=True` (`_PRECO_PAGO_SENTINEL = Decimal("1")`, dominio/modelos/routes.py;
# a migration 20260720233000 gravou o mesmo 1 no Menage de prod) -- "coluna preenchida" NAO
# significa "extra cadastrado". Abaixo deste piso a coluna esta dizendo "pago", nao um valor, e o
# extra cai no calculo derivado do pacote. Nenhum extra real de fetiche e de R$10.
PRECO_FETICHE_CADASTRADO_MINIMO = Decimal("10")


def preco_cadastrado_de_fetiche(preco: Any) -> Decimal | None:
    """O extra CADASTRADO do fetiche, ou None quando a coluna e so a flag pago/incluso.

    None (incluso) e o sentinel de "pago sem valor" caem no mesmo balde -- quem distingue
    incluso de pago continua sendo `preco IS NULL` vs NOT NULL, lido por quem chama
    (render_fetiches, _resolver_fetiches_em_pauta, o guard). Aqui a pergunta e outra: "ha um
    numero de verdade nesta coluna?".
    """
    if preco is None:
        return None
    valor = Decimal(str(preco))
    return valor if valor >= PRECO_FETICHE_CADASTRADO_MINIMO else None


# Piso de DURACAO para existir fetiche pago (decisao do dono do produto, 11/08/2026, ao subir a
# Catarina -- a tabela dela tem uma linha de 30 minutos, Normal a R$250). Pacote com menos de 1h
# e enxuto: sem extras. Vale nos DOIS regimes (cadastrado e derivado) -- "menos de 1h nao tem
# fetiche pago" e sobre a DURACAO, nao sobre a conta.
#
# Nasceu como defesa contra a formula antiga (preco-hora, ADR-0030), que em duracao fracionaria
# INVERTIA: 250 / 0,5h = +R$500 sobre um pacote de R$250. Sob a formula nova (ADR-0038, o extra e
# a linha de 1h) o absurdo aritmetico some -- o extra da meia hora seria os mesmos R$400 da 1h --
# e a regra fica mais simples de justificar, nao menos: cobrar +R$400 de extra sobre um pacote de
# R$250 e vender a meia hora como se fosse a hora. O caminho e o upsell (a conduta `pacote_curto`
# do `<fetiches>`), nao o extra.
DURACAO_MINIMA_FETICHE_PAGO = Decimal("1")


def aceita_fetiche_pago(duracao_horas: Any) -> bool:
    """True se um pacote dessa duracao pode carregar fetiche pago (>= 1h) -- SITE UNICO da regra.

    Quem precisa do NUMERO chama `extra_de_fetiche`, que ja devolve None na duracao curta. Este
    predicado e para quem filtra LINHA: o render do `<fetiches>` (que nao pode imprimir a linha
    do pacote curto) e o `_valores_legitimos` do output_guard (que nao pode legitimar o total
    dela). Duracao ausente e tratada como nao-elegivel -- fail-closed, como o resto do cardapio.
    """
    if duracao_horas is None:
        return False
    return Decimal(str(duracao_horas)) >= DURACAO_MINIMA_FETICHE_PAGO


def extra_de_fetiche(
    linha_de_uma_hora: LinhaDeTabela | None,
    duracao_horas: Any,
    *,
    patamar: Patamar = "cheio",
    preco_cadastrado: Any = None,
) -> Decimal | None:
    """Extra de UM fetiche pago sobre o pacote em pauta -- SITE UNICO da conta (render + painel).

    Duas fontes, nesta ordem:
    1. **preco CADASTRADO** no painel (`modelo_fetiches.preco` com numero de verdade, revisao de
       11/08/2026 do ADR-0030): cadastro explicito manda, fixo, e NAO acompanha o patamar -- o
       operador digitou um valor, nao uma escada.
    2. **derivado da linha de 1h** (`calcular_preco_extra_fetiche`, ADR-0038): o extra e o preco
       da 1 HORA do mesmo programa, no patamar vigente.

    A duracao do pacote entra so como PORTA (`aceita_fetiche_pago`), nao mais como divisor: o
    extra e o mesmo em 1h, 2h, 3h ou pernoite.

    **REGIME UNICO desde o ADR-0039**: composicao (casal/menage, `cobra_por_pessoa`) nao tem mais
    aritmetica propria -- a 2a pessoa custa o mesmo que qualquer outro extra, e o pacote NAO
    dobra. Por isso nem `cobra_por_pessoa` nem `preco_pacote` sao parametros daqui: nao existe
    mais nenhuma conta que dependa do preco do pacote. A flag continua no catalogo, mas como
    CLASSIFICACAO (a secao "Por pessoa" do `<fetiches>`, o `composicao_em_pauta`, o gate
    `<sem_menage>`), nunca como regime de preco. E preco CADASTRADO de composicao passou a ser o
    TOTAL do extra (o `x 2` morreu junto): uma coluna, uma regra.

    **None = nao existe extra nesta linha** -- nao e "extra zero". Acontece em duracao < 1h
    (`aceita_fetiche_pago`) e quando o programa NAO TEM linha de 1h cadastrada (fail-closed: o
    extra E a uma hora; sem ela, nao existe extra derivado a cotar). Cada chamador decide o que
    fazer com a recusa, e o tipo obriga a decidir: o render OMITE a linha, o guard nao legitima
    o total dela, o painel devolve 409 (gravar NULL diria "incluso") e o fechamento descarta o
    fetiche com warning.
    """
    if not aceita_fetiche_pago(duracao_horas):
        return None
    cadastrado = preco_cadastrado_de_fetiche(preco_cadastrado)
    if cadastrado is None:
        return calcular_preco_extra_fetiche(
            linha_de_uma_hora,
            duracao_horas,
            patamar=patamar,
        )
    return cadastrado


def calcular_preco_extra_fetiche(
    linha_de_uma_hora: LinhaDeTabela | None,
    duracao_horas: Any,
    *,
    patamar: Patamar = "cheio",
) -> Decimal | None:
    """Extra DERIVADO de um fetiche pago sem preco cadastrado (ADR-0038; `extra_de_fetiche` e o
    site unico a chamar): **o preco da linha de 1 HORA do mesmo programa, no patamar vigente**.
    Fixo em relacao a duracao do pacote -- 1 fetiche na 3h da Catarina soma os mesmos R$400 que
    somaria na 1h dela.

    POR QUE mudou (decisao do dono do produto, 11/08/2026, revisa o ADR-0030). A formula antiga
    era preco-hora do pacote (`preco_tabela / horas`) e ela COINCIDIA POR ACIDENTE justamente
    onde a tabela e linear -- 400/1h e 800/2h dao os mesmos R$400 -- o que a fez parecer certa
    por um ano. Ela diverge onde o preco DEIXA de ser linear, que e o desenho normal de tabela
    (pacote maior, preco-hora menor, ADR-0004): a 3h a R$1.000 daria +R$333 e o pernoite a
    R$2.000 daria +R$333, cobrando pelo MESMO ato menos do que a 1h cobra. E o extra tambem nao
    acompanhava o desconto -- pacote negociado para baixo com extra de tabela cheia produz um
    total que nao existe em lugar nenhum.

    PATAMAR e estagio, nao percentual (`valor_no_patamar`): o extra e o valor da 1h NAQUELE
    estagio (cheio / degrau / piso), nunca o extra cheio multiplicado pelo fator do pacote. Na
    3h da Catarina no piso o total e 900 + 300 = R$1.200, e nao 900 + 360 (o 0,9 da linha de 3h
    aplicado ao extra) -- o 360 nao e preco de nada.

    Sem `linha_de_uma_hora` (programa sem linha de 1h cadastrada) devolve None, fail-closed: o
    extra E a uma hora. Sem ela nao ha o que derivar, e inventar uma base (preco-hora, o pacote
    inteiro) e exatamente o que este ADR removeu.

    COMPOSICAO (casal/menage, `cobra_por_pessoa`) passa por aqui como qualquer outro fetiche
    desde o ADR-0039: a 2a pessoa custa a linha de 1h do mesmo programa, no patamar vigente, e o
    pacote NAO dobra mais. Consequencia dura: composicao passou a DEPENDER da linha de 1h -- o
    regime antigo (o pacote inteiro) funcionava sem ela e agora cai no mesmo None fail-closed dos
    atos, no render, no guard, no painel e no fechamento.

    Mudanca de conta aqui muda o render (`persona.py:_grupos_de_extra`) E o guard
    (`output_guard.py:_valores_legitimos`) juntos, nunca um so."""
    if not aceita_fetiche_pago(duracao_horas):
        return None
    if linha_de_uma_hora is None:
        return None
    preco_uma_hora, minimo_uma_hora = linha_de_uma_hora
    return valor_no_patamar(preco_uma_hora, minimo_uma_hora, patamar)


# -----------------------------------------------------------------------------
# Rastro do fetiche no fechamento (pendencia 4 do ADR-0030)
# -----------------------------------------------------------------------------

# Travessao (U+2014), meia-risca (U+2013), hifen nao-separavel (U+2011), traco de figura
# (U+2012) e sinal de menos (U+2212) -> hifen comum. Os cinco sao o que editor/Word produzem
# num copy-paste do rotulo do painel.
_TRACOS_PARA_HIFEN = {cp: "-" for cp in (0x2014, 0x2013, 0x2011, 0x2012, 0x2212)}


def _chave_de_fetiche(nome: str) -> str:
    """Forma canonica p/ casar o nome que a IA registrou com o nome CADASTRADO da modelo.

    Sem acento, casefold, whitespace colapsado -- 'inversao' casa 'Inversão'. Duplica de
    proposito a normalizacao de `agente/_normalizar.py` (mesmo motivo de core/ancora_feedback e
    workers/coordenador): `dominio/` nao importa `barra.agente` (dominio/CLAUDE.md).

    Traco dobrado tambem (11/08/2026), o que a normalizacao do agente NAO faz: os itens de
    COMPOSICAO do catalogo tem travessao no rotulo ("Acompanhante dele — mulher") e nada obriga a
    extracao a reproduzir U+2014 em vez de um hifen comum. Sem dobrar, "Acompanhante dele -
    mulher" nao casaria a linha cadastrada e o fetiche sumiria do breakdown do atendimento em
    silencio (so o warning do chamador). Dobrar aqui e barato e nao afrouxa nada: o casamento
    continua sendo por nome inteiro contra `modelo_fetiches`, closed-world.
    """
    decomposto = unicodedata.normalize("NFKD", nome)
    sem_acento = "".join(c for c in decomposto if not unicodedata.combining(c))
    sem_traco = sem_acento.translate(_TRACOS_PARA_HIFEN)
    return re.sub(r"\s+", " ", sem_traco.casefold()).strip()


async def _nomes_de_fetiche_em_pauta(conn: AsyncConnection[Any], atendimento_id: UUID) -> list[str]:
    """Os nomes que a extracao registrou na conversa, em ordem, sem repetir.

    `fetiches_em_pauta` nao tem coluna em `atendimentos` (como `motivo_perda_candidato`): vive no
    payload do evento `extracao_registrada`. A leitura e a UNIAO dos turnos, monotonica como
    `intencao`/`sinais_qualificacao` -- a extracao manda o que esta em pauta NAQUELE turno e o
    silencio dos turnos seguintes nao apaga o que ja foi pedido.
    """
    res = await conn.execute(
        """
        SELECT payload -> 'fetiches_em_pauta' AS nomes
          FROM barravips.eventos
         WHERE atendimento_id = %s
           AND tipo = 'extracao_registrada'
           AND payload -> 'fetiches_em_pauta' IS NOT NULL
         ORDER BY created_at
        """,
        (atendimento_id,),
    )
    vistos: dict[str, str] = {}
    for row in await res.fetchall():
        nomes = row["nomes"]
        if not isinstance(nomes, list):
            continue
        for nome in nomes:
            if isinstance(nome, str) and _chave_de_fetiche(nome):
                vistos.setdefault(_chave_de_fetiche(nome), nome)
    return list(vistos.values())


async def linha_de_uma_hora(
    conn: AsyncConnection[Any], modelo_id: Any, programa_id: Any
) -> LinhaDeTabela | None:
    """A linha de 1 HORA daquele programa na tabela da modelo, ou None se ela nao existe.

    E a base do extra derivado (ADR-0038). Chave composta de `modelo_programas` (modelo x
    programa x duracao) => no maximo uma linha. `preco_minimo` vem junto porque o extra
    acompanha o patamar (`valor_no_patamar`), e o patamar depende do piso absoluto da linha.
    """
    res = await conn.execute(
        """
        SELECT mp.preco, mp.preco_minimo
          FROM barravips.modelo_programas mp
          JOIN barravips.duracoes d ON d.id = mp.duracao_id
         WHERE mp.modelo_id = %s AND mp.programa_id = %s AND d.horas = %s
        """,
        (modelo_id, programa_id, DURACAO_MINIMA_FETICHE_PAGO),
    )
    row = await res.fetchone()
    if row is None or row["preco"] is None:
        return None
    return (
        Decimal(str(row["preco"])),
        None if row["preco_minimo"] is None else Decimal(str(row["preco_minimo"])),
    )


@dataclass(frozen=True)
class BaseDoPacote:
    """O pacote vendido, do jeito que a conta do extra precisa dele.

    `horas` e a PORTA (`aceita_fetiche_pago`); `linha_de_uma_hora` e a base do extra derivado
    (ADR-0038) e vem None quando nao da p/ dizer de QUAL programa o pacote e (varios servicos, ou
    duracao com mais de uma linha) -- fail-closed, o fetiche pago sem cadastro e descartado com
    warning.

    O `preco` do pacote saiu daqui com o ADR-0039: ele so servia ao regime por-pessoa (que dobrava
    o pacote) e, sem esse regime, nenhuma conta de extra depende mais do preco do pacote. O
    fail-closed de preco AMBIGUO continua em `_base_do_pacote` -- ele nao existe para achar um
    numero, e sim para saber se da p/ dizer QUAL pacote foi vendido.
    """

    horas: Decimal
    linha_de_uma_hora: LinhaDeTabela | None


async def _base_do_pacote(conn: AsyncConnection[Any], atendimento_id: UUID) -> BaseDoPacote | None:
    """O pacote vendido (`BaseDoPacote`), ou None quando nao da p/ dizer qual e.

    Prefere `atendimento_servicos` (a MESMA base do painel, `routes.py:adicionar_fetiche`); sem
    servico registrado -- o caso normal do fechamento pela IA, que nao escreve nessa tabela --
    deriva o PRECO DE TABELA de `modelo_programas` pela `duracao_horas` do atendimento, com as
    mesmas condicoes fail-closed de `contraproposta_da_escada`: sem duracao fechada, sem programa
    naquela duracao ou com mais de um preco na duracao devolve None (quem chama descarta com
    warning).

    A IDENTIDADE do programa e mais exigente que o preco: a linha de 1h so e resolvida quando ha
    exatamente UM servico vendido (ou UMA linha na duracao), porque "a 1h do mesmo programa" nao
    existe para um pacote que e a soma de dois. Preco ambiguo derruba tudo; programa ambiguo
    derruba so o extra derivado.

    `valor_acordado` NAO entra aqui, nunca: ele e o Valor final (ja pode conter extra e desconto),
    e o CONTEXT.md proibe confundi-lo com Preco de tabela. Usa-lo como base inflaria o proprio
    extra -- no caso do ADR-0030 (800 = pacote 400 + Inversao) a base sairia 800/1h.

    So serve ao extra DERIVADO (fetiche pago sem preco cadastrado); com preco cadastrado o extra
    nao depende disto.

    Le a duracao INTEIRA (`apenas_presenciais=False`), pelo mesmo motivo do `_piso_do_pacote`: e
    um atendimento JA fechado, que pode ser a vídeo chamada, e o numero que sai daqui vira
    `preco_snapshot` gravado. Presumir o pacote presencial gravaria o breakdown de um pacote que
    nao foi o vendido -- e o fail-closed (None => o ato pago sem cadastro e descartado com
    warning) e a resposta certa quando a duracao tem mais de uma linha.
    """
    res = await conn.execute(
        """
        SELECT ats.programa_id, ats.preco_snapshot, d.horas
          FROM barravips.atendimento_servicos ats
          JOIN barravips.duracoes d ON d.id = ats.duracao_id
         WHERE ats.atendimento_id = %s
        """,
        (atendimento_id,),
    )
    servicos = await res.fetchall()
    res = await conn.execute(
        "SELECT modelo_id, duracao_horas FROM barravips.atendimentos WHERE id = %s",
        (atendimento_id,),
    )
    atendimento = await res.fetchone()
    if atendimento is None:
        return None
    programa_id: Any = None
    if servicos:
        horas = max(Decimal(str(s["horas"])) for s in servicos)
        if len(servicos) == 1:
            programa_id = servicos[0]["programa_id"]
    else:
        if atendimento["duracao_horas"] is None:
            return None
        # Fail-closed igual ao teto/degrau: a duracao precisa ter UM preco de tabela so, senao
        # nao da p/ dizer QUAL pacote foi vendido. O preco em si ja nao vai para lugar nenhum
        # (ADR-0039 tirou o `preco` da `BaseDoPacote`), mas a AMBIGUIDADE dele continua sendo
        # motivo de recusa: duas linhas de precos diferentes na mesma duracao sao dois pacotes.
        linhas = await _linhas_da_duracao(
            conn,
            atendimento["modelo_id"],
            atendimento["duracao_horas"],
            apenas_presenciais=False,
        )
        if not linhas or linhas[0]["preco"] != linhas[-1]["preco"]:
            return None
        horas = Decimal(str(atendimento["duracao_horas"]))
        if len(linhas) == 1:
            programa_id = linhas[0]["programa_id"]
    if horas <= 0:
        return None
    uma_hora = (
        None
        if programa_id is None
        else await linha_de_uma_hora(conn, atendimento["modelo_id"], programa_id)
    )
    return BaseDoPacote(horas=horas, linha_de_uma_hora=uma_hora)


async def registrar_fetiches_do_fechamento(conn: AsyncConnection[Any], atendimento_id: UUID) -> int:
    """Grava em `atendimento_fetiches` os extras que a conversa combinou. Devolve quantos entraram.

    Pendencia 4 do ADR-0030 (achado 10c do diagnostico de 11/08/2026): `valor_acordado=800` com
    `duracao_horas=1` chegava ao painel sem dizer que R$350 eram a Inversao. A extracao passou a
    registrar `fetiches_em_pauta` (nomes do CADASTRO) e aqui, no fechamento, cada nome e resolvido
    contra `modelo_fetiches` -- closed-world: nome que a modelo nao tem cadastrado e DESCARTADO
    (warning), nunca inventa item. O `preco_snapshot` sai de `extra_de_fetiche`, o site unico que
    o painel tambem usa, entao o breakdown bate com o que a IA cotou.

    Idempotente por construcao: `ON CONFLICT DO NOTHING` sobre a UNIQUE (atendimento_id,
    fetiche_id) -- reexecutar o fechamento nao duplica, e o vinculo que Fernando ja tenha feito a
    mao no painel (com o preco que ELE decidiu) nao e sobrescrito.
    """
    nomes = await _nomes_de_fetiche_em_pauta(conn, atendimento_id)
    if not nomes:
        return 0
    res = await conn.execute(
        """
        SELECT mf.fetiche_id, f.nome, mf.preco, f.cobra_por_pessoa
          FROM barravips.atendimentos a
          JOIN barravips.modelo_fetiches mf ON mf.modelo_id = a.modelo_id
          JOIN barravips.fetiches f ON f.id = mf.fetiche_id
         WHERE a.id = %s
        """,
        (atendimento_id,),
    )
    cardapio = {_chave_de_fetiche(r["nome"]): r for r in await res.fetchall()}
    # Resolvida no maximo UMA vez, e so quando algum fetiche pago precisa do extra derivado
    # (com preco cadastrado o extra nao depende do pacote).
    base: BaseDoPacote | None = None
    base_resolvida = False
    gravados = 0
    for nome in nomes:
        item = cardapio.get(_chave_de_fetiche(nome))
        if item is None:
            # Alucinacao do extrator (ou fetiche que a modelo nao faz): silencio, so o warning.
            logger.warning(
                "fetiche_em_pauta fora do cadastro da modelo, descartado",
                extra={"atendimento_id": str(atendimento_id), "nome": nome},
            )
            continue
        preco_snapshot: Decimal | None = None
        if item["preco"] is not None:
            # NULL = incluso (snapshot NULL). NOT NULL = pago: o extra vem do preco cadastrado
            # quando ha numero de verdade na coluna; o sentinel de flag cai no fallback derivado,
            # que precisa do pacote vendido.
            if preco_cadastrado_de_fetiche(item["preco"]) is None:
                if not base_resolvida:
                    base = await _base_do_pacote(conn, atendimento_id)
                    base_resolvida = True
                if base is None:
                    logger.warning(
                        "fetiche pago sem preco cadastrado e sem pacote p/ derivar, descartado",
                        extra={"atendimento_id": str(atendimento_id), "nome": item["nome"]},
                    )
                    continue
            preco_snapshot = extra_de_fetiche(
                base.linha_de_uma_hora if base else None,
                base.horas if base else DURACAO_MINIMA_FETICHE_PAGO,
                preco_cadastrado=item["preco"],
            )
            if preco_snapshot is None:
                # Sem extra a gravar, e gravar NULL aqui diria "incluso" no breakdown do painel.
                # Duas causas, ambas fail-closed: pacote < 1h (decisao 11/08/2026) e programa sem
                # linha de 1h p/ derivar o extra (ADR-0038) -- inclusive o pacote de programa
                # ambiguo, que nem chega a ter uma 1h "do mesmo programa". Fica de fora do rastro,
                # com o warning, como o pago sem pacote acima.
                #
                # CAMINHO NOVO desde o ADR-0039: a COMPOSICAO (`cobra_por_pessoa`) cai aqui
                # tambem. No regime antigo o extra dela era o pacote inteiro e nao dependia da 1h,
                # entao ela gravava mesmo em programa sem 1h cadastrada; agora ela e o mesmo extra
                # dos atos e some pelo mesmo motivo. O `cobra_por_pessoa` do cardapio nao entra
                # mais na conta -- fica so como classificacao.
                logger.warning(
                    "fetiche pago sem extra derivavel (pacote < 1h ou sem linha de 1h), descartado",
                    extra={
                        "atendimento_id": str(atendimento_id),
                        "nome": item["nome"],
                        "cobra_por_pessoa": bool(item["cobra_por_pessoa"]),
                    },
                )
                continue
        result = await conn.execute(
            """
            INSERT INTO barravips.atendimento_fetiches
                   (atendimento_id, fetiche_id, preco_snapshot)
            VALUES (%s, %s, %s)
            ON CONFLICT (atendimento_id, fetiche_id) DO NOTHING
            """,
            (atendimento_id, item["fetiche_id"], preco_snapshot),
        )
        gravados += result.rowcount
    return gravados


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
    """Ressuscita um interno morto por timeout automatico, pela foto de portaria tardia (ADR 0027).

    A foto chegou DEPOIS de o timeout (ADR 0024) marcar o #1 interno como Perdido/sumiu e
    cancelar o bloqueio. Se o cliente literalmente chegou ao local, orfanar a prova de
    chegada e fragmentar num novo #N seria errado operacionalmente.

    Reconecta o atendimento — volta a Em_execucao, ia_pausada=true (modelo_em_atendimento),
    reativa o bloqueio cancelado e abre a escalada owner do card 'chegada' — SE E SO SE:
      - a morte foi por timeout AUTOMATICO — `auto_timeout_interno` (45min pos-horario, ADR
        0024) ou `auto_timeout` (24h de silencio). O que se respeita e o Perdido HUMANO, nao o
        mecanismo: as duas mortes deixam rastro identico e o timeout de 24h alcanca o interno
        agendado, entao exigir so a primeira orfanava a foto com o cliente na portaria
        (emenda 11/08/2026 ao ADR 0027);
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
                   -- O critério do ADR 0027 é "morte AUTOMÁTICA por timeout", não "qual cron":
                   -- o que se respeita é o Perdido HUMANO/explícito. O `timeout_longo` (24h de
                   -- silêncio) grava `auto_timeout` e o interno (ADR 0024) grava
                   -- `auto_timeout_interno`; os dois deixam exatamente o mesmo rastro (Perdido/
                   -- sumiu + bloqueio cancelado). Exigir só a fonte do interno deixava a foto de
                   -- portaria órfã quando quem matou foi o cron de 24h. As guardas que fazem o
                   -- filtro real continuam valendo: interno, bloqueio `cancelado`, dentro do
                   -- `b.fim` e slot livre (NOT EXISTS + EXCLUDE como backstop).
                   AND a.fonte_decisao_ultima_transicao IN ('auto_timeout_interno', 'auto_timeout')
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
    ANTERIOR ao fechamento: so a cotacao da fase de venda ancora o reengajamento; um `R$` que
    aparece depois (ex.: reconfirmar valor em Aguardando_confirmacao) nao cria ancora espuria.

    `Novo` entrou na lista em 12/08 (medido ao vivo): a IA cota na PRIMEIRA bolha da conversa
    ("400 1h no meu local", antes de a extracao ter gravado intencao/tipo), e nesse instante o
    atendimento ainda esta em `Novo` — o carimbo caia no vazio. Dois turnos depois, quando o
    cliente cravava a hora, a transicao para `Aguardando_confirmacao` batia no guard
    `CotacaoAusente` (preco "nunca dito"), a transacao inteira revertia e a HORA se perdia: a IA
    dizia "Confirmado amor" com o banco sem reserva nenhuma. `Novo` e fase de venda como as
    outras duas; o que o gate protege e o pos-fechamento.
    """
    result = await conn.execute(
        """
        UPDATE barravips.atendimentos
           SET cotacao_enviada_em = now()
         WHERE id = %s AND cotacao_enviada_em IS NULL
           AND estado IN ('Novo', 'Triagem', 'Qualificado')
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


async def gravar_valor_do_aceite(
    conn: AsyncConnection[Any], atendimento_id: UUID, valor: int
) -> bool:
    """Grava `valor_acordado` = o valor que o CLIENTE nomeou e a IA ACEITOU na fala já despachada
    (ADR-0040). Devolve True quando ESTA chamada moveu a mesa.

    Irmão dos contadores acima e pelo mesmo motivo: o número da venda é decidido pela FALA DA IA do
    próprio turno, e a extração é cega para ela por contrato (a janela dela exclui a fala do turno
    corrente, `agente/nos/extrair.py`). No trace 93fa67dd a IA cotou 800, ele disse "faz 700 que eu
    vou", ela fechou em 700 — e a extração, que só viu a fala DELE, registrou `aceita_valor` com
    `proxima_acao_esperada="Avaliar a contraproposta de 700"`: do ponto de vista dela ainda não
    havia aceite. `valor_acordado` ficou NULL e a venda de 700 não existiu no banco. Aqui o valor
    entra pela porta determinística — sem LLM nenhum decidindo número, como manda o ADR-0037/0038.

    Quem decide SE chamar é `workers/envio.py`, e o predicado tem DUAS pernas independentes
    (nenhuma basta sozinha, e é o que separa aceite de menção):
      (a) o `<valor_dele_serve>` deste turno rendeu ESTE número no prompt (`valor_dele_no_prompt`,
          carimbado pelo prepare_context) — o sistema já provou, contra a tabela, que o número é
          DELE e cai em `[piso, mesa)`;
      (b) o número saiu como OFERTA na bolha que de fato foi despachada
          (`precos_ofertados_na_fala`, que descarta cláusula negada).
    Sem (a), "acima do piso" viraria prova de aceite — foi exatamente o bug do valor fantasma (a IA
    RECUSOU 300, que estava acima do piso, e o extrator gravou 300). Sem (b), bastaria o sistema ter
    MANDADO aceitar: ela pode ter recusado assim mesmo, e o que vale é o que o cliente leu.

    Sobrescreve a mesa de propósito — é o único caminho por onde ela DESCE, e desce só até um número
    que o cliente nomeou e que o piso já aprovou (o `aceite_do_valor_dele` exige `proposto < mesa` e
    `proposto >= piso`). Idempotente por valor (`IS DISTINCT FROM`), e o chamador ainda o pendura no
    `inseriu` do INSERT da bolha, como os contadores."""
    res = await conn.execute(
        """
        UPDATE barravips.atendimentos
           SET valor_acordado = %s
         WHERE id = %s AND valor_acordado IS DISTINCT FROM %s
        """,
        (valor, atendimento_id, valor),
    )
    return res.rowcount > 0


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
    """Carimba `amiga_ofertada_em=now()` na 1a oferta da amiga (<composicoes>: uma vez por negociacao).
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
