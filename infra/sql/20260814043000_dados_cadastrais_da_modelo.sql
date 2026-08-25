-- =============================================================================
-- 20260814043000_dados_cadastrais_da_modelo.sql
-- Dados cadastrais oportunistas da modelo (spec 0005, ticket 12).
--
-- O grupo real dita dado operacional no meio da conversa, sem ninguem pedir ao
-- sistema (09/08/2026):
--   ~ Dani:                "Passa o novo apartamento amiga"
--   ~ Dani:                "Torre e apartamento"
--   +55 11 96854-4493:     "Torre 2 Apt 2706"
-- O Agente financeiro guarda isso CALADO (docs/dominio/grupo-financeiro.md,
-- "Agente financeiro": atualiza Dados cadastrais de forma oportunista e calada,
-- NUNCA sai perguntando cadastro — o "fetiche cadastro-first" ja mordeu o agente
-- de venda).
--
-- POR QUE TABELA PROPRIA E NAO COLUNA EM `barravips.modelos`:
-- `modelos.endereco_formatado` / `nome_local` / `chave_pix` sao a ficha que a IA
-- de VENDA le e cita para o cliente (e `endereco_formatado` anda casado com
-- latitude/longitude/place_id do geocode). "Torre 2 Apt 2706" e um COMPLEMENTO
-- dito no grupo, sem geocode e sem revisao humana: escrito la, ele entraria na
-- boca do agente de venda e desalinharia o endereco das coordenadas. O ticket
-- pede painel-only — entao o dado mora no modulo que o capturou, e o painel
-- (ticket 11) le daqui. Mesmo espirito do ADR-0043: nao corromper a entidade do
-- nucleo para reaproveitar tabela.
--
-- POR QUE APPEND-ONLY COM `valor_anterior` NA MESMA LINHA:
-- o criterio do ticket e "auditoria com valor anterior preservado". Uma tabela
-- de estado + uma de eventos daria duas verdades para reconciliar; aqui a linha
-- nova E o evento (o que passou a valer, o que valia antes, por causa de qual
-- mensagem), e o valor de agora e a linha mais recente por (modelo, campo). Sem
-- UPDATE e sem DELETE para `authenticated`: auditoria que se edita nao e
-- auditoria (mesma decisao de `venda_registrada_eventos`, ticket 05).
--
-- POR QUE A CHAVE PIX DA MODELO NAO ENTRA EM `chaves_pix_conhecidas`:
-- aquela lista e o destino LEGITIMO do dinheiro da casa (ticket 07) — cadastrar
-- a chave da propria modelo la faria um Pix para a conta dela passar como
-- fechamento da casa, que e exatamente o erro que o aviso de chave desconhecida
-- existe para pegar. Aqui a chave dela e contexto de QUEM E QUEM (pagador
-- conhecido), nao permissao de destino.
--
-- Idempotente (CREATE ... IF NOT EXISTS, DROP POLICY IF EXISTS): roda 2x sem
-- erro.
--
-- Aplicacao MANUAL (nunca `make migrate`), pelo caminho canonico do projeto
-- (infra/runbooks/aplicar-migrations-prod.md):
--   uv run python scripts/aplicar_sql.py infra/sql/20260814043000_dados_cadastrais_da_modelo.sql
--
-- Conferir DEPOIS (nunca confiar no retorno do script):
--   \d barravips.modelo_dados_cadastrais
--   SELECT indexdef FROM pg_indexes
--    WHERE schemaname='barravips' AND tablename='modelo_dados_cadastrais';
-- =============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS barravips.modelo_dados_cadastrais (
  id              uuid PRIMARY KEY DEFAULT barravips.uuidv7(),
  modelo_id       uuid NOT NULL REFERENCES barravips.modelos(id) ON DELETE CASCADE,
  campo           text NOT NULL,
  valor           text NOT NULL,
  valor_anterior  text,
  mensagem_id     uuid REFERENCES barravips.grupo_financeiro_mensagens(id) ON DELETE RESTRICT,
  observado_em    timestamptz NOT NULL DEFAULT now(),
  created_at      timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT modelo_dados_cadastrais_campo_valido
    CHECK (campo IN ('endereco_operacional', 'chave_pix')),
  CONSTRAINT modelo_dados_cadastrais_valor_nao_vazio
    CHECK (btrim(valor) <> '')
);

