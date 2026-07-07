# Ata 2 — Reunião ProcexAI × Fernando (limpa)

> Extrato apenas do que serve ao desenvolvimento do agente: filosofia de produto, conduta de venda, regras de negócio, dados do BI e padrões de comportamento de cliente. Papo pessoal, mecânica de slides e a integração GPT/financeiro pessoal do Fernando foram removidos.

## 1. Filosofia de produto: substituir antes de melhorar

- A missão da 1ª ida à produção **não é melhorar o atendimento, é substituir** o vendedor humano — trocar "A por A". Replicar exatamente o que os vendedores fazem hoje, não inventar o "melhor atendimento da história".
- Só de substituir já se ganha muito: atendimento 24/7, respostas simultâneas, sistema populado com dados, vendedores liberados do operacional.
- **Depois** de estar em produção, igual ao humano e vendendo, aí sim melhora-se por versão: v1.0 lança igual → v1.1 melhora desconto → melhora saudação → melhora follow-up, etc. Cada melhoria vem de dados reais.
- Produção gera aprendizado exponencial: 1 semana de tráfego real (~200 atendimentos) vale mais que meses de teste interno. Erro que aparece uma vez é corrigido e não reaparece (é IA — treina uma vez, aplica sempre).
- Piloto começa com **1 modelo, 1 WhatsApp** (talvez 2-3 no máximo). Demais modelos ficam ativas para homenagem: se pedirem alguém que a modelo ativa não faz, ela indica outra da casa.
- A IA entra **no número da própria modelo** (não em número novo). Vendedores seguem monitorando pelo painel (espelho tipo WhatsApp Web, cada um com login).

## 2. Conhecimento tático vs. teórico

- **Teórico** = as conversas/roteiro; a IA já tem.
- **Tático** = a expertise que falta: sagacidade de negociação, jogo de cintura, sair de situações, extrair o máximo de cada cliente. É a prioridade nº1 de refino do Fernando.
- Regra da rua: cada vendedor bom vende ~10k/dia porque **vende contexto, não uma hora** — busca sempre a melhor oportunidade dentro da cartela. Cada atendimento tem que "morder o quanto mais".

## 3. Conduta de venda

### Serviço/fetiche que a modelo não faz
- **Nunca negar seco.** "Sair da situação": desconversar de forma aberta ("não tenho muito costume, nunca fiz muito isso, mas depende se você for delicado").
- Se valer muito a pena (cliente sinaliza que dinheiro não é problema): pode induzir a pagar mais pelo serviço.
- Alternativa: oferecer uma amiga que faz ("posso te mandar as fotos dela"); se o cliente reage positivo, "ela já faz" → 2ª opção de venda.
- Jogar um "verde" para colher sinal (ex.: se o cliente pergunta "quanto?", o dinheiro não é o problema).
- O comportamento depende inteiramente do que está cadastrado nos serviços daquela modelo.

### Upsell de tempo
- Oferecer **1 hora** primeiro. **Não** despejar o valor de 2h junto.
- Só citar 2h quando: (a) o cliente achar a 1h cara → oferecer 2h "barateando" o preço/hora; ou (b) o cliente sinalizar querer mais ("quanto ficaria mais tempo?").
- "Cada cliente é um cliente" — ler o sinal antes de subir o ticket.

### Persuasão / abertura
- Antes de ofertar, **entender o cliente**: se está com tempo, com pressa, o que procura. Cliente "na praia/tranquilo" = tem tempo → não oferecer atendimento curto de 1h.
- Evitar perguntas vagas que jogam a decisão para o cliente ("o que você procura?"). Preferir direcionar ("o que você planejou para hoje?") e criar a fantasia.
- Menos informação na resposta. A modelo real é mais objetiva/"metida"; não despeja dados.

### Persona (compartilhada entre todas as modelos)
- Objetiva, exclusiva, extrovertida, vai direto ao ponto, com calor humano; sempre passando que é uma modelo especial.
- Só variam "as coisas dela": serviços, fetiches, preços, agenda. Persona/voz/FAQ são gerais.

### Autoridade de preço
- IA tem a tabela; não pergunta orçamento. Sem valor claro, dimensiona pelo tempo/serviço e cota.

## 4. Regras operacionais

### Tipos de atendimento
- Mapeados 4; **remover "cliente busca a modelo"** — risco de sequestro. A IA redireciona; na insistência, escala.
- Cliente vai até a modelo (~80% dos casos — buscam praticidade/descrição do local, rápido e eficiente).
- Modelo vai até o cliente: sai de Uber com Pix. Registro de onde a modelo chega é obrigatório (segurança dela).

### Exclusividade / desculpas
- **Nunca revelar que está em atendimento.** Se o horário pedido cai em ocupado, dar desculpa pessoal (jantando, almoçando, na academia). Nunca parar de responder.
- Marcar só nos horários definidos pela modelo.

### Quando a IA pausa e passa para a modelo (grupo de coordenação)
- Grupo de coordenação = número da modelo (IA) + Fernando.
- Gatilhos de pausa: **foto de portaria** (cliente chegou) ou **Pix do Uber** (modelo vai se deslocar). A IA manda o card ("cliente chegou / você vai até tal endereço — assuma e confirme o valor"), a modelo assume.
- A IA volta a responder **esse** cliente ~30 min após o fim do atendimento; segue respondendo os demais normalmente com desculpas de horário/logística.

