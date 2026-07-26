# 03 — Contador de pergunta de horário

**What to build:** Quando a IA pergunta o horário e o cliente desconversa (emoji, elogio, "que bom rs"), ela para de reperguntar: na vez seguinte propõe ela um horário concreto da agenda ("Podemos combinar 21h amor ?"); da segunda em diante não pergunta mais, propõe e segue. Hoje isso depende de o LLM contar as próprias perguntas dentro da janela de 20 mensagens.

**Blocked by:** 01 — mesma área do carimbo no write-time; a 01 fixa o molde.

**Status:** ready-for-agent

- [ ] Coluna contadora em `atendimentos` (smallint, default 0), no molde de `n_contrapropostas`, com migration em `infra/sql/`. Não aplicar em prod.
- [ ] Detector em `_disciplina.py` para a **pergunta de horário sem proposta** ("Seria que horas ?", "Qual horário amor ?"). Não casa a proposta que já carrega hora ("Consigo às 22h, fecha ?") — reaproveitar a leitura de hora explícita que já existe. Não dobra com a sondagem do dia ("seria hoje?" / "seria agora?"), que tem flag própria: teste cobrindo a fronteira entre as duas.
- [ ] Incremento no write-time só quando a bolha foi de fato inserida (`RETURNING` do `ON CONFLICT DO NOTHING`), para o retry não dobrar a contagem.
- [ ] Campo no `ContextoDoTurno` + tag no `contexto_dinamico.md.j2` com dois degraus (n=1: proponha você um horário concreto; n≥2: não pergunte mais, proponha e siga), no molde do `<ja_fez_contraproposta>`.
- [ ] O trecho de `<conducao_da_venda>` sobre não reperguntar "que horas ?" turno após turno encolhe para o resíduo.
- [ ] `make gate-conduta` e `make evals` verdes; gate padrão verde.
