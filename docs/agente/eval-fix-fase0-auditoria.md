# Eval Fix — Fase 0: auditoria estatica (pre-medicao paga)

> Sintese da auditoria ESTATICA (offline, gratis) do gate de evals do agente Barra antes de
> gastar credito Anthropic. Combina o baseline offline (test + typecheck) com a previsao
> deterministica por fixture, ja **verificada contra o codigo** (runner, dominio, tools, seed).
> Saldo Anthropic ~US$2,67 (quase esgotado): a meta e prever o veredito do gate de regressao
> SEM rodar, e so depois medir o minimo necessario para confirmar.

Data: 2026-06-03 · branch `hardening-agente-onda-a`

---

## 1. Baseline offline (gratis) — VERDE

| Dimensao | Resultado | Resumo |
|---|---|---|
| `pytest -m "not needs_key"` | **verde** | 719 passed, 66 skipped, 6 deselected (132.79s). 100% offline (`TEST_DATABASE_URL` e `ANTHROPIC_API_KEY` vazios confirmados). 66 skips = `needs_db`; 6 deselected = `needs_key`. Zero falha/erro. |
| `mypy src` | **verde** | Success, no issues in 108 source files. |

Unicos warnings: `DeprecationWarning` do Starlette/FastAPI (`HTTP_422_UNPROCESSABLE_ENTITY`), nao
relacionados. **Nada custou credito ate aqui — seguro prosseguir.**

O baseline verde NAO prova que o gate de evals (`runner.py`) fecha: a suite offline testa o
NUCLEO PURO do runner (`avaliar`/`gate`/`agregar_por_fixture`) e os graders, mas NAO exercita o
grafo real contra as fixtures (isso exige `TEST_DATABASE_URL` + `ANTHROPIC_API_KEY` = credito).
A previsao abaixo cobre exatamente esse buraco.

---

## 2. Tabela por fixture (15 fixtures)

Veredito previsto · confianca · graders em risco (so os de risco **alto**, com o vetor mecanico) ·
causa-raiz · fix minimo. ainvoke = nº de turnos de cliente (1 `ainvoke` cada).

