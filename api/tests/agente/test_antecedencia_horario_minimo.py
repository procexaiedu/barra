"""`registrar_extracao` desambigua `AntecedenciaInsuficiente` pelo `horario_minimo` do State.

Regressão do bug de borda (rig 2026-06-25): pedido "agora" perto do fim do expediente. O domínio
levanta `AntecedenciaInsuficiente` (o horário PEDIDO ainda está dentro da Disponibilidade, mas é
< now+buffer). Quando `horario_minimo` é None (now+buffer já passou do fim da janela), NÃO há
horário válido mais tarde hoje: mandar "ofereça o <horario_minimo>" apontaria pra uma tag ausente e
a IA inventaria um horário fora da janela (ela ofereceu "23h20" com expediente até 23h). A tool deve
cair na conduta de período de trabalho. Com `horario_minimo` presente, segue a conduta de preparo.

Unit, sem DB: monkeypatcha `_executar_idempotente` p/ levantar a exceção antes de tocar o banco;
o pool fake só prova que a tool abre/fecha a conexão. Mede o DELTA do counter (registry global).
"""

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from langchain_core.tools import ToolException
from prometheus_client import REGISTRY

import barra.agente.ferramentas.extracao as extracao_mod
from barra.agente.ferramentas.extracao import registrar_extracao
from barra.dominio.agenda.service import AntecedenciaInsuficiente

BRT = ZoneInfo("America/Sao_Paulo")

# .coroutine = corrotina crua do @tool; injeta `runtime` (.ainvoke({...}) não).
_chamar = registrar_extracao.coroutine  # type: ignore[attr-defined]


class _Result:
    def __init__(self, row: dict[str, Any] | None) -> None:
        self._row = row

    async def fetchone(self) -> dict[str, Any] | None:
        return self._row


class _FakeTx:
    """`conn.transaction()` — o escopo em que a RETIRADA do horario-palpite commita, depois de a
    transacao da tentativa ja ter revertido."""

    def __init__(self, conn: "_FakeConn") -> None:
        self._conn = conn

    async def __aenter__(self) -> "_FakeTx":
        self._conn.transacoes += 1
        return self

    async def __aexit__(self, *_: Any) -> None:
        return None


class _FakeConn:
    def __init__(self) -> None:
        self.sqls: list[str] = []
        self.transacoes = 0
        # Linha "tem palpite a retirar": o UPDATE condicional casa e devolve o id.
        self.retirada_casa = True

    async def __aenter__(self) -> "_FakeConn":
        return self

    async def __aexit__(self, *_: Any) -> None:
        return None

    def transaction(self) -> _FakeTx:
        return _FakeTx(self)

    async def execute(self, sql: str, params: Any = ()) -> _Result:
        self.sqls.append(" ".join(sql.split()))
        if "UPDATE barravips.atendimentos" in sql:
            return _Result({"id": _Ctx.atendimento_id} if self.retirada_casa else None)
        return _Result(None)


class _FakePool:
    def __init__(self) -> None:
        self.conn = _FakeConn()

    def connection(self) -> _FakeConn:
        return self.conn


class _Ctx:
    db_pool = _FakePool()
    atendimento_id = "00000000-0000-0000-0000-000000000001"
    turno_id = "00000000-0000-0000-0000-000000000002"
    agora_utc = None


class _Runtime:
    def __init__(self, state: dict[str, Any]) -> None:
        self.context = _Ctx()
        self.state = state


async def _forcar_antecedencia(*_a: Any, **_k: Any) -> Any:
    raise AntecedenciaInsuficiente("cedo demais (now + buffer)")


def _valor() -> float:
    valor = REGISTRY.get_sample_value(
        "agente_tool_erro_recuperavel_total",
        {"tool": "registrar_extracao", "motivo": "antecedencia_insuficiente"},
    )
    return valor or 0.0


