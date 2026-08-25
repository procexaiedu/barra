"""Venda registrada com recibo (spec 0005, ticket 02) — pela PORTA UNICA.

Todo caso aqui e uma mensagem REAL do export "Modelo Yasmin Ruiva/financeiro" (13/08/2026),
copiada com a grafia original: espaco sobrando no fim da linha, acento, typo ("yamin"), valor em
linha propria. E o ponto do ticket — o agente tem que entender o que a gestora JA escreve, nao um
formato que inventamos para ele.

O que este arquivo prova:

1. O anuncio de 08/08 vira UMA Venda registrada (modelo resolvida, valor, data = dia BRT da
   mensagem) e o grupo recebe o recibo curto — sem nenhum pedido de confirmacao previa.
2. "Perfil bianca/yasmin" e UMA mulher, resolvida pelo cadastro; nome fora do cadastro nao vira
   venda nem por prefixo nem por parecenca, e homonimo nao e sorteado.
3. Mensagem social nao registra, nao responde e NAO CUSTA EXTRACAO (o extrator injetado conta as
   chamadas — e a unica forma honesta de provar "descartada barato").
4. Nada nasce em `clientes` nem em `atendimentos` (ADR-0043).
5. A costura real: payload cru da Evolution -> webhook -> porta -> venda no banco.

Tudo entra por `processar_mensagem_do_grupo` (ou pelo webhook, que a chama). Nenhum teste toca
funcao interna do modulo: o desenho contrario induziu 4 bugs falsos no agente de venda (licao do
harness fiel, spec 0005 "Testing Decisions").

`needs_db` com `TEST_DATABASE_URL` + ROLLBACK sempre: o resolver e uma consulta closed-world e a
venda e uma linha com FK para a mensagem-fonte — FakeConn provaria o mock, nao o registro.
"""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, ClassVar
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from barra.agente_financeiro import processar_mensagem_do_grupo
from barra.dominio.grupo_financeiro.anuncio import AnuncioDeVenda, extrair_anuncio
from barra.dominio.grupo_financeiro.modelos import BRT, MensagemDoGrupo
from barra.webhook.routes import evolution_webhook

pytestmark = pytest.mark.needs_db

# --- mensagens reais do export (grafia intacta) -------------------------------------------------

ANUNCIO_SIMPLES = "Atendimento no nosso local \nCliente Gabriel \nPerfil bianca/yasmin \n700 1h"
ANUNCIO_COM_TYPO = "Atendimento no nosso local \nCliente Gustavo \nPerfil bianca/yamin \n650 1h"
ANUNCIO_SEM_PERFIL = (
    "Atendimento no nosso local \nCliente Antônio\nSeu nome é bianca \n600 1h \n"
    "Ele quer dois relaxamentos amigs"
)
ANUNCIO_NOME_FORA_DO_CADASTRO = (
    "Atendimento no nosso local \nCliente Tiago \nPerfil Alicia/ fran loira \n600 1h"
)
ANUNCIO_DUAS_MODELOS = (
    "Atendimento no nosso local \nCliente Gustavo e Diego \nPerfil sophia/julia \n"
    "Perfil bianca/yamin \n650 1h cada uma \n1300 no total"
)
ANUNCIO_SEM_VALOR = "Atendimento no nosso local \nCliente ramon \nPerfil bianca"
COBRANCA_DA_AGENCIA = "*3RJ Suporte/Anúncio:*\n3 DIAS | R$ 385,80"
"""Vive aqui como VIZINHA do anuncio: o teste que importa e o de que ela nao vira venda.

Ela ja foi item de `MENSAGENS_SOCIAIS` — no ticket 08 deixou de ser silencio e passou a virar
**Cobranca da agencia**, debito da modelo (test_grupo_financeiro_cobranca.py). O que este arquivo
continua guardando e o outro lado: cifra e a palavra "anuncio" na mesma mensagem nao produzem
Venda registrada nenhuma."""
MENSAGENS_SOCIAIS = (
    "Gente tá chamando pq da outra vez eu trabalhei bem e dessa vez nada",
    "Foi pix ou din ?",
    "Yasmin confere por favor \n\n600 pix \n600 pix",
    "Torre 2 Apt 2706",
)

