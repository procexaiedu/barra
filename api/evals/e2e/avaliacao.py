"""Veredito de uma corrida e2e: a IA conduziu ate a confirmacao, sem violar invariante?

Determinismo total (sem LLM-judge, como o gate da Camada 1): mede a linha de chegada, varre
vazamento cross-canal em cada turno (reusa os detectores de prod via `evals.checks`) e compara
a conducao com o desfecho real do corpus como rotulo.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from psycopg import AsyncConnection

from barra.agente.nos.output_guard import (
    tem_marcador_outro_cliente,
    tem_marcador_system,
)

from .perfil import PerfilCaso
from .runner import ResultadoE2E

if TYPE_CHECKING:
    from evals.conduta import CondutaScore
    from evals.harness import ResultadoTurno


@dataclass
class VeredictoE2E:
    perfil_nome: str
    conduziu: bool
    desfecho_conducao: str
    estado_final: str | None
    bate_desfecho_real: bool | None  # None se o caso nao tem rotulo do corpus
    n_turnos: int
    custo_brl: float
    violacoes: list[str] = field(default_factory=list)
    # Observacoes que NAO sao defeito de conduta e por isso nao zeram o `ok`: o turno que o
    # coordenador nem processou, a falha de infra e a escalada de sistema (ver `_silencio_do_turno`).
    # Ficam visiveis no transcrito para quem le a corrida saber que houve fala do cliente sem turno
    # do outro lado.
    anotacoes: list[str] = field(default_factory=list)
    # Conduta de venda por-conversa (voz + disciplina). Informativo: o pass/fail de conduta e' por
    # TAXA, decidido no agregado do gate (evals.e2e.conduta_gate), nao por corrida — `ok` segue so
    # a linha de chegada + invariantes DURAS.
    conduta: CondutaScore | None = None
    # Motivo da falha de INFRA que abortou a corrida (`modelo_indisponivel`, `timeout_grafo`, ...),
    # ou None. A corrida nao mediu conduta nenhuma: o provider caiu no meio dela. Quem agrega DEVE
    # EXCLUI-LA do denominador (ou refazer o caso), nunca conta-la como reprovacao — e por isso que
    # ela nao vira violacao: `ok` continua sendo so conduta, e este campo e o filtro.
    invalida_por_infra: str | None = None

    @property
    def ok(self) -> bool:
        """Conducao limpa: chegou na linha de chegada e nao violou nenhuma invariante dura."""
        return self.conduziu and not self.violacoes


def _tool_ok_no_turno(r: ResultadoTurno, nome: str) -> bool:
    """A tool `nome` rodou com SUCESSO neste turno, lida pelas ToolMessages.

    ToolMessage e o rastro que SOBREVIVE ao `_zerar_turno`: o output_guard reescreve as AIMessages
    do turno e leva os `tool_calls` junto (achado 12a da r3), entao ler `r.tool_calls` aqui daria
    "nao escalou" num turno que escalou. Erro recuperavel nao conta — tool que falhou nao escalou
    nem enviou midia nenhuma (mesmo par de sinais do `extrair_texto_do_turno`: status do ToolNode
    e o prefixo "ERRO:").
    """
    from langchain_core.messages import ToolMessage

    for m in r.mensagens:
        if not isinstance(m, ToolMessage) or m.name != nome:
            continue
        if m.status != "error" and not str(m.content).startswith("ERRO:"):
            return True
    return False


def _escalou_neste_turno(r: ResultadoTurno) -> bool:
    """A `ia_pausada` deste turno foi aberta PELO PROPRIO turno (escalada justificada)?

    Reusa o discriminador de PROD (`pausa_aberta_por_este_turno`, o mesmo que decide se o envio
    ignora a pausa): `escalar` bem-sucedida ou escalada silenciosa da guarda do `registrar_extracao`
    (texto exato de `MENSAGENS_GUARD_ESCALADA` numa ToolMessage). O `or` acrescenta o rastro que
    resiste ao `_zerar_turno` — o predicado de prod casa o tool_call por id, e o id mora na
    AIMessage que o guard tem o direito de apagar.

    O terceiro `or` e a escalada aberta pelo COORDENADOR, fora do grafo (`escalar_por_exaustao`):
    ela nao chama tool nem toca `messages` — o unico rastro e a linha nova em `barravips.escaladas`,
    que o harness fiel carimba em `escalada_do_turno`. Sem ela, um timeout do provider virava
    "pausa externa" e a regua cobrava da IA um handoff que a IA nem soube que existiu.

    Sem rastro => pausa EXTERNA (bloqueio do output_guard, pipeline de Pix/foto, pausa manual do
    operador). Nesse caso a modelo humana assumiu no meio do turno: a corrida NAO conduziu sozinha.
    """
    from barra.workers.coordenador import pausa_aberta_por_este_turno

    return (
        pausa_aberta_por_este_turno(r.mensagens)
        or _tool_ok_no_turno(r, "escalar")
        or r.escalada_do_turno is not None
    )


def _turno_nao_processado(r: ResultadoTurno) -> bool:
    """O coordenador NEM RODOU o grafo neste turno (gate do passo 2: `ia_pausada` herdada de um
    turno anterior ou estado terminal).

    Sinal: nenhum no visitado E nenhuma mensagem do grafo. Os dois juntos porque cada um sozinho
    mente num sentido: `nodes` vazio tambem acontece com um grafo FAKE injetado (que nao dispara os
    callbacks do handler), e `mensagens` e o que o proprio coordenador exige do resultado — quando
    o grafo roda, ela nunca volta vazia, nem sob `_zerar_turno` (que troca as AIMessages por
    vazias, sem remover nenhuma da lista).

    NAO confundir com o turno que RODOU e saiu calado: turno mudo de verdade, descarte na pausa
    externa (onde so a bolha critica e resgatada) e regen que esvaziou a fala tem `nodes`/
    `mensagens` — e seguem sendo violacao.
    """
    return not r.nodes and not r.mensagens


# Motivos de `escalar_por_exaustao` (workers/coordenador) partidos pelo que eles DIZEM sobre a
# corrida. Nenhum deles passa pelo grafo: sao decisao do coordenador, sem bolha ao cliente.
#
# INFRA — o turno nao chegou a acontecer (provider fora do ar, teto de 60s, excecao nao prevista,
# recursion_limit). Nao ha conduta a julgar: a corrida e REFAZIVEL, e cobra-la produzia o pior
# tipo de sinal — o eval reprovando a IA por um APITimeoutError (c8) e o ciclo seguinte "consertando"
# um prompt que nunca errou.
_ESCALADA_INFRA = frozenset(
    {
        "modelo_indisponivel",
        "timeout_grafo",
        "erro_interno",
        "exaustao_iteracoes",
        # `aup_saida_judge_falhou` (c12): o judge de AUP do output_guard caiu por rede e o guard
        # fechou fail-closed — `_bloquear` pausa a IA e zera as bolhas. E a QUARTA porta de
        # escalada (nem a tool, nem a guarda da extracao, nem o coordenador: o proprio guard),
        # e sem ela aqui uma queda de rede vira "handoff legitimo, viol=0" na regua. Medido em
        # `eb02:224236417331442` t6, onde a resposta CERTA ja existia ("Continua 400 a 1h amor")
        # e foi apagada por um APIConnectionError dentro de `_julgar_aup`.
        "aup_saida_judge_falhou",
    }
)
# CONDUTA/CUSTO — o sistema decidiu parar e chamar gente, e a decisao e legitima e MEDIDA: o teto
# de turnos do dia (CUSTO-04), o safety filter do provider e o truncamento com tool_use incompleto.
# Nao invalidam a corrida; so explicam o turno sem bolha.
_ESCALADA_SISTEMA = frozenset({"teto_turnos", "modelo_recusou", "modelo_truncado"})


def _infra_do_turno(r: ResultadoTurno) -> str | None:
    """O motivo de infra que abortou este turno, ou None. Ver `_ESCALADA_INFRA`."""
    return r.escalada_do_turno if r.escalada_do_turno in _ESCALADA_INFRA else None


def _silencio_do_turno(i: int, r: ResultadoTurno) -> tuple[list[str], list[str]]:
    """Invariantes duras que o `ok` da corrida ignorava: turno MUDO e pausa da IA (achado 12b).

    Devolve `(violacoes, anotacoes)`.

    `VeredictoE2E.ok` so olhava `conduziu` (= `estado_final in ESTADOS_CONDUZIDOS`) e as violacoes
    de vazamento/ordem. Com isso `decidido_rapido_a` entrou no corpus com `veredito_ok: true`
    tendo terminado em `Aguardando_confirmacao` + `ia_pausada` + bolha VAZIA no turno em que o
    cliente fechou — a linha de chegada estava no banco, mas quem cruzou foi o silencio e um
    handoff para o Fernando. `remarcacao` idem, com dois turnos no vacuo depois da pausa.

    Os dois silencios DELIBERADOS ficam de fora, por carimbo e nao por inferencia:
      - `_mute_por_erro_de_tool` — o `extrair` fechou o turno mudo de proposito (guard de dominio
        + reoferta ja gasta): silencio > reserva fantasma;
      - escalada DESTE turno — a IA (ou a guarda da extracao) decidiu chamar a modelo; em
        `motivo=conteudo_ilegal` o desenho e a recusa seca, sem canned de espera.

    E o turno que o coordenador NEM PROCESSOU vira ANOTACAO, nao violacao (re-prova `externo_a2`,
    t6): sem grafo nao ha bolha a cobrar nem pausa a julgar — a pausa e HERDADA, e a escalada que
    a abriu ja foi julgada no turno em que aconteceu. Cobrar de novo aqui reprovava duas vezes a
    MESMA decisao (e reprovava a corrida por uma escalada legitima).
    """
    fora: list[str] = []
    pausada = bool((r.estado_final or {}).get("ia_pausada"))
    if _turno_nao_processado(r):
        motivo = "pausa herdada" if pausada else "gate do coordenador"
        return fora, [f"turno {i}: turno nao processado ({motivo}); o grafo nao rodou"]
    # Falha de INFRA vem ANTES de qualquer regua: o turno nao produziu conduta a julgar. Sem esta
    # saida, o mesmo handoff era cobrado duas vezes ("mudo" + "pausada sem escalada") — as 2
    # violacoes duras do c8, ambas contra o provider e nenhuma contra a IA.
    infra = _infra_do_turno(r)
    if infra is not None:
        return fora, [f"turno {i}: corrida invalidada por falha de infra ({infra})"]
    escalou = _escalou_neste_turno(r)
    mudo = not r.texto.strip() and not _tool_ok_no_turno(r, "enviar_midia")
    if mudo and not (r.mute_deliberado or escalou):
        fora.append(f"turno {i}: turno mudo (nenhuma bolha chegou ao cliente)")
    if pausada and not escalou:
        fora.append(f"turno {i}: IA pausada sem escalada deste turno (handoff externo)")
    if r.escalada_do_turno in _ESCALADA_SISTEMA:
        # Escalada legitima do coordenador (custo/safety): `escalou` ja tirou as violacoes acima;
        # a anotacao existe para o turno sem bolha nao parecer silencio inexplicado no transcrito.
        return fora, [
            f"turno {i}: escalada do sistema ({r.escalada_do_turno}); "
            "handoff sem bolha ao cliente, por desenho"
        ]
    return fora, []


def avaliar_e2e(res: ResultadoE2E, perfil: PerfilCaso) -> VeredictoE2E:
    from evals.checks import _texto_ao_cliente
    from evals.conduta import avaliar_conduta
    from evals.sequencia import avaliar_sequencia

    violacoes: list[str] = []
    anotacoes: list[str] = []
    invalida_por_infra: str | None = None
    # `_texto_ao_cliente`, NAO `_texto_e_args`: a invariante dura e sobre o que CHEGA ao cliente
    # (mesma superficie do output_guard de prod). Args internos citam "atendimento"/"cliente"
    # legitimamente (proxima_acao_esperada, resumo de escalada) — rodar o detector neles gerou
    # falso positivo que zerou o `ok` da corrida (loop-massa r3, decidido_rapido_b).
    for i, t in enumerate(res.turnos, start=1):
        saida = _texto_ao_cliente(t)
        if tem_marcador_outro_cliente(saida):
            violacoes.append(f"turno {i}: marcador de outro cliente na saida (vazamento por-par)")
        if tem_marcador_system(saida):
            violacoes.append(f"turno {i}: marcador de system vazou para a bolha")
        duras, notas = _silencio_do_turno(i, t)
        violacoes.extend(duras)
        anotacoes.extend(notas)
        invalida_por_infra = invalida_por_infra or _infra_do_turno(t)

    # Camada 2: ordem de acoes cross-turn (cotacao antes de confirmar; pix so em externo).
    violacoes.extend(avaliar_sequencia(res))

    # Comparacao com o desfecho real do corpus: a IA "deveria" ter conduzido (chegado a
    # confirmacao) nos casos que o cliente real convergiu? Rotulo, nao gabarito de fechamento.
    bate: bool | None = None
    if perfil.desfecho_real:
        convergiu_real = perfil.desfecho_real.startswith("convertido")
        bate = res.conduziu == convergiu_real

    return VeredictoE2E(
        perfil_nome=res.perfil_nome,
        conduziu=res.conduziu,
        desfecho_conducao=res.desfecho_conducao,
        estado_final=res.estado_final,
        bate_desfecho_real=bate,
        n_turnos=res.n_turnos,
        custo_brl=round(res.custo_brl, 6),
        violacoes=violacoes,
        anotacoes=anotacoes,
        conduta=avaliar_conduta(res),
        invalida_por_infra=invalida_por_infra,
    )


async def pontuar_no_langfuse(trace_id: str | None, veredito: VeredictoE2E) -> None:
    """Empurra o veredito determinístico como scores no trace Langfuse do turno (EVAL-11 online).

    Ancora no `trace_id` do ultimo turno (vem de `ResultadoTurno.trace_id`, so com escopar_trace).
    Best-effort: no-op sem trace_id ou sem handler (`registrar_feedback_online` ja trata). Os nomes
    sao agregaveis no Langfuse junto do trace bruto da conducao.
    """
    if trace_id is None:
        return
    import asyncio

    from barra.core.tracing import registrar_feedback_online

    scores = {
        "e2e_conduziu": 1.0 if veredito.conduziu else 0.0,
        "e2e_sem_violacoes": 0.0 if veredito.violacoes else 1.0,
    }
    if veredito.bate_desfecho_real is not None:
        scores["e2e_bate_desfecho_real"] = 1.0 if veredito.bate_desfecho_real else 0.0
    for name, value in scores.items():
        await asyncio.to_thread(registrar_feedback_online, trace_id, name, value)


async def flush_langfuse() -> None:
    """Garante a entrega dos traces/scores Langfuse num processo curto (massa) ou no /fim (sessao).
    No-op sem handler (tracing desligado)."""
    from barra.core.tracing import langfuse_handler

    if langfuse_handler() is None:
        return
    import asyncio

    from langfuse import get_client

    await asyncio.to_thread(get_client().flush)


async def gravar_veredito(
    conn: AsyncConnection[dict[str, Any]],
    veredito: VeredictoE2E,
    *,
    run_tag: str,
    thread_ref: str | None,
    desfecho_real: str | None,
    trajetoria: list[dict[str, Any]],
    eixo: str = "",
) -> None:
    """Persiste UMA corrida em `corpus.eval_e2e` (uma linha por corrida x run_tag).

    ⚠️ §0: escreve no banco de prod (schema `corpus`, dado de pesquisa fora de barravips). Exige a
    `ddl.sql` aplicada. Deve receber uma conn AUTOCOMMIT SEPARADA do seed: o seed efemero da corrida
    da ROLLBACK (modo nao-persistir), e o veredito precisa sobreviver a esse rollback.
    """
    await conn.execute(
        """
        INSERT INTO corpus.eval_e2e
            (run_tag, perfil_nome, eixo, thread_ref, desfecho_conducao, estado_final, conduziu,
             desfecho_real, bate_desfecho_real, n_turnos, custo_brl, violacoes, trajetoria)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb)
        """,
        (
            run_tag,
            veredito.perfil_nome,
            eixo,
            thread_ref,
            veredito.desfecho_conducao,
            veredito.estado_final,
            veredito.conduziu,
            desfecho_real,
            veredito.bate_desfecho_real,
            veredito.n_turnos,
            veredito.custo_brl,
            json.dumps(veredito.violacoes, ensure_ascii=False),
            json.dumps(trajetoria, ensure_ascii=False, default=str),
        ),
    )
