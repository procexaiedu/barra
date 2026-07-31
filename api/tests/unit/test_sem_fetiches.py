"""Trilho determinístico do cardápio de ATOS vazio (issue 15 do refactor de prompt): modelo sem
nenhum vínculo em `modelo_fetiches` injeta <sem_fetiches> na cauda — a mecânica de extra cotado e
de item incluso do <fora_do_cardapio> colapsa por DADO na recusa curta, em vez de a IA ter de
derivá-la de um bloco vazio a cada turno.

Mesma família derivada do cardápio do <sem_periodo_longo>/<sem_menage>/<sem_video_chamada>: a
condição sai do CADASTRO (as mesmas linhas de fetiche que o BP_MODELO já lê), não de um evento da
conversa — por isso não é flag A2 materializada (sem coluna, sem detector, sem migration).

A metade DETERMINÍSTICA da mesma regra é o `bolhas_incluso_fantasma` do output_guard (issue 07):
o que a prosa deixa de dizer aqui continua tendo rede lá, inclusive para a modelo que TEM lista mas
não tem linha "Inclusos" (só extras pagos) — essa não recebe a tag.
"""

from datetime import UTC, datetime
from typing import Any

from barra.agente.contexto import ContextAgente
from barra.agente.nos.prepare_context import _carregar_bp3, _resolver_variaveis
from barra.agente.persona import render_contexto_dinamico


class _Result:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    async def fetchone(self) -> dict[str, Any] | None:
        return self.rows[0] if self.rows else None

    async def fetchall(self) -> list[dict[str, Any]]:
        return self.rows


class _FakeConn:
    """Vazio em tudo: a ausência de fetiches chega por kwarg (derivada das linhas já lidas em
    _carregar_bp3), não por query própria."""

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> _Result:
        return _Result([])


class _ConnCardapio:
    """Devolve o cardápio da modelo para `_carregar_bp3`: 1ª query = `modelos`, 2ª = programas,
    3ª = fetiches (a ordem das queries no nó)."""

    def __init__(self, fetiches: list[dict[str, Any]]) -> None:
        self._respostas = [
            [{"nome": "Manu", "idade": 25, "idiomas": [], "tipo_atendimento_aceito": ["interno"]}],
            [{"nome": "Encontro", "duracao_nome": "1 hora", "duracao_horas": 1, "preco": 400}],
            fetiches,
        ]

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> _Result:
        return _Result(self._respostas.pop(0))


def _ctx() -> ContextAgente:
    return ContextAgente(
        db_pool=None,  # type: ignore[arg-type]  # não usado por _resolver_variaveis
        redis=None,  # type: ignore[arg-type]
        modelo_id="11111111-1111-1111-1111-111111111111",
        atendimento_id="22222222-2222-2222-2222-222222222222",
        cliente_id="33333333-3333-3333-3333-333333333333",
        turno_id="t",
        agora_utc=datetime(2026, 7, 30, 23, 0, tzinfo=UTC),
    )


async def _contexto(sem_fetiches: bool) -> Any:
    return await _resolver_variaveis(
        _FakeConn(),  # type: ignore[arg-type]
        _ctx(),
        atendimento={"numero_curto": 1, "estado": "Triagem", "tipo_atendimento": None},
        sem_fetiches=sem_fetiches,
    )


# --- a tag na cauda -----------------------------------------------------------------------------


async def test_cardapio_vazio_injeta_a_tag_com_a_recusa_e_a_saida() -> None:
    saida = render_contexto_dinamico(**(await _contexto(True)).como_variaveis())

    assert "<sem_fetiches>" in saida
    # (1) recusa curta de mulher, sem moralizar — a fala é a mesma do <fora_do_cardapio>.
    assert "Não faço amor" in saida
    assert "sem moralizar" in saida
    # (2) a recusa não cresce pro encontro: o programa segue oferecido (fala de substituição, a
    # lição do incidente #36 — proibir sem dar saída foi o que criou o bug).
    assert "Nada disso encolhe o encontro" in saida
    assert "<programas>" in saida
    # (3) o incluso fantasma, que é a falha MEDIDA com o bloco vazio (trace do inventário): nem
    # copiado do exemplo da conduta.
    assert "nem copiado de um exemplo desta conduta" in saida
    # (4) insistência com mais dinheiro não vira preço — escala.
    assert "fora_de_oferta" in saida


