import asyncio
import json
from contextlib import asynccontextmanager
from decimal import Decimal
from uuid import uuid4

import pytest

from barra.core.errors import EntradaInvalida
from barra.dominio.escaladas.service import aplicar_comando
from barra.settings import get_settings


class _Result:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows

    async def fetchone(self):
        return self.rows[0] if self.rows else None

    async def fetchall(self):
        return self.rows


class FakeConn:
    def __init__(self, atendimento: dict) -> None:
        self.atendimento = atendimento
        self.executed: list[tuple[str, object]] = []

    @asynccontextmanager
    async def transaction(self):
        yield

    async def execute(self, query: str, params: object = None):
        self.executed.append((query, params))
        if "FROM barravips.atendimentos a" in query:
            return _Result([self.atendimento])
        if "SELECT estado::text AS estado FROM barravips.bloqueios" in query:
            return _Result([])
        if "UPDATE barravips.atendimentos" in query and "estado = 'Fechado'" in query:
            self.atendimento["estado"] = "Fechado"
        if "UPDATE barravips.atendimentos" in query and "estado = 'Perdido'" in query:
            self.atendimento["estado"] = "Perdido"
        # Fiel ao SQL real: o UPDATE que avança (`ia_pausada = true`) é outro comando que o
        # UPDATE que só carimba o pix_status. Sem essa distinção o fake "avançava" mesmo quando
        # o serviço não avançou — e um Fechado ressuscitado passaria batido.
        if "pix_status = 'validado'" in query:
            self.atendimento["pix_status"] = "validado"
            if "ia_pausada = true" in query:
                self.atendimento["estado"] = "Confirmado"
                self.atendimento["ia_pausada"] = True
                self.atendimento["responsavel_atual"] = "modelo"
        if "pix_status = 'em_revisao'" in query:
            self.atendimento["pix_status"] = "em_revisao"
            if "ia_pausada = true" in query:
                self.atendimento["estado"] = "Confirmado"
                self.atendimento["ia_pausada"] = True
                self.atendimento["responsavel_atual"] = "modelo"
        if "pix_status = 'invalido'" in query:
            self.atendimento["pix_status"] = "invalido"
        return _Result([])


def _atendimento() -> dict:
    return {
        "id": uuid4(),
        "estado": "Aguardando_confirmacao",
        "pix_status": "em_revisao",
        "ia_pausada": True,
        "tipo_atendimento": "externo",
        "percentual_repasse": Decimal("40.0"),
        "bloqueio_id": None,
    }


def test_fechamento_sem_valor_falha() -> None:
    conn = FakeConn(_atendimento())

    async def run() -> None:
        await aplicar_comando(
            conn,
            origem="painel",
            autor="Fernando",
            atendimento_id=conn.atendimento["id"],
            comando="registrar_fechado",
            payload={},
        )

    with pytest.raises(EntradaInvalida) as exc:
        asyncio.run(run())
    assert exc.value.code == "VALOR_FINAL_OBRIGATORIO"


def test_fechamento_com_valor_passa() -> None:
    conn = FakeConn(_atendimento())

    async def run():
        return await aplicar_comando(
            conn,
            origem="painel",
            autor="Fernando",
            atendimento_id=conn.atendimento["id"],
            comando="registrar_fechado",
            payload={"valor_final": Decimal("1000")},
        )

    result = asyncio.run(run())
    assert result.estado == "Fechado"


def _update_fechado(conn: "FakeConn") -> tuple[str, object]:
    return next(
        (q, p)
        for q, p in conn.executed
        if "UPDATE barravips.atendimentos" in q and "estado = 'Fechado'" in q
    )


