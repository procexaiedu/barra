"""O Vale dito no grupo (spec 0006, ticket 15) — pela PORTA ÚNICA, com banco.

O gesto é o da reunião de 20/08: *"tem que pagar uma conta de 500 reais, eu adianto"*. Até aqui o
adiantamento só existia se alguém abrisse o painel (ticket 05); dito no grupo, ele sumia — e o
saldo da temporada fechava sem ele, que é a diferença entre estar certo e estar mais ou menos
certo.

O que este arquivo guarda, e nenhuma linha dele o banco pode provar de outro jeito:

* o vale nasce com `origem = 'grupo'` e `mensagem_id` (o CHECK do banco exige o par) — e é essa
  coluna que o extrato do painel mostra para distinguir o que o gestor digitou do que o agente
  leu numa conversa;
* o **repost cai no dedup** por chave de conteúdo e o agente avisa, em vez de dobrar o débito;
* o recibo é **corrigível por quote**, com de→para — inclusive citando o recibo, que é o segundo
  salto que só existe porque a fala do agente está no log;
* a leitura **hesitante não grava nada** e vira pergunta; a resposta ("500") lança o vale com a
  data da DECLARAÇÃO, e não a do dia em que alguém respondeu;
* apagar a fala **anula** o vale — e não alcança o que nasceu no painel;
* vale e **Cobrança da agência** não se confundem em nenhuma direção: nenhum dos dois cria linha
  na tabela do outro.

`needs_db` com `TEST_DATABASE_URL` + ROLLBACK sempre: o dedup por chave viva, o CHECK
`razao_lancamentos_manuais_grupo_tem_mensagem` e a FK da mensagem são garantias do BANCO.

⚠️ Este arquivo lê e escreve em `barravips.razao_lancamentos_manuais`, da onda de migrations
`20260820*`, **escrita e ainda não aplicada**. Sem a migration ele falha com erro de SQL — de
propósito: não há caminho degradado.
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

from barra.agente_financeiro import ResultadoDaPorta, processar_evento_do_grupo
from barra.dominio.grupo_financeiro.modelos import DelecaoNoGrupo, MensagemDoGrupo
from barra.dominio.grupo_financeiro.repo import (
    cobrancas_abertas_da_modelo,
    lancamentos_manuais_da_modelo,
)

pytestmark = pytest.mark.needs_db

VALE = "adiantei 500 pra ela"
COBRANCA = "*3RJ Suporte/Anúncio:*\n3 DIAS | R$ 385,80\nEnvia para o site e envia o comprovante"

# 20/08 22:00 UTC = 20/08 19:00 em Brasília.
NOITE_DE_20_08 = datetime(2026, 8, 20, 22, 0, tzinfo=UTC)
DIA_20_08 = date(2026, 8, 20)


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
    """O que o agente postou no grupo. Coleta em vez de ir à rede."""

    def __init__(self) -> None:
        self.enviadas: list[str] = []

    async def __call__(self, texto: str, *, citar: str | None = None) -> None:
        self.enviadas.append(texto)

    @property
    def ultima(self) -> str | None:
        return self.enviadas[-1] if self.enviadas else None


class _Grupo:
    def __init__(self, modelo_id: UUID, jid: str) -> None:
        self.modelo_id = modelo_id
        self.jid = jid
        self.relogio = NOITE_DE_20_08


async def _montar_grupo(c: AsyncConnection[dict[str, Any]]) -> _Grupo:
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
            f"test-wpp-{uuid4().hex}",
            600,
            ["interno"],
            Decimal("50"),
        ),
    )
    jid = f"1203634{uuid4().hex[:12]}@g.us"
    await c.execute(
        """
        INSERT INTO barravips.grupos_financeiros (id, modelo_id, jid, nome)
        VALUES (%s, %s, %s, %s)
        """,
        (uuid4(), modelo_id, jid, "Modelo Yasmin Ruiva/financeiro"),
    )
    return _Grupo(modelo_id, jid)


async def _dizer(
    c: AsyncConnection[dict[str, Any]],
    grupo: _Grupo,
    texto: str,
    *,
    falas: _Falas,
    depois: timedelta = timedelta(seconds=30),
    **kw: Any,
) -> ResultadoDaPorta:
    """O gestor digita no grupo — é ele quem adianta dinheiro."""
    grupo.relogio += depois
    kw.setdefault("evolution_message_id", f"3EB0{uuid4().hex[:12]}")
    kw.setdefault("autor_nome", "Parcerias")
    kw.setdefault("autor_jid", "5521966666666@s.whatsapp.net")
    msg = MensagemDoGrupo(grupo_jid=grupo.jid, texto=texto, recebida_em=grupo.relogio, **kw)
    return await processar_evento_do_grupo(c, msg, enviar=falas)


async def _ecoar(
    c: AsyncConnection[dict[str, Any]],
    grupo: _Grupo,
    resultado: ResultadoDaPorta,
    *,
    falas: _Falas,
    citando: str,
) -> str:
    """O recibo volta pelo webhook como mensagem `de_mim` citando a fala — como em produção.

    Sem este eco o quote NO RECIBO não teria como ser resolvido: o segundo salto (recibo → fala do
    gestor) só existe porque a mensagem do agente está no log com o `quoted_message_id` dela.
    """
    assert resultado.resposta is not None
    recibo_id = f"3EB0{uuid4().hex[:12]}"
    await _dizer(
        c,
        grupo,
        resultado.resposta,
        falas=falas,
        de_mim=True,
        evolution_message_id=recibo_id,
        quoted_message_id=citando,
        depois=timedelta(seconds=2),
    )
    return recibo_id


# --- o vale nasce da fala -------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_adiantei_500_pra_ela_lanca_o_vale_e_emite_recibo(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    grupo = await _montar_grupo(conn)
    falas = _Falas()

    resultado = await _dizer(conn, grupo, VALE, falas=falas)

    assert resultado.motivo == "vale_registrado"
    assert len(resultado.vales) == 1
    assert falas.ultima is not None
    assert falas.ultima.startswith("💸 Registrei o vale: R$ 500,00")

    lancamentos = await lancamentos_manuais_da_modelo(conn, grupo.modelo_id)
    assert len(lancamentos) == 1
    vale = lancamentos[0]
    assert vale.tipo == "vale"
    assert vale.sentido == "debito"
    assert vale.valor == Decimal("500.00")
    assert vale.data == DIA_20_08
    assert vale.descricao == VALE


@pytest.mark.asyncio
async def test_o_vale_do_grupo_guarda_a_origem_e_a_mensagem_fonte(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """`origem='grupo'` é o que o extrato do painel mostra ao lado do vale digitado à mão.

    O par `origem`/`mensagem_id` é exigido pelo CHECK `..._grupo_tem_mensagem`: um vale de origem
    `grupo` sem a fala que o declarou seria um débito sem nada para conferir contra.
    """
    grupo = await _montar_grupo(conn)
    falas = _Falas()

    resultado = await _dizer(conn, grupo, VALE, falas=falas)

    vale = (await lancamentos_manuais_da_modelo(conn, grupo.modelo_id))[0]
    assert vale.origem == "grupo"
    assert vale.mensagem_id == resultado.mensagem_id


@pytest.mark.asyncio
async def test_o_repost_da_mesma_fala_nao_dobra_o_debito(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    grupo = await _montar_grupo(conn)
    falas = _Falas()

    await _dizer(conn, grupo, VALE, falas=falas)
    repost = await _dizer(conn, grupo, VALE, falas=falas)

    assert repost.motivo == "vale_duplicado"
    assert repost.vales == ()
    assert falas.ultima is not None
    assert falas.ultima.startswith("♻️ Esse vale já estava registrado")
    assert len(await lancamentos_manuais_da_modelo(conn, grupo.modelo_id)) == 1


# --- o recibo é corrigível por quote ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_o_recibo_do_vale_e_corrigivel_por_quote_com_de_para(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    grupo = await _montar_grupo(conn)
    falas = _Falas()

    fala_id = f"3EB0{uuid4().hex[:12]}"
    registro = await _dizer(conn, grupo, VALE, falas=falas, evolution_message_id=fala_id)
    recibo_id = await _ecoar(conn, grupo, registro, falas=falas, citando=fala_id)

    correcao = await _dizer(conn, grupo, "foi 600", falas=falas, quoted_message_id=recibo_id)

    assert correcao.motivo == "vale_corrigido"
    assert correcao.vales_corrigidos == registro.vales
    assert (
        falas.ultima == "✏️ Corrigi: valor R$ 500,00 → R$ 600,00 — corrige aí se algo estiver errado"
    )

    vale = (await lancamentos_manuais_da_modelo(conn, grupo.modelo_id))[0]
    assert vale.valor == Decimal("600.00")


@pytest.mark.asyncio
async def test_corrigir_para_o_mesmo_valor_nao_ecoa_nada(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Não houve evento — e dizer "corrigi" a uma correção que não corrigiu nada é pior que calar."""
    grupo = await _montar_grupo(conn)
    falas = _Falas()

    fala_id = f"3EB0{uuid4().hex[:12]}"
    registro = await _dizer(conn, grupo, VALE, falas=falas, evolution_message_id=fala_id)
    recibo_id = await _ecoar(conn, grupo, registro, falas=falas, citando=fala_id)
    antes = len(falas.enviadas)

    correcao = await _dizer(conn, grupo, "foi 500", falas=falas, quoted_message_id=recibo_id)

    assert correcao.motivo == "vale_correcao_sem_efeito"
    assert len(falas.enviadas) == antes