| Fixture | gate | veredito | conf. | ainvoke | grader(es) de risco ALTO | causa | fix minimo |
|---|---|---|---|---|---|---|---|
| `scripted_5.001` qualif_interno_desconto | regressao | **falha** | alta | 3 | `state_check[t4].estado==Qualificado` (pedido de desconto puro nao tem horario+tipo+agendamento → `_decidir_transicao` mantem Triagem) | **fixture-incorreta** | tirar `estado:Qualificado` do t4 (estado correto = Triagem) OU reescrever turnos do cliente com horario+tipo ANTES do desconto |
| `scripted_5.002` recusa_pratica_camadas | regressao | incerto | media | 2 | (medio) `nao_deve_conter:[kkk]` colide com persona que autoriza `kkkk` | prompt | afrouxar grader (banir `kkkk` literal, nao substring `kkk`) OU deixar 2a camada seca |
| `scripted_5.003` gringo_bilingue | regressao | incerto | media | 3 | `nao_deve_conter:[donde/cuanto/gracias/mi amor]` (ultimo turno do cliente e ES; LLM pode ecoar) | prompt | reforcar `<bilingue>` em `regras.md.j2` (nunca ecoar palavra ES; exemplo p/ "donde es tu apartamento?") |
| `scripted_5.004` desconto_unico_abaixo_piso | regressao | incerto | media | 3 | `escalar` sintetico + `ia_pausada_final:false` (LLM escala fora_de_oferta OU trap do piso com cardapio vazio) | prompt | desambiguar `<cliente_que_volta>`: "me da um bom preco" de cliente que volta NAO e gatilho de escalar; so grave `valor_acordado` se cliente cravar numero |
| `scripted_5.005` dupla_cliente_recua | regressao | incerto | media | 2 | `nao_deve_conter:[kkk]` (persona.md L12 manda usar `kkkk`) | prompt | remover `kkkk` da lista de fillers em `persona.md` e do exemplo `<armadilhas_de_voz>` |
| `scripted_5.006` drift_tardio_reminder | regressao | incerto | media | 9 | `nao_deve_conter:[**, 1., 2., - ]` + `max_chars:400` (pedido "passo a passo" puxa lista/comprimento) | prompt | reforcar `reminder.md.j2` com armadilha anti-"passo a passo" (1-2 bolhas em prosa) |
| `scripted_5.007` horario_vago_reserva_ansiosa | **capability** | incerto | media | 3 | `escalar` + `ia_pausada_final:false` (super-extracao de horario vago → branch 12 reagendamento → escala) | prompt | instruir agente a NAO cravar `horario_desejado` de horario VAGO ("depois das 21h"); reforco em `regras.md.j2` + `extracao.py` |
| `leitura.001` consulta_agenda | regressao | **falha** | alta | 1 | `tool_calls_proibidas:[registrar_extracao]` (prompt L329/333 manda registrar_extracao TODO turno; runner binda as 5 tools) | **fixture-incorreta** | tirar `registrar_extracao` de `tool_calls_proibidas` (so `pedir_pix`/`escalar` corretos) |
| `leitura.002` consulta_alem_48h | regressao | incerto | media | 1 | (alto) `tool_calls_proibidas:[registrar_extracao]` — mesmo conflito; nao-determinismo do LLM | prompt | carve-out em `regras.md.j2`: nao registrar em turno de pura consulta/disponibilidade |
| `leitura.003` disponibilidade_hoje_sem_tool | regressao | incerto | media | 1 | (alto) `tool_calls_proibidas:[registrar_extracao]` | prompt | mesmo carve-out (cobre 001/002/003 de uma vez) |
| `cache_hit.001` segundo_turno_cache | regressao | **passa** | media | 2 | (medio) so `escalar`/`ia_pausada` via output_guard judge default-seguro (over-refusal/infra) | nenhuma | nenhum fix; `metricas.cache_hit_rate` e `rubricas` NAO sao lidos por `avaliar()` (advisory) |
| `midia.pix_extracao.001` valor_ok | regressao | **falha** | alta | 0 | `executar_fixture` lanca `ValueError` (sem `mensagens_entrada`; schema `vision_pix` nao implementado) → **DERRUBA A RUN INTEIRA** | **fixture-incorreta** | pular fixtures com `tipo_pipeline` em `carregar_fixtures`/`rodar` (early-skip, nao raise) |
| `agenda.001` interno_qualifica_reserva | regressao | passa | media | 1 | (medio) `tool_obrig:[registrar_extracao]` + `state_check:Aguardando_confirmacao` (LLM precisa setar tipo=interno + horario) | prompt | sem fix se passar; senao reforco em `<sequencia_interna>` |
| `agenda.002` externo_pede_pix | regressao | **falha** | alta | 1 | `state_check.estado/pix_status` (seed sem `chave_pix` → tool faz early-return ANTES de transicionar; estado fica Qualificado) + `escalar` (erro da tool instrui `escalar(politica_nova)`) | **fixture-incorreta** | seed precisa `chave_pix`+`titular_chave`+`horario_desejado` em `_seed_entidades` (ler de `estado_inicial`) |
| `agenda.003` aviso_saida_nao_pausa | regressao | incerto | media | 1 | (alto) `deve_conter_um_de:[te espero/chega/...]` (nada no prompt obriga essas formas; LLM pode dizer "to te aguardando") | prompt | few-shot `<exemplo_aviso_saida>` em `regras.md.j2` que ancora "te espero"/"to aqui" e evita "pode vir" |

---

## 3. Slice `scripted_5` (alvo do gate)

O gate de cutover (`gate_split`) so conta a suite de **regressao**. Dentro de `scripted_5`:

- **Bloqueiam o gate (regressao): 001, 002, 003, 004, 005, 006.**
- **007 e `capability`** (campo `"gate":"capability"` explicito na fixture) — **advisory, NAO bloqueia.**
  E o achado conhecido da super-extracao de horario vago (EVAL-12); o ganho se mede pelos rotulos.

### Veredito do slice de regressao scripted_5

| Fixture | veredito | risco que decide |
|---|---|---|
| 001 | **falha** (alta) | DETERMINISTICO: pedido de desconto nao produz `Qualificado`. Independe do LLM. |
| 002 | incerto (media) | `kkk` (prompt vs grader) — nao-determinismo |
| 003 | incerto (media) | eco de token ES — nao-determinismo |
| 004 | incerto (media) | escalada espuria (LLM ou trap do piso) — nao-determinismo |
| 005 | incerto (media) | `kkk` (persona.md L12 manda usar `kkkk`) — nao-determinismo |
| 006 | incerto (media) | markdown/`max_chars:400` no "passo a passo" — nao-determinismo |

**001 e uma falha DETERMINISTICA**: a maquina de estados (`dominio/atendimentos/service.py:_decidir_transicao`,
verificada L311-317) so promove `Triagem→Qualificado` com `intencao=agendamento` **E** `horario_desejado`
**E** `tipo_atendimento`. A conversa da fixture (elogio → preco → cotacao → "melhora o preco?") nao
fornece nenhum deles → estado permanece Triagem → `state_check[t4].estado==Qualificado` reprova,
**independente do LLM**. Por isso o slice de regressao do scripted_5 **NAO fecha 100%** mesmo no melhor
caso de nao-determinismo. Alem de 001, ha 5 fixtures `incerto` por risco real (nao mero ruido):
o conflito `kkk` (002/005) e estrutural — `persona.md` literalmente autoriza `kkkk` e o grador o proibe
por substring.