def test_fechamento_cartao_carimba_taxa_padrao() -> None:
    # ADR 0013 (backend carimba): forma_pagamento='cartao' não isenta → o backend grava
    # taxa_cartao_snapshot = settings.taxa_cartao_padrao_pct e confirma a forma. Sem isso a
    # fórmula de valor líquido (VALOR_SERVICO_SQL) é no-op e repasse/comissão saem inflados.
    conn = FakeConn(_atendimento())

    async def run():
        return await aplicar_comando(
            conn,
            origem="painel",
            autor="Fernando",
            atendimento_id=conn.atendimento["id"],
            comando="registrar_fechado",
            payload={
                "valor_final": Decimal("1100"),
                "forma_pagamento": "cartao",
                "isentar_taxa": False,
            },
        )

    asyncio.run(run())
    query, params = _update_fechado(conn)
    assert "taxa_cartao_snapshot = %s" in query
    assert "forma_pagamento = COALESCE(%s, forma_pagamento)" in query
    assert params[2] == get_settings().taxa_cartao_padrao_pct  # type: ignore[index]
    assert params[3] == "cartao"  # type: ignore[index]


def test_fechamento_cartao_isento_nao_carimba_taxa() -> None:
    # Toggle "isentar taxa" (VIP/valor alto): cartão mas isento → taxa NULL, forma confirmada.
    conn = FakeConn(_atendimento())

    async def run():
        return await aplicar_comando(
            conn,
            origem="painel",
            autor="Fernando",
            atendimento_id=conn.atendimento["id"],
            comando="registrar_fechado",
            payload={
                "valor_final": Decimal("1100"),
                "forma_pagamento": "cartao",
                "isentar_taxa": True,
            },
        )

    asyncio.run(run())
    _query, params = _update_fechado(conn)
    assert params[2] is None  # type: ignore[index]  # taxa isenta
    assert params[3] == "cartao"  # type: ignore[index]


def test_fechamento_grupo_sem_forma_nao_carimba_taxa() -> None:
    # Comando do grupo (`fechado [valor]`) não envia forma → taxa NULL e forma preservada
    # (COALESCE com None); Fernando ajusta a taxa depois no painel (correção).
    conn = FakeConn(_atendimento())

    async def run():
        return await aplicar_comando(
            conn,
            origem="grupo_coordenacao",
            autor="modelo",
            atendimento_id=conn.atendimento["id"],
            comando="registrar_fechado",
            payload={"valor_final": Decimal("1000")},
        )

    asyncio.run(run())
    query, params = _update_fechado(conn)
    assert "taxa_cartao_snapshot = %s" in query
    assert params[2] is None  # type: ignore[index]  # sem taxa
    assert params[3] is None  # type: ignore[index]  # forma não informada → COALESCE preserva


def test_correcao_grava_taxa_cartao_snapshot() -> None:
    # Fernando recalcula o financeiro no painel: a correção também grava a taxa.
    conn = FakeConn(_atendimento())

    async def run():
        return await aplicar_comando(
            conn,
            origem="painel",
            autor="Fernando",
            atendimento_id=conn.atendimento["id"],
            comando="corrigir_registro",
            payload={
                "novo_resultado": "Fechado",
                "valor_final": Decimal("1100"),
                "taxa_cartao_snapshot": Decimal("10"),
            },
        )

    asyncio.run(run())
    query, params = next(
        (q, p)
        for q, p in conn.executed
        if "UPDATE barravips.atendimentos" in q and "estado = %s" in q
    )
    assert "taxa_cartao_snapshot = %s" in query
    assert Decimal("10") in params  # type: ignore[operator]


def test_perda_sem_motivo_falha() -> None:
    conn = FakeConn(_atendimento())

    async def run() -> None:
        await aplicar_comando(
            conn,
            origem="painel",
            autor="Fernando",
            atendimento_id=conn.atendimento["id"],
            comando="registrar_perdido",
            payload={},
        )

    with pytest.raises(EntradaInvalida) as exc:
        asyncio.run(run())
    assert exc.value.code == "MOTIVO_OBRIGATORIO"


def test_outro_sem_observacao_falha() -> None:
    conn = FakeConn(_atendimento())

    async def run() -> None:
        await aplicar_comando(
            conn,
            origem="painel",
            autor="Fernando",
            atendimento_id=conn.atendimento["id"],
            comando="registrar_perdido",
            payload={"motivo": "outro"},
        )

    with pytest.raises(EntradaInvalida) as exc:
        asyncio.run(run())
    assert exc.value.code == "OBSERVACAO_OBRIGATORIA"


