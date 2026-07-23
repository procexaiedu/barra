# agente/CLAUDE.md

Escopo: subsistema LangGraph que conduz a IA por modelo.

## Direção das dependências (regra dura)

`agente/` PODE importar `from barra.dominio.<x>.service import …`. `dominio/` **nunca** importa de `agente/`. Quebrar isso é bug arquitetural — corrija antes de seguir, não contorne com import tardio.

## Prompts são markdown, com Jinja onde há variável

`prompts/persona.md` e `prompts/regras.md.j2` são a fonte de verdade. O plano (`persona.md`) é markdown puro; os que interpolam variável usam Jinja com sufixo `.md.j2` (ex.: `regras.md.j2` interpola `desconto_degrau_pct`/`desconto_teto_pct` no bloco `<desconto>` — ADR-0031, escalada de 2 rodadas; `docs/agente/09 §4.4`). Para mudar tom ou regra de negócio do agente, edite o markdown — não cole string nova em `graph.py`, `classificador.py` nem em nenhum nó. Strings de prompt hardcoded no código são bug.

## Fronteira conduta ↔ tool description

Recorte da regra acima: tool descriptions (`ferramentas/*.py`, docstrings + `Field(description=…)`) são code-side por natureza — fazem parte do schema enviado ao modelo, então a regra "strings de prompt hardcoded são bug" não as proíbe; **ela delimita o que pode entrar nelas**. O modelo lê o prompt (BP_GERAL) e as tool descriptions no MESMO turno — duplicar conduta não é "senão ele não vê", ele vê os dois. Duplicar compra só redundância + drift (mude o protocolo no `regras.md.j2` e a DESC passa a mentir em silêncio). Três categorias:

1. **Mecânica de campo** (como preencher o arg, computação p/ derivar o valor, idempotência, o que a tool faz no sistema) → **só na DESC**; não migra pro prompt. Ex.: aritmética de horário relativo (`_DESC_HORARIO`), "grave `valor_acordado` junto com `duracao_horas`" (`_DESC_VALOR`), semântica do `limpar`.
2. **Conduta client-facing** (como falar/se portar com o cliente: foto antes de vídeo, desculpa pessoal, jeito de recusar) → **só no `regras.md.j2`**. Se a DESC precisa tocar, **referencia** ("siga sua conduta de X"), não reescreve. Faz certo hoje: o `ToolException` de `ConflitoAgenda` ("ver sua conduta de indisponibilidade"). Faz pela metade: o `Returns` do `consultar_agenda` (referencia E repete).
3. **Tool-selection policy** ("quando chamar / quando NÃO chamar") → versão **curta** na DESC (a Anthropic endossa "be prescriptive about *when* to call it"); o protocolo completo fica no prompt (`<quando_usar_escalar>`, protocolos de disclosure). A DESC aponta a fronteira, não replica o protocolo. **A fronteira NEGATIVA na DESC ("quando NÃO usar") NÃO é alvo de dedup**, ainda quando espelha o protocolo positivo do prompt: a Anthropic é explícita que exemplos negativos "define boundaries and ensure the tool doesn't over-trigger" — afirmar o limite pelos dois lados (positivo no prompt, negativo na DESC) é pedagogia, não duplicação. O "Quando NÃO usar" do `escalar` é o caso certo: complementa `<quando_usar_escalar>`, não o re-cola.

Regra de **leitura** usada nos dois lados (ex.: "cliente diz 'você' = a modelo" — `<tipos_de_encontro>` e `_DESC_TIPO_ATENDIMENTO`): **uma** afirmação canônica, o outro site referencia.

**Dedup não é deleção grátis:** remover uma cláusula de DESC que duplica o prompt pode regredir se o reforço no ponto de uso for load-bearing (cf. sensibilidade do "seria hoje?") — gate por simulador/eval antes de tirar, nunca mecânico.

## Graus de liberdade (onde uma regra nova deve morar)

Ponte estreita → código; campo aberto → prosa. Conduta que exige exatidão determinística (correferência de data, próximo-livre, negação de disclosure sob ataque, idempotência) vira Python/canned/pré-computação; conduta conversacional com muitos caminhos válidos vira prosa no prompt. Sinal de alerta: se um caso novo só funciona quando enterrado numa description gigante de campo (cf. o workaround A2 da extração barata), ele está pedindo o trilho determinístico — mova pro código, não engorde a description.

## Regras com eco multi-site

Algumas condutas têm, de propósito, mais de um site (sanduíche primacy+recency do `<nucleo>`/`<nucleo_final>`, reminder anti-drift, judges autocontidos por serem outro contexto de LLM). Mudou a regra → toque TODOS os ecos; o site canônico define os termos:

- **Empurrão sim/não pós-cotação** — canônico: `regras.md.j2` `<conducao_da_venda>` (Cotação). Ecos: `<nucleo>` linha 5, `<nucleo_final>`, `reminder.md.j2` (condensados), `judge_pos_envio.md` (autocontido).
- **Exemplos de fala com número**: valores são ILUSTRATIVOS concretos (600/1000/500/150), nunca chave `{placeholder}` — chave literal já vazou em prod e exigiu patch no output_guard (`_RE_PLACEHOLDER`). O preâmbulo de `<exemplos>` carrega a instrução de substituição; mantenha novos exemplos nesse padrão.

O gate do reminder (≥8 AIMessages, `_precisa_reminder`) é decisão de grilling 2026-05-23 (proativo > reativo a drift) — não converta para gate por sinal sem novo grilling.

## Escala léxica de dureza nos prompts

