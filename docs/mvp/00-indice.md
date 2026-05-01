# 00 — Índice do Plano de MVP — Central Inteligente de Atendimento e Operação com IA

> **Projeto:** Sistema de Gestão de Atendimento com IA para a operação Barra Vips
> **Origem:** Quebra do `plano_mvp_central_inteligente_atendimento.md` em arquivos menores para facilitar uso seletivo de contexto durante o desenvolvimento.

## Como usar

Cada arquivo cobre um domínio específico do plano. Carregue apenas os arquivos relevantes para a tarefa em andamento — não é necessário ler todos.

## Mapa de arquivos

| Arquivo | Conteúdo | Quando consultar |
|---------|----------|-------------------|
| [01-contexto-negocio.md](01-contexto-negocio.md) | Contexto Barra Vips, Fernando, persona da IA, atores, problema, resumo executivo | Para entender o negócio, o cliente, o porquê do projeto |
| [02-mvp-escopo.md](02-mvp-escopo.md) | Objetivos do MVP, princípios do produto, P0/P1, fora do escopo | Para decidir se algo entra no MVP ou não |
| [03-modulos-sistema.md](03-modulos-sistema.md) | Central de Atendimentos, Agenda, IA de Atendimento, CRM, Mídia, Dashboard e IA Administrativa P1 | Para implementar qualquer módulo do sistema |
| [04-fluxos-operacionais.md](04-fluxos-operacionais.md) | Fluxo geral, interno, externo (saída), agenda por áudio P1, perda por timeout, tipologia de cliente, mídia, máquina de estados | Para implementar lógica de conversa, agenda ou Pix |
| [05-escalada-regras-ia.md](05-escalada-regras-ia.md) | Regras de escalada humana, handoff via grupo, regras gerais e bloqueios da IA | Para configurar a IA ou fluxo de handoff |
| [06-dados-interfaces.md](06-dados-interfaces.md) | Entidades (Profissional, Cliente, Atendimento, Bloqueio) + telas | Para modelar banco e construir UI |
| [07-stack-tecnica.md](07-stack-tecnica.md) | Stack escolhida (Python/FastAPI + LangGraph + Supabase/Postgres + MinIO + Next) | Para decisões de infraestrutura e hospedagem |


## Definição em uma frase

> Uma central simples, com agenda, CRM básico e IA de triagem, operando com uma profissional piloto, escalando decisões sensíveis para Fernando e acionando a modelo apenas quando ela precisar agir operacionalmente.

## Persona da IA (resumo)

A IA de atendimento simula a comunicação da própria modelo. Quatro atributos inegociáveis: **objetiva, exclusiva, extrovertida, inocente/estrangeira**. Qualquer inconsistência mata a venda. Detalhes em [01-contexto-negocio.md](01-contexto-negocio.md).

## Regra de ouro

> Se a IA não tiver certeza, ela escala para Fernando. Improviso é proibido — uma palavra errada perde o cliente premium e não tem como recuperar.