def test_validar_pix_aplica_estado_correto() -> None:
    conn = FakeConn(_atendimento())

    async def run():
        return await aplicar_comando(
            conn,
            origem="pipeline_pix",
            autor="Fernando",
            atendimento_id=conn.atendimento["id"],
            comando="atualizar_pix",
            payload={"decisao": "validado"},
        )

    result = asyncio.run(run())
    assert result.pix_status == "validado"
    assert result.estado == "Confirmado"


def test_em_revisao_pix_avanca_para_confirmado() -> None:
    # Pix nunca trava: duvidoso (em_revisao) tambem avanca para Confirmado + pausa
    # (modelo_em_atendimento), igual ao validado (decisao grilling 2026-05-23).
    conn = FakeConn(_atendimento())

    async def run():
        return await aplicar_comando(
            conn,
            origem="pipeline_pix",
            autor="sistema",
            atendimento_id=conn.atendimento["id"],
            comando="atualizar_pix",
            payload={"decisao": "em_revisao", "motivo": "valor 80 != esperado 100"},
        )

    result = asyncio.run(run())
    assert result.pix_status == "em_revisao"
    assert result.estado == "Confirmado"


def test_pix_remoto_validado_nao_transiciona_nem_pausa() -> None:
    # ADR 0029: o Pix antecipado da video chamada so registra o pagamento — sem transicao
    # (a hora da chamada transiciona pelo cron, ADR 0021) e sem pausar a IA (o cliente segue
    # conversando ate a hora).
    atendimento = _atendimento()
    atendimento["tipo_atendimento"] = "remoto"
    atendimento["pix_status"] = "aguardando"
    atendimento["ia_pausada"] = False
    conn = FakeConn(atendimento)

    async def run():
        return await aplicar_comando(
            conn,
            origem="pipeline_pix",
            autor="sistema",
            atendimento_id=conn.atendimento["id"],
            comando="atualizar_pix",
            payload={"decisao": "validado"},
        )

    result = asyncio.run(run())
    assert result.pix_status == "validado"
    assert result.estado == "Aguardando_confirmacao"
    assert not any("ia_pausada = true" in q for q, _ in conn.executed)
    assert not any(
        "estado = " in q and "UPDATE barravips.atendimentos" in q for q, _ in conn.executed
    )


def test_pix_remoto_em_revisao_nao_transiciona_nem_pausa() -> None:
    # Duvidoso no remoto: mesma regra do validado (nunca trava por Pix) — so pix_status muda;
    # a duvidez vai no card e na fila de revisao de Fernando.
    atendimento = _atendimento()
    atendimento["tipo_atendimento"] = "remoto"
    atendimento["pix_status"] = "aguardando"
    atendimento["ia_pausada"] = False
    conn = FakeConn(atendimento)

    async def run():
        return await aplicar_comando(
            conn,
            origem="pipeline_pix",
            autor="sistema",
            atendimento_id=conn.atendimento["id"],
            comando="atualizar_pix",
            payload={"decisao": "em_revisao", "motivo": "valor 150 < esperado 300"},
        )

    result = asyncio.run(run())
    assert result.pix_status == "em_revisao"
    assert result.estado == "Aguardando_confirmacao"
    assert not any("ia_pausada = true" in q for q, _ in conn.executed)


def test_recusar_pix_nao_reverte_estado() -> None:
    # Veredito 'invalido' do painel e registro financeiro/auditoria: nao reverte estado
    # nem despausa a IA (a modelo ja agiu sobre o card de em_revisao).
    conn = FakeConn(_atendimento())

    async def run():
        return await aplicar_comando(
            conn,
            origem="painel",
            autor="Fernando",
            atendimento_id=conn.atendimento["id"],
            comando="atualizar_pix",
            payload={"decisao": "invalido", "motivo": "valor", "observacao": None},
        )

    result = asyncio.run(run())
    assert result.pix_status == "invalido"
    assert result.estado == "Aguardando_confirmacao"
    assert not any("ia_pausada = false" in q for q, _ in conn.executed)


