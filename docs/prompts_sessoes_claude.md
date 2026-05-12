# Prompts para sessões do Claude — backlog "Modelos"

Cada prompt abaixo é autocontido: cole inteiro como a **primeira mensagem** de uma nova sessão de Claude Code na raiz `C:\barra`. As instruções de domínio (`CLAUDE.md`, `CONTEXT.md`, AGENTS frontend) são carregadas automaticamente — os prompts apenas reforçam pontos específicos.

**Origem:** ata de reunião com sugestões de outra IA. Tratar como recomendações, não como especificação fechada — cada sessão deve confirmar premissas com o engenheiro antes de codar (CLAUDE.md §1).

## Ordem sugerida de execução

1. **Sessão 1 — Remover seção "Dúvidas" (FAQ)** _(quick win, limpa código antes de mexer no resto)_
2. **Sessão 2 — Redesenhar Serviços/Programas como atômico por modelo via modal** _(define a nova estrutura do perfil)_
3. **Sessão 3 — Google Maps no campo de local de atendimento** _(componente isolado de form)_
4. **Sessão 4 — CRUD de mídias integrado ao MinIO** _(feature substantiva, independente)_
5. **Sessão 5 — Conexão WhatsApp via Evolution API** _(crítica e arriscada — deixar entre as features funcionais)_
6. **Sessão 6 — Polimento visual dos formulários** _(depois que estrutura está estável)_

Critério para inverter 4↔5: se Rossi precisa do gerenciamento de WhatsApp em produção urgentemente, sobe 5 antes de 4.

---

## Sessão 1 — Remover seção "Dúvidas" (FAQ) do perfil da modelo

```
Tarefa: remover completamente a seção de Dúvidas/FAQ do perfil da modelo.

Contexto da decisão (ata de reunião, recomendação de IA — confirme comigo antes de finalizar):
A seção de "Dúvidas" foi testada com outros clientes e não funcionou: confunde os clientes e fica abandonada. O conhecimento da IA deve ser gerido pela equipe de dev/operação, não como campo editável pelo cliente. Decisão: remover a seção do sistema.

Leia primeiro:
- CLAUDE.md (princípios — esp. §3 mudanças cirúrgicas) e CONTEXT.md
- Antes de tocar em qualquer .tsx, leia interface/AGENTS.md e a guia de Next.js apontada nele

Estado atual a remover:
- Backend
  - Tabela: barravips.modelo_faq (criada em infra/sql/0001_schema_inicial.sql; declarada no realtime em 0005_modelos_painel.sql)
  - Endpoints em api/src/barra/dominio/modelos/routes.py: GET/POST /modelos/{id}/faq, PATCH/DELETE /modelos/{id}/faq/{faq_id}
  - Schemas: FaqBody em api/src/barra/dominio/modelos/schemas.py
  - Resposta de GET /modelos/{id}: campo "faq" inclui modelo_faq (linhas 150-158 de routes.py) — remover do response também
- Frontend
  - Tab "faq" em interface/src/components/modelos/AbasModelo.tsx
  - interface/src/components/modelos/AbaFaq.tsx (componente)
  - interface/src/components/modelos/DialogFaq.tsx (modal)
  - Tipo AbaModelo, FaqItem, FaqInput, EscopoFaq em interface/src/tipos/modelos.ts
  - Uso em interface/src/app/(interface)/modelos/page.tsx: estados faqDialog, ações onAdicionarFaq/onEditarFaq/onExcluirFaq, confirmacao tipo "excluir-faq", DialogFaq import
  - Métodos no hook interface/src/hooks/useModelos.ts (procurar salvarFaq, deletarFaq, etc.)
  - Tipo ModeloDetalheResponse.faq em tipos/modelos.ts
- Agente
  - Verifique se algum nó do LangGraph em api/src/barra/agente/ consulta modelo_faq (grep "modelo_faq" em api/src/barra/agente/). Se sim, decida comigo se removemos a leitura ou mantemos como leitura sem painel.

O que fazer:
1. Faça um plano em forma de checklist (CLAUDE.md §4) e me apresente antes de codar. Aponte:
   - todos os arquivos que serão deletados
   - todos os arquivos que serão editados (e o que será removido em cada um)
   - o nome da nova migration (próximo número disponível em infra/sql/, hoje deve ser 0021_*)
   - se algum consumidor (agente) será afetado e como
2. Aprovado o plano, execute. Migration: DROP TABLE barravips.modelo_faq CASCADE (ela está em ALTER PUBLICATION supabase_realtime — verifique se precisa de DROP FROM PUBLICATION antes).
3. Não "melhore" código adjacente nem renomeie nada que não seja FAQ-relacionado (CLAUDE.md §3).

Verificação ao final:
- `cd api && make lint && make test` passam
- `cd interface && pnpm lint && pnpm build` passam
- Suba o backend (uv run uvicorn barra.main:app --reload) e o frontend (pnpm dev). Abra o perfil de uma modelo no navegador e confirme que só restam abas "Perfil" e "Mídia", e que GET /modelos/{id} não retorna mais o campo "faq".
- grep recursivo por "faq", "Faq", "FAQ", "modelo_faq", "Dúvida", "Duvida" no repo todo: só deve sobrar em changelog/ADR (e talvez em este próprio arquivo de prompts). Me mostre o resultado do grep.
```

