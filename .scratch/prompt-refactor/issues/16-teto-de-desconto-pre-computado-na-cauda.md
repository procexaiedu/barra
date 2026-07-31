# 16 — Ela para de calcular o teto que o sistema já calcula para julgá-la

**What to build:** hoje ela recebe o teto como percentual e tem que aplicá-lo sobre o preço de tabela do pacote em jogo — enquanto o sistema já calcula esse mesmo piso em número absoluto e o usa para julgar a resposta dela (abaixo do piso, escala). O número existe e não é mostrado a quem precisa dele.

Depois deste ticket o valor já vem calculado na cauda, dentro da tag de contraproposta que já sai. Aritmética sai do modelo e vai para onde já estava sendo feita.

Não muda nada do que o cliente vê: os percentuais continuam nunca sendo expostos, e a escada continua de duas rodadas.

**Blocked by:** 01, 08

**Status:** claimed

- [x] a contraproposta de teto sai no valor exato que o sistema usaria para julgar, sem arredondamento divergente
- [x] nenhum percentual e nenhuma menção a limite ou política aparece na fala
- [x] segue valendo: duas rodadas, e abaixo do teto escala em vez de ofertar
- [x] o teste de contrato das variáveis de contexto cobre o campo novo

---

Diagnóstico de origem: `.scratch/prompt-refactor/auditoria-carga-instrucional.md` (com os anexos `inventario-turno.md` e `eixo-*.md`, que trazem as linhas citadas).

> Os anexos citam número de linha; este ticket cita bloco/tag de propósito — os números do `regras.md.j2` envelheceram em 40 min durante a própria auditoria.

## Comments

**Feito.** O número do teto passou a ser dado na cauda, dentro da tag que já saía. BP_GERAL
intocado (o `<desconto>` do `regras.md.j2` não mudou uma vírgula) — o valor é por-turno e
por-modelo, então mora só na última HumanMessage.

**O site único da conta** (`dominio/atendimentos/service.py`):
- `piso_de_desconto(preco_tabela)` — `preço × (1 − desconto_teto_pct)`, puro. É a conta que o
  `_abaixo_do_piso` já fazia inline; agora ele a CHAMA. Quem julga e quem mostra saem da mesma
  função, não de duas implementações que concordam hoje (critério 1).
- `teto_de_contraproposta(conn, modelo_id, duracao_horas)` — o valor absoluto para a cauda.
- `_preco_tabela_min` virou casca de `_precos_tabela`, que devolve `(menor, maior)` numa query só
  (`min`/`max` agregados no lugar do `ORDER BY … LIMIT 1`). O guard continua usando o MENOR:
  comportamento idêntico.

**A cauda:** campo `teto_desconto` no `ContextoDoTurno`, resolvido em `_resolver_variaveis` SÓ com
`n_contrapropostas == 1` (a query extra só roda nessa rodada), e renderizado dentro do
`<ja_fez_contraproposta n="1">` do `contexto_dinamico.md.j2`: "…você tem a segunda e ÚLTIMA
contraproposta — o teto, **que é 300: esse número já vem calculado da sua tabela, não recalcule nem
desça dele** — antes de escalar com fora_de_oferta." Não é flag A2 (não carimba coluna, não tem
detector, não precisa de migration): é valor derivado, pendurado no contador que já existia.

