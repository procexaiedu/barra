---
status: accepted
---

# Output-guard de saída antes da bolha

> **Implementado (AGENTE-OG, 2026-06-01).** Ajuste de wiring vs. a proposta: o despacho da
> humanização roda no **worker** (`coordenador.py`), *depois* do `graph.ainvoke` — não dentro do
> grafo. Logo o `output_guard` entrou como **nó terminal antes do END** (`post_process →
> output_guard → END`, roteando só por `Command(goto=END)`), e o bloqueio se dá por `abrir_handoff`
> (que seta `ia_pausada=true`, detectado pelo cinto-suspensório do coordenador) + bolha zerada.
> Decisões e etapas abaixo valem como implementadas.

> **Supersessão parcial (2026-06-26): o scan determinístico cross-modelo da Etapa 1 foi removido.**
> A Etapa 1 prometia (item c) barrar "qualquer nome/JID de outra modelo" via uma blocklist montada
> de `barravips.modelos WHERE id <> modelo_id`. Na prática isso era **net-negativo**: a IA roda por
> modelo e o `prepare_context` carrega só `WHERE id = %s` — ela **nunca tem em contexto** o
> nome/número de outra modelo, então a blocklist de nomes (primeiros-nomes brasileiros = palavras
> comuns) só podia casar por **coincidência de homônimo** (FP), nunca por leak real. Em 2026-06-26
> isso pausou um atendimento ao vivo: a IA disse o `nome_local` legítimo da própria modelo ("Hotel
> Vitória") e colidiu com outra modelo cadastrada como "Vitória" → `output_leak_cross_modelo`,
> turno zerado, handoff. A parte "dado de cliente do par errado" nunca chegou a ser implementada.
> O **isolamento por par é garantido na camada certa** — o carregamento (`WHERE cliente_id AND
> modelo_id`, canary `test_f0_3_canary_cross_modelo.py`) e `evolution_instance_id` UNIQUE — e o
> **backstop semântico de saída** permanece na Etapa 2 (judge AUP, que pode rotular `cross_modelo`
> sem blocklist). A Etapa 1 mantém o que a IA **pode de fato emitir**: auto-referência de IA,
> fragmento de system/persona e segredo da agenda ("estou com outro cliente"). O teste de gate (2)
> ("nome de outra modelo → bloqueada") foi substituído pelo seu inverso: o `nome_local` da própria
> modelo passa a Etapa 1.

Hoje a defesa do agente é toda de **entrada**: o `_classificador.py` casa 6 padrões fixos de jailbreak (`dan mode`, `developer/dev mode`, `ignore … instructions`, `esquece tudo … você`, `[system]`, `</persona>`) e 2 de disclosure sobre a cauda do cliente, e o `intercept_disclosure` roteia a partir disso. Não existe nenhuma checagem do **texto que a IA vai enviar** antes de despachar a humanização. O `post_process` (`api/src/barra/agente/nos/post_process.py:21-35`) só refaz o fetch de `ia_pausada` e zera a resposta em pausa concorrente; `humanizacao.py` (`api/src/barra/agente/humanizacao.py`) é um stub de uma linha — quem despacha a bolha não inspeciona conteúdo. Como a entrada do cliente é texto não-delimitado e a cobertura do regex é estreita por construção (lista fixa, sem variações de idioma/encoding/parafrase), um jailbreak que escape do classificador, um vazamento do system/persona, ou um vazamento de dado de outra modelo introduzido por uma tool/contexto sai **direto ao cliente**. Para um agente que produz conteúdo íntimo se passando por humana e cujo invariante de produto é o isolamento por par `(cliente, modelo)` + a persona GERAL, a ausência de qualquer rede de saída é gap de prontidão para produção: a falha não é detectável depois (a bolha já foi enviada como `fromMe` no número da modelo).

## Decisões

- **Novo nó `output_guard` entre o `post_process` e o despacho da humanização**, no caminho normal de saída (texto vindo do `llm`/ReAct e a negação canned). Recebe o texto final do turno (todas as bolhas concatenadas) e roda em duas etapas; só despacha a humanização se ambas passarem.
- **Etapa 1 — scan determinístico de vazamento (barato, sempre).** Regex/substring sobre o texto de saída procurando: (a) fragmentos do system/persona/regras (marcadores `</persona>`, `<desconto>`, trechos âncora do `regras.md.j2`/`persona.md`); (b) nomes de modelo de LLM ou auto-referência de IA já cobertos em `PADROES_DISCLOSURE`, agora aplicados à **saída**; (c) **vazamento cross-modelo** — qualquer nome/JID de outra modelo ou dado de cliente que não pertença ao par `(cliente_id, modelo_id)` do turno (lista negativa montada a partir do contexto do turno, não do prompt). Match → **não envia**; abre handoff para Fernando (`TipoEscalada.comportamento_atipico`, observação `output_leak_<motivo>`) e `Command(goto=END)`.
- **Etapa 2 — LLM-judge de AUP vinculante (Constitutional Classifiers, ~1% de custo).** Quando a etapa 1 passa, um classificador Sonnet 4.6 de prompt curto (constituição de saída em markdown próprio, fora do prefixo cacheado por-modelo) julga se a resposta viola a AUP. **Veredito vinculante**: reprovou → bloqueia o envio e escala (`TipoEscalada.comportamento_atipico`, observação `aup_saida`). Mesma porta de escalada do jailbreak de entrada — Fernando assume. Nunca reescreve a bolha (não há auto-correção silenciosa no P0).
- **O fluxo nunca trava silenciosamente.** Falha de infra do judge (timeout/erro) **não** vira "bloqueia tudo" nem "passa tudo": cai num default seguro configurável — bloquear-e-escalar — coerente com "Pix nunca trava o cliente, mas exceção sensível vira handoff". O canned de negação de disclosure **pula a Etapa 2** (texto já é de pool curado), passando só pela Etapa 1.
- **Métricas vivas** (`barra.core.metrics`): `OUTPUT_LEAK_DETECTADO{motivo}` e `AUP_SAIDA_BLOQUEADO`, com o custo do judge medido como % do turno (alvo ~1%). Cirúrgico: nenhum prompt de venda muda, nenhuma tool muda, o prefixo cacheado por-modelo não é tocado.

## Considered Options

- **Só ampliar os regex de jailbreak de entrada.** Rejeitado: defesa de entrada é por natureza incompleta (input não-delimitado, parafrase, idioma, encoding); o gap é a ausência de rede na **saída**, que é onde o dano é irreversível (bolha enviada). Ampliar a lista não cobre vazamento de persona/cross-modelo gerado *dentro* do turno.
- **Reaproveitar o `_classificador.py` aplicando-o à AIMessage final.** Aproveitado em parte (Etapa 1 reusa os padrões), mas insuficiente sozinho: os padrões existentes miram identidade/override do **cliente**, não vazamento de system/dados de outra modelo; e regex não captura violação de AUP semântica — daí a Etapa 2.
- **LLM-judge não-vinculante (só loga/alerta).** Rejeitado: para conteúdo íntimo + impersonação humana, "loga e envia mesmo assim" não fecha o gap de prontidão. O veredito precisa bloquear o envio.
- **Judge que reescreve a resposta para conformar.** Rejeitado por CLAUDE.md (mínimo que resolve) e por risco: auto-correção silenciosa esconde a falha do operador. No P0 a ação é bloquear + escalar para Fernando; reescrita fica para P1 se houver evidência de volume.
- **Guard no webhook de saída do Evolution (fora do grafo).** Rejeitado: o webhook não tem o contexto do par `(cliente_id, modelo_id)` nem a constituição; o lugar natural é o nó de saída do grafo, antes da humanização despachar.

## Consequences

- **Arquivos tocados:** novo `api/src/barra/agente/nos/output_guard.py`; wiring em `api/src/barra/agente/graph.py` (inserir `output_guard` no caminho `post_process → humanização`, roteando por `Command` — sem aresta estática de saída, conforme a armadilha M0-T4 com `Command(goto=END)`); `api/src/barra/agente/nos/__init__.py` (export); `api/src/barra/core/metrics.py` (2 contadores). A escalada reusa `abrir_handoff`/`TipoEscalada.comportamento_atipico` (já importados pelo `intercept_disclosure`).
- **Prompt do judge** mora em markdown próprio (ex.: `agente/prompts/aup_saida.md`), fonte de verdade como os demais — proibido hardcode de string no nó (regra `agente/CLAUDE.md`). É um **prompt separado do prefixo de venda**: não interpola dado por-modelo e **não entra** em BP_GERAL/BP_MODELO/BP_JANELA, então **não afeta o cache hit-rate** do chat principal. Pode ter cache próprio (constituição estável).
- **Custo/latência:** +1 chamada Sonnet curta por turno com resposta (alvo ~1% do custo do turno; latência some na fila de humanização, que já é assíncrona via ARQ). Não roda em turnos que já terminaram sem resposta (pausa, disclosure escalado).
- **Migrations:** nenhuma de schema obrigatória (escaladas e enum já existem). Opcional: enum/observação `output_leak`/`aup_saida` se quisermos distinguir no painel — segue o padrão de migration manual no prod self-hosted (não rodar `make migrate` em prod).
- **Testes (gate):** (1) saída com fragmento de persona/`</persona>` → bloqueada + handoff; (2) saída citando nome/dado de outra modelo do par errado → bloqueada (guarda do isolamento por par); (3) judge reprova AUP → não despacha humanização; (4) judge com falha de infra → default seguro (bloqueia+escala), não envia; (5) canned de disclosure passa pela Etapa 1 e pula a Etapa 2; (6) saída limpa passa as duas etapas e despacha normalmente. Integrar à suíte de evals de AUP (LLM-judge vinculante, zero-vazamento) já prevista.
- **Dependências:** vive no nó de saída, então depende de a humanização ser despachada a partir desse ponto do grafo (estado atual: `post_process → END`, despacho pelo coordenador) — o guard se insere antes do ponto de despacho. Independente das Lanes de cadastro/fetiche; só toca `agente/`. Sinérgico com o tratamento de `refusal`/exaustão já mapeado (mesma porta de escalada para Fernando).
