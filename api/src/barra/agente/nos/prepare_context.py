"""No prepare_context: dono unico do contexto + gate de pausa.

O coordenador invoca o grafo com `{"messages": []}`; este no monta tudo do zero a cada
turno (sem checkpointer, 01 §6.7) a partir do Postgres.

M0-T4:
    1. Gate de pausa (02 §1): le `ia_pausada` do atendimento. Pausado -> Command(goto=END),
       sem montar contexto. Sem flag `_pausada` no state (roteamento por Command, 09 §4.1).
    2. Prefixo system: BP_GERAL fundido (persona+regras+FAQ) via build_system_messages.
    3. Janela deslizante 20 (02 §4), traduzida para HumanMessage/AIMessage, em ordem
       cronologica, isolada pelo par (cliente_id, modelo_id) JUNTOS (agente/CLAUDE.md).
       BP_JANELA: cache_control na penultima mensagem (`marcar_cache_na_penultima`).

M1-T2:
    4. Contexto dinamico (02 §5): estado do atendimento + cliente + agenda 48h resolvidos por
       queries (reusando a mesma conexao) e concatenados no ULTIMO HumanMessage da janela
       (a msg atual do cliente), DEPOIS do prefixo cacheavel ("stable first, volatile last").
       SEM `cache_control` -- texto volatil, fora do prefixo (03 §3.4/§4.4).

M2-T1 (este escopo):
    5. BP3 por-modelo (03 §2/§3.3): identidade (nome/idade/idiomas/localizacao/tipos_aceitos) +
       programas/precos do modelo_id, montados na MESMA conexao e passados como 3º bloco system
       (cacheado por `ttl_modelo`), DEPOIS dos blocos GERAIS BP1/BP2. POR-MODELO, nao por par.

M3g (este escopo):
    2b. Classificacao de disclosure/jailbreak (10 §8): regex sobre a cauda de HumanMessages
        da janela; grava (_categoria/_confianca) no state para o intercept_disclosure rotear
        canned/escala/llm. Sem nova query.

Adiado: cache condicional da cauda (BP4, P1, 03 §4.4).
"""

from typing import Any, Literal

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langgraph.graph import END
from langgraph.runtime import Runtime
from langgraph.types import Command
from psycopg import AsyncConnection

from barra.core.db import conexao
from barra.core.metrics import PERSONA_DRIFT_REMINDER
from barra.dominio.conversas.modelos import DirecaoMensagem
from barra.settings import get_settings

from .._classificador import classificar_janela
from ..contexto import ContextAgente
from ..estado import EstadoAgente
from ..llm import build_system_messages, marcar_cache_na_penultima
from ..persona import (
    IdentidadeModelo,
    render_bp3,
    render_contexto_dinamico,
    render_prefixo_geral,
)


