"""A aba **Chaves Pix** — o registro tipado de "de quem e esta chave" (ADR-0049 §2, ticket 02).

O que este arquivo prova, sempre pela API real do painel (HTTP autenticado):

1. A linha que ja existia — a lista plana "chaves da casa" de 20260814031400 — sobrevive a
   migration com `papel = 'casa'`: **nenhuma linha existente perde significado**.
2. O papel exige o dono que ele pede e PROIBE o que ele nao pede (`modelo` sem modelo e recusado;
   `casa` com modelo tambem). A recusa e 422 com frase em portugues, nao 500 de constraint.
3. Uma modelo tem VARIAS chaves — CPF, telefone, aleatoria — e nenhuma delas atrapalha a outra.
4. Existe no maximo UMA chave padrao da casa: marcar a segunda desmarca a primeira sozinha.
5. Chave duplicada com outra pontuacao e a MESMA chave (409), porque o UNIQUE e sobre a forma
   normalizada — a mesma com que o OCR compara.
6. Inativar nunca deletar: a chave some da lista viva e volta com `incluir_inativas`, e nao ha
   rota de DELETE.

`needs_db` com `TEST_DATABASE_URL` + ROLLBACK sempre — nenhuma linha escapa da transacao.
"""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_asyncio
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from barra.api.deps import get_conn
from barra.main import app

pytestmark = pytest.mark.needs_db

CHAVE_DA_CASA = "+55 71 99984 0879"
"""Fictícia. A grafia com espaco e sinal existe para o teste 5: o OCR le a tela do banco, que nunca
e a grafia de quem cadastrou."""
MESMA_CHAVE_OUTRA_GRAFIA = "+5571999840879"


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


def _token(papel: str = "fernando") -> dict[str, str]:
    return {"Authorization": f"Bearer test:{uuid4()}:{papel}:true"}


@asynccontextmanager
async def _painel(c: AsyncConnection[dict[str, Any]]) -> AsyncIterator[httpx.AsyncClient]:
    async def _mesma_conexao() -> AsyncIterator[AsyncConnection[dict[str, Any]]]:
        yield c

    app.dependency_overrides[get_conn] = _mesma_conexao
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://painel") as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_conn, None)


async def _uma_modelo(c: AsyncConnection[dict[str, Any]]) -> UUID:
    modelo_id = uuid4()
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
            f"5511{uuid4().int % 1_000_000_000:09d}",
            600,
            ["interno"],
            Decimal("40"),
        ),
    )
    return modelo_id


async def _um_telefonista(c: AsyncConnection[dict[str, Any]]) -> UUID:
    vendedor_id = uuid4()
    await c.execute(
        "INSERT INTO barravips.vendedores (id, nome) VALUES (%s, %s)",
        (vendedor_id, f"Lula {uuid4().hex[:6]}"),
    )
    return vendedor_id


async def _limpar_o_registro(c: AsyncConnection[dict[str, Any]]) -> None:
    """Dentro da transacao que o rollback desfaz: o teste precisa de um registro previsivel."""
    await c.execute("DELETE FROM barravips.chaves_pix_conhecidas")


# --- 1. a linha que ja existia e da casa --------------------------------------------------------


@pytest.mark.asyncio
async def test_a_linha_antiga_virou_papel_casa(conn: AsyncConnection[dict[str, Any]]) -> None:
    """A tabela nasceu como "as chaves da casa". O backfill le esse significado e o escreve.

    E o MESMO significado governa o DEFAULT: um INSERT que nao nomeia o papel foi escrito quando a
    tabela so tinha chave da casa, e continua querendo dizer isso. Tirar o DEFAULT quebraria todo
    escritor anterior ao ADR com NotNullViolation — "nao perder significado" inclui nao quebrar
    quem ja escreve aqui. A exigencia de DECLARAR mora no painel (teste abaixo), onde ha um humano.
    """
    cur = await conn.execute(
        "SELECT count(*) AS fora FROM barravips.chaves_pix_conhecidas WHERE papel <> 'casa'"
    )
    linha = await cur.fetchone()
    assert linha is not None
    assert linha["fora"] == 0

    cur = await conn.execute(
        """
        SELECT is_nullable, column_default
          FROM information_schema.columns
         WHERE table_schema = 'barravips'
           AND table_name = 'chaves_pix_conhecidas'
           AND column_name = 'papel'
        """
    )
    coluna = await cur.fetchone()
    assert coluna is not None
    assert coluna["is_nullable"] == "NO"
    assert coluna["column_default"] == "'casa'::barravips.papel_da_chave_enum"


# --- 2. papel x dono ----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_aba_exige_declarar_o_papel(conn: AsyncConnection[dict[str, Any]]) -> None:
    """O banco tem DEFAULT `casa` por compatibilidade; a ABA nao tem default nenhum.

    E onde a politica do ADR-0049 §2 mora: cadastrar sem dizer de quem e a chave nao e um gesto
    possivel para um humano, porque e assim que a chave de um terceiro viraria "da casa".
    """
    async with _painel(conn) as painel:
        sem_papel = await painel.post(
            "/v1/financeiro/chaves-pix",
            json={"chave": f"chave-{uuid4().hex[:8]}"},
            headers=_token(),
        )
        assert sem_papel.status_code == 422


