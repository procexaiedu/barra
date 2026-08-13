"""Peças do contexto do turno no State (spec extracao-janela-dedicada, ticket 01).

O `prepare_context` passa a publicar a âncora temporal e o bloco `<ja_registrado>` — as duas
peças que a janela DEDICADA da extração vai montar — sem mexer em nada do que o chat recebe.
Aqui provamos as duas metades: (a) o contexto dinâmico sai byte-idêntico e o bloco não vaza na
cauda; (b) o bloco rotula palpite/cotado e carrega a instrução de delta. Sem DB e sem crédito.
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from barra.agente.contexto import ContextAgente
from barra.agente.nos._contexto_do_turno import ContextoDoTurno
from barra.agente.nos.prepare_context import _anexar_contexto_dinamico, _resolver_variaveis
from barra.agente.persona import (
    render_ancora_extracao,
    render_contexto_dinamico,
    render_ja_registrado,
)

# Relógio injetado (ContextAgente.agora_utc): 2026-07-25 17:30 UTC = 14:30 em Brasília.
_AGORA_UTC = datetime(2026, 7, 25, 17, 30, tzinfo=UTC)


class _FakeConnVazio:
    """Vazio em tudo: o atendimento chega por kwarg e o relógio vem injetado — nenhuma query
    precisa responder."""

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
        agora_utc=_AGORA_UTC,
    )


_ATENDIMENTO: dict[str, Any] = {
    "estado": "Qualificado",
    "numero_curto": 41,
    "tipo_atendimento": "interno",
    "urgencia": "imediato",
    "data_desejada": datetime(2026, 7, 25).date(),
    "horario_desejado": datetime(2026, 7, 25, 2, 0).time(),
    "horario_evidenciado": False,
    "valor_acordado": None,
    "sinais_qualificacao": {},
}


# Cardápio vazio de propósito nos testes da parte (a)/(b): eles medem a ORDEM da cauda, a âncora
# temporal e a rotulagem do `<ja_registrado>` (palpite/cotado/delta) — nada disso lê o cadastro, e
# nenhuma das falas cita fetiche ou serviço. A parte (c), que é justamente sobre o cardápio, passa
# o dict populado (`_pecas_com_cardapio`). O `{}` é a afirmação "esta modelo não tem cadastro",
# não a omissão que o default `None` permitia — ele apagava nove campos do `<foco_do_turno>` em
# silêncio.
_SEM_CARDAPIO: dict[str, list[dict[str, Any]]] = {}


async def _variaveis(**over: Any) -> ContextoDoTurno:
    return await _resolver_variaveis(
        _FakeConnVazio(),  # type: ignore[arg-type]
        _ctx(),
        atendimento={**_ATENDIMENTO, **over},
    )


# --- (a) nada do que o chat recebe muda ---------------------------------------------------------


async def test_contexto_dinamico_segue_byte_identico_com_a_ancora_no_dicionario() -> None:
    """A âncora crua (`agora`) entrou no dicionário de variáveis p/ alimentar as peças; o template
    do contexto dinâmico não a lê. Render com e sem ela tem que sair byte-a-byte igual — é o que
    garante que publicar as peças não mexeu em uma vírgula do que a IA lê."""
    variaveis = await _variaveis()
    como_dict = variaveis.como_variaveis()
    sem_ancora = {k: v for k, v in como_dict.items() if k != "agora"}

    assert "agora" in como_dict
    assert render_contexto_dinamico(**como_dict) == render_contexto_dinamico(**sem_ancora)


async def test_bloco_nao_vaza_na_cauda_e_a_ordem_do_turno_segue_a_mesma() -> None:
    """A cauda do chat é contexto dinâmico → msg do cliente (a fala por último, 29/07), sem o
    bloco de estado."""
    janela = [
        AIMessage(content="600 1h no meu local"),
        HumanMessage(content="e como funciona?"),
    ]
    mensagens, _contexto, pecas = await _anexar_contexto_dinamico(
        _FakeConnVazio(),  # type: ignore[arg-type]
        _ctx(),
        janela,
        atendimento=_ATENDIMENTO,
        cardapio_rows=_SEM_CARDAPIO,
    )
    cauda = str(mensagens[-1].content)

    assert cauda.startswith("<situacao_do_atendimento")
    assert cauda.endswith("\n\ne como funciona?")
    assert "<ja_registrado>" not in cauda
    assert pecas.ja_registrado.startswith("<ja_registrado>")


async def test_pecas_trazem_a_ancora_do_turno_ja_resolvida() -> None:
    """`agora` é o instante do turno em BRT — a MESMA fonte de `data_atual`/`hora_atual` que a IA
    lê no `<agenda>`, então âncora do extrator e âncora da IA não podem divergir."""
    janela = [HumanMessage(content="oi")]
    _msgs, _contexto, pecas = await _anexar_contexto_dinamico(
        _FakeConnVazio(),  # type: ignore[arg-type]
        _ctx(),
        janela,
        atendimento=_ATENDIMENTO,
        cardapio_rows=_SEM_CARDAPIO,
    )
    variaveis = await _variaveis()

    assert pecas.agora == datetime(2026, 7, 25, 14, 30)
    assert pecas.agora is not None
    assert pecas.agora.date() == variaveis.data_atual
    assert pecas.agora.strftime("%H:%M") == variaveis.hora_atual


# --- (b) o bloco de estado ----------------------------------------------------------------------


async def test_ancora_reusa_a_tag_que_as_descricoes_dos_campos_citam() -> None:
    """As descrições de `horario_desejado`/`data_desejada` mandam resolver tempo relativo contra
    `<agenda hoje="..." agora="HH:MM">`. A âncora da extração reusa a MESMA tag — se ela mudar de
    forma, as descrições passam a apontar pro nada."""
    assert render_ancora_extracao(datetime(2026, 7, 25, 14, 30)).strip() == (
        '<agenda hoje="2026-07-25" agora="14:30"/>'
    )
    assert render_ancora_extracao(None) == ""


async def test_bloco_rotula_o_horario_como_palpite_sem_evidencia() -> None:
    """#25: o fallback grava o horário e o extrator o devolve como observação nova. Sem evidência
    do cliente, o bloco diz que é palpite do sistema."""
    bloco = render_ja_registrado(**(await _variaveis(horario_evidenciado=False)).como_variaveis())

    assert 'origem="palpite do sistema' in bloco
    assert "NÃO confirmou" in bloco


async def test_bloco_rotula_o_horario_como_pedido_dele_com_evidencia() -> None:
    bloco = render_ja_registrado(**(await _variaveis(horario_evidenciado=True)).como_variaveis())

    assert 'origem="ele pediu"' in bloco


async def test_bloco_rotula_o_valor_como_cotado_ate_o_aceite() -> None:
    """`valor_acordado` é gravado JÁ na cotação: sem o aceite, o bloco não pode apresentá-lo como
    fechado (senão o extrator remarca o aceite lendo o próprio número)."""
    cotado = render_ja_registrado(
        **(
            await _variaveis(
                valor_acordado=Decimal("400"), duracao_horas=Decimal("1"), sinais_qualificacao={}
            )
        ).como_variaveis()
    )
    aceito = render_ja_registrado(
        **(
            await _variaveis(
                valor_acordado=Decimal("400"),
                duracao_horas=Decimal("1"),
                sinais_qualificacao={"aceita_valor": True},
            )
        ).como_variaveis()
    )

    assert "apenas COTADO" in cotado
    assert "aceito por ele" in aceito


async def test_bloco_nao_apresenta_como_gravado_o_dia_que_o_A2_so_assumiu() -> None:
    """O A2 (`_aplicar_dia_confirmado`) assume hoje no belief da IA sem persistir. Se essa
    suposição entrasse no bloco, o extrator omitiria `data_desejada` ("não mudou") e o dia nunca
    chegaria ao banco — a subextração, erro simétrico do eco. O belief da IA segue com o dia."""
    janela = [
        AIMessage(content="seria hoje ?"),
        HumanMessage(content="sim"),
    ]
    mensagens, _contexto, pecas = await _anexar_contexto_dinamico(
        _FakeConnVazio(),  # type: ignore[arg-type]
        _ctx(),
        janela,
        atendimento={**_ATENDIMENTO, "estado": "Triagem", "data_desejada": None},
        cardapio_rows=_SEM_CARDAPIO,
    )

    assert "<dia>" not in pecas.ja_registrado
    assert ">2026-07-25</dia>" in str(mensagens[-1].content)


async def test_bloco_carrega_a_instrucao_de_delta_com_a_excecao_da_proxima_acao() -> None:
    bloco = render_ja_registrado(**(await _variaveis()).como_variaveis())

    assert "NÃO fala do cliente" in bloco
    assert "só se ELE MUDOU" in bloco
    assert "proxima_acao_esperada" in bloco


# --- (c) o vocabulário canônico do cardápio na janela do extrator (A2 11/08) ---------------------


async def _pecas_com_cardapio(fetiches: list[dict[str, Any]]) -> str:
    """O `<ja_registrado>` do turno com um cardápio de fetiches dado (o mesmo caminho de prod:
    as linhas chegam por `cardapio_rows`, lidas uma vez pelo `_carregar_bp3`)."""
    _msgs, _contexto, pecas = await _anexar_contexto_dinamico(
        _FakeConnVazio(),  # type: ignore[arg-type]
        _ctx(),
        [HumanMessage(content="faz pegging ?")],
        atendimento=_ATENDIMENTO,
        cardapio_rows={"fetiches": fetiches, "programas": []},
    )
    return pecas.ja_registrado


async def test_bloco_leva_os_nomes_do_cardapio_para_o_extrator() -> None:
    """Com `extracao_no_modelo_barato` a janela da extração troca o BP_GERAL por um system mínimo:
    a tabela <fetiches> não chega ao extrator e ele não tinha como traduzir "pegging" para o nome
    cadastrado. `registrar_fetiches_do_fechamento` casa por nome exato e descarta o resto em
    silêncio — sem a lista, a cobertura se perdia sem sinal nenhum."""
    bloco = await _pecas_com_cardapio(
        [
            {"nome": "Inversão", "preco": 1, "cobra_por_pessoa": False},
            {"nome": "Beijo grego", "preco": None, "cobra_por_pessoa": False},
        ]
    )

    assert "<fetiches_do_cadastro" in bloco
    assert ">Inversão, Beijo grego</fetiches_do_cadastro>" in bloco
    # Não pode ser lido como "isto já foi registrado" (é o nome da tag que envolve o bloco).
    assert "NÃO é o que já foi registrado" in bloco


async def test_bloco_omite_a_tag_quando_a_modelo_nao_tem_fetiches() -> None:
    """Fail-closed igual ao resto do bloco: sem cadastro, sem tag — nada de lista vazia sugerindo
    ao extrator que o cardápio existe."""
    assert "<fetiches_do_cadastro" not in await _pecas_com_cardapio([])


async def test_chamador_sem_cardapio_nao_compila_mais() -> None:
    """Sucessor do teste do "caminho degradado": ele existia para afirmar que um chamador SEM
    `cardapio_rows` degradava em silêncio, e essa era exatamente a falha — o default `None` fazia
    eval/harness/teste perderem nove campos do `<foco_do_turno>` (fetiches, inclusos, composição,
    o bloco inteiro da parceira) sem um único erro.

    Agora o argumento é obrigatório. mypy pega os chamadores do `src`, mas NÃO roda sobre `tests/`
    (memória do repo) — sem esta afirmação em runtime, um teste novo voltaria a omitir o dict e
    ninguém veria. Modelo sem cardápio continua sendo caso legítimo: passa `{}`."""
    with pytest.raises(TypeError, match="cardapio_rows"):
        await _anexar_contexto_dinamico(
            _FakeConnVazio(),  # type: ignore[arg-type]
            _ctx(),
            [HumanMessage(content="faz pegging ?")],
            atendimento=_ATENDIMENTO,
        )  # type: ignore[call-arg]
