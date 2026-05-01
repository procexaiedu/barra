# 01 — Contexto do Negócio e Problema

> **Projeto:** Sistema de Gestão de Atendimento com IA para a operação Barra Vips  
> **Cliente / operador:** Fernando — proprietário da agência de acompanhantes de luxo Barra Vips, no Rio de Janeiro, com 10 anos de mercado.  
> **Time de tecnologia:** Lucas e sócio (Campinas), em modelo de participação percentual nas vendas geradas pelo sistema.  
> **Base:** Ata de Reunião de Alinhamento Estratégico — Projeto Barra Vips.

---

## 1. O negócio que está sendo digitalizado

Fernando opera a **Barra Vips**, uma agência de acompanhantes de luxo no Rio de Janeiro. Os perfis das modelos são publicados no site de anúncios BarraVips, por onde os clientes chegam organicamente. Hoje, a operação acontece quase inteiramente por WhatsApp, em telefones físicos gerenciados manualmente por vendedores.

### Posicionamento da agência

- Segmento **premium**, com modelos cobrando cerca de **R$ 1.000/hora**, acima ou no topo da média do mercado.
- Diferencial das modelos: multilíngues, sofisticadas, cultas e com experiência internacional.
- Cliente-alvo: homens **classe A ou B+**, executivos, empresários e clientes de alto poder aquisitivo que buscam companhia para experiências sofisticadas, como jantar, lancha e eventos sociais.

### Escala da operação

- **Baixa temporada:** 4 a 8 modelos ativas.
- **Alta temporada:** 10 a 15 modelos, especialmente em Carnaval, Rock in Rio, Réveillon e grandes eventos.
- Cada vendedor humano gerencia entre 3 e 5 modelos simultaneamente.
- Horário de funcionamento: 10h às 2h durante a semana em baixa temporada; 24h em finais de semana e datas comemorativas.

### Modelo de remuneração

- As modelos recebem o pagamento do cliente e repassam **30%, 40% ou 50%** para Fernando, conforme acordo individual.
- O time de tecnologia recebe **percentual sobre as vendas geradas** pelo sistema, alinhando incentivos com a operação.
- No registro de fechamento, `valor_final` significa o valor total bruto pago pelo cliente. Quando houver percentual acordado cadastrado para a modelo, o repasse de Fernando/agência é calculado a partir do snapshot desse percentual no fechamento; se não houver percentual cadastrado, o fechamento continua permitido e o repasse fica pendente/nulo.

---

## 2. Fernando como operador principal

Fernando é o **operador principal e único usuário-decisor da interface administrativa** no MVP. Com 10 anos de experiência, construiu sua metodologia por tentativa e erro e concentra um conhecimento operacional detalhado sobre:

- bairros seguros e perigosos do Rio;
- motéis, flats, hotéis e zonas de risco;
- comportamento típico de cliente que fecha vs. cliente que perde tempo;
- horários e sazonalidade do mercado;
- perfil de cada modelo, suas particularidades e seus limites.

Esse conhecimento tácito precisa ser progressivamente convertido em regras, fluxos e dados operacionais. O objetivo do sistema é tirar Fernando do acompanhamento manual de múltiplos telefones sem fazê-lo perder controle da operação.

---

## 3. Problema central

A Barra Vips recebe oportunidades comerciais qualificadas pelo BarraVips, mas opera em uma estrutura artesanal: múltiplos telefones físicos, conhecimento concentrado em Fernando, ausência de dados estruturados e dependência da qualidade individual dos vendedores. Isso torna difícil escalar sem comprometer o padrão premium da agência.

As principais dores são:

- atendimento manual em **10 a 15 telefones físicos** durante alta temporada;
- dificuldade de acompanhar várias conversas qualificadas ao mesmo tempo;
- **mais de 15.000 contatos acumulados** em 10 anos, sem histórico estruturado ou remarketing;
- ausência de métricas confiáveis sobre horário de pico, conversão, motivo de perda, performance por modelo, performance por vendedor e sazonalidade;
- decisões baseadas no “feeling” e na memória operacional de Fernando;
- perda de oportunidades quando o vendedor erra o tom, demora ou quebra a persona da modelo;
- gestão informal de agenda, sem visão centralizada;
- banimentos recorrentes de números do WhatsApp, que quebram histórico e exigem ressincronização manual;
- dificuldade de detectar, de forma sistemática, divergências entre valores recebidos pelas modelos e repasses ao operador.

A tecnologia é vista como o caminho para reduzir o gargalo operacional, preservar a qualidade do atendimento e permitir crescimento controlado.

---

## 5. Perfil obrigatório da IA de atendimento

A IA de atendimento **simula a comunicação da própria modelo** durante a conversa. Fernando definiu quatro atributos inegociáveis:

- **Objetiva:** direta ao ponto, sem rodeios e sem perguntas que não conduzam à decisão. O cliente premium quer informação prática e resposta rápida.
- **Exclusiva:** transmite sensação de raridade, sofisticação e diferenciação.
- **Extrovertida:** calorosa, simpática e envolvente. Arrogância ou antipatia prejudicam a venda.
- **Inocente / estrangeira:** transmite a impressão de alguém que não conhece profundamente o Rio, reforçando a aura internacional da modelo.

Credibilidade é crítica: contradições, mensagens apagadas, correções bruscas ou inconsistências podem gerar desconfiança e fazer o cliente abandonar a conversa.

---

## 6. Atores e papéis no sistema

| Ator | Papel | Onde aparece no sistema |
|------|-------|-------------------------|
| **Fernando** | Operador principal, dono da agência e decisor único no MVP | Painel no MVP; IA Administrativa por áudio em P1 |
| **Vendedores** | Observam conversas em modo **read-only** no MVP | Chatwoot, como “câmera de segurança” |
| **Modelos / profissionais** | Profissionais cadastradas, cada uma com agenda própria e acesso ao próprio WhatsApp; não acompanham todas as mensagens da IA, mas assumem a conversa no mesmo número quando houver handoff | Cadastro + Agenda + grupo de Coordenação por modelo com **2 participantes** (número da modelo operado pela IA + Fernando) |
| **Clientes finais** | Homens classe A/B+, executivos e clientes premium desconfiados | WhatsApp, interagindo com a IA como se falassem com a modelo |
| **IA de Atendimento** | Persona pública, opera no número de WhatsApp da modelo e conduz a conversa até fechar ou escalar | WhatsApp da modelo |
| **IA Administrativa (P1)** | Recebe comandos por áudio de Fernando para editar agenda, consultar comprovantes e executar ações administrativas internas | Grupo interno para Fernando falar com a IA Admin |
| **Time de tecnologia** | Lucas e sócio, responsáveis por desenvolvimento e operação do sistema | Parceria por percentual de vendas |

---

## 7. Escopo inicial do MVP

O foco inicial **não é** criar uma IA totalmente autônoma nem uma plataforma completa de turismo de luxo. O foco é construir uma **central operacional com IA assistiva**, rodando no WhatsApp, capaz de:

- conduzir conversas de clientes premium que chegam pelo BarraVips, respeitando a persona e as restrições do canal;
- consultar agenda da modelo piloto e permitir bloqueios pelo painel;
- escalar decisões sensíveis para Fernando e acionar a modelo apenas quando ela precisar agir operacionalmente;
- registrar dados operacionais conforme inventário do MVP ([02-mvp-escopo.md](02-mvp-escopo.md), §2.2 — ficha de atendimento), em substituição progressiva a decisões só baseadas em feeling.

