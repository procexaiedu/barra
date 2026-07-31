# 17 — Só o sim que crava licencia o verbo confirmar

**What to build:** a conduta usa "confirmar" com dois gatilhos diferentes: um site libera "Posso confirmar às 22h ?" depois do sim ao **valor**, outro proíbe "confirmar" antes do sim ao **horário**. São dois sins distintos licenciando o mesmo verbo, e um dos exemplos modela o lado oposto do que a regra do verbo prescreve — o que é grave, porque a auditoria mostrou que exemplo concreto vence prosa.

Depois deste ticket está dito qual sim licencia o quê, e o exemplo deixa de modelar o contrário. A regra que não pode se perder: proposta de horário sempre termina em "?", senão ele lê promessa de retorno e o encontro morre esperando.

**Blocked by:** 01, 06

**Status:** claimed

- [x] aceitou o valor e ainda não deu hora: ela oferece o horário, não o dá por confirmado
- [x] aceitou o horário: aí sim o verbo de confirmação, e ela pede o nome
- [x] o exemplo da conduta modela o mesmo verbo que a regra prescreve
- [x] toda proposta de horário sai com "?"
- [ ] `conduta_gate` verde contra o baseline de 01

---

Diagnóstico de origem: `.scratch/prompt-refactor/auditoria-carga-instrucional.md` (com os anexos `inventario-turno.md` e `eixo-*.md`, que trazem as linhas citadas).

> Os anexos citam número de linha; este ticket cita bloco/tag de propósito — os números do `regras.md.j2` envelheceram em 40 min durante a própria auditoria.

---

## Comments

### A regra, agora escrita

**Só o sim à HORA licencia o verbo de confirmação; o sim ao VALOR abre a proposta, que oferece e
acaba em "?".** É a fronteira de domínio do `CONTEXT.md` (**Horário desejado** × **Horário
combinado**) dita em prosa: o sim ao valor não crava horário nenhum, então nada ali pode ser dito
como combinado; o que promove a `Aguardando_confirmacao` (e cria o bloqueio prévio) é o sim dele à
hora — e é exatamente aí que o verbo vira dela.