async def prepare_context(
    state: EstadoAgente, runtime: Runtime[ContextAgente]
) -> Command[Literal["intercept_disclosure", "__end__"]]:
    """Gate de pausa (early exit) + monta system GERAL + janela deslizante traduzida.

    Roteia por Command nos DOIS caminhos (09 §4.1): pausa -> END, normal ->
    intercept_disclosure. Tem que ser Command tambem no caminho normal porque o no nao tem
    aresta estatica de saida: uma aresta `prepare_context -> intercept_disclosure` faria
    fan-out (intercept rodaria EM PARALELO ao END) e o turno chamaria o llm mesmo pausado.
    """
    ctx = runtime.context

    async with conexao(ctx.db_pool) as conn:
        # 1. Gate de pausa (02 §1): ia_pausada vive no atendimento. Pega pausa concorrente de
        #    pipelines sem lock (Pix/foto portaria). Webhook fino (M3c) -> atendimento_id None
        #    -> nada a pausar, segue o turno.
        if ctx.atendimento_id is not None:
            res = await conn.execute(
                "SELECT ia_pausada FROM barravips.atendimentos WHERE id = %s",
                (ctx.atendimento_id,),
            )
            row = await res.fetchone()
            if row and row["ia_pausada"]:
                # END e sys.intern("__end__") tipado `str` upstream; o Literal do retorno o cobre.
                return Command(goto=END)  # type: ignore[arg-type]

        # 2. Janela deslizante (02 §4) — isolada pelo par (cliente, modelo).
        linhas = await carregar_mensagens(conn, ctx.cliente_id, ctx.modelo_id)
        mensagens = traduzir_mensagens(linhas)

        # 2b. Classificacao de disclosure/jailbreak (10 §8): regex sobre a cauda de
        #     HumanMessages da janela, ANTES de anexar contexto/reminder (cauda limpa). Grava
        #     (_categoria/_confianca) no state; o intercept_disclosure (10 §2-3) consome e roteia
        #     canned/escala/llm. Sem nova query — reusa a janela ja traduzida.
        categoria, confianca = classificar_janela(mensagens)

        # 3. Contexto dinâmico (02 §5): resolve estado/cliente/agenda na MESMA conexão e
        #    concatena no último HumanMessage (sem cache_control — texto volátil na cauda).
        #    Devolve a `fase` (= estado do atendimento) já resolvida, p/ o reminder não requerer.
        mensagens, fase = await _anexar_contexto_dinamico(conn, ctx, mensagens)

        # 3b. Reminder anti-drift (03 §10): PREPEND o <lembrete_silencioso> no MESMO último
        #     HumanMessage, depois do contexto dinâmico (ordem final: lembrete → msg → contexto),
        #     só com ≥8 AIMessages na janela. Volátil — fica na cauda, fora do prefixo cacheável.
        mensagens = _injetar_reminder_se_necessario(mensagens, fase)

        # 4. BP_MODELO por-modelo (03 §2/§3.3): identidade + programas do modelo_id, reusando a
        #    conexão. É POR-MODELO (filtra modelo_id), não fura o isolamento por par (que vale
        #    para histórico do cliente, já filtrado por cliente+modelo na janela e no contexto).
        modelo_md = await _carregar_bp3(conn, ctx.modelo_id)

    # 5. BP_JANELA (cache na penúltima): aproveita o slot liberado pela fusão BP_GERAL (antes
    #    era BP1+BP2 separados). Só efetivo com janela ≥ 2; a última msg fica volátil (contexto
    #    dinâmico + reminder), penúltima entra no cache. TTL = `cache_ttl_modelo` (mesma cadência
    #    do BP_MODELO que vem logo antes — respeita "TTL maior antes do menor" da Anthropic).
    settings = get_settings()
    mensagens = marcar_cache_na_penultima(mensagens, ttl=settings.cache_ttl_modelo)

    # 6. Prefixo system: BP_GERAL fundido (persona+regras+FAQ byte-idêntico p/ todas —
    #    agente/CLAUDE.md) + BP_MODELO. Ordem estável: geral antes do por-modelo (invariante).
    system_msgs = build_system_messages(
        geral_md=render_prefixo_geral(),
        ttl_geral=settings.cache_ttl_geral,
        modelo_md=modelo_md,
        ttl_modelo=settings.cache_ttl_modelo,
    )
    return Command(
        goto="intercept_disclosure",
        update={
            "messages": [*system_msgs, *mensagens],
            "_categoria": categoria,
            "_confianca": confianca,
        },
    )


