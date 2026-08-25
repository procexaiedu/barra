"""ADR-0049 / ticket 03 — o registro tipado responde "de quem e", e o Pix de deslocamento obedece.

Duas metades, e elas sao a mesma funcao:

* `repo.registro_de_chaves` + `comprovante.papel_da_chave` respondem **de quem e** uma chave,
  lendo o cadastro tipado do ticket 02 (papel + dono), inclusive as INATIVAS;
* `workers/pix.py::carregar_chaves_da_operacao` responde **quem pode receber ESTE atendimento**,
  que e o papel filtrado por `ativo` e por dono.

O que este ticket ENCOLHEU: ate aqui a fonte era a lista PLANA (`chaves_pix_conhecidas` sem
papel), entao a chave de OUTRA modelo e a chave de um terceiro cadastrado autorizavam qualquer
deslocamento. Alargar a aceitacao nunca reprova nada — mas tambem nunca pega o Pix que foi para o
lugar errado, que e a metade do problema que o ADR existe para resolver.

`needs_db` com `TEST_DATABASE_URL` + ROLLBACK sempre.
"""

import os
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from barra.dominio.grupo_financeiro.comprovante import normalizar_chave, papel_da_chave
from barra.dominio.grupo_financeiro.repo import registro_de_chaves
from barra.workers.pix import carregar_chaves_da_operacao

pytestmark = pytest.mark.needs_db

CHAVE_DA_CASA = "casa-elite@pix.example"
TITULAR_DA_CASA = "Elite Servicos Ltda"
CHAVE_DO_TELEFONISTA = "+55 71 99984-0879"
CHAVE_DE_TERCEIRO = "agiota@pix.example"


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


# --- seeders ------------------------------------------------------------------------------------


async def _limpar_o_cadastro(c: AsyncConnection[dict[str, Any]]) -> None:
    """O registro so com o que este teste cadastra — o banco de teste pode ter a chave do seed."""
    await c.execute("DELETE FROM barravips.chaves_pix_conhecidas")


async def _uma_modelo(
    c: AsyncConnection[dict[str, Any]],
    *,
    chave_pix: str | None = None,
    titular_chave: str | None = None,
) -> UUID:
    modelo_id = uuid4()
    await c.execute(
        """
        INSERT INTO barravips.modelos
            (id, nome, idade, numero_whatsapp, valor_padrao, tipo_atendimento_aceito,
             chave_pix, titular_chave)
        VALUES (%s, %s, %s, %s, %s, %s::barravips.tipo_atendimento_enum[], %s, %s)
        """,
        (
            modelo_id,
            f"Modelo {uuid4().hex[:6]}",
            25,
            f"test-wpp-{uuid4().hex}",
            Decimal("500"),
            ["externo"],
            chave_pix,
            titular_chave,
        ),
    )
    return modelo_id


async def _um_telefonista(c: AsyncConnection[dict[str, Any]]) -> UUID:
    vendedor_id = uuid4()
    await c.execute(
        "INSERT INTO barravips.vendedores (id, nome) VALUES (%s, %s)",
        (vendedor_id, "Joao Pereira"),
    )
    return vendedor_id


async def _cadastrar(
    c: AsyncConnection[dict[str, Any]],
    *,
    chave: str,
    papel: str,
    modelo_id: UUID | None = None,
    vendedor_id: UUID | None = None,
    titular: str | None = None,
    ativo: bool = True,
) -> None:
    await c.execute(
        """
        INSERT INTO barravips.chaves_pix_conhecidas
            (chave, chave_normalizada, papel, modelo_id, vendedor_id, titular, ativo)
        VALUES (%s, %s, %s::barravips.papel_da_chave_enum, %s, %s, %s, %s)
        """,
        (chave, normalizar_chave(chave), papel, modelo_id, vendedor_id, titular, ativo),
    )


async def _um_atendimento(c: AsyncConnection[dict[str, Any]], modelo_id: UUID) -> UUID:
    cliente_id = uuid4()
    await c.execute(
        "INSERT INTO barravips.clientes (id, telefone, nome) VALUES (%s, %s, %s)",
        (cliente_id, f"test-tel-{uuid4().hex}", "Cliente Teste"),
    )
    conversa_id = uuid4()
    await c.execute(
        """
        INSERT INTO barravips.conversas (id, cliente_id, modelo_id, evolution_chat_id)
        VALUES (%s, %s, %s, %s)
        """,
        (conversa_id, cliente_id, modelo_id, f"test-chat-{uuid4().hex}"),
    )
    atendimento_id = uuid4()
    await c.execute(
        """
        INSERT INTO barravips.atendimentos
            (id, cliente_id, modelo_id, conversa_id, estado, tipo_atendimento, pix_status)
        VALUES (%s, %s, %s, %s, 'Aguardando_confirmacao', 'externo', 'aguardando')
        """,
        (atendimento_id, cliente_id, modelo_id, conversa_id),
    )
    return atendimento_id


