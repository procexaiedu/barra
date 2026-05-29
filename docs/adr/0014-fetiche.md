---
status: accepted
---

# Fetiche da modelo

> **Changelog — 2026-05-29 (revisão).** A versão original deste ADR (aceita) modelava o fetiche como **flag pura sim/não, sem preço**, num eixo separado dos serviços (a premissa "preço por fetiche / monta a tabela" tinha sido **rejeitada**). Em sabatina de 2026-05-29 o requisito foi revisto: fetiche passa a ser um **extra precificável no campo de serviços**, com **preço opcional** por modelo, **composição registrada no atendimento** e o **desconto de fechamento incidindo sobre o pacote** (programa + extras). Este documento foi reescrito para a decisão nova; o histórico fica neste changelog.

O cliente pediu registrar "o que a modelo faz e o que não faz" — o que ele chamou de "feitiço" e esclareceu ser **fetiche** (o que o cliente pode pedir). Modelamos como um **catálogo global** de fetiches curado no painel + uma marcação **por modelo com preço opcional**, dentro do **campo de serviços** da modelo (como um extra, sem duração), e **exposto ao contexto da IA por modelo** — porque, ao contrário do nível e da ficha cadastral, a IA precisa dele para responder "você faz X?" e cotar o extra na venda. É o cardápio da própria modelo ("coisa dela"), não dado de cliente, então não fere o isolamento por par.

## Decisões

- **Catálogo global + vínculo por modelo com preço opcional.** Tabela `fetiches` (lista curada no painel, como `programas`) + `modelo_fetiches (modelo_id, fetiche_id, preco numeric NULL)`. `preco NULL` = **incluso** (a modelo faz, sem custo extra); `preco` preenchido = **extra pago** que a IA cota ("+R$X"). **Presença de vínculo = faz**; ausência = **não faz**.
- **Sem duração.** Fetiche é um extra no campo de serviços, mas **não tem duração** (diferente de programa × duração). Não entra no cálculo de duração sugerida do atendimento (MAX das horas dos serviços).
- **Negação aberta (sem lista de negativos).** O contexto da IA recebe só os fetiches que a modelo **faz** (com preço/incluso). Qualquer prática fora dessa lista, a IA **recusa de forma curta quando perguntada**, sem enfileirar negativos no prompt nem inventar. Isso mantém o prefixo enxuto e o cache estável.
- **Composição no atendimento (snapshot), Valor final manual.** `atendimento_fetiches (atendimento_id, fetiche_id, preco_snapshot numeric NULL)` registra os fetiches de um atendimento com snapshot do preço (nullable = incluso). Preenchida **por Fernando no painel** (não pela IA), espelhando `atendimento_servicos`. O **Valor final continua digitado manualmente** pela modelo no fechamento — fetiche **não auto-soma**; entra na **decomposição/breakdown** do atendimento, não reescreve o bruto. Repasse, taxa de cartão e comissão de vendedor ficam **inalterados** (não recalculados pelo extra automaticamente).
- **Desconto de fechamento sobre o pacote.** O **Desconto de fechamento** (ADR 0004) passa a incidir sobre o **total cotado** = programa + extras pedidos (Pix de deslocamento sempre fora). O cálculo do pacote é **responsabilidade do prompt** (`regras.md.j2 §desconto`): a IA computa `(programa + extras) × (1 - piso%)` e escala `fora_de_oferta` abaixo disso. A **guarda de código do piso** (`dominio/atendimentos/service.py::_abaixo_do_piso`) permanece como **backstop sobre o programa** — não soma os extras ao vivo (a IA não registra os fetiches da cotação).
- **Alimenta a IA por modelo.** A lista de fetiches que a modelo faz (+ preço) entra no BP3 por-modelo (`agente/nos/prepare_context::_carregar_bp3` → `persona.render_bp3` → `prompts/fetiches.md.j2`), junto de identidade/programas/tipo de atendimento. É uma das **"coisas dela"** (varia por modelo), não a persona (geral e compartilhada).
- **Eixo próprio, distinto do que já existe.** Não é `tipo_atendimento_aceito` (interno/externo = logística) nem `programa` (duração+preço) nem ficha cadastral (RG/medidas). Catálogo separado, mas apresentado **dentro do campo de serviços** no painel.
- **Exceção deliberada à regra "a ficha não vaza para a IA".** A ficha cadastral (ADR 0007) e o **nível** são painel-only e a IA nunca lê. O fetiche **é lido pela IA** porque é cardápio de venda, não PII de gestão. Isolamento preservado: dado da própria modelo, exposto só ao painel e à IA daquela modelo — nunca cruza dado de cliente entre modelos.
- **Catálogo nasce vazio.** Sem seed; Fernando popula a lista mestre pela view de admin "Fetiches". Catálogo vazio = a IA trata como "não faz nada" até ser populado.

## Considered Options

- **Flag pura sim/não, sem preço (decisão original).** Substituída: o requisito passou a exigir preço opcional (extra pago) e composição no atendimento. Ver changelog.
- **Auto-somar o Valor final a partir de programa + extras.** Rejeitado: contraria o design de **Valor final manual** (digitado pela modelo no fechamento) e reabriria o financeiro inteiro (ADR 0011/0013). O extra entra só na composição/breakdown.
- **IA registra os fetiches da cotação para a guarda somar o piso ao vivo.** Rejeitado no P0: ampliaria a superfície de tools e o que a IA escreve no atendimento. O piso-sobre-pacote fica no prompt; a guarda de código segue backstop sobre o programa.
- **Texto livre por modelo.** Rejeitado: a IA consulta texto livre com menos precisão e não há curadoria; catálogo estruturado dá resposta consistente.

## Consequences

- **Tabelas `fetiches` + `modelo_fetiches` + `atendimento_fetiches`** (migration manual no prod self-hosted). Seção "Fetiches" dentro de "Serviços e preços" no cadastro da modelo + view de admin do catálogo global ("Modelos | Programas | Fetiches") + picker no atendimento (`ModalEdicao`) + breakdown nas telas de leitura.
- **`agente/nos/prepare_context` (BP3) inclui os fetiches da modelo** (faz + preço) no contexto por-modelo. Muda o conteúdo cacheado por-modelo do prompt (impacto de cache — ver memórias de cache do agente); aceitável.
- **`regras.md.j2 §desconto`** reescrito para o desconto incidir sobre programa + extras. `desconto_max_pct` segue global; `_abaixo_do_piso` inalterado (backstop sobre o programa).
- **Dado sensível/explícito:** só aparece no painel e no contexto da IA da própria modelo; nunca em telas públicas nem em agregações cross-modelo.
- **CONTEXT.md** atualizado: termo **Fetiche** reescrito (preço opcional, vive em serviços, composição no atendimento, Valor final manual, desconto sobre pacote).
