# Proveniência do horário desejado

Status: ready-for-agent

## Problem Statement

A IA às vezes conduz a venda em cima de um horário que o cliente nunca pediu. No atendimento #25 (23/07) a IA sondou "Seria agora?", o cliente ignorou a pergunta e mudou de assunto — e mesmo assim o sistema gravou `horario_desejado = 02:00`, passou a exibir esse horário para a IA como **"pedido dele"** e a conversa seguiu como se houvesse um horário na mesa.

Para Fernando, o efeito é um Atendimento cujo snapshot afirma algo que a Conversa cliente não sustenta. Para a modelo, é a possibilidade de um slot reservado em cima de um horário fantasma. Para o cliente, é a IA falando de um combinado que ele não fez.

A causa é que `horario_desejado` tem quatro origens indistinguíveis entre si:

1. o extrator, lendo uma fala real do cliente;
2. o **fallback de tempo imediato** do serviço de atendimentos, que sintetiza o `horario_minimo` quando a extração grava `urgencia='imediato'` sem hora;
3. o **eco**: o extrator relê o horário no belief-state colado na cauda do turno e o devolve no payload como se fosse observação nova;
4. o painel, via edição manual de dados do Atendimento.

O campo guarda o número, mas não guarda se existe uma fala do cliente que o sustente. Todos os consumidores — belief-state, FSM, agenda, crons — tratam os quatro casos como equivalentes.

## Solution

Introduzir no Atendimento a noção de **horário evidenciado**: existe, na Conversa cliente, uma fala do cliente que sustenta o horário gravado.

O eixo que separa **não é quem escreveu**. Auditoria de produção:

| Atendimento | quem escreveu o número | evidência na conversa | evidenciado? |
|---|---|---|---|
| #34 | extrator | "Tipo 18h, 18h15" + "Perfeito" | sim |
| #24 | extrator | "Umas 16 horas" | sim |
| #35 | fallback (`horario_minimo`) | IA: "seria agora?" → cliente: "sim" | **sim** — o número é sintético, a intenção não |
| #25 | fallback, depois eco | IA: "Seria agora?" → cliente ignora | **não** |

