# Promoção Triagem → Qualificado por evidência, não por julgamento

Status: ready-for-agent
Depends on: .scratch/extracao-proveniencia-horario/spec.md

## Problem Statement

A transição `Triagem → Qualificado` exige `intencao == 'agendamento'`. Esse é o campo mais subjetivo do snapshot, e quem o preenche é o extrator barato — que erra sistematicamente para baixo.

Em produção, de 44 Atendimentos:

- **9** têm o cliente com aceite de valor marcado e a intenção **abaixo** de agendamento;
- **4** têm horário e tipo do encontro preenchidos e a intenção abaixo;
- apenas **4** têm `intencao = 'agendamento'`.

Ou seja: mais Atendimentos têm o cliente aceitando o preço do que têm intenção de agendamento gravada.

O caso #34 é o retrato: o cliente perguntou o preço, ouviu "400 1h no meu local", respondeu "Melhor presencial né 😍", combinou 18h e disse "Perfeito, vou te avisando então". Tipo `interno`, horário `18:00`, aceite marcado — e o Atendimento **ficou em Triagem**, porque a intenção permaneceu `cotacao`.

Ficar em `Triagem` não é só rótulo: o ponto de encontro da modelo só entra no contexto a partir de `Qualificado`. O Atendimento #27 mostra o custo — o cliente perguntou "Onde você fica?" e a IA, sem o endereço no contexto, respondeu **"To no hotel no centro de campinas, no cambuí"**. O gate estrutural não impediu o vazamento; trocou dado cadastrado por alucinação.

Existe hoje um remendo — um piso de intenção que cobre **um único** padrão de correferência ("seria hoje?" + "sim"). Os outros oito casos passam reto.

## Solution

Tratar `intencao` como campo **derivado de evidência**, não julgado. É o mesmo padrão que o domínio já aplica ao espelhar o sinal de informação de horário a partir do horário gravado: quando existe um fato estruturado, ele manda no sinal.

Regra: **horário evidenciado ⇒ intenção ≥ agendamento**.

A derivação usa horário evidenciado, e não aceite de valor, porque a auditoria mostrou que o aceite é ruidoso demais para gatear a FSM — 1 verdadeiro em 10 no corpus. Trocar um julgamento por outro não resolveria; o horário com evidência conversacional é fato verificável (ver a spec de proveniência, da qual esta depende).

A derivação mora no serviço de atendimentos, onde a FSM vive, e generaliza o piso pontual que hoje existe no nó de extração.

## User Stories

1. Como modelo, quero que um cliente que já combinou horário comigo apareça como Qualificado, para eu ver no painel quem está de fato marcando.
2. Como modelo, quero que o slot seja reservado quando o encontro está combinado, para eu não perder o horário para outro cliente.
3. Como cliente que combinou horário, quero que a IA saiba me dizer onde é o encontro, para eu conseguir me organizar.
4. Como cliente, quero que a IA me passe o endereço cadastrado e não um bairro inventado, para eu chegar no lugar certo.
5. Como cliente que só está perguntando preço, quero que a IA não trate a conversa como marcada, para não me sentir pressionado.
6. Como Fernando, quero que o funil no painel reflita a realidade das conversas, para medir conversão com dado confiável.
7. Como Fernando, quero que a qualificação não dependa de o extrator "sentir" a intenção, para o funil não travar por variação de julgamento do modelo.
8. Como Fernando, quero que a promoção só ocorra com evidência conversacional, para não ver Atendimento qualificado por palpite do sistema.
9. Como IA, quero receber o ponto de encontro assim que o encontro está sendo combinado, para responder "onde é?" com o dado cadastrado.
10. Como IA, quero que a intenção registrada acompanhe o que já foi combinado, para o belief não me mandar cobrar algo que o cliente já resolveu.
11. Como desenvolvedor, quero a derivação junto da FSM e não como remendo no nó de extração, para haver uma fonte única da regra de transição.
12. Como desenvolvedor, quero que a derivação seja consequência do horário evidenciado, para não haver caminho de promoção sem evidência.
13. Como desenvolvedor, quero que o belief-state continue derivando dos mesmos predicados da FSM, para o que a IA lê e o que o sistema faz nunca divergirem.
14. Como desenvolvedor, quero regressão sobre os Atendimentos reais, para provar que #34/#24/#35 promovem e #25/#19 não.

## Implementation Decisions

