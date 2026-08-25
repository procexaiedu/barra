"""O Grupo de fichas: a modelo não vem do JID (spec 0006, ticket 19; ADR-0046 §2).

Offline: sem banco, sem chave, sem rede. As leituras de banco deste caminho ou são stubadas (as
que precisam devolver dado) ou caem numa conexão fake que responde vazio — o que se prova aqui é a
**decisão**, e ela é a mesma que a produção toma com o Postgres atrás.

A reunião de 20/08 abriu a possibilidade de a ficha completa ser postada num grupo dedicado só dos
telefonistas, com o Comunicado indo ao grupo individual da modelo. O arranjo não está decidido —
*"a gente pode testar"* — e é por isso que o código não pode assumir que o card caiu no grupo de
quem vai pagar.

Os invariantes que quebram calado se ninguém olhar:

  * **grupo sem dona não empresta modelo a ninguém**: no Grupo de fichas a modelo vem do campo
    `Nome da modelo` pelo resolver closed-world. Deduzi-la do JID ali registraria o atendimento no
    nome de quem não trabalhou;
  * **o card no grupo errado vira pergunta, não gravação**: as duas saídas silenciosas erram, e
    uma delas (gravar a ficha da Duda dentro do grupo da Yasmin) fura o isolamento cross-modelo;
  * **o comunicado vincula**, e o `quote` dele resolve para a ficha do OUTRO grupo — sem isso, a
    modelo que responde "recebi, foi dinheiro" no resumo não fecha atendimento nenhum;
  * **o agente segue calado**: no Grupo de fichas a única fala possível é pergunta.
"""

from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from psycopg import AsyncConnection

from barra.agente_financeiro import ResultadoDaPorta, processar_evento_do_grupo
from barra.agente_financeiro import porta as porta_mod
from barra.dominio.grupo_financeiro.ficha import (
    PREFIXO_DA_DIVERGENCIA,
    PREFIXO_DO_COMUNICADO,
    DivergenciaDeDona,
    FichaDeAgendamento,
    FichaLida,
    ParticipanteDaFicha,
    candidatas_do_comunicado,
    casar_comunicado,
    ler_ficha,
    montar_pergunta_da_divergencia,
    montar_pergunta_do_comunicado_ambiguo,
    planejar_ficha,
)
from barra.dominio.grupo_financeiro.modelos import (
    GrupoFinanceiro,
    GrupoSemDona,
    MensagemDoGrupo,
)
from barra.dominio.grupo_financeiro.nomes import CadastroDeNomes

YASMIN = uuid4()
BIANCA = uuid4()
DUDA = uuid4()

CADASTRO = CadastroDeNomes.de_linhas(
    modelos=[(YASMIN, "Yasmin"), (BIANCA, "Bianca"), (DUDA, "Duda")],
    apelidos=[(YASMIN, "Sofia"), (BIANCA, "Manu")],
)

GRUPO_DE_FICHAS_JID = "120363000000000009@g.us"
GRUPO_DA_YASMIN_JID = "120363000000000001@g.us"
NOITE_DE_20_08 = datetime(2026, 8, 20, 22, 0, tzinfo=UTC)

FICHA = """📋 *FICHA DE ATENDIMENTO*

👤 *CLIENTE*
Nome: Igor
WhatsApp: 21 99999-8888

📝 *CONTRATAÇÃO*
Nome do perfil/anúncio: Sofia
Site: Barra Vips
Origem: (x) Próprio  ( ) Fake
Nome da modelo: {modelo}

🕒 *HORÁRIO*
Data: 22/08
Hora: 19:00
Duração: 1h

📍 *LOCAL*
(x) Local próprio  ( ) Saída
Tipo: ( ) Casa  (X) Hotel  ( ) Motel  ( ) Festa  ( ) Passeio  ( ) Jantar/Almoço
Endereço: Rua Miguel y Canizares, 200
Número / bloco / complemento: Torre 2 Apt 2706

💰 *VALORES*
Valor total: R$ 700
Valor desta modelo: R$ 700
Valor do transporte: R$ 60
Valor antecipado: R$ 100
Forma do antecipado: (x) Pix  ( ) Link

💳 *PAGAMENTO*
( ) Dinheiro  ( ) Pix  ( ) Débito  (x) Crédito  ( ) Link

✏️ *OBSERVAÇÕES*
Não passar perfume.
"""

