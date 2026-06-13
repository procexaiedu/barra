-- Vídeo chamada (ADR 0021): terceiro valor do eixo de entrega `tipo_atendimento`.
-- `interno`/`externo` definem QUEM se desloca; `remoto` é o caso em que ninguém se desloca
-- -- o serviço é uma vídeo chamada ao vivo -- sem Pix, sem Foto de portaria, fora do Mapa de
-- clientes. A extração promove Qualificado -> Aguardando_confirmacao (bloqueio prévio, só pelo
-- horário, como o interno) e o cron confirmar_em_execucao pausa a IA no horário do bloqueio
-- (escalada tipo 'video_chamada' hospeda o card "Hora da vídeo chamada").
--
-- Diferente do `cliente_busca` (subcaso de externo via coluna booleana), `remoto` é valor
-- próprio do enum -- nenhuma coluna nova.
--
-- ALTER TYPE ... ADD VALUE é idempotente via IF NOT EXISTS. Postgres exige que o ADD VALUE rode
-- FORA de bloco transacional (mesmo do psycopg autocommit). O script make migrate aplica cada
-- arquivo em transação por padrão, então este precisa ser aplicado manualmente via psycopg em
-- autocommit ou via Studio. APLICAR ANTES do redeploy do worker: a extração e o cron
-- referenciam o valor novo.

ALTER TYPE barravips.tipo_atendimento_enum ADD VALUE IF NOT EXISTS 'remoto';
