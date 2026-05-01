# Especificação de Implementação Backend P0

> Projeto: Barra Vips MVP  
> Fase: Backend operacional para sustentar frontend/interface  
> Status: especificação acionável para agente implementador  
> Fonte de verdade de dados: `infra/sql/0001_schema_inicial.sql`

## 1. Objetivo desta fase

Construir o backend operacional P0 que sustenta o painel Next.js, a operação manual assistida de Fernando e os fluxos de WhatsApp/Evolution já modelados no banco.

Esta fase **não tem como foco implementar agente/IA/LangGraph**. O backend deve preparar integrações e contratos para IA futura, mas a entrega obrigatória agora é:

- API REST `/v1` consumida pelo frontend;
- autenticação/autorização via Supabase Auth JWT;
- serviços de domínio sobre o schema `barravips`;
- webhook Evolution para persistência e comandos operacionais;
- agenda, CRM, atendimentos, Pix, mídia e dashboard;
- comandos de grupo e ações do painel pela mesma porta de aplicação;
- workers operacionais sem agente: timeouts, limpeza de mídia, jobs de envio e manutenção;
- observabilidade, logs, métricas e erros previsíveis.

## 2. Decisões fechadas

### 2.1 Fonte de verdade do banco

O arquivo `infra/sql/0001_schema_inicial.sql` é a fonte de verdade da estrutura de dados já finalizada.

Se houver divergência entre documentação antiga em `docs/mvp/*.md` e o SQL, o backend deve seguir o SQL.

Decisões já assumidas pelo SQL:

- schema único: `barravips`;
- não existe tabela `modelo_perfil`;
- dados da modelo ficam estruturados em `barravips.modelos`;
- cards e confirmações do grupo não ficam em `mensagens`;
- `mensagens` representa conversa cliente-modelo;
- `escaladas` e `eventos` representam handoff/comandos/auditoria operacional;
- RLS está habilitada em todas as tabelas;
- Postgres/Supabase é a fonte de verdade operacional.

### 2.2 Migrations sem framework

Mudanças novas de banco devem ser SQL puro sequencial em `infra/sql/NNNN_nome.sql`, aplicadas na ordem numérica via `psql` ou Supabase Studio.

Para esta fase, criar:

- `infra/sql/0002_envios_evolution.sql`

O backend pode ter script simples para aplicar SQLs em ordem, mas não deve depender de ORM nem de migration framework.

### 2.3 API do painel

Prefixo público da API do painel:

- `/v1`

Endpoints técnicos fora da versão:

- `/health`
- `/ready`
- `/metrics`

Webhook:

- `/webhook/evolution`

O frontend deve configurar `NEXT_PUBLIC_API_URL` apontando para a base versionada do backend, por exemplo `https://api.exemplo.com/v1`.

### 2.4 Fronteira FastAPI vs Supabase

Toda mutação operacional passa pelo FastAPI.

O frontend pode usar Supabase para:

- autenticação;
- Realtime para atualizações incrementais;
- leitura direta apenas se explicitamente mantida simples e segura.

Mas as seguintes ações **sempre** passam pelo backend:

- fechar atendimento;
- perder atendimento;
- corrigir registro;
- devolver para IA;
- validar/recusar Pix;
- criar/editar/cancelar bloqueio;
- cadastrar/editar modelo;
- cadastrar/editar FAQ;
- cadastrar/editar mídia;
- processar comandos do grupo;
- qualquer ação que altere estado, agenda, Pix, financeiro, handoff ou auditoria.

### 2.5 Leitura no frontend

Padrão confirmado:

- carga inicial via REST `/v1`;
- atualizações incrementais via Supabase Realtime nas tabelas já publicadas:
  - `atendimentos`;
  - `mensagens`;
  - `bloqueios`;
  - `comprovantes_pix`;
  - `eventos`.

### 2.6 IA/agentes fora do foco atual

Não implementar agente ReAct, LangGraph, tools de IA ou prompt de produção nesta fase.

Preparar apenas abstrações futuras quando necessário, sem bloquear a entrega operacional:

- interfaces de provider LLM podem existir;
- variáveis de ambiente podem ser previstas;
- endpoints/serviços não devem depender de IA para funcionar.

## 3. Arquitetura esperada

Backend como monolito modular FastAPI, organizado por bounded contexts em `api/src/barra/dominio`.

### 3.1 Módulos obrigatórios

Implementar ou completar os módulos:

