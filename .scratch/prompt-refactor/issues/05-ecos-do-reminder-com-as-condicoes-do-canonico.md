# 05 — Os ecos do lembrete param de afirmar versão mais estreita que a conduta

**What to build:** dois ecos de recency afirmam sem condição o que a conduta afirma com condição — e por estarem perto do fim, ganham.

Primeiro: "pergunta dele não é aceite". Verdade antes de qualquer negociação de preço; falso depois dela, quando uma pergunta de horário ou logística é justamente o sim ao valor na mesa. A condição existe no site canônico apenas por posição (o parágrafo mora dentro da escada de desconto), então o eco precisa dizê-la com todas as letras — e pelos dois ramos: depois de ter recusado baixar **ou** de ter feito contraproposta.

Segundo: "o padrão é ele vir até você". Falso para a modelo que não recebe. Ela nunca deve oferecer um local que não tem.

**Blocked by:** 01

**Status:** resolved

- [x] depois de recusa de desconto, "que horas?" avança o fechamento em vez de virar pergunta a responder
- [x] depois de contraproposta, o mesmo — os dois ramos valem
- [x] antes de qualquer negociação de preço, pergunta dele continua sendo pergunta a responder
- [x] modelo que só se desloca não recebe eco dizendo que o padrão é ele ir até ela
- [ ] `conduta_gate` verde contra o baseline de 01

---

Diagnóstico de origem: `.scratch/prompt-refactor/auditoria-carga-instrucional.md` (com os anexos `inventario-turno.md` e `eixo-*.md`, que trazem as linhas citadas).

> Os anexos citam número de linha; este ticket cita bloco/tag de propósito — os números do `regras.md.j2` envelheceram em 40 min durante a própria auditoria.

---

## Comments

**O que mudou — dois ecos de recency, uma frase cada.**

1. `agente/prompts/reminder.md.j2`, parágrafo "Continua valendo na venda". Duas cláusulas:
   - *"e pergunta dele não é aceite"* → agora carrega a condição por extenso e **pelos dois ramos**:
     "não é aceite **enquanto a negociação de preço não rodou**; depois que ela rodou — você
     **recusou baixar ou fez contraproposta** —, a pergunta dele ('que horas ?', 'onde é ?') é o sim
     ao valor que está na mesa: crave o horário, sem re-cotar nem repetir 'não consigo'". É a mesma
     forma da correção de 30/07 (dizer a condição, não deletar o eco).
   - *"o padrão é ele vir até você"* → cortado, como o `eixo-b` A6 prescreve. Ficou **"não abra menu
     de formato ('vem aqui ou vou até você ?') — o formato sai do que já está de pé e dos seus tipos
     aceitos"**: o que o lembrete precisa condensar é a proibição do menu; a conclusão "ele vem até
     você" depende de dado **por-modelo** (`tipo_atendimento_aceito`) e não cabe num eco que é o
     mesmo texto para todas as modelos.
2. `agente/prompts/regras.md.j2` `<nucleo_final>`: mesma condição, mesma redação enxuta — "pergunta
   dele não é aceite **enquanto a negociação de preço não rodou** — depois que você recusou baixar
   ou fez contraproposta, a pergunta dele é o sim ao valor que está na mesa e você crava o horário".
   (`auditoria §3` item 1.4 lista os dois sites; o ticket só nomeia o lembrete no título.)

