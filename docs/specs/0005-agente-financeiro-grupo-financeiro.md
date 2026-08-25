# Agente financeiro no Grupo financeiro das modelos

> Spec local (sem issue). Vocabulário: `docs/dominio/grupo-financeiro.md`. Decisão estrutural:
> ADR-0043. Contextualização de negócio + reaproveitamento do myEYE: vault DevContext
> (`barra/agente-financeiro-grupo-modelos-contexto`, projeto EliteBaby).

## Problem Statement

A operação Elite Baby roda o dinheiro em **Grupos financeiros** de WhatsApp, um por modelo
(modelo + gestores). Ali os gestores fazem secretaria manual: anunciam cada venda em texto livre
("Atendimento no nosso local / Cliente Gabriel / Perfil bianca/yasmin / 700 1h"), cobram a forma
de pagamento dias depois ("foi pix ou din?"), fazem o fechamento de cabeça ("confere: 600 pix,
600 pix / ficou com você"), pedem transferência e conferem comprovante no olho. Nada disso entra
em sistema nenhum.

Ao mesmo tempo, a IA de atendimento do Barra ainda não foi para produção — então `atendimentos`
está vazio e o Módulo Financeiro não tem receita real. A operação gera dado todo dia e o sistema
não o vê; os gestores gastam horas num trabalho que é exatamente o tipo de coisa que vendemos.

## Solution

Um **Agente financeiro**: uma IA que participa de cada Grupo financeiro com o número ProceX e
assume a secretaria do gestor. Ele ingere em silêncio o que os humanos já postam (texto e áudio),
registra cada venda como **Venda registrada** (entidade própria — ADR-0043) emitindo um recibo
curto corrigível, pergunta **só** o que falta para o mínimo do registro, cobra pendências de
forma consolidada numa rotina diária (o "foi pix ou din?" deixa de ser trabalho humano), lê
comprovantes Pix por OCR, distingue transferência de fechamento de pagamento de **Cobrança da
agência**, e mantém o **Fechamento** — a conferência contínua de vendido × comprovado por modelo,
disponível também sob comando. O Módulo Financeiro passa a somar duas fontes de receita e o
sistema começa a ser populado com a operação real antes de a IA de venda estrear.

## User Stories

1. Como gestora, quero postar a venda no grupo do jeito que já escrevo hoje (texto livre, sem
   formato), para que ela seja registrada no sistema sem eu mudar meu processo.
2. Como gestora, quero que o agente pergunte apenas o que falta para o mínimo do registro
   (modelo + valor + data), para não ser interrogada sobre campo opcional.
3. Como gestora, quero receber um recibo curto quando algo for lançado ("✅ Registrei: …"), para
   conferir de relance e corrigir respondendo a mensagem se algo estiver errado.
4. Como gestora, quero que apagar a mensagem do anúncio anule o registro (e o repost caia no
   dedup), porque apagar-e-repostar é como a gente corrige hoje.
5. Como gestora, quero que o agente cobre a forma de pagamento pendente por mim (consolidado, na
   manhã seguinte), para eu nunca mais precisar perguntar "foi pix ou din?".
6. Como gestora, quero pedir o fechamento sob comando a qualquer momento, para ter na hora a
   foto do que está aberto.
7. Como gestora, quero o fechamento em três colunas — vendido, comprovado (pix), em espécie —
   para saber exatamente o que ainda falta comprovar sem fazer conta de cabeça.
8. Como gestora, quero que uma venda com duas modelos ("1300 cada uma") vire uma linha por
   modelo, cada uma no valor dela, para o número de cada uma ficar certo.
9. Como gestora, quero que o mesmo anúncio postado no grupo da outra modelo não duplique o
   registro (dedup cross-grupo), para o total não inflar.
10. Como gestora, quero que uma Cobrança da agência postada no grupo (ex.: anúncio 3RJ) vire
    pendência rastreada até o comprovante do pagamento chegar, para eu não precisar ficar
    lembrando a modelo.
11. Como gestora, quero ser avisada quando um comprovante apontar para uma chave Pix fora da
    lista conhecida da casa, para pegar erro ou golpe antes de virar prejuízo.
12. Como modelo, quero responder por áudio e ser entendida, porque é assim que eu uso o WhatsApp.
13. Como modelo, quero não ser metralhada de perguntas em tempo real — uma cobrança consolidada
    por dia basta — para o grupo continuar habitável.
14. Como modelo, quero que o comprovante que eu mando seja lido e abatido sozinho do que devo
    comprovar, sem ninguém precisar conferir no olho.
15. Como modelo, quero que venda paga em dinheiro não gere cobrança de comprovante, porque
    dinheiro em espécie não tem comprovante — o acerto é nosso, fora do sistema.
16. Como operador (Fernando), quero ver a receita real da operação no Módulo Financeiro somando
    as duas fontes (atendimentos fechados + Vendas registradas), para o painel refletir o
    negócio de verdade desde já.
17. Como operador, quero ver a lista de Vendas registradas com suas pendências e flags de
    divergência no painel, para auditar sem entrar em cada grupo.
18. Como operador, quero que divergência nunca trave a operação — vira pergunta no grupo e flag
    no painel — para o agente nunca ser um gargalo.
19. Como operador, quero que dados operacionais ditos no grupo (torre/apto, chave Pix da modelo)
    atualizem os Dados cadastrais dela de forma oportunista e calada (painel-only), para o
    cadastro se manter vivo sem interrogatório.
20. Como operador, quero que um Nome de anúncio desconhecido gere uma pergunta no grupo ("'fran
    loira' é quem?") e a resposta do gestor vire cadastro, para o resolver continuar
    closed-world sem eu precisar cadastrar apelido por apelido.
21. Como desenvolvedor, quero uma porta única de entrada do módulo (espelho do
    `processar_turno`), chamada pelo webhook, pelos testes e pelo futuro replay, para o
    comportamento testado ser o comportamento de produção (lição do harness fiel).
22. Como desenvolvedor, quero que mensagem de grupo não cadastrado seja ignorada com log, para o
    número compartilhado (myEYE + grupos financeiros) nunca responder no lugar errado.
23. Como desenvolvedor, quero o vínculo grupo↔modelo como cadastro explícito (closed-world),
    para o roteamento por JID ser determinístico.
24. Como desenvolvedor, quero que mensagem social (sticker, conversa, mídia sem dado) seja
    ignorada sem chamada cara, para o agente ser silencioso e barato no grupo vivo.

## Implementation Decisions

- **Módulo novo dentro do Barra** (mesma API, mesmo worker), não um produto separado. A entidade
  central é a **Venda registrada** (ADR-0043): tabela própria com modelo, valor, data, forma de
  pagamento opcional-até-conciliar, cliente como texto livre, local/duração opcionais e a
  mensagem-fonte como origem. **Nenhum `Atendimento` nem `Cliente` é fabricado.**
- **Tabelas de apoio**: vínculo grupo↔modelo (JID → modelo, closed-world), nomes de anúncio por
  modelo, Cobranças da agência, comprovantes lidos (OCR + classificação), chaves Pix conhecidas
  da casa.
- **Seam único** (decisão validada com o dev): uma porta de entrada estilo `processar_turno` —
  mensagem do grupo entra, efeitos (registros, pendências, respostas) saem. Webhook, testes e o
  futuro protótipo de replay chamam a mesma porta. A rotina diária de fechamento/cobrança é a
  exceção natural (nasce de relógio, não de mensagem): vive como worker de cron no padrão dos
  já existentes, mas o que ela decide/posta reusa as mesmas funções de domínio da porta.
- **Roteamento**: o número ProceX é compartilhado com o myEYE; o webhook roteia por JID de grupo
  contra o cadastro grupo↔modelo. Grupo não cadastrado = ignorar com log. Os gotchas vivos do
  EvoGo nessa rota (reconexão zera webhook, evento `MESSAGE` basta, entrega duplicada do router,
  `mediaUrl` para bytes) estão documentados no vault do myEYE e valem aqui.
- **Ingestão**: debounce/coalescência de burst reaproveitando o desenho do agente de venda;
  áudio via o STT já existente; imagem de comprovante via o pipeline de vision já existente
  (mesmo trilho do comprovante de Pix do agente de venda). Mensagem social é descartada barato
  (classificação antes de qualquer extração cara).
- **Registro direto com recibo** (sem confirmação em 2 tempos): quem afirmou o fato é o humano
  do grupo; o recibo é a porta de correção (quote). Deleção da mensagem-fonte anula o registro
  quando o evento chegar; dedup cross-grupo por conteúdo (data + valor + modelos + cliente),
  no espírito do dedup de NF do myEYE.
- **Resolver de Nome de anúncio**: closed-world sobre o cadastro (nome verdadeiro + nomes de
  anúncio); "X/Y" é anúncio/verdadeiro da MESMA mulher; desconhecido → pergunta no grupo e a
  resposta do gestor grava o nome novo. Nunca resolver por similaridade/palpite.
- **Fechamento**: saldo corrente contínuo por modelo (sem períodos estanques). Comprovante
  classificado como fechamento abate as vendas pix abertas mais antigas; comprovante de
  Cobrança da agência abate a cobrança, nunca as vendas. Venda em dinheiro conta no vendido,
  marcada "em espécie", fora da expectativa de comprovante. **Repasse/split ficam fora do
  sistema** (decisão do dono do produto). Gatilhos: comando no grupo + rotina diária de manhã
  (cobra pendências consolidadas e posta o saldo quando há movimento).
- **Pendência** nunca trava registro nem extrato; tipos: forma de pagamento não dita,
  comprovante não enviado, cobrança não paga, nome de anúncio desconhecido.
- **Painel P0 mínimo**: receita do Módulo Financeiro somando as duas fontes + lista de Vendas
  registradas com pendências e flags. Sem tela de extrato rica.
- **LLM e observabilidade**: mesmo provider e mesmo tracing (Langfuse) do agente de venda; o
  agente financeiro é um grafo próprio, muito mais simples (ingestão/extração, sem persona de
  venda, sem máquina de estados de atendimento).

## Testing Decisions

- **Bom teste aqui = comportamento pela porta única**: entra a mensagem crua do grupo (na grafia
  real do export da Yasmin), saem os efeitos observáveis — linhas de Venda registrada,
  pendências, resposta (ou silêncio) do agente. Não testar nós do grafo isoladamente: foi o
  desenho que induziu 4 bugs falsos no agente de venda (lição do harness fiel).
- **Fixtures da realidade**: os casos de teste saem do `_chat.txt` real (venda simples, venda
  com duas modelos "cada uma", "foi pix ou din?" respondido dias depois, cobrança 3RJ,
  comprovantes Bradesco do zip para o OCR, mensagem apagada + repost, conversa social a
  ignorar).
- **Prior art**: testes `needs_db` com `TEST_DATABASE_URL` + rollback (padrão da casa); FakeConn
  para o unitário; o cron de fechamento testado como os workers de relógio existentes
  (timeouts/lembretes); dedup e idempotência testados como no comando de grupo do agente de
  venda.
- **Módulos testados**: a porta única (o grosso), o resolver de nomes (closed-world + pergunta),
  o classificador de comprovante (fechamento × cobrança × chave desconhecida), o motor de
  fechamento (três colunas, abate FIFO), o roteamento por JID (grupo não cadastrado ignorado).
- **O protótipo de conversa (replay do chat completo da Yasmin) fica para quando o agente
  existir e executar de verdade** — decisão do dev; esta spec cobre os testes de construção, o
  replay é a validação de produto por cima da mesma porta.

## Out of Scope

- **Repasse/split modelo↔agência** — o sistema garante que os números batem, não distribui
  dinheiro (decisão do dono do produto).
- **Protótipo de conversa/replay** — etapa de validação posterior, sobre o agente pronto.
- **Criação de `Cliente` ou `Atendimento`** a partir do grupo (ADR-0043); a precedência entre as
  duas fontes de receita quando a IA de venda entrar em produção é decisão futura própria.
- **Tela rica de extrato por modelo no painel** — P0 é lista + flags.
- **Instância Evolution dedicada** — P0 usa o número ProceX compartilhado; dedicar instância é
  evolução operacional, não requisito.
- **Interpretar comandos operacionais do agente de venda** (cards, `IA assume`, etc.) — outro
  grupo, outro módulo (Coordenação por modelo).
- **Tasks no DevContext** para este módulo (decisão explícita do dev).

## Further Notes

- Ordem de leitura para quem pega isso do zero: `docs/dominio/grupo-financeiro.md` (vocabulário)
  → ADR-0043 (por que a entidade é própria) → vault `barra/agente-financeiro-grupo-modelos-contexto`
  (contexto de negócio + gotchas de infra herdados do myEYE).
- O comportamento do agente se baseia **100% nas mensagens reais do Grupo financeiro** (export
  da Yasmin na raiz do repo); o myEYE foi referência de funcionamento (rascunho → pergunta
  mínima → recibo), não de fluxo.
- Risco a observar no piloto: venda casada anunciada nos dois grupos ou só num (o export cobre
  um grupo só; o dedup cobre os dois mundos).