async def test_horario_minimo_none_cai_em_periodo_de_trabalho(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`horario_minimo` None: conduta de período de trabalho, NUNCA ancorar no <horario_minimo>."""
    monkeypatch.setattr(extracao_mod, "_executar_idempotente", _forcar_antecedencia)
    antes = _valor()
    with pytest.raises(ToolException) as exc:
        await _chamar(
            proxima_acao_esperada="agendar o horário",
            runtime=_Runtime({"horario_minimo": None}),
        )
    msg = str(exc.value)
    assert msg.startswith("ERRO:")
    assert "período de trabalho" in msg
    assert "<periodo_de_trabalho>" in msg
    # NÃO manda ancorar num horario_minimo que não existe (era o bug).
    assert "<horario_minimo>" not in msg
    # E NÃO importa o pressuposto falso "está de folga" (o None pode vir de bloqueio).
    assert "folga" not in msg.lower()
    assert _valor() == antes + 1


async def test_horario_minimo_presente_mantem_conduta_de_preparo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`horario_minimo` presente: conduta de preparo, guiando ao primeiro horário liberado.

    Pós-F10: a nota NÃO ecoa mais a tag viva `<horario_minimo>` (um eco vazaria a tag ao
    cliente, e a persona proíbe tag na fala) — guia por linguagem sem tag e manda arredondar
    o piso quebrado pra cima."""
    monkeypatch.setattr(extracao_mod, "_executar_idempotente", _forcar_antecedencia)
    antes = _valor()
    with pytest.raises(ToolException) as exc:
        await _chamar(
            proxima_acao_esperada="agendar o horário",
            runtime=_Runtime({"horario_minimo": datetime(2026, 6, 25, 23, 30, tzinfo=BRT)}),
        )
    msg = str(exc.value)
    assert msg.startswith("ERRO:")
    assert "cedo demais" in msg
    # F10: guia ao primeiro horário liberado SEM ecoar a tag viva.
    assert "<horario_minimo>" not in msg
    assert "primeiro horário" in msg
    assert _valor() == antes + 1


async def test_state_sem_a_chave_degrada_para_periodo_de_trabalho(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`.get` ausente (state vazio) → None → fallback seguro (período de trabalho), sem KeyError."""
    monkeypatch.setattr(extracao_mod, "_executar_idempotente", _forcar_antecedencia)
    with pytest.raises(ToolException) as exc:
        await _chamar(
            proxima_acao_esperada="agendar o horário",
            runtime=_Runtime({}),
        )
    assert "período de trabalho" in str(exc.value)


# --- o palpite recusado SAI do snapshot (P0 externo_a, prova r3) -------------------------------


async def test_antecedencia_retira_o_horario_palpite_do_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """O erro instrui a IA a NÃO registrar a hora que vai ofertar — e o UPSERT é incremental
    (`COALESCE`), então obedecer PRESERVA o horário que acabou de ser recusado. Na prova r3 isso
    fechou o latch: seis turnos re-tentando a mesma reserva inválida com `21:00` gravado.

    O handler agora retira o palpite ANTES de levantar, numa transação PRÓPRIA — a da tentativa já
    reverteu e a `ToolException` sai pelo caminho de erro do pool (que daria rollback)."""
    monkeypatch.setattr(extracao_mod, "_executar_idempotente", _forcar_antecedencia)
    conn = _Ctx.db_pool.conn
    conn.sqls.clear()
    conn.transacoes = 0

    with pytest.raises(ToolException):
        await _chamar(
            proxima_acao_esperada="agendar o horário",
            runtime=_Runtime({"horario_minimo": datetime(2026, 8, 12, 21, 30, tzinfo=BRT)}),
        )

    (update,) = [s for s in conn.sqls if "UPDATE barravips.atendimentos" in s]
    assert "horario_desejado = NULL" in update
    assert "horario_evidenciado = false" in update
    # As três condições que separam "palpite do sistema" de "hora que ELE disse" / reserva de pé.
    assert "horario_desejado IS NOT NULL" in update
    assert "horario_evidenciado IS NOT TRUE" in update
    assert "bloqueio_id IS NULL" in update
    assert conn.transacoes == 1  # commit próprio, fora do rollback da tentativa
    assert any("INSERT INTO barravips.eventos" in s for s in conn.sqls)  # audit log


async def test_retirada_que_falha_nao_troca_erro_recuperavel_por_turno_morto(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A compensação é best-effort: se o banco recusar o UPDATE, o turno segue com o erro
    RECUPERÁVEL (que a IA reoferta) em vez de uma exceção crua que mata o turno."""
    monkeypatch.setattr(extracao_mod, "_executar_idempotente", _forcar_antecedencia)
    conn = _Ctx.db_pool.conn

    async def _explode(sql: str, params: Any = ()) -> _Result:
        raise RuntimeError("banco fora do ar")

    monkeypatch.setattr(conn, "execute", _explode)
    with pytest.raises(ToolException) as exc:
        await _chamar(
            proxima_acao_esperada="agendar o horário",
            runtime=_Runtime({"horario_minimo": datetime(2026, 8, 12, 21, 30, tzinfo=BRT)}),
        )
    assert "cedo demais" in str(exc.value)
