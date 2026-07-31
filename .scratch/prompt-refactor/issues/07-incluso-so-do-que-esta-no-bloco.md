# 07 — A IA para de declarar incluso um serviço que a modelo não tem

**What to build:** é a única falha desta auditoria com dano medido em trace. Com a modelo sem nenhum fetiche cadastrado, a IA disse que beijo na boca e oral sem camisinha estão inclusos — copiando palavra por palavra a fala de um exemplo da própria conduta. Três cláusulas proibiam exatamente isso e todas perderam para o exemplo concreto.

Duas metades, e as duas neste ticket porque juntas é que entregam o comportamento:
1. a fala ilustrativa dos exemplos deixa de ser um item de cardápio plausível — o problema não é ser exemplo, é ser um item que existe no catálogo real e passa por cotação válida. A forma da fala se mantém; a cópia utilizável sai.
2. um guard de saída, na família dos que já existem para sonda e região: declarar item incluso sem que ele esteja nominalmente na linha "Inclusos" do bloco da modelo é fail. É o padrão que o repo já usa quando a prosa falha.

**Blocked by:** 01

**Status:** resolved

- [x] modelo sem linha "Inclusos" recebe apresentação só com estilo, sem lista de incluso
- [x] modelo com linha "Inclusos" continua apresentando os itens dela, nominalmente
- [x] o guard reprova a bolha que declara incluso um item ausente do bloco, e a resposta é recomposta
- [x] o exemplo da conduta não contém mais uma fala de incluso copiável como cotação válida
- [x] o cenário que reproduz a falha de hoje passa a falhar antes do envio, não depois

---

Diagnóstico de origem: `.scratch/prompt-refactor/auditoria-carga-instrucional.md` (com os anexos `inventario-turno.md` e `eixo-*.md`, que trazem as linhas citadas).

> Os anexos citam número de linha; este ticket cita bloco/tag de propósito — os números do `regras.md.j2` envelheceram em 40 min durante a própria auditoria.

---

## Comments

**Metade 1 — a fala ilustrativa (4 sites, não 2).** A fala trocada é
`Beijo na boca (e|,) oral sem camisinha tá incluso` → `Beijo no pescoço (e|,) carinho sem pressa tá
incluso`. Os itens novos são concretos e em voz (a forma da fala não mudou), mas nenhum dos dois é
item de catálogo: não passa por cotação válida nem por extra pago, e copiado por quem tem o bloco
vazio não é promessa de serviço. Sites tocados — todos no BP_GERAL, nada por-modelo:

- `regras.md.j2` `<apresentacao>` (o parêntese das 3 bolhas);
- `regras.md.j2` preâmbulo de `<exemplos>` (que NOMEIA os itens ilustrativos — ficaria mentindo);
- `regras.md.j2` `<exemplo classe="abertura + primeira cotação + apresentação">` (a bolha que vazou);
- `persona.md` `<armadilhas_de_voz>`, o par de apresentação — **quarto site, fora do escopo literal
  do 2.1**, mas é a MESMA string no mesmo prefixo cacheado: deixá-lo intacto manteria a cópia viva.
  Registrado como eco no `agente/CLAUDE.md` (bullet novo, ao lado do de números).

