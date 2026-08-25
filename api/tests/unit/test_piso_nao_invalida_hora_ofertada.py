"""O piso do `<horario_minimo>` não invalida a hora que a PRÓPRIA IA ofertou (campanha 13/08, c7).

Caso real do rig, eb01:210917388210413@lid: às 09:15 a IA ofertou "Consigo às 10h, fecha ?" (piso
10:00) e repetiu a hora em três turnos; às 09:32 o cliente aceitou ("10h tá ótimo") — mas o piso,
recalculado a cada turno como `arredonda_acima(agora + antecedência)`, já era 10:30, e ela negou a
própria oferta no instante do fechamento ("Fechado às 10:30 então" → "às 10h não consigo não").

O fix é determinístico e todo por baixo: a hora que a fala DELA pôs na mesa e ninguém retirou
(`horas_em_pauta_da_conversa`) rebaixa o piso APRESENTADO enquanto for fisicamente possível pela
régua real do tipo (`piso_com_hora_ofertada`). O piso CRU — o que viaja para o State e alimenta o
fallback de tempo imediato da extração — não muda.

As três fronteiras da rodada de refutação (13/08) estão pinadas dos DOIS lados: linha de tabela
("700 as 2h") não vira hora, mas "às 2h" vira; a recusa DELE retira a hora, mas a pergunta dele
não; hora de amanhã não entra na pauta de hoje, mas a de hoje entra.

Sem banco, sem crédito: `_FakeConn` vazio + relógio injetado (`ContextAgente.agora_utc`).
"""

import re
from datetime import UTC, date, datetime, time, timedelta, timezone
from typing import Any

from barra.agente._disciplina import horas_em_pauta_da_conversa
from barra.agente.contexto import ContextAgente
from barra.agente.nos._proximo_livre import piso_com_hora_ofertada
from barra.agente.nos.prepare_context import _resolver_variaveis
from barra.agente.persona import render_contexto_dinamico
from barra.dominio.agenda.service import antecedencia_min_por_tipo
from barra.dominio.conversas.modelos import DirecaoMensagem

BRT = timezone(timedelta(hours=-3))

# As bolhas REAIS da conversa do caso (t5, t7, t8), na ordem em que saíram.
_OFERTA_COM_COTACAO = "400 1h no meu local\n\nConsigo às 10h, fecha ?"
_OFERTA_REPETIDA = "400 então, às 10h te espero"
_EMPURRAO_SEM_HORA = "Me confirma o horário que eu te passo o número certinho"


def _dela(*bolhas: str) -> list[tuple[bool, str]]:
    return [(True, b) for b in bolhas]


# --------------------------------------------------------------------- o detector da fala dela
def test_hora_ofertada_entra_em_pauta_e_a_duracao_da_cotacao_nao() -> None:
    # "400 1h no meu local" é DURAÇÃO vendida, não relógio — só a hora atrás do marcador conta.
    assert horas_em_pauta_da_conversa(_dela(_OFERTA_COM_COTACAO)) == {time(10, 0)}
    assert horas_em_pauta_da_conversa(_dela(_OFERTA_REPETIDA)) == {time(10, 0)}
    assert horas_em_pauta_da_conversa(_dela("600 2h no meu local")) == set()
    assert horas_em_pauta_da_conversa(_dela(_EMPURRAO_SEM_HORA)) == set()


def test_meia_hora_dispensa_marcador_e_a_faixa_aberta_nao_e_oferta() -> None:
    assert horas_em_pauta_da_conversa(_dela("Fechado 10:30 então amor")) == {time(10, 30)}
    # Disponibilidade não é proposta (a MESMA fronteira do `_bolha_da_ia_propoe_hora`).
    assert horas_em_pauta_da_conversa(_dela("Estou livre hoje a partir das 19:30")) == set()
    assert horas_em_pauta_da_conversa(_dela("Atendo das 14h às 23h amor")) == set()


def test_a_hora_que_ela_retira_sai_da_pauta_sem_levar_a_nova_junto() -> None:
    # A bolha do t13: a recusa e a reoferta moram na MESMA fala, separadas por cláusula.
    falas = _dela(
        _OFERTA_COM_COTACAO,
        "Poxa amor, às 10h não consigo não\n\nConsigo às 10:30, me espera ?",
    )

    assert horas_em_pauta_da_conversa(falas) == {time(10, 30)}


