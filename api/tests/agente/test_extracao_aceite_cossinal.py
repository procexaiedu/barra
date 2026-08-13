"""`aceita_valor` só produz efeito com CO-SINAL determinístico na fala do cliente do turno.

Loop-massa r3, extração #1 — a chave-mestra da rodada. O produtor barato marca o aceite sobre
coisas que não são aceite (repergunta de preço, lowball, pergunta de logística) e o sinal é de MÃO
ÚNICA: `exclude_defaults` apaga o `False`, então o aceite errado nunca desce sozinho — ele apaga a
escada de desconto inteira (`preco_na_mesa = cotacao_na_mesa and not valor_aceito`, ADR-0040).

O co-sinal é o discriminante MEDIDO contra o corpus da rodada (6/6 falsos positivos mortos, 3/4 dos
aceites legítimos preservados): afirmação curta OU hora explícita no burst atual dele. O irmão já
existia para o horário (`horario_evidenciado`); para o valor, não existia nenhum.

Sem DB nem LLM: `_executar_idempotente` é mockado (mesmo padrão de `test_extracao_loc_pin.py`) e o
teste lê o PAYLOAD que a tool entregaria ao domínio.
"""

from contextlib import asynccontextmanager
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

import barra.agente.ferramentas.extracao as extracao
from barra.agente.ferramentas.extracao import _aceite_tem_cossinal, registrar_extracao

_chamar = registrar_extracao.coroutine  # type: ignore[attr-defined]


class _PoolNoOp:
    @asynccontextmanager
    async def connection(self) -> Any:
        yield object()


class _Ctx:
    def __init__(self) -> None:
        self.db_pool = _PoolNoOp()
        self.redis = None
        self.atendimento_id = "00000000-0000-0000-0000-000000000001"
        self.turno_id = "00000000-0000-0000-0000-000000000002"
        self.agora_utc = None


class _Runtime:
    def __init__(self, state: dict[str, Any]) -> None:
        self.context = _Ctx()
        self.state = state


# --- 1. o discriminante puro, contra o corpus medido ---------------------------------------------
# Falsos positivos da rodada 3: os 7 payloads em 3 eixos (objetor_b t4/t10, apressado t2/t4,
# ghost_b t2/t3). Nenhum é afirmação curta e nenhum crava hora.
_FALSOS = [
    "É 400 fechado mesmo pra 1h?",  # objetor_b t4 — repergunta de preço
    "Sério? Então faz 250 que eu chamo o uber agora",  # objetor_b t10 — lowball
    "Consigo chegar ai em uns 40 min",  # apressado t2 — logística
    "Da certo?",  # apressado t2 (2ª bolha do burst)
    "E onde é seu local, vida?",  # ghost_b t2 — logística
    "E o valor",  # ghost_b t3
]

# Aceites legítimos que o predicado TEM de preservar.
_LEGITIMOS = [
    "300 às 20h tá fechado",  # objetor_b t11 — hora explícita
    "Pode ser 20h sim",  # decidido_b t6 — afirmação curta + hora
    "Fechado entao",  # decidido_b t6 (2ª bolha)
    "Pode ser as 10h entao",  # retomada t7
    "Perfeito",  # decidido_b t5 — afirmação curta sobre a hora que ELA propôs
]


def _janela(*falas: str) -> list[Any]:
    return [AIMessage(content="Consigo às 20h, fecha ?"), *(HumanMessage(content=f) for f in falas)]


def test_cossinal_mata_os_falsos_positivos_do_corpus() -> None:
    for fala in _FALSOS:
        assert _aceite_tem_cossinal(_janela(fala)) is False, fala


def test_cossinal_preserva_os_aceites_legitimos() -> None:
    for fala in _LEGITIMOS:
        assert _aceite_tem_cossinal(_janela(fala)) is True, fala


def test_cossinal_le_o_burst_inteiro_nao_so_a_ultima_bolha() -> None:
    # "Consigo chegar ai em uns 40 min" + "Da certo?" seguem sem co-sinal; com a hora numa das
    # bolhas do mesmo burst, acende (a fala que sustenta pode não ser a última).
    assert _aceite_tem_cossinal(_janela("Consigo chegar ai em uns 40 min", "Da certo?")) is False
    assert _aceite_tem_cossinal(_janela("beleza", "chego as 21h")) is True


def test_cossinal_falso_sem_burst_do_cliente() -> None:
    # Último a falar foi ela: nada novo dele a sustentar o aceite.
    assert _aceite_tem_cossinal([HumanMessage(content="oi"), AIMessage(content="Oii")]) is False


# --- 2. a tool: o rebaixamento chega ao payload que o domínio recebe ------------------------------
async def _payload_da_tool(state: dict[str, Any], **kw: Any) -> dict[str, Any]:
    capturado: dict[str, Any] = {}

    async def _fake_idempotente(
        _conn: Any, _turno: Any, _nome: Any, _idx: Any, dados: dict[str, Any], **_k: Any
    ) -> dict[str, Any]:
        capturado.update(dados)
        return {"mensagem": "ok"}

    original = extracao._executar_idempotente
    extracao._executar_idempotente = _fake_idempotente  # type: ignore[assignment]
    try:
        await _chamar(
            proxima_acao_esperada="aguardar o cliente",
            runtime=_Runtime(state),
            sinais_qualificacao=extracao.SinaisQualificacao(aceita_valor=True),
            **kw,
        )
    finally:
        extracao._executar_idempotente = original  # type: ignore[assignment]
    return capturado


async def test_tool_rebaixa_aceite_sem_cossinal() -> None:
    dados = await _payload_da_tool({"conversa_crua": _janela("É 400 fechado mesmo pra 1h?")})
    # `exclude_defaults` apaga o False: a chave some, e o merge do domínio não sobe o sinal.
    assert "aceita_valor" not in (dados.get("sinais_qualificacao") or {})


async def test_tool_preserva_aceite_com_cossinal() -> None:
    dados = await _payload_da_tool({"conversa_crua": _janela("Pode ser 20h sim")})
    assert dados["sinais_qualificacao"]["aceita_valor"] is True


async def test_tool_fail_open_sem_janela_crua() -> None:
    """Nó alcançado fora do fluxo do prepare_context: sem a janela LIMPA não há veredito, e
    derrubar o aceite às cegas custaria a venda oposta."""
    dados = await _payload_da_tool({})
    assert dados["sinais_qualificacao"]["aceita_valor"] is True


async def test_rebaixamento_nao_toca_no_valor_acordado() -> None:
    """O aceite cai; o número combinado fica de pé (mesma fronteira do `recuo_detectado`)."""
    dados = await _payload_da_tool(
        {"conversa_crua": _janela("E onde é seu local, vida?")}, valor_acordado=400
    )
    assert "aceita_valor" not in (dados.get("sinais_qualificacao") or {})
    assert dados["valor_acordado"] == "400"
