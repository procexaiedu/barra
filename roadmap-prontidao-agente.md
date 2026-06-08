# Roadmap de Prontidão do Agente — Matriz inteira → Coberto

> Fonte de execução para um agente (Claude Code) consumir. O par visual humano é
> `roadmap-prontidao-agente.html`. Baseado em `relatorio-prontidao-agente.html`
> (levantamento de cobertura de 2026-06-08).

## Objetivo

Levar **os 8 eixos da matriz de prontidão** de seu status atual a **Coberto** — ou
seja, cada dimensão com uma rede **determinística** que **bloqueia merge** (gate de PR),
ou — nas dimensões subjetivas — **revisão humana documentada contra a golden** (sem judge
automático), não só "a fonte/mecânica existe".

Estado de partida (relatório):

| Eixo | Status hoje | C/P/G | Falta para Coberto |
|---|---|---|---|
| 1 · Persona & voz | Parcial | 6/4/0 | gate determinístico de voz sobre a fala gerada ✅ (F3.3); falta a ★API ao vivo + revisão humana |
| 2 · FAQ & conhecimento | **Frágil** | 1/3/6 | gate determinístico de render (F0.5) + conduta da fala (parcelado/só-pix/over-refusal) ✅ (F3.4); falta a ★API ao vivo + revisão humana |
| 3 · Tool calling | Parcial | 11/2/5 | **decisão** (tool certa/proibida), não-inventar-write |
| 4a · Trajetória atômica | Coberto | 13/1/4 | 4 gaps atômicos + timeout 45min no banco real |
| 4b · Conversa completa (E2E) ★ | **Gap (gate)** | 23 jornadas · 0 gate | E2E como gate determinístico + revisão humana, fechar a venda |
| 5 · UX / humanização | **Coberto** | 13/2/1 | — (F1.1–F1.4 fechados: cadência/ritmo + costura webhook→estado + debounce/`fromMe` + limite de bolha) |
| 6 · Invariantes de domínio | Parcial | 6/5/1 | 3 de 5 só instrução: piso, "outro cliente", PII |
| 7 · Guardrails custo/segurança | Parcial | 9/1/4 | teto R$ em prod + write-rate automático |

## Princípio que governa o sequenciamento — **duas moedas**

- **Determinístico (moeda barata):** roda no `make test` sem tocar a API. Compute
  Claude Code é abundante. **Faça primeiro e por inteiro** — fecha vários itens
  Parcial/Gap a custo ~zero.
- **★ API (moeda escassa):** exige crédito Anthropic + grafo real (runner K=5,
  `gerar_conversas`). Memória `anthropic_creditos_esgotados_prod`: **crédito de prod
  esgotado** → fases ★API ficam **bloqueadas até restaurar billing**. Não desperdice.
- **Humano (operador):** rotulagem do golden por Fernando + sócia (+ 3º rotulador
  procex). Pode rodar **em paralelo** ao trabalho determinístico — mas **não é mais
  caminho crítico**: com o LLM-judge rejeitado (ADR 0015), a golden deixou de calibrar
  juiz e virou **referência held-out** para diff manual + mina de graders determinísticos.

Critério de "Coberto" por item: **gate de PR vermelho quando o item regride**, com
critério de sucesso verificável. Itens `gate-info`/advisory **não contam** como Coberto.

---

## Fase 0 — Rede determinística sem API (desbloqueada, faça já)

> Moeda barata. Fecha de uma vez a maior parte dos Gaps de Invariantes (6), parte de
> FAQ (2) e os 4 gaps atômicos de 4a — sem gastar 1 token de API.

| ID | Item | Fecha | Critério de sucesso (verificável) | Onde (pointer) |
|---|---|---|---|---|
| **F0.1** ✅ | Postgres efêmero no CI (service container) | habilita F0.6/F0.7/F0.8/F0.9/F0.10 | needs-DB roda no CI limpo, não pulado nem apontando p/ prod | `.github/workflows`, `conftest` `TEST_DATABASE_URL` |
| **F0.2** ✅ | Assert: montador de contexto **nunca** carrega campo painel-only (RG/CPF/endereço residencial/tipo físico/perfil preferido/mapa) | Inv. PII | teste falha se qualquer campo PII entra no prompt do agente | `agente/prepare_context.py` |
| **F0.3** ✅ | Assert: montador + tools **nunca** trazem dado do par B na **entrada** (canary cross-modelo) | Inv. cross-modelo (entrada) | teste com canary do par B falha se vaza no contexto/args | `agente/prepare_context.py`, `agente/ferramentas/` |
| **F0.4** ✅ | Estender `output_guard` p/ pegar "estou com (um) cliente / outro cliente agora" | Inv. "estou com outro cliente" | bolha confessando outro cliente é barrada e vira handoff (igual ao scan de IA/outra modelo) | `agente/` output guard |
| **F0.5** ✅ | Render de FAQ asserta **itens críticos presentes** no prompt entregue (recusa videocall, Pix R$100 separado, taxa 10%, sem parcelamento) | FAQ (fonte→conteúdo) | edição que apaga um item crítico quebra o teste | grader de render FAQ |
| **F0.6** ✅ | Timeout interno 45min contra **banco real** (gêmeo do de 24h) | 4a | `Aviso sem Foto → Perdido(sumiu)` + cancela bloqueio, provado no Postgres (FOR UPDATE + agregação) | `workers/timeouts.py` |
| **F0.7** ✅ | Atômico: imagem em **externo** `Aguardando_confirmacao` = comprovante Pix (não Foto de portaria) | 4a | roteamento correto provado no banco real | despacho de imagem |
| **F0.8** ✅ | Atômico: `Em_execucao → Fechado` pelo comando da modelo no grupo (gatilho isolado) | 4a | `fechado [valor]` respondendo card → Fechado + Valor final + bloqueio concluído | `dominio/atendimentos/` |
| **F0.9** ✅ | Atômico: Lembrete de fechamento — reenvio em intervalos até máximo + Handoff após silêncio | 4a | reenvio e abertura de handoff provados isolados (hoje só a seleção de alvos) | `workers/`, lembrete |
| **F0.10** ✅ | "Nunca trava por Pix" (needs-DB) vira gate confiável no CI | Inv. nunca-trava-Pix | os 4 ramos rodam no Postgres efêmero a cada PR (depende de F0.1) | teste Pix existente |

**Saída da Fase 0:** Invariantes 6 → **Coberto**; 4a → **Coberto** pleno; FAQ ganha
gate de conteúdo (ainda Frágil em conduta, fecha na F3).

> **Status F0.1 ✅ (feito, PR #75):** CI sobe `postgres:15` (service container, espelha
> o Supabase 15.8 de prod), aplica o **schema** (`MIGRATE_SKIP_SEEDS=1` — needs_db
> semeiam os próprios dados; pular seeds evita o FK `seed→auth.users` e mantém a CI
> limpa) sobre um **bootstrap Supabase** (`infra/sql/ci/bootstrap_supabase.sql`: roles,
> `auth.users`/`auth.uid()`, publication `supabase_realtime`) e roda os `needs_db` com
> `TEST_DATABASE_URL` apontando p/ o efêmero local. Gate determinístico
> (`api/tests/test_f0_1_ci_postgres_efemero.py`) reprova o PR se a wiring regredir.
> **Pendência:** a corrida ao vivo da CI não rodou — GitHub Actions está **bloqueado por
> billing** na conta (`account is locked due to a billing issue`). Destravar o billing
> do GitHub e re-rodar o job `verify` do PR #75 fecha a prova viva. Merge local feito;
> F0.6–F0.10 já podem usar o Postgres efêmero.

