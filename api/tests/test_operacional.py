import asyncio
from contextlib import asynccontextmanager
from decimal import Decimal
from uuid import uuid4

import pytest

from barra.core.errors import EntradaInvalida
from barra.dominio.escaladas.service import aplicar_comando


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
        if "pix_status = 'validado'" in query:
            self.atendimento["pix_status"] = "validado"
            self.atendimento["estado"] = "Confirmado"
        if "pix_status = 'em_revisao'" in query:
            self.atendimento["pix_status"] = "em_revisao"
            self.atendimento["estado"] = "Confirmado"
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
