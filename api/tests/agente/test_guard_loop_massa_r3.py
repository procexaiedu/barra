"""Correções da família guard/judge/regen do loop de massa r3 (12/08/2026).

Cada teste aqui FALHA no código de antes da rodada e passa depois — é o par de regressão dos
consertos que a refutação adversarial confirmou:

1. `temperature=0` nos TRÊS judges (AUP #3, extração #2, pós-envio). Omitir o parâmetro NÃO era
   determinismo: `ChatOpenAI(temperature=None)` não envia o campo e vale o default do provider
   (~1.0) — a temperatura MAIS ALTA, num gate vinculante que roda em todo turno.
2. Timeout HTTP por chamada ESTRITAMENTE menor que o teto do turno (eram 60.0 = 60.0 literais).
3. Repetição: `houve_aceite` cobrindo `exato`/`fuzzy`; lembrete da regen por BOLHA; e o fim da
   contradição "avance pelo que falta" + "devolva vazio".
4. Regen cega: o lembrete conta o que o sistema JÁ anexou; `_RE_PLACEHOLDER` casa a rubrica entre
   parênteses.
6. Custo: `input_token_details` somado (cache-hit deixava de ser cache-hit e virava 6x a conta).
7. Observabilidade: `logger.warning` no ramo `viola` + `motivo` como label da métrica.

Sem DB, sem rede, sem LLM (mesmos fakes de test_output_guard.py).
"""

from __future__ import annotations

import importlib
import logging
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage
from prometheus_client import REGISTRY

from barra.agente.contexto import ContextAgente
from barra.core.llm import criar_chat_deepseek
from barra.settings import Settings, get_settings

mod = importlib.import_module("barra.agente.nos.output_guard")
mod_defesa = importlib.import_module("barra.agente._defesa")
mod_llm = importlib.import_module("barra.core.llm")

_USAGE = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}


def _settings() -> Settings:
    return Settings(deepseek_api_key="sk-test", _env_file=None)  # type: ignore[call-arg]


# ==================================================================================
# 1. temperature=0 nos três judges
# ==================================================================================


def test_omitir_temperatura_nao_e_determinismo() -> None:
    """O fato que embasa a família toda: sem o parâmetro, o campo NÃO vai no payload — e o
    provider aplica o default dele (~1.0). Este teste existe para que ninguém volte a ler
    "chama sem temperatura" como "determinismo"."""
    chat = criar_chat_deepseek(_settings())
    assert chat.temperature is None
    assert "temperature" not in chat._default_params


async def test_judge_aup_pede_temperatura_do_settings(monkeypatch: Any) -> None:
    capturado: dict[str, Any] = {}

    class _Chat:
        def with_structured_output(self, *_a: Any, **_k: Any) -> Any:
            return self

        async def ainvoke(self, *_a: Any, **_k: Any) -> Any:
            return {
                "raw": AIMessage(content="", response_metadata={"finish_reason": "stop"}),
                "parsed": mod._VeredictoAup(viola=False, motivo="nenhum"),
                "parsing_error": None,
            }

    def _fake(settings: Any, **kwargs: Any) -> Any:
        capturado.update(kwargs)
        return _Chat()

    monkeypatch.setattr(mod_llm, "criar_chat_deepseek", _fake)
    settings = SimpleNamespace(deepseek_model_chat="deepseek-v4-flash", judge_temperature=0.0)
    await mod._julgar_aup("texto", settings)
    assert capturado["temperature"] == 0.0


async def test_judge_pos_envio_pede_temperatura_do_settings(monkeypatch: Any) -> None:
    from barra.workers import judge_pos_envio as jpe

    capturado: dict[str, Any] = {}

    class _Chat:
        def with_structured_output(self, *_a: Any, **_k: Any) -> Any:
            return self

        async def ainvoke(self, *_a: Any, **_k: Any) -> Any:
            return {
                "raw": AIMessage(content="", response_metadata={"finish_reason": "stop"}),
                "parsed": jpe.VeredictoTurno(
                    rastro_llm=0.0, voz=1.0, conduta=1.0, vazou_dado_duro=False, comentario="ok"
                ),
                "parsing_error": None,
            }

    def _fake(settings: Any, **kwargs: Any) -> Any:
        capturado.update(kwargs)
        return _Chat()

    monkeypatch.setattr(mod_llm, "criar_chat_deepseek", _fake)
    await jpe._julgar("contexto", "turno", _settings())
    assert capturado["temperature"] == 0.0


def test_extracao_barata_roda_com_temperatura_zero() -> None:
    """Extração #2: mesma família. Ler o estado da negociação é classificação, não voz."""
    from barra.agente.graph import _criar_chat_extracao_barata

    assert _criar_chat_extracao_barata(_settings()).temperature == 0.0


