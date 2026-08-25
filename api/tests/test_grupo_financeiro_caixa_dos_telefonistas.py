"""O caixa dos telefonistas: segunda fonte, em leitura (spec 0006, ticket 17).

Offline: sem banco, sem chave, sem rede. O que se prova aqui é a **decisão** — a mesma que a
produção toma com o Postgres atrás.

O grupo do caixa é onde o gestor confere o dia com todas as modelos juntas — *"legal a gente fazer
uma conferência dos dois, até mesmo para saber se as informações estão batendo"*. A IA entra ali só
para **ler**, e os invariantes que quebram calado se ninguém olhar são três:

  * **nada nasce do caixa**: o mesmo anúncio que no grupo individual vira Venda registrada e recibo
    ali não vira nada, e o agente não fala. Sem isso, a mesma venda entra duas vezes e a receita da
    casa dobra sem uma linha de erro em lugar nenhum;
  * **as duas colunas nunca se somam**: `total_no_caixa` e `total_no_sistema` são o mesmo dinheiro
    contado por duas bocas. Somá-las é exatamente o bug que este ticket existe para impedir;
  * **silêncio não é "bateu"**: um dia em que ninguém escreveu no caixa sai como *não dá para
    afirmar* (`bate is None`), nunca como conferido — e nunca como uma divergência por venda do dia.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from psycopg import AsyncConnection

from barra.agente_financeiro import porta as porta_mod
from barra.agente_financeiro import processar_evento_do_grupo
from barra.agente_financeiro.rotina import grupos_da_rotina
from barra.dominio.grupo_financeiro import service as service_mod
from barra.dominio.grupo_financeiro.conferencia import (
    ConferenciaDoCaixa,
    LinhaDoCaixa,
    conferir,
    ler_caixa,
)
from barra.dominio.grupo_financeiro.modelos import (
    DelecaoNoGrupo,
    GrupoFinanceiro,
    GrupoSemDona,
    MensagemDoGrupo,
    MensagemRegistrada,
    VendaRegistrada,
)
from barra.dominio.grupo_financeiro.nomes import CadastroDeNomes

YASMIN = uuid4()
BIANCA = uuid4()

CADASTRO = CadastroDeNomes.de_linhas(
    modelos=[(YASMIN, "Yasmin"), (BIANCA, "Bianca")],
    apelidos=[(YASMIN, "Sofia")],
)

CAIXA_JID = "120363000000000017@g.us"
GRUPO_DA_YASMIN_JID = "120363000000000001@g.us"

DIA = date(2026, 8, 20)
NOITE = datetime(2026, 8, 20, 23, 40, tzinfo=UTC)  # 20h40 em BRT — ainda dia 20
MADRUGADA = datetime(2026, 8, 21, 3, 10, tzinfo=UTC)  # 00h10 em BRT — já dia 21

ANUNCIO = """Atendimento no nosso local
Cliente Gabriel
Perfil Sofia
700 1h"""

ANUNCIO_DA_BIANCA = """Atendimento no nosso local
Cliente Igor
Perfil Bianca
900 1h"""

FESTINHA = """Atendimento no nosso local
Cliente Ramon
Perfil Sofia
Perfil Bianca
1200 1h
600 cada uma"""


def _msg(
    texto: str, *, quando: datetime = NOITE, de_mim: bool = False, id: UUID | None = None
) -> MensagemRegistrada:
    return MensagemRegistrada(id=id or uuid4(), texto=texto, de_mim=de_mim, recebida_em=quando)


def _venda(
    *,
    modelo_id: UUID = YASMIN,
    valor: str = "700.00",
    dia: date = DIA,
    cliente: str | None = "Gabriel",
) -> VendaRegistrada:
    return VendaRegistrada(
        id=uuid4(),
        modelo_id=modelo_id,
        valor=Decimal(valor),
        data=dia,
        mensagem_id=uuid4(),
        cliente_nome=cliente,
    )


# --- a leitura do caixa: mesmo leitor do grupo, e a modelo vem do texto --------------------------


def test_o_caixa_e_lido_pelo_mesmo_leitor_do_grupo_e_a_modelo_vem_do_perfil() -> None:
    """No caixa estão todas as modelos: herdar a dona do grupo daria o atendimento a qualquer uma."""
    leitura = ler_caixa([_msg(ANUNCIO)], cadastro=CADASTRO)

    assert len(leitura.linhas) == 1
    linha = leitura.linhas[0]
    assert linha.modelo_id == YASMIN  # "Sofia" é o nome de anúncio dela
    assert linha.valor == Decimal("700.00")
    assert linha.data == DIA
    assert linha.cliente_nome == "Gabriel"
    assert leitura.nao_lidas == ()


def test_conversa_de_telefonista_nao_e_linha_nem_leitura_que_faltou() -> None:
    """ "subiu?" não é anúncio: sai pela triagem barata, sem virar pendência de conferência."""
    leitura = ler_caixa([_msg("subiu?"), _msg("ela chegou")], cadastro=CADASTRO)

    assert leitura.linhas == ()
    assert leitura.nao_lidas == ()


def test_nome_que_o_cadastro_nao_conhece_vira_nao_lida_e_nunca_divergencia() -> None:
    """Errar para "não deu para conferir" é recuperável; inventar a modelo, não."""
    mensagem = _msg(ANUNCIO.replace("Perfil Sofia", "Perfil fran loira"))

    leitura = ler_caixa([mensagem], cadastro=CADASTRO)

    assert leitura.linhas == ()
    assert leitura.nao_lidas == (mensagem.id,)


def test_a_propria_fala_do_agente_no_caixa_nao_vira_segunda_fonte() -> None:
    """O recibo tem gramática de anúncio de propósito, e `fromMe` se inverte nesta casa
    (`voz.py`) — sem os dois cortes, o agente viraria a fonte que ele deveria conferir.

    O texto abaixo passa a triagem (duas linhas da gramática) e só não vira linha porque a
    PRIMEIRA linha é a voz do agente: é o recibo colado de volta, e o mesmo formato que a fala
    dele teria se um dia ele falasse ali.
    """
    eco = f"✅ Registrei: Yasmin R$ 700,00 · 20/08\n{ANUNCIO}"

    assert ler_caixa([_msg(eco)], cadastro=CADASTRO).linhas == ()
    assert ler_caixa([_msg(ANUNCIO, de_mim=True)], cadastro=CADASTRO).linhas == ()
    # A tranca é a voz/`de_mim`, não a triagem: sem elas, este mesmo texto rende a linha.
    assert (
        len(
            ler_caixa(
                [_msg(eco.replace("✅ Registrei:", "Fechamos assim:"))], cadastro=CADASTRO
            ).linhas
        )
        == 1
    )


def test_festinha_no_caixa_rende_uma_linha_por_modelo_no_valor_de_cada_uma() -> None:
    """O rateio é o do grupo (`rateio.planejar`): um segundo leitor divergiria justo na borda."""
    leitura = ler_caixa([_msg(FESTINHA)], cadastro=CADASTRO)

    assert {(linha.modelo_id, linha.valor) for linha in leitura.linhas} == {
        (YASMIN, Decimal("600.00")),
        (BIANCA, Decimal("600.00")),
    }


def test_a_madrugada_ainda_conta_como_o_dia_seguinte_em_brt() -> None:
    """O grupo escreve de madrugada; datar por UTC jogaria a conferência das 22h para amanhã."""
    leitura = ler_caixa([_msg(ANUNCIO, quando=MADRUGADA)], cadastro=CADASTRO)

    assert leitura.linhas[0].data == date(2026, 8, 21)


# --- a conferência: duas fontes, nunca uma soma --------------------------------------------------


def _conferir(
    *,
    caixa: list[LinhaDoCaixa],
    vendas: list[VendaRegistrada],
    nao_lidas: tuple[UUID, ...] = (),
) -> ConferenciaDoCaixa:
    return conferir(linhas_do_caixa=caixa, vendas=vendas, de=DIA, ate=DIA, nao_lidas=nao_lidas)


def _linha(*, modelo_id: UUID = YASMIN, valor: str = "700.00", dia: date = DIA) -> LinhaDoCaixa:
    return LinhaDoCaixa(
        modelo_id=modelo_id,
        valor=Decimal(valor),
        data=dia,
        mensagem_id=uuid4(),
        cliente_nome="Gabriel",
    )


def test_a_mesma_venda_nas_duas_fontes_conta_uma_vez_e_os_totais_nao_se_somam() -> None:
    """O par é a MESMA venda dita duas vezes: ele vira `conferidas`, nunca receita."""
    conferencia = _conferir(caixa=[_linha()], vendas=[_venda()])

    assert conferencia.conferidas == 1
    assert conferencia.divergencias == ()
    assert conferencia.bate is True
    assert conferencia.total_no_caixa == Decimal("700.00")
    assert conferencia.total_no_sistema == Decimal("700.00")
    assert conferencia.diferenca == Decimal("0.00")


def test_duas_vendas_iguais_no_mesmo_dia_casam_duas_vezes() -> None:
    """Multiconjunto, não conjunto: com par por valor "único", a segunda de R$ 700 divergiria
    sozinha todo dia em que a modelo atende dois clientes pelo mesmo preço."""
    conferencia = _conferir(caixa=[_linha(), _linha()], vendas=[_venda(), _venda()])

    assert conferencia.conferidas == 2
    assert conferencia.divergencias == ()


def test_atendimento_so_no_caixa_vira_flag_apontando_a_mensagem() -> None:
    """O lado que esconde receita: o caixa conta, o sistema não registrou."""
    linha = _linha()

    conferencia = _conferir(caixa=[linha], vendas=[])

    assert [d.tipo for d in conferencia.divergencias] == ["so_no_caixa"]
    divergencia = conferencia.divergencias[0]
    assert divergencia.modelo_id == YASMIN
    assert divergencia.valor == Decimal("700.00")
    assert divergencia.mensagem_id == linha.mensagem_id
    assert divergencia.venda_id is None
    assert conferencia.bate is False


def test_venda_que_o_caixa_nao_mencionou_vira_flag_apontando_a_venda() -> None:
    venda = _venda(modelo_id=BIANCA, valor="900.00", cliente="Igor")

    conferencia = _conferir(caixa=[_linha()], vendas=[_venda(), venda])

    assert [d.tipo for d in conferencia.divergencias] == ["so_no_sistema"]
    divergencia = conferencia.divergencias[0]
    assert divergencia.venda_id == venda.id
    assert divergencia.modelo_id == BIANCA
    assert divergencia.cliente_nome == "Igor"
    assert divergencia.mensagem_id is None


def test_caixa_escrito_na_manha_seguinte_ainda_casa_com_a_venda_da_vespera() -> None:
    """Exigir o mesmo dia pintaria de vermelho toda conferência feita depois da meia-noite — e uma
    flag que acende sempre é uma flag que ninguém lê."""
    conferencia = conferir(
        linhas_do_caixa=[_linha(dia=date(2026, 8, 21))],
        vendas=[_venda(dia=DIA)],
        de=DIA,
        ate=date(2026, 8, 21),
    )

    assert conferencia.conferidas == 1
    assert conferencia.divergencias == ()


def test_dia_sem_nada_escrito_no_caixa_nao_bate_nem_diverge() -> None:
    """Sem segunda fonte não há conferência: dizer "bateu" seria dar por conferido um dia em que
    ninguém conferiu, e abrir uma divergência por venda seria alarme sobre quem não falou."""
    conferencia = _conferir(caixa=[], vendas=[_venda(), _venda(modelo_id=BIANCA)])

    assert conferencia.bate is None
    assert conferencia.divergencias == ()
    assert conferencia.total_no_sistema == Decimal("1400.00")
    assert conferencia.total_no_caixa == Decimal("0.00")


def test_o_que_nao_deu_para_ler_viaja_junto_da_flag() -> None:
    """Dez divergências com trinta linhas não lidas não são dez erros."""
    nao_lida = uuid4()

    conferencia = _conferir(caixa=[_linha()], vendas=[], nao_lidas=(nao_lida,))

    assert conferencia.nao_lidas == (nao_lida,)
    assert conferencia.bate is False


# --- a porta: no caixa a IA lê e não escreve nem fala --------------------------------------------


class _Cursor:
    async def fetchone(self) -> None:
        return None

    async def fetchall(self) -> list[Any]:
        return []


class _Conexao:
    """Conexão fake que aceita qualquer SQL e devolve vazio, guardando o que foi consultado."""

    def __init__(self) -> None:
        self.consultas: list[str] = []

    async def execute(self, sql: str, params: Any = None) -> _Cursor:
        self.consultas.append(sql)
        return _Cursor()


def _conn(fake: _Conexao) -> AsyncConnection[Any]:
    return cast(AsyncConnection[Any], fake)


class _Porta:
    def __init__(self) -> None:
        self.falas: list[str] = []
        self.mensagens_registradas: list[MensagemDoGrupo] = []
        self.apagadas: list[str] = []

    async def enviar(self, texto: str, *, citar: str | None = None) -> None:
        self.falas.append(texto)


@pytest.fixture
def porta(monkeypatch: pytest.MonkeyPatch) -> _Porta:
    estado = _Porta()

    async def registrar_mensagem(conn: Any, grupo_id: UUID, msg: MensagemDoGrupo) -> UUID:
        estado.mensagens_registradas.append(msg)
        return uuid4()

    async def marcar_mensagem_apagada(
        conn: Any, grupo_id: UUID, evolution_message_id: str, *, em: Any = None
    ) -> None:
        estado.apagadas.append(evolution_message_id)
        return None

    async def carregar_cadastro_de_nomes(conn: Any) -> CadastroDeNomes:
        return CADASTRO

    monkeypatch.setattr(porta_mod, "registrar_mensagem", registrar_mensagem)
    monkeypatch.setattr(porta_mod, "marcar_mensagem_apagada", marcar_mensagem_apagada)
    monkeypatch.setattr(porta_mod, "carregar_cadastro_de_nomes", carregar_cadastro_de_nomes)
    return estado


CAIXA = GrupoSemDona(
    id=uuid4(), papel="caixa_telefonistas", jid=CAIXA_JID, nome="Caixa · Telefonistas"
)
GRUPO_DA_YASMIN = GrupoFinanceiro(
    id=uuid4(), modelo_id=YASMIN, jid=GRUPO_DA_YASMIN_JID, nome="Yasmin · Financeiro"
)


def _cadastrado(monkeypatch: pytest.MonkeyPatch, *grupos: GrupoFinanceiro | GrupoSemDona) -> None:
    por_jid = {g.jid: g for g in grupos}

    async def buscar(conn: Any, jid: str) -> GrupoFinanceiro | GrupoSemDona | None:
        return por_jid.get(jid)

    monkeypatch.setattr(porta_mod, "buscar_grupo_cadastrado_por_jid", buscar)


def _mensagem_do_grupo(texto: str, *, jid: str = CAIXA_JID, **extra: Any) -> MensagemDoGrupo:
    return MensagemDoGrupo(
        grupo_jid=jid,
        texto=texto,
        autor_jid="5521988887777@s.whatsapp.net",
        autor_nome="Rossi",
        recebida_em=NOITE,
        **extra,
    )


async def test_o_anuncio_no_caixa_e_registrado_e_nao_vira_venda_nem_recibo(
    porta: _Porta, monkeypatch: pytest.MonkeyPatch
) -> None:
    """O MESMO texto que no grupo individual vira Venda registrada + "✅ Registrei". Aqui ele é só
    log: registrar de novo dobraria a receita da casa, e o agente não fala neste grupo."""
    _cadastrado(monkeypatch, CAIXA)
    fake = _Conexao()

    resultado = await processar_evento_do_grupo(
        _conn(fake), _mensagem_do_grupo(ANUNCIO), enviar=porta.enviar
    )

    assert resultado.status == "registrada"
    assert resultado.motivo == "grupo_em_leitura"
    assert resultado.vendas == ()
    assert resultado.modelo_id is None
    assert resultado.resposta is None
    assert porta.falas == []
    assert porta.mensagens_registradas[0].texto == ANUNCIO
    # Nenhuma outra ida ao banco: no caixa a porta grava o log de origem e para.
    assert fake.consultas == []


async def test_comprovante_no_caixa_nao_paga_nada(
    porta: _Porta, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Foto no caixa não é OCR nem abate: o dinheiro daquele Pix é de alguma modelo, e no caixa
    não há dona de quem ele seja."""
    _cadastrado(monkeypatch, CAIXA)
    fake = _Conexao()

    resultado = await processar_evento_do_grupo(
        _conn(fake),
        _mensagem_do_grupo("", tipo="imagem", caption="comprovante do dia"),
        enviar=porta.enviar,
    )

    assert resultado.motivo == "grupo_em_leitura"
    assert resultado.comprovante_id is None
    assert resultado.abatidas == ()
    assert porta.falas == []
    assert fake.consultas == []


