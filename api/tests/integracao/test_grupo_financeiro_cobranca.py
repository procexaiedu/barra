"""Cobranca da agencia (spec 0005, ticket 08) — pela PORTA UNICA.

O gesto real e o de 13/08 no export "Modelo Yasmin Ruiva/financeiro": um gestor posta
"*3RJ Suporte/Anuncio:* / 3 DIAS | R$ 385,80 / envia para o site e envia o comprovante", a modelo
pergunta a chave, paga e posta o comprovante. Ate aqui isso nao existia no sistema: a divida vivia
na memoria do gestor e o Pix que a quitava era, para o modulo, um comprovante retido que ninguem
conseguia explicar (`comprovante_sem_par`, ticket 09).

O que este arquivo guarda:

* a cobranca vira **debito da modelo**, nunca venda nem receita (ADR-0043 nao a conhece);
* o comprovante que a paga **abate a cobranca e nenhuma venda** — e a fala diz isso com todas as
  letras, porque e a unica frase que impede o gestor de continuar descontando esse dinheiro do que
  a modelo ainda deve comprovar;
* quando o mesmo Pix serviria para os dois eixos, o agente **pergunta** em vez de escolher;
* apagar a mensagem anula o debito PENDENTE — e nao desfaz um pagamento que ja tem prova.

Tudo entra pela mesma porta que a producao usa. O leitor de comprovante e stubado (nenhum teste
desta casa exige chave de provider). `needs_db` com `TEST_DATABASE_URL` + ROLLBACK sempre: o dedup
por chave viva e o CHECK de "quitacao tem prova" sao garantias do BANCO.
"""

import os
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from barra.agente_financeiro import (
    ResultadoDaPorta,
    processar_delecao_do_grupo,
    processar_mensagem_do_grupo,
)
from barra.agente_financeiro.porta import fechamento_da_modelo
from barra.agente_financeiro.rotina import cobrar_pendencias_do_grupo
from barra.dominio.grupo_financeiro.comprovante import LeituraDoComprovante, normalizar_chave
from barra.dominio.grupo_financeiro.modelos import (
    DelecaoNoGrupo,
    GrupoFinanceiro,
    ImagemDoGrupo,
    MensagemDoGrupo,
)
from barra.dominio.grupo_financeiro.repo import buscar_grupo_por_jid

pytestmark = pytest.mark.needs_db

# --- mensagens reais do export (grafia intacta) -------------------------------------------------

COBRANCA = "*3RJ Suporte/Anúncio:*\n3 DIAS | R$ 385,80\nEnvia para o site e envia o comprovante"
ANUNCIO = "Atendimento no nosso local \nCliente {cliente} \nPerfil {apelido} \n{valor} 1h"

CHAVE_DA_CASA = "00000000-0000-0000-0000-000000000000"
"""Destino de fechamento da casa, FICTICIO (a chave viva entra a mao pelo runbook, em prod)."""
TITULAR_DA_CASA = "Fulano de Tal"
CHAVE_3RJ = "+55 71 99984 0879"
"""Destino do pagamento da cobranca: a agencia. Fora da lista da casa por definicao — e por isso
que o aviso de "chave fora da lista" NAO sai neste caminho (ver `_conciliar_com_cobranca`)."""

# 14/08 00:30 UTC = 13/08 21:30 em Brasilia — a noite em que a 3RJ cobrou o anuncio.
NOITE_DE_13_08 = datetime(2026, 8, 14, 0, 30, tzinfo=UTC)
DIA_13_08 = date(2026, 8, 13)
# 14/08 11:00 UTC = 08:00 em Brasilia: a manha seguinte, quando o cron da rotina roda.
MANHA_DE_14_08 = datetime(2026, 8, 14, 11, 0, tzinfo=UTC)


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