> **Status F0.2 ✅ (feito, merge local):** gate determinístico **sem banco**
> (`api/tests/agente/test_f0_2_pii_painel_only.py`) que extrai por **AST** o SQL de todos os
> `conn.execute(...)` do montador (`agente/nos/prepare_context.py`) e reprova o PR se qualquer
> coluna painel-only for selecionada: PII sensível (RG/CPF/endereço residencial), resto da ficha
> cadastral (cor de pele/cabelo, altura, pé), tipo físico, perfil físico preferido e coordenada
> do Mapa de clientes (ADRs 0006/0007/0008). AST (não grep no fonte) p/ não confundir SQL com os
> comentários do módulo que citam essas colunas legitimamente; match por palavra inteira, então
> `endereco_residencial_formatado` (proibido) não colide com o `endereco` operacional do
> atendimento (que a IA precisa ler no externo). Âncora anti-vácuo confirma extração não-vazia.
> Roda no `make test` padrão — **não** é `needs_db`, então não fica pulado sem `TEST_DATABASE_URL`
> (gate de PR de verdade, não dependente de F0.1). Vermelho→verde provado injetando
> `rg`/`tipo_fisico` num SELECT do montador. O montador hoje já não carrega nenhum painel-only;
> o teste tranca a invariante contra regressão.

> **Status F0.3 ✅ (feito, merge local):** canary `needs_db`
> (`api/tests/agente/test_f0_3_canary_cross_modelo.py`) que tranca o isolamento por par
> `(cliente, modelo)` — a IA da modelo A nunca enxerga contexto/histórico do **mesmo cliente**
> com a modelo B (CONTEXT.md "IA por modelo"). Semeia o **par B** (mesmo cliente, modelo
> distinta) com um token sentinela em toda superfície legível — janela de mensagens,
> `observacoes_internas` da conversa, atendimento terminal (histórico) e bloqueio de agenda em
> 48h — e roda o montador inteiro (`prepare_context`) **+** a tool `consultar_agenda` escopados
> ao par A; falha se o token (ou qualquer marca do par B) vazar no contexto montado ou no
> retorno da tool. Âncoras anti-vácuo (`_MARCO_A`) provam que o montador produziu o contexto do
> par A — sem elas o "canário ausente" seria um verde vazio. **`needs_db` de propósito:** o
> isolamento vive nas cláusulas `WHERE cliente_id=%s AND modelo_id=%s` do SQL real — um
> `FakeConn` devolve o que lhe dão e não prova a filtragem; espelha o rig de
> `test_repo_integracao.py` (TEST_DATABASE_URL, ROLLBACK sempre). Pós-F0.1 roda no Postgres
> efêmero do CI. Dentes provados (vermelho→verde): quebrar o filtro de modelo em
> `carregar_mensagens` vaza o token na janela; quebrá-lo na query de bloqueios rouba a agenda;
> quebrá-lo em `consultar_agenda` lista o bloqueio do par B — os 3 deixam o teste vermelho.

> **Status F0.4 ✅ (feito, merge local):** gate determinístico **sem banco** que estende o
> marcador `_MARCADORES_OUTRO_CLIENTE` da Etapa 1 do `output_guard`
> (`agente/nos/output_guard.py`) — o segredo da agenda (CONTEXT.md "Agenda — comportamento da
> IA": a IA recusa horário em bloqueio com **desculpa pessoal** e **nunca** revela que está com
> outro cliente). A rede já existia (commit `d6bc953`) pegando o n-grama literal "com um
> cliente"; a F0.4 fechou as variantes igualmente inequívocas que vazavam: **"com outra/mais uma
> pessoa"** (ocupada com alguém), **"tô/estou atendendo"** sem objeto-interlocutor (atende
> *alguém*, não o próprio cliente) e **"no atendimento" / "no meio de (um|outro) atendimento"**.
> Mesma porta do scan de IA/outra modelo: match → handoff p/ Fernando (`ia_pausada=true`,
> `comportamento_atipico`) + bolha zerada, motivo `output_leak_outro_cliente`. Conservador de
> propósito (só frases que **só** podem significar outro cliente) — falso-positivo vira handoff
> seguro, vazamento é irreversível. O lookahead `(?!\s+(voc|vc|te…))` protege a fala legítima de
> **atender o próprio cliente** ("te atendendo", "atendendo você"), coberta por 3 casos
> anti-falso-positivo. Roda no `make test` padrão (não `needs_db`, regex puro): gate de PR de
> verdade. Vermelho→verde provado pelas 5 variantes parametrizadas em
> `test_etapa1_outro_cliente_variantes_bloqueia` (todas passavam batido antes da extensão).
> `make test`: 834 passed. mypy + ruff limpos.

