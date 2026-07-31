# 15 — A conduta de cardápio encolhe para quem não tem fetiche cadastrado

**What to build:** o bloco de fora-do-cardápio inteiro pende do bloco de fetiches da modelo — a mecânica de extra cotado, de item incluso, de recusa por item. Modelo sem nenhum fetiche cadastrado carrega esse aparato em cada turno sem ter como aplicá-lo.

Mesmo padrão dos tickets 11 e 12: a condição vira tag na cauda, a prosa encolhe. Este vem depois do 07 porque o guard de saída construído lá é a metade determinística desta mesma regra — sem ele, encolher a prosa é tirar a única rede.

O que **não** encolhe em nenhuma hipótese: camisinha não é item de lista, é como ela trabalha, e nunca sai como "incluso". Essa cláusula nasceu de falha real, o judge deu nota cheia nela e nenhum guard a pega.

**Blocked by:** 07

**Status:** claimed

- [x] modelo sem fetiches recusa pedido de ato com recusa curta de mulher, sem moralizar, e sem desmarcar o encontro — a tag `<sem_fetiches>` diz as três coisas por escrito; o `<fora_do_cardapio>` que as define ficou intacto
- [x] a recusa continua cobrindo só o item pedido, nunca o programa nem os itens vizinhos — nada foi cortado desse parágrafo, e a tag repete a saída ("Nada disso encolhe o encontro")
- [x] "só faço com camisinha" continua saindo como afirmação direta, nunca como item incluso — cláusula intocada no BP_GERAL + reforço na tag + `bolhas_incluso_fantasma`; teste de regressão em `tests/unit/test_sem_fetiches.py`
- [x] insistência com mais dinheiro continua sem precificar e escalando — parágrafo 2 do `<fora_do_cardapio>` intacto; a tag nomeia `fora_de_oferta`
- [ ] `conduta_gate` verde contra o baseline de 01 — **gate pago, pendente de autorização** (comando no `## Comments`)

---

Diagnóstico de origem: `.scratch/prompt-refactor/auditoria-carga-instrucional.md` (com os anexos `inventario-turno.md` e `eixo-*.md`, que trazem as linhas citadas).

> Os anexos citam número de linha; este ticket cita bloco/tag de propósito — os números do `regras.md.j2` envelheceram em 40 min durante a própria auditoria.

---

## Comments

### O que foi feito

1. **O gate virou dado.** `_carregar_bp3` (`nos/prepare_context.py`) já lia as linhas de fetiche da
   modelo para montar o `<fetiches>` do BP_MODELO; agora deriva delas o `sem_fetiches = not
   fetiches` — o espelho exato do `fetiches.md.j2`, que só imprime `(sem fetiches cadastrados)`
   quando as três seções (inclusos ∪ atos ∪ por-pessoa = a lista inteira) saem vazias. **Sem query
   nova**, mesmo caminho do `tabela_max_horas`/`sem_menage`/`sem_video_chamada`. Campo novo no
   `ContextoDoTurno` com default conservador `False`, passado por kwarg por
   `_anexar_contexto_dinamico` → `_resolver_variaveis`.
2. **Tag na cauda `<sem_fetiches>`** (`contexto_dinamico.md.j2`, depois do `<sem_video_chamada>`;
   951 chars, e **só** para quem tem o bloco vazio). Ela carrega o colapso da mecânica —
   sem lista não há extra a cotar e não há linha "Inclusos" — nos dois lados que o `<fora_do_
   cardapio>` mistura: (a) `"tá incluso"/"já vem junto"` não sai sobre ato nenhum, *nem copiado de
   um exemplo desta conduta* (a falha medida), e a apresentação fica só no estilo; (b) ato pedido
   pelo nome e fora dos `<programas>` é recusa curta, sem preço, com a insistência escalando por
   `fora_de_oferta`. E a **fala de substituição** (lição do incidente #36, exigida pelo
   `agente/CLAUDE.md`): "Nada disso encolhe o encontro — o programa dos seus `<programas>` é o que
   ele é (`<girias_do_cliente>`) e segue oferecido com a mesma prontidão de antes". Declarada na
   lista de blocos internos do `<instrucoes_meta>`.
