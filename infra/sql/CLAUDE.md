# infra/sql/CLAUDE.md

Escopo: migrations SQL puras. Sem alembic, sem flyway, sem prisma migrate — ver ADR-0002.

## Formato e numeração

Dois formatos aceitos. Ambos ordenam corretamente em `ls infra/sql/*.sql`:

### A) Sequencial 4 dígitos (legacy)

`NNNN_descricao_curta.sql`. Migrations existentes (0001..00NN) seguem nesse formato — não renumere (são imutáveis, ver seção abaixo).

Para escolher o próximo NNNN: liste o diretório e pegue `max(NNNN) + 1`. Não pule números, não preencha "buracos" antigos.

### B) Timestamp UTC (recomendado para mudanças novas)

`YYYYMMDDHHMMSS_descricao_curta.sql` (14 dígitos). Vantagem: **elimina a categoria inteira de colisão NNNN** quando há trabalho em paralelo — timestamps são únicos por segundo e dispensam consultar o diretório. Gere com:

```bash
# PowerShell
[DateTime]::UtcNow.ToString('yyyyMMddHHmmss')
# stdout: 20260513212347
```

Ordering lexicográfico: como `NNNN_` tem 4 dígitos e `YYYYMMDD…_` tem 14, no `ls`/glob do shell todas as legacy `00NN_*` aparecem antes de qualquer timestamp `2026…_*` (char-by-char `'0' < '2'`). `make migrate` aplica em ordem correta automaticamente.

**Recomendação prática:** novas migrations usam timestamp UTC. NNNN só para hotfix manual em sessão única quando o autor confere o número à mão.

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
