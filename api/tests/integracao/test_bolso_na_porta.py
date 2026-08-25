"""ADR-0047 / ticket 04 — o `bolso.py` deixa de ser ilha: a porta escreve em que conta caiu.

Ate aqui `resolver_bolso`, `confrontar_bolso`, `montar_recibo_do_bolso` e `montar_pergunta_do_bolso`
tinham **zero chamadores em `src/`** — so testes. Nenhum caminho de producao gravava
`bolso = 'empresa'`: a venda que o cliente pagou direto na conta da casa ficava `nao_dito`, o razao
a tratava como `dela` pelo default conservador (ADR-0047 §4) e **debitava dela um bruto que ela
nunca teve na mao**.

Com o papel da chave (ticket 03) a classificacao sai de (papel do pagador x papel do destino), que
e a entrada que o `bolso.py` esperava. Este arquivo pina o que a porta faz com ela:

- cliente -> chave da CASA: classe `cliente_para_a_casa`, bolso `empresa`, **nao abate**;
- modelo  -> chave da CASA: continua `fechamento`, abate e o bolso fica `dela`;
- cliente -> chave DELA:    classe `entrada_da_modelo`, bolso `dela`, e a venda CONTINUA na fila
  (ela recebeu o valor cheio e deve o valor cheio);
- `nao_dito` -> evidencia fixa sem perguntar; bolso ja AFIRMADO que diverge vira **pergunta**, uma
  so por janela de contexto;
- a fala explicita ("caiu na conta da casa") escreve o mesmo campo pelo mesmo caminho.

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
from barra.dominio.grupo_financeiro.bolso import PREFIXO_DA_PERGUNTA_DO_BOLSO
from barra.dominio.grupo_financeiro.comprovante import LeituraDoComprovante, normalizar_chave
from barra.dominio.grupo_financeiro.modelos import ImagemDoGrupo, MensagemDoGrupo

pytestmark = pytest.mark.needs_db

CHAVE_DA_CASA = "casa-elite@pix.example"
TITULAR_DA_CASA = "Elite Servicos Ltda"
CHAVE_DELA = "cpf-dela@pix.example"

ANUNCIO = "Atendimento no nosso local \nCliente Ramon \nPerfil {apelido} \n600 1h"
NOITE_DE_12_08 = datetime(2026, 8, 13, 1, 0, tzinfo=UTC)


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


async def _uma_venda(
    c: AsyncConnection[dict[str, Any]], grupo: _Grupo, *, falas: _Falas, forma: str = "Pix"
) -> UUID:
    lancou = await _dizer(c, grupo, ANUNCIO.format(apelido=grupo.apelido), falas=falas)
    (venda_id,) = lancou.vendas
    pago = await _dizer(c, grupo, forma, falas=falas)
    assert pago.pagamentos == (venda_id,)
    return venda_id


async def _postar_comprovante(
    c: AsyncConnection[dict[str, Any]],
    grupo: _Grupo,
    leitura: LeituraDoComprovante,
    *,
    falas: _Falas,
    foto: bytes = b"\xff\xd8\xff" + b"\x00" * 64,
) -> ResultadoDaPorta:
    grupo.relogio += timedelta(minutes=5)
    msg = MensagemDoGrupo(
        grupo_jid=grupo.jid,
        texto="",
        tipo="imagem",
        imagem=ImagemDoGrupo(foto, mimetype="image/jpeg"),
        recebida_em=grupo.relogio,
        evolution_message_id=f"3EB0{uuid4().hex[:12]}",
        autor_nome="Yasmin",
        autor_jid="5571988887777@s.whatsapp.net",
    )
    return await processar_mensagem_do_grupo(c, msg, enviar=falas, ler_comprovante=_Olho(leitura))


def _leitura(
    *,
    chave: str | None,
    pagador: str | None,
    titular: str | None = None,
    valor: str = "600.00",
) -> LeituraDoComprovante:
    return LeituraDoComprovante(
        e_comprovante=True,
        legivel=True,
        valor=Decimal(valor),
        data=date(2026, 8, 12),
        pagador=pagador,
        chave_destino=chave,
        titular_destino=titular,
    )


async def _venda(c: AsyncConnection[dict[str, Any]], venda_id: UUID) -> dict[str, Any]:
    cur = await c.execute(
        """
        SELECT bolso::text AS bolso, bolso_mensagem_id, comprovante_id, forma_pagamento
          FROM barravips.vendas_registradas
         WHERE id = %s
        """,
        (venda_id,),
    )
    linha = await cur.fetchone()
    assert linha is not None
    return dict(linha)


async def _comprovantes(c: AsyncConnection[dict[str, Any]], grupo: _Grupo) -> list[dict[str, Any]]:
    cur = await c.execute(
        """
        SELECT co.classificacao::text AS classificacao, co.chave_conhecida, co.valor_abatido
          FROM barravips.comprovantes_do_grupo co
          JOIN barravips.grupos_financeiros g ON g.id = co.grupo_id
         WHERE g.jid = %s
         ORDER BY co.created_at
        """,
        (grupo.jid,),
    )
    return [dict(linha) for linha in await cur.fetchall()]


async def _eventos_do_bolso(
    c: AsyncConnection[dict[str, Any]], venda_id: UUID
) -> list[dict[str, Any]]:
    cur = await c.execute(
        """
        SELECT tipo, campo, valor_anterior, valor_novo, mensagem_id
          FROM barravips.venda_registrada_eventos
         WHERE venda_id = %s AND campo = 'bolso'
         ORDER BY created_at
        """,
        (venda_id,),
    )
    return [dict(linha) for linha in await cur.fetchall()]


# --- 1. o cliente pagou a casa direto -----------------------------------------------------------


async def test_comprovante_do_cliente_para_a_casa_fixa_o_bolso_em_empresa(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """A linha do ADR-0047 §2 que nao tinha chamador nenhum, e o motivo do ticket.

    O cliente pagou na chave da CASA: o dinheiro nunca passou pela mao dela. Antes disso o
    comprovante virava `fechamento` e ABATIA a venda — o que fechava a conta pelo motivo errado,
    porque o bruto continuava debitado dela no razao. Agora ele nao abate: fixa o bolso em
    `empresa`, e a venda sai da fila do pix por consequencia (nao ha transferencia dela a esperar).
    """
    falas = _Falas()
    grupo = await _montar_grupo(conn)
    await _cadastrar(conn, chave=CHAVE_DA_CASA, papel="casa", titular=TITULAR_DA_CASA)
    venda_id = await _uma_venda(conn, grupo, falas=falas)

    lido = await _postar_comprovante(
        conn,
        grupo,
        _leitura(chave=CHAVE_DA_CASA, pagador="Lucas Prado", titular=TITULAR_DA_CASA),
        falas=falas,
    )

    assert lido.motivo == "comprovante_cliente_para_a_casa"
    assert lido.abatidas == ()
    assert lido.bolsos == (venda_id,)

    (comprovante,) = await _comprovantes(conn, grupo)
    assert comprovante["classificacao"] == "cliente_para_a_casa"
    assert comprovante["chave_conhecida"] is True
    assert comprovante["valor_abatido"] == Decimal("0.00")

    venda = await _venda(conn, venda_id)
    assert venda["bolso"] == "empresa"
    assert venda["comprovante_id"] is None  # nao e transferencia dela: nao ha o que comprovar
    assert venda["bolso_mensagem_id"] == lido.mensagem_id  # a foto em que o agente se apoiou

    assert "🏦" in falas.ultima
    assert "não abati nada" in falas.ultima
    assert "na conta da casa" in falas.ultima  # o de->para do recibo do bolso
    assert "(era: não dito)" in falas.ultima


async def test_a_venda_paga_direto_a_casa_sai_da_fila_da_cobranca(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """O efeito que o gestor ve: a manha para de cobrar comprovante de dinheiro que ela nao teve.

    `vendas_pix_a_comprovar` exclui `bolso = 'empresa'` — a consulta ja estava pronta e ninguem
    escrevia o valor que a liga.
    """
    falas = _Falas()
    grupo = await _montar_grupo(conn)
    await _cadastrar(conn, chave=CHAVE_DA_CASA, papel="casa", titular=TITULAR_DA_CASA)
    await _uma_venda(conn, grupo, falas=falas)

    from barra.dominio.grupo_financeiro.repo import vendas_pix_a_comprovar

    assert len(await vendas_pix_a_comprovar(conn, grupo.modelo_id)) == 1  # type: ignore[arg-type]

    await _postar_comprovante(
        conn, grupo, _leitura(chave=CHAVE_DA_CASA, pagador="Lucas Prado"), falas=falas
    )

    assert await vendas_pix_a_comprovar(conn, grupo.modelo_id) == []  # type: ignore[arg-type]


async def test_o_evento_do_bolso_registra_o_de_para_para_a_auditoria(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Mexer no bolso inverte o SINAL do saldo: a escrita sem rastro e a correcao que ninguem acha.

    `venda_registrada_eventos` com `campo = 'bolso'` e o rastro, na MESMA transacao do UPDATE.
    """
    falas = _Falas()
    grupo = await _montar_grupo(conn)
    await _cadastrar(conn, chave=CHAVE_DA_CASA, papel="casa", titular=TITULAR_DA_CASA)
    venda_id = await _uma_venda(conn, grupo, falas=falas)

    lido = await _postar_comprovante(
        conn, grupo, _leitura(chave=CHAVE_DA_CASA, pagador="Lucas Prado"), falas=falas
    )

    (evento,) = await _eventos_do_bolso(conn, venda_id)
    assert evento["tipo"] == "correcao"
    assert evento["valor_anterior"] == "nao_dito"
    assert evento["valor_novo"] == "empresa"
    assert evento["mensagem_id"] == lido.mensagem_id


