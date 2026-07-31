# 13 — A dúvida sobre as fotos passa a ter um dono só

**What to build:** "é você mesma nas fotos?" aparece literalmente em dois lugares da conduta com respostas diferentes: um manda mandar o book, o outro manda responder com uma fala sem inventar nem confirmar detalhe. O desvio que deveria resolver isso se autoexclui.

Depois deste ticket há uma resposta só para essa pergunta, e o outro site referencia em vez de prescrever. A regra que precisa sobreviver intacta: teste de bot **não** ganha prova espontânea — queimar o book num teste deixa ela sem mídia na hora do fechamento.

**Blocked by:** 01

**Status:** claimed

- [x] "essas fotos são suas?" recebe uma conduta única e determinada — a string literal só existe no `<midia>`, que manda o book; o `<protocolo_disclosure>` referencia
- [x] "é bot?" continua recebendo negação em personagem, sem book e sem prova espontânea — os dois lados do carve-out ficaram intactos (nada foi cortado do `<midia>`)
- [x] pergunta sobre detalhe físico que não está nos blocos continua sem número inventado — o parágrafo sobreviveu inteiro, menos a string mal alocada
- [ ] roteiro cobrindo os três, verde — roteiro escrito (`duvida_das_fotos`), **gate pago pendente de autorização** (comando no `## Comments`)

---

Diagnóstico de origem: `.scratch/prompt-refactor/auditoria-carga-instrucional.md` (com os anexos `inventario-turno.md` e `eixo-*.md`, que trazem as linhas citadas).

> Os anexos citam número de linha; este ticket cita bloco/tag de propósito — os números do `regras.md.j2` envelheceram em 40 min durante a própria auditoria.

---

## Comments

### O que foi feito

1. **Um dono só, por deleção da string mal alocada.** `regras.md.j2`, `<protocolo_disclosure>`,
   parágrafo do *detalhe do anúncio*: a lista de gatilhos era `(altura, manequim, "é você mesma nas
   fotos?")` e virou `(altura, manequim)`. É o que o eixo B (A4) prescrevia — a string não pertence
   a "detalhe do anúncio que não está nos seus blocos"; os exemplos legítimos daquele parágrafo são
   altura e manequim, e a dúvida sobre as FOTOS pertence ao `<midia>`. O **site canônico
   (`<midia>`) não foi tocado**: continua listando as duas formas da pergunta (`"é você mesma nas
   fotos?"`, `"essas fotos são suas?"`) e mandando o book.
