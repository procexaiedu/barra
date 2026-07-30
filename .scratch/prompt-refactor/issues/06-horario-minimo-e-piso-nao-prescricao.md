# 06 — O horário mínimo volta a ser piso, não a proposta obrigatória

**What to build:** a conduta afirma que o primeiro horário que ela oferece **é** o horário mínimo. Outra cláusula, e a cauda, mandam a proposta cair dentro da janela vaga que o cliente deu. Com mínimo às 14h e o cliente dizendo "de noite", ela propõe um horário que ele acabou de excluir.

O desempate correto — o mínimo é piso, não proposta — não está escrito em lugar nenhum: vive só no nome da variável. Depois deste ticket está escrito.

**Blocked by:** 01

**Status:** claimed

- [x] cliente que diz "de noite" com mínimo à tarde recebe proposta à noite
- [x] cliente que não deu janela nenhuma continua recebendo o piso como primeiro horário
- [x] nenhuma proposta cai abaixo do piso
- [ ] cenário de janela vaga do `conduta_gate` verde contra o baseline de 01

---

Diagnóstico de origem: `.scratch/prompt-refactor/auditoria-carga-instrucional.md` (com os anexos `inventario-turno.md` e `eixo-*.md`, que trazem as linhas citadas).

> Os anexos citam número de linha; este ticket cita bloco/tag de propósito — os números do `regras.md.j2` envelheceram em 40 min durante a própria auditoria.

---

## Comments

