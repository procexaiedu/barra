# Janela dedicada da extração: cortar o eco do belief-state

Status: ready-for-agent

## Problem Statement

A chamada de extração não recebe uma janela própria: ela recebe a janela do chat com as mensagens de sistema removidas. Só que tudo o que importa está **dentro da última mensagem do cliente**, que o strip preserva — o belief-state inteiro é concatenado ali, e o lembrete de persona é prependido no mesmo lugar.

O resultado é que o extrator lê, como se fosse conversa, os valores dos próprios campos que deve preencher. Ele para de extrair e passa a copiar.

Evidência de produção:

- **`tipo_atendimento`** foi reafirmado como `interno` em **todos** os turnos dos Atendimentos #34 e #41, inclusive naqueles em que a última fala do cliente era "quanto PG | obrigado", "não vou não obrigado", "vc melhora no valor eu vou" ou "atendimento so oral penetração ou com anal também" — nenhuma delas diz nada sobre quem se desloca.
- **`valor_acordado`**: em 16 de 44 gravações, o número não aparece em nenhuma mensagem dos 20 minutos anteriores.
- **Redundância por campo** entre 71% e 81% (tipo, data, hora, duração, valor, intenção).
- **35% das extrações** não trazem nenhum par chave-valor novo em relação à anterior.

O caso mais claro é o Atendimento #25: o fallback de tempo imediato gravou `horario_desejado = 02:00`; no turno seguinte o extrator **mandou 02:00 no payload**, e repetiu nos dois turnos seguintes. Um valor sintetizado pelo sistema voltou carimbado como observação independente.

Além do gabarito, o extrator recebe o **lembrete de persona** quando a conversa passa de oito falas da IA. Para um modelo cujo system diz "você lê uma conversa e registra o estado; você NÃO responde ao cliente", chega um bilhete mandando "segure firme quem você é: mulher real, bolhas de 2 a 5 palavras, emoji raro". Como o lembrete condensa parte das regras de venda, o extrator acaba recebendo conduta **por acidente e só em conversas longas** — uma fonte de variância por comprimento de conversa que ninguém desenhou.

## Solution

Parar de derivar a janela da extração por subtração e passar a **montá-la**. A chamada de extração recebe exatamente três coisas:

1. a **conversa crua** (mensagens do par, sem contexto colado e sem lembrete);
2. a **âncora temporal mínima** — data e hora atuais, que a descrição do campo de horário exige para resolver tempo relativo;
3. um bloco **`<ja_registrado>` na cauda**, rotulado como estado do sistema, com instrução de delta.

```
<ja_registrado>
  tipo=interno
  hora=02:00 (palpite do sistema — ele não confirmou)
  valor COTADO=400 (1h) — ele ainda não aceitou
  Isto é estado do sistema, NÃO fala do cliente.
  Registre um campo só se ELE MUDOU nesta conversa.
</ja_registrado>
```