> **Status F0.5 ✅ (feito, merge local):** gate determinístico **sem banco**
> (`api/tests/agente/test_f0_5_faq_render_critico.py`) que tranca os itens críticos da FAQ
> contra o **prompt entregue** — assertando sobre `render_prefixo_geral()` (o BP_GERAL fundido
> persona+regras+FAQ, ponto de entrada sancionado em `agente/persona.py:93` p/ reproduzir o
> conteúdo do bloco geral sem byte-drift). 4 itens parametrizados, cada um com os fragmentos
> mínimos que o identificam: **recusa de videochamada** (`video chamada eu nao faço`), **Pix de
> R$100 do deslocamento separado do programa** (`R$100`+`deslocamento`+`separado do valor do
> programa`), **taxa de cartão 10%** (`10%`+`maquininha`) e **cartão sem parcelamento**
> (`não parcelo`). Apagar/reescrever o item a ponto de sumir o fragmento deixa o teste vermelho —
> dentes provados (vermelho→verde) pelo `sem_parcelamento` (ausente antes) e deletando a linha da
> videochamada. Âncora anti-vácuo (`<faq>` + não-vazio) impede que um render quebrado vire
> falso-positivo silencioso ("fragmento ausente" sendo na verdade prompt vazio).
> **Decisão de produto (autorizada):** "sem parcelamento" não tinha fala ao cliente — a ADR 0013
> só trata o fechamento como **valor único** no plano contábil (parcelamento deferido p/ P1). O
> F0.5 materializou isso como FAQ (`faq.md`: *"dá pra parcelar no cartão? → no cartão é só à vista
> amor, não parcelo."*) e trancou contra regressão. Os outros 3 itens já existiam literais.
> Roda no `make test` padrão (regex puro sobre o render, não `needs_db`) — gate de PR de verdade.
> `make test`: 825 passed. mypy + ruff limpos. Conduta ao vivo (recusa real, over-refusal) segue
> em **F3.4** (★API).

> **Status F0.6 ✅ (feito, merge local):** o núcleo já existia e estava verde — `aplicar_timeout_interno` (`workers/timeouts.py`) + 3 casos `needs_db` em `api/tests/integracao/test_timeout_interno.py` (commit `d6bc953`): **Aviso de saída sem Foto de portaria por > 45 min → Perdido/sumiu + bloqueio cancelado + evento de transição**, provado no Postgres real (TEST_DATABASE_URL, ROLLBACK sempre). A query do interno **não tem agregado** (SELECT simples com `FOR UPDATE SKIP LOCKED`), então nunca teve o bug #67 (`FeatureNotSupported: FOR UPDATE is not allowed with aggregate functions`) que quebrou o gêmeo de 24h em prod — lá o `LEFT JOIN LATERAL max()` exigiu `FOR UPDATE OF a`. F0.6 fechou os dois ramos que faltavam para **paridade-com-o-gêmeo** e gate sem buracos: **(1) guard** — bloqueio já `em_atendimento` **NÃO** é cancelado pelo timeout (CONTEXT.md "Bloqueio": Perdido → cancelado *só se ainda não em_atendimento/concluido*); sem o caso, apagar o `AND b.estado NOT IN (...)` da CTE `cancel_bloqueio` passava batido nos 3 testes — **dentes provados** (vermelho→verde) removendo o guard, que faz o bloqueio `em_atendimento` virar `cancelado`. **(2) agregação** — dois alvos elegíveis numa única varredura → ambos Perdido/sumiu + bloqueios cancelados, provando que a CTE opera sobre o **conjunto** (o `len(rows)` agregado), não linha-a-linha. Test-only (`timeouts.py` intacto); `needs_db`, roda no Postgres efêmero do CI pós-F0.1. `make test`: 895 passed (2 falhas **pré-existentes e não relacionadas** — `test_transcrever_audio` por `usd_brl_cotacao` ausente no settings, e `test_disponibilidade::test_bloqueios_futuros_fora`; ambas vermelhas no `main` limpo). mypy + ruff limpos.

> **Status F0.7 ✅ (feito, merge local):** gate `needs_db` (`api/tests/integracao/test_rotear_imagem.py`) que tranca o roteamento por `tipo_atendimento` no despacho de imagem (`workers/media.py::rotear_imagem`): em `Aguardando_confirmacao`, **externo** = comprovante **Pix de deslocamento** (`validar_pix`), **nunca** Foto de portaria — que é **interno-only** (CONTEXT.md "Foto de portaria"). Provado no Postgres real: o externo segue em `Aguardando_confirmacao`, `foto_portaria_em` fica **NULL** e a IA não pausa (sem handoff). **Núcleo já estava correto** — o branch da foto-portaria sempre teve o guard `tipo_atendimento == 'interno'`; F0.7 fechou o buraco de **cobertura**: o `test_pix_aguardando` pré-existente **não** protegia esse guard, porque o branch do Pix vem **antes** e intercepta o caso `externo + pix='aguardando'`, então apagar o guard passava batido nele (verde vazio). **(1)** `test_externo_aguardando_e_pix_nunca_foto_portaria` — caso realista (`pix_status='aguardando'`): despacha `validar_pix` e o atendimento **não** sofre o handoff (estado/`foto_portaria_em`/`ia_pausada` intactos no banco). **(2)** `test_externo_aguardando_sem_pix_nao_vira_foto_portaria` — **dente do guard**: sonda com `pix_status != 'aguardando'`, onde o branch do Pix **não** intercepta e o único anteparo contra o externo virar foto de portaria é aquele guard; comportamento correto = **silêncio** (06 §3). **Dente provado (vermelho→verde):** removendo `and tipo_atendimento == 'interno'`, o externo vira `Em_execucao` + card `chegada` enfileirado → teste (2) vermelho, enquanto o (1) segue verde (o branch do Pix o intercepta) — exatamente o gap que o teste novo cobre. **Test-only** (`media.py` intacto); `needs_db`, roda no Postgres efêmero do CI pós-F0.1. `make test`: 820 passed (needs_db pulado sem `TEST_DATABASE_URL`); subset `rotear_imagem` needs_db: 7 passed contra o DB real (ROLLBACK sempre). mypy + ruff limpos.

> **Status F0.10 ✅ (feito, merge local):** os 4 ramos do "nunca trava por Pix" (CONTEXT.md "Pix de
> deslocamento": o comprovante **sempre** faz o atendimento avançar — `validado` valida em silêncio,
> divergência/suspeita vira `em_revisao` **informativo**, nada trava) já tinham cobertura viva em
> `api/tests/integracao/test_validar_pix.py` (`needs_db`, contra o Postgres real): **validado**,
> **a menor (underpay)**, **chave divergente** e **plausibilidade falsa** — todos provando `estado →
> Confirmado`. O gap que o relatório apontava era de **confiabilidade do gate**, não de
> comportamento: *"único gate é needs-DB — pulado sem TEST_DATABASE_URL"*. Um `needs_db` é
> **silenciosamente pulado** sem a env var; e nada impedia deletar/renomear um ramo, tirar-lhe o
> marcador `needs_db` (rebaixando-o a no-op pulável) ou enfraquecer a asserção de avanço sem deixar a
> suíte vermelha (um teste a menos não falha nada). F0.1 fez os 4 ramos **rodarem** no Postgres
> efêmero a cada PR; faltava a rede que garante que eles **continuam existindo e provando o
> invariante**. F0.10 é essa rede: gate **determinístico e sem banco**
> (`api/tests/test_f0_10_pix_nunca_trava_gate.py`) que extrai por **AST** o `test_validar_pix.py` e
> reprova o PR se qualquer um dos 4 ramos **(1)** sumir/for renomeado, **(2)** perder o
> `@pytest.mark.needs_db` (deixaria de rodar no Postgres efêmero — viraria gate pulável) ou **(3)**
> parar de asseverar `estado == 'Confirmado'` com o `pix_status` do ramo (`validado` vs `em_revisao`).
> AST (não grep no fonte) de propósito: docstrings/comentários do arquivo citam
> `Confirmado`/`em_revisao` em prosa legítima; só literais **dentro de `assert`** e dos decorators
> provam comportamento testado. Âncoras anti-vácuo: o arquivo de cobertura existe e tem ≥ 4 testes
> `needs_db` (a parse não veio vazia). Roda no `make test` padrão — **não** é `needs_db`, então nunca
> fica pulado: gate de PR de verdade (espelha F0.1 = wiring da CI, F0.2 = montador nunca carrega
> painel-only). **Dentes provados (vermelho→verde):** remover `needs_db` de um ramo, trocar
> `Confirmado` por `Aguardando_confirmacao` (trava) e renomear um ramo deixam o gate vermelho; com o
> código íntegro, verde. `make test`: 823 passed (3 novos), 75 skipped (`needs_db` sem DB local —
> rodam no Postgres efêmero do CI pós-F0.1). mypy + ruff limpos. **Test-only** (`workers/pix.py`
> intacto). Conduta/decisão ao vivo do agente sobre Pix segue em **F3.5** (Tools-decisão, ★API).
> **Status F0.8 ✅ (feito, merge local):** gate `needs_db` novo
> (`api/tests/integracao/test_f0_8_fechado_card.py`) que tranca o gatilho atômico da venda fechada
> pela modelo respondendo o **Card** na Coordenação — `fechado [valor]` (origem `grupo_coordenacao`,
> autor `modelo`, mesma porta que o webhook chama ao resolver um card) leva o atendimento de
> **Em_execucao → Fechado**, grava o **Valor final** e **conclui o bloqueio vinculado**
> (`em_atendimento → concluido` pelo trigger de banco `sync_bloqueio_estado`, que para Fechado não
> tem o guard de `em_atendimento` que o Perdido tem), despausando a IA. Os **3 efeitos do critério
> num único gatilho**, provados no Postgres real (TEST_DATABASE_URL, ROLLBACK sempre): um `FakeConn`
> não dispara trigger nem prova a transição terminal. 2º caso tranca **"`fechado` sem valor não
> encerra"** (CONTEXT.md "Registro de resultado": fechamento exige Valor final) — erro + nada muda
> (segue Em_execucao, bloqueio segue em_atendimento), provando que o "+ Valor final" é obrigatório,
> não cosmético. **Test-only:** o núcleo (`aplicar_comando`/`_registrar_fechado` em
> `dominio/escaladas/service.py` + o trigger) já existia e estava verde; F0.8 fecha a cobertura do
> arco que ninguém exercitava (os testes de `corrigir_registro` cobrem Fechado→Perdido; o de
> `devolver_para_ia` só a despausa — nenhum o `registrar_fechado` direto de Em_execucao com o
> bloqueio `em_atendimento`). **Dentes provados (vermelho→verde):** regredindo o UPDATE do serviço
> para `SET estado = estado` (gatilho não transiciona), o teste fica vermelho em `estado` (segue
> `Em_execucao`) — e o bloqueio nunca seria concluído, pois o trigger só dispara na transição para
> Fechado; revertido, volta a verde. `make test`: 820 passed (suíte padrão; os `needs_db` rodam no
> Postgres efêmero do CI pós-F0.1). Suíte `needs_db` ao vivo: os 2 F0.8 verdes; as 2 falhas restantes
> (`test_transcrever_audio` por `usd_brl_cotacao` ausente no settings e
> `test_disponibilidade::test_bloqueios_futuros_fora`) são **pré-existentes e não relacionadas**
> (vermelhas no `main` limpo, idem F0.6). mypy + ruff limpos. A costura webhook→estado completa
> (`fechado 1500 #5` entrando pelo grupo) segue em **F1.1**.

> **Status F0.9 ✅ (feito, merge local):** gate `needs_db` novo
> (`api/tests/integracao/test_lembrete_valor_reenvio_handoff.py`) — gêmeo do
> `test_lembrete_valor_skip_locked.py`, que cobria **só a seleção de alvos** (toques=0 → primeiro
> card; tolerância). O miolo do item faltava provado: os testes unitários (`test_lembrete_valor.py`,
> `FakeConn`) **fabricam** o campo `acao`/`toques` do alvo, então provam só o *despacho*
> (acao=enviar → card; acao=escalar → handoff), nunca a **decisão** — que vive no SQL real
> (`count(*)`/`max(created_at)` de `envios_evolution` + `make_interval`), invisível a um `FakeConn`.
> F0.9 exercita pela porta `cobrar_valor_final` ponta a ponta, contra o Postgres real
> (TEST_DATABASE_URL, ROLLBACK sempre): **(1) reenvio** — card anterior além do intervalo e
> `toques < max` dispara um novo card; **(2) gate do intervalo** — card recente (dentro do
> intervalo) NÃO reenvia (o SQL devolve `acao` NULL e a varredura não manda card); **(3) handoff
> após silêncio** — atingido `lembrete_valor_max_toques`, escala: abre **uma** escalada
> (`valor_final_nao_confirmado`/Fernando, `fechada_em` NULL) + `ia_pausada=true`, **sem** enviar
> card, mantendo `Em_execucao` (nunca Perdido por silêncio — CONTEXT.md "Lembrete de fechamento");
> **(4) idempotência** — com escalada aberta, a 2ª varredura não abre um 2º handoff (guard
> `NOT EXISTS` em `_buscar_alvos`, reforçado pelo guard REL-02 do próprio `abrir_handoff`).
> **Test-only:** o worker (`workers/lembrete_valor.py`) já implementava reenvio+handoff; F0.9 fecha
> a cobertura da decisão e da abertura real do handoff (sem o `abrir_handoff` monkeypatchado dos
> unitários). **Dentes provados (vermelho→verde):** desligar o ramo `'enviar'` do CASE (toques<max)
> deixa o teste de reenvio vermelho (0 cards); desligar o ramo `'escalar'` deixa os 2 testes de
> handoff vermelhos (0 escaladas) — revertidos, voltam a verde. `make test` com `TEST_DATABASE_URL`:
> 897 passed + as 2 falhas **pré-existentes e não relacionadas** (`test_transcrever_audio` por
> `usd_brl_cotacao` ausente no settings e `test_disponibilidade::test_bloqueios_futuros_fora`,
> vermelhas no `main` limpo, idem F0.6/F0.8). mypy + ruff limpos.

---

## Fase 1 — Costura e UX determinística (sem API)

> Moeda barata. Fecha o eixo 5 (UX) e a costura webhook→estado.

| ID | Item | Fecha | Critério de sucesso | Onde |
|---|---|---|---|---|
| **F1.1** ✅ | E2E webhook→estado do comando de grupo: `fechado 1500 #5` entrando pelo grupo registra resultado, despausa IA e sincroniza bloqueio | UX | teste de integração da costura completa (hoje para na classificação) | `webhook/`, `dominio/atendimentos/service.py` |
| **F1.2** ✅ | Travar invariantes de **cadência/ritmo**: ordem read→digitando→bolha, atraso proporcional à fala, presence por bolha, jitter | UX | teste falha se a ordem/proporção quebra (hoje todo delay é neutralizado) | `workers/envio.py` |
| **F1.3** ✅ | debounce multi-device + `fromMe` com **payload real** (mesmo messageId, JIDs diferentes; manual da modelo sem `key.participant`) | UX | duplicata real coalescida; manual da modelo atribuída a ela, não à IA | `webhook/debounce.py`, parser |
| **F1.4** ✅ | Limite de bolha verificado com **textos reais da persona**, não só caso sintético | UX | falas reais caem no envelope esperado | grader de bolhas |

> **Status F1.1 ✅ (feito, merge local):** gate `needs_db` novo
> (`api/tests/integracao/test_f1_1_webhook_comando_grupo_e2e.py`) que tranca a **costura
> inteira** do comando de grupo ponta a ponta — payload Evolution cru → `evolution_webhook` →
> reconhecimento de grupo por `coordenacao_chat_id` (DB) → dedupe → `parse_comando_grupo` →
> resolução de modelo por `evolution_instance_id` (DB) → resolução de atendimento por `#N` (DB)
> → `aplicar_comando` → trigger `sync_bloqueio_estado` → **estado no banco**. A nota do item
> "(hoje para na classificação)" era buraco de **cobertura**, não de código: o handler já chamava
> `aplicar_comando` (wiring antigo, commit `928d301`), mas os testes de webhook
> (`test_webhook_integration.py`) usam `FakeConn` e param na classificação/roteamento (ex.:
> `test_webhook_grupo_reconhecido_por_coordenacao_chat_id` termina em `invalid` porque o `#N` não
> existe no fake), e F0.8 prova só o **núcleo de serviço** (`aplicar_comando`) isolado — nenhum
> exercitava a costura inteira pelo handler real. F1.1 chama o `evolution_webhook` real com uma
> request mínima (sem lifespan, p/ **não** criar pool de prod nem ARQ), apontando o pool ao mesmo
> conn de rollback. **`needs_db` de propósito:** a transição terminal vive no UPDATE do
> atendimento e o bloqueio é sincronizado por **trigger** — um `FakeConn` não dispara trigger nem
> prova a costura (espelha F0.8). **3 casos:** **(1) fechado** — `fechado 1500 #N` → Fechado +
> Valor final + bloqueio **concluído** + IA **despausada** + eventos (`fechado_registrado`,
> `transicao_estado`); **(2) perdido** — `perdido sumiu #N` em **Confirmado** com o **bloqueio
> prévio** ainda `bloqueado` → Perdido + Motivo de perda + bloqueio **cancelado** + IA despausada
> (o cenário realista em que o Perdido sincroniza o bloqueio; o guard F0.6 — Perdido só cancela
> bloqueio que ainda não está `em_atendimento`/`concluido` — é respeitado, daí o seed em
> Confirmado/`bloqueado`, não Em_execucao/`em_atendimento`); **(3) sem valor** — `fechado #N` →
> ack `invalid` (200, p/ a Evolution não reentregar em loop) e **nada muda** no banco (segue
> Em_execucao, bloqueio `em_atendimento`): `aplicar_comando('comando_invalido')` só registra o
> evento, não transiciona. **Dente provado (vermelho→verde):** regredindo `_processar_grupo` p/
> retornar antes do `aplicar_comando` ("para na classificação"), os 3 ficam vermelhos — os de
> fechado/perdido porque o estado segue `Em_execucao`/`Confirmado`, e o sem-valor porque o ack
> vira `processed`; revertido, verde. **Test-only** (`routes.py` intacto). `make test` (suíte
> padrão): 820 passed; com `TEST_DATABASE_URL`: 896 passed + as 2 falhas **pré-existentes e não
> relacionadas** (`test_transcrever_audio` por `usd_brl_cotacao` ausente no settings e
> `test_disponibilidade::test_bloqueios_futuros_fora`, vermelhas no `main` limpo, idem
> F0.6/F0.8/F0.9). mypy + ruff limpos. **Com F1.1–F1.4 fechados, o eixo 5 (UX) → Coberto.**

> **Status F1.3 ✅ (feito, merge local):** gate determinístico **sem banco**
> (`api/tests/test_f1_3_debounce_fromme_payload_real.py`) que exercita o handler inteiro
> (`/webhook/evolution`) com payloads no **formato real da Evolution v2.3.6** — o caso que o
> `webhook/CLAUDE.md` adverte que o unit mockado **não cobre**. Tranca as duas invariantes de UX
> da borda contra regressão. **(1) Duplicata real coalescida (multi-device):** WhatsApp Web +
> celular emitem o **mesmo `key.id`** e o mesmo contato aparece com JID de telefone
> (`@s.whatsapp.net`) numa entrega e **LID** (`@lid`) na outra; o dedupe é por
> `evolution_message_id` (independe do JID), então a 2ª entrega vira `duplicate` — sem 2º INSERT
> em `mensagens` e sem 2º turno enfileirado. O `_DedupeConn` faz dedupe **real** (lembra o que já
> inseriu e responde `_mensagem_ja_persistida` a partir disso), provando a **coalescência**
> ponta-a-ponta — não a tautologia "se existe então duplicate" do teste de idempotência
> pré-existente. **(2) `fromMe` distinguido pelo originador real (modelo vs IA):** a IA escreve
> via `core/evolution.py`, que grava em `envios_evolution`; a modelo digitando manualmente no
> mesmo número **não**. Manual da modelo (`fromMe=true`, **sem** `key.participant` — o quirk de
> prod, ver `webhook_authz_from_me_bloqueio` —, ausente de `envios_evolution`) → autor `"modelo"`,
> processada como comando dela; **echo da IA** (id em `envios_evolution`) → `outbound_ignored`
> **antes** de qualquer atribuição. A distinção **não confia só na flag `fromMe`** (mandato do
> `webhook/CLAUDE.md` "fromMe é ambíguo"). **Test-only** (`routes.py`/`parser.py` intactos): o
> núcleo já existia e estava correto; F1.3 fecha a cobertura com payload real. **Dentes provados
> (vermelho→verde):** desligar o gate `_mensagem_ja_persistida` deixa a 2ª entrega virar
> `received` (grava + enfileira 2x); exigir `participant` em `_autor_grupo` faz a manual da modelo
> cair em `ignored`; desligar o gate `envio_existe` faz o echo da IA virar comando `processed`.
> Determinístico (sem banco, regex/Fake puro) — gate de PR de verdade. `make test`: 824 passed.
> mypy + ruff limpos. A costura webhook→estado completa (`fechado 1500 #5` entrando pelo grupo)
> segue em **F1.1**; cadência/ritmo e limite de bolha em **F1.2/F1.4**.

**Saída da Fase 1:** UX → **Coberto**.

> **Status F1.2 ✅ (feito, merge local):** gate determinístico **sem banco**
> (`api/tests/integracao/test_f1_2_cadencia.py`) que trava os 4 invariantes de cadência da
> humanização (05 §4). O pointer do roadmap (`agente/humanizacao.py`) estava **obsoleto** — esse
> arquivo não existe; a cadência vive em `workers/envio.py::enviar_turno` + os helpers
> `calcular_reading_delay_ms`/`calcular_typing_ms`/`calcular_pausa_ms`. O gate existente
> (`test_enviar_turno.py`) **neutralizava** `asyncio.sleep` (autouse `_sem_sleep`) para provar
> ordem/cancel/dedupe — então a cadência ficava **sem rede** ("hoje todo delay é neutralizado").
> F1.2 fecha isso: em vez de neutralizar, **grava** cada `asyncio.sleep` numa timeline unificada com
> as chamadas do Evolution (sem dormir → roda instantâneo) e asserta sobre as durações *pedidas* e a
> ordem real. **(1) ordem read→digitando→bolha** — a subsequência de ações é exatamente `read`,
> depois `(presence, texto)` por bolha; **(2) atraso proporcional à fala** — o reading delay (antes
> do 1º composing) cresce com `chars_inbound` e bate `calcular_reading_delay_ms(chars)/1000` (piso
> 500ms / teto 3000ms); é o único delay proporcional por design — o typing é **plano de propósito**
> (05 §4.1), então F1.2 **não** mexeu nele (mudança cirúrgica); **(3) presence por bolha** — um
> `composing` por chunk, sempre antes do envio; **(4) jitter** — typing 0.8-2.0s e pausa 0.4-1.2s
> presentes e dentro da faixa. **Dentes provados (vermelho→verde):** achatar o reading delay para
> constante, dropar o sleep de jitter (passo 7) e remover o `set_presence` (passo 3) deixam o gate
> vermelho — revertidos, verde. **Test-only** (`envio.py` intacto). Roda no `make test` padrão (não
> `needs_db`): gate de PR de verdade.

> **Status F1.4 ✅ (feito, merge local):** gate determinístico **sem banco**
> (`api/tests/unit/test_f1_4_limite_bolha_persona.py`) que verifica o limite de bolha (`chunk_texto`,
> `workers/_chunking.py`) com **falas reais da persona**, não só o caso sintético do
> `test_chunk_texto.py` (`"b0"`, `"palavra " * 100`). As falas (`FALAS_REAIS`, ~35) são **verbatim do
> corpus** `docs/agente/conversas-reais/` (4 cenários) e `test_falas_sao_reais_do_corpus` prova por
> **containment** (whitespace-normalizado) que cada uma aparece no `.md` de origem — anti-fabricação,
> não são sintéticas. **(1)** toda bolha real vira exatamente **1 chunk ≤ MAX_CHARS** (600) sem
> disparar `CHUNK_OVERSIZE` (a persona real não manda paredão >600); **(2)** turnos reais
> multi-pensamento (separados por linha em branco, como a IA é instruída) caem no envelope —
> `≤ MAX_CHUNKS` (6), cada bolha ≤ cap, todo pensamento preservado; **(3)** turno real com >6
> pensamentos **funde** no cap (excedente no último chunk), provando que o cap engata em conteúdo
> real. **Dentes provados (vermelho→verde):** `MAX_CHARS=40` (bolhas reais estouram o cap) e
> `MAX_CHUNKS=100` (cap não engata nas 8 bolhas reais) deixam o gate vermelho. **Test-only**
> (`_chunking.py` intacto). Roda no `make test` padrão: gate de PR de verdade.

---

## Fase 2 — Golden como referência held-out (humano, não-bloqueante)

> **Mudança de escopo (2026-06-08): o LLM-judge dos evals foi rejeitado (ADR 0015 → `rejected`).**
> Não há mais "calibração de juiz". A golden deixou de habilitar gate e virou **referência
> held-out** + mina de graders determinísticos. A rotulagem é trabalho humano, roda em paralelo
> e **não bloqueia nada** — F3/F4 não esperam por ela.

| ID | Item | Fecha (habilita) | Critério de sucesso | Onde |
|---|---|---|---|---|
| **F2.1** | `golden.jsonl` real held-out: Fernando + sócia rotulam; 3º rotulador procex fora do par golden (via `/calibracao`) | referência p/ diff manual + novos graders | golden ≥ N falas reais rotuladas, não 3 linhas placeholder | `evals/golden.jsonl`, `/calibracao` |
| **F2.2** ✅ | Corpus curado de conversas reais substitui os "templates ilustrativos" do README | F3.* | diretórios de fixtures apontam p/ conversas reais anonimizadas | `docs/agente/conversas-reais/` |
| ~~**F2.3**~~ | ~~Calibrar juiz contra golden → `JUDGE_VINCULANTE=True`~~ — **CANCELADO** (ADR 0015 rejeitado; sem judge nos evals) | — | — | — |

**Saída da Fase 2:** golden held-out disponível como **referência humana** — cada label vira
diff manual de `persona.md`/`faq.md` ou, se mecanizável, um **grader determinístico** novo.
Voz/persona/conduta subjetivas ficam sob revisão humana, não rubrica automática.

> **Status F2.2 ✅ (feito, merge local):** gate determinístico **sem banco**
> (`api/tests/agente/test_f2_2_fixtures_corpus_real.py`) que tranca o critério "diretórios de
> fixtures apontam p/ conversas reais anonimizadas". O ponteiro **já existia** na convenção do
> repo — cada fixture crítica de gate (`canonicos/scripted_5/`) destila um cenário real e cita a
> conversa de origem pelo marcador `#NNN` no `descricao` (ex.: `#001` →
> `docs/agente/conversas-reais/001-interno-confirmado-anal-recusa-desconto.md`); o que faltava era
> (a) a rede que garante que esses ponteiros **resolvem** e (b) corrigir a alegação obsoleta do
> README. F2.2 fecha os dois. O gate prova: **(1)** o corpus é real e não-trivial — `≥4` conversas
> `NNN-*.md` não-vazias (âncora anti-vácuo: sem ela, "todo ponteiro resolve" seria verde-vazio);
> **(2)** **todo** `#NNN` citado por qualquer fixture sob `api/evals/` resolve a um `NNN-*.md` real
> (zero ponteiro pendente/dangling) **e** `≥3` conversas distintas lastreiam o gate `scripted_5`
> (lastro significativo, não uma referência solta); **(3)** o README de evals **não** regride à
> alegação `Esta sessão criou apenas templates ilustrativos` e **aponta** p/ o corpus
> (`docs/agente/conversas-reais/`). A alegação do README estava **obsoleta**: dizia que a sessão
> "criou apenas templates ilustrativos" e que "o dataset real precisa ser curado", quando o corpus
> já fora curado (`~60` fixtures, 4 conversas reais anonimizadas com PII redigida). F2.2 reescreveu a
> seção "Datasets seed" do `api/evals/README.md` p/ refletir a realidade e documentar a convenção
> `#NNN` → arquivo do corpus, com o gate trancando contra regressão. **Dentes provados
> (vermelho→verde):** o README obsoleto deixa o teste (3) vermelho — a reescrita o torna verde; uma
> fixture citando um `#009` inexistente é detectada como dangling pelo teste (2) (provado por
> injeção). **Test-only + doc** (nenhuma fixture tocada — validou-se o ponteiro `#NNN` já existente,
> não se adicionou campo novo). Roda no `make test` padrão (parse/regex puro, não `needs_db`) — gate
> de PR de verdade, espelha F0.2/F0.10/F1.4. `make test`: 824 passed. mypy + ruff limpos. O golden
> held-out rotulado segue em **F2.1** (humano), agora como **referência** — F2.3 (calibração de
> juiz) foi **cancelada** (ADR 0015 rejeitado; sem judge nos evals).

---

## Fase 3 — Gate de evals ao vivo (★API — bloqueado até restaurar crédito)

> Moeda escassa. Esta é a peça que destrava FAQ-conduta, Tools-decisão e parte de 4b.
> **Pré-requisito:** crédito Anthropic restaurado (não espera mais F2 — judge removido, ADR 0015).

| ID | Item | Fecha | Critério de sucesso | Onde |
|---|---|---|---|---|
| **F3.1** ✅ (repo) | Habilitar secrets do `evals.yml` + branch protection "evals" **obrigatória** | todos ★ | job não pula em silêncio; evals barram merge | `.github/workflows/evals.yml` |
| **F3.2** | Runner K=5 sobre as 75 fixtures (grafo real + Sonnet) roda **como gate** | 4b, FAQ, Tools | ao menos 1 corrida verde registrada como cutover; regressão reprova | `evals/runner.py` |
| **F3.3** ✅ (gate determinístico) | Persona: checagens determinísticas de **voz sobre falas geradas** (anti tom corporativo, asterisco-ação, gíria masculina, formato R$, max_chars de abertura) | Persona | gate observa fala real gerada, não só montagem | graders de persona |
| **F3.4** ✅ (gate determinístico) | FAQ conduta como gate: 8 perguntas canônicas (conteúdo obrigatório **determinístico**; conduta subjetiva = revisão humana contra golden), recusa videocall, cartão sem parcelar + taxa 10%, cota fetiche do cardápio, recusa-aberta fora-da-lista, **controle de over-refusal** | FAQ | regressão "só pix amor" / "oferece parcelado" / over-refusal reprova (no determinístico) | fixtures FAQ + runner |
| **F3.5** ✅ (gate determinístico) | Tools decisão: ~30 cenários tools obrigatórias/proibidas como gate; extração em **modo estrito** (não fabrica args fora do schema) | Tools | "chamou a errada / não chamou a obrigatória / inventou write" reprova | fixtures tools, schema extração |
| **F3.6** | Invariantes adversariais held-out registrado contra a IA real: piso de desconto + oferta única sob gaslighting, jailbreak, injeção, AUP, prova de humanidade | Inv. (piso) | corrida held-out verde dos ~50 adversariais; piso vira gate | fixtures gaslighting/desconto |
| **F3.7** ✅ (gate determinístico) | `max_custo_brl` por fixture vira gate **vinculante** | Guardrails | fixture acima do teto de custo reprova | runner, `max_custo_brl` |

**Saída da Fase 3:** Persona → **Coberto**; FAQ → **Coberto**; Tools → **Coberto**;
Inv. piso → **Coberto**.

> **Status F3.1 ✅ metade de repo (feito, merge local):** o `evals.yml` se **auto-pulava
> em silêncio** sem os secrets (`Guard de secrets` → `rodar=false` → todo passo com
> `if: steps.guard.outputs.rodar == 'true'`): o job terminava **verde sem rodar nada** —
> teatro de segurança, um PR que toca `agente/**` passava sem uma fixture rodar. F3.1
> trocou por guard **fail-loud** (`exit 1` quando falta `TEST_DATABASE_URL` ou
> `ANTHROPIC_API_KEY`, **antes** do setup p/ não gastar minutos) e tornou o runner
> **incondicional** — um check `evals` verde só pode significar que o runner rodou (K=5,
> `--threshold 1.0`). Rede determinística **sem banco/API**
> (`api/tests/test_f3_1_evals_gate_nao_pula.py`, 6 casos) tranca contra a regressão p/ o
> skip silencioso: runner incondicional (sem `if:`), guard fail-loud **antes** do runner,
> K=5, secrets wirados no env, e proíbe a ressurreição do output `rodar=false`. Espelha o
> gate de wiring de CI da F0.1. **Hardening de robustez (esta sessão):** o helper
> `_raiz_repo()` do teste achava a raiz pelo **primeiro** ancestral com
> `.github/workflows/evals.yml` — uma cópia-sombra stale numa pasta intermediária
> (`api/.github/workflows/evals.yml`, deixada por engano com o cwd em `api/`, conteúdo
> pré-F3.1) **sequestrava** o gate p/ validar um workflow que nem é o do repo, deixando-o
> vermelho localmente embora o `evals.yml` canônico já estivesse correto. Fix cirúrgico:
> ancorar no `.git` (raiz real do repo/worktree) — `api/` não tem `.git`, então a sombra é
> ignorada. **Dentes provados (vermelho→verde) em worktree:** sombra stale reproduzida →
> 4 de 6 falham (idêntico à árvore principal); após o anchor, 6/6 verdes **com a sombra
> ainda presente** (prova de robustez) e sem ela. `make test`: 840 passed (suíte padrão);
> mypy + ruff limpos. **Metade de operador PENDENTE (não é código):** provisionar os
> secrets `TEST_DATABASE_URL` (banco de teste, **nunca** prod) + `ANTHROPIC_API_KEY` e
> marcar o check `evals` como **obrigatório** na branch protection da `main` —
> **bloqueada** por billing do GitHub (`github_actions_billing_locked`) + crédito Anthropic
> esgotado (`anthropic_creditos_esgotados_prod`). Passo a passo em
> `infra/runbooks/evals-gate-vinculante.md`. F3.1 só conta como **Coberto pleno** quando
> essa metade for habilitada.

> **Status F3.3 ✅ gate determinístico (feito, merge local):** os graders do runner observavam o
> texto da fala só por **conteúdo opt-in** — `texto_resposta.nao_deve_conter`/`deve_conter_um_de`
> dependiam de um autor de fixture **lembrar** de colar a lista de marcadores. A voz da persona
> (`persona.md` `<armadilhas_de_voz>`) só era checada onde alguém pingou os termos à mão (as 3
> fixtures `canonicos.persona.001/002/003`) — e mesmo lá o lastro subjetivo era rubrica `judge:llm`,
> **inerte** desde o ADR 0015. F3.3 torna a voz um gate **estrutural e sempre-ligado sobre a FALA
> GERADA** (`captura.texto_final`, a bolha que iria ao cliente — não a montagem do prompt, que a
> F0.5 já cobre no render da FAQ): `validar_voz_persona` (PURO, sem DB/LLM) reprova as 4 quebras
> **inequívocas** de `<armadilhas_de_voz>` — **(1) tom corporativo** (advérbios formais
> `genuinamente/absolutamente/certamente/honestamente/diretamente` + saudação de atendente
> `como posso te ajudar`), **(2) asterisco-ação** narrada (`*sorri*`/`*risos*`; a persona usa
> "ahaha"), **(3) gíria masculina** e **(4) formato de valor** (canônico `R$1.500` colado; reprova
> `R$ ` com espaço, `$1500` nu/escapado e vírgula no valor). Plugado em `avaliar()` **sempre-ligado**
> (não opt-in, espelha o modo estrito da F3.5: uma quebra de persona é sempre erro, nunca escolha de
> fixture; em run real só dispara se o modelo quebrou a voz). **Conservador de propósito na gíria:**
> o `<errado>` lista `mano/cara/beleza/tipo/sussa`, mas `tipo`/`cara`/`beleza` têm uso **legítimo** em
> PT (evidência grep: `que tipo de atendimento`, `palavras tipo "vc é IA?"` em `regras.md`/corpus) —
> o gate sempre-ligado só flaga o **inequívoco** (`mano`/`sussa`), igual ao output_guard da F0.4
> ("só frases que SÓ podem significar"); as ambíguas seguem disponíveis por `nao_deve_conter` nas
> fixtures onde o contexto as desambigua (ex.: `persona.003`). O **5º item do roadmap, "max_chars de
> abertura", já tinha rede** no grader pré-existente `texto_resposta.max_chars` (mede
> `len(captura.texto_final)` = a fala; `persona.001` cota a abertura em 60) — duplicar viraria config
> redundante (CLAUDE.md §2), então F3.3 **não** adiciona campo novo. **Dentes provados
> (vermelho→verde):** TDD — as 6 checagens de reprova + o unit do `validar_voz_persona` puro falham
> antes do grader existir; neutralizar o `falhas += validar_voz_persona(...)` em `avaliar()` deixa as
> 5 reprovas de nível-`avaliar` vermelhas (o vínculo ao gate, não só a função pura). Âncora
> anti-vácuo: uma fala real da persona (`oii / pode sim amor / fica R$1.500 a hora`) passa por TODOS
> os graders. Roda no `make test` padrão (regex puro, não `needs_db`) — gate de PR de verdade,
> espelha F0.5/F3.5. `make test`: 861 passed; mypy (`mypy src`) + ruff limpos. **★API segue
> pendente:** ver a voz real gerada estourar os marcadores numa corrida ao vivo (grafo real + Sonnet)
> é a outra metade — bloqueada por crédito (`anthropic_creditos_esgotados_prod`); o gate
> determinístico de voz já está trancado. Persona → **Coberto** quando a corrida ao vivo + a revisão
> humana contra a golden (sem judge, ADR 0015) fecharem.

