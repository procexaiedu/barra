"""Loop e2e: o agente conduz uma conversa multi-turn contra um cliente simulado.

Roda pelo CAMINHO FIEL (`evals.harness_fiel.rodar_turno_auditado`): cada turno passa por
`processar_turno` (lock, gate de pausa, drain/coalescing, refusal) e `enviar_turno` (output-guard
final, chunking, gravacao da bolha da IA) — o mesmo encanamento do WhatsApp. O seed continua vindo
de `evals.harness` (DB real; ROLLBACK e do caller). A cada iteracao: insere a msg do cliente, roda
UM turno, le o estado pos-turno e deixa o cliente reagir ao texto da IA. O grafo nao tem
checkpointer (P0): cada turno re-le a janela de `barravips.mensagens`, entao chamar o grafo varias
vezes na MESMA conn "lembra" os turnos.

O cenario pode declarar um RELOGIO (`agora` + `passo_min`/`offsets_min`) e uma AGENDA INICIAL
(`bloqueios`, `atendimento`) — ver `rodar_e2e`. Sem eles nada muda: relogio de parede e agenda
vazia, como nos cenarios anteriores a esta chave.

Uma fala do cliente pode ser um BURST (`list[str]`, ver `cliente.FalaDoCliente`): as bolhas descem
SEPARADAS ao turno (coalescing real do debounce, que o `rodar_turno_fiel` ja sabia fazer) e
`turnos_cliente` guarda o texto junto, que e o que os checks keyed por gatilho leem.

Para quando: (a) atinge a linha de chegada (`Aguardando_confirmacao`/`Confirmado`); (b) a IA
pausa (handoff/escala — `ia_pausada`); (c) o cliente encerra (sumiu/combinou); (d) estoura
`max_turnos`.

⚠️ §0: com o graph REAL isto gasta credito (1 ainvoke/turno) e exige TEST_DATABASE_URL. A
validacao offline injeta um chat FAKE no graph + ClienteRoteirizado — ver tests/agente/
test_e2e_conducao.py.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from psycopg import AsyncConnection

from evals.harness import Cenario, ResultadoTurno, seedar
from evals.harness_fiel import BolhaCliente, rodar_turno_auditado

from .cliente import ClienteSimulado, FalaDoCliente, texto_do_burst
from .perfil import ESTADOS_CONDUZIDOS, PerfilCaso, perfil_para_fixture

# Estado em que um caso e2e NASCE quando o cenario nao declara `atendimento`: e o que
# `perfil.perfil_para_fixture` escreve na fixture efemera e o que `persistencia.seed_caso_
# persistente` hardcoda no INSERT da corrida persistente. Quem AVALIA a corrida precisa dele
# (ver `evals.sequencia.derivar_eventos`): o estado seedado nao e transicao DA CORRIDA.
ESTADO_INICIAL_PADRAO = "Novo"


@dataclass
class ResultadoE2E:
    """O que uma corrida e2e produziu — insumo de `avaliacao.avaliar_e2e`."""

    perfil_nome: str
    trajetoria: list[dict[str, Any]]  # estado_final {estado, pix_status, ia_pausada} por turno
    turnos: list[ResultadoTurno] = field(default_factory=list)  # resultado bruto (auditoria)
    turnos_cliente: list[str] = field(default_factory=list)  # fala do cliente que gerou turnos[i]
    desfecho_conducao: str = "max_turnos"  # conduziu | pausou_handoff | cliente_sumiu | max_turnos
    estado_final: str | None = None
    desfecho_real: str | None = None  # rotulo do corpus (comparacao)
    cenario: Cenario | None = (
        None  # cenario seedado (atendimento_id p/ pos-eventos, ex.: foto portaria)
    )
    # Estado do atendimento ANTES do 1o turno (o que o seed aplicou). Transportado porque o
    # validador de ordem (`evals.sequencia`) precisa distinguir "transicao da corrida" de
    # "estado que ja existia": um caso seedado em `Aguardando_confirmacao` (a cotacao aconteceu
    # ANTES da janela avaliada) emitia `estado:Aguardando_confirmacao` no 1o turno e a regua R1
    # acusava "confirmou sem ter cotado" — falso positivo.
    estado_inicial: str = ESTADO_INICIAL_PADRAO
    # A COTACAO tambem pode ser pre-existente a janela avaliada (`atendimento.cotacao_enviada` no
    # seed): o cenario de remarcacao/retomada nasce com o preco JA na mesa e com `nao_deve_recotar`
    # — a conduta certa e nao repetir numero nenhum. Sem transportar isto, o validador de ordem via
    # a volta a `Aguardando_confirmacao` como "confirmou sem ter cotado" (falso positivo em
    # `remarcacao_aberta_e_volta_atras` e `piso_que_andou`, corrida c12cen_v2_20260814): a cotacao
    # existiu, so nao dentro da janela. Mesmo principio do `estado_inicial` acima.
    cotacao_inicial: bool = False

    @property
    def n_turnos(self) -> int:
        return len(self.turnos)

    @property
    def custo_brl(self) -> float:
        return sum(t.metricas.custo_brl for t in self.turnos)

    @property
    def conduziu(self) -> bool:
        return self.estado_final in ESTADOS_CONDUZIDOS


def _estado(r: ResultadoTurno) -> str | None:
    return (r.estado_final or {}).get("estado")


def _pausada(r: ResultadoTurno) -> bool:
    return bool((r.estado_final or {}).get("ia_pausada"))


def relogio_do_turno(
    agora: datetime | None, indice: int, *, passo_min: int = 0, offsets_min: list[int] | None = None
) -> datetime | None:
    """O `agora` do turno `indice` (0-based) a partir da ancora do cenario.

    `None` in -> `None` out, SEMPRE: sem ancora declarada o rig segue no relogio de parede, que e o
    comportamento de todos os cenarios anteriores a esta chave.

    `offsets_min` (offsets acumulados a partir da ancora, um por turno) vence `passo_min` (avanco
    constante). Turno alem da lista repete o ULTIMO offset — um roteiro que declara "aos 25 min o
    cliente aceita" nao volta no tempo se a conversa passar do turno declarado.
    """
    if agora is None:
        return None
    if offsets_min:
        i = min(indice, len(offsets_min) - 1)
        return agora + timedelta(minutes=offsets_min[i])
    return agora + timedelta(minutes=passo_min * indice)


async def rodar_e2e(
    conn: AsyncConnection[dict[str, Any]],
    perfil: PerfilCaso,
    cliente: ClienteSimulado,
    *,
    graph: Any | None = None,
    max_turnos: int = 12,
    cen: Cenario | None = None,
    pos_turno: Callable[[AsyncConnection[dict[str, Any]], Cenario, ResultadoTurno], Awaitable[None]]
    | None = None,
    agora: datetime | None = None,
    passo_min: int | None = None,
    offsets_min: list[int] | None = None,
    bloqueios: list[dict[str, Any]] | None = None,
    atendimento: dict[str, Any] | None = None,
) -> ResultadoE2E:
    """Conduz o caso `perfil` ate um desfecho de conducao. ROLLBACK e responsabilidade do caller.

    `cen` externo pula o seed efemero (a corrida persistente passa o caso da modelo sandbox) — e
    com ele `bloqueios`/`atendimento` nao tem efeito (quem seedou foi o caller).
    `pos_turno` roda apos cada turno (na corrida persistente, so o COMMIT — a bolha da IA ja foi
    gravada pelo `enviar_turno`). O trace Langfuse e o do coordenador (prod), com `trace_id`
    deterministico por turno; nao ha o que escopar por fora.

    RELOGIO (opcional; sem `agora` nada muda — relogio de parede, como antes):

    - `agora`: a ancora do cenario. Vai ao `seedar` E a CADA turno. Ancorar so um lado e o bug que
      a memoria `rig_relogio_injetado_finge_7_dias` registra: o historico nasce no `now()` do banco
      enquanto o turno acontece no relogio fixo, e a distancia entre os dois chega ao prompt como
      `<tempo_desde_ultima_msg_cliente minutos="~10200"/>` e, acima de 6h, como marca de pausa
      sintetica (`_GAP_PAUSA`) numa conversa que nunca teve pausa.
    - `passo_min`: avanco CONSTANTE entre turnos (turno i = ancora + i*passo).
    - `offsets_min`: offsets acumulados por turno, quando o roteiro precisa de um salto especifico
      ("ela ofertou a hora, ele aceitou 25 min depois" — o caso do piso que andou).

    AGENDA/ATENDIMENTO iniciais (opcionais): `bloqueios` e `atendimento` sao mesclados na fixture do
    `perfil_para_fixture` (que so sabe montar o atendimento cru em `Novo`) e seguem o spec do
    `evals.harness.seedar`. Os quatro parametros tambem podem vir declarados no proprio `PerfilCaso`
    (atributos de mesmo nome); o argumento explicito vence.
    """
    agora = agora if agora is not None else getattr(perfil, "agora", None)
    passo = passo_min if passo_min is not None else int(getattr(perfil, "passo_min", 0) or 0)
    offsets = offsets_min if offsets_min is not None else getattr(perfil, "offsets_min", None)
    # `cen` externo => quem seedou foi o caller (`persistencia.seed_caso_persistente`, que abre o
    # atendimento em `Novo` INCONDICIONALMENTE — o `atendimento` do perfil nao chega la). Por isso
    # o estado inicial so sai do override no caminho do seed efemero.
    estado_inicial = ESTADO_INICIAL_PADRAO
    cotacao_inicial = False
    if cen is None:
        fixture = perfil_para_fixture(perfil)
        extras = bloqueios if bloqueios is not None else getattr(perfil, "bloqueios", None)
        if extras:
            fixture["cenario"]["bloqueios"] = extras
        override = atendimento if atendimento is not None else getattr(perfil, "atendimento", None)
        if override:
            fixture["cenario"]["atendimento"] = {**fixture["cenario"]["atendimento"], **override}
        estado_inicial = str(
            fixture["cenario"]["atendimento"].get("estado") or ESTADO_INICIAL_PADRAO
        )
        # Mesma chave do `harness._seed_atendimento` (que a grava como `cotacao_enviada_em`).
        cotacao_inicial = bool(fixture["cenario"]["atendimento"].get("cotacao_enviada", False))
        # Mesma ancora do PRIMEIRO turno (nao a ancora crua): com `offsets_min[0] != 0` o seed
        # ficaria atras do turno 1 e o gap voltaria pela porta dos fundos.
        cen = await seedar(
            conn, fixture, agora=relogio_do_turno(agora, 0, passo_min=passo, offsets_min=offsets)
        )
    res = ResultadoE2E(
        perfil_nome=perfil.nome,
        trajetoria=[],
        desfecho_real=perfil.desfecho_real,
        cenario=cen,
        estado_inicial=estado_inicial,
        cotacao_inicial=cotacao_inicial,
    )

    turno_cliente: FalaDoCliente | None = perfil.abertura
    for i in range(max_turnos):
        assert turno_cliente is not None
        # `turnos_cliente` guarda o TEXTO do burst (bolhas juntas): e o que os checks keyed por
        # gatilho leem, e um gatilho tem de casar a fala dele esteja ela sozinha ou num burst.
        res.turnos_cliente.append(texto_do_burst(turno_cliente))  # paralelo a res.turnos
        # A bolha da IA e gravada em `mensagens` pelo proprio `enviar_turno` (caminho fiel), na
        # MESMA transacao efemera — junto com o backstop de carimbo da cotacao (ADR 0022). O patch
        # que o runner aplicava aqui (`gravar_resposta_ia`) virou DUPLICACAO: manter os dois
        # inseria a mesma fala duas vezes na janela do turno seguinte.
        # `list` de bolhas desce INTEIRA ao turno (coalescing real do debounce: o webhook grava
        # cada bolha e um unico turno le a janela toda) — nunca concatenada numa mensagem so, que
        # e uma forma que o WhatsApp nao produz.
        entrada: str | BolhaCliente | list[str | BolhaCliente] = (
            turno_cliente if isinstance(turno_cliente, str | BolhaCliente) else list(turno_cliente)
        )
        r = await rodar_turno_auditado(
            conn,
            cen,
            entrada,
            graph=graph,
            agora=relogio_do_turno(agora, i, passo_min=passo, offsets_min=offsets),
        )
        res.turnos.append(r)
        res.trajetoria.append(r.estado_final)
        if pos_turno is not None:
            await pos_turno(conn, cen, r)

        if _estado(r) in ESTADOS_CONDUZIDOS:
            res.desfecho_conducao = "conduziu"
            break
        if _pausada(r):
            res.desfecho_conducao = "pausou_handoff"
            break

        reacao = await cliente.responder(texto_ia=r.texto)
        if reacao.encerrou or not reacao.texto:
            res.desfecho_conducao = "cliente_sumiu"
            break
        turno_cliente = reacao.texto

    res.estado_final = _estado(res.turnos[-1]) if res.turnos else None
    return res