Auditada em 2026-07-15 e coerente — mantenha assim: **NUNCA em caps** só para linha dura do `<nucleo>` ou failure-mode comprovado em prod (hoje: sonda-de-balcão, preço inventado, segredo da agenda, menu de formato, unidade, chave Pix); **nunca/nada de** minúsculo para proibição comum; **"só quando/assim que"** para gate; **"prefira/pode"** para default derrotável. Um NUNCA novo em caps precisa se justificar nesse critério — caps banalizado dilui o sinal dos seis existentes.

## Flags deterministicas de disciplina conversacional (padrão A2)

Disciplina do tipo "X é UMA vez (ou até N vezes) na conversa" não pode depender da janela de 20 msgs (o evento desliza pra fora e o LLM repete). Padrão: detecção determinística (regex sobre texto `normalizar()`ado) + tag instrutiva no belief. Instâncias: `<ja_sondou_o_dia>` (janela + atendimento INTEIRO via `mensagens.atendimento_id` — o OR em `_anexar_contexto_dinamico`: a janela cobre a cauda recente incl. `modelo_manual`, o histórico cobre a sondagem que deslizou pra fora das 20 msgs), `<ja_fez_contraproposta>` (atendimento INTEIRO, `_contar_contrapropostas` — ADR-0031, até 2 rodadas: a contagem, não só um bool, é o que muda de degrau pra teto) e `<ja_enviou_book>` (atendimento INTEIRO: qualquer fala da IA com `tipo='imagem'` — mídia de saída persiste assim em `mensagens`, workers/envio.py). As três flags derivam da MESMA query de falas da IA em `_resolver_variaveis` — flag nova nessa família entra ali, sem query extra. Nova disciplina one-shot ou multi-rodada → mesma receita, nunca prosa extra no BP_GERAL.

## Isolamento por par (cliente, modelo)

Ver CONTEXT.md "IA por modelo". A IA da modelo A nunca enxerga histórico do mesmo cliente com a modelo B. Toda função que carrega contexto/histórico recebe `(cliente_id, modelo_id)` juntos; PR que carrega só por `cliente_id` está furando o isolamento — recuse.

## Sem checkpointer no P0

O grafo compila **sem** `checkpointer=` (`docs/agente/01 §6.7`). O prompt é montado do zero a cada turno a partir da tabela `mensagens` (sliding window, `01 §2.2`) — não há estado de conversa entre invocações. Estado vive no Postgres (`mensagens`/`eventos`), nunca em variável de módulo nem dicionário em memória. Continuidade/idempotência vêm de `tool_calls` + `turno_id` determinístico por `(job_id, loop_idx)` (`01 §6.7`), não de checkpoint. Reintrodução só em P1, se vier interrupt/time-travel.

## Prompt caching (chat = DeepSeek V4 Flash direto)

O chat ao vivo roda DeepSeek V4 Flash direto (`ChatOpenAI` → `api.deepseek.com`), que **cacheia o prefixo AUTOMATICAMENTE** no provider — sem `cache_control`, sem breakpoints, sem marcação no código. As tools vão bindadas cruas (schema function-calling OpenAI). Sem checkpointer, a árvore é **re-renderizada todo turno** (`01 §6.7`); o cache hit não depende de reusar o objeto, e sim de o **prefixo (tools + `system`) sair byte-idêntico** entre turnos. A única alavanca que sobra é a **DISCIPLINA de prefixo byte-idêntico** — recriar é correto; o que mata o cache é vazar variabilidade no prefixo. Detalhe em `docs/agente/03-prompts.md §4`.

**Invariante de prefixo global (quebrar isto derruba o cache de TODAS as modelos):**
- Ordem do prefixo, montada por `build_system_messages` (strings puras): **BP_GERAL** (persona+regras FUNDIDOS num único SystemMessage, byte-idêntico entre todas as modelos) → **BP_MODELO** (identidade + programas, num SystemMessage próprio DEPOIS do geral, por-modelo). As tools (constante `TOOLS`, ordem fixa) precedem o `system` no segmento de prefixo.
- `tools` e BP_GERAL são **byte-idênticos entre todas as modelos**. Nenhuma descrição de tool nem BP_GERAL interpola dado por-modelo — o nome da modelo vive só no BP_MODELO. `TOOLS` é constante de módulo congelada, ordem fixa; **proibido** `build_tools(modelo)` ou subsetting de tools por modelo.
- Dado por-modelo só no BP_MODELO. Dado por-turno (contexto dinâmico, reminder) vai na **última HumanMessage** — nunca em bloco `system`. A janela é **append-only** (`ORDER BY created_at, id`): mensagens só entram no fim, então o prefixo da janela sai byte-idêntico entre turnos enquanto a cabeça não desliza, e o provider casa o cache.
- Listas/dicts no prefixo renderizam em ordem determinística (`ORDER BY` / `sorted`), senão os bytes variam e o cache mira a frio em silêncio.

**Guard-rails (testes obrigatórios):** (1) BP_GERAL renderiza byte-idêntico (string pura) para 2 modelos diferentes, só o BP_MODELO difere (`test_bp3_render.py`); (2) a mesma conversa renderiza byte-idêntica em 2 renders (cobre `traduz_mensagens`, pré-requisito do prefixo append-only da janela).

## Organização

`graph.py` (montagem), `estado.py` (TypedDict do State), `classificador.py`, `nos/`, `ferramentas/`. Nó novo → `nos/`. Tool nova → `ferramentas/`. A humanização (chunking/jitter/presence) não vive aqui: roda no worker `enviar_turno` (`workers/`, despachada via `despachar_humanizacao`).
