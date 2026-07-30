# 11 — Menage deixa de ocupar o prompt de quem não oferece menage

**What to build:** o bloco de menage inteiro depende de a modelo ter a seção "Por pessoa" no cardápio. O gate está escrito em prosa, então toda modelo que não tem a seção lê e descarta o bloco em cada turno — é o maior pedaço de conduta inaplicável por cadastro do prompt.

O caminho é o que já funcionou para período longo: a condição vira tag na cauda (que aparece só para quem não oferece) e a prosa no prompt geral encolhe para uma linha. É o padrão que acertou 9 em 9 onde três reformulações de prosa haviam falhado.

Vai junto uma redundância do próprio bloco: a regra recota o dobro do pacote duas linhas depois de já tê-lo definido.

**Atenção:** nenhum eval hoje exercita menage. O roteiro faz parte deste ticket e tem que existir e passar **antes** da mudança, senão não há como saber que ela não regrediu.

**Blocked by:** 01

**Status:** claimed

- [x] roteiro novo cobre modelo COM e modelo SEM a seção "Por pessoa", e passa contra a conduta atual antes de qualquer edição
- [x] modelo sem a seção recusa menage como qualquer pedido fora do cardápio, sem cotar, sem dobrar e sem prometer amiga
- [x] modelo com a seção continua cobrando por duas pessoas, dobrando o pacote, e espelhando quem ele disse que vem
- [x] o pedido para ela trazer uma amiga continua escalando em vez de fechar sozinha
- [ ] roteiro verde depois da mudança — **gate pago, pendente de autorização** (comando no `## Comments`)

---

Diagnóstico de origem: `.scratch/prompt-refactor/auditoria-carga-instrucional.md` (com os anexos `inventario-turno.md` e `eixo-*.md`, que trazem as linhas citadas).

> Os anexos citam número de linha; este ticket cita bloco/tag de propósito — os números do `regras.md.j2` envelheceram em 40 min durante a própria auditoria.

---

## Comments

### O que foi feito

1. **O gate virou dado.** `_carregar_bp3` (`nos/prepare_context.py`) já lia as linhas de fetiche da
   modelo para montar o `<fetiches>` do BP_MODELO; agora deriva delas o `sem_menage` — espelhando
   *exatamente* o filtro `por_pessoa` do `fetiches.md.j2` (`preco` truthy **e** `cobra_por_pessoa`
   truthy). Sem query nova, mesmo caminho do `tabela_max_horas`. Campo novo no `ContextoDoTurno`,
   passado por kwarg por `_anexar_contexto_dinamico` → `_resolver_variaveis`.
2. **Tag na cauda `<sem_menage>`** (`contexto_dinamico.md.j2`, logo depois do `<sem_periodo_longo>`):
   sai **só** para quem não tem a seção, e carrega os quatro lados que a prosa carregava — não
   existe no cardápio, recusa aberta ("Não faço amor"), sem cotar/dobrar, sem prometer nem oferecer
   amiga — mais a fala de substituição (o encontro com ela segue de pé, `<fora_do_cardapio>`), que é
   a lição do incidente #36: proibir sem dar saída foi o que criou o bug. Declarada na lista de
   blocos internos do `regras.md.j2` (a mesma linha que declara `<sem_periodo_longo>`).
3. **BP_GERAL:** o 1º parágrafo do `<menage>` (o gate em prosa) sumiu; a condição virou meia oração
   na linha de abertura do bloco, que passou a ser a primeira linha dele. **Redundância interna
   (eixo A, A1.2):** o 1º bullet recotava o dobro que a abertura define duas linhas acima → virou
   "cobra dobrado como acima". Nada mais do bloco foi tocado.
4. **Teste:** `tests/unit/test_sem_menage.py` — a tag entra/não entra, e a derivação bate com o
   `<fetiches>` que a MESMA lista renderiza nos quatro cadastros (por-pessoa pago, só ato,
   por-pessoa *incluso*, cardápio vazio). Sem DB, sem crédito.

### Contabilidade de chars (o −2.174 do plano não é alcançável sob os critérios deste ticket)

- **BP_GERAL: 67.229 → 66.954 chars (−275).** Cauda: **+538**, e só para a modelo **sem** a seção
  (0 char para quem tem).
