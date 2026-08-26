"""Encanamento do Grupo financeiro (spec 0005, ticket 01) — pela PORTA UNICA.

O que este arquivo prova, e por que assim:

1. Mensagem num Grupo financeiro CADASTRADO entra pela porta unica e fica persistida com a
   origem completa (grupo, autor, tipo).
2. Mensagem num grupo NAO cadastrado (ou cadastrado e inativo) e ignorada com log — nao vira
   linha, nao cai em outro agente, nao gera resposta.
3. Entrega duplicada da mesma mensagem nao processa duas vezes — com id de mensagem e sem ele.
4. A costura real do webhook: payload cru da Evolution -> `extrair_mensagem` -> ramo de grupo ->
   porta unica -> banco; e o grupo desconhecido continuando a cair no descarte de sempre.

Tudo entra por `processar_mensagem_do_grupo` (ou pelo webhook, que a chama). Nenhum teste toca
funcao interna do modulo: o desenho contrario foi o que induziu 4 bugs falsos no agente de venda
(licao do harness fiel, spec 0005 "Testing Decisions").

`needs_db` com `TEST_DATABASE_URL` + ROLLBACK sempre (padrao da casa): a idempotencia mora num
UNIQUE do banco e o roteamento e uma consulta closed-world — FakeConn provaria o mock, nao o
encanamento.
"""

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, ClassVar
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from barra.agente_financeiro import processar_mensagem_do_grupo
from barra.dominio.grupo_financeiro.modelos import MensagemDoGrupo
from barra.webhook.routes import evolution_webhook

pytestmark = pytest.mark.needs_db


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


# --- seeds ------------------------------------------------------------------------------------


async def _seed_modelo(c: AsyncConnection[dict[str, Any]]) -> UUID:
    modelo_id = uuid4()
    await c.execute(
        """
        INSERT INTO barravips.modelos
            (id, nome, idade, numero_whatsapp, valor_padrao, tipo_atendimento_aceito,
             percentual_repasse, status)
        VALUES (%s, %s, %s, %s, %s, %s::barravips.tipo_atendimento_enum[], %s,
                'ativa'::barravips.modelo_status_enum)
        """,
        (modelo_id, "Yasmin Teste", 25, f"test-wpp-{uuid4().hex}", 700, ["interno"], Decimal("40")),
    )
    return modelo_id


