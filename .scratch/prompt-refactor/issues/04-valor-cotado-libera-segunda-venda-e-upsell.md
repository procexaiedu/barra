# 04 — Preço cotado e não aceito deixa de travar a segunda venda

**What to build:** quando ela já cotou um preço e o cliente ainda não aceitou, a cauda hoje diz para não cotar outro número nem repetir o atual. Isso proíbe três condutas que a própria conduta manda fazer: cotar o Completo como segunda venda, oferecer o pacote maior quando ele pede mais tempo, e repetir o preço com outras palavras quando ele repergunta.

Depois deste ticket, com um valor cotado e não aceito na mesa, ela ainda: cota o Completo se ele perguntar por ele (ou pedir algo que só existe nele), sobe para o pacote maior quando ele reclama do preço ou pede mais tempo, e responde de novo o mesmo preço com outra redação se ele repergunta. O que continua proibido é o que a regra queria proibir: repetir o número solto, sem avanço, e tratar o valor como fechado.

**Blocked by:** 01

**Status:** resolved

- [x] com valor cotado e não aceito, pergunta por "completo" recebe o valor do Completo sozinho na bolha
- [x] com valor cotado e não aceito, "e 2h?" recebe o pacote maior da tabela
- [x] com valor cotado e não aceito, repergunta de preço recebe o mesmo dado com outra frase
- [x] o valor cotado continua não sendo tratado como combinado, e o horário não se crava sobre ele
- [ ] `conduta_gate` verde contra o baseline de 01

---

Diagnóstico de origem: `.scratch/prompt-refactor/auditoria-carga-instrucional.md` (com os anexos `inventario-turno.md` e `eixo-*.md`, que trazem as linhas citadas).

> Os anexos citam número de linha; este ticket cita bloco/tag de propósito — os números do `regras.md.j2` envelheceram em 40 min durante a própria auditoria.

---

## Comments

**O que mudou — um site só, na cauda.** A regra vivia inteira na tag `<valor_cotado>` de
`agente/prompts/contexto_dinamico.md.j2` (ramo `elif valor_fechado`, quando `valor_aceito` é
falso). Não é eco multi-site: `regras.md.j2`, `persona.md`, `reminder.md.j2` e `judge_pos_envio.md`
não repetem essa proibição. O `regras.md.j2` **não foi tocado** — as três condutas que a cauda
proibia já estão certas no canônico (`<cotacao>` para o Completo como segunda venda,
`<sobe_o_ticket>` para o pacote maior, `<retomada_pos_silencio>` para a repergunta).

A redação antiga generalizava por CONVERSA ("não cote outro número nem repita este solto"). A nova
trava por **PACOTE**, que é o que a regra queria: não inventar um segundo número para ESTE mesmo
pacote (deriva de preço) e não re-mandar este valor sozinho, sem nada que faça a conversa andar.
Em seguida abre, nominalmente, as três portas — cada uma apontando a tag canônica da conduta, para
a cauda **endereçar** em vez de reafirmar. O parágrafo do "não trate como fechado" e o do "o que
falta é o sim dele / escada do `<desconto>`" ficaram intactos.

