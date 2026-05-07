# Prompt — Gerar SQL de Seed por Cliente (Barra Vips)

Você é um agente especialista em SQL (PostgreSQL / Supabase). Sua tarefa é gerar o arquivo SQL de seed do **próximo cliente ainda não gerado** do projeto Barra Vips.

## Passo 1 — Determinar o próximo cliente

Verifique quais arquivos existem em `infra/sql/` com o padrão `*_seed_*.sql`. A lista de clientes e seus arquivos esperados, **em ordem**, é:

| # | Cliente     | CLIENT_ID                                    | Arquivo esperado              |
|---|-------------|----------------------------------------------|-------------------------------|
| 1 | Ricardo     | `c1000000-0000-0000-0000-000000000001`        | `*_seed_ricardo.sql`          |
| 2 | Marcos      | `c1000000-0000-0000-0000-000000000002`        | `*_seed_marcos.sql`           |
| 3 | Bruno       | `c1000000-0000-0000-0000-000000000003`        | `*_seed_bruno.sql`            |
| 4 | Felipe      | `c1000000-0000-0000-0000-000000000004`        | `*_seed_felipe.sql`           |
| 5 | Adriano     | `c1000000-0000-0000-0000-000000000005`        | `*_seed_adriano.sql`          |
| 6 | Lucas       | `c1000000-0000-0000-0000-000000000006`        | `*_seed_lucas.sql`            |
| 7 | Rodrigo     | `c1000000-0000-0000-0000-000000000007`        | `*_seed_rodrigo.sql`          |
| 8 | Daniel      | `c1000000-0000-0000-0000-000000000008`        | `*_seed_daniel.sql`           |
| 9 | Eduardo     | `c1000000-0000-0000-0000-000000000009`        | `*_seed_eduardo.sql`          |
|10 | Gustavo     | `c1000000-0000-0000-0000-000000000010`        | `*_seed_gustavo.sql`          |
|11 | Paulo       | `c1000000-0000-0000-0000-000000000011`        | `*_seed_paulo.sql`            |
|12 | André       | `c1000000-0000-0000-0000-000000000012`        | `*_seed_andre.sql`            |

Escolha o **primeiro da lista cujo arquivo ainda não existe**. Determine o número sequencial `NNNN` pegando o maior número presente em `infra/sql/` e somando 1. Se todos os arquivos já existirem, informe que os seeds estão completos e encerre.

## Passo 2 — Ler as referências

Leia os dois arquivos abaixo antes de gerar qualquer SQL:

1. `docs/schema_barravips.md` — estrutura completa do banco: tabelas, colunas, tipos, ENUMs, constraints, triggers, ordem de dependências FK.
2. `docs/seed_spec.md` — especificação detalhada dos dados: UUIDs pré-definidos, valores campo a campo, narrativas por cenário.

## Passo 3 — Gerar o arquivo SQL

Gere `infra/sql/{NNNN}_seed_{nome_lower}.sql` contendo:

### Bloco A — Infraestrutura compartilhada (idempotente)

Sempre incluir, com `ON CONFLICT DO NOTHING`:
- `barravips.usuarios` (Fernando)
- `barravips.duracoes`
- `barravips.programas`
- `barravips.modelos` (Alessia, Bruna, Camila)
- `barravips.modelo_faq`
- `barravips.modelo_midia`
- `barravips.modelo_servicos`
- `barravips.modelo_programas`

### Bloco B — Dados do cliente alvo

Somente para o cliente escolhido no Passo 1:
- `barravips.clientes`
- `barravips.conversas` (1 por modelo com quem o cliente interagiu)
- `barravips.bloqueios` com `atendimento_id = NULL`
- `barravips.atendimentos` com `bloqueio_id = NULL`
- `UPDATE` cruzado de `bloqueios.atendimento_id` e `atendimentos.bloqueio_id`
- `barravips.mensagens`
- `barravips.comprovantes_pix` (se aplicável)
- `barravips.escaladas`
- `barravips.eventos`
- `barravips.envios_evolution`
- `barravips.atendimento_servicos`

## Regras obrigatórias

1. **Schema:** prefixar todas as tabelas com `barravips.`
2. **UUIDs:** usar exatamente os da seção "2. UUIDs Pré-definidos" do seed_spec. Não inventar.
3. **Timestamps:** usar `NOW() - INTERVAL 'X'` para dados sempre atuais a cada execução.
4. **Transação:** envolver tudo em `BEGIN;` / `COMMIT;`.
5. **Idempotência:** `ON CONFLICT DO NOTHING` em todos os INSERTs.
6. **numero_curto:** NÃO inserir — gerado por trigger. Se o ambiente não executar triggers, inserir explicitamente em sequência por modelo conforme seed_spec.
7. **Referência circular:** inserir bloqueios e atendimentos com NULL mútuo, fazer UPDATEs cruzados depois.
8. **evolution_message_id:** único globalmente — usar prefixo de 8 letras baseado no nome do cliente (ex: `3EB0RICO` para Ricardo) + índice 8 dígitos.
9. **Triggers que não exigem UPDATE manual:** `atualiza_ultima_mensagem_em_conversa` (conversas) e `sync_bloqueio_estado` (bloqueios ao fechar/perder atendimento).
10. **Seções no arquivo:** comentários claros como `-- === INFRA: MODELOS ===`, `-- === CLIENTE: RICARDO ===`.
11. **Mensagens:** mínimo 3 por atendimento (abertura do cliente, resposta da IA, encerramento).
12. **Constraints:**
    - `conversas`: UNIQUE `(cliente_id, modelo_id)`
    - `atendimentos`: UNIQUE parcial — um aberto por par `(cliente_id, modelo_id)`
    - `modelo_programas`: PK `(modelo_id, programa_id, duracao_id)`
    - `mensagens`: `media_object_key` obrigatório quando `tipo IN ('audio', 'imagem')`
    - `atendimentos`: `valor_final` obrigatório em `Fechado`; `motivo_perda` obrigatório em `Perdido`; `ia_pausada_motivo` obrigatório quando `ia_pausada = true`