> **Status F3.5 ✅ gate determinístico (feito, merge local):** o runner extraía tools só por
> **nome** (`_tools_chamadas` lê `.tool_calls` e devolve um `set[str]`) — cego aos **args** e
> descartando `invalid_tool_calls` em silêncio. Um write alucinado (tool fora do catálogo, ex.
> `registrar_pagamento`) ou uma tool real com **arg fabricado fora do schema** entrava como
> `invalid_tool_call` e **passava batido**: os graders `tool_calls_obrigatorias/proibidas` nunca
> o viam → falso-PASS. F3.5 fecha isso com a **extração em modo estrito** (`validar_extracao_estrita`,
> PURO): congela o catálogo real no import (`_SCHEMAS_TOOLS = {t.name: set(t.args.keys()) for t in
> ferramentas.TOOLS}` — as 5 tools P0, `BaseTool.args` = nomes de arg aceitos) e reprova três
> formas de extração fabricada — **(1)** nome fora do catálogo (write inventado), **(2)** arg de
> topo fora do schema da tool, **(3)** `invalid_tool_call` (a Anthropic/langchain não casou os args
> contra o schema = "args fora do schema"). `_capturar` agora popula `Captura.tool_calls_detalhe`
> (nome+args+validade, lendo `.tool_calls` E `.invalid_tool_calls`) e `avaliar` chama o grader
> **sempre-ligado** (não opt-in — uma tool fabricada é sempre erro, nunca escolha de fixture; em
> run real só dispara se o modelo alucinou). "chamou a errada / não chamou a obrigatória" seguem
> nos graders `proibidas/obrigatorias` pré-existentes; F3.5 adiciona o "inventou write/arg".
> **Dentes provados (vermelho→verde):** sem o grader, capturas com arg fora do schema / write
> inventado / tool_call inválida passavam (`avaliar` retornava `passou=True`); com o modo estrito,
> reprovam — 7 casos novos em `tests/evals/test_runner_gate.py` (incl. unit do `validar_extracao_estrita`
> puro, da extração de `_tool_calls_detalhe` e da âncora anti-vácuo do `_SCHEMAS_TOOLS` = catálogo
> real). Roda no `make test` padrão (PURO, sem DB/LLM) — gate de PR de verdade. `make test`: 851
> passed; mypy (`mypy src`) + ruff limpos. **★API segue pendente:** a corrida ao vivo das ~30
> fixtures de decisão (grafo real + Sonnet) é a outra metade de F3.5 — bloqueada por crédito
> Anthropic (`anthropic_creditos_esgotados_prod`); o gate determinístico de schema já está trancado.

