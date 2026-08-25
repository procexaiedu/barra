"""Vídeo chamada tinha DOIS interruptores independentes — `_tipo_aceito` passa a ler os dois.

O mesmo produto era governado por dois campos sem validação cruzada nenhuma: o PROMPT decide se
vende pelo CARDÁPIO (`prepare_context._carregar_bp3` → `sem_video_chamada`, derivado de
`e_video_chamada` sobre `modelo_programas`) e o DOMÍNIO decidia se aceita pelo CHECKBOX
(`modelos.tipo_atendimento_aceito[]`, lido por `_tipo_aceito`). O modo `checkbox OFF + programa
PRESENTE` é a violação direta da regra do dono ("o que está no cardápio dela não pode virar
handoff"): a IA vendia a chamada e cotava o preço da tabela enquanto toda extração `remoto` era
descartada em silêncio — a venda acontecia na conversa e não existia no sistema, e o trilho
ADR-0021/0029 (bloqueio prévio, Pix antecipado, cron, card) nunca armava.

As quatro combinações (checkbox x programa) estão aqui, mais os tipos presenciais — que NÃO mudam,
porque para eles não existe um segundo site de verdade (o `sem_externo` do prompt lê essa MESMA
coluna). Sem DB e sem crédito: `_tipo_aceito` faz UMA query, então um fake de uma linha basta.
"""

from typing import Any
from uuid import uuid4

from prometheus_client import REGISTRY

from barra.dominio.atendimentos.service import _label_tipo, _tipo_aceito

_METRICA_INCOERENTE = "agente_cadastro_remoto_incoerente_total"


class _FakeResult:
    def __init__(self, row: dict[str, Any] | None) -> None:
        self._row = row

    async def fetchone(self) -> dict[str, Any] | None:
        return self._row


class _FakeConn:
    """Devolve a linha do JOIN atendimentos x modelos (+ os nomes dos programas dela)."""

    def __init__(self, row: dict[str, Any] | None) -> None:
        self._row = row
        self.queries: list[str] = []

    async def execute(self, sql: str, params: Any = None) -> _FakeResult:
        self.queries.append(sql)
        return _FakeResult(self._row)


def _conn(aceitos: list[str], programas: list[str]) -> _FakeConn:
    return _FakeConn({"aceitos": aceitos, "programas": programas})


def _incoerente(modo: str) -> float:
    # Gotcha do repo: `get_sample_value` NÃO duplica o sufixo `_total`.
    return REGISTRY.get_sample_value(_METRICA_INCOERENTE, {"modo": modo}) or 0.0


async def _aceita(aceitos: list[str], programas: list[str], tipo: str = "remoto") -> bool:
    return await _tipo_aceito(_conn(aceitos, programas), uuid4(), tipo)  # type: ignore[arg-type]


# --- as quatro combinações de checkbox x programa, para `remoto` ------------------------------


async def test_checkbox_on_programa_on_aceita() -> None:
    """O cadastro coerente do ADR-0021 ("`remoto` em aceito[] E o programa"): nada muda."""
    assert await _aceita(["interno", "remoto"], ["Massagem", "Vídeo chamada"]) is True


async def test_checkbox_off_programa_on_aceita_por_derivacao() -> None:
    """O modo que doía: ela VENDE a chamada (o prompt cota 150/15min) e o checkbox está off.

    Antes do ciclo 7 isso ESCALAVA (handoff no turno 1, IA pausada, conversa morta); depois virou
    descarte mudo — melhor e ainda errado, porque o atendimento nunca vira `remoto` e o trilho de
    entrega da chamada não arma. O cardápio é o site único de "o que ela vende", então ele decide.
    """
    antes = _incoerente("programa_sem_checkbox")

    assert await _aceita(["interno"], ["Vídeo chamada"]) is True

    assert _incoerente("programa_sem_checkbox") == antes + 1


