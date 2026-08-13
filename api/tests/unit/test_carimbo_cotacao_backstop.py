"""Backstop de carimbo da cotação (ADR 0022) e sua aplicação no caminho de persistência do e2e.

Em prod quem carimba `cotacao_enviada_em` sobre o texto que de fato saiu é o worker de envio
(`workers/envio.py`), cobrindo o LLM que esquece de marcar `cotacao_apresentada`. O worker NÃO roda
no harness e2e: a bolha da IA entra em `mensagens` por `evals/e2e/persistencia.py`, que gravava sem
nunca carimbar. Resultado medido (`evals/saidas/conduta-20260730-182944/transcritos.jsonl`, perfil
`decidido_rapido:eb02:156306795180224@lid`): a IA disse "400 1h no meu local amor" no turno 3 e o
validador de ordem acusou "confirmou sem ter cotado" no turno 4 — violação DURA do gate de conduta
produzida pelo harness, não pela conduta.

A regra é UMA (`dominio/atendimentos/service.py`), consumida pelos dois caminhos. Aqui fixamos: o
positivo do caso medido, os negativos que NÃO podem carimbar (carimbar à toa satisfaz o guard de
`CotacaoAusente` e dispara reengajamento sem cotação real) e o efeito no validador de ordem.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from evals.e2e.persistencia import gravar_resposta_ia
from evals.harness import Cenario
from evals.sequencia import avaliar_sequencia, derivar_eventos

from barra.dominio.atendimentos.service import texto_tem_cotacao

# Falas reais dos transcritos: a IA cota em número seco (a persona strippa o cifrão).
COTACAO_MEDIDA = "400 1h no meu local amor"

# --- regra pura: o que tem e o que NÃO tem cara de cotação --------------------------------------


@pytest.mark.parametrize(
    "texto",
    [
        COTACAO_MEDIDA,
        "a hora fica R$800 amor",
        "600 1h no meu local",
        "250 30minutos",
        "2h 900 + uber amor",
        "pernoite 2500 amor",
    ],
)
def test_texto_com_cara_de_cotacao(texto: str) -> None:
    assert texto_tem_cotacao(texto)


@pytest.mark.parametrize(
    "texto",
    [
        # reengajamento (toque único, sem preço — ADR 0022) e canned de handoff
        "oi amor, ainda tá pensando? 🥰",
        "Oii vou responder ele 😊",
        # endereço com número: 3-4 dígitos SEM duração/local não é cotação
        "rua duque de caxias 880 amor",
        "aqui na Barra, Chácara da Barra",
        # hora combinada: 1-2 dígitos ficam fora do valor de 3-4
        "Consigo às 22h amor",
        # marcador de duração sozinho, sem valor
        "consigo 1h sim amor",
        "",
    ],
)
def test_texto_sem_cara_de_cotacao(texto: str) -> None:
    assert not texto_tem_cotacao(texto)


# --- o caminho de persistência do e2e aplica o mesmo backstop -----------------------------------


class _ConnCapta:
    """Conn falsa: registra os UPDATEs de carimbo que `gravar_resposta_ia` dispara."""

    def __init__(self) -> None:
        self.carimbos: list[tuple[str, Any]] = []

    async def execute(self, query: str, params: Any = None) -> Any:
        if "SET cotacao_enviada_em" in query:
            self.carimbos.append((query, params))
        return SimpleNamespace(rowcount=1)


def _cenario(atendimento_id: UUID) -> Cenario:
    return Cenario(
        cliente_id=uuid4(),
        modelo_id=uuid4(),
        conversa_id=uuid4(),
        atendimento_id=atendimento_id,
        programas=[],
    )


async def test_bolha_do_e2e_carimba_a_cotacao_medida() -> None:
    """O caso medido: a fala do turno 3, gravada pelo caminho do e2e SEM `cotacao_apresentada` na
    extração, deixa `cotacao_enviada_em` carimbado — como o worker de envio faria em prod."""
    aid = uuid4()
    conn = _ConnCapta()

    await gravar_resposta_ia(conn, _cenario(aid), COTACAO_MEDIDA)  # type: ignore[arg-type]

    assert len(conn.carimbos) == 1
    query, params = conn.carimbos[0]
    # mesmos guards de prod: first-write-wins + só na fase de venda
    assert "cotacao_enviada_em IS NULL" in query
    # `Novo` entra junto (12/08): a IA cota na PRIMEIRA bolha, quando o atendimento ainda nem saiu
    # de `Novo` — sem ele o carimbo caía no vazio e o `CotacaoAusente` revertia o turno em que o
    # cliente cravava a hora, dois turnos depois.
    assert "estado IN ('Novo', 'Triagem', 'Qualificado')" in query
    assert params == (aid,)


@pytest.mark.parametrize(
    "texto",
    [
        "oi amor, ainda tá pensando? 🥰",
        "rua duque de caxias 880 amor",
        "Oii\n\nBom dia amor 🥰",
    ],
)
async def test_bolha_sem_cotacao_nao_carimba(texto: str) -> None:
    """Negativo: um carimbo a mais é pior que um a menos — satisfaria o guard de `CotacaoAusente` e
    dispararia reengajamento sem cotação real."""
    conn = _ConnCapta()

    await gravar_resposta_ia(conn, _cenario(uuid4()), texto)  # type: ignore[arg-type]

    assert conn.carimbos == []


# --- validador de ordem: o backstop também vale para o evento `cotacao_apresentada` -------------


def _turno(texto: str, *, estado: str, args: dict[str, Any] | None = None) -> Any:
    return SimpleNamespace(
        texto=texto,
        tool_calls=["registrar_extracao"] if args is not None else [],
        tool_args=[args] if args is not None else [],
        estado_final={"estado": estado, "pix_status": "nao_solicitado", "ia_pausada": False},
    )


def test_ordem_aceita_a_cotacao_sem_o_flag_do_llm() -> None:
    """Reprodução do transcrito medido: o LLM não marcou `cotacao_apresentada`, mas a bolha do
    turno 3 disse o preço. O validador não pode acusar "confirmou sem ter cotado"."""
    res = SimpleNamespace(
        turnos=[
            _turno("Oii\n\nBom dia amor 🥰", estado="Triagem", args={"intencao": "informacao"}),
            _turno(COTACAO_MEDIDA, estado="Triagem", args={"intencao": "cotacao"}),
            _turno("Consigo sim amor\n\nSeria agora ?", estado="Aguardando_confirmacao"),
        ]
    )

    assert "cotacao_apresentada" in derivar_eventos(res)
    assert avaliar_sequencia(res) == []  # type: ignore[arg-type]


def test_ordem_ainda_acusa_confirmacao_sem_preco_nenhum() -> None:
    """Negativo do validador: sem preço no flag E sem preço na bolha, a violação continua dura."""
    res = SimpleNamespace(
        turnos=[
            _turno("Oii\n\nBom dia amor 🥰", estado="Triagem", args={"intencao": "informacao"}),
            _turno(
                "Consigo sim amor\n\nte espero às 22h",
                estado="Aguardando_confirmacao",
                args={"horario_desejado": "22:00"},
            ),
        ]
    )

    falhas = avaliar_sequencia(res)  # type: ignore[arg-type]
    assert len(falhas) == 1
    assert "confirmou sem ter cotado" in falhas[0]
