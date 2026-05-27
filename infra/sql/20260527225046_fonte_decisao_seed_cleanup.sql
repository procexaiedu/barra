-- Adiciona 'seed_cleanup' a fonte_decisao_enum.
--
-- Motivacao: o cron lembrete_valor (workers/lembrete_valor.py) estava casando
-- atendimentos seed em estado Em_execucao com bloqueio.fim no passado e tentando
-- enviar card numa instancia Evolution fake, gerando exception 1x/min por alvo.
-- Para tirar os seeds do scan precisamos virar o estado para 'Fechado'; a trilha
-- fonte_decisao_ultima_transicao='seed_cleanup' marca explicitamente que foi
-- limpeza operacional (nao painel_fernando, nao cron_em_execucao).
--
-- ALTER TYPE ... ADD VALUE eh idempotente via IF NOT EXISTS. Postgres exige que
-- o ADD VALUE rode FORA de bloco transacional (mesmo do psycopg autocommit). O
-- script make migrate aplica cada arquivo em transacao por padrao, entao este
-- precisa ser aplicado manualmente via psycopg em autocommit ou via Studio.

ALTER TYPE barravips.fonte_decisao_enum ADD VALUE IF NOT EXISTS 'seed_cleanup';