**O que mudou — um parágrafo, um site.** `agente/prompts/regras.md.j2`, bloco `<agenda>`,
parágrafo "Cedo demais". A prescrição incondicional ("**o primeiro horário que você oferece é** o de
`<horario_minimo>`") virou piso + default explícito:

> `<horario_minimo>` é o PISO da sua agenda, não a sua proposta pronta: nada antes dele, nunca um
> minuto quebrado inventado. **Sem hora dele na mesa**, o piso é o primeiro horário que você
> oferece, dito em hora leve e redonda; **com a hora ou a janela dele na mesa** ("de noite", "final
> do dia", "mais tarde"), a sua proposta cai dentro do que ELE pediu — o piso só volta a ser a sua
> oferta quando o que ele pediu é antes dele.

A frase do WIP do usuário sobre arredondar horário quebrado **para CIMA** ficou intacta, no mesmo
parágrafo, logo depois — ela responde a outra pergunta (como dizer a hora), não a esta (qual hora).

**Onde a regra mora (§"Graus de liberdade").** O desempate é conversacional, não aritmético: o que
"de noite" quer dizer é NLU, e a exatidão que existe aqui — o piso em si — **já** é determinística
(`prepare_context` calcula `horario_minimo` = arredonda_acima(agora + buffer) dentro da
Disponibilidade). O que faltava era só a semântica da variável dita em prosa. Por isso prosa, e por
isso no BP_GERAL: a regra não é condicional ao **estado do turno** (vale sempre que houver janela
dele), então não vai para a cauda. Nenhuma variável Jinja nova; BP_GERAL segue byte-idêntico entre
modelos (`test_bp3_render.py` verde).

**Sites conferidos, e por que não mexi neles:**
- `<cotacao>` ("Ele já deu uma janela vaga → a sua proposta cai DENTRO da janela dele, não antes")
  e a cauda `<ja_sondou_o_dia>` (`contexto_dinamico.md.j2`) — são o **lado que estava certo** da
  tensão; a auditoria (§3 item 1.6) e o `eixo-b` B1 dizem que quem cede é o parágrafo do `<agenda>`.
  Considerei pendurar nelas um clamp ("nunca antes do `<horario_minimo>`") e **recusei**: o piso já
  é afirmado duas vezes no BP_GERAL (o parágrafo novo e o `<fechamento>`, "sempre um horário válido
  da sua `<agenda>` (respeitando `<horario_minimo>`)") e tem backstop determinístico (abaixo) —
  seria carga instrucional nova num refactor que existe para tirá-la.
- **Âncora de tempo `<agenda hoje=… agora=…>`** (eco de 4 sites, `agente/CLAUDE.md`): intocada.
  Não renomeei tag nem atributo, e o nome `<horario_minimo>` continua idêntico nos sites que o
  citam nominalmente (`contexto_dinamico.md.j2`, o `ToolException` de `AntecedenciaInsuficiente` em
  `ferramentas/extracao.py`, `regras.md.j2`). Nenhum deles passou a mentir: o handler manda ancorar
  no piso exatamente no caso em que o parágrafo novo também manda (o que ele pediu é antes dele).
- **Escala léxica de dureza**: nenhum `NUNCA` em caps novo. O único caps é `PISO` (uma vez), no
  mesmo idioma de ênfase semântica que o arquivo já usa (`DENTRO`, `FECHAMENTO`, `MAX`) — o ticket
  19 tira caps de proibição banalizada, não ênfase de substantivo.

**Critério a critério.**
1. *"de noite" com mínimo à tarde → proposta à noite* — o ramo "com a janela dele na mesa" agora
   está escrito no site que afirmava o contrário; a cauda e o `<cotacao>` deixam de ser contraditos.
   Certificação empírica só na corrida paga (cenário novo abaixo).
2. *sem janela nenhuma → piso como primeiro horário* — o ramo "sem hora dele na mesa" preserva a
   conduta antiga por escrito, e o trilho determinístico que a implementa continua igual: o
   fallback #4 da extração (urgência imediata sem horário assume o `horario_minimo`) segue verde
   em `tests/integracao/test_registrar_extracao.py::test_imediato_sem_horario_assume_horario_minimo`
   e `test_extrair_inline.py::test_horario_minimo_propaga_pelo_state`.
3. *nenhuma proposta abaixo do piso* — "nada antes dele" na prosa **e** backstop determinístico
   intacto: reserva antes do piso levanta `AntecedenciaInsuficiente` (`dominio/agenda/service.py`),
   que vira `ToolException` mandando ancorar no `<horario_minimo>` e (com `auto_reoferta` ON) volta
   ao nó `llm` para reofertar. Cobertura: `tests/agente/test_antecedencia_horario_minimo.py`.
4. *cenário de janela vaga verde* — **pendente**, gasta crédito (§0). Cenário e checker escritos:
   - `janela_vaga_de_noite` (`evals/e2e/cenarios.py`): interno, **sem regra de disponibilidade** de
     propósito (modelo sem regra é reservável sempre → o `<horario_minimo>` existe qualquer que
     seja a hora da corrida), abertura pedindo preço + "pode ser de noite".
   - Check `dentro_da_janela_ok` (`_propos_dentro_da_janela`, `evals/e2e/massa.py`): **relacional**,
     não afirma número — o piso é ~agora+30min e muda com a hora da corrida. Olha só o turno que
     responde à fala vaga (`turnos_cliente` é paralelo a `turnos`), exige ao menos uma hora na
     faixa dele (19–23 para "de noite") e **nenhuma** na faixa que ele excluiu (6–18). Duração
     ("1h", "2h") cai fora das duas faixas e não contamina nenhum lado; janela sem faixa mapeada
     levanta `ValueError` em vez de passar em silêncio.
   - Teste puro do checker: `tests/unit/test_cenarios_e2e_checks.py` (6 asserções, incluindo o bug
     literal do ticket — "Consigo às 14h" depois de "de noite" reprova).

**Gate. Verde no que é meu:** `make lint` (ruff, clean) · `make typecheck` (mypy, 142 arquivos) ·
`make test` (**1791 passed / 239 skipped needs_db**, +1 vs o ticket 05).

**Não rodado, por gastar crédito real (§0) — autorização do humano:**
- `E2E_AUTORIZADO=1 TEST_DATABASE_URL=<dsn> uv run python -m evals.e2e.massa` — o cenário novo
  (3 turnos, o mais curto da suíte).
- `E2E_AUTORIZADO=1 TEST_DATABASE_URL=<dsn> make gate-conduta ARGS="--por-eixo 2 --max-turnos 12"`
  — critério 4 contra o baseline `dd4a7e9` (`empurrao_pct 0,0%`, `violacoes_duras 0`).

Os `needs_db` também não rodaram: o `DATABASE_URL` do `.env` aponta para o self-hosted de
**produção** (§0). Nenhum teste novo precisa de DB.

**Nada revertido do WIP do usuário**; nada commitado.

**Fechamento parcial (driver, 2026-07-30).** Diff conferido: um site de conduta (`regras.md.j2`,
bloco `<agenda>`, parágrafo "Cedo demais"). A prescrição virou piso + default explícito, e o WIP do
usuário na mesma região (arredondar horário quebrado para CIMA) ficou intacto — responde a outra
pergunta (como dizer a hora, não qual hora). Nenhuma variável Jinja nova; a tag `<horario_minimo>`
não foi renomeada, então os 4 sites do eco da âncora de tempo seguem coerentes.

`make lint` ✅ · `make typecheck` ✅ · `make test` ✅ (1791 passed, +1).

Critérios 1–3 cumpridos. **Critério 4 pendente**: `conduta_gate` roda uma vez no fim do lote 03–08.

Anotação para o ticket 19: a redação nova introduz um `ELE` em caps (ênfase de contraste, não
proibição) além do `PISO`. Entra na varredura do 19 junto com os outros 151 — não é regressão, mas
é uma linha a mais para aquele passe.
