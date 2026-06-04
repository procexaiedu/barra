"""Reset do agente para uma modelo (default: instancia de teste 'lucia').

Zera todo o estado transacional gerado pela operacao do agente — conversas,
mensagens, atendimentos, bloqueios, escaladas, eventos, envios e cards — de UMA
modelo, deixando o cadastro (modelos/programas/disponibilidade) e os dados das
OUTRAS modelos intactos. Serve para recomecar um teste de ponta a ponta do zero.

Escopo (decidido em 2026-05-29):
  - Filtra por barravips.modelos.evolution_instance_id = <instancia>.
  - Apaga clientes que ficarem ORFAOS (sem nenhuma conversa/atendimento restante
    com qualquer modelo) — preserva o cliente cross-modelo e os seeds do mapa.
  - tool_calls NAO e' tocado por padrao (respeita o escopo "so a modelo"): e' a
    guarda de idempotencia por turno_id = uuid5(NS_TURNO, "turno:{conversa_id}:
    {score}:{loop_idx}") (coordenador.py:72). Como a conversa recriada ganha um
    conversa_id novo, o turno_id muda e os tool_calls velhos NUNCA colidem com o
    re-teste. So sao lixo inerte. Use --purge-tool-calls para zerar o log global.
  - Redis: SCAN seletivo pelos ids da modelo (sem FLUSHDB — nao toca a fila ARQ
    de outras modelos).

SEM checkpointer no P0: o estado do LangGraph e' efemero (montado de `mensagens`
a cada turno), entao nao ha tabela de checkpoint para limpar.

Uso (a partir de api/, para herdar o venv com psycopg+redis):

    uv run python ../scripts/reset_agente.py            # DRY-RUN (nada e' commitado)
    uv run python ../scripts/reset_agente.py --apply     # efetiva
    uv run python ../scripts/reset_agente.py --instance outra --apply
    uv run python ../scripts/reset_agente.py --apply --skip-redis
    uv run python ../scripts/reset_agente.py --apply --purge-tool-calls

ATENCAO: o banco alvo e' o prod self-hosted (nao ha base de dev separada). O
dry-run e' read-only (executa os DELETEs e da ROLLBACK; SCAN do Redis nao apaga).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import psycopg
import redis as redis_sync

from barra.webhook.reset_teste import DELETES_RESET

ENV_PATH = Path(__file__).resolve().parent.parent / "api" / ".env"

def ler_env(path: Path) -> dict[str, str]:
    if not path.exists():
        sys.exit(f"ERRO: nao encontrei {path} (rode a partir de api/ com `uv run`).")
    env: dict[str, str] = {}
    for linha in path.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, valor = linha.split("=", 1)
        env[chave.strip()] = valor.strip().strip('"').strip("'")
    return env


def resetar_banco(dsn: str, instancia: str, apply: bool, purge_tool_calls: bool) -> tuple[list, list]:
    """Executa os DELETEs. Sem --apply faz ROLLBACK (impacto real, nada commitado).

    Retorna (conversa_ids, atendimento_ids) para a limpeza do Redis.
    """
    with psycopg.connect(dsn, autocommit=False) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM barravips.modelos WHERE evolution_instance_id = %s",
            (instancia,),
        )
        linha = cur.fetchone()
        if linha is None:
            conn.rollback()
            sys.exit(
                f"ERRO: nenhuma modelo com evolution_instance_id = '{instancia}'. "
                "Crie a modelo de teste antes (ver memoria 'instancia_lucia_compartilhada')."
            )
        modelo_id = linha[0]

        # Captura ANTES dos deletes: ids para o Redis e clientes candidatos a orfao.
        cur.execute("SELECT id FROM barravips.conversas WHERE modelo_id = %s", (modelo_id,))
        conversa_ids = [r[0] for r in cur.fetchall()]
        cur.execute("SELECT id FROM barravips.atendimentos WHERE modelo_id = %s", (modelo_id,))
        atendimento_ids = [r[0] for r in cur.fetchall()]
        cur.execute(
            "SELECT cliente_id FROM barravips.conversas WHERE modelo_id = %s "
            "UNION SELECT cliente_id FROM barravips.atendimentos WHERE modelo_id = %s",
            (modelo_id, modelo_id),
        )
        cliente_ids = [r[0] for r in cur.fetchall()]

        print(f"  modelo_id    = {modelo_id}  (instancia '{instancia}')")
        print(f"  conversas    = {len(conversa_ids)}")
        print(f"  atendimentos = {len(atendimento_ids)}")
        print(f"  clientes vinculados (candidatos a orfao) = {len(cliente_ids)}\n")

        contagens: list[tuple[str, int]] = []
        for rotulo, sql in DELETES_RESET:
            params = (modelo_id, modelo_id) if rotulo == "envios_evolution" else (modelo_id,)
            cur.execute(sql, params)
            contagens.append((rotulo, cur.rowcount))

        # Clientes orfaos: dos vinculados a' modelo, os que nao tem mais nenhuma
        # conversa/atendimento (com qualquer modelo) apos os deletes acima.
        if cliente_ids:
            cur.execute(
                "DELETE FROM barravips.clientes c WHERE c.id = ANY(%s) "
                "AND NOT EXISTS (SELECT 1 FROM barravips.conversas WHERE cliente_id = c.id) "
                "AND NOT EXISTS (SELECT 1 FROM barravips.atendimentos WHERE cliente_id = c.id)",
                (cliente_ids,),
            )
            contagens.append(("clientes (orfaos)", cur.rowcount))

        if purge_tool_calls:
            cur.execute("DELETE FROM barravips.tool_calls")
            contagens.append(("tool_calls (GLOBAL)", cur.rowcount))

        print("  Linhas afetadas por tabela:")
        for rotulo, n in contagens:
            print(f"    {rotulo:<28} {n:>6}")
        print()

        if apply:
            conn.commit()
            print("  >> COMMIT aplicado.\n")
        else:
            conn.rollback()
            print("  >> DRY-RUN: ROLLBACK (nada foi alterado). Use --apply para efetivar.\n")

    return conversa_ids, atendimento_ids


def resetar_redis(url: str, conversa_ids: list, atendimento_ids: list, apply: bool) -> None:
    try:
        r = redis_sync.from_url(url, socket_connect_timeout=5)
        r.ping()
    except Exception as exc:  # noqa: BLE001 — conexao opcional; nao aborta o reset do banco
        print(f"  AVISO: Redis inacessivel ({exc}). Pulei a limpeza.")
        print("  Alternativa via Portainer: docker exec <redis> redis-cli --scan "
              "--pattern '*<conversa_id>*' | xargs redis-cli del\n")
        return

    ids = [str(i) for i in (*conversa_ids, *atendimento_ids)]
    chaves: set[bytes] = set()
    for ident in ids:
        for chave in r.scan_iter(match=f"*{ident}*", count=500):
            chaves.add(chave)

    print(f"  Chaves Redis encontradas para os ids da modelo: {len(chaves)}")
    if chaves and apply:
        r.delete(*chaves)
        print(f"  >> {len(chaves)} chaves apagadas.\n")
    elif chaves:
        amostra = [c.decode("utf-8", "replace") for c in list(chaves)[:10]]
        print("  >> DRY-RUN: nao apagadas. Amostra:")
        for c in amostra:
            print(f"     {c}")
        print()
    else:
        print("  (nada a apagar)\n")


def main() -> None:
    p = argparse.ArgumentParser(description="Reset do agente para uma modelo.")
    p.add_argument("--instance", default="lucia", help="evolution_instance_id (default: lucia)")
    p.add_argument("--apply", action="store_true", help="efetiva (sem isto: dry-run)")
    p.add_argument("--skip-redis", action="store_true", help="nao toca no Redis")
    p.add_argument("--purge-tool-calls", action="store_true",
                   help="zera tool_calls GLOBAL (opcional; ids nunca colidem com re-teste)")
    args = p.parse_args()

    env = ler_env(ENV_PATH)
    dsn = env.get("DATABASE_URL")
    if not dsn:
        sys.exit("ERRO: DATABASE_URL ausente no api/.env")

    modo = "APPLY" if args.apply else "DRY-RUN"
    print(f"\n=== Reset do agente — instancia '{args.instance}' — modo {modo} ===\n")

    conversa_ids, atendimento_ids = resetar_banco(
        dsn, args.instance, args.apply, args.purge_tool_calls
    )

    if args.skip_redis:
        print("  Redis: pulado (--skip-redis).\n")
    else:
        url = env.get("REDIS_URL")
        if not url:
            print("  AVISO: REDIS_URL ausente no api/.env — pulei o Redis.\n")
        else:
            print("  --- Redis ---")
            resetar_redis(url, conversa_ids, atendimento_ids, args.apply)

    print("=== Fim. ===\n")


if __name__ == "__main__":
    main()
