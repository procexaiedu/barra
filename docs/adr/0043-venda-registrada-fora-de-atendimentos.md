---
data: 2026-08-13
status: aceito
relaciona: ADR-0011 (Módulo Financeiro — receita como projeção de atendimentos), CONTEXT.md (Cliente, Atendimento)
---

# ADR-0043 — Venda registrada é entidade própria; receita passa a ter duas fontes

## Contexto

A IA de atendimento ainda não foi para produção, então `atendimentos` não está sendo populado
pela operação real. Enquanto isso, a operação Elite Baby roda num **Grupo financeiro** de
WhatsApp por modelo (modelo + gestores), onde as vendas realizadas são anunciadas em texto livre
("Atendimento no nosso local / Cliente Gabriel / Perfil bianca/yasmin / 700 1h"), a forma de
pagamento é cobrada dias depois ("foi pix ou din?") e o fechamento é feito de cabeça pelo gestor.

Nasce o **Agente financeiro** (ver `docs/dominio/grupo-financeiro.md`): uma IA ingestora nesses
grupos que registra as vendas no sistema, cobra o que falta e faz a conferência — tirando os
gestores do financeiro e **populando o sistema com dados reais** antes de a IA de venda entrar.

O destino natural seria `atendimentos` — receita do Módulo Financeiro é, por ADR-0011, projeção
sobre atendimentos `Fechado`. Mas a venda dita no grupo não cabe lá:

- `atendimentos` exige `cliente_id` e `conversa_id` NOT NULL, e **Cliente = telefone E.164**
  (invariante do CONTEXT.md). A venda do grupo tem cliente por **nome** ("Cliente Igor"), sem
  telefone — não há Conversa cliente, não há par.
- O Atendimento carrega uma máquina de estados, `#N`, bloqueio de agenda, cards e timeouts.
  Uma venda já realizada, anunciada após o fato, não percorreu nada disso — fabricar um
  `Fechado` sintético dispararia invariantes e relatórios pensados para o ciclo comercial.
- Venda com **duas modelos** ("1300 cada uma") é proibida por construção no Atendimento
  (uma modelo por atendimento).

## Decisão

**1. Venda registrada é entidade própria** (tabela nova), fora de `atendimentos`: modelo, valor,
data, forma de pagamento (opcional até conciliar), cliente como **texto livre**, local/duração
opcionais, mensagem-fonte do grupo como origem. Mínimo para existir: **modelo + valor + data**.

**2. Nenhum Atendimento nem Cliente é fabricado.** O invariante "Cliente = telefone E.164" fica
intocado; se o telefone um dia aparecer, liga-se a posteriori.

**3. Venda com N modelos vira N linhas**, uma por modelo no valor dela, com dedup cross-grupo
(o mesmo anúncio pode aparecer no grupo de cada participante).

**4. A receita do Módulo Financeiro passa a somar DUAS fontes**: a projeção de atendimentos
`Fechado` (ADR-0011, hoje vazia em prod) e as Vendas registradas. Quando a IA de venda entrar em
produção, as fontes coexistem — o que ela fecha nasce como Atendimento; o que a operação anuncia
no grupo continua nascendo como Venda registrada.

## Alternativas rejeitadas

- **Fabricar Atendimento `Fechado` com cliente stub.** Exigiria relaxar NOT NULL de
  cliente/conversa ou criar clientes-fantasma sem telefone, corrompendo Mapa de clientes,
  Conversa cliente e a semântica do `#N`; e duas modelos numa venda quebraria o invariante
  estrutural. O custo de poluir o núcleo do domínio para reaproveitar uma tabela não paga.
- **Lançamento genérico crédito/débito no Módulo Financeiro** (estender `financeiro_despesas`).
  Perderia a semântica de venda (modelo, cliente, duração, local) que é justamente o dado que se
  quer popular; e `financeiro_despesas` é despesa da agência, outro conceito.

## Consequências

- Dashboard/receita precisam ler as duas fontes (hoje leem só a projeção de atendimentos).
- Existe um futuro em que a mesma venda real poderia entrar pelas duas portas (IA de venda fecha
  o atendimento E o gestor anuncia no grupo). Não é o mundo de hoje (a IA de venda não está em
  produção); quando for, a regra de precedência/dedup entre fontes precisa de decisão própria.
- A Venda registrada é a base do Fechamento (conferência vendido × comprovado) — repasse e split
  seguem fora do sistema, por decisão do dono do produto.
