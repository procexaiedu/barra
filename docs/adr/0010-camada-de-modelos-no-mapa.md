# Camada de Modelos no Mapa de clientes

O ADR 0008 criou o **Mapa de clientes** (demanda: 1 pin por cliente, no atendimento externo mais
recente) e deixou explícito que "um mapa de onde acontecem os atendimentos (internos = casa das
modelos) é **outra visão**, não um bug a corrigir nesta". Esta decisão materializa essa outra visão
como uma **camada de oferta** sobreposta ao mesmo mapa: plotar as **modelos** na sua localização
operacional, para Fernando ler **oferta × demanda** num olhar (a demanda concentra na Zona Sul e
nenhuma modelo cobre lá?). É a tarefa MAPA-15 do `docs/specs/roadmap-mapa-de-clientes.md`.

O dado necessário **já existe**: `barravips.modelos.latitude/longitude` (migration 0028) guarda a geo
do endereço **operacional** — explicitamente distinto do **residencial**, que é PII sensível e nem tem
lat/lng (ADR 0007). Logo, esta camada **não captura dado novo nem toca PII sensível**. Ver termos em
`CONTEXT.md`.

## Decisões

- **Camada de oferta separada, em toggle.** A camada de Modelos é distinta da de clientes (cor/ícone
  próprios) e liga/desliga por toggle, sem alterar a semântica dos pins de cliente do ADR 0008 (que
  seguem só-externo, 1 por cliente). 1 pin por modelo. Plotar os dois juntos é o ponto: ler oferta
  contra demanda no mesmo enquadramento.
- **Fonte: `modelos.latitude/longitude` (operacional, 0028).** É a geo canônica de "onde a modelo
  atende". **Nunca** o endereço residencial (ADR 0007: PII sensível, sem geo). **Não** derivar a
  posição dos atendimentos internos: o ponto operacional já é o mesmo lugar onde os internos
  acontecem, e derivar adicionaria complexidade sem ganho. Modelo sem geo operacional (texto-livre
  legado, `lat/lng NULL`) **não some**: entra num contador "sem localização operacional", espelhando
  o "sem localização" dos clientes (ADR 0008) e a linha "não classificadas" do ADR 0006.
- **Todas as modelos, com estilo por status.** Plota `ativa`/`pausada`/`inativa` com cor/ícone
  distintos (status já é `modelo_status_enum` na tabela). Operação e expansão se beneficiam de ver
  oferta corrente (ativa), recuperável (pausada) e potencial (inativa); o custo é só estilo. Limitar
  a "só ativas" descartaria sinal de graça — quem quiser filtrar usa o toggle/legenda no front.
- **Endpoint dedicado no contexto `modelos`, não em `clientes`.** Novo `GET /v1/modelos/mapa` em
  `dominio/modelos/routes.py`, **não** estender `GET /clientes/mapa`: o dado de modelo pertence ao
  bounded context `modelos` (isolamento do `dominio/CLAUDE.md` — não cruzar `modelos.py` entre
  contextos). Retorna só o necessário e **não-sensível** por modelo: `id, nome, latitude, longitude,
  status, tipo_fisico, tipo_atendimento_aceito`, mais `total_sem_localizacao_operacional`. Sem
  paginação (poucas modelos no P0). **Nunca** retorna `rg/cpf/endereço residencial/percentual_repasse`.
- **Render leve, sem deck.gl.** Poucas modelos → `AdvancedMarkerElement` clássico (como os clientes
  hoje), sem clustering nem overlay deck.gl. A camada **não depende** das fases 2/3 do roadmap
  (hexbin/KDE); pode ser entregue isolada, sobre o baseline atual ou sobre as bolhas (MAPA-2).
- **InfoWindow não-sensível.** Ao clicar no pin da modelo: `nome`, `status`, `tipo_fisico` (badge) e
  tipos de atendimento aceitos. Nenhum campo da ficha cadastral (ADR 0007).
- **Painel-only, IA nunca acessa.** Como o Mapa de clientes (ADR 0008) e o Perfil físico preferido
  (ADR 0006): exclusivo de Fernando. A **IA por modelo** não lê esta camada. A RLS já fecha
  `barravips.modelos` em Fernando (`fernando_full_access`/`is_fernando()`, ADR 0007) — nada novo de
  auth no P0.

## Considered Options

- **Estender `GET /clientes/mapa` para devolver também as modelos:** rejeitado — mistura dois bounded
  contexts num endpoint do contexto errado e infla um payload cuja semântica (1 ponto por cliente) é
  diferente. O front compõe as duas camadas chamando dois endpoints.
- **Derivar a posição da modelo dos atendimentos internos** (mais recente/mais comum): rejeitado — a
  geo operacional canônica já existe em `modelos` (0028); derivar reintroduz a lógica de "ponto mais
  recente" sem ganho, e o resultado seria o mesmo lugar.
- **Raio de cobertura (círculo fixo) por modelo:** **adiado**. Um raio fixo sugere um alcance que não
  é real numa cidade (e o **Pix de deslocamento** é valor fixo, não proporcional à distância): seria
  precisão falsa. Alcance realista é **isócrona/drive-time** — fica como MAPA-17 (🔴, ADR próprio).
- **Análise de lacuna (demanda sem modelo próxima):** **adiado** — pesado e prematuro com piloto
  esparso. Vira tarefa/ADR futuro depois que a camada simples estiver de pé e houver volume.
- **Plotar só `ativa`:** rejeitado — descarta oferta recuperável (pausada) e potencial (inativa) que
  importam para expansão; o estilo por status custa quase nada.
- **Usar o endereço residencial:** rejeitado — PII sensível (ADR 0007), sem geo, e mediria onde a
  modelo *mora*, não onde *atende*.

## Consequences

- A tarefa MAPA-15 do roadmap deixa de ser 🔴 (precisa de dado novo) e passa a 🟡 (dado existe; só
  expor no novo endpoint + camada no front), destravada por este ADR.
- Modelos legadas com `lat/lng NULL` caem no contador "sem localização operacional"; corrige-se
  preenchendo o endereço operacional pelo autocomplete no cadastro da modelo (sem backfill
  automático).
- Surge um segundo endpoint de "mapa" (`/modelos/mapa`) ao lado de `/clientes/mapa`; ambos
  painel-only, não paginados, no padrão SQL inline do contexto. Se um dia houver dezenas de modelos,
  o mesmo caminho de evolução do 0008 (bounding-box) se aplica.
- Sem migration: a única dependência de dado (`modelos.lat/lng`) já está aplicada (0028).
- Raio de cobertura e análise de lacuna ficam registrados aqui como **deliberadamente adiados**, não
  esquecidos — quando virarem necessidade, são ADRs/tarefas próprios (MAPA-17 e futura).