- `core`
  - configuração;
  - banco psycopg3;
  - auth JWT Supabase;
  - erros;
  - logging;
  - métricas;
  - Redis;
  - MinIO;
  - Evolution client.
- `dominio/atendimentos`
  - listagem;
  - detalhe;
  - transições operacionais;
  - fechamento/perda/correção.
- `dominio/agenda`
  - bloqueios;
  - consulta;
  - criação manual;
  - cancelamento;
  - conflito de horário.
- `dominio/crm` ou `dominio/conversas`
  - conversas;
  - clientes;
  - observações internas;
  - histórico.
- `dominio/modelos`
  - cadastro da modelo;
  - FAQ;
  - mídia;
  - conexão Evolution.
- `dominio/pix`
  - fila em revisão;
  - detalhe;
  - validar;
  - recusar.
- `dominio/escaladas`
  - comandos canônicos;
  - handoff/devolução;
  - porta única para escrita sensível.
- `dominio/eventos`
  - audit log humano-legível para ações operacionais de atendimento.
- `webhook`
  - entrada Evolution;
  - validação;
  - persistência;
  - comandos do grupo.
- `workers`
  - timeouts;
  - limpeza de mídia;
  - jobs de envio;
  - manutenção.

### 3.2 Banco e repositórios

Seguir ADR-0002:

- SQL puro com psycopg3;
- sem ORM;
- cada contexto com `repo.py`, `service.py`, `routes.py`, `schemas.py`, `modelos.py`;
- repositórios recebem conexão do pool;
- serviços controlam transações.

Conexão:

- usar `AsyncConnectionPool`;
- conectar ao Supabase via Supavisor;
- pool criado uma vez no lifespan FastAPI;
- nunca criar pool por request.

## 4. Migration SQL obrigatória: `envios_evolution`

Criar `infra/sql/0002_envios_evolution.sql`.

### 4.1 Objetivo

Registrar todo outbound enviado pelo backend via Evolution.

Essa tabela é crítica para distinguir:

- mensagem enviada pelo backend/IA/sistema;
- mensagem manual da modelo no número operado pela Evolution.

O parser de comandos no grupo deve consultar esta tabela por `evolution_message_id`.

### 4.2 Tabela

```sql
CREATE TABLE barravips.envios_evolution (
  id                    uuid PRIMARY KEY DEFAULT barravips.uuidv7(),
  evolution_message_id  text NOT NULL UNIQUE,
  instance_id           text NOT NULL,
  remote_jid            text NOT NULL,
  contexto              text NOT NULL,
  direcao               text NOT NULL DEFAULT 'outbound_backend',
  tipo                  text NOT NULL,
  atendimento_id        uuid REFERENCES barravips.atendimentos(id) ON DELETE SET NULL,
  conversa_id           uuid REFERENCES barravips.conversas(id) ON DELETE SET NULL,
  payload               jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at            timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT envios_evolution_contexto_check
    CHECK (contexto IN ('conversa_cliente', 'grupo_coordenacao')),
  CONSTRAINT envios_evolution_direcao_check
    CHECK (direcao = 'outbound_backend'),
  CONSTRAINT envios_evolution_tipo_check
    CHECK (tipo IN ('ia', 'card', 'confirmacao', 'erro_comando', 'midia'))
);
```

Índices:

```sql
CREATE INDEX envios_evolution_remote_jid_created_idx
  ON barravips.envios_evolution (remote_jid, created_at DESC);

CREATE INDEX envios_evolution_atendimento_created_idx
  ON barravips.envios_evolution (atendimento_id, created_at DESC)
  WHERE atendimento_id IS NOT NULL;

CREATE INDEX envios_evolution_conversa_created_idx
  ON barravips.envios_evolution (conversa_id, created_at DESC)
  WHERE conversa_id IS NOT NULL;
```

RLS/grants/realtime:

- habilitar RLS;
- aplicar policy `fernando_full_access` igual às demais tabelas;
- conceder grants para `authenticated` e `service_role`;
- não precisa entrar no Supabase Realtime no P0.

### 4.3 Regra transacional de envio

Todo envio via Evolution deve:

1. chamar Evolution;
2. obter `key.id` da resposta;
3. persistir `envios_evolution.evolution_message_id = key.id`;
4. só então considerar o envio concluído.

Se persistir falhar depois do Evolution enviar, registrar erro crítico no Sentry/log. Esse caso compromete a distinção entre backend e modelo manual.

## 5. Auth e autorização

### 5.1 Supabase Auth

O painel usa Supabase Auth.

Toda chamada `/v1` deve enviar:

