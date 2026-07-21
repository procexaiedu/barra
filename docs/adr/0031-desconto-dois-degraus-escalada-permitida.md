---
status: accepted
supersedes: parte do ADR 0004 (piso percentual único, anti-leilão one-shot)
---

# ADR-0031 — Desconto de fechamento em dois degraus percentuais, com escalada de uma rodada

## Contexto

O ADR-0004 fixou o **Piso de desconto** como um único percentual global (`desconto_max_pct`, ~15%) e uma regra **anti-leilão one-shot**: a IA faz **uma única** contraproposta, no piso, sem regatear em passos — recusada explicitamente a "escalada em 2+ rodadas" como alternativa (d) do próprio ADR. Na reunião de colocação da IA em produção (2026-07-20), o dono do domínio descreveu explicitamente uma escalada de **duas rodadas**: para o programa "Normal" (1h, R$400 na tabela — ver print de cadastro), a IA pode oferecer primeiro **R$50** de desconto e, se o cliente insiste, subir até **R$100** como teto — ambos **proporcionais ao preço do pacote** (R$50 ≈ 12,5%, R$100 ≈ 25%), não valores fixos cadastrados por combinação.

## Decisão

- **Dois percentuais globais** substituem o único: `desconto_degrau_pct` (~12,5%, calibrar) e `desconto_teto_pct` (~25%, calibrar) — ambos sobre o **Preço de tabela** do pacote (programa + extras vendidos no atendimento, ADR-0014), escalando automaticamente para qualquer programa×duração (não é valor absoluto cadastrado por combinação).
- **Escalada permitida em até 2 rodadas** dentro da mesma negociação: a IA oferece primeiro o desconto no **degrau**; se o cliente insiste (mesma negociação, não reabre depois de fechada), a IA pode subir até o **teto**. Uma terceira insistência **não** gera nova oferta — escala (`fora_de_oferta`), preservando o espírito anti-leilão só que com **teto de 2 rounds** em vez de 1.
- Gatilhos reativo (cliente pede) e proativo (reengajamento) continuam válidos para ambos os degraus — a reunião não distinguiu um gatilho por degrau.
- **Enforcement em duas camadas** (mantido do ADR-0004): percentuais no prompt geral (BP1); guarda determinística no código ao registrar `valor_acordado` abaixo do teto.

## Alternativas rejeitadas

- **Manter one-shot único (ADR-0004 original).** Rejeitada — o dono do domínio descreveu explicitamente uma escalada de 2 passos na reunião.
- **Valores absolutos cadastrados por (modelo, programa, duração).** Rejeitada: os números da reunião (R$50/R$100) são proporcionais ao preço (12,5%/25% de R$400), não fixos — fórmula percentual generaliza sozinha para Completo, Pernoite etc. sem cadastro extra.

## Consequências

- `settings.desconto_max_pct` vira dois campos (`desconto_degrau_pct`, `desconto_teto_pct`); `regras.md.j2 §desconto` reescrito para a escalada de 2 rounds; `_abaixo_do_piso` (guarda de código) passa a checar contra o teto (segundo percentual), não mais o único.
- Evals/fixtures de "tem que escalar" precisam distinguir 3 casos agora: dentro do degrau, entre degrau e teto (ainda ok, 2ª rodada), abaixo do teto (`fora_de_oferta`).
- Calibração dos dois percentuais (~12,5%/~25%) é o valor citado no exemplo da reunião para o programa Normal — confirmar com Fernando antes de travar como default de produção.
