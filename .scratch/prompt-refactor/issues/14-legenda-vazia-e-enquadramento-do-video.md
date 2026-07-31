# 14 — O book vai com o enquadramento na bolha e a legenda vazia

**What to build:** a conduta manda mandar foto e vídeo no mesmo turno, manda a legenda das mídias ficar vazia (o mesmo texto na bolha e na legenda chega duplicado ao cliente) e manda o vídeo ir enquadrado como exclusividade. Como o enquadramento é texto e a legenda é vazia, não está dito onde o enquadramento sai.

Depois deste ticket está dito: o enquadramento vive na bolha, junto da linha que acompanha o book, e a legenda continua vazia. O backstop de saída que já valida legenda vazia não muda.

**Blocked by:** 01

**Status:** claimed

- [ ] book de 2-3 fotos + vídeo sai com uma bolha de texto e legendas vazias — conduta reescrita e checker `book_uma_bolha_ok` pronto; **gate pago pendente** (comando no `## Comments`)
- [ ] o enquadramento de exclusividade aparece na bolha, e o vídeo nunca é revelado como acervo — conduta reescrita e checker `enquadramento_na_bolha_ok` pronto; **gate pago pendente**
- [ ] pergunta de quando gravou continua sem data — regra intacta no prompt e checker `sem_data_do_video_ok` pronto; **gate pago pendente**
- [x] backstop de legenda verde — `_legenda_duplica_bolha` (`workers/envio.py`) **não foi tocado**; os 3 testes que o cercam passam

---

Diagnóstico de origem: `.scratch/prompt-refactor/auditoria-carga-instrucional.md` (com os anexos `inventario-turno.md` e `eixo-*.md`, que trazem as linhas citadas).

> Os anexos citam número de linha; este ticket cita bloco/tag de propósito — os números do `regras.md.j2` envelheceram em 40 min durante a própria auditoria.

---

## Comments

### O que foi feito

