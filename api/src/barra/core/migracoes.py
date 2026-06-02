"""Guarda de ambiente para aplicação de migrations (DEPLOY-05/06).

Lógica PURA e testável de filtragem por nome de arquivo: em `producao`, recusar
qualquer arquivo cujo nome contenha `seed` (case-insensitive, qualquer posição) —
tanto o prefixo legacy `00NN_seed_*.sql` quanto o timestamp novo
(`..._seed_...`, `..._seed_cleanup.sql`). Os seeds são dados de teste descartáveis
da interface (ver infra/sql/CLAUDE.md / runbook) e nunca devem ir para o banco
de produção self-hosted.

Usada por `scripts/aplicar_sql.py` antes de tocar o banco.
"""

from __future__ import annotations

from pathlib import PurePath

NOME_SEED = "seed"


def e_arquivo_seed(nome_arquivo: str) -> bool:
    """True se o nome do arquivo contém `seed` (case-insensitive, qualquer posição).

    Considera só o nome (não o caminho), para não confundir um diretório chamado
    `seeds/` com um arquivo de schema dentro dele.
    """
    return NOME_SEED in PurePath(nome_arquivo).name.casefold()


def seed_bloqueado(nome_arquivo: str, ambiente: str) -> bool:
    """True se este arquivo deve ser RECUSADO neste ambiente.

    Em `producao`, seeds são bloqueados. Nos demais ambientes
    (`desenvolvimento`/`teste`), nada é bloqueado.
    """
    return ambiente == "producao" and e_arquivo_seed(nome_arquivo)
