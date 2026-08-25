-- =============================================================================
-- 20260814175416_deslocamento_por_conta_do_cliente.sql
-- Quem paga a corrida no externo — o carimbo que falta para o gate do Pix de
-- deslocamento obedecer a regra que a IA ja obedece na fala.
--
-- O DEFEITO (corrida real c12cen_v2_20260814, cenario `uber_dele_ida_e_volta`):
-- o cliente disse que ele mesmo chamaria o uber; a IA respondeu certo, nos dois
-- turnos ("Mas e o uber ida e volta, senao eu fico sem a volta rs" e depois
-- "Poxa, e voce que chama o uber amor, entao sem pix rs") — e no MESMO turno em
-- que ela disse "sem pix" o sistema anexou a bolha com a chave Pix de R$100.
-- A regra do operador (`regras.md.j2`, <tipos_de_encontro>) e explicita: "ou
-- voce chama e ele adianta o Pix, ou ele chama o ida e volta — nunca as duas
-- coisas juntas".
--
-- POR QUE UMA COLUNA E NAO INFERENCIA DO TEXTO: o gate
-- `_solicitar_pix_deslocamento_se_aplicavel` (dominio/atendimentos/service.py)
-- decidia olhando SO `estado`/`tipo_atendimento`/`pix_status` — nao havia campo
-- nenhum, em lugar nenhum do sistema, que dissesse quem paga a corrida. E o
-- fato e dito no turno 2 enquanto o gate dispara no turno 4: ler a fala do
-- turno corrente nao resolveria, porque no turno do disparo o assunto ja saiu
-- da janela. Carimbo deterministico persistido, no espirito de
-- `horario_evidenciado` e `endereco_enviado_em`.
--
-- POR QUE `boolean` NULLABLE (tri-estado) E NAO `NOT NULL DEFAULT false`:
--   NULL  = ninguem tocou no assunto -> comportamento de HOJE (pede o Pix). E o
--           que toda linha existente vira, sem backfill: nenhum atendimento em
--           voo muda de comportamento;
--   true  = o CLIENTE declarou que chama e paga o ida e volta -> o gate faz
--           early-return e a chave nao sai;
--   false = ele voltou atras e devolveu a corrida pra modelo -> religa o Pix.
-- O tri-estado e o que faz o UPSERT incremental da extracao (`COALESCE`,
-- `_CAMPOS_UPSERT`) funcionar: o campo omitido no payload preserva o gravado,
-- e so uma declaracao explicita do cliente escreve. Com `NOT NULL DEFAULT
-- false` o payload nao teria como distinguir "ele nao falou disso" de "ele
-- devolveu a corrida", e o carimbo do turno 2 seria apagado pelo turno 3.
--
-- POR QUE NAO UM VALOR NOVO NO ENUM `pix_status` ('dispensado'): `pix_status` e
-- lido/escrito por sete modulos (workers/pix, workers/media, workers/timeouts,
-- dominio/pix/routes, dominio/escaladas/service, os cards Jinja, o painel) e a
-- pergunta que ele responde e "em que pe esta a cobranca", nao "quem paga a
-- corrida". Sao dois fatos: ele pode ser 'nao_solicitado' porque o encontro
-- ainda nao fechou OU porque a corrida e do cliente, e apagar essa diferenca no
-- mesmo enum obrigaria todo consumidor a reconstrui-la. Alem disso `ALTER TYPE
-- ... ADD VALUE` nao pode ser usado na mesma transacao que o cria, o que
-- quebraria o BEGIN/COMMIT unico exigido pelo caminho de aplicacao daqui.
--
-- O QUE ESTA MIGRATION **NAO** FAZ: nao mexe em `pix_status`, nao faz backfill,
-- nao apaga cobranca ja feita. Atendimento que ja esta com o Pix 'aguardando'
-- segue igual — o gate so olha esta coluna enquanto `pix_status` ainda e
-- 'nao_solicitado', entao marcar a coluna depois nao cancela nada.
--
-- Idempotente (ADD COLUMN IF NOT EXISTS): roda 2x sem erro. Sem seed: schema
-- puro.
--
-- ORDEM: esta migration e PRE-REQUISITO DURO do deploy do codigo. A coluna e lida
-- incondicionalmente em dois SELECTs — `agente/nos/prepare_context.py`
-- (`_carregar_atendimento`, roda TODO turno) e
-- `dominio/atendimentos/service.py` (`_solicitar_pix_deslocamento_se_aplicavel`).
-- Codigo antes da migration nao degrada em silencio: e `UndefinedColumn` em todo
-- turno. Aplicar ANTES do deploy — e aplicar tambem em `barra_test`, em ordem
-- cronologica, antes de rodar `needs_db`/evals.
--
-- Conferir ANTES de aplicar (divergencia repo x prod e historica neste projeto,
-- e `ADD COLUMN IF NOT EXISTS` e no-op SILENCIOSO se ja existir uma coluna de
-- mesmo nome com TIPO diferente — o codigo passaria a ler o tipo errado):
--   SELECT data_type, is_nullable FROM information_schema.columns
--    WHERE table_schema='barravips' AND table_name='atendimentos'
--      AND column_name='deslocamento_por_conta_do_cliente';
--   -- esperado: 0 linhas (ou boolean/YES, se ja aplicada)
--
-- Aplicacao MANUAL (nunca `make migrate` contra prod), pelo caminho canonico
-- do projeto (infra/runbooks/aplicar-migrations-prod.md):
--   uv run python scripts/aplicar_sql.py \
--     infra/sql/20260814175416_deslocamento_por_conta_do_cliente.sql
--
-- Conferir DEPOIS (nunca confiar no retorno do script; `\d` e meta-comando de
-- psql, que pode nao existir local — a query abaixo roda pelo caminho canonico):
--   SELECT data_type, is_nullable FROM information_schema.columns
--    WHERE table_schema='barravips' AND table_name='atendimentos'
--      AND column_name='deslocamento_por_conta_do_cliente';  -- boolean / YES
--   SELECT count(*) FILTER (WHERE deslocamento_por_conta_do_cliente)
--     FROM barravips.atendimentos;   -- 0 logo apos aplicar (sem backfill)
--
-- ROLLBACK (so com o codigo acima FORA do ar — com ele deployado, derrubar a
-- coluna quebra todo turno):
--   ALTER TABLE barravips.atendimentos
--     DROP COLUMN IF EXISTS deslocamento_por_conta_do_cliente;
--   DELETE FROM barravips.schema_migrations
--    WHERE filename = '20260814175416_deslocamento_por_conta_do_cliente.sql';
-- =============================================================================