**Os 3 sites do eco "Avanço que equivale a sim" (`agente/CLAUDE.md`), conferidos um a um:**
- **Canônico** `regras.md.j2` `<desconto>` — o WIP em curso do usuário **já** tinha transformado a
  condição posicional em afirmada, com os dois ramos ("você recusou baixar **ou** fez
  contraproposta") e com o lado estrito dito ("Isso vale SÓ depois da negociação de preço: sem ela,
  uma pergunta dele continua sendo pergunta"). Nada a fazer — é justamente o texto que os ecos
  passaram a espelhar.
- **`ferramentas/extracao.py`, campo `aceita_valor`** — já autocontido e já com os **dois** ramos
  ("recusando ('não consigo amor') **ou** com a sua contraproposta ('consigo 500 se vier hoje')").
  A emenda de 25/07 (o extrator não recebe o BP_GERAL) está cumprida. **Nada a fazer.**
- **`evals/extracao/extrator.py`, variante `aceite-referenciado`** — **de propósito NÃO tocada**: ela
  congela a descrição órfã que rodou até 25/07 para a bancada comparar. Atualizá-la destruiria o
  ponto de comparação.

**Quarto site do "padrão é ele vir até você", checado e deixado como está:** `persona.md`, o
`<par>` de `<armadilhas_de_voz>` cujo `<porque>` diz "o padrão é ele vir no seu local
(<tipos_de_encontro>)". Fica: (a) o `<errado>` dele é o **menu de formato**, que é errado para
qualquer modelo; (b) ele **endereça** `<tipos_de_encontro>`, que carrega o ramo "se você só se
desloca…", e persona.md é BP_GERAL — a referência resolve no mesmo turno, ao contrário do lembrete.
Mesma razão vale para `<abertura>` ("Abrir menu de formato: o padrão é ele vir até você
(<tipos_de_encontro>)") e para o próprio `<tipos_de_encontro>`: são os dois sites canônicos que o
`eixo-b` A6 conta como a rede de segurança do default interno.

**⚠️ Risco residual que só a corrida paga resolve (achado, fora do escopo deste ticket).** No turno
exato que os critérios 1 e 2 miram — ele pergunta o horário logo depois da escada —, a **cauda**
ainda renderiza `<valor_cotado>` (`contexto_dinamico.md.j2`, ramo `elif valor_fechado`) dizendo
"…e o horário **não se crava** sobre um valor que ele não topou. O que falta é o sim dele". O
`extrair` roda DEPOIS do `llm`, então o `aceita_valor` que essa pergunta acende só chega no turno
seguinte: no turno da pergunta, a cauda (recency máxima) contradiz o que os ecos corrigidos agora
mandam fazer. O `eixo-b` A3 trata essa rigidez de `CD:7` como o **contrapeso** do risco simétrico
(fechar sobre quem só perguntou), então não a mexi — mas se a corrida paga mostrar a IA respondendo
o horário e esperando um "sim" que já veio, o site a atacar é esse, não os ecos. O material para
gatear existe: `n_contrapropostas` já é coluna materializada (`<ja_fez_contraproposta>`); o ramo
"recusou sem contrapropor" é que não tem flag.

**Prompt caching.** Nenhuma variável Jinja nova; `regras.md.j2` e `reminder.md.j2` seguem sem dado
por-modelo e por-turno (o `nome`/`fase` do lembrete são pré-existentes e o lembrete mora na cauda).
BP_GERAL continua byte-idêntico entre modelas — `test_bp3_render.py` verde.

**Cenários novos para o gate (o `eixo-b` registra "sem gate" para os dois casos).**
- `aceite_pos_teto_horario` (`evals/e2e/cenarios.py`): escada até o teto → "e por 280?" (recusa) →
  **"que horas você pode hoje ?"**. Check `avancou_apos_negociacao_ok`
  (`_avancou_no_horario_apos_negociacao`, `massa.py`): olha SÓ o turno que responde essa pergunta
  (`turnos_cliente` é paralelo a `turnos`) e exige hora concreta, **sem** "não consigo" e **sem**
  número de preço. Olhar só esse turno é o ponto: antes da escada a mesma conduta seria erro.
- `externo_only_pergunta_preco`: modelo `["externo"]`, abertura "oi" + 8 falas de papo antes de
  "quanto é 1 hora?" — os 8 turnos da IA são o que faz o `<lembrete_silencioso>` entrar
  (`_precisa_reminder` ≥ 8 AIMessages), que é a condição do bug A6. Check `sem_local_proprio_ok`
  (`_ofereceu_local_proprio`): nenhuma bolha oferece "no meu local"/"vem aqui"/"te espero aqui".
- Os dois checkers têm teste puro em `tests/unit/test_cenarios_e2e_checks.py` (4 asserções cada
  lado) — um checker que sempre devolve `True` deixaria o cenário decorativo e só apareceria na
  corrida paga.

**Gate. Verde no que é meu:** `make lint` (ruff, clean), `make typecheck` (mypy, 142 arquivos),
`make test` (**1790 passed / 239 skipped needs_db**). **Não rodado, por gastar crédito real (§0):**
- `E2E_AUTORIZADO=1 TEST_DATABASE_URL=<dsn> make gate-conduta ARGS="--por-eixo 2 --max-turnos 12"`
  — o critério 5, contra o baseline `dd4a7e9` (`empurrao_pct 0,0%`, `violacoes_duras 0`).
- `E2E_AUTORIZADO=1 TEST_DATABASE_URL=<dsn> uv run python -m evals.e2e.massa` — os dois cenários
  novos (o `externo_only_pergunta_preco` são 9 turnos, o mais longo da suíte; ~R$0,005 pelo custo
  por turno da corrida de baseline).

Os `needs_db` também não rodaram: o `DATABASE_URL` do `.env` aponta para o self-hosted de
**produção** (§0). Nenhuma asserção `needs_db` toca as frases mexidas.

**Fechamento parcial (driver, 2026-07-30).** Diff conferido. Os dois ecos de recency passaram a
carregar a condição por extenso e **pelos dois ramos** (recusa **ou** contraproposta), e o
"padrão é ele vir até você" saiu do lembrete — confirmei por grep que a frase permanece em
`regras.md.j2` e `persona.md`, os dois sites que carregam o ramo por-modelo e onde a referência
resolve. Os 3 sites do eco "Avanço que equivale a sim" foram verificados: `ferramentas/extracao.py`
já era autocontido com os dois ramos (emenda de 25/07), e `evals/extracao/extrator.py` fica
intocado de propósito (congela a versão órfã para a bancada comparar).

`make lint` ✅ · `make typecheck` ✅ · `make test` ✅ (1790 passed, +2).

Critérios 1–4 cumpridos. **Critério 5 pendente**: `conduta_gate` roda uma vez no fim do lote 03–08.
Ticket segue `claimed` até o checkpoint.

**Risco residual anotado pelo subagente, e que o checkpoint deve olhar:** no turno exato da
pergunta de horário, a cauda ainda renderiza `<valor_cotado>` dizendo que o horário "não se crava
sobre um valor que ele não topou" — o `extrair` roda depois do `llm`, então `aceita_valor` chega um
turno atrasado. O `eixo-b` A3 trata essa rigidez como contrapeso proposital, então não foi mexida.
Se o gate reprovar por aí, o site a atacar é `contexto_dinamico.md.j2`, não os ecos.

Nota de commit: o commit carrega junto WIP do usuário em `regras.md.j2` e `reminder.md.j2` — mesma
decisão registrada no ticket 03.

**Fechado no checkpoint (driver, 2026-07-30).** O `conduta_gate` rodou contra o baseline `dd4a7e9`
e voltou **APROVADO** (`empurrao_pct 0,0%`, `violacoes_duras 0`), com o lote melhorando condução
(`conduziu decidido_rapido` 0% → 50%), desfecho (`bate_desfecho_real` 83,3% → 91,7%) e forma
(`fluxo_jsd` 0,1985 → 0,1896). Números e a comparação das duas corridas em
`.scratch/prompt-refactor/checkpoint-lote-03-08.md`. `Status: resolved`.
