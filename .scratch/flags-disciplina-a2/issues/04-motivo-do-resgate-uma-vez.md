# 04 — O motivo do resgate é perguntado uma vez

**What to build:** Na despedida educada do cliente ("obrigado, fica pra próxima"), a IA pergunta o motivo uma vez ("Poxa, não gostou de mim?") e não repete essa pergunta no resto da conversa — inclusive se ele voltar depois de um silêncio. O que a resposta dele destrava (se o motivo for preço e ainda houver degrau ou teto disponível, a escada entra) continua valendo.

**Blocked by:** 01 — mesma área do carimbo no write-time; a 01 fixa o molde.

**Status:** ready-for-agent

- [x] Coluna nova em `atendimentos` (timestamptz, first-write-wins), migration em `infra/sql/` com `COMMENT ON COLUMN`. Não aplicar em prod. — `20260726031204_atendimentos_motivo_resgate_perguntado.sql` (`motivo_resgate_perguntado_em`), não aplicada.
- [x] Detector em `_disciplina.py` para a pergunta de resgate, cobrindo as formas que o prompt treina. Não casa a recusa de desconto nem o empurrão de fechamento. — `contem_pergunta_do_motivo_do_resgate`, ancorado no "de mim" (a negação solta casava a contraproposta "se você não gostou do valor consigo 500, fecha ?" e a reação ao book "não curtiu as fotos ?").
- [x] Carimbo no write-time, mesma transação, só na primeira inserção da bolha. — `workers/envio.py`, sob o mesmo `inseriu` das irmãs.
- [x] Campo no `ContextoDoTurno` + tag no `contexto_dinamico.md.j2` — `motivo_resgate_ja_perguntado` → `<ja_perguntou_o_motivo>`.
- [x] O parágrafo do resgate no `<desconto>` encolhe. **Não tocar** a proibição de perguntar um número. — saiu só o "uma vez" (a mecânica que virou coluna); a proibição do número está intacta.
- [ ] `make gate-conduta` e `make evals` verdes; gate padrão verde. — gate padrão verde (`make lint`, `make typecheck`, `make test`: 1728 passed). `gate-conduta`/`evals` e os `needs_db` **não rodaram**: exigem `TEST_DATABASE_URL` (o `.env` local aponta pra prod) + crédito → §0.
