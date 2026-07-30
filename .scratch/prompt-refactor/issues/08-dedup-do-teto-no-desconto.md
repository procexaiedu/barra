# 08 — A escada de desconto diz o teto uma vez, não três

**What to build:** mudança sem efeito de comportamento: a regra "depois do teto não há oferta nova" está escrita três vezes em seis linhas do bloco de desconto, e o primeiro item da escada termina com três formulações da mesma coisa — a do meio sendo uma linha do núcleo repetida. Sai texto, a escada fica idêntica.

Verificação é o ponto: os dois gates de desconto que já existem precisam ficar verdes sem nenhuma alteração de expectativa.

**Blocked by:** 01

**Status:** resolved

- [x] duas rodadas de contraproposta, degrau e depois teto, seguem exatamente como hoje
- [x] terceira insistência continua recebendo a recusa e escalando na insistência
- [x] pedido que já começa abaixo do teto continua sem oferta nova
- [ ] gates de desconto (dentro do degrau e abaixo do teto) verdes sem mudar expectativa

---

Diagnóstico de origem: `.scratch/prompt-refactor/auditoria-carga-instrucional.md` (com os anexos `inventario-turno.md` e `eixo-*.md`, que trazem as linhas citadas).

> Os anexos citam número de linha; este ticket cita bloco/tag de propósito — os números do `regras.md.j2` envelheceram em 40 min durante a própria auditoria.

## Comments

**Feito** — três cortes, todos dentro do bloco `<desconto>` do `regras.md.j2`. Nenhum outro arquivo tocado.

**Qual formulação o backstop pressupõe (a pergunta que gateava o corte).** O backstop determinístico é
`<ja_fez_contraproposta n="…">` (`contexto_dinamico.md.j2`, coluna `n_contrapropostas`, ADR-0031). O texto
do degrau `n="2"` é **autocontido**: "Não oferte outro desconto. Aceite fecha no valor da mesa; pedido
abaixo, de novo: 'Poxa amor não consigo' e, na insistência, escale com fora_de_oferta." Ou seja, ele espelha
**o item 5 da escada** — gatilho (pedido abaixo depois do teto), fala literal e escalada. As outras duas
formulações não são pressupostas por ele: a de `:160` é um aposto dentro do item do teto, e a do parágrafo
do aceite é carona. Item 5 fica intacto, palavra por palavra.

**Os cortes:**

1. Item 4 da escada (o teto) — sai `, não tem terceira oferta` (**25 chars**). O que sobra na mesma frase
   já diz o mesmo: "esse é o seu melhor valor: não desce mais um centavo".
2. Parágrafo do aceite ("qualquer sinal de aceite ou avanço… é SIM ao valor que está na mesa") — sai a
   cauda ` — e depois do teto não há oferta nova, só "Poxa amor não consigo"` (**66 chars**), quatro linhas
   depois do item 5 que a define. A frase termina em "A recusa só volta se ele pedir de novo, explícito, um
   número abaixo do valor na mesa."
3. Item 1 da escada, fecho da cláusula de referência externa — sai a 2ª de três formulações,
   `seu preço sai da sua tabela e do seu histórico interno, nunca da memória dele nem do print que ele
   descreve, ` (**109 chars**). Era `<nucleo>` linha 2 reafirmado ("Preço … saem SÓ dos seus blocos");
   ficam a 1ª ("não mudam sua tabela nem pulam degrau") e a 3ª, que é a única acionável ("você não valida,
   discute nem comenta o número dele"). As três âncoras concretas (comparação de mercado, combinado que ele
   afirma, anúncio que ele descreve) ficam.

**Delta do bloco `<desconto>`: 3.987 → 3.787 chars (−200).** Bate com a soma dos itens da auditoria
(25 + 66 + 109 = 200). O cabeçalho do A1.1 no `eixo-a` anuncia 147, mas a linha "Cortar:" do mesmo item
prescreve 66 + 25 = 91 — segui a prescrição itemizada, não o cabeçalho.

