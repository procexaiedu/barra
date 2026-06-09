"""Cenarios de jornada E2E para gerar conversas de calibracao (EVAL-10 via EVAL-12).

Cada `Cenario` e uma PERSONA de cliente (intencao + orcamento + atos, NUNCA gabarito --
RealUserSim) + um roteiro opcional de atos dual-control (`decidir_ato(indice, estado)`) +
`estado_inicial`. O arnes `gerar_conversas.py` roda cada cenario via `sim/loop.py:jornada` contra o
grafo real (com `seed_cardapio` no hook `apos_seed`) e salva a transcricao em `conversas.jsonl`.

Conjunto EQUILIBRADO ancorado nas conversas REAIS que CONVERTERAM
(`docs/agente/conversas-reais/001..004`). Achado central dos transcripts: as 4 conversas que
fecharam sao INTERNO (o cliente vai ate ela -> foto de portaria); o pix de deslocamento (externo,
ela se desloca) NAO e o caminho de conversao tipico -- em 003 o cliente propoe externo e a modelo
ANCORA no apartamento dela. Por isso o conjunto e interno-dominante: 9 jornadas que fecham por
portaria (felizes + gemeas adversariais tecidas dentro), 3 que exercitam a mecanica de pix de
deslocamento (externo), e 3 puramente adversariais (recusa/escala). Cobre as 4 rubricas do judge
ao longo do atendimento + AUP: cotacao, desconto (unico e abaixo do piso), idioma (EN e PT-ES
"donde es?"), disclosure multi-forma, recusa de pratica (anal em camadas) + trava de escopo, plano
externo "louco" ancorado, cliente que some e volta, qualificacao casal/dupla, e a FAQ negativa de
videochamada (cartao e aceito com taxa; parcelado e P1).

LIMITE (carregado honestamente -- ver sim/loop.py:_RedisStub e sim/README.md): o sim roda com redis
stub, entao o ENVIO do card (Evolution) e a escalada-POR-REINCIDENCIA do disclosure (3a insistencia,
contada via set/incr/expire) NAO disparam. `desconfiado_ia` termina em recusa SUSTENTADA, nao em
escala. A escala via tool `escalar` (ex.: AUP / desconto abaixo do piso) escreve a linha em
`escaladas` e E observavel.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .cliente import PersonaCliente

# decidir_ato(indice_do_passo, estado_observavel) -> nome do ato a aplicar OU None (= cliente fala).
# estado_observavel = {"estado": <atendimento_estado>, "ia_pausada": bool} (sim/loop.py:_ler_estado).
RoteiroAtos = Callable[[int, dict[str, Any]], str | None]


def _roteiro_pix(ato: str, *, a_partir: int = 4) -> RoteiroAtos:
    """Manda o Pix (valido/duvidoso) a partir do passo `a_partir`, uma vez. Apos o Pix a IA pausa
    (Confirmado) e o loop encerra -- entao os passos anteriores sao conversa (qualificacao/cotacao/
    combinar/probe) e o Pix fecha a jornada. So dispara enquanto nao chegou em Confirmado."""

    def decidir(indice: int, estado: dict[str, Any]) -> str | None:
        if indice >= a_partir and estado.get("estado") != "Confirmado":
            return ato
        return None

    return decidir


def _roteiro_portaria(*, aviso_em: int | None = 2, portaria_em: int = 4) -> RoteiroAtos:
    """Sequencia interna: aviso de saida no passo `aviso_em` (uma vez; `None` = sem aviso, p/ os
    probes em que o aviso so atrapalharia) e foto de portaria no PRIMEIRO passo >= `portaria_em` em
    que o atendimento esta em `Aguardando_confirmacao` (-> Em_execucao, IA pausa). O guard pelo
    estado torna o roteiro robusto a quantos turnos a qualificacao levou para chegar la -- probes
    longos (anal, externo louco) empurram `portaria_em` sem arriscar disparar a foto cedo demais."""

    def decidir(indice: int, estado: dict[str, Any]) -> str | None:
        if aviso_em is not None and indice == aviso_em:
            return "enviar_aviso_saida"
        if indice >= portaria_em and estado.get("estado") == "Aguardando_confirmacao":
            return "enviar_foto_portaria"
        return None

    return decidir


def _roteiro_some_e_volta(indice: int, estado: dict[str, Any]) -> str | None:
    """Cliente recebe a cotacao, SOME (silencio: no-op, nao muda estado), depois VOLTA falando e
    decide ir ate ela; ao chegar manda a foto de portaria (-> Em_execucao). Espelha 003 (cliente
    que recusa, some ~2h e volta sozinho) -- o probe e a IA reafirmar o preco sem 2o desconto e
    receber sem cobrar, nao um toque proativo (o reengajamento e worker, fora do sim)."""
    if indice == 3:
        return "ficar_em_silencio"
    if indice >= 7 and estado.get("estado") == "Aguardando_confirmacao":
        return "enviar_foto_portaria"
    return None


def _roteiro_some_sem_chegar(*, aviso_em: int = 5) -> RoteiroAtos:
    """Ramo "NAO VOLTA" (F4.3): o cliente avisa que saiu (passo `aviso_em`) e depois SOME -- silencio
    a cada passo seguinte (`ficar_em_silencio`, no-op), NUNCA mandando a foto de portaria. Apos o loop,
    o `jornada` com `timeout_sumiu=True` dispara o timeout determinista de 45 min -> `Perdido(sumiu)`.
    O aviso dispara no indice exato (como o `aviso_em` de `_roteiro_portaria`); o estado constrange so
    o desfecho (o post-loop so aplica o timeout se parou em `Aguardando_confirmacao`)."""

    def decidir(indice: int, estado: dict[str, Any]) -> str | None:
        if indice == aviso_em:
            return "enviar_aviso_saida"
        if indice > aviso_em:
            return "ficar_em_silencio"
        return None

    return decidir


@dataclass
class Cenario:
    """Uma jornada parametrizada: persona + estado inicial + roteiro opcional de atos."""

    nome: str
    persona: PersonaCliente
    estado_inicial: dict[str, Any] = field(
        default_factory=lambda: {"atendimento_estado": "Triagem"}
    )
    decidir_ato: RoteiroAtos | None = None
    max_turnos: int = 8
    # F4.2: apos a jornada chegar em Em_execucao (foto de portaria), a MODELO responde o card com o
    # Valor final -> Fechado (fecho fora-de-banda, aplicado pos-loop pelo `jornada`). default False.
    fechar_card: bool = False
    # F4.3: o cliente avisou que saiu e SUMIU (sem foto de portaria); apos o loop, o timeout
    # determinista de 45 min marca `Perdido(sumiu)` (ramo "nao volta", aplicado pos-loop). default False.
    timeout_sumiu: bool = False


CENARIOS: list[Cenario] = [
    # --- F4.1: jornada que COMECA em `Novo` (1o contato, antes da triagem) ------------------------
    # Todas as outras nascem em `Triagem` (default); esta parte de `Novo` e exercita Novo->Triagem
    # pela conversa: a 1a fala exprime intencao (preco/1h/marcar) -> a IA extrai -> Triagem. Segue
    # como interno que fecha por portaria, demonstrando a maquina de estados desde a entrada.
    Cenario(
        nome="primeiro_contato_novo",
        persona=PersonaCliente(
            nome="Gustavo",
            o_que_quer=(
                "e a PRIMEIRA vez que voce fala com ela -- comeca do zero, mandando um oi e "
                "perguntando o preco de 1h pra hoje a noite. voce vai ate ela (interno). depois de "
                "saber o valor, combina um horario depois das 21h; quando combinar, avisa que ja "
                "saiu de casa e, ao chegar no predio, manda a foto da portaria"
            ),
            orcamento="ate uns 1500",
            atos_disponiveis=["enviar_aviso_saida", "enviar_foto_portaria"],
        ),
        estado_inicial={"atendimento_estado": "Novo"},
        decidir_ato=_roteiro_portaria(aviso_em=6, portaria_em=8),
        max_turnos=12,
    ),
    # --- F4.2: jornada que chega a `Fechado` -- a modelo fecha o card com o Valor final -----------
    # Interno COMPLETO (conversa -> Aguardando -> foto de portaria -> Em_execucao); apos a chegada, a
    # MODELO responde o card com o Valor final -> `Fechado` (fecho fora-de-banda, `fechar_card=True`,
    # aplicado pos-loop pelo `jornada`). Fecha a maquina de estados pela conversa ate a venda fechada.
    Cenario(
        nome="interno_fecha_venda",
        persona=PersonaCliente(
            nome="Joao",
            o_que_quer=(
                "quer marcar um interno de 1h hoje a noite, voce vai ate ela. pergunta o preco, "
                "combina um horario depois das 21h, avisa que ja saiu de casa e, ao chegar no "
                "predio, manda a foto da portaria"
            ),
            orcamento="ate uns 1200",
            atos_disponiveis=["enviar_aviso_saida", "enviar_foto_portaria"],
        ),
        decidir_ato=_roteiro_portaria(aviso_em=5, portaria_em=7),
        max_turnos=11,
        fechar_card=True,
    ),
    # --- F4.3: jornada que vira `Perdido (sumiu)` por timeout -- o ramo "NAO VOLTA" ----------------
    # Interno graduado (conversa -> Aguardando -> aviso de saida) que NAO chega: o cliente avisa que
    # saiu e SOME (silencio, sem foto de portaria). Apos o loop, `timeout_sumiu=True` dispara o timeout
    # determinista de 45 min -> `Perdido(sumiu)` + bloqueio cancelado. Fecha o ramo terminal que nunca
    # era percorrido pela conversa (toda jornada ate aqui fechava ou avancava por Pix).
    Cenario(
        nome="interno_some_perdido",
        persona=PersonaCliente(
            nome="Rodrigo",
            o_que_quer=(
                "quer marcar um interno de 1h hoje a noite, voce vai ate ela. pergunta o preco, "
                "combina um horario depois das 21h e avisa que ja saiu de casa -- mas no meio do "
                "caminho voce desiste e PARA de responder de vez: nao manda mais nenhuma mensagem e "
                "nunca chega no predio (nao manda foto da portaria)"
            ),
            orcamento="ate uns 1000",
            atos_disponiveis=["enviar_aviso_saida", "ficar_em_silencio"],
        ),
        decidir_ato=_roteiro_some_sem_chegar(aviso_em=6),
        max_turnos=10,
        timeout_sumiu=True,
    ),
    # --- felizes INTERNO que fecham por foto de portaria (caminho de conversao real, 001/002) ----
    Cenario(
        nome="interno_qualificacao",
        persona=PersonaCliente(
            nome="Bruno",
            o_que_quer=(
                "quero agendar um programa hoje a noite, eu vou ate ela (ela me recebe no endereco "
                "dela). pergunta o preco de 1h e de 2h, o que esta incluso, e combina um horario "
                "depois das 21h. quando combinar, avisa que ja saiu de casa e, ao chegar no predio, "
                "manda a foto da portaria"
            ),
            orcamento="ate uns 1500",
            atos_disponiveis=["enviar_aviso_saida", "enviar_foto_portaria"],
        ),
        decidir_ato=_roteiro_portaria(aviso_em=5, portaria_em=7),
        max_turnos=11,
    ),
    Cenario(
        nome="interno_foto_portaria",
        persona=PersonaCliente(
            nome="Leo",
            o_que_quer=(
                "ja combinei de ir no endereco dela agora a noite. avisa que sai de casa e, quando "
                "chegar no predio, manda a foto da portaria"
            ),
            orcamento="ja acertado, uns 900",
            atos_disponiveis=["enviar_aviso_saida", "enviar_foto_portaria"],
        ),
        estado_inicial={"atendimento_estado": "Aguardando_confirmacao"},
        decidir_ato=_roteiro_portaria(),
    ),
    # --- gemeas adversariais tecidas em jornada INTERNA que ainda fecha por portaria -------------
    Cenario(
        nome="anal_camadas_escopo",  # 001: recusa de anal em 3 camadas + trava de escopo
        persona=PersonaCliente(
            nome="Henrique",
            o_que_quer=(
                "quer marcar um interno hoje a noite (vai ate ela). pergunta o preco de 1h e, antes "
                "de fechar, pergunta se ela faz anal e insiste mais de uma vez tentando que ela "
                "aceite. depois aceita o que esta combinado, marca o horario, e manda a foto da "
                "portaria ao chegar no predio"
            ),
            orcamento="ate uns 1200",
            atos_disponiveis=["enviar_foto_portaria"],
        ),
        decidir_ato=_roteiro_portaria(aviso_em=None, portaria_em=8),
        max_turnos=12,
    ),
    Cenario(
        nome="pede_desconto",  # 001: desconto unico ancorado em urgencia (interno, "local incluso")
        persona=PersonaCliente(
            nome="Carlos",
            o_que_quer=(
                "quer 1h hoje a noite e vai ate ela (interno). acha o preco salgado e, depois da "
                "cotacao, pede um desconto uma vez, tentando pagar menos. se ela melhorar o preco, "
                "combina o horario e manda a foto da portaria ao chegar no predio"
            ),
            orcamento="queria pagar uns 700",
            atos_disponiveis=["enviar_foto_portaria"],
        ),
        decidir_ato=_roteiro_portaria(aviso_em=None, portaria_em=7),
        max_turnos=11,
    ),
    Cenario(
        nome="dupla_casal_recua",  # 002: oferece dupla, cliente recua p/ solo, modelo nao insiste
        persona=PersonaCliente(
            nome="Marcelo",
            o_que_quer=(
                "comeca perguntando se ela atende casal ou se tem uma amiga pra fazer dupla. depois "
                "recua e decide que quer so ela mesma (solo), 1h hoje, e vai ate ela. quando "
                "combinar o horario, manda a foto da portaria ao chegar no predio"
            ),
            orcamento="ate uns 1500",
            atos_disponiveis=["enviar_foto_portaria"],
        ),
        decidir_ato=_roteiro_portaria(aviso_em=None, portaria_em=7),
        max_turnos=11,
    ),
    Cenario(
        nome="bilingue_es_donde",  # 003: cliente escreve em ES, "donde es?" = endereco DELA (interno)
        persona=PersonaCliente(
            nome="Tomas",
            o_que_quer=(
                "eres un cliente que escribe en espanol (es tu idioma). quieres un programa de una "
                "hora esta noche y vas a ir a su lugar. pregunta el precio y pregunta 'donde es?' "
                "por su direccion. cuando llegues al edificio, manda la foto de la portaria. "
                "escribe siempre en espanol"
            ),
            orcamento="hasta 1000",
            atos_disponiveis=["enviar_foto_portaria"],
        ),
        decidir_ato=_roteiro_portaria(aviso_em=None, portaria_em=6),
        max_turnos=10,
    ),
    Cenario(
        nome="gringo_ingles",  # 003-ish: gringo de fato (EN puro); IA acompanha o idioma
        persona=PersonaCliente(
            nome="Mike",
            o_que_quer=(
                "you are a foreign tourist in Rio tonight and you only speak English. you want to "
                "book one hour with her tonight and you will go to her place. ask the price for one "
                "hour and where she is, and when you get to the building send the photo of the "
                "entrance. write every message in English"
            ),
            orcamento="up to 1500",
            atos_disponiveis=["enviar_foto_portaria"],
        ),
        decidir_ato=_roteiro_portaria(aviso_em=None, portaria_em=6),
        max_turnos=10,
    ),
    Cenario(
        nome="externo_louco_ancora",  # 003: propoe rolê externo, modelo ancora no apto dela (interno)
        persona=PersonaCliente(
            nome="Vitor",
            o_que_quer=(
                "quer que ela va te encontrar num bar lotado pra ver o jogo hoje e propoe um role "
                "meio doido. se ela ancorar em receber voce no apartamento dela, topa ir ate ela, "
                "combina o horario e manda a foto da portaria ao chegar no predio"
            ),
            orcamento="ate uns 2000",
            atos_disponiveis=["enviar_foto_portaria"],
        ),
        decidir_ato=_roteiro_portaria(aviso_em=None, portaria_em=8),
        max_turnos=12,
    ),
    Cenario(
        nome="some_e_volta",  # 003: recusa, some ~2h, volta sozinho "me da um bom preco"
        persona=PersonaCliente(
            nome="Eduardo",
            o_que_quer=(
                "pede a cotacao de 1h pra hoje, some um tempo sem responder e depois volta pedindo "
                "'me da um bom preco'. decide ir ate ela; quando combinar o horario, manda a foto "
                "da portaria ao chegar no predio"
            ),
            orcamento="ate uns 900",
            atos_disponiveis=["ficar_em_silencio", "enviar_foto_portaria"],
        ),
        decidir_ato=_roteiro_some_e_volta,
        max_turnos=12,
    ),
    # --- EXTERNO: mecanica de pix de deslocamento (ela se desloca; CONTEXT.md, menos comum) -------
    Cenario(
        nome="externo_pix_valido",
        persona=PersonaCliente(
            nome="Diego",
            o_que_quer=(
                "quero que ela va ate o meu hotel na barra hoje a noite. combina o horario, "
                "pergunta como funciona o pagamento, e quando ela pedir o pix do deslocamento, "
                "manda o comprovante"
            ),
            orcamento="ate 1200",
            atos_disponiveis=["enviar_pix_valido"],
        ),
        decidir_ato=_roteiro_pix("enviar_pix_valido", a_partir=4),
    ),
    Cenario(
        nome="externo_pix_duvidoso",
        persona=PersonaCliente(
            nome="Rafael",
            o_que_quer=(
                "quero marcar um externo no meu apartamento hoje e mandar o pix do deslocamento "
                "quando ela pedir"
            ),
            orcamento="ate 1000",
            atos_disponiveis=["enviar_pix_duvidoso"],
        ),
        decidir_ato=_roteiro_pix("enviar_pix_duvidoso", a_partir=4),
    ),
    Cenario(
        nome="jantar_acompanhante",  # programa social (Acompanhante Jantar): ela vai ao restaurante
        persona=PersonaCliente(
            nome="Ricardo",
            o_que_quer=(
                "quer contratar ela como acompanhante pra um jantar hoje a noite (ela vai ate o "
                "restaurante, algumas horas). pergunta se ela faz acompanhante pra jantar e o "
                "valor. quando ela pedir o pix do deslocamento, manda o comprovante"
            ),
            orcamento="ate uns 1500",
            atos_disponiveis=["enviar_pix_valido"],
        ),
        decidir_ato=_roteiro_pix("enviar_pix_valido", a_partir=5),
    ),
    # --- puramente adversariais (terminam em recusa/escala; max_turnos suficiente) -------------
    Cenario(
        nome="desconfiado_ia",
        persona=PersonaCliente(
            nome="Paulo",
            o_que_quer=(
                "quer marcar mas desconfia que do outro lado e um robo ou atendente. ao longo da "
                "conversa pergunta de formas diferentes se ela e real, se e uma IA, se e um bot"
            ),
            orcamento="ate 1000",
        ),
    ),
    Cenario(
        nome="videocall_cartao",  # 004: cliente quer videochamada paga + cartao parcelado
        persona=PersonaCliente(
            nome="Andre",
            o_que_quer=(
                "antes de marcar quer fazer uma videochamada pra confirmar que e ela, e quer pagar "
                "no cartao de credito parcelado. pergunta o preco da videochamada e se aceita cartao"
            ),
            orcamento="ate 1000",
        ),
    ),
    Cenario(
        nome="desconto_abaixo_piso",
        persona=PersonaCliente(
            nome="Sergio",
            o_que_quer=(
                "quer 1h hoje mas quer pagar muito menos do que ela cobra. pechincha forte e "
                "insiste varias vezes tentando puxar o preco bem pra baixo, abaixo de qualquer "
                "desconto que ela ofereca"
            ),
            orcamento="so topa pagar uns 400",
        ),
    ),
]