---

## 4. Causas agrupadas

### 4.1 fixture-incorreta (4 fixtures) — bloqueadores duros, fix barato e cirurgico
- **`scripted_5.001`** — pede `Qualificado` num turno que o dominio nao promove. Fix na fixture
  (`001_qualificacao_interno_desconto.jsonl`): trocar `estado:Qualificado`→`Triagem` no t4, OU
  injetar horario+tipo nos turnos do cliente.
- **`leitura.001`** — proibe `registrar_extracao`, que o prompt MANDA chamar todo turno. Fix na
  fixture: remover `registrar_extracao` de `tool_calls_proibidas`.
- **`agenda.002`** — `state_check` so e atingivel com `chave_pix` no seed (que nao existe) +
  `horario_desejado` (senao `criar_bloqueio_previo` estoura `TypeError` num `datetime.combine`
  com horario NULL). Fix no **seed do runner** (`_seed_entidades`), nao na fixture/prompt.
- **`midia.pix_extracao.001` (+ 002)** — schema `vision_pix` cujo caminho de worker
  (`workers/pix.py:validar_pix`) o runner **nunca implementou**. Sem `mensagens_entrada`,
  `executar_fixture` lanca `ValueError` (runner.py L412-415) que **NAO e capturado** — o `finally`
  da `rodar()` so faz `rollback`, a excecao propaga e **aborta a run inteira**. VERIFICADO no codigo:
  uma run `--subdir canonicos` (rglob) carrega esta fixture e crasha; uma run `--subdir
  canonicos/scripted_5` NAO a carrega. Fix: pular fixtures com `tipo_pipeline` no carregamento.

### 4.2 prompt (8 fixtures) — todos nao-deterministicos, fix de prompt/grador
`scripted_5.002/003/004/005/006/007`, `leitura.002/003`, `agenda.001/003`. Dois clusters:
- **`kkk` vs `kkkk`** (002, 005, e residual em 003/004/006): `persona.md` autoriza `kkkk` como
  filler; o grador proibe a substring `kkk`. Conflito estrutural prompt↔fixture. Decidir UM lado:
  ou tirar `kkkk` da persona, ou afrouxar o grador p/ banir `kkkk` literal.
- **`registrar_extracao` todo-turno** (leitura.002/003): o prompt empurra a tool de escrita mesmo
  em turno de pura leitura. Carve-out no prompt cobre as 3 fixtures de leitura de uma vez.
- Demais: eco ES (003), escalada espuria do "me da um bom preco" (004), drift "passo a passo"
  (006), formas de acolhida do aviso de saida (003 agenda).

### 4.3 arquitetura-grafo — **NENHUMA**
Nenhuma falha prevista atribuivel a defeito do grafo. O output_guard judge default-seguro (escala
em falha de infra) e um RISCO de flakiness sob API instavel, nao um bug — e a postura correta.

### 4.4 dominio — **NENHUMA**
Todas as regras de dominio invocadas estao CORRETAS e verificadas: `_decidir_transicao`
(transicoes), `_abaixo_do_piso` (conservador sem cardapio — ADR-0004), early-return do
`pedir_pix` sem `chave_pix`, `marcar_aviso_saida` (nao pausa/transiciona), branch 12
reagendamento. Onde a fixture diverge do dominio, **a fixture esta errada** (001, agenda.002).

> **Resumo das causas:** 4 fixture-incorreta (bloqueadores duros) · 8 prompt (nao-det.) ·
> 0 arquitetura · 0 dominio. O gate NAO fecha hoje, e a culpa e de **fixtures/seed mal-formados**
> + **conflito prompt↔grader**, nao do agente.

---

## 5. Estrategia de medicao paga (saldo ~US$2,67)

Premissa de custo: **1 `ainvoke` = 1 turno de cliente**, e cada bolha nao-canned dispara uma
**2a chamada Sonnet** (output_guard AUP judge, `output_guard_judge_habilitado=True` por default).
Ou seja, o custo real em chamadas LLM e ~**2× o nº de ainvoke** nos turnos com bolha. Orcamento
apertado → medir o MINIMO que confirma o veredito estatico, na ordem certo-determinista primeiro.

### 5.1 NAO rodar `--subdir canonicos` inteiro (armadilha de crash)
A fixture `vision_pix` **aborta a run inteira** com `ValueError`. Rodar o canonicos completo
(`rglob`) crasha ANTES de produzir qualquer veredito util — **e desperdicio de credito** (os turnos
ja gastos ate o crash nao viram relatorio). **Sempre escopar por subdiretorio** que NAO inclua
`midia/pix_extracao/`, OU aplicar primeiro o fix de skip do `tipo_pipeline`.

### 5.2 Ordem de medicao (mais barato + mais informativo primeiro)

