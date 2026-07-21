---
status: accepted
---

# ADR-0034 — Piloto de produção assistida: supervisão automatizada, rollback e graduação

> **Nota (2026-07-21):** este ADR *registra* decisões tomadas em grilling com o dev em
> **2026-07-02** e já implementadas na `main` desde então. Ele não decide nada novo — existe
> porque os limiares e critérios viviam só em comentário de código (`workers/rollback_watch.py`:
> "Limiares acordados no plano do piloto (grilling 02/07) — mudá-los é decisão de plano, não
> tuning") e num plano que nunca entrou no repo. Sem esta casa, ninguém consegue conferir se o
> código ainda corresponde ao combinado — que foi exatamente o que a auditoria de 21/07 achou
> em três pontos (ver "Divergências conhecidas").

## Contexto

Colocar a IA para atender clientes reais no WhatsApp de uma modelo. O risco não é técnico: é um
cliente perceber que fala com um robô, ou a IA conduzir mal uma negociação de verdade. O freio
óbvio — um humano revisando cada resposta — não serve: o Fernando quer escala, não virar revisor.
A supervisão precisa ser **automatizada**, e o humano só entra para decidir parar.

## Decisões

### Escopo do piloto

- **Uma modelo**, número INTEIRO (clientes novos e recorrentes), sem A/B (`experimento_braco`
  segue OFF). Cutover em horário morto, com o vendedor fechando as negociações abertas antes.
- **Backup humano é o VENDEDOR de plantão**, não a modelo: quem já responde aquele número assume
  os handoffs. Transição de papel, não demissão.
- Amnésia dos recorrentes é explicada pela persona como "apaguei as mensagens" (natural no ramo);
  a IA nunca contradiz fato afirmado pelo cliente.

### Supervisão em três camadas

1. **Gate PRÉ-ENVIO** (`agente/nos/output_guard.py`) — determinístico (leak, placeholder,
   repetição) + judge de AUP. Falhou → **regenera 1x** com feedback; falhou de novo → **não
   envia**, pausa a IA, card de handoff. Score ruim **nunca** vira tarefa para o Fernando: ou
   vira ação automática, ou vira telemetria de dev.
2. **Rede final do envio** (`workers/_saida_guard.py` + `envio.py`) — última defesa, cobre também
   os caminhos que pulam o grafo (canned, reengajamento) e redige PII ecoada.
3. **Judge PÓS-ENVIO 100%** (`workers/judge_pos_envio.py`) — telemetria pura (rastro de LLM, voz,
   conduta). Nunca pausa a IA, nunca gera tarefa.

### Gatilhos objetivos de rollback

Avaliados por cron diário sobre janela de 7 dias (`workers/rollback_watch.py`), contando **só
cliente real** (o rig de teste em `...@g.us` fica fora):

| Gatilho | Limiar |
|---|---|
| Incidentes críticos **não-contidos** (turno enviado com rastro de LLM) | ≥ 2 / semana |
| Conversas com **acusação-padrão** ("é robô?", pedido de prova impossível) | ≥ 3 / semana |
| **Gate abortando** turnos | > 20% |

Mais o **freio manual**, sempre disponível e sem justificativa.

**O rollback em si é decisão HUMANA.** O cron só alerta (log ERROR + gauge Prometheus + Sentry +
relay para o WhatsApp do dev); nunca pausa a modelo sozinho. A pausa é reversível (status da
modelo) — runbook em `infra/runbooks/pausar-piloto.md`.

Mudar um limiar é **decisão de plano**, não tuning: exige emendar este ADR.

### Rotina

- **Fernando**: digest semanal automático no grupo de Coordenação + `/observabilidade` quando
  quiser. As pontuações dele são o ground-truth para calibrar o judge.
- **Dev**: revisão diária dos flags nas duas primeiras semanas; alertas chegam por WhatsApp.

### Acusação "é robô"

Nega 1x (a persona já tem negação ativa). Insistência na mesma conversa **ou** pedido de prova
impossível (áudio, chamada) → pausa + card "cliente desconfiado". Cada evento é métrica-sentinela.

⚠️ Ver "Divergências conhecidas" — a implementação atual não cumpre esta decisão como escrita.

### Graduação para mais modelos

Os quatro critérios, todos simultâneos:

- ≥ **100 conversas** completas conduzidas pela IA;
- **zero** incidente crítico não-contido;
- taxa do gate **estável ou caindo**;
- conversão ≥ **80% do baseline do vendedor**.

Batidos, a expansão é **gradual (2-3 modelos por vez)**. Critério para o Fernando escolher a
próxima: volume médio, atendimento simples, cadastro completo, colaborativa, vendedor disposto a
ser backup.

### A porta ainda está fechada

Enquanto `JID_PERMITIDO` listar os grupos de teste, o webhook rejeita todo remetente fora deles:
**nenhum cliente real fala com o agente**. Isso tem duas consequências que valem estar escritas:

- os 3 gatilhos ficam em **zero permanente** (contam só cliente real) — zero aqui é *ausência de
  sinal*, não saúde;
- abrir a porta (`JID_PERMITIDO=[]`) é o cutover de verdade, e é irreversível no que já saiu.
  As pré-condições estão no BLOCO G de `infra/runbooks/pre-launch-checklist.md`.

## Alternativas rejeitadas

- **Revisão humana pré-envio de cada resposta.** Rejeitada — transforma o Fernando em gargalo e
  mata o motivo de existir do produto.
- **Score ruim virando tarefa para o Fernando.** Rejeitada pela mesma razão: telemetria de
  qualidade é assunto de dev; o operador só recebe o que exige decisão dele.
- **Rollback automático (o cron pausa a modelo sozinho).** Rejeitada — pausar derruba o
  faturamento da modelo; um falso-positivo estatístico não pode ter esse poder. O cron garante
  que ninguém precise olhar dashboard para saber que o critério bateu; a decisão fica com gente.
- **A/B no piloto.** Rejeitada — com uma modelo só, o N não sustenta comparação, e dividir o
  tráfego atrasa o aprendizado.

## Consequências

- Os limiares e critérios acima passam a ter fonte única aqui; o código os cita.
- **Graduação não é computável hoje**: não existe baseline de conversão por vendedor, e nenhum
  cron/relatório acompanha o progresso rumo aos quatro critérios. Enquanto isso, a decisão de
  graduar é feita a olho — registrado como dívida, não como decisão.
- A taxa do gate é **subcontada** por construção (aborts sem `atendimento_id`, e aborts cujo
  handoff já estava aberto, não deixam linha em `escaladas`): o gatilho erra para o lado seguro
  (se disparou, disparou de verdade), mas o número real é ≥ o medido.

## Divergências conhecidas (auditoria 2026-07-21)

A política de acusação implementada difere do decidido, em três pontos, e a fonte que o código
cita (`docs/agente/10 §3.1`) hoje aponta para o documento de corpus — o doc original de segurança
saiu do repo, e `docs/agente/03-prompts.md:266` afirma o contrário do código:

1. escala na **3ª** insistência (`intercept_disclosure.py`), não na 2ª;
2. pedido de **prova impossível** vai para o LLM **sem pausar**;
3. o card "cliente desconfiado" **não chega ao grupo** de Coordenação (a escalada nasce com
   `responsavel="Fernando"`, e o roteamento manda card ao grupo só para outros responsáveis) —
   ou seja, na 3ª acusação o cliente fica sem resposta e ninguém vê o card.

**Pendente de arbitragem do dono**: ou o código é corrigido para 2 toques + pausa + card no
grupo, ou esta seção do ADR é emendada para refletir a política de 3 toques que se decidiu depois.
Enquanto não se decide, o comportamento vivo é o do código.
