-- =============================================================================
-- 0001_schema_inicial.sql
-- Schema inicial do MVP barravips Vips — Central Inteligente de Atendimento.
--
-- Fonte de verdade desta modelagem: docs/mvp/06-dados-interfaces.md (§2 e §3),
-- com restrições e relacionamentos referenciados pelas demais seções do plano
-- (03-modulos-sistema.md, 04-fluxos-operacionais.md, 05-escalada-regras-ia.md,
-- 07-stack-tecnica.md) e pelo CONTEXT.md.
--
-- Convenções (§1 do doc 06):
--   - schema único `barravips`;
--   - id em uuid v7 via barravips.uuidv7() (PL/pgSQL — PG17 ainda não tem uuidv7 nativo);
--   - timestamptz em todas as tabelas com `created_at`/`updated_at`;
--   - enums nativos em `barravips.<nome>_enum`;
--   - snake_case em tabelas e colunas;
--   - RLS habilitada em todas as tabelas (policy `fernando_full_access` no P0);
--   - Realtime publicado nas tabelas que o painel assina.
--
-- Aplicação:
--   psql "$DATABASE_URL" -f 0001_schema_inicial.sql
--   (ou via Supabase Studio / MCP `apply_migration`).
-- =============================================================================


-- -----------------------------------------------------------------------------
-- 1. Extensões
-- -----------------------------------------------------------------------------
-- btree_gist: necessário para o EXCLUDE USING gist em `bloqueios`
-- (combina igualdade em `modelo_id` com sobreposição em tstzrange).
-- pgcrypto: fornece gen_random_bytes() usado em barravips.uuidv7().
-- (uuidv7() nativo só existe a partir do Postgres 18; Supabase managed roda PG17.
--  Quando Supabase migrar para PG18, dá pra trocar barravips.uuidv7() pelo nativo.)
CREATE EXTENSION IF NOT EXISTS btree_gist;
CREATE EXTENSION IF NOT EXISTS pgcrypto;


-- -----------------------------------------------------------------------------
-- 2. Schema
-- -----------------------------------------------------------------------------
CREATE SCHEMA IF NOT EXISTS barravips;
SET search_path TO barravips, public;


-- -----------------------------------------------------------------------------
-- 3. Enums (canônicos em §3 do doc 06; +4 derivados das tabelas em §2)
-- -----------------------------------------------------------------------------

-- §3 — canônicos
CREATE TYPE barravips.estado_atendimento_enum AS ENUM (
  'Novo', 'Triagem', 'Qualificado',
  'Aguardando_confirmacao', 'Confirmado', 'Em_execucao',
  'Fechado', 'Perdido'
);

CREATE TYPE barravips.tipo_atendimento_enum AS ENUM ('interno', 'externo');

CREATE TYPE barravips.urgencia_enum AS ENUM (
  'imediato', 'agendado', 'indefinido', 'estimado'
);

CREATE TYPE barravips.tipo_local_enum AS ENUM (
  'hotel', 'casa', 'apartamento', 'outro'
);

CREATE TYPE barravips.forma_pagamento_enum AS ENUM ('pix', 'dinheiro', 'outro');

CREATE TYPE barravips.motivo_perda_enum AS ENUM (
  'preco', 'sumiu', 'risco', 'indisponibilidade', 'fora_de_area', 'outro'
);

CREATE TYPE barravips.pix_status_enum AS ENUM (
  'nao_solicitado', 'aguardando', 'enviado',
  'em_revisao', 'validado', 'invalido'
);

CREATE TYPE barravips.ia_pausada_motivo_enum AS ENUM (
  'pix_em_revisao', 'modelo_em_atendimento', 'handoff_ia'
);

CREATE TYPE barravips.responsavel_atual_enum AS ENUM ('IA', 'Fernando', 'modelo');

-- direcao_mensagem_enum: somente valores que cabem em `mensagens` (conversa cliente).
-- Conteúdo do grupo de Coordenação (cards, confirmações) vive em `escaladas` + `eventos`,
-- não em `mensagens`. Se houver demanda futura por histórico cru do grupo, criar uma
-- tabela `mensagens_grupo` com enum próprio.
CREATE TYPE barravips.direcao_mensagem_enum AS ENUM (
  'cliente', 'ia', 'modelo_manual'
);

CREATE TYPE barravips.tipo_mensagem_enum AS ENUM ('texto', 'audio', 'imagem');

CREATE TYPE barravips.estado_bloqueio_enum AS ENUM (
  'bloqueado', 'em_atendimento', 'concluido', 'cancelado'
);

CREATE TYPE barravips.origem_bloqueio_enum AS ENUM ('ia', 'painel_fernando', 'manual');

CREATE TYPE barravips.decisao_pipeline_pix_enum AS ENUM ('validado', 'em_revisao');

CREATE TYPE barravips.decisao_final_pix_enum AS ENUM ('validado', 'invalido');

CREATE TYPE barravips.papel_usuario_enum AS ENUM ('fernando', 'vendedor_read_only');

-- fonte_decisao: doc 04 §9.1 (P0 tem 8 valores; P1 introduz 'classificador_p1' depois)
CREATE TYPE barravips.fonte_decisao_enum AS ENUM (
  'extracao_ia', 'webhook_imagem', 'pipeline_pix',
  'comando_grupo', 'painel_fernando',
  'auto_timeout', 'auto_timeout_interno', 'cron_em_execucao'
);

-- tipo_evento: doc 06 §2.12.1
CREATE TYPE barravips.tipo_evento_enum AS ENUM (
  'transicao_estado', 'extracao_registrada',
  'pix_solicitado', 'pix_status_mudado',
  'handoff_aberto', 'devolucao_para_ia',
  'fechado_registrado', 'perdido_registrado', 'correcao_registro',
  'bloqueio_criado', 'bloqueio_estado_mudado',
  'comando_invalido'
);

