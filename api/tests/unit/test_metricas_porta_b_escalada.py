"""A porta B da escalada deixa de ser invisível em Prometheus.

A escalada tem três portas e só uma era medida: a tool `escalar` (o LLM decidindo) emitia
`agente_escalada_total`; as guardas DETERMINÍSTICAS da extração (`_escalar_modelo`, no domínio) e o
coordenador não emitiam nada. Consequência concreta do ciclo 7: 3 dos 4 handoffs indevidos nasceram
na porta B — a IA escreveu a resposta certa, uma guarda apagou a fala, abriu handoff e pausou a IA —
e nenhum deles apareceria em `agente_escalada_total`.

O que este arquivo fixa:
- `agente_escalada_dominio_total{motivo,fase}` existe e conta a porta B, e só conta o handoff que
  virou LINHA (o `abrir_handoff` é idempotente e devolve `None` quando já havia uma escalada
  aberta; contar ali inflaria a série a cada reprocessamento do turno);
- `agente_escalada_total` ganhou a label `fase` — escalada em `Novo`/`Triagem` é a assinatura do
  handoff indevido, e sem ela a série diz quantas escaladas houve sem dizer se são saudáveis;
- `fase` é fechada pelo enum de estado, com fallback `desconhecida` que nunca derruba um handoff.

Sem DB e sem crédito.
"""

from typing import Any
from uuid import uuid4

import pytest
from prometheus_client import REGISTRY

from barra.core.metrics import AGENTE_ESCALADA, AGENTE_ESCALADA_DOMINIO
from barra.dominio.atendimentos.service import _escalar_modelo
from barra.dominio.escaladas import service as escaladas_service

_METRICA_DOMINIO = "agente_escalada_dominio_total"


class _FakeResult:
    def __init__(self, row: dict[str, Any] | None) -> None:
        self._row = row

    async def fetchone(self) -> dict[str, Any] | None:
        return self._row


class _FakeConn:
    def __init__(self, row: dict[str, Any] | None) -> None:
        self._row = row

    async def execute(self, sql: str, params: Any = None) -> _FakeResult:
        return _FakeResult(self._row)


def _dominio(motivo: str, fase: str) -> float:
    # Gotcha do repo: `get_sample_value` NÃO duplica o sufixo `_total`.
    return REGISTRY.get_sample_value(_METRICA_DOMINIO, {"motivo": motivo, "fase": fase}) or 0.0


async def test_fase_do_atendimento_le_o_estado() -> None:
    conn = _FakeConn({"estado": "Aguardando_confirmacao"})

    fase = await escaladas_service.fase_do_atendimento(conn, uuid4())  # type: ignore[arg-type]

    assert fase == "Aguardando_confirmacao"


@pytest.mark.parametrize("row", [None, {}, {"estado": None}])
async def test_fase_desconhecida_nunca_derruba_o_handoff(row: dict[str, Any] | None) -> None:
    """Atendimento apagado, linha sem a coluna: a label cai no fallback e a escalada segue de pé.
    Uma métrica não pode ser o motivo de um handoff de defesa não abrir."""
    conn = _FakeConn(row)

    assert await escaladas_service.fase_do_atendimento(conn, uuid4()) == "desconhecida"  # type: ignore[arg-type]


async def test_escalada_do_dominio_conta_com_motivo_e_fase(monkeypatch: Any) -> None:
    """O caso 4 do ciclo 7 em miniatura: guarda do piso abrindo handoff em `Triagem`."""
    monkeypatch.setattr(escaladas_service, "abrir_handoff", _abrir_handoff_criou)
    conn = _FakeConn({"estado": "Triagem"})
    antes = _dominio("fora_de_oferta", "Triagem")

    await _escalar_modelo(
        conn,  # type: ignore[arg-type]
        uuid4(),
        motivo="fora_de_oferta",
        resumo="Cliente fechou abaixo do piso.",
        acao="Confirmar se aceita o valor.",
    )

    assert _dominio("fora_de_oferta", "Triagem") == antes + 1


async def test_handoff_reaproveitado_nao_re_conta(monkeypatch: Any) -> None:
    """`abrir_handoff` devolvendo `None` = já havia escalada aberta, nada foi gravado. Contar ali
    é o mesmo furo que `ferramentas/escalada.py` já tinha fechado do lado do LLM."""
    monkeypatch.setattr(escaladas_service, "abrir_handoff", _abrir_handoff_noop)
    conn = _FakeConn({"estado": "Novo"})
    antes = _dominio("reagendamento_pos_bloqueio", "Novo")

    await _escalar_modelo(
        conn,  # type: ignore[arg-type]
        uuid4(),
        motivo="reagendamento_pos_bloqueio",
        resumo="Cliente quer mudar o horário já reservado.",
        acao="Confirmar o horário novo.",
    )

    assert _dominio("reagendamento_pos_bloqueio", "Novo") == antes


def test_series_tem_as_labels_do_contrato() -> None:
    """As duas séries são IRMÃS, não a mesma: `agente_escalada_total` significa "o LLM decidiu" e
    `agente_escalada_dominio_total` "uma guarda determinística decidiu". Os alertas propostos
    (`fase=~"Novo|Triagem"`) dependem das labels; renomear aqui quebra o painel."""
    assert AGENTE_ESCALADA._labelnames == ("bucket", "motivo", "fase")
    assert AGENTE_ESCALADA_DOMINIO._labelnames == ("motivo", "fase")


async def _abrir_handoff_criou(conn: Any, **kwargs: Any) -> Any:
    return uuid4()


async def _abrir_handoff_noop(conn: Any, **kwargs: Any) -> Any:
    return None