async def carregar_mensagens(
    conn: AsyncConnection[Any], cliente_id: str, modelo_id: str
) -> list[dict[str, Any]]:
    """Janela deslizante 20 do par (cliente, modelo), em ordem cronologica (02 §4.1/§4.2).

    Deriva conversa_id pelo par (cliente_id, modelo_id) JUNTOS (isolamento, agente/CLAUDE.md):
    a IA da modelo A nunca le historico do mesmo cliente com a modelo B. O `ORDER BY
    created_at DESC, id DESC` + revert em Python da a ordem cronologica; o desempate por `id`
    (uuidv7, time-ordered) torna o render deterministico — pre-requisito do cache (02 §4.1).
    """
    res = await conn.execute(
        """
        SELECT m.id, m.direcao, m.tipo, m.conteudo, m.media_object_key, m.created_at
          FROM barravips.mensagens m
          JOIN barravips.conversas c ON c.id = m.conversa_id
         WHERE c.cliente_id = %s AND c.modelo_id = %s
         ORDER BY m.created_at DESC, m.id DESC
         LIMIT 20
        """,
        (cliente_id, modelo_id),
    )
    linhas = await res.fetchall()
    linhas.reverse()  # cronologico (mais antiga primeiro) p/ entrada do grafo
    return linhas


def traduzir_mensagens(linhas: list[dict[str, Any]]) -> list[BaseMessage]:
    """Traduz linhas de `mensagens` para LangChain messages (02 §4.2).

    Mapeamento pela coluna `direcao` (enum DirecaoMensagem):
    - cliente -> HumanMessage (audio sem transcricao/imagem viram placeholder de contexto);
    - ia -> AIMessage;
    - modelo_manual -> AIMessage COM PREFIXO. A msg manual da modelo saiu no MESMO numero da
      IA (turno assistant), mas o prefixo a distingue para a IA nao se atribuir o que a
      modelo disse (decisao de estado, 02 §4.2).
    """
    out: list[BaseMessage] = []
    for linha in linhas:
        direcao = linha["direcao"]
        if direcao == DirecaoMensagem.cliente:
            conteudo = linha["conteudo"] or ""
            if linha["tipo"] == "audio":
                # transcricao falhou/nao chegou -> placeholder so de contexto; a resposta ao
                # audio falho do turno atual e canned (06 §1.4), nao via LLM.
                conteudo = (
                    f"{conteudo}\n_(originalmente áudio)_"
                    if conteudo
                    else "[áudio que não consegui ouvir]"
                )
            elif linha["tipo"] == "imagem":
                # IA e cega a imagens no P0: com legenda, a legenda e o conteudo; sem, placeholder.
                conteudo = conteudo or "[imagem]"
            out.append(HumanMessage(content=conteudo, id=str(linha["id"])))
        elif direcao == DirecaoMensagem.ia:
            out.append(AIMessage(content=linha["conteudo"], id=str(linha["id"])))
        elif direcao == DirecaoMensagem.modelo_manual:
            out.append(
                AIMessage(
                    content=f"[mensagem manual da modelo]: {linha['conteudo']}",
                    id=str(linha["id"]),
                )
            )
        else:
            # Defesa: schema so permite cliente/ia/modelo_manual; chegar aqui e bug.
            raise ValueError(f"direcao desconhecida em mensagens.id={linha['id']}: {direcao!r}")
    return out


async def _anexar_contexto_dinamico(
    conn: AsyncConnection[Any], ctx: ContextAgente, mensagens: list[BaseMessage]
) -> tuple[list[BaseMessage], str | None]:
    """Resolve o contexto dinâmico do turno e concatena no último HumanMessage (02 §5).

    O contexto dinâmico (estado do atendimento, cliente, agenda das próximas 48h, data atual)
    é texto VOLÁTIL: vai na cauda do turno, depois do prefixo cacheável, SEM cache_control. Reusa a
    conexão já aberta. As queries de conversa/histórico filtram pelo par (cliente, modelo)
    JUNTOS (isolamento — agente/CLAUDE.md).

    Concatena no ÚLTIMO HumanMessage (a msg atual do cliente). Defesa: se a janela não tiver
    nenhum HumanMessage, anexa o contexto como novo HumanMessage no fim. Devolve também a `fase`
    (= `estado` do atendimento) já resolvida, p/ o reminder (03 §10) reusar sem nova query.
    """
    variaveis = await _resolver_variaveis(conn, ctx)
    texto = render_contexto_dinamico(**variaveis)
    fase = variaveis["estado"]

    for i in range(len(mensagens) - 1, -1, -1):
        msg = mensagens[i]
        if isinstance(msg, HumanMessage):
            anexadas = list(mensagens)
            anexadas[i] = HumanMessage(content=f"{msg.content}\n\n{texto}", id=msg.id)
            return anexadas, fase
    return [*mensagens, HumanMessage(content=texto)], fase