CREATE TYPE barravips.origem_evento_enum AS ENUM (
  'agente', 'grupo_coordenacao', 'painel', 'pipeline_pix', 'cron'
);

CREATE TYPE barravips.autor_evento_enum AS ENUM (
  'IA', 'Fernando', 'modelo', 'sistema'
);

-- Enums derivados de §2 (não listados em §3, mas usados em colunas específicas)
CREATE TYPE barravips.modelo_status_enum AS ENUM ('ativa', 'pausada', 'inativa');

CREATE TYPE barravips.midia_tipo_enum AS ENUM ('foto', 'video');

CREATE TYPE barravips.escalada_responsavel_enum AS ENUM ('Fernando', 'modelo');

CREATE TYPE barravips.escalada_canal_enum AS ENUM (
  'grupo_coordenacao', 'painel', 'pipeline_pix'
);


-- -----------------------------------------------------------------------------
-- 4. Funções utilitárias (triggers e helpers)
-- -----------------------------------------------------------------------------

-- 4.0 uuidv7(): geração de UUID versão 7 (timestamp ms + random).
-- Implementação em PL/pgSQL pra não depender de extensão de terceiros.
-- Trocar por uuidv7() nativo quando Supabase migrar para Postgres 18.
CREATE OR REPLACE FUNCTION barravips.uuidv7()
RETURNS uuid
LANGUAGE plpgsql
PARALLEL SAFE
AS $$
DECLARE
  ts_ms      bigint;
  uuid_bytes bytea;
BEGIN
  ts_ms := floor(extract(epoch FROM clock_timestamp()) * 1000)::bigint;
  -- 6 bytes de timestamp em ms + 10 bytes aleatórios = 16 bytes
  uuid_bytes := substring(int8send(ts_ms) from 3) || gen_random_bytes(10);
  -- Versão 7: byte 6, high nibble = 0111
  uuid_bytes := set_byte(uuid_bytes, 6, (get_byte(uuid_bytes, 6) & 15) | 112);
  -- Variante RFC 4122: byte 8, high bits = 10xx
  uuid_bytes := set_byte(uuid_bytes, 8, (get_byte(uuid_bytes, 8) & 63) | 128);
  RETURN encode(uuid_bytes, 'hex')::uuid;
END;
$$;

-- 4.1 Atualiza `updated_at` em UPDATEs.
CREATE OR REPLACE FUNCTION barravips.set_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END;
$$;

-- 4.2 Gera `numero_curto` sequencial por `modelo_id` em INSERTs em `atendimentos`.
-- Usa advisory lock por modelo (hash do uuid → bigint) pra serializar o MAX+1
-- sem criar uma SEQUENCE física por modelo.
CREATE OR REPLACE FUNCTION barravips.gen_numero_curto()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
  proximo integer;
BEGIN
  IF NEW.numero_curto IS NOT NULL THEN
    RETURN NEW;
  END IF;

  PERFORM pg_advisory_xact_lock(hashtextextended(NEW.modelo_id::text, 0));

  SELECT COALESCE(MAX(numero_curto), 0) + 1
    INTO proximo
    FROM barravips.atendimentos
   WHERE modelo_id = NEW.modelo_id;

  NEW.numero_curto := proximo;
  RETURN NEW;
END;
$$;

-- 4.3 Sincroniza estado do bloqueio quando o atendimento for Fechado/Perdido
-- (doc 04 §8.4). Fechado → bloqueio.concluido; Perdido → bloqueio.cancelado
-- apenas se ainda não estiver em_atendimento ou concluido.
CREATE OR REPLACE FUNCTION barravips.sync_bloqueio_estado()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
  IF NEW.bloqueio_id IS NULL THEN
    RETURN NEW;
  END IF;

  IF NEW.estado = 'Fechado' AND
     (OLD.estado IS DISTINCT FROM 'Fechado') THEN
    UPDATE barravips.bloqueios
       SET estado = 'concluido',
           updated_at = now()
     WHERE id = NEW.bloqueio_id
       AND estado <> 'concluido';

  ELSIF NEW.estado = 'Perdido' AND
        (OLD.estado IS DISTINCT FROM 'Perdido') THEN
    UPDATE barravips.bloqueios
       SET estado = 'cancelado',
           updated_at = now()
     WHERE id = NEW.bloqueio_id
       AND estado NOT IN ('em_atendimento', 'concluido');
  END IF;

  RETURN NEW;
END;
$$;

-- 4.4 is_fernando(): SECURITY DEFINER pra evitar recursão de RLS quando
-- outras policies consultam barravips.usuarios. STABLE permite cache por query.
-- LANGUAGE plpgsql (não sql) porque referencia barravips.usuarios — em SQL functions,
-- check_function_bodies valida o corpo na criação, e a tabela ainda não existe
-- quando a função é declarada.
CREATE OR REPLACE FUNCTION barravips.is_fernando()
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
STABLE
SET search_path = ''
AS $$
BEGIN
  RETURN EXISTS (
    SELECT 1
      FROM barravips.usuarios u
     WHERE u.id = (SELECT auth.uid())
       AND u.ativo
       AND u.papel = 'fernando'
  );
END;
$$;

REVOKE ALL ON FUNCTION barravips.is_fernando() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION barravips.is_fernando() TO authenticated;

-- 4.5 Atualiza ultima_mensagem_em / ultima_mensagem_direcao na conversa quando
-- nova mensagem entra. Denormalização que sustenta a timeline do painel
-- (lista de conversas ordenada por atividade recente, com badge de direção).
-- Sem isso, a query precisa fazer subquery em mensagens por linha.
CREATE OR REPLACE FUNCTION barravips.atualiza_ultima_mensagem_em_conversa()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
  UPDATE barravips.conversas
     SET ultima_mensagem_em      = NEW.created_at,
         ultima_mensagem_direcao = NEW.direcao
   WHERE id = NEW.conversa_id;
  RETURN NEW;
