"""Peças do contexto do turno no State (spec extracao-janela-dedicada, ticket 01).

O `prepare_context` passa a publicar a âncora temporal e o bloco `<ja_registrado>` — as duas
peças que a janela DEDICADA da extração vai montar — sem mexer em nada do que o chat recebe.
Aqui provamos as duas metades: (a) o contexto dinâmico sai byte-idêntico e o bloco não vaza na
cauda; (b) o bloco rotula palpite/cotado e carrega a instrução de delta. Sem DB e sem crédito.
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

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
    )

    assert "<dia>" not in pecas.ja_registrado
    assert ">2026-07-25</dia>" in str(mensagens[-1].content)


async def test_bloco_carrega_a_instrucao_de_delta_com_a_excecao_da_proxima_acao() -> None:
    bloco = render_ja_registrado(**(await _variaveis()).como_variaveis())

    assert "NÃO fala do cliente" in bloco
    assert "só se ELE MUDOU" in bloco
    assert "proxima_acao_esperada" in bloco