def _precisa_reminder(historico: list[BaseMessage]) -> bool:
    """Proativo (decisão grilling 2026-05-23): injeta a partir de ≥8 turnos da IA, SEM esperar
    sinal de drift (03 §10). Reagir só após o drift aparecer seria 1 turno atrasado — a mensagem
    quebrada já foi ao cliente. Conta de turnos da IA = AIMessages na janela (inclui o
    `modelo_manual`, já traduzido para AIMessage em traduzir_mensagens).
    """
    return sum(1 for m in historico if m.type == "ai") >= 8


def _injetar_reminder_se_necessario(
    historico: list[BaseMessage], fase: str | None
) -> list[BaseMessage]:
    """Prepende o <lembrete_silencioso> no último HumanMessage acima do limiar (03 §10).

    Combate persona drift em conversas longas. Vai no último HumanMessage (cauda volátil, sem
    cache_control); como roda DEPOIS de _anexar_contexto_dinamico, o conteúdo final fica
    lembrete → msg do cliente → contexto dinâmico, num único HumanMessage de cauda. `fase` é o
    estado do atendimento (reusado do contexto dinâmico). Sem HumanMessage na janela → no-op.
    """
    if not _precisa_reminder(historico):
        return historico

    ultima_user_idx = next(
        (i for i in range(len(historico) - 1, -1, -1) if historico[i].type == "human"),
        None,
    )
    if ultima_user_idx is None:
        return historico

    ultima = historico[ultima_user_idx]
    novo_conteudo = (
        f"<lembrete_silencioso>"
        f"Mantenha o tom WhatsApp informal e a persona. "
        f"Fase do atendimento: {fase}. "
        f"Responda direto, como amiga digitando no celular."
        f"</lembrete_silencioso>\n\n"
        f"{ultima.content}"
    )
    historico = list(historico)
    historico[ultima_user_idx] = HumanMessage(content=novo_conteudo, id=ultima.id)
    PERSONA_DRIFT_REMINDER.inc()
    return historico


async def _carregar_bp3(conn: AsyncConnection[Any], modelo_id: str) -> str:
    """Monta o BP3 por-modelo: identidade + programas do modelo_id (03 §2.1/§3.3).

    A coluna `tipo_atendimento_aceito` (banco) é mapeada para `tipos_aceitos` (dataclass). Os
    programas vêm do schema real (pós-0010): `modelo_programas`/`programas`/`duracoes` — a
    duração é entidade própria (`duracao_nome`), NÃO `programas.duracao_horas` (removida em
    0009; a query do §3.3 está desatualizada). O `ORDER BY` é determinístico (pré-req do cache:
    bytes estáveis no prefixo — agente/CLAUDE.md), espelhando o painel (dominio/modelos/routes).
    """
    res = await conn.execute(
        """
        SELECT nome, idade, idiomas, localizacao_operacional, tipo_atendimento_aceito
          FROM barravips.modelos
         WHERE id = %s
        """,
        (modelo_id,),
    )
    m = await res.fetchone() or {}
    identidade = IdentidadeModelo(
        nome=m["nome"],
        idade=m["idade"],
        idiomas=m.get("idiomas") or [],
        localizacao_operacional=m.get("localizacao_operacional"),
        tipos_aceitos=m.get("tipo_atendimento_aceito") or [],
    )

    res = await conn.execute(
        """
        SELECT p.nome, d.nome AS duracao_nome, mp.preco
          FROM barravips.modelo_programas mp
          JOIN barravips.programas p ON p.id = mp.programa_id
          JOIN barravips.duracoes d ON d.id = mp.duracao_id
         WHERE mp.modelo_id = %s
         ORDER BY p.categoria NULLS FIRST, p.nome ASC, d.ordem ASC
        """,
        (modelo_id,),
    )
    programas = await res.fetchall()

    # Fetiches que a modelo FAZ (ADR 0014 revisado): cardápio de venda por-modelo, com preço
    # opcional (NULL = incluso). Ordem determinística (pré-req do cache, igual aos programas).
    res = await conn.execute(
        """
        SELECT f.nome, mf.preco
          FROM barravips.modelo_fetiches mf
          JOIN barravips.fetiches f ON f.id = mf.fetiche_id
         WHERE mf.modelo_id = %s
         ORDER BY f.ordem ASC, f.nome ASC
        """,
        (modelo_id,),
    )
    fetiches = await res.fetchall()
    return render_bp3(identidade, programas, fetiches)


