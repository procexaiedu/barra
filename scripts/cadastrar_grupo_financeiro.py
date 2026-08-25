"""Cadastra um Grupo financeiro (spec 0005) — o passo 2 do runbook de go-live.

O vinculo grupo↔modelo e o que AUTORIZA o agente a falar num grupo (closed-world): enquanto ele
nao existe, a mensagem e ignorada com log. Por isso este passo e SQL a mao no runbook — e por isso
ele merece um script: sao quatro escritas em tres tabelas, e errar o `modelo_id` liga o agente no
grupo da pessoa errada.

Idempotente (`ON CONFLICT DO NOTHING` em tudo) e **dry-run por padrao**: sem `--confirmar` ele so
mostra o que faria e o estado atual do banco.

Uso (da raiz do repo; `DATABASE_URL` do ambiente ou de api/.env):

    uv run --project api python scripts/cadastrar_grupo_financeiro.py \\
        --modelo "Yasmin" \\
        --jid 1203634xxxxxxxxxx@g.us \\
        --nome-do-grupo "Modelo Yasmin Ruiva/ financeiro" \\
        --apelido bianca --apelido yasmin

    # ... confira a saida e repita com --confirmar

Descobrir o JID: adicione o numero da ProceX ao grupo, mande uma mensagem e leia o log da API
(`grupo_financeiro_nao_cadastrado jid=...`). O agente fica MUDO ate este script rodar.

A chave Pix de fechamento da casa entra por `--chave-da-casa` (opcional, tambem idempotente): sem
ela, todo comprovante que a modelo mandar vem com "⚠️ chave fora da lista da casa".
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api" / "src"))

import psycopg
from psycopg.rows import dict_row

from barra.dominio.grupo_financeiro.anuncio import normalizar
from barra.dominio.grupo_financeiro.comprovante import normalizar_chave
from barra.settings import get_settings


async def _modelo(conn: psycopg.AsyncConnection[dict[str, Any]], busca: str) -> dict[str, Any]:
    """Resolve a modelo por UUID ou por nome exato. Ambiguidade e ERRO, nunca palpite."""
    try:
        alvo = UUID(busca)
    except ValueError:
        cur = await conn.execute(
            "SELECT id, nome, status FROM barravips.modelos WHERE lower(nome) = lower(%s)",
            (busca,),
        )
    else:
        cur = await conn.execute(
            "SELECT id, nome, status FROM barravips.modelos WHERE id = %s", (alvo,)
        )
    achadas = list(await cur.fetchall())
    if not achadas:
        raise SystemExit(f"modelo nao encontrada: {busca!r}")
    if len(achadas) > 1:
        nomes = ", ".join(f"{m['id']} ({m['nome']})" for m in achadas)
        raise SystemExit(f"nome ambiguo — passe o UUID. Candidatas: {nomes}")
    return achadas[0]


async def rodar(args: argparse.Namespace) -> int:
    settings = get_settings()
    url = args.database_url or settings.database_url
    conn = await psycopg.AsyncConnection.connect(url, autocommit=False, row_factory=dict_row)
    try:
        cur = await conn.execute("SELECT current_database() AS db, inet_server_addr() AS host")
        onde = await cur.fetchone()
        print(f"banco: {onde['db'] if onde else '?'} @ {onde['host'] if onde else '?'}")

        modelo = await _modelo(conn, args.modelo)
        print(f"modelo: {modelo['id']} · {modelo['nome']} · status={modelo['status']}")
        if modelo["status"] != "ativa":
            print("  ⚠️  modelo nao esta 'ativa' — o cadastro segue, mas confirme se e a certa.")

        print(f"grupo:  {args.jid} · {args.nome_do_grupo!r}")
        print(f"nomes de anuncio: {', '.join(args.apelido) or '(nenhum novo)'}")
        if args.chave_da_casa:
            print(f"chave da casa: {args.chave_da_casa} · titular {args.titular_da_casa!r}")

        if not args.confirmar:
            await _mostrar_estado(conn, modelo["id"], args.jid)
            print("\nDRY-RUN — nada foi escrito. Repita com --confirmar.")
            await conn.rollback()
            return 0

        for apelido in args.apelido:
            await conn.execute(
                """
                INSERT INTO barravips.modelo_nomes_anuncio (modelo_id, nome, nome_normalizado)
                VALUES (%s, %s, %s) ON CONFLICT DO NOTHING
                """,
                (modelo["id"], apelido, normalizar(apelido)),
            )
        await conn.execute(
            """
            INSERT INTO barravips.grupos_financeiros (modelo_id, jid, nome)
            VALUES (%s, %s, %s) ON CONFLICT (jid) DO NOTHING
            """,
            (modelo["id"], args.jid, args.nome_do_grupo),
        )
        if args.chave_da_casa:
            await conn.execute(
                """
                INSERT INTO barravips.chaves_pix_conhecidas
                    (chave, chave_normalizada, titular, descricao)
                VALUES (%s, %s, %s, %s) ON CONFLICT (chave_normalizada) DO NOTHING
                """,
                (
                    args.chave_da_casa,
                    normalizar_chave(args.chave_da_casa),
                    args.titular_da_casa,
                    "Chave de fechamento da casa (go-live do Agente financeiro).",
                ),
            )
        await conn.commit()
        print("\n✅ aplicado.")
        await _mostrar_estado(conn, modelo["id"], args.jid)
        return 0
    finally:
        await conn.close()


async def _mostrar_estado(
    conn: psycopg.AsyncConnection[dict[str, Any]], modelo_id: UUID, jid: str
) -> None:
    """O que o banco tem AGORA — a unica coisa em que se deve confiar depois de escrever."""
    cur = await conn.execute(
        "SELECT nome FROM barravips.modelo_nomes_anuncio WHERE modelo_id = %s ORDER BY nome",
        (modelo_id,),
    )
    print(f"\nnomes de anuncio no banco: {[linha['nome'] for linha in await cur.fetchall()]}")
    cur = await conn.execute(
        "SELECT id, nome, ativo FROM barravips.grupos_financeiros WHERE jid = %s", (jid,)
    )
    linha = await cur.fetchone()
    print(f"grupo no banco: {linha or '(nao cadastrado)'}")
    cur = await conn.execute("SELECT count(*) AS n FROM barravips.chaves_pix_conhecidas")
    linha = await cur.fetchone()
    print(f"chaves Pix conhecidas: {linha['n'] if linha else 0}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--modelo", required=True, help="UUID ou nome exato da modelo")
    parser.add_argument("--jid", required=True, help="JID do grupo (…@g.us)")
    parser.add_argument("--nome-do-grupo", default="", help="so para painel e log")
    parser.add_argument(
        "--apelido", action="append", default=[], help="Nome de anuncio (repetivel)"
    )
    parser.add_argument("--chave-da-casa", default=None, help="chave Pix de fechamento da casa")
    parser.add_argument("--titular-da-casa", default=None, help="titular da chave acima")
    parser.add_argument("--database-url", default=None, help="sobrescreve o DATABASE_URL")
    parser.add_argument("--confirmar", action="store_true", help="escreve (default: dry-run)")
    args = parser.parse_args()
    if not args.jid.endswith("@g.us"):
        raise SystemExit("o JID de grupo termina em @g.us — confira o que voce copiou do log.")
    return asyncio.run(rodar(args))


if __name__ == "__main__":
    raise SystemExit(main())
