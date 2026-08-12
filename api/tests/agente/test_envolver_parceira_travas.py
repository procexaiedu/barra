"""As travas de WRITE-TIME da tool `envolver_parceira` (ADR-0042).

O prompt pode errar; o discriminante cobre o TURNO. Estas três travas cobrem a conversa inteira, no
banco, e são o que impede o pior caso mesmo com um turno mal-formado:

1. **whitelist do par** — sem linha ativa em `modelo_parcerias`, ou sem a flag do modo pedido,
   nenhum dos dois fluxos acontece;
2. **aceite dele antes de qualquer dado dela** — `encaminhar` exige `amiga_ofertada_em` já
   carimbado, e esse carimbo é write-time do ENVIO: ele só existe num turno ANTERIOR, então o
   contato nunca sai na mesma resposta em que ela ofereceu a parceira;
3. **uma vez por atendimento** + **fluxos mutuamente exclusivos** — o encaminhamento não se repete,
   e quem entrou por um caminho não reabre pelo outro.

Sem DB: um fake de conexão responde as duas leituras da tool (`modelo_parcerias` e as flags do
atendimento) e registra o UPDATE que o efeito dispara.
"""

from contextlib import asynccontextmanager
from typing import Any

import pytest
from langchain_core.tools import ToolException

from barra.agente.ferramentas.parceria import envolver_parceira

# .coroutine é a corrotina crua do @tool; .ainvoke({...}) NÃO injeta runtime, .coroutine sim.
_chamar = envolver_parceira.coroutine  # type: ignore[attr-defined]

_PARCERIA_CHEIA: dict[str, Any] = {
    "parceira_id": "019ff2e1-339a-7a7f-ae5c-a63e5796883f",
    "nome": "Yasmin",
    "idade": 19,
    "encaminhamento_ativo": True,
    "encaminhamento_atos": ["anal"],
    "dupla_ativa": True,
}
_SEM_FLAG: dict[str, Any] = {
    "amiga_ofertada_em": None,
    "parceira_encaminhada_em": None,
    "parceira_dupla_em": None,
}


class _Result:
    def __init__(self, row: dict[str, Any] | None) -> None:
        self._row = row

    async def fetchone(self) -> dict[str, Any] | None:
        return self._row


class _Conn:
    def __init__(self, parceria: dict[str, Any] | None, flags: dict[str, Any]) -> None:
        self._parceria = parceria
        self._flags = flags
        self.updates: list[str] = []

    @asynccontextmanager
    async def transaction(self) -> Any:
        yield

    async def execute(self, query: str, params: Any = None) -> _Result:
        if "modelo_parcerias" in query:
            return _Result(self._parceria)
        if "amiga_ofertada_em" in query and "SELECT" in query:
            return _Result(self._flags)
        if "INSERT INTO barravips.tool_calls" in query and "RETURNING" in query:
            return _Result({"turno_id": params[0]})
        if query.strip().startswith("UPDATE barravips.atendimentos"):
            self.updates.append(query)
            return _Result(None)
        return _Result(None)


class _Pool:
    def __init__(self, conn: _Conn) -> None:
        self.conn = conn

    @asynccontextmanager
    async def connection(self) -> Any:
        yield self.conn


class _Ctx:
    def __init__(self, conn: _Conn) -> None:
        self.db_pool = _Pool(conn)
        self.redis = None
        self.modelo_id = "00000000-0000-0000-0000-0000000000aa"
        self.atendimento_id = "00000000-0000-0000-0000-000000000001"
        self.cliente_id = "00000000-0000-0000-0000-000000000003"
        self.turno_id = "00000000-0000-0000-0000-000000000002"
        self.agora_utc = None


class _Runtime:
    def __init__(self, ctx: _Ctx) -> None:
        self.context = ctx


def _rt(parceria: dict[str, Any] | None = _PARCERIA_CHEIA, **flags: Any) -> tuple[_Runtime, _Conn]:
    conn = _Conn(parceria, {**_SEM_FLAG, **flags})
    return _Runtime(_Ctx(conn)), conn


# --- 1. whitelist do par -------------------------------------------------------------------------


