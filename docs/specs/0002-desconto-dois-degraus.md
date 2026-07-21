# Desconto de fechamento: dois degraus percentuais com escalada de 2 rodadas

> Issue: [procexaiedu/barra#95](https://github.com/procexaiedu/barra/issues/95)

## Problem Statement

O Desconto de fechamento hoje (ADR-0004) tem um único percentual global (`desconto_max_pct`, ~15%) e uma regra anti-leilão estrita: a IA faz **uma única** contraproposta, no piso, e não negocia mais depois disso. Na reunião de colocação da IA em produção, o dono do domínio descreveu um comportamento diferente do que está implementado: para o programa Normal (R$400/h), a IA pode oferecer primeiro um desconto menor (R$50, ~12,5%) e, se o cliente insiste, subir até um teto maior (R$100, ~25%) — uma escalada de duas rodadas, não uma tacada só. O mecanismo atual não suporta essa segunda rodada: hoje, uma vez feita a contraproposta no piso, qualquer insistência do cliente escala para Fernando (`fora_de_oferta`), mesmo que ainda houvesse margem de negociação combinada.

## Solution

O piso de desconto passa a ter **dois degraus percentuais globais** em vez de um: um degrau intermediário (~12,5%) e um teto (~25%), ambos sobre o Preço de tabela do pacote vendido (programa + extras, ADR-0014) — escalando automaticamente para qualquer programa/duração, sem cadastro adicional por combinação. A IA pode oferecer o degrau intermediário primeiro; se o cliente insiste na mesma negociação, pode subir até o teto — mas nunca uma terceira vez. Abaixo do teto, o comportamento de hoje se mantém: escala para Fernando (`fora_de_oferta`) em vez de negociar mais.

## User Stories

1. Como Fernando, quero que a IA tenha uma segunda rodada de desconto disponível quando o cliente insiste depois da primeira oferta, para não perder vendas que fechariam com um segundo empurrão, sem abrir negociação livre.
2. Como Fernando, quero que os dois valores de desconto sejam percentuais sobre o preço do pacote, e não valores fixos em reais cadastrados por programa, para que a regra funcione automaticamente em qualquer programa/duração sem eu ter que cadastrar cada combinação.
3. Como cliente numa negociação, ao pedir desconto uma segunda vez na mesma conversa, quero receber uma oferta melhor que a primeira (até o teto), para sentir que insistir teve algum efeito, sem virar um leilão sem fim.
4. Como Fernando, quero que depois do teto a IA pare de baixar e escale para mim, para preservar o posicionamento premium e não deixar a IA regatear até zerar a margem.
5. Como desenvolvedor, quero que a guarda de código que bloqueia gravar um valor abaixo do piso passe a checar contra o **teto** (o segundo percentual), não mais o único piso antigo, para o backstop continuar impedindo fechamento abaixo do combinado mesmo se o prompt falhar.
6. Como desenvolvedor, quero os dois percentuais configuráveis via settings (como o único de hoje), para poder calibrar sem alterar código.
7. Como Fernando, quero que tanto o gatilho reativo (cliente pede) quanto o proativo (reengajamento) continuem valendo para os dois degraus, para não restringir sem necessidade onde a escalada pode ser oferecida.
8. Como desenvolvedor de evals, quero que os testes de "tem que escalar" distingam três faixas (dentro do degrau, entre degrau e teto — ainda ok numa 2ª rodada —, abaixo do teto), para o gate de qualidade continuar cobrindo o comportamento certo.

## Implementation Decisions

- **`settings.py`: `desconto_max_pct` vira dois campos** — `desconto_degrau_pct` (default a calibrar, ~0.125) e `desconto_teto_pct` (default a calibrar, ~0.25). Mesmo padrão de `Field(default=..., ge=0.0, le=1.0)` do campo atual.
- **`_abaixo_do_piso` (`dominio/atendimentos/service.py`)** passa a comparar contra `desconto_teto_pct` (o segundo, maior desconto permitido) em vez do único percentual de hoje — é o backstop final; o degrau intermediário não precisa de guarda de código própria, só o teto importa como limite duro.
- **`regras.md.j2` bloco `<desconto>`** reescrito para descrever a escalada de 2 rodadas: primeira contraproposta no degrau; se o cliente insiste **na mesma negociação**, segunda e última contraproposta no teto; terceira insistência não gera nova oferta, escala (`fora_de_oferta`). Interpola os dois percentuais (`desconto_degrau_pct`, `desconto_teto_pct`) — mesmo mecanismo Jinja de hoje (bloco geral, byte-idêntico entre modelos, não quebra cache).
- **"Mesma negociação"** — precisa de uma forma determinística de saber se a segunda oferta é a mesma conversa ou uma nova (evitar reabrir desconto em atendimentos recorrentes). Reaproveita o padrão já existente de disciplina "one-shot por atendimento" (`<ja_fez_contraproposta>`, `_tem_contraproposta` em `agente/CLAUDE.md` — flags determinísticas via `mensagens.atendimento_id`). Este spec estende esse mecanismo para contar **até duas** contrapropostas por atendimento em vez de até uma, mantendo a mesma detecção determinística (não depender da janela de mensagens).
- **`persona.py::render_persona`/`render_prefixo_geral`** passam a receber/interpolar os dois percentuais em vez de um.

## Testing Decisions

- **Teste unitário:** `_abaixo_do_piso` contra o novo `desconto_teto_pct` — mesmos casos de hoje (dentro do teto ok, abaixo do teto escala, sem programa correspondente à duração escala), só trocando qual settings field é lido. Prior art: testes já existentes desse helper em `api/tests/dominio/atendimentos/`.
- **Teste da flag determinística de "já ofereceu 2x":** extensão do teste já existente de `_tem_contraproposta`/`<ja_fez_contraproposta>` — cobrir contagem 0/1/2 contrapropostas no mesmo atendimento e reset em atendimento novo (recorrência).
- **Eval/fixture "tem que escalar":** atualizar fixtures existentes (mencionadas no ADR-0004 original) para distinguir as 3 faixas — dentro do degrau, entre degrau e teto, abaixo do teto.
- **Módulos tocados:** `settings.py`, `dominio/atendimentos/service.py` (`_abaixo_do_piso`), `agente/persona.py`, `agente/prompts/regras.md.j2`, evals/fixtures de desconto.

## Out of Scope

- Gatilhos diferentes por degrau (ex.: degrau só no reengajamento, teto só no reativo) — a reunião não distinguiu isso; os dois gatilhos valem para os dois degraus.
- Piso por (modelo, programa) ou granularidade além do percentual global — segue rejeitado, mesma razão do ADR-0004 original (prematuro para o piloto de 1 modelo).
- Calibração final dos valores exatos (~12,5%/~25%) — os números vieram de um único exemplo concreto (Normal R$400) na reunião; confirmar com Fernando antes de travar como default de produção (ver Further Notes).
- Mudar o comportamento de upsell (pacote maior com preço/hora menor) — continua livre, não é desconto, inalterado por este spec.

## Further Notes

- **Ver ADR-0031** (`docs/adr/0031-desconto-dois-degraus-escalada-permitida.md`) para o histórico completo da decisão, incluindo a reconciliação com o anti-leilão original do ADR-0004.
- Este spec **reverte parcialmente** uma decisão de sabatina anterior (ADR-0004, 2026-05-23) que rejeitou explicitamente escalada em múltiplas rodadas como opção (d) — vale mencionar isso no PR/changelog para quem revisar não estranhar a reversão.
- A calibração real dos dois percentuais precisa de confirmação explícita do Fernando antes do go-live — o exemplo da reunião cobre só um programa (Normal, R$400); não foi confirmado se o Completo (R$800) segue a mesma proporção ou tem calibração própria.
