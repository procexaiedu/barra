# Domínio — painel-only e fora do P0

Verbetes extraídos do `CONTEXT.md` para não pesarem no contexto de toda sessão. São conceitos que a **IA conversacional nunca lê nem escreve**, ou que ainda não existem no P0.

O `CONTEXT.md` mantém o ponteiro e o invariante resumido; aqui fica a definição completa. **Mesma regra de precedência:** onde divergir de um ADR não-superseded, o ADR vence.

## Painel-only / Fernando

**Perfil físico preferido**:
Tipo físico que o cliente prefere (loira, morena, ruiva, negra, asiática, outra). Dado **global do cliente** e **painel-only/Fernando**, com duas leituras: a **declarada** (Fernando marca uma ou mais) e a **calculada** (breakdown dos `Fechado` agrupados pelo `tipo_fisico` das modelos atendidas — "6 ruivas, 2 loiras", expondo também quantos fechados são de modelos não classificadas). A IA conversacional nunca lê o breakdown (seria agregação cross-modelo, fura o isolamento por par) nem escreve a preferência — isso é **IA Admin** (P1). Eixo único (não separa cabelo/etnia/biotipo; biotipo fica de fora). O filtro de clientes usa só a parte **declarada**, semântica OR. Classificar `tipo_fisico` é pré-condição da parte calculada (sem ela o breakdown é parcial mas válido; modelos existentes nascem sem `tipo_fisico`, sem backfill). Ver ADR 0006.
_Avoid_: tratar como dado por par; expor à IA conversacional; inferir um rótulo único ("prefere X") do breakdown; materializar biotipo; customizar a persona por preferência.

**Dados cadastrais da modelo**:
Ficha pessoal para gestão — RG, CPF, endereço residencial (distinto do operacional), cor de pele, cor de cabelo, altura, tamanho do pé. Descreve **quem a pessoa é**, diferente do **tipo físico** (balde de venda, que alimenta a parte calculada do **Perfil físico preferido**) e do **Perfil físico preferido** (preferência do cliente). **Painel-only/Fernando**; RG, CPF e endereço residencial são **PII sensível**. A IA nunca lê nem usa esses campos. Cor de pele/cabelo são eixos próprios da ficha, separados do tipo físico e podendo divergir dele de propósito. Ver ADR 0007.
_Avoid_: confundir com **tipo físico** ou **Perfil físico preferido**; expor à IA / interpolar na persona; tratar RG/CPF/endereço residencial como dado não sensível.

**Mapa de clientes**:
Visão agregada do painel (exclusiva de Fernando) que plota cada cliente como um pin no mapa do Brasil pela coordenada (`latitude`/`longitude`) do **atendimento externo** mais recente — para ler a concentração geográfica da demanda. Atendimentos **internos** ficam de fora (o endereço é o ponto de encontro na modelo); cliente sem externo geocodificado entra num contador "sem localização" em vez de sumir. Cross-modelo por natureza, por isso painel-only e nunca acessado pela IA. Os totais por pin (nº de atendimentos e **Valor final** somado dos `Fechado`) agregam todas as modelos do cliente. Ver ADR 0008.
_Avoid_: plotar interno como localização do cliente; mapa por cliente individual; expor à IA; tratar pin ausente como erro.

**Tarefa**:
Item de gestão interna (estilo ClickUp enxuto), **painel-only/Fernando** e **desconexo do domínio de atendimento** (sem cliente, IA ou agenda). Tem **status** (`a_fazer`/`fazendo`/`feita`), **prioridade** (`baixa`/`media`/`alta`) e **prazo** (`date` opcional, sem hora); aparece como lista filtrável, board Kanban de 3 colunas e widget "Tarefas de hoje". O **Responsável** é um **ator polimórfico** (`usuario` | `modelo` | `vendedor`) usado só como **rótulo de execução** — sem login, permissão ou notificação (forward-compat para um multi-principal que o MVP não implementa). Ver ADR 0017.
_Avoid_: confundir o **Responsável** com o **Vendedor** do atendimento ou supor que ele loga/é notificado; confundir com o **Card**; atribuir RBAC no P0.

## Fora do P0 (planejado para P1)

**IA Admin (P1)**:
Grupo persistente entre IA e Fernando para alertas de exceção e comandos internos. Só no P1; no P0, decisões sensíveis chegam pelo painel e/ou pela **Coordenação por modelo**.
_Avoid_: grupo da modelo; handoff do vendedor; tratar como infra P0.

**Reativação (P1)**:
Disparo em massa **iniciado por Fernando** no painel que reabre clientes **dormentes** de uma modelo para buscar um **segundo atendimento** — toque quente e curto (**sem desconto**), enviado pelo número da própria modelo (IA), só a clientes que **já tiveram atendimento com ELA** e não voltaram. **Respeita o isolamento por par**: a IA da modelo X só toca clientes do par (cliente, X), **nunca cross-modelo** (ao contrário do **Mapa de clientes**/**Perfil físico preferido**, painel-only). Fernando escolhe o segmento (só `Fechado`, ou incluir `Perdido`/`sumiu`); quando o cliente responde, a IA conduz um **novo Atendimento** (recorrência) nas regras normais — qualquer desconto sai da negociação da IA, não da campanha. **No P0 não existe; planejada para P1.**
_Avoid_: confundir com **Reengajamento** (automático, por atendimento aberto silenciado pós-cotação, vs. campanha manual por cliente dormente); disparo cross-modelo (fura o isolamento por par); promo/desconto autônomo da IA no toque; tratar o toque como abertura de **Atendimento** (o atendimento nasce quando o cliente engaja).
