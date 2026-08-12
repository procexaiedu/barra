"""POST /{atendimento_id}/fetiches — o `preco_snapshot` do extra sai do MESMO site de conta que o
render e o guard usam (`extra_de_fetiche`): preço cadastrado quando existe (revisão 11/08/2026 do
ADR-0030) e, sem ele, a linha de 1 HORA do programa vendido (ADR-0038 — não mais o preço-hora do
pacote da spec 0001-fetiche-calculado).

`needs_db` (Postgres via TEST_DATABASE_URL), mesmo padrão de test_pausar_ia.py /
test_registrar_extracao.py: conn real autocommit=False + ROLLBACK sempre. Chama a rota
`adicionar_fetiche` diretamente (mesmo padrão de test_pausar_ia.py chamando `aplicar_comando`).
"""

import json
import os
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from barra.core.errors import ConflitoEstado
from barra.dominio.atendimentos.routes import adicionar_fetiche
from barra.dominio.atendimentos.schemas import AdicionarFeticheRequest
from barra.dominio.escaladas.service import aplicar_comando


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


# --- seeds (espelham test_pausar_ia / test_registrar_extracao) -------------------------------


async def _seed_modelo(c: AsyncConnection[dict[str, Any]]) -> UUID:
    modelo_id = uuid4()
    await c.execute(
        """
        INSERT INTO barravips.modelos
            (id, nome, idade, numero_whatsapp, valor_padrao, tipo_atendimento_aceito)
        VALUES (%s, %s, %s, %s, %s, %s::barravips.tipo_atendimento_enum[])
        """,
        (modelo_id, "Modelo Teste", 25, f"test-wpp-{uuid4().hex}", 500, ["interno", "externo"]),
    )
    return modelo_id


async def _seed_cliente(c: AsyncConnection[dict[str, Any]]) -> UUID:
    cliente_id = uuid4()
    await c.execute(
        "INSERT INTO barravips.clientes (id, telefone) VALUES (%s, %s)",
        (cliente_id, f"test-tel-{uuid4().hex}"),
    )
    return cliente_id


async def _seed_conversa(
    c: AsyncConnection[dict[str, Any]], cliente_id: UUID, modelo_id: UUID
) -> UUID:
    conversa_id = uuid4()
    await c.execute(
        """
        INSERT INTO barravips.conversas (id, cliente_id, modelo_id, evolution_chat_id)
        VALUES (%s, %s, %s, %s)
        """,
        (conversa_id, cliente_id, modelo_id, f"test-chat-{uuid4().hex}"),
    )
    return conversa_id


async def _seed_atendimento(
    c: AsyncConnection[dict[str, Any]], *, cliente_id: UUID, modelo_id: UUID, conversa_id: UUID
) -> UUID:
    atendimento_id = uuid4()
    await c.execute(
        """
        INSERT INTO barravips.atendimentos
            (id, cliente_id, modelo_id, conversa_id, estado, tipo_atendimento, pix_status)
        VALUES (%s, %s, %s, %s, 'Qualificado'::barravips.estado_atendimento_enum,
                'interno'::barravips.tipo_atendimento_enum,
                'nao_solicitado'::barravips.pix_status_enum)
        """,
        (atendimento_id, cliente_id, modelo_id, conversa_id),
    )
    return atendimento_id


async def _seed_fetiche(
    c: AsyncConnection[dict[str, Any]], *, cobra_por_pessoa: bool = False
) -> UUID:
    fetiche_id = uuid4()
    await c.execute(
        "INSERT INTO barravips.fetiches (id, nome, cobra_por_pessoa) VALUES (%s, %s, %s)",
        (fetiche_id, f"Fetiche Teste {uuid4().hex[:8]}", cobra_por_pessoa),
    )
    return fetiche_id


