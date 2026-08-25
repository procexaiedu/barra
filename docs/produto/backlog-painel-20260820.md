# Backlog de painel — reunião de alinhamento de 20/08/2026

> Fonte: `reuniaoalinhamento.txt`. Estes pedidos vieram do Rossi ao vivo, navegando o painel comigo.
> **Nenhum deles é do módulo Agente financeiro** (spec 0006) — por isso estão aqui e não lá.
> Prioridade **a decidir**; nada foi prometido com prazo.

## 1. Agenda: temporada e atendimento na mesma tela

Hoje a agenda mostra atendimentos. Ele quer ver, junto, **em que dias a empresa esteve ativa**:

> *"Eu trabalhei do dia 17 ao dia 23. Aí vai aparecer tipo uma bolinha amarela do lado (…). Quando a
> gente não tiver trabalhado, não vai aparecer essa bolinha, porque não teve trabalho. Então a gente
> vai identificar que teve uma temporada naqueles dias."*

Forma preferida: **camadas/etiquetas** no estilo das "várias agendas" do Google Calendar — agenda de
temporada + agenda de atendimento — em vez de duas telas. Resumo dele: *"preciso saber, na agenda,
os dias que a empresa esteve ativa, e ver os clientes daquele dia."*

Depende da entidade **Temporada** (ADR-0045), que a spec 0006 constrói.

## 2. Cadastro de telefonista no painel

Aba ao lado de Modelos, com nome e **percentual de comissão editável**. Decidido no **ADR-0048** —
é o único item desta lista que já tem ADR e entra pela spec 0006.

## 3. Cliente com etiqueta A / B / C

Classificação por ticket, para remarketing e upsell:

| Etiqueta | Critério que ele deu |
|---|---|
| C− | 30 minutos |
| C | 1 hora |
| B | 3 horas |
| A | pernoite |

> *"Precisa identificar isso no sistema até mesmo pra depois fazer um remarketing, fazer um disparo
> (…) e tentar vender outra coisa pra ele, porque a gente já identifica que esse cliente é bom."*

⚠️ A régua é de **duração**, não de valor — e a memória do projeto já registra que duração é a chave
da escada de preço. Antes de implementar, checar se a etiqueta deve ler duração ou ticket médio: ele
disse os dois na mesma frase.

## 4. Histórico da conversa no cadastro do cliente

Não a conversa crua do WhatsApp — o **que foi conversado**:

> *"Não precisa ser a conversa do WhatsApp, mas sim a conversa que aconteceu naquele atendimento.
> Quais foram as perguntas? Qual foi o tipo de conversa? (…) Quando chamar um cliente, eu posso
> mandar para o vendedor um resumo da última conversa."*

O caso de uso é real: outro vendedor assume um cliente que já é da casa e não sabe o que foi falado.

Precisa cobrir **os dois lados** — a conversa da IA (que o painel já tem) e a do vendedor humano,
que vive no Procex Chat. Ver a memória sobre a topologia router → Chat Procex.

## 5. Módulo de tarefas espelhando o Google Tasks

Ele quer a funcionalidade, **não a integração**:

> *"Até melhor, para não ter vínculo com nada, não ter vínculo com o Google, de registro do que eu
> faço e do que eu não faço."*

O paralelo que ele mesmo usou é o Maps embutido em `/clientes`: usa o componente, nenhum dado sai.
Depois, evoluir na direção do ClickUp (*"tem muito mais opções dentro do mesmo tipo de ferramenta"*).

## 6. Renomear "Atendimentos" para "Jobs"

> *"Jobs acho que fica melhor para entender, porque está muito confuso para mim."*

Rename **de UI apenas**. `atendimentos` é entidade de domínio em ADRs, migrations e código — não
renomear no banco.

## 7. Endereço do cliente em campos separados

Hoje é um campo só. Ele pediu, editando um cliente ao vivo: **rua**, **número**, **bloco/
complemento**, e o **tipo de local** (casa, apartamento). É o que alimenta o mapa de `/clientes`.

## 8. Renomear a marca para "Face Baby"

> *"Tu pode botar o nome de Face Baby, que a gente já decidiu esse nome."*

⚠️ Confirmar o alcance antes de mexer: se é só o rótulo visível do painel ou a marca da operação. O
código, o schema (`barravips`) e os ADRs falam Elite Baby / Barra VIPs — **não** renomear nada disso
por causa de uma frase de reunião.

## 9. Gateway de pagamento próprio

> *"O ideal seria a gente ter o pagamento direto no WhatsApp. Fechou, já vai mandar pro cara o QR
> Code do Pix na conversa (…), link de pagamento."*

É o que dá sentido à forma `Link` que entrou na ficha. Fluxo que ele descreveu: o cliente confirma
que chegou → o sistema manda a chave/QR. Projeto próprio, com decisão de adquirente e conciliação —
não cabe como campo.

## 10. Resumo da conversa enviado à modelo antes do atendimento

Ideia da Lula, e o Rossi endossou:

> *"Se a gente conseguir mandar para a modelo um resumo da conversa antes do atendimento, é
> interessante."* — e, ao ouvir "você acha que ela iria ler?": *"a gente consegue mandar em áudio
> também? Mesmo que seja uma IA falando?"*

Ele mesmo desqualificou como urgente: *"depois tu pensa com calma"*. Fica registrado.

---

## O que a reunião confirmou e não vira trabalho

- O painel **é** o sistema inteiro para eles — *"tudo que você fizer na empresa, você tem que usar
  esse sistema aqui"*. Não há separação entre "área da IA" e "área do cadastro", e ele perguntou
  explicitamente se deveria haver. Resposta dada: não.
- `/midias` tem valor de sinal que ninguém tinha notado: cliente que manda muita foto e não paga.
  *"Quando o cara fica mandando muita foto assim, o cara não quer pagar."* Vale como métrica um dia.