Não tocado de propósito: `<apresentacao>` "Beijo na boca e oral tá incluso amor", `<girias_do_
cliente>` "o oral sem já vem junto rs" e `<fora_do_cardapio>` "Mas oral sem tá incluso rs`" — são
falas de SUBSTITUIÇÃO dentro da prosa da regra (a auditoria lista `:246` como intocável, e o
incidente #36 é sobre proibir sem dar fala substituta). Pressão de cópia menor que a do `<exemplo>`,
e agora coberta pelo guard. O 2.3 (tirar a duplicação de `:48`) NÃO foi feito — é o ticket 18.

**Metade 2 — `bolhas_incluso_fantasma`, família da `sonda`/`regiao`.** `nos/output_guard.py`:
detector puro + `_inclusos_da_modelo` (lê `modelo_fetiches` com `preco IS NULL`, na conexão que o
guard já abre) + gatilho `incluso` no gate → regenera 1x, dropa só a bolha ofensora se persistir,
**nunca handoff**. Métrica `agente_output_incluso_fantasma_total{acao}`.

Ao contrário do eco de região, **conjunto vazio NÃO desliga o detector** — é justamente o caso
medido: sem linha "Inclusos", nenhum item pode ser declarado incluso.

Quatro camadas contra falso-positivo (a rede reprova demais é pior que a falha):
1. só as formas de DECLARAR (`tá incluso`, `já vem junto`); o verbo "inclui" fica de fora — é a fala
   legítima do programa ("o normal já inclui a penetração");
2. claim NEGADO não conta ("beijo na boca não tá incluso amor" é recusa correta);
3. `_TERMOS_NAO_FETICHE` — claim de PROGRAMA/valor/logística não sai da linha "Inclusos": "Tudo isso
   tá incluso no completo" (fala REAL do corpus de prod) e "O completo tem anal incluso amor" passam;
4. claim que não nomeia item ("Já vem junto sim amor") não dá para julgar — passa.

**Camisinha:** "Só faço com camisinha amor" não tem claim → passa (não é FP). E `camisinha` fica FORA
do vocabulário absolvedor mesmo vindo de "Oral sem camisinha", senão "camisinha tá incluso" passaria
em toda modelo que tem oral sem na linha. Limite conhecido e testado: UM token da linha absolve a
bolha (generoso de propósito, "oral sem" abrevia "oral sem camisinha") — então "beijo grego tá
incluso" pega carona no "beijo" de "beijo na boca". Fica para o judge.

**Falso-positivo medido, não estimado.** Rodei o detector sobre as **471 bolhas únicas da IA** nos
transcritos de eval (`evals/saidas/`, gitignored): **7 flagradas** com o bloco vazio, e as 7 são a
MESMA fala copiada do exemplo (variantes de pontuação/emoji); **0 flagradas** com a linha "Inclusos"
no bloco. Nenhuma fala legítima cai. As 7 variantes viraram asserção congelada.

**Testes** (`make test` verde, 1810 passed): `tests/agente/test_output_guard_incluso.py` (17 —
inclui a bolha exata do trace de hoje como regressão) e 2 casos de nó em
`tests/agente/test_output_guard_regen.py` (gatilho `incluso` → regen limpou / persistiu → drop).
`make lint` e `make typecheck` verdes. Nenhuma migration: o guard lê tabelas que já existem.

**Gate pago NÃO rodado** (§0 — só o humano autoriza): `cd api && make gate-conduta` (real exige
`E2E_AUTORIZADO=1` + `TEST_DATABASE_URL`; `ARGS="--fake"` valida encanamento sem crédito),
com o perfil `MODELO_SINTETICA` (`evals/e2e/perfil.py`), que é a modelo sem fetiches que reproduziu
a falha. É o que fecha o critério 5 ponta a ponta e mede se a troca da fala mudou a taxa de cópia;
esperado: `agente_output_incluso_fantasma_total` sai de 0 e a bolha não chega ao transcrito.

**Sem gate para o critério 2 nos evals:** o `MODELO_SINTETICA` não tem fetiche nenhum, então nenhum
cenário e2e exercita a modelo COM linha "Inclusos" — essa metade está coberta só por unit test.
Se quiser gate vivo, o perfil precisa de um `fetiches` no spec do harness.

**Fechamento parcial (driver, 2026-07-30).** Diff conferido nas duas metades.

Metade 1: a fala ilustrativa foi trocada nos **4 sites** (`<apresentacao>`, preâmbulo de
`<exemplos>`, o `<exemplo>` de abertura+cotação+apresentação e o par de `<armadilhas_de_voz>` do
`persona.md`); grep confirma que não sobrou nenhuma ocorrência de "beijo na boca e oral sem
camisinha" como fala de incluso. A cláusula **intocável** da camisinha (`<fora_do_cardapio>`,
"recusa absoluta do sem camisinha", "nunca 'faço sim' nem 'tudo incluso'") está de pé. O eco novo
item↔fala foi registrado no `agente/CLAUDE.md`, ao lado do eco dos números — correto: sem isso o
próximo a mexer num dos 4 sites não saberia dos outros 3.

Metade 2: guard `bolhas_incluso_fantasma`, família da `sonda`/`regiao`, com 4 camadas
anti-falso-positivo e falso-positivo **medido** (471 bolhas reais dos transcritos: 7 flagradas,
todas a mesma cópia do exemplo; 0 com a linha "Inclusos" presente).

`make lint` ✅ · `make typecheck` ✅ · `make test` ✅ (1810 passed, +19).

Critérios 1–5 cumpridos no que é verificável offline. **Pendente do checkpoint**: a corrida do
`conduta_gate` fecha o critério 5 ponta a ponta e mede se a troca da fala derrubou a taxa de cópia
(esperado: `agente_output_incluso_fantasma_total` sai de 0 e a bolha não chega ao transcrito).

Duas observações que ficam registradas:

1. **Buraco de cobertura**: nenhum cenário e2e roda modelo **com** linha "Inclusos" —
   `MODELO_SINTETICA` não tem fetiche. O critério 2 está coberto só por unit test. Gate vivo
   exigiria um `fetiches` no spec do perfil; é candidato a ticket próprio.
2. `_inclusos_da_modelo` roda **uma query por turno**, incondicionalmente, dentro da conexão que o
   guard já abre — mesmo padrão do `_lugares_permitidos`, que já existia. Consistente com o repo,
   não é regressão, mas fica anotado.

**Fechado no checkpoint (driver, 2026-07-30).** O `conduta_gate` rodou contra o baseline `dd4a7e9`
e voltou **APROVADO** (`empurrao_pct 0,0%`, `violacoes_duras 0`), com o lote melhorando condução
(`conduziu decidido_rapido` 0% → 50%), desfecho (`bate_desfecho_real` 83,3% → 91,7%) e forma
(`fluxo_jsd` 0,1985 → 0,1896). Números e a comparação das duas corridas em
`.scratch/prompt-refactor/checkpoint-lote-03-08.md`. `Status: resolved`.
