"""ADR-0049 / ticket 03 — no Grupo financeiro, o papel diz de QUEM e o destino do comprovante.

`chave_e_conhecida(chave) -> bool` respondia "esta na lista da casa". Fora da lista cabiam duas
coisas opostas: a chave da PROPRIA modelo (o cliente pagou direto a ela — dinheiro que a casa
nunca recebeu) e a chave de um terceiro qualquer. O agente disparava o MESMO ⚠️ nos dois, e — pior
— com uma venda em pix aberta na fila ele abatia, dando por comprovado dinheiro que nao entrou.

Ate aqui a unica forma de o agente saber que a chave era dela era o proprio grupo ter ensinado
(`dados_cadastrais`, ticket 12). Agora o cadastro tipado (ticket 02) tambem responde, com o papel
`modelo` + o dono — e e por isso que estes testes NUNCA cadastram a chave por `dados_cadastrais`.

`needs_db` com `TEST_DATABASE_URL` + ROLLBACK sempre.
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

from barra.agente_financeiro import ResultadoDaPorta, processar_mensagem_do_grupo
from barra.dominio.grupo_financeiro.comprovante import LeituraDoComprovante, normalizar_chave
from barra.dominio.grupo_financeiro.modelos import ImagemDoGrupo, MensagemDoGrupo

pytestmark = pytest.mark.needs_db

CHAVE_DA_CASA = "casa-elite@pix.example"
TITULAR_DA_CASA = "Elite Servicos Ltda"
CHAVE_DELA = "cpf-dela@pix.example"
CHAVE_DE_TERCEIRO = "agiota@pix.example"

ANUNCIO = "Atendimento no nosso local \nCliente Ramon \nPerfil {apelido} \n600 1h"
NOITE_DE_12_08 = datetime(2026, 8, 13, 1, 0, tzinfo=UTC)
JPEG = b"\xff\xd8\xff" + b"\x00" * 64


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


class _Falas:
    def __init__(self) -> None:
        self.enviadas: list[str] = []

    async def __call__(self, texto: str, *, citar: str | None = None) -> None:
        self.enviadas.append(texto)

    @property
    def ultima(self) -> str:
        return self.enviadas[-1] if self.enviadas else ""


class _Olho:
    def __init__(self, leitura: LeituraDoComprovante) -> None:
        self._leitura = leitura

    async def __call__(self, imagem: ImagemDoGrupo) -> LeituraDoComprovante:
        return self._leitura


class _Grupo:
    def __init__(self, modelo_id: UUID, jid: str, apelido: str) -> None:
        self.modelo_id = modelo_id
        self.jid = jid
        self.apelido = apelido
        self.relogio = NOITE_DE_12_08


async def _montar_grupo(c: AsyncConnection[dict[str, Any]]) -> _Grupo:
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
            Decimal("600"),
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
        "INSERT INTO barravips.grupos_financeiros (id, modelo_id, jid, nome) VALUES (%s,%s,%s,%s)",
        (uuid4(), modelo_id, jid, "Modelo Yasmin Ruiva/financeiro"),
    )
    await c.execute("DELETE FROM barravips.chaves_pix_conhecidas")
    return _Grupo(modelo_id, jid, apelido)


async def _cadastrar(
    c: AsyncConnection[dict[str, Any]],
    *,
    chave: str,
    papel: str,
    modelo_id: UUID | None = None,
    titular: str | None = None,
) -> None:
    await c.execute(
        """
        INSERT INTO barravips.chaves_pix_conhecidas
            (chave, chave_normalizada, papel, modelo_id, titular)
        VALUES (%s, %s, %s::barravips.papel_da_chave_enum, %s, %s)
        """,
        (chave, normalizar_chave(chave), papel, modelo_id, titular),
    )


async def _dizer(
    c: AsyncConnection[dict[str, Any]], grupo: _Grupo, texto: str, *, falas: _Falas
) -> ResultadoDaPorta:
    grupo.relogio += timedelta(minutes=5)
    msg = MensagemDoGrupo(
        grupo_jid=grupo.jid,
        texto=texto,
        recebida_em=grupo.relogio,
        evolution_message_id=f"3EB0{uuid4().hex[:12]}",
        autor_nome="Dani",
        autor_jid="5521999999999@s.whatsapp.net",
    )
    return await processar_mensagem_do_grupo(c, msg, enviar=falas)


async def _uma_venda_em_pix(
    c: AsyncConnection[dict[str, Any]], grupo: _Grupo, *, falas: _Falas
) -> UUID:
    lancou = await _dizer(c, grupo, ANUNCIO.format(apelido=grupo.apelido), falas=falas)
    (venda_id,) = lancou.vendas
    pago = await _dizer(c, grupo, "Pix", falas=falas)
    assert pago.pagamentos == (venda_id,)
    return venda_id


async def _postar_comprovante(
    c: AsyncConnection[dict[str, Any]],
    grupo: _Grupo,
    leitura: LeituraDoComprovante,
    *,
    falas: _Falas,
) -> ResultadoDaPorta:
    grupo.relogio += timedelta(minutes=5)
    msg = MensagemDoGrupo(
        grupo_jid=grupo.jid,
        texto="",
        tipo="imagem",
        imagem=ImagemDoGrupo(JPEG, mimetype="image/jpeg"),
        recebida_em=grupo.relogio,
        evolution_message_id=f"3EB0{uuid4().hex[:12]}",
        autor_nome="Yasmin",
        autor_jid="5571988887777@s.whatsapp.net",
    )
    return await processar_mensagem_do_grupo(c, msg, enviar=falas, ler_comprovante=_Olho(leitura))


def _leitura(
    *, chave: str | None, pagador: str | None, titular: str | None = None
) -> LeituraDoComprovante:
    return LeituraDoComprovante(
        e_comprovante=True,
        legivel=True,
        valor=Decimal("600.00"),
        data=date(2026, 8, 12),
        pagador=pagador,
        chave_destino=chave,
        titular_destino=titular,
    )


async def _comprovante(c: AsyncConnection[dict[str, Any]], grupo: _Grupo) -> dict[str, Any]:
    cur = await c.execute(
        """
        SELECT co.classificacao::text AS classificacao, co.chave_conhecida, co.valor_abatido
          FROM barravips.comprovantes_do_grupo co
          JOIN barravips.grupos_financeiros g ON g.id = co.grupo_id
         WHERE g.jid = %s
        """,
        (grupo.jid,),
    )
    linha = await cur.fetchone()
    assert linha is not None
    return dict(linha)


# --- os testes ----------------------------------------------------------------------------------


async def test_a_chave_da_casa_continua_fechando_a_venda_calada(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """A linha de base: `papel='casa'` e o que o booleano chamava de conhecida. Abate e nao avisa."""
    falas = _Falas()
    grupo = await _montar_grupo(conn)
    await _cadastrar(conn, chave=CHAVE_DA_CASA, papel="casa", titular=TITULAR_DA_CASA)
    await _uma_venda_em_pix(conn, grupo, falas=falas)

    await _postar_comprovante(
        conn, grupo, _leitura(chave=CHAVE_DA_CASA, pagador="YASMIN N DE ALBUQUERQUE"), falas=falas
    )

    linha = await _comprovante(conn, grupo)
    assert linha["classificacao"] == "fechamento"
    assert linha["chave_conhecida"] is True
    assert linha["valor_abatido"] == Decimal("600.00")
    assert "⚠️" not in falas.ultima


async def test_o_papel_modelo_no_cadastro_impede_o_abate_do_dinheiro_que_nao_entrou(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """O cliente pagou DIRETO na conta dela. Sem o papel, "fora da lista da casa" com uma venda em
    pix aberta virava `fechamento`: o agente dava por comprovado dinheiro que a casa nao recebeu.

    A chave dela entra SO pelo cadastro tipado (papel `modelo` + `modelo_id`) — nada foi ensinado
    por `dados_cadastrais`. E o registro respondendo "de quem e" sozinho.
    """
    falas = _Falas()
    grupo = await _montar_grupo(conn)
    await _cadastrar(conn, chave=CHAVE_DA_CASA, papel="casa", titular=TITULAR_DA_CASA)
    await _cadastrar(conn, chave=CHAVE_DELA, papel="modelo", modelo_id=grupo.modelo_id)
    venda_id = await _uma_venda_em_pix(conn, grupo, falas=falas)

    await _postar_comprovante(
        conn, grupo, _leitura(chave=CHAVE_DELA, pagador="Vanessa Melo De Oliveira"), falas=falas
    )

    linha = await _comprovante(conn, grupo)
    assert linha["classificacao"] == "entrada_da_modelo"
    assert linha["valor_abatido"] == Decimal("0.00")
    assert "📥" in falas.ultima
    cur = await conn.execute(
        "SELECT comprovante_id FROM barravips.vendas_registradas WHERE id = %s", (venda_id,)
    )
    venda = await cur.fetchone()
    assert venda is not None
    assert venda["comprovante_id"] is None  # a venda NAO foi dada por comprovada


async def test_chave_de_outra_modelo_nao_conta_como_dela(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """`e_da_modelo` e por PESSOA. A chave da Bianca no cadastro nao explica o comprovante da
    Yasmin — vira o aviso generico, que e a resposta honesta ("conheco, e nao e o esperado")."""
    falas = _Falas()
    grupo = await _montar_grupo(conn)
    outra = await _montar_grupo(conn)
    await _cadastrar(conn, chave=CHAVE_DA_CASA, papel="casa", titular=TITULAR_DA_CASA)
    await _cadastrar(conn, chave=CHAVE_DELA, papel="modelo", modelo_id=outra.modelo_id)
    await _uma_venda_em_pix(conn, grupo, falas=falas)

    await _postar_comprovante(
        conn, grupo, _leitura(chave=CHAVE_DELA, pagador="YASMIN N DE ALBUQUERQUE"), falas=falas
    )

    linha = await _comprovante(conn, grupo)
    assert linha["chave_conhecida"] is False
    assert "fora da lista da casa" in falas.ultima


async def test_chave_de_terceiro_cadastrada_nao_vira_chave_da_casa(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """O papel que o booleano nao tinha: cadastrada SIM, da casa NAO. Na lista plana, cadastrar o
    agiota do exemplo o teria promovido a destino de fechamento em silencio."""
    falas = _Falas()
    grupo = await _montar_grupo(conn)
    await _cadastrar(conn, chave=CHAVE_DE_TERCEIRO, papel="terceiro", titular="Erick de Melo")
    await _uma_venda_em_pix(conn, grupo, falas=falas)

    await _postar_comprovante(
        conn,
        grupo,
        _leitura(chave=CHAVE_DE_TERCEIRO, pagador="YASMIN N DE ALBUQUERQUE"),
        falas=falas,
    )

    linha = await _comprovante(conn, grupo)
    assert linha["chave_conhecida"] is False
    assert "fora da lista da casa" in falas.ultima


async def test_comprovante_sem_chave_lida_nao_vira_da_casa(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Closed-world na ponta que mais dói: o OCR nao achou o destino. Assumir a casa aqui, depois
    do ticket 04, fixaria o bolso da venda em `empresa` sem evidencia nenhuma."""
    falas = _Falas()
    grupo = await _montar_grupo(conn)
    await _cadastrar(conn, chave=CHAVE_DA_CASA, papel="casa", titular=TITULAR_DA_CASA)
    await _uma_venda_em_pix(conn, grupo, falas=falas)

    await _postar_comprovante(
        conn, grupo, _leitura(chave=None, pagador="YASMIN N DE ALBUQUERQUE"), falas=falas
    )

    linha = await _comprovante(conn, grupo)
    assert linha["chave_conhecida"] is False


async def test_cadastro_vazio_nao_quebra_o_grupo(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """O estado de producao em 20/08/2026: registro vazio. Tudo `desconhecida`, nada explode, o
    abate continua acontecendo (chave desconhecida sinaliza, NUNCA trava)."""
    falas = _Falas()
    grupo = await _montar_grupo(conn)
    await _uma_venda_em_pix(conn, grupo, falas=falas)

    await _postar_comprovante(
        conn, grupo, _leitura(chave=CHAVE_DA_CASA, pagador="YASMIN N DE ALBUQUERQUE"), falas=falas
    )

    linha = await _comprovante(conn, grupo)
    assert linha["classificacao"] == "fechamento"
    assert linha["chave_conhecida"] is False
    assert linha["valor_abatido"] == Decimal("600.00")
    assert "fora da lista da casa" in falas.ultima