O fallback produz tanto horário legítimo (#35) quanto fantasma (#25); o extrator produz tanto observação genuína (#34) quanto eco do próprio sistema (#25). Logo a marca é um booleano sobre **evidência conversacional**, decidido por detector determinístico sobre a janela — nunca derivado do payload da extração (que é justamente o canal contaminado pelo eco).

O fallback continua gravando o horário (a agenda precisa de um número para ofertar), mas marcado como não-evidenciado: a FSM não promove o Atendimento por causa dele e o belief-state deixa de apresentá-lo como pedido do cliente.

## User Stories

1. Como modelo, quero que a IA só trate um horário como pedido do cliente quando ele de fato pediu, para eu não me organizar em cima de um encontro que não foi combinado.
2. Como modelo, quero que um slot da minha agenda só seja reservado a partir de horário evidenciado, para não perder janela de atendimento com reserva fantasma.
3. Como cliente, quero que a modelo não fale de um horário que eu nunca mencionei, para a conversa não parecer confusa ou automatizada.
4. Como cliente que respondeu "sim" a "seria agora?", quero que isso conte como horário combinado, para não ter de repetir um número que já ficou claro.
5. Como cliente que ignorou a pergunta do horário, quero que a IA volte a perguntar em vez de assumir, para eu escolher o horário que me serve.
6. Como Fernando, quero ver no Atendimento se o horário veio do cliente ou de um palpite do sistema, para saber se posso confiar no combinado ao decidir no painel.
7. Como Fernando, quero que o horário que EU coloco pelo painel valha como evidência forte, porque eu combinei aquilo por fora e sei que é verdade.
8. Como Fernando, quero que o piloto não cancele leads por causa de bloqueios nascidos de horário fantasma, para não perder cliente por defeito interno.
9. Como IA, quero receber o horário rotulado como "palpite do sistema, ele não confirmou" quando não há evidência, para não afirmar ao cliente que está combinado.
10. Como IA, quero manter o horário evidenciado no contexto mesmo quando a fala que o originou saiu da janela de mensagens, para não reabrir uma negociação já fechada.
11. Como IA, quero que o cliente confirmando mais tarde um horário que o sistema propôs faça esse horário passar a valer como evidenciado, para a conversa avançar quando ele finalmente concorda.
12. Como IA, quero que um horário novo dito pelo cliente substitua o palpite anterior sem gerar Escalada, para não pausar a venda no meio por uma divergência que o próprio sistema criou.
13. Como desenvolvedor, quero uma marca persistida no Atendimento em vez de recomputada por varredura de mensagens, porque a fala que evidencia o horário desliza para fora da janela em conversas longas (o #41 tinha 77 mensagens).
14. Como desenvolvedor, quero que a marca seja decidida por detector determinístico e não por julgamento do LLM, para que o eco do belief não consiga se auto-validar.
15. Como desenvolvedor, quero que a marca não exija backfill, para poder subir a mudança sem escrita corretiva em produção.
16. Como desenvolvedor, quero os casos reais de produção como testes de regressão, para provar que #34/#24/#35 marcam evidência e #25 não.

## Implementation Decisions

**Nova coluna no Atendimento.** `horario_evidenciado`, booleano, `NOT NULL DEFAULT false`. Migration de schema apenas (nenhum seed).

**Sem backfill.** Diferente das flags de disciplina materializadas no write-time, esta é recomputável a partir da janela a cada turno: nasce `false` e o detector a corrige no primeiro turno seguinte de qualquer Atendimento vivo. A coluna existe só porque a fala que evidencia pode sair da janela deslizante, não porque a informação seja irrecuperável.

**Detector determinístico, no módulo de disciplina do agente**, seguindo o padrão já estabelecido pela captura do dia ("seria hoje?" + afirmação curta). Três gatilhos, todos presentes no corpus real:

1. hora explícita numa fala do cliente ("Umas 16 horas", "tipo 18h, 18h15", "daqui 1h", "meio dia");
2. confirmação curta do cliente logo após uma bolha da IA que contém hora ("Consigo às 17:30" → "pode") — mesma mecânica de correferência já usada para o dia;
3. aceite da sondagem de imediatismo, que já é computado no `prepare_context` e vive no estado do grafo.

**Fluxo do carimbo.** O `prepare_context` computa e coloca no estado do grafo, ao lado das demais marcas por-turno; o nó `extrair` carimba junto com a gravação do horário. A rota de edição de dados do Atendimento (painel) carimba `true` diretamente — operador é fonte forte.

**Regra de transição da marca** (decisão fechada na discussão que originou esta spec — a versão ingênua "sticky por valor" perde o caso em que o cliente confirma depois o palpite do sistema):

```
false → true : sempre que o detector encontrar evidência, mesmo que o VALOR não mude
true  → false: apenas quando o VALOR muda sem evidência nova
true  → true : valor muda com evidência
```

**O fallback de tempo imediato permanece**, com o comportamento atual de gravar `horario_desejado = horario_minimo`. Ele apenas não carimba evidência. Isso preserva o conserto que ele introduziu (Atendimento imediato que ficava `Qualificado` e morria sem reserva) sem deixá-lo promover o Atendimento sozinho.

**Consumidores que passam a ler a marca:**

- **belief-state / contexto dinâmico** — o bloco de horário ganha um terceiro status. Hoje ele alterna entre "pedido dele, ainda não confirmado" e combinado; passa a existir "palpite seu, ele não confirmou" quando `horario_evidenciado` é falso. Sem isso a IA continua lendo o palpite como pedido do cliente, que é exatamente a falha do #25.
- **promoção de intenção** — consumidor principal, especificado à parte (ver `.scratch/extracao-promocao-intencao/`).

**Consumidores que NÃO mudam nesta spec:** criação de bloqueio prévio, crons de timeout e do piloto, e a classificação de reagendamento pós-bloqueio. Eles passam a receber menos horário fantasma como efeito indireto, mas sua lógica não é tocada aqui.

## Testing Decisions

Um bom teste aqui afirma **o que o Atendimento passa a valer depois do turno**, não como a marca foi computada. Nada de asserção sobre chamadas internas, ordem de nós ou forma do payload da extração.

**Seam primária: o harness fiel.** Os testes de regressão semeiam a Conversa cliente com as falas reais e rodam o turno pelo mesmo caminho de produção (`processar_turno` → `enviar_turno`), afirmando sobre o estado do Atendimento no banco. O relógio é fixado por clock injection, e o grafo real roda com o chat do LLM substituído por um fake roteirizado — padrão já existente nos testes de integração da extração inline, que constroem o grafo real após substituir a factory de chat. Isso mantém o teste determinístico e **sem consumo de crédito**.

Casos obrigatórios, extraídos de produção:

- **#34** — "Você tem horário amanhã? / No final de tarde" → IA "Consigo às 17:30" → "Tipo 18h, 18h15" → IA "Posso confirmar às 18h" → "Perfeito": termina com horário evidenciado.
- **#24** — "Umas 16 horas": evidenciado por hora explícita.
- **#35** — IA "Seria agora?" → "sim": evidenciado, ainda que o número tenha vindo do fallback.
- **#25** — IA "Seria agora?" → cliente pergunta outra coisa: **não** evidenciado, com o horário mesmo assim gravado.
- **promoção tardia** — a partir do estado do #25, o cliente diz "pode ser 2h então": a marca sobe sem que o valor mude.

**Seam secundária: o detector puro.** Tabela de falas do corpus contra o booleano esperado, incluindo os negativos que já sabemos que enganam: "Não conheço" (respondendo "Campinas?", não é hora) e as falas de fetiche/valor que no #41 conviviam com o horário reafirmado.

**Prior art:** testes do harness fiel para a mecânica do turno; testes de integração da extração inline para grafo real com LLM fake; testes das flags de disciplina para a materialização de marcas no Atendimento; testes de contexto dinâmico para o render dos status do bloco de horário.

Testes que tocam banco rodam contra o Postgres real (`TEST_DATABASE_URL`), com rollback no teardown, e precisam entrar no gate como `needs_db` — não apenas no subconjunto que roda no CI.

## Out of Scope

- Cancelar ou realocar bloqueio prévio quando a marca cai para `false`. O bloqueio nasce em `Aguardando_confirmacao` e mexer nele é assunto de agenda.
- Mudar a classificação de reagendamento pós-bloqueio, a tolerância de drift ou o descarte de flip de tipo.
- Distinguir "o cliente pediu a hora" de "a IA propôs e ele confirmou": ambos são evidência e recebem o mesmo tratamento.
- Registrar cadeia de origem (quem escreveu cada versão do horário). A decisão é binária de propósito.
- O eco do belief-state, que é causa raiz compartilhada e tem spec própria (`.scratch/extracao-janela-dedicada/`).
- Rever o fallback de tempo imediato em si (mantido como está, apenas sem carimbar evidência).

## Further Notes

O detector determinístico é escolha deliberada sobre pedir a informação ao extrator. O campo que deveria carregá-la já existe e foi neutralizado: `informa_horario`, nos sinais de qualificação, é hoje derivado da própria presença do horário no payload — logo, exatamente nos casos em que a pergunta importa (existe horário gravado; ele é confiável?), o sinal é `true` por construção e não distingue nada.

No #25, o horário fantasma só não virou reserva porque a `intencao` ficou baixa por outro defeito. Ao consertar a promoção de intenção sem esta marca, esse freio acidental desaparece — motivo pelo qual esta spec deve ser implementada **antes ou junto** da promoção de intenção, nunca depois.

O corpus que embasa a spec tem dez dias, uma modelo e tráfego de piloto com cancelamento automático ligado. Os casos servem como regressão; não provam cobertura do detector em tráfego real.
