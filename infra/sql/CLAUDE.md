# infra/sql/CLAUDE.md

Escopo: migrations SQL puras. Sem alembic, sem flyway, sem prisma migrate — ver ADR-0002.

## Formato e numeração

Nome obrigatório: `NNNN_descricao_curta.sql`, sequencial de 4 dígitos. Para escolher o NNNN:

**Modo manual (humano):** liste o diretório e pegue `max(NNNN) + 1`.

**Modo pipeline (worktrees paralelas):** use o helper `scripts/proxima-migration.ps1`. Listar o diretório à mão dentro de uma worktree não enxerga migrations criadas em outras worktrees ativas — overnight 2026-05-12 produziu duas migrations `0031` distintas pelo mesmo overnight (colidiriam no merge). O helper considera main + todas as worktrees + reservas vivas com lock por arquivo:

```bash
# Reservar próximo NNNN (TTL 30min)
powershell -NoProfile -File scripts/proxima-migration.ps1 -Reserve '<slug>'
# stdout: 4 dígitos (ex: 0031)

# Após commitar o .sql, liberar:
powershell -NoProfile -File scripts/proxima-migration.ps1 -Release '<slug>'
```

Não pule números, não preencha "buracos" antigos.

> **Roadmap (Opção B)**: migrar para timestamp UTC `YYYYMMDDHHMMSS_*.sql` resolve colisão sem helper, ao custo de migrar todas as migrations existentes e atualizar `make migrate`. Não fazer no MVP — a operação só executa um overnight por vez e o helper já resolve o problema imediato.

## Migrations aplicadas são imutáveis

Já rodou em qualquer ambiente (dev, stage, prod)? **Não renumere, não edite o conteúdo.** Para corrigir, escreva nova migration que aplica o ajuste (DROP/ALTER/UPDATE). Renumerar uma aplicada deixa ambientes inconsistentes — exatamente o que `0030_remove_modelo_faq.sql` (que substituiu uma 0025 errada) corrigiu.

## Idempotência obrigatória

Toda migration precisa rodar 2x sem quebrar:

- `CREATE TABLE IF NOT EXISTS …`
- `ALTER TABLE … ADD COLUMN IF NOT EXISTS …`
- `INSERT … ON CONFLICT DO NOTHING` para seeds
- Para `CREATE POLICY`/`CREATE TRIGGER`: envelope com `DROP … IF EXISTS` antes

## Aplicação

Três caminhos equivalentes:

- `make migrate` a partir de `api/` (exige `DATABASE_URL`) — itera os arquivos em ordem.
- `psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f NNNN_*.sql` direto.
- Supabase Studio (colar e rodar) para hotfix manual.

Não use feature exclusiva do Studio que não rode no `psql` — quebra a paridade.

## RLS é o padrão (Supabase managed)

Toda tabela nova precisa **ou** `ALTER TABLE … ENABLE ROW LEVEL SECURITY` + policies explícitas, **ou** carregar `COMMENT ON TABLE … IS 'interna: sem RLS porque …'`. Tabela exposta sem decisão registrada é vazamento esperando para acontecer.
