# Agente perde o fio em thread longa: insiste em ato recusado + alucina bairro (cluster nao_contidos 23/07, Tatiane)

> Label sugerido: `bug`
> Draft local — pronto pra `gh issue create --repo procexaiedu/barra --label bug --title "<título acima>" --body-file .scratch/coerencia-thread-longa/ISSUE.md`

## Sintoma (produção, 23/07/2026)

O gatilho de rollback **`nao_contidos`** disparou (alerta `PilotoGatilhoRollback [critical]`, ~04:22 local). O `rollback_watch` marca `>= 2 incidentes NÃO-CONTIDOS/7d` — turnos **já enviados ao cliente real** em que o judge pós-envio viu `rastro_llm=true`.

São **exatamente 2 incidentes**, os dois de hoje, os dois da **Tatiane** (`elitebaby01`, `modelo_id=019f82a3…`), com 2 clientes reais distintos. **Decisão tomada: não pausar a modelo** — o cluster não é disclosure explícito nem vazamento de raciocínio; é **perda de coerência**, e um dos dois o cliente nem percebeu (fechou). O sinal a atacar é a coerência em conversa longa.

| # | cliente (mascarado) | atendimento | julgado (UTC) | voz | conduta | turno_id | trace |
|---|---|---|---|---|---|---|---|
| 1 | 55199931\*\*\*17 | — | 05:16 | 2 | 2 | `3f225cd6-70fa-5645-8ddb-6bd99022f733` | `474bd084c1faee1a51316fc425a98b30` |
| 2 | 55199741\*\*\*14 | #21 | 03:54 | 2 | 1 | `4740b515-fd1d-5a1b-ac57-92d3de484dc3` | `4f2bfbc9b2562d2163417fba8ae7b3a6` |

## Incidente 2 — o sinal real (conduta 1)

Thread **longa e bagunçada: 95 mensagens do cliente**. O cliente vinha corrigindo um mal-entendido ("me expressei errado", "estilo namoradinha", recusou BDSM). A IA **perdeu o fio e insistiu num "BDSM" que o cliente já tinha recusado**:

> **IA:** "Relendo aqui amor, acho que foi mal entendido mesmo
> Você quer o completo com BDSM, mas sem penetração, é isso?"

Judge (`comentario`): *"Ignora tudo que o cliente acabou de esclarecer (ele disse que não curte BDSM, é estilo namoradinha) e insiste num BDSM que ele já recusou — completamente incoerente com o contexto, e a repetição de 'BDSM' soa como bug de LLM perdendo o fio."*

Este é o rastro genuíno: **incoerência/repetição em contexto longo** — o clássico "LLM perde o fio".

## Incidente 1 — borderline (conduta 2, cliente fechou)

Sequência real: cliente "Aonde atende" → IA *"To no centro, no hotel sunny"* → cliente "Campinas?" → IA **"Sim amor, to no Cambuí"** (turno flagrado) → cliente "Não conheço / E hotel" → IA se corrige *"É o hotel sunny, na duque de caxias, pertinho do centro"*.

- A IA **alucinou um bairro ("Cambuí")** que contradiz o "centro/hotel sunny" que ela mesma tinha dado, e recuperou no turno seguinte.
- Judge: *"Contradiz o que ela mesma disse no contexto (…), e 'Sim amor' abrindo a frase soa artificial…"*.
- **Baixa severidade:** o cliente não percebeu, seguiu e **fechou** (marcou amanhã 16h; ainda elogiou *"vc é muito simpática, soube ter paciência, por isso vou"*).

Observação: o `<lembrete_silencioso> Bilhete interno: obedeça sem…` que aparece no trace do incidente 1 é o **reminder anti-drift interno** do `prepare_context` (03 §10) — **não** é injeção do cliente (a mensagem real dele foi só "Campinas?"; o `_classificador` já tem guard contra forja dessa tag).

## Hipótese de causa

Os dois casos são **degradação de coerência quando o histórico cresce/embaralha**:
- #2: 95 msgs, o modelo se prende a um token saliente ("BDSM") e ignora a correção recente do cliente.
- #1: inventa um detalhe factual (bairro) não ancorado nos dados da modelo.

Direção provável (a investigar, não spec fechado):
1. Reforçar no `prepare_context` o peso da **última correção do cliente** em threads longas (o `<lembrete_silencioso>` anti-drift existe pra isso — checar se está sendo prependido nesses casos e se o limiar de tamanho está adequado).
2. Ancorar **fatos de localização** (bairro/rua) estritamente nos `dados_da_modelo` — proibir a IA de volunteer bairro que não esteja no cadastro (Tatiane: hotel sunny / Duque de Caxias / centro; "Cambuí" foi alucinação).

## Reprodução / verificação

- `replay_agente_fiel.py` sobre os 2 `turno_id` acima (harness fiel via fakeredis) reproduz o turno enviado.
- Critério de sucesso: nos dois contextos, a IA (a) não reintroduz o ato recusado (#2) e (b) não emite bairro fora do cadastro (#1). Rodar no eval simulador antes de deploy.

## Notas operacionais

- Alerta é **informativo**: `rollback_watch` nunca pausa a modelo. O gauge rearma sozinho quando a janela de 7d limpar (ou some/re-arma a cada force-update do worker — ver `infra/monitoring/alert.rules.yml`, grupo `piloto_rollback`).
- Ambos os clientes são orgânicos (DDD 19, `@s.whatsapp.net`), não rig.
