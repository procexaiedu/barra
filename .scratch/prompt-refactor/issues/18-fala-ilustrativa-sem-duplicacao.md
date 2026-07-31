# 18 — A fala ilustrativa do incluso fica em um lugar só

**What to build:** a mesma fala de apresentação com item incluso aparece duas vezes — inline na conduta e de novo no exemplo — dobrando a pressão de cópia sobre a string que vazou em prod. Depois de as duas redes do 07 e do 15 estarem verdes, uma das cópias sai.

Vem por último de propósito: enquanto as redes não existirem, a duplicação é reforço, e tirar reforço antes da rede é o erro que o `agente/CLAUDE.md` avisa (dedup não é deleção grátis).

**Blocked by:** 07, 15

**Status:** claimed

- [x] a apresentação continua saindo com estilo + incluso, montada do bloco da modelo — a prescrição (o quê, em quantas bolhas, na ordem dela) e o gate por item ficaram no `<apresentacao>`; só o molde concreto saiu, e ele continua no `<exemplo>`
- [x] modelo sem linha "Inclusos" continua sem lista de incluso — as duas redes conferidas com os próprios olhos (ver `## Comments`), e nenhuma delas dependia da cópia retirada
- [ ] o cenário que reproduziu a falha original continua verde — `fora_do_cardapio_sem_fetiches` identificado e conferido (segue cobrindo; nada mudou nele nem no checker), mas a corrida é **gate pago, pendente de autorização**
- [ ] `conduta_gate` verde contra o baseline de 01 — **gate pago, pendente de autorização** (comando no `## Comments`)

---

Diagnóstico de origem: `.scratch/prompt-refactor/auditoria-carga-instrucional.md` (com os anexos `inventario-turno.md` e `eixo-*.md`, que trazem as linhas citadas).

> Os anexos citam número de linha; este ticket cita bloco/tag de propósito — os números do `regras.md.j2` envelheceram em 40 min durante a própria auditoria.

---

## Comments

### As duas redes, conferidas antes de apagar

O ticket só é seguro se o 07 e o 15 pegarem o caso. Não aceitei os `## Comments` deles como prova —
rodei o detector e li os dois sites:

- **`bolhas_incluso_fantasma`** (`nos/output_guard.py`, gatilho `incluso` no gate; regenera 1x,
  dropa a bolha ofensora, nunca handoff). Com o conjunto de inclusos **vazio** ele reprova tanto a
  fala que vazou em prod ("Beijo na boca e oral sem camisinha já vem junto 🥰") quanto a fala
  ilustrativa **atual** do `<exemplo>` ("Beijo no pescoço e carinho sem pressa tá incluso amor") —
  ou seja: se o chat copiar o molde que SOBREVIVEU, o guard pega. Com a linha "Inclusos" preenchida
  as duas passam, e "O completo tem anal incluso amor" / "Só faço com camisinha amor" passam nos
  dois cadastros (as camadas anti-FP do 07 seguram).