@pytest.mark.asyncio
async def test_papel_exige_e_proibe_o_dono(conn: AsyncConnection[dict[str, Any]]) -> None:
    modelo_id = await _uma_modelo(conn)
    async with _painel(conn) as painel:
        sem_dono = await painel.post(
            "/v1/financeiro/chaves-pix",
            json={"chave": f"chave-{uuid4().hex[:8]}", "papel": "modelo"},
            headers=_token(),
        )
        assert sem_dono.status_code == 422

        dono_a_mais = await painel.post(
            "/v1/financeiro/chaves-pix",
            json={
                "chave": f"chave-{uuid4().hex[:8]}",
                "papel": "casa",
                "modelo_id": str(modelo_id),
            },
            headers=_token(),
        )
        assert dono_a_mais.status_code == 422


@pytest.mark.asyncio
async def test_telefonista_tambem_tem_chave(conn: AsyncConnection[dict[str, Any]]) -> None:
    """O deslocamento as vezes cai na conta dele — *"vai depender"*."""
    vendedor_id = await _um_telefonista(conn)
    async with _painel(conn) as painel:
        r = await painel.post(
            "/v1/financeiro/chaves-pix",
            json={
                "chave": f"chave-{uuid4().hex[:8]}",
                "papel": "telefonista",
                "vendedor_id": str(vendedor_id),
            },
            headers=_token(),
        )
        assert r.status_code == 201, r.text
        assert r.json()["vendedor_nome"] is not None


# --- 3. uma modelo, varias chaves ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_uma_modelo_tem_varias_chaves(conn: AsyncConnection[dict[str, Any]]) -> None:
    """CPF, telefone, aleatoria — e ela troca de banco. O dono e coluna da chave, nao o contrario."""
    await _limpar_o_registro(conn)
    modelo_id = await _uma_modelo(conn)
    async with _painel(conn) as painel:
        for rotulo in ("cpf", "telefone", "aleatoria"):
            r = await painel.post(
                "/v1/financeiro/chaves-pix",
                json={
                    "chave": f"{rotulo}-{uuid4().hex[:8]}",
                    "papel": "modelo",
                    "modelo_id": str(modelo_id),
                    "descricao": rotulo,
                },
                headers=_token(),
            )
            assert r.status_code == 201, r.text

        lista = await painel.get("/v1/financeiro/chaves-pix", headers=_token())
        assert lista.status_code == 200
        itens = lista.json()["items"]
        assert len(itens) == 3
        assert {i["descricao"] for i in itens} == {"cpf", "telefone", "aleatoria"}
        assert all(i["modelo_nome"] is not None for i in itens)


# --- 4. no maximo UMA padrao --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_so_existe_uma_padrao_da_casa(conn: AsyncConnection[dict[str, Any]]) -> None:
    """Marcar a segunda desmarca a primeira — na mesma transacao, senao bate no indice unico."""
    await _limpar_o_registro(conn)
    async with _painel(conn) as painel:
        primeira = await painel.post(
            "/v1/financeiro/chaves-pix",
            json={"chave": f"casa-a-{uuid4().hex[:8]}", "papel": "casa", "padrao": True},
            headers=_token(),
        )
        assert primeira.status_code == 201, primeira.text
        assert primeira.json()["padrao"] is True

        segunda = await painel.post(
            "/v1/financeiro/chaves-pix",
            json={"chave": f"casa-b-{uuid4().hex[:8]}", "papel": "casa"},
            headers=_token(),
        )
        assert segunda.status_code == 201, segunda.text
        virou = await painel.patch(
            f"/v1/financeiro/chaves-pix/{segunda.json()['id']}",
            json={"padrao": True},
            headers=_token(),
        )
        assert virou.status_code == 200, virou.text
        assert virou.json()["padrao"] is True

        itens = (await painel.get("/v1/financeiro/chaves-pix", headers=_token())).json()["items"]
        padroes = [i["id"] for i in itens if i["padrao"]]
        assert padroes == [segunda.json()["id"]]
        # A padrao vem primeiro na lista: e a pergunta do dia.
        assert itens[0]["id"] == segunda.json()["id"]


@pytest.mark.asyncio
async def test_chave_de_modelo_nao_vira_padrao(conn: AsyncConnection[dict[str, Any]]) -> None:
    """A padrao e "a conta da casa que a gente mais recebe" — nao existe padrao de terceiro."""
    modelo_id = await _uma_modelo(conn)
    async with _painel(conn) as painel:
        r = await painel.post(
            "/v1/financeiro/chaves-pix",
            json={
                "chave": f"chave-{uuid4().hex[:8]}",
                "papel": "modelo",
                "modelo_id": str(modelo_id),
                "padrao": True,
            },
            headers=_token(),
        )
        assert r.status_code == 422


# --- 5. a mesma chave com outra pontuacao -------------------------------------------------------