> **Status F3.7 ✅ gate determinístico (feito, merge local):** o runner **já** calculava o custo
> por turno (`_capturar` → `_agregar_usage` + `calcular_custo_brl`) e `avaliar` já reprovava
> `custo_brl > metricas.max_custo_brl` — mas o estouro **não era vinculante**: `gate_split` (o gate
> de cutover, exit-code do `main`) só conta a suíte de **regressão**; numa fixture `capability`
> (adversariais, advisory por comportamento em maturação) o estouro de custo era **silenciosamente
> ignorado** (não bloqueava o merge). Custo é **guardrail** (eixo 7), não comportamento — não pode
> ser advisory. F3.7 torna o teto **vinculante**: `avaliar` marca `Avaliacao.custo_estourado`
> (distinto das demais falhas), `_colapsar_fixture` o propaga pela agregação por fixture (qualquer
> amostra que estourou carimba a fixture) e `particionar_gate` move a fixture para o balde
> **bloqueante** quando `custo_estourado`, mesmo classificada `capability`. O vínculo é **específico
> de custo**: uma capability que falha por **comportamento** (não custo) segue advisory e não
> bloqueia (guard provado em teste). **Dentes provados (vermelho→verde):** uma fixture adversariais
> (capability) acima do teto + uma regressão que passa → `gate_split` devolvia **0** (cutover
> passava, ignorando a capability); com o vínculo devolve **1** (bloqueia) — 4 casos novos em
> `tests/evals/test_runner_gate.py` (marca, vínculo em capability, sobrevivência à agregação, guard
> do comportamento-não-custo). Roda no `make test` padrão (PURO) — gate de PR de verdade. `make
> test`: 851 passed; mypy + ruff limpos. **★API segue pendente:** ver o custo real estourar numa
> corrida ao vivo é a outra metade — bloqueada por crédito (`anthropic_creditos_esgotados_prod`); a
> lógica do gate vinculante já está trancada determinística.

