"""Vincula uma instância Evolution existente (legada) a uma modelo do DB.

Necessário UMA VEZ por instância legada após a migração 0029, porque o webhook
agora exige que o `instance_id` esteja cadastrado em
`barravips.modelos.evolution_instance_id`. Sem esse vínculo, mensagens da
instância legada caem em `unknown_instance` e são silenciosamente descartadas.

Uso:
    DATABASE_URL=postgresql://... \\
        uv run python scripts/vincular_instance_legacy.py \\
        --instance lucia \\
        --modelo-id 11111111-2222-3333-4444-555555555555 \\
        --yes

Lookup alternativo pelo número de WhatsApp:
    uv run python scripts/vincular_instance_legacy.py \\
        --instance lucia --numero +5521999999999

Roda dentro do projeto Python (deps já presentes em api/) — execute da raiz do
repo com `uv run python scripts/vincular_instance_legacy.py ...`.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Permite rodar a partir da raiz do repo sem instalar o pacote.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api" / "src"))

import psycopg
from psycopg.rows import dict_row


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instance", required=True, help="instance_id na Evolution (ex: lucia)")
    grupo = parser.add_mutually_exclusive_group(required=True)
    grupo.add_argument("--modelo-id", help="UUID da modelo no DB")
    grupo.add_argument("--numero", help="numero_whatsapp da modelo (ex: +5521999999999)")
    parser.add_argument("--yes", action="store_true", help="aplica sem confirmação interativa")
    args = parser.parse_args()

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("erro: DATABASE_URL não definida no ambiente.", file=sys.stderr)
        return 2

    with psycopg.connect(database_url, row_factory=dict_row, autocommit=False) as conn:
        existing = _modelo_por_instance(conn, args.instance)
        if existing is not None:
            print(
                f"instance '{args.instance}' já está vinculada à modelo "
                f"{existing['nome']} (id={existing['id']}). Nada a fazer.",
            )
            return 0

        if args.modelo_id:
            modelo = _modelo_por_id(conn, args.modelo_id)
            if modelo is None:
                print(f"erro: modelo {args.modelo_id} não encontrada.", file=sys.stderr)
                return 1
        else:
            modelo = _modelo_por_numero(conn, args.numero)
            if modelo is None:
                print(f"erro: nenhuma modelo com numero_whatsapp={args.numero}.", file=sys.stderr)
                return 1

        if modelo["evolution_instance_id"] and modelo["evolution_instance_id"] != args.instance:
            print(
                f"erro: modelo {modelo['nome']} já tem outra instance vinculada "
                f"({modelo['evolution_instance_id']}). Despareie pelo painel antes.",
                file=sys.stderr,
            )
            return 1

        print(f"Vincular instance '{args.instance}' à modelo:")
        print(f"  id:     {modelo['id']}")
        print(f"  nome:   {modelo['nome']}")
        print(f"  numero: {modelo['numero_whatsapp']}")
        print(f"  status: {modelo['status']}  evolution_status: {modelo['evolution_status']}")
        if not args.yes:
            resp = input("Confirmar? [y/N] ").strip().lower()
            if resp not in {"y", "yes", "s", "sim"}:
                print("abortado.")
                return 0

        conn.execute(
            """
            UPDATE barravips.modelos
               SET evolution_instance_id = %s,
                   evolution_status = 'conectado',
                   evolution_pareado_em = COALESCE(evolution_pareado_em, now())
             WHERE id = %s
            """,
            (args.instance, modelo["id"]),
        )
        conn.commit()
        print(f"OK: instance '{args.instance}' vinculada à modelo {modelo['nome']}.")
        return 0


def _modelo_por_instance(conn: psycopg.Connection, instance: str) -> dict | None:
    cur = conn.execute(
        "SELECT id, nome FROM barravips.modelos WHERE evolution_instance_id = %s",
        (instance,),
    )
    return cur.fetchone()


def _modelo_por_id(conn: psycopg.Connection, modelo_id: str) -> dict | None:
    cur = conn.execute(
        """
        SELECT id, nome, numero_whatsapp, status,
               evolution_instance_id, evolution_status
          FROM barravips.modelos
         WHERE id = %s
        """,
        (modelo_id,),
    )
    return cur.fetchone()


def _modelo_por_numero(conn: psycopg.Connection, numero: str) -> dict | None:
    cur = conn.execute(
        """
        SELECT id, nome, numero_whatsapp, status,
               evolution_instance_id, evolution_status
          FROM barravips.modelos
         WHERE numero_whatsapp = %s
        """,
        (numero,),
    )
    return cur.fetchone()


if __name__ == "__main__":
    sys.exit(main())
