# Backup e restore do Postgres

Como o banco de produção é protegido contra perda e como reconstruí-lo. Criado em 2026-05-30 (DEPLOY-04).

## Por que este runbook existe

O Postgres self-hosted é a **única fonte de verdade** do Barra (histórico de conversas, atendimentos, financeiro — ver [topologia-banco.md](topologia-banco.md)). Não há réplica nem ponto de restauração: uma queda de disco ou um `DROP` errado hoje perde tudo de forma irreversível. Este runbook fecha esse buraco com um **dump lógico diário** e um procedimento de **restore testado**.

Escopo P0: dump lógico (`pg_dump -Fc`) com RPO de ~24h. PITR (WAL archiving / pgBackRest) fica como upgrade de P1 — ver "Upgrade path".

## O que o backup faz

[`infra/backup/backup_postgres.sh`](../backup/backup_postgres.sh), rodando no host self-hosted via cron, a cada execução:

1. Dump custom-format do banco `postgres` inteiro → `barra_pg_<UTC>.dump` (fiel: mantém owners).
2. Globals (roles/grants) → `barra_pg_<UTC>.globals.sql` (sem senhas — as senhas dos roles vêm do compose do Supabase).
3. Valida a integridade do dump com `pg_restore --list` (TOC legível = arquivo não-corrompido).
4. Retenção: apaga backups com mais de `BARRA_BACKUP_RETENCAO_DIAS` (default 14) dias.

O `pg_dump` roda por uma imagem `postgres:15` casada com o servidor (PG 15.8) — versão do `pg_dump` menor que a do servidor quebra com "server version mismatch".

| Variável | Default | Função |
|---|---|---|
| `DATABASE_URL` | — (obrigatória) | `postgresql://postgres:...@db.procexai.tech:5433/postgres?sslmode=disable` |
| `BARRA_BACKUP_DIR` | `/var/backups/barra` | onde os dumps ficam |
| `BARRA_BACKUP_RETENCAO_DIAS` | `14` | janela de retenção |
| `BARRA_PG_IMAGE` | `postgres:15` | imagem casada com o servidor |

## Agendar (host self-hosted)

O backup roda no **host** (precisa de `docker` e alcance a `db.procexai.tech:5433`), não na stack do Barra — o Postgres vive na stack do Supabase, separada.

1. Versionar o script no host (clone do repo ou cópia direta) e dar permissão:
   ```bash
   chmod +x /opt/barra/infra/backup/backup_postgres.sh
   ```
2. Guardar a `DATABASE_URL` num arquivo de ambiente só-root (não commitar):
   ```bash
   install -m 600 /dev/null /etc/barra/backup.env
   printf 'DATABASE_URL=postgresql://postgres:SENHA@db.procexai.tech:5433/postgres?sslmode=disable\n' \
     | tee /etc/barra/backup.env >/dev/null
   ```
3. Crontab do root — diário às 03:10 (horário de baixa carga), log em arquivo:
   ```cron
   10 3 * * * set -a; . /etc/barra/backup.env; set +a; /opt/barra/infra/backup/backup_postgres.sh >> /var/log/barra-backup.log 2>&1
   ```
4. Rodar uma vez à mão e conferir que o `.dump` e o `.globals.sql` apareceram em `/var/backups/barra` com tamanho > 0.

> Alternativa Swarm: um serviço com `deploy.mode: replicated` + loop `sleep`/`ofelia` pode disparar o mesmo script; o host crontab é mais simples para P0 e foi o escolhido.

## Restore

Os dumps são auto-suficientes; restaure com a mesma `postgres:15`. **Sempre restaure num alvo de teste primeiro** — o drill mensal (abaixo) exige isso, e em DR real você valida num banco temporário antes de promover.

### A) Restore num banco de TESTE (drill — não-destrutivo ao prod)

Cria um banco descartável no mesmo servidor e restaura nele. Não toca os dados de prod.

```bash
DUMP=/var/backups/barra/barra_pg_<UTC>.dump
ADMIN_URL='postgresql://postgres:SENHA@db.procexai.tech:5433/postgres?sslmode=disable'
TESTE_URL='postgresql://postgres:SENHA@db.procexai.tech:5433/barra_restore_drill?sslmode=disable'

# 1. cria o banco de teste
docker run --rm postgres:15 psql "$ADMIN_URL" -c 'CREATE DATABASE barra_restore_drill;'

# 2. restaura o dump nele (--no-owner: o banco de teste não tem os roles de prod)
docker run --rm -v /var/backups/barra:/backup postgres:15 \
  pg_restore --no-owner --no-privileges --dbname "$TESTE_URL" "/backup/$(basename "$DUMP")"

# 3. valida: contagens batem com o esperado do dia do dump
docker run --rm postgres:15 psql "$TESTE_URL" -c \
  "SELECT 'conversas' t, count(*) FROM barravips.conversas
   UNION ALL SELECT 'atendimentos', count(*) FROM barravips.atendimentos
   UNION ALL SELECT 'eventos', count(*) FROM barravips.eventos;"

# 4. derruba o banco de teste
docker run --rm postgres:15 psql "$ADMIN_URL" -c 'DROP DATABASE barra_restore_drill;'
```

### B) Restore de DR real (perda do banco)

1. Suba uma instância Postgres limpa (recriar a stack do Supabase recria os roles base).
2. Restaure os globals (roles/grants) **antes** do dump, para os owners casarem:
   ```bash
   docker run --rm -v /var/backups/barra:/backup postgres:15 \
     psql "$NOVO_URL" -f "/backup/barra_pg_<UTC>.globals.sql"
   ```
3. Restaure o banco mantendo owners:
   ```bash
   docker run --rm -v /var/backups/barra:/backup postgres:15 \
     pg_restore --clean --if-exists --dbname "$NOVO_URL" "/backup/barra_pg_<UTC>.dump"
   ```
4. Reaplique as senhas dos roles via o compose/env do Supabase (o backup não as guarda).
5. Verifique `current_database()` e contagens das tabelas-chave antes de repontar o app.

## Drill de restore mensal (obrigatório)

Backup não-testado não é backup. **Uma vez por mês**, execute o "Restore A" com o dump mais recente e registre abaixo. O drill prova que o dump é restaurável e que as contagens fecham.

Checklist:
- [ ] `pg_restore` do dump mais recente num banco `barra_restore_drill` conclui sem erro.
- [ ] contagens de `conversas`/`atendimentos`/`eventos` batem com a ordem de grandeza esperada.
- [ ] banco de teste derrubado ao fim.

| Data | Dump usado | Resultado | Por |
|---|---|---|---|
| _(pendente — primeiro drill)_ | | | |

## Limitações e upgrade path

- **RPO ~24h**: perda entre o último dump e o incidente. Suficiente para P0; para RPO menor, evoluir para **WAL archiving + pgBackRest** (PITR) — restaura a um instante arbitrário.
- **Dump lógico** restaura schema+dados, não o estado físico do cluster. Para uma operação maior, `pgBackRest` faz backup físico incremental.
- **Off-site**: hoje os dumps ficam no mesmo host. Replicar `/var/backups/barra` para storage externo (MinIO/S3) protege contra perda do host inteiro — recomendado assim que o backup local estiver de pé.

## Regras

- Nunca rodar o backup/restore contra prod sem confirmar `current_database()`/`inet_server_addr()` — dev = prod (um banco só).
- O `restore A` (drill) é não-destrutivo; o `restore B` (`--clean`) é destrutivo — só em DR real, nunca contra o banco vivo.