# --- de quem e esta chave -----------------------------------------------------------------------


async def test_o_registro_responde_o_papel_e_o_dono(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Uma passada pelo cadastro tipado inteiro: os quatro papeis, com o dono resolvido."""
    await _limpar_o_cadastro(conn)
    yasmin = await _uma_modelo(conn)
    joao = await _um_telefonista(conn)
    await _cadastrar(conn, chave=CHAVE_DA_CASA, papel="casa", titular=TITULAR_DA_CASA)
    await _cadastrar(conn, chave="dela@pix.example", papel="modelo", modelo_id=yasmin)
    await _cadastrar(conn, chave=CHAVE_DO_TELEFONISTA, papel="telefonista", vendedor_id=joao)
    await _cadastrar(conn, chave=CHAVE_DE_TERCEIRO, papel="terceiro", titular="Erick de Melo")

    registro = await registro_de_chaves(conn)

    casa = papel_da_chave(CHAVE_DA_CASA, registro)
    assert casa.papel == "casa"
    assert casa.e_da_casa
    assert casa.dono_nome == TITULAR_DA_CASA

    dela = papel_da_chave("dela@pix.example", registro)
    assert dela.papel == "modelo"
    assert dela.dono_id == yasmin
    assert dela.e_da_modelo(yasmin)

    telefonista = papel_da_chave("+5571999840879", registro)  # a grafia do OCR, nao a do cadastro
    assert telefonista.papel == "telefonista"
    assert telefonista.dono_id == joao
    assert telefonista.dono_nome == "Joao Pereira"

    terceiro = papel_da_chave(CHAVE_DE_TERCEIRO, registro)
    assert terceiro.papel == "terceiro"
    assert terceiro.e_conhecida
    assert terceiro.e_da_casa is False


async def test_registro_traz_a_chave_inativa_com_o_dono(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Inativar nunca deletar: `registro_de_chaves` passa `incluir_inativas=True` de proposito, e
    e o que faz o comprovante de tres semanas atras continuar tendo explicacao."""
    await _limpar_o_cadastro(conn)
    yasmin = await _uma_modelo(conn)
    await _cadastrar(
        conn, chave="banco-antigo@pix.example", papel="modelo", modelo_id=yasmin, ativo=False
    )

    registro = await registro_de_chaves(conn)

    assert [c.ativo for c in registro] == [False]
    papel = papel_da_chave("banco-antigo@pix.example", registro)
    assert papel.papel == "modelo"
    assert papel.dono_id == yasmin


async def test_cadastro_vazio_nao_conhece_nada(conn: AsyncConnection[dict[str, Any]]) -> None:
    """O estado de producao em 20/08/2026. Tem que atravessar sem excecao."""
    await _limpar_o_cadastro(conn)
    registro = await registro_de_chaves(conn)
    assert registro == ()
    assert papel_da_chave(CHAVE_DA_CASA, registro).papel == "desconhecida"


# --- quem pode receber ESTE atendimento ---------------------------------------------------------


async def test_a_chave_de_outra_modelo_nao_autoriza_este_deslocamento(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """O que o ticket 03 ENCOLHEU. Com a lista plana, a chave da Bianca autorizava o deslocamento
    da Yasmin — a tabela nao sabia de quem era a chave. Agora o papel `modelo` so vale para o
    atendimento da dona dela; a da casa continua valendo para todos."""
    await _limpar_o_cadastro(conn)
    bianca = await _uma_modelo(conn)
    yasmin = await _uma_modelo(conn, chave_pix="dela@pix.example", titular_chave="Yasmin N A")
    await _cadastrar(conn, chave=CHAVE_DA_CASA, papel="casa", titular=TITULAR_DA_CASA)
    await _cadastrar(conn, chave="da-bianca@pix.example", papel="modelo", modelo_id=bianca)
    atendimento_id = await _um_atendimento(conn, yasmin)

    conhecidas = await carregar_chaves_da_operacao(conn, atendimento_id=atendimento_id)

    assert conhecidas.aceita_chave(CHAVE_DA_CASA)
    assert conhecidas.aceita_chave("dela@pix.example")  # a expectativa, de `modelos.chave_pix`
    assert conhecidas.aceita_chave("da-bianca@pix.example") is False


async def test_a_outra_chave_da_propria_modelo_autoriza(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Uma modelo tem VARIAS chaves (CPF, telefone, aleatoria — e ela troca de banco, ADR-0049 §2).
    A segunda chave dela recebe tao legitimamente quanto a que a IA entregou ao cliente."""
    await _limpar_o_cadastro(conn)
    yasmin = await _uma_modelo(conn, chave_pix="dela@pix.example", titular_chave="Yasmin N A")
    await _cadastrar(
        conn,
        chave="cpf-dela@pix.example",
        papel="modelo",
        modelo_id=yasmin,
        titular="YASMIN NASCIMENTO DE ALBUQUERQUE",
    )
    atendimento_id = await _um_atendimento(conn, yasmin)

    conhecidas = await carregar_chaves_da_operacao(conn, atendimento_id=atendimento_id)

    assert conhecidas.aceita_chave("cpf-dela@pix.example")
    assert conhecidas.aceita_titular("Yasmin Albuquerque")
    # A EXPECTATIVA nao muda: continua sendo so o que a IA entregou ao cliente.
    assert conhecidas.chave_da_modelo == "dela@pix.example"


async def test_chave_de_terceiro_cadastrada_nao_autoriza_destino(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """`terceiro` existe exatamente para dizer "conheco esta chave E ela nao e da operacao".
    Na lista plana ela autorizava — cadastrar o agiota do exemplo abria a porta."""
    await _limpar_o_cadastro(conn)
    yasmin = await _uma_modelo(conn, chave_pix="dela@pix.example", titular_chave="Yasmin N A")
    await _cadastrar(conn, chave=CHAVE_DE_TERCEIRO, papel="terceiro", titular="Erick de Melo")
    atendimento_id = await _um_atendimento(conn, yasmin)

    conhecidas = await carregar_chaves_da_operacao(conn, atendimento_id=atendimento_id)

    assert conhecidas.aceita_chave(CHAVE_DE_TERCEIRO) is False
    assert conhecidas.aceita_titular("Erick de Melo") is False
    # Conhecida ela e — o que ela nao e, e destino legitimo.
    assert papel_da_chave(CHAVE_DE_TERCEIRO, await registro_de_chaves(conn)).e_conhecida


async def test_o_telefonista_tipado_recebe_por_qualquer_atendimento(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """*"ele sempre manda pra conta da empresa? — vai depender"*: o deslocamento cai na conta do
    telefonista tambem, e agora ela tem papel proprio em vez de morar solta na lista da casa."""
    await _limpar_o_cadastro(conn)
    joao = await _um_telefonista(conn)
    yasmin = await _uma_modelo(conn, chave_pix="dela@pix.example", titular_chave="Yasmin N A")
    await _cadastrar(
        conn,
        chave=CHAVE_DO_TELEFONISTA,
        papel="telefonista",
        vendedor_id=joao,
        titular="Joao Pereira",
    )
    atendimento_id = await _um_atendimento(conn, yasmin)

    conhecidas = await carregar_chaves_da_operacao(conn, atendimento_id=atendimento_id)

    assert conhecidas.aceita_chave("+5571999840879")
    assert conhecidas.aceita_titular("Joao Pereira")


async def test_chave_inativa_explica_o_passado_mas_nao_autoriza_o_futuro(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """As duas perguntas, lado a lado, sobre a MESMA linha — e a razao de `registro_de_chaves`
    trazer as inativas e de `workers/pix.py` filtra-las."""
    await _limpar_o_cadastro(conn)
    yasmin = await _uma_modelo(conn, chave_pix="dela@pix.example", titular_chave="Yasmin N A")
    await _cadastrar(conn, chave=CHAVE_DA_CASA, papel="casa", titular=TITULAR_DA_CASA, ativo=False)
    atendimento_id = await _um_atendimento(conn, yasmin)

    assert papel_da_chave(CHAVE_DA_CASA, await registro_de_chaves(conn)).e_da_casa  # de quem e
    conhecidas = await carregar_chaves_da_operacao(conn, atendimento_id=atendimento_id)
    assert conhecidas.aceita_chave(CHAVE_DA_CASA) is False  # autoriza destino novo?


async def test_sem_chave_na_ficha_nada_diverge_mesmo_com_o_cadastro_cheio(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """A guarda que o ticket 01 pos e que o 03 NAO pode remover: a expectativa vem so de
    `modelos.chave_pix` (o que a IA entregou ao cliente). Cadastrar a chave dela na aba nova
    NAO pode acordar a checagem de divergencia — seria a regressao por DADO do ADR-0049."""
    await _limpar_o_cadastro(conn)
    yasmin = await _uma_modelo(conn)  # ficha vazia: o estado real de 20/08/2026
    await _cadastrar(conn, chave="dela@pix.example", papel="modelo", modelo_id=yasmin)
    await _cadastrar(conn, chave=CHAVE_DA_CASA, papel="casa", titular=TITULAR_DA_CASA)
    atendimento_id = await _um_atendimento(conn, yasmin)

    conhecidas = await carregar_chaves_da_operacao(conn, atendimento_id=atendimento_id)

    assert conhecidas.chave_da_modelo is None
    assert conhecidas.titular_da_modelo is None
    assert conhecidas.aceita_chave("dela@pix.example")  # aceita, mas nao cobra