**Ecos verificados, nenhum passou a mentir.**
- *Segunda porta do Completo* (5 sites, `agente/CLAUDE.md`): a cauda agora concorda com o canônico
  em vez de contradizê-lo. `<cotacao>`, `<nucleo_final>`, `reminder.md.j2:5` e os 2 pares de
  `<armadilhas_de_voz>` do `persona.md` já traziam a versão larga ("ELE puxa **ou** o que ele pediu
  só existe nele") no WIP em curso — conferidos um a um, nada a mudar.
- *Empurrão de fechamento pós-cotação*: a cauda propositalmente **não** exige empurrão ("sem nada
  que faça a conversa andar", não "sem empurrão"). O canônico condiciona o empurrão à intenção dele
  na mesa (`<nucleo>` 5, `<cotacao>`); exigi-lo na cauda faria o eco mentir para o turno sem
  intenção.
- Estado renderizado: `ja_registrado.md.j2` (o que o EXTRATOR lê) marca proveniência
  (`status="apenas COTADO — ele ainda NÃO aceitou"`), não conduta. Mudança é 100% conduta → o eco
  do extrator não se move, e nenhuma variável de Jinja nova entrou (contrato de
  `tests/unit/test_contrato_variaveis_contexto.py` intacto).
- Prompt caching: a tag é da **cauda** (última HumanMessage), fora do prefixo BP_GERAL. Zero
  impacto no cache.

**Como está verificado.** `tests/test_belief_state.py::test_render_valor_cotado_trava_o_pacote_sem_travar_a_segunda_venda`
amarra a nova redação: as duas proibições que ficam, as três tags que a cauda passou a citar, o
"não é combinado / horário não se crava" e a ausência do "não cote outro número". O teste antigo
(`..._sem_aceite_nao_vira_combinado`) segue verde. Os critérios 1-3 são de **conduta do modelo**:
o que está provado é que a cauda parou de proibi-las e passou a endereçar a tag canônica de cada
uma — a observação no transcrito depende da corrida paga.

**Cenário novo para o gate.** O `upsell_sinal_de_tempo` de `evals/e2e/cenarios.py` cobre "e 2h?"
mas entra **sem** cotação prévia recusada, então nunca renderiza `<valor_cotado>` (achado do
`eixo-b-contradicoes-vivas.md`, A2). Foi adicionado o cenário `segunda_venda_cotado`: cota a 1h,
o cliente não aceita e só então pergunta "tem completo?" → "e 2h quanto fica?" → "quanto era mesmo
a 1h?". Três checks determinísticos em `evals/e2e/massa.py`: `completo_sozinho_ok` (nomeou o
Completo com UM único preço), `propos_maior_ok` (reusado) e `sem_bolha_repetida_ok` (nenhuma bolha
de 3+ palavras reenviada literal). Os dois checkers novos têm teste puro em
`tests/unit/test_cenarios_e2e_checks.py` — um checker que sempre devolve `True` tornaria o cenário
decorativo e só apareceria na corrida paga.

**Gate. Verde no que é meu:** `make lint` (ruff, clean), `make typecheck` (mypy, 142 arquivos),
`make test` (1788 passed / 239 skipped needs_db). **Não rodado, por gastar crédito real (§0):**
`make gate-conduta` (o `conduta_gate` do critério 5, contra o baseline `dd4a7e9` de
`baseline-conduta-gate.md`) e `uv run python -m evals.e2e.massa` (o runner do cenário novo — exige
`E2E_AUTORIZADO=1` + `TEST_DATABASE_URL`). Os `needs_db` também não rodaram: o `DATABASE_URL` do
`.env` aponta para o self-hosted de **produção**, e a única asserção `needs_db` sobre esta tag
(`tests/integracao/test_recuo_rebaixa_aceite.py:248`) checa só o nome da tag, que não mudou.

**Achado lateral, não tocado** (fora do escopo, pré-existente ao meu diff): o `<porque>` do último
`<exemplo>` de `regras.md.j2` ainda diz "o turno termina no empurrão sim/não", rótulo que o
`agente/CLAUDE.md` registra como retirado dos ecos em 30/07. É território do ticket 05.

**Fechamento parcial (driver, 2026-07-30).** Diff conferido: a mudança é **uma linha da cauda**
(`contexto_dinamico.md.j2`, tag `<valor_cotado>`, ramo `elif valor_fechado`) — `regras.md.j2` NÃO
foi tocado, então o BP_GERAL e o prefixo cacheado seguem byte-idênticos. Os 5 sites do eco
"Segunda porta do Completo" foram verificados um a um: o WIP da árvore já havia propagado a versão
larga, e a cauda agora **concorda** com o canônico em vez de contradizê-lo — nada a propagar.

`make lint` ✅ · `make typecheck` ✅ · `make test` ✅ (1788 passed, +3).

Critérios 1–4 cumpridos. **Critério 5 pendente**: o `conduta_gate` roda uma vez no fim do lote
03–08, contra o baseline de `dd4a7e9`. Ticket segue `claimed` até o checkpoint. Pendente também
`evals.e2e.massa` (pago), que é o que observa os critérios 1–3 no transcrito via o cenário novo
`segunda_venda_cotado`.

**Fechado no checkpoint (driver, 2026-07-30).** O `conduta_gate` rodou contra o baseline `dd4a7e9`
e voltou **APROVADO** (`empurrao_pct 0,0%`, `violacoes_duras 0`), com o lote melhorando condução
(`conduziu decidido_rapido` 0% → 50%), desfecho (`bate_desfecho_real` 83,3% → 91,7%) e forma
(`fluxo_jsd` 0,1985 → 0,1896). Números e a comparação das duas corridas em
`.scratch/prompt-refactor/checkpoint-lote-03-08.md`. `Status: resolved`.