BEGIN;

ALTER TABLE barravips.atendimentos
  ADD COLUMN IF NOT EXISTS deslocamento_por_conta_do_cliente boolean;

COMMENT ON COLUMN barravips.atendimentos.deslocamento_por_conta_do_cliente IS
  'Externo (uber): quem paga a corrida. true = o CLIENTE declarou que ele mesmo chama e paga o '
  'ida e volta -> o Pix de deslocamento NAO e solicitado (early-return em '
  '`_solicitar_pix_deslocamento_se_aplicavel`, dominio/atendimentos/service.py) e a bolha com a '
  'chave nao e anexada pelo coordenador. false = ele devolveu a corrida para a modelo (religa o '
  'Pix). NULL = ninguem tocou no assunto -> comportamento padrao, pede o Pix; e o estado de toda '
  'linha anterior a esta migration (sem backfill). Escrito pela extracao da IA (arg '
  '`deslocamento_por_conta_do_cliente` de `registrar_extracao`, UPSERT incremental por COALESCE), '
  'nunca inferido do texto no momento do disparo — o cliente declara isso turnos ANTES de o gate '
  'do Pix rodar. Sem efeito em `interno`/`remoto`: no remoto o Pix e o valor da chamada '
  '(ADR-0029), nao transporte. Regra do operador: "ou voce chama e ele adianta o Pix, ou ele '
  'chama o ida e volta — nunca as duas coisas juntas".';

COMMIT;
