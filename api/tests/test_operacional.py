import asyncio
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