**Ecos verificados antes de cortar, todos intactos:**
- "Avanço que equivale a sim" (eco multi-site declarado no `agente/CLAUDE.md`): o site canônico é justamente
  o parágrafo do aceite, e a cauda cortada **não** faz parte do que os ecos afirmam — nem o campo
  `aceita_valor` de `ferramentas/extracao.py` nem a variante `aceite-referenciado` de
  `evals/extracao/extrator.py` mencionam "depois do teto"/"terceira oferta". Sem drift.
- Duas rodadas e o "abaixo do teto escala" continuam ditos em `<nucleo>` item 6, em `<nucleo_final>` e no
  `reminder`. Nenhum eco foi tocado, porque a regra não mudou.
- `grep` por "terceira oferta" / "não há oferta nova" / "histórico interno" / "print que ele" em `tests/`,
  `evals/`, `src/` e `docs/`: zero asserts sobre as strings removidas.

**Verificação local (verde):** `make lint` (ruff, All checks passed), `make typecheck` (mypy, 142 arquivos,
0 issues), `make test` (**1810 passed, 239 skipped, 8 deselected**). `needs_db` não rodou de propósito — o
`DATABASE_URL` do `.env` aponta pro self-hosted de produção (§0). Passa junto o
`tests/unit/test_contraproposta_flag.py`, que amarra os três degraus da tag do backstop.

**Pendente e pago (não rodei — autorização é do humano):**
`cd api && uv run python -m evals.e2e.conduta_gate` — precisa fechar com os três cenários de desconto de
`evals/e2e/cenarios.py` (`desconto_dentro_degrau`, `desconto_entre_degrau_teto`, `desconto_abaixo_teto`)
verdes **sem mudar expectativa**, contra o baseline `dd4a7e9` (APROVADO, `empurrao_pct` 0,0%,
`violacoes_duras` 0). Se algum exigir afrouxar asserção, o corte está errado e a resposta é reverter, não
ajustar o teste. É o único checkbox que fica aberto.

**Redeploy:** o LangGraph roda no `barra-worker` — mudança de prompt só vale em prod depois de
`docker service update --force <stack>_barra-worker`. Nada disso foi feito; nada commitado.

**Fechamento parcial (driver, 2026-07-30).** Diff conferido: três cortes, todos dentro do bloco
`<desconto>`, nenhum outro arquivo. **−200 chars** (3.987 → 3.787).

O que tornou o corte seguro, e que o ticket exigia checar antes: o backstop
`<ja_fez_contraproposta n="2">` é autocontido e espelha o **item 5** da escada (gatilho, fala
literal e `fora_de_oferta`). As duas formulações cortadas não são pressupostas por ele — uma era
aposto dentro do item do teto, a outra carona no parágrafo do aceite. **Item 5 intacto, palavra por
palavra.**

O terceiro corte (a cláusula de referência externa no item 1) é absorvido pelo `<nucleo>` linha 2,
que verifiquei no texto vivo: "Preço, duração, serviço, extra e endereço saem SÓ dos seus blocos. O
que não está lá você não cota, não promete e não inventa." A parte acionável específica da objeção
externa permanece no item 1.

`make lint` ✅ · `make typecheck` ✅ · `make test` ✅ (1810 passed — mesmo número do ticket 07,
como esperado num dedup sem teste novo; `test_contraproposta_flag.py`, que amarra os três degraus
da tag, segue verde sem alteração de expectativa).

Critérios 1–3 cumpridos. **Critério 4 pendente**: os gates de desconto rodam no checkpoint do lote
03–08. A regra do ticket vale na leitura do resultado — se algum só passar afrouxando asserção, o
corte está errado e se reverte, não se ajusta o teste.

**Fechado no checkpoint (driver, 2026-07-30).** O `conduta_gate` rodou contra o baseline `dd4a7e9`
e voltou **APROVADO** (`empurrao_pct 0,0%`, `violacoes_duras 0`), com o lote melhorando condução
(`conduziu decidido_rapido` 0% → 50%), desfecho (`bate_desfecho_real` 83,3% → 91,7%) e forma
(`fluxo_jsd` 0,1985 → 0,1896). Números e a comparação das duas corridas em
`.scratch/prompt-refactor/checkpoint-lote-03-08.md`. `Status: resolved`.
