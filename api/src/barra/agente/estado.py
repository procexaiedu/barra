"""Estado do grafo LangGraph.

Espelha a maquina de estados de docs/mvp/04 §8:
Novo -> Triagem -> Qualificado -> Aguardando_confirmacao -> Em_atendimento -> Concluido/Perdido.

State minimalista: so `messages`. IDs de escopo (atendimento_id, modelo_id, cliente_id,
turno_id) vivem em `RunnableConfig.configurable`, nao no State -- evita duplicar verdade
entre Postgres e checkpoint do grafo. Ver docs/agente/02-estado-fluxo.md §6.
"""

from langgraph.graph import MessagesState


class EstadoAgente(MessagesState):
    """Estado canonico do agente. So mensagens; tudo mais por RunnableConfig."""

    pass