```http
Authorization: Bearer <access_token>
```

FastAPI deve:

- validar o JWT;
- não confiar apenas no frontend;
- resolver usuário pelo `sub`;
- consultar `barravips.usuarios`;
- exigir `ativo=true`;
- exigir `papel='fernando'` para P0.

### 5.2 Permissões P0

No P0:

- Fernando pode ler e mutar tudo que a API expõe;
- `vendedor_read_only` não opera;
- chamadas sem token retornam `401`;
- usuário sem permissão retorna `403`;
- workers usam credencial server-side/service role, nunca token do frontend.

### 5.3 CORS

Permitir apenas:

- domínio da Vercel em produção;
- localhost em desenvolvimento.

Não usar `*` em produção.

## 6. Padrão de erro REST

Todos os erros não-2xx da API `/v1` devem retornar:

```json
{
  "error": {
    "code": "COMANDO_INVALIDO",
    "message": "Valor final obrigatório.",
    "details": {
      "campo": "valor_final"
    }
  }
}
```

Regras:

- `code`: string estável em `SCREAMING_SNAKE_CASE`;
- `message`: texto curto e seguro para o painel;
- `details`: objeto opcional;
- `422`: validação de input;
- `401`: sem autenticação;
- `403`: sem permissão;
- `404`: recurso inexistente;
- `409`: conflito de estado, agenda ou comando;
- `500`: erro inesperado, com mensagem genérica e detalhe real apenas em log/Sentry.

## 7. Endpoints REST P0

Todos exigem autenticação de Fernando, exceto `/health`, `/ready`, `/metrics` e webhook.

### 7.1 Atendimentos

#### `GET /v1/atendimentos`

Lista paginada para Central de Atendimentos.

Query params:

- `estado?`
- `tipo_atendimento?`
- `ia_pausada?`
- `modelo_id?`
- `q?` busca por nome/telefone/numero_curto
- `limit?` default 50
- `cursor?`

Resposta:

```json
{
  "items": [
    {
      "id": "uuid",
      "numero_curto": 142,
      "cliente": {
        "id": "uuid",
        "nome": "Carlos",
        "telefone_mascarado": "+55*****1234"
      },
      "modelo": {
        "id": "uuid",
        "nome": "Bia"
      },
      "estado": "Aguardando_confirmacao",
      "tipo_atendimento": "externo",
      "urgencia": "imediato",
      "ia_pausada": true,
      "ia_pausada_motivo": "pix_em_revisao",
      "responsavel_atual": "Fernando",
      "motivo_escalada": "pix divergente",
      "proxima_acao_esperada": "Validar comprovante",
      "updated_at": "2026-04-30T12:00:00Z"
    }
  ],
  "next_cursor": "string|null"
}
```

#### `GET /v1/atendimentos/{id}`

Detalhe completo do atendimento.

Deve incluir:

- atendimento;
- cliente;
- conversa;
- modelo;
- bloqueio vinculado;
- mensagens paginadas mais recentes;
- eventos;
- comprovantes Pix vinculados;
- escaladas abertas/fechadas.

#### `POST /v1/atendimentos/{id}/devolver`

Libera `ia_pausada=false`.

Body:

```json
{
  "observacao": "Resolvido no grupo"
}
```

Efeitos:

- atualizar atendimento;
- fechar escalada aberta, se houver;
- inserir evento `devolucao_para_ia`;
- não disparar IA nem mensagem proativa.

Erros:

- `409` se atendimento já estiver `Fechado` ou `Perdido`;
- `409` se `ia_pausada=false`.

#### `POST /v1/atendimentos/{id}/fechar`

Body:

```json
{
  "valor_final": 1000.0
}
```

Efeitos:

- `estado='Fechado'`;
- `valor_final` obrigatório;
- snapshot de `percentual_repasse` da modelo, se existir;
- trigger do banco deve concluir bloqueio vinculado;
- inserir `fechado_registrado` e `transicao_estado`.

#### `POST /v1/atendimentos/{id}/perder`

Body:

```json
{
  "motivo": "sumiu",
  "observacao": null
}
```

Regras:

- motivo enum: `preco`, `sumiu`, `risco`, `indisponibilidade`, `fora_de_area`, `outro`;
- `outro` exige observação curta.

Efeitos:

- `estado='Perdido'`;
- trigger do banco cancela bloqueio se aplicável;
- inserir `perdido_registrado` e `transicao_estado`.

#### `POST /v1/atendimentos/{id}/corrigir-registro`