async def _seed_grupo(
    c: AsyncConnection[dict[str, Any]], modelo_id: UUID, *, jid: str, ativo: bool = True
) -> UUID:
    grupo_id = uuid4()
    await c.execute(
        """
        INSERT INTO barravips.grupos_financeiros (id, modelo_id, jid, nome, ativo)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (grupo_id, modelo_id, jid, "Modelo Yasmin Ruiva/financeiro", ativo),
    )
    return grupo_id


async def _mensagens_do_grupo(
    c: AsyncConnection[dict[str, Any]], grupo_id: UUID
) -> list[dict[str, Any]]:
    cur = await c.execute(
        """
        SELECT autor_jid, autor_nome, de_mim, tipo, texto, caption, media_url,
               quoted_message_id, evolution_message_id, chave_dedup
          FROM barravips.grupo_financeiro_mensagens
         WHERE grupo_id = %s
         ORDER BY recebida_em
        """,
        (grupo_id,),
    )
    return list(await cur.fetchall())


def _jid_novo() -> str:
    return f"1203634{uuid4().hex[:12]}@g.us"


# --- 1. grupo cadastrado: registra com origem completa ------------------------------------------


async def test_mensagem_de_grupo_cadastrado_fica_persistida_com_origem(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    modelo_id = await _seed_modelo(conn)
    jid = _jid_novo()
    grupo_id = await _seed_grupo(conn, modelo_id, jid=jid)

    resultado = await processar_mensagem_do_grupo(
        conn,
        MensagemDoGrupo(
            grupo_jid=jid,
            texto="Atendimento no nosso local\nCliente Gabriel\nPerfil bianca/yasmin\n700 1h",
            evolution_message_id="3EB0AAA1",
            autor_jid="5521999999999@s.whatsapp.net",
            autor_nome="Dani",
        ),
    )

    assert resultado.status == "registrada"
    assert resultado.grupo_id == grupo_id
    assert resultado.modelo_id == modelo_id
    assert resultado.mensagem_id is not None

    (linha,) = await _mensagens_do_grupo(conn, grupo_id)
    assert linha["autor_jid"] == "5521999999999@s.whatsapp.net"
    assert linha["autor_nome"] == "Dani"
    assert linha["tipo"] == "texto"
    assert linha["de_mim"] is False
    assert "Cliente Gabriel" in linha["texto"]
    assert linha["chave_dedup"] == "evo:3EB0AAA1"


async def test_origem_de_audio_e_imagem_tambem_fica_registrada(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Tipo faz parte da origem: audio e comprovante entram no ticket 06/07 lendo esta linha."""
    modelo_id = await _seed_modelo(conn)
    jid = _jid_novo()
    grupo_id = await _seed_grupo(conn, modelo_id, jid=jid)

    for tipo, id_msg in (("audio", "3EB0AUD1"), ("imagem", "3EB0IMG1")):
        resultado = await processar_mensagem_do_grupo(
            conn,
            MensagemDoGrupo(
                grupo_jid=jid,
                texto="",
                tipo=tipo,  # type: ignore[arg-type]
                evolution_message_id=id_msg,
                autor_jid="5521988888888@s.whatsapp.net",
                caption="comprovante" if tipo == "imagem" else None,
                media_url="https://mmg.whatsapp.net/x",
            ),
        )
        assert resultado.status == "registrada"

    tipos = {linha["tipo"] for linha in await _mensagens_do_grupo(conn, grupo_id)}
    assert tipos == {"audio", "imagem"}


# --- 2. grupo nao cadastrado / inativo: ignora com log ------------------------------------------


async def test_grupo_nao_cadastrado_e_ignorado_com_log(
    conn: AsyncConnection[dict[str, Any]], caplog: pytest.LogCaptureFixture
) -> None:
    jid = _jid_novo()
    with caplog.at_level(logging.INFO, logger="barra.agente_financeiro.porta"):
        resultado = await processar_mensagem_do_grupo(
            conn, MensagemDoGrupo(grupo_jid=jid, texto="bom dia meninas", autor_jid="x@lid")
        )

    assert resultado.status == "grupo_nao_cadastrado"
    assert resultado.grupo_id is None and resultado.mensagem_id is None
    assert any("grupo_financeiro_nao_cadastrado" in r.message for r in caplog.records)

    cur = await conn.execute("SELECT count(*) AS n FROM barravips.grupo_financeiro_mensagens")
    row = await cur.fetchone()
    assert row is not None and row["n"] == 0


async def test_grupo_inativo_e_tratado_como_nao_cadastrado(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Inativar, nunca deletar: desligar a ingestao de um grupo devolve o silencio, nao um erro."""
    modelo_id = await _seed_modelo(conn)
    jid = _jid_novo()
    grupo_id = await _seed_grupo(conn, modelo_id, jid=jid, ativo=False)

    resultado = await processar_mensagem_do_grupo(
        conn, MensagemDoGrupo(grupo_jid=jid, texto="600 pix", evolution_message_id="3EB0OFF1")
    )

    assert resultado.status == "grupo_nao_cadastrado"
    assert await _mensagens_do_grupo(conn, grupo_id) == []


# --- 3. entrega duplicada -----------------------------------------------------------------------


async def test_entrega_duplicada_com_id_nao_registra_duas_vezes(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """O router do numero ProceX entrega a mesma requisicao 2x (1-56 ms de diferenca)."""
    modelo_id = await _seed_modelo(conn)
    jid = _jid_novo()
    grupo_id = await _seed_grupo(conn, modelo_id, jid=jid)
    msg = MensagemDoGrupo(
        grupo_jid=jid, texto="foi pix ou din?", evolution_message_id="3EB0DUP1", autor_nome="FEH"
    )

    primeiro = await processar_mensagem_do_grupo(conn, msg)
    segundo = await processar_mensagem_do_grupo(conn, msg)

    assert primeiro.status == "registrada"
    assert segundo.status == "duplicada"
    assert segundo.mensagem_id is None
    assert len(await _mensagens_do_grupo(conn, grupo_id)) == 1


async def test_entrega_duplicada_sem_id_de_mensagem_tambem_e_absorvida(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Id nulo (envelope da EvoGo sem ID, replay do export): a chave cai no conteudo + balde.

    Sem isto a defesa seria um unico sobre coluna nullable — e no Postgres cada NULL e distinto,
    entao ele nunca colide (foi assim que o myEYE respondeu 2x com o indice ja aplicado).
    """
    modelo_id = await _seed_modelo(conn)
    jid = _jid_novo()
    grupo_id = await _seed_grupo(conn, modelo_id, jid=jid)
    recebida_em = datetime(2026, 8, 13, 12, 0, 1, tzinfo=UTC)

    def _entrega(quando: datetime) -> MensagemDoGrupo:
        return MensagemDoGrupo(
            grupo_jid=jid,
            texto="confere: 600 pix, 600 pix",
            autor_jid="5521977777777@s.whatsapp.net",
            recebida_em=quando,
        )

    primeiro = await processar_mensagem_do_grupo(conn, _entrega(recebida_em))
    # Segunda entrega da MESMA mensagem: chega milissegundos depois, no mesmo balde.
    segundo = await processar_mensagem_do_grupo(
        conn, _entrega(recebida_em.replace(microsecond=56_000))
    )

    assert primeiro.status == "registrada"
    assert segundo.status == "duplicada"
    linhas = await _mensagens_do_grupo(conn, grupo_id)
    assert len(linhas) == 1
    assert linhas[0]["evolution_message_id"] is None
    assert linhas[0]["chave_dedup"].startswith("conteudo:")


async def test_mesmo_texto_em_grupos_diferentes_nao_colide(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """A chave de conteudo e por GRUPO: o mesmo anuncio nos dois grupos entra nos dois.

    (Que a VENDA nao duplique e dedup cross-grupo por conteudo do registro — outro ticket, outra
    camada. O log de origem tem que preservar as duas mensagens.)
    """
    modelo_a = await _seed_modelo(conn)
    modelo_b = await _seed_modelo(conn)
    jid_a, jid_b = _jid_novo(), _jid_novo()
    grupo_a = await _seed_grupo(conn, modelo_a, jid=jid_a)
    grupo_b = await _seed_grupo(conn, modelo_b, jid=jid_b)
    recebida_em = datetime(2026, 8, 13, 21, 30, tzinfo=UTC)

    a = await processar_mensagem_do_grupo(
        conn, MensagemDoGrupo(grupo_jid=jid_a, texto="1300 cada uma", recebida_em=recebida_em)
    )
    b = await processar_mensagem_do_grupo(
        conn, MensagemDoGrupo(grupo_jid=jid_b, texto="1300 cada uma", recebida_em=recebida_em)
    )

    assert (a.status, b.status) == ("registrada", "registrada")
    assert len(await _mensagens_do_grupo(conn, grupo_a)) == 1
    assert len(await _mensagens_do_grupo(conn, grupo_b)) == 1


# --- 4. costura pelo webhook (destino novo da rota compartilhada) -------------------------------


class _FakeSettings:
    """So os campos que o ramo de grupo do `evolution_webhook` le, isolados do singleton."""

    evolution_webhook_token = ""
    webhook_max_body_bytes = 1_000_000
    jid_permitido = None
    evolution_grupo_coordenacao_jid = None
    feedback_rig_grupo_jid = None
    # A instancia do numero da ProceX, IGUAL a do payload deste arquivo. Preenchida (e nao vazia,
    # que seria o fail-open) para o teste rodar o mesmo caminho de producao: o Grupo financeiro tem
    # a modelo dentro, e o WhatsApp dela entrega a MESMA mensagem por outra instancia.
    grupo_financeiro_instancia = "procex-shared"
    # Default de producao (26/08/2026): o agente ingere e NAO fala. Os testes deste arquivo
    # medem ingestao, entao rodam no default; quem quiser a boca liga por atributo de instancia.
    grupo_financeiro_responde = False
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


def _payload_grupo(*, jid: str, texto: str, message_id: str) -> dict[str, Any]:
    """Payload Evolution de uma gestora falando no Grupo financeiro (numero da ProceX)."""
    return {
        "instance": "procex-shared",
        "data": {
            "pushName": "Parcerias",
            "key": {
                "id": message_id,
                "remoteJid": jid,
                "fromMe": False,
                "participant": "5521966666666@s.whatsapp.net",
            },
            "message": {"conversation": texto},
        },
    }


async def _chamar_webhook(
    c: AsyncConnection[dict[str, Any]], payload: dict[str, Any]
) -> dict[str, str]:
    request = _Request(payload, _App(_PoolUmaConn(c)))
    return await evolution_webhook(request)  # type: ignore[arg-type]


async def test_webhook_entrega_grupo_financeiro_na_porta_unica(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    modelo_id = await _seed_modelo(conn)
    jid = _jid_novo()
    grupo_id = await _seed_grupo(conn, modelo_id, jid=jid)
    payload = _payload_grupo(jid=jid, texto="Cliente Igor 800 1h", message_id="3EB0WEB1")

    assert await _chamar_webhook(conn, payload) == {"status": "grupo_financeiro_registrada"}
    # Segunda entrega da MESMA requisicao pelo router: absorvida, sem segunda linha.
    assert await _chamar_webhook(conn, payload) == {"status": "grupo_financeiro_duplicada"}

    (linha,) = await _mensagens_do_grupo(conn, grupo_id)
    assert linha["evolution_message_id"] == "3EB0WEB1"
    assert linha["autor_jid"] == "5521966666666@s.whatsapp.net"
    assert linha["autor_nome"] == "Parcerias"
    assert linha["texto"] == "Cliente Igor 800 1h"


async def test_modo_so_escuta_ingere_tudo_e_nao_manda_a_boca_para_a_porta(
    conn: AsyncConnection[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`grupo_financeiro_responde=False`: registra igual, e a porta recebe `enviar=None`.

    O que se prova aqui e o ENCANAMENTO, nao a educacao da porta: a boca nao pode chegar la
    dentro. Mandar um `enviar` que engole o texto pareceria igual por fora e seria pior — a porta
    gravaria a linha `de_mim` de uma fala que ninguem leu, e a trava de "ja perguntei isso"
    passaria a se auto-silenciar por causa dela.
    """
    modelo_id = await _seed_modelo(conn)
    jid = _jid_novo()
    grupo_id = await _seed_grupo(conn, modelo_id, jid=jid)

    from barra.webhook import routes as _routes

    def _explode(*_a: Any, **_k: Any) -> Any:  # pragma: no cover - so falha se for chamado
        raise AssertionError("o transporte foi montado no modo so escuta")

    monkeypatch.setattr(_routes, "_falar_no_grupo_financeiro", _explode)

    payload = _payload_grupo(jid=jid, texto="Cliente Igor 800 1h", message_id="3EB0MUDO")
    assert await _chamar_webhook(conn, payload) == {"status": "grupo_financeiro_registrada"}

    # A ingestao aconteceu inteira: a mensagem entrou no log de origem do grupo...
    (linha,) = await _mensagens_do_grupo(conn, grupo_id)
    assert linha["texto"] == "Cliente Igor 800 1h"
    # ...e nenhuma fala do agente foi registrada como dita.
    cur = await conn.execute(
        "SELECT count(*) AS n FROM barravips.grupo_financeiro_mensagens WHERE de_mim",
    )
    assert (await cur.fetchone())["n"] == 0


async def test_com_a_boca_ligada_o_transporte_e_montado(
    conn: AsyncConnection[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """O outro lado do interruptor — senao o teste acima passaria com o ramo quebrado dos dois.

    Mede a mesma coisa que ele, pelo mesmo ponto: se o transporte foi MONTADO. O que a porta faz
    com a boca depois disso (se ha recibo, qual o texto, o que ela cita) e assunto dos testes da
    porta, nao deste arquivo.
    """
    modelo_id = await _seed_modelo(conn)
    jid = _jid_novo()
    await _seed_grupo(conn, modelo_id, jid=jid)

    from barra.webhook import routes as _routes

    montado: list[str] = []
    original = _routes._falar_no_grupo_financeiro

    def _espiao(settings: Any, msg: Any) -> Any:
        montado.append(msg.remote_jid)
        return original(settings, msg)

    monkeypatch.setattr(_routes, "_falar_no_grupo_financeiro", _espiao)

    app = _App(_PoolUmaConn(conn))
    app.state.settings.grupo_financeiro_responde = True  # type: ignore[attr-defined]
    request = _Request(
        _payload_grupo(jid=jid, texto="Cliente Ramon 600 1h", message_id="3EB0FALA"), app
    )
    assert await evolution_webhook(request) == {  # type: ignore[arg-type]
        "status": "grupo_financeiro_registrada"
    }
    assert montado == [jid]


async def test_webhook_grupo_desconhecido_nao_vira_nada(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Numero compartilhado (myEYE + grupos financeiros): grupo fora do cadastro cai no descarte
    de sempre — nao vira Grupo financeiro, nao vira cliente, nao gera resposta."""
    payload = _payload_grupo(
        jid=_jid_novo(), texto="alguem viu meu carregador?", message_id="3EB0X"
    )

    assert await _chamar_webhook(conn, payload) == {"status": "grupo_nao_coordenacao"}

    cur = await conn.execute("SELECT count(*) AS n FROM barravips.grupo_financeiro_mensagens")
    row = await cur.fetchone()
    assert row is not None and row["n"] == 0


async def test_entrega_espelhada_pela_instancia_da_modelo_e_descartada(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """A modelo esta DENTRO do grupo: o WhatsApp dela entrega a mesma mensagem por outra instancia.

    Descartar a espelhada nao e so economia. `fromMe` e relativo a instancia que entregou: na
    entrega da modelo as falas DELA chegam com `fromMe=true` (morreriam como eco do agente) e o
    recibo do proprio agente chega com `fromMe=false` (voltaria para o processamento) — o corte de
    eco invertido, exatamente o que ele existe para impedir.
    """
    modelo_id = await _seed_modelo(conn)
    jid = _jid_novo()
    grupo_id = await _seed_grupo(conn, modelo_id, jid=jid)
    payload = _payload_grupo(jid=jid, texto="Cliente Igor 800 1h", message_id="3EB0ESPELHO")
    payload["instance"] = "wpp-da-modelo"

    assert await _chamar_webhook(conn, payload) == {"status": "grupo_nao_coordenacao"}

    assert await _mensagens_do_grupo(conn, grupo_id) == []
