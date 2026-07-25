# Bancada offline de avaliação do extrator

Status: ready-for-agent

## Problem Statement

Toda mudança no extrator hoje é decidida por hipótese. Não existe forma de responder "isso melhorou?" antes de subir para produção — e, com o volume do piloto, esperar o tráfego responder leva semanas.

Consequências concretas, todas presentes agora:

- O patch de 24/07 (que removeu a derivação do aceite, fez a retratação rebaixar e endureceu a descrição do campo) **não tem nenhuma evidência**: a última extração de produção aconteceu antes dele.
- A extração roda com **temperatura de sampling**, não zero. O comentário no código afirma que chamar "sem temperatura" dá determinismo, mas omitir o parâmetro faz o provider aplicar o próprio default — que não é zero em nenhuma API compatível com OpenAI. A tarefa mais determinística do sistema (ler uma conversa e preencher campos) roda com sampling, enquanto o chat criativo roda num valor escolhido por experimento.
- As quatro frentes de conserto do extrator especificadas em paralelo a esta são todas hipóteses plausíveis e nenhuma é mensurável sem bancada.

Os evals existentes não cobrem isso: são de conduta, precisam de LLM-judge e já mediram o custo disso (concordância baixíssima no judge de desfecho).

## Solution

Uma bancada offline que roda o extrator sobre turnos históricos reconstruídos do banco e compara o resultado com rótulo humano.

O ponto que torna isto barato: **o extrator não precisa de judge**. A saída é estruturada, o rótulo é um conjunto de pares campo-valor, a métrica é igualdade. Determinístico, sem crédito de judge, sem o problema de concordância que afeta os evals de conduta.

A entrada de cada turno é reconstruível:

- **conversa** — mensagens do par até o instante do turno;
- **snapshot no instante** — replay dos payloads das extrações do Atendimento em ordem (a máquina de estados é determinística, então aplicar as extrações desde `Novo` reproduz o estado de cada turno);
- **agora** — o instante do turno, injetado pelo mecanismo de clock injection que já existe.

Não se rotula 531 extrações. Rotula-se os **turnos decisivos** — aqueles em que um campo aparece ou muda pela primeira vez, ~130 no corpus — com alvo prático de 50 a 60 turnos curados, cobrindo os modos de falha conhecidos mais uma amostra aleatória.

## User Stories

1. Como Fernando, quero saber se uma mudança no extrator melhora ou piora antes de ela chegar aos clientes, para não usar o piloto como ambiente de teste.
2. Como Fernando, quero comparar variantes com número em vez de opinião, para decidir onde investir esforço.
3. Como modelo, quero que mudanças no sistema sejam testadas antes de afetarem as minhas conversas, para não perder cliente por experimento.
4. Como desenvolvedor, quero medir a precisão do extrator por campo, para saber qual campo está custando venda.
5. Como desenvolvedor, quero medir o efeito de uma mudança na trajetória de estados do Atendimento, porque campo certo que não faz o funil andar não resolve o problema do usuário.
6. Como desenvolvedor, quero rodar a bancada com temperatura zero e com a temperatura atual, para decidir a configuração com dado.
7. Como desenvolvedor, quero rodar com e sem o bloco de estado registrado, para medir o efeito da janela dedicada.
8. Como desenvolvedor, quero rodar com a descrição do aceite autocontida e com a referenciada, para medir o efeito da correção da referência órfã.
9. Como desenvolvedor, quero rodar com e sem a promoção de intenção derivada, para medir quanto do funil ela destrava.
10. Como desenvolvedor, quero medir o patch de 24/07 que ainda não tem evidência, para saber se ele ajudou.
11. Como desenvolvedor, quero repetição por item enquanto a temperatura não for zero, para distinguir melhora de sorte.
12. Como desenvolvedor, quero um golden set versionado no repositório, para o resultado ser comparável entre execuções e entre pessoas.
13. Como desenvolvedor, quero que o golden set seja rotulado por humano, para não pedir a um LLM que corrija a prova de outro LLM.
14. Como desenvolvedor, quero que a bancada fique fora do gate padrão de testes, para não gastar crédito em toda execução da suíte.
15. Como desenvolvedor, quero um relatório legível por campo e por trajetória, para levar o resultado à discussão sem reprocessar dados.
16. Como desenvolvedor, quero que os limites do corpus estejam escritos no relatório, para ninguém ler o número como promessa de qualidade absoluta.

## Implementation Decisions

**A bancada vive junto dos evals existentes**, como alvo próprio de Makefile — separado do gate de segurança e do gate de conduta, e marcado como teste que consome crédito.