Body:

```json
{
  "novo_resultado": "Fechado",
  "valor_final": 1200.0,
  "motivo": null,
  "observacao": null,
  "confirmar_alteracao_bloqueio_finalizado": false
}
```

Regras:

- apenas Fernando;
- recalcula financeiro;
- audita em `correcao_registro`;
- se precisar alterar bloqueio já `em_atendimento` ou `concluido`, exigir confirmação explícita.

### 7.2 Agenda

#### `GET /v1/agenda/bloqueios`

Query:

- `modelo_id`
- `inicio`
- `fim`
- `estado?`

Resposta: lista de bloqueios com atendimento resumido quando vinculado.

#### `POST /v1/agenda/bloqueios`

Body:

```json
{
  "modelo_id": "uuid",
  "inicio": "2026-04-30T22:00:00-03:00",
  "fim": "2026-04-30T23:00:00-03:00",
  "observacao": "Bloqueio manual"
}
```

Efeitos:

- cria `bloqueios` com `origem='painel_fernando'`;
- falha com `409` se houver sobreposição ativa;
- inserir evento `bloqueio_criado` apenas se vinculado a atendimento; caso contrário log estruturado basta.

#### `PATCH /v1/agenda/bloqueios/{id}`

Edita horário/observação de bloqueio manual.

Não permitir edição insegura de bloqueio vinculado a atendimento sem validação explícita.

#### `POST /v1/agenda/bloqueios/{id}/cancelar`

Cancela bloqueio.

Regras:

- não cancelar bloqueio `concluido`;
- se bloqueio estiver `em_atendimento`, exigir confirmação no body.

### 7.3 CRM / Conversas

#### `GET /v1/crm/conversas`

Query:

- `modelo_id?`
- `recorrente?`
- `ultimo_motivo_perda?`
- `q?`
- `limit?`
- `cursor?`

Lista conversas por par cliente-modelo.

#### `GET /v1/crm/conversas/{id}`

Inclui:

- cliente;
- conversa;
- atendimentos históricos;
- últimas mensagens;
- observações internas.

#### `PATCH /v1/crm/conversas/{id}`

Body:

```json
{
  "observacoes_internas": "Cliente prefere horário após 22h",
  "nome_cliente": "Carlos"
}
```

Pode atualizar:

- `conversas.observacoes_internas`;
- `clientes.nome`.

Não altera histórico bruto.

### 7.4 Modelos

#### `GET /v1/modelos`

Lista modelos.

P0 normalmente terá uma modelo ativa, mas não hardcodar isso.

#### `POST /v1/modelos`

Body mínimo alinhado ao SQL:

```json
{
  "nome": "Bia",
  "idade": 25,
  "numero_whatsapp": "5521999999999",
  "valor_padrao": 1000.0,
  "percentual_repasse": 40.0,
  "chave_pix": "pix@example.com",
  "titular_chave": "Nome Titular",
  "idiomas": ["pt-BR", "en-US"],
  "localizacao_operacional": "Barra da Tijuca",
  "tipo_atendimento_aceito": ["interno", "externo"]
}
```

#### `GET /v1/modelos/{id}`

Perfil completo:

- modelo;
- FAQs;
- mídia;
- status Evolution, quando consultável.

#### `PATCH /v1/modelos/{id}`

Edita campos cadastrais da modelo.

Não deve alterar histórico de atendimentos.

#### `POST /v1/modelos/{id}/conectar-whatsapp`

Body:

```json
{
  "confirmar_rotacao": false
}
```

Comportamento:

- chama Evolution para criar/selecionar instância;
- atualiza `modelos.evolution_instance_id`;
- retorna status e QR code quando disponível;
- se já conectada, retorna `connected` sem recriar sessão;
- se rotação/troca puder derrubar sessão, exigir `confirmar_rotacao=true`;
- não persistir QR em banco.

Eventos cadastrais/conexão Evolution não precisam ir para `eventos`; usar logs estruturados e Sentry em erro.

### 7.5 FAQ

Endpoints:

- `GET /v1/modelos/{id}/faq`
- `POST /v1/modelos/{id}/faq`
- `PATCH /v1/modelos/{id}/faq/{faq_id}`
- `DELETE /v1/modelos/{id}/faq/{faq_id}`

Body:

```json
{
  "pergunta": "Atende em hotel?",
  "resposta": "Sim, conforme disponibilidade.",
  "tags": ["local", "hotel"]
}
```

