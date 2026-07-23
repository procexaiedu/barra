-- =============================================================================
-- Fetiche "por pessoa" (casal/menage): dobra o pacote em vez de somar 1 hora.
--
-- Reabre a alternativa que o ADR-0030 deixou EXPLICITAMENTE em aberto ("Multiplicador
-- por fetiche ... reabrir se aparecer um fetiche que realmente precise valer mais que
-- os outros" — ver ADR-0035). Casal (o cliente traz um acompanhante) e Menage são
-- cobrados POR PESSOA = 2 pessoas fixas = o DOBRO do pacote vendido, não o preço-hora
-- dos demais fetiches (atos como inversão/golden shower, que seguem preço-hora —
-- dominio/atendimentos/service.py:calcular_preco_extra_fetiche). Trio/grupo a IA escala.
--
-- Flag no CATÁLOGO GLOBAL (barravips.fetiches), não em modelo_fetiches: ser "por pessoa"
-- é propriedade do fetiche, igual para todas as modelos (só o incluso/pago é por-modelo).
-- Curada por Fernando.
--
-- "Casal"/"Menage" não nascem de seed deste repo (cadastrados via Studio em prod — mesmo
-- gotcha da migration 20260720233000_menage_pago_correcao_dado): o UPDATE casa por
-- lower(btrim(nome)); nome ausente não afeta nada. Novos fetiches por-pessoa marcam-se
-- via painel/SQL. Idempotente: roda 2x sem quebrar.
--
-- Aplicar MANUALMENTE em prod self-hosted via psycopg — NUNCA `make migrate`.
-- =============================================================================

BEGIN;

ALTER TABLE barravips.fetiches
  ADD COLUMN IF NOT EXISTS cobra_por_pessoa boolean NOT NULL DEFAULT false;

COMMENT ON COLUMN barravips.fetiches.cobra_por_pessoa IS
  'true = cobrado por pessoa (casal/menage): dobra o pacote vendido (2 pessoas fixas). false = ato normal, soma o preço-hora do pacote (ADR-0030). Reabre o multiplicador que o ADR-0030 deixou em aberto (ADR-0035).';

UPDATE barravips.fetiches
   SET cobra_por_pessoa = true
 WHERE lower(btrim(nome)) IN ('casal', 'menage')
   AND NOT cobra_por_pessoa;

COMMIT;
