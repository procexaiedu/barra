"""ADR-0049 / ticket 01 — o Pix de deslocamento confere o destino contra a OPERACAO INTEIRA.

Antes deste ticket, `workers/pix.py` reprovava (`em_revisao`, "chave divergente") todo comprovante
cujo destino nao batesse com `modelos.chave_pix` **daquela** modelo. A checagem estava DORMENTE
porque nenhuma modelo tinha a chave preenchida (medido 20/08/2026: 0 de 0) — e o ticket 02 pede ao
dono exatamente esse cadastro. Preenche-lo ACORDARIA a checagem, e todo deslocamento que
legitimamente foi para a conta da casa (*"ele sempre manda pra conta da empresa? — vai depender"*)
passaria a cair em revisao manual. Regressao disparada por DADO, nao por deploy.

Estes testes fixam as duas metades do conserto:

* a **aceitacao** e a operacao inteira — casa, modelo daquele atendimento, telefonista;
* a **expectativa** continua vindo so da chave da modelo (o que a IA entregou ao cliente). Sem ela,
  nada diverge — e e por isso que o comportamento de HOJE, com o cadastro vazio, nao muda em nada.

vision_client + MinIO + redis mockados; so o Postgres e real, com ROLLBACK no teardown.
"""

import os
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from barra.workers.pix import (
    ChavesDaOperacao,
    ExtracaoPix,
    carregar_chaves_da_operacao,
    validar_pix,
)

# --- infra de DB real (ROLLBACK sempre) ------------------------------------------------------


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


class _PoolDeUmaConexao:
    """Pool fake que sempre devolve a conexao da fixture (mantem tudo na MESMA transacao)."""

    def __init__(self, connection: AsyncConnection[dict[str, Any]]) -> None:
        self._conn = connection

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[AsyncConnection[dict[str, Any]]]:
        yield self._conn


class _FakeMinio:
    JPEG_MAGIC = b"\xff\xd8\xff" + b"\x00" * 16

    def get_object(self, _bucket: str, _key: str) -> Any:
        dados = self.JPEG_MAGIC

        class _Resp:
            def read(self_inner: Any) -> bytes:
                return dados

            def close(self_inner: Any) -> None:
                return None

            def release_conn(self_inner: Any) -> None:
                return None

        return _Resp()


class _FakeVisionClient:
    def __init__(self, extracao: ExtracaoPix) -> None:
        self._extracao = extracao

        async def _create(**_: Any) -> Any:
            msg = SimpleNamespace(content=self._extracao.model_dump_json())
            return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

        self.chat = SimpleNamespace(completions=SimpleNamespace(create=_create))

    async def close(self) -> None:
        return None


class _FakeRedis:
    def __init__(self) -> None:
        self.jobs: list[tuple[str, dict[str, Any]]] = []

    async def enqueue_job(self, name: str, **kwargs: Any) -> None:
        self.jobs.append((name, kwargs))


# --- seeders ---------------------------------------------------------------------------------


CHAVE_DA_MODELO = "modelo-do-atendimento@pix.example"
TITULAR_DA_MODELO = "Maria Silva"
CHAVE_DA_CASA = "casa-elite@pix.example"
TITULAR_DA_CASA = "Elite Servicos Ltda"
CHAVE_DO_TELEFONISTA = "+55 71 99984-0879"
TITULAR_DO_TELEFONISTA = "Joao Pereira"
CHAVE_DE_TERCEIRO = "golpista@pix.example"