3. **A cláusula da camisinha não passou pela tag.** Ela continua **inteira e incondicional** no
   `<fora_do_cardapio>` ("Camisinha não é item da sua lista, é como você trabalha: nunca sai como
   'incluso' … 'Só faço com camisinha amor'"), como manda o enunciado. A tag só reafirma o
   enquadramento em uma oração e aponta de volta pro bloco — não reescreve a fala nem a condiciona.
   `tests/unit/test_sem_fetiches.py::test_a_tag_nao_engole_a_clausula_da_camisinha` congela os dois
   lados (BP_GERAL + cauda) para que um corte futuro não a leve junto.
4. **BP_GERAL: −73 chars** (`regras.md.j2` 54.570 → 54.497). O único trecho cortado é o **gate em
   prosa do caso vazio** no `<apresentacao>`: "*, e sem essa linha no seu bloco a apresentação fica
   só no estilo, sem lista de incluso*". Ele agora é dado (a tag, para a modelo sem fetiche nenhum)
   e trilho determinístico (o `bolhas_incluso_fantasma` do ticket 07 mais o hint de regeneração
   `_EXTRA_INCLUSO`, que carrega essa frase por extenso e vale para **qualquer** modelo sem a linha
   "Inclusos", inclusive a de cardápio só com extras pagos, que não recebe a tag). O `<fora_do_
   cardapio>` **não foi tocado** — ver a contabilidade abaixo.
5. **Sem migration.** A condição é estática da modelo, sai do CADASTRO que o BP_MODELO já lê: não é
   flag A2 materializada (nem coluna, nem detector em `_disciplina.py`, nem gancho no write-time).
6. **Doc:** `agente/CLAUDE.md`, "Flags determinísticas (padrão A2)", ganhou `<sem_fetiches>` como
   quarta instância da variante derivada do cardápio. E o comentário-cabeçalho do
   `bolhas_incluso_fantasma` (`nos/output_guard.py`), que citava o clause removido do
   `<apresentacao>`, foi atualizado — passou a citar a tag e a registrar explicitamente que o guard
   é quem cobre o cardápio **só de extras pagos** (tem lista, não tem linha "Inclusos", não recebe
   tag). Sem isso a citação viraria drift mudo.
7. **Testes** (sem DB, sem crédito):
   - `tests/unit/test_sem_fetiches.py` (8) — a tag entra/não entra; o conteúdo dela (os quatro
     critérios, um a um); a cláusula da camisinha nos dois sites; e a derivação contra as MESMAS
     linhas que o BP_MODELO renderiza (vazio → tag **e** `(sem fetiches cadastrados)`; só incluso /
     só ato pago / só por-pessoa → sem tag).
   - `tests/unit/test_cenarios_e2e_checks.py` (3) — as duas respostas de cada checker novo sobre
     transcritos sintéticos, com os falsos-positivos que eles têm de recusar (recusa que **cotou**,
     recusa que **levou o encontro**, incluso legítimo do programa "O completo tem anal incluso").
   - `tests/unit/test_sem_menage.py` / `test_sem_video_chamada.py`: só o desempacotamento da tupla
     de `_carregar_bp3`, que ganhou um campo.

### Roteiro e2e novo

`fora_do_cardapio_sem_fetiches` (`evals/e2e/cenarios.py`, 21º cenário) + 3 checkers em
`evals/e2e/massa.py`. É o primeiro cenário a exercitar o `<fora_do_cardapio>` — a auditoria já
registrava "sem gate" para esse bloco (eixo A, A2.7). A modelo é a `_modelo(["interno"])` **sem** a
chave `fetiches`: o `harness._seed_fetiche` só roda com a chave presente, então o bloco sai
`(sem fetiches cadastrados)` — o mesmo cadastro que produziu o "incluso fantasma" na corrida de
30/07. Roteiro: pede o ato → pergunta se o sem camisinha "tá incluso" → oferece 2000 → oferece 3000.

- `recusou_o_ato_ok` — recusa aberta no turno do pedido, **sem número** e sem a recusa larga que
  derruba o encontro (regex estreito: só casa "não vou te atender", "não faço nada/programa",
  "melhor deixar pra outra", nunca o "Não faço amor" correto).
- `camisinha_direta_ok` — a afirmação direta no turno + **nenhuma** bolha da corrida com incluso
  fantasma. O segundo lado reusa `bolhas_incluso_fantasma(texto, set())` do próprio output_guard,
  em vez de um regex novo: é literalmente a mesma regra, medida no resultado final.
- `nao_precificou_ok` — o turno que responde à oferta de dinheiro não devolve número nenhum.
- `tool_esperada="escalar"` fecha o outro lado do critério 4.

**Não estendi um cenário existente** (a orientação era preferir estender): `escalar` pausa a IA e o
`rodar_e2e` **para** no `pausou_handoff`, então esta sonda só funciona no fim do roteiro e mataria a
cauda de qualquer cenário em que fosse enxertada — no `video_chamada_sem_programa`, que tem o mesmo
cadastro, os checks da issue 12 passariam a depender de a escalada não ter acontecido antes.

### Contabilidade de chars (e por que o `<fora_do_cardapio>` não encolheu)

- **BP_GERAL: −73** (`regras.md.j2` 54.570 → 54.497; −86 no `<apresentacao>`, +13 no
  `<instrucoes_meta>`). Cauda: **+951**, e só para a modelo com o bloco vazio (0 char para as
  outras).
- **A auditoria já previa isto.** A Etapa 5.1/5.2 traziam número de chars (−2.174, −650); a linha
  **5.3** desta família traz `(casa com 2.2)` — ou seja, os chars deste corte foram contabilizados
  no ticket 07, e o que sobrava aqui era o mecanismo: "o guard da etapa 2 é a metade determinística
  disto". Não há um −2.539 escondido.
- **Por quê:** ao contrário do `<menage>` e da vídeo chamada, o `<fora_do_cardapio>` não tinha um
  *gate em prosa* a substituir. A mecânica de três vias ("com preço é extra que você cota; NA LISTA
  sem preço está incluso; fora da lista não existe por dinheiro nenhum") e a proibição do incluso
  nominal são **load-bearing para toda modelo que TEM lista** — tirá-las do prefixo byte-idêntico
  não é condicionar, é apagar. O que a tag faz é entregar o colapso já resolvido para quem não tem
  lista, em vez de a IA ter de derivá-lo de um bloco vazio a cada turno, que é exatamente onde ela
  falhou em prod.
- Rotas que chegariam mais fundo, **nenhuma delas deste ticket**: (a) **A2.7** do eixo A (a regra
  "a recusa cobre exatamente o item pedido" dita três vezes seguidas, −74 chars) — cabe no critério
  2 deste ticket e agora **tem gate** (`recusou_o_ato_ok`), mas é item de eixo sem ticket próprio e
  eu não o assumi; (b) `<cotacao>` "Extra/fetiche pago se cota do MESMO jeito…" (~430 chars) é
  igualmente morto para o bloco vazio e igualmente load-bearing para quem tem extras pagos — mesma
  parede.

### Achados laterais (não corrigidos, fora do escopo)

- **O cardápio só de extras PAGOS não recebe a tag e perdeu uma linha de prosa.** O corte do
  `<apresentacao>` era gatado por "não ter linha *Inclusos*"; a tag é gatada por "não ter fetiche
  nenhum" — o primeiro conjunto é maior. A modelo que tem só extras pagos (é o cadastro do cenário
  `menage_sem_secao`) fica sem essa meia-frase e coberta só pelo guard + pelo hint de regeneração.
  Foi escolha consciente: a alternativa era um segundo booleano `sem_inclusos` para 86 chars, e o
  guard já é fail-closed para esse caso (`conjunto vazio NÃO desliga o detector`, ticket 07).
- **`<sem_fetiches>` e `<sem_menage>` renderizam juntos** para a modelo de bloco vazio (sem
  fetiche ⇒ sem seção "Por pessoa"). As duas dizem "pedido fora do cardápio", mas sobre pedidos
  diferentes (ato × segunda pessoa) e cada uma com a sua saída. Não fundi: são condições distintas
  e a fusão só valeria se uma implicasse a outra nos dois sentidos.
- **`<girias_do_cliente>`** repete o gate por item ("só existem se estiverem no seu `<fetiches>`")
  em três bullets. São ecos do canônico e o `agente/CLAUDE.md` proíbe cortá-los por serem eco;
  ficam.

### Verificação

`make lint` ✅ · `make typecheck` ✅ · `make test` ✅ (**1867 passed, 239 skipped, +11** — `needs_db`
não rodou: o `DATABASE_URL` local aponta para prod, §0). `tests/agente/test_bp3_render.py` verde: o
BP_GERAL segue byte-idêntico entre modelos, e o que entrou é cauda.

### Gates pagos pendentes (NÃO rodados — §0, só o humano autoriza)

Critério 5, e a única forma de medir a conduta dos critérios 1–4 ao vivo:

```
cd api && make gate-conduta          # (real exige E2E_AUTORIZADO=1 + TEST_DATABASE_URL)
```

Roda o perfil `MODELO_SINTETICA` (`evals/e2e/perfil.py`), que é **exatamente** a modelo sem fetiches
deste ticket — é onde a tag passa a renderizar. Comparação contra o baseline de 01;
referência da última corrida aprovada: `.scratch/prompt-refactor/checkpoint-lote-03-08.md`, 2ª
corrida, commit `5ba74ac` (APROVADO, `empurrao_pct 0,0%`, `violacoes_duras 0`). Esperado:
`agente_output_incluso_fantasma_total` não subir e nenhuma violação dura nova.

E o roteiro novo:

```
E2E_AUTORIZADO=1 TEST_DATABASE_URL=… uv run python -m evals.e2e.massa --k 1
```

Ler `fora_do_cardapio_sem_fetiches.{recusou_o_ato_ok, camisinha_direta_ok, nao_precificou_ok,
tool_esperada_ok}` e conferir que os 20 cenários anteriores não regrediram. O runner não filtra por
cenário: a corrida cobre a massa inteira. ⚠️ Diferente dos tickets 11/12, este roteiro **não rodou
contra a conduta antiga** — foi criado junto com a mudança, então a primeira corrida é ao mesmo
tempo o baseline e o gate; uma falha ali precisa ser lida com essa ressalva.