O desempate segue o veredito do `eixo-b-contradicoes-vivas.md` A7 ("quem cede é a *fala de exemplo*
de `R:90`, não a regra dela — 'proposta fechada, não pergunta aberta' se cumpre com 'Consigo às 22h,
fecha ?'"). Nenhuma taxonomia nova foi inventada.

### Sites tocados (bloco/tag, nunca linha)

Levantamento primeiro, edição depois. O verbo e os dois "sins" aparecem em ~20 lugares entre
`prompts/`, `ferramentas/` e a cauda; a tabela traz os que **mudaram** (14, contando as 3 linhas
agrupadas e mais o `<porque>` do exemplo e o `persona.md`, tratados logo abaixo), e o parágrafo
seguinte os que foram conferidos e ficaram como estavam:

| site | o que era | o que é |
|---|---|---|
| `regras.md.j2` `<cotacao>`, "o verbo diz a fase" — **canônico** | "antes do sim dele você OFERECE… só depois do sim" (referente de "o sim" indefinido) | nomeia o sim: "o sim dele à hora, nunca o sim ao preço… inclusive depois de ele topar o valor" |
| `<cotacao>`, a regra do "?" | ilustrada só pela falha ("Posso confirmar às 18h") | ganha a forma **positiva** com o verbo certo ("Consigo às 22h ?"); a falha fica, agora rotulada como erro duplo (verbo + "?") |
| `<cotacao>`, `<ja_sondou_o_dia>` | "…proposta concreta ou 'Confirmado ?'" | o "Confirmado ?" ganha a condição que era posicional: "quando a hora já veio dele" |
| `<fechamento>`, "Ele topou o valor" — **o item grave** | prescrevia **"Posso confirmar às 22h ?", "Vamos confirmar 14h amor ?"** | "Ele topou o valor **e ainda não deu hora**… o verbo é o de oferta, porque quem crava é o sim dele: 'Consigo às 22h, fecha ?', 'Posso às 14h amor, fecha ?' … sempre com '?'" |
| `<fechamento>`, último item | "Confirmado, pergunte 'Qual seu nome amor?'" (sem dizer confirmado *do quê*) | "Ele topou a hora ('fechou 22h', 'pode ser', 'isso'): é esse sim que crava, e só aqui entra o verbo de confirmação — uma palavra e já pergunte o nome" |
| `<nucleo>` 5 · `<nucleo_final>` · `<agenda>` (reoferta) | "enquanto ele não disse sim" / "até ele dizer sim" / "depois do sim dele" | "enquanto ele não aceitar a hora" / "até ele aceitar a hora" / "depois de ele aceitar a hora" |
| `reminder.md.j2` (eco condensado) | "Antes do sim dele o empurrão OFERECE; 'confirmar' é depois do sim" | "Enquanto a hora não vier dele o empurrão OFERECE…, **mesmo com o valor já topado**" |
| `judge_pos_envio.md` (autocontido, outro contexto de LLM) | "antes do sim do cliente ela OFERECE" | "o sim que conta é o da hora, não o do preço… mesmo com o valor já topado" |
| `contexto_dinamico.md.j2` `<hora status=…>` (cauda) | "confirme o horário com ele antes de tratar como combinado" | "ofereça esta hora a ele e espere o sim…" — a cauda deixa de pôr o verbo proibido na fase que o proíbe |
| `_PROXIMO_PASSO["Qualificado"]` (`dominio/atendimentos/service.py`) | "**confirmar** os detalhes e seguir pro próximo passo" | "**combinar** o horário com ele e seguir…" — em `Qualificado` o que falta É a hora (é ela que promove a `Aguardando_confirmacao`), e "combinar" é o verbo do domínio (**Horário combinado**), que pressupõe o sim dele |

**O exemplo (critério 3).** O `<exemplo classe="horário pedido cai em bloqueio">` já modelava o
lado certo — reoferta "Pode ser às 22h ?", ele "fechou 22h", ela "Confirmado" + nome. Era o
`<fechamento>` que contradizia o exemplo, não o contrário; agora os dois dizem a mesma coisa e o
`<porque>` do exemplo nomeia qual sim ("só depois que ele topa a hora vem a confirmação").

**Sites conferidos e NÃO tocados:** `<recuo_pos_objecao>` ("'fechamos'/'confirmado' não existem
depois de um 'ainda não'" — outro gatilho, coerente); `<fechamento>` "Dado ambíguo" ("o sim" ali é
o sim à proposta dela, sem ambiguidade); `<desconto>`, o parágrafo do avanço-que-equivale-a-sim
(define o aceite do VALOR, não usa o verbo — mexer nele arrastaria o eco autocontido do
`aceita_valor` em `ferramentas/extracao.py` sem necessidade); `_DESC_HORARIO` da extração, que já
modela a forma certa ("se a hora foi VOCÊ que propôs ('consigo às 22h, fecha ?') e o cliente
confirmou"); `persona.md` `<armadilhas_de_voz>` ("Consigo às 14h, fecha ?" já era o lado certo).
Em `persona.md` `<voz>` só a fala ILUSTRATIVA da regra do "?" trocou ("Posso confirmar ?" →
"Consigo às 22h ?"): a bolha modelo deixa de ser uma que a conduta agora reserva para depois do sim
— **a falha literal continua ali**, porque é ela que justifica a regra.

### Dois acoplamentos que mandaram na escolha das falas

1. **`_PEDE_FECHAMENTO` (`agente/_disciplina.py`)** — o detector que dá sentido ao "não" isolado do
   cliente (rebaixa `aceita_valor`, #19) só reconhece a bolha antecedente pelo vocabulário
   *confirmar/fecha/fechamos/marcado/reservo* + "?". As duas falas que saíram do `<fechamento>`
   tinham "confirmar"; por isso as duas que entraram carregam **"fecha ?"** — sem isso o detector
   ficaria cego em silêncio, que é o que o comentário dele avisa ("mudou a fala de lá, revise").
2. **`restaurar_interrogacao_proposta` (`workers/_saida_guard.py`)** — backstop determinístico do
   "?" (incidente #34). Segue intocado e continua valendo: a mudança de prosa reduz a chance de a
   IA emitir o molde, não substitui o guard. Vale a regra transversal da auditoria (§"o que fica
   intocado"): cláusula com backstop determinístico é a que menos se corta — a prosa do "?" ficou.

### Onde a regra mora (§"Graus de liberdade")

Conversacional, muitos caminhos válidos → prosa. Não há exatidão determinística a extrair aqui: o
que *é* determinístico (a proveniência da hora — `horario_evidenciado`) já existe e já alimenta a
cauda; o que faltava era a semântica do verbo. Nada por-modelo nem por-turno entrou no BP_GERAL
(zero variável Jinja nova; `test_bp3_render.py` verde), e o único acréscimo de cauda foi
reescrita de texto já existente. **Nenhum caps novo** — a distinção hora×preço é dita por extenso
de propósito (ticket 19).

### Roteiro e2e (escrito, NÃO rodado — gasta crédito)

Estendi `aceite_pos_teto_horario` em vez de duplicar: ele já entra exatamente no estado do ticket
(escada rodada, "que horas você pode hoje ?" = o sim ao valor sem hora na mesa). Ganhou **uma** fala
de cliente — "pode ser, fechou" — e o campo `os_dois_sins`, que é um par de propósito: os dois lados
se medem no mesmo cenário, em turnos adjacentes, porque o erro é usar o verbo de um no momento do
outro. Dois checks em `evals/e2e/massa.py`:

- `ofereceu_a_hora_ok` (`_ofereceu_a_hora_sem_dar_por_combinada`): no turno que responde ao sim ao
  valor — hora concreta na mesa, **sem** o verbo de confirmação, e "?" em alguma bolha (o corte por
  bolha, não pelo fim do turno, porque o chunker parte "Consigo às 22h" / "fecha ?" com facilidade).
- `confirmou_e_pediu_o_nome_ok` (`_confirmou_a_hora_e_pediu_o_nome`): no turno seguinte — fechou
  (confirmação curta ou o verbo) **e** pediu o nome. A lista de confirmação é aberta ("Confirmado",
  "Perfeito", "Ok"): o que se cobra é que ela FECHE, não uma palavra específica.

Teste puro dos dois checkers (sem DB, sem crédito): `tests/unit/test_cenarios_e2e_checks.py`, 12
asserções incluindo os 4 moldes literais do bug ("Posso confirmar às 22h ?", "Vamos confirmar 14h
amor ?", "Fechamos 22h então ?", "Confirmado 22h amor") e a proposta sem "?".

### Gate

Verde no que é meu: `make lint` (ruff) · `make typecheck` (mypy, 142 arquivos) · `make test`
(**1881 passed / 239 skipped `needs_db`**, +2 meus). Os `needs_db` não rodaram: o `DATABASE_URL` do
`.env` aponta para o self-hosted de **produção** (§0); nada que mudei precisa de DB.

**Gates pagos pendentes (NÃO rodados — §0, só o humano autoriza):**

```
cd api && E2E_AUTORIZADO=1 TEST_DATABASE_URL=… make gate-conduta ARGS="--por-eixo 2 --max-turnos 12"
cd api && E2E_AUTORIZADO=1 TEST_DATABASE_URL=… uv run python -m evals.e2e.massa
```

O primeiro é o critério 5, contra o baseline de 01 (referência da última corrida aprovada:
`.scratch/prompt-refactor/checkpoint-lote-03-08.md`, 2ª corrida, commit `5ba74ac` — `empurrao_pct
0,0%`, `violacoes_duras 0`). O segundo lê
`aceite_pos_teto_horario.{ofereceu_a_hora_ok, confirmou_e_pediu_o_nome_ok, avancou_apos_negociacao_ok}`
e confere que os outros 20 cenários não regrediram (o runner não filtra por cenário). ⚠️ Como nos
tickets 13–16, os checks novos nasceram junto com a mudança: a primeira corrida é baseline e gate ao
mesmo tempo.

### Achado adjacente, registrado e não corrigido

O `<porque>` do `<exemplo classe="cotação com intenção de marcar já na mesa">` ainda diz que o turno
"termina no empurrão **sim/não**" — rótulo que o `agente/CLAUDE.md` registra como **retirado dos
ecos em 30/07**, justamente porque proibia a pergunta de horário; e o exemplo que ele descreve
termina em "Seria que horas amor ?", que não é sim/não. É resíduo do mesmo passe do ticket 05, não
do verbo — não mexi (§3, "mencione, não delete").

**Nada revertido do WIP do usuário** (`judge_pos_envio.md` recebeu edição cirúrgica em linhas fora
do diff dele — conferido com `git diff`); nada commitado.
