"""ADR-0049 §5 / ticket 05 — o alarme fala UMA vez; a repeticao vira fila no painel.

O que este arquivo prova, ponta a ponta (grupo real -> banco -> HTTP do painel):

1. Destino desconhecido aparecendo pela PRIMEIRA vez continua avisando no grupo — e o unico caso
   que merece alarme imediato.
2. A MESMA chave de novo nao repete o ⚠️. A operacao nao muda em nada: o abate acontece igual, a
   linha e gravada igual, a metrica conta igual. So a fala some.
3. Do segundo aparecimento em diante ela entra na fila de sugestoes, com contagem e periodo.
4. Classificar pelo painel some com a sugestao e passa a valer no papel NA HORA — porque a fila e
   uma consulta sobre `comprovantes_do_grupo`, nao uma tabela que alguem precisa invalidar.
5. Sugestao nunca vira cadastro sozinha: ler a fila cem vezes nao escreve uma linha.

`needs_db` com `TEST_DATABASE_URL` + ROLLBACK sempre.
"""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_asyncio
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from barra.agente_financeiro import ResultadoDaPorta, processar_mensagem_do_grupo
from barra.api.deps import get_conn
from barra.dominio.grupo_financeiro.comprovante import LeituraDoComprovante, normalizar_chave
from barra.dominio.grupo_financeiro.modelos import ImagemDoGrupo, MensagemDoGrupo
from barra.main import app

pytestmark = pytest.mark.needs_db

AVISO = "fora da lista da casa"
ANUNCIO = "Atendimento no nosso local \nCliente {cliente} \nPerfil {apelido} \n600 1h"
NOITE_DE_12_08 = datetime(2026, 8, 13, 1, 0, tzinfo=UTC)


def _uma_chave_nova() -> str:
    """Cada teste inventa a sua: a contagem de "quantas vezes este destino ja apareceu" e GLOBAL,
    e uma chave fixa herdaria as linhas ja commitadas no banco de teste."""
    return f"agiota{uuid4().hex[:10]}@pix.example"


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


def _token() -> dict[str, str]:
    return {"Authorization": f"Bearer test:{uuid4()}:fernando:true"}


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
    def __init__(self, modelo_id: UUID, jid: str, apelido: str, nome: str) -> None:
        self.modelo_id = modelo_id
        self.jid = jid
        self.apelido = apelido
        self.nome = nome
        self.relogio = NOITE_DE_12_08


async def _montar_grupo(c: AsyncConnection[dict[str, Any]], *, limpar: bool = True) -> _Grupo:
    modelo_id = uuid4()
    apelido = f"bianca{uuid4().hex[:8]}"
    nome = f"Yasmin {uuid4().hex[:6]}"
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
            nome,
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
    if limpar:
        await c.execute("DELETE FROM barravips.chaves_pix_conhecidas")
    return _Grupo(modelo_id, jid, apelido, nome)


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
    # Cliente diferente a cada venda: o anuncio identico e recusado como duplicata pelo hash de
    # conteudo, e o que este arquivo repete e o DESTINO do comprovante, nao o anuncio.
    texto = ANUNCIO.format(cliente=f"Ramon {uuid4().hex[:6]}", apelido=grupo.apelido)
    lancou = await _dizer(c, grupo, texto, falas=falas)
    (venda_id,) = lancou.vendas
    pago = await _dizer(c, grupo, "Pix", falas=falas)
    assert pago.pagamentos == (venda_id,)
    return venda_id


async def _postar_comprovante(
    c: AsyncConnection[dict[str, Any]],
    grupo: _Grupo,
    chave: str,
    *,
    falas: _Falas,
    titular: str | None = None,
) -> ResultadoDaPorta:
    """Uma foto DIFERENTE a cada post — o dedup por conteudo recusa a mesma imagem duas vezes, e
    o que este arquivo mede e a repeticao do DESTINO, nao a da foto."""
    grupo.relogio += timedelta(minutes=5)
    imagem = b"\xff\xd8\xff" + uuid4().bytes + b"\x00" * 48
    leitura = LeituraDoComprovante(
        e_comprovante=True,
        legivel=True,
        valor=Decimal("600.00"),
        data=date(2026, 8, 12),
        pagador=grupo.nome.upper(),
        chave_destino=chave,
        titular_destino=titular,
    )
    msg = MensagemDoGrupo(
        grupo_jid=grupo.jid,
        texto="",
        tipo="imagem",
        imagem=ImagemDoGrupo(imagem, mimetype="image/jpeg"),
        recebida_em=grupo.relogio,
        evolution_message_id=f"3EB0{uuid4().hex[:12]}",
        autor_nome="Yasmin",
        autor_jid="5571988887777@s.whatsapp.net",
    )
    return await processar_mensagem_do_grupo(c, msg, enviar=falas, ler_comprovante=_Olho(leitura))