COMMENT ON TABLE barravips.modelo_dados_cadastrais IS
  'Dados cadastrais da modelo capturados de forma oportunista no Grupo financeiro (spec 0005, '
  'ticket 12). PAINEL-ONLY: nada daqui entra no contexto/persona da IA de venda. APPEND-ONLY — '
  'cada linha e uma observacao nova, com o valor que passou a valer, o que valia antes e a '
  'mensagem que causou. O valor de AGORA e a linha mais recente por (modelo_id, campo).';
COMMENT ON COLUMN barravips.modelo_dados_cadastrais.campo IS
  'endereco_operacional (torre/apto do local de atendimento, como o grupo escreve: "Torre 2 Apt '
  '2706" — complemento, nao endereco geocodificado) | chave_pix (a chave da PROPRIA modelo, dita '
  'por ela; nao e destino autorizado da casa — ver `chaves_pix_conhecidas`).';
COMMENT ON COLUMN barravips.modelo_dados_cadastrais.valor IS
  'O dado COMO foi dito no grupo. Guardar a grafia original (e nao uma forma normalizada) e o que '
  'permite ao humano do painel comparar com o que esta na tela dele; a comparacao "mudou?" e feita '
  'no codigo, sobre a forma normalizada.';
COMMENT ON COLUMN barravips.modelo_dados_cadastrais.valor_anterior IS
  'O que valia antes desta observacao (nulo na primeira). E o criterio de auditoria do ticket: '
  'dado cadastral sobrescrito sem rastro e a unica forma de um endereco certo virar errado sem '
  'ninguem conseguir dizer quando.';
COMMENT ON COLUMN barravips.modelo_dados_cadastrais.mensagem_id IS
  'A mensagem do Grupo financeiro que trouxe o dado — a origem auditavel. Nula so quando a origem '
  'nao for o grupo (edicao pelo painel, que ainda nao existe).';

-- A leitura quente e "o valor de agora deste campo" (DISTINCT ON) e o historico do campo, as
-- duas na mesma ordem.
CREATE INDEX IF NOT EXISTS modelo_dados_cadastrais_atual_idx
  ON barravips.modelo_dados_cadastrais (modelo_id, campo, observado_em DESC, id DESC);

-- Idempotencia de ULTIMA instancia: a porta ja para na reentrega (a mensagem nao entra duas
-- vezes no log de origem), mas se algum caminho futuro reprocessar a mesma mensagem, ela nao
-- pode virar duas observacoes do mesmo campo — seria um evento de auditoria fantasma, com
-- valor_anterior igual ao valor.
CREATE UNIQUE INDEX IF NOT EXISTS modelo_dados_cadastrais_mensagem_campo_idx
  ON barravips.modelo_dados_cadastrais (mensagem_id, campo)
  WHERE mensagem_id IS NOT NULL;

ALTER TABLE barravips.modelo_dados_cadastrais ENABLE ROW LEVEL SECURITY;
ALTER TABLE barravips.modelo_dados_cadastrais FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS fernando_full_access ON barravips.modelo_dados_cadastrais;
CREATE POLICY fernando_full_access
  ON barravips.modelo_dados_cadastrais
  FOR ALL
  TO authenticated
  USING (barravips.is_fernando())
  WITH CHECK (barravips.is_fernando());

-- Sem UPDATE/DELETE de proposito (o resto do schema concede os quatro): append-only e garantia
-- do banco, nao convencao da aplicacao.
GRANT SELECT, INSERT ON barravips.modelo_dados_cadastrais TO authenticated;
GRANT ALL PRIVILEGES ON barravips.modelo_dados_cadastrais TO service_role;

COMMIT;