async def _resolver_variaveis(conn: AsyncConnection[Any], ctx: ContextAgente) -> dict[str, Any]:
    """Resolve as variáveis do template de contexto dinâmico via queries específicas (02 §5).

    `atendimento` só é consultado quando há `atendimento_id` (espelha a guarda do gate); no
    fluxo real o coordenador sempre o resolve antes de invocar o grafo (02 §7).
    """
    atendimento: dict[str, Any] = {}
    if ctx.atendimento_id is not None:
        res = await conn.execute(
            """
            SELECT numero_curto, estado, tipo_atendimento, urgencia, pix_status,
                   data_desejada, horario_desejado, endereco, bairro
              FROM barravips.atendimentos
             WHERE id = %s
            """,
            (ctx.atendimento_id,),
        )
        atendimento = await res.fetchone() or {}

    res = await conn.execute(
        """
        SELECT recorrente, observacoes_internas, ultimo_motivo_perda
          FROM barravips.conversas
         WHERE cliente_id = %s AND modelo_id = %s
        """,
        (ctx.cliente_id, ctx.modelo_id),
    )
    conversa = await res.fetchone() or {}

    res = await conn.execute(
        "SELECT nome FROM barravips.clientes WHERE id = %s",
        (ctx.cliente_id,),
    )
    cliente = await res.fetchone() or {}

    res = await conn.execute(
        """
        SELECT inicio, fim, estado
          FROM barravips.bloqueios
         WHERE modelo_id = %s
           AND estado IN ('bloqueado', 'em_atendimento')
           AND inicio >= now()
           AND inicio < now() + interval '48 hours'
         ORDER BY inicio
        """,
        (ctx.modelo_id,),
    )
    bloqueios = await res.fetchall()

    disponibilidade = await _resolver_disponibilidade(conn, ctx.modelo_id)

    historico = await _resumir_historico(conn, ctx.cliente_id, ctx.modelo_id)

    # data atual do banco (mesma conexão/relógio das janelas com now() acima): a IA escreve
    # datas absolutas em consultar_agenda e precisa da âncora de "hoje" (04 §2.1).
    res = await conn.execute("SELECT current_date AS hoje")
    hoje_row = await res.fetchone()
    data_atual = hoje_row["hoje"] if hoje_row else None

    return {
        "data_atual": data_atual,
        "numero_curto": atendimento.get("numero_curto"),
        "estado": atendimento.get("estado"),
        "tipo_atendimento": atendimento.get("tipo_atendimento"),
        "urgencia": atendimento.get("urgencia"),
        "pix_status": _pix_status_humano(atendimento.get("pix_status")),
        "data_desejada": atendimento.get("data_desejada"),
        "horario_desejado": atendimento.get("horario_desejado"),
        "endereco": atendimento.get("endereco"),
        "bairro": atendimento.get("bairro"),
        "recorrente": conversa.get("recorrente", False),
        "observacoes_internas": conversa.get("observacoes_internas"),
        "ultimo_motivo_perda": conversa.get("ultimo_motivo_perda"),
        "cliente_nome": cliente.get("nome"),
        "historico_anteriores": historico,
        "bloqueios": bloqueios,
        "disponibilidade": disponibilidade,
    }