class _Olho:
    """Leitor de comprovante stubado: devolve o combinado, sem tocar em provider nenhum."""

    def __init__(self, *leituras: LeituraDoComprovante) -> None:
        self.leituras = list(leituras)

    async def __call__(self, imagem: ImagemDoGrupo) -> LeituraDoComprovante | None:
        return self.leituras.pop(0) if self.leituras else None


class _Grupo:
    def __init__(self, modelo_id: UUID, jid: str, apelido: str, inicio: datetime) -> None:
        self.modelo_id = modelo_id
        self.jid = jid
        self.apelido = apelido
        self.relogio = inicio


async def _montar_grupo(
    c: AsyncConnection[dict[str, Any]], *, inicio: datetime = NOITE_DE_13_08
) -> _Grupo:
    """Um Grupo financeiro novo (modelo + Nome de anuncio + vinculo closed-world)."""
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
    await c.execute(
        """
        INSERT INTO barravips.chaves_pix_conhecidas (chave, chave_normalizada, titular, descricao)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (chave_normalizada) DO NOTHING
        """,
        (
            CHAVE_DA_CASA,
            normalizar_chave(CHAVE_DA_CASA),
            TITULAR_DA_CASA,
            "Chave de fechamento ficticia, cadastrada pelo teste.",
        ),
    )
    return _Grupo(modelo_id, jid, apelido, inicio)


async def _dizer(
    c: AsyncConnection[dict[str, Any]],
    grupo: _Grupo,
    texto: str,
    *,
    falas: _Falas,
    depois: timedelta = timedelta(seconds=30),
    **kw: Any,
) -> ResultadoDaPorta:
    """Um humano digita no grupo (o gestor, por default — e ele quem cobra)."""
    grupo.relogio += depois
    kw.setdefault("evolution_message_id", f"3EB0{uuid4().hex[:12]}")
    kw.setdefault("autor_nome", "Parcerias")
    kw.setdefault("autor_jid", "5521966666666@s.whatsapp.net")
    msg = MensagemDoGrupo(grupo_jid=grupo.jid, texto=texto, recebida_em=grupo.relogio, **kw)
    return await processar_mensagem_do_grupo(c, msg, enviar=falas)


async def _apagar(
    c: AsyncConnection[dict[str, Any]], grupo: _Grupo, evolution_message_id: str
) -> ResultadoDaPorta:
    grupo.relogio += timedelta(seconds=30)
    return await processar_delecao_do_grupo(
        c,
        DelecaoNoGrupo(
            grupo_jid=grupo.jid,
            evolution_message_id=evolution_message_id,
            autor_jid="5521966666666@s.whatsapp.net",
            ocorrida_em=grupo.relogio,
        ),
    )


async def _postar_comprovante(
    c: AsyncConnection[dict[str, Any]],
    grupo: _Grupo,
    leitura: LeituraDoComprovante,
    *,
    falas: _Falas,
    depois: timedelta = timedelta(minutes=20),
    conteudo: bytes = b"\xff\xd8\xff\xe0jpeg-do-export",
) -> ResultadoDaPorta:
    """A modelo posta a foto do comprovante (mensagem `imagem`, texto vazio).

    `conteudo` e o que o dedup por foto enxerga (sha256 dos bytes). O default e a mesma imagem em
    toda postagem porque a maioria dos testes olha OUTRA coisa e so precisa de bytes validos —
    quem fala sobre reenvio passa (ou nao passa) o conteudo de proposito.
    """
    grupo.relogio += depois
    msg = MensagemDoGrupo(
        grupo_jid=grupo.jid,
        texto="",
        tipo="imagem",
        imagem=ImagemDoGrupo(conteudo, mimetype="image/jpeg"),
        evolution_message_id=f"3EB0{uuid4().hex[:12]}",
        autor_nome="Yasmin",
        autor_jid="5571988887777@s.whatsapp.net",
        recebida_em=grupo.relogio,
    )
    return await processar_mensagem_do_grupo(c, msg, enviar=falas, ler_comprovante=_Olho(leitura))


