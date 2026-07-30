# 23 — Menage e vídeo chamada ganham roteiro, antes de alguém cortar a prosa deles

**What to build:** os tickets 11 e 12 movem ~2.800 chars de conduta da prosa para tag de cauda, e
hoje **nenhum eval exercita as duas condutas**. A auditoria é explícita: "sem gate — nenhum eval
exercita menage. Precisa roteiro novo ANTES". Este ticket escreve esse roteiro. Ele **não corta
nada de prompt** — ao contrário, ele é a rede que torna o corte auditável.

O que falta, exatamente:

- **Menage** — não há cenário nenhum. Precisa dos **dois ramos**: modelo **com** a seção "Por
  pessoa" no cardápio (a IA cota o dobro do pacote) e modelo **sem** a seção (a IA não oferece
  menage nenhum). O ramo "sem" é o que o ticket 11 vai converter em tag, e é o que não existe.
- **Vídeo chamada** — o cenário existente roda uma modelo **com** o programa na tabela. O ramo que
  o ticket 12 precisa é o oposto: modelo **sem** o programa, que nunca deve oferecer chamada e
  resolve o pedido de prova com foto.

**Blocked by:** None — can start immediately.

**Status:** claimed

- [x] cenário de menage, ramo COM a seção "Por pessoa": a IA cota o **dobro do pacote** quando o
      cliente traz uma segunda pessoa — não o preço-hora dos fetiches-ato (ADR 0035)
- [x] cenário de menage, ramo SEM a seção: a IA **não oferece nem cota** menage, e o pedido é
      recusado de forma aberta
- [x] cenário de vídeo chamada, ramo SEM o programa na tabela: a IA **não oferece chamada nenhuma**,
      e o pedido de prova de humanidade se resolve com **foto**, não com chamada
- [x] cada cenário tem checker **determinístico** em `evals/e2e/massa.py` e teste puro em
      `tests/unit/test_cenarios_e2e_checks.py` — um checker que sempre devolve `True` torna o
      cenário decorativo, e isso só apareceria na corrida paga
- [x] os checkers são exercitados nos **dois sentidos**: aceitam a fala certa e **reprovam** a
      errada (o padrão que o ticket 22 usou para o carimbo)
- [ ] a corrida do `evals.e2e.massa` roda os cenários novos **e** os cinco pendentes dos tickets
      03–08 (`abertura_oi_seco`, `segunda_venda_cotado`, `janela_vaga_de_noite`,
      `aceite_pos_teto_horario`, `externo_only_pergunta_preco`) — corrida paga, autorização do humano

---

Diagnóstico de origem: `.scratch/prompt-refactor/auditoria-carga-instrucional.md`, §3 Etapa 5
(itens 5.1 e 5.2), que marca os dois como "sem gate" e manda escrever roteiro antes. Vocabulário de
domínio de **Menage** e **Vídeo chamada** está no `CONTEXT.md`; a mecânica de preço "por pessoa" é o
ADR 0035, e o remoto é o ADR 0021 (com o Pix antecipado no ADR 0029).

> Ticket aberto pelo driver, fora da numeração original da auditoria, por decisão do humano na
> parada obrigatória que precede o 11 e o 12.

## Comments

Aberto em 2026-07-30. A razão de ser um ticket separado, e não parte do 11 e do 12: um roteiro
escrito na mesma passada que a mudança que ele deveria julgar tende a ser escrito **para passar**.
Aqui ele nasce antes, contra o comportamento atual — que é o comportamento que os cortes têm que
preservar.

Consequência prática: ao terminar este ticket, os cenários novos devem passar **contra a prosa de
hoje**, sem nenhuma edição de `regras.md.j2`. Se algum não passar, o achado é sobre a conduta atual
e vira ticket próprio — não se conserta o roteiro para caber.

---

### 2026-07-30 — roteiro escrito (nenhum byte de prompt tocado)

**O que entrou** (3 cenários, 3 checkers, 3 testes de checker, 1 seed):

- `evals/e2e/cenarios.py` — `menage_com_secao`, `menage_sem_secao`, `video_chamada_sem_programa`;
  flags `menage_dobra_o_pacote: tuple[int,int]`, `menage_fora_do_cardapio: list[int]`,
  `nao_deve_oferecer_video_chamada: bool`. Total de cenários: **16 → 19**.
- `evals/e2e/massa.py` — `_cotou_dobro_do_pacote`, `_recusou_menage_sem_cotar`,
  `_ofereceu_video_chamada`, ligados em `_avaliar_cenario` (`dobrou_o_pacote_ok`,
  `recusou_menage_ok`, `sem_oferta_de_chamada_ok`).
- `tests/unit/test_cenarios_e2e_checks.py` — 3 testes novos, 18 asserts, os dois sentidos em cada.
- `evals/harness.py` — `_seed_fetiche` + `spec["fetiches"]` em `_seed_modelo`. **Era o que
  faltava**: o harness nunca semeou fetiche, então TODA modelo dos cenários rodava com
  `<fetiches> (sem fetiches cadastrados)` — sem isso o ramo COM era irrepresentável.