---

## Sessão 2 — Serviços/programas atômicos por modelo via modal

```
Tarefa: redesenhar a gestão de serviços e preços da modelo para ser atômica por modelo (cada modelo cadastra os próprios serviços e durações no próprio perfil, via modal), em vez do modelo atual (catálogo global + grid programa × duração no perfil).

Contexto da decisão (ata de reunião, recomendação de IA — confirme premissas antes de fechar):
Hoje a operação é em duas etapas: (1) seção global "Programas" cria categorias (anal, oral...) e durações; (2) no perfil da modelo, todas as combinações programa × duração aparecem para definir preço. Problema: força todas as durações para todos os serviços, mesmo quando a modelo só faz "anal" em 30min e 1h e não em 2h/pernoite. Solução pedida: tornar atômico — dentro do perfil, "Adicionar Serviço" abre modal com multi-select de serviços (com opção de criar novo inline), seleção de durações para esse serviço (com criar nova inline), preço por duração. Manter a seção global como gerenciamento da lista master.

QUESTÃO IMPORTANTE A DECIDIR COMIGO ANTES DE CODAR:
A descrição da ata fala em "serviço" (anal/oral) com "durações específicas" — isso bate exatamente com a arquitetura atual: barravips.programas (catálogo) + barravips.duracoes (catálogo) + barravips.modelo_programas (vínculo modelo_id, programa_id, duracao_id, preco). A diferença não é estrutural, é de UX:
  - Estrutura atual: persiste linha em modelo_programas só quando há preço — então só os pares "ativos" estão registrados. O problema é a UI que mostra TODAS as combinações como linhas vazias com "Definir preço".
  - Reescrita pedida: mesma persistência, mas UI muda para fluxo "Adicionar serviço (modal)" — usuário escolhe quais serviços e quais durações fazem sentido para essa modelo, sem ver o grid combinatório.
Logo: provavelmente é só refatoração de UI + helpers para "criar programa/duração inline" a partir do modal. Esquema de DB NÃO precisa mudar. Cuidado para não cair na armadilha de inventar uma nova tabela.

Confirme essa interpretação comigo (ou aponte porque eu estou errado) antes de codar. Existe também uma tabela legada barravips.modelo_servicos criada em 0006_modelo_servicos.sql que NÃO é a usada hoje — não confunda; só remova se a faxina for solicitada.

Leia primeiro:
- CLAUDE.md (esp. §1 pense antes, §2 simplicidade — não invente abstração) e CONTEXT.md
- interface/AGENTS.md e a guia Next.js apontada nele antes de qualquer .tsx
- docs/adr/ e docs/mvp/ se houver decisão registrada sobre programas

Estado atual relevante:
- Schema (já existente, não recriar):
  - infra/sql/0007_programas.sql (catálogo barravips.programas)
  - infra/sql/0009_programas_simplificar.sql (drop colunas duracao_horas/descricao)
  - infra/sql/0010_duracoes.sql (catálogo barravips.duracoes e chave composta de modelo_programas)
- Backend (api/src/barra/dominio/modelos/):
  - routes.py: endpoints /modelos/{id}/programas (POST vincular, PATCH preço, DELETE desvincular)
  - programas_routes.py: catálogo global de programas e durações
  - schemas.py: ProgramaCreate, DuracaoCreate, VincularProgramaBody, AtualizarPrecoProgramaBody
- Frontend:
  - interface/src/app/(interface)/modelos/page.tsx: aba "Programas" → PainelProgramas (catálogo global)
  - interface/src/components/modelos/ProgramasModelo.tsx: render dentro do perfil — grid combinatório que precisa virar lista atômica
  - interface/src/components/modelos/PainelProgramas.tsx: mantém função de "lista master"
  - interface/src/hooks/useModelos.ts, useProgramas.ts
  - interface/src/tipos/modelos.ts: Programa, Duracao, ProgramaModeloVinculo

O que fazer:
1. Plano em checklist primeiro. Inclua:
   - Layout do novo "Card de Serviços e Preços" no perfil (lista vazia + botão "Adicionar Serviço")
   - Estrutura do novo modal: campos, fluxo "criar inline" para serviço e duração novos
   - Quais endpoints já cobrem o que (POST /programas para criar inline, POST /duracoes para criar inline, POST /modelos/{id}/programas para vincular)
   - O que muda em useModelos / ProgramasModelo.tsx, o que vira novo (DialogAdicionarServicoModelo.tsx, talvez)
   - Decisão: mantém aba "Programas" global como gerenciamento da lista master, com nota deixando claro que adicionar lá é opcional. Quaisquer programa/duração criados inline pelo perfil aparecem lá também.
   - Eventos UX: edição inline do preço de cada linha já vinculada; remover linha individualmente
2. Aprovado, codifique cirurgicamente — sem deletar PainelProgramas (continua sendo a lista master).
3. Reutilize componentes shadcn existentes (Dialog, MultiSelect, Combobox se existir, ou padrão de input com datalist).

Verificação ao final:
- Subir backend e frontend e fazer fluxo completo no navegador (CLAUDE.md §5):
  a) Criar uma modelo nova
  b) No perfil, abrir o modal, selecionar "Anal" + duração "30 min" + preço — verificar que só essa linha aparece
  c) Adicionar segundo serviço, criando inline um programa novo "Beijo grego" e duração nova "45 min", preço definido — verificar que apareceu em barravips.programas e barravips.duracoes
  d) Editar preço de uma linha; remover uma linha individualmente
  e) Confirmar que aba "Programas" global mostra os novos programas/durações criados inline
- `make lint && make test` no backend; `pnpm lint && pnpm build` no frontend.
```