async def test_sem_parceria_cadastrada_os_dois_modos_recusam() -> None:
    for modo in ("dupla", "encaminhar"):
        runtime, conn = _rt(parceria=None)
        with pytest.raises(ToolException, match="não tem parceira"):
            await _chamar(modo=modo, runtime=runtime)
        assert conn.updates == []


async def test_modo_nao_liberado_recusa_sem_efeito() -> None:
    so_dupla = {**_PARCERIA_CHEIA, "encaminhamento_ativo": False}
    runtime, conn = _rt(parceria=so_dupla, amiga_ofertada_em="2026-08-11")
    with pytest.raises(ToolException, match="não está liberado"):
        await _chamar(modo="encaminhar", runtime=runtime)
    assert conn.updates == []


# --- 2. aceite dele antes de qualquer dado dela ---------------------------------------------------


async def test_encaminhar_sem_a_oferta_previa_recusa() -> None:
    """O contato NÃO sai no mesmo turno da oferta: `amiga_ofertada_em` é carimbado no write-time do
    envio, então ele só existe depois que a bolha da oferta foi de fato entregue."""
    runtime, conn = _rt()
    with pytest.raises(ToolException, match="ainda não ofereceu"):
        await _chamar(modo="encaminhar", runtime=runtime)
    assert conn.updates == []


async def test_encaminhar_com_a_oferta_previa_carimba() -> None:
    runtime, conn = _rt(amiga_ofertada_em="2026-08-11T00:00:00Z")

    retorno = await _chamar(modo="encaminhar", runtime=runtime)

    assert "Yasmin" in retorno
    assert "NÃO escreva número nenhum" in retorno
    assert "não cote valor" in retorno.lower()
    assert any("parceira_encaminhada_em" in u for u in conn.updates)


async def test_a_dupla_nao_exige_oferta_previa() -> None:
    """Assimetria proposital: nada dela sai no fluxo B — nem contato, nem nome novo ao cliente que
    ela não fosse dizer de qualquer jeito —, então não há dado a proteger com um aceite."""
    runtime, conn = _rt()

    retorno = await _chamar(modo="dupla", runtime=runtime)

    assert "coordenação já foi avisada" in retorno
    assert "NUNCA vai ao cliente" in retorno
    assert any("parceira_dupla_em" in u for u in conn.updates)


# --- 3. uma vez por atendimento + fluxos mutuamente exclusivos -----------------------------------


async def test_encaminhamento_e_uma_vez_por_atendimento() -> None:
    runtime, conn = _rt(
        amiga_ofertada_em="2026-08-11T00:00:00Z",
        parceira_encaminhada_em="2026-08-11T01:00:00Z",
    )
    with pytest.raises(ToolException, match="já passou o contato"):
        await _chamar(modo="encaminhar", runtime=runtime)
    assert conn.updates == []


async def test_negociacao_de_dupla_nunca_vira_encaminhamento() -> None:
    """O pior caso do produto: o telefone dela indo para quem estava comprando as duas."""
    runtime, conn = _rt(
        amiga_ofertada_em="2026-08-11T00:00:00Z",
        parceira_dupla_em="2026-08-11T01:00:00Z",
    )
    with pytest.raises(ToolException, match="já entrou pelo outro caminho"):
        await _chamar(modo="encaminhar", runtime=runtime)
    assert conn.updates == []


async def test_negociacao_encaminhada_nunca_vira_dupla() -> None:
    """O sentido inverso: depois de mandar o contato, ela não volta a vender as duas."""
    runtime, conn = _rt(parceira_encaminhada_em="2026-08-11T01:00:00Z")
    with pytest.raises(ToolException, match="já entrou pelo outro caminho"):
        await _chamar(modo="dupla", runtime=runtime)
    assert conn.updates == []


async def test_o_retorno_ao_llm_nunca_carrega_o_telefone() -> None:
    """O telefone não passa pelo LLM em ponto nenhum: a tool devolve conduta, e o número nasce
    depois, na bolha determinística do coordenador."""
    runtime, _conn = _rt(amiga_ofertada_em="2026-08-11T00:00:00Z")

    retorno = await _chamar(modo="encaminhar", runtime=runtime)

    assert not any(c.isdigit() for c in retorno)
