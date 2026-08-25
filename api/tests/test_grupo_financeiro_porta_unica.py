"""A porta UNICA do Agente financeiro: um evento do grupo entra, os efeitos saem (spec 0006).

Offline: sem banco, sem chave, sem rede. O que se prova aqui e o ROTEAMENTO da porta — quem cai em
qual ramo e o que os nomes antigos fazem hoje — e nao a conduta de cada ramo, que os testes de
integracao ja exercitam com banco de verdade (`tests/integracao/test_grupo_financeiro_*.py`).

Dois invariantes, os dois de quebrar calado:

  * o gesto que a porta ainda NAO trata (reacao, edicao) sai ignorado sem tocar no banco. Se um dia
    ele passar a consultar o grupo "so para logar", o numero compartilhado da ProceX (myEYE +
    grupos financeiros + os grupos pessoais das modelos) vira uma ida ao banco por emoji de
    terceiro — e ninguem descobre isso por um teste de conduta. A conexao aqui e uma que EXPLODE em
    qualquer atributo: e o unico jeito de afirmar "nao tocou".
  * `processar_mensagem_do_grupo` e `processar_delecao_do_grupo` sao WRAPPERS, nao caminhos
    paralelos. Se um deles voltar a ter corpo proprio, producao e teste passam a percorrer codigo
    diferente — que e exatamente o que a porta unica existe para impedir.
"""

import logging
from typing import Any, cast

import pytest
from psycopg import AsyncConnection

from barra.agente_financeiro import (
    EdicaoNoGrupo,
    ReacaoNoGrupo,
    ResultadoDaPorta,
    processar_delecao_do_grupo,
    processar_evento_do_grupo,
    processar_mensagem_do_grupo,
)
from barra.agente_financeiro import porta as porta_mod
from barra.dominio.grupo_financeiro.modelos import DelecaoNoGrupo, MensagemDoGrupo

GRUPO_JID = "120363000000000001@g.us"
AUTOR_JID = "5521999998888@s.whatsapp.net"


class _ConexaoProibida:
    """Uma conexao que nao pode ser usada: qualquer acesso levanta.

    E a afirmacao "este ramo nao vai ao banco" escrita de um jeito que nao da para passar por
    acidente — um `SELECT` novo no caminho quebra o teste em vez de sumir na latencia.
    """

    def __getattr__(self, nome: str) -> Any:  # pragma: no cover - so dispara se o ramo regredir
        raise AssertionError(f"o ramo ignorado nao pode tocar na conexao (pediu {nome!r})")


def _conn() -> AsyncConnection[Any]:
    return cast(AsyncConnection[Any], _ConexaoProibida())


def _reacao() -> ReacaoNoGrupo:
    return ReacaoNoGrupo(
        grupo_jid=GRUPO_JID,
        evolution_message_id="3EB0ALVO",
        emoji="✅",
        autor_jid=AUTOR_JID,
    )


def _edicao() -> EdicaoNoGrupo:
    return EdicaoNoGrupo(
        grupo_jid=GRUPO_JID,
        evolution_message_id="3EB0ALVO",
        texto="Duda 700 pix",
        autor_jid=AUTOR_JID,
    )


@pytest.mark.parametrize("evento", [_reacao(), _edicao()], ids=["reacao", "edicao"])
async def test_gesto_sem_comportamento_sai_ignorado_sem_tocar_no_banco(
    evento: ReacaoNoGrupo | EdicaoNoGrupo,
) -> None:
    resultado = await processar_evento_do_grupo(_conn(), evento)

    assert resultado == ResultadoDaPorta(status="ignorado")


@pytest.mark.parametrize(
    ("evento", "gesto"), [(_reacao(), "reacao"), (_edicao(), "edicao")], ids=["reacao", "edicao"]
)
async def test_gesto_ignorado_deixa_log_sem_o_telefone_de_quem_gesticulou(
    evento: ReacaoNoGrupo | EdicaoNoGrupo, gesto: str, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="barra.agente_financeiro.porta"):
        await processar_evento_do_grupo(_conn(), evento)

    (registro,) = [r for r in caplog.records if "gesto_ignorado" in r.getMessage()]
    mensagem = registro.getMessage()
    assert f"gesto={gesto}" in mensagem
    assert GRUPO_JID in mensagem
    # Mesmo motivo do ramo de grupo nao cadastrado: este caminho dispara para grupo que nem e
    # nosso, e o autor e o telefone E.164 de um terceiro.
    assert AUTOR_JID not in mensagem