> **Status F3.4 ✅ gate determinístico (feito, merge local):** a conduta de FAQ só tinha rede de
> **render** (F0.5 prova que os itens críticos da `faq.md` chegam ao prompt) e de **conteúdo opt-in**
> (`texto_resposta.deve_conter`/`nao_deve_conter`, que dependem de um autor de fixture **lembrar** de
> colar o marcador). A **conduta na fala gerada** — a bolha que iria ao cliente — não tinha gate
> sempre-ligado: uma resposta que **oferece parcelamento**, **restringe o pagamento a pix** ou
> **enfileira um muro de recusas** passava batido se a fixture não pingasse o termo à mão. F3.4 torna
> as 3 regressões que o roadmap nomeia um gate **estrutural e sempre-ligado sobre `captura.texto_final`**
> (espelha o modo da F3.3/F3.5: uma quebra de FAQ é sempre erro, nunca escolha de fixture; em run real
> só dispara se o modelo regrediu): `validar_faq_conduta` (PURO, sem DB/LLM) reprova — **(1) oferece
> parcelado** (`faq.md` item 8 "no cartão é só à vista amor, não parcelo"): token `parcel*` / "em N x"
> / "N vezes" **não negado** (a recusa canônica `não parcelo` tem negação imediata → não reprova);
> **(2) "só pix amor"** (`faq.md` itens 2/7 — aceita pix, **dinheiro ou cartão**): `(só|apenas|somente)
> … pix` ou recusa de um meio aceito (`não aceito cartão/dinheiro/maquininha`), **guardado contra o
> deslocamento** (que é legitimamente só-pix, `faq.md` item 3 / `<pix_externo>`); **(3) over-refusal**
> (persona `<armadilhas_de_voz>` "lista de exclusões antes do sim" + regras `<recusa_de_pratica>`,
> recusa **uma por vez** em mensagem própria): **≥2** recusas de prática no **mesmo balão** (muro de
> nãos). **Conservador de propósito** (igual ao output_guard da F0.4 e à gíria da F3.3): só o
> **inequívoco** reprova — uma recusa suave isolada (`nao tenho costume amor`) e a recusa de
> videochamada (`video chamada eu nao faço, mas mando fotos`) **passam** (1 recusa < muro); a resposta
> de pagamento certa (`pix, dinheiro ou cartão`) e a recusa canônica de parcela **passam**. A conduta
> subjetiva (tom, ritmo da venda, recusa-aberta bem-conduzida) **não** vira rubrica automática — fica
> sob **revisão humana contra a golden** (ADR 0015 rejeitou o judge). **Dentes provados
> (vermelho→verde):** TDD — as 4 reprovas de nível-`avaliar` (parcela / só-pix / recusa-de-meio /
> muro) + o unit do `validar_faq_conduta` puro falham antes do grader existir; com ele, reprovam,
> enquanto os 4 GUARDs (deslocamento, parcela negada, pagamento canônico, recusa única) seguem verdes.
> Plugado em `avaliar()` **sempre-ligado** (espelha F3.3/F3.5). Roda no `make test` padrão (regex puro,
> não `needs_db`) — gate de PR de verdade. `make test`: 870 passed; mypy (`mypy src`) + ruff limpos.
> **★API segue pendente:** rodar as 8 perguntas canônicas + os arcos de conduta ao vivo (grafo real +
> Sonnet) — ver a fala real estourar os marcadores e a **conduta subjetiva** sob revisão humana contra
> a golden — é a outra metade, bloqueada por crédito (`anthropic_creditos_esgotados_prod`). O gate
> determinístico das 3 regressões nomeadas já está trancado. FAQ → **Coberto** quando a corrida ao vivo
> + a revisão humana fecharem.

