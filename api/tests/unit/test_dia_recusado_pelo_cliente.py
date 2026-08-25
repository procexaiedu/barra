"""O DIA que o cliente já tirou da mesa (campanha 13/08, ciclo 7 — eb04:79981032001710).

Caso real: o cliente disse "Não hoje não" (t4), "Tô lotado hoje, sem chance" (t13) e "Hoje eu
realmente não consigo" (t14) — e a IA ofertou 11h (t12) e 14h (t13) do MESMO dia. Atropelar
restrição declarada é o erro capital nº 3 do playbook.

O contexto do t13 não tinha carimbo nenhum da recusa: o `<escada_travada_sem_o_dia>` afirmava
"você ainda NÃO sabe que dia ele quer" e o `<agenda>` abria a `janela_livre` em HOJE — o único dia
concreto à vista era justamente o recusado. O que já existia cobria outra coisa: `_TOKEN_OUTRO_DIA`
só VETA (impede assumir hoje, não registra a recusa), `classificar_recuo` é evento do burst que vai
para a extração (e nem casa estas falas), e a família do ADR-0041 condiciona o DESCONTO ao dia.

Aqui ficam as duas pontas do fix: o detector puro (`dia_recusado_pelo_cliente`, agente/_disciplina)
e a fiação até o bloco `<dia_recusado>` do `<agenda>`. Sem DB, sem crédito.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from barra.agente._disciplina import dia_recusado_pelo_cliente
from barra.agente.contexto import ContextAgente
from barra.agente.nos._contexto_do_turno import ContextoDoTurno
from barra.agente.nos.prepare_context import _resolver_variaveis
from barra.agente.persona import render_contexto_dinamico
from barra.dominio.conversas.modelos import DirecaoMensagem

_AGORA = datetime(2026, 8, 13, 12, 35, tzinfo=UTC)  # 09:35 BRT, o relógio do caso real
_HOJE = date(2026, 8, 13)

# --- detector puro ------------------------------------------------------------------------------


def _dele(*falas: str) -> list[tuple[bool, str]]:
    return [(False, f) for f in falas]


def test_as_tres_falas_do_caso_real_recusam_hoje() -> None:
    """As três formas que a conversa de verdade produziu — nenhuma delas casava em detector algum
    do projeto antes deste."""
    assert dia_recusado_pelo_cliente(_dele("Hahaha", "Não hoje não")) == "hoje"
    assert dia_recusado_pelo_cliente(_dele("Tô lotado hoje, sem chance.")) == "hoje"
    assert (
        dia_recusado_pelo_cliente(_dele("Hoje eu realmente não consigo, to sem cabeça e lotado"))
        == "hoje"
    )


def test_recusa_dupla_continua_valendo_no_turno_seguinte() -> None:
    """O carimbo é ESTADO da conversa contígua, não evento do burst: entre a recusa e a oferta da
    IA passaram turnos inteiros de outro assunto (vídeo, verificação), e é aí que ela reofertava."""
    bolhas = [
        (False, "Não hoje não"),
        (True, "Cheguei faz pouquinho amor"),
        (False, "Moro em valinhos sim, mas trabalho em camp"),
        (True, "400 1h no meu local"),
        (False, "Tô lotado hoje, sem chance."),
        (False, "Mas me conta, como funciona o rolê ai?"),
    ]

    assert dia_recusado_pelo_cliente(bolhas) == "hoje"


def test_recusa_hedgeada_do_c8_carimba() -> None:
    """t8 do c8: "Hmm hoje acho que não vou dar conta não / Tô lotado de coisa pra resolver".

    Duas coisas faltavam de uma vez — o "acho que" desgruda o "hoje" do "não" (por isso o hedge
    entra na negação colada), e "não vou dar conta" não era vocabulário de impossibilidade."""
    assert dia_recusado_pelo_cliente(_dele("Hmm hoje acho que não vou dar conta não")) == "hoje"
    assert dia_recusado_pelo_cliente(_dele("hoje realmente não")) == "hoje"
    assert dia_recusado_pelo_cliente(_dele("hoje infelizmente não")) == "hoje"


def test_o_motivo_em_outra_bolha_do_mesmo_burst_ainda_recusa() -> None:
    """A leitura de BURST: no WhatsApp o dia sai numa bolha e o motivo na seguinte, e ler cláusula
    a cláusula perdia a recusa inteira."""
    assert (
        dia_recusado_pelo_cliente(
            _dele("Hmm hoje acho que não vou dar conta não", "Tô lotado de coisa pra resolver")
        )
        == "hoje"
    )
    assert dia_recusado_pelo_cliente(_dele("hoje", "tô atolado de coisa")) == "hoje"


def test_incerteza_nao_e_recusa() -> None:
    """ "Hoje não sei" é o cliente PENSANDO — empurrá-lo pra amanhã joga fora quem ainda pode vir
    hoje, que é o erro simétrico ao que o carimbo corrige."""
    assert dia_recusado_pelo_cliente(_dele("hoje não sei")) is None
    assert dia_recusado_pelo_cliente(_dele("hoje não sei se consigo")) is None
    assert dia_recusado_pelo_cliente(_dele("hoje não tenho certeza")) is None
    assert dia_recusado_pelo_cliente(_dele("hoje acho que rola")) is None


def test_o_hedge_e_lista_fechada_nao_folga_livre() -> None:
    """O que separa a recusa hedgeada de uma frase qualquer com "hoje" e "não" no meio é a lista
    curta de advérbios — com folga livre, toda menção a hoje numa negativa viraria veto do dia."""
    assert dia_recusado_pelo_cliente(_dele("hoje eu não te falei o endereço")) is None
    assert dia_recusado_pelo_cliente(_dele("hoje de manhã não te respondi")) is None


def test_reabertura_no_mesmo_burst_desarma_a_leitura_de_burst() -> None:
    """A trava da leitura larga: com o dia REABERTO na mesma salva, o motivo não veta dia nenhum."""
    assert (
        dia_recusado_pelo_cliente(_dele("hoje eu consigo", "tô atolado mas dou um jeito")) is None
    )


def test_so_outro_dia_recusa_hoje_sem_nunca_dizer_hoje() -> None:
    assert dia_recusado_pelo_cliente(_dele("só amanhã")) == "hoje"
    assert dia_recusado_pelo_cliente(_dele("fica pra sexta então")) == "hoje"
    assert dia_recusado_pelo_cliente(_dele("melhor segunda amor")) == "hoje"
    # "só hoje" é o contrário: ninguém recusou nada.
    assert dia_recusado_pelo_cliente(_dele("só hoje mesmo")) is None


def test_recusa_de_outro_dia_nomeia_o_dia_recusado() -> None:
    assert dia_recusado_pelo_cliente(_dele("sexta não vai dar")) == "sexta"
    assert dia_recusado_pelo_cliente(_dele("amanhã tô lotado")) == "amanhã"


def test_pergunta_dele_sobre_hoje_nao_e_recusa() -> None:
    """O falso positivo que mataria a venda pelo outro lado: ele PERGUNTANDO por hoje é o cliente
    mais quente que existe. Mesmo veto do "?" que `horas_em_pauta_da_conversa` aplica."""
    assert dia_recusado_pelo_cliente(_dele("você está livre hoje?")) is None
    assert dia_recusado_pelo_cliente(_dele("Vc não tem horário hoje ?")) is None
    assert dia_recusado_pelo_cliente(_dele("da pra ser hoje ?")) is None


def test_recusa_de_horario_nao_e_recusa_do_dia() -> None:
    """ "10h não dá" tira uma HORA da pauta (`horas_em_pauta_da_conversa`), não o dia — quem trata
    a hora é o piso do `<horario_minimo>`."""
    assert dia_recusado_pelo_cliente(_dele("10h não dá pra mim, só consigo 11h")) is None
    assert dia_recusado_pelo_cliente(_dele("hoje às 10h não dá")) is None
    assert dia_recusado_pelo_cliente(_dele("às 14h não consigo não")) is None
    # o veto vale para as DUAS leituras: cláusula vetada não alimenta nem a do burst
    assert dia_recusado_pelo_cliente(_dele("hoje às 10h não vou dar conta")) is None


def test_objecao_de_preco_nao_e_recusa_do_dia() -> None:
    assert dia_recusado_pelo_cliente(_dele("hoje não consigo pagar isso")) is None
    assert dia_recusado_pelo_cliente(_dele("hoje tá caro amor")) is None


def test_a_fala_dela_nunca_recusa_o_proprio_dia() -> None:
    """Assimetria de desenho, a mesma da pauta de horas: quem fecha o dia é ELE. A bolha dela que
    cita hoje ("não consigo hoje mais cedo") não pode carimbar recusa contra ela mesma."""
    assert dia_recusado_pelo_cliente([(True, "hoje não consigo mais cedo não")]) is None


def test_a_fala_dela_corta_o_burst() -> None:
    """A leitura larga vale DENTRO da salva dele: dia numa salva e motivo em outra, com a fala dela
    no meio, são dois assuntos — juntá-los seria inventar a recusa que ele não declarou."""
    bolhas = [(False, "hoje"), (True, "Te espero amor"), (False, "tô atolado de trabalho")]

    assert dia_recusado_pelo_cliente(bolhas) is None


def test_ele_reabre_o_dia_e_o_carimbo_some() -> None:
    assert dia_recusado_pelo_cliente(_dele("hoje não", "hoje agora deu certo")) is None
    assert dia_recusado_pelo_cliente(_dele("Tô lotado hoje", "consigo hoje sim")) is None
    assert dia_recusado_pelo_cliente(_dele("hoje não consigo", "hoje pode ser então")) is None


def test_reabrir_outro_dia_nao_reabre_o_recusado() -> None:
    """O t17 do caso real ("Amanhã consigo sim"): ele marca AMANHÃ, e hoje segue fora da mesa."""
    assert dia_recusado_pelo_cliente(_dele("hoje não consigo", "Amanhã consigo sim")) == "hoje"


# --- fiação: da janela crua ao bloco do prompt ---------------------------------------------------


def _bolha(direcao: DirecaoMensagem, texto: str, *, minutos: int = 0) -> dict[str, Any]:
    return {
        "id": f"m{minutos}",
        "direcao": direcao,
        "conteudo": texto,
        "tipo": "texto",
        "created_at": _AGORA + timedelta(minutes=minutos),
    }


def _conversa(*bolhas: tuple[str, str], gap_min: int = 1) -> list[dict[str, Any]]:
    return [
        _bolha(
            DirecaoMensagem.cliente if quem == "ele" else DirecaoMensagem.ia,
            texto,
            minutos=i * gap_min,
        )
        for i, (quem, texto) in enumerate(bolhas)
    ]


class _FakeConn1h400:
    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> Any:
        linhas = (
            [{"programa_id": "p1", "preco": Decimal("400"), "preco_minimo": Decimal("300")}]
            if "modelo_programas" in sql
            else []
        )

        class _R:
            async def fetchone(self) -> dict[str, Any] | None:
                return None

            async def fetchall(self) -> list[Any]:
                return linhas

        return _R()


async def _do_turno(linhas: list[dict[str, Any]]) -> tuple[ContextoDoTurno, str]:
    ctx = ContextAgente(
        db_pool=None,  # type: ignore[arg-type]
        redis=None,  # type: ignore[arg-type]
        modelo_id="11111111-1111-1111-1111-111111111111",
        atendimento_id="22222222-2222-2222-2222-222222222222",
        cliente_id="33333333-3333-3333-3333-333333333333",
        turno_id="t",
        agora_utc=_AGORA,
    )
    contexto = await _resolver_variaveis(
        _FakeConn1h400(),  # type: ignore[arg-type]
        ctx,
        linhas,
        atendimento={
            "estado": "Triagem",
            "n_contrapropostas": 0,
            "duracao_horas": Decimal("1"),
            "valor_acordado": Decimal("400"),
            "data_desejada": None,
        },
        precos_por_horas={1.0: [Decimal("400")]},
    )
    return contexto, render_contexto_dinamico(**contexto.como_variaveis())


async def test_o_turno_do_caso_real_carimba_e_renderiza_o_veto() -> None:
    """O t13 reconstruído: recusa no t4, recusa de novo agora, e a IA prestes a ofertar 14h."""
    contexto, prompt = await _do_turno(
        _conversa(
            ("ele", "Não hoje não"),
            ("ela", "Cheguei faz pouquinho amor, to conhecendo ainda rs"),
            ("ela", "400 1h no meu local, aqui na Barra"),
            ("ele", "Tô lotado hoje, sem chance."),
            ("ele", "Mas me conta, como funciona o rolê ai?"),
        )
    )

    assert contexto.dia_recusado == "hoje"
    assert '<dia_recusado dia="hoje">' in prompt
    # O bloco tem de NOMEAR o veto (o dia fora da mesa) e fechar a porta da re-pergunta, que é o
    # que o <escada_travada_sem_o_dia> manda fazer quando o dia é desconhecido.
    bloco = prompt.split('<dia_recusado dia="hoje">')[1].split("</dia_recusado>")[0]
    assert "FORA da mesa" in bloco
    assert "NÃO recusou" in bloco  # a oferta mira o primeiro dia que sobrou


async def test_a_recusa_hedgeada_do_c8_chega_ao_prompt() -> None:
    """O t8 do c8 pelo caminho inteiro: duas bolhas do mesmo burst, o dia numa e o motivo na outra."""
    contexto, prompt = await _do_turno(
        _conversa(
            ("ela", "Estou livre hoje amor"),
            ("ele", "Hmm hoje acho que não vou dar conta não"),
            ("ele", "Tô lotado de coisa pra resolver"),
        )
    )

    assert contexto.dia_recusado == "hoje"
    assert '<dia_recusado dia="hoje">' in prompt


async def test_incerteza_nao_renderiza_bloco() -> None:
    _contexto, prompt = await _do_turno(
        _conversa(("ela", "Estou livre hoje amor"), ("ele", "hoje não sei ainda"))
    )

    assert "<dia_recusado" not in prompt


async def test_pergunta_dele_sobre_hoje_nao_renderiza_bloco() -> None:
    _contexto, prompt = await _do_turno(
        _conversa(("ela", "400 1h no meu local"), ("ele", "você tem horário hoje ?"))
    )

    assert "<dia_recusado" not in prompt


async def test_recusa_de_horario_nao_renderiza_bloco() -> None:
    _contexto, prompt = await _do_turno(
        _conversa(("ela", "Consigo às 10h, fecha ?"), ("ele", "10h não dá pra mim"))
    )

    assert "<dia_recusado" not in prompt


async def test_reabertura_apaga_o_bloco() -> None:
    _contexto, prompt = await _do_turno(
        _conversa(
            ("ele", "Tô lotado hoje, sem chance."),
            ("ela", "Fica tranquilo amor"),
            ("ele", "amor, hoje agora deu certo"),
        )
    )

    assert "<dia_recusado" not in prompt


async def test_pausa_de_6h_apaga_a_recusa_velha() -> None:
    """Mesma régua de contiguidade do piso (`_GAP_PAUSA`): a recusa de "hoje" de ontem não é a de
    hoje, e o detector não precisa de relógio próprio para saber disso."""
    linhas = [
        _bolha(DirecaoMensagem.cliente, "Não hoje não", minutos=0),
        _bolha(DirecaoMensagem.ia, "Tranquilo amor", minutos=1),
        _bolha(DirecaoMensagem.cliente, "Oi, tudo bem ?", minutos=7 * 60),
    ]

    contexto, prompt = await _do_turno(linhas)

    assert contexto.dia_recusado is None
    assert "<dia_recusado" not in prompt


async def test_conversa_sem_recusa_nao_paga_nada_no_prompt() -> None:
    contexto, prompt = await _do_turno(
        _conversa(("ele", "Oie, tudo joia?"), ("ela", "Tudo sim amor"), ("ele", "Que legal rs"))
    )

    assert contexto.dia_recusado is None
    assert "<dia_recusado" not in prompt
    assert f'<agenda hoje="{_HOJE}"' in prompt