async def _seed_modelo_fetiche(
    c: AsyncConnection[dict[str, Any]], *, modelo_id: UUID, fetiche_id: UUID, pago: bool
) -> None:
    # Semântica atual (ADR-0030, ticket 02 pendente): NULL = incluso; NOT NULL = pago, valor
    # ignorado pelo cálculo. Usamos um valor deliberadamente "errado" (R$1) para provar que o
    # cálculo NUNCA lê esta coluna quando pago=True.
    await c.execute(
        "INSERT INTO barravips.modelo_fetiches (modelo_id, fetiche_id, preco) VALUES (%s, %s, %s)",
        (modelo_id, fetiche_id, Decimal("1") if pago else None),
    )


async def _duracao_id_por_horas(c: AsyncConnection[dict[str, Any]], horas: str) -> UUID:
    res = await c.execute(
        "SELECT id FROM barravips.duracoes WHERE horas = %s LIMIT 1", (Decimal(horas),)
    )
    row = await res.fetchone()
    assert row is not None, f"nenhuma duracao com horas={horas} (seed 0010/20260525181816)"
    return row["id"]


async def _programa_id_qualquer(c: AsyncConnection[dict[str, Any]]) -> UUID:
    res = await c.execute("SELECT id FROM barravips.programas LIMIT 1")
    row = await res.fetchone()
    assert row is not None, "nenhum programa no catalogo global (seed 0010)"
    return row["id"]


async def _seed_atendimento_servico(
    c: AsyncConnection[dict[str, Any]],
    *,
    atendimento_id: UUID,
    programa_id: UUID,
    duracao_id: UUID,
    preco_snapshot: Decimal,
) -> None:
    await c.execute(
        """
        INSERT INTO barravips.atendimento_servicos
            (atendimento_id, programa_id, duracao_id, preco_snapshot)
        VALUES (%s, %s, %s, %s)
        """,
        (atendimento_id, programa_id, duracao_id, preco_snapshot),
    )


async def _preco_snapshot_gravado(c: AsyncConnection[dict[str, Any]], atendimento_id: UUID) -> Any:
    res = await c.execute(
        "SELECT preco_snapshot FROM barravips.atendimento_fetiches WHERE atendimento_id = %s",
        (atendimento_id,),
    )
    row = await res.fetchone()
    assert row is not None
    return row["preco_snapshot"]


async def _setup_atendimento(c: AsyncConnection[dict[str, Any]]) -> tuple[UUID, UUID]:
    """Modelo + cliente + conversa + atendimento Qualificado. Retorna (atendimento_id, modelo_id)."""
    modelo_id = await _seed_modelo(c)
    cliente_id = await _seed_cliente(c)
    conversa_id = await _seed_conversa(c, cliente_id, modelo_id)
    atendimento_id = await _seed_atendimento(
        c, cliente_id=cliente_id, modelo_id=modelo_id, conversa_id=conversa_id
    )
    return atendimento_id, modelo_id


# --- adicionar_fetiche -------------------------------------------------------------------


