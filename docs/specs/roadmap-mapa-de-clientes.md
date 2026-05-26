# Roadmap — Mapa de clientes

> **Para consumo por agente (Claude Code).** Cada item abaixo é uma **tarefa autocontida**: tem
> objetivo, escopo, dependências, arquivos, mudanças e **critério de aceite verificável**. Pegue
> uma tarefa por vez, na ordem das fases, e termine cada uma com a verificação descrita (princípio
> §4/§5 do `CLAUDE.md`: execução guiada por objetivos + verificação agêntica).
>
> **Herda decisões de** `docs/adr/0008-mapa-de-clientes.md` e do termo **Mapa de clientes** em
> `CONTEXT.md`. A tela pertence ao módulo Clientes/CRM (`docs/specs/tela-04-crm.md`). Em conflito,
> o ADR 0008 vence; quando uma tarefa **estende** o escopo do ADR, isso está marcado e exige ADR
> próprio antes de implementar.

---

## Propósito (a bússola)

O mapa é **painel-only (Fernando), cross-modelo**, e existe para **ler a concentração geográfica
da demanda** e com isso **direcionar marketing e operação**. Toda tarefa deve servir a uma destas
perguntas: *onde está o dinheiro* · *onde eu perco* · *onde existe demanda que não cubro* · *onde a
oferta (modelos) cobre a demanda*. Nada que exponha agregação cross-modelo à IA por modelo (ela
**nunca** acessa este mapa).

## Estado atual (baseline)

- **Endpoint:** `GET /v1/crm/clientes/mapa` — SQL inline em `api/src/barra/dominio/clientes/routes.py`
  (`mapa_clientes`, declarado **antes** de `GET /clientes/{cliente_id}`). Retorna, por ponto:
  `cliente_id, nome, latitude, longitude, bairro, endereco_formatado, total_atendimentos,
  valor_total` + `total_sem_localizacao`. 1 ponto por cliente, no **atendimento externo mais
  recente com `lat/lng`**. Sem paginação. Filtros: `modelo_id, q, periodo, perfis, incluir_arquivados`.
- **Frontend:** `interface/src/components/clientes/MapaClientes.tsx` (mapa imperativo) +
  `interface/src/hooks/useClientesMapa.ts` (fetch) + `interface/src/tipos/clientes.ts`
  (`MapaClientePonto`, `MapaClientesResponse`) + `interface/src/lib/googleMaps.ts` (loader único).
- **Render:** `google.maps.Map` (vetorial, **Map ID** via `NEXT_PUBLIC_GOOGLE_MAPS_MAP_ID` /
  `DEMO_MAP_ID`) + `AdvancedMarkerElement` + `@googlemaps/markerclusterer` + `InfoWindow` ao clicar.

## Restrições duras (ler antes de qualquer fase de calor)

1. **`google.maps.visualization.HeatmapLayer` está MORTA.** Deprecada em maio/2025, indisponível a
   partir de maio/2026. **Não usar.** O caminho oficial do Google é **deck.gl** (`@deck.gl/google-maps`
   `GoogleMapsOverlay` + `@deck.gl/aggregation-layers`), que **anexa um overlay ao `google.maps.Map`
   já existente** (`overlay.setMap(map)`) — não roda um segundo carregador do Google, respeitando o
   ADR 0008.
2. **deck.gl exige mapa vetorial + Map ID.** Já temos (migração recente para `AdvancedMarkerElement`
   + `DEMO_MAP_ID`). Em produção, definir um Map ID próprio em `NEXT_PUBLIC_GOOGLE_MAPS_MAP_ID`.
3. **Dado esparso no P0.** Heatmap KDE com poucos pontos **engana**. Por isso a ordem das fases:
   bolhas → hexbin → KDE. Não inverter sem volume real de pontos.
4. **Privacidade.** Endereço **residencial** da modelo é PII sensível (ADR 0007) e **nunca** entra no
   mapa. Camada de modelos, se feita, usa só endereço **operacional** (onde ocorrem os internos).
5. **Mudanças cirúrgicas.** Reusar o seletor de métrica e a legenda entre camadas; não duplicar.

### Legenda de escopo

| Marca | Significado |
|---|---|
| ✅ | Usa só dado/ADR atuais — pode implementar direto |
| 🟡 | Dado existe no banco, mas precisa expor no endpoint / ADR leve |
| 🔴 | Exige dado novo, API externa **e/ou novo ADR** antes de implementar |