# --------------------------------------------- refutação 1 (GRAVE): a LINHA DE TABELA não é hora
def test_linha_de_tabela_nao_vira_hora_do_relogio() -> None:
    """Falas REAIS do corpus (eb03:180316434104536 t6, eb01:160219460010212 t7): o preço colado na
    duração usa o MESMO marcador da oferta e injetava 02:00/12:00 na pauta — na madrugada isso
    rebaixava o piso de verdade."""
    assert horas_em_pauta_da_conversa(_dela("400 a 1h amor\n\n700 as 2h")) == set()
    assert horas_em_pauta_da_conversa(_dela("2500 as 12h de pernoite")) == set()
    assert horas_em_pauta_da_conversa(_dela("Consigo hoje 14h até as 2h")) == set()
    # O outro lado: sem preço colado, a hora do relógio continua entrando.
    assert horas_em_pauta_da_conversa(_dela("Consigo às 2h, fecha ?")) == {time(2, 0)}
    # E a cotação COM hora do relógio (13-23, onde duração de pacote não cabe) segue valendo.
    assert horas_em_pauta_da_conversa(_dela("consigo 600 as 21h amor")) == {time(21, 0)}


# ------------------------------------- refutação 2: a recusa DELE também tira a hora da pauta
def test_a_recusa_do_cliente_retira_a_hora_mas_a_pergunta_dele_nao() -> None:
    ofertou_10 = (True, "Consigo às 10h, fecha ?")
    recusou = (False, "10h não dá pra mim, só consigo 11h")
    perguntou = (False, "não dá 10h ?")

    # Ele recusa; ela reoferta 11h -> só 11h fica de pé (10h foi abandonada).
    assert horas_em_pauta_da_conversa(
        [ofertou_10, recusou, (True, "Consigo às 11h então amor")]
    ) == {time(11, 0)}
    # Pergunta não é recusa: a hora dela continua na mesa.
    assert horas_em_pauta_da_conversa([ofertou_10, perguntou]) == {time(10, 0)}
    # E a proposta DELE não entra sozinha na pauta: quem compromete a agenda é a fala dela.
    assert horas_em_pauta_da_conversa([(False, "posso às 11h ?")]) == set()


# ------------------------------------------- refutação 3: hora de OUTRO DIA não é pauta de hoje
def test_hora_de_outro_dia_nao_entra_na_pauta_de_hoje() -> None:
    assert horas_em_pauta_da_conversa(_dela("Amanhã consigo às 10h amor")) == set()
    assert horas_em_pauta_da_conversa(_dela("Sábado às 10h te espero")) == set()
    assert horas_em_pauta_da_conversa(_dela("Semana que vem às 10h então")) == set()
    # O outro lado: hoje entra (e é o caso real).
    assert horas_em_pauta_da_conversa(_dela("Hoje consigo às 10h, fecha ?")) == {time(10, 0)}


# ------------------------------------------------------------------------ a aritmética do piso
def test_piso_desce_ate_a_hora_ofertada_e_nunca_sobe() -> None:
    agora = datetime(2026, 8, 13, 9, 32, tzinfo=BRT)
    piso = datetime(2026, 8, 13, 10, 30, tzinfo=BRT)

    # Ofertada e ainda futura -> o piso apresentado é ela.
    assert piso_com_hora_ofertada(
        piso, {time(10, 0)}, agora, [], [], 30, antecedencia_min=0
    ) == datetime(2026, 8, 13, 10, 0, tzinfo=BRT)
    # Ofertada DEPOIS do piso não sobe o piso (não é trabalho desta função).
    assert (
        piso_com_hora_ofertada(piso, {time(14, 0)}, agora, [], [], 30, antecedencia_min=0) == piso
    )
    # Bloqueio novo em cima da hora ofertada derruba a exceção.
    bloco = [
        {
            "inicio": datetime(2026, 8, 13, 10, 0, tzinfo=BRT),
            "fim": datetime(2026, 8, 13, 11, 0, tzinfo=BRT),
        }
    ]
    assert (
        piso_com_hora_ofertada(piso, {time(10, 0)}, agora, bloco, [], 30, antecedencia_min=0)
        == piso
    )


# ------------------------------------------------------ o turno inteiro, como o prompt o monta
class _Result:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    async def fetchone(self) -> dict[str, Any] | None:
        return self.rows[0] if self.rows else None

    async def fetchall(self) -> list[dict[str, Any]]:
        return self.rows


