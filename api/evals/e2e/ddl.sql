-- corpus.eval_e2e: uma linha por corrida e2e (1 PerfilCaso x 1 run_tag).
-- NAO aplicar contra prod automaticamente (§0: escrita em prod e ato manual autorizado).
-- Vive no schema `corpus` (read-only de pesquisa, fora de barravips), como as demais eval_*.

CREATE TABLE IF NOT EXISTS corpus.eval_e2e (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    run_tag            text        NOT NULL,
    perfil_nome        text        NOT NULL,
    eixo               text        NOT NULL DEFAULT '',  -- eixo de comportamento (cobertura); '' nos cenarios sinteticos
    thread_ref         text,                    -- origem no corpus (instancia:remote_jid)
    desfecho_conducao  text        NOT NULL,    -- conduziu | pausou_handoff | cliente_sumiu | max_turnos
    estado_final       text,                    -- estado do atendimento ao parar
    conduziu           boolean     NOT NULL,    -- estado_final em {Aguardando_confirmacao, Confirmado}
    desfecho_real      text,                    -- corpus.threads.desfecho_proxy (rotulo)
    bate_desfecho_real boolean,                 -- conduziu == convergiu_real
    n_turnos           integer     NOT NULL,
    custo_brl          numeric(10,4) NOT NULL DEFAULT 0,
    violacoes          jsonb       NOT NULL DEFAULT '[]'::jsonb,
    trajetoria         jsonb       NOT NULL DEFAULT '[]'::jsonb,  -- estado_final por turno
    criado_em          timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_eval_e2e_run_tag ON corpus.eval_e2e (run_tag);