@pytest.mark.needs_db
async def test_fetiche_incluso_grava_preco_snapshot_null(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    atendimento_id, modelo_id = await _setup_atendimento(conn)
    fetiche_id = await _seed_fetiche(conn)
    await _seed_modelo_fetiche(conn, modelo_id=modelo_id, fetiche_id=fetiche_id, pago=False)

    row = await adicionar_fetiche(
        atendimento_id, AdicionarFeticheRequest(fetiche_id=fetiche_id), conn
    )

    assert row["preco_snapshot"] is None
    assert await _preco_snapshot_gravado(conn, atendimento_id) is None


@pytest.mark.needs_db
async def test_fetiche_pago_servico_unico_usa_a_linha_de_uma_hora(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """ADR-0038: o extra é a linha de 1h do MESMO programa, não o preço-hora do pacote vendido.

    Pacote de 2h a R$700 e 1h a R$400: o extra é 400 (o preço-hora daria 350)."""
    atendimento_id, modelo_id = await _setup_atendimento(conn)
    fetiche_id = await _seed_fetiche(conn)
    await _seed_modelo_fetiche(conn, modelo_id=modelo_id, fetiche_id=fetiche_id, pago=True)
    programa_id = await _programa_id_qualquer(conn)
    await _seed_modelo_programa(
        conn,
        modelo_id=modelo_id,
        programa_id=programa_id,
        duracao_id=await _duracao_id_por_horas(conn, "1"),
        preco=Decimal("400"),
    )
    await _seed_atendimento_servico(
        conn,
        atendimento_id=atendimento_id,
        programa_id=programa_id,
        duracao_id=await _duracao_id_por_horas(conn, "2"),
        preco_snapshot=Decimal("700"),
    )

    row = await adicionar_fetiche(
        atendimento_id, AdicionarFeticheRequest(fetiche_id=fetiche_id), conn
    )

    assert row["preco_snapshot"] == Decimal("400.00")
    assert await _preco_snapshot_gravado(conn, atendimento_id) == Decimal("400.00")


@pytest.mark.needs_db
async def test_fetiche_pago_sem_linha_de_uma_hora_levanta_erro(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Fail-closed do ADR-0038: o programa vendido não tem 1h cadastrada, então não há extra a
    derivar. 409 explícito — gravar NULL diria "incluso" no breakdown do painel."""
    atendimento_id, modelo_id = await _setup_atendimento(conn)
    fetiche_id = await _seed_fetiche(conn)
    await _seed_modelo_fetiche(conn, modelo_id=modelo_id, fetiche_id=fetiche_id, pago=True)
    await _seed_atendimento_servico(
        conn,
        atendimento_id=atendimento_id,
        programa_id=await _programa_id_qualquer(conn),
        duracao_id=await _duracao_id_por_horas(conn, "2"),
        preco_snapshot=Decimal("700"),
    )

    with pytest.raises(ConflitoEstado) as exc_info:
        await adicionar_fetiche(
            atendimento_id, AdicionarFeticheRequest(fetiche_id=fetiche_id), conn
        )

    assert exc_info.value.message == "sem_linha_de_uma_hora_para_o_extra"


@pytest.mark.needs_db
async def test_fetiche_pago_multiplos_servicos_nao_tem_extra_derivado(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Dois serviços no mesmo atendimento: "a 1h do MESMO programa" não existe para um pacote que
    é a soma de dois (ADR-0038). Fail-closed em vez de eleger um dos programas por conta própria
    — antes disso o extra saía da soma dividida pelo MAX(duracao)."""
    atendimento_id, modelo_id = await _setup_atendimento(conn)
    fetiche_id = await _seed_fetiche(conn)
    await _seed_modelo_fetiche(conn, modelo_id=modelo_id, fetiche_id=fetiche_id, pago=True)
    programa_id = await _programa_id_qualquer(conn)
    await _seed_modelo_programa(
        conn,
        modelo_id=modelo_id,
        programa_id=programa_id,
        duracao_id=await _duracao_id_por_horas(conn, "1"),
        preco=Decimal("400"),
    )
    await _seed_atendimento_servico(
        conn,
        atendimento_id=atendimento_id,
        programa_id=programa_id,
        duracao_id=await _duracao_id_por_horas(conn, "1"),
        preco_snapshot=Decimal("400"),
    )
    await _seed_atendimento_servico(
        conn,
        atendimento_id=atendimento_id,
        programa_id=programa_id,
        duracao_id=await _duracao_id_por_horas(conn, "2"),
        preco_snapshot=Decimal("800"),
    )

    with pytest.raises(ConflitoEstado) as exc_info:
        await adicionar_fetiche(
            atendimento_id, AdicionarFeticheRequest(fetiche_id=fetiche_id), conn
        )

    assert exc_info.value.message == "sem_linha_de_uma_hora_para_o_extra"


@pytest.mark.needs_db
async def test_fetiche_por_pessoa_soma_o_mesmo_extra_dos_atos(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """ADR-0039: casal/menage (cobra_por_pessoa=true) perdeu a aritmética própria. O extra é a
    linha de 1h do mesmo programa, igual a qualquer ato — o pacote NÃO dobra.

    Pacote de 2h a R$800 com 1h a R$400: o extra é 400. O regime revogado gravava 800."""
    atendimento_id, modelo_id = await _setup_atendimento(conn)
    fetiche_id = await _seed_fetiche(conn, cobra_por_pessoa=True)
    await _seed_modelo_fetiche(conn, modelo_id=modelo_id, fetiche_id=fetiche_id, pago=True)
    programa_id = await _programa_id_qualquer(conn)
    await _seed_modelo_programa(
        conn,
        modelo_id=modelo_id,
        programa_id=programa_id,
        duracao_id=await _duracao_id_por_horas(conn, "1"),
        preco=Decimal("400"),
    )
    await _seed_atendimento_servico(
        conn,
        atendimento_id=atendimento_id,
        programa_id=programa_id,
        duracao_id=await _duracao_id_por_horas(conn, "2"),
        preco_snapshot=Decimal("800"),
    )

    row = await adicionar_fetiche(
        atendimento_id, AdicionarFeticheRequest(fetiche_id=fetiche_id), conn
    )

    assert row["preco_snapshot"] == Decimal("400.00")
    assert await _preco_snapshot_gravado(conn, atendimento_id) == Decimal("400.00")


@pytest.mark.needs_db
async def test_fetiche_por_pessoa_sem_linha_de_uma_hora_devolve_409(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Caminho de recusa NOVO do ADR-0039: o regime revogado gravava o pacote inteiro sem olhar a
    1h. Agora a composição cai no MESMO fail-closed dos atos."""
    atendimento_id, modelo_id = await _setup_atendimento(conn)
    fetiche_id = await _seed_fetiche(conn, cobra_por_pessoa=True)
    await _seed_modelo_fetiche(conn, modelo_id=modelo_id, fetiche_id=fetiche_id, pago=True)
    await _seed_atendimento_servico(
        conn,
        atendimento_id=atendimento_id,
        programa_id=await _programa_id_qualquer(conn),
        duracao_id=await _duracao_id_por_horas(conn, "2"),
        preco_snapshot=Decimal("800"),
    )

    with pytest.raises(ConflitoEstado) as exc_info:
        await adicionar_fetiche(
            atendimento_id, AdicionarFeticheRequest(fetiche_id=fetiche_id), conn
        )

    assert exc_info.value.message == "sem_linha_de_uma_hora_para_o_extra"


@pytest.mark.needs_db
async def test_fetiche_pago_sem_servico_vendido_levanta_erro(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    atendimento_id, modelo_id = await _setup_atendimento(conn)
    fetiche_id = await _seed_fetiche(conn)
    await _seed_modelo_fetiche(conn, modelo_id=modelo_id, fetiche_id=fetiche_id, pago=True)

    with pytest.raises(ConflitoEstado) as exc_info:
        await adicionar_fetiche(
            atendimento_id, AdicionarFeticheRequest(fetiche_id=fetiche_id), conn
        )

    assert exc_info.value.code == "CONFLITO_ESTADO"
    assert exc_info.value.message == "nenhum_servico_vendido"


# --- rastro do fetiche no fechamento (pendência 4 do ADR-0030) -------------------------------
#
# A IA não escreve em `atendimento_fetiches` (a tabela era painel-only): ela registra os nomes em
# `fetiches_em_pauta`, que ficam no payload do evento `extracao_registrada`, e o fechamento
# (`aplicar_comando(registrar_fechado)`) materializa as linhas. Estes testes exercitam o SQL de
# verdade — o operador jsonb, a UNIQUE + ON CONFLICT e a resolução contra o cadastro da modelo.


async def _seed_fetiche_nomeado(
    c: AsyncConnection[dict[str, Any]], nome: str, *, cobra_por_pessoa: bool = False
) -> UUID:
    fetiche_id = uuid4()
    await c.execute(
        "INSERT INTO barravips.fetiches (id, nome, cobra_por_pessoa) VALUES (%s, %s, %s)",
        (fetiche_id, nome, cobra_por_pessoa),
    )
    return fetiche_id


async def _seed_extracao_em_pauta(
    c: AsyncConnection[dict[str, Any]], atendimento_id: UUID, nomes: list[str]
) -> None:
    await c.execute(
        """
        INSERT INTO barravips.eventos (atendimento_id, tipo, origem, autor, payload)
        VALUES (%s, 'extracao_registrada', 'agente', 'IA', %s::jsonb)
        """,
        (atendimento_id, json.dumps({"fetiches_em_pauta": nomes})),
    )


async def _fetiches_do_atendimento(
    c: AsyncConnection[dict[str, Any]], atendimento_id: UUID
) -> list[dict[str, Any]]:
    res = await c.execute(
        """
        SELECT f.nome, atf.preco_snapshot
          FROM barravips.atendimento_fetiches atf
          JOIN barravips.fetiches f ON f.id = atf.fetiche_id
         WHERE atf.atendimento_id = %s
         ORDER BY atf.created_at
        """,
        (atendimento_id,),
    )
    return await res.fetchall()


async def _fechar(c: AsyncConnection[dict[str, Any]], atendimento_id: UUID) -> None:
    await aplicar_comando(
        c,
        origem="painel",
        autor="Fernando",
        atendimento_id=atendimento_id,
        comando="registrar_fechado",
        payload={"valor_final": Decimal("800")},
    )


@pytest.mark.needs_db
async def test_fechamento_grava_o_extra_com_preco_cadastrado(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Preço real na coluna (>= o piso do sentinel) é a fonte de verdade do extra: R$350 fixos,
    independentes do pacote de R$800/1h que o cliente fechou."""
    atendimento_id, modelo_id = await _setup_atendimento(conn)
    nome = f"Inversão {uuid4().hex[:8]}"
    fetiche_id = await _seed_fetiche_nomeado(conn, nome)
    await conn.execute(
        "INSERT INTO barravips.modelo_fetiches (modelo_id, fetiche_id, preco) VALUES (%s, %s, %s)",
        (modelo_id, fetiche_id, Decimal("350")),
    )
    await conn.execute(
        "UPDATE barravips.atendimentos SET valor_acordado = 800, duracao_horas = 1 WHERE id = %s",
        (atendimento_id,),
    )
    # O extrator escreve sem acento/caixa; o cadastro tem o nome bonito.
    await _seed_extracao_em_pauta(conn, atendimento_id, [nome.lower()])

    await _fechar(conn, atendimento_id)

    assert await _fetiches_do_atendimento(conn, atendimento_id) == [
        {"nome": nome, "preco_snapshot": Decimal("350.00")}
    ]


@pytest.mark.needs_db
async def test_fechamento_descarta_nome_fora_do_cadastro_e_nao_duplica(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Closed-world + idempotência num teste só: o nome alucinado não vira linha, e a correção
    de registro (que refecha o atendimento) não duplica o que já está lá."""
    atendimento_id, modelo_id = await _setup_atendimento(conn)
    nome = f"Beijo na boca {uuid4().hex[:8]}"
    fetiche_id = await _seed_fetiche_nomeado(conn, nome)
    await conn.execute(
        "INSERT INTO barravips.modelo_fetiches (modelo_id, fetiche_id, preco) VALUES (%s, %s, NULL)",
        (modelo_id, fetiche_id),
    )
    await _seed_extracao_em_pauta(conn, atendimento_id, [nome, "Fetiche Que Ela Nao Faz"])

    await _fechar(conn, atendimento_id)
    # Refecha via correção de registro (Fechado -> Perdido -> Fechado passa pelo mesmo rastro).
    await aplicar_comando(
        conn,
        origem="painel",
        autor="Fernando",
        atendimento_id=atendimento_id,
        comando="corrigir_registro",
        payload={"novo_resultado": "Perdido", "motivo": "sumiu"},
    )
    await aplicar_comando(
        conn,
        origem="painel",
        autor="Fernando",
        atendimento_id=atendimento_id,
        comando="corrigir_registro",
        payload={"novo_resultado": "Fechado", "valor_final": Decimal("800")},
    )

    # Incluso = snapshot NULL; o nome fora do cadastro sumiu; uma linha só.
    assert await _fetiches_do_atendimento(conn, atendimento_id) == [
        {"nome": nome, "preco_snapshot": None}
    ]


@pytest.mark.needs_db
async def test_fechamento_sem_slot_nao_grava_nada(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    atendimento_id, modelo_id = await _setup_atendimento(conn)
    fetiche_id = await _seed_fetiche_nomeado(conn, f"Chuva dourada {uuid4().hex[:8]}")
    await _seed_modelo_fetiche(conn, modelo_id=modelo_id, fetiche_id=fetiche_id, pago=True)

    await _fechar(conn, atendimento_id)

    assert await _fetiches_do_atendimento(conn, atendimento_id) == []


# --- fallback derivado: a base é o PREÇO DE TABELA, nunca o Valor final ----------------------


async def _seed_modelo_programa(
    c: AsyncConnection[dict[str, Any]],
    *,
    modelo_id: UUID,
    programa_id: UUID,
    duracao_id: UUID,
    preco: Decimal,
) -> None:
    await c.execute(
        """
        INSERT INTO barravips.modelo_programas (modelo_id, programa_id, duracao_id, preco)
        VALUES (%s, %s, %s, %s)
        """,
        (modelo_id, programa_id, duracao_id, preco),
    )


@pytest.mark.needs_db
async def test_fechamento_deriva_o_extra_do_preco_de_tabela_e_nao_do_valor_final(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """O caso motivador do ADR-0030, agora pelo SQL de verdade.

    O cliente fechou R$800 = pacote de R$400 (1h) + o extra. `valor_acordado` é o Valor FINAL:
    usá-lo como base do extra derivado devolveria R$800 — o extra "comendo" o pacote inteiro.
    A base tem de sair de `modelo_programas` pela duração fechada: R$400.
    """
    atendimento_id, modelo_id = await _setup_atendimento(conn)
    nome = f"Ménage {uuid4().hex[:8]}"
    fetiche_id = await _seed_fetiche_nomeado(conn, nome, cobra_por_pessoa=True)
    # Sentinel legado (`preco` < o piso): "pago" sem valor -> cai no fallback derivado.
    await _seed_modelo_fetiche(conn, modelo_id=modelo_id, fetiche_id=fetiche_id, pago=True)
    await _seed_modelo_programa(
        conn,
        modelo_id=modelo_id,
        programa_id=await _programa_id_qualquer(conn),
        duracao_id=await _duracao_id_por_horas(conn, "1"),
        preco=Decimal("400"),
    )
    await conn.execute(
        "UPDATE barravips.atendimentos SET valor_acordado = 800, duracao_horas = 1 WHERE id = %s",
        (atendimento_id,),
    )
    await _seed_extracao_em_pauta(conn, atendimento_id, [nome])

    await _fechar(conn, atendimento_id)

    # O extra é a linha de 1h da TABELA: 400. Nunca 800 (o Valor final).
    assert await _fetiches_do_atendimento(conn, atendimento_id) == [
        {"nome": nome, "preco_snapshot": Decimal("400.00")}
    ]


@pytest.mark.needs_db
async def test_fechamento_sem_programa_na_duracao_descarta_o_fetiche(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Fail-closed: a modelo não tem programa na duração fechada, então não há preço de tabela
    para derivar. Gravar NULL diria "incluso" (falso) e gravar o Valor final mentiria o extra —
    a linha fica de fora, só o warning."""
    atendimento_id, modelo_id = await _setup_atendimento(conn)
    nome = f"Inversão {uuid4().hex[:8]}"
    fetiche_id = await _seed_fetiche_nomeado(conn, nome)
    await _seed_modelo_fetiche(conn, modelo_id=modelo_id, fetiche_id=fetiche_id, pago=True)
    await conn.execute(
        "UPDATE barravips.atendimentos SET valor_acordado = 800, duracao_horas = 1 WHERE id = %s",
        (atendimento_id,),
    )
    await _seed_extracao_em_pauta(conn, atendimento_id, [nome])

    await _fechar(conn, atendimento_id)

    assert await _fetiches_do_atendimento(conn, atendimento_id) == []
