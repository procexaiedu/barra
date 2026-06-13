-- Vídeo chamada (ADR 0021): card de entrega remota na Coordenação por modelo.
-- Quando o cron confirmar_em_execucao promove um atendimento remoto a Em_execucao no horário do
-- bloqueio, ele insere uma escalada tipo 'video_chamada' que hospeda o card "Hora da vídeo
-- chamada" (espelho do 'cliente_busca' do ADR 0020). Card próprio -- texto e métrica distintos
-- do pickup presencial.
--
-- ALTER TYPE ... ADD VALUE é idempotente via IF NOT EXISTS. Postgres exige que o ADD VALUE rode
-- FORA de bloco transacional (mesmo do psycopg autocommit). O script make migrate aplica cada
-- arquivo em transação por padrão, então este precisa ser aplicado manualmente via psycopg em
-- autocommit ou via Studio. APLICAR ANTES do redeploy do worker: o cron e o _ROTULOS
-- (escaladas/modelos.py) referenciam o valor novo.

ALTER TYPE barravips.tipo_escalada_enum ADD VALUE IF NOT EXISTS 'video_chamada';
