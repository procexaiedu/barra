# A/B: thinking do DeepSeek no chat #1

Status: ready-for-human

## Pergunta

O input do chat #1 é grande (BP_GERAL + BP_MODELO + histórico + beliefs + tools). Ligar o
thinking do DeepSeek V4 Flash melhora a **conduta** (obediência às regras globais do prompt)
sem regredir **voz** e **anti-paredão**?

## Por que é plausível — e por que pode piorar

- A favor (hipótese do Fernando... do dev): em prompt com muitas restrições, thinking melhora a
  classe de restrições de **coordenação global** (arXiv 2606.09662, thinking ON/OFF nos mesmos
  pesos) — a classe dos nossos degraus de endereço, gates de escalada e "nunca revelar X".
- Contra: o mesmo paper mostra que thinking **piora** restrições de **forma local precisa**
  (a nossa voz: bolha curta, sem travessão, vocativo dosado) e a literatura de roleplay
  (arXiv 2511.04962) mostra reasoning degradando fidelidade de persona justamente em personas
  moralmente "cinza" — reasoning dá espaço para o modelo se convencer a amaciar a venda
  (regressão de anti-paredão). Além disso: +2–5 s/turno (raciocínio ~3x o tamanho da resposta
  no tráfego OpenRouter do modelo) e a `chat_temperature=0.7` (exp N-1 30/06) é ignorada em
  thinking.
- Nota de escopo: os incidentes históricos de contexto (tag que some, belief latch) foram bugs
  de **mecanismo**, corrigidos em código — thinking não recupera informação ausente do contexto.
  O A/B mede o que sobra: obediência às regras presentes.

## Mecânica (implementada)

- `settings.deepseek_thinking_chat: "disabled" | "low" | "high" | "max"` (env
  `DEEPSEEK_THINKING_CHAT`), default **disabled** = prod intocada. Escopo: SÓ o chat #1
  (`graph._criar_chat_principal` + regen do output_guard). Extração #2 e judge #3 seguem
  travados em disabled (thinking corrompe structured output).
- `criar_chat_deepseek(thinking=...)`: `extra_body={"thinking":{"type":"enabled"},
  "reasoning_effort": <valor>}`; temperatura omitida (provider ignora em thinking).
- `_ChatDeepSeekThinking` (core/llm.py): captura `reasoning_content` da resposta para
  `additional_kwargs` e o reinjeta nas assistant do payload — sem isso o loop de tool call toma
  HTTP 400 (guides/thinking_mode). Só não-streaming (único caminho do agente).
- `make ab-thinking [ARGS=...]`: roda o gate de conduta 2x (braço A disabled, braço B
  `DEEPSEEK_THINKING_CHAT=high`). O braço fica visível em `ResultadoFiel.flags`
  (`deepseek_thinking_chat`) e nos relatórios do gate.

## Protocolo

1. `make ab-thinking ARGS="--fake"` — valida o encanamento sem crédito (exige
   TEST_DATABASE_URL com corpus).
2. Corrida real: `E2E_AUTORIZADO=1 make ab-thinking` (§0: gasta crédito DeepSeek,
   ~R$0,09/braço no gate de conduta; autorização explícita antes).
3. Mesmos roteiros/núcleo nos dois braços (ClienteRoteirizado é determinístico); comparar os
   dois relatórios em `evals/relatorios/`.
4. Se o braço high der sinal positivo, braço extra opcional com `low` (menor latência) antes de
   qualquer conversa de promoção.

## Critérios de decisão

Thinking só se promove a candidato de prod se, vs braço A:

- **Conduta** (hard gate + advisory conduziu/violações): melhora mensurável; e
- **Voz** (estilometria vs baseline): sem regressão; e
- **Empurrão/paredão** (`empurrao_pct`, desculpas/amaciamento): sem regressão; e
- **Latência** (`Metricas.latencia_s` por turno): p95 aceitável para WhatsApp (referência:
  ≤ 2x o braço A); custo (`custo_brl`) dentro do alvo (`custo_alvo_brl`).

Qualquer regressão em voz/empurrão mata a promoção mesmo com ganho de conduta (o cliente sente
voz e paredão na primeira mensagem; o ganho de conduta é em turno raro). Empate = fica
non-thinking (menos latência, temperatura calibrada válida).

Aposta registrada antes da corrida (10/08): empata-ou-perde no placar composto.

## Comments
