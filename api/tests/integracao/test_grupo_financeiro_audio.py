"""Audio na porta do Agente financeiro (spec 0005, ticket 06) — pela PORTA UNICA.

A modelo responde falando, porque e assim que ela usa o WhatsApp: "foi pix", "600", "é a Duda"
chegam como audio de 3 segundos. A tese do ticket e que isso NAO e um fluxo: o audio vira texto na
entrada e daí em diante a conduta e a mesma do texto digitado — mesma leitura, mesmo recibo, mesmo
silencio para conversa social.

Por isso o teste central aqui e de PARIDADE: a mesma conversa e rodada duas vezes, uma com a
resposta digitada e outra com a resposta falada, e os efeitos observaveis tem que ser iguais campo
a campo. Um teste que so afirmasse "audio de pix escreveu pix" passaria com um segundo caminho de
codigo escondido atras do audio, que e exatamente o que a spec proibe.

A transcricao e STUBADA (padrao da casa: nenhum teste novo pode exigir chave). O que o stub troca e
so a ida ao provider — o resto do caminho e o de producao, incluindo a gravacao do texto ouvido no
log de origem, que e o que faz o audio existir no CONTEXTO das mensagens seguintes.

`needs_db` com `TEST_DATABASE_URL` + ROLLBACK sempre.
"""

import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from prometheus_client import REGISTRY
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from barra.agente_financeiro import ResultadoDaPorta, processar_mensagem_do_grupo
from barra.dominio.grupo_financeiro.modelos import (
    AUDIO_SEM_TRANSCRICAO,
    AudioDoGrupo,
    MensagemDoGrupo,
)
from barra.dominio.grupo_financeiro.pergunta import PREFIXO_DA_PERGUNTA

pytestmark = pytest.mark.needs_db

# Grafia do export "Modelo Yasmin Ruiva/financeiro".
ANUNCIO = "Atendimento no nosso local \nCliente Lucas \nPerfil {apelido} \n600 1h"
ANUNCIO_SEM_VALOR = "Atendimento no nosso local \nCliente Lucas \nPerfil {apelido}"

# 09/08 01:09 UTC = 08/08 22:09 em Brasilia — a venda e do dia 08, como a gestora conta.
NOITE_DE_08_08 = datetime(2026, 8, 9, 1, 9, tzinfo=UTC)

# Um audio de WhatsApp de verdade e ogg/opus; para o teste basta que os bytes cheguem inteiros ate
# o transcritor (e o stub confere que chegaram).
OGG = b"OggS\x00\x02fake-opus"


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


# --- o grupo -------------------------------------------------------------------------------------


class _Falas:
    """O que o agente postou no grupo. Coleta em vez de ir a rede."""

    def __init__(self) -> None:
        self.enviadas: list[str] = []

    async def __call__(self, texto: str, *, citar: str | None = None) -> None:
        self.enviadas.append(texto)

    @property
    def ultima(self) -> str | None:
        return self.enviadas[-1] if self.enviadas else None


class _Ouvido:
    """Transcritor stubado: devolve o que foi combinado e conta o que ouviu.

    A contagem e metade do teste — ela prova o que NAO se transcreve (eco do proprio agente,
    segunda entrega da mesma mensagem), que e onde o custo de STT escaparia sem ninguem ver.
    """

    def __init__(self, *falado: str, erro: Exception | None = None) -> None:
        self.falado = list(falado)
        self.erro = erro
        self.ouvidos: list[bytes] = []

    async def __call__(self, audio: AudioDoGrupo) -> str | None:
        self.ouvidos.append(audio.conteudo)
        if self.erro is not None:
            raise self.erro
        return self.falado.pop(0) if self.falado else None

    @property
    def vezes(self) -> int:
        return len(self.ouvidos)


class _Grupo:
    def __init__(self, modelo_id: UUID, jid: str, apelido: str, inicio: datetime) -> None:
        self.modelo_id = modelo_id
        self.jid = jid
        self.apelido = apelido
        self.relogio = inicio