---

## Sessão 3 — Google Maps Places no campo de local de atendimento

```
Tarefa: integrar Google Maps Places Autocomplete no campo "Bairro ou região" (localizacao_operacional) do perfil da modelo, persistindo endereço formatado, lat/lng e place_id.

Contexto da decisão (ata de reunião — confirme comigo):
Hoje "localizacao_operacional" é texto livre. Pode gerar endereço impreciso/mal formatado. A IA usa essa info para informar o cliente onde a modelo atende e para enviar a localização no atendimento interno. Solução pedida: substituir por Places Autocomplete, com coordenadas geográficas armazenadas.

ANTES DE CODAR, confirme comigo:
1. Existe API key do Google Maps disponível? (verificar api/.env.example e infra/compose/env/; se não existir, eu vou precisar provisionar — me peça)
2. Bairro/região é o nível certo? A ata fala em "endereço enviado ao cliente durante o atendimento". Para atendimento INTERNO (cliente vai à modelo), faz sentido endereço cheio com lat/lng. Para EXTERNO (modelo vai ao cliente), o que importa é a região de cobertura. Hoje o campo é único — vamos manter como um campo só (endereço estruturado, mas com label adaptável) ou separar? Decida comigo.
3. Próxima dúvida: Places Autocomplete (campo single) ou Place Picker com mapa (mais visual)? Recomendo Autocomplete pela simplicidade — confirma?

Leia primeiro:
- CLAUDE.md (§1, §2 — não over-engineer com mapa interativo se Autocomplete resolve) e CONTEXT.md (especialmente "Aviso de saída" e "Foto de portaria" para entender o uso operacional do endereço)
- interface/AGENTS.md e guia Next.js
- Procure se já existe alguma integração com Google em api/src/barra/core/

Estado atual:
- Schema: barravips.modelos.localizacao_operacional text NULL (criado em 0001_schema_inicial.sql, comentado em 0005_modelos_painel.sql)
- Backend:
  - api/src/barra/dominio/modelos/schemas.py: ModeloCreate/ModeloPatch.localizacao_operacional: str | None
  - routes.py: criar_modelo, editar_modelo aceitam o campo
- Frontend:
  - interface/src/components/modelos/AbaPerfil.tsx — card "Atendimento", linha "Bairro ou região" como <Input>
  - interface/src/components/modelos/DialogCriarModelo.tsx — também tem o campo (verificar; pelo que vi no estado atual NÃO tem, é só no PATCH; confirme)
  - interface/src/tipos/modelos.ts: ModeloDetalhe.localizacao_operacional: string | null

O que fazer:
1. Plano em checklist:
   - Migration: adicionar colunas em barravips.modelos (latitude numeric(10,7), longitude numeric(10,7), place_id text, endereco_formatado text). Não dropar localizacao_operacional já — mantenha como campo "humano" extra OU faça migração estrutural completa, comigo.
   - Provisão de API key: env var GOOGLE_MAPS_API_KEY no backend (se for usado em /place details) e/ou NEXT_PUBLIC_GOOGLE_MAPS_API_KEY no frontend (para Autocomplete client-side). Adicione a api/.env.example e interface/.env.example.
   - Componente novo no frontend: CampoLocalAutocomplete.tsx (envelope sobre @googlemaps/js-api-loader ou Places Web Component). Avalie packages — não escolha sem me consultar se for >100KB de bundle. Há a opção de PlaceAutocompleteElement (Web Component novo, mais leve).
   - Substituição em AbaPerfil.tsx e (se aplicável) DialogCriarModelo.tsx
   - Backend: schemas aceitam novos campos, routes.py grava-os no INSERT/UPDATE
   - Restrições da API key (HTTP referrers para frontend; restrição por API para backend) — me lembre de configurar no console Google Cloud
2. Implementação com fallback: se NEXT_PUBLIC_GOOGLE_MAPS_API_KEY não existir em runtime, o componente faz fallback para input texto comum (não quebrar dev local).

Verificação:
- Buscar um endereço real ("Rua Conde de Bonfim, 50, Tijuca, Rio") e confirmar que ao salvar:
  - lat/lng foram persistidos em modelos
  - place_id idem
  - endereço formatado segue padrão Google
- Trocar para outra modelo e voltar — campo carrega corretamente
- `make lint && make test` e `pnpm lint && pnpm build`
- Reporte tamanho do bundle do JS de Maps adicionado (`pnpm build` mostra)
```