2. **O outro site passou a referenciar no ponto do erro.** O desvio do ticket já existia no
   CABEÇALHO do `<protocolo_disclosure>` ("quando a dúvida é sobre as FOTOS, quem responde é o book
   do `<midia>`, não este bloco") — e era ele que **se autoexcluía**, porque o parágrafo que
   reivindicava a string mora dentro do mesmo bloco, seis linhas abaixo. Removida a string, o
   cabeçalho para de se contradizer; e o parágrafo ganhou o ponteiro local ("Duvidar das FOTOS é
   outra coisa, e não se responde aqui: ali quem responde é o book do `<midia>`"). O ponteiro local
   é load-bearing porque a **fala** que sobra ali ("Sou eu mesma amor, bem gata como nas fotos rs")
   é justamente o que atrai a pergunta das fotos por proximidade — referência, não prescrição
   (`agente/CLAUDE.md`, fronteira conduta ↔ referência). Saldo: −25 chars da string, +62 do
   ponteiro.
3. **A fala do parágrafo NÃO mudou** — de propósito. "Sou eu mesma amor, bem gata como nas fotos
   rs" é eco do par de `<armadilhas_de_voz>` do `persona.md` (o `<certo>` da acusação de "perfil
   fake"); reescrevê-la obrigaria a tocar o outro site sem que o ticket peça, e o eixo B já dizia
   que "o 'bem gata como nas fotos' continua valendo como fala de atributo".
4. **O carve-out do "é bot?" ficou intacto.** O eixo C (M4) propunha CORTAR do `<midia>` as duas
   frases ("nunca como resposta a 'é bot?'…" + "Queimar o book num teste de bot…", 219 chars),
   argumentando que um "é bot?" de alta confiança nem chega ao LLM (o `intercept_disclosure`
   responde canned). **Este ticket manda o contrário** ("a regra que precisa sobreviver intacta") e
   o corte foi recusado: o argumento do M4 vale para o "é bot?" que casa
   `_classificador.PADROES_DISCLOSURE`, e é fácil escrever um teste de bot que não casa ("isso aí é
   resposta automática né") — esse chega ao LLM, e é exatamente o turno em que o book queimaria.
   O roteiro novo usa uma variante dessas de propósito.

### Roteiro (critério 4)

Cobertura existente conferida antes de escrever: nenhum cenário cobre dúvida sobre as fotos;
`video_chamada_sem_programa` afirma `enviar_midia` mas pelo gatilho da chamada (issue 12/23);
`disclosure_insistente` cobre "é bot?" só pelo caminho **canned** (a abertura casa o regex, o LLM
nem roda) e não afirma nada sobre mídia. Por isso o roteiro é **novo**, e cobre os três num
cenário só.

`evals/e2e/cenarios.py` → `duvida_das_fotos` (modelo interno, cardápio padrão 1h/400 e 2h/700):

| turno do cliente | o que afirma | check |
|---|---|---|
| "isso aí é resposta automática né kkk" | teste de bot **fora** de `PADROES_DISCLOSURE` (chega ao LLM) → sem prova espontânea | `sem_book_no_teste_ok` |
| "essas fotos são suas mesmo ?" | a dúvida das fotos → **book de uma vez** | `book_na_duvida_ok` (`enviar_midia` 2x+ no MESMO turno) |
| "vc tem quantos de altura ? qual seu manequim ?" | detalhe físico fora dos blocos → sem número | `sem_medida_inventada_ok` |

O teste de bot vem **antes** da dúvida das fotos de propósito: depois do book a flag
`<ja_enviou_book>` proibiria o reenvio sozinha e o check passaria por acidente, medindo a
idempotência em vez da regra.

Checkers em `evals/e2e/massa.py`, os três escopados ao turno que responde a fala-gatilho
(`turnos_cliente` é paralelo a `turnos`) — um book espontâneo mais tarde é legítimo ("quando você
sentir que uma foto fecha"), então um check de conversa inteira reprovaria a conduta certa. Probe
que não rodou (corrida terminou antes) devolve `False` nos três: nada de aprovação silenciosa.
`_RE_MEDIDA_INVENTADA` é de alta precisão — só casa número colado a unidade/rótulo de medida ou
altura em metros ("1,70"/"1m70"/"175 cm"/"60 kg"/"manequim 40"), então preço (400), duração ("1h"),
horário ("22h") e "1.400" do mesmo turno não contaminam.

Seed: nada novo. `harness._seed_midias` já semeia **foto e vídeo aprovados em cada tag**, que é o
que o `enviar_midia` precisa.

### Verificação

- `make lint` ✅ · `make typecheck` ✅ (+ `MYPYPATH=src mypy evals/e2e/{massa,cenarios}.py` ✅, que
  o alvo do Makefile não cobre) · `make test` ✅ **1851 passed, 239 skipped** (sem
  `TEST_DATABASE_URL`: `needs_db` pulados de propósito — o `DATABASE_URL` do `.env` é prod).
- Testes novos, ambos sem crédito e sem DB:
  - `tests/unit/test_duvida_das_fotos_dono_unico.py` — o invariante do ticket lido do BP_GERAL
    renderizado: a string existe no `<midia>` e **não** no `<protocolo_disclosure>`; o disclosure
    aponta pro `<midia>`; o carve-out do "é bot?" e o parágrafo do detalhe físico seguem por
    escrito. (O extrator de bloco é ancorado em início de linha: os dois blocos se citam por nome
    no meio do texto, e um casamento solto engolia o vizinho.)
  - `tests/unit/test_cenarios_e2e_checks.py` — as duas respostas de cada checker novo sobre
    transcritos sintéticos (inclusive os falsos-positivos que o regex de medida precisa recusar).

### Gate pago pendente (NÃO rodado — §0)

Precisa da autorização do dev; com `E2E_AUTORIZADO=1` e `TEST_DATABASE_URL` setados, a partir de
`api/`:

```
uv run python -m evals.e2e.massa --k 1
```

Roda os **20 cenários** (19 + `duvida_das_fotos`) contra o grafo real; o que interessa aqui são
`book_na_duvida_ok`, `sem_book_no_teste_ok` e `sem_medida_inventada_ok` no cenário novo, e os
demais cenários sem regressão. Comparação de referência: `checkpoint-lote-03-08.md`, 2ª corrida,
commit `5ba74ac` (APROVADO, `empurrao_pct 0,0%`, `violacoes_duras 0`).

O `conduta_gate` (`make gate-conduta`) **não** exercita este ticket — ele roda personas do corpus,
não roteiro; só entraria como guarda de não-regressão geral do BP_GERAL, e o diff aqui é de 87
chars num parágrafo.
