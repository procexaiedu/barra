"""Estado do grafo LangGraph.

Espelha a maquina de estados de docs/mvp/04 §8:
Novo -> Triagem -> Qualificado -> Aguardando_confirmacao -> Confirmado -> Em_execucao -> Fechado/Perdido.

State minimalista: `messages` + campos transitorios por-invocacao. Deps de runtime
(pool, redis) e IDs de escopo (atendimento_id, modelo_id, cliente_id, turno_id) vivem no
`ContextAgente` (Runtime Context API, em `agente/contexto.py`), injetado via
`graph.ainvoke(..., context=...)` -- nao no State nem em `config["configurable"]` (legado).
Ver docs/agente/04-tools.md §1.1, 01-arquitetura.md §2.3/§4.3 e 02-estado-fluxo.md §6.
"""

import asyncio
from datetime import datetime

from langchain_core.messages import BaseMessage
from langgraph.graph import MessagesState


class EstadoAgente(MessagesState):
    """Estado canonico do agente: mensagens + campos efemeros por-invocacao.

    Sem checkpointer no P0 (01 §6.7): todos os campos abaixo nascem zerados/ausentes a
    cada `ainvoke` e morrem com ele. Pausa (ia_pausada) NAO usa flag de State --
    prepare_context faz early exit via Command(goto=END) (02 §1).

    (O `call_idx` de `enviar_midia` NAO vive aqui. Existiu um campo `midia_idx` no State
    prometendo ser esse contador, mas ele nunca chegou a ser escrito nem lido: a idempotencia
    real e `nos/tools.py:_calcular_call_idx_midia`, que DERIVA o ordinal varrendo
    `state["messages"]`. Um contador de State seria pior -- ele conta chamadas na ordem em que
    o loop as executa, e a PK precisa do ordinal por `tool_call_id`, que e estavel no replay.
    O campo foi removido em 12/08; a docstring o descrevia com semantica que o codigo nao tinha,
    que e como o proximo leitor reintroduz o bug. Ver docs/agente/04-tools.md §3.3.)
    _categoria / _confianca: classificacao de disclosure/jailbreak gravada pelo
        prepare_context (regex sobre a cauda da janela), lida pelo intercept_disclosure
        para rotear canned/escala/llm (10 §8). _confianca e a string "alta" (ou None) que
        `classificar_janela` retorna -- nao um float. Ausentes => sem deteccao.
    _reoferta_tentada: one-shot da auto-reoferta (nos/extrair.py, settings.reoferta_automatica_habilitada).
        Quando a extracao (executada inline no no `extrair`) erra recuperavel (ConflitoAgenda etc.) e
        a reoferta esta ligada, o no volta ao llm p/ o modelo REOFERTAR um horario em vez de fechar
        mudo, e seta este flag. Se a reoferta tambem errar (o llm reoferta, o llm roteia de novo ao
        `extrair` e a 2a extracao erra), o `extrair` cai no MUTE (sem reofertar de novo) -- silencio >
        reserva fantasma. Nasce ausente a cada `ainvoke` (sem checkpointer).
    _mute_por_erro_de_tool: CARIMBO de que o `extrair` fechou o turno MUDO de proposito, porque a
        extracao errou (guard de dominio: piso, tipo, reagendamento, cotacao ausente) e a reoferta
        ja tinha sido gasta. E um carimbo, nao um predicado re-avaliavel: o `output_guard` roda
        DEPOIS e nao tem como redescobrir o motivo -- a janela que ele monta p/ a regen
        (`_janela_ate_a_fala_do_cliente`) corta na ultima HumanMessage e descarta, POR DESENHO, o
        par [AIMessage forcada, ToolMessage] que carrega o erro.

        Sem o carimbo, o gatilho `mudo` do guard via um turno sem texto, regenerava com o lembrete
        generico ("sua resposta veio VAZIA, escreva de novo") e o modelo -- cego ao erro --
        respondia "Confirmado amor", exatamente a reserva fantasma que o mute existe p/ impedir
        (trace 71c7196e, 12/08: a reoferta tinha ACERTADO a cotacao e a regen a substituiu pela
        confirmacao proibida). Nasce ausente a cada `ainvoke` (sem checkpointer).
    _midia_esgotada: one-shot do cap de loop de `enviar_midia` (nos/llm.py). Quando a modelo nao tem
        midia e o modelo insiste em `enviar_midia` (tag apos tag), o loop tools<->llm estouraria o
        recursion_limit -> GraphRecursionError -> escalar_por_exaustao -> SILENCIO ao cliente (trace
        8194e2c0). Ao ver >=2 `enviar_midia` com erro no turno, o no llm forca UMA resposta em texto
        (chat sem tools) e fecha, setando este flag p/ nao re-disparar. Nasce ausente a cada
        `ainvoke` (sem checkpointer).
    horario_minimo: o quanto antes a IA pode oferecer p/ um pedido imediato hoje (= o `<horario_minimo>`
        do contexto dinamico), computado por prepare_context (proximo_livre). `None` = now+buffer cai
        fora da Disponibilidade -> NAO ha horario valido mais tarde hoje. A tool `registrar_extracao`
        le este campo (`runtime.state.get`) p/ desambiguar a conduta de `AntecedenciaInsuficiente`:
        com valor, ancora no horario_minimo ("me arrumo, a partir das X"); `None`, cai na conduta de
        periodo de trabalho ("por hoje ja parei, amanha"). Sem ele a tool mandaria ancorar num
        horario_minimo inexistente e a IA inventaria um horario fora da janela. Reusa o VALOR ja
        renderizado (nao recomputa). Nasce ausente a cada `ainvoke` (sem checkpointer).
    horario_evidenciado: a janela do turno tem fala do CLIENTE que sustenta o horario
        (`_horario_evidenciado_no_turno`, prepare_context): hora explicita dele, confirmacao curta
        sobre a hora que a IA propos, ou o aceite da sondagem de imediatismo. A tool
        `registrar_extracao` o le e o repassa ao dominio, que carimba
        `atendimentos.horario_evidenciado` e (com horario gravado) promove a `intencao` a
        'agendamento'. Vive no State pelo mesmo motivo que `horario_minimo` (nasce no
        prepare_context, e consumido no `extrair`, sem recomputar nem acoplar no->no) e NUNCA sai
        do payload da extracao — esse e o canal contaminado pelo eco do belief. Nasce ausente a
        cada `ainvoke` (sem checkpointer).
    recuo_detectado: o burst do CLIENTE no turno carrega um recuo (`_recuo_no_turno`,
        prepare_context / `classificar_recuo`, _disciplina — o PORQUE mora la). A tool
        `registrar_extracao` o le e o repassa ao dominio, que REBAIXA
        `sinais_qualificacao.aceita_valor` no merge. Mesmo canal e mesmos motivos do
        `horario_evidenciado` (nasce no prepare_context, e consumido na extracao, nunca sai do
        payload). Nasce ausente a cada `ainvoke` (sem checkpointer).
    agora_turno / ja_registrado / conversa_crua: as pecas do contexto do turno que a janela
        DEDICADA da extracao monta (spec extracao-janela-dedicada) — ancora temporal (BRT naive),
        bloco de estado ja renderizado e a janela do par ANTES da anexacao do contexto dinamico e
        do lembrete (o que o extrator le como conversa; `messages` so tem a versao com o belief
        colado na cauda, e depois de fundida nao ha como separa-la). Nascem no prepare_context
        (`PecasDoTurno`, o PORQUE mora la), NAO entram em `messages` e nascem ausentes a cada
        `ainvoke` (sem checkpointer).
    local_endereco_no_prompt: o ponto de encontro EXATAMENTE como o `<local_de_encontro>` deste
        turno o apresentou ao modelo (nome do local + endereco no degrau vigente), ou None quando
        o bloco NAO entrou no prompt. E um CARIMBO da decisao do prepare_context, nao um predicado
        re-avaliavel: o `output_guard` decidia se cobrar a entrega do endereco reavaliando
        `_libera_local_de_encontro` com a linha RELIDA depois da extracao, e no turno em que o
        cliente escolhe "no seu local" a extracao promove NULL->interno no meio do turno — o prompt
        saia sem o bloco e o guard exigia entregar um dado que o modelo nao tinha; ele inventou a
        rua (trace 648d7f6f, agenda_local t3). Carimbando a decisao, o gatilho `endereco` so arma
        sobre o que o modelo de fato leu, e o lembrete da regen cola o dado LITERAL daqui em vez de
        citar uma tag condicional pelo nome. Nasce ausente a cada `ainvoke` (sem checkpointer).
    valor_dele_no_prompt: o numero que o `<valor_dele_serve>` deste turno mandou ela ACEITAR
        (ADR-0040), ou None quando o bloco NAO entrou no prompt. Carimbo da decisao do
        prepare_context, pela mesma razao do `local_endereco_no_prompt` — e nao um predicado
        re-avaliavel: quem o consome e o write-time (`workers/envio.py`), depois de o turno ja ter
        andado (a extracao pode ter mexido em `valor_acordado`/`n_contrapropostas` no meio, e
        reavaliar `aceite_do_valor_dele` la daria OUTRA resposta sobre a fala que ja saiu).
        Existe porque o aceite do valor DELE e decidido pela FALA DA IA do proprio turno, e a
        extracao e cega para ela por contrato (a janela dela exclui a fala do turno corrente,
        nos/extrair.py): no trace 93fa67dd a IA aceitou "faz 700 que eu vou" em cima de 800 e o
        `valor_acordado` ficou NULL, porque do ponto de vista do extrator ainda nao havia aceite
        nenhum a registrar. Com o carimbo, o valor da venda vai pela mesma porta deterministica
        que ja carimba `n_contrapropostas`: le a bolha DEPOIS de despachada. Nasce ausente a cada
        `ainvoke` (sem checkpointer).
    _extracao_task / _extracao_janela: o braco PARALELO da chamada forcada da extracao
        (settings.extracao_paralela_habilitada, nos/extrair.py:`DisparoExtracao`). O no `llm`
        dispara a chamada como `asyncio.Task` no comeco do turno e publica aqui a Task + a JANELA de
        onde ela saiu; o no `extrair` remonta a janela real e so consome a Task se as duas baterem
        (senao cancela e chama em serie). Nascem ausentes a cada `ainvoke`.

        ⚠️ `_extracao_task` guarda um objeto NAO-SERIALIZAVEL (`asyncio.Task`) no State. Isso so e
        legitimo porque o grafo compila SEM checkpointer (graph.py, decisao 01 §6.7): nada tenta
        serializar o State. Ligar um checkpointer QUEBRA este campo (o serializer do saver estoura
        no Task) — nesse dia, o campo tem de sair do State e virar registro por-turno fora dele
        (ex.: dict keyed por `turno_id` no escopo da factory). O mesmo vale, em menor grau, para
        `_extracao_janela` (lista de BaseMessage, serializavel, mas volumosa e redundante com
        `messages`). O guard que torna isso barulhento em vez de silencioso vive em
        `build_graph` (graph.py): ligar checkpointer COM a flag paralela levanta na construcao do
        grafo, nao num turno de producao.
    """

    _categoria: str | None
    _confianca: str | None
    _reoferta_tentada: bool
    _mute_por_erro_de_tool: bool
    _midia_esgotada: bool
    horario_minimo: datetime | None
    horario_evidenciado: bool
    recuo_detectado: bool
    agora_turno: datetime | None
    ja_registrado: str
    conversa_crua: list[BaseMessage]
    local_endereco_no_prompt: str | None
    valor_dele_no_prompt: int | None
    _extracao_task: "asyncio.Task[BaseMessage] | None"
    _extracao_janela: list[BaseMessage]