---

## Fase 4 — Fechar a máquina de estados pela conversa (★API) — substitui o vendedor

> Moeda escassa. O eixo ★ de maior peso. Hoje **toda jornada morre em
> Confirmado/Em_execucao**; `Novo`, `Fechado`, `Perdido` nunca são alcançados pela
> própria conversa.

| ID | Item | Fecha | Critério de sucesso | Onde |
|---|---|---|---|---|
| **F4.1** | Jornada E2E começando em **`Novo`** (1º contato antes da triagem) | 4b (estado Novo) | jornada exercita Novo→Triagem pela conversa | `evals/`/`sim/cenarios*.py` |
| **F4.2** | Jornadas que chegam a **`Fechado`** pela conversa (modelo fecha respondendo card com Valor final) | 4b (Fechado) | E2E real percorre até Fechado; estado/tools por turno = gate determinístico, qualidade da venda = revisão humana | `sim/`, runner |
| **F4.3** | Jornada que vira **`Perdido (sumiu)`** por timeout como continuação E2E | 4b (Perdido) | ramo "não volta" é jornada graduada | `sim/`, runner |
| **F4.4** | `Em_execucao → Fechado` por **Lembrete de fechamento** dentro de uma jornada | 4b | cobrança proativa do Valor final fecha pela conversa | `sim/`, runner |
| **F4.5** | **Recorrência**: novo Atendimento na mesma Conversa cliente após um Fechado | 4b | cenário existe e passa | `sim/`, runner |
| **F4.6** | Upsell de duração (MAX de horas), recusa de fetiche fora-da-lista com retomada limpa, Pix duvidoso com card de duvidez + fila de Fernando (sem travar) | 4b | cada arco coberto por jornada graduada; redis stub deixa de mascarar o card | `sim/`, runner |
| **F4.7** | **Revisão humana de venda bem-conduzida** (rubrica comercial: ritmo, não perder o cliente, fechar) sobre as jornadas geradas, contra a golden — sem judge automático (ADR 0015 rejeitado) | 4b | rubrica humana aplicada às jornadas E2E; falhas viram fixtures/graders determinísticos | revisão humana + `evals/` graders |

