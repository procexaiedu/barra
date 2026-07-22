"""Tool de escrita registrar_extracao (04 §3.1).

Wrapper fino: idempotencia (`_executar_idempotente`) + delega a regra de dominio para
`dominio/atendimentos/service.py:registrar_extracao_ia` (UPSERT do snapshot + transicao de
estado + bloqueio previo interno + guarda do piso de desconto). O pin de endereco e o pin de
side-effect: enfileirado APOS o commit, simetrico ao card do escalar (Notas, 04 §3.1).
"""

from datetime import date, time
from decimal import Decimal
from typing import Annotated, Literal

from langchain_core.tools import ToolException, tool
from langgraph.prebuilt import ToolRuntime
from pydantic import BaseModel, ConfigDict, Field

from barra.core.metrics import AGENTE_TOOL_ERRO_RECUPERAVEL
from barra.dominio.agenda.service import (
    AntecedenciaInsuficiente,
    ConflitoAgenda,
    ForaDisponibilidade,
    HorarioNaoDefinido,
)
from barra.dominio.atendimentos.service import (
    CotacaoAusente,
    ParPrecoDuracaoInvalido,
    registrar_extracao_ia,
)

from ..contexto import ContextAgente
from ._idempotencia import _executar_idempotente


class SinaisQualificacao(BaseModel):
    """Sinais booleanos detectados; inclua só os True."""

    model_config = ConfigDict(extra="forbid")

    informa_horario: bool = Field(False, description="cliente disse um horário concreto que quer")
    informa_local: bool = Field(False, description="cliente informou bairro/endereço/tipo de local")
    aceita_valor: bool = Field(
        False, description="cliente concordou com o valor cotado (não apenas perguntou o preço)"
    )
    envia_pix: bool = Field(
        False, description="cliente alegou ter enviado o Pix ou mandou comprovante"
    )
    responde_objetivamente: bool = Field(
        False,
        description="cliente responde direto às perguntas, sem enrolar — sinal de intenção real",
    )