Para FAQ global (`modelo_id IS NULL`), definir endpoints separados somente se o painel precisar. Não improvisar no mesmo endpoint sem decisão.

### 7.6 Mídia da modelo

#### `POST /v1/modelos/{id}/midia/upload-url`

Body:

```json
{
  "filename": "foto1.jpg",
  "content_type": "image/jpeg"
}
```

Resposta:

```json
{
  "object_key": "modelos/{modelo_id}/midia/{uuid}/foto1.jpg",
  "upload_url": "https://...",
  "expires_in": 900
}
```

#### `POST /v1/modelos/{id}/midia`

Body:

```json
{
  "tipo": "foto",
  "tag": "apresentacao",
  "object_key": "modelos/{modelo_id}/midia/{uuid}/foto1.jpg",
  "aprovada": true
}
```

Regras:

- backend valida prefixo esperado da modelo;
- não aceitar object_key fora do namespace da modelo;
- IA futura só pode usar `aprovada=true`.

Outros endpoints:

- `GET /v1/modelos/{id}/midia`
- `PATCH /v1/modelos/{id}/midia/{midia_id}`
- `DELETE /v1/modelos/{id}/midia/{midia_id}`

Leitura deve retornar URL assinada curta, nunca URL pública permanente.

### 7.7 Pix

#### `GET /v1/pix/em-revisao`

Lista comprovantes com:

- `decisao_pipeline='em_revisao'`;
- `decisao_final IS NULL`.

#### `GET /v1/pix/{id}`

Detalhe:

- comprovante;
- atendimento;
- cliente;
- modelo;
- comparação com chave/titular/valor esperado;
- URL assinada da imagem.

#### `POST /v1/pix/{id}/validar`

Efeitos:

- `comprovantes_pix.decisao_final='validado'`;
- aplicar comando operacional `atualizar_pix(validado)`;
- `atendimentos.pix_status='validado'`;
- atendimento externo vai para `Confirmado`;
- `ia_pausada=true`;
- `ia_pausada_motivo='modelo_em_atendimento'`;
- `responsavel_atual='modelo'`;
- enviar card "saída confirmada" no grupo;
- registrar outbound em `envios_evolution`;
- inserir eventos.

#### `POST /v1/pix/{id}/recusar`

Body:

```json
{
  "motivo": "valor divergente"
}
```

Efeitos:

- `comprovantes_pix.decisao_final='invalido'`;
- `atendimentos.pix_status='invalido'`;
- atendimento continua em `Aguardando_confirmacao`;
- `ia_pausada=false`;
- não pedir automaticamente novo Pix;
- Fernando decide próximo passo.

### 7.8 Dashboard

#### `GET /v1/dashboard`

Query:

- `periodo=hoje|7d|30d`
- `modelo_id?`

Resposta:

```json
{
  "periodo": "hoje",
  "atendimentos_por_estado": {
    "Novo": 1,
    "Triagem": 2,
    "Qualificado": 3,
    "Aguardando_confirmacao": 1,
    "Confirmado": 0,
    "Em_execucao": 0,
    "Fechado": 4,
    "Perdido": 2
  },
  "fechamentos": {
    "quantidade": 4,
    "valor_bruto": 4200.0
  },
  "perdas_por_motivo": {
    "sumiu": 2
  },
  "pix_em_revisao": 1,
  "atendimentos_escalados": 2
}
```

## 8. Webhook Evolution

Endpoint:

- `POST /webhook/evolution`

### 8.1 Validação

Obrigatório:

- validar segredo/token configurado;
- validar instance permitida;
- em ambiente de teste, respeitar `JID_PERMITIDO`/allowlist;
- idempotência por `evolution_message_id`.

### 8.2 Tipos de evento P0

Processar no mínimo:

- mensagens da conversa cliente;
- mensagens do grupo de Coordenação por modelo;
- mídia recebida;
- eventos enviados com `fromMe=true` para distinguir backend/manual.

Não é obrigatório processar todos os eventos do Evolution nesta fase.

### 8.3 Persistência de conversa cliente

Para mensagem de cliente:

1. resolver modelo por `evolution_instance_id`;
2. resolver/criar cliente por telefone;
3. resolver/criar conversa `(cliente_id, modelo_id)`;
4. resolver atendimento aberto para `(cliente_id, modelo_id)` se existir;
5. se não existir, criar atendimento `Novo`;
6. inserir `mensagens`;
7. atualizar `conversas.ultima_mensagem_*` via trigger;
8. não chamar agente/IA nesta fase.

### 8.4 Mensagem em atendimento pausado