# --- confiança baixa não lança ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_adiantamento_sem_valor_pergunta_e_nao_grava(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    grupo = await _montar_grupo(conn)
    falas = _Falas()

    resultado = await _dizer(conn, grupo, "adiantei pra ela", falas=falas)

    assert resultado.motivo == "vale_incompleto"
    assert resultado.vales == ()
    assert falas.ultima == "❓ Só falta saber: quanto foi o adiantamento?"
    assert await lancamentos_manuais_da_modelo(conn, grupo.modelo_id) == []


@pytest.mark.asyncio
async def test_a_resposta_a_pergunta_lanca_o_vale_datado_da_declaracao(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """O adiantamento aconteceu quando o gestor disse — não no dia em que alguém respondeu.

    A mesma disciplina do anúncio, que nasce datado do anúncio e não do "600" que o completou.
    """
    grupo = await _montar_grupo(conn)
    falas = _Falas()

    pergunta_do_agente = await _dizer(conn, grupo, "adiantei pra ela", falas=falas)
    assert pergunta_do_agente.resposta is not None
    await _dizer(
        conn,
        grupo,
        pergunta_do_agente.resposta,
        falas=falas,
        de_mim=True,
        depois=timedelta(seconds=2),
    )

    # Sete horas depois: já é o dia seguinte em Brasília.
    resultado = await _dizer(conn, grupo, "500", falas=falas, depois=timedelta(hours=7))

    assert resultado.motivo == "vale_registrado"
    vale = (await lancamentos_manuais_da_modelo(conn, grupo.modelo_id))[0]
    assert vale.valor == Decimal("500.00")
    assert vale.data == DIA_20_08
    assert vale.descricao == "adiantei pra ela"


@pytest.mark.asyncio
async def test_um_numero_solto_sem_pergunta_do_vale_nao_vira_adiantamento(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """A guarda que impede o "500" de qualquer conversa virar débito no nome dela."""
    grupo = await _montar_grupo(conn)
    falas = _Falas()

    resultado = await _dizer(conn, grupo, "500", falas=falas)

    assert resultado.vales == ()
    assert await lancamentos_manuais_da_modelo(conn, grupo.modelo_id) == []


# --- apagar a fala anula o vale --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apagar_a_fala_anula_o_vale(conn: AsyncConnection[dict[str, Any]]) -> None:
    grupo = await _montar_grupo(conn)
    falas = _Falas()

    fala_id = f"3EB0{uuid4().hex[:12]}"
    registro = await _dizer(conn, grupo, VALE, falas=falas, evolution_message_id=fala_id)

    grupo.relogio += timedelta(seconds=30)
    delecao = await processar_evento_do_grupo(
        conn,
        DelecaoNoGrupo(
            grupo_jid=grupo.jid,
            evolution_message_id=fala_id,
            autor_jid="5521966666666@s.whatsapp.net",
            ocorrida_em=grupo.relogio,
        ),
    )

    assert delecao.status == "delecao"
    assert delecao.motivo == "vale_anulado"
    assert delecao.vales_anulados == registro.vales
    assert await lancamentos_manuais_da_modelo(conn, grupo.modelo_id) == []


# --- vale não é Cobrança da agência, em nenhuma direção --------------------------------------------


@pytest.mark.asyncio
async def test_o_vale_nao_cria_cobranca_da_agencia(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    grupo = await _montar_grupo(conn)
    falas = _Falas()

    resultado = await _dizer(conn, grupo, VALE, falas=falas)

    assert resultado.cobrancas == ()
    assert await cobrancas_abertas_da_modelo(conn, grupo.modelo_id) == []


@pytest.mark.asyncio
async def test_a_cobranca_da_agencia_nao_cria_vale(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Serviço vendido a ela (anúncio, site) continua sendo cobrança — e ela espera comprovante."""
    grupo = await _montar_grupo(conn)
    falas = _Falas()

    resultado = await _dizer(conn, grupo, COBRANCA, falas=falas)

    assert resultado.motivo == "cobranca_registrada"
    assert resultado.vales == ()
    assert await lancamentos_manuais_da_modelo(conn, grupo.modelo_id) == []