# Descricoes LLM-visiveis dos args achatados (04 §3.4, mesmo padrao do `escalar`): vivem na
# ASSINATURA da tool (Annotated+Field), nao no model — o ExtracaoPayload abaixo e so validacao
# interna reconstruida no corpo, fora do schema enviado ao LLM.
_DESC_HORARIO = (
    "Horário de relógio do encontro (HH:MM). PREENCHA na PRIMEIRA vez que o cliente der o "
    "horário — não re-pergunte algo que ele já disse. Cravou uma hora ('22h', 'meio-dia') → "
    "use-a. Disse tempo RELATIVO/imediato → calcule a partir da hora atual (vem em "
    "<agenda agora=\"HH:MM\"> no contexto): 'agora/já/imediato' = a hora atual; 'daqui N "
    "min/horas' = hora atual + N (ex.: agora=22:30 e cliente diz 'daqui 1h' → preencha "
    "23:30; data_desejada=hoje, virando o dia se passar da meia-noite). É o que faz o "
    "atendimento AVANÇAR para Aguardando_confirmacao e te pausar na chegada. Se o encontro "
    "for em OUTRO dia (não hoje), grave data_desejada no MESMO turno junto com a hora — a "
    "reserva do slot usa os DOIS e, sem o dia, cai em HOJE (slot no dia errado). NÃO preencha em "
    "horário vago/aberto ('depois das 21h', 'à noite'): aí siga qualificando até cravar. "
    "CRÍTICO: se a hora foi VOCÊ que propôs ('consigo às 22h, fecha ?') e o cliente confirmou "
    "('pode', 'fechou', 'isso', 'pode ser'), esse sim É o horário — grave-o, não espere ele "
    "repetir o número. "
    "Depois de registrado, NÃO recalcule horário relativo nos turnos seguintes — omita o campo "
    "(o snapshot preserva o anterior); só reenvie se o CLIENTE pedir outro horário."
)
_DESC_DATA = (
    "Dia do encontro. PREENCHA na PRIMEIRA vez que o cliente DECLARA ou CONFIRMA um dia — não "
    're-pergunte o que já está combinado. Resolva palavras relativas contra <agenda hoje="..."> '
    "no contexto: 'hoje' = a data de hoje; 'amanhã' = hoje + 1; nome de dia da semana = a próxima "
    "ocorrência. CRÍTICO: se VOCÊ perguntou o dia ('seria hoje?', 'é pra hoje?') e o cliente "
    "confirmou ('sim', 'isso', 'pode ser', 'aham'), esse 'sim' É a data — grave o dia confirmado, "
    "NÃO trate como se ele 'ainda não tivesse informado'. Sem dia explícito a reserva assume hoje, "
    "então registrar o dia certo é o que evita o slot cair no dia errado. Recuo do cliente ('não "
    "sei o dia ainda') usa o campo `limpar`, não este."
)
_DESC_VALOR = (
    "Valor do SERVIÇO/programa fechado com o cliente — a base que o sistema confere contra o "
    "piso de desconto. SEMPRE grave JUNTO com duracao_horas (a duração do programa cotado) — "
    "sem a duração o sistema não consegue conferir o piso e escala à toa uma oferta válida. "
    "NUNCA grave aqui o Pix de deslocamento/uber (custo fixo à parte, NÃO é o valor do "
    "programa — gravá-lo faz o sistema achar que você fechou abaixo do piso e escalar à toa), "
    "nem um número que o cliente PROPÔS e você NÃO aceitou — só o valor efetivamente combinado. "
    "Na vídeo chamada (remoto), gravar o valor_acordado é o que dispara o Pix antecipado da "
    "chamada — sem ele o sistema não pede o Pix, então registre-o ao confirmar a chamada."
)
_DESC_INTENCAO = (
    "Intenção do cliente NESTE ponto da conversa. 'curiosidade' = só perguntando, sem sinal de "
    "marcar; 'cotacao' = quer saber preço/como funciona; 'agendamento' = quer MARCAR de fato "
    "(deu horário, aceitou o valor, 'vamos marcar', 'pode ser hoje'). Suba para 'agendamento' "
    "assim que ele demonstra querer marcar — é o que move o atendimento de Triagem para "
    "Qualificado. Na dúvida entre 'cotacao' e 'agendamento' com sinal claro de marcar, use "
    "'agendamento'."
)
_DESC_URGENCIA = (
    "Urgência do encontro. 'imediato' = ele quer AGORA/já/hoje com pressa ('to afim agora', 'da "
    "pra ser já?'); 'agendado' = marcou dia/hora futura; 'estimado' = deu janela vaga ('mais "
    "tarde', 'à noite'); 'indefinido' = sem sinal de tempo. Marque 'imediato' quando ele tem "
    "pressa — ativa a rede que ancora o horário mínimo pra já."
)
_DESC_DURACAO = (
    "Duração em horas do PACOTE que o cliente fechou — a duração do programa no seu cardápio "
    "(ex.: pernoite = 12h), NÃO a diferença de relógio entre o horário de início e o de fim que "
    "vocês conversaram. Se ele fecha um pernoite e vocês falam 'das 22h às 6h', a duração é 12h "
    "(o pacote), não 8h (o intervalo do relógio) — gravar o span do relógio faz o sistema não "
    "encontrar o programa e escalar à toa uma oferta válida (abaixo do piso). PREENCHA assim que "
    "ele escolhe o pacote — é o que dimensiona o bloqueio na agenda; sem ela o sistema reserva "
    "só 1h por padrão e pode subdimensionar o horário. Se você cotou mais de uma duração "
    "(ex.: 1h e 2h) e o cliente ainda NÃO escolheu, a duração não está fechada — omita o campo "
    "até ele cravar, não chute. Grave junto com valor_acordado quando ambos estiverem fechados."
)
_DESC_TIPO_ATENDIMENTO = (
    "Quem se desloca. REGRA CRÍTICA de leitura: 'você/vc/te' na boca do CLIENTE se refere a "
    "VOCÊ (a modelo) — não inverta o sentido. Classifique pelo que o cliente diz:\n"
    "- 'interno' = o CLIENTE vem até você (ele se desloca): 'vou', 'vou aí', 'vou até você', "
    "'vou no seu local', 'posso ir'. É também o PADRÃO: quando o encontro está sendo combinado "
    "no SEU local e ele NÃO sinalizou uber (você indo) nem chamada de vídeo, grave 'interno' "
    "mesmo sem um verbo de deslocamento explícito — senão a reserva do horário não dispara e o "
    "atendimento fica travado. O endereço é o SEU ponto de encontro; SEM Pix.\n"
    "- 'externo' = VOCÊ vai até o cliente de uber (você se desloca): 'vem até mim', 'vem aqui', "
    "'você vem?', 'pode vir no meu endereço'. Pega o endereço DELE; tem Pix de deslocamento.\n"
    "- 'remoto' = vídeo chamada, ninguém se desloca.\n"
    "Cliente quer TE BUSCAR de carro ('vou te buscar', 'te pego')? Caso NÃO suportado — não "
    "classifique como 'externo'; deixe o campo de fora (sua conduta redireciona e, se ele "
    "insistir, escala)."
)
_DESC_ENDERECO = (
    "Endereço do CLIENTE / destino do atendimento (externo: onde ele está ou para onde vão — "
    "vira a localização DELE no sistema). NUNCA grave aqui o SEU ponto de encontro."
)
_DESC_COTACAO = (
    "Marque True SÓ no turno em que você APRESENTA o valor de um programa ao cliente "
    "(preço + duração) — a cotação de fato. É o que ativa o reengajamento proativo se o "
    "cliente sumir DEPOIS de receber o preço. NÃO marque quando ele só pergunta/sonda o valor "
    "sem você ter cotado ainda, nem nos turnos seguintes (o sistema guarda o primeiro carimbo "
    "e ignora repetições)."
)
_DESC_AVISO_SAIDA = (
    "Cliente avisou que saiu de casa em direção ao endereço combinado "
    "(texto livre tipo 'sai', 'tô indo', 'estou indo', 'sai agora'). "
    "Sinalize True SÓ em atendimento interno em Aguardando_confirmacao; "
    "ignore em outros contextos. Marque MESMO quando o cliente diz isso JUNTO "
    "com outra coisa no mesmo turno (ex.: confirma o endereço, pergunta o "
    "horário) — o aviso de saída não é exclusivo de outros campos. "
    "NÃO pausa a IA — segue a conversa normal."
)
_DESC_LIMPAR = (
    "Campos a ZERAR (NULL) quando o cliente RECUA/desmarca — ex.: disse um horário "
    "e depois 'não sei o dia ainda'. Nomes dos outros campos desta tool (ex.: "
    "['data_desejada','horario_desejado']). Só o que o cliente retratou; tem "
    "precedência sobre os demais campos. Zerar um campo apaga o valor anterior e pode "
    "reverter a qualificação do atendimento — na dúvida, não liste."
)
_DESC_BAIRRO = (
    "Bairro/região do endereço do CLIENTE (par com `endereco`, atendimento externo), quando "
    "ele informar. NUNCA grave aqui o bairro do SEU ponto de encontro. Omita se não disse."
)
_DESC_TIPO_LOCAL = (
    "Tipo do local do encontro que o cliente descreveu quando VOCÊ vai até ele (externo): "
    "'hotel', 'casa', 'apartamento'; 'outro' quando não se encaixa. Omita se não ficou claro."
)
_DESC_FORMA_PAGAMENTO = (
    "Forma de pagamento que o cliente sinalizou pro programa: 'pix', 'dinheiro', ou 'outro' "
    "(cartão e afins entram em 'outro'). Omita enquanto ele não disser."
)
_DESC_MOTIVO_PERDA = (
    "Sinal de perda PROVÁVEL desta conversa: 'preco' = travou no valor, 'sumiu' = silêncio "
    "prolongado, 'risco', 'indisponibilidade' = sem horário que sirva, 'fora_de_area', "
    "'outro'. É só um candidato interno — NÃO encerra o atendimento nem muda sua conduta; "
    "continue conduzindo normalmente."
)
_DESC_PROXIMA_ACAO = (
    "Nota interna curta pro painel (Fernando): a próxima ação que você espera na conversa "
    "(sua ou do cliente). NÃO é texto pro cliente."
)


