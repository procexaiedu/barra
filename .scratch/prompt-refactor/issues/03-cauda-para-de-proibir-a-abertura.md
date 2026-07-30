# 03 — A cauda para de proibir a abertura que a conduta prescreve

**What to build:** um cliente que manda só "oi" tem que receber as 2 bolhas curtas de cumprimento. Hoje o bloco de contexto do turno afirma, sem nenhuma condição, que ela já está no meio do atendimento e não deve recumprimentar — e como esse bloco é lido logo antes da fala do cliente, ele vence a conduta. No mesmo bloco, o próximo-passo injeta "entender o que ele procura", que é exatamente a sonda-de-balcão que a conduta proíbe com a dureza máxima do vocabulário.

Depois deste ticket: a instrução de não recumprimentar só aparece quando há mesmo conversa anterior no atendimento, e o léxico de sonda desaparece do próximo-passo.

**Blocked by:** 01 (sem a janela em ordem, o gate não distingue recumprimento legítimo de artefato de ordem)

**Status:** resolved

- [x] "oi" seco no primeiro contato recebe cumprimento em 2 bolhas, sem informação e sem cardápio
- [x] a instrução de não recumprimentar continua aparecendo quando o atendimento já tem histórico
- [x] o texto do próximo-passo não contém mais nenhuma paráfrase de "o que ele procura"
- [ ] cenário de abertura e cenário de sonda do `conduta_gate` verdes, comparados ao baseline de 01

---

Diagnóstico de origem: `.scratch/prompt-refactor/auditoria-carga-instrucional.md` (com os anexos `inventario-turno.md` e `eixo-*.md`, que trazem as linhas citadas).

> Os anexos citam número de linha; este ticket cita bloco/tag de propósito — os números do `regras.md.j2` envelheceram em 40 min durante a própria auditoria.

---

## Comments

### O que mudou (por bloco/tag, nunca por linha)

