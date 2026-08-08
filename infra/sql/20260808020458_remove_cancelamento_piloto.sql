-- Remove o cancelamento automatico do piloto de teste (ADR-0033, revogado pelo ADR-0036).
--
-- O mecanismo inteiro saiu do codigo (cron cancelar_piloto_teste, backstop da desculpa, flags,
-- pool de desculpas canned). Aqui cai o rastro no schema:
--
-- - piloto_cancelado_em: marcador de idempotencia do cron -- sem cron, coluna morta.
-- - aguardando_confirmacao_em: ancora do timer de 10min do braco externo/remoto. Nao tinha outro
--   leitor (a auditoria da entrada no estado vive em eventos.transicao_estado), entao sai junto.
-- - fonte_decisao_enum: recriado sem 'auto_cancelamento_piloto'. Postgres nao remove valor de
--   enum, so recria o tipo -- por isso o rename/create/alter/drop. As linhas que carregavam esse
--   valor (atendimentos mortos pelo cron durante o piloto) perdem a fonte: viram NULL, decisao
--   explicita de 2026-08-07 ("limpar tudo, inclusive schema"). Elas seguem `Perdido`/`outro` com
--   a observacao "cancelamento automatico -- piloto de teste", e os eventos de auditoria
--   (jsonb, texto livre) nao sao tocados.
--
-- O DROP TYPE nao leva CASCADE de proposito: se alguma view/funcao passar a depender do tipo, e
-- melhor esta migration falhar alto do que arrastar o dependente junto em silencio.
--
-- Schema-only -- nao aplicar seeds em prod. Em producao, aplique este arquivo manualmente
-- (psql/Studio), nunca via `make migrate`.

ALTER TABLE barravips.atendimentos DROP COLUMN IF EXISTS piloto_cancelado_em;

ALTER TABLE barravips.atendimentos DROP COLUMN IF EXISTS aguardando_confirmacao_em;

-- Idempotente: o bloco inteiro so roda enquanto o valor existir no enum.
DO $$
BEGIN
  IF EXISTS (
    SELECT 1
      FROM pg_enum e
      JOIN pg_type t ON t.oid = e.enumtypid
      JOIN pg_namespace n ON n.oid = t.typnamespace
     WHERE n.nspname = 'barravips'
       AND t.typname = 'fonte_decisao_enum'
       AND e.enumlabel = 'auto_cancelamento_piloto'
  ) THEN
    UPDATE barravips.atendimentos
       SET fonte_decisao_ultima_transicao = NULL
     WHERE fonte_decisao_ultima_transicao = 'auto_cancelamento_piloto';

    ALTER TYPE barravips.fonte_decisao_enum RENAME TO fonte_decisao_enum_old;

    -- Mesma ordem do 0001_schema_inicial.sql + 'seed_cleanup' (20260527225046), menos o valor
    -- do piloto -- que era o ultimo adicionado.
    CREATE TYPE barravips.fonte_decisao_enum AS ENUM (
      'extracao_ia', 'webhook_imagem', 'pipeline_pix',
      'comando_grupo', 'painel_fernando',
      'auto_timeout', 'auto_timeout_interno', 'cron_em_execucao',
      'seed_cleanup'
    );

    ALTER TABLE barravips.atendimentos
      ALTER COLUMN fonte_decisao_ultima_transicao
      TYPE barravips.fonte_decisao_enum
      USING fonte_decisao_ultima_transicao::text::barravips.fonte_decisao_enum;

    DROP TYPE barravips.fonte_decisao_enum_old;
  END IF;
END
$$;