---

## Sessão 4 — CRUD completo de mídias (fotos/vídeos) com MinIO

```
Tarefa: garantir que o CRUD de mídias do perfil da modelo está realmente funcional contra MinIO, sem dados mockados, com inativação (soft-delete) e deleção permanente.

Contexto (ata de reunião com IA — VALIDE com cuidado, a descrição da ata diz que "não está integrada ao Minio" e "exibe dados mockados", mas o código atual SUGERE integração funcional. Confirme o que está realmente quebrado antes de reescrever do zero):
- Backend já tem POST /modelos/{id}/midia/upload-url (presigned PUT), POST /modelos/{id}/midia (registrar metadados), GET (listar com presigned GET), PATCH, DELETE. Está em api/src/barra/dominio/modelos/routes.py linhas ~679-766.
- Tabela barravips.modelo_midia já existe (criada em 0001_schema_inicial.sql, comentada em 0012_bucket_rename.sql — bucket "barra-media").
- Frontend tem DialogMidiaUpload.tsx que chama upload-url, faz PUT direto pro MinIO, depois confirma metadados. GridMidia / ItemMidia mostram as mídias.

Confirme comigo antes de codar:
1. Onde aparecem dados mockados? Faça grep por "mock", "fake", placeholder.jpg, "via.placeholder" no frontend. Se não encontrar, abra o módulo no navegador (com MinIO local rodando ou desligado) e me reporte o que de fato aparece quebrado.
2. "Inativar mídia sem deletar" — hoje existe o flag `aprovada` (boolean). A UI já tem toggle "Disponível no atendimento" / "Ocultas". Isso JÁ é inativação. Está faltando algo? Ou só falta renomear a UX para "Ativa/Inativa" em vez de "Aprovada"? Confirme comigo.
3. MinIO está provisionado em dev? Verifique infra/compose/stack.barra.yml e api/.env.example (variáveis MINIO_*). Se não estiver subindo, eu te ajudo a provisionar.

Leia primeiro:
- CLAUDE.md (esp. §1 pense, §3 cirúrgico — NÃO reescreva o que já funciona) e CONTEXT.md
- interface/AGENTS.md
- api/src/barra/core/storage.py (presigned_put/presigned_get)
- api/src/barra/settings.py para descobrir minio_bucket_media, minio_endpoint, minio_access_key etc.

Estado atual a verificar:
- Backend
  - api/src/barra/dominio/modelos/routes.py: handlers de midia (linhas 679 em diante)
  - api/src/barra/dominio/modelos/schemas.py: MidiaUploadUrlRequest, MidiaCreate, MidiaPatch
  - api/src/barra/core/storage.py: presigned functions
  - infra/sql/0001_schema_inicial.sql + 0012_bucket_rename.sql para o schema completo de modelo_midia
- Frontend
  - interface/src/components/modelos/AbaMidia.tsx (filtros tipo/tag/aprovação)
  - interface/src/components/modelos/GridMidia.tsx, ItemMidia.tsx (render)
  - interface/src/components/modelos/DialogMidiaUpload.tsx (upload)
  - interface/src/components/modelos/DialogVisualizarMidia.tsx (preview)
  - interface/src/hooks/useModelos.ts: criarUploadUrl, criarMidia, atualizarMidia, deletarMidia
  - interface/src/tipos/modelos.ts: MidiaItem, MidiaInput, UploadUrlResponse, TipoMidia

O que fazer:
1. Validação primeiro (NÃO codifique antes):
   - Subir MinIO local (Portainer ou docker-compose) e backend; tentar upload real de foto e vídeo
   - Reportar exatamente o que falha (CORS no PUT pro MinIO? presigned URL apontando pra hostname errado? bucket inexistente? thumbnail ausente para vídeo? play do vídeo?)
2. Com base no que de fato quebrar, plano em checklist. Cenários prováveis a cobrir:
   - Bucket "barra-media" não existe no MinIO local → criar via setup ou via cliente Python no lifespan (verifique se já existe esse boot)
   - presigned URL retorna endpoint interno do container ("minio:9000") em vez do externo ("localhost:9000") quando o navegador tenta o PUT — corrigir presigned_put para usar settings.minio_public_endpoint se existir
   - Vídeos: thumbnail. Decidir comigo se geramos via ffmpeg no worker (ARQ) ou exibimos só <video> com poster do primeiro frame via metadata
   - Renomear UX "Aprovada/Ocultas" → "Ativa/Inativa" no AbaMidia.tsx se decidirmos. Manter coluna `aprovada` no schema OU renomear para `ativo` via migration. Para minimizar churn (CLAUDE.md §3), prefiro só ajustar labels e manter `aprovada` no schema.
3. Adicionar "deleção permanente" se ainda não existe: já tem DELETE /modelos/{id}/midia/{midia_id} (linha 757) mas pode estar somente removendo o registro DB e deixando o object_key no bucket. Decida comigo se deletar do bucket também (provavelmente sim — mas atenção que isso é destrutivo). Adicione MinIO.remove_object no fluxo de DELETE.

Verificação:
- Fluxo completo no navegador: upload foto JPEG, upload vídeo MP4, ver lista, abrir preview, marcar como inativa, voltar a ativar, deletar permanentemente. Confirmar no MinIO Console que o objeto sumiu após delete e permanece após inativação.
- `make lint && make test`; `pnpm lint && pnpm build`
- Sem mocks: grep por placeholder.*jpg, via.placeholder, mock, fake retorna vazio em interface/src/components/modelos/.
```

