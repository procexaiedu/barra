# Scripts

Utilitarios de desenvolvimento e operacao local.

Nao colocar codigo de producao neste diretorio.

- `nova-trilha.ps1` — cria uma worktree dedicada para uma trilha de tasks isolada (`git worktree add` da main + copia `api/.env` + deriva `TEST_DATABASE_URL`).
- `aplicar_sql.py` — aplica SQL no banco via psycopg.
- `reset_agente.py` — reset de estado do agente para testes.
- `vincular_instance_legacy.py` — vincula instancia Evolution legada a uma modelo.
- `tail_prod.py` — tail cronologico do trafego de prod: uma linha por MENSAGEM (cliente e IA), com estado do atendimento e a mecanica do turno vinda do trace no Langfuse. Marca cliente sem resposta — que o painel `/observabilidade` (so `direcao='ia'`) nao mostra. Somente leitura. `--follow` ao vivo, `--json` p/ agente.
- `monitor_atendimentos.py` — vigia de prod em 2 estagios: o gate le o banco a cada tick (custo zero) e so quando ha turno novo invoca `claude -p` pra julgar a conduta contra CONTEXT.md/ADRs, gravando relatorio em `~/.barra-monitor/relatorios/` e notificando no macOS a cada atendimento novo. Agendado por `launchd/com.barra.monitor.plist` (5 min). Somente leitura.
- `repara_encoding_evals.py` — conserta mojibake (dupla codificacao latin-1<->utf-8) nas fixtures `.jsonl` de `api/evals/`. Idempotente; `--dry-run` so reporta.
- `backfill_presos_pre_98.py` — one-off: abre Handoff `modelo_pausada` para atendimentos presos com o motivo antigo `modelo_em_atendimento` (pausados antes do deploy da issue #98). ⚠️ ESCREVE no banco do `--dsn` e dispara cards reais; `--dry-run` so lista. Rodar de `api/` (importa `barra.*`).
