"""Estado do grafo LangGraph.

Espelha a maquina de estados de docs/mvp/04 §8:
Novo -> Triagem -> Qualificado -> Aguardando_confirmacao -> Em_atendimento -> Concluido/Perdido.

State minimalista: `messages` + campos transitorios por-invocacao. Deps de runtime
(pool, redis) e IDs de escopo (atendimento_id, modelo_id, cliente_id, turno_id) vivem no
`ContextAgente` (Runtime Context API, em `agente/contexto.py`), injetado via
`graph.ainvoke(..., context=...)` -- nao no State nem em `config["configurable"]` (legado).
Ver docs/agente/04-tools.md §1.1, 01-arquitetura.md §2.3/§4.3 e 02-estado-fluxo.md §6.
"""

from langgraph.graph import MessagesState


class EstadoAgente(MessagesState):
    """Estado canonico do agente: mensagens + campos efemeros por-invocacao.

    Sem checkpointer no P0 (01 §6.7): todos os campos abaixo nascem zerados/ausentes a
    cada `ainvoke` e morrem com ele. Pausa (ia_pausada) NAO usa flag de State --
    prepare_context faz early exit via Command(goto=END) (02 §1).

    midia_idx: contador determinístico de chamadas a `enviar_midia` no turno corrente.
        Nasce 0 a cada `ainvoke` (sem checkpointer o State e efemero) e e injetado como
        `call_idx` (InjectedToolArg) pelo no `tools`. Garante a idempotencia de
        `enviar_midia` no replay -- reinicia em 0, entao o `ON CONFLICT` deduplica e
        nao reenvia (jamais usar `COUNT(*)` no DB para isso). NAO e verdade duplicada do
        Postgres, e sim estado de controle do loop -- por isso vive aqui, nao no ContextAgente.
        Lido com `state.get("midia_idx", 0)`. Ver docs/agente/04-tools.md §3.3.
    _categoria / _confianca: classificacao de disclosure/jailbreak gravada pelo
        prepare_context (regex sobre a cauda da janela), lida pelo intercept_disclosure
        para rotear canned/escala/llm (10 §8). _confianca e a string "alta" (ou None) que
        `classificar_janela` retorna -- nao um float. Ausentes => sem deteccao.
    _extracao_forcada: guard do fallback deterministico de extracao (#2, nos/llm.py). O no
        llm o seta True ao forcar registrar_extracao no fim do turno; na reentrada pos-`tools`
        ele fecha o turno (goto post_process) SEM reinvocar o modelo -- evita bolha dupla e
        loop infinito de forcamento. Nasce ausente a cada `ainvoke` (sem checkpointer).
    _resposta_inline_concluida: irmao inline do _extracao_forcada (nos/llm.py). O no llm o seta
        True quando a 1a passagem ja emitiu texto ao cliente E so pediu registrar_extracao na
        MESMA AIMessage (padrao do DeepSeek V4 Flash; o Sonnet responde OU extrai). A tool de
        escrita nao devolve nada acionavel, entao a reentrada do ReAct nao tem o que reprocessar:
        o guard fecha no post_process sem reinvocar o modelo -- senao o DeepSeek tagarela uma 2a
        bolha espuria (trace 022e0a70, 2026-06-18). Nasce ausente a cada `ainvoke`.
    """

    midia_idx: int
    _categoria: str | None
    _confianca: str | None
    _extracao_forcada: bool
    _resposta_inline_concluida: bool