async def _seed_cenario(
    c: AsyncConnection[dict[str, Any]],
    *,
    chave_da_modelo: str | None,
    titular_da_modelo: str | None,
) -> tuple[UUID, UUID]:
    """Atendimento externo em Aguardando_confirmacao, com a ficha da modelo parametrizavel.

    `chave_da_modelo=None` e o estado REAL de producao em 20/08/2026 (0 de 0 preenchidas).
    """
    modelo_id = uuid4()
    await c.execute(
        """
        INSERT INTO barravips.modelos
            (id, nome, idade, numero_whatsapp, valor_padrao, tipo_atendimento_aceito,
             chave_pix, titular_chave, coordenacao_chat_id, evolution_instance_id)
        VALUES (%s, %s, %s, %s, %s, %s::barravips.tipo_atendimento_enum[], %s, %s, %s, %s)
        """,
        (
            modelo_id,
            "Modelo Teste",
            25,
            f"test-wpp-{uuid4().hex}",
            500,
            ["externo"],
            chave_da_modelo,
            titular_da_modelo,
            f"test-grp-{uuid4().hex}@g.us",
            f"inst-{uuid4().hex}",
        ),
    )
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
    mensagem_id = uuid4()
    await c.execute(
        """
        INSERT INTO barravips.mensagens
            (id, conversa_id, direcao, tipo, conteudo, media_object_key, evolution_message_id)
        VALUES (%s, %s, 'cliente', 'imagem', %s, %s, %s)
        """,
        (
            mensagem_id,
            conversa_id,
            "",
            f"conversas/{conversa_id}/mensagens/{uuid4().hex}.jpg",
            f"test-evo-{uuid4().hex}",
        ),
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
    return atendimento_id, mensagem_id


async def _cadastrar_chave_conhecida(
    c: AsyncConnection[dict[str, Any]],
    *,
    chave: str,
    titular: str,
    descricao: str,
    ativo: bool = True,
    papel: str = "casa",
) -> None:
    """Uma chave da operacao, cadastrada como a casa cadastra hoje.

    Enquanto o cadastro tipado (ticket 02) nao existe, a tabela e PLANA: a chave da casa e a do
    telefonista moram juntas aqui, sem dizer o papel — `vendedores` nao tem coluna de chave Pix.
    O ticket 02 acrescenta `papel` NOT NULL; este seeder preenche a coluna QUANDO ela existe, para
    que o ticket 01 (que precisa entrar em producao ANTES) continue verificavel nos dois esquemas.
    """
    cur = await c.execute(
        """
        SELECT 1 FROM information_schema.columns
         WHERE table_schema = 'barravips'
           AND table_name = 'chaves_pix_conhecidas'
           AND column_name = 'papel'
        """
    )
    tipada = await cur.fetchone() is not None
    normalizada = re.sub(r"[\s.\-+()/]", "", chave).lower()
    if tipada:
        # O CHECK `papel x dono` exige `vendedor_id` quando o papel e telefonista.
        vendedor_id = None
        if papel == "telefonista":
            vendedor_id = uuid4()
            await c.execute(
                "INSERT INTO barravips.vendedores (id, nome) VALUES (%s, %s)",
                (vendedor_id, titular),
            )
        await c.execute(
            """
            INSERT INTO barravips.chaves_pix_conhecidas
                (chave, chave_normalizada, titular, descricao, ativo, papel, vendedor_id)
            VALUES (%s, %s, %s, %s, %s, %s::barravips.papel_da_chave_enum, %s)
            """,
            (chave, normalizada, titular, descricao, ativo, papel, vendedor_id),
        )
    else:
        await c.execute(
            """
            INSERT INTO barravips.chaves_pix_conhecidas
                (chave, chave_normalizada, titular, descricao, ativo)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (chave, normalizada, titular, descricao, ativo),
        )


async def _ler_comprovante(
    c: AsyncConnection[dict[str, Any]], atendimento_id: UUID
) -> dict[str, Any]:
    res = await c.execute(
        """
        SELECT decisao_pipeline::text AS decisao_pipeline, motivo_em_revisao
          FROM barravips.comprovantes_pix WHERE atendimento_id = %s
        """,
        (atendimento_id,),
    )
    row = await res.fetchone()
    assert row is not None
    return row


def _extracao(*, chave: str | None, titular: str | None) -> ExtracaoPix:
    return ExtracaoPix(
        valor=Decimal("100.00"),
        chave_pix_destinatario=chave,
        titular_destinatario=titular,
        banco_origem="Itau",
        plausibilidade_visual=True,
        motivo_se_implausivel=None,
        confianca="alta",
    )


def _ctx(
    conn: AsyncConnection[dict[str, Any]],
    extracao: ExtracaoPix,
    redis: _FakeRedis,
) -> dict[str, Any]:
    from barra.settings import get_settings

    return {
        "db_pool": _PoolDeUmaConexao(conn),
        "minio": _FakeMinio(),
        "vision_client": _FakeVisionClient(extracao),
        "settings": get_settings(),
        "redis": redis,
    }


async def _rodar(
    conn: AsyncConnection[dict[str, Any]],
    *,
    atendimento_id: UUID,
    mensagem_id: UUID,
    extracao: ExtracaoPix,
) -> dict[str, Any]:
    await validar_pix(
        _ctx(conn, extracao, _FakeRedis()),
        mensagem_id=str(mensagem_id),
        atendimento_id=str(atendimento_id),
    )
    return await _ler_comprovante(conn, atendimento_id)


# --- o estado de HOJE nao pode mudar ----------------------------------------------------------


@pytest.mark.needs_db
async def test_cadastro_vazio_nao_diverge_nunca(conn: AsyncConnection[dict[str, Any]]) -> None:
    """O CRITERIO CENTRAL do ticket: com `modelos.chave_pix` vazia — o estado de producao de hoje —
    nenhum destino diverge, exatamente como antes do conserto.

    Note que a casa TEM chave cadastrada aqui: se a aceitacao tivesse virado "tem que estar na lista
    da casa", este comprovante (destino desconhecido) cairia em revisao, e seria uma regressao NOVA
    em vez do bug dormente consertado.
    """
    await _cadastrar_chave_conhecida(
        conn, chave=CHAVE_DA_CASA, titular=TITULAR_DA_CASA, descricao="casa"
    )
    atendimento_id, mensagem_id = await _seed_cenario(
        conn, chave_da_modelo=None, titular_da_modelo=None
    )

    cp = await _rodar(
        conn,
        atendimento_id=atendimento_id,
        mensagem_id=mensagem_id,
        extracao=_extracao(chave=CHAVE_DE_TERCEIRO, titular="Fulano Qualquer"),
    )

    assert cp["decisao_pipeline"] == "validado"
    assert cp["motivo_em_revisao"] is None


# --- a aceitacao e a operacao inteira ---------------------------------------------------------


@pytest.mark.needs_db
async def test_pix_para_a_conta_da_casa_valida(conn: AsyncConnection[dict[str, Any]]) -> None:
    """O caso que o bug dormente reprovaria assim que o cadastro fosse preenchido."""
    await _cadastrar_chave_conhecida(
        conn, chave=CHAVE_DA_CASA, titular=TITULAR_DA_CASA, descricao="casa"
    )
    atendimento_id, mensagem_id = await _seed_cenario(
        conn, chave_da_modelo=CHAVE_DA_MODELO, titular_da_modelo=TITULAR_DA_MODELO
    )

    cp = await _rodar(
        conn,
        atendimento_id=atendimento_id,
        mensagem_id=mensagem_id,
        extracao=_extracao(chave=CHAVE_DA_CASA, titular=TITULAR_DA_CASA),
    )

    assert cp["decisao_pipeline"] == "validado", cp["motivo_em_revisao"]
    assert cp["motivo_em_revisao"] is None


@pytest.mark.needs_db
async def test_pix_para_a_chave_da_modelo_do_atendimento_valida(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    await _cadastrar_chave_conhecida(
        conn, chave=CHAVE_DA_CASA, titular=TITULAR_DA_CASA, descricao="casa"
    )
    atendimento_id, mensagem_id = await _seed_cenario(
        conn, chave_da_modelo=CHAVE_DA_MODELO, titular_da_modelo=TITULAR_DA_MODELO
    )

    cp = await _rodar(
        conn,
        atendimento_id=atendimento_id,
        mensagem_id=mensagem_id,
        extracao=_extracao(chave=CHAVE_DA_MODELO, titular=TITULAR_DA_MODELO),
    )

    assert cp["decisao_pipeline"] == "validado", cp["motivo_em_revisao"]


@pytest.mark.needs_db
async def test_pix_para_a_chave_do_telefonista_valida(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """A chave do telefonista vive na mesma lista plana enquanto o ticket 02 nao tipa o cadastro.

    A grafia tambem muda de tela para tela: o OCR le "+5571999840879" e o cadastro guarda
    "+55 71 99984-0879". A normalizacao de `_chaves_compativeis` e quem faz as duas serem a mesma.
    """
    await _cadastrar_chave_conhecida(
        conn,
        chave=CHAVE_DO_TELEFONISTA,
        titular=TITULAR_DO_TELEFONISTA,
        descricao="telefonista (papel proprio quando o cadastro tipado existe)",
        papel="telefonista",
    )
    atendimento_id, mensagem_id = await _seed_cenario(
        conn, chave_da_modelo=CHAVE_DA_MODELO, titular_da_modelo=TITULAR_DA_MODELO
    )

    cp = await _rodar(
        conn,
        atendimento_id=atendimento_id,
        mensagem_id=mensagem_id,
        extracao=_extracao(chave="+5571999840879", titular=TITULAR_DO_TELEFONISTA),
    )

    assert cp["decisao_pipeline"] == "validado", cp["motivo_em_revisao"]


@pytest.mark.needs_db
async def test_chave_inativa_nao_conta_como_conhecida(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Inativar nunca deletar: a chave desligada continua explicando comprovante antigo, mas nao
    autoriza destino novo."""
    await _cadastrar_chave_conhecida(
        conn,
        chave=CHAVE_DA_CASA,
        titular=TITULAR_DA_CASA,
        descricao="casa, conta encerrada",
        ativo=False,
    )
    atendimento_id, mensagem_id = await _seed_cenario(
        conn, chave_da_modelo=CHAVE_DA_MODELO, titular_da_modelo=TITULAR_DA_MODELO
    )

    cp = await _rodar(
        conn,
        atendimento_id=atendimento_id,
        mensagem_id=mensagem_id,
        extracao=_extracao(chave=CHAVE_DA_CASA, titular=TITULAR_DA_CASA),
    )

    assert cp["decisao_pipeline"] == "em_revisao"
    assert "chave divergente" in (cp["motivo_em_revisao"] or "")


# --- o que continua caindo em revisao ---------------------------------------------------------


@pytest.mark.needs_db
async def test_chave_fora_de_tudo_cai_em_revisao_dizendo_o_que_se_esperava(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    await _cadastrar_chave_conhecida(
        conn, chave=CHAVE_DA_CASA, titular=TITULAR_DA_CASA, descricao="casa"
    )
    atendimento_id, mensagem_id = await _seed_cenario(
        conn, chave_da_modelo=CHAVE_DA_MODELO, titular_da_modelo=TITULAR_DA_MODELO
    )

    cp = await _rodar(
        conn,
        atendimento_id=atendimento_id,
        mensagem_id=mensagem_id,
        extracao=_extracao(chave=CHAVE_DE_TERCEIRO, titular=TITULAR_DA_MODELO),
    )

    assert cp["decisao_pipeline"] == "em_revisao"
    motivo = cp["motivo_em_revisao"] or ""
    assert "chave divergente" in motivo
    assert CHAVE_DE_TERCEIRO in motivo  # o que veio
    assert CHAVE_DA_MODELO in motivo  # o que se esperava
    assert "conhecidas da operacao" in motivo  # e que havia mais destinos legitimos


@pytest.mark.needs_db
async def test_titular_de_terceiro_cai_em_revisao_mas_o_da_casa_nao(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """`titular_divergente` tinha o MESMO defeito: conferia so contra `modelos.titular_chave`.

    Aqui a chave nem foi extraida (o comprovante so mostrou o nome), entao a decisao e do titular.
    """
    await _cadastrar_chave_conhecida(
        conn, chave=CHAVE_DA_CASA, titular=TITULAR_DA_CASA, descricao="casa"
    )
    atendimento_id, mensagem_id = await _seed_cenario(
        conn, chave_da_modelo=CHAVE_DA_MODELO, titular_da_modelo=TITULAR_DA_MODELO
    )
    cp = await _rodar(
        conn,
        atendimento_id=atendimento_id,
        mensagem_id=mensagem_id,
        extracao=_extracao(chave=None, titular=TITULAR_DA_CASA),
    )
    assert cp["decisao_pipeline"] == "validado", cp["motivo_em_revisao"]

    outro_id, outra_msg = await _seed_cenario(
        conn, chave_da_modelo=CHAVE_DA_MODELO, titular_da_modelo=TITULAR_DA_MODELO
    )
    cp = await _rodar(
        conn,
        atendimento_id=outro_id,
        mensagem_id=outra_msg,
        extracao=_extracao(chave=None, titular="Fulano de Tal"),
    )
    assert cp["decisao_pipeline"] == "em_revisao"
    motivo = cp["motivo_em_revisao"] or ""
    assert "titular divergente" in motivo
    assert TITULAR_DA_MODELO in motivo  # o que se esperava


# --- a leitura, direto ------------------------------------------------------------------------


@pytest.mark.needs_db
async def test_carregar_chaves_da_operacao_junta_casa_e_modelo(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """O seam do ticket 03: quem trocar o corpo desta funcao por `papel_da_chave` tem que continuar
    devolvendo (a) todo destino legitimo e (b) qual deles e a expectativa da modelo."""
    await _cadastrar_chave_conhecida(
        conn, chave=CHAVE_DA_CASA, titular=TITULAR_DA_CASA, descricao="casa"
    )
    atendimento_id, _ = await _seed_cenario(
        conn, chave_da_modelo=CHAVE_DA_MODELO, titular_da_modelo=TITULAR_DA_MODELO
    )

    conhecidas = await carregar_chaves_da_operacao(conn, atendimento_id=atendimento_id)

    assert CHAVE_DA_CASA in conhecidas.chaves
    assert CHAVE_DA_MODELO in conhecidas.chaves
    assert conhecidas.chave_da_modelo == CHAVE_DA_MODELO
    assert conhecidas.titular_da_modelo == TITULAR_DA_MODELO
    assert conhecidas.aceita_chave(CHAVE_DA_CASA)
    assert not conhecidas.aceita_chave(CHAVE_DE_TERCEIRO)


@pytest.mark.needs_db
async def test_carregar_chaves_da_operacao_sem_ficha_nao_tem_expectativa(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    atendimento_id, _ = await _seed_cenario(conn, chave_da_modelo=None, titular_da_modelo=None)

    conhecidas = await carregar_chaves_da_operacao(conn, atendimento_id=atendimento_id)

    assert conhecidas.chave_da_modelo is None
    assert conhecidas.titular_da_modelo is None
    assert isinstance(conhecidas, ChavesDaOperacao)
