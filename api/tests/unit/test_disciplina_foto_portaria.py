"""A2 da foto de portaria: detectar a bolha em que a IA PEDE o print da chegada.

O pedido é o que põe em movimento o handoff implícito (quem o dispara é o print CHEGANDO —
CONTEXT.md "Foto de portaria") e sai uma vez: depois dele a IA espera, com presença curta ("Vou me
arrumar rs"), sem recobrar. A disciplina era só prosa
no <conducao_da_venda> ("pergunte uma vez, depois espere"), e o pedido acontece no FIM do
combinado: desliza pra fora da janela de 20 msgs justamente enquanto o cliente não chega, que é
quando a regra vale. O detector alimenta `foto_portaria_pedida_em`, a memória durável.

As duas formas que o prompt treina: o pedido na despedida do combinado ("Ele avisou que saiu →
já pedindo a foto na chegada") e o mesmo pedido em resposta a "cheguei"/"to chegando"
(<tipos_de_encontro> 3, o trilho que segura a unidade).
"""

from datetime import UTC, datetime
from typing import Any

from barra.agente._disciplina import contem_pedido_da_foto_de_portaria
from barra.agente.contexto import ContextAgente
from barra.agente.nos.prepare_context import _resolver_variaveis
from barra.agente.persona import render_contexto_dinamico

_TS = datetime(2026, 7, 26, 3, 0, tzinfo=UTC)  # instante qualquer: presença = flag ligada

# --- o pedido, nas formas do prompt -------------------------------------------------------------


def test_pedido_canonico_do_prompt_e_pego() -> None:
    assert contem_pedido_da_foto_de_portaria("Quando chegar me manda uma foto da portaria amor")


def test_variantes_do_pedido_sao_pegas() -> None:
    # Formas que o modelo produz em volta da canônica (mesma família: foto/print + portaria, ou
    # o pedido ancorado na chegada).
    assert contem_pedido_da_foto_de_portaria("Me manda uma foto da portaria quando chegar 🥰")
    assert contem_pedido_da_foto_de_portaria("Manda foto da portaria amor")
    assert contem_pedido_da_foto_de_portaria("Me manda um print da portaria")
    assert contem_pedido_da_foto_de_portaria("Quando chegar na portaria me manda uma foto")
    assert contem_pedido_da_foto_de_portaria("Quando estiver chegando me manda uma fotinha")


def test_pedido_em_resposta_ao_cheguei_e_pego() -> None:
    # <tipos_de_encontro> 3: "To chegando, me passa o apartamento" recebe o mesmo trilho — e é
    # exatamente o turno em que a IA mais recobra. Aqui o contexto já está posto: ela pede a foto
    # sem repetir "portaria", e o verbo da chegada vem no PASSADO ou em outra ordem.
    assert contem_pedido_da_foto_de_portaria("Me manda uma foto da portaria que eu já te falo amor")
    assert contem_pedido_da_foto_de_portaria("Você chegou ? me manda a foto amor")
    assert contem_pedido_da_foto_de_portaria("Me manda uma foto quando chegar amor")


def test_promessa_de_mandar_foto_nao_conta_como_pedido() -> None:
    # A IA prometendo mídia DELA (<midia>) usa o mesmo vocabulário: o corte é o imperativo
    # ("manda") contra o infinitivo ("mandar"). Carimbar aqui calaria o pedido antes de ele existir.
    assert not contem_pedido_da_foto_de_portaria("Quando chegar eu vou te mandar uma foto rs")


# --- o resto do vocabulário de foto/chegada na conversa -----------------------------------------


def test_book_e_comprovante_nao_contam_como_pedido_da_foto() -> None:
    # Os outros dois "manda a imagem" da conversa: a mídia dela (<midia>) e o comprovante do Pix
    # (<tipos_de_encontro>). Carimbar aqui calaria o pedido da portaria antes de ele existir.
    assert not contem_pedido_da_foto_de_portaria("Te mando uma foto minha amor")
    assert not contem_pedido_da_foto_de_portaria("Me manda o comprovante amor")
    assert not contem_pedido_da_foto_de_portaria("me confirma no comprovante amor")


def test_falar_da_chegada_sem_pedir_a_foto_nao_conta() -> None:
    # Presença curta e história da persona ("Cheguei faz pouquinho amor"): não é pedido nenhum.
    assert not contem_pedido_da_foto_de_portaria("Estou te esperando amor")
    assert not contem_pedido_da_foto_de_portaria("Cheguei faz pouquinho amor, to conhecendo ainda")
    assert not contem_pedido_da_foto_de_portaria("Me avisa quando chegar amor")


# --- read-time: a coluna vira campo do turno e tag no contexto ----------------------------------


class _FakeConnVazio:
    """Vazio em tudo: a flag chega por kwarg (coluna do atendimento), não por query."""

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
    )


async def _resolver(atendimento: dict[str, Any]) -> Any:
    return await _resolver_variaveis(
        _FakeConnVazio(),  # type: ignore[arg-type]
        _ctx(),
        atendimento=atendimento,
    )


async def test_foto_ja_pedida_le_coluna_e_reseta_na_recorrencia() -> None:
    pediu = await _resolver({"foto_portaria_pedida_em": _TS})
    nao_pediu = await _resolver({})  # atendimento novo do mesmo par nasce sem a flag

    assert pediu.foto_portaria_ja_pedida is True
    assert nao_pediu.foto_portaria_ja_pedida is False


def _render(**over: object) -> str:
    return render_contexto_dinamico(
        numero_curto=7,
        estado="Aguardando_confirmacao",
        slots_faltantes=[],
        proximo_passo="esperar o cliente chegar",
        pix_status="não aplicável",
        **over,
    )


def test_render_foto_pedida_injeta_tag() -> None:
    out = _render(foto_portaria_ja_pedida=True)
    assert "<ja_pediu_a_foto_da_portaria>" in out
    assert "não repita o pedido" in out


def test_render_sem_pedido_nao_injeta_tag() -> None:
    assert "<ja_pediu_a_foto_da_portaria>" not in _render(foto_portaria_ja_pedida=False)
    assert "<ja_pediu_a_foto_da_portaria>" not in _render()