1. **`leitura/001` (1 ainvoke, ~$0)** — confirma DE GRACA a falha determinista mais barata
   (`registrar_extracao` proibido mas chamado). 1 turno, 1 fixture. Prova/refuta o vetor
   `registrar_extracao` todo-turno que tambem governa leitura.002/003 e agenda.001. **Medir
   PRIMEIRO.** Custo unitario aferido aqui = base p/ extrapolar o resto.
2. **`scripted_5/001` (3 ainvoke)** — confirma a falha determinista da maquina de estados
   (`Qualificado` impossivel). Valida o veredito-chave do gate de regressao. Barato e decisivo.
3. **`agenda/002` (1 ainvoke)** — confirma o duplo-blocker do seed (chave_pix + horario).
   1 turno, alta confianca.
4. **`leitura/003` + `leitura/002` (1+1 ainvoke)** — afere o NAO-determinismo do
   `registrar_extracao` (quantas amostras chamam a tool). Barato; calibra o risco dos `incerto`.

So depois (se o saldo aguentar) medir o slice scripted_5 de regressao restante (002-006) p/
quantificar os `incerto` do `kkk`/eco/drift — sao 2+3+3+2+9 = 19 ainvoke adicionais, os mais caros.

### 5.3 Custo estimado em ainvoke

| Slice | ainvoke (turnos) | observacao |
|---|---|---|
| **scripted_5 regressao (001-006)** | **22** | 3+2+3+3+2+9. **006 sozinha = 9** (40% do slice) |
| scripted_5 full (001-007) | 25 | +3 do 007 (capability) |
| leitura (001-003) | 3 | 1 cada — os mais baratos |
| cache_hit (001) | 2 | — |
| agenda (001-003) | 3 | 1 cada |
| midia vision (001-002) | 0 | **crasha a run, nao roda** |
| **canonicos turn-based (sem vision)** | **33** | 25 + 3 + 2 + 3 |

> Chamadas LLM efetivas ≈ **2×** esses numeros onde a bolha passa pelo output_guard judge
> (cada turno nao-canned = 1 invoke do grafo + 1 judge AUP). No pior caso o canonicos sem vision
> custa da ordem de **~66 chamadas Sonnet**. Com saldo ~US$2,67, **medir o slice completo de uma vez
> e arriscado** — siga a ordem 5.2 e pare assim que o veredito de regressao estiver confirmado.
> Para baratear, pode-se desligar o output_guard judge na medicao (corta ~metade das chamadas),
> mas isso muda o caminho testado — preferivel medir as 4 fixtures baratas (itens 1-4, ~6 ainvoke
> ≈ ~12 chamadas) e extrapolar.

### 5.4 Itens que NAO custam credito (medir/decidir de graca antes)
- Aplicar os 3 fixes de fixture-incorreta (001, leitura.001, agenda.002 no seed) e o skip do
  `tipo_pipeline` — sao edicoes de arquivo, verificaveis pela suite offline (`pytest`/`mypy`).
- `cache_hit.001`: `metricas.cache_hit_rate`/`rubricas` NAO sao lidos por `avaliar()` — o smoke de
  cache e puramente documental nesta suite. Nada a medir.

---

## 6. Veredito do gate de regressao (previsto)

**`falha_provavel`.** O slice de regressao do gate (que inclui scripted_5 001-006, leitura
001-003, cache_hit 001, agenda 001-003) **nao fecha 100%** no estado atual, por motivos
**deterministicos** (independem do LLM):

1. **`scripted_5.001`** — `Qualificado` impossivel para pedido de desconto (maquina de estados).
2. **`leitura.001`** — proibe `registrar_extracao` que o prompt manda chamar todo turno.
3. **`agenda.002`** — seed sem `chave_pix` → tool nao transiciona; estado fica Qualificado.
4. **`midia.pix_extracao.001`** — `vision_pix` aborta a run inteira se o canonicos for rodado por
   `rglob` (crash, nao falha de grader).

Essas 4 sao **fixture/seed-incorretas**, nao falhas do agente — mas enquanto nao corrigidas, o
gate de regressao **reprova de forma determinista**. Acrescente 5+ fixtures `incerto` por
nao-determinismo real (cluster `kkk`, eco ES, drift). **Nao e honesto prever "fecha 100".**

Caminho para `fecha_100` (todos sem custo de credito, exceto a verificacao final):
1. Aplicar os 3 fixes de fixture-incorreta + o skip do `tipo_pipeline`.
2. Decidir o conflito `kkk`↔`kkkk` (tirar da persona OU afrouxar grader) — remove o maior cluster
   de `incerto`.
3. Aplicar os carve-outs de prompt (registrar_extracao em leitura; few-shots de bilingue/aviso).
4. So entao medir (ordem 5.2) para confirmar.