FICHA_DE_GRUPO = """📋 *FICHA DE ATENDIMENTO*

👤 *CLIENTE*
Nome: Ramon

📝 *CONTRATAÇÃO*
Nome do perfil/anúncio: Sofia
Origem: ( ) Próprio  (x) Fake
Modelo 1: Yasmin
Modelo 2: Bianca
Modelo 3: Duda

🕒 *HORÁRIO*
Data: 23/08
Hora: 22:00
Duração: 2h

📍 *LOCAL*
( ) Local próprio  (x) Saída
Tipo: ( ) Casa  ( ) Hotel  ( ) Motel  (x) Festa  ( ) Passeio  ( ) Jantar/Almoço
Endereço: Av. Lúcio Costa, 3000

💰 *VALORES*
Valor total: R$ 2400
Valor de cada modelo: R$ 800

💳 *PAGAMENTO*
( ) Dinheiro  (x) Pix  ( ) Débito  ( ) Crédito  ( ) Link
"""

COMUNICADO = """👤 *CLIENTE*
Nome: Igor

📝 *CONTRATAÇÃO*
Nome do perfil/anúncio: Sofia
Origem: Próprio

🕒 *HORÁRIO*
Duração: 1h

📍 *LOCAL DO JOB*
Tipo: Hotel
Endereço: Rua Miguel y Canizares, 200

💰 *VALOR DO JOB*
Valor: R$ 700
Forma de pagamento: Dinheiro

✏️ *OBSERVAÇÕES*
Não passar perfume.
"""


# --- a decisão pura: quem é a modelo, e quando isso vira pergunta --------------------------------


def _lida(texto: str) -> FichaLida:
    lida = ler_ficha(texto, hoje=date(2026, 8, 20))
    assert lida is not None
    return lida


def test_no_grupo_de_fichas_a_modelo_vem_do_card_e_nao_do_jid() -> None:
    """`dona_do_grupo=None` é o Grupo de fichas: não há de quem herdar, e o card manda."""
    plano = planejar_ficha(
        _lida(FICHA.format(modelo="Duda")), cadastro=CADASTRO, dona_do_grupo=None
    )

    assert [p.modelo_id for p in plano.participantes] == [DUDA]
    assert plano.divergencia is None


def test_festinha_no_grupo_de_fichas_rende_uma_participante_por_modelo_listada() -> None:
    plano = planejar_ficha(_lida(FICHA_DE_GRUPO), cadastro=CADASTRO, dona_do_grupo=None)

    assert [p.modelo_id for p in plano.participantes] == [YASMIN, BIANCA, DUDA]
    assert {p.valor for p in plano.participantes} == {Decimal("800.00")}


def test_nome_desconhecido_no_grupo_de_fichas_nao_vira_cadastro_novo() -> None:
    plano = planejar_ficha(
        _lida(FICHA.format(modelo="fran loira")), cadastro=CADASTRO, dona_do_grupo=None
    )

    assert plano.participantes == ()
    assert plano.nomes_desconhecidos == ("fran loira",)
    assert plano.faltas == ("modelo",)


def test_card_no_grupo_individual_de_outra_modelo_vira_divergencia() -> None:
    """A ficha da Duda postada no grupo da Yasmin. Gravar pela dona registraria o atendimento no
    nome errado; gravar pelo card poria a ficha da Duda dentro do grupo da Yasmin."""
    plano = planejar_ficha(
        _lida(FICHA.format(modelo="Duda")), cadastro=CADASTRO, dona_do_grupo=YASMIN
    )

    assert plano.divergencia == DivergenciaDeDona(
        dona=YASMIN, nome_da_dona="Yasmin", nomeadas=("Duda",)
    )


def test_festinha_que_inclui_a_dona_do_grupo_nao_e_divergencia() -> None:
    """O card de grupo postado no grupo de uma das participantes é o caso NORMAL."""
    plano = planejar_ficha(_lida(FICHA_DE_GRUPO), cadastro=CADASTRO, dona_do_grupo=BIANCA)

    assert plano.divergencia is None
    assert [p.modelo_id for p in plano.participantes] == [YASMIN, BIANCA, DUDA]


