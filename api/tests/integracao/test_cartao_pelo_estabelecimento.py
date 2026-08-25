"""ADR-0049 §6 / ticket 06 — o registro de maquininhas e o print de cartao no banco.

O que so o banco prova, e por isso mora aqui:

* o registro de estabelecimentos tem as mesmas travas do de chaves — UNIQUE pela forma de
  comparacao (a mesma maquininha nao entra duas vezes com grafias diferentes) e papel x dono
  (papel `modelo` sem dona seria uma linha que nao explica nada);
* o print de cartao vira linha do MESMO `comprovantes_do_grupo`, com a forma de comparacao gravada
  pelo Python — e por isso "PagBank" e "PAG BANK" contam como UMA maquininha na fila, sem
  `unaccent` no Postgres;
* ⚠️ **o print de cartao nao abate venda em pix nem quita Cobranca da agencia** (criterio do
  ticket). Esta e a unica prova que vale, porque ela passa pela porta unica de verdade: o dinheiro
  do cartao nao saiu da conta da modelo, e dar uma transferencia por comprovada tira a venda da
  fila de cobranca pelo motivo errado.

`needs_db` com `TEST_DATABASE_URL` + ROLLBACK sempre.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from psycopg import AsyncConnection
from psycopg.errors import CheckViolation, UniqueViolation
from psycopg.rows import dict_row

from barra.agente_financeiro import ResultadoDaPorta, processar_mensagem_do_grupo
from barra.dominio.grupo_financeiro.comprovante import (
    LeituraDoComprovante,
    montar_pergunta_da_sugestao,
    sugestoes_de_estabelecimento,
)
from barra.dominio.grupo_financeiro.modelos import ImagemDoGrupo, MensagemDoGrupo
from barra.dominio.grupo_financeiro.repo import (
    criar_estabelecimento,
    estabelecimentos_vistos_em_comprovantes,
    listar_estabelecimentos,
    registrar_comprovante,
    registro_de_estabelecimentos,
)

pytestmark = pytest.mark.needs_db

MAQUININHA_DA_CASA = "Elite Servicos Ltda"
MAQUININHA_DELA = "PAGBANK * YASMIN"

ANUNCIO = "Atendimento no nosso local \nCliente Ramon \nPerfil {apelido} \n600 1h"
COBRANCA = "*3RJ Suporte/Anúncio:*\n3 DIAS | R$ 385,80\nEnvia para o site e envia o comprovante"
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


class _Olho:
    def __init__(self, leitura: LeituraDoComprovante) -> None:
        self._leitura = leitura

    async def __call__(self, imagem: ImagemDoGrupo) -> LeituraDoComprovante:
        return self._leitura


class _Grupo:
    def __init__(self, id_: UUID, modelo_id: UUID, jid: str, apelido: str) -> None:
        self.id = id_
        self.modelo_id = modelo_id
        self.jid = jid
        self.apelido = apelido
        self.relogio = NOITE_DE_12_08


async def _montar_grupo(c: AsyncConnection[dict[str, Any]]) -> _Grupo:
    modelo_id = uuid4()
    apelido = f"yasmin{uuid4().hex[:8]}"
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
    grupo_id = uuid4()
    jid = f"1203634{uuid4().hex[:12]}@g.us"
    await c.execute(
        "INSERT INTO barravips.grupos_financeiros (id, modelo_id, jid, nome) VALUES (%s,%s,%s,%s)",
        (grupo_id, modelo_id, jid, "Modelo Yasmin Ruiva/financeiro"),
    )
    await c.execute("DELETE FROM barravips.estabelecimentos_conhecidos")
    return _Grupo(grupo_id, modelo_id, jid, apelido)


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


async def _postar_print(
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


def _print_de_cartao(*, valor: str, estabelecimento: str | None) -> LeituraDoComprovante:
    """O que o OCR devolve para um cupom de maquininha: cartao SIM, transferencia NAO."""
    return LeituraDoComprovante(
        e_comprovante=False,
        legivel=True,
        valor=Decimal(valor),
        data=date(2026, 8, 12),
        e_de_cartao=True,
        estabelecimento=estabelecimento,
    )


async def _uma_mensagem(c: AsyncConnection[dict[str, Any]], grupo: _Grupo) -> UUID:
    """Uma linha em `grupo_financeiro_mensagens` — o comprovante e filho dela (FK + UNIQUE)."""
    mensagem_id = uuid4()
    await c.execute(
        """
        INSERT INTO barravips.grupo_financeiro_mensagens
            (id, grupo_id, chave_dedup, evolution_message_id, autor_jid, autor_nome, tipo,
             recebida_em)
        VALUES (%s, %s, %s, %s, %s, %s, 'imagem', %s)
        """,
        (
            mensagem_id,
            grupo.id,
            uuid4().hex,
            f"3EB0{uuid4().hex[:12]}",
            "5571988887777@s.whatsapp.net",
            "Yasmin",
            NOITE_DE_12_08,
        ),
    )
    return mensagem_id


# --- 1. o registro de maquininhas -----------------------------------------------------------------


async def test_a_maquininha_cadastrada_responde_de_quem_ela_e(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    grupo = await _montar_grupo(conn)
    await criar_estabelecimento(conn, nome=MAQUININHA_DA_CASA, papel="casa")
    await criar_estabelecimento(
        conn, nome=MAQUININHA_DELA, papel="modelo", modelo_id=grupo.modelo_id
    )

    registro = await registro_de_estabelecimentos(conn)

    por_nome = {e.nome: e for e in registro}
    assert por_nome[MAQUININHA_DA_CASA].papel == "casa"
    dela = por_nome[MAQUININHA_DELA]
    assert (dela.papel, dela.dono_id) == ("modelo", grupo.modelo_id)
    assert dela.dono_nome is not None and dela.dono_nome.startswith("Yasmin")


async def test_a_mesma_maquininha_com_outra_grafia_nao_entra_duas_vezes(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """O UNIQUE e sobre a forma de COMPARACAO. Sem ele o gestor cadastraria "PagBank" e "PAG BANK"
    como duas maquininhas e a fila continuaria pedindo a mesma classificacao."""
    await _montar_grupo(conn)
    await criar_estabelecimento(conn, nome="PagBank", papel="casa")

    with pytest.raises(UniqueViolation):
        await criar_estabelecimento(conn, nome="PAG BANK", papel="casa")


async def test_papel_modelo_sem_dona_e_recusado_pelo_banco(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """A mesma trava da chave: `modelo` sem `modelo_id` seria uma linha que diz "e dela" sem dizer
    de quem — e quem le teria que escolher em qual metade acreditar."""
    await _montar_grupo(conn)

    with pytest.raises(CheckViolation):
        await criar_estabelecimento(conn, nome=MAQUININHA_DELA, papel="modelo")


async def test_maquininha_inativa_some_da_tela_e_fica_no_registro(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Autoria nao e autorizacao (a mesma decisao do ticket 03): a maquininha devolvida continua
    explicando o print de tres semanas atras."""
    await _montar_grupo(conn)
    estabelecimento_id = await criar_estabelecimento(conn, nome=MAQUININHA_DA_CASA, papel="casa")
    await conn.execute(
        "UPDATE barravips.estabelecimentos_conhecidos SET ativo = false WHERE id = %s",
        (estabelecimento_id,),
    )

    assert await listar_estabelecimentos(conn) == []
    assert [e.nome for e in await listar_estabelecimentos(conn, incluir_inativos=True)] == [
        MAQUININHA_DA_CASA
    ]
    assert [e.nome for e in await registro_de_estabelecimentos(conn)] == [MAQUININHA_DA_CASA]


