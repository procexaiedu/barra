Você é um agente especialista em SQL (PostgreSQL / Supabase). Sua tarefa é gerar o arquivo SQL de seed do **próximo cliente ainda não gerado** do projeto Barra Vips.

## Passo 1 — Determinar o próximo cliente

Verifique quais arquivos existem em `infra/sql/` com o padrão `*_seed_*.sql`. A lista de clientes e seus arquivos esperados, **em ordem**, é:

| # | Cliente  | CLIENT_ID                               | Arquivo esperado         | Evolution prefix |
|---|----------|-----------------------------------------|--------------------------|------------------|
| 1 | Ricardo  | `c1000000-0000-0000-0000-000000000001`  | `0013_seed_ricardo.sql`  | `3EB0RICO`       |
| 2 | Eduardo  | `c1000000-0000-0000-0000-000000000002`  | `0014_seed_eduardo.sql`  | `3EB0EDUA`       |
| 3 | Gustavo  | `c1000000-0000-0000-0000-000000000003`  | `0015_seed_gustavo.sql`  | `3EB0GUST`       |
| 4 | Adriano  | `c1000000-0000-0000-0000-000000000004`  | `0016_seed_adriano.sql`  | `3EB0ADRI`       |
| 5 | Marcos   | `c1000000-0000-0000-0000-000000000005`  | `0017_seed_marcos.sql`   | `3EB0MARC`       |
| 6 | Bruno    | `c1000000-0000-0000-0000-000000000006`  | `0018_seed_bruno.sql`    | `3EB0BRUN`       |
| 7 | Felipe   | `c1000000-0000-0000-0000-000000000007`  | `0019_seed_felipe.sql`   | `3EB0FELI`       |
| 8 | Rodrigo  | `c1000000-0000-0000-0000-000000000008`  | `0020_seed_rodrigo.sql`  | `3EB0RODR`       |

Escolha o **primeiro da lista cujo arquivo ainda não existe**. Se todos já existirem, informe que os seeds estão completos e encerre.

## Passo 2 — Ler as referências

Leia os dois arquivos abaixo **antes** de gerar qualquer SQL:

1. `docs/schema_barravips.md` — estrutura completa do banco: tabelas, colunas, tipos, ENUMs, constraints, triggers e ordem de dependências FK.
2. `docs/seed_spec.md` — especificação completa dos dados: UUIDs pré-definidos, valores campo a campo, narrativas e mensagens por cenário. Use a seção **"2. UUIDs Pré-definidos"** para localizar os IDs do cliente e dos atendimentos vinculados.

## Passo 3 — Gerar o arquivo SQL

Gere `infra/sql/{arquivo_esperado}` com dois blocos:

---

### Bloco A — Infraestrutura compartilhada (idempotente)

Sempre incluir, com `ON CONFLICT DO NOTHING`:

- `barravips.usuarios` — Fernando (`00000000-0000-0000-0000-000000000001`)
- `barravips.duracoes` — DUR_1H … DUR_PERNOITE
- `barravips.programas` — PRG_MASSAGEM … PRG_TANTRICA
- `barravips.modelos` — **Alessia** (`a1000000-0000-0000-0000-000000000001`) e **Bruna** (`a1000000-0000-0000-0000-000000000002`)
- `barravips.modelo_faq` — todos os FAQs das duas modelos
- `barravips.modelo_midia` — todas as mídias das duas modelos
- `barravips.modelo_servicos` — todos os serviços das duas modelos
- `barravips.modelo_programas` — todas as combinações das duas modelos

---

### Bloco B — Dados exclusivos do cliente alvo

Somente para o cliente escolhido no Passo 1. Siga a ordem abaixo:

1. `barravips.clientes`
2. `barravips.conversas` (uma por modelo com quem o cliente interagiu, conforme seed_spec)
3. `barravips.bloqueios` com `atendimento_id = NULL`
4. `barravips.atendimentos` com `bloqueio_id = NULL`
5. `UPDATE` cruzado `bloqueios.atendimento_id` e `atendimentos.bloqueio_id`
6. `barravips.mensagens`
7. `barravips.comprovantes_pix` (se aplicável — inserir após mensagens, FK → mensagens.id)
8. `barravips.escaladas`
9. `barravips.eventos`
10. `barravips.envios_evolution`
11. `barravips.atendimento_servicos` (apenas atendimentos `Fechado`)

---

## Regras obrigatórias

1. **Schema:** prefixar todas as tabelas com `barravips.`
2. **UUIDs:** usar exatamente os da seção "2. UUIDs Pré-definidos" do `seed_spec.md`. Não inventar UUIDs.
3. **Timestamps:** usar `NOW() - INTERVAL 'X'` para dados relativos ao momento de execução, conforme os intervalos especificados no `seed_spec.md`.
4. **Transação:** envolver tudo em `BEGIN;` / `COMMIT;`.
5. **Idempotência:** `ON CONFLICT DO NOTHING` em todos os INSERTs.
6. **numero_curto:** NÃO inserir explicitamente — gerado por trigger. Se o ambiente não executar triggers, inserir conforme o valor numérico indicado no seed_spec (sequencial por `modelo_id`).
7. **Referência circular bloqueios ↔ atendimentos:** inserir ambos com NULL mútuo e executar os UPDATEs cruzados logo após.
8. **evolution_message_id:** globalmente único. Usar o prefixo da coluna "Evolution prefix" da tabela acima (8 chars) + índice 8 dígitos em zero-pad. Ex: Ricardo → `3EB0RICO00000001`, `3EB0RICO00000002`. Cards no grupo de coordenação: `3EB0{PREFIX}CARD0001`. Mensagens da IA: `3EB0{PREFIX}IA000001`.
9. **Triggers automáticos — não gerar UPDATE manual para:**
   - `atualiza_ultima_mensagem_em_conversa`: atualiza `conversas.ultima_mensagem_em` e `ultima_mensagem_direcao` a cada INSERT em mensagens.
   - `sync_bloqueio_estado`: atualiza `bloqueios.estado` para `concluido` (Fechado) ou `cancelado` (Perdido) automaticamente.
   - `gen_numero_curto`: gera `atendimentos.numero_curto` sequencial por `modelo_id`.
10. **Seções no arquivo:** usar comentários de bloco claros, ex: `-- ============================================================`, `-- BLOCO A — INFRAESTRUTURA`, `-- BLOCO B — CLIENTE: RICARDO`, `-- === clientes ===`, `-- === mensagens ===`.
11. **Mensagens:** incluir todas as mensagens do seed_spec para o cliente. Mínimo 3 por atendimento (abertura do cliente, resposta da IA, encerramento ou desfecho). Para mensagens do tipo `imagem` ou `audio`, preencher `media_object_key`.
12. **Constraints críticas:**
    - `conversas`: UNIQUE `(cliente_id, modelo_id)` — um registro por par.
    - `atendimentos`: UNIQUE parcial — um atendimento aberto (não Fechado/Perdido) por par `(cliente_id, modelo_id)`.
    - `modelo_programas`: PK composta `(modelo_id, programa_id, duracao_id)`.
    - `mensagens`: `media_object_key` obrigatório quando `tipo IN ('audio', 'imagem')`.
    - `atendimentos`: `valor_final` NOT NULL quando `estado = 'Fechado'`; `motivo_perda` NOT NULL quando `estado = 'Perdido'`; `ia_pausada_motivo` NOT NULL quando `ia_pausada = true`.
    - `comprovantes_pix`: `mensagem_id` é FK obrigatória → inserir após as mensagens.