def test_card_que_nomeia_a_propria_dona_pelo_perfil_nao_e_divergencia() -> None:
    """ "Sofia" é o nome de anúncio da Yasmin: o resolver é o mesmo índice, e ele resolve nela."""
    plano = planejar_ficha(
        _lida(FICHA.format(modelo="Sofia")), cadastro=CADASTRO, dona_do_grupo=YASMIN
    )

    assert plano.divergencia is None
    assert [p.modelo_id for p in plano.participantes] == [YASMIN]


def test_a_pergunta_da_divergencia_se_responde_com_um_nome() -> None:
    pergunta = montar_pergunta_da_divergencia(
        DivergenciaDeDona(dona=YASMIN, nome_da_dona="Yasmin", nomeadas=("Duda",))
    )

    assert pergunta == "❓ Essa ficha é da Duda ou da Yasmin? Ela veio no grupo da Yasmin."
    assert pergunta.startswith(PREFIXO_DA_DIVERGENCIA)


def test_sem_nome_da_dona_nao_ha_pergunta() -> None:
    """Sem as duas pontas a frase viraria "essa ficha é de quem?" — o card já respondeu isso."""
    assert (
        montar_pergunta_da_divergencia(
            DivergenciaDeDona(dona=YASMIN, nome_da_dona=None, nomeadas=("Duda",))
        )
        is None
    )


# --- o comunicado ambíguo vira UMA pergunta ------------------------------------------------------


def _ficha_aberta(
    *,
    cliente: str | None = "Igor",
    valor: Decimal | None = Decimal("700.00"),
    modelo_id: UUID = YASMIN,
    dia: date | None = date(2026, 8, 22),
) -> FichaDeAgendamento:
    return FichaDeAgendamento(
        id=uuid4(),
        estado="aberta",
        mensagem_id=uuid4(),
        chave_conteudo=f"ficha|{uuid4()}",
        participantes=(ParticipanteDaFicha(modelo_id=modelo_id, valor=valor),),
        cliente_nome=cliente,
        data=dia,
    )


def test_as_candidatas_do_comunicado_sao_as_mesmas_que_o_casamento_usa() -> None:
    """A pergunta nomeia o que o casamento considerou — nomear todas as abertas ofereceria
    atendimentos que nem batem com o comunicado."""
    batem = [_ficha_aberta(dia=date(2026, 8, 22)), _ficha_aberta(dia=date(2026, 8, 25))]
    outra = _ficha_aberta(cliente="Ramon", valor=Decimal("900.00"))

    candidatas = candidatas_do_comunicado(
        _lida(COMUNICADO), modelo_id=YASMIN, abertas=[*batem, outra]
    )

    assert list(candidatas) == batem
    assert casar_comunicado(_lida(COMUNICADO), modelo_id=YASMIN, abertas=[*batem, outra]) == (
        "ambiguo",
        None,
    )


def test_a_pergunta_do_comunicado_nomeia_as_candidatas_com_o_valor_dela() -> None:
    candidatas = [_ficha_aberta(dia=date(2026, 8, 22)), _ficha_aberta(dia=date(2026, 8, 25))]

    pergunta = montar_pergunta_do_comunicado_ambiguo(candidatas=candidatas, modelo_id=YASMIN)

    assert pergunta is not None
    assert pergunta.startswith(PREFIXO_DO_COMUNICADO)
    assert pergunta == (
        "❓ Esse comunicado é de qual atendimento? Igor (R$ 700,00) · Igor (R$ 700,00)"
        " — me diz o nome do cliente."
    )


def test_a_pergunta_do_comunicado_mostra_o_valor_da_participante_e_nunca_o_total() -> None:
    """Numa festinha de R$ 2.400, dizer 2.400 para uma das três entrega a conta das outras."""
    festinha = replace(
        _ficha_aberta(cliente="Ramon", valor=Decimal("800.00")),
        valor_total=Decimal("2400.00"),
        participantes=(
            ParticipanteDaFicha(modelo_id=YASMIN, valor=Decimal("800.00")),
            ParticipanteDaFicha(modelo_id=BIANCA, valor=Decimal("900.00"), ordem=2),
        ),
    )

    pergunta = montar_pergunta_do_comunicado_ambiguo(
        candidatas=[festinha, _ficha_aberta()], modelo_id=YASMIN
    )

    assert pergunta is not None
    assert "800,00" in pergunta
    assert "2.400,00" not in pergunta
    assert "900,00" not in pergunta