# --- Pix aprovado depois de o atendimento morrer -------------------------------------------
# A fila de revisão é assíncrona por design ("o Pix nunca trava"): Fernando dá o veredito dias
# depois, quando o encontro já aconteceu e a modelo já fechou no grupo. Registrar a decisão do
# COMPROVANTE é legítimo; ressuscitar o ATENDIMENTO não — reverter `Fechado`→`Confirmado` some
# com a venda do faturamento (que filtra estado='Fechado'), reabre o par contra o índice único
# parcial `atendimentos_um_aberto_por_par` e devolve o zumbi ao `timeout_longo`.


def _atendimento_terminal(estado: str) -> dict:
    at = _atendimento()
    at["estado"] = estado
    at["ia_pausada"] = False
    at["responsavel_atual"] = "Fernando"
    return at


def _aplicar_pix(conn: "FakeConn", decisao: str, origem: str = "painel"):
    async def run():
        return await aplicar_comando(
            conn,
            origem=origem,  # type: ignore[arg-type]
            autor="Fernando",
            atendimento_id=conn.atendimento["id"],
            comando="atualizar_pix",
            payload={"decisao": decisao, "pix_id": "pix-1"},
        )

    return asyncio.run(run())


@pytest.mark.parametrize("estado", ["Fechado", "Perdido"])
@pytest.mark.parametrize("decisao", ["validado", "em_revisao"])
def test_pix_em_atendimento_terminal_registra_sem_ressuscitar(estado: str, decisao: str) -> None:
    conn = FakeConn(_atendimento_terminal(estado))

    result = _aplicar_pix(conn, decisao)

    # A decisão sobre o comprovante fica gravada...
    assert result.pix_status == decisao
    assert conn.atendimento["pix_status"] == decisao
    # ...e o atendimento não se mexe: nem estado, nem pausa da IA, nem responsável.
    assert result.estado == estado
    assert conn.atendimento["estado"] == estado
    assert conn.atendimento["ia_pausada"] is False
    assert conn.atendimento["responsavel_atual"] == "Fernando"
    updates = [q for q, _ in conn.executed if "UPDATE barravips.atendimentos" in q]
    assert updates and not any("ia_pausada = true" in q for q in updates)
    assert not any("estado = %s" in q for q in updates)
    # Auditoria: o evento sai, carimbado com o motivo de não ter avançado.
    eventos = [p for q, p in conn.executed if "INSERT INTO barravips.eventos" in q]
    assert len(eventos) == 1
    payload_evento = json.loads(eventos[0][4])  # type: ignore[index]
    assert payload_evento["decisao"] == decisao
    assert payload_evento["avanco_suprimido"] == "atendimento_terminal"
    assert payload_evento["estado"] == estado


@pytest.mark.parametrize("decisao", ["validado", "em_revisao"])
def test_pix_em_atendimento_vivo_continua_avancando(decisao: str) -> None:
    # Caminho feliz intacto (invariante "nunca trava por Pix"): externo vivo avança para
    # Confirmado, pausa a IA e passa o bastão para a modelo, com o evento limpo.
    conn = FakeConn(_atendimento())

    result = _aplicar_pix(conn, decisao, origem="pipeline_pix")

    assert result.estado == "Confirmado"
    assert result.pix_status == decisao
    assert conn.atendimento["ia_pausada"] is True
    assert conn.atendimento["responsavel_atual"] == "modelo"
    avanco = [
        q
        for q, _ in conn.executed
        if "UPDATE barravips.atendimentos" in q and "ia_pausada = true" in q
    ]
    assert len(avanco) == 1
    assert "responsavel_atual = 'modelo'" in avanco[0]
    eventos = [p for q, p in conn.executed if "INSERT INTO barravips.eventos" in q]
    payload_evento = json.loads(eventos[0][4])  # type: ignore[index]
    assert "avanco_suprimido" not in payload_evento