# --- 2. a fila de sugestoes, agrupada pelo que o Python normalizou --------------------------------


async def test_o_mesmo_estabelecimento_em_duas_grafias_conta_como_uma_maquininha(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """O agrupamento e por `estabelecimento_normalizado`, a coluna que o repositorio escreve — e e
    assim que a dobra de acento existe sem `unaccent` no Postgres."""
    grupo = await _montar_grupo(conn)
    for lido in ("PagBank", "PAG BANK", "pag-bank"):
        await registrar_comprovante(
            conn,
            grupo_id=grupo.id,
            mensagem_id=await _uma_mensagem(conn, grupo),
            classificacao="nao_classificado",
            valor=Decimal("600.00"),
            estabelecimento=lido,
        )

    vistas = await estabelecimentos_vistos_em_comprovantes(conn)

    assert len(vistas) == 1
    (vista,) = vistas
    assert vista.vezes == 3
    assert vista.valor_total == Decimal("1800.00")
    uma = vista.de_uma_modelo_so
    assert uma is not None and uma.modelo_id == grupo.modelo_id


async def test_maquininha_desconhecida_recorrente_vira_pergunta_e_cadastrar_a_tira_da_fila(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """A fila e DERIVADA, nao materializada: cadastrar e o proprio gesto que tira a linha dela —
    sem invalidacao e sem sugestao fantasma."""
    grupo = await _montar_grupo(conn)
    for _ in range(2):
        await registrar_comprovante(
            conn,
            grupo_id=grupo.id,
            mensagem_id=await _uma_mensagem(conn, grupo),
            classificacao="nao_classificado",
            valor=Decimal("600.00"),
            estabelecimento=MAQUININHA_DELA,
        )

    fila = sugestoes_de_estabelecimento(
        await estabelecimentos_vistos_em_comprovantes(conn),
        await registro_de_estabelecimentos(conn),
    )
    assert [v.chave for v in fila] == [MAQUININHA_DELA]
    pergunta = montar_pergunta_da_sugestao(fila[0])
    assert pergunta.startswith("Apareceu 2 vezes")
    assert "de quem é?" in pergunta

    await criar_estabelecimento(
        conn, nome=MAQUININHA_DELA, papel="modelo", modelo_id=grupo.modelo_id
    )

    assert (
        sugestoes_de_estabelecimento(
            await estabelecimentos_vistos_em_comprovantes(conn),
            await registro_de_estabelecimentos(conn),
        )
        == ()
    )


async def test_comprovante_de_transferencia_nao_entra_na_fila_das_maquininhas(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """As duas filas nao se misturam: a chave de destino nao e nome de estabelecimento."""
    grupo = await _montar_grupo(conn)
    for _ in range(3):
        await registrar_comprovante(
            conn,
            grupo_id=grupo.id,
            mensagem_id=await _uma_mensagem(conn, grupo),
            classificacao="fechamento",
            valor=Decimal("600.00"),
            chave_destino="casa@pix.example",
        )

    assert await estabelecimentos_vistos_em_comprovantes(conn) == ()


# --- 3. o criterio do ticket: cartao nao abate nem quita ------------------------------------------


async def test_print_de_cartao_nao_abate_venda_em_pix(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """A venda em pix continua aberta depois do print da maquininha — pelo caminho de producao.

    O cupom prova que o CLIENTE pagou no cartao; nenhum centavo saiu da conta da modelo. Se ele
    abatesse, a venda sairia da fila de cobranca pelo motivo errado e o Fechamento fecharia sem
    acusar nada.
    """
    falas = _Falas()
    grupo = await _montar_grupo(conn)
    await criar_estabelecimento(conn, nome=MAQUININHA_DA_CASA, papel="casa")
    lancou = await _dizer(conn, grupo, ANUNCIO.format(apelido=grupo.apelido), falas=falas)
    (venda_id,) = lancou.vendas
    await _dizer(conn, grupo, "Pix", falas=falas)
    faladas_antes = len(falas.enviadas)

    resultado = await _postar_print(
        conn,
        grupo,
        _print_de_cartao(valor="600.00", estabelecimento=MAQUININHA_DA_CASA),
        falas=falas,
    )

    assert resultado.abatidas == ()
    cur = await conn.execute(
        "SELECT comprovante_id FROM barravips.vendas_registradas WHERE id = %s", (venda_id,)
    )
    venda = await cur.fetchone()
    assert venda is not None
    assert venda["comprovante_id"] is None
    assert len(falas.enviadas) == faladas_antes  # o cartao ainda nao tem fala propria


async def test_print_de_cartao_nao_quita_cobranca_da_agencia(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Mesmo com o valor EXATO da cobranca aberta. Quitar uma divida com um cupom de cartao moveria
    dinheiro entre dois eixos que nunca se cruzam."""
    falas = _Falas()
    grupo = await _montar_grupo(conn)
    registrada = await _dizer(conn, grupo, COBRANCA, falas=falas)
    assert len(registrada.cobrancas) == 1

    await _postar_print(
        conn, grupo, _print_de_cartao(valor="385.80", estabelecimento=MAQUININHA_DELA), falas=falas
    )

    cur = await conn.execute(
        "SELECT quitada_em, comprovante_id FROM barravips.cobrancas_da_agencia WHERE modelo_id = %s",
        (grupo.modelo_id,),
    )
    cobranca = await cur.fetchone()
    assert cobranca is not None
    assert (cobranca["quitada_em"], cobranca["comprovante_id"]) == (None, None)