async def test_checkbox_on_programa_off_segue_aceitando_e_conta() -> None:
    """O modo inverso NÃO muda de comportamento — de propósito.

    Aqui o prompt renderiza `<sem_video_chamada>` ("Não faço chamada amor") e o domínio grava
    `remoto` assim mesmo, o que deixa o `<ja_combinado>` do belief dizendo "remoto" numa conversa
    em que a IA acabou de negar a chamada. Reprovar tiraria uma capacidade que existe hoje em
    produção: é decisão do dono, não do fix. O que o fix faz é PARAR DE SER MUDO sobre ela.
    """
    antes = _incoerente("checkbox_sem_programa")

    assert await _aceita(["interno", "remoto"], ["Massagem"]) is True

    assert _incoerente("checkbox_sem_programa") == antes + 1


async def test_checkbox_off_programa_off_recusa_sem_contar_incoerencia() -> None:
    """Ela não vende chamada por nenhum dos dois lados: descarte, e cadastro NÃO é incoerente."""
    antes = (_incoerente("programa_sem_checkbox"), _incoerente("checkbox_sem_programa"))

    assert await _aceita(["interno"], ["Massagem"]) is False

    assert (_incoerente("programa_sem_checkbox"), _incoerente("checkbox_sem_programa")) == antes


# --- o predicado do cardápio é o mesmo do prompt ----------------------------------------------


async def test_nome_do_programa_segue_o_site_unico_do_predicado() -> None:
    """`e_video_chamada` (core/catalogo) é quem decide, com as mesmas variações que o prompt casa —
    e com o mesmo lado do erro: cadastro batizado só "Vídeo" não casa em lugar nenhum."""
    assert await _aceita(["interno"], ["Videochamada"]) is True
    assert await _aceita(["interno"], ["Chamada de vídeo 15min"]) is True
    assert await _aceita(["interno"], ["Vídeo"]) is False


# --- o que não muda ---------------------------------------------------------------------------


async def test_presenciais_seguem_governados_so_pelo_checkbox() -> None:
    """Para interno/externo não existe segundo site de verdade — nada a derivar, nada a medir."""
    antes = (_incoerente("programa_sem_checkbox"), _incoerente("checkbox_sem_programa"))

    assert await _aceita(["interno"], ["Vídeo chamada"], tipo="interno") is True
    assert await _aceita(["interno"], ["Vídeo chamada"], tipo="externo") is False

    assert (_incoerente("programa_sem_checkbox"), _incoerente("checkbox_sem_programa")) == antes


async def test_array_vazio_segue_aceitando_tudo() -> None:
    """Cadastro incompleto não trava a venda (mesmo espírito de "modelo sem Disponibilidade é
    reservável sempre") — e sem checkbox nenhum não há divergência a contar."""
    antes = (_incoerente("programa_sem_checkbox"), _incoerente("checkbox_sem_programa"))

    assert await _aceita([], []) is True
    assert await _aceita([], [], tipo="externo") is True

    assert (_incoerente("programa_sem_checkbox"), _incoerente("checkbox_sem_programa")) == antes


async def test_atendimento_inexistente_nao_trava() -> None:
    conn = _FakeConn(None)
    assert await _tipo_aceito(conn, uuid4(), "remoto") is True  # type: ignore[arg-type]


async def test_uma_query_so() -> None:
    """A derivação NÃO custa uma segunda ida ao banco por extração: o cardápio vem no mesmo SELECT
    (ARRAY subquery), e a guarda roda em todo turno que traz `tipo_atendimento`."""
    conn = _conn(["interno"], ["Vídeo chamada"])

    await _tipo_aceito(conn, uuid4(), "remoto")  # type: ignore[arg-type]

    assert len(conn.queries) == 1


# --- label da métrica de descarte -------------------------------------------------------------


def test_label_tipo_fecha_no_enum_do_dominio() -> None:
    """`tipo_atendimento` chega de payload de LLM: valor torto não pode virar série nova."""
    assert _label_tipo("remoto") == "remoto"
    assert _label_tipo("interno") == "interno"
    assert _label_tipo("externo") == "externo"
    assert _label_tipo("videochamada") == "outro"
    assert _label_tipo(None) == "outro"