async def _montar_grupo(
    c: AsyncConnection[dict[str, Any]], *, inicio: datetime = NOITE_DE_08_08
) -> _Grupo:
    """Um Grupo financeiro novo (modelo + Nome de anuncio + vinculo closed-world).

    Apelido unico por grupo: `modelo_nomes_anuncio.nome_normalizado` e UNIQUE global (um apelido
    pertence a UMA mulher), entao dois grupos montados no mesmo teste nao podem dividir "bianca".
    """
    modelo_id = uuid4()
    apelido = f"bianca{uuid4().hex[:8]}"
    await c.execute(
        """
        INSERT INTO barravips.modelos
            (id, nome, idade, numero_whatsapp, valor_padrao, tipo_atendimento_aceito,
             percentual_repasse, status)
        VALUES (%s, %s, %s, %s, %s, %s::barravips.tipo_atendimento_enum[], %s,
                'ativa'::barravips.modelo_status_enum)
        """,
        (
            modelo_id,
            f"Yasmin {uuid4().hex[:6]}",
            25,
            f"test-wpp-{uuid4().hex}",
            600,
            ["interno"],
            Decimal("40"),
        ),
    )
    await c.execute(
        """
        INSERT INTO barravips.modelo_nomes_anuncio (modelo_id, nome, nome_normalizado)
        VALUES (%s, %s, %s)
        """,
        (modelo_id, apelido, apelido),
    )
    jid = f"1203634{uuid4().hex[:12]}@g.us"
    await c.execute(
        """
        INSERT INTO barravips.grupos_financeiros (id, modelo_id, jid, nome)
        VALUES (%s, %s, %s, %s)
        """,
        (uuid4(), modelo_id, jid, "Modelo Yasmin Ruiva/financeiro"),
    )
    return _Grupo(modelo_id, jid, apelido, inicio)


async def _dizer(
    c: AsyncConnection[dict[str, Any]],
    grupo: _Grupo,
    texto: str,
    *,
    falas: _Falas,
    ouvido: _Ouvido | None = None,
    depois: timedelta = timedelta(seconds=30),
    **kw: Any,
) -> ResultadoDaPorta:
    """Um humano digita no grupo."""
    grupo.relogio += depois
    kw.setdefault("evolution_message_id", f"3EB0{uuid4().hex[:12]}")
    kw.setdefault("autor_nome", "Dani")
    kw.setdefault("autor_jid", "5521999999999@s.whatsapp.net")
    msg = MensagemDoGrupo(grupo_jid=grupo.jid, texto=texto, recebida_em=grupo.relogio, **kw)
    return await processar_mensagem_do_grupo(c, msg, enviar=falas, transcrever=ouvido)


async def _falar(
    c: AsyncConnection[dict[str, Any]],
    grupo: _Grupo,
    *,
    falas: _Falas,
    ouvido: _Ouvido | None,
    depois: timedelta = timedelta(seconds=30),
    audio: AudioDoGrupo | None = AudioDoGrupo(conteudo=OGG, mimetype="audio/ogg; codecs=opus"),
    **kw: Any,
) -> ResultadoDaPorta:
    """A modelo manda um audio: mensagem de tipo `audio`, com texto VAZIO (e assim que chega)."""
    grupo.relogio += depois
    kw.setdefault("evolution_message_id", f"3EB0{uuid4().hex[:12]}")
    kw.setdefault("autor_nome", "Yasmin")
    kw.setdefault("autor_jid", "5571988887777@s.whatsapp.net")
    msg = MensagemDoGrupo(
        grupo_jid=grupo.jid,
        texto="",
        tipo="audio",
        audio=audio,
        recebida_em=grupo.relogio,
        **kw,
    )
    return await processar_mensagem_do_grupo(c, msg, enviar=falas, transcrever=ouvido)


async def _vendas(c: AsyncConnection[dict[str, Any]], modelo_id: UUID) -> list[dict[str, Any]]:
    cur = await c.execute(
        """
        SELECT id, valor, data, cliente_nome, duracao_minutos, forma_pagamento
          FROM barravips.vendas_registradas
         WHERE modelo_id = %s AND anulada_em IS NULL
         ORDER BY data, id
        """,
        (modelo_id,),
    )
    return list(await cur.fetchall())


async def _texto_no_log(c: AsyncConnection[dict[str, Any]], mensagem_id: UUID | None) -> str | None:
    cur = await c.execute(
        "SELECT texto, tipo FROM barravips.grupo_financeiro_mensagens WHERE id = %s",
        (mensagem_id,),
    )
    row = await cur.fetchone()
    assert row is not None and row["tipo"] == "audio"
    return row["texto"]


# --- 1. paridade: falado == digitado --------------------------------------------------------------


@dataclass(frozen=True)
class _Efeito:
    """O que se observa de fora depois da resposta de pagamento — sem ids, que sao unicos."""

    motivo: str | None
    resposta: str | None
    fala_no_grupo: str | None
    quantos_pagamentos: int
    pendencias: tuple[str, ...]
    """Só os TIPOS de pendencia: `Pendencia` carrega o venda_id, e id nao se compara entre duas
    rodadas da mesma conversa (ticket 07 — a venda em pix passou a ter pendencia de comprovante)."""
    venda: tuple[Decimal, date, str | None, str | None]


