"""Validador de ORDEM de acoes numa corrida e2e (Camada 2) — porte do `ToolSequenceValidator`.

Complementa os graders POR TURNO de `checks.py` com a dimensao CROSS-TURN: o agente percorreu a
conversa numa sequencia valida? Funcao pura e deterministica (sem DB/rede/LLM, como `checks.py`):
le so `ResultadoE2E.turnos[i].{tool_calls,tool_args,extracao,estado_final}` — dados ja capturados
pelo harness — e devolve violacoes de ordem, somadas as `violacoes` DURAS do veredito e2e.

Regra = "A-antes-de-B": quando um evento `gatilho` ocorre, seu `requer_antes` tem de ter ocorrido
em-ou-antes. Eventos derivados (sem captura nova):
  - `cotacao_apresentada` — arg `cotacao_apresentada` truthy num `registrar_extracao`, OU a bolha
    do turno com cara de cotacao (`barra.dominio.atendimentos.service.texto_tem_cotacao`, a MESMA
    regra do backstop do ADR 0022 que carimba `cotacao_enviada_em` no envio). O flag depende do LLM
    lembrar de marca-lo; o backstop e justamente a rede para quando ele esquece, e sem ele o
    validador acusava "confirmou sem ter cotado" numa conversa em que a IA disse o preco.
  - `tipo:<valor>`        — arg `tipo_atendimento` num `registrar_extracao` (ex.: `tipo:externo`).
  - `estado:<Nome>`       — TRANSICAO: `estado_final["estado"]` muda em relacao ao turno anterior.
  - `pix:solicitado`      — `estado_final["pix_status"]` deixa de ser `nao_solicitado`.

Premissa do baseline: os casos e2e nascem em `Novo`, sem cotacao/tipo/pix (ver
`evals.e2e.perfil.perfil_para_fixture`). Por isso o estado inicial nao precisa ser semeado: a
varredura comeca com `vistos` vazio. Um caso seedado no MEIO da conversa (fora desse caminho)
poderia gerar falso-positivo — fora do escopo do v1.

Ordem DENTRO de um turno: os eventos de extracao saem ANTES dos de transicao, porque os args do
`registrar_extracao` (cotacao marcada, tipo fixado) sao a CAUSA da transicao que o servidor decide
no mesmo turno. Assim, cotar e confirmar no mesmo turno NAO viola; so confirmar sem nunca cotar.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from barra.dominio.atendimentos.service import texto_tem_cotacao

if TYPE_CHECKING:
    from evals.e2e.runner import ResultadoE2E


@dataclass(frozen=True)
class ReguaOrdem:
    gatilho: str  # evento que dispara a obrigacao, ex.: "estado:Aguardando_confirmacao"
    requer_antes: str  # evento que tem de ter ocorrido em-ou-antes do gatilho
    desc: str  # descricao curta da invariante (entra na mensagem de falha)


# Regras v1. Ambas pegam algo que o SERVIDOR nao bloqueia deterministicamente no caminho da IA:
#  R1 — a transicao p/ Aguardando_confirmacao e por tipo+horario, NAO pela cotacao (funil-vazamento).
#  R2 — regression-guard do gate de Pix (ver docstring).
REGRAS_V1: list[ReguaOrdem] = [
    ReguaOrdem(
        "estado:Aguardando_confirmacao",
        "cotacao_apresentada",
        "confirmou sem ter cotado (funil-vazamento)",
    ),
    ReguaOrdem(
        "pix:solicitado",
        "tipo:externo",
        "pix solicitado sem tipo_atendimento=externo",
    ),
]


def derivar_eventos(res: ResultadoE2E) -> list[str]:
    """Sequencia ordenada de eventos da corrida (ver vocabulario no docstring do modulo)."""
    eventos: list[str] = []
    estado_anterior: str | None = None
    pix_solicitado_visto = False

    for t in res.turnos:
        # 1) eventos de extracao primeiro (causa da transicao no mesmo turno)
        payloads = [
            args
            for nome, args in zip(t.tool_calls, t.tool_args, strict=False)
            if nome == "registrar_extracao"
        ]
        # UNIAO com o CARIMBO do State: a varredura de `tool_calls` some inteira quando o
        # output_guard regenera (`_zerar_turno` reescreve as AIMessages sem tool_calls, achado 12a
        # da r3) — e um turno de fechamento sem `tipo:externo` fazia o validador acusar
        # "pix solicitado sem tipo externo" numa corrida que extraiu o tipo. Uniao e nao
        # substituicao porque o carimbo guarda so o ULTIMO payload do turno; evento repetido e
        # inofensivo (as regras so perguntam "A ocorreu antes de B").
        carimbo = t.extracao
        if carimbo is not None and carimbo not in payloads:
            payloads.append(carimbo)
        for args in payloads:
            if args.get("cotacao_apresentada"):
                eventos.append("cotacao_apresentada")
            tipo = args.get("tipo_atendimento")
            if tipo:
                eventos.append(f"tipo:{tipo}")

        # 1b) backstop do ADR 0022: a bolha com preco cota mesmo sem o flag do LLM (ver docstring).
        if texto_tem_cotacao(t.texto or ""):
            eventos.append("cotacao_apresentada")

        estado = (t.estado_final or {}).get("estado")
        # 2) transicao de estado (emite so na mudanca)
        if estado and estado != estado_anterior:
            eventos.append(f"estado:{estado}")
            estado_anterior = estado

        # 3) transicao de pix (emite so na 1a saida de nao_solicitado)
        pix = (t.estado_final or {}).get("pix_status")
        if pix and pix != "nao_solicitado" and not pix_solicitado_visto:
            eventos.append("pix:solicitado")
            pix_solicitado_visto = True

    return eventos


def avaliar_sequencia(res: ResultadoE2E, regras: list[ReguaOrdem] = REGRAS_V1) -> list[str]:
    """Devolve as violacoes de ordem (vazio = passou). A-antes-de-B sobre os eventos derivados."""
    eventos = derivar_eventos(res)
    vistos: set[str] = set()
    falhas: list[str] = []
    for evento in eventos:
        for regra in regras:
            if regra.gatilho == evento and regra.requer_antes not in vistos:
                falhas.append(
                    f"ordem: {regra.desc} (gatilho={evento!r}, faltou {regra.requer_antes!r})"
                )
        vistos.add(evento)
    return falhas
