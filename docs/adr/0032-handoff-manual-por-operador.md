---
status: accepted
---

# ADR-0032 — Handoff manual por operador, escopo por Atendimento

## Contexto

Todo `Handoff` hoje nasce de um gatilho **automático** do state machine (Pix recebido, Foto de portaria, Lembrete de fechamento sem resposta — ver `atendimentos.ia_pausada`/`ia_pausada_motivo`). Não existe ação para Fernando ou a modelo pausarem a IA **por decisão livre**, no meio de uma conversa, sem que o domínio já tenha disparado o evento. Na reunião de colocação da IA em produção (2026-07-20), o plano de monitoramento em tempo real depende exatamente disso: "a IA respondeu algo não legal — já pode desabilitar para a gente assumir".

## Decisão

- **Novo gatilho de Handoff: manual, por operador.** Endpoint equivalente ao `/devolver` já existente, só que na direção inversa (pausa em vez de reativa) — Fernando ou a modelo pode pausar a IA para um Atendimento específico a qualquer momento, sem depender de Pix/Foto/timeout.
- **Escopo = Atendimento aberto**, igual a todo Handoff hoje — **não** a Conversa cliente inteira. Quando esse atendimento fecha (`Fechado`/`Perdido`) e um novo nasce por recorrência, a IA volta ativa por padrão nesse novo atendimento.
- Reativação segue a **Devolução** já existente (`IA assume`/`IA assume #N` no grupo, botão no painel).
- O campo `conversas.ia_pausada` (definido no schema mas nunca lido/escrito) **não** é usado para isso — permanece órfão; se um dia for necessário pausar no nível da Conversa cliente (P1), é decisão à parte.

## Alternativas rejeitadas

- **Escopo por Conversa cliente** (usar o campo `conversas.ia_pausada` já existente). Rejeitada para o piloto: mais forte que o necessário — o pedido da reunião é "não gostei dessa resposta, eu assumo agora", não "esse cliente nunca mais fala com a IA". Reabrir se o piloto mostrar necessidade real de pausa persistente por cliente.
- **Só o on/off global da Modelo (`modelos.status`).** Rejeitada — grosso demais; pausaria a IA para todos os clientes da modelo por causa de uma resposta ruim com um único cliente.

## Consequências

- Novo endpoint em `dominio/atendimentos/routes.py` (ou comando de card equivalente na Coordenação por modelo) para pausar sem gatilho automático — reaproveita a mesma coluna `ia_pausada`/`ia_pausada_motivo` (motivo novo, ex. `pausa_manual_operador`).
- CONTEXT.md `Handoff` atualizado para descrever os dois tipos de gatilho (automático vs. manual) e reafirmar o escopo por Atendimento.
