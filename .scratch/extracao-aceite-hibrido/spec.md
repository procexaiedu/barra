# Aceite de valor: LLM marca, detector determinístico rebaixa

Status: ready-for-agent

## Problem Statement

O sinal `aceita_valor` decide se o belief-state apresenta o preço como **cotado** ou como **fechado**. Quando ele é `true`, o contexto do turno passa a instruir a IA a "não re-cotar nem renegociar" — e, com isso, o **Desconto de fechamento** nunca engata.

Em produção o sinal foi marcado em 10 Atendimentos. Auditando a fala do cliente imediatamente anterior ao carimbo:

| Atendimento | última fala do cliente | veredito |
|---|---|---|
| #41 | "quanto PG \| **obrigado**" | falso |
| #38 | falas sobre fetiche, nenhum preço | falso |
| **#34** | "Tipo 18h, 18h15" | **verdadeiro** |
| #27 | "Hoje não consigo, te mando msg mais pra frente" | falso |
| #24 | "Tem fotos \| E liberal? \| Aonde atende" | falso |
| #21 | "Le de novo com calma gata" | falso |
| #20 | "Quero muito ir mas... tenho que esperar começo do mês" | falso |
| #19 | "Hummm \| Pretendo...mais para o final do dia" | falso |
| #9 | "É o mesmo vl \| O normal o que seria" | falso |
| #8 | "Rua gata seria do seu local dlc?" | falso |

Um verdadeiro em dez. E `n_contrapropostas` ficou em zero nos dez — a escada de desconto não engatou em nenhum.

Pior que a imprecisão é a **irreversibilidade**. O merge dos sinais só adiciona; o único canal de retratação é o campo `limpar`, usado **2 vezes em 531 extrações**. No #19 o cliente respondeu "Não" quando a IA pediu para confirmar o horário, e isso não reverteu nada: o Atendimento seguiu com o preço marcado como aceito.

## Solution

Separar quem sobe de quem desce, porque o dano é assimétrico: aceite falso trava a escada de desconto e faz a IA afirmar um fechamento que o cliente nunca deu; aceite ausente apenas mantém a negociação aberta.

- **Sobe** — o extrator continua marcando, mas com a descrição do campo **autocontida**.
- **Desce** — um **detector determinístico de recuo** sobre a fala do cliente rebaixa o sinal, sem depender de o LLM emitir `limpar`.

