---
register: product
name: Elite Baby
description: >-
  Central inteligente de atendimento da agência Elite Baby. Uma IA por modelo
  opera o WhatsApp de cada profissional, conduz a conversa do cliente do primeiro
  "oi" até a confirmação, e pausa para handoff quando há decisão sensível
  (Fernando) ou ação física (modelo). O painel é a sala de controle onde a
  operação é supervisionada, decidida e medida.
---

# Elite Baby

> **Antes de tudo:** o vocabulário do domínio é fechado e vive em `@CONTEXT.md`.
> Use os termos exatos (Conversa cliente, Handoff, Devolução para IA, Registro de
> resultado, Pix de deslocamento, Aviso de saída, Foto de portaria, Coordenação
> por modelo). Este documento descreve **o produto**; `CONTEXT.md` descreve **a
> língua**; `DESIGN.md` descreve **a aparência**.

## O que é o produto

A **Elite Baby** é uma agência premium de acompanhantes de luxo no Rio de Janeiro,
dez anos de mercado, modelos na faixa de R$1.000/h, clientela classe A/B+. Hoje a
operação é artesanal e frágil: 4 a 15 telefones físicos na alta temporada,
**vendedores humanos respondendo no WhatsApp se passando pela modelo**, todo o
conhecimento concentrado na cabeça de Fernando, 15.000+ contatos sem histórico
estruturado, zero métrica confiável e banimentos recorrentes de número.

O produto digitaliza essa operação sem perder o padrão premium. Uma **IA dedicada
por modelo** opera o WhatsApp de cada profissional, conduz a conversa do cliente —
triagem, qualificação, agenda, Pix, confirmação — **imitando a persona da modelo**,
e registra tudo como dado estruturado. Quando aparece uma decisão sensível ou uma
ação que só a modelo pode tomar, a IA **pausa e escala** (Handoff): para Fernando,
quando é decisão; para a modelo, via grupo de Coordenação, quando é execução. O
painel é onde Fernando supervisiona a IA, resolve os handoffs, valida Pix, registra
resultados e lê a operação em números.

**Fluxo de ponta a ponta:** cliente chega pelo canal orgânico → escreve no WhatsApp
da modelo → a IA atende como se fosse ela → coleta dados, consulta agenda e FAQ,
cota o programa → pede o Pix de deslocamento → confirma o encontro → a modelo
executa → o resultado (`Fechado`/`Perdido`) é registrado → vira métrica no painel.

**Regra de ouro do produto:** *na dúvida, escala*. Improviso é proibido. Uma palavra
errada perde um cliente premium e não há segunda chance — então a IA conduz só o que
é previsível e devolve para o humano tudo o que não é.

## Estado atual

P0 (MVP). **Uma modelo piloto**, **Fernando no loop como decisor único**. O objetivo
do P0 não é escalar — é provar que a operação roda com IA mantendo a qualidade
premium e **sem causar banimento de WhatsApp**, e que o modelo é replicável para a
próxima modelo.

## Usuários

### Quem usa o painel (tem login)

- **Fernando** — operador principal, dono, decisor único no P0. Passa horas seguidas
  no painel, em desktop, alternando entre atendimentos, agenda, CRM, modelos, Pix,
  dashboard e tarefas. Resolve handoffs, valida Pix, registra `Fechado`/`Perdido`,
  corrige registros, gerencia a base de conhecimento da modelo. Erro operacional tem
  custo real: cliente perdido, modelo sem aviso, número banido.
- **Sócia** — **mesma permissão de Fernando** (sem RBAC; ADR 0012). A operação real
  tem dois operadores idênticos.
- **`vendedor_read_only`** — login somente-leitura, **planejado para o P1** (não
  existe no P0).

### Atores no fluxo (sem login no P0)

- **IA por modelo** — opera o número da modelo e conduz a conversa. **Persona, voz e
  FAQ são gerais e compartilhadas** entre todas as modelos; só "as coisas dela"
  variam (identidade óbvia, programas/preços, agenda, fetiches). O cliente nunca sabe
  que fala com uma IA.
- **Modelo** — profissional cadastrada. Tem agenda própria, recebe cards no grupo de
  **Coordenação por modelo**, assume a conversa no mesmo número durante o handoff e
  registra `finalizado/fechado/perdido` respondendo ao card. Não tem identidade
  separada no grupo: as mensagens dela entram como `fromMe` do número operado pela IA.