async def test_delecao_no_caixa_atualiza_o_log_e_nao_anula_venda_nenhuma(
    porta: _Porta, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nada nasceu ali, então não há o que anular — mas o log tem que continuar refletindo o que
    se vê no WhatsApp."""
    _cadastrado(monkeypatch, CAIXA)

    resultado = await processar_evento_do_grupo(
        _conn(_Conexao()),
        DelecaoNoGrupo(grupo_jid=CAIXA_JID, evolution_message_id="EVO-1", ocorrida_em=NOITE),
    )

    assert resultado.status == "delecao"
    assert resultado.motivo == "delecao_sem_venda"
    assert resultado.anuladas == ()
    assert porta.apagadas == ["EVO-1"]
    assert porta.falas == []


async def test_caixa_nao_cadastrado_continua_ignorado(
    porta: _Porta, monkeypatch: pytest.MonkeyPatch
) -> None:
    """O número da ProceX é compartilhado: grupo desconhecido é o caso NORMAL, não erro."""
    _cadastrado(monkeypatch, GRUPO_DA_YASMIN)
    fake = _Conexao()

    resultado = await processar_evento_do_grupo(
        _conn(fake), _mensagem_do_grupo(ANUNCIO), enviar=porta.enviar
    )

    assert resultado.status == "grupo_nao_cadastrado"
    assert resultado.mensagem_id is None
    assert porta.mensagens_registradas == []
    assert porta.falas == []
    assert fake.consultas == []


async def test_a_rotina_da_manha_nunca_visita_o_caixa() -> None:
    """A varredura de relógio é a única que não chega por JID — e é por onde uma fala entraria no
    caixa sem ninguém ter escrito nada lá. O filtro é do SQL (o banco é quem exclui o papel), então
    é o SQL que este teste afirma; a versão com Postgres é `needs_db` e depende das migrations da
    onda 20260820, que ainda não foram aplicadas."""
    fake = _Conexao()

    grupos = await grupos_da_rotina(_conn(fake))

    assert grupos == []
    assert len(fake.consultas) == 1
    assert "papel = 'modelo'" in fake.consultas[0]


# --- a composição que o painel chama -------------------------------------------------------------


async def test_a_conferencia_do_painel_le_as_duas_fontes_e_nao_escreve(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ponta a ponta sem banco: mensagens do caixa + vendas vivas -> flag. Sem consumidor, a
    função pura não entrega o produto — é o que o gestor abre no painel."""
    venda_conferida = _venda()
    venda_sozinha = _venda(modelo_id=BIANCA, valor="900.00", cliente="Igor")

    async def mensagens_do_caixa(conn: Any, *, de: date, ate: date) -> list[MensagemRegistrada]:
        assert (de, ate) == (DIA, DIA)
        return [_msg(ANUNCIO), _msg("subiu?")]

    async def vendas_vivas_no_periodo(conn: Any, *, de: date, ate: date) -> list[VendaRegistrada]:
        return [venda_conferida, venda_sozinha]

    async def carregar_cadastro_de_nomes(conn: Any) -> CadastroDeNomes:
        return CADASTRO

    monkeypatch.setattr(service_mod, "mensagens_do_caixa", mensagens_do_caixa)
    monkeypatch.setattr(service_mod, "vendas_vivas_no_periodo", vendas_vivas_no_periodo)
    monkeypatch.setattr(service_mod, "carregar_cadastro_de_nomes", carregar_cadastro_de_nomes)

    fake = _Conexao()
    conferencia = await service_mod.conferencia_do_caixa(_conn(fake), de=DIA, ate=DIA)

    assert conferencia.conferidas == 1
    assert conferencia.bate is False
    assert [(d.tipo, d.venda_id) for d in conferencia.divergencias] == [
        ("so_no_sistema", venda_sozinha.id)
    ]
    assert conferencia.total_no_caixa == Decimal("700.00")
    assert conferencia.total_no_sistema == Decimal("1600.00")
    assert fake.consultas == []