**1.1 — a proibição de recumprimentar virou condicional.**
`contexto_dinamico.md.j2`, tag `<antes_de_perguntar>`: a segunda frase ("Você já está no meio do
atendimento, não recumprimente nem se reapresente") passou a viver dentro de
`{% if conversa_em_andamento %}`. A primeira frase (anti-repergunta sobre `<ainda_falta>`) segue
incondicional — não era ela que colidia com a `<abertura>`.

O gate é `conversa_em_andamento`, campo novo do `ContextoDoTurno` (default `False`, resolvido
depois das queries como o `dia_ja_sondado`), alimentado pelo detector `_conversa_em_andamento` em
`nos/_janela_do_turno.py`: varre a janela de trás pra frente e devolve `True` no primeiro
`AIMessage`, **parando na marca de pausa** do ticket 01.

Por que a marca de pausa e não `estado != 'Novo'`: o eixo B já apontava o buraco do teste por
estado (o turno em que ela já falou mas o estado ainda é `Novo` — a extração roda depois do `llm` —
cairia no ramo errado, e o webhook fino com `atendimento_id=None` também). O detector de janela
não tem esse atraso. E parar na marca de pausa é o que faz o "oi" de quem sumiu seis dias voltar a
ser abertura, em vez de "meio de atendimento" por causa de bolha de outro atendimento na mesma
janela (a janela cruza atendimentos de propósito — CONTEXT.md, "Conversa cliente").

**1.2 — o léxico da sonda saiu do `<proximo_passo>`.**
`_PROXIMO_PASSO["Novo"]` (`dominio/atendimentos/service.py`): `"entender o que ele procura e puxar
pro encontro"` → `"deixar ele abrir o assunto e puxar pro encontro"`. O resto da frase (`— sua
conduta agora é <abertura>; se a fala dele já pede preço, <cotacao> junto`) está intacto.

Eco multi-site "Fase do funil apontada pela cauda" **revisitado**: o canônico são as tags de fase
do `<conducao_da_venda>` em `regras.md.j2`, e elas não mudaram — o que mudou é como o eco descreve
o *objetivo* da fase, não que fase ele aponta. `<abertura>` e `<cotacao>` continuam citadas, então
`tests/unit/test_contrato_variaveis_contexto.py::test_fase_apontada_pelo_proximo_passo_existe_no_regras`
continua verde sem ajuste. Nada foi tocado em `regras.md.j2`.

**Prompt caching:** as duas mudanças ficam na cauda (última `HumanMessage`). O BP_GERAL
(`persona.md` + `regras.md.j2`) não foi tocado — zero cache-miss, zero condicional por-turno dentro
do prefixo.

### Testes

Novo: `tests/unit/test_cauda_nao_proibe_a_abertura.py` (sem DB, sem crédito) — o detector nos 4
casos (primeiro contato, bolha dela, dos dois lados da marca de pausa), o bloco renderizado pelo
caminho real (`_anexar_contexto_dinamico`) com e sem histórico, e o `<proximo_passo>` de **todas**
as fases contra um regex de paráfrases da sonda.

Ajustado: `tests/test_belief_state.py::test_novo_sem_intencao_falta_entender` — a asserção de
prefixo da frase-guia. `slots_faltantes == ["o que ele procura"]` continua valendo (ver achado
abaixo).

Gate local verde: `make lint` · `make typecheck` (142 arquivos) · `make test` (1785 passed, 239
skipped `needs_db`). `needs_db` **não** rodado: nenhuma linha de SQL mudou neste ticket.

### Critério 4 — o gate que falta

`conduta_gate` **não consome** `evals/e2e/cenarios.py`: ele roda personas do corpus
(`extrair_nucleo`, 6 eixos × 2 = as 12 corridas do baseline). Quem consome os cenários é
`evals/e2e/massa.py`. E, como o eixo B já registrava em A1, **nenhum dos cenários abria com "oi"
seco** — todos entram com pergunta colada. Ou seja: o "cenário de abertura" e o "cenário de sonda"
do critério 4 não existiam.

Criei o que faltava, sem rodar nada pago:

- `cenarios.py`: `CenarioFunc(nome="abertura_oi_seco", ...)`, abertura literal `"oi"`, com o novo
  flag `deve_abrir_so_com_cumprimento`;
- `massa.py`: `_abriu_so_com_cumprimento` — o 1º turno da IA não pode ter número de preço
  (`\d{3,4}`) nem paráfrase de sonda. O probe CRU já tem backstop no `output_guard`; o que este
  check pega é a **paráfrase**, que passa por lá. Os regexes foram conferidos contra falas certas e
  erradas fora do runner.

O cenário cobre os dois lados do critério de uma vez (abertura limpa **é** ausência de sonda).
Falta a corrida paga — ver "Pendências".

### Achado adjacente, NÃO corrigido (fora do escopo do ticket)

O `<ainda_falta>` do mesmo bloco continua renderizando `<item>o que ele procura</item>`: é o rótulo
de `_PRECONDICOES_TRANSICAO["Novo"]` (`service.py`), não do `_PROXIMO_PASSO`. Ele fica **duas
linhas acima** do próximo-passo e é lido junto do `<antes_de_perguntar>`, cuja primeira frase diz
"Antes de perguntar qualquer item de 'ainda falta'…" — ou seja, a cauda ainda apresenta a intenção
dele como um item **a perguntar**, no léxico exato que a `<abertura>` proíbe.

Deixei de propósito: o critério 3 fala do próximo-passo, e a §3 do plano (item 1.2) nomeia só
`service.py:790`. Mas, na minha leitura, esse rótulo é hoje o driver mais forte da sonda que sobra
no turno `Novo`. Se você concordar, é um ticket de uma linha (`"o que ele procura"` → algo como
`"a que ele veio (você não pergunta — ele diz)"`), com o mesmo gate.

**Fechamento parcial (driver, 2026-07-30).** Diff conferido: a condicional foi para a **cauda**
(`contexto_dinamico.md.j2`, `<antes_de_perguntar>`), não para o BP_GERAL — `regras.md.j2`,
`persona.md` e `reminder.md.j2` intocados, prefixo cacheado byte-idêntico. `make lint` ✅ ·
`make typecheck` ✅ · `make test` ✅ (1785 passed, +7).

Critérios 1–3 cumpridos. **Critério 4 pendente**: depende da corrida paga do `conduta_gate`, que
por decisão do plano roda **uma vez no fim do lote 03–08**, contra o baseline de `dd4a7e9`
(APROVADO, `empurrao 0,0%`, `violacoes_duras 0`). Por isso o ticket segue `claimed` até o
checkpoint.

Nota de commit: o commit deste ticket carrega junto WIP do usuário em `nos/_janela_do_turno.py` e
`nos/prepare_context.py` (frente da marca de pausa, incidente 29/07) — os arquivos já estavam
sujos e `git add -p` não roda neste ambiente. Decisão do humano, registrada também no corpo do
commit.

**Fechado no checkpoint (driver, 2026-07-30).** O `conduta_gate` rodou contra o baseline `dd4a7e9`
e voltou **APROVADO** (`empurrao_pct 0,0%`, `violacoes_duras 0`), com o lote melhorando condução
(`conduziu decidido_rapido` 0% → 50%), desfecho (`bate_desfecho_real` 83,3% → 91,7%) e forma
(`fluxo_jsd` 0,1985 → 0,1896). Números e a comparação das duas corridas em
`.scratch/prompt-refactor/checkpoint-lote-03-08.md`. `Status: resolved`.