---

## Sessão 5 — Conexão WhatsApp via Evolution API funcional

```
Tarefa: tornar funcionais os botões "Conectar WhatsApp", "Trocar Conexão" e "Remover Conexão" no perfil da modelo, com integração real à Evolution API: gerar QR Code, detectar quando o cliente escaneou (conectado), permitir reconectar e desconectar.

Contexto da operação (Barra Vips):
Cada modelo opera no PRÓPRIO número de WhatsApp e tem uma instância Evolution dedicada. A IA conduz os atendimentos por esse número. Conectar = criar/parear instância Evolution gerando QR. Trocar = re-pareamento (instance existe, novo QR). Remover = limpar a vinculação (não necessariamente deletar a instância na Evolution). Validar isso comigo antes de codar.

Estado atual (leia antes de pedir mudanças):
- api/src/barra/core/evolution.py: EvolutionClient com:
  - enviar_texto (envio outbound)
  - conectar_instancia (GET /instance/connect/{instance_id} → retorna {status, qrcode})
  - buscar_grupo_info
- api/src/barra/dominio/modelos/routes.py:
  - POST /modelos/{id}/conectar-whatsapp (linha 203) — gera instance_id determinístico "modelo-{uuid}", chama EvolutionClient.conectar_instancia, grava evolution_instance_id na tabela
  - POST /modelos/{id}/desparear-whatsapp (linha 223) — só seta evolution_instance_id = NULL no DB; NÃO chama Evolution para deletar a instância
  - POST /modelos/{id}/coordenacao/verificar (linha 340) — verifica grupo Evolution
- Webhook Evolution: api/src/barra/webhook/routes.py — recebe eventos da Evolution (mensagens, talvez CONNECTION_UPDATE, QRCODE_UPDATED) — leia antes para entender o que já entra.
- Frontend:
  - interface/src/components/modelos/DialogConectarWhatsapp.tsx — exibe QR code (image base64), botão "Atualizar QR"
  - interface/src/components/modelos/AbaPerfil.tsx — botões "Trocar conexão", "Remover conexão", "Conectar WhatsApp"
  - interface/src/app/(interface)/modelos/page.tsx — useEffect "fecha sozinho quando evolution_instance_id ficar preenchido" (linha 75-81). ATENÇÃO: evolution_instance_id já está preenchido ANTES do scan acontecer (é setado no POST), então esse useEffect não detecta o evento "conectado". Esse é provavelmente um bug real.
- Settings (api/src/barra/settings.py): evolution_base_url, evolution_api_key, evolution_fernando_jids, etc.

Confirme comigo antes de codar:
1. Sinalização de "conectado" deve vir do webhook Evolution (event CONNECTION_UPDATE com state=open) ou de polling no GET /instance/connectionState/{instance}? Recomendo webhook para evitar polling. Mas se a Evolution na nossa infra ainda não posta esse evento, pode ser preciso ambos. Verifique.
2. "Remover Conexão" deve apenas desvincular no nosso DB (estado atual) ou também chamar DELETE /instance/{instance} na Evolution? Recomendo chamar a Evolution porque senão a instância fica "ghost". Confirme.
3. Status visual no modal: "loading" (gerando QR) → "aguardando scan" (QR exibido) → "conectado" (autofechar) ou → "expirado" (refresh). Hoje só tem loading/success/error e o success depende de evolution_instance_id setado. Vamos modelar estados explícitos.
4. Endpoint GET /modelos/{id}/whatsapp/status para o frontend polar enquanto o modal está aberto? Ou usar WebSocket/Realtime (Supabase Realtime já publica modelos)? Decida comigo.

Leia primeiro:
- CLAUDE.md (especialmente §1 pense, §4 critérios verificáveis) e CONTEXT.md
- interface/AGENTS.md
- docs/adr/ para qualquer ADR sobre Evolution
- docs/runbooks/ em infra/ para qualquer manual de operação da Evolution
- Documentação da Evolution API v2 (ou versão que estamos usando — verifique no docker-compose ou no requirements). Use o MCP Context7 se disponível.

O que fazer:
1. Plano em checklist. Cobertura mínima:
   - Criação de instância (verificar se a Evolution API tem POST /instance/create separado do connect, ou se connect cria — depende da versão)
   - Geração de QR e exposição no nosso endpoint
   - Detecção de "conectado": handler de webhook CONNECTION_UPDATE em api/src/barra/webhook/routes.py que ATUALIZA barravips.modelos.evolution_instance_id (ou nova coluna evolution_status enum: pareando/conectado/desconectado)
   - Migration: adicionar coluna evolution_status text (ou enum) com default 'desconectado'; talvez também evolution_pareado_em timestamptz para auditoria
   - GET /modelos/{id}/whatsapp/status para polling defensivo (fallback se webhook falhar)
   - DELETE na Evolution ao remover conexão (passar comigo se quer destrutivo)
   - Refresh do QR após expiração (já tem botão "Atualizar QR" — confirmar fluxo)
2. Não toque em código de envio de mensagens (já funciona, não regredir).

Verificação:
- Pré-requisitos: Evolution rodando em dev (verifique Portainer); número de teste secundário para escanear.
- Fluxo no navegador:
  a) Modelo sem WhatsApp → clicar "Conectar WhatsApp" → modal abre, QR aparece em <3s
  b) Escanear com WhatsApp Web no celular de teste → modal detecta dentro de 5s e fecha; badge "WhatsApp pronto" aparece
  c) "Trocar Conexão" → modal abre, novo QR; ao escanear, antigo "instance" é trocado (ou rotacionado conforme decisão)
  d) "Remover Conexão" → confirmação → DB limpo E (se decidido) instância removida da Evolution
- Logs: nenhum 5xx em backend; webhook recebe e processa.
- `make lint && make test` (cobertura mínima do novo handler de webhook); `pnpm lint && pnpm build`
- Atualize docs/runbooks/ com o fluxo operacional novo (mesmo que mínimo).
```

