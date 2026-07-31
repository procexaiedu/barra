# 09 — As tags de fase passam a ser todas endereçadas pela cauda

**What to build:** duas pontas soltas na estrutura do funil, e vale resolver juntas porque as duas mexem em quem nomeia as fases.

A tag da espera pela chegada do cliente foi superseded: a flag de disciplina que já existe carrega as mesmas falas e as mesmas proibições, e só aparece quando é aplicável. A tag na conduta não tem resíduo instrucional próprio, mas o texto do próximo-passo a cita — então tirar a tag sem ajustar o próximo-passo quebra o teste de contrato, e é assim que se sabe que não sobrou referência.

A tag da retomada depois do silêncio é endereçada por nada: nenhuma referência interna, nenhum ponteiro na cauda. Ela ganha endereço — ou um ponteiro no próximo-passo, ou é absorvida pela abertura como o caso "ele volta".

**Blocked by:** 01

**Status:** claimed

- [x] cliente que avisou que saiu e ainda não chegou continua recebendo presença curta, sem cobrança repetida
- [x] cliente que volta depois de silêncio é retomado do ponto exato, sem recumprimento e sem desconto de boas-vindas
- [x] o teste de contrato das variáveis de contexto passa, sem citar tag que não existe mais
- [ ] `make test` verde e `conduta_gate` contra o baseline de 01 — `make test` **verde** (1829 passed); `conduta_gate` **pendente** (pago, autorização do humano)

---

Diagnóstico de origem: `.scratch/prompt-refactor/auditoria-carga-instrucional.md` (com os anexos `inventario-turno.md` e `eixo-*.md`, que trazem as linhas citadas).

> Os anexos citam número de linha; este ticket cita bloco/tag de propósito — os números do `regras.md.j2` envelheceram em 40 min durante a própria auditoria.

---

## Comments

**Delta do BP_GERAL: −276 chars** (`regras.md.j2`, 53.411 → 53.135). Cauda: `Aguardando_confirmacao`
−5 chars, `Triagem`/`Qualificado` +60 chars cada (o ponteiro condicional) — cauda, não prefixo.

### Ponta 1 — `<enquanto_ele_nao_chega>` sai (superseded pela flag A2)

Confirmado no texto vivo **antes** de cortar, como manda o ticket. A tag dizia três coisas:

| o que a tag dizia | onde já estava |
|---|---|
| falas de presença: "Vou me arrumar rs", "Estou te esperando" | `<ja_pediu_a_foto_da_portaria>` (`contexto_dinamico.md.j2`), palavra por palavra |
| proibições: "Vai vir mesmo?", "chega em quanto tempo?" | idem, palavra por palavra — e a flag ainda acrescenta o caso "ele DISSE que chegou sem a imagem: peça de novo, uma vez" |
| "e já peça a foto da chegada (`<tipos_de_encontro>`)" | `<tipos_de_encontro>` já escreve por inteiro: "Ele avisou que saiu ('to indo') → siga normal, já pedindo a foto na chegada: 'Quando chegar me manda uma foto da portaria amor'" (+ o mesmo trilho na resposta a "to chegando, me passa o apartamento") |

Ou seja: **resíduo instrucional zero**. O terceiro item nunca foi conteúdo da tag — era um ponteiro
para `<tipos_de_encontro>`, e é esse ponteiro que foi realocado (abaixo). A cobertura temporal
também fecha: o pedido da foto liga `foto_portaria_pedida_em` no write-time
(`_disciplina.contem_pedido_da_foto_de_portaria` → `workers/envio.py`), no MESMO turno em que a IA
pede; do turno seguinte em diante a flag está de pé, e é exatamente aí que a espera acontece.
Risco residual honesto: se o detector errar a fala (regex), a conduta de espera fica sem site —
antes o BP_GERAL era a rede. É a mesma exposição que as outras flags A2 já aceitam.

`_PROXIMO_PASSO["Aguardando_confirmacao"]` passou a apontar `<fechamento>` e **`<tipos_de_encontro>`**
— a conduta desse estado (pedir a foto, Pix, horário) é logística, e é lá que ela mora; o próprio
`<fechamento>` já roteia pra lá ("daí em diante a logística segue o `<tipos_de_encontro>`"). É a
primeira vez que a cauda aponta para fora do `<conducao_da_venda>`; registrado no `agente/CLAUDE.md`
e no comentário do `_PROXIMO_PASSO`.

### Ponta 2 — endereço da `<retomada_pos_silencio>`: **ponteiro no próximo-passo** (opção 1)

Escolhida a opção 1 (ponteiro), **não** a fusão no `<abertura>`. Justificativa:

- Fundir no `<abertura>` daria à retomada o endereço ERRADO: `<abertura>` só é apontada em `Novo`,
  e o cliente que some e volta está quase sempre em `Triagem`/`Qualificado` (a perda típica é o
  silêncio pós-cotação). Também não devolveria chars — só moveria 847 de lugar.