# 09/08 01:09 UTC = 08/08 22:09 em Brasilia. A venda e do dia 08 — e assim que a gestora conta.
NOITE_DE_08_08 = datetime(2026, 8, 9, 1, 9, tzinfo=UTC)


@pytest_asyncio.fixture
async def conn() -> AsyncIterator[AsyncConnection[dict[str, Any]]]:
    connection = await AsyncConnection.connect(
        os.environ["TEST_DATABASE_URL"],
        autocommit=False,
        row_factory=dict_row,
        prepare_threshold=None,
    )
    try:
        yield connection
    finally:
        try:
            await connection.rollback()
        finally:
            await connection.close()


# --- seeds --------------------------------------------------------------------------------------


async def _seed_modelo(c: AsyncConnection[dict[str, Any]], nome: str) -> UUID:
    modelo_id = uuid4()
    await c.execute(
        """
        INSERT INTO barravips.modelos
            (id, nome, idade, numero_whatsapp, valor_padrao, tipo_atendimento_aceito,
             percentual_repasse, status)
        VALUES (%s, %s, %s, %s, %s, %s::barravips.tipo_atendimento_enum[], %s,
                'ativa'::barravips.modelo_status_enum)
        """,
        (modelo_id, nome, 25, f"test-wpp-{uuid4().hex}", 700, ["interno"], Decimal("40")),
    )
    return modelo_id


async def _seed_apelido(c: AsyncConnection[dict[str, Any]], modelo_id: UUID, nome: str) -> None:
    await c.execute(
        """
        INSERT INTO barravips.modelo_nomes_anuncio (modelo_id, nome, nome_normalizado)
        VALUES (%s, %s, %s)
        """,
        (modelo_id, nome, nome.strip().lower()),
    )


async def _seed_grupo(c: AsyncConnection[dict[str, Any]], modelo_id: UUID, *, jid: str) -> UUID:
    grupo_id = uuid4()
    await c.execute(
        """
        INSERT INTO barravips.grupos_financeiros (id, modelo_id, jid, nome)
        VALUES (%s, %s, %s, %s)
        """,
        (grupo_id, modelo_id, jid, "Modelo Yasmin Ruiva/financeiro"),
    )
    return grupo_id


class _GrupoDaYasmin:
    """O grupo real montado: modelo "Yasmin", apelido "bianca" e o vinculo closed-world."""

    def __init__(self, modelo_id: UUID, grupo_id: UUID, jid: str) -> None:
        self.modelo_id = modelo_id
        self.grupo_id = grupo_id
        self.jid = jid


async def _montar_grupo_da_yasmin(c: AsyncConnection[dict[str, Any]]) -> _GrupoDaYasmin:
    """Cadastro minimo do grupo do export: Yasmin + o apelido "bianca" que o grupo usa.

    NB: o `barra_test` tem varias "Yasmin" de residuo de teste, e o seed abaixo cria mais uma.
    Isso e proposital — e o caso homonimo real: "yasmin" sozinho seria ambiguo, e quem desempata
    e o "bianca" da mesma linha (intersecao dos candidatos), nunca um palpite.
    """
    modelo_id = await _seed_modelo(c, "Yasmin")
    await _seed_apelido(c, modelo_id, "bianca")
    jid = _jid_novo()
    grupo_id = await _seed_grupo(c, modelo_id, jid=jid)
    return _GrupoDaYasmin(modelo_id, grupo_id, jid)


async def _vendas(c: AsyncConnection[dict[str, Any]], modelo_id: UUID) -> list[dict[str, Any]]:
    cur = await c.execute(
        """
        SELECT valor, data, cliente_nome, local_atendimento, duracao_minutos, forma_pagamento,
               mensagem_id
          FROM barravips.vendas_registradas
         WHERE modelo_id = %s
         ORDER BY created_at
        """,
        (modelo_id,),
    )
    return list(await cur.fetchall())


async def _contar(c: AsyncConnection[dict[str, Any]], tabela: str) -> int:
    cur = await c.execute(f"SELECT count(*) AS n FROM barravips.{tabela}")
    row = await cur.fetchone()
    assert row is not None
    return int(row["n"])


def _jid_novo() -> str:
    return f"1203634{uuid4().hex[:12]}@g.us"


