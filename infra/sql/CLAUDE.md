# infra/sql/CLAUDE.md

Escopo: migrations SQL puras. Sem alembic, sem flyway, sem prisma migrate — ver ADR-0002.

## Formato e numeração

Nome obrigatório: `NNNN_descricao_curta.sql`, sequencial de 4 dígitos. Antes de criar uma nova, liste o diretório e pegue `max(NNNN) + 1`. Não pule números, não preencha "buracos" antigos.

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