- **Cliente** — homem premium; interage com a IA acreditando falar com a modelo.
- **Vendedor** — humano que **hoje** responde o WhatsApp se passando pela modelo; é o
  "assento" que a IA vai assumindo aos poucos. Entidade de domínio, **não login**
  (ADR 0012). Recebe **Comissão de vendedor** por nível (iniciante/intermediário/
  avançado, ref. 4/5/6%). Nunca é exposto à IA. Onde a IA conduz, não há vendedor.
- **IA Admin** — comandos internos de Fernando por áudio/texto. **P1**, não existe no
  P0; no P0 as decisões sensíveis chegam pelo painel e/ou pela Coordenação por modelo.

## O agente de IA — o coração do produto

A IA é um agente ReAct (LangGraph sobre Claude), chamado **uma vez por turno** pelo
Coordenador de Turno, com teto de iterações por turno. Ela conduz o previsível e
escala o resto.

**O que faz:** triagem, identificação de intenção (atendimento interno — cliente vai
à modelo — ou externo — modelo vai ao cliente), coleta dos dados mínimos da conversa,
qualificação, consulta de agenda/cliente/FAQ/Pix/mídia, extração estruturada para o
CRM, pedido do Pix de deslocamento, envio de **Mídia exclusiva** pré-aprovada,
**Desconto de fechamento** até o **Piso de desconto** (ADR 0004) e cotação de
**Fetiches** (ADR 0014).

**Onde pausa (Handoff, `ia_pausada=true`):**
- **Para Fernando** — quando a IA `escala`: Pix em revisão, pedido fora da política
  (desconto abaixo do piso, serviço fora da FAQ), conflito de agenda, dúvida não
  coberta, exaustão de iterações, recusa do modelo.
- **Para a modelo (handoff implícito)** — Pix de deslocamento validado (externo →
  `Confirmado`) ou **Foto de portaria** recebida (interno → `Em_execucao`).

A IA só retoma por **Devolução para IA** explícita (nunca automática).

**Invariante crítico — isolamento por par `(cliente, modelo)`:** a IA da modelo A
nunca enxerga, cita ou se apoia em dados do mesmo cliente com a modelo B. A barreira é
a camada de dados, não a boa vontade do modelo. Persona/voz/FAQ são compartilhadas; o
**dado do cliente** (histórico, recorrência, observações) é isolado por par.

**O que a IA nunca faz:** criar atendimento (é determinístico, do coordenador),
decidir risco, negociar livremente, confirmar saída sem Pix validado, verbalizar
serviços explícitos, inventar dados, ou rodar vision sobre imagem do cliente (exceto o
pipeline dedicado de OCR do Pix).

## O painel — capacidades

Todas as telas são de Fernando/sócia (desktop, dark-only; identidade visual em
`DESIGN.md`).

- **Painel Geral** — visão do dia. Cards do que precisa de decisão *agora*, separados
  por motivo de pausa (Pix em revisão, handoff da IA, modelo em atendimento). Métricas
  do dia, agenda do dia, Pix pendentes, fechamentos e perdas, atalhos.
- **Central de Atendimentos** — lista e detalhe dos ciclos comerciais. Filtros por
  estado/tipo/urgência/pausa; timeline da conversa (read-only); mídia recebida;
  eventos do atendimento; ações **Devolver para IA**, **Fechar** (+ valor final),
  **Perder** (+ motivo), **Corrigir registro**.
- **Agenda Operacional** — calendário de bloqueios (dia/semana/mês); criar/editar/
  cancelar bloqueio manual; constraint do Postgres impede sobreposição; integra com a
  **Disponibilidade** da modelo ("Período de trabalho", ADR 0005).
- **CRM** — histórico por **conversa (par cliente-modelo)**, não por cliente global.
  Recorrência, observações e último motivo de perda por par; edição inline.
- **Modelos e Base de Conhecimento** — perfil (WhatsApp + pareamento QR via Evolution,
  valor, repasse, chave Pix), dados para o prompt (idade, idiomas, localização, tipos
  aceitos), FAQ (global + específica), mídia (MinIO), ficha cadastral PII sensível
  (ADR 0007) e fetiches/serviços (ADR 0014).
- **Pix e Comprovantes** — fila de Pix em revisão; dados extraídos por OCR/vision
  confrontados com o cadastro; **Validar** / **Recusar**.