def _mensagem(grupo: _GrupoDaYasmin, texto: str, **kw: Any) -> MensagemDoGrupo:
    kw.setdefault("evolution_message_id", f"3EB0{uuid4().hex[:10]}")
    kw.setdefault("autor_nome", "Dani")
    kw.setdefault("autor_jid", "5521999999999@s.whatsapp.net")
    kw.setdefault("recebida_em", NOITE_DE_08_08)
    return MensagemDoGrupo(grupo_jid=grupo.jid, texto=texto, **kw)


# --- dubles da fronteira (nada fala com a Evolution) --------------------------------------------


class _RecibosDoGrupo:
    """Quem entrega no grupo o que a porta decidiu dizer. Coleta em vez de ir a rede."""

    def __init__(self) -> None:
        self.enviados: list[str] = []

    async def __call__(self, texto: str, *, citar: str | None = None) -> None:
        self.enviados.append(texto)


class _ExtratorEspiao:
    """Extrator real, com contador de chamadas — o observavel de "nao custou extracao"."""

    def __init__(self) -> None:
        self.chamadas: list[str] = []

    def __call__(self, texto: str) -> AnuncioDeVenda:
        self.chamadas.append(texto)
        return extrair_anuncio(texto)


# --- 1. o tracer bullet: anuncio -> Venda registrada + recibo -----------------------------------


