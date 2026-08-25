-- =============================================================================
-- 20260820127000_backfill_percentual_comissao_do_nivel.sql
-- Backfill do `vendedores.percentual_comissao` a partir do `nivel` ATUAL de cada
-- vendedor: iniciante -> 4.00, intermediario -> 5.00, avancado -> 6.00.
--
-- ⚠️ **4/5/6, NAO 7** — e o ponto inteiro desta migration. O 7.00 e default de
-- CADASTRO NOVO, nao reprecificacao retroativa de quem ja existe (ADR-0048,
-- Consequencias: "o backfill do percentual a partir do nivel atual de cada
-- vendedor (4/5/6 -> o numero, nao 7)"). A migration irma
-- `20260820126000_vendedores_percentual_e_whatsapp_jid.sql` cria a coluna com
-- DEFAULT 7.00, o que deixa TODO vendedor existente valendo 7% ate esta rodar.
-- As duas sao um par: aplicar a primeira sem esta e dar aumento a equipe inteira
-- em silencio.
--
-- OS NUMEROS SAIEM DE `financeiro_comissao_niveis`, NAO DE UMA LISTA FIXA: e a
-- tabela de config do ADR-0012 e ela pode ter sido ajustada no painel desde
-- entao. Copiar 4/5/6 hardcoded aqui congelaria o valor errado para quem mexeu
-- na config. Vendedor cujo nivel nao tiver linha na config fica com o default
-- 7.00 (LEFT JOIN implicito pelo WHERE: simplesmente nao e atualizado).
--
-- IDEMPOTENCIA — POR QUE A GUARDA POR `schema_migrations` E NAO
-- `WHERE percentual_comissao = 7.00`:
-- este e um UPDATE de DADO, nao um DDL: rodar 2x nao da erro, da o resultado
-- ERRADO. A guarda ingenua ("so mexe em quem ainda esta no default") reverteria
-- para 4.00 um iniciante que o Rossi tivesse promovido a 7.00 no painel — e
-- `make migrate` reaplica TODOS os arquivos do diretorio, entao isso aconteceria
-- em qualquer dev/test que rodasse o alvo duas vezes. A guarda abaixo le e
-- ESCREVE `barravips.schema_migrations` dentro do mesmo bloco, o que a torna
-- one-shot pelos dois caminhos de aplicacao: `scripts/aplicar_sql.py` (que
-- tambem registra, com ON CONFLICT DO NOTHING) e `make migrate`/psql (que nao
-- registra nada — por isso o registro esta AQUI DENTRO).
--
-- Nao e seed: nao cria dado de negocio, ajusta linhas que ja existem. O nome do
-- arquivo evita a palavra "seed" de proposito — `scripts/aplicar_sql.py` recusa
-- aplicar em producao qualquer arquivo cujo nome a contenha, e este PRECISA
-- rodar em producao.
--
-- Aplicacao MANUAL (nunca `make migrate` contra prod), LOGO APOS a irmã:
--   uv run python scripts/aplicar_sql.py \
--     infra/sql/20260820127000_backfill_percentual_comissao_do_nivel.sql
--
-- Conferir ANTES (para saber o que esperar):
--   SELECT nivel, count(*) FROM barravips.vendedores GROUP BY nivel;
--   SELECT * FROM barravips.financeiro_comissao_niveis ORDER BY nivel;
--
-- Conferir DEPOIS (nunca confiar no retorno do script):
--   SELECT nome, nivel, percentual_comissao FROM barravips.vendedores ORDER BY nome;
--   -- esperado: iniciante 4.00 | intermediario 5.00 | avancado 6.00
--   SELECT 1 FROM barravips.schema_migrations
--    WHERE filename = '20260820127000_backfill_percentual_comissao_do_nivel.sql';
-- =============================================================================

BEGIN;

DO $$
DECLARE
  este_arquivo constant text := '20260820127000_backfill_percentual_comissao_do_nivel.sql';
  atualizados int;
BEGIN
  IF EXISTS (
    SELECT 1 FROM barravips.schema_migrations WHERE filename = este_arquivo
  ) THEN
    RAISE NOTICE 'backfill do percentual_comissao ja foi aplicado — nada a fazer';
    RETURN;
  END IF;

  UPDATE barravips.vendedores v
     SET percentual_comissao = n.percentual
    FROM barravips.financeiro_comissao_niveis n
   WHERE n.nivel = v.nivel
     AND v.percentual_comissao IS DISTINCT FROM n.percentual;

  GET DIAGNOSTICS atualizados = ROW_COUNT;
  RAISE NOTICE 'percentual_comissao ajustado pelo nivel em % vendedor(es)', atualizados;

  INSERT INTO barravips.schema_migrations (filename) VALUES (este_arquivo)
  ON CONFLICT (filename) DO NOTHING;
END
$$;

COMMIT;