- **`<sem_fetiches>`** (`contexto_dinamico.md.j2`, cauda, só para o `<fetiches>` inteiro vazio):
  diz por escrito o que o corte poderia levar — `"tá incluso"/"já vem junto"` não sai sobre ato
  nenhum, *nem copiado de um exemplo desta conduta*, e **a apresentação fica só no estilo ("Sou bem
  tranquila" / "Estilo namoradinha"), sem lista de incluso**. Isto é o critério 2 dito como dado, no
  ponto de maior autoridade posicional, para exatamente a modelo do incidente.

### Achado que decidiu QUAL cópia sai (e não estava no ticket)

O guard só enxerga quem **DECLARA** incluso (`tá incluso`, `já vem junto`, `incluído`). Medido:

| fala | é claim? | `bolhas_incluso_fantasma(…, set())` |
|---|---|---|
| `Beijo no pescoço e carinho sem pressa tá incluso amor` (a do `<exemplo>`) | sim | **pega** |
| `Beijo no pescoço, carinho sem pressa 🥰` (a inline do `<apresentacao>`) | não | **não pega** |

A cópia inline era uma **lista de itens sem verbo** — a única das duas formas que a rede não vê.
Cortar essa é o lado seguro: some a cópia sem rede, fica a cópia com rede. (Se o ticket tivesse
mandado cortar a do `<exemplo>`, o resultado seria o inverso e eu teria voltado `needs-triage`.)

### O que mudou (bloco/tag, nunca linha)

1. **`regras.md.j2` `<apresentacao>`, 1º parágrafo** — o parêntese com as 3 bolhas-molde saiu e
   virou ponteiro, como o `eixo-a` A2.8 prescreveu:
   - antes: `… em 2-3 bolhas curtas, na sua ordem ("Sou bem tranquila" / "Estilo namoradinha" /
     "Beijo no pescoço, carinho sem pressa 🥰"). Os itens dessa terceira bolha são ILUSTRATIVOS: …`
   - depois: `… em 2-3 bolhas curtas, na sua ordem — o molde é o <exemplo> de apresentação. Os itens
     que ele cita são ILUSTRATIVOS: os SEUS saem nominalmente da linha "Inclusos" do seu <fetiches>.`

   O antecedente do "Os itens" foi religado ao `<exemplo>` (senão apontava para um parêntese que não
   existe mais). **BP_GERAL: −56 chars** (`regras.md.j2` 53.076 → 53.020 chars). Nada por-modelo e
   nada por-turno entrou; zero variável Jinja nova.
2. **`agente/CLAUDE.md`, eco "Item de cardápio em exemplo de fala"** — o eco deixa de ter 4 sites e
   passa a ter 3 (preâmbulo de `<exemplos>`, o `<exemplo>` e o par de `persona.md`
   `<armadilhas_de_voz>`); o 4º fica registrado como **retirado em 31/07 por este ticket**, com o
   motivo (as duas redes) e o achado da tabela acima — "o molde sem verbo não tem rede", que é o que
   o próximo a reintroduzir fala ilustrativa em bloco de regra precisa saber. Sem essa atualização,
   quem lesse "troque nos quatro" iria procurar no `<apresentacao>` e não acharia: drift mudo.
3. **`tests/unit/test_fala_ilustrativa_do_incluso.py`** (4, sem DB e sem crédito) — lê o BP_GERAL
   pelo caminho real (`render_prefixo_geral`): o `<apresentacao>` não tem mais a fala e aponta para
   o `<exemplo>`; a prescrição e o gate por item continuam lá; o molde existe **uma vez só** no
   prefixo; e a assimetria da tabela (a que ficou tem rede, a que saiu não tinha) fica congelada —
   é ela que licencia a deleção, e sem teste ela se perde.

### Sites conferidos e NÃO tocados

- **`persona.md` `<armadilhas_de_voz>`, o par de apresentação** — carrega quase a mesma fala
  ("… tá incluso 🥰") e continua no BP_GERAL. Não cortei: é um par `<errado>/<certo>`, e o `<porque>`
  dele é "apresentação é estilo + **o que está incluso**, sem número" — um `<certo>` sem a bolha de
  incluso deixaria de ilustrar o que o par ensina. Consequência honesta: **"em um lugar só" vale
  para `regras.md.j2`** (regra × exemplo, que era o alvo do A2.8 e o único n-grama repetido entre os
  dois); no prefixo inteiro sobram 2 falas + o preâmbulo que nomeia os itens. Essa cópia declara
  incluso, então tem rede.
- **`<apresentacao>`, 3º parágrafo** ("Programa se descreve pelo que ELE INCLUI… 'Beijo na boca e
  oral tá incluso amor'") — fala de **substituição** dentro da prosa da regra, explicitamente
  preservada pelo 07 (incidente #36: não proibir sem dar fala substituta). Fora do escopo.
- **`<fora_do_cardapio>`** (a cláusula da camisinha e a mecânica de três vias) e a tag
  `<sem_fetiches>` — intocados; são a rede, não o alvo.
- **`evals/e2e/cenarios.py` / `massa.py`** — nenhum cenário novo, como orientado. Os 21 seguem 21.

### Cenário que reproduz a falha (critério 3)

`fora_do_cardapio_sem_fetiches` (21º cenário, criado no 15) + `camisinha_direta_ok`
(`_camisinha_direta_sem_incluso`, `massa.py`), que roda `bolhas_incluso_fantasma(texto, set())`
sobre **todos** os turnos da corrida. Continua cobrindo sem alteração: o cadastro é o mesmo (modelo
sem a chave `fetiches` → `(sem fetiches cadastrados)`, o do incidente de 30/07) e o checker mede a
regra no resultado final. Se a mudança de prosa fizer o chat copiar o molde do `<exemplo>`, esse
checker reprova — é o detector vivo que o A2.8 pedia.

### Verificação (offline, meu)

`make lint` ✅ (ruff) · `make typecheck` ✅ (mypy, 142 arquivos) · `make test` ✅ — **1885 passed,
239 skipped, +4 meus**. `needs_db` não rodou: o `DATABASE_URL` do `.env` aponta para o self-hosted
de **produção** (§0); nada que mudei precisa de DB. `tests/agente/test_bp3_render.py` verde — o
BP_GERAL segue byte-idêntico entre modelos (a mudança é texto estático do prefixo).

### Gates pagos pendentes (NÃO rodados — §0, só o humano autoriza)

```
cd api && E2E_AUTORIZADO=1 TEST_DATABASE_URL=… make gate-conduta
cd api && E2E_AUTORIZADO=1 TEST_DATABASE_URL=… uv run python -m evals.e2e.massa --k 1
```

- O primeiro é o **critério 4**, contra o baseline de 01 (referência aprovada:
  `.scratch/prompt-refactor/checkpoint-lote-03-08.md`, 2ª corrida, commit `5ba74ac` — `empurrao_pct
  0,0%`, `violacoes_duras 0`). É também o único jeito de medir o **critério 1** ao vivo: a
  apresentação continuar saindo em 2-3 bolhas com estilo + incluso agora que o molde está 250 linhas
  abaixo, no `<exemplo>` — o risco declarado pelo A2.8 como **médio**. Esperado: sem violação dura
  nova e `agente_output_incluso_fantasma_total` sem subir.
- O segundo é o **critério 3**: ler `fora_do_cardapio_sem_fetiches.{camisinha_direta_ok,
  recusou_o_ato_ok, nao_precificou_ok, tool_esperada_ok}` e conferir que os outros 20 cenários não
  regrediram (o runner não filtra por cenário). Como no 15, esse roteiro nunca correu contra a
  conduta antiga — a primeira corrida é baseline e gate ao mesmo tempo.

### Achado adjacente, registrado e não corrigido

Confirmo o resíduo que o 17 deixou anotado, porque cruzei com ele: o `<porque>` do
`<exemplo classe="cotação com intenção de marcar já na mesa">` ainda diz que o turno "termina no
empurrão **sim/não**", rótulo que o `agente/CLAUDE.md` registra como retirado dos ecos em 30/07.
Resíduo do ticket 05; não mexi (§3, "mencione, não delete").

**Nada revertido do WIP do usuário** (nenhum dos arquivos que toquei estava sujo — conferido com
`git diff` antes de editar); nada commitado.
