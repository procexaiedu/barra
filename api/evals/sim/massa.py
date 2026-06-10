"""Rodada em MASSA de jornadas E2E (`Novo` -> `Fechado`/`Perdido`) para o veredito de go-live.

Compoe as pecas que ja existem -- `sim/loop.py:jornada` (loop dual-control contra o grafo REAL),
`sim/cenarios.py` (19 robo) + `sim/cenarios_fixos.py` (11 fixos + 3 held-out), `sim/perfis.py`
(variacao de FORMA da persona) e `gerar_conversas._serializar` -- numa rodada de ~52 jornadas com
K amostras por cenario robo, teto de custo (budget guard) e persistencia auditavel em
`evals/registros/rodadas/<carimbo>/{massa.jsonl, meta.json}`.

NAO-GATE como o resto do sim (sim/README.md): o verde da massa NUNCA substitui o gate
deterministico (runner K=5). A massa entra no veredito (evals/diagnostico/veredito.py) como
(1) invariantes-duros (violacao de disclosure/canary bloqueia), (2) estatistica de conducao
(taxa E2E estrutural) e (3) DESCOBERTA (fila do juiz). needs_db + needs_anthropic_api: passo
deliberado de operador, CUSTA CREDITO (a IA + o cliente-LLM rodam ao vivo por turno), FORA do CI.

    # da raiz de api/, com TEST_DATABASE_URL + ANTHROPIC_API_KEY (ou --usar-database-url):
    uv run python -m evals.sim.massa                          # rodada completa (~52 jornadas)
    uv run python -m evals.sim.massa --cenario interno_qualificacao --k-robo 1 \
        --sem-fixos --sem-heldout --teto-brl 5                # smoke de 1 jornada
    uv run python -m evals.sim.massa --rodada <dir>           # continua/regrava numa rodada

Escrita INCREMENTAL: cada conversa e appendada em `massa.jsonl` ao terminar -- abort por teto ou
crash nao perde o ja gerado. O plano e DETERMINISTICO por `--semente` (mesma semente = mesma
composicao de perfis), mas as conversas em si sao nao-deterministicas (2 LLMs em loop).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .cenarios import CENARIOS, Cenario
from .cenarios_fixos import CENARIOS_FIXOS, CENARIOS_FIXOS_HELDOUT, CenarioFixo
from .cliente import ClienteLike, ClienteSimulado
from .cliente_fixo import ClienteRoteirizado
from .gerar_conversas import _apos_seed, _serializar
from .loop import Trajetoria, _carregar_runner, jornada
from .perfis import PERFIS, PerfilCliente, variar_persona

_RODADAS = Path(__file__).resolve().parents[1] / "registros" / "rodadas"

# Ordem de grandeza p/ a estimativa impressa no inicio (nao e o guard; o guard usa custo MEDIDO).
_ESTIMATIVA_ROBO_BRL = 1.20  # agente + cliente-LLM, ~8-12 turnos
_ESTIMATIVA_FIXO_BRL = 0.60  # so o agente roda ao vivo


@dataclass(frozen=True)
class ItemMassa:
    """Uma jornada planejada da rodada: cenario + perfil (robo) e o id da amostra."""

    conversa_id: str  # "<cenario>#k<i>"
    tipo: str  # "robo" | "fixo" | "heldout"
    cenario: Any  # Cenario | CenarioFixo
    perfil: PerfilCliente | None  # None nos fixos/heldout e no k0 robo


def montar_plano(
    *,
    k_robo: int = 2,
    incluir_fixos: bool = True,
    incluir_heldout: bool = True,
    nomes: list[str] | None = None,
    semente: int = 0,
) -> list[ItemMassa]:
    """Monta a composicao da rodada (PURO, deterministico por semente).

    Robo: k0 = persona ORIGINAL do cenario; k1..k(K-1) rotacionam `PERFIS` por
    `(semente + indice_do_cenario + k - 1) % len(PERFIS)` -- mesma semente reproduz a composicao,
    sementes distintas redistribuem os perfis. Fixos/held-out entram 1x (falas roteirizadas: perfil
    nao se aplica). `nomes` filtra por nome de cenario (smoke); nenhum casamento -> ValueError.
    """
    itens: list[ItemMassa] = []
    for i, cen in enumerate(CENARIOS):
        for k in range(max(1, k_robo)):
            perfil = None if k == 0 else PERFIS[(semente + i + k - 1) % len(PERFIS)]
            itens.append(ItemMassa(f"{cen.nome}#k{k}", "robo", cen, perfil))
    if incluir_fixos:
        itens.extend(ItemMassa(f"{c.nome}#k0", "fixo", c, None) for c in CENARIOS_FIXOS)
    if incluir_heldout:
        itens.extend(ItemMassa(f"{c.nome}#k0", "heldout", c, None) for c in CENARIOS_FIXOS_HELDOUT)
    if nomes:
        alvo = set(nomes)
        itens = [it for it in itens if it.cenario.nome in alvo]
        if not itens:
            raise ValueError(f"nenhum cenario casou {sorted(alvo)}")
    return itens


class GuardaOrcamento:
    """Teto de custo da rodada: acumula o custo MEDIDO por jornada e sinaliza o estouro.

    Checado ANTES de iniciar cada jornada -- overshoot maximo = as jornadas ja em voo (1 no modo
    sequencial). `registrar(None)` e no-op (jornada sem usage medivel nao conta)."""

    def __init__(self, teto_brl: float) -> None:
        self.teto_brl = teto_brl
        self._acumulado = 0.0

    def registrar(self, custo_brl: float | None) -> None:
        if custo_brl:
            self._acumulado += custo_brl

    @property
    def acumulado_brl(self) -> float:
        return self._acumulado

    @property
    def estourou(self) -> bool:
        return self._acumulado >= self.teto_brl


def custo_da_jornada(traj: Trajetoria, cliente: Any) -> float:
    """Custo total de UMA jornada (PURO): turnos da IA + chamadas do cliente-LLM (se houver)."""
    custo = sum(p.custo_brl or 0.0 for p in traj.passos)
    return custo + float(getattr(cliente, "custo_brl_acumulado", 0.0) or 0.0)


def _construir_cliente(item: ItemMassa) -> ClienteLike:
    if item.tipo == "robo":
        assert isinstance(item.cenario, Cenario)
        return ClienteSimulado(variar_persona(item.cenario.persona, item.perfil))
    assert isinstance(item.cenario, CenarioFixo)
    return ClienteRoteirizado(item.cenario.mensagens_cliente)


def _git_sha() -> str | None:
    git = shutil.which("git")
    if git is None:
        return None
    try:
        # S603: args fixos (binario resolvido + literais) — telemetria do meta.json, sem input externo.
        return subprocess.run(  # noqa: S603
            [git, "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except Exception:
        return None


async def _rodar_item(
    runner: Any, item: ItemMassa
) -> tuple[dict[str, Any] | None, float, str | None]:
    """Roda UMA jornada na sua propria conexao/transacao (rollback+close sempre, como
    `gerar_conversas._rodar`: um item que quebra nao contamina nem mata a rodada).
    Retorna (conversa serializada | None, custo medido, erro | None)."""
    conn = await runner._conectar()  # TEST_DATABASE_URL; SystemExit(2) se ausente
    cliente = _construir_cliente(item)
    cen = item.cenario
    try:
        traj = await jornada(
            conn,
            {"estado_inicial": cen.estado_inicial},
            cliente,
            cen.decidir_ato,
            max_turnos=cen.max_turnos,
            apos_seed=_apos_seed,
            fechar_card=cen.fechar_card,
            cobrar_e_fechar=cen.cobrar_e_fechar,
            timeout_sumiu=cen.timeout_sumiu,
        )
        custo = custo_da_jornada(traj, cliente)
        conversa = _serializar(
            cen,
            traj,
            conversa_id=item.conversa_id,
            extras={
                "tipo": item.tipo,
                "perfil": item.perfil.nome if item.perfil else None,
                "custo_brl": round(custo, 6),
            },
        )
        return conversa, custo, None
    except Exception as e:
        import traceback

        traceback.print_exc()
        # cliente-LLM pode ter gasto credito mesmo na falha -- o guard ainda conta esse residuo.
        return None, custo_da_jornada(Trajetoria(), cliente), f"{type(e).__name__}: {e}"
    finally:
        try:
            await conn.rollback()
        except Exception as rb:  # higiene; close() ja garante zero persistencia
            print(f"  (rollback best-effort falhou: {type(rb).__name__})", file=sys.stderr)
        await conn.close()


async def rodar_massa(
    plano: list[ItemMassa],
    *,
    teto_brl: float,
    paralelo: int = 1,
    dir_rodada: Path,
) -> dict[str, Any]:
    """Roda o plano com teto de custo e escrita incremental; devolve o meta da rodada.

    needs_db + needs_anthropic_api. `paralelo` N>1 roda N jornadas em voo (cada uma com conexao
    propria); o guard fica atrasado em ate N itens -- manter N<=3 (rate limit Anthropic: sao 2
    LLMs por turno por jornada)."""
    runner = _carregar_runner()
    guarda = GuardaOrcamento(teto_brl)
    # os.makedirs (nao Path.mkdir): ASYNC240 do ruff; blocking trivial num CLI de operador.
    os.makedirs(dir_rodada, exist_ok=True)
    arquivo = dir_rodada / "massa.jsonl"
    lock_escrita = asyncio.Lock()
    inicio = time.monotonic()
    itens_meta: list[dict[str, Any]] = []
    proximo = 0
    abortado = False

    async def _worker() -> None:
        nonlocal proximo, abortado
        while True:
            if proximo >= len(plano):
                return
            if guarda.estourou:
                abortado = True
                return
            item = plano[proximo]
            proximo += 1
            rotulo = f"[{proximo}/{len(plano)}] {item.conversa_id}"
            conversa, custo, erro = await _rodar_item(runner, item)
            guarda.registrar(custo)
            async with lock_escrita:
                if conversa is not None:
                    with arquivo.open("a", encoding="utf-8") as f:
                        f.write(json.dumps(conversa, ensure_ascii=False) + "\n")
                itens_meta.append(
                    {
                        "conversa_id": item.conversa_id,
                        "tipo": item.tipo,
                        "perfil": item.perfil.nome if item.perfil else None,
                        "custo_brl": round(custo, 6),
                        "erro": erro,
                    }
                )
            status = "FALHOU -- " + erro if erro else "ok"
            print(
                f"{rotulo}: {status} (R${custo:.2f}; acumulado R${guarda.acumulado_brl:.2f}"
                f" de R${guarda.teto_brl:.2f})"
            )

    await asyncio.gather(*(_worker() for _ in range(max(1, paralelo))))

    meta = {
        "carimbo": dir_rodada.name,
        "n_planejado": len(plano),
        "n_gerado": sum(1 for m in itens_meta if not m["erro"]),
        "n_falhou": sum(1 for m in itens_meta if m["erro"]),
        "custo_total_brl": round(guarda.acumulado_brl, 4),
        "teto_brl": teto_brl,
        "abortado_por_orcamento": abortado,
        "paralelo": paralelo,
        "git_sha": _git_sha(),
        "duracao_s": round(time.monotonic() - inicio, 1),
        "itens": itens_meta,
    }
    (dir_rodada / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return meta


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]  # console Windows cp1252
    parser = argparse.ArgumentParser(
        description="Rodada em massa de jornadas E2E (needs_db + needs_anthropic_api; CUSTA CREDITO)."
    )
    parser.add_argument(
        "--k-robo", type=int, default=2, help="amostras por cenario robo (default 2)."
    )
    parser.add_argument(
        "--cenario", action="append", help="nome do cenario a rodar (repetivel; default todos)."
    )
    parser.add_argument("--sem-fixos", action="store_true", help="exclui os cenarios fixos.")
    parser.add_argument("--sem-heldout", action="store_true", help="exclui o held-out.")
    parser.add_argument(
        "--paralelo", type=int, default=1, help="jornadas em voo (default 1; recomendado <=3)."
    )
    parser.add_argument(
        "--teto-brl", type=float, default=50.0, help="teto de custo da rodada em BRL (default 50)."
    )
    parser.add_argument(
        "--semente", type=int, default=0, help="semente da composicao de perfis (default 0)."
    )
    parser.add_argument(
        "--rodada",
        help="dir de rodada existente (continua/appenda); default cria novo por carimbo.",
    )
    parser.add_argument(
        "--usar-database-url",
        action="store_true",
        help="DELIBERADO: usa o DATABASE_URL do .env (PROD) como TEST_DATABASE_URL. O arnes nunca "
        "commita (rollback sempre); padrao do projeto p/ needs_db.",
    )
    parser.add_argument(
        "--ingerir-calibracao",
        action="store_true",
        help="apos a rodada, grava as conversas como rodada de calibracao no banco do PAINEL "
        "(escrita COMMITADA, §0 -- opt-in explicito). Reusa o runner.",
    )
    parser.add_argument(
        "--rodada-nome", help="nome da rodada de calibracao (exige --ingerir-calibracao)."
    )
    args = parser.parse_args()

    if args.usar_database_url:
        import os

        from barra.settings import get_settings

        os.environ.setdefault("TEST_DATABASE_URL", get_settings().database_url)

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    plano = montar_plano(
        k_robo=args.k_robo,
        incluir_fixos=not args.sem_fixos,
        incluir_heldout=not args.sem_heldout,
        nomes=args.cenario,
        semente=args.semente,
    )
    n_robo = sum(1 for it in plano if it.tipo == "robo")
    n_fixo = len(plano) - n_robo
    estimativa = n_robo * _ESTIMATIVA_ROBO_BRL + n_fixo * _ESTIMATIVA_FIXO_BRL
    print(
        f"rodada: {len(plano)} jornadas ({n_robo} robo + {n_fixo} fixas/held-out); "
        f"estimativa ~R${estimativa:.0f}, teto R${args.teto_brl:.0f}."
    )

    # Tracing do sim (Langfuse-sim; no-op sem chaves) -- mesma ligacao do gerar_conversas.
    from barra.core.tracing import setup_langfuse_sim, setup_tracing_sim
    from barra.settings import get_settings

    setup_tracing_sim(get_settings())
    setup_langfuse_sim(get_settings())

    dir_rodada = Path(args.rodada) if args.rodada else _RODADAS / time.strftime("%Y%m%dT%H%M%S")
    meta = asyncio.run(
        rodar_massa(plano, teto_brl=args.teto_brl, paralelo=args.paralelo, dir_rodada=dir_rodada)
    )
    print(
        f"\nrodada gravada: {dir_rodada} ({meta['n_gerado']} conversas, "
        f"R${meta['custo_total_brl']:.2f}"
        + (", ABORTADA POR ORCAMENTO" if meta["abortado_por_orcamento"] else "")
        + ")"
    )

    if args.ingerir_calibracao:
        runner = _carregar_runner()
        conversas = [
            json.loads(linha)
            for linha in (dir_rodada / "massa.jsonl").read_text(encoding="utf-8").splitlines()
            if linha.strip()
        ]
        nome = args.rodada_nome or f"massa-{dir_rodada.name}"
        asyncio.run(runner._persistir_calibracao(nome, conversas))

    if get_settings().langfuse_public_key:
        try:
            from langfuse import get_client

            get_client().flush()
        except ModuleNotFoundError:
            pass


if __name__ == "__main__":
    main()