Mensagens recebidas com `ia_pausada=true`:

- persistir no histórico;
- não criar badge especial;
- não disparar IA;
- não gerar transição automática.

### 8.5 Grupo de Coordenação por modelo

O parser deve reconhecer:

- `IA assume #N`
- `finalizado valor #N`
- `fechado valor #N`
- `perdido motivo #N`

Quote ao card pode dispensar `#N` se o payload Evolution permitir mapear com segurança ao `card_message_id` em `escaladas`.

Se não houver `#N` e não houver quote resolvível:

- comando inválido;
- responder erro curto no grupo;
- registrar `comando_invalido`;
- não alterar estado.

### 8.6 Autoria no grupo

Regra confirmada:

- comando de Fernando: aceitar apenas se remetente/JID for reconhecido como Fernando;
- comando da modelo: aceitar apenas se `fromMe=true` e `evolution_message_id` **não existir** em `envios_evolution`;
- se `evolution_message_id` existir em `envios_evolution`, é outbound do backend e não pode ser interpretado como comando manual;
- se houver dúvida, rejeitar sem alterar estado.

Antes de habilitar comandos da modelo em produção, executar teste documentado com payload real Evolution.

Critérios de teste:

- todo envio do backend gera `envios_evolution`;
- mensagem manual da modelo no grupo chega com `fromMe=true` e `key.id` não registrado;
- mensagem de Fernando chega com remetente/JID distinguível;
- quote ao card traz referência suficiente para mapear `card_message_id`.

### 8.7 `finalizado` sem valor

Regra dura P0:

- `finalizado` sem valor é inválido;
- não fecha atendimento;
- não conclui bloqueio;
- responder erro curto pedindo valor;
- inserir evento `comando_invalido`.

Valor aceito:

- formatos brasileiros comuns: `1000`, `1.000`, `R$ 1.000`, `1k`;
- valor ambíguo exige erro/confirmar via novo comando;
- não adivinhar.

## 9. Porta única de comandos operacionais

Implementar serviço único para comandos sensíveis, por exemplo:

```python
aplicar_comando(origem, autor, atendimento_id, comando, payload)
```

Fontes:

- `painel`;
- `grupo_coordenacao`;
- `pipeline_pix`;
- `cron`;
- futuro `agente`.

Comandos P0:

- `devolver_para_ia`;
- `registrar_fechado`;
- `registrar_perdido`;
- `corrigir_registro`;
- `atualizar_pix`;
- `abrir_handoff` quando necessário;
- `comando_invalido`.

Nenhum outro módulo deve escrever diretamente:

- `ia_pausada`;
- `ia_pausada_motivo`;
- `responsavel_atual`;
- estado de atendimento;
- financeiro;
- agenda vinculada;
- Pix final.

## 10. Pix de deslocamento

### 10.1 Implementação nesta fase

Como foco atual não é agente, o backend deve suportar validação manual pelo painel e preparar worker de pipeline.

O pipeline automático via LLM pode ficar implementado se for simples, mas não deve bloquear entrega do backend operacional.

### 10.2 Gateway de modelos futuro

Decisão arquitetural:

- OpenRouter será gateway padrão para modelos;
- Anthropic SDK deve permanecer possível para chat futuro por causa de prompt caching;
- não hardcodar modelo.

Variáveis previstas:

- `LLM_CHAT_PROVIDER=openrouter|anthropic`
- `LLM_VISION_PROVIDER=openrouter`
- `LLM_AUDIO_PROVIDER=openrouter`
- `OPENROUTER_API_KEY`
- `OPENROUTER_MODEL_CHAT`
- `OPENROUTER_MODEL_VISION_PIX`
- `OPENROUTER_MODEL_AUDIO_TRANSCRIBE`
- `ANTHROPIC_API_KEY`
- `ANTHROPIC_MODEL_CHAT`

Nesta fase, se criar abstração, manter pequena:

- `chat_agent(...)` futuro;
- `vision_pix(...)` futuro;
- `transcribe_audio(...)` futuro.

### 10.3 Critérios de Pix automático quando implementado

Quando o pipeline automático for implementado:

- usar OpenRouter com modelo vision configurável;
- extrair JSON estruturado:
  - `valor_extraido`;
  - `chave_extraida`;
  - `titular_extraido`;
  - `timestamp_extraido`;
  - `confianca`;
  - `motivos`;
- comparar determinísticamente no backend;
- nunca deixar LLM decidir sozinha o status final sem regras determinísticas.