async def _vender(
    c: AsyncConnection[dict[str, Any]],
    grupo: _Grupo,
    *,
    cliente: str,
    valor: str,
    falas: _Falas,
) -> UUID:
    """Um anuncio de venda em pix — a fila que a cobranca NUNCA pode abater."""
    lancou = await _dizer(
        c,
        grupo,
        ANUNCIO.format(cliente=cliente, apelido=grupo.apelido, valor=valor),
        falas=falas,
        depois=timedelta(hours=2),
    )
    (venda_id,) = lancou.vendas
    pago = await _dizer(c, grupo, "Pix", falas=falas, depois=timedelta(minutes=5))
    assert pago.pagamentos == (venda_id,)
    return venda_id


def _comprovante(
    valor: str, *, dia: date = DIA_13_08, chave: str = CHAVE_3RJ
) -> LeituraDoComprovante:
    return LeituraDoComprovante(
        e_comprovante=True,
        legivel=True,
        valor=Decimal(valor),
        data=dia,
        pagador="YASMIN NASCIMENTO DE ALBUQUERQUE",
        chave_destino=chave,
        titular_destino="3RJ PRODUCAO E SERVICOS ADMINISTRATIVOS",
    )


async def _cadastro_do_grupo(c: AsyncConnection[dict[str, Any]], grupo: _Grupo) -> GrupoFinanceiro:
    """O vinculo como o modulo o le — a rotina da manha recebe o cadastro, nao o helper do teste."""
    cadastro = await buscar_grupo_por_jid(c, grupo.jid)
    assert cadastro is not None
    return cadastro


async def _cobrancas(c: AsyncConnection[dict[str, Any]], modelo_id: UUID) -> list[dict[str, Any]]:
    cur = await c.execute(
        """
        SELECT id, descricao, valor, data, comprovante_id, quitada_em, anulada_em
          FROM barravips.cobrancas_da_agencia
         WHERE modelo_id = %s
         ORDER BY created_at
        """,
        (modelo_id,),
    )
    return list(await cur.fetchall())


async def _vendas(c: AsyncConnection[dict[str, Any]], modelo_id: UUID) -> list[dict[str, Any]]:
    cur = await c.execute(
        """
        SELECT id, valor, comprovante_id
          FROM barravips.vendas_registradas
         WHERE modelo_id = %s AND anulada_em IS NULL
         ORDER BY created_at
        """,
        (modelo_id,),
    )
    return list(await cur.fetchall())


async def _comprovantes(
    c: AsyncConnection[dict[str, Any]], modelo_id: UUID
) -> list[dict[str, Any]]:
    cur = await c.execute(
        """
        SELECT cp.classificacao, cp.valor, cp.valor_abatido, cp.chave_conhecida
          FROM barravips.comprovantes_do_grupo cp
          JOIN barravips.grupos_financeiros g ON g.id = cp.grupo_id
         WHERE g.modelo_id = %s
         ORDER BY cp.created_at
        """,
        (modelo_id,),
    )
    return list(await cur.fetchall())


# --- 1. o gesto de 13/08: a cobranca vira debito, nao receita ------------------------------------


