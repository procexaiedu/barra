"""Marca de pausa na janela + ordem da cauda (incidente prod 29/07, trace 06db4298).

A janela são as últimas 40 msgs do PAR e cruza atendimentos de propósito (CONTEXT.md "Conversa
cliente"), mas o `created_at` era descartado na tradução: 36 bolhas de 23/07 e um "Oi" de 29/07
chegaram ao modelo como conversa CONTÍGUA e ele reciclou o horário de seis dias antes,
contradizendo o belief do atendimento novo. Duas frentes, ambas cobertas aqui:

  1. a marca de pausa entre bolhas distantes — inserida, byte-idêntica entre renders (pré-requisito
     do cache) e respeitada pelos detectores como fronteira ESTRUTURAL;
  2. a cauda invertida — contexto dinâmico ANTES da fala do cliente, para o último token antes da
     resposta ser o que ele disse.

Puro: sem DB, sem crédito.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from barra.agente._texto_turno import e_marca_pausa
from barra.agente.contexto import ContextAgente
from barra.agente.nos._janela_do_turno import (
    _burst_do_cliente,
    _confirmou_dia_hoje,
    _horario_evidenciado_no_turno,
)
from barra.agente.nos.prepare_context import (
    _anexar_contexto_dinamico,
    _injetar_reminder_se_necessario,
    traduzir_mensagens,
)

_BASE = datetime(2026, 7, 23, 16, 0, tzinfo=UTC)


def _linha(direcao: str, conteudo: str, criada_em: datetime | None) -> dict[str, Any]:
    """Linha de `mensagens` na forma que `carregar_mensagens` devolve (já cronológica)."""
    return {
        "id": f"id-{conteudo[:8]}-{criada_em.isoformat() if criada_em else 'sem-data'}",
        "direcao": direcao,
        "tipo": "texto",
        "conteudo": conteudo,
        "media_object_key": None,
        "created_at": criada_em,
    }


# --- frente 1: a marca de pausa ------------------------------------------------------------------


def test_marca_de_pausa_entra_no_gap_de_seis_dias() -> None:
    """O caso do trace: a cauda de 23/07 e o "Oi" de 29/07 deixam de ser conversa contígua."""
    linhas = [
        _linha("cliente", "Posso confirmar amanhã 16h então ?", _BASE),
        _linha("cliente", "Oi", _BASE + timedelta(days=6)),
    ]
    msgs = traduzir_mensagens(linhas)

    assert [str(m.content) for m in msgs] == [
        "Posso confirmar amanhã 16h então ?",
        "[pausa de 6 dias na conversa]",
        "Oi",
    ]
    assert e_marca_pausa(msgs[1])
    # id DETERMINÍSTICO derivado da bolha SEGUINTE e nunca None: `_janela_para_extracao` monta
    # `do_banco = {m.id for m in crua}` e um None passaria a excluir do extrator toda mensagem do
    # turno sem id.
    assert msgs[1].id == f"pausa-{linhas[1]['id']}"
    assert all(m.id is not None for m in msgs)


def test_marca_de_pausa_em_horas_abaixo_de_48h() -> None:
    """Abaixo de 48h a pausa é dita em horas; de 48h em diante, em dias."""
    curta = traduzir_mensagens(
        [
            _linha("cliente", "e amanhã?", _BASE),
            _linha("cliente", "voltei", _BASE + timedelta(hours=7, minutes=40)),
        ]
    )
    longa = traduzir_mensagens(
        [
            _linha("cliente", "e amanhã?", _BASE),
            _linha("cliente", "voltei", _BASE + timedelta(hours=48)),
        ]
    )

    assert str(curta[1].content) == "[pausa de 7h na conversa]"
    assert str(longa[1].content) == "[pausa de 2 dias na conversa]"


def test_sem_marca_quando_a_conversa_e_seguida() -> None:
    """Pausa curta (a negociação da madrugada) segue contígua: nenhuma marca, nenhuma bolha nova."""
    linhas = [
        _linha("cliente", "tá atendendo?", _BASE),
        _linha("ia", "Seria agora ?", _BASE + timedelta(minutes=1)),
        _linha("cliente", "sim", _BASE + timedelta(hours=5, minutes=59)),
    ]
    msgs = traduzir_mensagens(linhas)

    assert len(msgs) == 3
    assert not any(e_marca_pausa(m) for m in msgs)


def test_linha_sem_created_at_nao_inventa_marca() -> None:
    """Linha sem `created_at` (fixtures/testes que chamam a tradução direto) não gera marca nem
    perde a âncora da bolha anterior."""
    linhas = [
        _linha("cliente", "oi", _BASE),
        _linha("cliente", "sem data", None),
        _linha("cliente", "Oi", _BASE + timedelta(days=6)),
    ]
    msgs = traduzir_mensagens(linhas)

    assert [str(m.content) for m in msgs] == [
        "oi",
        "sem data",
        "[pausa de 6 dias na conversa]",
        "Oi",
    ]


def test_render_da_janela_byte_identico_em_dois_renders() -> None:
    """Guard-rail de cache (agente/CLAUDE.md): a marca é função PURA dos dois `created_at`
    vizinhos, nunca de "agora" — dois renders da MESMA janela saem byte-idênticos, senão o prefixo
    muda a cada turno e o cache do DeepSeek mira a frio para TODAS as modelos."""
    linhas = [
        _linha("cliente", "Umas 16 horas", _BASE),
        _linha("ia", "16h ótimo", _BASE + timedelta(minutes=1)),
        _linha("cliente", "Oi", _BASE + timedelta(days=6)),
    ]
    a = traduzir_mensagens(linhas)
    b = traduzir_mensagens(linhas)

    assert [(m.type, str(m.content), m.id) for m in a] == [
        (m.type, str(m.content), m.id) for m in b
    ]


# --- frente 1: os detectores param na marca ------------------------------------------------------


def _janela_com_pausa() -> list[BaseMessage]:
    """A janela do trace, encurtada: negociação de 23/07 com horário combinado, seis dias de
    silêncio e o "Oi" de 29/07 abrindo um atendimento NOVO."""
    return traduzir_mensagens(
        [
            _linha("ia", "seria hoje ?", _BASE),
            _linha("cliente", "sim", _BASE + timedelta(minutes=1)),
            _linha("cliente", "Umas 16 horas", _BASE + timedelta(minutes=2)),
            _linha("cliente", "Oi", _BASE + timedelta(days=6)),
        ]
    )


def test_burst_do_cliente_para_na_marca() -> None:
    """O burst é a fala contígua dele AGORA: só o "Oi". Sem a parada, a marca (HumanMessage
    sintética) e as bolhas de seis dias atrás entrariam no burst como fala do cliente."""
    mensagens = _janela_com_pausa()
    inicio = _burst_do_cliente(mensagens)

    assert [str(m.content) for m in mensagens[inicio:]] == ["Oi"]


def test_horario_evidenciado_nao_atravessa_a_marca() -> None:
    """ "Umas 16 horas" é de seis dias atrás: não sustenta horário no turno do "Oi" (era o que fazia
    a IA reciclar o horário antigo). A MESMA janela, sem a pausa, evidencia."""
    assert _horario_evidenciado_no_turno(_janela_com_pausa()) is False

    seguida = traduzir_mensagens(
        [
            _linha("ia", "seria hoje ?", _BASE),
            _linha("cliente", "Umas 16 horas", _BASE + timedelta(minutes=1)),
        ]
    )
    assert _horario_evidenciado_no_turno(seguida) is True


def test_confirmou_dia_hoje_nao_atravessa_a_marca() -> None:
    """O par "seria hoje ?" + "sim" de seis dias atrás não acende o dia de HOJE no belief."""
    assert _confirmou_dia_hoje(_janela_com_pausa()) is False

    seguida = traduzir_mensagens(
        [
            _linha("ia", "seria hoje ?", _BASE),
            _linha("cliente", "sim", _BASE + timedelta(minutes=1)),
        ]
    )
    assert _confirmou_dia_hoje(seguida) is True


def test_confirmou_dia_hoje_nao_liga_sondagem_antiga_a_sim_novo() -> None:
    """O par que ATRAVESSA a pausa: a sondagem ficou no trecho antigo e o "sim" é de hoje — não é
    resposta a uma pergunta de seis dias atrás."""
    mensagens = traduzir_mensagens(
        [
            _linha("ia", "seria hoje ?", _BASE),
            _linha("cliente", "sim", _BASE + timedelta(days=6)),
        ]
    )

    assert any(e_marca_pausa(m) for m in mensagens)
    assert _confirmou_dia_hoje(mensagens) is False


# --- frente 2: a ordem da cauda ------------------------------------------------------------------


class _FakeConnVazio:
    """Vazio em tudo: o atendimento chega por kwarg e o relógio vem injetado."""

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> Any:
        class _R:
            async def fetchone(self) -> None:
                return None

            async def fetchall(self) -> list[Any]:
                return []

        return _R()


def _ctx() -> ContextAgente:
    return ContextAgente(
        atendimento_id="22222222-2222-2222-2222-222222222222",
        db_pool=None,  # type: ignore[arg-type]
        redis=None,  # type: ignore[arg-type]
        modelo_id="11111111-1111-1111-1111-111111111111",
        cliente_id="33333333-3333-3333-3333-333333333333",
        turno_id="t",
        agora_utc=datetime(2026, 7, 29, 17, 30, tzinfo=UTC),
    )


async def _cauda(janela: list[BaseMessage], *, com_lembrete: bool) -> str:
    """A cauda como o chat a recebe: contexto dinâmico anexado e, acima do limiar, o lembrete —
    na MESMA ordem em que o `prepare_context` os aplica."""
    mensagens, contexto, _pecas = await _anexar_contexto_dinamico(
        _FakeConnVazio(),  # type: ignore[arg-type]
        _ctx(),
        janela,
        atendimento={"estado": "Novo", "numero_curto": 7},
    )
    if com_lembrete:
        mensagens = _injetar_reminder_se_necessario(mensagens, contexto.estado, "Lucia")
    return str(mensagens[-1].content)


async def test_ordem_da_cauda_sem_lembrete() -> None:
    """Contexto dinâmico → fala do cliente: o último token antes de responder é o que ele disse, não
    uma `<observacao>` do belief (no trace o "Oi" caía no offset 2.076 de 4.548 chars)."""
    cauda = await _cauda(
        [AIMessage(content="oi amor"), HumanMessage(content="Oi", id="m1")], com_lembrete=False
    )

    assert cauda.startswith("<situacao_do_atendimento")
    assert cauda.endswith("\n\nOi")
    assert "<lembrete_silencioso>" not in cauda


async def test_ordem_da_cauda_com_lembrete() -> None:
    """Com o lembrete anti-drift (≥8 AIMessages) a ordem é lembrete → contexto → fala: o lembrete
    é prepend, então a fala continua por último."""
    janela: list[BaseMessage] = [AIMessage(content=f"bolha {i}") for i in range(8)]
    janela.append(HumanMessage(content="Oi", id="m1"))
    cauda = await _cauda(janela, com_lembrete=True)

    assert cauda.startswith("<lembrete_silencioso>")
    assert cauda.index("<situacao_do_atendimento") < cauda.index("\n\nOi")
    assert cauda.endswith("\n\nOi")


async def test_cauda_preserva_o_id_da_msg_do_cliente() -> None:
    """A cauda continua sendo a MESMA HumanMessage do cliente: um id novo faria o belief vazar p/ a
    janela do extrator via `do_turno` (`_janela_para_extracao`, nos/extrair.py)."""
    janela: list[BaseMessage] = [HumanMessage(content="Oi", id="m1")]
    mensagens, _contexto, _pecas = await _anexar_contexto_dinamico(
        _FakeConnVazio(),  # type: ignore[arg-type]
        _ctx(),
        janela,
        atendimento={"estado": "Novo"},
    )

    assert mensagens[-1].id == "m1"