---

## Sessão 6 — Polimento visual dos formulários (transversal, não só Modelos)

```
Tarefa: melhorar o design dos campos de formulário em todos os módulos do sistema, eliminando a "ilusão de ótica" em que a borda do input se confunde com o fundo. Aplicar de forma consistente.

Contexto da ata:
Os formulários estão muito simplistas e os campos de input se confundem com o fundo da página. Difícil identificar onde começa/termina cada campo, especialmente em forms longos. A melhoria precisa ser sistêmica (não pontual no módulo Modelos).

ANTES DE CODAR, confirme comigo:
1. Esta tarefa precisa vir DEPOIS das tarefas 1-5 deste backlog, porque elas alteram a estrutura dos forms (modal de serviços, campo de mapa, etc.). Confirme que 1-5 estão completas antes de começar.
2. Direção visual: prefere mexer no token de cor (--border, --input) globalmente, OU criar uma variante "Field" do Input com tratamento próprio (ring, label flutuante, etc.)? Eu recomendo: ajustar tokens em globals.css/theme E adicionar pequenas melhorias no componente Input (sem mudar API). Confirme.
3. Escopo dos módulos a varrer: pelo menos Modelos, Atendimentos, Clientes, Programas, Pix. Verifique se há outros forms relevantes em (interface)/agenda, dashboard.
4. Acessibilidade: garantir AA contrast no border do input.

Leia primeiro:
- CLAUDE.md (§3 mudanças cirúrgicas — atenção para NÃO refatorar lógica adjacente) e CONTEXT.md
- interface/AGENTS.md e a guia Next.js
- interface/src/components/ui/input.tsx (componente base shadcn — usa @base-ui/react/input, data-slot pattern)
- interface/src/app/globals.css (tokens de cor)
- tailwind config (se existir tailwind.config.* ou se é Tailwind v4 com @theme inline em globals.css)
- interface/src/components/ui/{button,select,textarea,label}.tsx para coerência de tom

Estado atual:
- Input: h-8 default, rounded-lg, border border-input bg-transparent, focus ring-3 ring-ring/50. O problema reportado é principalmente `bg-input` sutil aplicado em cima por callers (ex: AbaPerfil.tsx usa `className="h-10 bg-input"`).
- Padrão de "label flutuante por cima" não existe; labels são tags <label className="grid gap-2 text-xs font-semibold uppercase tracking-[0.08em] text-text-muted"> em AbaPerfil, DialogCriarModelo, DialogMidiaUpload, DialogFaq (este último sai com a tarefa 1), PainelProgramas, etc.
- Inputs <select> em vários lugares são raw HTML (sem o wrapper shadcn) → também sofrem da mesma falta de contraste. Padronizar.
- Textarea em DialogFaq usa classes ad-hoc; centralizar via componente ui/textarea se ainda não existe.

O que fazer:
1. Plano em checklist:
   - Inventário (rodar grep antes): lista de todos os <Input>, <select>, <textarea> em interface/src/. Quantos? Onde? Quais usam className extra de bg/border?
   - Decisão sobre tokens: --input, --border, --ring values (com contraste AA). Light/dark se ambos forem suportados.
   - Componente Input: revisar default border (1.5px ou cor mais sólida), default bg (manter transparente OU semi-elevado consistente)
   - Padronizar <select> via componente shadcn Select (composto, com Trigger/Content) — listar onde substituir
   - Textarea: ui/textarea.tsx (se não existe, criar)
   - Helper visual: pequeno espaçamento entre label e campo, divider sutil entre cards de form se necessário
   - Estado :invalid e :disabled visivelmente distintos
2. Execução em onda única (não fica passando em arquivos para refatorar lógica — só visual e tipo Input).
3. Para cada arquivo tocado, remova classes redundantes ("h-10 bg-input" passa a ser default do componente).

Verificação:
- Antes/depois visual: abra cada tela com form (criar modelo, perfil aba Perfil, criar atendimento se aplicável, novo cliente, etc.) e tire screenshots ANTES e DEPOIS. Anexe os pares no commit ou em um docs/visual/ effémero.
- Contrast check: ferramenta tipo axe-core ou Chromium DevTools — borda do input deve ter contraste ≥ 3:1 com fundo (WCAG AA non-text).
- Regression: `pnpm lint && pnpm build`; e abrir todos os módulos para garantir que nada quebrou de layout (CLAUDE.md §5 — verificação concreta).
- Não introduzir dependências novas pesadas.
```

---

## Notas finais

- Cada sessão começa do zero, sem memória das anteriores. Os prompts acima incluem o contexto necessário, mas se mudanças do P0 forem feitas em paralelo, atualize o estado-atual antes de colar.
- Toda migration nova vai em `infra/sql/NNNN_*.sql` sequencial (sem framework — ver CLAUDE.md). Hoje próximo número livre é **0021**.
- Branches recomendadas (CLAUDE.md):
  - `feat/modelos-remover-faq`
  - `feat/modelos-servicos-atomicos`
  - `feat/modelos-google-maps-local`
  - `feat/modelos-midia-minio`
  - `feat/modelos-whatsapp-evolution`
  - `chore/ui-forms-visual`