class _FakeConn:
    """Vazio em tudo: o atendimento chega por kwarg e o relógio vem injetado (sem query, sem DB)."""

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> _Result:
        return _Result([])


def _ctx(agora_utc: datetime) -> ContextAgente:
    return ContextAgente(
        db_pool=None,  # type: ignore[arg-type]  # nenhuma query roda com o _FakeConn
        redis=None,  # type: ignore[arg-type]
        modelo_id="11111111-1111-1111-1111-111111111111",
        atendimento_id="22222222-2222-2222-2222-222222222222",
        cliente_id="33333333-3333-3333-3333-333333333333",
        turno_id="t",
        agora_utc=agora_utc,
    )


def _janela(bolhas_dela: list[str], *, dia: date, hora_inicial: int = 9) -> list[dict[str, Any]]:
    """Janela crua no formato de `carregar_mensagens`: bolha dela + resposta dele, alternando."""
    linhas: list[dict[str, Any]] = []
    minuto = 0
    for i, texto in enumerate(bolhas_dela):
        for direcao, conteudo in (
            (DirecaoMensagem.ia, texto),
            (DirecaoMensagem.cliente, "blz"),
        ):
            linhas.append(
                {
                    "id": f"{i}-{direcao.value}",
                    "direcao": direcao,
                    "tipo": "texto",
                    "conteudo": conteudo,
                    "created_at": datetime(
                        dia.year, dia.month, dia.day, hora_inicial, minuto, tzinfo=UTC
                    )
                    + timedelta(minutes=minuto),
                }
            )
            minuto += 5
    return linhas


def _turnos(pares: list[tuple[Any, str]], *, inicio: datetime) -> list[dict[str, Any]]:
    """Janela crua com as duas direções explícitas, uma bolha a cada 5 min a partir de `inicio`."""
    return [
        {
            "id": f"m{i}",
            "direcao": direcao,
            "tipo": "texto",
            "conteudo": conteudo,
            "created_at": inicio + timedelta(minutes=5 * i),
        }
        for i, (direcao, conteudo) in enumerate(pares)
    ]


async def _variaveis(
    *,
    agora_brt: datetime,
    bolhas_dela: list[str] | None = None,
    linhas: list[dict[str, Any]] | None = None,
    tipo: str = "interno",
    estado: str = "Qualificado",  # default: tipo AINDA pode flipar -> piso publicado conservador
) -> Any:
    atendimento = {
        "numero_curto": 1,
        "estado": estado,
        "tipo_atendimento": tipo,
        "data_desejada": agora_brt.date(),
    }
    if linhas is None:
        linhas = _janela(bolhas_dela or [], dia=agora_brt.date())
    return await _resolver_variaveis(
        _FakeConn(),  # type: ignore[arg-type]  # nenhuma query roda: tudo vazio + relógio injetado
        _ctx(agora_brt.astimezone(UTC)),
        linhas,
        atendimento=atendimento,
    )


async def test_caso_real_a_hora_ofertada_sobrevive_ao_piso_que_andou() -> None:
    # 09:32 BRT: o piso cru já é 10:30 (agora + 30 do conservador, arredondado), mas ela ofertou
    # 10h três vezes — e é 10h que o prompt apresenta.
    variaveis = await _variaveis(
        agora_brt=datetime(2026, 8, 13, 9, 32, tzinfo=BRT),
        bolhas_dela=[_OFERTA_COM_COTACAO, _OFERTA_REPETIDA, _EMPURRAO_SEM_HORA],
    )

    assert variaveis.horario_minimo.astimezone(BRT).strftime("%H:%M") == "10:30"  # cru intacto
    assert variaveis.horario_minimo_apresentado.astimezone(BRT).strftime("%H:%M") == "10:00"

    saida = render_contexto_dinamico(**variaveis.como_variaveis())
    assert re.search(r'<horario_minimo inicio="[^"]*10:00"', saida), saida
    # O mapa desce junto: âncora em 10:00 com janela abrindo 10:30 é a mesma contradição.
    assert re.search(r'<janela_livre de="[^"]*10:00"', saida), saida
    assert variaveis.livre_agora == "livre hoje a partir de 10:00"