async def test_anuncio_real_vira_venda_registrada_com_recibo(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    grupo = await _montar_grupo_da_yasmin(conn)
    recibos = _RecibosDoGrupo()

    resultado = await processar_mensagem_do_grupo(
        conn, _mensagem(grupo, ANUNCIO_SIMPLES), enviar=recibos
    )

    assert resultado.status == "registrada"
    assert resultado.motivo is None
    assert len(resultado.vendas) == 1
    assert resultado.modelo_id == grupo.modelo_id

    (venda,) = await _vendas(conn, grupo.modelo_id)
    assert venda["valor"] == Decimal("700.00")
    assert venda["data"] == date(2026, 8, 8)  # dia BRT da mensagem, nao o UTC
    assert venda["cliente_nome"] == "Gabriel"
    assert venda["duracao_minutos"] == 60
    assert venda["local_atendimento"] == "no nosso local"
    assert venda["forma_pagamento"] is None  # chega dias depois (ticket 03), nao trava o registro
    assert venda["mensagem_id"] == resultado.mensagem_id

    # Recibo: postado DEPOIS do lancamento, curto, com o convite a corrigir — e nenhuma pergunta
    # antes ("posso lancar?" nao existe neste agente).
    assert recibos.enviados == [resultado.resposta]
    (recibo,) = recibos.enviados
    assert recibo.startswith("✅ Registrei:")
    assert "R$ 700,00" in recibo
    assert "Yasmin" in recibo
    assert "Cliente Gabriel" in recibo
    assert "corrige aí se algo estiver errado" in recibo
    assert "?" not in recibo


async def test_registro_nao_cria_cliente_nem_atendimento(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """ADR-0043: o cliente do grupo e texto livre; Cliente do sistema e telefone E.164."""
    grupo = await _montar_grupo_da_yasmin(conn)
    antes = (await _contar(conn, "clientes"), await _contar(conn, "atendimentos"))

    resultado = await processar_mensagem_do_grupo(conn, _mensagem(grupo, ANUNCIO_SIMPLES))

    assert len(resultado.vendas) == 1
    assert (await _contar(conn, "clientes"), await _contar(conn, "atendimentos")) == antes


# --- 2. resolver de Nome de anuncio: closed-world, nunca por parecenca --------------------------


async def test_perfil_x_barra_y_resolve_uma_unica_modelo(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """ "bianca/yasmin" = apelido / nome verdadeiro da MESMA mulher — uma linha, nao duas."""
    grupo = await _montar_grupo_da_yasmin(conn)

    resultado = await processar_mensagem_do_grupo(conn, _mensagem(grupo, ANUNCIO_SIMPLES))

    assert len(resultado.vendas) == 1
    assert len(await _vendas(conn, grupo.modelo_id)) == 1


async def test_typo_no_nome_verdadeiro_nao_derruba_o_anuncio(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """ "Perfil bianca/yamin" (08/08, typo da gestora): o apelido conhecido resolve, o typo e
    ignorado — e continua NAO casando por similaridade com "yasmin"."""
    grupo = await _montar_grupo_da_yasmin(conn)

    resultado = await processar_mensagem_do_grupo(conn, _mensagem(grupo, ANUNCIO_COM_TYPO))

    (venda,) = await _vendas(conn, grupo.modelo_id)
    assert venda["valor"] == Decimal("650.00")
    assert resultado.motivo is None


async def test_nome_fora_do_cadastro_nao_vira_venda_por_similaridade(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """ "Perfil Alicia/ fran loira" com uma "Alicia Prado" cadastrada: prefixo NAO e resposta.

    Ninguem recebe a venda por parecenca. O que o agente faz e PERGUNTAR de quem ela e (pergunta
    minima, ticket 03) — registrar na mulher errada seria pior que esperar.
    """
    grupo = await _montar_grupo_da_yasmin(conn)
    alicia = await _seed_modelo(conn, "Alicia Prado")
    recibos = _RecibosDoGrupo()

    resultado = await processar_mensagem_do_grupo(
        conn, _mensagem(grupo, ANUNCIO_NOME_FORA_DO_CADASTRO), enviar=recibos
    )

    assert resultado.motivo == "nome_desconhecido"
    assert resultado.vendas == ()
    assert await _vendas(conn, alicia) == []
    assert await _vendas(conn, grupo.modelo_id) == []  # nem cai na dona do grupo
    assert recibos.enviados == [resultado.resposta]
    assert "fran loira" in recibos.enviados[0]


async def test_homonimo_no_cadastro_nao_e_sorteado(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Duas modelos com o mesmo nome e o unico token do anuncio: ambiguo, ninguem recebe a venda."""
    nome_repetido = f"Duda{uuid4().hex[:6]}"
    primeira = await _seed_modelo(conn, nome_repetido)
    segunda = await _seed_modelo(conn, nome_repetido)
    jid = _jid_novo()
    grupo_id = await _seed_grupo(conn, primeira, jid=jid)
    grupo = _GrupoDaYasmin(primeira, grupo_id, jid)

    resultado = await processar_mensagem_do_grupo(
        conn,
        _mensagem(
            grupo, f"Atendimento no nosso local \nCliente Ramon \nPerfil {nome_repetido} \n600 1h"
        ),
    )

    assert resultado.motivo == "nome_ambiguo"
    assert await _vendas(conn, primeira) == []
    assert await _vendas(conn, segunda) == []


async def test_anuncio_sem_perfil_fica_com_a_dona_do_grupo(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """10/08: "Seu nome é bianca" — ninguem foi NOMEADO na gramatica do anuncio.

    O grupo e de uma modelo so (vinculo closed-world do ticket 01), entao a dona do grupo e a
    resposta — nao ha palpite: e diferente de nome desconhecido, onde alguem FOI nomeado.
    """
    grupo = await _montar_grupo_da_yasmin(conn)

    resultado = await processar_mensagem_do_grupo(conn, _mensagem(grupo, ANUNCIO_SEM_PERFIL))

    (venda,) = await _vendas(conn, grupo.modelo_id)
    assert venda["valor"] == Decimal("600.00")
    assert venda["cliente_nome"] == "Antônio"
    assert resultado.motivo is None


# --- 3. silencio barato: mensagem social ---------------------------------------------------------


@pytest.mark.parametrize("texto", MENSAGENS_SOCIAIS)
async def test_mensagem_social_nao_registra_nao_responde_e_nao_extrai(
    conn: AsyncConnection[dict[str, Any]], texto: str
) -> None:
    """Conversa, cobranca da 3RJ, conferencia de fechamento, endereco: nada disso e venda.

    O extrator espiao prova o "barato" da spec: a triagem corta ANTES da extracao — quando o
    extrator for um LLM, e este assert que impede o grupo social de virar fatura.
    """
    grupo = await _montar_grupo_da_yasmin(conn)
    recibos, espiao = _RecibosDoGrupo(), _ExtratorEspiao()

    resultado = await processar_mensagem_do_grupo(
        conn, _mensagem(grupo, texto), extrair=espiao, enviar=recibos
    )

    assert resultado.status == "registrada"  # a MENSAGEM entra no log de origem...
    # ...mas nao vira venda. "Foi pix ou din ?" ganhou motivo proprio no ticket 03 (a pergunta do
    # gestor e o que o "Sim" seguinte responde) e "Torre 2 Apt 2706" ganhou o dele no ticket 12
    # (vira Dado cadastral da modelo, calado) — os tres continuam sem registro, sem fala e sem
    # extracao, que e o que este teste guarda.
    assert resultado.motivo in ("nao_e_anuncio", "pergunta_de_pagamento", "cadastro_atualizado")
    assert resultado.vendas == ()
    assert resultado.resposta is None
    assert recibos.enviados == []
    assert espiao.chamadas == []


async def test_cobranca_da_agencia_nao_vira_venda_registrada(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """ "3RJ Suporte/Anúncio: 3 DIAS | R$ 385,80" tem cifra dentro e NAO e receita da casa.

    Ela vira Cobranca da agencia — debito da modelo, outro eixo (ADR-0043 nao a conhece; ela nao
    entra em `vendas_registradas` nem na receita do Modulo Financeiro). O que se guarda aqui e so
    isso: nenhuma linha de venda, e nenhuma extracao paga por uma mensagem que nunca foi anuncio.
    """
    grupo = await _montar_grupo_da_yasmin(conn)
    espiao = _ExtratorEspiao()

    resultado = await processar_mensagem_do_grupo(
        conn, _mensagem(grupo, COBRANCA_DA_AGENCIA), extrair=espiao
    )

    assert resultado.motivo == "cobranca_registrada"
    assert resultado.vendas == ()
    assert await _vendas(conn, grupo.modelo_id) == []
    assert espiao.chamadas == []


async def test_sticker_e_midia_sem_dado_nao_custam_extracao(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    grupo = await _montar_grupo_da_yasmin(conn)
    espiao = _ExtratorEspiao()

    resultado = await processar_mensagem_do_grupo(
        conn,
        _mensagem(grupo, "", tipo="imagem", media_url="https://mmg.whatsapp.net/sticker"),
        extrair=espiao,
    )

    # Imagem sem bytes ganhou motivo proprio no ticket 07 (ali ela e um comprovante que o webhook
    # nao conseguiu baixar). O que este teste guarda continua valendo: nenhuma extracao, nenhuma
    # venda, nenhuma fala.
    assert resultado.motivo == "imagem_sem_leitura"
    assert resultado.vendas == ()
    assert resultado.resposta is None
    assert espiao.chamadas == []


async def test_recibo_do_proprio_agente_nao_vira_venda(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """O eco `fromMe` do proprio recibo tem valor, cliente e nome — e nao pode se auto-registrar."""
    grupo = await _montar_grupo_da_yasmin(conn)
    espiao = _ExtratorEspiao()

    resultado = await processar_mensagem_do_grupo(
        conn,
        _mensagem(
            grupo,
            "✅ Registrei: Yasmin · R$ 700,00 · 08/08 · Cliente Gabriel · 1h — corrige aí se algo estiver errado",
            de_mim=True,
        ),
        extrair=espiao,
    )

    assert resultado.motivo == "eco_do_agente"
    assert resultado.vendas == ()
    assert espiao.chamadas == []
    assert await _vendas(conn, grupo.modelo_id) == []


# --- 4. fronteiras declaradas com os tickets vizinhos -------------------------------------------


async def test_venda_com_duas_modelos_nao_vira_uma_linha_so(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """08/08 "650 1h cada uma / 1300 no total": duas mulheres, UMA linha por modelo (ticket 04).

    Aqui so a Yasmin esta cadastrada, entao o que se prova e o essencial deste arquivo: o valor
    que entra e o de CADA UMA (650), nunca o total (1300) e nunca os dois somados numa linha. O
    ciclo completo das duas participantes vive em `test_grupo_financeiro_duas_modelos.py`.
    """
    grupo = await _montar_grupo_da_yasmin(conn)
    recibos = _RecibosDoGrupo()

    resultado = await processar_mensagem_do_grupo(
        conn, _mensagem(grupo, ANUNCIO_DUAS_MODELOS), enviar=recibos
    )

    (venda,) = await _vendas(conn, grupo.modelo_id)
    assert venda["valor"] == Decimal("650.00")
    assert resultado.motivo == "nome_desconhecido"  # a outra participante ainda e desconhecida
    assert "sophia / julia" in recibos.enviados[0]


async def test_anuncio_sem_valor_nao_registra_e_pergunta_o_valor(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Falta o minimo (valor): nao se inventa numero — pergunta-se (ticket 03).

    O vai-e-vem completo (a resposta que completa o registro) vive em
    `test_grupo_financeiro_pendencia_pagamento.py`; aqui so fica provado que o anuncio
    incompleto nao vira linha.
    """
    grupo = await _montar_grupo_da_yasmin(conn)
    recibos = _RecibosDoGrupo()

    resultado = await processar_mensagem_do_grupo(
        conn, _mensagem(grupo, ANUNCIO_SEM_VALOR), enviar=recibos
    )

    assert resultado.motivo == "sem_valor"
    assert await _vendas(conn, grupo.modelo_id) == []
    assert recibos.enviados == [resultado.resposta]
    assert "✅" not in recibos.enviados[0]


async def test_entrega_duplicada_do_anuncio_nao_duplica_a_venda(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """O router do numero ProceX entrega a mesma requisicao 2x — a venda nao pode nascer duas."""
    grupo = await _montar_grupo_da_yasmin(conn)
    msg = _mensagem(grupo, ANUNCIO_SIMPLES)
    recibos = _RecibosDoGrupo()

    primeiro = await processar_mensagem_do_grupo(conn, msg, enviar=recibos)
    segundo = await processar_mensagem_do_grupo(conn, msg, enviar=recibos)

    assert (primeiro.status, segundo.status) == ("registrada", "duplicada")
    assert len(await _vendas(conn, grupo.modelo_id)) == 1
    assert len(recibos.enviados) == 1  # nem o recibo sai duas vezes


# --- 5. costura pelo webhook (o caminho de producao) --------------------------------------------


class _FakeSettings:
    """So os campos que o ramo de grupo do `evolution_webhook` le, isolados do singleton.

    `evolution_base_url` vazio de proposito: o cliente da Evolution devolve `None` antes de
    qualquer HTTP, entao a costura inteira roda sem tocar a rede.
    """

    evolution_webhook_token = ""
    webhook_max_body_bytes = 1_000_000
    jid_permitido = None
    evolution_grupo_coordenacao_jid = None
    feedback_rig_grupo_jid = None
    evolution_base_url = ""
    evolution_api_key = ""
    # A instancia do numero da ProceX, a mesma do payload: sem ela a entrega espelhada pelo
    # WhatsApp da modelo processaria a mensagem duas vezes (webhook/routes::_e_a_instancia_da_procex).
    grupo_financeiro_instancia = "procex-shared"
    evolution_fernando_jids: ClassVar[list[str]] = []
    reset_teste_instances: ClassVar[list[str]] = []


class _PoolUmaConn:
    def __init__(self, c: AsyncConnection[dict[str, Any]]) -> None:
        self._conn = c

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[AsyncConnection[dict[str, Any]]]:
        yield self._conn


class _State:
    pass


class _App:
    def __init__(self, pool: _PoolUmaConn) -> None:
        self.state = _State()
        self.state.settings = _FakeSettings()  # type: ignore[attr-defined]
        self.state.db_pool = pool  # type: ignore[attr-defined]


class _Request:
    def __init__(self, payload: dict[str, Any], app: _App) -> None:
        self._payload = payload
        self.app = app
        self.headers: dict[str, str] = {}
        self.state = _State()

    async def json(self) -> dict[str, Any]:
        return self._payload


async def test_webhook_transforma_o_anuncio_cru_em_venda_registrada(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Payload cru da Evolution -> `extrair_mensagem` -> porta unica -> linha no banco."""
    grupo = await _montar_grupo_da_yasmin(conn)
    payload = {
        "instance": "procex-shared",
        "data": {
            "pushName": "Dani",
            "key": {
                "id": "3EB0WEBVENDA",
                "remoteJid": grupo.jid,
                "fromMe": False,
                "participant": "5521966666666@s.whatsapp.net",
            },
            "message": {"conversation": ANUNCIO_SIMPLES},
        },
    }

    request = _Request(payload, _App(_PoolUmaConn(conn)))
    assert await evolution_webhook(request) == {"status": "grupo_financeiro_registrada"}  # type: ignore[arg-type]

    (venda,) = await _vendas(conn, grupo.modelo_id)
    assert venda["valor"] == Decimal("700.00")
    assert venda["cliente_nome"] == "Gabriel"
    # Sem `recebida_em` no envelope, a data e o dia BRT de agora (o grupo anuncia no mesmo dia).
    assert venda["data"] == datetime.now(UTC).astimezone(BRT).date()