END;
$$;

-- 4.6 Sincroniza barravips.usuarios com auth.users do Supabase Auth.
-- Trigger AFTER INSERT em auth.users cria row em barravips.usuarios.
-- IMPORTANTE: P0 tem somente Fernando como admin → default papel='fernando'.
-- Quando vendedor_read_only entrar no P1, fazer UPDATE explícito após o convite.
CREATE OR REPLACE FUNCTION barravips.handle_new_user()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, barravips
AS $$
BEGIN
  INSERT INTO barravips.usuarios (id, email, nome, papel, ativo)
  VALUES (
    NEW.id,
    NEW.email,
    COALESCE(NEW.raw_user_meta_data ->> 'nome', NEW.email),
    'fernando',
    true
  )
  ON CONFLICT (id) DO NOTHING;
  RETURN NEW;
END;
$$;


-- -----------------------------------------------------------------------------
-- 5. Tabelas
-- -----------------------------------------------------------------------------

-- 5.1 usuarios (doc 06 §2.13) ------------------------------------------------
-- Operadores do painel. Vinculado 1:1 a auth.users via FK direta.
CREATE TABLE barravips.usuarios (
  id          uuid PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  nome        text NOT NULL,
  email       text NOT NULL UNIQUE,
  papel       barravips.papel_usuario_enum NOT NULL DEFAULT 'fernando',
  ativo       boolean NOT NULL DEFAULT true,
  created_at  timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE barravips.usuarios IS
  'Operadores do painel. P0: somente Fernando (papel=fernando). P1: vendedor_read_only.';


-- 5.2 modelos (doc 06 §2.1) --------------------------------------------------
-- Persona da IA é template global (api/src/barra/agente/prompts/persona.md);
-- só interpolam-se variáveis estruturadas (nome, idade, idiomas, etc) — por isso
-- não há campos free-text como persona/politica_comercial/restricoes nesta tabela.
CREATE TABLE barravips.modelos (
  id                       uuid PRIMARY KEY DEFAULT barravips.uuidv7(),
  nome                     text NOT NULL,
  idade                    integer NOT NULL CHECK (idade > 0),
  numero_whatsapp          text NOT NULL UNIQUE,
  evolution_instance_id    text,
  status                   barravips.modelo_status_enum NOT NULL DEFAULT 'ativa',
  valor_padrao             numeric(10,2) NOT NULL CHECK (valor_padrao >= 0),
  percentual_repasse       numeric(5,2) CHECK (percentual_repasse IS NULL OR (percentual_repasse >= 0 AND percentual_repasse <= 100)),
  chave_pix                text,
  titular_chave            text,
  idiomas                  text[] NOT NULL DEFAULT ARRAY['pt-BR'],
  localizacao_operacional  text,
  tipo_atendimento_aceito  barravips.tipo_atendimento_enum[] NOT NULL,
  created_at               timestamptz NOT NULL DEFAULT now(),
  updated_at               timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT modelos_tipo_atendimento_nao_vazio
    CHECK (array_length(tipo_atendimento_aceito, 1) >= 1)
);

COMMENT ON TABLE barravips.modelos IS
  'Profissional cadastrada que opera no sistema. P0 esperado: 1 modelo piloto ativa.';
COMMENT ON COLUMN barravips.modelos.idade IS
  'Variável estruturada interpolada no system prompt da IA.';
COMMENT ON COLUMN barravips.modelos.idiomas IS
  'BCP-47 (ex: pt-BR, en-US). Default pt-BR. Interpolado no system prompt da IA.';
COMMENT ON COLUMN barravips.modelos.tipo_atendimento_aceito IS
  'Tipos de atendimento que a modelo realiza (interno/externo). Crítico: a IA usa este campo no qualificador para não negociar tipo que a modelo não faz.';


-- 5.4 modelo_faq (doc 06 §2.3) -----------------------------------------------
CREATE TABLE barravips.modelo_faq (
  id          uuid PRIMARY KEY DEFAULT barravips.uuidv7(),
  modelo_id   uuid REFERENCES barravips.modelos(id) ON DELETE CASCADE,
  pergunta    text NOT NULL,
  resposta    text NOT NULL,
  tags        text[] NOT NULL DEFAULT ARRAY[]::text[],
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE barravips.modelo_faq IS
  'FAQ consultada pela IA via consultar_faq. modelo_id NULL = FAQ global; preenchido = especialização.';


-- 5.5 modelo_midia (doc 06 §2.4) ---------------------------------------------
CREATE TABLE barravips.modelo_midia (
  id          uuid PRIMARY KEY DEFAULT barravips.uuidv7(),
  modelo_id   uuid NOT NULL REFERENCES barravips.modelos(id) ON DELETE CASCADE,
  tipo        barravips.midia_tipo_enum NOT NULL,
  tag         text NOT NULL,
  bucket      text NOT NULL DEFAULT 'media',
  object_key  text NOT NULL,
  aprovada    boolean NOT NULL DEFAULT true,
  created_at  timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE barravips.modelo_midia IS
  'Mídia pré-aprovada armazenada em MinIO (bucket "media"). Mínimo 10 por modelo antes do piloto.';


-- 5.6 clientes (doc 06 §2.5) -------------------------------------------------
-- Entidade global, mas histórico operacional vive em conversas (par cliente, modelo).
CREATE TABLE barravips.clientes (
  id                            uuid PRIMARY KEY DEFAULT barravips.uuidv7(),
  telefone                      text NOT NULL UNIQUE,
  nome                          text,
  primeiro_contato_modelo_id    uuid REFERENCES barravips.modelos(id) ON DELETE SET NULL,
  created_at                    timestamptz NOT NULL DEFAULT now(),
  updated_at                    timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE barravips.clientes IS
  'Cliente identificado por número de WhatsApp (E.164). Histórico operacional vive em conversas (par cliente, modelo).';
COMMENT ON COLUMN barravips.clientes.primeiro_contato_modelo_id IS
  'Modelo que originou o cliente na operação. Preenchido na criação do primeiro registro. Não viola isolamento entre IAs (atributo identitário, não operacional).';


-- 5.7 conversas (doc 06 §2.6) ------------------------------------------------
-- Uma conversa por par (cliente, modelo). Unidade que carrega histórico,
-- recorrência e observações no CRM (doc 04 §4.1).
CREATE TABLE barravips.conversas (
  id                       uuid PRIMARY KEY DEFAULT barravips.uuidv7(),
  cliente_id               uuid NOT NULL REFERENCES barravips.clientes(id) ON DELETE RESTRICT,
  modelo_id                uuid NOT NULL REFERENCES barravips.modelos(id) ON DELETE RESTRICT,
  evolution_chat_id        text NOT NULL,
  recorrente               boolean NOT NULL DEFAULT false,
  observacoes_internas     text,
  ultimo_motivo_perda      barravips.motivo_perda_enum,
  ultima_mensagem_em       timestamptz,
  ultima_mensagem_direcao  barravips.direcao_mensagem_enum,
  created_at               timestamptz NOT NULL DEFAULT now(),
  updated_at               timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT conversas_par_unico UNIQUE (cliente_id, modelo_id)
);

COMMENT ON TABLE barravips.conversas IS
  'Hilo de WhatsApp entre cliente e modelo (1 por par). thread_id usado pelo LangGraph (07 §7.1).';


-- 5.8 atendimentos (doc 06 §2.8) ---------------------------------------------
-- Ciclo comercial. Um atendimento ABERTO por (cliente, modelo).
-- bloqueio_id é FK para bloqueios (criada após barravips.bloqueios existir — ver §6).
CREATE TABLE barravips.atendimentos (
  id                                uuid PRIMARY KEY DEFAULT barravips.uuidv7(),
  numero_curto                      integer NOT NULL CHECK (numero_curto > 0),
  cliente_id                        uuid NOT NULL REFERENCES barravips.clientes(id) ON DELETE RESTRICT,
  modelo_id                         uuid NOT NULL REFERENCES barravips.modelos(id) ON DELETE RESTRICT,
  conversa_id                       uuid NOT NULL REFERENCES barravips.conversas(id) ON DELETE RESTRICT,
  bloqueio_id                       uuid, -- FK adicionada em §6 (referência circular com bloqueios)

  estado                            barravips.estado_atendimento_enum NOT NULL DEFAULT 'Novo',
  tipo_atendimento                  barravips.tipo_atendimento_enum,
  urgencia                          barravips.urgencia_enum,

  data_desejada                     date,
  horario_desejado                  time,
  duracao_horas                     numeric(4,2) CHECK (duracao_horas IS NULL OR duracao_horas > 0),

  endereco                          text,
  bairro                            text,
  tipo_local                        barravips.tipo_local_enum,
  referencia_local                  text,

  forma_pagamento                   barravips.forma_pagamento_enum,
  valor_acordado                    numeric(10,2) CHECK (valor_acordado IS NULL OR valor_acordado >= 0),
  valor_final                       numeric(10,2) CHECK (valor_final IS NULL OR valor_final >= 0),
  percentual_repasse_snapshot       numeric(5,2) CHECK (percentual_repasse_snapshot IS NULL OR (percentual_repasse_snapshot >= 0 AND percentual_repasse_snapshot <= 100)),

  motivo_perda                      barravips.motivo_perda_enum,
  motivo_perda_obs                  text,

  pix_status                        barravips.pix_status_enum NOT NULL DEFAULT 'nao_solicitado',
  aviso_saida_em                    timestamptz,
  foto_portaria_em                  timestamptz,

  ia_pausada                        boolean NOT NULL DEFAULT false,
  ia_pausada_motivo                 barravips.ia_pausada_motivo_enum,

  responsavel_atual                 barravips.responsavel_atual_enum NOT NULL DEFAULT 'IA',
  proxima_acao_esperada             text,
  motivo_escalada                   text,
  resumo_operacional                text,

  sinais_qualificacao               jsonb NOT NULL DEFAULT '{}'::jsonb,
  fonte_decisao_ultima_transicao    barravips.fonte_decisao_enum,

  created_at                        timestamptz NOT NULL DEFAULT now(),
  updated_at                        timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT atendimentos_numero_curto_modelo_unique UNIQUE (modelo_id, numero_curto),
  CONSTRAINT atendimentos_fechado_exige_valor_final
    CHECK (estado <> 'Fechado' OR valor_final IS NOT NULL),
  CONSTRAINT atendimentos_perdido_exige_motivo
    CHECK (estado <> 'Perdido' OR motivo_perda IS NOT NULL),
  CONSTRAINT atendimentos_motivo_outro_exige_obs
    CHECK (motivo_perda IS DISTINCT FROM 'outro' OR motivo_perda_obs IS NOT NULL),
  CONSTRAINT atendimentos_ia_pausada_exige_motivo
    CHECK (ia_pausada = false OR ia_pausada_motivo IS NOT NULL)
);

COMMENT ON TABLE barravips.atendimentos IS
  'Ciclo comercial. Um atendimento aberto por (cliente, modelo). Estados em doc 03 §4.2.';

-- Único parcial: garante UM atendimento aberto por par (cliente, modelo)
-- (doc 06 §2.8). Estados terminais (Fechado/Perdido) não restringem.
CREATE UNIQUE INDEX atendimentos_um_aberto_por_par
  ON barravips.atendimentos (cliente_id, modelo_id)
  WHERE estado NOT IN ('Fechado', 'Perdido');


-- 5.9 bloqueios (doc 06 §2.9) ------------------------------------------------
CREATE TABLE barravips.bloqueios (
  id              uuid PRIMARY KEY DEFAULT barravips.uuidv7(),
  modelo_id       uuid NOT NULL REFERENCES barravips.modelos(id) ON DELETE RESTRICT,
  atendimento_id  uuid REFERENCES barravips.atendimentos(id) ON DELETE SET NULL,
  inicio          timestamptz NOT NULL,
  fim             timestamptz NOT NULL,
  estado          barravips.estado_bloqueio_enum NOT NULL DEFAULT 'bloqueado',
  origem          barravips.origem_bloqueio_enum NOT NULL,
  observacao      text,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT bloqueios_intervalo_valido CHECK (inicio < fim),
  -- Impede sobreposição de bloqueios ATIVOS (bloqueado/em_atendimento) por modelo
  -- (doc 06 §2.9). Estados terminais (concluido/cancelado) não geram conflito.
  CONSTRAINT bloqueios_sem_sobreposicao
    EXCLUDE USING gist (
      modelo_id WITH =,
      tstzrange(inicio, fim, '[)') WITH &&
    ) WHERE (estado IN ('bloqueado', 'em_atendimento'))
);

COMMENT ON TABLE barravips.bloqueios IS
  'Reserva de agenda da modelo. atendimento_id NULL = bloqueio manual avulso.';

-- FK circular: atendimentos.bloqueio_id → bloqueios.id (criada agora que ambas existem).
ALTER TABLE barravips.atendimentos
  ADD CONSTRAINT atendimentos_bloqueio_fk
  FOREIGN KEY (bloqueio_id) REFERENCES barravips.bloqueios(id) ON DELETE SET NULL;


-- 5.10 mensagens (doc 06 §2.7) -----------------------------------------------
-- Histórico bruto. Persistido pelo módulo 5.1 antes de qualquer decisão (doc 03 §5.1).
CREATE TABLE barravips.mensagens (
  id                      uuid PRIMARY KEY DEFAULT barravips.uuidv7(),
  conversa_id             uuid NOT NULL REFERENCES barravips.conversas(id) ON DELETE CASCADE,
  atendimento_id          uuid REFERENCES barravips.atendimentos(id) ON DELETE SET NULL,
  direcao                 barravips.direcao_mensagem_enum NOT NULL,
  tipo                    barravips.tipo_mensagem_enum NOT NULL,
  conteudo                text NOT NULL DEFAULT '',
  media_object_key        text,
  evolution_message_id    text NOT NULL UNIQUE,
  created_at              timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT mensagens_midia_exige_object_key
    CHECK (tipo = 'texto' OR media_object_key IS NOT NULL)
);

COMMENT ON TABLE barravips.mensagens IS
  'Histórico bruto de mensagens. Persistido antes de qualquer decisão (doc 03 §5.1). Idempotência via evolution_message_id.';


-- 5.11 comprovantes_pix (doc 06 §2.10) ---------------------------------------
CREATE TABLE barravips.comprovantes_pix (
  id                  uuid PRIMARY KEY DEFAULT barravips.uuidv7(),
  atendimento_id      uuid NOT NULL REFERENCES barravips.atendimentos(id) ON DELETE CASCADE,
  mensagem_id         uuid NOT NULL REFERENCES barravips.mensagens(id) ON DELETE CASCADE,
  valor_extraido      numeric(10,2),
  chave_extraida      text,
  titular_extraido    text,
  timestamp_extraido  timestamptz,
  decisao_pipeline    barravips.decisao_pipeline_pix_enum NOT NULL,
  motivo_em_revisao   text,
  decisao_final       barravips.decisao_final_pix_enum,
  decisao_final_por   uuid REFERENCES barravips.usuarios(id) ON DELETE SET NULL,
  created_at          timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE barravips.comprovantes_pix IS
  'Comprovantes recebidos pelo pipeline OCR/vision (doc 04 §4.6/§5.6).';


-- 5.12 escaladas (doc 06 §2.11) ----------------------------------------------
CREATE TABLE barravips.escaladas (
  id                  uuid PRIMARY KEY DEFAULT barravips.uuidv7(),
  atendimento_id      uuid NOT NULL REFERENCES barravips.atendimentos(id) ON DELETE CASCADE,
  responsavel         barravips.escalada_responsavel_enum NOT NULL,
  motivo              text NOT NULL,
  resumo_operacional  text NOT NULL,
  acao_esperada       text NOT NULL,
  card_message_id     text,
  aberta_em           timestamptz NOT NULL DEFAULT now(),
  fechada_em          timestamptz,
  fechada_por         uuid REFERENCES barravips.usuarios(id) ON DELETE SET NULL,
  fechada_canal       barravips.escalada_canal_enum
);

COMMENT ON TABLE barravips.escaladas IS
  'Cards de handoff abertos no grupo de Coordenação por modelo (doc 03 §5.4).';


-- 5.13 eventos (doc 06 §2.12) ------------------------------------------------
-- Audit log humano-legível. Insert em TODA ação operacional (doc 03 §7.4, 07 §2.2).
CREATE TABLE barravips.eventos (
  id              uuid PRIMARY KEY DEFAULT barravips.uuidv7(),
  atendimento_id  uuid REFERENCES barravips.atendimentos(id) ON DELETE SET NULL,
  tipo            barravips.tipo_evento_enum NOT NULL,
  origem          barravips.origem_evento_enum NOT NULL,
  autor           barravips.autor_evento_enum NOT NULL,
  payload         jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at      timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE barravips.eventos IS
  'Audit log humano-legível. Recebe insert em toda ação operacional persistida. Não substitui checkpointer LangGraph.';


-- -----------------------------------------------------------------------------
-- 6. Índices adicionais (além dos UNIQUE/PRIMARY KEY já criados)
-- -----------------------------------------------------------------------------

-- conversas: lookup rápido pelo painel/IA
CREATE INDEX conversas_modelo_idx           ON barravips.conversas (modelo_id);
CREATE INDEX conversas_cliente_idx          ON barravips.conversas (cliente_id);
CREATE INDEX conversas_evolution_chat_idx   ON barravips.conversas (modelo_id, evolution_chat_id);
CREATE INDEX conversas_atualizada_idx       ON barravips.conversas (modelo_id, updated_at DESC);
-- Timeline do painel: lista de conversas da modelo ordenada pela última mensagem.
-- NULLS LAST para conversas sem mensagens ainda caírem no fim da lista.
CREATE INDEX conversas_modelo_ultima_msg_idx
  ON barravips.conversas (modelo_id, ultima_mensagem_em DESC NULLS LAST);

-- atendimentos: filtros principais do painel (doc 06 §4.1, §4.2)
CREATE INDEX atendimentos_modelo_estado_idx ON barravips.atendimentos (modelo_id, estado);
CREATE INDEX atendimentos_conversa_idx      ON barravips.atendimentos (conversa_id);
CREATE INDEX atendimentos_cliente_idx       ON barravips.atendimentos (cliente_id);
CREATE INDEX atendimentos_pausada_idx
  ON barravips.atendimentos (modelo_id, ia_pausada_motivo)
  WHERE ia_pausada = true;
CREATE INDEX atendimentos_em_aberto_idx
  ON barravips.atendimentos (modelo_id, updated_at DESC)
  WHERE estado NOT IN ('Fechado', 'Perdido');

-- mensagens: histórico ordenado (doc 06 §2.7)
CREATE INDEX mensagens_conversa_created_idx
  ON barravips.mensagens (conversa_id, created_at DESC);
CREATE INDEX mensagens_atendimento_idx
  ON barravips.mensagens (atendimento_id)
  WHERE atendimento_id IS NOT NULL;

-- bloqueios: agenda por modelo no calendário do painel (doc 06 §4.3)
CREATE INDEX bloqueios_modelo_inicio_idx ON barravips.bloqueios (modelo_id, inicio);
CREATE INDEX bloqueios_atendimento_idx
  ON barravips.bloqueios (atendimento_id)
  WHERE atendimento_id IS NOT NULL;

-- comprovantes_pix: fila de revisão de Fernando (doc 06 §4.6)
CREATE INDEX comprovantes_pix_atendimento_idx ON barravips.comprovantes_pix (atendimento_id);
CREATE INDEX comprovantes_pix_em_revisao_idx
  ON barravips.comprovantes_pix (created_at DESC)
  WHERE decisao_pipeline = 'em_revisao' AND decisao_final IS NULL;

-- escaladas: cards abertos
CREATE INDEX escaladas_atendimento_idx ON barravips.escaladas (atendimento_id);
CREATE INDEX escaladas_abertas_idx
  ON barravips.escaladas (aberta_em DESC)
  WHERE fechada_em IS NULL;

-- eventos: timeline + busca em payload
CREATE INDEX eventos_atendimento_idx     ON barravips.eventos (atendimento_id);
CREATE INDEX eventos_created_idx         ON barravips.eventos (created_at DESC);
CREATE INDEX eventos_tipo_idx            ON barravips.eventos (tipo);
CREATE INDEX eventos_payload_gin_idx     ON barravips.eventos USING gin (payload);

-- modelo_faq: busca por tags + por modelo
CREATE INDEX modelo_faq_modelo_idx       ON barravips.modelo_faq (modelo_id);
CREATE INDEX modelo_faq_tags_gin_idx     ON barravips.modelo_faq USING gin (tags);

-- modelo_midia: lookup por (modelo, tag, aprovada) + cobertura do CASCADE de modelos
CREATE INDEX modelo_midia_modelo_idx
  ON barravips.modelo_midia (modelo_id);
CREATE INDEX modelo_midia_modelo_tag_idx
  ON barravips.modelo_midia (modelo_id, tag)
  WHERE aprovada = true;

-- FKs adicionais que precisam de índice próprio para JOIN/CASCADE/SET NULL
-- (regra schema-foreign-key-indexes — Postgres não indexa FK automaticamente).
CREATE INDEX atendimentos_bloqueio_idx
  ON barravips.atendimentos (bloqueio_id)
  WHERE bloqueio_id IS NOT NULL;
CREATE INDEX clientes_primeiro_contato_modelo_idx
  ON barravips.clientes (primeiro_contato_modelo_id)
  WHERE primeiro_contato_modelo_id IS NOT NULL;
CREATE INDEX comprovantes_pix_mensagem_idx
  ON barravips.comprovantes_pix (mensagem_id);
CREATE INDEX comprovantes_pix_decisao_por_idx
  ON barravips.comprovantes_pix (decisao_final_por)
  WHERE decisao_final_por IS NOT NULL;
CREATE INDEX escaladas_fechada_por_idx
  ON barravips.escaladas (fechada_por)
  WHERE fechada_por IS NOT NULL;


-- -----------------------------------------------------------------------------
-- 7. Triggers
-- -----------------------------------------------------------------------------

-- 7.1 set_updated_at em todas as tabelas com `updated_at`
CREATE TRIGGER set_updated_at_modelos
  BEFORE UPDATE ON barravips.modelos
  FOR EACH ROW EXECUTE FUNCTION barravips.set_updated_at();

CREATE TRIGGER set_updated_at_modelo_faq
  BEFORE UPDATE ON barravips.modelo_faq
  FOR EACH ROW EXECUTE FUNCTION barravips.set_updated_at();

CREATE TRIGGER set_updated_at_clientes
  BEFORE UPDATE ON barravips.clientes
  FOR EACH ROW EXECUTE FUNCTION barravips.set_updated_at();

CREATE TRIGGER set_updated_at_conversas
  BEFORE UPDATE ON barravips.conversas
  FOR EACH ROW EXECUTE FUNCTION barravips.set_updated_at();

CREATE TRIGGER set_updated_at_atendimentos
  BEFORE UPDATE ON barravips.atendimentos
  FOR EACH ROW EXECUTE FUNCTION barravips.set_updated_at();

CREATE TRIGGER set_updated_at_bloqueios
  BEFORE UPDATE ON barravips.bloqueios
  FOR EACH ROW EXECUTE FUNCTION barravips.set_updated_at();

-- 7.2 Geração de numero_curto sequencial por modelo
CREATE TRIGGER gen_numero_curto_atendimentos
  BEFORE INSERT ON barravips.atendimentos
  FOR EACH ROW EXECUTE FUNCTION barravips.gen_numero_curto();

-- 7.3 Sincronização do bloqueio quando o atendimento for Fechado/Perdido
CREATE TRIGGER sync_bloqueio_estado_atendimentos
  AFTER UPDATE OF estado ON barravips.atendimentos
  FOR EACH ROW
  WHEN (NEW.estado IN ('Fechado', 'Perdido') AND OLD.estado IS DISTINCT FROM NEW.estado)
  EXECUTE FUNCTION barravips.sync_bloqueio_estado();

-- 7.4 Atualização da timeline da conversa em cada mensagem nova
CREATE TRIGGER atualiza_ultima_mensagem_conversa
  AFTER INSERT ON barravips.mensagens
  FOR EACH ROW EXECUTE FUNCTION barravips.atualiza_ultima_mensagem_em_conversa();

-- 7.5 Sincronização auth.users → barravips.usuarios
-- Nome qualificado por schema pra não colidir com triggers pré-existentes em
-- auth.users (o ProceX já tem um `on_auth_user_created` apontando para
-- public.handle_new_user() — não relacionado a este projeto).
CREATE TRIGGER on_auth_user_created_barravips
  AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE FUNCTION barravips.handle_new_user();


-- -----------------------------------------------------------------------------
-- 8. Row-Level Security (RLS)
-- -----------------------------------------------------------------------------
-- Estratégia P0:
--   - Backend (FastAPI/ARQ workers) usa service_role do Supabase, que faz BYPASS
--     automático da RLS. Toda escrita operacional vai por aí.
--   - Painel (Next.js) usa chave anon/authenticated com sessão Supabase Auth.
--     Para Fernando (papel='fernando' em barravips.usuarios), a policy
--     `fernando_full_access` libera SELECT/INSERT/UPDATE/DELETE em tudo.
--   - Realtime herda RLS — o subscribe do painel só recebe rows que o usuário
--     pode ler.
--   - Quando vendedor_read_only entrar no P1, criar tabela `usuarios_modelos`
--     (N:N) e estender as policies com OR sobre o JOIN.

-- Helper: barravips.is_fernando() (definida em §4.4) é SECURITY DEFINER e STABLE,
-- evitando recursão de RLS ao consultar barravips.usuarios dentro das policies.
-- A skill supabase-postgres-best-practices recomenda embrulhar em (SELECT ...)
-- pra que o planner cacheie a expressão por query.

ALTER TABLE barravips.usuarios            ENABLE ROW LEVEL SECURITY;
ALTER TABLE barravips.modelos             ENABLE ROW LEVEL SECURITY;
ALTER TABLE barravips.modelo_faq          ENABLE ROW LEVEL SECURITY;
ALTER TABLE barravips.modelo_midia        ENABLE ROW LEVEL SECURITY;
ALTER TABLE barravips.clientes            ENABLE ROW LEVEL SECURITY;
ALTER TABLE barravips.conversas           ENABLE ROW LEVEL SECURITY;
ALTER TABLE barravips.atendimentos        ENABLE ROW LEVEL SECURITY;
ALTER TABLE barravips.bloqueios           ENABLE ROW LEVEL SECURITY;
ALTER TABLE barravips.mensagens           ENABLE ROW LEVEL SECURITY;
ALTER TABLE barravips.comprovantes_pix    ENABLE ROW LEVEL SECURITY;
ALTER TABLE barravips.escaladas           ENABLE ROW LEVEL SECURITY;
ALTER TABLE barravips.eventos             ENABLE ROW LEVEL SECURITY;

-- FORCE RLS: aplica RLS inclusive ao owner da tabela (postgres). Defesa em
-- profundidade contra bypass acidental — service_role continua bypassando por
-- ter o atributo BYPASSRLS, mas ninguém mais escapa.
ALTER TABLE barravips.usuarios            FORCE ROW LEVEL SECURITY;
ALTER TABLE barravips.modelos             FORCE ROW LEVEL SECURITY;
ALTER TABLE barravips.modelo_faq          FORCE ROW LEVEL SECURITY;
ALTER TABLE barravips.modelo_midia        FORCE ROW LEVEL SECURITY;
ALTER TABLE barravips.clientes            FORCE ROW LEVEL SECURITY;
ALTER TABLE barravips.conversas           FORCE ROW LEVEL SECURITY;
ALTER TABLE barravips.atendimentos        FORCE ROW LEVEL SECURITY;
ALTER TABLE barravips.bloqueios           FORCE ROW LEVEL SECURITY;
ALTER TABLE barravips.mensagens           FORCE ROW LEVEL SECURITY;
ALTER TABLE barravips.comprovantes_pix    FORCE ROW LEVEL SECURITY;
ALTER TABLE barravips.escaladas           FORCE ROW LEVEL SECURITY;
ALTER TABLE barravips.eventos             FORCE ROW LEVEL SECURITY;

-- Policy única "fernando_full_access" em todas as tabelas, restrita ao role
-- `authenticated` (a service_role do Supabase já bypassa RLS sem precisar de policy).
DO $$
DECLARE
  t text;
BEGIN
  FOR t IN
    SELECT unnest(ARRAY[
      'usuarios','modelos','modelo_faq','modelo_midia',
      'clientes','conversas','atendimentos','bloqueios','mensagens',
      'comprovantes_pix','escaladas','eventos'
    ])
  LOOP
    EXECUTE format($f$
      CREATE POLICY fernando_full_access
        ON barravips.%I
        AS PERMISSIVE
        FOR ALL
        TO authenticated
        USING ((SELECT barravips.is_fernando()))
        WITH CHECK ((SELECT barravips.is_fernando()));
    $f$, t);
  END LOOP;
END
$$;


-- -----------------------------------------------------------------------------
-- 8.5 Privilégios (GRANTs)
-- -----------------------------------------------------------------------------
-- Schemas customizados no Supabase NÃO recebem grants automáticos para os roles
-- anon/authenticated/service_role. Sem estes GRANTs, mesmo com RLS permissiva,
-- queries em barravips.* falham com "permission denied for schema barravips"
-- antes da RLS ser avaliada.
--
-- service_role (BYPASSRLS) precisa de USAGE no schema + ALL nas tabelas.
-- authenticated (sujeito a RLS) recebe SELECT/INSERT/UPDATE/DELETE — a policy
-- fernando_full_access decide quais rows.
-- anon (não autenticado) NÃO recebe grants — não há fluxo público no MVP.
--
-- ATENÇÃO: além destes GRANTs, o schema `barravips` precisa estar em
-- "Project Settings → API → Exposed schemas" no dashboard do Supabase pra
-- aparecer no PostgREST e no Realtime. Isso é config, não SQL.

GRANT USAGE ON SCHEMA barravips TO authenticated, service_role;

GRANT ALL PRIVILEGES ON ALL TABLES    IN SCHEMA barravips TO service_role;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA barravips TO service_role;
GRANT EXECUTE        ON ALL FUNCTIONS IN SCHEMA barravips TO service_role;

GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES    IN SCHEMA barravips TO authenticated;
GRANT USAGE, SELECT                  ON ALL SEQUENCES IN SCHEMA barravips TO authenticated;
GRANT EXECUTE                        ON ALL FUNCTIONS IN SCHEMA barravips TO authenticated;

-- Default privileges: garante que tabelas/funções criadas no futuro herdam
-- automaticamente os mesmos grants (sem precisar reaplicar a cada migration).
ALTER DEFAULT PRIVILEGES IN SCHEMA barravips
  GRANT ALL PRIVILEGES ON TABLES    TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA barravips
  GRANT ALL PRIVILEGES ON SEQUENCES TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA barravips
  GRANT EXECUTE        ON FUNCTIONS TO service_role;

ALTER DEFAULT PRIVILEGES IN SCHEMA barravips
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES    TO authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA barravips
  GRANT USAGE, SELECT                  ON SEQUENCES TO authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA barravips
  GRANT EXECUTE                        ON FUNCTIONS TO authenticated;


-- -----------------------------------------------------------------------------
-- 9. Realtime publication (doc 06 §5.3)
-- -----------------------------------------------------------------------------
-- Tabelas que o painel assina via Supabase Realtime (Postgres Changes c/ RLS).
ALTER PUBLICATION supabase_realtime ADD TABLE
  barravips.atendimentos,
  barravips.mensagens,
  barravips.bloqueios,
  barravips.comprovantes_pix,
  barravips.eventos;


-- -----------------------------------------------------------------------------
-- 10. Comentários complementares (campos críticos)
-- -----------------------------------------------------------------------------
COMMENT ON COLUMN barravips.atendimentos.numero_curto IS
  'Sequencial por modelo, gerado por trigger BEFORE INSERT. Usado como #N em comandos do grupo (doc 05 §3).';
COMMENT ON COLUMN barravips.atendimentos.ia_pausada IS
  'Flag ortogonal ao estado (doc 04 §8.5). Pode coexistir com qualquer estado pré-fechamento.';
COMMENT ON COLUMN barravips.atendimentos.sinais_qualificacao IS
  'jsonb {informa_horario, informa_local, aceita_valor, envia_pix, responde_objetivamente} — doc 04 §4.4.';
COMMENT ON COLUMN barravips.atendimentos.fonte_decisao_ultima_transicao IS
  'Auditoria da última transição (doc 04 §9.1).';
COMMENT ON COLUMN barravips.mensagens.atendimento_id IS
  'Atribuído pelo coordenador (5.2) após resolver/criar atendimento. Mensagem é persistida ANTES dessa resolução (doc 03 §5.1).';
COMMENT ON COLUMN barravips.mensagens.evolution_message_id IS
  'Único — usado para idempotência no webhook do Evolution.';
COMMENT ON COLUMN barravips.bloqueios.estado IS
  'bloqueado | em_atendimento | concluido | cancelado. Sobreposição é proibida apenas em estados ativos.';
COMMENT ON COLUMN barravips.eventos.payload IS
  'jsonb com dados da ação (estado anterior/novo, valor, motivo, fonte_decisao). GIN index para busca.';

-- =============================================================================
-- Fim do schema inicial.
--   12 tabelas, 24 enums, 7 funções (uuidv7, set_updated_at, gen_numero_curto,
--   sync_bloqueio_estado, is_fernando, atualiza_ultima_mensagem_em_conversa,
--   handle_new_user), 10 triggers, 25 índices adicionais (incluindo 5 cobrindo
--   FKs CASCADE/SET NULL), 1 policy por tabela + FORCE RLS em todas,
--   5 tabelas em Realtime, GRANTs explícitos para authenticated e service_role
--   + ALTER DEFAULT.
-- =============================================================================