def test_uma_candidata_so_nao_e_pergunta() -> None:
    """Uma candidata é `vincula`, e vincular calado é a conduta certa."""
    assert (
        montar_pergunta_do_comunicado_ambiguo(candidatas=[_ficha_aberta()], modelo_id=YASMIN)
        is None
    )


# --- a porta: roteamento por papel do grupo ------------------------------------------------------


class _Cursor:
    """Cursor que nunca devolve linha: o banco fake responde "não achei" para tudo."""

    async def fetchone(self) -> None:
        return None

    async def fetchall(self) -> list[Any]:
        return []


class _Conexao:
    """Conexão fake que aceita qualquer SQL e devolve vazio.

    O que não é stubado explicitamente cai aqui e responde "nada" — que é o estado inicial certo
    de um grupo novo. Guarda o SQL para o teste poder afirmar o que NÃO foi consultado.
    """

    def __init__(self) -> None:
        self.consultas: list[str] = []

    async def execute(self, sql: str, params: Any = None) -> _Cursor:
        self.consultas.append(sql)
        return _Cursor()


def _conn(fake: _Conexao) -> AsyncConnection[Any]:
    return cast(AsyncConnection[Any], fake)


class _Porta:
    """Os stubs mínimos para a porta rodar sem Postgres, com o que ela precisa achar."""

    def __init__(self) -> None:
        self.falas: list[str] = []
        self.fichas_gravadas: list[tuple[FichaLida, tuple[ParticipanteDaFicha, ...]]] = []
        self.abertas: list[FichaDeAgendamento] = []
        self.texto_citado: str | None = None
        self.promovidas: list[UUID] = []

    async def enviar(self, texto: str, *, citar: str | None = None) -> None:
        self.falas.append(texto)


@pytest.fixture
def porta(monkeypatch: pytest.MonkeyPatch) -> _Porta:
    estado = _Porta()

    async def registrar_mensagem(conn: Any, grupo_id: UUID, msg: MensagemDoGrupo) -> UUID:
        return uuid4()

    async def carregar_cadastro_de_nomes(conn: Any) -> CadastroDeNomes:
        return CADASTRO

    async def registrar_ficha(
        conn: Any,
        *,
        lida: FichaLida,
        participantes: Sequence[ParticipanteDaFicha],
        mensagem_id: UUID,
        chave_conteudo: str,
        vendedor_id: UUID | None = None,
    ) -> FichaDeAgendamento:
        estado.fichas_gravadas.append((lida, tuple(participantes)))
        return FichaDeAgendamento(
            id=uuid4(),
            estado="aberta",
            mensagem_id=mensagem_id,
            chave_conteudo=chave_conteudo,
            participantes=tuple(participantes),
            cliente_nome=lida.cliente_nome,
            data=lida.data,
        )

    async def fichas_abertas_da_modelo(conn: Any, modelo_id: UUID) -> list[FichaDeAgendamento]:
        return [f for f in estado.abertas if any(p.modelo_id == modelo_id for p in f.participantes)]

    async def texto_da_mensagem_citada(conn: Any, grupo_id: UUID, evo_id: str) -> str | None:
        return estado.texto_citado

    async def promover(conn: Any, *, ficha: FichaDeAgendamento, **kwargs: Any) -> ResultadoDaPorta:
        estado.promovidas.append(ficha.id)
        return ResultadoDaPorta(status="registrada", ficha_id=ficha.id, motivo="ficha_promovida")

    monkeypatch.setattr(porta_mod, "registrar_mensagem", registrar_mensagem)
    monkeypatch.setattr(porta_mod, "carregar_cadastro_de_nomes", carregar_cadastro_de_nomes)
    monkeypatch.setattr(porta_mod, "registrar_ficha", registrar_ficha)
    monkeypatch.setattr(porta_mod, "fichas_abertas_da_modelo", fichas_abertas_da_modelo)
    monkeypatch.setattr(porta_mod, "texto_da_mensagem_citada", texto_da_mensagem_citada)
    monkeypatch.setattr(porta_mod, "_promover_ficha", promover)
    return estado