async def _conversa_ate_o_pagamento(
    c: AsyncConnection[dict[str, Any]], *, por_audio: bool
) -> _Efeito:
    """Anuncio digitado -> "Foi pix" (digitado ou falado). Devolve o efeito da SEGUNDA mensagem."""
    grupo = await _montar_grupo(c)
    falas = _Falas()
    ouvido = _Ouvido("Foi pix")

    await _dizer(c, grupo, ANUNCIO.format(apelido=grupo.apelido), falas=falas)
    antes = len(falas.enviadas)

    if por_audio:
        pagou = await _falar(c, grupo, falas=falas, ouvido=ouvido, depois=timedelta(hours=20))
        assert ouvido.vezes == 1
    else:
        pagou = await _dizer(c, grupo, "Foi pix", falas=falas, depois=timedelta(hours=20))

    (venda,) = await _vendas(c, grupo.modelo_id)
    return _Efeito(
        motivo=pagou.motivo,
        resposta=pagou.resposta,
        fala_no_grupo=falas.enviadas[antes] if len(falas.enviadas) > antes else None,
        quantos_pagamentos=len(pagou.pagamentos),
        pendencias=tuple(p.tipo for p in pagou.pendencias),
        venda=(venda["valor"], venda["data"], venda["cliente_nome"], venda["forma_pagamento"]),
    )