Critérios:

- valor precisa ser exatamente `100.00`;
- chave Pix normalizada precisa bater com `modelos.chave_pix`;
- titular normalizado deve bater claramente com `modelos.titular_chave`;
- timestamp aceito entre 2 horas antes e 10 minutos depois do recebimento da imagem;
- imagem precisa ser plausivelmente comprovante Pix;
- qualquer ausência, divergência ou baixa confiança vira `em_revisao`;
- validação automática nunca altera cadastro da modelo.

## 11. Áudio recebido

Como o modelo STT não foi decidido, não fixar modelo.

Decisão:

- OpenRouter será o gateway;
- modelo de transcrição será configurável por `OPENROUTER_MODEL_AUDIO_TRANSCRIBE`;
- usar `/api/v1/chat/completions` com `input_audio` conforme documentação OpenRouter;
- áudio precisa ser base64;
- formatos aceitos dependem do modelo.

Nesta fase:

- persistir áudio recebido em MinIO;
- inserir `mensagens` com `tipo='audio'`;
- se transcrição ainda não existir, `conteudo` pode ficar vazio ou conter marcador técnico curto;
- worker de transcrição pode ser preparado, mas não deve bloquear a API operacional.

Quando implementado:

- worker baixa áudio do MinIO;
- envia ao OpenRouter com prompt de transcrição literal;
- grava texto em `mensagens.conteudo`;
- em falha, log/Sentry e manter mídia no histórico.

## 12. Mídia e retenção

### 12.1 Mídia recebida do cliente

Bucket MinIO:

- `media`

Prefixo:

- `clientes/{modelo_id}/{conversa_id}/{mensagem_id}/...`

Regras:

- nunca expor URL pública permanente;
- painel pede URL assinada curta ao FastAPI;
- linhas de `mensagens` não são apagadas quando objeto expira.

Retenção:

- comprovantes Pix e fotos de portaria: 90 dias após `Fechado` ou `Perdido`;
- áudios transcritos: 30 dias após transcrição bem-sucedida;
- mídia da modelo aprovada: sem expiração automática.

### 12.2 Worker de limpeza

Rodar diariamente.

Deve:

- localizar mídias vencidas;
- apagar objetos no MinIO;
- registrar log estruturado;
- não deletar linhas de domínio;
- ser idempotente.

## 13. Workers P0

### 13.1 Timeouts determinísticos

Worker periódico.

Regras:

- timeout longo: estados `Novo`, `Triagem`, `Qualificado`, `Aguardando_confirmacao` sem mensagem do cliente há mais de 24h;
- marcar `Perdido`, `motivo_perda='sumiu'`, `fonte_decisao='auto_timeout'`;
- não enviar mensagem ao cliente;
- não afetar `ia_pausada=true`.

Timeout interno curto:

- atendimento interno em `Aguardando_confirmacao`;
- `aviso_saida_em` preenchido;
- sem `foto_portaria_em`;
- 30 minutos após horário combinado;
- marcar `Perdido`, `motivo_perda='sumiu'`, `fonte_decisao='auto_timeout_interno'`;
- cancelar bloqueio vinculado quando permitido.

### 13.2 Confirmado para Em_execucao

Worker/cron:

- atendimento externo em `Confirmado`;
- quando horário previsto chegar;
- atualizar para `Em_execucao`;
- bloqueio vai para `em_atendimento`;
- `fonte_decisao='cron_em_execucao'`.

### 13.3 Envio Evolution

Todo envio deve passar por cliente único que:

- chama Evolution;
- captura `key.id`;
- grava `envios_evolution`;
- aplica idempotência quando houver `dedupe_key`;
- mascara dados sensíveis em logs.

## 14. Realtime

O backend não precisa implementar WebSocket próprio.

Frontend usa Supabase Realtime.

Backend deve garantir que mutações feitas por FastAPI atualizem as tabelas publicadas:

- `atendimentos`;
- `mensagens`;
- `bloqueios`;
- `comprovantes_pix`;
- `eventos`.

## 15. Observabilidade

### 15.1 Endpoints

Implementar:

- `/health`: liveness simples;
- `/ready`: verifica DB, Redis e dependências essenciais;
- `/metrics`: Prometheus.

### 15.2 Logs

Logs JSON em stdout.

Campos quando disponíveis:

- `request_id`;
- `correlation_id`;
- `conversa_id`;
- `atendimento_id`;
- `modelo_id`;
- `turno_id` futuro;
- `job_id`;
- `evolution_message_id`;
- `remote_jid` mascarado.