async def _comprovantes(c: AsyncConnection[dict[str, Any]], grupo: _Grupo) -> list[dict[str, Any]]:
    cur = await c.execute(
        """
        SELECT co.classificacao::text AS classificacao, co.chave_conhecida, co.chave_destino
          FROM barravips.comprovantes_do_grupo co
          JOIN barravips.grupos_financeiros g ON g.id = co.grupo_id
         WHERE g.jid = %s
         ORDER BY co.created_at
        """,
        (grupo.jid,),
    )
    return [dict(r) for r in await cur.fetchall()]


async def _sugestoes(c: AsyncConnection[dict[str, Any]], chave: str) -> list[dict[str, Any]]:
    """A fila do painel, pela API real — filtrada pela chave deste teste, porque a rota devolve o
    banco inteiro e o `barra_test` tem linhas commitadas de outras suites."""
    alvo = normalizar_chave(chave)
    async with _painel(c) as painel:
        r = await painel.get("/v1/financeiro/chaves-pix/sugestoes", headers=_token())
    assert r.status_code == 200, r.text
    return [s for s in r.json()["items"] if s["chave_normalizada"] == alvo]


async def _quantas_chaves_cadastradas(c: AsyncConnection[dict[str, Any]]) -> int:
    cur = await c.execute("SELECT count(*) AS n FROM barravips.chaves_pix_conhecidas")
    linha = await cur.fetchone()
    assert linha is not None
    return int(linha["n"])


# --- 1. o alarme no grupo -----------------------------------------------------------------------