class ExtracaoPayload(BaseModel):
    """Validacao interna do snapshot. NAO e mais o schema da tool (args achatados, 04 §3.4).

    Todos os campos opcionais — a tool registra o que está claro; NULL preserva o anterior
    (o domínio faz UPSERT: campos não-nulos sobrescrevem). Reconstruida no corpo da tool,
    preservando os constraints (ge/le, min/max_length); as descriptions LLM-visiveis moram
    na assinatura da tool.
    """

    # extra="forbid" => additionalProperties:false (strict tool use §7); nenhum dado de cliente
    # entra em nome de campo/enum (a grammar do strict e cacheada fora das protecoes, §7).
    model_config = ConfigDict(extra="forbid")

    intencao: Literal["curiosidade", "cotacao", "agendamento"] | None = None
    urgencia: Literal["imediato", "agendado", "indefinido", "estimado"] | None = None
    tipo_atendimento: Literal["interno", "externo", "remoto"] | None = None
    data_desejada: date | None = None
    horario_desejado: time | None = None
    duracao_horas: Decimal | None = Field(None, ge=0, le=48)
    endereco: str | None = None
    bairro: str | None = None
    tipo_local: Literal["hotel", "casa", "apartamento", "outro"] | None = None
    forma_pagamento: Literal["pix", "dinheiro", "outro"] | None = None
    valor_acordado: Decimal | None = Field(None, ge=0)
    sinais_qualificacao: SinaisQualificacao = Field(default_factory=SinaisQualificacao)
    motivo_perda_candidato: (
        Literal["preco", "sumiu", "risco", "indisponibilidade", "fora_de_area", "outro"] | None
    ) = None
    aviso_saida_detectado: bool = False
    cotacao_apresentada: bool = False
    limpar: list[str] = Field(default_factory=list)
    proxima_acao_esperada: str = Field(min_length=3, max_length=240)