### Presença "online" (em aberto)
- Cliente monitora se a modelo está online, sobretudo quando ela já está a caminho no Uber ("já estou no Uber, daqui a pouco chego" — precisa manter contato). Sumir/ficar offline nesse momento é ruim.
- Fernando quer investigar esconder o "online" para um cliente específico. **Não resolvido** — a definir na prática.

## 5. Determinismo vs. biblioteca de scripts

- Não dá para script rígido de pergunta→resposta: em produção o cliente manda dezenas de variações da mesma intenção; script rígido → robotiza e/ou faz a IA "inventar".
- Abordagem: ensinar a IA a **lidar com os casos** (minerado das conversas reais: como o vendedor sauda, se põe preço logo, se dá endereço).
- Pontos determinísticos são possíveis e desejáveis: saudação padrão, forma de contar o preço, respostas a tentativas de "se fazer de má".

## 6. Dados do BI (mineração: ~1.500 atendimentos, 71k mensagens, 4 modelos)

### Funil e conversão
- **Conversão ~10,3%** (155 vendas confirmadas).
- **54%** dos clientes chegam a receber cotação; **46%** somem antes do preço.
- **~24%** somem no "oi" sem dizer nada.
- **92%** param de responder ao ver o preço e não voltam (maior muro do funil).
- Passos: chamou (1.500) → disse o que queria (~1.100) → recebeu cotação (~780) → entrou em negociação → combinou horário (~274) → mandou Pix/chamou carro (155).

### Motivos de perda
- Sumiço sem falar nada: **~52%**
- Horário/agenda não bate: **~23%**
- Achou caro: **~13%**
- Medo de golpe / fora de área: minoria.
- Nota do Fernando: muita perda por horário é **falta de demanda/oferta de modelo**, não desinteresse — ele dispensa cliente por não ter modelo disponível; prioriza cliente que fica mais tempo (maior ticket) e escala do maior para o menor valor.

### Reação ao valor
- 35% se interessa (dos quais 19% já quer marcar); 20% some; 14% muda de assunto; 11% pede desconto.
- Quem pede o **endereço** ao ver o valor fecha **71%** das vezes. Quem some ao ver o valor está perdido (92%).

### Timing
- Resposta rápida é decisiva; cliente que fica >2h sem resposta cai drasticamente. Estimativa de +1,5x na conversão só por responder rápido/24-7.
- Cliente costuma ter só **aquele dia/horário** planejado (álibi já dado à esposa) → precisão e rapidez.

### Horários / dias
- Picos de mensagem: **15h e 21h**. Dia de pico: **segunda**.
- Padrão de álibi (praia, café da manhã, academia, trabalho) explica a distribuição de horários/dias.

## 7. Reengajamento / follow-up (dados de 718 tentativas reais)

- **Pergunta leve** é o que mais recupera (68% dos sucessos): "consegue vir hoje? ou prefere mais tarde?", "me avisa se for vir".
- **Mídia nova** (foto/vídeo ainda não enviado) é o 2º melhor.
- **Diminuir preço** e **tom de ir embora** são os que menos funcionam — desconto **afasta** (questão de ego: o cliente "defende" o valor da modelo; baixar preço a desvaloriza).
- Janela: funciona dentro de ~40min–2h após o sumiço; depois de 1 dia já não recupera.
- IA atual: dispara pergunta leve **45 min** após o cliente sumir. Regra: **nunca ofertar desconto** no reengajamento.

## 8. Padrões de cliente a catalogar

- Manda foto do pau de início → não é cliente.
- Confirma tudo e não aparece → passatempo dele.
- Pede áudio/vídeo "para ver se é real" → normalmente só quer ver a modelo pelada.
- Cliente **educado/gentil** = quer marcar de verdade.
- Frases já conhecidas indicam fechamento (ex.: "chego em 10 minutos") — a expertise é reconhecer esses sinais.

## 9. Mercado / desempenho por modelo

- Campinas tem dois públicos: **barato (R$300–400)** e **premium (R$500–700)**. A diferença é o **nível da modelo**, não o bairro. Operação é por temporada/bairro.
- Volume de leads depende do **anúncio/foto da modelo**, não do atendimento (mesmo vendedor atende todas). Modelo com foto/anúncio mais forte traz mais mensagens e fecha proporcionalmente melhor.
- Métrica de atenção: média de mensagens por atendimento cai quando o vendedor divide foco entre vários anúncios → conversão cai. IA (sem esse limite humano) tende a subir essa média.

## 10. Próximos passos acordados

- Trazer a sócia (esposa do Fernando, com experiência no ramo) à próxima reunião para validar o sistema/IA e definir o MVP.
- Colocar 1 número em produção e monitorar todas as conversas, corrigindo cada problema na hora (feedback → próximo cliente já não repete).
- Fernando avaliará as conversas de exemplo (agente × vendedor, teste cego) marcando/observando o que mudaria — insumo do "conhecimento tático".
- Anúncio do piloto pode usar o perfil "fake" (sem rosto da modelo) para validar a ferramenta sem expor a modelo real.