def test_judge_temperature_default_zero() -> None:
    assert _settings().judge_temperature == 0.0


# ==================================================================================
# 2. timeout HTTP < timeout do turno
# ==================================================================================


def test_timeout_http_estritamente_menor_que_o_do_turno() -> None:
    """Com os dois iguais (60.0 = 60.0) a chamada pendurada estourava o TURNO por fora do grafo
    (`timeout_grafo` -> handoff terminal, cliente sem bolha) em vez de morrer dentro dele, onde o
    fallback determinístico do guard existe."""
    s = _settings()
    assert s.llm_timeout_s < s.turno_timeout_s


def test_factory_usa_o_timeout_do_settings() -> None:
    s = _settings()
    assert criar_chat_deepseek(s).request_timeout == s.llm_timeout_s
    assert criar_chat_deepseek(s, thinking="low").request_timeout == s.llm_timeout_s


# ==================================================================================
# 3. repetição
# ==================================================================================


def test_aceite_isenta_a_reentrega_do_dado_combinado() -> None:
    """`decidido_rapido_b` t6: o `<entregue_agora>` MANDOU entregar a rua, o modelo entregou, e a
    bolha caiu no ramo `exato` — duas vezes. Re-entregar o dado depois do "fechou" é conduta."""
    historicas = ["Estou na Rua das Flores 100, Cambui amor"]
    bolha = "Estou na Rua das Flores 100, Cambui amor"
    assert mod.bolhas_repetidas(bolha, historicas) == [bolha]  # sem aceite: eco
    assert mod.bolhas_repetidas(bolha, historicas, houve_aceite=True) == []


def test_aceite_nao_isenta_pergunta_repetida() -> None:
    """O gate não é "desliga tudo no aceite": re-perguntar o que ele já respondeu continua sendo o
    papagaio mais visível — e depois do "fechou" é pior, não melhor."""
    historicas = ["Qual seu nome amor ?"]
    bolha = "Qual seu nome amor ?"
    assert mod.bolhas_repetidas(bolha, historicas, houve_aceite=True) == [bolha]


def test_responde_pedido_isenta_a_reformulacao_do_preco_perguntado() -> None:
    """Campanha 13/08 (eb02:26311003246742 t3): "E o investimento?" respondido com "é 400 a 1h no
    meu local" dava ratio 0,9048 contra a cotação do turno anterior — 0,005 acima do limiar — e o
    drop + regen produziam o AP-S1 ("Seria hoje amor ?"). O prompt manda exatamente essa jogada
    ("o valor volta, com outras palavras"); com o pedido de preço no burst, a bolha que carrega o
    dado é resposta, não papagaio."""
    historicas = ["400 1h no meu local"]
    bolha = "é 400 a 1h no meu local"
    pred = mod.re.compile(r"\d").search
    assert mod.bolhas_repetidas(bolha, historicas) == [bolha]  # sem o pedido: flagrada
    assert mod.bolhas_repetidas(bolha, historicas, responde_pedido=lambda b: bool(pred(b))) == []


def test_responde_pedido_nao_isenta_pergunta_nem_bolha_sem_o_dado() -> None:
    """A isenção é fechada no DADO pedido: pergunta repetida segue flagrada (mesma razão do
    aceite), e a bolha repetida que NÃO carrega o dado (sem dígito num pedido de preço) também."""
    pred = mod.re.compile(r"\d").search
    resposta = lambda b: bool(pred(b))  # noqa: E731
    assert mod.bolhas_repetidas(
        "Seria hoje amor ?", ["Seria hoje amor ?"], responde_pedido=resposta
    ) == ["Seria hoje amor ?"]
    eco = "Sou bem tranquila, estilo namoradinha completa"
    assert mod.bolhas_repetidas(eco, [eco], responde_pedido=resposta) == [eco]


# ==================================================================================
# 3b/3c/4. lembrete da regen: por bolha, sem contradição, com os anexos do turno
# ==================================================================================


class _ChatCaptura:
    def __init__(self) -> None:
        self.janelas: list[list[Any]] = []

    async def ainvoke(self, messages: list[Any], **_k: Any) -> AIMessage:
        self.janelas.append(list(messages))
        return AIMessage(content="nova fala", id="r1", usage_metadata=_USAGE)  # type: ignore[arg-type]


def _mensagens_do_turno(rascunho: str) -> list[Any]:
    return [
        HumanMessage(content="oi", id="h1"),
        AIMessage(content="fala antiga", id="hist0"),
        HumanMessage(content="e o endereço?", id="h2"),
        AIMessage(content=rascunho, id="a1", usage_metadata=_USAGE),  # type: ignore[arg-type]
    ]


async def _lembrete(monkeypatch: Any, **kwargs: Any) -> str:
    chat = _ChatCaptura()
    monkeypatch.setattr(mod_llm, "criar_chat_deepseek", lambda *a, **kw: chat)
    await mod._regenerar(settings=get_settings(), **kwargs)
    return str(chat.janelas[0][-1].content)


