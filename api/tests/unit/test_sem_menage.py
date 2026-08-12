"""Trilho determinístico da COMPOSIÇÃO (issue 11 do refactor de prompt, ADR-0030/0035/0039):
modelo sem a seção "Por pessoa" no <fetiches> injeta <sem_menage> na cauda — ela fica proibida por
DADO, não só por prosa, de cotar uma segunda pessoa ou prometer amiga que ela não vende.

O gate continua sendo por CARDÁPIO INTEIRO ("nenhuma composição cadastrada"), e não por item,
depois da taxonomia de 11/08/2026 (migration 20260811232000, quatro itens no lugar de dois): a
ausência de UM item já é tratada, mais fina, pelo `<servico_em_pauta>` do foco, que resolve a fala
do cliente contra o cadastro e emite `fora`. O gate é o piso — quem não tem NADA. O nome da tag
sobrevive por ser identificador interno; a prosa dela não diz mais "menage".

`cobra_por_pessoa` continua sendo a condição do gate DEPOIS do ADR-0039: ela deixou de ser regime
de PREÇO (a 2ª pessoa passou a somar o mesmo extra dos atos) e ficou sendo CLASSIFICAÇÃO — é
exatamente esta tag, e o `composicao_em_pauta`, que a sustentam.

O gate era o 1º parágrafo do <composicoes> no BP_GERAL (prefixo byte-idêntico entre TODAS as modelos —
agente/CLAUDE.md), lido e descartado em todo turno de toda modelo sem a seção. Mesmo padrão do
<sem_periodo_longo>. A condição sai do CARDÁPIO (as linhas de fetiche que o BP_MODELO já lê), não
de um evento da conversa — por isso não é flag A2 materializada.
"""

from datetime import UTC, datetime
from typing import Any

from barra.agente.contexto import ContextAgente
from barra.agente.nos.prepare_context import _carregar_bp3, _resolver_variaveis
from barra.agente.persona import (
    render_bloco_da_modelo,
    render_contexto_dinamico,
    render_fetiches,
)


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


# --- a tag no bloco ESTÁTICO por-modelo ---------------------------------------------------------
#
# Hoist de custo (diagnóstico de traces 11/08): a tag é função SÓ do cadastro dela — nunca do
# turno — e passou da cauda volátil (re-enviada como cache-MISS a cada turno) para a 3ª
# SystemMessage do prefixo, `render_bloco_da_modelo`, que o DeepSeek cacheia. O que estes testes
# provam continua o mesmo e é o que importa pra segurança: a NEGAÇÃO ATIVA chega ao prompt final
# quando o cadastro não oferece — só mudou o bloco em que ela viaja. Cada teste positivo checa
# também que a tag SAIU da cauda (o byte que o hoist economiza).


async def test_sem_a_secao_injeta_a_tag_com_a_recusa_inteira() -> None:
    variaveis = (await _contexto(True)).como_variaveis()
    saida = render_bloco_da_modelo(**variaveis)

    assert "<sem_menage>" in saida
    assert "<sem_menage>" not in render_contexto_dinamico(**variaveis)
    # Os três lados que o roteiro `menage_sem_secao` cobra: recusa aberta, nada de cotar segunda
    # pessoa, nada de amiga (a prosa cortada do BP_GERAL dizia os três; a tag é o único site que
    # sobra). O regime de composição hoje SOMA um extra em vez de dobrar o pacote — a proibição
    # cobre os dois nomes da conta pra não ficar órfã do regime revogado.
    assert "Não faço amor" in saida
    assert "nem pacote, nem extra de segunda pessoa" in saida
    assert "sem prometer amiga" in saida
    # E a fala de substituição junto da proibição (lição do incidente #36): a venda dela segue.
    assert "<fora_do_cardapio>" in saida
    # A referência cruzada aponta para o bloco que existe hoje — um <menage> órfão mandaria a IA
    # procurar uma tag que o BP_GERAL não tem mais.
    assert "<composicoes>" in saida and "<menage>" not in saida


async def test_com_a_secao_o_prompt_nao_diz_nada_de_composicao() -> None:
    variaveis = (await _contexto(False)).como_variaveis()

    assert "<sem_menage>" not in render_bloco_da_modelo(**variaveis)
    assert "<sem_menage>" not in render_contexto_dinamico(**variaveis)


# --- a condição: mesma leitura do <fetiches> do BP_MODELO ---------------------------------------


async def _sem_menage_do_cardapio(fetiches: list[dict[str, Any]]) -> tuple[bool, str]:
    """(`sem_menage` derivado em `_carregar_bp3`, o <fetiches> que a mesma lista renderiza)."""
    (
        _md,
        _nome,
        _max,
        _vazio,
        sem_menage,
        _sem_chamada,
        _externo,
        _end,
        _local,
        _precos,
        _cardapio,
    ) = await _carregar_bp3(
        _ConnCardapio(fetiches),  # type: ignore[arg-type]
        "11111111-1111-1111-1111-111111111111",
    )
    return sem_menage, render_fetiches(
        fetiches, [{"nome": "Encontro", "duracao_nome": "1 hora", "duracao_horas": 1, "preco": 400}]
    )


async def test_fetiche_por_pessoa_pago_e_o_que_desliga_a_tag() -> None:
    sem_menage, bloco = await _sem_menage_do_cardapio(
        [{"nome": "Acompanhante dele — mulher", "preco": 700, "cobra_por_pessoa": True}]
    )

    assert sem_menage is False
    assert "Por pessoa" in bloco


async def test_so_fetiche_ato_mantem_a_tag() -> None:
    # Fetiche pago SEM a flag do catálogo: o <fetiches> abre "Extras pagos" e nenhuma seção
    # "Por pessoa" — composição não existe pra ela.
    sem_menage, bloco = await _sem_menage_do_cardapio(
        [{"nome": "Inversão", "preco": 350, "cobra_por_pessoa": False}]
    )

    assert sem_menage is True
    assert "Por pessoa" not in bloco


async def test_por_pessoa_incluso_abre_a_secao_e_a_tag_sai() -> None:
    # `cobra_por_pessoa` vence o preco NULL (CONTEXT.md, verbete Composição: a 2ª pessoa é paga
    # "sem exceção incluso" — cadastro incluso existe em prod e é cadastro a corrigir, não licença
    # pra confirmar composição grátis). O render põe o fetiche na seção "Por pessoa" com o extra
    # derivado da linha de 1h, e a cauda NÃO proíbe o que a tabela dela oferece.
    sem_menage, bloco = await _sem_menage_do_cardapio(
        [{"nome": "Acompanhante dele — mulher", "preco": None, "cobra_por_pessoa": True}]
    )

    assert sem_menage is False
    assert "Por pessoa" in bloco
    assert (
        "Acompanhante dele — mulher" not in bloco.split("Por pessoa")[0]
    )  # nunca na linha "Inclusos"


async def test_cardapio_vazio_mantem_a_tag() -> None:
    sem_menage, bloco = await _sem_menage_do_cardapio([])

    assert sem_menage is True
    assert "(sem fetiches cadastrados)" in bloco
