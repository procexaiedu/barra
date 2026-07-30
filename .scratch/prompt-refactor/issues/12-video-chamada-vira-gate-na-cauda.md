# 12 — Vídeo chamada deixa de ser negada em quatro lugares diferentes

**What to build:** a regra "a vídeo chamada só existe se estiver na sua tabela" está afirmada em quatro pontos da conduta, três deles como condicional negativa pendurada em outro assunto (prova de humanidade, mídia, pedido de conteúdo). Mesmo padrão do menage: o gate vira tag na cauda para quem não tem o programa, e a prosa fica em um site só.

O comportamento a preservar dos dois lados: quem não tem o programa nunca oferece chamada nenhuma, e o pedido de prova se resolve com foto; quem tem, cota a menor da tabela e o valor é adiantado.

**Atenção:** o cenário de eval que existe roda uma modelo **com** o programa. O ramo sem o programa precisa de roteiro novo, e ele é parte deste ticket.

**Blocked by:** 01

**Status:** claimed

- [x] roteiro novo cobre modelo sem vídeo chamada na tabela, e passa contra a conduta atual antes da edição — feito pelo **ticket 23** (`video_chamada_sem_programa`), verde na corrida real de 30/07 contra a prosa de hoje
- [x] modelo sem o programa recusa chamada e redireciona para foto, e não a oferece como saída em nenhum contexto — a tag `<sem_video_chamada>` cobre os quatro contextos por escrito; conduta pendente do gate pago
- [x] modelo com o programa continua cotando a menor da tabela, com o valor adiantado e comprovante só em imagem — a prosa positiva do `<tipos_de_encontro>` ficou intacta; o cadastro do cenário `remoto_videochamada` foi corrigido para de fato TER o programa
- [x] pedido de "chamada rapidinha de graça pra provar" continua não existindo nos dois casos — canônico intacto no ramo COM; a tag diz "de graça ou paga" no ramo SEM
- [ ] roteiros verdes depois da mudança — **gate pago, pendente de autorização** (comando no `## Comments`)

---

Diagnóstico de origem: `.scratch/prompt-refactor/auditoria-carga-instrucional.md` (com os anexos `inventario-turno.md` e `eixo-*.md`, que trazem as linhas citadas).

> Os anexos citam número de linha; este ticket cita bloco/tag de propósito — os números do `regras.md.j2` envelheceram em 40 min durante a própria auditoria.

---

## Comments

### O que foi feito

