-- =============================================================================
-- 20260814113002_bloqueio_tipo_de_deslocamento.sql
-- Deslocamento no gap da agenda: saber se um bloqueio acontece FORA do local
-- da modelo (emenda 2026-08-14 do ADR-0025).
--
-- O PEDIDO: "cliente querendo ir logo quando ela sai de um serviço, sendo na
-- casa de um cliente (tem que ter um tempo de deslocamento até o lugar dela)".
-- Hoje `barravips.bloqueios` nao tem NADA que diga onde o compromisso acontece:
-- um externo do outro lado da cidade e indistinguivel de um interno no proprio
-- apartamento dela, e o gap entre atendimentos e um unico numero global
-- (`agenda_buffer_min`, 30 min, "todos os tipos" — ADR-0025 e a emenda de
-- 2026-06-26). O ADR-0025 ja admitia o buraco na secao Consequences: "Externo:
-- 30 min global pode ser curto para o deslocamento da modelo ate o cliente;
-- aceito por ora".
--
-- POR QUE UMA COLUNA NULLABLE E NAO UM CAMPO OBRIGATORIO:
-- para o bloqueio VINCULADO (o normal — reserva previa criada pela IA) o tipo
-- JA existe em `atendimentos.tipo_atendimento`, e duplica-lo aqui criaria duas
-- verdades para reconciliar: o tipo do atendimento muda DENTRO do turno (o
-- cliente diz "prefiro ir ate voce" depois de a reserva existir) e uma copia
-- congelada no bloqueio silenciaria a mudanca. Entao o valor EFETIVO e
--   COALESCE(bloqueios.tipo_atendimento, atendimentos.tipo_atendimento)
-- (ver `dominio/agenda/service.py::existe_vizinho_no_buffer`): derivado por
-- padrao, e esta coluna serve a dois casos que a derivacao nao cobre —
--   1. bloqueio AVULSO (`atendimento_id IS NULL`): compromisso pessoal fora de
--      casa (medico, viagem, cliente de outra origem). Sem a coluna ele nao tem
--      como declarar que ela vai estar na rua;
--   2. override do painel: o bloqueio que o Fernando cria/edita para um
--      atendimento cujo tipo gravado nao descreve o deslocamento real.
-- NULL = desconhecido -> o dominio aplica o gap padrao de hoje (compatibilidade
-- provada em tests/unit/test_buffer_deslocamento.py).
--
-- ENUM REUSADO (`barravips.tipo_atendimento_enum`: interno | externo | remoto)
-- de proposito: e o MESMO vocabulario de `atendimentos.tipo_atendimento`, e o
-- COALESCE acima exige tipos identicos. Inventar um enum de "local" paralelo
-- daria dois vocabularios para a mesma pergunta ("quem se desloca?").
--
-- O QUE ESTA MIGRATION **NAO** FAZ: nao mede distancia. Nao ha geocoding, nao
-- ha endereco no bloqueio, nao ha ETA. A coluna responde uma pergunta binaria
-- ("o compromisso e fora do local dela?") e o gap correspondente e um numero
-- fixo de setting (`agenda_buffer_externo_min`). Lead por distancia real
-- continua fora de escopo, como no ADR-0025 original.
--
-- Sem backfill: as linhas existentes ficam NULL e continuam derivando do
-- atendimento vinculado (que ja tem o tipo). Nenhum comportamento muda para
-- bloqueio sem tipo.
--
-- Idempotente (ADD COLUMN IF NOT EXISTS): roda 2x sem erro.
--
-- Aplicacao MANUAL (nunca `make migrate`), pelo caminho canonico do projeto
-- (infra/runbooks/aplicar-migrations-prod.md):
--   uv run python scripts/aplicar_sql.py infra/sql/20260814113002_bloqueio_tipo_de_deslocamento.sql
--
-- Conferir DEPOIS (nunca confiar no retorno do script):
--   \d barravips.bloqueios
--   SELECT count(*) FILTER (WHERE tipo_atendimento IS NOT NULL) FROM barravips.bloqueios;
-- =============================================================================

BEGIN;

ALTER TABLE barravips.bloqueios
  ADD COLUMN IF NOT EXISTS tipo_atendimento barravips.tipo_atendimento_enum;

COMMENT ON COLUMN barravips.bloqueios.tipo_atendimento IS
  'Onde o compromisso acontece, no vocabulario de `atendimentos.tipo_atendimento` (interno = no '
  'local dela | externo = ela se desloca ate o cliente | remoto = ninguem se desloca). NULL = '
  'desconhecido -> gap padrao (`agenda_buffer_min`). Para bloqueio VINCULADO o valor normal e '
  'NULL: o dominio deriva do atendimento (COALESCE(bloqueios.tipo_atendimento, '
  'atendimentos.tipo_atendimento)) para nao ter duas verdades quando o tipo muda no meio do turno. '
  'Preencher aqui e para (a) bloqueio AVULSO, que nao tem atendimento de onde derivar, e (b) '
  'override do painel. `externo` faz o gap ao redor deste bloqueio subir para '
  '`agenda_buffer_externo_min` DOS DOIS LADOS (ida e volta da viagem) — emenda 2026-08-14 do '
  'ADR-0025.';

COMMIT;
