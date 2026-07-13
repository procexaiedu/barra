---
name: processar-feedbacks
description: >-
  Processa o feedback CRU do Fernando sobre o agente da Elite Baby — print do grupo de testes
  + áudio ou texto — e produz um DRAFT enriquecido com o contexto interno do agente (belief,
  extração, output_guard, estado), pronto pra virar issue que o Claude Code resolve. Ferramenta
  de DEV, fora da stack de prod: não redeploya, não gasta o trilho de crédito do agente ao vivo.
  Use quando o usuário disser "processa os feedbacks", "roda o /processar-feedbacks", "o Fernando
  mandou feedback do teste", ou pedir pra transformar um comentário cru sobre o agente em algo
  acionável. Ancora o feedback ao trace real no Langfuse (não ao banco — o #reset apaga). v1
  (#92): núcleo feedback → draft, um por vez. Ler o grupo + abrir issue + reply-marcador é #93.
---

# Processar feedbacks (rig do agente)

Fernando testa o agente no grupo de testes (Playground, na instância de teste vigente) fazendo o
papel de cliente, e larga feedback **cru** — um print do grupo + um áudio/texto comentando o
ponto. Esse feedback só tem o **output** da IA (o que apareceu na tela). Falta tudo o que explica
*por que* a IA se comportou assim (belief state, extração, veredito do output_guard, estado do
atendimento) e *onde no código/prompt* isso é governado.

Esta skill fecha esse buraco: transforma o feedback cru num **draft estruturado e enriquecido com
o interno**, fiel ao que o Fernando disse e ancorado na evidência do trace. É **dev-only** — não
toca `barra-vips`, não redeploya, não roda no trilho DeepSeek de prod; o enriquecimento roda no
plano do Claude Code.

> **Fonte de verdade do interno = Langfuse, não o banco.** O `#reset` do rig **deleta**
> `conversas`/`mensagens`/`atendimentos` da modelo de teste entre sessões (`webhook/reset_teste.py`).
> Os traces do Langfuse são append-only e sobrevivem. Ancore **sempre** no Langfuse.

## Escopo desta fatia

- **v1 núcleo (#92, esta skill hoje):** um feedback por vez → draft enriquecido na sessão. O
  feedback chega **fornecido** (você cola o print/áudio/texto de amostra). Demoável já, contra um
  trace real de produção, **sem depender da `procex-teste`**.
- **#93 (ainda não wired):** ler o grupo de feedbacks via `evo_call`, gate de revisão, abrir
  `gh issue` / resumo, postar o **reply-marcador** e idempotência. Quando #93 landar, estende esta
  mesma skill com uma "Fase de I/O".

## Antes de começar

1. **Instância(s) de teste** — lidas do config, nunca hardcodadas: `settings.reset_teste_instances` é a allowlist de `evolution_instance_id` que são instâncias de teste (as que aceitam `#reset`). Hoje inclui `lucia`, migrando pra `procex-teste`.
2. **`modelo_id` de teste** — resolva pela instância: `SELECT id FROM barravips.modelos WHERE evolution_instance_id = ANY(<reset_teste_instances>)`. É o filtro dos traces no Langfuse (tag `modelo_id:<uuid>`). No demo de #92 sem `procex-teste`, pegue o `modelo_id` de um trace real recente qualquer.
3. **MCP `langfuse-traces`** conectado (fetch de traces/observações).

## Passo 1 — Desmontar o feedback

Separe o feedback cru em três insumos:

- **Áudio → STT.** Reusa a MESMA infra de STT do worker (OpenAI `whisper-1`, `settings.openai_model_audio_transcribe`) — a chamada que `workers/media.transcrever_audio` faz por dentro (`openai.audio.transcriptions.create`), sem o acoplamento a MinIO/DB/redis do job. Transcreva o arquivo local direto com `AsyncOpenAI` + a chave do `settings`. Não reimplemente STT, não use provider novo.
- **Print → vision NATIVA.** Leia a imagem com a ferramenta **Read** (você tem vision nativa). Sem OCR/provider externo. Extraia a **fala do agente** que aparece no print — é o que ancora o turno.
- **Texto** → use direto.

Guarde: (a) `texto_agente_print` (a fala do agente extraída do print, via vision nativa), (b) o comentário do Fernando (transcrito/textual), (c) o **timestamp do feedback** (quando ele mandou).

## Passo 2 — Ancorar ao trace (Langfuse)

Encontre o turno exato que o Fernando critica — sem chutar.

1. Via MCP `langfuse-traces`, busque os traces da modelo de teste numa janela ao redor do
   timestamp do feedback: filtro por tag `modelo_id:<uuid>`, ordenado por tempo. Cada trace tem
   `id`, `timestamp` e a saída do agente daquele turno.
2. Monte o payload e chame a **função pura de âncora** (Seam 1, `barra.ancora_feedback`) — ela casa
   por similaridade textual + janela de tempo e é determinística:

   ```
   echo '{
     "texto_agente_print": "<fala do agente extraída do print>",
     "ts_feedback": "<ISO 8601 tz-aware>",
     "traces": [ {"trace_id": "...", "saida_agente": "...", "timestamp": "<ISO>"}, ... ]
   }' | uv run python -m barra.core.ancora_feedback
   ```

   Resposta: `{trace_id, ambiguo, motivo, score, candidatos}`.
3. **Se `ambiguo` = true → PARE.** Não escolha um turno em silêncio. Reporte o `motivo`
   (`empate` / `nenhum_match` / `sem_candidato_na_janela`) e os `candidatos`, e peça desambiguação
   (qual turno? amplie a janela? o print tem vários turnos?). Só siga com um turno confirmado.

## Passo 3 — Puxar o slice interno do turno

Do trace escolhido, via MCP `langfuse-traces` (`fetch_trace` / observações), extraia o **contexto
interno** — o que o feedback cru não tem:

- **belief state** (o que a IA acreditava: tipo definido? cotação enviada? intenção real?)
- **extração** (o que ela extraiu da mensagem do cliente)
- **veredito do output_guard / judge** (passou? sanou? bloqueou?)
- **estado do atendimento** (estado, `tipo_atendimento`, `pix_status`)

Os nós/spans relevantes: `prepare_context` (monta o belief/estado), `llm`, `output_guard`. Inspecione
o trace **ao vivo** (nomes de span podem evoluir) e cite os valores reais, não genéricos.

## Passo 4 — Hipótese de código (marcada como hipótese)

Best-effort: aponte **onde** o comportamento é governado — bloco de `agente/prompts/*.md.j2`, nó do
grafo (`agente/nos/*.py`), ou slot do belief. Use `grep` pelo comportamento/termo. **Marque
explicitamente como hipótese a confirmar** — o Claude Code re-verifica ao pegar a issue; um
apontamento errado não deve ancorar.

## Passo 5 — Montar o draft

Estruture assim (é o corpo que #93 vira issue):

```
## Sintoma
<ancorado no trace: em que turno, o que o belief/estado dizia, o que a IA fez —
 NÃO só a paráfrase do Fernando>

## Esperado
<o que o Fernando disse que deveria ser. Se ele NÃO explicitou o gatilho/comportamento,
 NÃO invente: escreva "PERGUNTA PRO FERNANDO: <a dúvida concreta>">

## Contexto interno (trace)
belief: ...   extração: ...   output_guard: ...   estado: ...
(valores reais do trace ancorado)

## Hipótese de código (confirmar)
~ <arquivo/bloco/nó suspeito> — marcado como hipótese
```

Classifique o feedback: **acionável** (vira issue no #93) ou **elogio/ruído** (resumo leve). Um
elogio ancorado também é valioso — vira nota de regressão/fixture, não issue.

## Regras de conduta (invariantes)

- **Nunca invente o "esperado"** que o Fernando não deu — emita PERGUNTA.
- **Nunca escolha um turno em silêncio** — âncora ambígua para e pergunta.
- **Ancore no Langfuse, nunca no banco operacional** (o `#reset` apaga).
- **Fiel ao Fernando + ancorado no trace** — o sintoma é evidência, não paráfrase.
- **Dev-only** — nenhuma ação atinge prod (sem redeploy, sem mutação no banco de prod, sem envio a
  cliente). No #92 nem abre issue — só produz o draft na sessão.

## Verificação (Seam 2 — demo do núcleo)

Prove contra um **trace real de produção** + um feedback de amostra, sem `procex-teste`:
escolha um turno real do Langfuse, use a fala do agente dele como `texto_agente_ocr`, e confirme que
a âncora casa aquele `trace_id`, o slice interno sai correto, e o draft fica ancorado (com PERGUNTA
onde o "esperado" não foi dado). Âncora ambígua deve parar e pedir desambiguação.