@tool
async def registrar_extracao(
    proxima_acao_esperada: Annotated[
        # Sem max_length na assinatura de proposito: acima de 240 o texto e TRUNCADO no corpo
        # (nota interna, cortar nao perde nada critico) em vez de estourar validacao -> retry do
        # tool-call inteiro (ruido recorrente em prod; feedback piloto 21/07).
        str,
        Field(min_length=3, description=_DESC_PROXIMA_ACAO),
    ],
    runtime: ToolRuntime[ContextAgente],
    intencao: Annotated[
        Literal["curiosidade", "cotacao", "agendamento"] | None,
        Field(description=_DESC_INTENCAO),
    ] = None,
    urgencia: Annotated[
        Literal["imediato", "agendado", "indefinido", "estimado"] | None,
        Field(description=_DESC_URGENCIA),
    ] = None,
    tipo_atendimento: Annotated[
        Literal["interno", "externo", "remoto"] | None,
        Field(description=_DESC_TIPO_ATENDIMENTO),
    ] = None,
    data_desejada: Annotated[date | None, Field(description=_DESC_DATA)] = None,
    horario_desejado: Annotated[time | None, Field(description=_DESC_HORARIO)] = None,
    duracao_horas: Annotated[Decimal | None, Field(ge=0, le=48, description=_DESC_DURACAO)] = None,
    endereco: Annotated[str | None, Field(description=_DESC_ENDERECO)] = None,
    bairro: Annotated[str | None, Field(description=_DESC_BAIRRO)] = None,
    tipo_local: Annotated[
        Literal["hotel", "casa", "apartamento", "outro"] | None,
        Field(description=_DESC_TIPO_LOCAL),
    ] = None,
    forma_pagamento: Annotated[
        Literal["pix", "dinheiro", "outro"] | None,
        Field(description=_DESC_FORMA_PAGAMENTO),
    ] = None,
    valor_acordado: Annotated[Decimal | None, Field(ge=0, description=_DESC_VALOR)] = None,
    sinais_qualificacao: Annotated[
        SinaisQualificacao | None,
        Field(description="Sinais detectados na conversa — inclua só os True."),
    ] = None,
    motivo_perda_candidato: Annotated[
        Literal["preco", "sumiu", "risco", "indisponibilidade", "fora_de_area", "outro"] | None,
        Field(description=_DESC_MOTIVO_PERDA),
    ] = None,
    aviso_saida_detectado: Annotated[bool, Field(description=_DESC_AVISO_SAIDA)] = False,
    cotacao_apresentada: Annotated[bool, Field(description=_DESC_COTACAO)] = False,
    limpar: Annotated[list[str] | None, Field(description=_DESC_LIMPAR)] = None,
) -> str:
    """Registre o snapshot do que aprendeu nesta conversa. Chame UMA vez por turno, perto do fim.

    IMPORTANTE: registrar NÃO envia nada ao cliente — é uma nota interna. Você ainda precisa
    responder ao cliente normalmente neste mesmo turno, em personagem, como se já soubesse.

    Todos os campos são opcionais, exceto `proxima_acao_esperada` — registre o que está claro;
    deixe de fora o que ainda não. O snapshot é incremental (COALESCE): campos não-nulos
    sobrescrevem, nulos preservam o anterior. Para apagar um dado que o cliente retratou de
    fato, use o campo `limpar`.

    Returns:
        Confirmação interna do que o sistema gravou/avançou — nota sua, nunca repita ao
        cliente. Se vier "ERRO: ...", o registro NÃO foi gravado: siga a instrução do erro,
        corrija a fala E registre de novo neste turno.
    """
    # Transicoes de estado disparadas por esta tool (regra em registrar_extracao_ia):
    # - intencao=curiosidade/cotacao/agendamento + estado=Novo -> Triagem
    # - intencao=agendamento + horario_desejado + tipo_atendimento + Triagem -> Qualificado
    # - tipo_atendimento=interno + horario_desejado + Qualificado -> Aguardando_confirmacao
    #   (cria bloqueio previo E dispara o pin de endereco — side-effect, nao tool)
    # - externo + horario_desejado + Qualificado -> Aguardando_confirmacao
    #   (externo-Uber: side-effect deterministico cria bloqueio previo, marca pix_status e
    #    solicita o Pix — _solicitar_pix_deslocamento_se_aplicavel; a IA so escreve a bolha)
    pool = runtime.context.db_pool
    atendimento_id = runtime.context.atendimento_id
    turno_id = runtime.context.turno_id
    # Relogio do turno (clock injection): None em prod (criar_bloqueio_previo le now() real);
    # instante fixo no harness fiel/replay -> a reserva do slot fica deterministica e coerente
    # com a ancora que a IA leu no contexto (ContextAgente.agora_utc).
    agora = runtime.context.agora_utc
    # horario_minimo (cedo agenda-coerente, resolvido pelo prepare_context e lido tambem abaixo no
    # handler de AntecedenciaInsuficiente): ancora o fallback de tempo imediato (#4) no dominio. O
    # `now` cru nao passaria a guarda estrita de antecedencia; o horario_minimo, sim (por construcao).
    horario_minimo = runtime.state.get("horario_minimo")

    # Clamp antes da revalidacao: o model interno mantem max_length=240 como invariante; aqui o
    # excesso vira truncamento silencioso (ver comentario na assinatura).
    proxima_acao_esperada = proxima_acao_esperada[:240]

    # Revalida os args achatados no model interno (constraints ge/le, min/max_length, forbid).
    payload = ExtracaoPayload(
        intencao=intencao,
        urgencia=urgencia,
        tipo_atendimento=tipo_atendimento,
        data_desejada=data_desejada,
        horario_desejado=horario_desejado,
        duracao_horas=duracao_horas,
        endereco=endereco,
        bairro=bairro,
        tipo_local=tipo_local,
        forma_pagamento=forma_pagamento,
        valor_acordado=valor_acordado,
        sinais_qualificacao=sinais_qualificacao or SinaisQualificacao(),
        motivo_perda_candidato=motivo_perda_candidato,
        aviso_saida_detectado=aviso_saida_detectado,
        cotacao_apresentada=cotacao_apresentada,
        limpar=limpar or [],
        proxima_acao_esperada=proxima_acao_esperada,
    )
    # exclude_defaults: campos com valor igual ao default ficam fora do dict (comparacao por
    # VALOR — arg omitido pelo LLM e arg explicitamente default dao no mesmo). Critico pro
    # `sinais_qualificacao` (schema fechado pos-refactor): garante que so chaves True sejam
    # mergeadas no JSONB acumulado (`||` em service.py).
    dados = payload.model_dump(mode="json", exclude_defaults=True)
    async with pool.connection() as conn:
        try:
            resultado = await _executar_idempotente(
                conn,
                turno_id,
                "registrar_extracao",
                0,
                dados,
                executor=lambda c, p: registrar_extracao_ia(
                    c, atendimento_id, p, agora=agora, horario_minimo=horario_minimo
                ),
            )
        except ConflitoAgenda:
            # Erro recuperavel (04 §6): a transacao reverteu; instrua a IA a reofertar outro
            # horario. ToolException -> ToolMessage(status="error") -> `is_error: true` na
            # Anthropic; o texto orienta a recuperacao (o loop funcionando, nao falha do turno).
            AGENTE_TOOL_ERRO_RECUPERAVEL.labels("registrar_extracao", "agenda_conflito").inc()
            raise ToolException(
                "ERRO: o horário escolhido já está reservado para a modelo. "
                "Ofereça outro horário ao cliente com uma desculpa pessoal (ver sua conduta de "
                "indisponibilidade) — NUNCA diga que o horário foi reservado — e registre de novo."
            ) from None
        except ForaDisponibilidade:
            # Trava dura (ADR 0005): horário fora do período de trabalho da modelo. Conduta
            # DIFERENTE do conflito de agenda: aqui não há outro cliente a esconder — a IA
            # assume a folga, revela quando volta e ancora a primeira data disponível.
            AGENTE_TOOL_ERRO_RECUPERAVEL.labels("registrar_extracao", "fora_disponibilidade").inc()
            raise ToolException(
                "ERRO: o horário pedido cai FORA do seu período de trabalho — o sistema não "
                "reserva, então NUNCA diga ao cliente que fechou ou confirmou esse horário. "
                "Siga sua conduta de período de trabalho: assuma que está fora, diga "
                "quando volta e ofereça a primeira data/horário dentro do período (veja "
                "<periodo_de_trabalho> no contexto) — depois registre de novo."
            ) from None
        except AntecedenciaInsuficiente:
            # Buffer de preparo (ADR 0025): o horário pedido é cedo demais a partir de agora. NÃO
            # é conflito com outro cliente — é tempo de se arrumar. Ancore no <horario_minimo> do
            # contexto (já calculado), nunca num número inventado.
            AGENTE_TOOL_ERRO_RECUPERAVEL.labels(
                "registrar_extracao", "antecedencia_insuficiente"
            ).inc()
            # Desambiguação (ADR 0025/0005): quando `horario_minimo` é None (now+buffer cai fora da
            # Disponibilidade), NÃO há horário válido mais tarde hoje — mandar "ofereça o
            # <horario_minimo>" apontaria pra uma tag ausente e a IA inventaria um horário fora da
            # janela. Cai na conduta de período de trabalho ("por hoje já parei, amanhã"). Texto
            # NEUTRO de propósito: o None pode vir de fim de janela OU de bloqueio ocupando o resto
            # do dia, então NÃO afirma "está de folga / não há outro cliente a esconder" (seria
            # falso no 2º caso) — só referencia a conduta e a 1ª data do próximo período.
            if runtime.state.get("horario_minimo") is None:
                raise ToolException(
                    "ERRO: não há horário válido ainda hoje — então NUNCA diga ao cliente que "
                    "fechou ou confirmou um horário pra hoje. Siga sua conduta de período de "
                    "trabalho: ancore a volta na primeira data/horário do próximo período (veja "
                    "<periodo_de_trabalho> no contexto) — depois registre de novo."
                ) from None
            raise ToolException(
                "ERRO: esse horário é cedo demais — você precisa de um tempinho pra se arrumar. "
                "Ofereça ao cliente o horário de <horario_minimo> do seu contexto (numa hora leve e "
                "redonda, sem inventar minutos) — depois registre de novo."
            ) from None
        except HorarioNaoDefinido:
            # Reserva pedida sem horario combinado (ex.: atendimento promovido no painel p/
            # Aguardando_confirmacao com horario_desejado NULL). Erro RECUPERAVEL por contrato do
            # proprio dominio — sem este catch a excecao sobe e MATA o turno (sem resposta e sem
            # escalada), repetindo a cada mensagem do cliente.
            AGENTE_TOOL_ERRO_RECUPERAVEL.labels("registrar_extracao", "horario_nao_definido").inc()
            raise ToolException(
                "ERRO: ainda não há horário combinado neste atendimento, então o sistema não "
                "reservou nada — NUNCA diga ao cliente que confirmou. Combine o horário com ele e "
                "registre `data_desejada` + `horario_desejado` no mesmo registro."
            ) from None
        except ParPrecoDuracaoInvalido:
            # Guarda do par preco x duracao (feedback piloto 21/07): a IA esticou a duracao por
            # cima de um valor combinado pra OUTRA duracao ("3h 800" com tabela so de 1h). A
            # transacao reverteu; a instrucao cobre os dois caminhos honestos (re-cotar pela
            # tabela ou nao vender o periodo) — nunca improvisar preco.
            AGENTE_TOOL_ERRO_RECUPERAVEL.labels("registrar_extracao", "par_preco_duracao").inc()
            raise ToolException(
                "ERRO: essa duração não combina com o valor já acordado — o valor na mesa é de "
                "OUTRA duração, e vender um período pelo preço de outro é prejuízo. Se a sua "
                "tabela em <programas> tem o período, re-cote pelo preço DELA (diga o valor novo "
                "ao cliente) e registre valor_acordado + duracao_horas JUNTOS; se NÃO tem, siga "
                "sua conduta de período fora da tabela (ver <sobe_o_ticket>) — sem registrar "
                "essa duração."
            ) from None
        except CotacaoAusente:
            # Guard onda 1 A: combinar horário sem preço dito. A transação reverteu; a IA precisa
            # cotar antes de reservar o slot (o cliente não pode sair de casa sem saber o valor).
            AGENTE_TOOL_ERRO_RECUPERAVEL.labels("registrar_extracao", "cotacao_ausente").inc()
            raise ToolException(
                "ERRO: você não disse o preço nesta conversa ainda, então NÃO pode combinar o "
                "horário — o cliente marcaria o encontro sem saber o valor. Cote primeiro (diga o "
                "valor com duração e local ao cliente) e registre com cotacao_apresentada=True; só "
                "então reserve o horário. NUNCA diga que confirmou ou reservou um horário agora."
            ) from None

    # Pin de endereco (interno): NAO enfileirado enquanto o renderer `_card_loc_pin`
    # (workers/envio.py) ainda levanta NotImplementedError — o job so falharia 5x (M3d, 09 §4.3).
    # O dominio segue setando `enviar_pin`; o enqueue volta junto com o renderer.
    # Aviso de saida (06 §5): card 'cliente saiu de casa' sem owner — SETNX no renderer
    # garante idempotencia inter-turnos; o _job_id aqui evita re-enfileirar no mesmo ARQ.
    if resultado.get("enviar_aviso_saida"):
        await runtime.context.redis.enqueue_job(
            "enviar_card",
            tipo="aviso_saida",
            atendimento_id=atendimento_id,
            _job_id=f"card:aviso_saida:{atendimento_id}",
        )
    mensagem: str = resultado["mensagem"]
    return mensagem
