#!/usr/bin/env bash
# Backup diário do Postgres (Supabase self-hosted) do Barra — única fonte de verdade.
#
# Tira um dump lógico custom-format do banco inteiro + os globals (roles), valida a
# integridade do dump e aplica retenção. Roda no HOST self-hosted via cron.
# Procedimento de restore e drill mensal: infra/runbooks/backup-restore-postgres.md
#
# Por que dockerizado: pg_dump exige versão >= servidor. O servidor é PG 15.8; rodar
# pg_dump por uma imagem postgres:15 casada evita "server version mismatch" sem depender
# do binário do host.
set -euo pipefail

: "${DATABASE_URL:?defina DATABASE_URL=postgresql://postgres:...@db.procexai.tech:5433/postgres?sslmode=disable}"
BACKUP_DIR="${BARRA_BACKUP_DIR:-/var/backups/barra}"
RETENCAO_DIAS="${BARRA_BACKUP_RETENCAO_DIAS:-14}"
PG_IMAGE="${BARRA_PG_IMAGE:-postgres:15}"   # casar com o servidor (PG 15.8); mismatch quebra pg_dump
STAMP="$(date -u +%Y%m%d_%H%M%S)"
BASE="barra_pg_${STAMP}"

mkdir -p "${BACKUP_DIR}"

# Roda um binário do postgres na imagem casada, com BACKUP_DIR montado em /backup.
run_pg() {
  docker run --rm -e DATABASE_URL="${DATABASE_URL}" -v "${BACKUP_DIR}:/backup" "${PG_IMAGE}" "$@"
}

echo "[backup] ${BASE}: dump do banco -> ${BACKUP_DIR}/${BASE}.dump"
# Dump FIEL (mantém owners): a flexibilidade fica no restore (pg_restore --no-owner).
run_pg pg_dump --format=custom --file="/backup/${BASE}.dump" "${DATABASE_URL}"

echo "[backup] ${BASE}: globals (roles/grants) -> ${BACKUP_DIR}/${BASE}.globals.sql"
# --no-role-passwords: não guardar credencial no backup em disco (senhas vêm do compose do Supabase).
run_pg pg_dumpall --globals-only --no-role-passwords -d "${DATABASE_URL}" \
  > "${BACKUP_DIR}/${BASE}.globals.sql"

echo "[backup] ${BASE}: validando integridade do dump (pg_restore --list)"
run_pg pg_restore --list "/backup/${BASE}.dump" > /dev/null

TAMANHO="$(du -h "${BACKUP_DIR}/${BASE}.dump" | cut -f1)"
echo "[backup] ${BASE}: OK (${TAMANHO})"

echo "[backup] retenção: removendo backups > ${RETENCAO_DIAS}d em ${BACKUP_DIR}"
find "${BACKUP_DIR}" -maxdepth 1 -type f -name 'barra_pg_*' -mtime "+${RETENCAO_DIAS}" -print -delete

echo "[backup] concluído: ${BASE}"