- O ponteiro entrou **condicional**, na forma que o `Novo` já usava para a `<cotacao>`:
  "…; se ele sumiu e voltou agora, `<retomada_pos_silencio>` junto", em `Triagem` e `Qualificado`.
- Bônus estrutural: com a tag citada pelo `_PROXIMO_PASSO`, ela passa a ser amarrada pelo
  `test_contrato_variaveis_contexto.py` — o mesmo teste que provou que a tag removida não deixou
  referência órfã agora impede que a retomada volte a ficar órfã. Nenhum teste novo foi preciso.

**Alternativa avaliada e descartada:** pendurar o ponteiro na tag determinística
`<tempo_desde_ultima_msg_cliente>` da cauda (que o eixo-D sugere como candidata). Ela **não** mede
o silêncio: a fala do turno já está na janela quando o `prepare_context` roda, então
`min_desde_ultima_msg_cliente` é a latência de processamento (debounce + fila), não o tempo que ele
ficou sumido. Pendurar a retomada ali seria apontar a conduta pelo sinal errado. O sinal real de
sumiço que existe hoje é a marca de pausa da janela (`[pausa de Nh na conversa]`, ≥6h), que é
grosseira demais (a retomada vale bem antes de 6h) e vive na janela, não na cauda.

### O que NÃO foi feito

- Nenhuma injeção condicional por fase — a cauda continua apontando, nunca amputando (recusa 25/07).
- Nenhuma migration, nenhuma flag nova, nada por-modelo/por-turno no prefixo cacheado.
- `<recuo_pos_objecao>` segue endereçada só por cross-ref interna (`:93`/`:98`) — fora do escopo
  deste ticket, e o eixo-D recusa mexer sem falha colhida.

### Verificação

- `make lint` ✅ · `make typecheck` ✅ (142 arquivos) · `make test` ✅ **1829 passed, 239 skipped**
- `tests/unit/test_contrato_variaveis_contexto.py` ✅ 5 passed — tags citadas hoje:
  `abertura`, `apresentacao`, `cotacao`, `fechamento`, `retomada_pos_silencio`, `tipos_de_encontro`;
  órfãs: nenhuma.
- **Gate pago pendente (não rodado, exige autorização frase a frase):**
  `E2E_AUTORIZADO=1 make gate-conduta ARGS="--por-eixo 2 --max-turnos 12"` — mesmos parâmetros da
  referência (2ª corrida, `5ba74ac`: APROVADO, `empurrao_pct` 0,0%, `violacoes_duras` 0,
  `conduziu decidido_rapido` 50%, `bate_desfecho_real` 91,7%, `fluxo_jsd` 0,1896). Os eixos que
  interessam aqui: qualquer roteiro que chegue a `Aguardando_confirmacao` interno (prova a ponta 1)
  e o eixo que exercita repergunta/retomada (prova a ponta 2). Lembrando o diagnóstico do lote
  anterior: `violacoes_duras` pode subir por artefato de harness (o carimbo de `cotacao_apresentada`
  do `workers/envio.py` não roda no e2e) — antes de ler como regressão, cheque o transcrito.

**Fechamento parcial (driver, 2026-07-30).** Diff conferido nas duas pontas.

Ponta 1: a remoção do `<enquanto_ele_nao_chega>` foi precedida da checagem que o ticket exigia — a
flag A2 `<ja_pediu_a_foto_da_portaria>` carrega as mesmas duas falas e as mesmas duas proibições,
palavra por palavra, e ainda cobre o caso "ele disse que chegou sem a imagem". Grep confirma que não
sobrou referência órfã em `src/`, `tests/` ou `evals/`: as duas ocorrências restantes estão no
`agente/CLAUDE.md` e são **documentais**, registrando a remoção e o motivo. O `_PROXIMO_PASSO` foi
ajustado na mesma mudança, como a auditoria mandava.

Ponta 2: escolhida a opção do ponteiro no próximo-passo, não a fusão no `<abertura>` — e a
justificativa está certa: `<abertura>` só é apontada em `Novo`, e quem some e volta está em
`Triagem`/`Qualificado` (a perda típica é o silêncio pós-cotação). Efeito colateral bom: a tag
passa a ser amarrada pelo `test_contrato_variaveis_contexto.py`, sem teste novo.

**−276 chars no BP_GERAL** (`regras.md.j2` 53.411 → 53.135). O que cresceu foi cauda, não prefixo.

`make lint` ✅ · `make typecheck` ✅ · `make test` ✅ (1829 passed).

**Pendente**: a corrida do `conduta_gate` roda no próximo checkpoint, contra a referência `5ba74ac`.

Correção de uma nota do retorno do subagente: ele avisou que "o carimbo de `cotacao_apresentada` do
`workers/envio.py` não roda no harness e2e". Isso **deixou de ser verdade** — o ticket 22 (commit
`5ba74ac`) fez o harness aplicar o mesmo backstop. Se `violacoes_duras` subir no próximo gate, a
leitura de artefato não vale mais de graça.
