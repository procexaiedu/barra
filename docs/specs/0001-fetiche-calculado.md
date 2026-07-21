# Fetiche: preço calculado a partir do programa vendido

> Issue: [procexaiedu/barra#94](https://github.com/procexaiedu/barra/issues/94)

## Problem Statement

O preço de um Fetiche pago (ex.: Beijo Grego, Chuva dourada) é hoje um valor fixo, digitado à mão por Fernando no cadastro de cada modelo (`modelo_fetiches.preco`). Na prática, o valor certo do extra não é fixo — ele é sempre o preço de uma hora do programa que o cliente está efetivamente comprando naquele atendimento (Normal a R$400 ou Completo a R$800, por exemplo). Hoje, se Fernando cadastra o Beijo Grego a R$400 pensando no programa Normal, um cliente que fecha o Completo paga o mesmo R$400 de extra — errado, deveria ser R$800. O cadastro atual (ver print de produção) já reflete esse valor fixo desatualizado: "Menage" aparece como **incluso** (grátis) quando deveria ser um extra pago, seguindo a mesma lógica.

## Solution

O preço de qualquer Fetiche pago deixa de ser um valor cadastrado e passa a ser **sempre calculado**: preço do extra = preço de tabela do programa vendido ÷ horas vendidas (preço-hora efetivo do pacote), somado uma vez por fetiche pedido, igual para todos os fetiches pagos (nenhum vale mais que outro). `modelo_fetiches.preco` vira um flag (incluso vs. pago) em vez de um valor monetário. O cadastro por modelo (painel) para de pedir um número e passa a pedir só a escolha incluso/pago. O card de Fetiches no BP3 (contexto da IA) mostra, para cada fetiche pago, o valor correspondente a cada programa que a modelo oferece — pré-calculado no momento do render, sem depender do turno da conversa, preservando o prefixo cacheado do prompt.

O caso especial **Menage** segue exatamente essa mesma fórmula (dobra o pacote): tipo (a) cliente traz uma acompanhante — só regra de preço, sem rastro estrutural da segunda pessoa; tipo (b) modelo traz uma amiga (outra modelo) — fora de escopo deste spec, sempre escalada manual para Fernando (ver Out of Scope).

## User Stories

1. Como Fernando, quero que o preço de um fetiche pago escale automaticamente com o programa que o cliente está comprando, para não perder receita quando o cliente fecha o pacote maior.
2. Como Fernando, quero parar de digitar um valor em reais para cada fetiche no cadastro da modelo, e só marcar se ela faz aquilo incluso ou como extra pago, para não ter que recalcular manualmente cada vez que o preço de tabela dela mudar.
3. Como a IA (na conversa de venda), quero saber, para cada fetiche pago que a modelo faz, o valor exato do extra em cada programa que ela oferece, para cotar corretamente sem fazer conta na hora.
4. Como Fernando, quero que ao registrar os fetiches de um atendimento no painel, o valor gravado (`atendimento_fetiches.preco_snapshot`) seja calculado a partir do(s) programa(s) efetivamente vendido(s) naquele atendimento, não lido de um valor cadastrado desatualizado.
5. Como Fernando, quero que o Menage deixe de ser tratado como "incluso" (grátis) por padrão no cadastro, e passe a seguir a mesma regra de qualquer fetiche pago (dobra o pacote), para cobrar corretamente quando o cliente traz uma acompanhante.
6. Como cliente que traz uma acompanhante para o encontro, quero que o preço reflita duas pessoas sem precisar virar um cadastro separado no sistema, para o atendimento continuar simples do lado da modelo/Fernando.
7. Como Fernando, quero que quando a modelo traz uma amiga (segunda modelo) para o menage, isso vire uma escalada explícita para eu coordenar manualmente, para não ter o sistema tentando modelar uma coisa que ele não suporta ainda (dois atendimentos, dois recebedores).
8. Como desenvolvedor, quero que o cálculo do preço do extra viva num único lugar reutilizável (backend), para o painel e a cotação da IA nunca divergirem sobre quanto custa um fetiche.
9. Como desenvolvedor, quero que o card de Fetiches renderizado no BP3 continue sendo função só de dados por-modelo (fetiches que ela faz + seus programas), para não quebrar a regra de prefixo de prompt byte-idêntico entre turnos (cache do DeepSeek).
10. Como Fernando, quero que um atendimento com mais de um programa vendido (ex.: dois serviços combinados) ainda produza um valor de fetiche sensato, mesmo que a regra exata desse caso não tenha sido validada com o Fernando (ver Further Notes).

## Implementation Decisions

- **`modelo_fetiches.preco` vira flag, não valor monetário.** Sem migration de schema (mantém a coluna `numeric NULL` existente para não quebrar dados/joins já em produção) — reinterpretação de semântica: `NULL` = incluso (sem custo extra), `NOT NULL` (qualquer valor, ignorado) = pago. O endpoint de vínculo (`POST/PATCH /modelos/{modelo_id}/fetiches`) para de aceitar um valor numérico livre do frontend e passa a aceitar só um booleano `pago: bool` (grava `preco = 0` ou um sentinel não-NULL fixo quando `pago=true`, `NULL` quando `false` — detalhe de codificação, não expor `preco` como número editável na API pública).
- **Nova função pura de cálculo:** `calcular_preco_extra_fetiche(preco_tabela: Decimal, duracao_horas: Decimal) -> Decimal` em `dominio/atendimentos/service.py` (mesmo módulo de `_abaixo_do_piso`, mesmo padrão de função privada determinística). Fórmula: `preco_tabela / duracao_horas` (preço-hora efetivo), aplicada uma vez por fetiche marcado como pago.
- **Seam do registro do atendimento:** `adicionar_fetiche` (`dominio/atendimentos/routes.py`) para de fazer `SELECT preco FROM modelo_fetiches` e passa a: (1) checar se o vínculo é `pago`; se não, `preco_snapshot = NULL` (incluso); se sim, (2) buscar o(s) `atendimento_servicos` do atendimento (`programa_id`, `duracao_id`, `preco_snapshot`) e calcular o extra a partir deles.
  - Um único serviço vendido (caso comum, todos os exemplos da reunião): usa o `preco_snapshot`/duração desse serviço diretamente.
  - Mais de um serviço vendido no mesmo atendimento (combinação de programas): soma os `preco_snapshot` e divide pelo `MAX(duracao_horas)` — mesma convenção de "duração sugerida = MAX das horas" já documentada em CONTEXT.md (**Programa e duração**). Não confirmado com Fernando (ver Further Notes).
  - Se o atendimento ainda não tem nenhum `atendimento_servicos` registrado, a chamada falha com erro claro (não dá pra calcular o extra sem saber o que foi vendido) — mesmo padrão de erro de outros endpoints deste módulo.
- **BP3 (`agente/prompts/fetiches.md.j2` + `agente/nos/prepare_context.py`):** para de renderizar um valor único `+R$X` por fetiche. Passa a renderizar, para cada fetiche pago, uma linha por programa que a modelo oferece (ex.: "Beijo Grego — +R$400 no Normal, +R$800 no Completo"), calculado com a mesma função `calcular_preco_extra_fetiche` no momento do render. Continua **estático por modelo** (função só de fetiches × programas da própria modelo) — não depende do turno/negociação em curso, preservando o prefixo cacheável (`agente/CLAUDE.md` — dado por-turno nunca no `system`).
- **`regras.md.j2`** (bloco `<desconto>`/composição do pacote, ADR-0014) não muda de mecânica — continua incidindo sobre "programa + extras", só que agora o "extra" que entra na conta é o valor calculado, não mais um valor cadastrado.
- **Menage** entra no catálogo global de fetiches (se ainda não estiver) marcado como `pago` por padrão nas modelos que o oferecem — correção de dado, não de código, mas o frontend do cadastro (`Serviços e preços` → seção Fetiches) precisa parar de aceitar/mostrar "incluso" como default para itens que na prática são sempre cobrados em dobro.
- **Menage tipo (b) — modelo traz amiga:** fora do sistema. Sem novo campo, sem segunda `Modelo` vinculada ao atendimento. A IA pode oferecer/mencionar o serviço, mas fechar exige **Escalada** (handoff) para Fernando coordenar manualmente — nenhuma tool nova, usa o mecanismo de escalada já existente (`escalar` com um motivo apropriado, ex. `outro`/observação livre, já que não é um `TipoEscalada` dedicado no P0).

## Testing Decisions

- **Teste principal (unit, puro):** `calcular_preco_extra_fetiche` — tabela de casos: 1h/preço simples, múltiplas horas (Pernoite-like), programa a preço "quebrado" (não múltiplo exato), zero fetiches pagos. Sem DB, sem rede — mesmo padrão dos testes de `_abaixo_do_piso` já existentes em `api/tests/dominio/atendimentos/`.
- **Teste de integração (`needs_db`):** `adicionar_fetiche` com um `atendimento_servicos` já registrado — confere que `preco_snapshot` gravado bate com o cálculo, para incluso (`NULL`) e pago. Cobrir também o caso de múltiplos `atendimento_servicos` (soma ÷ MAX horas) e o caso de erro (nenhum serviço vendido ainda).
- **Teste do render BP3:** `test_bp3_render.py` (já existe, cobre byte-identidade entre modelos) ganha um caso novo verificando que a tabela de fetiches lista o valor por-programa e que o render continua **byte-idêntico** para duas modelos com o mesmo cadastro de fetiches/programas — não pode variar por turno/conversa.
- **Módulos tocados:** `dominio/atendimentos/service.py` (função nova), `dominio/atendimentos/routes.py` (`adicionar_fetiche`), `dominio/modelos/routes.py` + `schemas.py` (vínculo vira flag), `agente/prompts/fetiches.md.j2`, `agente/nos/prepare_context.py`.

## Out of Scope

- Multiplicador diferente por fetiche (todo fetiche pago vale uniformemente +1x o preço-hora do pacote — ver ADR-0030).
- Modelar Atendimento com duas Modelas (menage tipo b) — permanece escalada manual.
- Migration de schema em `modelo_fetiches.preco` (reaproveita a coluna existente como flag; migration de tipo fica para uma limpeza futura, se necessário).
- Recalcular/backfill de `atendimento_fetiches.preco_snapshot` de atendimentos já fechados — só atendimentos novos usam o cálculo.
- Calibração fina do multiplicador para casos além do documentado na reunião (ex.: um fetiche que valha 2x) — não apareceu nenhum caso real que precise disso.

## Further Notes

- **Ver ADR-0030** (`docs/adr/0030-preco-fetiche-calculado-do-programa.md`) para o histórico da decisão e a reconciliação da aritmética contraditória da transcrição da reunião.
- **Regra de múltiplos serviços no mesmo atendimento** (soma ÷ MAX horas) é inferida por analogia com a convenção já documentada de "duração sugerida", **não foi confirmada explicitamente com Fernando** na reunião — vale checar antes de travar como comportamento definitivo de produção, já que money-math errado é o tipo de bug caro nesse domínio.
- Este spec assume que a UI do cadastro de fetiches (`Serviços e preços`) muda de "campo de valor" para um toggle incluso/pago — ajuste de frontend (`interface/`) faz parte da entrega, mesmo não estando listado como seam de teste automatizado (é UI simples, verificação manual/Playwright basta).