1. **A bolha única passou a ser o dono do enquadramento.** `regras.md.j2`, bloco `<midia>`,
   2º bullet: era "Junto vai UMA linha sua numa bolha (\"Você vai gostar 🥰\") — e a legenda das
   mídias fica VAZIA"; virou "Junto vai UMA linha sua numa bolha — e é ela que **enquadra o vídeo
   como exclusividade** (\"Gravei um vídeo pra você 🥰\"): uma linha só, cobrindo o book inteiro. A
   legenda das mídias fica VAZIA: … então o **enquadramento sai na bolha, nunca na legenda**". A
   fala ilustrativa mudou junto, de propósito: com uma linha só cobrindo fotos **e** vídeo, o
   exemplo tinha que ser um que enquadrasse ("Você vai gostar 🥰" não enquadra nada). Ela não é eco
   de nenhum outro site — o `persona.md` `<voz>` cita "a linha que acompanha o book" sem transcrevê-la,
   e os outros "você vai gostar" do prompt (`<apresentacao>`, `<desconto>`, o `<exemplo>` da escada
   e dois pares de `<armadilhas_de_voz>`) são autoelogio de venda, não a linha do book.
2. **O parágrafo do vídeo aponta pra ela e para de contradizer o turno.** Era "Vídeo é o **degrau
   seguinte** e vai enquadrado como exclusividade (\"gravei pra você rs\")"; virou "Vídeo é o
   **último item do book** — vai **no mesmo turno, depois das fotos** — e nunca sai cru: quem o
   enquadra como exclusividade é **aquela linha da bolha**". Fecha as duas metades do A9 do
   `eixo-b`: o enquadramento ganhou lugar, e "degrau seguinte" parou de disputar com o "chamando
   `enviar_midia` mais de uma vez **no mesmo turno**" do bullet acima. As duas regras de produto do
   parágrafo (nunca revelar acervo, quando-gravou sem data) ficaram **literalmente intactas**.
3. **Eco de mecânica de campo, o único divergente do R22.** `ferramentas/midia.py`,
   `_DESC_LEGENDA`: dizia "Omitir = sem caption; sobre **quando preencher**, siga sua conduta de
   mídia" — apresentava o preenchimento como opção normal e delegava a regra a um bloco cuja
   instrução é "nunca preencha" (é a "divergência principal" que o `mapa-de-ecos.md` registra em
   R22). Virou "**Deixe de fora**: sua linha de acompanhamento (e o enquadramento do vídeo) vai na
   **BOLHA** de texto do turno, como manda sua conduta de mídia — repetida aqui, ela chega
   duplicada ao cliente". É categoria 1 do `agente/CLAUDE.md` (mecânica de campo: como preencher o
   arg) + referência à conduta, não reescrita dela. Sem esse toque o modelo lê, no MESMO turno, uma
   conduta que manda pôr o enquadramento na bolha e uma DESC que o convida a pôr na legenda.
4. **A escolha do eixo B que NÃO foi seguida.** O A9 propunha "declarar duas bolhas nominalmente
   (uma antes das fotos, uma antes do vídeo)". O ticket manda o contrário — critério 1 diz "**uma**
   bolha de texto" —, então quem cedeu foi o número de falas, não o número de bolhas: uma linha só,
   que já vem enquadrando. Registro aqui porque o anexo é histórico e não pode ser editado.
5. **Nada tocado no que o ticket manda não tocar.** `workers/envio.py` (`_legenda_duplica_bolha`) e
   `workers/_saida_guard.py` (sujo com WIP do dev) não foram abertos para edição; o `<midia>`
   manteve intacto o carve-out do "é bot?" e as duas formas da pergunta das fotos que o ticket 13
   consolidou ali (o teste dele continua verde).

### Roteiro (critérios 1-3)

Cobertura conferida antes: o `duvida_das_fotos` (issue 13) já é o único cenário que **dispara o
book** — por isso ele foi **estendido**, não duplicado. Seguem 20 cenários.

`evals/e2e/cenarios.py` → `duvida_das_fotos`, um turno de cliente novo depois do book:

| turno do cliente | o que afirma | check |
|---|---|---|
| "essas fotos são suas mesmo ?" (já existia) | o book sai com foto(s) ANTES do vídeo, **uma** bolha e legenda vazia em todas as mídias | `book_uma_bolha_ok` |
| idem | a bolha **enquadra** o vídeo como exclusividade e não entrega o acervo | `enquadramento_na_bolha_ok` |
| "e esse vídeo você gravou quando ?" (**novo**) | a pergunta de quando gravou não recebe data | `sem_data_do_video_ok` |

Detalhes que o checker precisa e que não são óbvios:

- `_book_em_uma_bolha` lê `tool_args` (paralelo a `tool_calls` por construção, `harness._coletar_tools`)
  e filtra por **nome** da tool — todo turno real leva `registrar_extracao` junto. `tipo` ausente é
  **foto** (default da tool), então omitir o campo não vira vídeo por acidente; `tipos.index("video") == 0`
  reprova o vídeo antes da foto.
- `_RE_DATA_DO_VIDEO` só casa **passado** ("ontem", "semana passada", "faz uns dias", "em março"):
  a resposta prescrita ("agora", "hoje de manhã") e a volta pro encontro no mesmo turno ("Te espero
  amanhã") são presente/futuro e não podem contaminar. Dia-da-semana ficou **fora** de propósito —
  "no sábado" é proposta de encontro tão plausível quanto data de gravação.
- `_RE_REVELA_ACERVO` é o guarda de negação do `enquadramento_na_bolha_ok`: a fala certa e a errada
  compartilham o verbo ("Gravei pra você" × "Gravei pra você, é um vídeo antigo"), então exigir só
  o enquadramento aprovaria a revelação.
- Probe que não rodou (corrida terminou antes) devolve `False` nos três — sem aprovação silenciosa.

Seed: nada novo. `harness._seed_midias` já semeia **foto e vídeo aprovados em cada tag**.

### Verificação

- `make lint` ✅ · `make typecheck` ✅ (+ `MYPYPATH=src mypy evals/e2e/{massa,cenarios}.py
  tests/unit/test_{cenarios_e2e_checks,enquadramento_do_video_na_bolha}.py` ✅) ·
  `make test` ✅ **1857 passed, 239 skipped** (sem `TEST_DATABASE_URL`: `needs_db` pulados de
  propósito — o `DATABASE_URL` do `.env` é prod).
- Critério 4 (backstop de legenda): `pytest tests/integracao/test_enviar_turno.py -k legenda` ✅
  **3 passed** — `test_legenda_igual_a_bolha_e_dropada`, `test_legenda_distinta_da_bolha_preservada`,
  `test_legenda_com_rastro_e_dropada_sem_derrubar_a_midia`. Nenhum arquivo de envio foi editado.
- Testes novos, ambos sem crédito e sem DB:
  - `tests/unit/test_enquadramento_do_video_na_bolha.py` — o invariante lido do BP_GERAL
    renderizado: a bolha única enquadra, o parágrafo do vídeo aponta pra ela, a legenda continua
    VAZIA nos **dois** sites (prompt + `_DESC_LEGENDA`), "degrau seguinte" sumiu e acervo/data
    seguem proibidos.
  - `tests/unit/test_cenarios_e2e_checks.py` — as duas respostas dos três checkers novos sobre
    transcritos sintéticos (inclusive os falsos-positivos que os regexes precisam recusar).

### Gate pago pendente (NÃO rodado — §0)

Precisa da autorização do dev; com `E2E_AUTORIZADO=1` e `TEST_DATABASE_URL` setados, a partir de
`api/`:

```
uv run python -m evals.e2e.massa --k 1
```

Roda os 20 cenários contra o grafo real (1 `ainvoke` por turno = crédito DeepSeek). O que interessa
aqui são `book_uma_bolha_ok`, `enquadramento_na_bolha_ok` e `sem_data_do_video_ok` no
`duvida_das_fotos` — mais os checks da issue 13 no mesmo cenário, que ganharam um turno de cliente
no meio —, e os demais cenários sem regressão. Referência: `checkpoint-lote-03-08.md`, 2ª corrida,
commit `5ba74ac` (APROVADO, `empurrao_pct 0,0%`, `violacoes_duras 0`).

O `conduta_gate` (`make gate-conduta`) não exercita este ticket (roda personas do corpus, não
roteiro, e nenhuma delas pede foto); entraria só como guarda de não-regressão geral do BP_GERAL.
