-- 20260625223000_modelos_nome_local.sql
-- Nome do local do ponto de encontro (ex.: "Hotel Vitória"), capturado do
-- displayName do Google Places no autocomplete de endereço da modelo.
-- Complementa endereco_formatado (que é só o formattedAddress, sem o nome do
-- estabelecimento). Operacional: a IA cita junto do endereço no atendimento
-- interno ("to no Hotel Vitória, R. ...").

ALTER TABLE barravips.modelos
  ADD COLUMN IF NOT EXISTS nome_local text NULL;

COMMENT ON COLUMN barravips.modelos.nome_local IS
  'Nome do local do ponto de encontro (Google Places displayName, ex.: "Hotel Vitória"). Operacional, lido pela IA no atendimento interno. NULL quando o endereço é texto livre legado ou não é um estabelecimento nomeado.';
