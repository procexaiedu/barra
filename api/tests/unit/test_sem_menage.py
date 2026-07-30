"""Trilho determinístico do menage (issue 11 do refactor de prompt, ADR-0030/0035): modelo sem a
seção "Por pessoa" no <fetiches> injeta <sem_menage> na cauda — ela fica proibida por DADO, não só
por prosa, de cotar/dobrar pacote pra uma segunda pessoa ou prometer amiga que ela não vende.

O gate era o 1º parágrafo do <menage> no BP_GERAL (prefixo byte-idêntico entre TODAS as modelos —
agente/CLAUDE.md), lido e descartado em todo turno de toda modelo sem a seção. Mesmo padrão do
<sem_periodo_longo>. A condição sai do CARDÁPIO (as linhas de fetiche que o BP_MODELO já lê), não
de um evento da conversa — por isso não é flag A2 materializada.
"""

from datetime import UTC, datetime
from typing import Any

from barra.agente.contexto import ContextAgente
from barra.agente.nos.prepare_context import _carregar_bp3, _resolver_variaveis
from barra.agente.persona import render_contexto_dinamico, render_fetiches


class _Result:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    async def fetchone(self) -> dict[str, Any] | None:
        return self.rows[0] if self.rows else None

    async def fetchall(self) -> list[dict[str, Any]]:
        return self.rows


class _FakeConn:
    """Vazio em tudo: a seção "Por pessoa" chega por kwarg (derivada dos fetiches já lidos em
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


async def _contexto(sem_menage: bool) -> Any:
    return await _resolver_variaveis(
        _FakeConn(),  # type: ignore[arg-type]
        _ctx(),
        atendimento={"numero_curto": 1, "estado": "Triagem", "tipo_atendimento": None},
        sem_menage=sem_menage,
    )


# --- a tag na cauda -----------------------------------------------------------------------------


async def test_sem_a_secao_injeta_a_tag_com_a_recusa_inteira() -> None:
    saida = render_contexto_dinamico(**(await _contexto(True)).como_variaveis())

    assert "<sem_menage>" in saida
    # Os três lados que o roteiro `menage_sem_secao` cobra: recusa aberta, nada de dobrar, nada de
    # amiga (a prosa cortada do BP_GERAL dizia os três; a tag é o único site que sobra).
    assert "Não faço amor" in saida
    assert "sem dobrar pacote nenhum" in saida
    assert "sem prometer amiga" in saida
    # E a fala de substituição junto da proibição (lição do incidente #36): a venda dela segue.
    assert "<fora_do_cardapio>" in saida


async def test_com_a_secao_a_cauda_nao_diz_nada_de_menage() -> None:
    saida = render_contexto_dinamico(**(await _contexto(False)).como_variaveis())

    assert "<sem_menage>" not in saida


# --- a condição: mesma leitura do <fetiches> do BP_MODELO ---------------------------------------


async def _sem_menage_do_cardapio(fetiches: list[dict[str, Any]]) -> tuple[bool, str]:
    """(`sem_menage` derivado em `_carregar_bp3`, o <fetiches> que a mesma lista renderiza)."""
    _md, _nome, _max, sem_menage, _end, _local = await _carregar_bp3(
        _ConnCardapio(fetiches),  # type: ignore[arg-type]
        "11111111-1111-1111-1111-111111111111",
    )
    return sem_menage, render_fetiches(
        fetiches, [{"nome": "Encontro", "duracao_nome": "1 hora", "duracao_horas": 1, "preco": 400}]
    )


async def test_fetiche_por_pessoa_pago_e_o_que_desliga_a_tag() -> None:
    sem_menage, bloco = await _sem_menage_do_cardapio(
        [{"nome": "Menage", "preco": 700, "cobra_por_pessoa": True}]
    )

    assert sem_menage is False
    assert "Por pessoa" in bloco


async def test_so_fetiche_ato_mantem_a_tag() -> None:
    # Fetiche pago SEM a flag do catálogo: o <fetiches> abre "Extras pagos" e nenhuma seção
    # "Por pessoa" — menage não existe pra ela.
    sem_menage, bloco = await _sem_menage_do_cardapio(
        [{"nome": "Inversão", "preco": 350, "cobra_por_pessoa": False}]
    )

    assert sem_menage is True
    assert "Por pessoa" not in bloco


async def test_por_pessoa_incluso_nao_abre_a_secao_e_a_tag_fica() -> None:
    # `preco` NULL = incluso: o template filtra por `selectattr('preco')` e o item cai na linha
    # "Inclusos", sem seção "Por pessoa". A derivação espelha ESSA truthiness — divergir faria a
    # cauda liberar o menage de uma modelo cujo bloco não tem tabela pra cotá-lo.
    sem_menage, bloco = await _sem_menage_do_cardapio(
        [{"nome": "Menage", "preco": None, "cobra_por_pessoa": True}]
    )

    assert sem_menage is True
    assert "Por pessoa" not in bloco


async def test_cardapio_vazio_mantem_a_tag() -> None:
    sem_menage, bloco = await _sem_menage_do_cardapio([])

    assert sem_menage is True
    assert "(sem fetiches cadastrados)" in bloco