async def test_a_primeira_vez_continua_avisando_no_grupo(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Destino desconhecido recebendo dinheiro de venda pela primeira vez e o caso que merece
    alarme imediato — e ele nao mudou."""
    falas = _Falas()
    grupo = await _montar_grupo(conn)
    chave = _uma_chave_nova()
    await _uma_venda_em_pix(conn, grupo, falas=falas)

    conferiu = await _postar_comprovante(conn, grupo, chave, falas=falas)

    assert conferiu.motivo == "comprovante_conciliado"
    assert AVISO in falas.ultima
    assert chave in falas.ultima


async def test_a_repeticao_do_mesmo_destino_nao_repete_o_aviso(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """O criterio central. E o que NAO muda importa tanto quanto o que muda: o abate continua
    acontecendo e a linha continua sendo gravada com `chave_conhecida = false` — o que some e a
    fala que treinou o gestor a ignorar o ⚠️."""
    falas = _Falas()
    grupo = await _montar_grupo(conn)
    chave = _uma_chave_nova()
    await _uma_venda_em_pix(conn, grupo, falas=falas)
    await _postar_comprovante(conn, grupo, chave, falas=falas)
    assert AVISO in falas.ultima

    await _uma_venda_em_pix(conn, grupo, falas=falas)
    segundo = await _postar_comprovante(conn, grupo, chave, falas=falas)

    assert AVISO not in falas.ultima
    assert falas.ultima.startswith("✅ Comprovante conferido")
    assert segundo.motivo == "comprovante_conciliado"
    assert len(segundo.abatidas) == 1
    linhas = await _comprovantes(conn, grupo)
    assert [linha["chave_conhecida"] for linha in linhas] == [False, False]


async def test_a_mesma_chave_com_outra_pontuacao_tambem_nao_repete(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """O OCR le a grafia da tela do banco, e ela varia entre duas fotos do mesmo destino. Comparar
    literal faria o alarme voltar a cada leitura diferente da MESMA conta."""
    falas = _Falas()
    grupo = await _montar_grupo(conn)
    sufixo = uuid4().hex[:8]
    await _uma_venda_em_pix(conn, grupo, falas=falas)
    await _postar_comprovante(conn, grupo, f"+55 71 9{sufixo} 0879", falas=falas)
    assert AVISO in falas.ultima

    await _uma_venda_em_pix(conn, grupo, falas=falas)
    await _postar_comprovante(conn, grupo, f"+55719{sufixo}0879", falas=falas)

    assert AVISO not in falas.ultima


async def test_um_destino_novo_volta_a_avisar(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """A defesa contra o excesso: silenciar a chave repetida NAO pode silenciar a proxima chave
    nova. Se silenciasse, o ticket teria trocado ruido por cegueira."""
    falas = _Falas()
    grupo = await _montar_grupo(conn)
    await _uma_venda_em_pix(conn, grupo, falas=falas)
    await _postar_comprovante(conn, grupo, _uma_chave_nova(), falas=falas)
    await _uma_venda_em_pix(conn, grupo, falas=falas)
    await _postar_comprovante(conn, grupo, _uma_chave_nova(), falas=falas)

    assert AVISO in falas.ultima


async def test_a_chave_cadastrada_da_casa_nunca_avisou_e_continua_calada(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Linha de base preservada: destino da casa e o caminho silencioso de sempre."""
    falas = _Falas()
    grupo = await _montar_grupo(conn)
    chave = _uma_chave_nova()
    await conn.execute(
        """
        INSERT INTO barravips.chaves_pix_conhecidas (chave, chave_normalizada, papel, titular)
        VALUES (%s, %s, 'casa'::barravips.papel_da_chave_enum, %s)
        """,
        (chave, normalizar_chave(chave), "Elite Servicos Ltda"),
    )
    await _uma_venda_em_pix(conn, grupo, falas=falas)

    await _postar_comprovante(conn, grupo, chave, falas=falas)

    assert "⚠️" not in falas.ultima


# --- 2. a fila de sugestoes ---------------------------------------------------------------------


async def test_a_primeira_aparicao_nao_entra_na_fila(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Ela ja teve o alarme. A fila e para a chave que voltou."""
    falas = _Falas()
    grupo = await _montar_grupo(conn)
    chave = _uma_chave_nova()
    await _uma_venda_em_pix(conn, grupo, falas=falas)
    await _postar_comprovante(conn, grupo, chave, falas=falas)

    assert await _sugestoes(conn, chave) == []


async def test_do_segundo_aparecimento_ela_entra_com_contagem_e_periodo(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """A informacao nao sumiu com o silencio no grupo: ela mudou de canal, e no painel vem com
    contagem, periodo, valor e de quem ela recebeu."""
    falas = _Falas()
    grupo = await _montar_grupo(conn)
    chave = _uma_chave_nova()
    for _ in range(2):
        await _uma_venda_em_pix(conn, grupo, falas=falas)
        await _postar_comprovante(conn, grupo, chave, falas=falas, titular="Erick de Melo")

    (sugerida,) = await _sugestoes(conn, chave)

    assert sugerida["vezes"] == 2
    assert sugerida["chave"] == chave
    assert sugerida["titulares"] == ["Erick de Melo"]
    assert sugerida["valor_total_brl"] == 1200.00
    assert [m["nome"] for m in sugerida["modelos"]] == [grupo.nome]
    assert sugerida["modelo_id_sugerido"] == str(grupo.modelo_id)
    assert sugerida["pergunta"].startswith("Apareceu 2 vezes")
    assert sugerida["pergunta"].endswith("— de quem é?")


async def test_a_mesma_chave_em_dois_grupos_conta_as_duas_modelos(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """A mesma chave desconhecida recebendo de duas modelos e outra conversa — e o painel e o
    unico lugar onde essa leitura existe, porque cada grupo so ve o proprio comprovante.

    O aviso tambem nao se repete entre grupos: a contagem e por CHAVE. Repetir o ⚠️ so porque a
    segunda foto veio noutro grupo devolveria o alarme que o ticket veio calar — e o gestor que
    o le e o mesmo nos dois."""
    falas = _Falas()
    yasmin = await _montar_grupo(conn)
    bianca = await _montar_grupo(conn, limpar=False)
    chave = _uma_chave_nova()
    await _uma_venda_em_pix(conn, yasmin, falas=falas)
    await _postar_comprovante(conn, yasmin, chave, falas=falas)
    assert AVISO in falas.ultima

    await _uma_venda_em_pix(conn, bianca, falas=falas)
    await _postar_comprovante(conn, bianca, chave, falas=falas)

    assert AVISO not in falas.ultima
    (sugerida,) = await _sugestoes(conn, chave)
    assert sugerida["vezes"] == 2
    assert sorted(m["nome"] for m in sugerida["modelos"]) == sorted([yasmin.nome, bianca.nome])
    assert sugerida["modelo_id_sugerido"] is None
    assert "recebendo de 2 modelos" in sugerida["pergunta"]


async def test_ler_a_fila_nao_cadastra_nada(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """ "Sugestao nunca vira cadastro sozinha" (criterio do ticket): a rota e somente leitura, e
    nao existe caminho que promova uma sugestao a linha sem um humano escolher o papel."""
    falas = _Falas()
    grupo = await _montar_grupo(conn)
    chave = _uma_chave_nova()
    for _ in range(3):
        await _uma_venda_em_pix(conn, grupo, falas=falas)
        await _postar_comprovante(conn, grupo, chave, falas=falas)

    assert len(await _sugestoes(conn, chave)) == 1
    assert len(await _sugestoes(conn, chave)) == 1
    assert await _quantas_chaves_cadastradas(conn) == 0


# --- 3. classificar resolve, e resolve na hora --------------------------------------------------


async def test_classificar_pelo_painel_some_com_a_sugestao_e_vale_na_hora(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """O criterio que amarra os dois lados. A fila e DERIVADA de `comprovantes_do_grupo`, entao
    cadastrar e o proprio gesto que tira a linha dela — nao ha invalidacao a esquecer.

    E o papel vale no comprovante SEGUINTE, sem cache: o cenario e o do dono na ata ("a gente pode
    ter umas cinco" chaves da casa) — a sexta chave que ninguem tinha cadastrado aparece na fila,
    o gestor responde "essa e nossa", e o proximo comprovante ja fecha calado, com
    `chave_conhecida = true`."""
    falas = _Falas()
    grupo = await _montar_grupo(conn)
    chave = _uma_chave_nova()
    for _ in range(2):
        await _uma_venda_em_pix(conn, grupo, falas=falas)
        await _postar_comprovante(conn, grupo, chave, falas=falas)
    assert len(await _sugestoes(conn, chave)) == 1

    async with _painel(conn) as painel:
        criada = await painel.post(
            "/v1/financeiro/chaves-pix",
            headers=_token(),
            json={"chave": chave, "papel": "casa", "titular": "Elite Servicos Ltda"},
        )
    assert criada.status_code == 201, criada.text

    assert await _sugestoes(conn, chave) == []
    await _uma_venda_em_pix(conn, grupo, falas=falas)
    await _postar_comprovante(conn, grupo, chave, falas=falas)

    assert "⚠️" not in falas.ultima
    assert [linha["chave_conhecida"] for linha in await _comprovantes(conn, grupo)] == [
        False,
        False,
        True,
    ]


async def test_classificar_como_modelo_troca_o_alarme_pela_atribuicao(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """A outra resposta possivel — "essa e a conta dela". O ⚠️ generico morre e a fala vira a
    ATRIBUICAO do dinheiro, que continua saindo em TODO comprovante: ela nao e alarme (nada a
    apurar), e dizer de qual venda a casa nao recebeu vale uma vez por venda, nao uma vez por
    chave."""
    falas = _Falas()
    grupo = await _montar_grupo(conn)
    chave = _uma_chave_nova()
    for _ in range(2):
        await _uma_venda_em_pix(conn, grupo, falas=falas)
        await _postar_comprovante(conn, grupo, chave, falas=falas)

    async with _painel(conn) as painel:
        criada = await painel.post(
            "/v1/financeiro/chaves-pix",
            headers=_token(),
            json={"chave": chave, "papel": "modelo", "modelo_id": str(grupo.modelo_id)},
        )
    assert criada.status_code == 201, criada.text

    assert await _sugestoes(conn, chave) == []
    for _ in range(2):
        await _uma_venda_em_pix(conn, grupo, falas=falas)
        await _postar_comprovante(conn, grupo, chave, falas=falas)
        assert AVISO not in falas.ultima
        assert "chave da própria modelo" in falas.ultima


async def test_classificar_como_terceiro_tambem_encerra_a_pergunta(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """O agiota do exemplo do dono: legitimo, de ninguem do sistema. `terceiro` existe para PARAR
    de perguntar — e nao para dizer de quem e o dinheiro."""
    falas = _Falas()
    grupo = await _montar_grupo(conn)
    chave = _uma_chave_nova()
    for _ in range(2):
        await _uma_venda_em_pix(conn, grupo, falas=falas)
        await _postar_comprovante(conn, grupo, chave, falas=falas)

    async with _painel(conn) as painel:
        criada = await painel.post(
            "/v1/financeiro/chaves-pix",
            headers=_token(),
            json={"chave": chave, "papel": "terceiro", "titular": "Erick de Melo"},
        )
    assert criada.status_code == 201, criada.text

    assert await _sugestoes(conn, chave) == []


async def test_inativar_a_chave_nao_ressuscita_a_sugestao(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Inativar nunca deletar: a conta desligada tem dono e continua explicando comprovante
    antigo. Voltar a sugeri-la seria pedir ao gestor que classificasse duas vezes a mesma conta."""
    falas = _Falas()
    grupo = await _montar_grupo(conn)
    chave = _uma_chave_nova()
    for _ in range(2):
        await _uma_venda_em_pix(conn, grupo, falas=falas)
        await _postar_comprovante(conn, grupo, chave, falas=falas)

    async with _painel(conn) as painel:
        criada = await painel.post(
            "/v1/financeiro/chaves-pix",
            headers=_token(),
            json={"chave": chave, "papel": "terceiro"},
        )
        assert criada.status_code == 201, criada.text
        inativou = await painel.patch(
            f"/v1/financeiro/chaves-pix/{criada.json()['id']}",
            headers=_token(),
            json={"ativo": False},
        )
    assert inativou.status_code == 200, inativou.text

    assert await _sugestoes(conn, chave) == []