Os rótulos são o que impede o bloco de recriar o problema: sem o rótulo do horário, o extrator reconfirma o palpite (o #25 de novo); sem a distinção entre cotado e aceito, ele vê o número e remarca o aceite.

O contra-argumento óbvio — "mas o eco preserva memória quando a janela desliza" — não se sustenta: o snapshot é incremental no banco, campos nulos preservam o anterior. Reafirmar valor idêntico grava o que já estava lá. O eco não adiciona; ele **subtrai** de duas formas: destrói o sinal de "este campo mudou neste turno" (o extrator nunca omite porque sempre tem gabarito) e alimenta os guards do domínio com falsos pedidos do cliente.

## User Stories

1. Como modelo, quero que o sistema só registre mudança quando o cliente de fato mudou de ideia, para meus dados refletirem a negociação e não o eco do próprio sistema.
2. Como modelo, quero não ser escalada por um "reagendamento" que o sistema inventou ao reler o próprio horário, para não ser interrompida à toa.
3. Como cliente, quero que a IA perceba quando eu mudo de ideia, e não que ela repita o que já estava anotado.
4. Como Fernando, quero que o histórico de extrações mostre o que mudou a cada turno, para reconstruir a negociação sem ler 500 linhas idênticas.
5. Como Fernando, quero que os guards do domínio (reagendamento, flip de tipo, par preço × duração) sejam acionados por pedido real do cliente, para as Escaladas serem sinal e não ruído.
6. Como IA extratora, quero receber as falas do cliente sem o belief colado, para julgar o que foi dito e não o que já está gravado.
7. Como IA extratora, quero saber o que já está registrado num bloco rotulado como sistema, para não confundir memória com observação.
8. Como IA extratora, quero a instrução explícita de registrar só o que mudou, para omitir campo passar a ser informação em vez de esquecimento.
9. Como IA extratora, quero manter a âncora de data e hora, para continuar resolvendo "daqui 1h" e "agora" corretamente.
10. Como IA extratora, quero não receber o lembrete de persona, porque eu não falo com o cliente e ele só me confunde.
11. Como IA extratora, quero receber o mesmo tratamento em conversa curta e longa, para meu comportamento não variar com o tamanho do papo.
12. Como desenvolvedor, quero que o bloco de estado seja renderizado a partir das mesmas variáveis do contexto dinâmico, para o que a IA vê e o que o extrator vê nunca divergirem.
13. Como desenvolvedor, quero o bloco na cauda da chamada, para o prefixo cacheável da chamada de extração ficar estável entre turnos.
14. Como desenvolvedor, quero o texto do bloco num template de prompt e não numa string de código, seguindo a regra do repositório.
15. Como desenvolvedor, quero que a entrada da extração passe a ser reconstruível a partir do banco, para poder replayar turnos históricos numa bancada offline.
16. Como desenvolvedor, quero medir a queda da redundância no próprio banco depois da mudança, para saber se a hipótese estava certa.

## Implementation Decisions

**A montagem da janela de extração deixa de ser subtrativa.** Hoje ela filtra mensagens de sistema e herda tudo o que está escondido dentro da mensagem do cliente. Passa a ser construtiva: system mínimo (que já existe) + conversa crua + âncora temporal + bloco de estado.

**O bloco `<ja_registrado>` é renderizado a partir do mesmo dicionário de variáveis que alimenta o contexto dinâmico**, no `prepare_context`, e trafega pelo estado do grafo até o nó `extrair` — mesmo padrão já usado por outras marcas por-turno. Zero query nova e nenhuma chance de divergência entre o que a IA lê e o que o extrator lê.

**Consequência arquitetural que precisa ser resolvida:** hoje o `prepare_context` funde a mensagem do cliente e o contexto dinâmico num único `HumanMessage`, e depois não há como separá-los. A decisão é guardar as peças no estado do grafo (âncora e bloco de estado), em vez de reconstruir a janela no nó `extrair` a partir das linhas cruas — mais barato e coerente com o padrão existente.

**Rótulos do bloco são obrigatórios** e dependem das outras duas frentes: o horário é apresentado como palpite quando não há evidência (`.scratch/extracao-proveniencia-horario/`) e o valor é apresentado como cotado enquanto não houver aceite (`.scratch/extracao-aceite-hibrido/`). Implementar este bloco com um dump cru do snapshot recria os dois defeitos.

**Texto vai para um template de prompt**, não para string no código — a regra do CLAUDE.md do agente é explícita, e o system mínimo da extração já é uma exceção tolerada; texto novo não amplia a exceção.

**O campo de próxima ação esperada fica fora do delta.** É obrigatório, por natureza reescrito a cada turno, e tem consumidores reais no painel, nas conversas e no fluxo de Pix.

**Efeito colateral positivo no cache:** hoje a conversa termina numa mensagem inchada que muda a cada turno. Com conversa crua seguida de bloco volátil, o prefixo da chamada barata (system + conversa append-only) fica byte-idêntico entre turnos.

**Métrica de aceitação, verificável no próprio banco:** a redundância por campo (hoje 71–81%) e a proporção de extrações sem nenhum par novo (hoje 35%) precisam cair de forma clara. Se não caírem, a hipótese estava errada.

## Testing Decisions

Um bom teste aqui afirma o que o Atendimento registra depois do turno — não o texto exato do bloco nem a ordem das mensagens enviadas ao provider.

**Seam primária: o harness fiel.** Semear uma Conversa cliente com um combinado já registrado, rodar um turno cuja fala do cliente não menciona nenhum campo, e afirmar que o turno **não registrou mudança** (nenhuma transição, nenhum campo reescrito com valor novo). O caso do #41 serve tal e qual: cliente falando de fetiche e de desconto enquanto o tipo do encontro permanece o mesmo.

Casos obrigatórios:

- **eco de tipo** — conversa com tipo já combinado e fala do cliente sobre outro assunto: o tipo não é reenviado.
- **mudança real** — o cliente pede outro horário: o campo é registrado normalmente e a mudança chega ao Atendimento.
- **#25** — depois do fallback ter gravado o palpite, o turno seguinte **não** reafirma o horário.
- **conversa longa** — acima do limiar do lembrete de persona, o comportamento da extração é o mesmo da conversa curta.

**Seam secundária: o nó `extrair` com chat fake.** Os fakes existentes já registram a janela recebida, então dá para afirmar que o bloco de estado chega e que o lembrete e os blocos de conduta não — sem banco e sem crédito. Usar apenas para o que o harness não alcança.

**Prior art:** testes do nó `extrair` (fakes que capturam a janela); testes do harness fiel; testes de contexto dinâmico para o render dos rótulos; testes de render do prefixo geral para a disciplina de bytes estáveis.

## Out of Scope

- Mudar o contexto dinâmico que o **chat** recebe. Belief, conduta e lembrete continuam exatamente como estão para quem fala com o cliente.
- Mudar o system mínimo da extração.
- Alterar a janela deslizante de mensagens ou seu tamanho.
- Reescrever as descrições dos campos (frente do aceite trata a que precisa mudar).
- Alterar os guards do domínio que hoje absorvem o ruído (tolerância de drift, descarte de flip de tipo). Eles passam a receber menos ruído; sua lógica não é tocada aqui.

## Further Notes

Esta spec tem um segundo benefício, tão importante quanto o primeiro: **ela torna o extrator testável**. Hoje a entrada da extração inclui agenda, bloqueios, disponibilidade e janelas livres do instante — estado que mudou desde então e não é reconstruível a partir do banco. Depois da janela dedicada, a entrada é `(conversa, agora, ja_registrado)`, e as três são reproduzíveis por replay. A bancada offline (`.scratch/extracao-eval-offline/`) depende disso.

O risco novo introduzido é a **subextração**: se o extrator passar a omitir demais, um campo que de fato mudou deixa de ser gravado e o snapshot preserva silenciosamente o valor velho. É o erro simétrico do eco e é *menos visível* — o eco produz ruído mensurável no banco, a omissão produz nada. Só se detecta comparando com rótulo humano na bancada offline, o que é mais um motivo para as duas frentes andarem próximas.