**A derivação vive no serviço de atendimentos**, aplicada sobre o payload antes da montagem do upsert, ao lado da derivação já existente de sinais de qualificação. O piso de intenção pontual que hoje mora no nó `extrair` é absorvido por ela — o caso da sondagem aceita passa a ser apenas mais uma fonte de evidência de horário, não uma regra própria.

**Predicado:** horário desejado presente **e** marcado como evidenciado ⇒ intenção sobe para `agendamento`. A monotonicidade da intenção já existente (o extrator não rebaixa `agendamento`) é preservada; o canal de desqualificação continua sendo a retratação explícita.

**As pré-condições da FSM não mudam.** `Triagem → Qualificado` continua exigindo intenção de agendamento e tipo do encontro; `Qualificado → Aguardando_confirmacao` continua exigindo horário e tipo. O que muda é como a intenção chega lá. Manter a tabela de pré-condições intacta preserva a fonte única entre FSM e belief-state.

**Cascata aceita e esperada.** Com a iteração multi-hop já existente, um turno pode percorrer `Triagem → Qualificado → Aguardando_confirmacao` de uma vez, criando o bloqueio prévio no mesmo turno. Não é comportamento novo — é o que já ocorre quando o extrator acerta a intenção —, só mais frequente.

**Efeitos que precisam ser assumidos conscientemente:**

- Atendimentos **externos** promovidos passam a disparar a solicitação determinística de Pix de deslocamento mais cedo do que hoje. É o comportamento correto, mas é dinheiro pedido antes.
- Com o piloto ligado, o cancelamento automático do externo dispara dez minutos após a entrada em `Aguardando_confirmacao`.
- O guard de cotação ausente continua barrando a reserva quando o preço nunca foi dito, o que limita a cascata a negociações que já cotaram.

**Nenhuma mudança no gate do ponto de encontro** nesta spec: ele continua liberando a partir de `Qualificado`. A consequência de promover corretamente é que ele passa a liberar quando deve.

## Testing Decisions

Bons testes afirmam **em que estado o Atendimento fica** e **o que a IA passa a ter no contexto** — não como a intenção foi derivada.

**Seam primária: o harness fiel**, com as conversas reais semeadas, grafo real com chat fake roteirizado e clock injection.

Casos obrigatórios:

- **#34** — combina 18h com tipo interno: termina em `Qualificado` (ou adiante), com o ponto de encontro disponível no contexto do turno seguinte.
- **#24** — "Umas 16 horas": promove.
- **#35** — sondagem de imediatismo aceita: promove, apesar de o número ter vindo do fallback.
- **#25** — horário sem evidência: **permanece em Triagem**, com o horário gravado e não evidenciado.
- **#19** — sem horário e com recuo: permanece em Triagem.
- **cascata externa** — Atendimento externo com cotação enviada, horário evidenciado e tipo: chega a `Aguardando_confirmacao` e a solicitação de Pix é enfileirada uma única vez.
- **sem cotação** — mesma cascata sem preço dito: barrada pelo guard de cotação ausente, sem reserva.

**Seam secundária:** os predicados puros da FSM e do belief-state, garantindo que ambos continuam derivando da mesma tabela após a mudança — prior art nos testes de belief-state existentes.

**Prior art:** testes de belief-state; testes de transição do painel; testes de integração da extração inline para a cascata multi-hop e o bloqueio prévio; testes do harness fiel.

## Out of Scope

- Usar aceite de valor como gatilho de promoção. Descartado com base na auditoria (1 verdadeiro em 10).
- Mudar as pré-condições da FSM ou introduzir novos estados.
- Desacoplar o gate do ponto de encontro do estado do Atendimento — é frente própria, motivada pelo #27, e não é pré-requisito desta.
- Alterar o comportamento do Pix de deslocamento, do cancelamento automático do piloto ou do guard de cotação ausente.
- Rever a monotonicidade da intenção.

## Further Notes

Esta spec **não pode** ser implementada antes da proveniência do horário. Hoje, o que impediu o horário fantasma do #25 de virar reserva foi justamente a intenção ter ficado baixa por outro defeito: um freio acidental. Promover por horário sem a marca de evidência remove o freio e mantém o defeito — o pior dos dois mundos.

O gate do ponto de encontro merece registro à parte: o #27 mostra que bloquear o endereço no contexto não impede a IA de responder "onde é?" — ela alucina. Promover corretamente reduz a exposição, mas não elimina a classe do problema, que é o gate estar amarrado ao estado da FSM em vez de a evidência própria.
