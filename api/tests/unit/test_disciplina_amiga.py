"""A2 da amiga: detectar a bolha em que a IA CONVIDA o cliente pra conhecer a amiga.

A disciplina do <composicoes> ("você PODE oferecer uma vez, como quem convida") era só prosa, e o
convite é pós-venda — sai no FIM da negociação, quando ele já deslizou pra fora da janela de 20
msgs. O detector alimenta `amiga_ofertada_em`, a memória durável que a janela não consegue ser.

O corte que o detector precisa acertar: a oferta PROATIVA dela conta; a promessa de retorno
("Deixa eu ver com ela e já te retorno amor") NÃO conta — carimbá-la calaria um convite que ela
nunca fez.

Essa promessa era a ESCALADA prescrita quando o CLIENTE pedia a dupla; o ADR-0042 a revogou (a
modelo do canal fecha sozinha) e ela virou regressão de prompt. O veto, porém, ficou MAIS
importante, não menos: `amiga_ofertada_em` é o que destrava o contato da parceira no fluxo de
encaminhamento, e um turno de promessa vazia não pode valer por um sim do cliente.
"""

from datetime import UTC, datetime
from typing import Any

from barra.agente._disciplina import contem_escalada_da_amiga, contem_oferta_da_amiga
from barra.agente.contexto import ContextAgente
from barra.agente.nos.prepare_context import _resolver_variaveis
from barra.agente.persona import render_contexto_dinamico

_TS = datetime(2026, 7, 26, 2, 0, tzinfo=UTC)  # instante qualquer: presença = flag ligada

# --- a oferta proativa dela ---------------------------------------------------------------------


def test_convite_canonico_do_prompt_e_pego() -> None:
    assert contem_oferta_da_amiga(
        "Tenho uma amiga aqui no mesmo hotel, no apartamento dela rs, quer conhecer as duas ?"
    )


def test_variantes_do_convite_sao_pegas() -> None:
    # Formas que o modelo produz em volta da canônica (e que o corpus do vendedor confirma:
    # "Tenho uma amiga vida", "Tenho minha amiga também rs").
    assert contem_oferta_da_amiga("Tenho uma amiga vida rs")
    assert contem_oferta_da_amiga("Tenho minha amiga também amor")
    assert contem_oferta_da_amiga("Quer conhecer as duas amor ?")
    assert contem_oferta_da_amiga("Quer conhecer a minha amiga ?")
    assert contem_oferta_da_amiga("Posso chamar minha amiga pra vir junto")


# --- a escalada, que NÃO é oferta ---------------------------------------------------------------


def test_resposta_de_escalada_nao_conta_como_oferta() -> None:
    # <composicoes>: quando é o CLIENTE quem pede a dupla, a IA não fecha sozinha — responde isto e
    # escala. Não houve convite dela; carimbar aqui bloquearia a oferta que ainda pode acontecer.
    assert not contem_oferta_da_amiga("Deixa eu ver com ela e já te retorno amor")
    assert not contem_oferta_da_amiga("Deixa eu ver com ela amor")


def test_confirmar_a_amiga_dentro_da_escalada_nao_conta() -> None:
    # A mesma escalada, com a palavra "amiga" na bolha: continua sendo resposta ao pedido DELE.
    assert not contem_oferta_da_amiga("Tenho uma amiga sim amor, deixa eu ver com ela")


def test_escalada_partida_em_duas_bolhas_ainda_veta_a_oferta() -> None:
    """O chunker parte a escalada em duas bolhas com facilidade, e a 1ª sozinha CASA a oferta —
    por isso o write-time mede o veto sobre o TURNO (workers/envio.py), não bolha a bolha."""
    bolhas = ["Tenho uma amiga sim amor", "Deixa eu ver com ela e já te retorno"]

    assert contem_oferta_da_amiga(bolhas[0])  # a bolha isolada engana
    assert contem_escalada_da_amiga("\n".join(bolhas))  # o turno inteiro desmente


# --- o resto do vocabulário de "amiga" na conversa ----------------------------------------------


def test_negar_a_amiga_nao_conta_como_oferta() -> None:
    # <fora_do_cardapio>: cliente pescando outra mulher da casa — a IA nega, não oferece.
    assert not contem_oferta_da_amiga("Não tenho uma amiga pra levar não amor")
    assert not contem_oferta_da_amiga("Só eu amor rs")


def test_pergunta_de_seguranca_nao_conta_como_oferta() -> None:
    # "Só eu e você" responde o medo do cliente (ninguém mais entra nisso) — a amiga nem entra na
    # conversa. Carimbar aqui gastaria o convite sem ele ter sido feito.
    assert not contem_oferta_da_amiga("Só eu e você amor")
    assert not contem_oferta_da_amiga("Bem discreto rs")


def test_segunda_pessoa_DELE_nao_conta_como_oferta() -> None:
    # <composicoes> 1º caso: quem traz a segunda pessoa é o cliente. A IA só cota o dobro.
    assert not contem_oferta_da_amiga("Faço sim amor, pra vocês dois fica 1200")
    assert not contem_oferta_da_amiga("Pode trazer sua amiga sim amor")


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


async def test_amiga_ja_ofertada_le_coluna_e_reseta_na_recorrencia() -> None:
    ofertou = await _resolver({"amiga_ofertada_em": _TS})
    nao_ofertou = await _resolver({})  # atendimento novo do mesmo par nasce sem a flag

    assert ofertou.amiga_ja_ofertada is True
    assert nao_ofertou.amiga_ja_ofertada is False


def _render(**over: object) -> str:
    return render_contexto_dinamico(
        numero_curto=7,
        estado="Aguardando_confirmacao",
        slots_faltantes=[],
        proximo_passo="confirmar a saída",
        pix_status="não aplicável",
        **over,
    )


def test_render_amiga_ofertada_injeta_tag() -> None:
    out = _render(amiga_ja_ofertada=True)
    assert "<ja_ofereceu_a_amiga>" in out
    assert "NÃO reofereça" in out


def test_render_sem_oferta_nao_injeta_tag() -> None:
    assert "<ja_ofereceu_a_amiga>" not in _render(amiga_ja_ofertada=False)
    assert "<ja_ofereceu_a_amiga>" not in _render()
