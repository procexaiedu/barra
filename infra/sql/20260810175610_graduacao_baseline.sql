-- ---------------------------------------------------------------------------
-- 20260810175610_graduacao_baseline.sql
-- Baseline de conversao do VENDEDOR -- a peca que faltava para o 4o criterio de
-- graduacao do piloto (ADR-0034) sair do "a olho".
--
-- O ADR pede "conversao >= 80% do baseline do vendedor" e confessa, em
-- Consequencias, que "nao existe baseline de conversao por vendedor". Os outros
-- tres criterios sao derivaveis do que ja existe (conversas/atendimentos,
-- julgamentos_turno, escaladas); este NAO e -- o desempenho do vendedor ANTES do
-- cutover nao esta no banco e nao ha como recomputa-lo. Ele e um numero APURADO
-- FORA (caderno do vendedor, corpus historico) e REGISTRADO aqui com procedencia,
-- para que a comparacao seja auditavel em vez de memoria de reuniao.
--
-- Append-only por convencao: cada apuracao nova e uma LINHA nova; o relatorio le a
-- mais recente por `registrado_em`. Sem UPDATE, para que a serie de baselines
-- (e a data em que cada um passou a valer) fique preservada.
--
-- ESCOPO: um baseline por operacao, nao por vendedor. O piloto e de UMA modelo com UM
-- vendedor de plantao (ADR-0034, "Escopo do piloto"), entao a coluna `vendedor_id` seria
-- especulativa hoje -- e pior que isso: com ela, `NULL` teria de significar "agregado", e
-- o leitor (que pega a linha mais recente) passaria a comparar a conversao global da IA
-- contra o baseline de um vendedor especifico sem avisar. Quando a expansao pedir baseline
-- por vendedor, a coluna entra numa migration propria, junto com o filtro no leitor.
--
-- Schema-only -- sem seed. O baseline e dado de operacao e entra por INSERT manual
-- autorizado, nunca por migration. Em producao, aplicar com
-- `uv run python scripts/aplicar_sql.py infra/sql/20260810175610_graduacao_baseline.sql`
-- (runbook `infra/runbooks/aplicar-migrations-prod.md`), NUNCA via `make migrate` -- que
-- arrastaria os seeds descartaveis junto.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS barravips.graduacao_baseline (
  id             uuid PRIMARY KEY DEFAULT barravips.uuidv7(),
  -- Conversao do vendedor em PONTOS PERCENTUAIS (0-100): fechados / terminais * 100.
  conversao_pct  numeric(5,2) NOT NULL
                 CHECK (conversao_pct >= 0 AND conversao_pct <= 100),
  -- Tamanho da amostra que produziu o percentual. Sem ele o numero nao e criticavel:
  -- 60% em 5 negociacoes nao e baseline, e ruido.
  amostra_n      integer NOT NULL CHECK (amostra_n > 0),
  apurado_de     date NOT NULL,
  apurado_ate    date NOT NULL,
  -- Procedencia em texto livre (ex.: 'corpus do vendedor 2026-05/06', 'caderno do
  -- Fernando'): de onde saiu o numero, para quem ler o relatorio poder desconfiar dele.
  -- `btrim` e nao `<> ''`: um espaco em branco passaria pelo segundo e derrotaria o ponto.
  fonte          text NOT NULL CHECK (btrim(fonte) <> ''),
  observacao     text,
  registrado_em  timestamptz NOT NULL DEFAULT now(),
  registrado_por uuid REFERENCES barravips.usuarios(id) ON DELETE SET NULL,
  CONSTRAINT graduacao_baseline_periodo CHECK (apurado_de <= apurado_ate)
);

-- O `REVOKE` faz o "sem superficie exposta" do COMMENT virar garantia, nao intencao: sem RLS, a tabela
-- nasce com SELECT/INSERT/UPDATE/DELETE para `authenticated` (ALTER DEFAULT PRIVILEGES do
-- 0001_schema_inicial). O unico leitor e a CLI, que conecta pela DATABASE_URL do stack.
REVOKE ALL ON barravips.graduacao_baseline FROM authenticated;

COMMENT ON TABLE barravips.graduacao_baseline IS
  'interna: sem RLS porque e lida so pelo relatorio de graduacao (CLI dev, `make graduacao`) e escrita por INSERT manual autorizado; o acesso de `authenticated` e REVOGADO nesta mesma migration, entao nao ha superficie PostgREST/painel. Baseline de conversao do vendedor ANTES do cutover, referencia do 4o criterio de graduacao do piloto (ADR-0034): a IA gradua com conversao >= 80% deste numero. Um baseline por OPERACAO (nao por vendedor). Append-only: nova apuracao = nova linha; vale a mais recente.';
COMMENT ON COLUMN barravips.graduacao_baseline.conversao_pct IS
  'Conversao do vendedor em pontos percentuais (0-100): Fechados / (Fechados+Perdidos) * 100.';
COMMENT ON COLUMN barravips.graduacao_baseline.fonte IS
  'Procedencia do numero (corpus, caderno, planilha). Obrigatoria: baseline sem origem nao e auditavel.';

-- Leitura unica do relatorio: "a apuracao mais recente". Casa com o ORDER BY do leitor
-- (`registrado_em DESC, id DESC`) -- o `id` desempata linhas do mesmo instante.
CREATE INDEX IF NOT EXISTS graduacao_baseline_registrado_idx
  ON barravips.graduacao_baseline (registrado_em DESC, id DESC);