**Reconstrução da entrada por replay.** O construtor recebe um Atendimento e devolve, para cada turno decisivo, a tripla `(conversa até t, snapshot em t, agora)`. O snapshot vem de aplicar em ordem os payloads das extrações registradas no histórico de eventos, e não do estado atual do Atendimento — o estado atual é o resultado final e não serve para reproduzir turnos intermediários.

**Dependência de desenho:** a bancada só é fiel depois da janela dedicada da extração (`.scratch/extracao-janela-dedicada/`). Enquanto a entrada da extração incluir agenda, bloqueios, disponibilidade e janelas livres do instante, ela não é reconstruível — esse estado mudou desde então. Antes disso a bancada roda, mas mede uma entrada aproximada.

**Métrica em dois níveis.**

*Nível campo* (diagnóstico), com a assimetria explícita — cada campo tem um erro que dói mais:

| campo | métrica que manda | por quê |
|---|---|---|
| aceite de valor | precisão | falso positivo trava a escada de desconto |
| intenção | recall | falso negativo trava o funil inteiro |
| horário desejado | ambos, mais a marca de evidência | fantasma queima slot; ausência mata a reserva |
| tipo do encontro | precisão | flip indevido dispara Pix de deslocamento |

*Nível trajetória* (impacto): rodar o replay completo do Atendimento e comparar a sequência de estados com a rotulada. É o que traduz "campo certo" em "a venda avançou" — só o nível campo pode melhorar sem que nada mude no funil.

**Golden set versionado no diretório desta spec**, iniciado pelas rotulagens já produzidas (ver `golden-set-inicial.md`). Rotulagem **humana**; nada de gerar gabarito com LLM-judge.

**Variantes que a bancada precisa suportar desde o início**, porque são exatamente as decisões em aberto: temperatura, presença do bloco de estado registrado, descrição autocontida vs. referenciada, promoção de intenção derivada, e o patch de 24/07.

**Repetição por item:** enquanto a extração rodar com temperatura de sampling, cada item roda ao menos três vezes e o relatório mostra dispersão, não só média. Se a temperatura for cravada em zero, a repetição pode cair para um — e essa é a primeira medição que a bancada deve produzir.

**Custo e gate:** o corpus inteiro sai por menos de um dólar no provider atual e o golden set curado por centavos, mas é crédito real e cai na regra de produção do CLAUDE.md — o alvo é marcado como teste que bate na API real e fica fora da suíte padrão.

## Testing Decisions

Esta spec entrega uma ferramenta de medição, então "testar" tem dois níveis distintos.

**A ferramenta em si** é testada com o extrator substituído por um fake roteirizado: dado um golden set pequeno e um extrator que devolve payload conhecido, o relatório precisa apresentar as métricas corretas. Isso roda sem crédito e entra no gate padrão. O que se afirma é o comportamento externo — o relatório produzido —, nunca a estrutura interna do cálculo.

**A reconstrução da entrada** é testada contra um Atendimento semeado com histórico conhecido: o replay dos payloads precisa reproduzir o snapshot esperado em cada turno. Toca banco, então roda como teste de banco contra o Postgres real com rollback.

**A execução real** (extrator batendo no provider) não é teste de regressão e não entra em gate: é um alvo que produz relatório, comparado manualmente entre execuções.

**Prior art:** o gate de conduta, que já separa execução com fake da execução real autorizada; os relatórios de regressão existentes, para o formato de série histórica; os scripts de replay do corpus, para leitura de conversas históricas.

## Out of Scope

- Avaliar a conduta ou a voz da IA. Isto mede só a extração.
- Substituir os evals existentes de segurança e conduta.
- LLM-judge de qualquer natureza.
- Rotular as 531 extrações. O alvo é o conjunto decisivo.
- Rodar automaticamente em CI. É execução deliberada, com crédito.
- Corrigir a temperatura da extração — esta spec só entrega a medição; a mudança de configuração é consequência do resultado.

## Further Notes

O corpus tem **dez dias, uma modelo e tráfego de piloto com cancelamento automático ligado**. Um extrator afinado nele pode não generalizar para outra modelo, outro cardápio ou tráfego real. A bancada mede regressão e compara variantes com confiança; ela não prova qualidade absoluta. Isso precisa estar escrito no relatório, antes que alguém leia uma porcentagem como promessa.

O achado da temperatura merece verificação independente antes de virar mudança: o valor exato do default do provider não foi confirmado na documentação. O que se sabe com certeza é que não é zero — e cravar zero explicitamente para uma tarefa de extração estruturada remove a dúvida com uma linha de configuração. A bancada existe justamente para dizer se isso muda alguma coisa.
