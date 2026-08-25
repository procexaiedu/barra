"""A rotina da manha cobra a Ficha sem desfecho (spec 0006, ticket 10; ADR-0044/0046).

Ficha esquecida e dinheiro perdido, e ela e o unico item da cobranca que **nao** e derivado de uma
venda: enquanto ninguem diz que recebeu, o atendimento do Igor nao existe em coluna nenhuma do
extrato — nao esta em `a_comprovar`, nem em `sem_forma`, nem em `em_especie`. Ninguem sente falta
dele. Por isso a linha nova entra na MESMA mensagem consolidada, e nao numa pergunta na hora:
o combinado pode nem ter acontecido quando o card e postado.

O que este arquivo prova, e nenhuma linha dele precisa de banco:

1. **O corte** (`fichas_sem_desfecho`) — so ficha VIVA e VENCIDA e cobrada. O ❌ (cancelada) e a
   ficha ja promovida (realizada) somem; a de hoje ainda vai acontecer; a sem data nao tem como
   ser nomeada nem datada, e nao vira pergunta no escuro.
2. **A fala** — a linha nomeia cliente, valor e dia, e pede a forma junto com o "rolou?", porque a
   venda so nasce com a forma dita (ADR-0046 §5). O valor e o **dela** (`valor_de`), nunca o total
   da festinha.
3. **O teto** — dez pendencias viram UMA mensagem, com as mais recentes nomeadas e o resto
   resumido com quantas, quando e quanto.
4. **O silencio continua sendo o default** — ficha que ainda nao venceu nao e pendencia acionavel,
   e grupo sem nada acionavel nao recebe mensagem nenhuma.
5. **A resposta cai na ficha certa e a promove** — a cobranca nomeia o cliente, e e o nome citado
   que faz "o do Igor foi pix" atravessar a allowlist (`ler_fala_de_pagamento`), escolher a ficha
   certa entre duas (`escolher_ficha`) e virar a Venda registrada (`planejar_promocao`).
6. **Uma mensagem por grupo por dia** — `cobrar_pendencias_do_grupo` com o repo trocado por
   dubles: a segunda corrida do mesmo dia bate na reserva e nao fala.

O que so o banco prova — a reserva `chave_dedup` de verdade, a ficha virando `realizada`, a
resposta entrando pela porta unica — vive em `tests/integracao/`, com `needs_db`.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest

from barra.agente_financeiro import rotina as rotina_do_agente
from barra.dominio.grupo_financeiro.fechamento import Extrato
from barra.dominio.grupo_financeiro.ficha import (
    EstadoDaFicha,
    FichaDeAgendamento,
    ParticipanteDaFicha,
    planejar_promocao,
)
from barra.dominio.grupo_financeiro.modelos import GrupoFinanceiro, VendaRegistrada
from barra.dominio.grupo_financeiro.pagamento import escolher_ficha, ler_fala_de_pagamento
from barra.dominio.grupo_financeiro.rotina import (
    MAX_FICHAS_NOMEADAS,
    MovimentoDoGrupo,
    fichas_sem_desfecho,
    montar_cobranca_da_manha,
)
from barra.dominio.grupo_financeiro.voz import e_fala_do_agente

YASMIN = UUID("11111111-1111-1111-1111-111111111111")
JULIA = UUID("22222222-2222-2222-2222-222222222222")

HOJE = date(2026, 8, 14)
ONTEM = date(2026, 8, 13)
# 14/08 11:00 UTC = 08:00 BRT: a janela em que o cron da manha roda.
MANHA = datetime(2026, 8, 14, 11, 0, tzinfo=UTC)


def _ficha(
    *,
    cliente: str | None = "Igor",
    valor: str | None = "700.00",
    dia: date | None = ONTEM,
    estado: EstadoDaFicha = "aberta",
    participantes: tuple[ParticipanteDaFicha, ...] | None = None,
    valor_total: str | None = None,
) -> FichaDeAgendamento:
    if participantes is None:
        participantes = (
            ParticipanteDaFicha(
                modelo_id=YASMIN, valor=Decimal(valor) if valor else None, nome="Yasmin"
            ),
        )
    return FichaDeAgendamento(
        id=uuid4(),
        estado=estado,
        mensagem_id=uuid4(),
        chave_conteudo=f"ficha:{cliente}:{dia}:{valor}",
        participantes=participantes,
        cliente_nome=cliente,
        data=dia,
        valor_total=Decimal(valor_total) if valor_total else None,
    )


def _extrato(**kw: Any) -> Extrato:
    return Extrato(modelo_id=YASMIN, **kw)


def _venda(valor: str, *, cliente: str = "Gabriel", dia: date = ONTEM) -> VendaRegistrada:
    return VendaRegistrada(
        id=uuid4(),
        modelo_id=YASMIN,
        valor=Decimal(valor),
        data=dia,
        mensagem_id=uuid4(),
        cliente_nome=cliente,
    )


# --- 1. o corte: quem e cobrada ------------------------------------------------------------------


def test_ficha_aberta_de_ontem_e_cobrada() -> None:
    ficha = _ficha()
    assert fichas_sem_desfecho([ficha], hoje=HOJE) == (ficha,)


@pytest.mark.parametrize("estado", ["cancelada", "realizada"])
def test_ficha_com_desfecho_nunca_e_cobrada(estado: EstadoDaFicha) -> None:
    """O ❌ mata a ficha e a promocao a resolve — cobrar depois disso e a pendencia orfa."""
    assert fichas_sem_desfecho([_ficha(estado=estado)], hoje=HOJE) == ()


def test_ficha_de_hoje_ainda_vai_acontecer() -> None:
    """Perguntar "rolou?" as 8h sobre o combinado da noite gasta a unica mensagem do dia."""
    assert fichas_sem_desfecho([_ficha(dia=HOJE)], hoje=HOJE) == ()


def test_ficha_sem_data_nao_vira_pergunta_no_escuro() -> None:
    """A ficha nascida de um comunicado nao diz quando: sem dia nao da para saber se venceu."""
    assert fichas_sem_desfecho([_ficha(dia=None)], hoje=HOJE) == ()


def test_ficha_confirmada_continua_esperando_desfecho() -> None:
    """`confirmada` e um estado ABERTO: o cliente confirmou, o dinheiro ninguem viu."""
    ficha = _ficha(estado="confirmada")
    assert fichas_sem_desfecho([ficha], hoje=HOJE) == (ficha,)


# --- 2. a fala -----------------------------------------------------------------------------------


def _cobranca(**kw: Any) -> str:
    fala = montar_cobranca_da_manha(
        extrato=kw.pop("extrato", _extrato()),
        a_cobrar=kw.pop("a_cobrar", []),
        movimento=kw.pop("movimento", MovimentoDoGrupo()),
        hoje=kw.pop("hoje", HOJE),
        **kw,
    )
    assert fala is not None
    return fala


def test_a_linha_da_ficha_nomeia_cliente_valor_e_dia() -> None:
    fala = _cobranca(fichas=[_ficha()])
    assert "❓ Ficha · Cliente Igor · R$ 700,00 · ontem — rolou? foi pix ou dinheiro?" in fala
    # A voz do agente tem que se reconhecer: e a segunda tranca do corte de eco.
    assert e_fala_do_agente(fala)


def test_a_pergunta_pede_a_forma_junto() -> None:
    """ "Rolou?" sozinho colhe um "sim" que nao promove nada — a venda nasce com a forma dita."""
    fala = _cobranca(fichas=[_ficha()])
    assert "foi pix ou dinheiro?" in fala


def test_a_ficha_de_festinha_mostra_o_valor_dela_e_nunca_o_total() -> None:
    ficha = _ficha(
        valor_total="2000.00",
        participantes=(
            ParticipanteDaFicha(modelo_id=YASMIN, valor=Decimal("700.00"), ordem=1),
            ParticipanteDaFicha(modelo_id=JULIA, valor=Decimal("1300.00"), ordem=2),
        ),
    )
    fala = _cobranca(fichas=[ficha])
    assert "R$ 700,00" in fala
    assert "2.000,00" not in fala
    assert "1.300,00" not in fala


def test_ficha_sem_valor_da_participante_sai_sem_valor_inventado() -> None:
    """Cliente e dia ainda identificam o atendimento; inventar um numero e pior que omiti-lo."""
    fala = _cobranca(fichas=[_ficha(valor=None)])
    linha = next(x for x in fala.splitlines() if x.startswith("❓ Ficha"))
    assert linha == "❓ Ficha · Cliente Igor · ontem — rolou? foi pix ou dinheiro?"


def test_a_ficha_nao_se_confunde_com_a_venda_do_mesmo_cliente() -> None:
    """As duas linhas tem a mesma gramatica; o rotulo "Ficha" e o que as separa."""
    fala = _cobranca(a_cobrar=[_venda("700.00", cliente="Igor")], fichas=[_ficha()])
    linhas = [linha for linha in fala.splitlines() if "Igor" in linha]
    assert len(linhas) == 2
    assert sum(linha.startswith("❓ Ficha ·") for linha in linhas) == 1


def test_ficha_vencida_ha_dias_leva_a_data_crua() -> None:
    fala = _cobranca(fichas=[_ficha(dia=date(2026, 8, 7))])
    assert "· 07/08 —" in fala


# --- 3. o teto -----------------------------------------------------------------------------------


def test_dez_fichas_viram_uma_mensagem_com_as_recentes_nomeadas() -> None:
    # 04/08 a 13/08, uma por dia — a ordem em que o repo devolve (a mais antiga primeiro).
    fichas = [
        _ficha(cliente=f"Cliente{i}", valor="100.00", dia=date(2026, 8, 4) + timedelta(days=i))
        for i in range(10)
    ]
    fala = _cobranca(fichas=fichas)
    nomeadas = [linha for linha in fala.splitlines() if linha.startswith("❓ Ficha · Cliente")]
    assert len(nomeadas) == MAX_FICHAS_NOMEADAS
    # As NOMEADAS sao as mais RECENTES: a de ontem e a que alguem ainda lembra e responde.
    assert "Cliente9" in fala
    assert "Cliente0" not in fala
    resumo = next(linha for linha in fala.splitlines() if "sem desfecho" in linha)
    assert resumo == "❓ E mais 7 fichas sem desfecho de 04/08 a 10/08 (R$ 700,00)."


def test_o_resumo_de_uma_ficha_so_fica_no_singular() -> None:
    fichas = [
        _ficha(cliente=f"C{i}", valor="100.00", dia=date(2026, 8, 8) + timedelta(days=i))
        for i in range(4)
    ]
    fala = _cobranca(fichas=fichas)
    assert "❓ E mais 1 ficha sem desfecho de 08/08 (R$ 100,00)." in fala


# --- 4. o silencio -------------------------------------------------------------------------------


def test_grupo_sem_nada_acionavel_nao_recebe_mensagem() -> None:
    assert (
        montar_cobranca_da_manha(
            extrato=_extrato(),
            a_cobrar=[],
            movimento=MovimentoDoGrupo(),
            hoje=HOJE,
            fichas=[_ficha(dia=HOJE), _ficha(estado="cancelada"), _ficha(dia=None)],
        )
        is None
    )


def test_a_ficha_sozinha_ja_e_motivo_para_falar() -> None:
    fala = montar_cobranca_da_manha(
        extrato=_extrato(),
        a_cobrar=[],
        movimento=MovimentoDoGrupo(),
        hoje=HOJE,
        fichas=[_ficha()],
    )
    assert fala is not None
    assert fala.startswith("☀️ Bom dia! Ficou pendente:")


def test_ficha_sozinha_nao_arrasta_um_saldo_zerado() -> None:
    """ "Ficou pendente" seguido de "R$ 0,00 em aberto" e a mensagem se contradizendo.

    A ficha e a unica pendencia que nao e derivada de uma venda, entao e a primeira que pode
    aparecer sozinha num extrato zerado: o atendimento existe e o modulo ainda nao tem numero
    nenhum sobre ele. O saldo volta assim que houver o que somar.
    """
    fala = _cobranca(fichas=[_ficha()])
    assert "Em aberto" not in fala

    com_venda = _cobranca(
        extrato=_extrato(vendido=Decimal("700.00"), sem_forma=Decimal("700.00")),
        a_cobrar=[_venda("700.00")],
        fichas=[_ficha()],
    )
    assert "📊 Em aberto: R$ 700,00 de R$ 700,00 vendidos" in com_venda


# --- 5. a resposta cai na ficha certa e a promove ------------------------------------------------


def test_o_nome_citado_na_cobranca_e_o_que_deixa_a_resposta_passar() -> None:
    """Nome proprio nao passa pela allowlist a menos que seja cliente de algo aberto."""
    igor, lucas = _ficha(cliente="Igor"), _ficha(cliente="Lucas", valor="600.00")
    fala = _cobranca(fichas=[igor, lucas])
    assert "Cliente Igor" in fala and "Cliente Lucas" in fala

    resposta = "o do Igor foi pix"
    assert ler_fala_de_pagamento(resposta) is None
    lida = ler_fala_de_pagamento(resposta, nomes_de_cliente=["Igor", "Lucas"])
    assert lida is not None and lida.forma == "pix"

    escolha = escolher_ficha(texto=resposta, abertas=[igor, lucas])
    assert escolha.motivo == "escolhida"
    assert escolha.ficha is igor

    promocao = planejar_promocao(
        igor, modelo_id=YASMIN, origem_do_gesto="modelo", dia_do_gesto=HOJE, forma="pix"
    )
    assert promocao is not None
    assert promocao.ficha_id == igor.id
    assert promocao.valor == Decimal("700.00")
    # A venda pertence ao dia do COMBINADO, nao ao da manha em que a cobranca foi respondida.
    assert promocao.data == ONTEM
    assert promocao.forma_pagamento == "pix"


# --- 6. uma mensagem por grupo por dia -----------------------------------------------------------


class _Repo:
    """Os dubles do repo. A rotina le quatro coisas e reserva uma — nada mais toca o banco."""

    def __init__(self, fichas: list[FichaDeAgendamento]) -> None:
        self.fichas = fichas
        self.reservas: list[str] = []
        self.falou = False

    async def fechamento(self, conn: Any, modelo_id: UUID) -> Extrato:
        return _extrato()

    async def sem_forma(self, conn: Any, modelo_id: UUID) -> list[VendaRegistrada]:
        return []

    async def movimento(self, conn: Any, grupo_id: UUID, *, desde: datetime) -> MovimentoDoGrupo:
        return MovimentoDoGrupo()

    async def abertas(self, conn: Any, modelo_id: UUID) -> list[FichaDeAgendamento]:
        return list(self.fichas)

    async def reservar(
        self, conn: Any, grupo_id: UUID, *, chave: str, texto: str, em: datetime
    ) -> UUID | None:
        if chave in self.reservas:
            return None
        self.reservas.append(chave)
        return uuid4()


@pytest.fixture
def repo(monkeypatch: pytest.MonkeyPatch) -> _Repo:
    duble = _Repo([_ficha()])
    monkeypatch.setattr(rotina_do_agente, "fechamento_da_modelo", duble.fechamento)
    monkeypatch.setattr(rotina_do_agente, "vendas_sem_forma_de_pagamento", duble.sem_forma)
    monkeypatch.setattr(rotina_do_agente, "movimento_do_grupo", duble.movimento)
    monkeypatch.setattr(rotina_do_agente, "fichas_abertas_da_modelo", duble.abertas)
    monkeypatch.setattr(rotina_do_agente, "reservar_fala_da_rotina", duble.reservar)
    return duble


GRUPO = GrupoFinanceiro(id=uuid4(), modelo_id=YASMIN, jid="123@g.us", nome="Yasmin")
CONN: Any = None
"""A conexao nunca e tocada: os cinco acessos ao banco estao trocados por dubles."""


async def test_a_rotina_cobra_a_ficha_e_devolve_qual(repo: _Repo) -> None:
    falas: list[str] = []

    async def enviar(texto: str, *, citar: str | None = None) -> None:
        falas.append(texto)

    resultado = await rotina_do_agente.cobrar_pendencias_do_grupo(
        CONN, GRUPO, agora=MANHA, enviar=enviar
    )

    assert resultado.status == "cobrou"
    assert resultado.fichas == (repo.fichas[0].id,)
    assert len(falas) == 1
    assert "Cliente Igor" in falas[0]


async def test_a_segunda_corrida_do_dia_nao_fala_de_novo(repo: _Repo) -> None:
    falas: list[str] = []

    async def enviar(texto: str, *, citar: str | None = None) -> None:
        falas.append(texto)

    for _ in range(2):
        resultado = await rotina_do_agente.cobrar_pendencias_do_grupo(
            CONN, GRUPO, agora=MANHA, enviar=enviar
        )

    assert resultado.status == "ja_falou"
    assert resultado.fichas == ()
    assert len(falas) == 1


async def test_sem_ficha_vencida_a_rotina_cala(repo: _Repo) -> None:
    repo.fichas = [_ficha(dia=HOJE)]
    falas: list[str] = []

    async def enviar(texto: str, *, citar: str | None = None) -> None:
        falas.append(texto)

    resultado = await rotina_do_agente.cobrar_pendencias_do_grupo(
        CONN, GRUPO, agora=MANHA, enviar=enviar
    )

    assert resultado.status == "silencio"
    assert falas == []
    assert repo.reservas == []