async def test_hora_ja_passada_nao_rebaixa_o_piso() -> None:
    # Mesma conversa, 10:05 BRT: 10h já é passado de verdade — o piso volta a ser só o piso.
    variaveis = await _variaveis(
        agora_brt=datetime(2026, 8, 13, 10, 5, tzinfo=BRT),
        bolhas_dela=[_OFERTA_COM_COTACAO, _OFERTA_REPETIDA],
    )

    assert variaveis.horario_minimo_apresentado == variaveis.horario_minimo
    assert variaveis.horario_minimo.astimezone(BRT).strftime("%H:%M") == "11:00"


async def test_sem_hora_ofertada_o_piso_segue_intacto() -> None:
    variaveis = await _variaveis(
        agora_brt=datetime(2026, 8, 13, 9, 32, tzinfo=BRT),
        bolhas_dela=["Oii amor", _EMPURRAO_SEM_HORA],
    )

    assert variaveis.horario_minimo_apresentado == variaveis.horario_minimo
    assert variaveis.horario_minimo.astimezone(BRT).strftime("%H:%M") == "10:30"


async def test_tipo_congelado_rebaixa_pela_regua_do_proprio_tipo() -> None:
    # `Aguardando_confirmacao` congela o tipo (`tipo_atendimento_congelado`): não há flip possível,
    # e a régua do interno (~0) vale sem ressalva nenhuma. 10:00 está dentro da janela em que as
    # duas réguas discordam ([antecedência do interno, antecedência do externo)).
    variaveis = await _variaveis(
        agora_brt=datetime(2026, 8, 13, 9, 32, tzinfo=BRT),
        bolhas_dela=[_OFERTA_COM_COTACAO, _OFERTA_REPETIDA],
        estado="Aguardando_confirmacao",
    )

    assert variaveis.horario_minimo_apresentado.astimezone(BRT).strftime("%H:%M") == "10:00"


async def test_o_custo_nomeado_do_flip_de_tipo_dentro_do_turno() -> None:
    """PIN do custo aceito (revisão LangGraph 13/08), para ninguém o descobrir por acidente.

    Com o tipo NÃO congelado a exceção usa a régua do tipo GRAVADO (interno, ~0), e não a bumpada
    do piso cru: é o que mantém de pé a hora que ela ofertou — sem isso a exceção vira no-op
    justamente na família do defeito (`test_caso_real...` mede isso). O preço é que a hora
    apresentada pode cair DENTRO da antecedência do externo: se o cliente aceitar a hora e flipar
    para externo na MESMA fala, a reserva recusa com `AntecedenciaInsuficiente` — recusa correta
    (deslocamento leva tempo) e recuperável (auto-reoferta). Se um dia o dono do produto trocar
    esse trade-off, é este teste que cai junto com o de cima."""
    agora = datetime(2026, 8, 13, 9, 32, tzinfo=BRT)
    variaveis = await _variaveis(
        agora_brt=agora, bolhas_dela=[_OFERTA_COM_COTACAO, _OFERTA_REPETIDA]
    )

    apresentado = variaveis.horario_minimo_apresentado.astimezone(BRT)
    assert apresentado.strftime("%H:%M") == "10:00"
    assert apresentado >= agora + timedelta(minutes=antecedencia_min_por_tipo("interno"))
    assert apresentado < agora + timedelta(minutes=antecedencia_min_por_tipo("externo"))


async def test_externo_le_a_regua_do_proprio_tipo_e_nao_rebaixa_dentro_da_antecedencia() -> None:
    # No externo a modelo se DESLOCA: a antecedência real é o buffer, e 10:00 às 09:32 é hora que a
    # reserva recusaria (`AntecedenciaInsuficiente`). Prompt e gate não podem divergir.
    variaveis = await _variaveis(
        agora_brt=datetime(2026, 8, 13, 9, 32, tzinfo=BRT),
        bolhas_dela=[_OFERTA_COM_COTACAO, _OFERTA_REPETIDA],
        tipo="externo",
    )

    assert variaveis.horario_minimo_apresentado == variaveis.horario_minimo
    assert variaveis.horario_minimo.astimezone(BRT).strftime("%H:%M") == "10:30"