async def test_cobranca_da_3rj_vira_debito_com_recibo(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """A mensagem do gestor vira Cobranca da agencia, com a rubrica na grafia dele e o recibo."""
    grupo = await _montar_grupo(conn)
    falas = _Falas()

    resultado = await _dizer(conn, grupo, COBRANCA, falas=falas)

    assert resultado.motivo == "cobranca_registrada"
    assert len(resultado.cobrancas) == 1
    (cobranca,) = await _cobrancas(conn, grupo.modelo_id)
    assert cobranca["valor"] == Decimal("385.80")
    assert cobranca["data"] == DIA_13_08
    # A descricao guarda a rubrica SEM a cifra e sem a instrucao que vem depois dela ("envia para
    # o site…" e recado a modelo, nao identidade da divida).
    assert cobranca["descricao"] == "3RJ Suporte/Anúncio: 3 DIAS"
    assert (cobranca["quitada_em"], cobranca["anulada_em"]) == (None, None)

    assert falas.ultima is not None
    assert falas.ultima.startswith("🧾 Registrei a cobrança: 3RJ Suporte/Anúncio: 3 DIAS · ")
    assert "R$ 385,80" in falas.ultima and "13/08" in falas.ultima


async def test_cobranca_nao_e_venda_nem_receita(conn: AsyncConnection[dict[str, Any]]) -> None:
    """Debito da modelo nao pode encostar em `vendas_registradas` — e de la que sai a receita.

    Emula-la como "venda negativa" poluiria as tres colunas do Fechamento e a receita do Modulo
    Financeiro (ADR-0043 + a migration do ticket): sao dois eixos que nunca se cruzam.
    """
    grupo = await _montar_grupo(conn)
    falas = _Falas()

    await _dizer(conn, grupo, COBRANCA, falas=falas)

    assert await _vendas(conn, grupo.modelo_id) == []


@pytest.mark.parametrize(
    "texto",
    [
        "Envia para o site e envia o comprovante",  # rubrica conhecida, cifra nenhuma
        "*3RJ Suporte/Anúncio:*\n3 DIAS",  # a rubrica sozinha
        "Ficou 385,80 com você",  # numero sem "R$" e sem rubrica
        "Yasmin confere por favor \n\n600 pix \n600 pix",  # conferencia de fechamento
    ],
)
async def test_allowlist_fechada_nao_inventa_divida(
    conn: AsyncConnection[dict[str, Any]], texto: str
) -> None:
    """Rubrica E cifra com "R$", as duas na mesma mensagem — senao e silencio.

    Cada metade sozinha e comum no grupo. Sem a allowlist fechada, qualquer frase com numero
    viraria divida no nome da modelo, e divida inventada e coisa que ninguem revisa depois.
    """
    grupo = await _montar_grupo(conn)
    falas = _Falas()

    resultado = await _dizer(conn, grupo, texto, falas=falas)

    assert resultado.motivo != "cobranca_registrada"
    assert resultado.cobrancas == ()
    assert await _cobrancas(conn, grupo.modelo_id) == []


async def test_anuncio_de_venda_vence_a_cobranca(conn: AsyncConnection[dict[str, Any]]) -> None:
    """Mensagem com a gramatica do anuncio e VENDA, mesmo falando em site/anuncio.

    A cobranca so e consultada depois de o anuncio ser descartado. Invertida a ordem, o anuncio do
    dia em que a gestora escrevesse "anuncio" viraria debito da modelo — receita virando divida.
    """
    grupo = await _montar_grupo(conn)
    falas = _Falas()

    resultado = await _dizer(
        conn,
        grupo,
        f"Atendimento no nosso local \nCliente Igor \nPerfil {grupo.apelido} \nR$ 700 1h \n"
        "veio pelo anuncio do site",
        falas=falas,
    )

    assert len(resultado.vendas) == 1
    assert await _cobrancas(conn, grupo.modelo_id) == []


# --- 2. dedup e delecao: os gestos de correcao do grupo ------------------------------------------


async def test_repost_da_mesma_cobranca_nao_duplica_o_debito(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Mesmo debito postado de novo (ou no outro grupo da modelo) nao vira segunda divida."""
    grupo = await _montar_grupo(conn)
    falas = _Falas()

    await _dizer(conn, grupo, COBRANCA, falas=falas)
    repost = await _dizer(conn, grupo, COBRANCA, falas=falas, depois=timedelta(minutes=3))

    assert repost.motivo == "cobranca_duplicada"
    assert repost.cobrancas == ()
    assert len(await _cobrancas(conn, grupo.modelo_id)) == 1
    assert falas.ultima is not None
    assert falas.ultima.startswith("♻️ Essa cobrança já estava registrada: ")


async def test_apagar_a_mensagem_anula_a_cobranca_e_o_repost_volta_a_valer(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Apagar-e-repostar e como o grupo corrige: a cobranca apagada para de cobrar e solta a chave."""
    grupo = await _montar_grupo(conn)
    falas = _Falas()
    registrou = await _dizer(
        conn, grupo, COBRANCA, falas=falas, evolution_message_id="3EB0COBRANCA"
    )
    (cobranca_id,) = registrou.cobrancas

    anulou = await _apagar(conn, grupo, "3EB0COBRANCA")

    assert anulou.motivo == "cobranca_anulada"
    assert anulou.cobrancas_anuladas == (cobranca_id,)
    (anulada,) = await _cobrancas(conn, grupo.modelo_id)
    assert anulada["anulada_em"] is not None
    # O agente NAO fala na delecao (mesmo contrato do ticket 05): quem apagou estava olhando.
    assert falas.ultima is not None and falas.ultima.startswith("🧾")

    # E o repost volta a registrar: a linha anulada nao segura mais a chave de conteudo.
    de_novo = await _dizer(conn, grupo, COBRANCA, falas=falas)
    assert de_novo.motivo == "cobranca_registrada"
    vivas = [c for c in await _cobrancas(conn, grupo.modelo_id) if c["anulada_em"] is None]
    assert len(vivas) == 1


async def test_apagar_depois_de_paga_nao_desfaz_o_pagamento(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Quitacao tem PROVA amarrada: apagar a mensagem nao pode desfazer um Pix que aconteceu."""
    grupo = await _montar_grupo(conn)
    falas = _Falas()
    await _dizer(conn, grupo, COBRANCA, falas=falas, evolution_message_id="3EB0COBRANCA")
    quitou = await _postar_comprovante(conn, grupo, _comprovante("385.80"), falas=falas)
    assert len(quitou.cobrancas_quitadas) == 1

    anulou = await _apagar(conn, grupo, "3EB0COBRANCA")

    assert anulou.cobrancas_anuladas == ()
    assert anulou.motivo == "delecao_sem_venda"
    (cobranca,) = await _cobrancas(conn, grupo.modelo_id)
    assert cobranca["anulada_em"] is None
    assert cobranca["quitada_em"] is not None
    assert cobranca["comprovante_id"] == quitou.comprovante_id


# --- 3. o comprovante que paga a cobranca (e nenhuma venda) -------------------------------------


async def test_comprovante_quita_a_cobranca_e_nao_abate_venda_nenhuma(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """O R$ 385,80 de 13/08: quita a divida e deixa a fila de vendas EXATAMENTE como estava.

    A ultima frase da confirmacao ("Nenhuma venda foi abatida") e o ponto do ticket: sem ela, quem
    confere de cabeca continua descontando esse dinheiro do que a modelo ainda deve comprovar.
    """
    grupo = await _montar_grupo(conn)
    falas = _Falas()
    venda_id = await _vender(conn, grupo, cliente="Ramon", valor="600", falas=falas)
    registrou = await _dizer(conn, grupo, COBRANCA, falas=falas)
    (cobranca_id,) = registrou.cobrancas

    pagou = await _postar_comprovante(conn, grupo, _comprovante("385.80"), falas=falas)

    assert pagou.motivo == "comprovante_de_cobranca"
    assert pagou.cobrancas_quitadas == (cobranca_id,)
    assert pagou.abatidas == ()  # nenhuma venda tocada
    (venda,) = await _vendas(conn, grupo.modelo_id)
    assert venda["id"] == venda_id and venda["comprovante_id"] is None

    (comprovante,) = await _comprovantes(conn, grupo.modelo_id)
    assert comprovante["classificacao"] == "cobranca"
    assert comprovante["valor_abatido"] == Decimal("385.80")

    assert falas.ultima is not None
    assert falas.ultima.startswith(
        "✅ Comprovante conferido: R$ 385,80 · 13/08 — quitei a cobrança"
    )
    assert falas.ultima.endswith("Nenhuma venda foi abatida.")


async def test_a_foto_da_semana_passada_nao_quita_a_cobranca_desta_semana(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """A renovacao semanal do portal: mesma descricao, mesmo valor, semana seguinte.

    Este e o pior caso do modulo porque nada nele parece errado: a cobranca de 20/08 e legitima, a
    foto e um comprovante de verdade, e o valor bate. So a DATA da transferencia denuncia — e ela
    esta dentro da imagem, nao na conferencia. Sem o dedup por foto neste eixo (medido em 16/08
    pelo replay `exports/renovacao_da_cobranca`), a mesma prova quitava as duas dividas e o
    debito da modelo com a agencia sumia do extrato com `valor_abatido` cheio nas duas linhas.
    """
    grupo = await _montar_grupo(conn)
    falas = _Falas()
    await _dizer(conn, grupo, COBRANCA, falas=falas)
    await _postar_comprovante(conn, grupo, _comprovante("385.80"), falas=falas)

    # Uma semana depois: cobranca NOVA, do mesmo valor — e a foto da semana passada de novo.
    renovou = await _dizer(conn, grupo, COBRANCA, falas=falas, depois=timedelta(days=7))
    (segunda_id,) = renovou.cobrancas
    reenviou = await _postar_comprovante(
        conn, grupo, _comprovante("385.80"), falas=falas, depois=timedelta(hours=1)
    )

    assert reenviou.motivo == "comprovante_duplicado"
    assert reenviou.cobrancas_quitadas == ()
    assert len(await _comprovantes(conn, grupo.modelo_id)) == 1
    abertas = await _cobrancas(conn, grupo.modelo_id)
    assert [c["id"] for c in abertas if c["quitada_em"] is None] == [segunda_id]

    # E ela precisa OUVIR que a foto ja tinha sido contada: em silencio, a modelo manda uma
    # terceira vez e a divida continua aberta sem ninguem entender por que.
    assert falas.ultima is not None
    assert falas.ultima.startswith("♻️")


async def test_duas_fotos_diferentes_quitam_as_duas_cobrancas(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """O contraponto obrigatorio do teste acima: pagar duas semanas continua funcionando.

    O dedup e por CONTEUDO da imagem, nao por valor — duas transferencias iguais, com prints
    diferentes, sao dois pagamentos. Sem esta afirmacao ao lado, a proxima pessoa "conserta" o
    dedup comparando valor+data e passa a recusar o pagamento legitimo da semana seguinte.
    """
    grupo = await _montar_grupo(conn)
    falas = _Falas()
    await _dizer(conn, grupo, COBRANCA, falas=falas)
    await _postar_comprovante(conn, grupo, _comprovante("385.80"), falas=falas)

    await _dizer(conn, grupo, COBRANCA, falas=falas, depois=timedelta(days=7))
    pagou = await _postar_comprovante(
        conn,
        grupo,
        _comprovante("385.80", dia=DIA_13_08 + timedelta(days=7)),
        falas=falas,
        depois=timedelta(hours=1),
        conteudo=b"\xff\xd8\xff\xe0print-da-semana-seguinte",
    )

    assert pagou.motivo == "comprovante_de_cobranca"
    assert len(pagou.cobrancas_quitadas) == 1
    assert all(c["quitada_em"] is not None for c in await _cobrancas(conn, grupo.modelo_id))


async def test_pagamento_da_cobranca_nao_leva_aviso_de_chave_fora_da_lista(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """O destino de um pagamento de cobranca e a AGENCIA — fora da lista da casa por definicao.

    Repetir o ⚠️ a cada cobranca paga treinaria o grupo a ignorar o alarme que existe para o Pix de
    fechamento (user story 11). A flag continua no banco, para o painel: o sinal nao some, muda de
    lugar.
    """
    grupo = await _montar_grupo(conn)
    falas = _Falas()
    await _dizer(conn, grupo, COBRANCA, falas=falas)

    await _postar_comprovante(conn, grupo, _comprovante("385.80"), falas=falas)

    assert falas.ultima is not None
    assert "⚠️" not in falas.ultima
    assert "fora da lista" not in falas.ultima
    (comprovante,) = await _comprovantes(conn, grupo.modelo_id)
    assert comprovante["chave_conhecida"] is False  # o dado nao foi perdido


async def test_comprovante_que_serviria_para_os_dois_eixos_fica_retido_com_pergunta(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Mesmo valor na cobranca aberta e na fila de vendas: o agente PERGUNTA, nao escolhe.

    Chutar aqui moveria dinheiro entre dois eixos que nunca mais se cruzam — a venda "comprovada"
    por engano sai da fila e a cobranca segue cobrada, e nenhum dos dois erros aparece para
    ninguem.
    """
    grupo = await _montar_grupo(conn)
    falas = _Falas()
    venda_id = await _vender(conn, grupo, cliente="Ramon", valor="385,80", falas=falas)
    await _dizer(conn, grupo, COBRANCA, falas=falas)

    retido = await _postar_comprovante(conn, grupo, _comprovante("385.80"), falas=falas)

    assert retido.motivo == "comprovante_nao_classificado"
    assert retido.cobrancas_quitadas == () and retido.abatidas == ()
    assert retido.comprovante_id is not None  # existe: e a prova de que dinheiro saiu

    (cobranca,) = await _cobrancas(conn, grupo.modelo_id)
    assert cobranca["quitada_em"] is None
    (venda,) = await _vendas(conn, grupo.modelo_id)
    assert venda["id"] == venda_id and venda["comprovante_id"] is None

    assert falas.ultima is not None
    # A pergunta NOMEIA a candidata: "é de quê?" sobre um valor solto nao se responde.
    assert falas.ultima.startswith("❓ Recebi um comprovante de R$ 385,80 · 13/08 — é o pagamento")
    assert "3RJ Suporte/Anúncio: 3 DIAS" in falas.ultima


async def test_comprovante_de_outro_valor_segue_abatendo_vendas(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Cobranca aberta nao atrapalha o fechamento: casamento e por valor EXATO."""
    grupo = await _montar_grupo(conn)
    falas = _Falas()
    venda_id = await _vender(conn, grupo, cliente="Ramon", valor="600", falas=falas)
    await _dizer(conn, grupo, COBRANCA, falas=falas)

    fechou = await _postar_comprovante(
        conn, grupo, _comprovante("600.00", chave=CHAVE_DA_CASA), falas=falas
    )

    assert fechou.motivo == "comprovante_conciliado"
    assert fechou.abatidas == (venda_id,)
    assert fechou.cobrancas_quitadas == ()
    (cobranca,) = await _cobrancas(conn, grupo.modelo_id)
    assert cobranca["quitada_em"] is None  # a divida continua la, cobravel


# --- 4. o extrato: a coluna de debito, e a divergencia que deixa de existir ----------------------


async def test_extrato_mostra_a_cobranca_aberta_como_debito(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """A divida entra como linha de DEBITO, fora das quatro colunas — e nao muda nenhuma delas."""
    grupo = await _montar_grupo(conn)
    falas = _Falas()
    await _vender(conn, grupo, cliente="Ramon", valor="600", falas=falas)
    await _dizer(conn, grupo, COBRANCA, falas=falas)

    pediu = await _dizer(conn, grupo, "fechamento", falas=falas)

    extrato = pediu.extrato
    assert extrato is not None
    assert extrato.vendido == Decimal("600.00")  # a cobranca NAO entra no vendido
    assert extrato.debito == Decimal("385.80")
    assert [c.valor for c in extrato.cobrancas] == [Decimal("385.80")]
    assert falas.ultima is not None
    assert "Cobrança da agência: R$ 385,80 (3RJ Suporte/Anúncio: 3 DIAS — não paga)" in falas.ultima


async def test_rotina_da_manha_cobra_a_agencia_ate_o_comprovante_chegar(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """E o "nao precisar ficar lembrando a modelo" da user story 10 — na mensagem consolidada.

    A linha da agencia entra na MESMA fala das outras pendencias (uma por dia), e por ultimo: as
    de cima sao sobre o dinheiro que ela recebeu, esta e sobre o que ela deve.
    """
    grupo = await _montar_grupo(conn)
    falas = _Falas()
    await _vender(conn, grupo, cliente="Ramon", valor="600", falas=falas)
    await _dizer(conn, grupo, COBRANCA, falas=falas)
    ditas_antes = len(falas.enviadas)

    rotina = await cobrar_pendencias_do_grupo(
        conn, await _cadastro_do_grupo(conn, grupo), agora=MANHA_DE_14_08, enviar=falas
    )

    assert rotina.status == "cobrou"
    assert len(falas.enviadas) == ditas_antes + 1, "a cobranca da manha continua sendo UMA mensagem"
    fala = falas.ultima
    assert fala is not None
    assert (
        "💸 Falta pagar a agência: R$ 385,80 (3RJ Suporte/Anúncio: 3 DIAS) — "
        "manda o comprovante quando pagar." in fala
    )
    assert "📸 Falta o comprovante de R$ 600,00 (1 venda em pix)." in fala
    # O debito nao entra no "em aberto", que e sobre a receita: sao dois eixos.
    assert "📊 Em aberto: R$ 600,00 de R$ 600,00 vendidos" in fala


async def test_rotina_da_manha_para_de_cobrar_a_agencia_depois_do_pagamento(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Paga a cobranca e a linha da agencia SOME da manha seguinte — ninguem lembra a modelo de
    uma divida que ela ja quitou.

    A rotina ainda fala (houve movimento no grupo: o comprovante), e e justamente por isso que o
    teste olha o TEXTO: o que tem que sumir e a cobranca, nao a mensagem.
    """
    grupo = await _montar_grupo(conn)
    falas = _Falas()
    await _vender(conn, grupo, cliente="Ramon", valor="600", falas=falas)
    await _dizer(conn, grupo, COBRANCA, falas=falas)
    await _postar_comprovante(conn, grupo, _comprovante("385.80"), falas=falas)

    rotina = await cobrar_pendencias_do_grupo(
        conn, await _cadastro_do_grupo(conn, grupo), agora=MANHA_DE_14_08, enviar=falas
    )

    fala = rotina.fala or ""
    assert "Falta pagar a agência" not in fala and "💸" not in fala
    # E o que continua aberto continua cobrado: a venda em pix segue sem comprovante.
    assert "📸 Falta o comprovante de R$ 600,00 (1 venda em pix)." in fala


async def test_cobranca_paga_some_do_extrato_e_o_pix_deixa_de_divergir(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """O par cobranca+comprovante e o que EXPLICA o R$ 385,80 que antes ficava sem resposta.

    Ate o ticket 08 esse Pix aparecia como `comprovante_sem_par` para sempre: o extrato perguntava
    sobre o unico dinheiro cujo destino a operacao ja conhecia.
    """
    grupo = await _montar_grupo(conn)
    falas = _Falas()
    await _vender(conn, grupo, cliente="Ramon", valor="600", falas=falas)
    await _dizer(conn, grupo, COBRANCA, falas=falas)
    await _postar_comprovante(conn, grupo, _comprovante("385.80"), falas=falas)

    extrato = await fechamento_da_modelo(conn, grupo.modelo_id)

    assert extrato.cobrancas == () and extrato.debito == Decimal("0.00")
    assert extrato.divergencias == ()
    assert extrato.vendido == Decimal("600.00")
    assert extrato.a_comprovar == Decimal("600.00")  # a venda em pix continua aberta
