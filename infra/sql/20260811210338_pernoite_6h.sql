-- =============================================================================
-- "Pernoite" passa a valer 6 horas (era 12) em `barravips.duracoes`.
--
-- Motivação (Fernando, 11/08/2026, ao subir a Catarina e derivar a tabela do preço de 1h): o
-- pernoite que a agência VENDE é de 6 horas. As 12h vieram do seed 0010 e sobreviveram à
-- 20260722024720_duracoes_6h_8h.sql, que introduziu "6 horas" e "8 horas" como durações próprias
-- mas deixou o "Pernoite" ancorado em 12 — desde então a mesma faixa de produto tem duas linhas
-- no catálogo e só uma delas com o nome que o cliente usa.
--
-- `horas` NÃO é decorativo — não é rótulo de painel, é entrada de duas contas do agente:
--
--   1. O extra de fetiche DERIVADO por preço-hora (`calcular_preco_extra_fetiche`,
--      dominio/atendimentos/service.py, ADR-0030): `extra = preco_tabela / duracao_horas`. Com
--      `horas = 12` num pernoite de 6h REAIS, o preço-hora sai pela metade e todo fetiche pago
--      sem preço cadastrado é cotado pela metade do correto — desconto silencioso que ninguém
--      aprovou, em cima do pacote mais caro da tabela.
--   2. O limiar do bloco `<sem_periodo_longo>` do contexto dinâmico (`prepare_context.py`:
--      `sem_periodo_longo = 0 < tabela_max_horas < 6`). Uma modelo cujo pacote mais longo é o
--      pernoite de 6h precisa cair FORA do bloco (ela tem período longo, e o bloco a mandaria
--      negá-lo). Com `horas = 6` isso é exato na fronteira; com 12 era exato por acidente.
--
-- Impacto no cadastro existente: só a modelo Lucia (status `pausada`) tem linha de
-- `modelo_programas` em Pernoite hoje — impacto real zero. Não há preço a reajustar aqui; se a
-- linha dela for reativada, o preço entra pelo painel/MCP como toda tabela por modelo.
--
-- Keyed por NOME, não por `horas`: em prod existe uma "12 horas" DUPLICADA (ordem 999, mesmas 12h
-- do Pernoite original, ver o cabeçalho da 20260722024720). Ela NÃO deve ser tocada — continua
-- sendo a duração de 12h do catálogo, que segue existindo como produto. Um UPDATE por
-- `horas = 12` renomearia as duas faixas de uma vez.
--
-- Consequência aceita: passa a haver DUAS durações com `horas = 6` ("Pernoite" e a "6 horas" da
-- 20260722024720). Não há UNIQUE em `nome` nem em `horas` (seed 0010), e é exatamente o estado
-- que já existe hoje em 12h ("Pernoite" + "12 horas"). São rótulos comerciais distintos para a
-- mesma faixa; o cadastro por modelo escolhe qual vender.
--
-- Idempotente: roda 2x sem quebrar. O `IS DISTINCT FROM 6` deixa a segunda passada como no-op
-- (0 linhas afetadas) em vez de reescrever o mesmo valor, e impede que uma correção manual
-- posterior seja desfeita por um replay desta migration. `IS DISTINCT FROM` e não `<>` porque
-- `horas` é nullable (20260525181816) e `NULL <> 6` não atualizaria uma linha sem horas.
--
-- Aplicar MANUALMENTE em prod self-hosted via psycopg — NUNCA `make migrate`.
-- =============================================================================

BEGIN;

UPDATE barravips.duracoes
   SET horas = 6
 WHERE nome = 'Pernoite'
   AND horas IS DISTINCT FROM 6;

COMMIT;
