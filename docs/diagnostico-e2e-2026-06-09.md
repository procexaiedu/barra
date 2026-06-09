# Diagnóstico E2E ao vivo — 2026-06-09 (rig Lucia)

Corrida manual de atendimento E2E no WhatsApp (Fernando digitando), monitorada turno a turno
via LangSmith + Postgres prod (MCP) + logs Portainer. Atendimento ficou **travado em
`Aguardando_confirmacao`** por um bug de mídia inbound (achado #1). Este doc é self-contained:
outro agente retoma sem precisar dos logs vivos (efêmeros já capturados verbatim aqui).

> **Atualização 2026-06-09 — ACHADO #1 resolvido + cascata.** O fix do #1 (mídia base64 inbound)
> destravou o pipeline e expôs dois problemas latentes: **#1b** (`rotear_imagem` passava o id errado
> a `validar_pix` — corrigido) e **#1c** (credencial de OCR vazia no worker — **config pendente do
> Fernando**), além de um defeito de robustez em `validar_pix` (corrigido para honrar "Pix nunca
> trava"). Fluxo mídia→Pix→`Confirmado` **provado em prod**. Detalhes em cada achado abaixo. Único
> item em aberto: setar `OPENROUTER_API_KEY`/`OPENROUTER_MODEL_VISION_PIX` (ver #1c).

## Coordenadas (durável, consultável via MCP)

| | |
|---|---|
| Modelo | **Lucia Teste** `019e60ec-c251-7243-99c1-ea6ef7e603a8` (ativa, vendedor nulo → IA conduz) |
| Conversa | `019eac3f-1fbf-7694-b3ea-a22be91d66de` (= **thread_id** no LangSmith) |
| Atendimento | #1 `019eac3f-30bb-7e44-ad9d-5c54eefd56ee` |
| evolution_chat_id | `120363423572479616@g.us` (grupo cliente-teste do rig) |
| Deploy | revision `46a1104` (depois mudou: fix de mídia subiu novas imagens) · agente roda via ARQ `processar_turno` — memória do projeto diz **`barra-worker`**; ⚠️ NÃO confirmado nesta sessão (os logs do worker que eu li eram de container morto — ver não-achados) |
| LangSmith | projeto `barra-vips-prod` (conteúdo **mascarado `[PII]`** em prod → texto real vem do DB) |

Traces por turno: T1 `019eac3f-30f0` · T2 `019eac40-e99a` · T3 `019eac43-4f69`+`019eac43-6b46`
· T5 `019eac4b-5f48` · T6 `019eac4d-a1fc` · T7 `019eac4f-a6d7` · T8 `019eac52-dcde` ·
**T9 (comprovante): SEM trace** (descartado antes do grafo — ver #1).

## Transcrição (texto real do DB)

```
T1  cliente "oi"                          → IA "oi amor"
T2  cliente "tudo bem?"                    → IA "tudo ótima, e você?"
T3  cliente "que bom, estou bem também." / "quanto é o programa?"
                                           → IA "meu cache 800 1h, ou 1.200 2h 😊" / "tem interesse em qual?"
T5  cliente "nao sei" / "800 1h" / "da?"   → IA "dá sim, 1h comigo 😊" / "você quer vir até mim ou prefere que eu vá até você?"
T6  cliente "consegue vir ate mim?"        → IA "consigo sim" / "qual o bairro e horário que vc tá pensando?"
T7  cliente "to aqui no copacabana palace" / "daqui uma hr"
                                           → IA "ótimo, Copacabana Palace fica tranquilo pra mim 😊" / "lembra que tem o pix de R$100..." / "às 10h15 te serve?"
T8  cliente "ok" / "pode ser 10 15 sim"    → IA "perfeito!" / "pra garantir teu horário, manda o pixzinho do deslocamento 😊" / "chave pix: 12992609133 / Lucia Teste / R$100"
T9  cliente [IMAGEM comprovante]           → (nada — descartada)
```

Progressão de estado: `Novo`(T1-2) → `Triagem`(T3) → `Qualificado`(T7) → `Aguardando_confirmacao`(T8) → **travado**.

---

## ACHADOS

### #1 ✅ RESOLVIDO (2026-06-09) — mídia inbound do cliente era descartada (allowlist anti-SSRF nega o CDN do WhatsApp)
**Sintoma:** cliente mandou comprovante de Pix (imagem) no T9; nada aconteceu — sem `comprovantes_pix`,
sem transição, sem trace. A mensagem virou texto vazio no DB (`tipo=texto`, `conteudo=""`, `media_object_key=null`).

**Causa raiz (confirmada em código + log):** `api/src/barra/webhook/routes.py:44-54`, `_host_permitido`
exige que o host da `media_url` seja **idêntico ao host da Evolution** (fail-closed anti-SSRF). A Evolution
v2.3.6 deste rig devolveu a URL **crua do CDN do WhatsApp** (`mmg.whatsapp.net`), que ≠ host da Evolution → negado.

**Log verbatim (API container, 2026-06-09T12:23:34Z) — efêmero, preservado aqui:**
```
WARNING  download_midia_host_negado host=mmg.whatsapp.net
WARNING  midia_sem_upload_salva_como_texto evolution_id=3B1961B08AC5DF536DC0 tipo_original=imagem
INFO     POST /webhook/evolution HTTP/1.1 200 OK
```

**Impacto:** bloqueia **toda imagem inbound do cliente** → Pix de deslocamento (externo) E Foto de portaria
(interno). Nenhum atendimento que dependa de mídia do cliente passa de `Aguardando_confirmacao`/`Em_execucao`.

**Correção importante ao menu de fix:** a opção "ampliar allowlist p/ `mmg.whatsapp.net`" **não resolve** — a mídia naquele host é cifrada (E2E do WhatsApp), só utilizável após decifrar com a `mediaKey`; um GET cru baixaria ciphertext. A decifragem é responsabilidade da Evolution. E não há ADR de SSRF dedicado: o allowlist é decisão inline em `routes.py` (fail-closed). Prod **não** divergia do rig — mesma Evolution (`evolution3`, v2.3.6), mesmo código → bug universal, nunca exercido porque nenhum cliente real tinha mandado mídia.

**✅ Fix aplicado (commit `d2924e3`, deploy `barra-api`):** a instância Evolution de prod já estava com **Webhook Base64 LIGADO** → entrega a mídia **decifrada inline** no payload. `webhook/parser.py` passou a ler `media_base64` (helper `_media_base64`, tenta `message.base64` e `message.imageMessage.base64`) + `media_mimetype`; `webhook/routes.py` decodifica inline (`_decodificar_base64`, **sem rede → sem SSRF**) quando há base64, mantendo `_baixar_midia` host-locked como fallback. `webhook_max_body_bytes` 1 MiB → 36 MiB (mídia agora viaja inline; base64 infla ~33% sobre `midia_max_bytes`). +7 testes. **Provado em prod:** imagem persiste `tipo=imagem` + `media_object_key` (antes virava `texto`/`null`).

### #1b ✅ RESOLVIDO (2026-06-09) — `rotear_imagem` passava `evolution_message_id` em vez do UUID interno
Destravado o #1, a imagem chegou no worker e expôs o próximo bug: o webhook enfileira `rotear_imagem`
com o `evolution_message_id` (string), mas `validar_pix`/`_handoff_foto_portaria` operam pelo **UUID
interno** de `mensagens.id` (FK + `UUID()` estrito). `rotear_imagem` repassava o id da Evolution →
`validar_pix failed, ValueError: badly formed hexadecimal UUID string`. Nunca aparecera porque nenhuma
imagem passava da borda **e** os testes de integração alimentavam `rotear_imagem` com o UUID interno em
vez do `evolution_message_id` — premissa divergente da produção, que mantinha o caminho verde.
**Fix (commit `e05629a`, deploy `barra-worker`):** `rotear_imagem` resolve o UUID interno
(`_resolver_mensagem_uuid`) sob o lock e o passa aos dois ramos; mantém o `evolution_message_id` no ramo
legenda→turno e no `_job_id`. Testes de `rotear_imagem`/`foto_portaria` agora modelam o webhook (viram
guarda de regressão). **Provado em prod:** `validar_pix` passou a receber o UUID interno.

### #1c 🟡 CONFIG (prod) — `OPENROUTER_API_KEY`/`MODEL_VISION_PIX` vazias no worker → OCR não roda
Com o #1b resolvido, `validar_pix` rodou e bateu em `AttributeError: 'NoneType' object has no attribute
'chat'`: o `vision_client` é `None` porque as 4 env `OPENROUTER_*` do `barra-vips_barra-worker` estão
**vazias** (verificado via MCP). Não é bug de código — é **secret de prod faltando**. **Ação pendente
(Fernando):** setar `OPENROUTER_API_KEY` + `OPENROUTER_MODEL_VISION_PIX` (`anthropic/claude-sonnet-4.6`)
via **Portainer UI** (nunca redeploy-git — zera segredos). Sem isso o OCR não extrai; o Pix cai em
`em_revisao` e o Fernando valida na fila (comportamento correto de fallback, ver robustez abaixo).

### robustez ✅ RESOLVIDO (2026-06-09) — `validar_pix` não pode travar quando o vision falha/ausente
Defeito vs. a invariante **"Pix nunca trava"** (CONTEXT.md / 01 §6.1): `vision_client=None` (ou falha
inesperada do OCR) **crashava** o job e deixava o atendimento preso em `Aguardando_confirmacao` até o
timeout-24h virar `Perdido`. **Fix (commit `743156d`, deploy `barra-worker`):** vision ausente/falho
degrada a `em_revisao` + avança para `Confirmado` (IA pausa, card à modelo), igual aos demais casos
duvidosos. +2 testes. **Provado em prod (foto reenviada):** `comprovantes_pix` criado
(`decisao_pipeline=em_revisao`, motivo "vision indisponivel: credencial de OCR ausente"), atendimento
#1 → `Confirmado`, `ia_pausada=true`, card enviado à Coordenação.

### #2 ✅ RESOLVIDO (2026-06-09) — `registrar_extracao` pulada nos turnos substantivos (FSM defasa)
**Sintoma:** nos T5 e T6 o agente **respondeu sem chamar `registrar_extracao`** (`stop_reason=end_turn`,
`tool_calls=[]`), deixando o estado congelado: valor aceito (800/1h) e tipo (externo) **não persistidos por
2 turnos**. Recuperou no T7 (registrou em lote → `Qualificado`). A extração dependia 100% da boa vontade do
LLM chamar a tool — **sem fallback determinístico** (não está em `STRICT_TOOLS`, sem `INPUT_EXAMPLES`).

**Correção (loop corretivo sob demanda, `agente/nos/llm.py`):** quando o LLM encerra o turno **sem tool_calls
E sem ter chamado `registrar_extracao` neste turno** (`_extraiu_no_turno`, isola por `usage_metadata`), o nó
faz **1 chamada forçada** via `tool_choice=registrar_extracao` (2º bind `chat_forcado`) e despacha pelo
`tools`. A reentrada pós-`tools` fecha o turno direto no `post_process` **sem reinvocar o modelo** (guard
`_extracao_forcada` no `EstadoAgente`) — sem bolha dupla, +1 request **só** nos turnos onde o LLM esqueceu
(~25% no rig). A força roda sobre `state["messages"]` (não inclui o `resp` assistant — evita 2 assistant
consecutivas = 400); o texto ao cliente vai só no update local. Forçado truncado / sem tool_call → descarta
(nunca persiste payload parcial). Kill-switch sem deploy: `settings.forcar_extracao_por_turno` (default True).
A semântica da extração continua sendo do LLM (intenção/valor/tipo) — o determinismo é só a **garantia de que
ela acontece**. +6 testes de roteamento do nó (`test_llm_forca_extracao.py`). **Falta:** prova ao vivo em prod
(gasta crédito, §0 — depende do Fernando rodar um turno substantivo no rig e conferir a FSM avançar no turno).

### #3 ✅ RESOLVIDO (2026-06-09) — PERSONA / coerência (anotações do Fernando)
Quatro anotações, todas tratadas via prompt (texto markdown — nenhuma fixture/eval assere essas frases no
`texto` da IA; só aparecem dentro de `prompt_montado`, snapshot de diagnóstico não comparado byte-a-byte).
Render + invariantes de cache verdes (`test_persona_render`/`test_build_system`/`test_f0_5_faq_render_critico`/
`test_metricas_cache`); gate do agente 196 passed. **Falta:** prova ao vivo em prod (§0 — gasta crédito;
depende do Fernando rodar um turno no rig e conferir a fala).

- **[T2]** ✅ "tudo ótima" — concordância errada; "tudo" pede neutro → "tudo ótim**o**". **Fix:** `<par>` em
  `persona.md` `<armadilhas_de_voz>` (errado "tudo ótima"/"tudo ótimo e vc?" → certo "tudo ótimo, e você?";
  quem está ótimo é "tudo", não você).
- **[T7]** ✅ "**lembra** que tem o pix..." — pressupõe contexto inexistente; foi a 1ª menção ao Pix.
  **Fix:** bullet novo em `regras.md.j2` `<pix_externo>`: "o pedido de Pix é a PRIMEIRA vez que o assunto
  aparece — apresente, nunca relembre. Não use 'lembra que tem o pix' nem 'como te falei do pix'".
- **[T8]** ✅ "**pra garantir teu horário**, manda o pix" — desencontra da mecânica: o horário **já está
  reservado** pelo *bloqueio prévio* (criado no instante do pedido de Pix, T8, bloqueio `019eac52-e9d6`,
  10:15–11:15 BRT), não pelo pagamento. O Pix de deslocamento é **adiantamento do custo de saída** (o uber)
  e o que ele destrava é a transição `→ Confirmado` (IA pausa). Vender como caução do slot é factualmente
  incorreto. **Fix:** a frase cravada em `regras.md.j2:81` virou "pra eu já chamar o uber e ir te encontrar,
  manda o pixzinho do deslocamento" + bloco **Por quê** travando a mecânica (enquadrar como "pra eu sair",
  nunca "pra garantir/segurar teu horário"). Frase escolhida pelo Fernando (uber, não "carro").
- **[T3]** ✅ cardápio parcial: cliente perguntou "o programa" (genérico); IA cotou só **Programa Completo**
  (800/1h, 1.200/2h), omitindo Massagem Relaxante (300/500) e Acompanhante Jantar (1.000/3h). (Preços batem
  com `modelo_programas` — não alucinou.) **Decisão do Fernando:** manter âncora alta + **ponte curta**
  (não despejar o leque). **Fix:** `<cotacao>` ganhou regra + `<exemplo_cotacao_generica_com_ponte>` —
  cota o principal e, em bolha separada, "tenho outros programas também se preferir". (Hoje o catálogo da
  Lucia é só de teste; em prod haverá mais programas — daí a ponte fazer sentido.)

### #4 ✅ RESOLVIDO (2026-06-09) — AGENDA: disponibilidade afirmada sem conferir o contexto
**Sintoma:** no T7 a IA afirmou disponibilidade ("fica tranquilo pra mim", "10h15 te serve?") **sem chamar
`consultar_agenda`**. Inócuo aqui (Lucia tem agenda vazia), mas em agenda real = risco de afirmar slot ocupado.

**Diagnóstico (parcial falso-positivo + buraco real de prompt):** a agenda das próximas 48h **já é injetada
no contexto** todo turno (`prepare_context.py:411-424` → bloco `<agenda janela="próximas 48h">` em
`contexto_dinamico.md.j2:14-17`, com `<bloqueio>`/`<livre>`). O design é **híbrido por desenho**: para slot
**≤48h** a IA responde do contexto **sem** tool; `consultar_agenda` é só para **>48h** (`regras.md.j2`
`<tools_disponiveis>` + docstring `leitura.py:25-27`). No T7 o cliente pediu "daqui uma hr" (≈10:15, dentro de
48h) → **não chamar a tool foi o comportamento correto** (chamar contraria o design). O resíduo real: as
instruções de agenda no prompt eram **100% reativas** (`<indisponibilidade>` só cobria "quando o cliente pede
horário que cai num bloqueio") — nada mandava a IA **conferir o `<agenda>` antes de ela própria propor/cravar**
uma hora; e para **>48h** `consultar_agenda` é voluntária (nunca forçada) → risco de cravar data distante às cegas.

**Pesquisa de melhores práticas (valida não-forçar tool):** o padrão **híbrido** (pré-carregar o subconjunto
estável + tool just-in-time para o resto) é o recomendado pela Anthropic ("just-in-time vs pre-loading"; é o
próprio padrão do Claude Code: CLAUDE.md pré-carregado + grep on-demand) — logo **forçar tool / guard
determinístico para ≤48h seria errado**. E o prompt é a **primeira linha de defesa** contra afirmação infundada:
instruir explicitamente *grounding* ("só afirme a partir do que está no contexto") + *verify-before-assert*.

**✅ Fix (prompt-only, `regras.md.j2` bloco `<indisponibilidade>`):** instrução proativa de grounding —
"**antes de cravar ou propor qualquer horário, inclusive quando é você quem sugere a hora, confira o `<agenda>`:
só ofereça horário livre, nunca um `<bloqueio estado="ocupado">`**; para um dia **além das 48h**, chame
`consultar_agenda` antes de afirmar — não prometa data distante sem conferir". Texto estático no BP_GERAL (sem
interpolação por-modelo → não viola a invariante de cache cross-modelo). Gate do agente verde (947 passed,
inclui guard-rails de render e de byte-identidade do BP_GERAL). **Falta:** prova ao vivo em prod (§0 — gasta
crédito; depende do Fernando rodar um turno com agenda não-vazia e conferir a IA respeitar o bloqueio).

(Nota: o bloqueio prévio foi criado depois, no passo do pedido de Pix (T8), e passou pelo gate de Disponibilidade
— sem regras → reservável sempre.)

### #5 ✅ RESOLVIDO (2026-06-09) — sinais de qualificação defasaram e auto-corrigiram
**Sintoma:** no T7 `aceita_valor=false`/`informa_horario=false` apesar dos campos estruturados
(`valor_acordado`, `horario_desejado`) preenchidos; o T8 re-registrou corrigindo. Ruído transitório,
sem impacto de estado — a FSM (`_decidir_transicao`) ignora os sinais (só lê os campos), então o
único consumidor afetado era o filtro `qualificacao_completa` do painel (`atendimentos/routes.py:102`).

**Causa raiz:** os dois booleans eram **redundantes** com campos que o mesmo payload já carrega —
`aceita_valor` ≡ `valor_acordado` preenchido (= "Valor total **acordado**"; abaixo-do-piso nem grava),
`informa_horario` ≡ `horario_desejado` preenchido (docstring só manda preencher com hora concreta).
O LLM preenchia o campo mas esquecia o boolean (extração com `exclude_defaults=True` dropa o `False`) —
mesma classe do #2 (depender da boa-vontade do LLM marcar o sinal).

**✅ Fix (`dominio/atendimentos/service.py`):** `_montar_upsert` passou a chamar
`_sinais_qualificacao_derivados`, que parte dos sinais que o LLM passou e **deriva
deterministicamente** os dois redundantes a partir do campo estruturado (`valor_acordado`→`aceita_valor`,
`horario_desejado`→`informa_horario`). Não deriva ao `limpar` o campo (cliente recuou) e o merge `||`
só adiciona True (nunca rebaixa sinal já gravado). Os sinais não-deriváveis (`responde_objetivamente`,
`envia_pix`, `informa_local`) seguem julgados pelo LLM. Prompt e FSM intocados. +7 testes unitários
(`test_atendimentos_sinais_derivados.py`); lint/typecheck/snapshot verdes. Validado contra as melhores
práticas da Anthropic (*Writing effective tools for agents* — minimizar carga cognitiva, fonte única,
não pedir ao modelo o que o código deriva). **Falta:** rodar o `needs_db` (`test_registrar_extracao.py`)
contra o DB real antes do push (gate §0 — código DB-adjacente; payloads atuais não exercitam o ramo novo).

### #6 ✅ RESOLVIDO (2026-06-09) — TIMEZONE no card de Coordenação: hora exibida em UTC, não BRT
**Sintoma:** o card "saída confirmada" enviado à Coordenação (14:42:12) mostrou **`🕒 13:15`** onde o
horário combinado é **10:15 BRT**. As três queries de card com horário em `workers/envio.py` (`_card_pix`,
`_card_chegada`, `_card_aviso_saida`) selecionavam `b.inicio AS bloqueio_inicio` **cru** — `bloqueios.inicio`
é `timestamptz` (`0001_schema_inicial.sql:505`), então psycopg devolvia datetime aware em UTC e o template
`_cards/*.md.j2` (`horario.strftime('%H:%M')`) imprimia UTC. Contrasta com a camada conversacional (LLM),
que disse "10h15" correto ao cliente — o bug era só na **formatação determinística do card**, não no
contexto do agente. Mesma classe de bug em três cards (pix, "cliente chegou", "cliente saiu"); o
`lembrete_valor` já estava correto (converte `b.fim AT TIME ZONE` em `atendimentos/service.py:200`).

**Pesquisa de melhores práticas:** dois padrões válidos — converter no banco (`AT TIME ZONE`) ou em Python
(`astimezone(ZoneInfo(...))`). O repo **já padroniza no banco** (`AT TIME ZONE 'America/Sao_Paulo'`) em todo
lado (lembrete_valor, financeiro, pix/atendimentos routes, `prepare_context`), então o fix consistente é o
mesmo padrão DB-side, que devolve `timestamp` naive já em BRT, pronto p/ `strftime` no template.

**✅ Fix (`workers/envio.py`, SQL-only):** as três queries passaram a selecionar
`(b.inicio AT TIME ZONE 'America/Sao_Paulo') AS bloqueio_inicio`. Render verificado (`🕒 13:15` → `🕒 10:15`),
lint + typecheck verdes. Nenhum teste asseria a hora do card. **Falta:** prova ao vivo em prod (§0 — depende
de um novo Pix/aviso no rig para reemitir o card).

Texto verbatim do card (antes do fix):
```
⚠️ *Pix recebido #1* — cliente
Confira antes de sair: vision indisponivel: credencial de OCR ausente
📍 Copacabana Palace
🕒 13:15            ← deveria ser 10:15 (BRT)
💰 Combinado R$ 800.00
```

### #7 ✅ RESOLVIDO (2026-06-09) — auditoria do card de Pix sem linkage + payload mínimo nos lembretes
A linha do card de saída confirmada em `envios_evolution` tinha `atendimento_id=NULL` e `conversa_id=NULL`
(os cards `lembrete_valor` têm `atendimento_id`). Inconsistência de auditoria — a idempotência seguia ok via
`comprovantes_pix.card_message_id`. Bônus: os envios `lembrete_valor` gravavam payload mínimo
`{"card_kind":"lembrete_valor"}` em vez do payload Evolution completo (key/message), enquanto os textos da
IA gravam o payload inteiro — dificultava reconstruir o texto do lembrete a partir da auditoria.

**Causa raiz (dois pontos independentes):**
1. **Linkage** — os renderers de card em `workers/envio.py` (`_card_pix`, `_card_escalada`, `_card_chegada`,
   `_card_aviso_saida`) chamavam `enviar_texto`/`enviar_midia` **sem** `atendimento_id`/`conversa_id`, gravando
   `NULL` nas duas FKs. Só `lembrete_valor` passava `atendimento_id`. O schema (`0002_envios_evolution.sql`)
   **já tem** as FKs + índices parciais dedicados (`envios_evolution_atendimento_created_idx`,
   `..._conversa_created_idx`) — foi desenhado para o linkage; era só preenchimento esquecido.
2. **Payload** — `enviar_texto`/`enviar_midia` faziam `payload=payload or data`: quando o caller passava um
   marcador (`lembrete_valor` → `{"card_kind": ...}`), ele **substituía** a resposta completa da Evolution
   (que carrega o texto), perdendo a reconstrução.

**Pesquisa de melhores práticas:** linha de auditoria que *concerne* uma entidade deve carregar FK para ela
(queryável — e aqui os índices parciais já existiam) e deve preservar o **snapshot completo** do payload, com
um marcador de **classificação** adicional, em vez de trocar um pelo outro. Os dois padrões (FK denormalizada
para query + JSON imutável para reconstrução) são complementares, não excludentes. ([Red Gate — Database Design
for Audit Logging](https://www.red-gate.com/blog/database-design-for-audit-logging/); [Audit Log Paradigms &
PostgreSQL Patterns](https://dev.to/akkaraponph/comprehensive-research-audit-log-paradigms-gopostgresqlgorm-design-patterns-1jmm)).

**✅ Fix (`core/evolution.py` + `workers/envio.py`):**
- **Payload (B):** `payload or data` → `{**data, **payload} if payload else data` em `enviar_texto` **e**
  `enviar_midia` — o marcador do caller **mescla** sobre a resposta da Evolution (não substitui). `lembrete_valor`
  segue passando `{"card_kind": ...}` (intocado): agora a linha tem o `data` completo + `card_kind` queryável.
  A query de toques (`payload->>'card_kind'` em `lembrete_valor._buscar_alvos`) continua válida. Comentário inline
  cravando a semântica para impedir regressão de "simplificação".
- **Linkage (A):** os quatro renderers passaram a propagar `atendimento_id` + `conversa_id` (o `_card_pix` já
  tinha `atendimento_id` no payload do job; os demais leem `a.conversa_id`/`e.atendimento_id` da query, colunas
  que **já** estavam nas próprias queries via JOIN). Fix estendido aos 4 (não só o Pix nomeado) porque é o mesmo
  defeito de classe — deixar 3 com `NULL` só deslocaria a inconsistência.

**Verificação:** `make lint` + `make typecheck` verdes; suíte padrão **959 passed** (sem regressão; os asserts
de `test_lembrete_valor`/`test_evolution_ext` checam o *kwarg* passado e o request body, não o payload final
gravado, então o merge não os toca). **Falta:** rodar os `needs_db` (`test_enviar_card.py`) contra o DB real
antes do push (gate §0 — código DB-adjacente; `TEST_DATABASE_URL` não estava setado nesta sessão) e prova ao
vivo (um novo Pix/card no rig reemitindo a linha com as FKs preenchidas).

### #8 ✅ RESOLVIDO (2026-06-09) — comando de grupo da Coordenação levava 403 por `jid_permitido` (limitação do rig, não bug de prod)
Ao tentar fechar (`Em_execucao → Fechado`) mandando `finalizado 800` no grupo de **Coordenação**
(`...407815206369`), o webhook respondeu **403 Forbidden** e nada aconteceu (estado intacto, 0 eventos).
**Causa:** `webhook/routes.py:162` — `if settings.jid_permitido and msg.remote_jid != settings.jid_permitido: → 403`.
O rig pina `jid_permitido` no **grupo do cliente** (`...479616`) para isolar o teste; como `jid_permitido`
aceitava **um único JID** (flag Fase 1.5), o inbound da Coordenação era barrado **na porta**,
antes do parser de comando avaliar card-reply / `#N` / valor.
**Provado (antes do fix):** dois POSTs → 403 — `15:57:40` (mensagem solta) e `16:02:26` (resposta ao card).
Ambos 403 → **não é o card-reply** (regra real e correta, mas nem chega a ser avaliada). Em **prod real**
(`jid_permitido` vazio) o comando da Coordenação sempre funcionou — por isso nunca foi bug de prod.

**Por que resolver mesmo sendo limitação do rig:** o workaround do painel (Registro de resultado via REST)
**pula o webhook inteiro** — o caminho de comando de grupo (`finalizado`/`perdido`/`ia assume`), card-reply,
parser de valor BR e eco de confirmação **nunca era exercido no E2E ao vivo**. Foi tentando esse caminho que
o #8 apareceu; mantê-lo fora de cobertura E2E mascara regressões nele.

**✅ Fix (`settings.py` + `webhook/routes.py`):** `jid_permitido` virou **allowlist** (`list[str]`, era `str`),
igual à convenção de `evolution_fernando_jids`/`reset_teste_instances`. O gate passou a `msg.remote_jid not in
settings.jid_permitido`. O rig agora pina os **dois** JIDs (cliente + Coordenação) — `JID_PERMITIDO=["...479616@g.us","...407815206369@g.us"]`
no compose — mantendo o espelho do cliente E destravando o fechamento pelo grupo. Backward-compat: um
`field_validator(mode="before")` + `NoDecode` aceita os três formatos no env (vazio → `[]`; JID cru único
→ `[JID]`, compat com deploys antigos; lista JSON `["a","b"]`). +2 testes de gate (`test_webhook_integration.py`:
403 fora da allowlist · Coordenação liberada além do cliente) — antes o gate **não tinha cobertura nenhuma**.
Suíte padrão **961 passed**, lint + typecheck verdes.

**Para aplicar no rig de prod:** o compose já carrega os dois JIDs; basta o redeploy carregar o novo `JID_PERMITIDO`
(via Portainer UI / git-backed stack, **nunca** redeploy-git sem `Env` — §0). Sem isso, o painel segue como
workaround (fecha com valor, sincroniza bloqueio `019eac52 → concluido`, recalcula financeiro).

---

## NÃO-ACHADOS (verificados e OK — não perseguir)

- ✅ **Hora/TZ no contexto**: "daqui uma hr" às 09:15 BRT → IA cravou **10:15** (correto). O bug histórico
  de "só `current_date` sem hora" **não se manifesta** nesta revisão. (Comportamental; confirmar no código de
  injeção de contexto se quiser certeza.)
- ✅ **Coalescência de debounce (Redis)**: mecanismo = `_job_id` estático SET NX + `_defer_by=4s`
  (`webhook/despacho.py`), **não** janela de silêncio. Provado: T3 (msgs 4,2s apart > 4s → 2 runs, correto);
  T5 (3 msgs <3s apart → **1 run só**, coalesceu). `lock:conv` serializa, sem corrida, sem resposta dupla.
- ✅ **Worker de crons SAUDÁVEL** — *falso alarme inicial*. Container `oyhisvdv`/`c91d7898` saiu (137, churn
  normal de redeploy) às 11:56 e o Swarm subiu `qm0a59gv`/`ef2653d9` no mesmo instante; os crons logam de
  minuto em minuto (verificado 12:30–12:33). O erro foi fixar o ID do container velho às 11:36. **Lição p/ o
  próximo agente: re-resolver o container (`barra-worker` E `barra-api`) a cada checagem, nunca cachear o ID
  (armadilha Swarm).** Reincidiu: a `barra-api` foi redeployada com o fix de mídia e o container `430cf461`
  morreu às 14:07 — logs lidos do defunto até re-resolver pro vivo `1898e9f0`. Qualquer deploy troca o container.
- ✅ **Quote (reply/citação) nunca exercitado na jornada** — *não é bug; gatilho não ocorreu*. A IA não
  citou nenhuma mensagem do cliente, mas o mecanismo está fiado de ponta a ponta: o LLM emite `[quote]` no
  início da bolha (`prompts/regras.md.j2:304-328`, bloco `<quote>`), o worker mapeia para a **última msg do
  cliente do turno** (`workers/coordenador.py:390-400` → `quote_msg_ids`) e `workers/envio.py:602-616` manda
  com `quoted.key.id` + `quoted.message.conversation` (texto ecoado obrigatório — Evolution v2.3.6 não faz
  lookup pelo id). Quem **decide** citar é o LLM, e a persona instrui usar `[quote]` **só** em 3 casos
  (recusa de prática específica · qualificação de pergunta solta · repetir dado que o cliente ignorou) e
  **NÃO** em saudação/cotação/fechamento. A jornada foi happy-path puro (saudação T1-2 → cotação T3/T5 →
  confirmação logística T6/T8) — caiu inteira fora dos gatilhos, metade na lista de *não-use*. Código presente
  e condições não atingidas; **não confirmado em prod que o balão de reply renderiza certo no celular**.
  **Teste mínimo p/ exercitar:** mandar "vc faz anal?" (prática que ela recusa) — gatilho mais determinístico
  do `<quote>`, deve sair com `[quote]` na bolha de recusa.

---

## Estado atual do atendimento (atualizado 2026-06-09, ~15:53)

**`Em_execucao`** · externo · valor_acordado 800 · duração 1h · Copacabana Palace (hotel) ·
horário 10:15 BRT · `pix_status=em_revisao` · `ia_pausada=true` (`modelo_em_atendimento`) ·
`responsavel_atual=modelo` · bloqueio `019eac52-e9d6` (10:15–11:15 BRT).

Cadeia completa pós-comprovante (provada em prod): imagem persiste `tipo=imagem`+MinIO (14:42:10, #1
ok) → `comprovantes_pix` `019eacd5-78f3` `em_revisao` (OCR ausente, #1c) → card "saída confirmada" à
Coordenação (14:42:12) → **`Confirmado`** (IA pausa) → cron `confirmar_em_execucao` → **`Em_execucao`**
(14:43, `fonte=cron_em_execucao`; horário 13:15 UTC já passado) → **Lembrete de fechamento** (`lembrete_valor`)
disparando à Coordenação a cada ~30min (14:44 / 15:14 / 15:45), **sem escalada ainda** (não atingiu máx. toques).

**Último passo para `Fechado`:** a modelo responde no grupo de Coordenação com `finalizado/fechado [valor]`
→ `Fechado` (exige valor final) + sincroniza bloqueio `019eac52` → `concluido` + recalcula financeiro.
Único pendente de infra: **#1c** (setar `OPENROUTER_API_KEY`/`OPENROUTER_MODEL_VISION_PIX` via Portainer UI);
sem isso o Pix permanece `em_revisao` (correto — degrada, não trava).