async def test_lembrete_descarta_por_bolha_e_preserva_o_resto(monkeypatch: Any) -> None:
    """Achado 4b: o gatilho é UMA bolha, e o lembrete jogava fora o turno inteiro — o modelo
    devolvia turno encolhido, com a pergunta do cliente engolida junto."""
    rascunho = "Consigo as 17h, fecha ?\n\nO uber ida e volta fica 100 amor"
    texto = await _lembrete(
        monkeypatch,
        messages=_mensagens_do_turno(rascunho),
        rascunho=rascunho,
        gatilho="repeticao",
        feedback_gatilho=mod._feedback_repeticao(["Consigo as 17h, fecha ?"]),
        bolhas_vetadas=["Consigo as 17h, fecha ?"],
    )
    assert "SO esta parte nao passou" in texto
    assert "pode ser reaproveitado" in texto
    assert "O uber ida e volta fica 100 amor" in texto


async def test_lembrete_de_repeticao_nao_manda_calar(monkeypatch: Any) -> None:
    """Achado 4b: `_feedback_repeticao` ("siga pelo que ainda FALTA combinar") vinha CONCATENADO
    com o extra ("devolva vazio -- silencio e melhor que repetir"). A mesma mensagem mandava
    avançar e calar; no fechamento o modelo escolhia calar."""
    texto = await _lembrete(
        monkeypatch,
        messages=_mensagens_do_turno("Consigo as 17h, fecha ?"),
        rascunho="Consigo as 17h, fecha ?",
        gatilho="repeticao",
        feedback_gatilho=mod._feedback_repeticao(["Consigo as 17h, fecha ?"]),
        bolhas_vetadas=["Consigo as 17h, fecha ?"],
    )
    assert "devolva vazio" not in texto
    assert "silencio e melhor" not in texto
    assert "FALTA combinar" in texto


async def test_lembrete_conta_os_anexos_do_turno(monkeypatch: Any) -> None:
    """Achado 5: a regen roda sem tools e sem as ToolMessages do turno — sem esta linha ela não
    tem sinal de que as fotos já estão indo e preenche com rubrica de teatro."""
    texto = await _lembrete(
        monkeypatch,
        messages=_mensagens_do_turno("Gravei um video pra voce"),
        rascunho="Gravei um video pra voce",
        gatilho="mudo",
        anexos=["as suas fotos/video"],
    )
    assert "JA anexou as suas fotos/video" in texto
    assert "nao prometa mandar de novo" in texto


async def test_lembrete_sem_anexos_fica_como_antes(monkeypatch: Any) -> None:
    texto = await _lembrete(
        monkeypatch,
        messages=_mensagens_do_turno("bolha qualquer"),
        rascunho="bolha qualquer",
        gatilho="mudo",
    )
    assert "JA anexou" not in texto


