"""Arnes que gera CONVERSAS E2E para o golden de calibracao (EVAL-10 via EVAL-12).

Roda cada `Cenario` (sim/cenarios.py) como uma jornada cliente-LLM <-> GRAFO REAL (sim/loop.py),
com o cardapio da modelo seedado (sim/seed_cardapio.py via hook `apos_seed`), e salva a transcricao
completa em `evals/calibracao/conversas.jsonl` -- onde cada FALA DA IA e uma unidade rotulavel pelo
Fernando (UI por-conversa). Substitui o antigo `calibracao/gerar_candidatos.py` (turno isolado).

Com `--fixo`, troca o cliente-LLM pelo cliente FIXO (sim/cenarios_fixos.py + sim/cliente_fixo.py):
falas de cliente pre-escritas (das conversas reais), SEM cliente-LLM -> ~metade do custo (so a IA
roda ao vivo) e reutilizavel. Sai em `evals/calibracao/conversas_fixas.jsonl` (arquivo SEPARADO,
congelavel: regerar as do robo nao apaga as fixas). A UI (evals-notas.html) carrega os dois juntos.

needs_db + needs_anthropic_api. Passo deliberado de operador (custa credito: a IA roda por turno --
no modo --fixo so a IA; no modo robo tambem o cliente-LLM), FORA do CI. Roda contra TEST_DATABASE_URL
(= prod, com rollback): 1 transacao por cenario, `rollback()` SEMPRE no finally, ZERO commit.

    # da raiz de api/, com TEST_DATABASE_URL + ANTHROPIC_API_KEY:
    uv run python -m evals.sim.gerar_conversas                 # robo: todos os cenarios
    uv run python -m evals.sim.gerar_conversas --fixo          # fixo: todas as conversas roteirizadas
    uv run python -m evals.sim.gerar_conversas --cenario interno_qualificacao   # so um (smoke)

O sim e NAO-DETERMINISTICO e NAO-GATE (sim/README.md): gera-se UMA vez, inspeciona-se, e congela-se
o resultado no golden held-out. Trajetoria ruim -> tambem vira fixture pre-roteirizada de scripted_5/.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Protocol

from .cenarios import CENARIOS, Cenario
from .cenarios_fixos import CENARIOS_FIXOS, CENARIOS_FIXOS_HELDOUT, CenarioFixo
from .cliente import ClienteLike, ClienteSimulado
from .cliente_fixo import ClienteRoteirizado
from .loop import Trajetoria, _carregar_runner, jornada
from .seed_cardapio import seed_cardapio

_SAIDA = Path(__file__).resolve().parents[1] / "calibracao" / "conversas.jsonl"
_SAIDA_FIXAS = Path(__file__).resolve().parents[1] / "calibracao" / "conversas_fixas.jsonl"
# held-out fica em arquivo SEPARADO: o Loop A nunca itera sobre ele; a medição de generalização e a
# rotulagem do golden o consomem à parte.
_SAIDA_HELDOUT = Path(__file__).resolve().parents[1] / "calibracao" / "conversas_heldout.jsonl"


class _CenarioComum(Protocol):
    """Campos comuns a `Cenario` (robo) e `CenarioFixo` (roteirizado) que o arnes le -- so o que
    `_rodar`/`_serializar`/`_filtrar` tocam, agnostico de como o cliente decide (persona-LLM vs
    falas fixas). O que diverge (`persona` vs `mensagens_cliente`) fica na factory injetada."""

    nome: str
    estado_inicial: dict[str, Any]
    decidir_ato: Any
    max_turnos: int
    fechar_card: bool
    cobrar_e_fechar: bool
    timeout_sumiu: bool


async def _apos_seed(conn: Any, modelo_id: Any, *_ids: Any) -> None:
    """Hook do jornada: popula o cardapio da modelo recem-seedada antes do 1o turno."""
    await seed_cardapio(conn, modelo_id)


def _serializar(cenario: _CenarioComum, traj: Trajetoria) -> dict[str, Any]:
    """Trajetoria -> conversa rotulavel. Cada fala da IA ganha `idx` (chave de rotulagem na UI) +
    os sinais de OBSERVABILIDADE do turno (estado/ia_pausada/pix_status/tools/escalou/nodes) que
    tornam "chamada de tools / escalada / handoff" auditaveis no corpus e na evals-notas.html. Os
    campos extras sao ADITIVOS: o export do golden le so texto_resposta/idx/historico (calibrar.py
    e a UI ignoram o resto), entao nao afetam a rotulagem nem a calibracao."""
    turnos: list[dict[str, Any]] = []
    for passo in traj.passos:
        if passo.acao_ato:
            turnos.append(
                {
                    "papel": "ato",
                    "ato": passo.acao_ato,
                    "estado": passo.estado_atendimento,
                    "ia_pausada": passo.ia_pausada,
                    "pix_status": passo.pix_status,
                }
            )
            continue
        if passo.acao_mensagem is not None:
            turnos.append({"papel": "cliente", "texto": passo.acao_mensagem})
        if passo.bolha_ia:
            turnos.append(
                {
                    "papel": "ia",
                    "texto": passo.bolha_ia,
                    "estado": passo.estado_atendimento,
                    "ia_pausada": passo.ia_pausada,
                    "pix_status": passo.pix_status,
                    "tools": passo.tools_chamadas,
                    "escalou": passo.escalou,
                    "nodes": passo.nodes_visitados,
                    "extracao": passo.extracao,
                    # diagnostico (C5a): aditivo, a UI/calibrar.py ignoram. O tool_io traz o motivo
                    # da escalada (args de `escalar`) que o classificador E2E le.
                    "prompt_montado": passo.prompt_montado,
                    "thinking": passo.thinking,
                    "tool_io": passo.tool_io,
                }
            )
    idx = 0
    for turno in turnos:
        if turno["papel"] == "ia":
            turno["idx"] = idx
            idx += 1
    return {"conversa_id": cenario.nome, "cenario": cenario.nome, "turnos": turnos}


async def _rodar[T: _CenarioComum](
    cenarios: Sequence[T],
    construir_cliente: Callable[[T], ClienteLike],
) -> list[dict[str, Any]]:
    """Roda cada cenario via `jornada` com o cliente que a factory constroi (robo ou fixo). O resto
    (seed/serializacao/observabilidade) e identico aos dois -- so o cliente diverge.

    Cada cenario usa SUA PROPRIA conexao (1 transacao por cenario, depois rollback+close). Isolar por
    conexao e o que torna o arnes robusto a falha: se uma tool de escrita estoura DENTRO do
    `conn.transaction()` que `_executar_idempotente` abre, a conexao fica num estado de transacao
    quebrado e o `conn.rollback()` seguinte bate em "rollback forbidden within a Transaction context"
    -- com conexao COMPARTILHADA essa 2a excecao escapava do loop e DERRUBAVA o run inteiro, perdendo
    as conversas ja coletadas e nunca gravando o jsonl. Por conexao + rollback best-effort + close
    sempre: um cenario que quebra nao contamina nem mata os outros, e o `close()` sem commit ja
    garante zero persistencia (o rollback e so higiene)."""
    runner = _carregar_runner()
    conversas: list[dict[str, Any]] = []
    for i, cen in enumerate(cenarios, 1):
        conn = await runner._conectar()  # TEST_DATABASE_URL; SystemExit(2) se ausente
        seed = {"estado_inicial": cen.estado_inicial}
        try:
            traj = await jornada(
                conn,
                seed,
                construir_cliente(cen),
                cen.decidir_ato,
                max_turnos=cen.max_turnos,
                apos_seed=_apos_seed,
                fechar_card=cen.fechar_card,
                cobrar_e_fechar=cen.cobrar_e_fechar,
                timeout_sumiu=cen.timeout_sumiu,
            )
            conversas.append(_serializar(cen, traj))
            n_ia = sum(1 for p in traj.passos if p.bolha_ia)
            print(
                f"[{i}/{len(cenarios)}] {cen.nome}: {len(traj.passos)} passos, {n_ia} falas da IA"
            )
        except Exception as e:  # um cenario que quebra nao mata os outros
            import traceback

            print(
                f"[{i}/{len(cenarios)}] {cen.nome}: FALHOU -- {type(e).__name__}: {e}",
                file=sys.stderr,
            )
            traceback.print_exc()
        finally:
            # rollback best-effort: se a tool estourou DENTRO do conn.transaction() do
            # _executar_idempotente, a conn fica em "transaction context" e o rollback bate -- o
            # close() abaixo descarta a transacao do mesmo jeito. So registramos para nao mascarar.
            try:
                await conn.rollback()
            except Exception as rb:  # higiene; close() ja garante zero persistencia
                print(f"  (rollback best-effort falhou: {type(rb).__name__})", file=sys.stderr)
            # close sem commit descarta a transacao -> zero persistencia, mesmo apos rollback abortado.
            await conn.close()
    return conversas


def _filtrar[T: _CenarioComum](todos: Sequence[T], pedidos: list[str] | None) -> list[T]:
    """Aplica o filtro --cenario (repetivel) a um conjunto homogeneo; SystemExit(2) se nada casa."""
    if not pedidos:
        return list(todos)
    alvo = set(pedidos)
    casados = [c for c in todos if c.nome in alvo]
    if not casados:
        print(
            f"nenhum cenario casou {sorted(alvo)}; disponiveis: {[c.nome for c in todos]}",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return casados


def _cliente_robo(cen: Cenario) -> ClienteSimulado:
    return ClienteSimulado(cen.persona)


def _cliente_fixo(cen: CenarioFixo) -> ClienteRoteirizado:
    return ClienteRoteirizado(cen.mensagens_cliente)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]  # console Windows cp1252
    parser = argparse.ArgumentParser(description="Gera conversas E2E p/ o golden (EVAL-10).")
    parser.add_argument(
        "--cenario", action="append", help="nome do cenario a rodar (repetivel; default todos)."
    )
    parser.add_argument(
        "--fixo",
        action="store_true",
        help="usa o cliente FIXO (falas roteirizadas de cenarios_fixos.py, SEM cliente-LLM) e grava "
        "em conversas_fixas.jsonl. Sem o flag: cliente-LLM (cenarios.py -> conversas.jsonl).",
    )
    parser.add_argument(
        "--held-out",
        action="store_true",
        help="com --fixo: roda o conjunto HELD-OUT (medição de generalização, nunca usado p/ iterar) "
        "e grava em conversas_heldout.jsonl.",
    )
    parser.add_argument(
        "--usar-database-url",
        action="store_true",
        help="DELIBERADO: usa o DATABASE_URL do .env (PROD) como TEST_DATABASE_URL. O arnes nunca "
        "commita (autocommit=False + rollback sempre); e o padrao do projeto p/ needs_db "
        "(memoria testes_db_fake_vs_real). Sem este flag, exige TEST_DATABASE_URL no ambiente.",
    )
    args = parser.parse_args()

    if args.usar_database_url:
        # Copia o DATABASE_URL (prod) para TEST_DATABASE_URL dentro do processo -- nenhuma URL no
        # comando/log. runner._conectar le os.environ; rollback garante zero persistencia no banco.
        import os

        from barra.settings import get_settings

        os.environ.setdefault("TEST_DATABASE_URL", get_settings().database_url)

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    # Tracing LangSmith-sim (sem anonymizer; dados sintéticos) -> root-cause via MCP do LangSmith.
    # No-op sem LANGCHAIN_API_KEY: o diagnóstico ainda tem o conversas.jsonl enriquecido (C5a).
    from barra.core.tracing import setup_tracing_sim
    from barra.settings import get_settings

    setup_tracing_sim(get_settings())

    if args.fixo and args.held_out:
        conversas = asyncio.run(
            _rodar(_filtrar(CENARIOS_FIXOS_HELDOUT, args.cenario), _cliente_fixo)
        )
        saida = _SAIDA_HELDOUT
    elif args.fixo:
        conversas = asyncio.run(_rodar(_filtrar(CENARIOS_FIXOS, args.cenario), _cliente_fixo))
        saida = _SAIDA_FIXAS
    else:
        conversas = asyncio.run(_rodar(_filtrar(CENARIOS, args.cenario), _cliente_robo))
        saida = _SAIDA

    saida.write_text(
        "\n".join(json.dumps(c, ensure_ascii=False) for c in conversas) + "\n", encoding="utf-8"
    )
    print(f"\nGravado: {saida} ({len(conversas)} conversas)")


if __name__ == "__main__":
    main()