- **Dashboard** — volume por estado, taxa de conversão, valor bruto fechado, perdas
  por motivo, profissionais mais procuradas, Pix em revisão, escaladas por motivo, e o
  bloco financeiro/ROI (ADRs 0011/0012/0013).
- **Mapa de Clientes** — pins de clientes pela geo do atendimento externo mais recente,
  com camada de modelos sobreposta (oferta × demanda). Cross-modelo, painel-only
  (ADRs 0008/0010).
- **Módulo Financeiro** — receita projetada a partir dos atendimentos `Fechado`,
  repasses em pagamentos livres, saldo por modelo (ADR 0011).
- **Tarefas** — CRUD enxuto estilo ClickUp (status/prioridade/prazo/responsável);
  sem RBAC/notificação/comentários (ADR 0017).

## Escopo

### Dentro do P0
Modelo piloto pareada via QR; agenda com bloqueio por IA e manual; máquina de estados
enxuta (`Novo → Triagem → Qualificado → Aguardando_confirmacao → Confirmado →
Em_execucao → Fechado/Perdido`); IA de triagem/intenção/disponibilidade/humanização/
escalada; áudio recebido transcrito (resposta só em texto); extração estruturada para
CRM; ficha de atendimento canônica; motivo de perda padronizado; Pix de deslocamento
de valor fixo com OCR/vision; confirmação interna (Aviso de saída + Foto de portaria,
sem vision); grupo de Coordenação por modelo; registro `Fechado`/`Perdido` com valor
final; biblioteca mínima de mídia; dashboard simples.

### P1 (depois da validação)
Classificador automático de estado; tags de cliente; IA Admin por áudio; auditoria por
fonte de decisão; fila de prioridade; ranking de mídia por contexto; vendedor
read-only; Reengajamento ligado; view-once real na mídia.

### Fora de escopo
Importação dos 15k contatos; remarketing em massa; operar 10–15 modelos em escala;
dashboard avançado; plataforma de turismo de luxo; mídia generativa; score "fecha vs
não fecha"; aquecimento de número reserva; Pix antecipado do atendimento interno;
unificação automática de cliente recorrente (sempre manual); TTS para o cliente.

## Métricas de sucesso

A KPI central é a **taxa de conversão** = `Fechados / (Fechados + Perdidos)`. Ao redor
dela: volume de atendimentos por estado, valor bruto fechado, **perdas por motivo**
(para aprender por que não converte), profissionais mais procuradas, Pix em revisão
pendentes e escaladas por motivo. Sinais de qualificação (informa horário/local,
aceita o valor, envia Pix, responde objetivamente) alimentam o dashboard.

Objetivos qualitativos do MVP: reduzir o tempo de resposta inicial; padronizar o tom;
registrar dados que hoje se perdem; evitar conflito de agenda; provar replicabilidade
para a próxima modelo; e, acima de tudo, **não causar banimento de WhatsApp**.

Prova de ROI (fase posterior): "a IA custou R$X e evitou R$Y de comissão de vendedor
neste mês", por modelo — `custo_IA_por_fechado` contra `comissao_evitada`.

## Tom do produto

Direto, denso, profissional. Sem decoração. Cada pixel serve a uma função
operacional. A identidade preto + dourado da Elite Baby está presente, mas nunca
domina a função.

## Anti-referências

- Painéis SaaS genéricos com gradientes coloridos.
- Dashboards com hero-metrics e cards idênticos em grade.
- Interfaces "consumer" com muito espaço em branco.
- Qualquer coisa que pareça template de admin.
- Replicar no painel a estética sensual/adulta do canal orgânico — são públicos
  diferentes: o canal vende perfis, o painel coordena operação.

## Princípios estratégicos

- **Densidade primeiro** — Fernando precisa ver muito em pouco espaço.
- **Ação imediata** — o que precisa de decisão agora salta aos olhos; o elemento mais
  brilhante de qualquer tela é a próxima ação.
- **Estado antes de conteúdo** — cada atendimento, Pix ou conversa carrega um estado
  finito; mostre o estado antes do nome.
- **Na dúvida, escala** — a IA conduz o previsível e devolve o resto para o humano. A
  qualidade premium vale mais que a automação total.
- **Isolamento por par é sagrado** — nunca vaze dado de cliente entre modelos.
- **Zero ambiguidade** — status, nomes e horários são inequívocos.
- **Vocabulário fechado** — use sempre os termos de `CONTEXT.md` na UI e no código.