1. **O gate virou dado.** `_carregar_bp3` (`nos/prepare_context.py`) já lia as linhas de
   `modelo_programas` para montar o `<programas>` do BP_MODELO; agora deriva delas o
   `sem_video_chamada`, **sem query nova** — mesmo caminho do `tabela_max_horas` e do `sem_menage`
   (ticket 11). O gate do prompt sempre foi por NOME ("ela só existe se estiver nos seus
   `<programas>`", lido pelo próprio LLM na tabela), então a derivação é o mesmo julgamento sobre as
   mesmas linhas: `_e_video_chamada()` casa `"chamada"` no nome `normalizar()`ado — "Vídeo chamada",
   "Videochamada", "Chamada de vídeo", com ou sem acento/caixa. Campo novo no `ContextoDoTurno`
   (default conservador `False` = não injeta), passado por kwarg por `_anexar_contexto_dinamico` →
   `_resolver_variaveis`.
2. **Tag na cauda `<sem_video_chamada>`** (`contexto_dinamico.md.j2`, logo depois do
   `<sem_menage>`): sai **só** para quem não tem a linha, e carrega os quatro contextos que a prosa
   negava um a um — prova de humanidade, alternativa a nude/conteúdo, redirecionamento do book
   repetido, e a oferta em si — mais a **fala de substituição** ("Não faço chamada amor" + a prova é
   a FOTO + o encontro logo atrás), que é a lição do incidente #36. Declarada na lista de blocos
   internos do `regras.md.j2`, ao lado do `<sem_menage>`.
3. **BP_GERAL — os 4 sites do ticket + um 5º que o ticket não contava.** Todos são eco do MESMO
   gate, então todos foram tocados (agente/CLAUDE.md, "Regras com eco multi-site"):
   - `<tipos_de_encontro>`, parágrafo "Vídeo chamada" — **site canônico**: o ramo "NÃO estando lá…"
     inteiro saiu; sobrou meia oração de gate apontando a tag. **A conduta positiva ficou intacta**
     (programa ao vivo no horário combinado, valor adiantado por Pix no mesmo trilho do uber, chave
     é o sistema que manda, comprovante só em imagem, não liga na hora, "chamada rapidinha de graça"
     não existe, ofereça a menor da tabela — ADR-0021/0029). **−275**
   - `<midia>`, bullet do book repetido: "se ela estiver na sua tabela" saiu. **−30**
   - `<midia>`, pedido de conteúdo/nude: "; se não estiver, a recusa fica sozinha…" saiu. **−102**
   - `<protocolo_disclosure>`, pedido de ligação/vídeo de prova: o bifurcado "se você TEM… se não
     tem…" virou a afirmação positiva. **−115**
   - `<exemplo classe="pedido de prova de humanidade">`, o `<porque>`: o 5º eco ("Este diálogo
     PRESSUPÕE que ela está lá…") saiu. Não estava na conta do ticket, mas é o mesmo gate — e é o
     mais perigoso de deixar, porque a segunda bolha do exemplo é a fala proibida por extenso.
     Por isso a tag desmonta o exemplo **com as mesmas palavras** ("Podemos fazer uma vídeo chamada
     amor" não é fala sua): exemplo concreto já venceu prosa uma vez (corrida do `conduta_gate`
     30/07, o "incluso fantasma"). **−140**
   - `<instrucoes_meta>`, lista de blocos internos: **+21**
4. **Sem migration.** A condição sai do CADASTRO, não de evento da conversa — não é flag A2
   materializada: nada de coluna, detector ou gancho no write-time.
5. **Cadastro do cenário `remoto_videochamada` corrigido** (`evals/e2e/cenarios.py`). A auditoria o
   descrevia como "a modelo **com** o programa", mas a tabela dele era só `Encontro 1h/2h` — o gate
   em prosa deixava passar. Com o gate determinístico, esse cenário passaria a medir o ramo **SEM**
   (que já tem o seu, `video_chamada_sem_programa`) e falharia por artefato de cadastro. Agora a
   modelo tem `Vídeo chamada / 30 min / 300`, que é o que o cenário sempre quis testar — e é o que
   sustenta o critério de aceite 3.
6. **Doc:** `agente/CLAUDE.md`, seção das flags A2, ganhou a distinção entre a variante
   **materializada no write-time** (evento da conversa) e a **derivada do cardápio/BP_MODELO**
   (condição estática da modelo, resolvida no `prepare_context` do que já foi lido, sem coluna e sem
   detector), com as três instâncias: `<sem_periodo_longo>`, `<sem_menage>`, `<sem_video_chamada>`.
   Sem isso o próximo ticket dessa família (15) cria coluna à toa.
7. **Teste:** `tests/unit/test_sem_video_chamada.py` — a tag entra/não entra, o conteúdo dela (a
   recusa, a foto como saída, o desmonte do exemplo), a derivação a partir das linhas de programa
   (só `Encontro` → tag; com a linha da chamada → sem tag; cardápio vazio → tag) e as variantes de
   nome do cadastro. Sem DB, sem crédito.

### Contabilidade de chars

- **BP_GERAL: 66.954 → 66.313 (−641).** Cauda: **+568**, e só para a modelo **sem** o programa
  (0 char para quem tem).
- O plano tinha DOIS números para isto: **−149** (item 3.6 / eixo A1.9 — só as condicionais
  negativas de `<midia>` e `<protocolo_disclosure>`) e **−650** (item 5.2 — "vídeo chamada ausente
  de `<programas>`", os 4 sites). O entregue (−641) é o 5.2, praticamente cravado; supera o 3.6
  porque o ramo SEM do **canônico** e o caveat do `<exemplo>` saíram junto, e nenhum dos dois estava
  na conta estreita de A1.9.
- Diferente do ticket 11, aqui **não há discrepância a explicar**: a conduta positiva da vídeo
  chamada é curta e mora num site só, então o gate era quase tudo que dava para cortar.

### Achados laterais (não corrigidos, fora do escopo)

- **`<ja_enviou_book>`** (`contexto_dinamico.md.j2`) diz "redirecione pro encontro ou pra vídeo
  chamada paga", sem condição. É tag de CAUDA, não BP_GERAL, e o `<sem_video_chamada>` renderiza
  **depois** dela cobrindo exatamente esse caso ("nem quando ele repete o pedido de prova depois do
  book"). Deixei como está — condicioná-la exigiria cruzar duas flags no mesmo template.
- **`<ainda_falta>`** (belief, `dominio/atendimentos/service.py`) cita "só uber/vídeo se ELE
  sinalizar — não pergunte o formato". Não oferece a chamada, é sobre não perguntar o formato, e
  também renderiza antes da tag. Fica.
- **`<cotacao>`, "COMO você chama o programa"** lista "a vídeo chamada" entre os programas que
  ganham nome na fala. É conduta de NOMEAÇÃO de um programa que ela tem; para quem não tem, a tag
  ("não sai da sua boca em lugar nenhum") resolve. Não toquei.
- **`_e_video_chamada` casa por nome.** Cadastro que batize o programa sem a palavra "chamada"
  ("Vídeo", só) não casa, e a cauda passaria a tratá-lo como ausente — a modelo recusaria o que
  vende. É o lado do erro que **não** promete ao cliente uma chamada que a tabela não tem, mas vale
  conferir o nome no cadastro real antes do go-live desta mudança (não consegui ler o catálogo de
  prod: a query foi bloqueada, e §0 me impede de insistir).

### Verificação

`make lint` ✅ · `make typecheck` ✅ · `make test` ✅ (1844 passed, 239 skipped, +6 — `needs_db` não
rodou: o `DATABASE_URL` local aponta para prod, §0). `tests/agente/test_bp3_render.py` verde: o
BP_GERAL segue byte-idêntico entre modelos, e o que entrou é cauda.

**Gate pago pendente** (não rodei — §0): `E2E_AUTORIZADO=1 TEST_DATABASE_URL=… uv run python -m
evals.e2e.massa --k 1`, e ler `video_chamada_sem_programa.tool_esperada_ok` +
`.sem_oferta_de_chamada_ok` (os dois que passaram contra a prosa de hoje na corrida do ticket 23) e
`remoto_videochamada.estado_ok` + `.nao_pediu_pix_ok` (o ramo COM, agora com o cadastro certo). O
runner não filtra por cenário: a corrida cobre a massa inteira.

**Fechamento parcial (driver, 2026-07-30).** Diff conferido. Cinco ecos tocados (o ticket contava
quatro; o quinto é o `<porque>` do `<exemplo classe="pedido de prova de humanidade">`, e era o mais
perigoso de deixar — a segunda bolha do exemplo é a fala proibida **por extenso**, e a auditoria já
mostrou no ticket 07 que exemplo concreto vence prosa). `test_bp3_render.py` verde: BP_GERAL
byte-idêntico entre modelos.

**−641 chars no BP_GERAL** (66.954 → 66.313), +568 na cauda só de quem não tem o programa. O plano
previa −650 para o item 5.2 — praticamente cravado, **sem a discrepância do ticket 11**, porque
aqui a conduta positiva é curta e mora num site só.

**A pendência que o subagente deixou aberta foi fechada por leitura direta do catálogo de prod.**
Ele suspeitava que `_e_video_chamada` (que casa `"chamada"` no nome normalizado) pudesse errar se o
cadastro real batizasse o programa de outro jeito — nesse caso a tag entraria indevidamente e a
modelo recusaria o que vende. Consultei `barravips.programas` (leitura pura): são 11 itens —
`Acompanhante Jantar`, `Anal`, `Beijo Grego`, `Completo`, `Encontro`, `Massagem Relaxante`,
`Massagem Tântrica`, `Normal`, `Oral`, `Pernoite`, `Programa Completo` — e **nenhum contém
"chamada"**.

Como `modelo_programas` referencia esse catálogo global, é **impossível hoje** uma modelo ter vídeo
chamada. Três consequências:

1. **O risco não se materializa**: ninguém vende chamada, então a tag entrar para todas é o
   comportamento correto, não um bug.
2. **Vira pré-requisito de cadastro**: quando o programa for cadastrado (ADR-0021), o nome precisa
   conter "chamada", senão a tag continua entrando e aí sim a modelo recusa o que vende. Isso deve
   estar escrito onde quem cadastra vai ler.
3. **A conduta positiva de vídeo chamada no BP_GERAL é hoje inaplicável a 100% das modelos** — o
   que reforça este ticket e sugere que sobraria mais para cortar, se a decisão for que o programa
   não entra no P0.

O ticket também corrigiu um artefato: o cenário `remoto_videochamada` rodava com tabela
`Encontro 1h/2h`, **sem** o programa que a auditoria supunha — com o gate determinístico ele passaria
a medir o ramo SEM e falharia por artefato. Agora a modelo do cenário tem `Vídeo chamada / 30 min /
300`. Isso provavelmente explica o `estado_esperado_ok=False` que esse cenário deu na corrida do
`massa` de hoje, e que ficou registrado como "falha pré-existente" no ticket 23.

A distinção de doc pedida entrou no `agente/CLAUDE.md`: variante materializada no write-time versus
derivada do cardápio/BP_MODELO (sem coluna, sem detector), citando as três instâncias.

`make lint` ✅ · `make typecheck` ✅ · `make test` ✅ (1844 passed, +6).

**Pendente**: corrida do `evals.e2e.massa` lendo os dois ramos.