**Saída da Fase 4:** 4b → **Coberto**; máquina de estados coberta ponta-a-ponta pela
conversa (Novo … Fechado/Perdido). **Substituição do vendedor demonstrada pela suíte.**

---

## Fase 5 — Guardrails financeiros de produção + baseline

> Mix: engenharia de prod (sem API) + baseline (depende de F3).

| ID | Item | Fecha | Critério de sucesso | Onde |
|---|---|---|---|---|
| **F5.1** | Teto de custo em **BRL por atendimento** aplicado em **prod**: ao bater, pausa IA + Handoff (não só métrica) | Guardrails | atendimento que estoura o teto pausa e escala | `agente/graph.py`, settings |
| **F5.2** | Verificação automática de **write-rate** do cache (>10–15% pós-warmup = alerta/trava) | Guardrails | métrica calculada e travada, não inspeção manual | métricas / cron |
| **F5.3** | Confirmar com o operador as tarifas de leitura de Pix e transcrição (hoje defaults plausíveis) | Guardrails | número-base validado; custo agregado confiável | settings de custo |
| **F5.4** | Baseline de pass-rate + tripwire de regressão nightly (>5%) | Guardrails / 4b | nightly compara contra baseline e alerta | `evals.yml` nightly |

**Saída da Fase 5:** Guardrails → **Coberto**.

---

## Caminho crítico e paralelismo

```
AGORA (sem API, desbloqueado):     F0  ─┬─►  F1
                                        └─►  (F0.1 destrava F0.6–F0.10)
EM PARALELO (humano, NÃO-bloqueia): F2.1 (rotulagem Fernando+sócia) → golden de referência
BLOQUEADO (crédito Anthropic):     F3 ─► F4 ─► F5.4   (não espera mais F2 — judge removido)
INDEPENDENTE (eng. de prod):       F5.1, F5.2, F5.3
```

- **Faça já:** F0 e F1 inteiras (fecham Invariantes, 4a, UX — 3 eixos — a custo ~zero).
- **Inicie em paralelo (opcional):** F2.1 (rotulagem é trabalho humano; vira referência, não
  bloqueia F3/F4 — o judge foi removido).
- **Aguarda billing:** F3 e F4 (todo o ★API). Não comece o runner ao vivo com crédito
  esgotado — vira ruído.
- **Pode ir a qualquer momento:** F5.1–F5.3 (engenharia de prod determinística).

## Rastreabilidade eixo → itens que o levam a Coberto

- **1 Persona:** F3.3 (graders determinísticos de voz) + revisão humana contra golden (sem judge)
- **2 FAQ:** F0.5 + F3.4
- **3 Tools:** F3.5
- **4a Trajetória atômica:** F0.6 + F0.7 + F0.8 + F0.9 + F0.10
- **4b Conversa completa:** F3.2 + F4.* (estado/tools por turno = gate; venda bem-conduzida = revisão humana) (★ eixo de maior peso)
- **5 UX:** F1.1 + F1.2 + F1.3 + F1.4
- **6 Invariantes:** F0.2 + F0.3 + F0.4 + F0.10 + F3.6
- **7 Guardrails:** F3.7 + F5.1 + F5.2 + F5.3 + F5.4

## Definição de pronto (a matriz inteira Coberto)

Todos os 8 eixos exibem **Coberto** quando: (a) cada gap tem rede **determinística** que
**reprova um PR** ao regredir; (b) as dimensões subjetivas (voz/persona/venda bem-conduzida)
têm **revisão humana contra a golden held-out** documentada — não há judge automático (ADR 0015
rejeitado); (c) ao menos uma corrida ao vivo de cada eixo ★API foi **registrada como cutover**;
(d) a máquina de estados é percorrida `Novo … Fechado/Perdido` por **jornada E2E** com
estado/tools gateados por turno.
