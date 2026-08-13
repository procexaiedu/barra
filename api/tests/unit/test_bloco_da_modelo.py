"""O bloco ESTÁTICO por-modelo — 3ª SystemMessage do prefixo (hoist de custo, traces 11/08).

Diagnóstico: 66% do custo de cache-MISS por turno era conteúdo que só o CADASTRO da modelo
decide (`<sem_menage>`, `<sem_video_chamada>`, `<sem_fetiches>`, `<sem_periodo_longo>`,
`<periodo_de_trabalho>`) renderizado na cauda volátil — re-enviado inteiro a cada turno porque
mora na última HumanMessage. Ele subiu para o prefixo, que o DeepSeek cacheia automaticamente.

A economia só existe se o bloco for BYTE-IDÊNTICO turno a turno (senão o prefixo quebra e o
hoist vira custo puro). É o que este arquivo prova, junto com o outro lado: as tags saíram
mesmo da cauda, e o que é POR-TURNO (`<cliente>`, `<local_de_encontro>` — liberado por degrau de
estado, ADR-0026) NÃO subiu junto.

Sem DB e sem crédito: `_anexar_contexto_dinamico` sobre um FakeConn vazio, como o contrato de
variáveis do turno.
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from barra.agente.contexto import ContextAgente
from barra.agente.llm import build_system_messages
from barra.agente.nos.prepare_context import _anexar_contexto_dinamico
from barra.agente.persona import render_bloco_da_modelo, render_contexto_dinamico

# As cinco tags que o hoist moveu.
_TAGS_ESTATICAS = (
    "<sem_periodo_longo>",
    "<sem_menage>",
    "<sem_video_chamada>",
    "<sem_fetiches>",
    "<periodo_de_trabalho>",
)

# O cadastro que ACENDE todas elas de uma vez (modelo sem fetiche, sem menage, sem chamada e com
# tabela só de 1h): é o pior caso de custo e o caso em que a negação ativa precisa chegar.
_CADASTRO_MINIMO: dict[str, Any] = {
    "tabela_max_horas": 1.0,
    "sem_fetiches": True,
    "sem_menage": True,
    "sem_video_chamada": True,
    # Coerente com o `sem_fetiches=True` acima: o cardápio VAZIO é o mesmo cadastro visto pelo
    # outro lado. Passar as chaves com listas vazias (e não omitir o argumento, que agora nem
    # compila) é a afirmação "esta modelo não tem nada cadastrado" — que é justamente o caso que
    # este arquivo exercita.
    "cardapio_rows": {"fetiches": [], "programas": []},
}


class _FakeConnVazio:
    """Vazio em tudo: cadastro e atendimento chegam por kwarg, o relógio vem injetado."""

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> Any:
        class _R:
            async def fetchone(self) -> None:
                return None

            async def fetchall(self) -> list[Any]:
                return []

        return _R()


def _ctx(agora: datetime) -> ContextAgente:
    return ContextAgente(
        db_pool=None,  # type: ignore[arg-type]  # nenhuma query roda com o FakeConn
        redis=None,  # type: ignore[arg-type]
        modelo_id="11111111-1111-1111-1111-111111111111",
        atendimento_id="22222222-2222-2222-2222-222222222222",
        cliente_id="33333333-3333-3333-3333-333333333333",
        turno_id="t",
        agora_utc=agora,
    )


async def _variaveis_do_turno(
    *,
    agora: datetime,
    mensagens: list[Any],
    atendimento: dict[str, Any],
    local: str | None = None,
) -> dict[str, Any]:
    """O dicionário como o `prepare_context` o entrega aos templates, para UM turno."""
    _msgs, contexto, _pecas = await _anexar_contexto_dinamico(
        _FakeConnVazio(),  # type: ignore[arg-type]
        _ctx(agora),
        mensagens,
        atendimento=atendimento,
        local_endereco_raw=local,
        local_nome_raw="Hotel X" if local else None,
        **_CADASTRO_MINIMO,
    )
    return contexto.como_variaveis()


async def _dois_turnos() -> tuple[dict[str, Any], dict[str, Any]]:
    """Dois turnos do MESMO atendimento, tão diferentes quanto o turno consegue ser: relógio,
    janela, estado, valor na mesa e o degrau do endereço todos mudam entre eles."""
    turno_1 = await _variaveis_do_turno(
        agora=datetime(2026, 7, 25, 17, 30, tzinfo=UTC),
        mensagens=[HumanMessage(content="oi")],
        atendimento={"numero_curto": 7, "estado": "Triagem", "tipo_atendimento": None},
    )
    turno_2 = await _variaveis_do_turno(
        agora=datetime(2026, 7, 25, 21, 5, tzinfo=UTC),
        mensagens=[HumanMessage(content="oi"), HumanMessage(content="pode ser 21h")],
        atendimento={
            "numero_curto": 7,
            "estado": "Confirmado",
            "tipo_atendimento": "interno",
            "valor_acordado": Decimal("400"),
            "aceita_valor": True,
        },
        local="Rua Y, 100",
    )
    return turno_1, turno_2


async def test_bloco_estatico_e_byte_identico_entre_dois_turnos() -> None:
    """A premissa inteira do hoist: mesmo atendimento, turnos diferentes, MESMOS bytes.

    Um único campo por-turno que vazasse para o template torraria o prefixo a cada turno — o
    bloco pagaria cache-MISS igual à cauda de onde saiu, com a salience pior. Por isso a
    igualdade é de bytes, não "contém as mesmas tags"."""
    turno_1, turno_2 = await _dois_turnos()

    assert render_bloco_da_modelo(**turno_1) == render_bloco_da_modelo(**turno_2)


async def test_os_turnos_comparados_sao_mesmo_diferentes() -> None:
    """Guarda do teste acima: se a cauda dos dois turnos saísse igual, a byte-identidade do bloco
    não provaria nada (dois turnos idênticos são triviais)."""
    turno_1, turno_2 = await _dois_turnos()

    assert render_contexto_dinamico(**turno_1) != render_contexto_dinamico(**turno_2)


async def test_as_tags_estaticas_sairam_da_cauda_volatil() -> None:
    """O outro lado do hoist: o que subiu para o prefixo não pode continuar sendo re-enviado na
    cauda (dupla contagem = o custo que a mudança veio cortar)."""
    turno_1, turno_2 = await _dois_turnos()

    for variaveis in (turno_1, turno_2):
        bloco = render_bloco_da_modelo(**variaveis)
        cauda = render_contexto_dinamico(**variaveis)
        for tag in _TAGS_ESTATICAS:
            assert tag in bloco, f"{tag} sumiu do prompt em vez de mudar de bloco"
            assert tag not in cauda, f"{tag} continua pagando cache-MISS na cauda"


async def test_o_que_e_por_turno_nao_subiu_junto() -> None:
    """Regra inviolável do hoist: `<cliente>` é por-turno e o `<local_de_encontro>` é liberado por
    DEGRAU DE ESTADO (ADR-0026) — congelá-lo no prefixo entregaria, no turno 1, o endereço que o
    degrau só libera depois (ou o negaria para sempre)."""
    _turno_1, turno_2 = await _dois_turnos()

    bloco = render_bloco_da_modelo(**turno_2)
    cauda = render_contexto_dinamico(**turno_2)

    assert "<local_de_encontro>" in cauda and "<local_de_encontro>" not in bloco
    assert "<cliente" in cauda and "<cliente" not in bloco
    assert "<situacao_do_atendimento" in cauda and "<situacao_do_atendimento" not in bloco


async def test_o_bloco_entra_como_3a_system_depois_do_por_modelo() -> None:
    """Posição no prefixo: `[BP_GERAL][BP_MODELO][bloco da modelo]`. O bloco vem por ÚLTIMO para
    que o prefixo que já está quente no provider não mude um byte com esta adição."""
    turno_1, _turno_2 = await _dois_turnos()
    bloco = render_bloco_da_modelo(**turno_1)

    msgs = build_system_messages(geral_md="GERAL", modelo_md="MODELO", cadastro_md=bloco)

    assert [m.content for m in msgs] == ["GERAL", "MODELO", bloco]
    assert all(isinstance(m, SystemMessage) for m in msgs)
    # Sem o bloco (cadastro que não acende nada é impossível — o <periodo_de_trabalho> sempre
    # renderiza —, mas o caller antigo/teste continua válido): o prefixo é o de antes.
    assert build_system_messages(geral_md="GERAL", modelo_md="MODELO") == msgs[:2]