**Achado que mudou a forma da entrega — leia antes de julgar o critério 1.** O piso que o guard usa
é o do programa **mais barato** da duração, de propósito (ADR-0004 §Decisão item 5: minimiza
falso-positivo de escalada). O teto que ela pode OFERTAR é sobre o "Preço de tabela do pacote
**vendido**" (CONTEXT.md, *Piso de desconto*) — e o pacote não está gravado no atendimento
(`atendimento_servicos` só o painel escreve; o agente só grava `duracao_horas`). Quando a duração
tem mais de um preço na tabela da modelo (existe: seed `0015_seed_gustavo` tem Massagem 800 e
Tântrica 1800 na mesma duração; o catálogo global tem Padrão/Casal/Jantar/Social), os dois números
divergem — e entregar o piso do mais barato como "seu teto" mandaria a IA dar 25% em cima do pacote
errado (na Tântrica de 1800 ela ofereceria 600). Por isso `teto_de_contraproposta` devolve `None`
quando a duração tem mais de um preço: aí a cauda **cala** e vale o percentual do `<desconto>`,
exatamente como hoje. Com um preço só na duração as duas leituras são o MESMO número e o critério 1
vale literalmente. Default conservador, no padrão "sem o dado, não injeta" do `agente/CLAUDE.md`.

**Ecos.** Nenhum eco da escada mudou, porque a REGRA não mudou (duas rodadas, degrau→teto, abaixo
do teto escala): `<nucleo>` 6, `<nucleo_final>`, `reminder`, `<exemplos>`, `persona.md`,
`ferramentas/extracao.py` e a variante `aceite-referenciado` da bancada seguem intactos. O item 8
que o ticket 08 preservou palavra por palavra (`<ja_fez_contraproposta n="2">`) também. O que ganhou
uma linha foi o `agente/CLAUDE.md`, seção das flags A2, onde a instância `<ja_fez_contraproposta>`
está documentada — o novo acoplamento (cauda ↔ função que julga) precisava estar escrito em algum
lugar que o próximo leitor abra.

**Verificação local (verde):** `make lint` (All checks passed) · `make typecheck` (142 arquivos, 0
issues) · `make test` (**1879 passed, 239 skipped, 8 deselected**). `needs_db` não rodou de
propósito — o `DATABASE_URL` do `.env` aponta pro self-hosted de produção (§0).

Testes novos/estendidos, todos offline:
- `tests/unit/test_piso_de_desconto.py` (novo): a conta, o não-arredondamento, e os três `None` de
  `teto_de_contraproposta` (sem duração, sem programa na duração, dois preços na duração).
- `tests/unit/test_contraproposta_flag.py`: o valor sai em `n=1` e só nela; render com e sem o
  número; a cauda continua sem `%`.
- `tests/unit/test_contrato_variaveis_contexto.py`: recorte nominal do campo novo (critério 4) —
  publicado no `ContextoDoTurno` E lido pelo `contexto_dinamico.md.j2`.

**Roteiro e2e estendido (escrito, NÃO rodado):** campo `teto_do_pacote` no `CenarioFunc` e checker
`_ofertou_abaixo_do_teto` em `massa.py`, ligados nos TRÊS cenários de desconto que já existiam
(`desconto_dentro_degrau`, `desconto_entre_degrau_teto`, `desconto_abaixo_teto`; 1h/R$400 → teto
300). O checker lê só o número que segue "consigo" — o valor OFERTADO —, espelhando o
`_RE_CONTRAPROPOSTA` do `_disciplina.py`, para não confundir com o número que o cliente pediu e ela
ecoou ao recusar. Nenhum cenário novo.

**Pendente e pago (não rodei — autorização é do humano):**
`cd api && uv run python -m evals.e2e.massa` (ou o `conduta_gate`, que roda a mesma massa) — é o
único lugar onde o critério 1 vira medida de COMPORTAMENTO: a nova chave `contraproposta_no_teto_ok`
tem de sair verde nos três cenários de desconto, junto com o `nao_escalou_ok` dos dois primeiros e o
`tool_esperada_ok` (escalar) do terceiro. Se algum exigir afrouxar asserção, o número na cauda está
sendo lido como "oferte isto agora" e a resposta é reverter, não ajustar o teste.

**Redeploy:** o LangGraph roda no `barra-worker` — mudança de prompt/cauda só vale em prod depois de
`docker service update --force <stack>_barra-worker`. Nada disso foi feito; nada commitado.