Nunca logar:

- tokens;
- chave Pix completa;
- comprovante bruto;
- mídia base64;
- telefone completo sem máscara.

### 15.3 Métricas mínimas

- request rate/error/duration por rota;
- jobs executados/falhos/retry por tipo;
- locks Redis adquiridos/expirados/conflitados;
- comandos de grupo válidos/inválidos;
- Pix validado/em revisão/inválido;
- envios Evolution com sucesso/falha;
- erros de webhook;
- timeouts aplicados.

### 15.4 Sentry

Capturar exceções FastAPI e workers.

Não enviar payload bruto sensível sem sanitização.

## 16. Segurança

Obrigatório:

- JWT Supabase validado no backend;
- CORS restrito;
- webhook com segredo;
- allowlist de JID em teste;
- Evolution API key só server-side;
- MinIO sem bucket público;
- URLs assinadas curtas;
- service_role só no backend/workers;
- logs mascarados;
- validação Pydantic em todos os bodies;
- checagem de estado antes de mutações.

## 17. Fora do escopo desta fase

Não implementar agora:

- agente ReAct;
- LangGraph de produção;
- tools de IA;
- IA Admin por áudio;
- classificador automático P1;
- score de cliente;
- importação dos 15 mil contatos;
- remarketing;
- vendedor operando;
- TTS para cliente;
- dashboard avançado;
- auditoria de classificador;
- múltiplas modelos em produção;
- refatorações amplas fora do backend operacional.

O schema/API não deve impedir segunda modelo no futuro, mas P0 opera uma modelo piloto.

## 18. Critérios de aceite

### 18.1 Banco

- `0002_envios_evolution.sql` criado e aplicável;
- RLS/grants corretos na nova tabela;
- índices criados;
- nenhum migration framework introduzido (apenas SQL puro sequencial em `infra/sql/`).

### 18.2 API

- `/health`, `/ready`, `/metrics` existem;
- `/v1` exige JWT válido;
- endpoints P0 implementados;
- erros seguem envelope padrão;
- OpenAPI gerado automaticamente pelo FastAPI sem YAML manual.

### 18.3 Operação

- fechar atendimento exige `valor_final`;
- perder atendimento exige motivo;
- `outro` exige observação;
- `finalizado` sem valor no grupo é inválido;
- mutações sensíveis passam por serviço único;
- `eventos` registra ações operacionais de atendimento.

### 18.4 Evolution

- webhook valida token/instância;
- mensagens são idempotentes por `evolution_message_id`;
- outbound grava `envios_evolution`;
- comando manual da modelo só é aceito se `key.id` não estiver em `envios_evolution`;
- comandos inválidos não alteram estado.

### 18.5 Frontend support

- endpoints retornam dados suficientes para:
  - Painel Geral;
  - Central de Atendimentos;
  - Agenda;
  - CRM;
  - Modelo/FAQ/Mídia;
  - Pix;
  - Dashboard.
- Realtime funciona porque as tabelas certas são atualizadas.

### 18.6 Testes mínimos

Implementar testes automatizados para:

- auth ausente/inválida;
- envelope de erro;
- fechamento sem valor falha;
- fechamento com valor passa;
- perda sem motivo falha;
- `outro` sem observação falha;
- bloqueio sobreposto retorna `409`;
- validar Pix aplica estado correto;
- recusar Pix aplica estado correto;
- `envios_evolution` impede outbound de ser interpretado como comando;
- webhook idempotente não duplica mensagem;
- timeout longo marca `Perdido`;
- `finalizado` sem valor retorna comando inválido.

Testes de integração com Evolution real podem ficar como checklist manual de Fase 1.5, mas o parser deve ter testes unitários com payloads fixture.

## 19. Ordem recomendada de implementação

1. Configurar core: settings, DB pool, auth JWT, erros, logging.
2. Criar `0002_envios_evolution.sql`.
3. Implementar repositórios base e serviços de `atendimentos`, `agenda`, `conversas/crm`.
4. Implementar REST `/v1` para painel.
5. Implementar MinIO URLs assinadas e mídia da modelo.
6. Implementar Evolution client + `envios_evolution`.
7. Implementar webhook básico e persistência de mensagens.
8. Implementar parser de comandos do grupo.
9. Implementar Pix manual pelo painel.
10. Implementar workers de timeout e limpeza.
11. Implementar métricas, Sentry e testes.
12. Só depois preparar provider abstraction LLM, sem bloquear entrega operacional.