# --- 2. a modelo transferindo para a casa (o que NAO pode mudar) ---------------------------------


async def test_comprovante_dela_para_a_casa_continua_abatendo_com_bolso_dela(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """A tranca do ticket: quem PAGOU foi ela, entao o destino da casa continua sendo fechamento.

    Se `cliente_para_a_casa` tambem pegasse o comprovante dela, o abate FIFO pararia de acontecer
    e a fila de comprovante nunca mais andaria.
    """
    falas = _Falas()
    grupo = await _montar_grupo(conn)
    await _cadastrar(conn, chave=CHAVE_DA_CASA, papel="casa", titular=TITULAR_DA_CASA)
    venda_id = await _uma_venda(conn, grupo, falas=falas)

    lido = await _postar_comprovante(
        conn,
        grupo,
        _leitura(chave=CHAVE_DA_CASA, pagador="YASMIN N DE ALBUQUERQUE"),
        falas=falas,
    )

    assert lido.motivo == "comprovante_conciliado"
    assert lido.abatidas == (venda_id,)
    (comprovante,) = await _comprovantes(conn, grupo)
    assert comprovante["classificacao"] == "fechamento"

    venda = await _venda(conn, venda_id)
    assert venda["bolso"] == "dela"
    assert venda["comprovante_id"] is not None
    assert "✅" in falas.ultima


async def test_pagador_ilegivel_continua_abatendo_e_nao_vira_a_classe_nova(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """A guarda do `e_do_cliente_para_a_casa`: sem pagador lido, o comprovante vale pelo VALOR.

    O OCR falha no nome do pagador com frequencia, e e assim que metade dos fechamentos legitimos
    chega. Sem esta linha, "pagador desconhecido + destino da casa" deixaria de abater e a fila
    pararia — em silencio, e para sempre.
    """
    falas = _Falas()
    grupo = await _montar_grupo(conn)
    await _cadastrar(conn, chave=CHAVE_DA_CASA, papel="casa", titular=TITULAR_DA_CASA)
    venda_id = await _uma_venda(conn, grupo, falas=falas)

    lido = await _postar_comprovante(
        conn, grupo, _leitura(chave=CHAVE_DA_CASA, pagador=None), falas=falas
    )

    assert lido.abatidas == (venda_id,)
    assert (await _venda(conn, venda_id))["bolso"] == "dela"


# --- 3. o cliente pagou na chave DELA -----------------------------------------------------------


async def test_comprovante_do_cliente_para_a_chave_dela_fixa_o_bolso_em_dela(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """A classe `entrada_da_modelo` deixa de ser so um aviso e vira o bolso da venda.

    "Onde o dinheiro parou" e exatamente a pergunta do bolso, e este comprovante e a resposta por
    escrito. A venda CONTINUA na fila do pix: ela recebeu o valor cheio e deve o valor cheio
    (ADR-0047, *"o certo vai ser ela receber e enviar pra gente"*).
    """
    falas = _Falas()
    grupo = await _montar_grupo(conn)
    await _cadastrar(conn, chave=CHAVE_DA_CASA, papel="casa", titular=TITULAR_DA_CASA)
    await _cadastrar(conn, chave=CHAVE_DELA, papel="modelo", modelo_id=grupo.modelo_id)
    venda_id = await _uma_venda(conn, grupo, falas=falas)

    lido = await _postar_comprovante(
        conn, grupo, _leitura(chave=CHAVE_DELA, pagador="Vanessa Melo De Oliveira"), falas=falas
    )

    assert lido.motivo == "comprovante_entrada_da_modelo"
    assert lido.abatidas == ()
    assert lido.bolsos == (venda_id,)

    venda = await _venda(conn, venda_id)
    assert venda["bolso"] == "dela"
    assert venda["comprovante_id"] is None  # a casa nao recebeu nada: nao ha venda comprovada

    from barra.dominio.grupo_financeiro.repo import vendas_pix_a_comprovar

    assert len(await vendas_pix_a_comprovar(conn, grupo.modelo_id)) == 1  # type: ignore[arg-type]
    assert "📥" in falas.ultima
    assert "com a modelo" in falas.ultima


# --- 4. o valor que nao casa, e o bolso que continua nao dito ------------------------------------


async def test_comprovante_de_valor_que_nao_casa_deixa_o_bolso_nao_dito(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """So valor EXATO, e so se for uma so — a mesma disciplina da promocao da ficha.

    Casar por aproximacao penduraria o sinal do saldo na venda de outro atendimento, e ninguem
    reconfere um campo que o sistema preencheu sozinho. `nao_dito` e estado legitimo: quem cobra e
    a manha.
    """
    falas = _Falas()
    grupo = await _montar_grupo(conn)
    await _cadastrar(conn, chave=CHAVE_DA_CASA, papel="casa", titular=TITULAR_DA_CASA)
    venda_id = await _uma_venda(conn, grupo, falas=falas)

    lido = await _postar_comprovante(
        conn,
        grupo,
        _leitura(chave=CHAVE_DA_CASA, pagador="Lucas Prado", valor="450.00"),
        falas=falas,
    )

    assert lido.motivo == "comprovante_cliente_para_a_casa"
    assert lido.bolsos == ()
    assert (await _venda(conn, venda_id))["bolso"] == "nao_dito"
    assert "(era:" not in falas.ultima  # nao ha de->para a anunciar
    assert await _eventos_do_bolso(conn, venda_id) == []


# --- 5. o bolso ja afirmado que diverge ---------------------------------------------------------


async def test_bolso_afirmado_que_diverge_vira_pergunta_e_nao_reescreve(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Mexer no bolso inverte o SINAL do saldo — reescrever isso sozinho e a correcao que ninguem
    descobre. A venda em dinheiro nasce `dela` por regra; o comprovante do cliente para a casa diz
    `empresa`. O agente PERGUNTA, e nao escreve nada enquanto nao for respondido.
    """
    falas = _Falas()
    grupo = await _montar_grupo(conn)
    await _cadastrar(conn, chave=CHAVE_DA_CASA, papel="casa", titular=TITULAR_DA_CASA)
    venda_id = await _uma_venda(conn, grupo, falas=falas, forma="Dinheiro")
    assert (await _venda(conn, venda_id))["bolso"] == "dela"

    lido = await _postar_comprovante(
        conn, grupo, _leitura(chave=CHAVE_DA_CASA, pagador="Lucas Prado"), falas=falas
    )

    assert lido.bolsos == ()
    assert (await _venda(conn, venda_id))["bolso"] == "dela"  # nada foi reescrito
    assert await _eventos_do_bolso(conn, venda_id) == []
    assert PREFIXO_DA_PERGUNTA_DO_BOLSO in falas.ultima
    assert "está anotado como com a modelo" in falas.ultima


async def test_a_pergunta_do_bolso_nao_se_repete_no_segundo_comprovante(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Uma pergunta por janela de contexto — a mesma tranca do desempate da forma.

    Sem ela, cada foto nova sobre a mesma venda reperguntaria a mesma coisa: a metralhadora que o
    dominio proibe. A tranca le o log do grupo, onde a propria fala do agente ja esta gravada.
    """
    falas = _Falas()
    grupo = await _montar_grupo(conn)
    await _cadastrar(conn, chave=CHAVE_DA_CASA, papel="casa", titular=TITULAR_DA_CASA)
    await _uma_venda(conn, grupo, falas=falas, forma="Dinheiro")

    await _postar_comprovante(
        conn,
        grupo,
        _leitura(chave=CHAVE_DA_CASA, pagador="Lucas Prado"),
        falas=falas,
        foto=b"\xff\xd8\xff" + b"\x01" * 64,
    )
    assert PREFIXO_DA_PERGUNTA_DO_BOLSO in falas.ultima

    de_novo = await _postar_comprovante(
        conn,
        grupo,
        _leitura(chave=CHAVE_DA_CASA, pagador="Lucas Prado"),
        falas=falas,
        foto=b"\xff\xd8\xff" + b"\x02" * 64,
    )

    assert de_novo.resposta is not None
    assert PREFIXO_DA_PERGUNTA_DO_BOLSO not in de_novo.resposta


# --- 6. a fala explicita ------------------------------------------------------------------------


async def test_a_fala_do_grupo_fixa_o_bolso_sem_comprovante_nenhum(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """A terceira linha da tabela. "Caiu na conta da casa" e uma frase, e ela decide o mesmo campo.

    Nenhuma imagem, nenhum cadastro de chave: e o caminho que funciona no grupo que nunca manda
    comprovante.
    """
    falas = _Falas()
    grupo = await _montar_grupo(conn)
    venda_id = await _uma_venda(conn, grupo, falas=falas)

    dito = await _dizer(conn, grupo, "Caiu na conta da casa", falas=falas)

    assert dito.motivo == "bolso_fixado"
    assert dito.bolsos == (venda_id,)
    assert (await _venda(conn, venda_id))["bolso"] == "empresa"
    assert falas.ultima.startswith("💰 Anotei:")
    assert "Ramon" in falas.ultima


async def test_a_fala_que_contradiz_o_que_esta_anotado_pergunta_em_vez_de_reescrever(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """A fala nao tem privilegio nenhum sobre o que ja foi afirmado: divergiu, pergunta."""
    falas = _Falas()
    grupo = await _montar_grupo(conn)
    venda_id = await _uma_venda(conn, grupo, falas=falas, forma="Dinheiro")

    dito = await _dizer(conn, grupo, "Caiu na conta da casa", falas=falas)

    assert dito.motivo == "bolso_divergente"
    assert dito.bolsos == ()
    assert (await _venda(conn, venda_id))["bolso"] == "dela"
    assert PREFIXO_DA_PERGUNTA_DO_BOLSO in falas.ultima


async def test_a_fala_que_repete_o_que_ja_esta_anotado_morre_calada(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """O agente nao ecoa o que ja esta certo — repetir "essa foi da casa" e o ruido que faz o
    grupo parar de ler o que ele escreve."""
    falas = _Falas()
    grupo = await _montar_grupo(conn)
    venda_id = await _uma_venda(conn, grupo, falas=falas, forma="Dinheiro")
    quantas = len(falas.enviadas)

    dito = await _dizer(conn, grupo, "Ficou com você", falas=falas)

    assert dito.motivo == "nao_e_anuncio"
    assert dito.bolsos == ()
    assert (await _venda(conn, venda_id))["bolso"] == "dela"
    assert len(falas.enviadas) == quantas


async def test_fala_de_bolso_sem_venda_nenhuma_nao_toma_o_turno(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Sem venda para apontar, "ficou com você" e conversa — e a mensagem segue a cascata de
    sempre em vez de morrer no leitor de bolso."""
    falas = _Falas()
    grupo = await _montar_grupo(conn)

    dito = await _dizer(conn, grupo, "Ficou com você", falas=falas)

    assert dito.bolsos == ()
    assert dito.motivo == "nao_e_anuncio"
    assert falas.enviadas == []


# --- 7. a corrida entre duas evidencias ---------------------------------------------------------


async def test_quem_perde_o_compare_and_swap_rele_a_venda_antes_de_perguntar(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """Duas evidencias no mesmo segundo: a segunda vê a coluna mudada e recebe `None`.

    Se ela perguntasse com o valor que leu, diria "está anotado como não dito" sobre uma venda que
    já está anotada como outra coisa — errado no único fato que quem responde pode conferir na
    tela do painel. `venda_para_o_bolso` é a releitura que dá o "de" honesto.
    """
    from barra.dominio.grupo_financeiro.repo import (
        definir_bolso_da_venda,
        venda_para_o_bolso,
    )

    falas = _Falas()
    grupo = await _montar_grupo(conn)
    venda_id = await _uma_venda(conn, grupo, falas=falas)

    # A outra evidencia chegou primeiro e escreveu.
    primeira = await definir_bolso_da_venda(
        conn,  # type: ignore[arg-type]
        venda_id,
        de="nao_dito",
        para="dela",
        mensagem_id=None,
    )
    assert primeira is not None

    # A segunda ainda achava que a coluna era `nao_dito`: o CAS a recusa.
    segunda = await definir_bolso_da_venda(
        conn,  # type: ignore[arg-type]
        venda_id,
        de="nao_dito",
        para="empresa",
        mensagem_id=None,
    )
    assert segunda is None

    relida = await venda_para_o_bolso(conn, venda_id)  # type: ignore[arg-type]
    assert relida is not None
    assert relida.bolso == "dela"
    assert relida.id == venda_id


# --- 8. a ficha aberta que o proprio comprovante do cliente fecha --------------------------------

FICHA = """📋 *FICHA DE ATENDIMENTO*

👤 *CLIENTE*
Nome: Igor

📝 *CONTRATAÇÃO*
Nome do perfil/anúncio: Sofia
Site: Barra Vips
Origem: (x) Próprio  ( ) Fake
Nome da modelo: {modelo}

🕒 *HORÁRIO*
Data: 12/08/2026
Hora: 19:00
Duração: 1h

📍 *LOCAL*
( ) Saída  (x) Local próprio
Tipo: (x) Casa

💰 *VALORES*
Valor total: R$ 600
Valor desta modelo: R$ 600

💳 *PAGAMENTO*
( ) Dinheiro  (x) Pix  ( ) Débito  ( ) Crédito  ( ) Link
"""


async def test_ficha_aberta_vira_venda_com_bolso_empresa_no_mesmo_comprovante(
    conn: AsyncConnection[dict[str, Any]],
) -> None:
    """O pagamento que o cliente fez direto à casa continua fazendo a ficha virar receita.

    A promoção acontece com `da_casa=False` de propósito: `bolso_da_promocao` lê esse parâmetro
    como "comprovante DELA para a casa" e faria a venda nascer `dela`, que é o contrário do que
    este comprovante prova. Ela nasce `nao_dito` e a evidência certa fixa `empresa` logo em
    seguida — com o de→para no recibo, em vez de um valor escrito de lado.
    """
    falas = _Falas()
    grupo = await _montar_grupo(conn)
    await _cadastrar(conn, chave=CHAVE_DA_CASA, papel="casa", titular=TITULAR_DA_CASA)
    aberta = await _dizer(conn, grupo, FICHA.format(modelo=grupo.apelido), falas=falas)
    assert aberta.ficha_id is not None

    lido = await _postar_comprovante(
        conn, grupo, _leitura(chave=CHAVE_DA_CASA, pagador="Igor Prado"), falas=falas
    )

    assert lido.motivo == "comprovante_cliente_para_a_casa"
    assert lido.abatidas == ()
    assert len(lido.bolsos) == 1

    venda = await _venda(conn, lido.bolsos[0])
    assert venda["bolso"] == "empresa"
    assert venda["forma_pagamento"] == "pix"
    assert venda["comprovante_id"] is None

    cur = await conn.execute(
        "SELECT estado::text AS estado FROM barravips.fichas_de_agendamento WHERE id = %s",
        (aberta.ficha_id,),
    )
    linha = await cur.fetchone()
    assert linha is not None
    assert linha["estado"] == "realizada"