- O `−2.174` da Etapa 5.1 da auditoria é o bloco `<menage>` **inteiro menos o gate** — ou seja,
  supõe que a conduta POSITIVA também saia do BP_GERAL. Ela não pode sair sem violar os critérios
  de aceite 3 e 4 deste ticket: "espelhe quem ELE disse que vem, sem chamar de casal", o
  não-cadastro da segunda pessoa, a fala do ramo da amiga e a resposta de discrição ("Só eu e você",
  canônica e cross-referenciada pelo `<fora_do_cardapio>`) não existem em nenhum outro site. O que
  de fato duplica o BP_MODELO é só o regime de preço (o `<fetiches>` da modelo já imprime "Por
  pessoa — são 2 pessoas, DOBRA o pacote" **com a tabela do dobro pronta**) — e o eixo A declarou
  essa linha canônica e mandou manter.
- As duas saídas para chegar perto do −2.174, **nenhuma delas deste ticket**:
  - **(5.1b)** mover o parágrafo da **oferta pós-venda da amiga** (~330 chars) para a cauda, gatado
    por (tem a seção ∧ venda fechada ∧ `amiga_ofertada_em` nulo). É a aplicação mais fiel do padrão
    — a tag apareceria só nos turnos em que a oferta é acionável, e já existe a irmã dela
    (`<ja_ofereceu_a_amiga>`) para o estado "depois". Não fiz: muda QUANDO a IA vê a oferta, e não
    há gate barato para isso.
  - **(5.1c)** mover o `<menage>` inteiro para a cauda em duas tags mutuamente exclusivas. Corta os
    2.133 do prefixo, mas põe ~2.1k chars de playbook estático na cauda volátil de toda modelo que
    **tem** a seção, todo turno — o oposto do que faz a cauda funcionar (blocos pequenos e
    aplicáveis AGORA). Precisa de decisão, não de implementação.

### Achado lateral (não corrigido, fora do escopo)

A resposta de **discrição** ("você atende sozinha?" → "Só eu e você amor") mora dentro do `<menage>`
e, portanto, sempre esteve gatada pelo cadastro — mas é pergunta de SEGURANÇA que qualquer cliente
faz a qualquer modelo, e o `<fora_do_cardapio>` a cita como canônica sem gate nenhum. Hoje a modelo
sem a seção "Por pessoa" recebe a proibição ("Só eu amor" seco fecha a porta) sem a fala que a
substitui. O `<sem_menage>` **preserva** esse comportamento de propósito (não regride nem conserta);
o conserto é tirar essa meia-oração do `<menage>` e levá-la ao `<fora_do_cardapio>`.

### Verificação

`make lint` ✅ · `make typecheck` ✅ · `make test` ✅ (1838 passed, 239 skipped — `needs_db` não
rodou: o `DATABASE_URL` local aponta para prod, §0).

**Gate pago pendente** (não rodei — §0): `E2E_AUTORIZADO=1 TEST_DATABASE_URL=… uv run python -m
evals.e2e.massa --k 1`, e ler `menage_com_secao.dobrou_o_pacote_ok` + `menage_sem_secao.
recusou_menage_ok` (os mesmos dois que passaram contra a prosa de hoje na corrida do ticket 23). O
runner não filtra por cenário: a corrida cobre a massa inteira.

**Fechamento parcial (driver, 2026-07-30).** Diff conferido. A condição por-modelo foi para a
**cauda** (`<sem_menage>`, ao lado do `<sem_periodo_longo>` que serviu de gabarito), derivada do
mesmo filtro que o `fetiches.md.j2` usa — **sem query nova**, no mesmo caminho do `tabela_max_horas`.
`test_bp3_render.py` verde: o BP_GERAL segue byte-idêntico entre modelos.

`make lint` ✅ · `make typecheck` ✅ · `make test` ✅ (1838 passed, +6).

**O delta ficou muito abaixo do plano, e a explicação é boa.** −275 chars no BP_GERAL (67.229 →
66.954), +538 na cauda só de quem **não** tem a seção. O plano previa −2.174.

A diferença não é execução incompleta: o número do plano supunha que a **conduta positiva** de
menage também saísse do BP_GERAL, e ela não sai sem violar os critérios 3 e 4 deste próprio ticket.
"Espelhe quem ELE disse que vem, sem chamar de casal", o não-cadastro da segunda pessoa, a fala do
ramo da amiga e a resposta de discrição ("Só eu e você") **não existem em nenhum outro site** — e o
eixo A declarou a linha do regime de preço canônica, mandando mantê-la. O que duplicava o BP_MODELO
era só o gate, e é o gate que saiu.

Consequência para o veredito quantitativo da auditoria: o teto de ~7.400 chars da §4 está
superestimado ao menos nesta linha. As duas rotas que chegariam perto ficaram registradas pelo
subagente (5.1b: oferta pós-venda da amiga → cauda gatada; 5.1c: bloco inteiro → cauda em duas
tags, ~2,1k estáticos na cauda volátil de quem TEM a seção) — as duas pedem decisão, não
implementação.

**Pendente**: a corrida do `evals.e2e.massa` relendo `menage_com_secao.dobrou_o_pacote_ok` e
`menage_sem_secao.recusou_menage_ok` — os dois passaram hoje contra a prosa, e é isso que o corte
tem que preservar.
