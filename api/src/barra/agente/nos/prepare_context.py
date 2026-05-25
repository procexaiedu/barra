"""No prepare_context: dono unico do contexto + gate de pausa.

O coordenador invoca o grafo com `{"messages": []}`; este no monta tudo do zero a cada
turno (sem checkpointer, 01 §6.7) a partir do Postgres.

M0-T4:
    1. Gate de pausa (02 §1): le `ia_pausada` do atendimento. Pausado -> Command(goto=END),
       sem montar contexto. Sem flag `_pausada` no state (roteamento por Command, 09 §4.1).
    2. Prefixo system GERAL: BP1 (persona+regras) + BP2 (FAQ) via build_system_messages.
    3. Janela deslizante 20 (02 §4), traduzida para HumanMessage/AIMessage, em ordem
       cronologica, isolada pelo par (cliente_id, modelo_id) JUNTOS (agente/CLAUDE.md).

M1-T2 (este escopo):
    4. Contexto dinamico (02 §5): estado do atendimento + cliente + agenda 48h resolvidos por
       queries (reusando a mesma conexao) e concatenados no ULTIMO HumanMessage da janela
       (a msg atual do cliente), DEPOIS do prefixo cacheavel ("stable first, volatile last").
       SEM `cache_control` -- texto volatil, fora do prefixo (03 §3.4/§4.4).

Adiado: BP3 por-modelo (M2-T1), reminder >=8 turnos no ultimo HumanMessage (M2-T2),
    cache condicional da cauda (BP3/BP4, M2-T1), classificacao de disclosure
    (`_categoria`/`_confianca`, M3g).
"""

from typing import Any, Literal

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langgraph.graph import END
from langgraph.runtime import Runtime
from langgraph.types import Command
from psycopg import AsyncConnection

from barra.core.db import conexao
from barra.dominio.conversas.modelos import DirecaoMensagem
from barra.settings import get_settings

from ..contexto import ContextAgente
from ..estado import EstadoAgente
from ..llm import build_system_messages
from ..persona import carregar_faq, render_contexto_dinamico, render_persona


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

        # 3. Contexto dinâmico (02 §5): resolve estado/cliente/agenda na MESMA conexão e
        #    concatena no último HumanMessage (sem cache_control — texto volátil na cauda).
        mensagens = await _anexar_contexto_dinamico(conn, ctx, mensagens)

    # 4. Prefixo system GERAL (BP1+BP2), byte-identico p/ todas as modelos (agente/CLAUDE.md).
    system_msgs = build_system_messages(
        geral_md=render_persona(),
        faq_md=carregar_faq(),
        ttl_geral=get_settings().cache_ttl_geral,
    )
    return Command(
        goto="intercept_disclosure",
        update={"messages": [*system_msgs, *mensagens]},
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
) -> list[BaseMessage]:
    """Resolve o contexto dinâmico do turno e concatena no último HumanMessage (02 §5).

    O contexto dinâmico (estado do atendimento, cliente, agenda das próximas 48h, data atual)
    é texto VOLÁTIL: vai na cauda do turno, depois do prefixo cacheável, SEM cache_control. Reusa a
    conexão já aberta. As queries de conversa/histórico filtram pelo par (cliente, modelo)
    JUNTOS (isolamento — agente/CLAUDE.md).

    Concatena no ÚLTIMO HumanMessage (a msg atual do cliente). Defesa: se a janela não tiver
    nenhum HumanMessage, anexa o contexto como novo HumanMessage no fim.
    """
    variaveis = await _resolver_variaveis(conn, ctx)
    texto = render_contexto_dinamico(**variaveis)

    for i in range(len(mensagens) - 1, -1, -1):
        msg = mensagens[i]
        if isinstance(msg, HumanMessage):
            anexadas = list(mensagens)
            anexadas[i] = HumanMessage(content=f"{msg.content}\n\n{texto}", id=msg.id)
            return anexadas
    return [*mensagens, HumanMessage(content=texto)]


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
        "pix_status": atendimento.get("pix_status"),
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
    }


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