def _grupo(monkeypatch: pytest.MonkeyPatch, grupo: GrupoFinanceiro | GrupoSemDona) -> None:
    async def buscar(conn: Any, jid: str) -> GrupoFinanceiro | GrupoSemDona | None:
        return grupo if jid == grupo.jid else None

    monkeypatch.setattr(porta_mod, "buscar_grupo_cadastrado_por_jid", buscar)


GRUPO_DE_FICHAS = GrupoSemDona(id=uuid4(), papel="fichas", jid=GRUPO_DE_FICHAS_JID, nome="Fichas")
CAIXA = GrupoSemDona(id=uuid4(), papel="caixa_telefonistas", jid=GRUPO_DE_FICHAS_JID, nome="Caixa")
GRUPO_DA_YASMIN = GrupoFinanceiro(
    id=uuid4(), modelo_id=YASMIN, jid=GRUPO_DA_YASMIN_JID, nome="Yasmin · Financeiro"
)


def _mensagem(texto: str, *, jid: str = GRUPO_DE_FICHAS_JID, **extra: Any) -> MensagemDoGrupo:
    return MensagemDoGrupo(
        grupo_jid=jid,
        texto=texto,
        autor_jid="5521988887777@s.whatsapp.net",
        autor_nome="Lula",
        recebida_em=NOITE_DE_20_08,
        **extra,
    )


async def test_ficha_no_grupo_de_fichas_cria_a_ficha_da_modelo_nomeada(
    porta: _Porta, monkeypatch: pytest.MonkeyPatch
) -> None:
    _grupo(monkeypatch, GRUPO_DE_FICHAS)

    resultado = await processar_evento_do_grupo(
        _conn(_Conexao()), _mensagem(FICHA.format(modelo="Duda")), enviar=porta.enviar
    )

    assert resultado.motivo == "ficha_registrada"
    assert resultado.ficha_id is not None
    (_, participantes) = porta.fichas_gravadas[0]
    assert [p.modelo_id for p in participantes] == [DUDA]
    # Calado como sempre foi ao receber um card (ADR-0044 §1).
    assert porta.falas == []
    assert resultado.resposta is None


async def test_festinha_no_grupo_de_fichas_grava_uma_participante_por_modelo(
    porta: _Porta, monkeypatch: pytest.MonkeyPatch
) -> None:
    _grupo(monkeypatch, GRUPO_DE_FICHAS)

    await processar_evento_do_grupo(
        _conn(_Conexao()), _mensagem(FICHA_DE_GRUPO), enviar=porta.enviar
    )

    (_, participantes) = porta.fichas_gravadas[0]
    assert [p.modelo_id for p in participantes] == [YASMIN, BIANCA, DUDA]
    assert porta.falas == []


async def test_nome_desconhecido_no_grupo_de_fichas_pergunta_e_nao_grava(
    porta: _Porta, monkeypatch: pytest.MonkeyPatch
) -> None:
    _grupo(monkeypatch, GRUPO_DE_FICHAS)

    resultado = await processar_evento_do_grupo(
        _conn(_Conexao()), _mensagem(FICHA.format(modelo="fran loira")), enviar=porta.enviar
    )

    assert resultado.motivo == "ficha_nome_desconhecido"
    assert porta.fichas_gravadas == []
    assert porta.falas == [resultado.resposta]
    assert resultado.resposta is not None and "fran loira" in resultado.resposta