# ------------------------ as três refutações, agora no turno inteiro (do jeito que prod monta)
async def test_linha_de_tabela_na_madrugada_nao_rebaixa_o_piso() -> None:
    """Refutação 1, ponta a ponta: 01:35 BRT, piso cru 02:30, e a tabela "700 as 2h" oferecia
    02:00. Era o achado GRAVE — a hora vinha da LISTA DE PREÇOS, não de oferta nenhuma."""
    agora = datetime(2026, 8, 13, 1, 35, tzinfo=BRT)
    linhas = _turnos(
        [
            (DirecaoMensagem.cliente, "quanto?"),
            (DirecaoMensagem.ia, "400 a 1h amor\n\n700 as 2h"),
            (DirecaoMensagem.cliente, "hmm"),
        ],
        inicio=datetime(2026, 8, 13, 4, 0, tzinfo=UTC),
    )

    variaveis = await _variaveis(agora_brt=agora, linhas=linhas)

    assert variaveis.horario_minimo_apresentado == variaveis.horario_minimo
    assert variaveis.horario_minimo.astimezone(BRT).strftime("%H:%M") == "02:30"


async def test_hora_recusada_pelo_cliente_nao_ressuscita() -> None:
    """Refutação 2, ponta a ponta: ela ofertou 10h, ELE recusou e pediu 11h, ela concordou. 10h
    está abandonada — o piso apresentado não pode ressuscitá-la."""
    linhas = _turnos(
        [
            (DirecaoMensagem.cliente, "que horas?"),
            (DirecaoMensagem.ia, "Consigo às 10h, fecha ?"),
            (DirecaoMensagem.cliente, "10h não dá pra mim, só consigo 11h"),
            (DirecaoMensagem.ia, "Consigo às 11h então amor"),
            (DirecaoMensagem.cliente, "beleza"),
        ],
        inicio=datetime(2026, 8, 13, 12, 0, tzinfo=UTC),
    )

    variaveis = await _variaveis(agora_brt=datetime(2026, 8, 13, 9, 32, tzinfo=BRT), linhas=linhas)

    assert variaveis.horario_minimo_apresentado == variaveis.horario_minimo
    assert variaveis.horario_minimo.astimezone(BRT).strftime("%H:%M") == "10:30"


async def test_hora_de_amanha_nao_rebaixa_o_piso_de_hoje() -> None:
    """Refutação 3, ponta a ponta: a hora combinada para AMANHÃ era materializada na data de hoje
    e rebaixava o piso do dia errado."""
    linhas = _turnos(
        [
            (DirecaoMensagem.cliente, "hoje não dá, amanhã"),
            (DirecaoMensagem.ia, "Amanhã consigo às 10h amor"),
            (DirecaoMensagem.cliente, "beleza"),
        ],
        inicio=datetime(2026, 8, 13, 12, 0, tzinfo=UTC),
    )

    variaveis = await _variaveis(agora_brt=datetime(2026, 8, 13, 9, 32, tzinfo=BRT), linhas=linhas)

    assert variaveis.horario_minimo_apresentado == variaveis.horario_minimo


async def test_hora_ofertada_no_manual_da_modelo_tambem_vale() -> None:
    """A bolha manual da modelo é a MESMA voz para o cliente (refutação B, comportamento mantido)."""
    linhas = _turnos(
        [
            (DirecaoMensagem.cliente, "que horas?"),
            (DirecaoMensagem.modelo_manual, "Consigo às 10h amor"),
            (DirecaoMensagem.cliente, "10h tá ótimo"),
        ],
        inicio=datetime(2026, 8, 13, 12, 0, tzinfo=UTC),
    )

    variaveis = await _variaveis(agora_brt=datetime(2026, 8, 13, 9, 32, tzinfo=BRT), linhas=linhas)

    assert variaveis.horario_minimo_apresentado.astimezone(BRT).strftime("%H:%M") == "10:00"


async def test_pausa_de_6h_apaga_a_hora_ofertada_antes_dela() -> None:
    """A hora ofertada antes de um sumiço de 6h não está mais em pauta (mesma régua `_GAP_PAUSA`
    da marca de pausa) — refutação C, comportamento mantido."""
    linhas = _turnos(
        [
            (DirecaoMensagem.cliente, "oi"),
            (DirecaoMensagem.ia, "Consigo às 10h, fecha ?"),
        ],
        inicio=datetime(2026, 8, 13, 5, 0, tzinfo=UTC),
    )
    linhas.append(
        {
            "id": "m9",
            "direcao": DirecaoMensagem.cliente,
            "tipo": "texto",
            "conteudo": "voltei",
            "created_at": datetime(2026, 8, 13, 12, 25, tzinfo=UTC),  # >6h depois
        }
    )

    variaveis = await _variaveis(agora_brt=datetime(2026, 8, 13, 9, 32, tzinfo=BRT), linhas=linhas)

    assert variaveis.horario_minimo_apresentado == variaveis.horario_minimo