class _ResultFake:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    async def fetchall(self) -> list[dict[str, Any]]:
        return self._rows

    async def fetchone(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None


class _ConnAnexos:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    async def execute(self, *_a: Any, **_k: Any) -> _ResultFake:
        return _ResultFake(self._rows)


async def test_anexos_do_turno_le_o_que_commitou() -> None:
    rows = [
        {"tool_name": "enviar_midia", "pin": None, "pix": None},
        {"tool_name": "registrar_extracao", "pin": "true", "pix": "true"},
    ]
    assert await mod._anexos_do_turno(_ConnAnexos(rows), "t1") == [
        "as suas fotos/video",
        "a localizacao do ponto de encontro",
        "a sua chave Pix",
    ]
    assert await mod._anexos_do_turno(_ConnAnexos([]), "t1") == []


def test_placeholder_casa_rubrica_entre_parenteses() -> None:
    """Achado 5, item 3: `(aqui vão as fotos e o vídeo)` passava por TODOS os estágios (inclusive o
    re-scan da 2ª volta) e entrava na janela histórica como fala dela."""
    assert mod.tem_placeholder_template("(aqui vão as fotos e o vídeo)")
    assert mod.tem_placeholder_template("Te mando sim amor (segue o book)")
    # Fala legítima com parênteses NÃO pode virar placeholder.
    assert not mod.tem_placeholder_template("600 1h (valor fechado) amor")
    assert not mod.tem_placeholder_template("te espero (às 21h)")


# ==================================================================================
# 6. custo: input_token_details somado
# ==================================================================================


def _msg(input_t: int, cache_read: int, ident: str) -> AIMessage:
    return AIMessage(
        id=ident,
        content="x",
        usage_metadata={  # type: ignore[arg-type]
            "input_tokens": input_t,
            "output_tokens": 10,
            "total_tokens": input_t + 10,
            "input_token_details": {"cache_read": cache_read},
        },
    )


def test_usage_acumulado_preserva_o_cache_read() -> None:
    """Achado 7: reconstruir o usage só com as três chaves grandes fazia `_custo.py` ler
    `cache_read=0` e tarifar o prefixo QUENTE inteiro a preço de miss — 6x a conta do turno."""
    somado = mod._com_usage_acumulado(_msg(30_000, 29_000, "nova"), _msg(29_400, 29_000, "antes"))
    detalhes = (somado.usage_metadata or {}).get("input_token_details") or {}
    assert detalhes.get("cache_read") == 58_000

    from barra.agente._custo import input_nao_cacheado

    assert input_nao_cacheado(dict(somado.usage_metadata or {})) == 1_400


def test_usage_acumulado_sem_details_de_um_lado() -> None:
    nova = _msg(100, 80, "n")
    antes = AIMessage(
        id="a",
        content="y",
        usage_metadata={"input_tokens": 50, "output_tokens": 5, "total_tokens": 55},  # type: ignore[arg-type]
    )
    somado = mod._com_usage_acumulado(nova, antes)
    assert ((somado.usage_metadata or {}).get("input_token_details") or {})["cache_read"] == 80


# ==================================================================================
# 7. observabilidade do ramo `viola`
# ==================================================================================


class _FakeConn:
    async def execute(self, *_a: Any, **_k: Any) -> _ResultFake:
        return _ResultFake([])


class _FakePool:
    @asynccontextmanager
    async def connection(self) -> Any:
        yield _FakeConn()


class _Runtime:
    def __init__(self, context: ContextAgente) -> None:
        self.context = context


def _runtime() -> _Runtime:
    return _Runtime(
        ContextAgente(
            db_pool=_FakePool(),  # type: ignore[arg-type]
            redis=None,  # type: ignore[arg-type]
            modelo_id=str(uuid4()),
            atendimento_id=str(uuid4()),
            cliente_id=str(uuid4()),
            turno_id="turno-r3",
        )
    )


def _bloqueado(motivo: str) -> float:
    return (
        REGISTRY.get_sample_value(
            "agente_aup_saida_bloqueado_total", {"resultado": "violou", "motivo": motivo}
        )
        or 0.0
    )


async def test_ramo_viola_loga_e_rotula_o_motivo(monkeypatch: Any, caplog: Any) -> None:
    """Achado 8c: só o ramo de INFRA logava. Num post-mortem, decisão do judge e ausência de
    decisão eram indistinguíveis — mesma sanção, rastro só no banco."""

    async def _viola(texto: str, settings: Any, **_k: Any) -> Any:
        return mod._VeredictoAup(viola=True, motivo="system_leak")

    async def _nao_escala(*_a: Any, **_k: Any) -> None:
        return None

    monkeypatch.setattr(mod, "_julgar_aup", _viola)
    monkeypatch.setattr(mod_defesa, "escalar_defesa", _nao_escala)
    monkeypatch.setattr(mod, "escalar_defesa", _nao_escala)

    state = {
        "messages": [
            HumanMessage(content="oi", id="h1"),
            AIMessage(content="ja te mando o pix amor", id="a1", usage_metadata=_USAGE),  # type: ignore[arg-type]
        ]
    }
    antes = _bloqueado("system_leak")
    with caplog.at_level(logging.WARNING, logger="barra.agente.nos.output_guard"):
        res = await mod.output_guard(state, _runtime())  # type: ignore[arg-type]

    assert res.update["messages"][0].content == ""
    assert _bloqueado("system_leak") == antes + 1
    logs = [r.getMessage() for r in caplog.records if "aup viola" in r.getMessage()]
    assert logs and "system_leak" in logs[0] and "turno-r3" in logs[0]


async def test_bloqueio_carimba_a_pausa_no_state(monkeypatch: Any) -> None:
    """Achado 6, metade que não depende do Fernando: `_bloquear` escreve direto no banco, sem tocar
    em `messages` — sem o carimbo o coordenador lia a pausa do PRÓPRIO grafo como externa."""

    async def _viola(texto: str, settings: Any, **_k: Any) -> Any:
        return mod._VeredictoAup(viola=True, motivo="aup_dura")

    async def _nao_escala(*_a: Any, **_k: Any) -> None:
        return None

    monkeypatch.setattr(mod, "_julgar_aup", _viola)
    monkeypatch.setattr(mod, "escalar_defesa", _nao_escala)

    state = {
        "messages": [
            HumanMessage(content="oi", id="h1"),
            AIMessage(content="texto que o judge reprova", id="a1", usage_metadata=_USAGE),  # type: ignore[arg-type]
        ]
    }
    res = await mod.output_guard(state, _runtime())  # type: ignore[arg-type]
    assert res.update["_pausa_aberta_pelo_guard"] is True