async def test_a_tag_nao_engole_a_clausula_da_camisinha() -> None:
    """A cláusula que NÃO encolhe: camisinha não é item de lista e nunca sai como "incluso".

    Nasceu de falha real e nenhum guard determinístico a pega (o `bolhas_incluso_fantasma` deixa
    `camisinha` FORA do vocabulário absolvedor, mas "Só faço com camisinha amor" não tem claim de
    incluso e passa por ele). Ela continua no BP_GERAL, inteira, e a tag reafirma o enquadramento
    em vez de deixá-la cair no caminho do corte."""
    from barra.agente.persona import render_prefixo_geral

    assert "Só faço com camisinha amor" in render_prefixo_geral()
    assert "Camisinha não é item da sua lista" in render_prefixo_geral()

    saida = render_contexto_dinamico(**(await _contexto(True)).como_variaveis())
    assert "Camisinha fica fora dessa conta" in saida
    assert "não é item de lista" in saida


async def test_com_fetiches_a_cauda_nao_diz_nada_de_cardapio_vazio() -> None:
    saida = render_contexto_dinamico(**(await _contexto(False)).como_variaveis())

    assert "<sem_fetiches>" not in saida


# --- a condição: as MESMAS linhas de fetiche que o <fetiches> do BP_MODELO renderiza ------------


async def _do_cardapio(fetiches: list[dict[str, Any]]) -> tuple[bool, str]:
    """(`sem_fetiches` derivado em `_carregar_bp3`, o BP_MODELO que a MESMA lista renderiza)."""
    md, _nome, _max, sem_fetiches, _menage, _chamada, _end, _local = await _carregar_bp3(
        _ConnCardapio(fetiches),  # type: ignore[arg-type]
        "11111111-1111-1111-1111-111111111111",
    )
    return sem_fetiches, md


async def test_sem_vinculo_nenhum_liga_a_tag_e_o_bloco_sai_vazio() -> None:
    sem_fetiches, md = await _do_cardapio([])

    assert sem_fetiches is True
    # O espelho exato: a tag só entra quando o BP_MODELO imprime "(sem fetiches cadastrados)".
    assert "(sem fetiches cadastrados)" in md


async def test_so_incluso_desliga_a_tag() -> None:
    sem_fetiches, md = await _do_cardapio(
        [{"nome": "Beijo na boca", "preco": None, "cobra_por_pessoa": False}]
    )

    assert sem_fetiches is False
    assert "(sem fetiches cadastrados)" not in md


async def test_so_extra_pago_desliga_a_tag() -> None:
    """Cardápio só de extras PAGOS tem lista (tem o que cotar) — a tag não entra, mesmo sem a linha
    "Inclusos". Esse caso fica com o guard determinístico (`bolhas_incluso_fantasma` com conjunto
    vazio), que é justamente quem cobre o "tá incluso" sem linha no bloco."""
    sem_fetiches, md = await _do_cardapio(
        [{"nome": "Inversão", "preco": 350, "cobra_por_pessoa": False}]
    )

    assert sem_fetiches is False
    assert "(sem fetiches cadastrados)" not in md


async def test_so_por_pessoa_desliga_a_tag() -> None:
    sem_fetiches, md = await _do_cardapio(
        [{"nome": "Menage", "preco": 700, "cobra_por_pessoa": True}]
    )

    assert sem_fetiches is False
    assert "(sem fetiches cadastrados)" not in md