async def test_card_sem_nome_de_modelo_no_grupo_de_fichas_nao_vira_ficha_de_ninguem(
    porta: _Porta, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sem dona de quem herdar e sem nome no card, não há a quem atribuir o atendimento — e não há
    nome para perguntar por ("'?' é quem?" não se responde). Fica no log e o telefonista reposta."""
    _grupo(monkeypatch, GRUPO_DE_FICHAS)
    sem_nome = FICHA.format(modelo="").replace("Nome do perfil/anúncio: Sofia", "")

    resultado = await processar_evento_do_grupo(
        _conn(_Conexao()), _mensagem(sem_nome), enviar=porta.enviar
    )

    assert resultado.motivo == "ficha_sem_modelo"
    assert porta.fichas_gravadas == []
    assert porta.falas == []


async def test_conversa_no_grupo_de_fichas_nao_vira_nada(
    porta: _Porta, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nenhuma leitura de dinheiro roda num grupo sem dona: elas são todas DELA."""
    _grupo(monkeypatch, GRUPO_DE_FICHAS)

    resultado = await processar_evento_do_grupo(
        _conn(_Conexao()), _mensagem("subiu? ela já chegou"), enviar=porta.enviar
    )

    assert resultado.motivo == "nao_e_ficha"
    assert resultado.modelo_id is None
    assert resultado.vendas == () and resultado.cobrancas == () and resultado.pendencias == ()
    assert porta.falas == []


async def test_o_caixa_dos_telefonistas_entra_so_em_leitura(
    porta: _Porta, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Um card postado no caixa não vira ficha: lá o mesmo atendimento aparece de novo, e gravá-lo
    duplicaria o combinado que já nasceu no Grupo de fichas."""
    _grupo(monkeypatch, CAIXA)

    resultado = await processar_evento_do_grupo(
        _conn(_Conexao()), _mensagem(FICHA.format(modelo="Duda")), enviar=porta.enviar
    )

    assert resultado.motivo == "grupo_em_leitura"
    assert porta.fichas_gravadas == []
    assert porta.falas == []


async def test_card_de_outra_modelo_no_grupo_individual_pergunta_e_nao_grava(
    porta: _Porta, monkeypatch: pytest.MonkeyPatch
) -> None:
    """O isolamento cross-modelo é o invariante que não cede."""
    _grupo(monkeypatch, GRUPO_DA_YASMIN)

    resultado = await processar_evento_do_grupo(
        _conn(_Conexao()),
        _mensagem(FICHA.format(modelo="Duda"), jid=GRUPO_DA_YASMIN_JID),
        enviar=porta.enviar,
    )

    assert resultado.motivo == "ficha_de_outra_modelo"
    assert resultado.ficha_id is None
    assert porta.fichas_gravadas == []
    assert porta.falas == [resultado.resposta]
    assert resultado.resposta is not None
    assert resultado.resposta.startswith(PREFIXO_DA_DIVERGENCIA)


async def test_comunicado_casa_com_a_ficha_do_outro_grupo_e_nao_cria_uma_segunda(
    porta: _Porta, monkeypatch: pytest.MonkeyPatch
) -> None:
    _grupo(monkeypatch, GRUPO_DA_YASMIN)
    alvo = _ficha_aberta()
    porta.abertas = [alvo]

    resultado = await processar_evento_do_grupo(
        _conn(_Conexao()), _mensagem(COMUNICADO, jid=GRUPO_DA_YASMIN_JID), enviar=porta.enviar
    )

    assert resultado.motivo == "comunicado_vinculado"
    assert resultado.ficha_id == alvo.id
    assert porta.fichas_gravadas == []
    assert porta.falas == []


async def test_comunicado_sem_ficha_correspondente_cria_a_ficha(
    porta: _Porta, monkeypatch: pytest.MonkeyPatch
) -> None:
    """O arranjo sem Grupo de fichas — e o que acontece quando o telefonista pula a ficha completa."""
    _grupo(monkeypatch, GRUPO_DA_YASMIN)

    resultado = await processar_evento_do_grupo(
        _conn(_Conexao()), _mensagem(COMUNICADO, jid=GRUPO_DA_YASMIN_JID), enviar=porta.enviar
    )

    assert resultado.motivo == "ficha_registrada"
    (_, participantes) = porta.fichas_gravadas[0]
    assert [p.modelo_id for p in participantes] == [YASMIN]
    assert porta.falas == []


async def test_comunicado_que_casa_com_duas_fichas_vira_uma_pergunta(
    porta: _Porta, monkeypatch: pytest.MonkeyPatch
) -> None:
    _grupo(monkeypatch, GRUPO_DA_YASMIN)
    porta.abertas = [_ficha_aberta(dia=date(2026, 8, 22)), _ficha_aberta(dia=date(2026, 8, 25))]

    resultado = await processar_evento_do_grupo(
        _conn(_Conexao()), _mensagem(COMUNICADO, jid=GRUPO_DA_YASMIN_JID), enviar=porta.enviar
    )

    assert resultado.motivo == "comunicado_ambiguo"
    assert resultado.ficha_id is None
    assert porta.fichas_gravadas == []
    assert porta.falas == [resultado.resposta]
    assert resultado.resposta is not None
    assert resultado.resposta.startswith(PREFIXO_DO_COMUNICADO)


async def test_quote_no_comunicado_resolve_a_ficha_do_outro_grupo(
    porta: _Porta, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A ficha nasceu no Grupo de fichas; o que a modelo tem à mão para citar é o Comunicado.

    DUAS fichas abertas de propósito: com uma só, "recebi, foi dinheiro" fecharia a única aberta
    por eliminação e o teste passaria sem o salto existir. Com duas e nenhum nome na fala, só o
    quote resolvido no comunicado aponta qual é.
    """
    _grupo(monkeypatch, GRUPO_DA_YASMIN)
    alvo = _ficha_aberta()
    porta.abertas = [alvo, _ficha_aberta(cliente="Ramon", valor=Decimal("900.00"))]
    porta.texto_citado = COMUNICADO

    resultado = await processar_evento_do_grupo(
        _conn(_Conexao()),
        _mensagem(
            "recebi, foi dinheiro",
            jid=GRUPO_DA_YASMIN_JID,
            quoted_message_id="3EB0COMUNICADO",
        ),
        enviar=porta.enviar,
    )

    assert porta.promovidas == [alvo.id]
    assert resultado.motivo == "ficha_promovida"


async def test_quote_num_comunicado_que_nao_casa_nao_aponta_ficha_nenhuma(
    porta: _Porta, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sem casar, o quote não aponta nada: quem desempata é a pergunta de sempre, e não um palpite
    ancorado num resumo que serve a dois atendimentos."""
    _grupo(monkeypatch, GRUPO_DA_YASMIN)
    porta.abertas = [
        _ficha_aberta(dia=date(2026, 8, 22)),
        _ficha_aberta(dia=date(2026, 8, 25)),
    ]
    porta.texto_citado = COMUNICADO

    await processar_evento_do_grupo(
        _conn(_Conexao()),
        _mensagem(
            "recebi, foi dinheiro",
            jid=GRUPO_DA_YASMIN_JID,
            quoted_message_id="3EB0COMUNICADO",
        ),
        enviar=porta.enviar,
    )

    assert porta.promovidas == []


async def test_quote_numa_mensagem_que_nao_e_comunicado_nao_promove_por_palpite(
    porta: _Porta, monkeypatch: pytest.MonkeyPatch
) -> None:
    _grupo(monkeypatch, GRUPO_DA_YASMIN)
    porta.abertas = [_ficha_aberta(), _ficha_aberta(cliente="Ramon", valor=Decimal("900.00"))]
    porta.texto_citado = "bom dia amigas"

    await processar_evento_do_grupo(
        _conn(_Conexao()),
        _mensagem(
            "recebi, foi dinheiro",
            jid=GRUPO_DA_YASMIN_JID,
            quoted_message_id="3EB0SOCIAL",
        ),
        enviar=porta.enviar,
    )

    # O quote de uma conversa não é sinal de nada: o alvo volta a ser escolhido pela escada de
    # sempre (`escolher_ficha`), que com duas abertas e nenhum nome na fala não escolhe.
    assert porta.promovidas == []


async def test_grupo_nao_cadastrado_continua_saindo_calado(
    porta: _Porta, monkeypatch: pytest.MonkeyPatch
) -> None:
    """O número da ProceX é compartilhado: grupo que não é nosso é o caso NORMAL."""
    _grupo(monkeypatch, GRUPO_DE_FICHAS)

    resultado = await processar_evento_do_grupo(
        _conn(_Conexao()),
        _mensagem(FICHA.format(modelo="Duda"), jid="120363000000000099@g.us"),
        enviar=porta.enviar,
    )

    assert resultado == ResultadoDaPorta(status="grupo_nao_cadastrado")
    assert porta.falas == []