**Decisões de projeto do roteiro, e por que elas importam:**

1. **Pacote de 2h no ramo COM (R$700), nunca 1h.** Em 1h o dobro e o preço-hora dão o mesmo
   número (ADR 0035) — um cenário de 1h passaria sem distinguir regime nenhum. O checker **levanta
   `ValueError`** se receber `horas < 2`, e o teste prova isso: erro de cenário não pode virar
   check que passa em silêncio.
2. **A modelo COM tem as DUAS seções** (`Inversão` ato + `Menage` por-pessoa). O bloco renderizado
   dela traz `+R$350 / R$1.050` (regime-ato) **e** `R$1.400` (por-pessoa) para o mesmo pacote de
   2h. Logo o checker não testa "inventou número", testa **escolha de linha da tabela** — que é
   exatamente o que o ADR 0035 corrige. Exige 1400 e reprova 350/1050 na resposta ao pedido dele.
3. **O ramo SEM checa três coisas** (recusa aberta no turno do pedido + nenhum dobro em turno
   NENHUM + nenhuma promessa de amiga). Recusar e cotar o dobro dois turnos depois é o mesmo erro,
   só mais tarde — está no teste. E a recusa de *indicar* outra ("não indico não amor",
   `<fora_do_cardapio>`) **não** conta como promessa de amiga: também está no teste, senão o
   checker reprovaria a conduta correta.
4. **A oferta de chamada é checada por bolha, com guarda de negação.** A recusa certa ("Não faço
   chamada amor") contém literalmente as palavras da oferta ("faço … chamada"); sem o guarda, o
   checker reprovaria justamente a conduta que o ticket quer preservar. Os dois casos estão no
   teste. O lado positivo do cenário (a prova sai em **foto**) é o `tool_esperada="enviar_midia"`
   que a infra já avalia — não precisou de checker novo.
5. **`_seed_fetiche` falha alto, não decora.** `cobra_por_pessoa` é do catálogo GLOBAL (ADR 0035):
   se "Menage" já existir em `barravips.fetiches` com a flag diferente da que o cenário pede, o
   seed levanta `RuntimeError` em vez de renderizar o bloco errado — um cenário de menage rodando
   contra o regime-ato passaria despercebido. O seed **nunca** dá `UPDATE` no catálogo curado.

**Leitura da prosa de hoje (estático, não é o veredito):** os três cenários foram escritos contra
o que `regras.md.j2` já diz, e a prosa cobre os três — `<menage>` 1º parágrafo (ramo SEM: "'Não
faço amor', sem cotar, sem dobrar nada e sem prometer amiga") e 2º/3º (ramo COM: "DOBRA o pacote …
o total dobrado, nunca o '+Extra' dos atos"); `<tipos_de_encontro>` parágrafo da vídeo chamada
("NÃO estando lá … o pedido de prova se responde com foto") com eco em `<protocolo_disclosure>` e
`<midia>`. Ou seja: **nenhuma edição de prompt foi necessária e nenhuma foi feita** — nem em
`persona.md`, `regras.md.j2`, `reminder.md.j2` ou na cauda. O veredito de verdade (o agente
obedece a essa prosa?) só sai na corrida paga; se algum dos três reprovar lá, o achado é sobre a
conduta atual e vira ticket próprio, exatamente como este ticket estabelece.

**Verificação offline:** `make lint` verde, `make typecheck` verde (142 arquivos), `make test`
verde (1832 passed / 239 skipped — os skipped são `needs_db`, não rodados: o `DATABASE_URL` do
`.env` aponta para o prod self-hosted, §0). O bloco `<fetiches>` das duas modelos de menage foi
renderizado offline via `persona.render_fetiches` para conferir que os números do cenário são os
que o prompt de fato mostra.

**Gate pago pendente — autorização do humano (§0):**

```
cd api && E2E_AUTORIZADO=1 TEST_DATABASE_URL=... uv run python -m evals.e2e.massa --k 1
```

Roda os **19** cenários (a corrida em massa não filtra por nome). **8 nunca foram exercitados numa
corrida real**: os 5 pendentes dos tickets 03–08 (`abertura_oi_seco`, `segunda_venda_cotado`,
`janela_vaga_de_noite`, `aceite_pos_teto_horario`, `externo_only_pergunta_preco`) e os 3 deste
ticket (`menage_com_secao`, `menage_sem_secao`, `video_chamada_sem_programa`). Pré-requisito de
banco já satisfeito: `fetiches.cobra_por_pessoa` está fisicamente aplicada no prod self-hosted
(introspecção de 25/07) e "Casal"/"Menage" estão marcados `true` — se não estivessem, o seed
falharia alto em vez de rodar o cenário errado.

**Fica em aberto (fora do escopo deste ticket, para quem for escrever o 11):** o ramo (b) do
`<menage>` — cliente pede que **ela** traga uma amiga → "Deixa eu ver com ela" + `escalar(outro)`
— continua sem cenário. O ticket pediu os dois ramos COM/SEM da seção, e é o que está aqui; o
ramo da amiga é uma escalada, não uma cotação, e mereceria cenário próprio com
`tool_esperada="escalar"`.