async def test_resposta_falada_produz_o_mesmo_efeito_que_a_digitada(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """A prova de que audio nao e um fluxo: os dois caminhos terminam no MESMO estado."""
    digitado = await _conversa_ate_o_pagamento(conn, por_audio=False)
    falado = await _conversa_ate_o_pagamento(conn, por_audio=True)

    assert falado == digitado
    # E o efeito e o esperado, nao dois nadas iguais.
    assert digitado.motivo == "pagamento_absorvido"
    assert digitado.venda == (Decimal("600.00"), date(2026, 8, 8), "Lucas", "pix")
    assert digitado.fala_no_grupo is not None
    assert digitado.fala_no_grupo.startswith("✅ Anotei: pix")


async def test_anuncio_ditado_por_audio_registra_a_venda_e_fica_no_log(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """A venda inteira pode chegar falada — e o que foi ouvido fica no log como texto do grupo."""
    grupo = await _montar_grupo(conn)
    falas = _Falas()
    ouvido = _Ouvido(ANUNCIO.format(apelido=grupo.apelido))

    lancou = await _falar(conn, grupo, falas=falas, ouvido=ouvido)

    assert lancou.status == "registrada"
    assert len(lancou.vendas) == 1
    (venda,) = await _vendas(conn, grupo.modelo_id)
    assert venda["valor"] == Decimal("600.00")
    assert venda["cliente_nome"] == "Lucas"
    assert venda["duracao_minutos"] == 60
    assert falas.ultima is not None and falas.ultima.startswith("✅ Registrei:")
    # O texto ouvido vai para a MESMA coluna do texto digitado: e o que deixa a mensagem existir
    # para quem relê o grupo depois (correcao por quote, pergunta minima, fechamento).
    assert await _texto_no_log(conn, lancou.mensagem_id) == ANUNCIO.format(apelido=grupo.apelido)


async def test_resposta_falada_completa_a_pergunta_minima(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """ "600" falado destrava o anuncio incompleto igual ao "600" digitado."""
    grupo = await _montar_grupo(conn)
    falas = _Falas()
    ouvido = _Ouvido("600 1h")

    pediu = await _dizer(conn, grupo, ANUNCIO_SEM_VALOR.format(apelido=grupo.apelido), falas=falas)
    assert pediu.motivo == "sem_valor"
    assert falas.ultima is not None and falas.ultima.startswith(PREFIXO_DA_PERGUNTA)

    respondeu = await _falar(conn, grupo, falas=falas, ouvido=ouvido, depois=timedelta(minutes=6))

    assert respondeu.motivo is None
    assert len(respondeu.vendas) == 1
    (venda,) = await _vendas(conn, grupo.modelo_id)
    assert venda["valor"] == Decimal("600.00")
    assert venda["duracao_minutos"] == 60
    assert venda["data"] == date(2026, 8, 8)  # dia do ANUNCIO, nao o do audio
    assert falas.ultima.startswith("✅ Registrei:")


# --- 2. falha de transcricao ----------------------------------------------------------------------


def _contador_de_audio(resultado: str) -> float:
    # Gotcha da casa: `get_sample_value` NAO duplica o sufixo `_total`.
    return (
        REGISTRY.get_sample_value("barra_grupo_financeiro_audio_total", {"resultado": resultado})
        or 0.0
    )


async def test_falha_de_transcricao_nao_derruba_o_turno_e_a_pendencia_continua_aberta(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Provider fora: a mensagem entra, o agente cala, a fila anda e o que faltava segue faltando."""
    grupo = await _montar_grupo(conn)
    falas = _Falas()
    surdo = _Ouvido(erro=RuntimeError("openrouter fora do ar"))
    # Este agente falha CALADO: sem a metrica, um provider fora nao aparece em lugar nenhum — nao
    # ha resposta faltando na tela, so venda que nunca foi registrada.
    erros_antes = _contador_de_audio("erro")
    vazios_antes = _contador_de_audio("vazio")

    await _dizer(conn, grupo, ANUNCIO.format(apelido=grupo.apelido), falas=falas)
    depois_do_recibo = len(falas.enviadas)

    mudo = await _falar(conn, grupo, falas=falas, ouvido=surdo, depois=timedelta(hours=20))

    # Nao levantou (o webhook e sincrono: excecao aqui viraria reentrega em loop da Evolution).
    assert mudo.status == "registrada"
    assert mudo.motivo == "audio_sem_transcricao"
    assert mudo.pagamentos == ()
    assert len(falas.enviadas) == depois_do_recibo  # o agente nao pede para repetir
    assert await _texto_no_log(conn, mudo.mensagem_id) == AUDIO_SEM_TRANSCRICAO
    (venda,) = await _vendas(conn, grupo.modelo_id)
    assert venda["forma_pagamento"] is None  # a Pendencia continua aberta
    # Contado como ERRO, nao como "audio sem fala": as duas causas pedem acoes diferentes de quem
    # olha o painel (uma e o provider, a outra e a modelo mandando audio mudo).
    assert _contador_de_audio("erro") == erros_antes + 1
    assert _contador_de_audio("vazio") == vazios_antes

    # E a fila nao travou: a proxima mensagem do grupo e processada normalmente e resolve o que o
    # audio perdido resolveria.
    pagou = await _dizer(conn, grupo, "Foi pix", falas=falas, depois=timedelta(minutes=2))
    assert pagou.motivo == "pagamento_absorvido"
    (venda,) = await _vendas(conn, grupo.modelo_id)
    assert venda["forma_pagamento"] == "pix"


async def test_audio_sem_fala_e_audio_sem_bytes_terminam_no_mesmo_lugar(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Audio mudo, midia que o webhook nao conseguiu e ambiente sem provider: um desfecho so."""
    grupo = await _montar_grupo(conn)
    falas = _Falas()

    sem_fala = await _falar(conn, grupo, falas=falas, ouvido=_Ouvido())  # devolve None
    sem_bytes = await _falar(conn, grupo, falas=falas, ouvido=_Ouvido("foi pix"), audio=None)
    sem_provider = await _falar(conn, grupo, falas=falas, ouvido=None)

    for resultado in (sem_fala, sem_bytes, sem_provider):
        assert resultado.status == "registrada"
        assert resultado.motivo == "audio_sem_transcricao"
        assert resultado.vendas == ()
        assert await _texto_no_log(conn, resultado.mensagem_id) == AUDIO_SEM_TRANSCRICAO
    assert falas.enviadas == []


# --- 3. audio social e o custo de ouvir -----------------------------------------------------------


async def test_audio_social_nao_registra_nem_responde(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Mesma regra do texto social: entra no log, morre ali, sem venda e sem resposta."""
    grupo = await _montar_grupo(conn)
    falas = _Falas()
    ouvido = _Ouvido("kkkkk amiga eu não acredito que ele falou isso, depois te conto")

    social = await _falar(conn, grupo, falas=falas, ouvido=ouvido)

    assert social.status == "registrada"
    assert social.motivo == "nao_e_anuncio"
    assert social.vendas == ()
    assert social.resposta is None
    assert falas.enviadas == []
    assert await _vendas(conn, grupo.modelo_id) == []


async def test_eco_do_agente_e_reentrega_nao_custam_transcricao(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """STT so para audio de gente, uma vez por mensagem — o resto seria dinheiro queimado."""
    grupo = await _montar_grupo(conn)
    falas = _Falas()
    ouvido = _Ouvido("Foi pix", "Foi pix")

    eco = await _falar(conn, grupo, falas=falas, ouvido=ouvido, de_mim=True)
    assert eco.motivo == "eco_do_agente"
    assert ouvido.vezes == 0

    evo = f"3EB0{uuid4().hex[:12]}"
    await _falar(conn, grupo, falas=falas, ouvido=ouvido, evolution_message_id=evo)
    repetida = await _falar(conn, grupo, falas=falas, ouvido=ouvido, evolution_message_id=evo)

    assert repetida.status == "duplicada"
    assert ouvido.vezes == 1  # a segunda entrega do router morre no dedup ANTES do provider