@pytest.mark.asyncio
async def test_mesma_chave_outra_grafia_e_conflito(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    await _limpar_o_registro(conn)
    async with _painel(conn) as painel:
        primeira = await painel.post(
            "/v1/financeiro/chaves-pix",
            json={"chave": CHAVE_DA_CASA, "papel": "casa"},
            headers=_token(),
        )
        assert primeira.status_code == 201, primeira.text
        repetida = await painel.post(
            "/v1/financeiro/chaves-pix",
            json={"chave": MESMA_CHAVE_OUTRA_GRAFIA, "papel": "casa"},
            headers=_token(),
        )
        assert repetida.status_code == 409, repetida.text


# --- 6. inativar nunca deletar ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_inativar_a_padrao_solta_a_padrao(conn: AsyncConnection[dict[str, Any]]) -> None:
    """Inativar a padrao e PERDER a padrao — alguem precisa escolher outra.

    Sem soltar a marca antes do UPDATE, o CHECK `chaves_pix_conhecidas_padrao_e_da_casa_viva`
    estouraria um 500 na cara do gestor.
    """
    await _limpar_o_registro(conn)
    async with _painel(conn) as painel:
        criada = await painel.post(
            "/v1/financeiro/chaves-pix",
            json={"chave": f"casa-{uuid4().hex[:8]}", "papel": "casa", "padrao": True},
            headers=_token(),
        )
        assert criada.status_code == 201, criada.text
        chave_id = criada.json()["id"]

        inativada = await painel.patch(
            f"/v1/financeiro/chaves-pix/{chave_id}",
            json={"ativo": False},
            headers=_token(),
        )
        assert inativada.status_code == 200, inativada.text
        assert inativada.json()["ativo"] is False
        assert inativada.json()["padrao"] is False

        vivas = (await painel.get("/v1/financeiro/chaves-pix", headers=_token())).json()["items"]
        assert vivas == []

        todas = (
            await painel.get("/v1/financeiro/chaves-pix?incluir_inativas=true", headers=_token())
        ).json()["items"]
        assert [i["id"] for i in todas] == [chave_id]

        # Nao existe DELETE nesta aba: a chave precisa continuar explicando comprovante antigo.
        apagar = await painel.delete(f"/v1/financeiro/chaves-pix/{chave_id}", headers=_token())
        assert apagar.status_code == 405


@pytest.mark.asyncio
async def test_trocar_o_papel_troca_o_dono_junto(conn: AsyncConnection[dict[str, Any]]) -> None:
    """Promover a chave de uma modelo a `casa` nao pode deixar o `modelo_id` antigo para tras."""
    modelo_id = await _uma_modelo(conn)
    async with _painel(conn) as painel:
        criada = await painel.post(
            "/v1/financeiro/chaves-pix",
            json={
                "chave": f"chave-{uuid4().hex[:8]}",
                "papel": "modelo",
                "modelo_id": str(modelo_id),
            },
            headers=_token(),
        )
        assert criada.status_code == 201, criada.text
        virou = await painel.patch(
            f"/v1/financeiro/chaves-pix/{criada.json()['id']}",
            json={"papel": "casa"},
            headers=_token(),
        )
        assert virou.status_code == 200, virou.text
        assert virou.json()["papel"] == "casa"
        assert virou.json()["modelo_id"] is None
        assert virou.json()["modelo_nome"] is None


@pytest.mark.asyncio
async def test_a_aba_e_do_painel(conn: AsyncConnection[dict[str, Any]]) -> None:
    """Sem token nao ha registro de chave — e chave e dado operacional da casa."""
    async with _painel(conn) as painel:
        sem_token = await painel.get("/v1/financeiro/chaves-pix")
        assert sem_token.status_code in (401, 403)


@pytest.mark.asyncio
async def test_desmarcar_uma_chave_qualquer_nao_apaga_a_padrao(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """`padrao=false` numa chave que nunca foi padrao nao pode mexer na padrao de OUTRA linha.

    Limpar a marca e uma escrita sobre o banco inteiro (`WHERE padrao`), entao o gesto so pode
    disparar quando quem esta sendo editada E a padrao — senao a estrela some da outra linha e
    ninguem entende por que.
    """
    await _limpar_o_registro(conn)
    async with _painel(conn) as painel:
        a_padrao = await painel.post(
            "/v1/financeiro/chaves-pix",
            json={"chave": f"casa-p-{uuid4().hex[:8]}", "papel": "casa", "padrao": True},
            headers=_token(),
        )
        assert a_padrao.status_code == 201, a_padrao.text
        outra = await painel.post(
            "/v1/financeiro/chaves-pix",
            json={"chave": f"casa-o-{uuid4().hex[:8]}", "papel": "casa"},
            headers=_token(),
        )
        assert outra.status_code == 201, outra.text

        desmarcada = await painel.patch(
            f"/v1/financeiro/chaves-pix/{outra.json()['id']}",
            json={"padrao": False},
            headers=_token(),
        )
        assert desmarcada.status_code == 200, desmarcada.text

        itens = (await painel.get("/v1/financeiro/chaves-pix", headers=_token())).json()["items"]
        assert [i["id"] for i in itens if i["padrao"]] == [a_padrao.json()["id"]]