async def test_gesto_ignorado_nao_produz_efeito_nenhum() -> None:
    resultado = await processar_evento_do_grupo(_conn(), _reacao())

    assert resultado.vendas == ()
    assert resultado.pagamentos == ()
    assert resultado.correcoes == ()
    assert resultado.anuladas == ()
    assert resultado.cobrancas == ()
    assert resultado.abatidas == ()
    assert resultado.mensagem_id is None
    assert resultado.comprovante_id is None
    assert resultado.extrato is None
    assert resultado.resposta is None
    assert resultado.motivo is None


async def test_dependencias_injetadas_sao_aceitas_pelo_ramo_que_nao_usa() -> None:
    """A costura e UNICA: quem chama passa ouvido, olho e boca sempre, sem saber o ramo."""
    falas: list[str] = []

    async def enviar(texto: str, *, citar: str | None = None) -> None:  # pragma: no cover
        falas.append(texto)

    resultado = await processar_evento_do_grupo(
        _conn(),
        _reacao(),
        enviar=enviar,
        transcrever=None,
        ler_comprovante=None,
        ler_intencao=None,
    )

    assert resultado.status == "ignorado"
    assert falas == []


async def test_nome_antigo_de_mensagem_e_wrapper_da_porta_unica(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chamadas: list[tuple[MensagemDoGrupo, dict[str, Any]]] = []
    esperado = ResultadoDaPorta(status="registrada")

    async def espiao(_conn_: Any, msg: MensagemDoGrupo, **kwargs: Any) -> ResultadoDaPorta:
        chamadas.append((msg, kwargs))
        return esperado

    monkeypatch.setattr(porta_mod, "_processar_mensagem", espiao)
    msg = MensagemDoGrupo(grupo_jid=GRUPO_JID, texto="Duda 600 pix", autor_jid=AUTOR_JID)

    async def enviar(texto: str, *, citar: str | None = None) -> None:  # pragma: no cover
        return None

    def extrator(texto: str) -> Any:  # pragma: no cover - so precisa chegar do outro lado
        raise AssertionError

    pelo_nome_antigo = await processar_mensagem_do_grupo(
        _conn(), msg, extrair=extrator, enviar=enviar
    )
    pela_porta_unica = await processar_evento_do_grupo(
        _conn(), msg, extrair=extrator, enviar=enviar
    )

    assert pelo_nome_antigo is esperado
    assert pela_porta_unica is esperado
    assert len(chamadas) == 2
    # Mesmo destino e MESMAS dependencias: o wrapper nao pode comer nem trocar um kwarg no caminho.
    assert chamadas[0] == chamadas[1]
    assert chamadas[0][1]["extrair"] is extrator
    assert chamadas[0][1]["enviar"] is enviar


async def test_nome_antigo_de_delecao_e_wrapper_da_porta_unica(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chamadas: list[DelecaoNoGrupo] = []
    esperado = ResultadoDaPorta(status="delecao")

    async def espiao(_conn_: Any, delecao: DelecaoNoGrupo) -> ResultadoDaPorta:
        chamadas.append(delecao)
        return esperado

    monkeypatch.setattr(porta_mod, "_processar_delecao", espiao)
    delecao = DelecaoNoGrupo(grupo_jid=GRUPO_JID, evolution_message_id="3EB0ALVO")

    pelo_nome_antigo = await processar_delecao_do_grupo(_conn(), delecao)
    pela_porta_unica = await processar_evento_do_grupo(_conn(), delecao)

    assert pelo_nome_antigo is esperado
    assert pela_porta_unica is esperado
    assert chamadas == [delecao, delecao]


async def test_a_porta_unica_nao_precisa_saber_o_ramo_para_ser_chamada() -> None:
    """Um `EventoDoGrupo` qualquer entra pela mesma funcao e sai no mesmo `ResultadoDaPorta`."""
    eventos: list[porta_mod.EventoDoGrupo] = [_reacao(), _edicao()]

    for evento in eventos:
        assert isinstance(await processar_evento_do_grupo(_conn(), evento), ResultadoDaPorta)