A descrição precisa ser autocontida porque hoje ela delega: manda "seguir a sua conduta de `<desconto>`" — um bloco que vive no prompt geral, que é exatamente o que a chamada de extração remove ao rodar com a janela mínima. **O leitor da descrição não recebe a conduta referenciada.** Pior, a conduta referenciada é contextual: o prompt afirma que pergunta não é aceite, e também que pergunta de logística ("onde é?", "que horas?") é sim ao valor da mesa — a segunda regra vale só *depois* de a IA ter recusado desconto, distinção que o extrator não tem como aplicar sem o estado da negociação. Dois dos falsos positivos (#24, #8) são exatamente esse padrão.

## User Stories

1. Como modelo, quero que a IA só considere o preço fechado quando o cliente aceitou de fato, para não perder venda por deixar de negociar com quem ainda estava em dúvida.
2. Como modelo, quero que a escada de desconto continue disponível enquanto o cliente não aceitou, para converter quem só precisava de um degrau.
3. Como cliente, quero que a modelo não diga "o valor que fechamos" sobre um preço que eu nunca topei, porque isso me irrita e me faz sair da conversa.
4. Como cliente que disse "não" ao fechamento, quero que a negociação volte a ficar aberta, para eu poder voltar depois sem ter de reabrir tudo do zero.
5. Como cliente que disse "vou esperar começo do mês", quero que a IA entenda que adiei e não que aceitei, para a conversa continuar coerente.
6. Como cliente que agradeceu ("obrigado"), quero que a cortesia não seja lida como aceite, porque agradecer não é fechar.
7. Como cliente que perguntou onde é ou que horas, quero que a pergunta não seja tratada como fechamento antes de haver proposta na mesa.
8. Como cliente que já aceitou e só não controla o relógio ("vou te avisando"), quero que o valor e o horário sigam de pé, para não ter de negociar de novo o que já ficou combinado.
9. Como Fernando, quero ver o preço marcado como aceito só quando houve aceite, para o painel refletir a negociação real.
10. Como Fernando, quero que o contador de contrapropostas reflita a negociação de fato ocorrida, para avaliar se o piso de desconto está calibrado.
11. Como IA, quero receber a regra de aceite completa na descrição do campo, para julgar sem depender de um bloco de prompt que não me foi enviado.
12. Como IA, quero que um recuo explícito do cliente reabra a negociação de preço, para eu poder oferecer o degrau em vez de repetir uma recusa.
13. Como IA, quero que "vou te avisando" NÃO seja lido como recuo, para não jogar fora um fechamento que já aconteceu.
14. Como desenvolvedor, quero que o rebaixamento não dependa de o LLM emitir `limpar`, porque o dado mostra que ele praticamente não emite.
15. Como desenvolvedor, quero que o rebaixamento atinja apenas o sinal de aceite e não o valor cotado, para preservar a base que o guard do **Piso de desconto** confere.
16. Como desenvolvedor, quero o detector no agente e a aplicação no nó de extração, para não fazer o domínio importar código do agente.
17. Como desenvolvedor, quero os dez casos auditados como regressão, para provar que o único verdadeiro sobrevive e os nove falsos são rebaixados quando há recuo.

## Implementation Decisions

**Descrição do campo `aceita_valor` passa a ser autocontida.** Sai a referência ao bloco `<desconto>` do prompt geral; entra a regra inteira, incluindo a distinção que hoje só existe no prompt: pergunta de horário ou logística vale como sim **apenas depois de a IA ter recusado desconto**; antes disso, pergunta não é aceite. Cortesia e reconhecimento ("obrigado", "ok", "entendi", "blz") continuam explicitamente fora, como já está.

Isso é uma **emenda à fronteira conduta ↔ tool description** documentada no CLAUDE.md do agente. A regra vigente ("conduta client-facing mora no prompt; a descrição referencia, não reescreve") foi escrita quando o leitor da descrição era o chat principal, que recebe o prompt inteiro. Para a chamada de extração com janela mínima ela se inverte: o único texto que chega é a descrição, então conduta referenciada **não chega**. Registrar a emenda no CLAUDE.md do agente faz parte desta spec, porque outras descrições têm o mesmo defeito (a de tipo de atendimento também delega para "sua conduta").

**Detector de recuo, no módulo de disciplina do agente**, com duas classes:

1. **Recuo autônomo** (não precisa de correferência): "vou ver", "estou analisando", "te chamo antes", "hoje não consigo", "mês que vem", "quando eu tiver", "depois eu vejo".
2. **Negativa correferenciada**: "não" / "agora não" / "acho que não" imediatamente após uma bolha da IA que pede fechamento ("podemos confirmar?", "fecha?", "vamos confirmar X?"). Isolado, "não" é ambíguo demais — no #24 o cliente escreveu "Não conheço" respondendo a "Campinas?".

**Lista negativa explícita — nunca é recuo:** "vou te avisando", "te aviso quando sair", "me confirma". O vocabulário canônico dessa distinção já existe no prompt de regras: quem diz "vou te avisando" **já quer** e só não manda no relógio; horário e valor seguem de pé. Ignorar isso rebaixaria o #34 — o único aceite verdadeiro do corpus, cuja fala é "Perfeito, vou te avisando então".

**Aplicação no nó `extrair`**, não no domínio: o detector vive no agente e o domínio não importa `barra.agente`. O nó injeta o sinal de aceite como `false` no payload antes da execução da tool — mesmo padrão do piso de intenção já existente, que muta os argumentos do tool call antes da execução inline. Funciona mesmo quando o extrator não repete o sinal no turno, porque o merge dos sinais de qualificação sobrescreve chave explícita.

**Precedência:** havendo aceite marcado pelo extrator e recuo detectado no mesmo turno, o recuo vence. A economia de erro favorece esse lado — falso negativo do detector mantém o estado atual; falso positivo reabre a escada de desconto, que é o comportamento seguro.

**Escopo do rebaixamento:** apenas o sinal `aceita_valor`. O `valor_acordado` permanece — ele é gravado já na cotação e é a base que o guard do Piso de desconto confere. O efeito visível é o belief-state voltar de "valor já combinado" para "preço que você já cotou e ele ainda não aceitou".

## Testing Decisions

Bons testes aqui afirmam o que a negociação passa a permitir: o preço volta a ser negociável, a IA pode oferecer o degrau, o painel mostra cotado em vez de fechado. Não afirmam sobre regex, ordem de detectores ou forma do payload.

**Seam primária: o harness fiel**, com as conversas reais semeadas e assert no Atendimento após o turno. Grafo real com chat fake roteirizado (padrão dos testes de integração da extração inline) e clock injection — determinístico, sem crédito.

Casos obrigatórios:

- **#19** — IA "Podemos confirmar 18h?" → cliente "Não": aceite rebaixado (negativa correferenciada).
- **#20** — "Quero muito ir mas... tenho que esperar começo do mês": aceite rebaixado (recuo autônomo).
- **#27** — "Hoje não consigo, te mando msg mais pra frente": aceite rebaixado.
- **#34** — "Perfeito, vou te avisando então": aceite **preservado**. Este é o teste que pega a armadilha do "te aviso" na lista negativa.
- **#24** — "Não conheço" respondendo a "Campinas?": não rebaixa por si só (negativa sem correferência de fechamento).
- **valor preservado** — depois de qualquer rebaixamento, o valor cotado continua gravado e o belief o apresenta como cotado.

**Seam secundária: o detector puro**, com tabela de falas do corpus contra as três saídas (recuo autônomo / negativa correferenciada / não é recuo).

**Prior art:** testes dos sinais de qualificação do turno para a semântica de merge e rebaixamento; testes das flags de disciplina para detectores determinísticos sobre a janela; testes de contexto dinâmico para o render de cotado vs. fechado.

A precisão do sinal **subindo** (a descrição autocontida funcionou?) não é testável por teste determinístico — é medida pelo eval offline (`.scratch/extracao-eval-offline/`).

## Out of Scope

- Reintroduzir a derivação de aceite a partir do valor gravado. Ela foi removida de propósito (o valor é gravado já na cotação) e não volta.
- Fazer o recuo mexer no horário, no bloqueio ou na marca de horário evidenciado. O prompt diz que "horário e valor que ele retratou quem libera é o sistema", mas isso envolve agenda e fica para outra frente.
- Mudar o campo `limpar`, que segue existindo como canal de retratação explícita.
- Detectar aceite deterministicamente (o extrator continua sendo quem marca; a alternativa totalmente determinística foi considerada e descartada por perder aceites indiretos como "melhor presencial né 😍").
- Alterar o piso de desconto, o número de contrapropostas ou a conduta de negociação.

## Further Notes

Os dez casos auditados são do regime **anterior** ao patch de 24/07 que removeu a derivação do aceite a partir do valor, fez `limpar` rebaixar e endureceu a descrição. A última extração de produção ocorreu antes desse patch, então ele **não tem nenhuma evidência** a favor ou contra. Esta spec assume que o patch ajudou e ataca o que ele não cobre — a referência órfã ao bloco de conduta e a irreversibilidade prática.

Como os testes determinísticos não medem a precisão do julgamento, subir esta mudança sem o eval offline significa trocar uma hipótese não verificada por outra. A ordem recomendada é implementar o rebaixamento (que é determinístico e verificável agora) e tratar a descrição autocontida como variante a ser medida na bancada.