# dia_semana segue EXTRACT(DOW): 0=domingo .. 6=sábado (ADR 0005).
_DIAS_SEMANA = ["dom", "seg", "ter", "qua", "qui", "sex", "sáb"]

# Mapa enum pix_status -> texto p/ a IA. Expor enum cru ("em_revisao", "validado") faz a IA
# adivinhar o significado; texto humano evita ruído na leitura da cauda volátil.
_PIX_STATUS_HUMANO = {
    "pendente": "ainda não pedido",
    "aguardando": "aguardando comprovante",
    "em_revisao": "comprovante em análise",
    "validado": "confirmado",
    "invalido": "comprovante recusado",
}


def _pix_status_humano(status: str | None) -> str:
    if status is None:
        return "não aplicável"
    return _PIX_STATUS_HUMANO.get(status, status)


async def _resolver_disponibilidade(
    conn: AsyncConnection[Any], modelo_id: str
) -> list[dict[str, Any]]:
    """Regras de disponibilidade da modelo, já legíveis, p/ a IA não sugerir fora (ADR 0005).

    Texto volátil na cauda (não cacheável). `ORDER BY` determinístico só por higiene de render;
    a cauda não entra no prefixo cacheável. Sem regra → lista vazia (template diz "sem restrição").
    """
    res = await conn.execute(
        """
        SELECT data_inicio, data_fim, dia_semana, hora_inicio, hora_fim
          FROM barravips.modelo_disponibilidade
         WHERE modelo_id = %s
         ORDER BY data_inicio, dia_semana, hora_inicio
        """,
        (modelo_id,),
    )
    return [
        {
            "dia": _DIAS_SEMANA[r["dia_semana"]],
            "hora_inicio": r["hora_inicio"].strftime("%H:%M"),
            "hora_fim": r["hora_fim"].strftime("%H:%M"),
            "data_inicio": r["data_inicio"].strftime("%d/%m/%Y"),
            "data_fim": r["data_fim"].strftime("%d/%m/%Y") if r["data_fim"] else None,
        }
        for r in await res.fetchall()
    ]


async def _resumir_historico(
    conn: AsyncConnection[Any], cliente_id: str, modelo_id: str
) -> str | None:
    """Resumo curto dos atendimentos terminais do par — ex.: "fechou 2x (R$1.2k), perdeu 1x".

    Substitui a antiga tool `consultar_cliente` (04 §2.2): `recorrente` (booleano) não
    distingue quem fechou de quem perdeu. Isolamento por par preservado (filtra cliente E
    modelo). `None` quando não há atendimento terminal.
    """
    res = await conn.execute(
        """
        SELECT estado, count(*) AS n, coalesce(sum(valor_final), 0) AS total
          FROM barravips.atendimentos
         WHERE cliente_id = %s AND modelo_id = %s
           AND estado IN ('Fechado', 'Perdido')
         GROUP BY estado
        """,
        (cliente_id, modelo_id),
    )
    rows = await res.fetchall()
    partes: list[str] = []
    for r in rows:
        if r["estado"] == "Fechado":
            partes.append(f"fechou {r['n']}x (R${_fmt_valor_curto(r['total'])})")
        elif r["estado"] == "Perdido":
            partes.append(f"perdeu {r['n']}x")
    return ", ".join(partes) if partes else None


def _fmt_valor_curto(total: Any) -> str:
    """Formata um total em reais de forma curta: 1200 -> "1.2k", 1000 -> "1k", 500 -> "500"."""
    valor = float(total)
    if valor >= 1000:
        return f"{valor / 1000:.1f}k".replace(".0k", "k")
    return str(int(valor))