---

## Índice de tarefas

> **Status atualizado em 2026-05-26** (após pipeline noturno de routines do Claude Code; ver
> [[pipeline-autonomo-via-routines]] na memória do agente).

| ID | Tarefa | Fase | Escopo | Depende de | Status |
|---|---|---|---|---|---|
| MAPA-1 | Seletor de métrica + legenda (espinha dorsal) | 1 | ✅ | — | ✅ shipado (pré-pipeline) |
| MAPA-2 | Bolhas graduadas | 1 | ✅ | MAPA-1 | ✅ mergeado (PR #23, PR #12 fechado por DIRTY) |
| MAPA-3 | Cor por desfecho do atendimento mais recente | 1 | 🟡 | MAPA-1 | ✅ mergeado (PR #21) |
| MAPA-4 | Ranking lateral de bairros/cidades quentes | 1 | 🟡 | MAPA-1 | ✅ mergeado (PR #14) |
| MAPA-5 | InfoWindow enriquecido | 1 | 🟡 | MAPA-5b | ⏳ destravado por MAPA-5b — retomar PR #15 |
| MAPA-5b | Suporte a `?cliente=<id>` em `/clientes` | 1 | ✅ | — | ✅ PR aberto em `feat/clientes-deeplink-id` |
| MAPA-6 | deck.gl: infraestrutura + camada Hexbin/H3 | 2 | ✅ | MAPA-1 | ⏸️ retry cancelado — replanejar pós-deploy |
| MAPA-7 | Camada Heatmap KDE (toggle) | 3 | ✅ | MAPA-6 | — |
| MAPA-8 | Filtro por desfecho + motivo de perda | extra | 🟡 | MAPA-3 | — (desbloqueado por MAPA-3 mergeado) |
| MAPA-9 | Camada "demanda não atendida" | extra | 🟡 | MAPA-8 | — |
| MAPA-10 | Cor/filtro por perfil físico preferido | extra | 🟡 | MAPA-1 | ✅ mergeado (PR #22) |
| MAPA-11 | Faixa de R$ + recência (filtros) | extra | 🟡 | MAPA-1 | ⏸️ retry cancelado — replanejar pós-deploy |
| MAPA-12 | Mapa ↔ Lista linkados | extra | 🟡 | — | ✅ mergeado (PR #19) |
| MAPA-13 | Lasso/raio → segmento de clientes | extra | 🟡 | — | — |
| MAPA-14 | Comparar dois períodos (lift de campanha) | extra | 🟡 | MAPA-6 | — |
| MAPA-15 | Camada "Modelos" (oferta × demanda) | extensão | 🟡 | ADR 0010 | ⏸️ retry cancelado — replanejar pós-deploy |
| MAPA-16 | Choropleth por região (estado/cidade) | extensão | 🔴 | novo ADR | — |
| MAPA-17 | Isócrona / drive-time a partir das modelos | extensão | 🔴 | novo ADR | — |

### Snapshot do pipeline noturno (2026-05-26)

- **Mergeados na feature branch** (ordem cronológica): MAPA-4 (#14), MAPA-12 (#19), MAPA-3 (#21, retry), MAPA-10 (#22, retry). Plus commit cirúrgico removendo `interface/src/app/demo-mapa/page.tsx` (rota temporária da MAPA-1 que bloqueava type-check em PRs que estendiam `MapaClientePonto`).
- **`[FAIL]` documentado** que viraram lixo: MAPA-3 (#13) e MAPA-10 (#17), substituídos pelos retries #21/#22 e fechados.
- **`[FAIL]` em aberto por motivo de domínio**: MAPA-5 (#15) — `/clientes/{id}` não existe; criada sub-tarefa MAPA-5b para suportar `?cliente=<id>`.
- **Cancelados por conflito recorrente em `MapaClientes.tsx` / `MapaControles.tsx`**: MAPA-6, MAPA-11, MAPA-15. Causa raiz: routines paralelas tocam o mesmo arquivo. Próximo ciclo: rodar essas tarefas sequencialmente após o deploy atual estar validado.
- **MAPA-2 (#12)** ficou como draft fora do auto-merge (já estava pronto antes do acordo). Retomado em 2026-05-26 em branch nova `feat/mapa-2-bolhas` (PR #12 fechado), porque a base ficou CONFLICTING contra MAPA-3/4/10/12 — a composição com `modoCor` (bolhas só quando "Por métrica"), o destaque do bairro (MAPA-4 vence), e o `peso` no `markersRef` foram redesenhados sobre a versão de main.

---

## Fase 1 — Núcleo (barato, honesto com o dado de hoje, sem deck.gl)

### MAPA-1 — Seletor de métrica + legenda
- **Objetivo:** dar a Fernando um seletor para alternar o "peso" do mapa entre **R$ fechado
  (`valor_total`)**, **nº de atendimentos (`total_atendimentos`)** e **nº de clientes (contagem)**,
  com uma **legenda de escala** sempre visível. É a espinha dorsal reutilizada por todas as camadas.
- **Escopo:** ✅ frontend puro. Os três valores já vêm no endpoint (clientes = contagem de pontos,
  peso 1).
- **Depende de:** —
- **Arquivos:** `interface/src/components/clientes/MapaClientes.tsx`; novo
  `interface/src/components/clientes/MapaControles.tsx` (seletor + legenda); estado do seletor pode
  subir para o componente pai do módulo Clientes que já hospeda as abas Lista | Mapa.
- **Mudanças:**
  - Componente de seletor (3 opções) + componente de legenda com a rampa de cor e os limites
    (min/max) da métrica atual. Cor **perceptualmente uniforme** (família viridis/magma), legível no
    tema escuro do painel — **não** arco-íris vermelho.
  - Expor o valor selecionado (`metrica: "valor" | "atendimentos" | "clientes"`) para as camadas.
- **Critério de aceite:** alternar a métrica re-renderiza a legenda com os limites corretos
  (verificar via Playwright: trocar opção → texto da legenda muda). Sem métrica selecionada, default =
  R$ fechado.
- **Notas:** atenção ao caso degenerado — em **bolhas** (MAPA-2) a métrica "nº de clientes" deixaria
  todas as bolhas iguais (1 cliente = 1 ponto); nesse modo, "clientes" deve cair para tamanho fixo +
  só fazer sentido pleno nas camadas de agregação (MAPA-6/7). Documentar isso na UI (tooltip).

### MAPA-2 — Bolhas graduadas
- **Objetivo:** transformar os pins em **círculos dimensionados e coloridos pela métrica do MAPA-1**
  (raio/cor ∝ valor). É o "parece intensidade" honesto com dado esparso, sem deck.gl.
- **Escopo:** ✅ frontend puro.
- **Depende de:** MAPA-1.
- **Arquivos:** `interface/src/components/clientes/MapaClientes.tsx` (a função `desenharPontos`).
- **Mudanças:**
  - Trocar o conteúdo do `AdvancedMarkerElement` por um elemento (DOM/SVG) com raio e cor mapeados
    pela métrica, usando escala (ex.: `sqrt` para área proporcional ao valor).
  - Manter `MarkerClusterer` e o `InfoWindow` ao clicar.
  - Toggle "Pins | Bolhas" (default Bolhas), preservando o comportamento atual de pins como opção.
- **Critério de aceite:** com pontos de valores diferentes, as bolhas têm raios visivelmente
  distintos e seguem a métrica do seletor (verificar via Playwright + snapshot do mapa). Cluster e
  InfoWindow continuam funcionando.

### MAPA-3 — Cor por desfecho do atendimento mais recente
- **Objetivo:** colorir cada ponto pelo **desfecho do atendimento externo mais recente** (Fechado /
  Perdido / em andamento) → "onde eu ganho vs. onde eu vazo".
- **Escopo:** 🟡 backend (expor `estado`) + frontend (cor).
- **Depende de:** MAPA-1.
- **Arquivos:** `api/src/barra/dominio/clientes/routes.py` (`mapa_clientes`, o `LEFT JOIN LATERAL geo`);
  `interface/src/tipos/clientes.ts` (`MapaClientePonto`); `MapaClientes.tsx`.
- **Mudanças:**
  - Backend: adicionar `a.estado` ao `SELECT` do `LATERAL geo` (mesmo atendimento que já define o
    ponto) e devolver `estado` no ponto.
  - Frontend: novo modo de cor "Por desfecho" (verde/vermelho/âmbar), independente do tamanho (que
    segue a métrica). Decidir se "desfecho" é um *modo de cor* separado do *modo de métrica*.
- **Critério de aceite:** teste pytest do endpoint cobrindo um cliente cujo externo mais recente é
  `Fechado`, outro `Perdido`, outro em andamento → `estado` correto no payload. Frontend mostra as 3
  cores (Playwright).
- **Notas:** o desfecho é do **atendimento que ancora o ponto** (externo mais recente), não do
  cliente. Manter consistência com a regra do ADR 0008.

### MAPA-4 — Ranking lateral de bairros/cidades quentes
- **Objetivo:** painel lateral com **top N regiões** por R$ e por volume, ao lado do mapa — número +
  mapa juntos (muitas vezes o ranking decide mais rápido).
- **Escopo:** 🟡 (agregação por região). Pode ser feita no frontend a partir dos pontos (agrupando
  por `bairro`) ou no endpoint.
- **Depende de:** MAPA-1.
- **Arquivos:** novo `interface/src/components/clientes/MapaRanking.tsx`; opcionalmente
  `routes.py` se a agregação for server-side.
- **Mudanças:** agrupar pontos por `bairro` (fallback `endereco_formatado`/"sem bairro"), somar a
  métrica do seletor, ordenar desc, listar top N com valor formatado.
- **Critério de aceite:** o ranking reflete a métrica selecionada e reordena ao trocar a métrica
  (Playwright). Clicar num item do ranking centraliza/destaca a região no mapa (liga com MAPA-12 se
  já existir).

### MAPA-5 — InfoWindow enriquecido
- **Objetivo:** no clique do ponto, mostrar além do atual (nome, bairro, total, R$): **última data de
  atendimento**, **recorrência** e **link para a ficha do cliente**.
- **Escopo:** 🟡 (endpoint precisa de `ultima_data`/`recorrente`).
- **Depende de:** —
- **Arquivos:** `routes.py` (`mapa_clientes`), `tipos/clientes.ts`, `MapaClientes.tsx` (`conteudoInfo`).
- **Mudanças:** adicionar campos ao ponto; enriquecer o HTML do `InfoWindow` (manter escape de dado
  livre já existente). Link para a ficha do cliente no CRM.
- **Critério de aceite:** InfoWindow exibe os novos campos; link navega para a ficha correta
  (Playwright). Campos ausentes degradam para "—".

---

## Fase 2 — deck.gl + Hexbin (primeiro "calor" que não mente)

### MAPA-6 — Infraestrutura deck.gl + camada Hexbin/H3
- **Objetivo:** introduzir o **`GoogleMapsOverlay`** do deck.gl e uma camada **Hexbin** (favos
  coloridos, contáveis e clicáveis) ponderada pela métrica do MAPA-1, como **toggle** sobre o mesmo
  mapa.
- **Escopo:** ✅ (nova dependência; sem mudança de dado — os pontos já bastam).
- **Depende de:** MAPA-1 (reusa seletor + legenda).
- **Arquivos:** `interface/package.json` (`@deck.gl/core`, `@deck.gl/aggregation-layers`,
  `@deck.gl/google-maps`); `MapaClientes.tsx`; possível `interface/src/lib/deckMap.ts` para isolar a
  criação do overlay.
- **Mudanças:**
  - Importar deck.gl com `import()` dinâmico **client-only** (o componente já é `"use client"`; sem
    SSR — deck.gl renderiza em WebGL).
  - `new GoogleMapsOverlay({ layers: [hexLayer] }); overlay.setMap(map)` no mesmo `google.maps.Map`.
  - `HexagonLayer` (ou `H3HexagonLayer`) com `getPosition`, `colorAggregation: 'SUM'`,
    `getColorWeight` = métrica selecionada (R$ → `valor_total`; atendimentos → `total_atendimentos`;
    clientes → 1/COUNT). 2D (sem elevação) por padrão — mais legível num painel operacional.
  - Toggle de camada: **Bolhas | Hexbin** (e, depois, Calor). Compartilhar a mesma legenda/cor.
- **Critério de aceite:** alternar para Hexbin renderiza favos coerentes com a métrica; trocar a
  métrica recolore os favos; clicar num favo abre InfoWindow com o agregado da célula. Build do
  Next passa (`pnpm build`) e o bundle do deck.gl fica em chunk dinâmico (não no bundle inicial).
- **Notas:** `radiusPixels`/raio do hexágono e `colorRange` (viridis) bem calibrados. Conferir
  consistência com a contagem do ADR ("sem localização" continua fora dos favos).

---

## Fase 3 — Heatmap KDE (só brilha no volume)

### MAPA-7 — Camada Heatmap KDE (toggle)
- **Objetivo:** adicionar a camada de **calor KDE** clássica (`HeatmapLayer` do deck.gl), ponderada
  pela métrica, como mais um toggle. Desligada por padrão até haver pontos suficientes.
- **Escopo:** ✅ (mesma dep da Fase 2).
- **Depende de:** MAPA-6.
- **Arquivos:** `MapaClientes.tsx` / `lib/deckMap.ts`.
- **Mudanças:** `new HeatmapLayer({ getPosition, getWeight: <métrica>, radiusPixels, intensity,
  threshold, colorRange })`. Reusar legenda. Aplicar guarda de honestidade: **se nº de pontos < N
  (config), desabilitar o toggle Calor** com tooltip ("poucos pontos para um calor confiável — use
  Bolhas ou Hexbin").
- **Critério de aceite:** com dataset denso de teste, o calor aparece e responde à métrica; abaixo
  do limiar N, o toggle Calor fica desabilitado com a explicação. iOS Safari fora de escopo (painel
  desktop) — apenas registrar a limitação de textura float.

---

## Extras (fatiáveis a qualquer momento após a Fase 1)

### MAPA-8 — Filtro por desfecho + motivo de perda
- **Objetivo:** filtrar o mapa por **desfecho** (Fechado/Perdido/andamento) e por **motivo de perda**.
- **Escopo:** 🟡 (expor `motivo_perda` do externo mais recente).
- **Depende de:** MAPA-3.
- **Arquivos:** `routes.py` (LATERAL geo + novos query params), `tipos/clientes.ts`,
  `useClientesMapa.ts` (querystring), `MapaControles.tsx`.
- **Critério de aceite:** filtrar por `Perdido`+`fora_de_area` reduz os pontos corretamente
  (pytest no endpoint + Playwright).

### MAPA-9 — Camada "demanda não atendida"
- **Objetivo:** camada isolada dos **Perdidos por `indisponibilidade`/`fora_de_area`** = mapa de
  oportunidade/expansão.
- **Escopo:** 🟡.
- **Depende de:** MAPA-8.
- **Arquivos:** `routes.py`, `MapaClientes.tsx`.
- **Critério de aceite:** a camada mostra só os pontos com esses motivos; alterna independente das
  demais.

### MAPA-10 — Cor/filtro por perfil físico preferido (declarado)
- **Objetivo:** colorir/filtrar pontos pelo **perfil físico declarado** do cliente (ADR 0006) para
  cruzar com o `tipo_fisico` das modelos por região.
- **Escopo:** 🟡 (`perfis_preferidos` já existe; hoje só usado como filtro no endpoint).
- **Depende de:** MAPA-1.
- **Arquivos:** `routes.py` (devolver `perfis`), `tipos/clientes.ts`, `MapaClientes.tsx`.
- **Critério de aceite:** modo de cor por perfil + filtro OR (semântica do ADR 0006) funcionam.
- **Notas:** segue painel-only; **não** expor à IA. Só a parte **declarada** (nunca o breakdown
  calculado, que é cross-modelo).

### MAPA-11 — Filtros de faixa de R$ + recência
- **Objetivo:** slider de **faixa de valor** e toggle de **recência** (ativos nos últimos X dias ×
  dormentes) → reativação geográfica.
- **Escopo:** 🟡.
- **Depende de:** MAPA-1.
- **Arquivos:** `routes.py`, `useClientesMapa.ts`, `MapaControles.tsx`.
- **Critério de aceite:** filtros reduzem o conjunto coerentemente (pytest + Playwright).

### MAPA-12 — Mapa ↔ Lista linkados
- **Objetivo:** clicar numa região (favo/bairro) filtra a aba **Lista** por aquela área.
- **Escopo:** 🟡 (estado compartilhado entre abas).
- **Depende de:** — (combina melhor com MAPA-4/MAPA-6).
- **Arquivos:** componente pai das abas Lista|Mapa; `useClientes.ts`.
- **Critério de aceite:** selecionar uma região no mapa e ir para a Lista mostra só os clientes
  daquela área (Playwright).

### MAPA-13 — Lasso/raio → segmento de clientes
- **Objetivo:** desenhar uma área (polígono/raio) e **selecionar os clientes dentro** para uma ação
  ("criar lista/campanha para esta região").
- **Escopo:** 🟡 (frontend; seleção espacial client-side).
- **Depende de:** —
- **Arquivos:** `MapaClientes.tsx` + utilitário de point-in-polygon; UI de saída do segmento.
- **Critério de aceite:** desenhar um polígono retorna exatamente os pontos contidos (teste unitário
  da função geométrica + Playwright do fluxo).

### MAPA-14 — Comparar dois períodos (lift de campanha)
- **Objetivo:** comparar a demanda entre **dois períodos** (antes/depois de uma campanha) no mapa —
  medir efeito geográfico de marketing.
- **Escopo:** 🟡.
- **Depende de:** MAPA-6 (mais natural sobre agregação).
- **Arquivos:** `routes.py` (dois recortes), `MapaControles.tsx`, `MapaClientes.tsx`.
- **Critério de aceite:** seleção de dois períodos mostra a diferença/comparação de forma legível.

---

## Extensões (exigem ADR próprio — NÃO implementar sem ele)

### MAPA-15 — Camada "Modelos" (oferta × demanda)
- **Objetivo:** plotar as **modelos** na localização **operacional** como camada distinta (toggle),
  para cruzar oferta com a demanda dos clientes. Decidido no **ADR 0010**.
- **Escopo:** 🟡 backend (novo endpoint) + frontend (camada). Sem dado novo — `modelos.lat/lng`
  (operacional) já existe (migration 0028).
- **Depende de:** ADR 0010 (já aprovado). Independe das fases 2/3 (sem deck.gl).
- **Arquivos:** `api/src/barra/dominio/modelos/routes.py` (novo `GET /v1/modelos/mapa`);
  `interface/src/tipos/` (tipo do ponto de modelo); novo hook de fetch;
  `interface/src/components/clientes/MapaClientes.tsx` (camada + toggle).
- **Mudanças:**
  - Backend: endpoint não paginado retornando por modelo `id, nome, latitude, longitude, status,
    tipo_fisico, tipo_atendimento_aceito` + `total_sem_localizacao_operacional`. **Nunca** PII
    (rg/cpf/endereço residencial/percentual_repasse).
  - Frontend: 1 `AdvancedMarkerElement` por modelo, cor/ícone por **status** (ativa/pausada/inativa),
    toggle de camada, InfoWindow não-sensível (nome, status, tipo_fisico, tipos aceitos).
- **Critério de aceite:** pytest do endpoint (sem campos PII no payload; modelo sem geo entra no
  contador). Frontend mostra as modelos com estilo por status, sobreposta à camada de clientes, e o
  toggle liga/desliga (Playwright).
- **Notas:** painel-only; IA **nunca** acessa. ⚠️ **Só endereço operacional, nunca o residencial**
  (PII sensível, ADR 0007). Raio de cobertura e análise de lacuna ficam **adiados** (ver ADR 0010 /
  MAPA-17).

### MAPA-16 — Choropleth por região (estado/cidade)
- **Objetivo:** pintar estados/cidades por demanda (R$/volume) para decisão de marketing "por praça".
- **Escopo:** 🔴 novo ADR (precisa de **geometria IBGE** + mapear cada ponto a uma região confiável;
  hoje só há `bairro` texto-livre).
- **Pré-requisito:** ADR definindo a fonte de fronteiras, o nível (UF/município) e o de-para
  ponto→região.

### MAPA-17 — Isócrona / drive-time a partir das modelos
- **Objetivo:** desenhar a **área de deslocamento viável** das modelos (conecta com o **Pix de
  deslocamento**) para ver quem está fora do alcance operacional.
- **Escopo:** 🔴 novo ADR + **API externa de isócrona** (custo).
- **Pré-requisito:** ADR definindo provedor, custo e como a área se relaciona ao Pix de deslocamento.

---

## Sequência recomendada

1. **Fase 1 inteira** (MAPA-1 → MAPA-5): vira ferramenta de marketing/expansão sem dependência nova
   e sem enganar com dado esparso.
2. **MAPA-6** (deck.gl + Hexbin) quando quiser o "cara de calor" de verdade.
3. **MAPA-7** (KDE) só quando o volume de pontos justificar.
4. **Extras** conforme a necessidade do momento (perda/oportunidade, perfil, filtros, lista linkada).
5. **Extensões (15-17)** apenas depois de aprovar um ADR para cada.
