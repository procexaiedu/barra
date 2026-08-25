"""Gate pre-envio com regeneracao one-shot + detector de repeticao (output_guard, producao assistida).

Unit test sem DB/LLM (mesmo rig do test_output_guard.py): `_regenerar`/`_julgar_aup`/`abrir_handoff`
sao trocados por fakes; conn/pool fakes. Cobre:

- detector puro `bolhas_repetidas`: bolha longa quase identica a bolha recente da IA flagra;
  cumprimento curto, reformulacao real e negacao canned NAO flagram; duplicata dentro do turno flagra.
- regen LIMPOU: leak/repeticao/mudo no texto -> regenera 1x -> despacha a nova (originais zeradas,
  nova anexada), sem handoff.
- regen PERSISTIU: leak -> bloqueia + handoff (nova tambem zerada); repeticao -> dropa a bolha
  repetida (silencio > papagaio), sem handoff.
- regen DESLIGADA (flag): leak volta ao comportamento antigo (bloqueio direto, sem chamada);
  repeticao dropa direto das mensagens originais.
- incluso FANTASMA (item declarado incluso fora da linha "Inclusos" do <fetiches>): mesmo trilho da
  sonda -- regenera 1x e, persistindo, dropa so a bolha; nunca handoff.
- leak em LEGENDA e nao-regeneravel: bloqueia sem tentar regen.
- judge (Etapa 2) roda tambem sobre o texto regenerado: viola -> bloqueia tudo.
- `_regenerar` (unit): monta a janela ate ANTES do turno + lembrete; recusa/excecao -> None.
"""

import importlib
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langgraph.graph import END

from barra.agente._canned import NEGACOES_CANNED
from barra.agente._texto_turno import raciocinio_do_turno
from barra.agente.contexto import ContextAgente
from barra.agente.ferramentas.escalada import ESCALADA_ABERTA_PREFIXO
from barra.settings import get_settings

# nos/__init__ reexporta a funcao output_guard, sombreando o submodulo; importlib pega o modulo
# real p/ monkeypatch (memoria "nos/__init__ sombreia submodulo").
mod = importlib.import_module("barra.agente.nos.output_guard")
mod_defesa = importlib.import_module("barra.agente._defesa")

_USAGE = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}


class _FakeResult:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    async def fetchall(self) -> list[dict[str, Any]]:
        return self._rows

    async def fetchone(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None


class _FakeConn:
    def __init__(self, legendas: list[str] | None = None) -> None:
        self._legendas = legendas or []

    async def execute(self, query: str, *args: Any, **kwargs: Any) -> _FakeResult:
        if "enviar_midia" in query:
            return _FakeResult([{"legenda": leg} for leg in self._legendas])
        return _FakeResult([])


class _FakePool:
    def __init__(self, conn: _FakeConn) -> None:
        self._conn = conn

    @asynccontextmanager
    async def connection(self) -> Any:
        yield self._conn


class _Runtime:
    def __init__(self, context: ContextAgente) -> None:
        self.context = context


def _runtime(legendas: list[str] | None = None) -> _Runtime:
    pool = _FakePool(_FakeConn(legendas))
    ctx = ContextAgente(
        db_pool=pool,  # type: ignore[arg-type]
        redis=None,  # type: ignore[arg-type]
        modelo_id=str(uuid4()),
        atendimento_id=str(uuid4()),
        cliente_id=str(uuid4()),
        turno_id=str(uuid4()),
    )
    return _Runtime(ctx)


def _state(texto: str, historico: list[str] | None = None) -> dict[str, Any]:
    """Janela minima: historico (AIMessages SEM usage = ja enviadas) + a bolha do turno (com usage)."""
    msgs: list[BaseMessage] = [HumanMessage(content="oi", id="h1")]
    for i, h in enumerate(historico or []):
        msgs.append(AIMessage(content=h, id=f"hist{i}"))
    msgs.append(HumanMessage(content="e ai?", id="h2"))
    msgs.append(AIMessage(content=texto, id="a1", usage_metadata=_USAGE))
    return {"messages": msgs}


class _Capturador:
    def __init__(self) -> None:
        self.chamadas: list[dict[str, Any]] = []

    async def __call__(self, conn: Any, **kwargs: Any) -> None:
        self.chamadas.append(kwargs)


def _fake_regen(content: str | None) -> Any:
    """Fake de _regenerar: devolve a AIMessage regenerada (ou None = indisponivel) e grava a chamada."""

    class _Regen:
        def __init__(self) -> None:
            self.chamadas: list[dict[str, Any]] = []

        async def __call__(self, *args: Any, **kwargs: Any) -> AIMessage | None:
            self.chamadas.append(kwargs)
            if content is None:
                return None
            return AIMessage(content=content, id="regen1", usage_metadata=_USAGE)

    return _Regen()


def _judge_ok(monkeypatch: Any) -> None:
    # **_kw tolera o `contexto_factual` que o guard anexa quando há endereço liberado no turno
    # (ponto #2 da auditoria guard/judge): o double só precisa devolver "não viola".
    async def _ok(texto: str, settings: Any, **_kw: Any) -> Any:
        return mod._VeredictoAup(viola=False, motivo="nenhum")

    monkeypatch.setattr(mod, "_julgar_aup", _ok)


def _msgs_update(res: Any) -> dict[str, Any]:
    return {m.id: m.content for m in (res.update or {}).get("messages", [])}


# --- detector puro -------------------------------------------------------------------------------

_BOLHA_LONGA = "então amor, qual horário fica melhor pra você vir aqui hoje?"


def test_repeticao_flagra_bolha_quase_identica_ao_historico() -> None:
    # variacao minima (pontuacao/emoji) da mesma pergunta ja enviada = rastro de papagaio.
    quase = "Então amor, qual horário fica melhor pra você vir aqui hoje 🥰"
    assert mod.bolhas_repetidas(quase, [_BOLHA_LONGA]) == [quase]


def test_repeticao_nao_flagra_cumprimento_curto() -> None:
    # "oi amor" repete legitimamente (abaixo de _REPETICAO_MIN_VERBATIM chars normalizados).
    assert mod.bolhas_repetidas("oi amor", ["oi amor", _BOLHA_LONGA]) == []


def test_repeticao_flagra_bolha_de_preco_curta_verbatim() -> None:
    # onda 1 finding C: "400 1h no meu local" (19 chars normalizados) passava sob o piso fuzzy de
    # 25 e o papagaio literal ia ao cliente. Reenvio EXATO agora conta pelo piso verbatim.
    preco = "400 1h no meu local"
    assert mod.bolhas_repetidas(preco, [preco]) == [preco]


def test_repeticao_flagra_pergunta_curta_repetida() -> None:
    """ "Qual seu nome ?" tem 13 chars normalizados — um a menos que o piso verbatim — e a
    allowlist de sondas so cobre o que alguem lembrou de listar. Medido ao vivo em 12/08: a IA
    perguntou o nome em dois turnos seguidos. Pergunta refeita verbatim soa como quem nao leu a
    resposta; afirmacao curta ("Perfeito") segue repetindo de graca."""
    nome = "Qual seu nome ?"
    assert mod.bolhas_repetidas(nome, [nome]) == [nome]
    assert mod.bolhas_repetidas("Perfeito", ["Perfeito"]) == []
    # "tudo bem?" (8 normalizados) fica de fora: e saudacao, nao sonda de qualificacao.
    assert mod.bolhas_repetidas("Tudo bem ?", ["Tudo bem ?"]) == []


def test_repeticao_flagra_bolha_curta_com_o_mesmo_numero() -> None:
    """O papagaio mais caro do funil: a bolha de fechamento reformulada sobre a MESMA hora, turno
    apos turno ("Consigo às 17h, te espero aqui" -> "Consigo às 17h, te espero"). 24 chars
    normalizados contra um piso fuzzy de 25 — passava batido (medido ao vivo em 12/08)."""
    assert mod.bolhas_repetidas(
        "Consigo às 17h, te espero", ["Consigo às 17h, te espero aqui"]
    ) == ["Consigo às 17h, te espero"]


def test_repeticao_flagra_reoferta_que_muda_so_a_cauda() -> None:
    """Ultimo degrau do papagaio de fechamento: mesma oferta, mesma hora, cauda nova ("Consigo às
    17h, fecha ?" -> "Consigo às 17h então ?") — ratio 0,80, longe do limiar, e ia ao cliente."""
    assert mod.bolhas_repetidas("Consigo às 17h então ?", ["Consigo às 17h, fecha ?"]) == [
        "Consigo às 17h então ?"
    ]


def test_repeticao_flagra_cotacao_dita_duas_vezes_com_abertura_diferente() -> None:
    """O outro recorte: a bolha nova cabe quase inteira dentro da anterior ("Isso amor, 400 a 1h +
    o uber ida e volta" -> "400 1h + o uber ida e volta"), sem compartilhar abertura (ratio 0,79)."""
    assert mod.bolhas_repetidas(
        "400 1h + o uber ida e volta", ["Isso amor, 400 a 1h + o uber ida e volta"]
    ) == ["400 1h + o uber ida e volta"]


def test_repeticao_nao_flagra_a_mesma_cotacao_reformulada_de_verdade() -> None:
    """Reformular com palavras proprias segue livre — o detector mira o eco, nao o assunto."""
    assert mod.bolhas_repetidas("São 400 na 1h aqui em casa amor", ["400 1h no meu local"]) == []


def test_repeticao_nao_flagra_abertura_diferente_com_a_mesma_hora() -> None:
    """Confirmar a hora combinada nao e reofertar: so o par que compartilha a ABERTURA conta."""
    assert mod.bolhas_repetidas("Consigo às 20h, fecha ?", ["Te espero às 20h aqui em casa"]) == []


def test_repeticao_flagra_dois_pedidos_de_fechamento_no_mesmo_turno() -> None:
    """Repeticao de ATO, nao de forma: as duas frases nao se parecem (nenhum limiar as pega), mas
    pedir duas vezes o mesmo sim na MESMA resposta soa ansioso (grupo de testes, 12/08)."""
    turno = "Podemos combinar 21h?\n\nFechou 21h então amor?"
    assert mod.bolhas_repetidas(turno, []) == ["Fechou 21h então amor?"]


def test_repeticao_nao_flagra_fechamento_seguido_de_outra_pergunta() -> None:
    """Pedir o sim e depois pedir o endereco e o turno bem conduzido — so a SEGUNDA cobranca do
    mesmo sim conta, e a confirmacao afirmativa pos-aceite nem entra (nao e pergunta)."""
    assert mod.bolhas_repetidas("Te espero às 21h então amor\n\nMe manda o endereço ?", []) == []
    assert (
        mod.bolhas_repetidas("Consigo às 20h ou 21h, qual prefere ?\n\nMe diz o bairro ?", []) == []
    )


def test_repeticao_nao_flagra_bolha_de_forma_igual_com_numero_novo() -> None:
    """Mesma forma com dado NOVO e informacao, nao papagaio — a segunda porta da tabela sai assim.

    O par curto abaixo passava por ACIDENTE (ratio 0,8947 e 19 chars, os dois um fio abaixo dos
    limiares), e o invariante nao era aplicado no ramo fuzzy: o par LONGO do loop-massa r2 (eixo
    externo t6 — 29 chars, ratio 0,926) atravessava as duas margens e a bolha que carregava o
    numero INEDITO do turno era flagrada como papagaio (guard disparou, o feedback da regen mandou
    justamente essa bolha embora e o turno custou +88%)."""
    assert mod.bolhas_repetidas("700 2h no meu local", ["400 1h no meu local"]) == []
    assert (
        mod.bolhas_repetidas("400 1h + 100 o uber ida e volta", ["400 1h + o uber ida e volta"])
        == []
    )
    # E a direcao contraria segue flagrando: sem numero novo, so a forma mudando, e eco.
    assert mod.bolhas_repetidas("400 1h no meu local amor", ["400 1h no meu local aqui"]) == [
        "400 1h no meu local amor"
    ]


def test_repeticao_flagra_fala_que_FUNDE_duas_bolhas_ja_enviadas() -> None:
    """Assimetria medida no loop-massa r2 (eixo explorador t2): o mesmo conteudo era pego quando
    saia em duas bolhas e passava quando saia FUNDIDO numa so (cada metade dava ratio ~0,59 contra
    a bolha correspondente). O cliente respondeu "Vc ja falou isso rs" — dano observado."""
    historicas = ["Sou bem tranquila amor", "Estilo namoradinha"]
    fundida = "Sou bem tranquila amor, estilo namoradinha"
    assert mod.bolhas_repetidas(fundida, historicas) == [fundida]
    # simetria: soltas continuam sendo pegas bolha a bolha (comportamento de antes)
    assert mod.bolhas_repetidas("\n\n".join(historicas), historicas) == historicas


def test_fusao_nao_dropa_o_turno_do_fechamento() -> None:
    """A cauda da fusao passa pelo MESMO gate do eco de abertura (`houve_aceite`) — e aqui o dano e
    maior: o veredito e sobre o TURNO INTEIRO, entao a confirmacao pos-aceite (que por construcao
    junta a oferta que ele acabou de aceitar) saia MUDA no instante do fechamento (revisao da r2).

    Sem aceite, a mesma fala continua flagrada — o gate desliga a cauda, nao o detector."""
    historicas = ["Fica 400 a 1h no meu local amor", "Te espero às 21h então"]
    fechamento = "Fica 400 a 1h no meu local amor, te espero às 21h então"
    assert mod.bolhas_repetidas(fechamento, historicas, houve_aceite=True) == []
    assert mod.bolhas_repetidas(fechamento, historicas) == [fechamento]


def test_fusao_nao_derruba_fala_com_dado_novo_nem_conteudo_novo() -> None:
    """A juncao herda a isencao de NUMERO NOVO (`_tem_numero_novo`) e o limiar: repetir o que ja
    disse MAIS um numero inedito e informacao, e fala nova nao se parece com juncao nenhuma."""
    historicas = ["Sou bem tranquila amor", "Estilo namoradinha"]
    assert (
        mod.bolhas_repetidas("Sou bem tranquila amor, estilo namoradinha, 400 a 1h", historicas)
        == []
    )
    assert mod.bolhas_repetidas("Consigo às 21h amor, fecha ?", historicas) == []


def test_repeticao_verbatim_isenta_saudacao_media() -> None:
    # "boa tarde amor" (14 chars) segue isento mesmo verbatim: fica abaixo do piso verbatim (15),
    # onde a repeticao de saudacao ainda e legitima.
    assert mod.bolhas_repetidas("boa tarde amor", ["boa tarde amor"]) == []


def test_repeticao_nao_flagra_reformulacao_real() -> None:
    # reformulacao humana ("como te falei...") cai abaixo do limiar de similaridade.
    reform = "como te falei amor: 400 a hora aqui no meu local, perto do centro"
    assert mod.bolhas_repetidas(reform, ["o valor de 1h é 400 no meu local amor"]) == []


def test_repeticao_flagra_duplicata_dentro_do_mesmo_turno() -> None:
    turno = f"{_BOLHA_LONGA}\n\n{_BOLHA_LONGA}"
    assert mod.bolhas_repetidas(turno, []) == [_BOLHA_LONGA]


def test_repeticao_ignora_a_cauda_de_voz_que_o_envio_tira_depois() -> None:
    # P1-4a/4b (trace 66b8161e): o 2o passe do ReAct pos-`enviar_midia` re-emitiu a pergunta e o
    # detector errou por 0,011 ("seria que horas hoje amor" x "seria que horas hoje" = 0,889 < 0,90)
    # — a camada de voz do envio (vocativo/emoji) roda DEPOIS do guard, entao ele julgava um texto
    # que nao e o que o cliente recebe. A cauda de voz sai da CHAVE de comparacao.
    assert mod.bolhas_repetidas("Seria que horas hoje amor ?", ["Seria que horas hoje ?"]) == [
        "Seria que horas hoje amor ?"
    ]
    assert mod.bolhas_repetidas("Seria que horas hoje ? 🥰", ["Seria que horas hoje amor rs"]) == [
        "Seria que horas hoje ? 🥰"
    ]


def test_repeticao_flagra_sonda_canonica_curta() -> None:
    # "seria hoje" normaliza para 10 chars e passava sob o piso verbatim (15) — e e justamente a
    # fala que o <ja_sondou_o_dia> promete dizer UMA vez na conversa inteira (medida repetida
    # verbatim em 2 cenarios do diagnostico 11/08).
    assert mod.bolhas_repetidas("Seria hoje ?", ["Seria hoje amor ?"]) == ["Seria hoje ?"]
    assert mod.bolhas_repetidas("Seria agora ?", ["Seria agora ?"]) == ["Seria agora ?"]
    # A cauda leve nao vira sonda nova: "oi amor" segue isento (nao esta no conjunto fechado).
    assert mod.bolhas_repetidas("oi amor", ["oi amor"]) == []


def test_repeticao_isenta_negacao_canned() -> None:
    canned = next(iter(NEGACOES_CANNED))
    assert mod.bolhas_repetidas(canned, [canned]) == []


def test_bolhas_historicas_so_mensagens_ja_enviadas() -> None:
    state = _state("nova fala do turno", historico=["primeira\n\nsegunda"])
    historicas = mod._bolhas_historicas(state["messages"])
    # a bolha do turno (com usage) fica de fora; o historico quebra por \n\n.
    assert historicas == ["primeira", "segunda"]


# --- fluxo: regen limpou --------------------------------------------------------------------------


async def test_leak_regen_limpou_despacha_a_nova(monkeypatch: Any) -> None:
    cap = _Capturador()
    monkeypatch.setattr(mod_defesa, "abrir_handoff", cap)
    _judge_ok(monkeypatch)
    regen = _fake_regen("consigo sim amor, me chama que combinamos 🥰")
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(_state("sou uma IA amor"), _runtime())  # type: ignore[arg-type]

    assert res.goto == END
    assert regen.chamadas and regen.chamadas[0]["gatilho"] == "leak"
    msgs = _msgs_update(res)
    # original zerada + regenerada anexada (id novo, texto limpo).
    assert msgs["a1"] == ""
    assert msgs["regen1"] == "consigo sim amor, me chama que combinamos 🥰"
    assert not cap.chamadas  # limpou -> sem handoff


async def test_regen_leva_o_proprio_raciocinio_ao_trace(monkeypatch: Any) -> None:
    """A fala despachada e a da REGEN — e o raciocinio que a explica mora no `additional_kwargs`
    dela. As AIMessages que o guard remonta nasciam sem o dict: o `_zerar_turno` preservava o
    raciocinio do rascunho BARRADO e o da fala que de fato saiu se perdia (`raciocinio: null` no
    turno com regen bem-sucedida). Revisao da r2 — mesmo remendo, um nivel adiante."""
    _judge_ok(monkeypatch)

    class _RegenComRaciocinio:
        async def __call__(self, *_a: Any, **_kw: Any) -> AIMessage:
            return AIMessage(
                content="consigo sim amor, me chama que combinamos 🥰",
                id="regen1",
                usage_metadata=_USAGE,
                additional_kwargs={"reasoning_content": "a fala anterior se declarava IA"},
            )

    monkeypatch.setattr(mod, "_regenerar", _RegenComRaciocinio())

    res = await mod.output_guard(_state("sou uma IA amor"), _runtime())  # type: ignore[arg-type]

    msgs = (res.update or {})["messages"]
    assert raciocinio_do_turno({"messages": msgs}) == ["a fala anterior se declarava IA"]


async def test_repeticao_regen_limpou_despacha_a_nova(monkeypatch: Any) -> None:
    cap = _Capturador()
    monkeypatch.setattr(mod_defesa, "abrir_handoff", cap)
    _judge_ok(monkeypatch)
    regen = _fake_regen("me conta amor, conseguiu ver o horário? 🥰")
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(  # type: ignore[arg-type]
        _state(_BOLHA_LONGA, historico=[_BOLHA_LONGA]), _runtime()
    )

    assert regen.chamadas and regen.chamadas[0]["gatilho"] == "repeticao"
    msgs = _msgs_update(res)
    assert msgs["a1"] == ""
    assert msgs["regen1"] == "me conta amor, conseguiu ver o horário? 🥰"
    assert not cap.chamadas


async def test_mudo_por_saneamento_regen_limpou_despacha_a_nova(monkeypatch: Any) -> None:
    # turno 100%-raciocinio: antes ficava mudo; com regen, vira fala de verdade.
    _judge_ok(monkeypatch)
    regen = _fake_regen("oi amor, me conta o que você procura?")
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(  # type: ignore[arg-type]
        _state("o cliente demonstrou interesse, meu próximo passo é cotar"), _runtime()
    )

    assert regen.chamadas and regen.chamadas[0]["gatilho"] == "mudo"
    msgs = _msgs_update(res)
    assert msgs["a1"] == ""
    assert msgs["regen1"] == "oi amor, me conta o que você procura?"


async def test_sonda_regen_limpou_despacha_a_nova(monkeypatch: Any) -> None:
    # Regressao (lead RNine, 22/07): a sonda era dropada em silencio no Estagio 0 e o turno saia so
    # com o cumprimento, emperrando a conversa. Agora ela e gatilho de regen e a fala volta inteira.
    cap = _Capturador()
    monkeypatch.setattr(mod_defesa, "abrir_handoff", cap)
    _judge_ok(monkeypatch)
    regen = _fake_regen("Tudo bem sim amor 🥰\n\nEstá aqui na cidade ?")
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(  # type: ignore[arg-type]
        _state("Tudo bem sim amor 🥰\n\nO que você procura ?"), _runtime()
    )

    assert regen.chamadas and regen.chamadas[0]["gatilho"] == "sonda"
    msgs = _msgs_update(res)
    assert msgs["a1"] == ""
    assert msgs["regen1"] == "Tudo bem sim amor 🥰\n\nEstá aqui na cidade ?"
    assert not cap.chamadas


# --- fluxo: regen persistiu -----------------------------------------------------------------------


async def test_leak_persistiu_na_regen_bloqueia_e_zera_tudo(monkeypatch: Any) -> None:
    cap = _Capturador()
    monkeypatch.setattr(mod_defesa, "abrir_handoff", cap)
    regen = _fake_regen("continuo sendo uma IA amor")  # regen tambem vaza
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(_state("sou uma IA amor"), _runtime())  # type: ignore[arg-type]

    assert res.goto == END
    assert len(cap.chamadas) == 1  # handoff aberto (fallback pre-regen)
    msgs = _msgs_update(res)
    assert msgs["a1"] == "" and msgs["regen1"] == ""  # nada sai ao cliente, nem a regen


async def test_repeticao_persistiu_na_regen_passa_pelo_piso_anti_mudo(monkeypatch: Any) -> None:
    """Bolha UNICA repetida + regen reincidente: ate 14/08 o turno fechava MUDO (este teste pinava
    `msgs["a1"] == ""`). O piso anti-mudo (corrida c12, 5 turnos mudos em 327) inverteu a saida:
    `repeticao` e QUALIDADE, e silencio total e pior que eco — a bolha original passa, com a
    regen inutilizavel zerada e metrica propria. Handoff continua fora de questao."""
    cap = _Capturador()
    monkeypatch.setattr(mod_defesa, "abrir_handoff", cap)
    _judge_ok(monkeypatch)
    regen = _fake_regen(_BOLHA_LONGA)  # regen repete de novo
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(  # type: ignore[arg-type]
        _state(_BOLHA_LONGA, historico=[_BOLHA_LONGA]), _runtime()
    )

    assert res.goto == END
    assert not cap.chamadas  # repeticao NUNCA vira handoff: silencio > papagaio
    msgs = _msgs_update(res)
    assert "a1" not in msgs  # a bolha original segue viva
    assert msgs["regen1"] == ""


async def test_sonda_persistiu_na_regen_dropa_so_o_probe(monkeypatch: Any) -> None:
    # Reincidiu: cai no fallback de hoje (drop da bolha ofensora), mas o resto da fala sai.
    cap = _Capturador()
    monkeypatch.setattr(mod_defesa, "abrir_handoff", cap)
    _judge_ok(monkeypatch)
    regen = _fake_regen("Tudo bem sim amor 🥰\n\nO que você busca ?")  # sonda de novo
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(  # type: ignore[arg-type]
        _state("Tudo bem sim amor 🥰\n\nO que você procura ?"), _runtime()
    )

    assert not cap.chamadas  # sonda NUNCA vira handoff
    msgs = _msgs_update(res)
    assert msgs["a1"] == ""
    assert msgs["regen1"] == "Tudo bem sim amor 🥰"


async def test_incluso_fantasma_e_gatilho_de_regen(monkeypatch: Any) -> None:
    # Corrida do conduta_gate 30/07: modelo com "(sem fetiches cadastrados)" e a IA copiando a fala
    # do exemplo. O _FakeConn nao devolve fetiche nenhum -> e exatamente o bloco vazio da falha.
    cap = _Capturador()
    monkeypatch.setattr(mod_defesa, "abrir_handoff", cap)
    _judge_ok(monkeypatch)
    regen = _fake_regen("Sou bem tranquila\n\nEstilo namoradinha")
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(  # type: ignore[arg-type]
        _state("Carinhosa e atenciosa amor\n\nBeijo na boca e oral sem camisinha já vem junto 🥰"),
        _runtime(),
    )

    assert regen.chamadas and regen.chamadas[0]["gatilho"] == "incluso"
    msgs = _msgs_update(res)
    assert msgs["a1"] == ""
    assert msgs["regen1"] == "Sou bem tranquila\n\nEstilo namoradinha"
    assert not cap.chamadas  # incluso fantasma NUNCA vira handoff


async def test_incluso_persistiu_na_regen_dropa_so_a_bolha(monkeypatch: Any) -> None:
    # Reincidiu: dropa a bolha do incluso e manda o resto (a apresentacao de estilo sobrevive).
    cap = _Capturador()
    monkeypatch.setattr(mod_defesa, "abrir_handoff", cap)
    _judge_ok(monkeypatch)
    regen = _fake_regen("Carinhosa e atenciosa amor\n\nBeijo na boca tá incluso amor")
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(  # type: ignore[arg-type]
        _state("Carinhosa e atenciosa amor\n\nBeijo na boca e oral sem camisinha já vem junto 🥰"),
        _runtime(),
    )

    assert not cap.chamadas
    msgs = _msgs_update(res)
    assert msgs["a1"] == ""
    assert msgs["regen1"] == "Carinhosa e atenciosa amor"


# --- fluxo: regen desligada/indisponivel ----------------------------------------------------------


async def test_flag_desligada_leak_bloqueia_direto_sem_regen(monkeypatch: Any) -> None:
    cap = _Capturador()
    monkeypatch.setattr(mod_defesa, "abrir_handoff", cap)
    regen = _fake_regen("nunca deveria ser chamada")
    monkeypatch.setattr(mod, "_regenerar", regen)
    settings = get_settings().model_copy(update={"output_guard_regen_habilitado": False})
    monkeypatch.setattr(mod, "get_settings", lambda: settings)

    res = await mod.output_guard(_state("sou uma IA amor"), _runtime())  # type: ignore[arg-type]

    assert not regen.chamadas  # kill-switch: comportamento antigo
    assert len(cap.chamadas) == 1
    assert _msgs_update(res)["a1"] == ""


async def test_repeticao_sem_regen_dropa_a_bolha_e_mantem_a_fresca(monkeypatch: Any) -> None:
    cap = _Capturador()
    monkeypatch.setattr(mod_defesa, "abrir_handoff", cap)
    _judge_ok(monkeypatch)
    settings = get_settings().model_copy(update={"output_guard_regen_habilitado": False})
    monkeypatch.setattr(mod, "get_settings", lambda: settings)

    fresca = "consegue chegar aqui pra que horas amor?"
    res = await mod.output_guard(  # type: ignore[arg-type]
        _state(f"{_BOLHA_LONGA}\n\n{fresca}", historico=[_BOLHA_LONGA]), _runtime()
    )

    assert not cap.chamadas
    # a repetida sai; a fresca segue ao cliente na PROPRIA mensagem reescrita (mesmo id).
    assert _msgs_update(res)["a1"] == fresca


# --- fronteiras: legenda e judge ------------------------------------------------------------------


async def test_leak_em_legenda_bloqueia_sem_tentar_regen(monkeypatch: Any) -> None:
    cap = _Capturador()
    monkeypatch.setattr(mod_defesa, "abrir_handoff", cap)
    regen = _fake_regen("nunca deveria ser chamada")
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(  # type: ignore[arg-type]
        _state("fala limpa amor"), _runtime(legendas=["sou uma IA nessa foto"])
    )

    assert not regen.chamadas  # legenda ja persistiu como arg de tool: nao-regeneravel
    assert len(cap.chamadas) == 1
    assert _msgs_update(res)["a1"] == ""


async def test_judge_roda_sobre_o_texto_regenerado_e_pode_bloquear(monkeypatch: Any) -> None:
    cap = _Capturador()
    monkeypatch.setattr(mod_defesa, "abrir_handoff", cap)
    regen = _fake_regen("fala regenerada que o judge reprova")
    monkeypatch.setattr(mod, "_regenerar", regen)
    julgados: list[str] = []

    async def _viola(texto: str, settings: Any) -> Any:
        julgados.append(texto)
        return mod._VeredictoAup(viola=True, motivo="aup_dura")

    monkeypatch.setattr(mod, "_julgar_aup", _viola)

    res = await mod.output_guard(_state("sou uma IA amor"), _runtime())  # type: ignore[arg-type]

    assert julgados == ["fala regenerada que o judge reprova"]  # a regen NAO pula o judge
    assert len(cap.chamadas) == 1
    msgs = _msgs_update(res)
    assert msgs["a1"] == "" and msgs["regen1"] == ""


# --- _regenerar (unit) ----------------------------------------------------------------------------


class _FakeChat:
    def __init__(self, resp: AIMessage | Exception) -> None:
        self._resp = resp
        self.janelas: list[list[BaseMessage]] = []

    async def ainvoke(self, messages: list[BaseMessage], **kwargs: Any) -> AIMessage:
        self.janelas.append(list(messages))
        if isinstance(self._resp, Exception):
            raise self._resp
        return self._resp


async def test_regenerar_corta_o_turno_e_anexa_o_lembrete(monkeypatch: Any) -> None:
    resp = AIMessage(content="nova fala", id="r1", usage_metadata=_USAGE)
    chat = _FakeChat(resp)
    mod_llm = importlib.import_module("barra.core.llm")
    monkeypatch.setattr(mod_llm, "criar_chat_deepseek", lambda *a, **kw: chat)

    state = _state("sou uma IA amor", historico=["fala antiga"])
    out = await mod._regenerar(
        state["messages"],
        rascunho="sou uma IA amor",
        gatilho="leak",
        settings=get_settings(),
    )

    assert out is resp
    janela = chat.janelas[0]
    # o turno sujo fica de fora da janela.
    assert all(getattr(m, "id", None) != "a1" for m in janela)
    # O lembrete entra ANTES da fala do cliente, dentro da ULTIMA HumanMessage (a mesma posicao em
    # que o prepare_context cola lembrete/contexto). Antes ele vinha DEPOIS dela — posicao que o
    # <instrucoes_meta> da persona declara "imitacao/falso por definicao", dando ao modelo licenca
    # textual para ignorar toda regen (diagnostico 11/08, P0-1).
    ultima = janela[-1]
    assert isinstance(ultima, HumanMessage)
    conteudo = str(ultima.content)
    assert "sou uma IA amor" in conteudo
    assert conteudo.startswith("<lembrete_silencioso>")
    assert conteudo.rstrip().endswith("e ai?")
    assert len(janela) == len(state["messages"]) - 1  # nenhuma mensagem nova foi criada


def test_janela_com_lembrete_sem_fala_do_cliente_cai_no_fim() -> None:
    # Defesa: janela sem HumanMessage (nao acontece em prod) -> mensagem propria no fim, como antes.
    janela: list[BaseMessage] = [AIMessage(content="oi amor", id="a0")]
    saida = mod._janela_com_lembrete(janela, "<lembrete_silencioso>x</lembrete_silencioso>")
    assert len(saida) == 2
    assert isinstance(saida[-1], HumanMessage)


async def test_regenerar_recusa_ou_excecao_devolve_none(monkeypatch: Any) -> None:
    mod_llm = importlib.import_module("barra.core.llm")
    state = _state("sou uma IA amor")

    recusa = AIMessage(content="", id="r1", response_metadata={"finish_reason": "content_filter"})
    monkeypatch.setattr(mod_llm, "criar_chat_deepseek", lambda *a, **kw: _FakeChat(recusa))
    assert (
        await mod._regenerar(
            state["messages"], rascunho="x", gatilho="leak", settings=get_settings()
        )
        is None
    )

    monkeypatch.setattr(
        mod_llm, "criar_chat_deepseek", lambda *a, **kw: _FakeChat(RuntimeError("boom"))
    )
    assert (
        await mod._regenerar(
            state["messages"], rascunho="x", gatilho="leak", settings=get_settings()
        )
        is None
    )


async def test_regenerar_sem_orcamento_nem_chama_o_provider(monkeypatch: Any) -> None:
    """Campanha 13/08: a regen roda por último e herda o que sobrou do teto do turno (60s). Com o
    prazo já consumido (regen custaria mais que o restante menos a reserva do judge), ela devolve
    None SEM chamar o LLM — o fallback determinístico do gatilho é melhor que uma chamada que faz
    o turno morrer por fora do grafo (mute + escalada por exaustão)."""
    from time import monotonic

    mod_llm = importlib.import_module("barra.core.llm")

    def _nunca(*a: Any, **kw: Any) -> Any:
        raise AssertionError("nao deveria chamar o provider sem orcamento")

    monkeypatch.setattr(mod_llm, "criar_chat_deepseek", _nunca)
    state = _state("é 400 a 1h no meu local")
    assert (
        await mod._regenerar(
            state["messages"],
            rascunho="x",
            gatilho="repeticao",
            settings=get_settings(),
            deadline_mono=monotonic() + mod._RESERVA_POS_REGEN_S + mod._REGEN_MIN_S - 1.0,
        )
        is None
    )


async def test_excecao_no_guard_deixa_o_turno_mudo(monkeypatch: Any) -> None:
    """Fail-closed: o guard é a última defesa dentro do grafo, então falha DELE (DB fora, bug) não
    pode virar passagem livre — as bolhas do turno vão zeradas para o coordenador."""

    async def _explode(*a: Any, **kw: Any) -> Any:
        raise RuntimeError("pool esgotado")

    monkeypatch.setattr(mod, "_legendas_do_turno", _explode)
    state = _state("consigo sim amor")

    res = await mod.output_guard(state, _runtime())  # type: ignore[arg-type]

    assert res.goto == END
    assert [m.content for m in res.update["messages"]] == [""]


# --- silencio do modelo (campanha-subst rodada 1): turno vazio sem tool de efeito -----------------


def _state_silencio(tool: str = "registrar_extracao") -> dict[str, Any]:
    """Turno em que o modelo SO chamou tool e terminou vazio: nenhuma fala ao cliente."""
    msgs: list[BaseMessage] = [
        HumanMessage(content="Quero. Quanto?", id="h1"),
        AIMessage(
            content="",
            id="a1",
            usage_metadata=_USAGE,
            tool_calls=[{"name": tool, "args": {}, "id": "tc1"}],
        ),
        AIMessage(content="", id="a2", usage_metadata=_USAGE),
    ]
    return {"messages": msgs}


async def test_silencio_do_modelo_regenera_como_mudo(monkeypatch: Any) -> None:
    """Regressao (shadow funil, 10/08): 4,5% dos pontos terminavam com o modelo mudo (so
    registrar_extracao, content vazio) e o guard dava early-return 'nada a guardar' — cliente no
    vacuo. Agora entra no gate como `mudo` e regenera."""
    _judge_ok(monkeypatch)
    regen = _fake_regen("600 1h no meu local amor 😊\n\nSeria hoje ?")
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(_state_silencio(), _runtime())  # type: ignore[arg-type]

    assert res.goto == END
    assert regen.chamadas and regen.chamadas[0]["gatilho"] == "mudo"
    msgs = _msgs_update(res)
    assert msgs["regen1"] == "600 1h no meu local amor 😊\n\nSeria hoje ?"


async def test_silencio_com_tool_de_efeito_preserva_o_silencio(monkeypatch: Any) -> None:
    """Turno vazio mas com tool de efeito (escalar/enviar_midia): o silencio e proposital
    (pausa/handoff/midia sem texto) — nao regenera."""
    regen = _fake_regen("nao deveria ser chamada")
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(_state_silencio(tool="escalar"), _runtime())  # type: ignore[arg-type]

    assert res.goto == END
    assert not regen.chamadas


async def test_silencio_com_ia_pausada_preserva_o_silencio(monkeypatch: Any) -> None:
    """Turno vazio com ia_pausada=true no DB (pausa concorrente): nao regenera."""

    class _ConnPausada(_FakeConn):
        async def execute(self, query: str, *args: Any, **kwargs: Any) -> _FakeResult:
            if "ia_pausada" in query:
                return _FakeResult([{"ia_pausada": True}])
            return await super().execute(query, *args, **kwargs)

    pool = _FakePool(_ConnPausada())
    ctx = ContextAgente(
        db_pool=pool,  # type: ignore[arg-type]
        redis=None,  # type: ignore[arg-type]
        modelo_id=str(uuid4()),
        atendimento_id=str(uuid4()),
        cliente_id=str(uuid4()),
        turno_id=str(uuid4()),
    )
    regen = _fake_regen("nao deveria ser chamada")
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(_state_silencio(), _Runtime(ctx))  # type: ignore[arg-type]

    assert res.goto == END
    assert not regen.chamadas


# --- gatilhos da rodada 3 (servico/preco fantasma, endereco sonegado) ----------------------------


class _ConnCardapio(_FakeConn):
    """Fake com cadastro/cardapio: programas com preco (arma o scanner de preco), endereco no
    cadastro + estado Qualificado interno (arma o gatilho de endereco)."""

    async def execute(self, query: str, *args: Any, **kwargs: Any) -> _FakeResult:
        if "modelo_programas" in query:
            return _FakeResult([{"nome": "Padrão", "preco": 400, "horas": 1}])
        if "modelo_fetiches" in query:
            return _FakeResult([])
        if "localizacao_operacional" in query:
            return _FakeResult(
                [
                    {
                        "localizacao_operacional": "Cambuí",
                        "nome_local": "Hotel Sirius",
                        "endereco_formatado": "Av. Aquidabã, 130 - Centro, Campinas - SP",
                        "tipo_atendimento": "interno",
                        "estado": "Qualificado",
                    }
                ]
            )
        return await super().execute(query, *args, **kwargs)


def _runtime_cardapio() -> _Runtime:
    pool = _FakePool(_ConnCardapio())
    ctx = ContextAgente(
        db_pool=pool,  # type: ignore[arg-type]
        redis=None,  # type: ignore[arg-type]
        modelo_id=str(uuid4()),
        atendimento_id=str(uuid4()),
        cliente_id=str(uuid4()),
        turno_id=str(uuid4()),
    )
    return _Runtime(ctx)


async def test_servico_fantasma_e_gatilho_de_regen(monkeypatch: Any) -> None:
    # "Faço sim" para anal fora do cadastro (a derrota mais grave do shadow v2): regenera como
    # `servico`; a regen recusa oferecendo o que faz e a nova e despachada. Nunca handoff.
    cap = _Capturador()
    monkeypatch.setattr(mod_defesa, "abrir_handoff", cap)
    _judge_ok(monkeypatch)
    regen = _fake_regen("Anal não faço amor, mas beijo na boca e carinho sem pressa rs")
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(_state("Faço anal sim amor"), _runtime())  # type: ignore[arg-type]

    assert res.goto == END
    assert regen.chamadas and regen.chamadas[0]["gatilho"] == "servico"
    msgs = _msgs_update(res)
    assert msgs["a1"] == ""
    assert "não faço" in msgs["regen1"]
    assert not cap.chamadas


async def test_servico_persistiu_dropa_so_a_bolha(monkeypatch: Any) -> None:
    _judge_ok(monkeypatch)
    regen = _fake_regen("Oi amor 🥰\n\nFaço anal sim pode vir")
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(_state("Anal pode sim amor"), _runtime())  # type: ignore[arg-type]

    assert res.goto == END
    msgs = _msgs_update(res)
    assert msgs["regen1"] == "Oi amor 🥰"  # a promessa caiu, a saudacao sobreviveu


async def test_preco_fantasma_e_gatilho_de_regen(monkeypatch: Any) -> None:
    # Tabela = 400 1h (fake): 750 nao existe no conjunto legitimo -> regenera. (700 saiu da
    # lista de fantasmas com o ADR-0038: e o degrau 350 + um fetiche no MESMO patamar.)
    _judge_ok(monkeypatch)
    regen = _fake_regen("O encontro é 400 1h no meu local amor")
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(_state("Fica 750 1h amor"), _runtime_cardapio())  # type: ignore[arg-type]

    assert res.goto == END
    assert regen.chamadas and regen.chamadas[0]["gatilho"] == "preco"
    msgs = _msgs_update(res)
    assert "400 1h" in msgs["regen1"]


async def test_preco_da_tabela_nao_dispara(monkeypatch: Any) -> None:
    _judge_ok(monkeypatch)
    regen = _fake_regen("nao deveria ser chamada")
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(
        _state("O encontro é 400 1h no meu local amor"),
        _runtime_cardapio(),
    )  # type: ignore[arg-type]

    assert res.goto == END
    assert not regen.chamadas


async def test_pix_do_uber_prescrito_nao_dispara(monkeypatch: Any) -> None:
    # Incidente 11/08 (turno MUDO em Aguardando_confirmacao com Pix pendente): a fala PRESCRITA
    # pelo <tipos_de_encontro> ("O uber ida e volta fica {pix_valor} amor") era derrubada como
    # preco fantasma — o modelo insistia na fala certa, a regen persistia e o drop esvaziava o
    # turno. O pix_deslocamento_valor de settings agora e legitimo.
    _judge_ok(monkeypatch)
    regen = _fake_regen("nao deveria ser chamada")
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(
        _state("O uber ida e volta fica 100 amor, já te mando o pix"),
        _runtime_cardapio(),
    )  # type: ignore[arg-type]

    assert res.goto == END
    assert not regen.chamadas


async def test_preco_fantasma_regen_recebe_a_escada(monkeypatch: Any) -> None:
    # Incidente 11/08 (contraproposta de 300 sobre 400 -> rascunho "Consigo 320", que nao e
    # degrau nem piso): o guard derruba CERTO, mas a mensagem de regen agora NOMEIA os numeros
    # que a IA PODE (degrau 350 / piso 300) em vez de so apontar a tabela — familia do incidente
    # #36: proibir sem dar a fala de substituicao fazia o modelo recuar sem contraproposta.
    _judge_ok(monkeypatch)
    regen = _fake_regen("Poxa amor, 300 não consigo\n\nConsigo 350 se você vier hoje 😊")
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(
        _state("Poxa amor\n\nConsigo 320 se você vier hoje 😊"),
        _runtime_cardapio(),
    )  # type: ignore[arg-type]

    assert res.goto == END
    assert regen.chamadas and regen.chamadas[0]["gatilho"] == "preco"
    feedback = regen.chamadas[0]["feedback_gatilho"]
    assert "os seus numeros possiveis sao 350 e 300" in feedback
    # A regen que oferece o degrau (350) e legitima e sai ao cliente.
    msgs = _msgs_update(res)
    assert "350" in msgs["regen1"]


_PONTO_DE_ENCONTRO = "Hotel Sirius — Av. Aquidabã, 130 - Centro, Campinas - SP"


def _state_pedido_endereco(
    texto: str, *, no_prompt: str | None = _PONTO_DE_ENCONTRO
) -> dict[str, Any]:
    state = _state(texto)
    state["conversa_crua"] = [
        HumanMessage(content="oi", id="c1"),
        AIMessage(content="oi amor", id="c2"),
        HumanMessage(content="Manda a localização", id="c3"),
    ]
    # O gatilho `endereco` lê o CARIMBO do prepare_context (o <local_de_encontro> esteve mesmo no
    # prompt deste turno), não mais o gate re-avaliado sobre a linha pós-extração — era esse skew
    # que cobrava a entrega de um bloco ausente e produzia endereço inventado (trace 648d7f6f).
    state["local_endereco_no_prompt"] = no_prompt
    return state


async def test_endereco_pedido_sem_entrega_regenera(monkeypatch: Any) -> None:
    _judge_ok(monkeypatch)
    regen = _fake_regen("To no Hotel Sirius amor, Av. Aquidabã 130, bem no centro")
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(
        _state_pedido_endereco("É bem discreto amor, você vai gostar rs"),
        _runtime_cardapio(),
    )  # type: ignore[arg-type]

    assert res.goto == END
    assert regen.chamadas and regen.chamadas[0]["gatilho"] == "endereco"
    msgs = _msgs_update(res)
    assert "Aquidabã" in msgs["regen1"]


async def test_endereco_persistiu_segue_como_esta(monkeypatch: Any) -> None:
    # Pass-through: a rede do endereco e de melhoria, nao de bloqueio — regen que nao entregou
    # segue mesmo assim (nada e dropado, nada e zerado alem da original substituida).
    _judge_ok(monkeypatch)
    regen = _fake_regen("Fica tranquilo amor, é fácil de chegar rs")
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(
        _state_pedido_endereco("É bem discreto amor, você vai gostar rs"),
        _runtime_cardapio(),
    )  # type: ignore[arg-type]

    assert res.goto == END
    msgs = _msgs_update(res)
    assert msgs["regen1"] == "Fica tranquilo amor, é fácil de chegar rs"


async def test_endereco_ja_entregue_nao_dispara(monkeypatch: Any) -> None:
    _judge_ok(monkeypatch)
    regen = _fake_regen("nao deveria ser chamada")
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(
        _state_pedido_endereco("To no Hotel Sirius amor, Av. Aquidabã 130"),
        _runtime_cardapio(),
    )  # type: ignore[arg-type]

    assert res.goto == END
    assert not regen.chamadas


async def test_sem_pedido_de_endereco_nao_dispara(monkeypatch: Any) -> None:
    # Mesma resposta vaga, mas o cliente nao pediu a localizacao: fala legitima, segue.
    _judge_ok(monkeypatch)
    regen = _fake_regen("nao deveria ser chamada")
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(
        _state("É bem discreto amor, você vai gostar rs"),
        _runtime_cardapio(),
    )  # type: ignore[arg-type]

    assert res.goto == END
    assert not regen.chamadas


async def test_endereco_fora_do_prompt_nao_cobra_a_entrega(monkeypatch: Any) -> None:
    """P0-1 (trace 648d7f6f, agenda_local t3): o cliente escolhe "no seu local" e pede o endereco
    no MESMO turno; a extracao promove tipo_atendimento NULL->interno no meio do turno, entao o
    prompt saiu SEM o <local_de_encontro> e o guard, relendo a linha ja promovida, cobrava a
    entrega. O modelo respondeu com uma rua inexistente e a regen a reimprimiu.

    Sem carimbo no State, o gatilho nao arma — o guard nunca cobra dado que o prompt nao tinha."""
    _judge_ok(monkeypatch)
    regen = _fake_regen("nao deveria ser chamada")
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(
        _state_pedido_endereco("É bem discreto amor, você vai gostar rs", no_prompt=None),
        _runtime_cardapio(),
    )  # type: ignore[arg-type]

    assert res.goto == END
    assert not regen.chamadas


async def test_regen_do_endereco_cola_o_dado_literal(monkeypatch: Any) -> None:
    """O lembrete da regen factual leva o ENDERECO, nunca o nome da tag condicional: o rascunho
    descartado era a unica "fonte de endereco" a vista e o modelo o copiava."""
    _judge_ok(monkeypatch)
    regen = _fake_regen("To no Hotel Sirius amor, Av. Aquidabã 130")
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(
        _state_pedido_endereco("É bem discreto amor, você vai gostar rs"),
        _runtime_cardapio(),
    )  # type: ignore[arg-type]

    assert res.goto == END
    feedback = regen.chamadas[0]["feedback_gatilho"]
    assert _PONTO_DE_ENCONTRO in feedback
    assert "<local_de_encontro>" not in feedback


# --- recuperacao de turno vazio (vazio-pos-drop / mudo persistido) -------------------------------


def _fake_regen_seq(contents: list[str | None]) -> Any:
    """Fake de _regenerar com resposta POR CHAMADA (a recuperacao de vazio responde diferente)."""

    class _Regen:
        def __init__(self) -> None:
            self.chamadas: list[dict[str, Any]] = []

        async def __call__(self, *args: Any, **kwargs: Any) -> AIMessage | None:
            i = len(self.chamadas)
            self.chamadas.append(kwargs)
            content = contents[min(i, len(contents) - 1)]
            if content is None:
                return None
            return AIMessage(content=content, id=f"regen{i + 1}", usage_metadata=_USAGE)

    return _Regen()


async def test_drop_que_esvazia_recupera_pelo_trilho_do_mudo(monkeypatch: Any) -> None:
    """Regressao (shadow v3, 11/08): preco fantasma persistiu, o drop esvaziou o turno e o
    cliente ficava no vacuo (derrota automatica). Vazio-pos-drop agora ganha UMA regen extra
    pelo trilho do mudo, aceita so se a bateria inteira re-aprovar."""
    _judge_ok(monkeypatch)
    regen = _fake_regen_seq(["Sai 555 amor", "Seria hoje amor ?"])
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(_state("Fica 750 1h amor"), _runtime_cardapio())  # type: ignore[arg-type]

    assert res.goto == END
    assert [c["gatilho"] for c in regen.chamadas] == ["preco", "mudo"]
    msgs = _msgs_update(res)
    assert msgs["regen2"] == "Seria hoje amor ?"


async def test_recuperacao_que_reincide_fecha_mudo(monkeypatch: Any) -> None:
    """A recuperacao NAO e passagem livre: reincidiu (preco invalido de novo), fecha mudo."""
    _judge_ok(monkeypatch)
    regen = _fake_regen_seq(["Sai 555 amor", "Consigo por 555 amor"])
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(_state("Fica 750 1h amor"), _runtime_cardapio())  # type: ignore[arg-type]

    assert res.goto == END
    assert [c["gatilho"] for c in regen.chamadas] == ["preco", "mudo"]
    msgs = _msgs_update(res)
    assert all(not str(c).strip() for c in msgs.values())


async def test_mudo_persistido_ganha_uma_recuperacao(monkeypatch: Any) -> None:
    """Silencio do modelo cuja regen devolve vazio de novo: uma ultima tentativa antes do
    silencio final (a falha e estocastica — o mesmo ponto re-rodado respondia normal)."""
    _judge_ok(monkeypatch)
    regen = _fake_regen_seq(["", "600 1h no meu local amor 😊"])
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(_state_silencio(), _runtime())  # type: ignore[arg-type]

    assert res.goto == END
    assert [c["gatilho"] for c in regen.chamadas] == ["mudo", "mudo"]
    msgs = _msgs_update(res)
    assert msgs["regen2"] == "600 1h no meu local amor 😊"


# --- rodada 4: pedagio (empurrao vazio com pergunta pendente) -------------------------------


def _state_pergunta_pendente(texto: str) -> dict[str, Any]:
    state = _state(texto)
    state["conversa_crua"] = [
        AIMessage(content="oi amor", id="c1"),
        HumanMessage(content="Você atende no seu local?", id="c2"),
    ]
    return state


async def test_pedagio_com_pergunta_pendente_regenera(monkeypatch: Any) -> None:
    _judge_ok(monkeypatch)
    regen = _fake_regen("Atendo sim amor, no meu local\n\nSeria hoje ?")
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(
        _state_pergunta_pendente("Poxa amor\n\nSeria hoje ?"),
        _runtime_cardapio(),
    )  # type: ignore[arg-type]

    assert res.goto == END
    assert regen.chamadas and regen.chamadas[0]["gatilho"] == "pedagio"
    msgs = _msgs_update(res)
    assert "Atendo sim" in msgs["regen1"]


async def test_pedagio_persistiu_segue_como_esta(monkeypatch: Any) -> None:
    # Mesma rede de melhoria do endereco: regen que continuou pedagio segue (pass-through).
    _judge_ok(monkeypatch)
    regen = _fake_regen("Seria que horas ?")
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(
        _state_pergunta_pendente("Seria hoje ?"),
        _runtime_cardapio(),
    )  # type: ignore[arg-type]

    assert res.goto == END
    msgs = _msgs_update(res)
    assert msgs["regen1"] == "Seria que horas ?"


async def test_empurrao_sem_pergunta_pendente_nao_dispara(monkeypatch: Any) -> None:
    # Anti-FP: despedida/fala sem pergunta no burst — empurrao-so pode ser a jogada; nao arma.
    _judge_ok(monkeypatch)
    regen = _fake_regen("nao deveria ser chamada")
    monkeypatch.setattr(mod, "_regenerar", regen)

    state = _state("Seria hoje ?")
    state["conversa_crua"] = [
        AIMessage(content="oi amor", id="c1"),
        HumanMessage(content="boa noite, fica com Deus", id="c2"),
    ]
    res = await mod.output_guard(state, _runtime_cardapio())  # type: ignore[arg-type]

    assert res.goto == END
    assert not regen.chamadas


async def test_resposta_com_conteudo_e_empurrao_nao_dispara(monkeypatch: Any) -> None:
    _judge_ok(monkeypatch)
    regen = _fake_regen("nao deveria ser chamada")
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(
        _state_pergunta_pendente("Atendo sim amor\n\nSeria hoje ?"),
        _runtime_cardapio(),
    )  # type: ignore[arg-type]

    assert res.goto == END
    assert not regen.chamadas


# --- rodada 4: saudacao espelhada ------------------------------------------------------------


async def test_saudacao_conflitante_regenera(monkeypatch: Any) -> None:
    _judge_ok(monkeypatch)
    regen = _fake_regen("Boa tarde amor 🥰")
    monkeypatch.setattr(mod, "_regenerar", regen)

    state = _state("Boa noite amor 🥰")
    state["conversa_crua"] = [
        AIMessage(content="oi", id="c1"),
        HumanMessage(content="Boa tarde, tudo bem?", id="c2"),
    ]
    res = await mod.output_guard(state, _runtime_cardapio())  # type: ignore[arg-type]

    assert res.goto == END
    assert regen.chamadas and regen.chamadas[0]["gatilho"] == "saudacao"
    msgs = _msgs_update(res)
    assert "Boa tarde" in msgs["regen1"]


async def test_saudacao_sem_referencia_do_cliente_nao_dispara(monkeypatch: Any) -> None:
    # "Boa noite" legitimo a noite: sem saudacao DELE no burst nao ha conflito a julgar.
    _judge_ok(monkeypatch)
    regen = _fake_regen("nao deveria ser chamada")
    monkeypatch.setattr(mod, "_regenerar", regen)

    state = _state("Boa noite amor 🥰")
    state["conversa_crua"] = [
        AIMessage(content="oi", id="c1"),
        HumanMessage(content="oi gata", id="c2"),
    ]
    res = await mod.output_guard(state, _runtime_cardapio())  # type: ignore[arg-type]

    assert res.goto == END
    assert not regen.chamadas


async def test_regenerar_nao_manda_tool_orfao_ao_provider(monkeypatch: Any) -> None:
    """Regressao (12/08, medido ao vivo): a janela da regen nao pode conter `role=tool` sem o
    `tool_calls` que o abre — o provider recusa o request inteiro (HTTP 400) e a regen devolve
    None, jogando o gate no fallback (handoff) exatamente no turno do fechamento.

    O state reproduzido e o real: o `post_process` ZEROU as falas do turno por causa da escalada
    (a AIMessage forcada perde os `tool_calls`), o `ToolMessage` da extracao ficou no state e a
    canned entrou depois dele. O corte antigo (pela 1a mensagem do turno) deixava o par vazar."""
    resp = AIMessage(content="nova fala", id="r1", usage_metadata=_USAGE)
    chat = _FakeChat(resp)
    mod_llm = importlib.import_module("barra.core.llm")
    monkeypatch.setattr(mod_llm, "criar_chat_deepseek", lambda *a, **kw: chat)

    messages: list[BaseMessage] = [
        HumanMessage(content="oi, quanto?", id="h0"),
        AIMessage(content="400 1h", id="a0"),
        HumanMessage(content="entao fechamos? me passa o endereco", id="h1"),
        AIMessage(content="", id="a1", usage_metadata=_USAGE),  # fala do turno, zerada
        AIMessage(content="", id="forcado", usage_metadata=_USAGE),  # forcada SEM tool_calls
        ToolMessage(content="Horario ja reservado.", tool_call_id="call_1", id="tm1"),
        AIMessage(content="Só um minutinho amor", id="canned", usage_metadata=_USAGE),
    ]

    out = await mod._regenerar(
        messages, rascunho="rascunho", gatilho="endereco", settings=get_settings()
    )

    assert out is resp
    janela = chat.janelas[0]
    assert not any(isinstance(m, ToolMessage) for m in janela)
    assert [getattr(m, "id", None) for m in janela] == ["h0", "a0", "h1"]


def test_sem_tool_orfao_preserva_o_par_completo() -> None:
    """O saneamento so tira o ToolMessage DESEMPARELHADO: o par ReAct legitimo continua inteiro."""
    par: list[BaseMessage] = [
        AIMessage(content="", id="a0", tool_calls=[{"name": "t", "args": {}, "id": "c1"}]),
        ToolMessage(content="ok", tool_call_id="c1", id="tm0"),
        ToolMessage(content="orfao", tool_call_id="c9", id="tm9"),
    ]
    assert [m.id for m in mod._sem_tool_orfao(par)] == ["a0", "tm0"]


async def test_canned_de_escalada_nao_arma_gatilho_de_melhoria(monkeypatch: Any) -> None:
    """Turno que ESCALOU (guarda de dominio) responde com a bolha de espera curada. Se o cliente
    tinha pedido o endereco, o gatilho `endereco` armava sobre ela e a regen gastava um turno de
    LLM para, no caminho feliz, TROCAR a espera por uma fala com o endereco — furando a escalada
    recem-aberta, com a IA ja pausada (medido em 3 de 20 conversas, 12/08)."""
    from barra.agente._canned import ESPERA_ESCALADA_CANNED

    regen = _fake_regen("To na rua X, 421")
    monkeypatch.setattr(mod, "_regenerar", regen)

    canned = next(iter(ESPERA_ESCALADA_CANNED))
    res = await mod.output_guard(_state(canned), _runtime())  # type: ignore[arg-type]

    assert res.goto == END
    assert not regen.chamadas  # nem tentou regenerar a decisao do sistema


async def test_mute_por_erro_de_tool_nao_arma_o_gatilho_mudo(monkeypatch: Any) -> None:
    """O mute do `extrair` e uma DECISAO, nao um turno a recuperar.

    Quando a extracao erra no guard de dominio e a reoferta ja foi gasta, o `extrair` fecha o turno
    mudo de proposito (silencio > reserva fantasma) e carimba `_mute_por_erro_de_tool`. Esse turno
    tem a MESMA assinatura de um modelo que respondeu vazio, e sem o carimbo o guard armava `mudo`
    e regenerava — mas a janela da regen corta o ToolMessage do erro, entao o modelo respondia
    "Confirmado amor", justamente a reserva fantasma que o mute impedia (trace 71c7196e, 12/08:
    a auto-reoferta tinha ACERTADO a cotacao e a regen a substituiu pela confirmacao proibida)."""
    regen = _fake_regen("Confirmado amor\n\nMe passa seu nome ?")
    monkeypatch.setattr(mod, "_regenerar", regen)

    state = {**_state_silencio(), "_mute_por_erro_de_tool": True}
    res = await mod.output_guard(state, _runtime())  # type: ignore[arg-type]

    assert res.goto == END
    assert not regen.chamadas  # o silencio do mute e preservado
    assert not _msgs_update(res)


async def test_sem_o_carimbo_o_silencio_segue_regenerando(monkeypatch: Any) -> None:
    """Contraprova do teste acima: o gatilho `mudo` continua valendo p/ o modelo que so ficou
    vazio (4,5% dos pontos do shadow) — o carimbo restringe, nao desliga."""
    _judge_ok(monkeypatch)
    regen = _fake_regen("400 1h no meu local amor")
    monkeypatch.setattr(mod, "_regenerar", regen)

    state = {**_state_silencio(), "_mute_por_erro_de_tool": False}
    res = await mod.output_guard(state, _runtime())  # type: ignore[arg-type]

    assert res.goto == END
    assert regen.chamadas and regen.chamadas[0]["gatilho"] == "mudo"


def test_dobradinha_nao_flagra_segunda_pergunta_sem_numero() -> None:
    """A pergunta de logistica depois do pedido de fechamento e o turno BEM conduzido.

    `_dobradinha_de_fechamento` casava vacuamente quando a bolha nova nao tinha digito
    (`not numeros or ...`), e como `pode ser`/`te espero`/`confirma` estao na regex de fechamento,
    qualquer segunda pergunta de lugar, logistica ou flerte virava "dobradinha" e era dropada."""
    for segunda in (
        "Pode ser aqui no meu apartamento ?",
        "Pode ser aqui no meu apê ou prefere hotel ?",
        "Posso te esperar de lingerie vermelha ?",
        "Me confirma que voce vem mesmo ?",
    ):
        texto = f"Consigo às 21h, fecha ?\n\n{segunda}"
        assert mod.bolhas_repetidas(texto, []) == [], segunda


def test_dobradinha_ainda_flagra_o_mesmo_sim_duas_vezes() -> None:
    """Contraprova: pedir DUAS vezes o mesmo sim (mesmos numeros) segue sendo repeticao de ato."""
    texto = "Podemos combinar 21h ?\n\nFechou 21h entao amor ?"
    assert mod.bolhas_repetidas(texto, []) == ["Fechou 21h entao amor ?"]


def test_confirmacao_apos_aceite_do_cliente_nao_e_eco() -> None:
    """Depois do "fechou" dele, confirmar reusando a abertura da oferta e conduta certa.

    `_mesma_abertura` e cego ao que o CLIENTE disse entre os dois turnos: mesmos numeros + prefixo
    comum bastavam. Sendo a unica bolha do turno, o drop zerava o texto e o turno saia MUDO no
    instante do fechamento."""
    historicas = ["Consigo às 17h, fecha ?"]
    nova = "Consigo às 17h então, te espero 🥰"

    assert mod.bolhas_repetidas(nova, historicas) == [nova]  # sem o aceite, segue flagrando
    assert mod.bolhas_repetidas(nova, historicas, houve_aceite=True) == []


def test_aceite_nao_libera_o_reenvio_literal() -> None:
    """O aceite desliga so o ramo do eco de abertura; repetir a bolha IGUAL continua sendo rastro."""
    historicas = ["Consigo às 17h, fecha ?"]
    assert mod.bolhas_repetidas("Consigo às 17h, fecha ?", historicas, houve_aceite=True) == [
        "Consigo às 17h, fecha ?"
    ]


def test_feedback_de_repeticao_cola_a_bolha_e_nomeia_a_saida() -> None:
    """O gatilho `repeticao` entrou na família do feedback enriquecido em 12/08.

    A razão estática só dizia "você repetiu", e o modelo obedecia REFORMULANDO a mesma frase:
    "Consigo às 17h, fecha ?" virou "Consigo às 17h, seria bom pra você ?" na regen (trace
    61f4044c). Como o piso fuzzy veta as duas bolhas que carregam os mesmos números, a
    reformulação reincidiu, a 2a tentativa acabou e o fallback dropou tudo -- turno MUDO. Trocar
    papagaio por silêncio é piorar.
    """
    from barra.agente.nos.output_guard import _feedback_repeticao

    msg = _feedback_repeticao(["Consigo às 17h, fecha ?"])

    assert "Consigo às 17h, fecha ?" in msg, "o modelo tem de ver O QUE não passou, não um rótulo"
    assert "outras palavras" in msg, "a FUNÇÃO volta com outras palavras; a forma não volta"
    assert "FALTA" in msg, "a saída tem de ser nomeada: avance pelo que ainda falta"


def test_feedback_de_repeticao_sem_bolha_cai_na_razao_estatica() -> None:
    from barra.agente.nos.output_guard import _FEEDBACK_GATILHO, _feedback_repeticao

    assert _feedback_repeticao([]) == _FEEDBACK_GATILHO["repeticao"]
    assert _feedback_repeticao(["   "]) == _FEEDBACK_GATILHO["repeticao"]


# --- feedback de repetição: a FORMA não volta, a FUNÇÃO sim (trace 13/08, "e por 280?") ----------
#
# Turno certo pelo domínio (defesa do valor + empurrão de hora na mesma mensagem, o que
# `regras.md.j2:160` cobra) virou turno jogado fora: a bolha do empurrão era verbatim a de um turno
# anterior -> gatilho `repeticao` -> a regen recebeu um "não repita" que não dizia O QUE não repetir
# -> repetiu -> o fallback dropou a bolha e sobrou a defesa solta ("Poxa amor / Esse é o meu valor").
_DEFESA = "Poxa amor, esse é o meu valor rs"
_EMPURRAO_REPETIDO = "Consigo às 23h, fecha ?"
_EMPURRAO_REFORMULADO = "Te espero hoje às 23h então, pode ser ?"


def test_feedback_de_repeticao_cita_as_bolhas_e_manda_manter_a_funcao() -> None:
    """(a) O feedback cita a(s) bolha(s) literalmente e prescreve a INTENÇÃO: função devida."""
    msg = mod._feedback_repeticao([_EMPURRAO_REPETIDO])

    assert f'"{_EMPURRAO_REPETIDO}"' in msg, "a bolha vetada vai colada, palavra por palavra"
    assert "palavra por palavra" in msg
    assert "FUNCAO" in msg, "a função da bolha continua devida -- é o que faltava ser dito"
    assert "proximo passo tem de" in msg, "o próximo passo tem de reaparecer, dito de outro jeito"
    assert "trocar so o final" in msg, "reformular só a cauda reincide no `_mesma_abertura`"
    assert "Turno vazio" in msg, "silêncio segue vetado (a pior saída medida no shadow)"
    # Intenção, nunca fala pronta: o feedback não entrega frase de persona para copiar.
    assert "Consigo às" not in msg.replace(_EMPURRAO_REPETIDO, "")


def test_feedback_de_repeticao_cita_todas_as_ofensoras() -> None:
    """Com duas ofensoras o modelo via só a primeira e reincidia na outra."""
    msg = mod._feedback_repeticao([_EMPURRAO_REPETIDO, "A 2h fica 700 amor"])

    assert _EMPURRAO_REPETIDO in msg and "A 2h fica 700 amor" in msg


def test_feedback_novo_nao_vaza_para_os_outros_gatilhos() -> None:
    """A conduta da FUNÇÃO é da repetição e só dela (gatilho genérico desfaz decisão de outro nó)."""
    outros = [v for k, v in mod._FEEDBACK_GATILHO.items() if k != "repeticao"]
    assert all("FUNCAO" not in v for v in outros)
    assert "FUNCAO" not in mod._FEEDBACK_GATILHO["repeticao"], "a razão estática segue enxuta"


async def test_regen_reformulada_mantem_defesa_e_empurrao(monkeypatch: Any) -> None:
    """(b) Regen que muda a FORMA e mantém a FUNÇÃO passa: o turno sai com defesa + empurrão."""
    cap = _Capturador()
    monkeypatch.setattr(mod_defesa, "abrir_handoff", cap)
    _judge_ok(monkeypatch)
    nova = f"{_DEFESA}\n\n{_EMPURRAO_REFORMULADO}"
    regen = _fake_regen(nova)
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(  # type: ignore[arg-type]
        _state(f"{_DEFESA}\n\n{_EMPURRAO_REPETIDO}", historico=[_EMPURRAO_REPETIDO]),
        _runtime(),
    )

    chamada = regen.chamadas[0]
    assert chamada["gatilho"] == "repeticao"
    assert _EMPURRAO_REPETIDO in chamada["feedback_gatilho"], "a bolha vetada vai citada na regen"
    msgs = _msgs_update(res)
    assert msgs["a1"] == ""
    assert msgs["regen1"] == nova, "a bolha reformulada sobrevive ao re-scan"
    assert not cap.chamadas


async def test_regen_reincidente_ainda_dropa_a_bolha(monkeypatch: Any) -> None:
    """(c) A POLÍTICA não mudou: reincidiu igual -> drop da ofensora (silêncio > papagaio)."""
    _judge_ok(monkeypatch)
    regen = _fake_regen(f"{_DEFESA}\n\n{_EMPURRAO_REPETIDO}")  # idêntica de novo
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(  # type: ignore[arg-type]
        _state(f"{_DEFESA}\n\n{_EMPURRAO_REPETIDO}", historico=[_EMPURRAO_REPETIDO]),
        _runtime(),
    )

    msgs = _msgs_update(res)
    assert msgs["a1"] == ""
    assert msgs["regen1"] == _DEFESA, "o fallback segue dropando a bolha repetida"


async def test_drop_por_repeticao_ainda_dropa_o_preco_fantasma_da_outra_bolha(
    monkeypatch: Any,
) -> None:
    """Regressao: o fallback de drop saia por `break` direto p/ o judge, sem re-escanear.

    Os detectores abaixo do gatilho vencedor sao curto-circuitados no scan (cada um so roda com os
    anteriores vazios). Com uma bolha repetida armando `repeticao`, `bolhas_preco_fantasma` nem era
    calculado; o fallback dropava so a repetida e mandava o resto — e o judge que vem depois julga
    AUP, nao preco fora de cardapio. Bastava a regen nao limpar (provider fora, como aqui) para o
    preco inventado chegar ao cliente."""
    _judge_ok(monkeypatch)
    monkeypatch.setattr(mod, "_regenerar", _fake_regen(None))  # regen indisponivel

    historicas = ["Consigo às 21h, fecha ?"]
    texto = "Consigo às 21h, fecha ?\n\nFica 750 1h amor"
    res = await mod.output_guard(_state(texto, historicas), _runtime_cardapio())  # type: ignore[arg-type]

    assert res.goto == END
    enviado = "".join(_msgs_update(res).values())
    assert "750" not in enviado  # o preco fantasma nao escapa pelo trilho da repeticao
    assert "Consigo às 21h" not in enviado  # a repetida tambem cai, como antes


async def test_recuperacao_acumula_os_tokens_da_regen_que_ela_substitui(monkeypatch: Any) -> None:
    """Duas chamadas de LLM no turno tem de contar como duas no custo.

    A regen da t1 nunca entra no State: quando `_recuperar_vazio` a substitui, o objeto e trocado e
    os tokens dela sumiam da soma por turno do coordenador (que percorre `usage_metadata` das
    mensagens do State). O turno gastava duas chamadas e `atendimentos.custo_ia_brl` registrava
    uma. Mesmo cenario do `test_drop_que_esvazia_recupera_pelo_trilho_do_mudo`, olhando o custo."""
    _judge_ok(monkeypatch)
    regen = _fake_regen_seq(["Sai 555 amor", "Seria hoje amor ?"])
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(_state("Fica 750 1h amor"), _runtime_cardapio())  # type: ignore[arg-type]

    assert [c["gatilho"] for c in regen.chamadas] == ["preco", "mudo"]
    (final,) = [m for m in (res.update or {})["messages"] if str(m.content).strip()]
    assert final.usage_metadata is not None
    # as DUAS regens contam: a descartada (preco) + a que ficou (mudo).
    assert final.usage_metadata["total_tokens"] == _USAGE["total_tokens"] * 2


def test_hora_nova_na_mesma_forma_de_pergunta_nao_e_papagaio() -> None:
    """Trocar o horario ofertado e informacao NOVA, mesmo na forma de pergunta ja usada.

    Regressao do turno mudo do roteiro `escada` (12/08, trace 273f46ca): o cliente aceitou os 300,
    o gatilho `repeticao` armou por outra via e a regen ofertou 17h no lugar de 18h. "Consigo as
    18h, fecha ?" x "Consigo as 17h, fecha ?" da ratio 0,95, e o piso de PERGUNTA (9) as flagrava
    como papagaio -- a 2a tentativa acabou ali e o cliente que acabara de fechar nao recebeu nada.

    O ramo de mesmos-numeros ja excluia numero diferente ("400 1h" x "700 2h"); o ramo de pergunta,
    acrescentado depois, nao herdou a regra. Papagaio de verdade (a MESMA hora reformulada) e a
    pergunta repetida SEM numero continuam caindo -- e o que os outros dois casos abaixo fixam."""
    historicas = ["Consigo às 18h, fecha ?", "Qual seu nome ?"]

    assert mod.bolhas_repetidas("Consigo às 17h, fecha ?", historicas) == []
    assert mod.bolhas_repetidas("Consigo às 18h, fecha mesmo ?", historicas) == [
        "Consigo às 18h, fecha mesmo ?"
    ]
    assert mod.bolhas_repetidas("E qual seu nome ?", historicas) == ["E qual seu nome ?"]

    # ACRESCENTAR a hora tambem e dado novo: a guarda compara as listas inteiras, e nao "as duas
    # tem numero e diferem" -- senao a bolha que finalmente CRAVA o horario cairia no fechamento.
    vaga = ["Consigo te encaixar hoje a noite, fecha ?"]
    assert mod.bolhas_repetidas("Consigo te encaixar hoje a noite as 21h, fecha ?", vaga) == []


# --- rede do vazio: regen vazia 2x nao pode emudecer um turno com bolhas boas (13/08) ------------


async def test_regen_vazia_2x_preserva_bolhas_boas_do_original(monkeypatch: Any) -> None:
    """Mecanismo do duvida_das_fotos t4 (campanha 13/08): o papagaio flagra UMA bolha do turno
    ("Sou eu mesma..."), a regen da t1 devolve VAZIO e a recuperacao do mudo tambem — antes o
    turno fechava MUDO, jogando fora a bolha boa nao-flagrada. A rede deterministica resgata o
    original menos a ofensora."""
    _judge_ok(monkeypatch)
    regen = _fake_regen_seq(["", ""])
    monkeypatch.setattr(mod, "_regenerar", regen)

    fresca = "consegue chegar aqui pra que horas amor?"
    res = await mod.output_guard(  # type: ignore[arg-type]
        _state(f"{_BOLHA_LONGA}\n\n{fresca}", historico=[_BOLHA_LONGA]), _runtime()
    )

    assert res.goto == END
    assert [c["gatilho"] for c in regen.chamadas] == ["repeticao", "mudo"]
    msgs = _msgs_update(res)
    assert msgs["a1"] == fresca  # a bolha boa sobrevive na PROPRIA mensagem original
    assert msgs["regen1"] == ""  # a regen vazia sai zerada (usage preservado, sem fala)


async def test_regen_reincidiu_e_drop_esvaziou_preserva_bolhas_boas(monkeypatch: Any) -> None:
    """Variante: a regen da t1 devolve a MESMA bolha repetida (reincide), o drop da t2 esvazia o
    texto da regen e a recuperacao devolve vazio — o fallback nao pode perder o original."""
    _judge_ok(monkeypatch)
    regen = _fake_regen_seq([_BOLHA_LONGA, ""])
    monkeypatch.setattr(mod, "_regenerar", regen)

    fresca = "consegue chegar aqui pra que horas amor?"
    res = await mod.output_guard(  # type: ignore[arg-type]
        _state(f"{_BOLHA_LONGA}\n\n{fresca}", historico=[_BOLHA_LONGA]), _runtime()
    )

    assert res.goto == END
    assert [c["gatilho"] for c in regen.chamadas] == ["repeticao", "mudo"]
    msgs = _msgs_update(res)
    assert msgs["a1"] == fresca
    assert msgs["regen1"] == ""


async def test_todas_flagradas_e_regen_vazia_2x_fecha_mudo(monkeypatch: Any) -> None:
    """TODAS as bolhas do original flagradas + regen vazia 2x: nao ha o que resgatar — o mudo
    fica (silencio > papagaio; nao existe canned generica de venda no pool curado)."""
    _judge_ok(monkeypatch)
    regen = _fake_regen_seq(["", ""])
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(  # type: ignore[arg-type]
        _state(_BOLHA_LONGA, historico=[_BOLHA_LONGA]), _runtime()
    )

    assert res.goto == END
    assert [c["gatilho"] for c in regen.chamadas] == ["repeticao", "mudo"]
    msgs = _msgs_update(res)
    assert all(not str(c).strip() for c in msgs.values())


def _state_pos_escalada(texto: str, historico: list[str] | None = None) -> dict[str, Any]:
    """Turno que chamou `escalar` no MEIO: a ToolMessage de sucesso e o rastro deterministico da
    escalada aberta (ToolMessages nunca sao reescritas e as historicas nao voltam ao contexto), e a
    bolha pre-tool foi PRESERVADA pelo corte do post_process (post_process.py:76-86)."""
    msgs: list[BaseMessage] = list(_state(texto, historico)["messages"])
    msgs.insert(
        len(msgs) - 1,
        ToolMessage(
            content=f"{ESCALADA_ABERTA_PREFIXO}Fernando. Próxima fala virá quando ele responder.",
            tool_call_id="tc1",
            id="t1",
        ),
    )
    return {"messages": msgs}


async def test_pos_escalada_rede_do_vazio_nao_ressuscita_o_turno(monkeypatch: Any) -> None:
    """Turno com escalada ABERTA (rastro `ESCALADA_ABERTA_PREFIXO` na ToolMessage): a rede do
    vazio tem de ficar de fora por precedencia — ressuscitar fala de venda depois da escalada e o
    bug de eb02:21123135741957 t12. O turno fecha mudo, como antes.

    O gatilho aqui e de SEGURANCA (`preco` fantasma): esse trilho continua valendo com escalada
    aberta — so os de QUALIDADE ficam de fora (ver os testes do c10, logo abaixo)."""
    _judge_ok(monkeypatch)
    regen = _fake_regen_seq(["", ""])
    monkeypatch.setattr(mod, "_regenerar", regen)

    fresca = "consegue chegar aqui pra que horas amor?"
    # Tabela do fake = 400 1h; 750 e fantasma.
    estado = _state_pos_escalada(f"Fica 750 1h amor\n\n{fresca}")
    res = await mod.output_guard(estado, _runtime_cardapio())  # type: ignore[arg-type]

    assert res.goto == END
    assert regen.chamadas and regen.chamadas[0]["gatilho"] == "preco"  # seguranca ainda age
    msgs = _msgs_update(res)
    assert all(not str(c).strip() for c in msgs.values())


# --- escalada aberta: gatilho de QUALIDADE nao arma, o de SEGURANCA sim (c10, campanha 13/08) ----


async def test_pos_escalada_repeticao_nao_roda_o_loop_de_regen(monkeypatch: Any) -> None:
    """c10 `encaixe_apos_o_atual`: a IA chamou `escalar` no meio do turno e o post_process
    PRESERVOU a bolha pre-tool (por design — ela e a fala que acompanha a escalada). O guard lia
    essa bolha como papagaio da cotacao ja dita e rodava a regen na tentativa 1: fala de VENDA
    reescrita depois de a escalada estar aberta, e o dado bom ("19:30") perdido no caminho.
    Mesma familia de `silencio_modelo` e da rede do vazio, entrando por porta nova."""
    _judge_ok(monkeypatch)
    regen = _fake_regen("Me confirma o horario amor ?")
    monkeypatch.setattr(mod, "_regenerar", regen)

    bolha = "Consigo te encaixar às 19:30 amor, fecha ?"
    res = await mod.output_guard(  # type: ignore[arg-type]
        _state_pos_escalada(bolha, historico=[bolha]), _runtime()
    )

    assert res.goto == END
    assert not regen.chamadas  # o loop de regen nem comeca
    assert not _msgs_update(res)  # nada zerado/dropado: a bolha do corte sai como esta


async def test_pos_escalada_sonda_tambem_nao_arma(monkeypatch: Any) -> None:
    """A porta e a CLASSE, nao o gatilho: `sonda` (estilo, como `pedagio`/`saudacao`) tambem fica
    de fora — `promessa_midia` e `despedida` ja ficavam."""
    _judge_ok(monkeypatch)
    regen = _fake_regen("Tudo bem sim amor 🥰")
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(  # type: ignore[arg-type]
        _state_pos_escalada("Tudo bem sim amor 🥰\n\nO que você procura ?"), _runtime()
    )

    assert res.goto == END
    assert not regen.chamadas
    assert not _msgs_update(res)


async def test_pos_escalada_saudacao_conflitante_tambem_nao_arma(monkeypatch: Any) -> None:
    """Terceiro da classe (o quarto, `pedagio`, entra pelo mesmo `not escalada_no_turno`): espelhar
    o periodo do cliente e melhoria de estilo — nao vale um turno de LLM depois da escalada."""
    _judge_ok(monkeypatch)
    regen = _fake_regen("Boa tarde amor 🥰")
    monkeypatch.setattr(mod, "_regenerar", regen)

    state = _state_pos_escalada("Boa noite amor 🥰")
    state["conversa_crua"] = [
        AIMessage(content="oi", id="c1"),
        HumanMessage(content="Boa tarde, tudo bem?", id="c2"),
    ]
    res = await mod.output_guard(state, _runtime_cardapio())  # type: ignore[arg-type]

    assert res.goto == END
    assert not regen.chamadas


async def test_pos_escalada_vazio_por_seguranca_nao_ganha_recuperacao(monkeypatch: Any) -> None:
    """Ultima porta da familia: gatilho de SEGURANCA (`preco` fantasma) esvazia o turno e o trilho
    do vazio chamava `_recuperar_vazio` — UMA regen extra que, pos-escalada, ressuscita fala de
    venda por cima da decisao de outro no (a rede deterministica logo abaixo ja se isentava, mas
    ela so roda DEPOIS). Com escalada aberta o turno fecha MUDO, como o topo do modulo declara."""
    _judge_ok(monkeypatch)
    # 1a chamada: regen indisponivel (cai no fallback de drop, que esvazia o turno). 2a: seria a
    # recuperacao, com texto que passa a bateria inteira — e justamente ela que nao pode sair.
    regen = _fake_regen_seq([None, "400 1h no meu local amor"])
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(  # type: ignore[arg-type]
        _state_pos_escalada("Fica 750 1h amor"), _runtime_cardapio()
    )

    assert res.goto == END
    assert [c["gatilho"] for c in regen.chamadas] == ["preco"]  # nenhuma regen extra de `mudo`
    msgs = _msgs_update(res)
    assert msgs and all(not str(c).strip() for c in msgs.values())  # turno mudo


async def test_sem_escalada_vazio_ainda_e_recuperado(monkeypatch: Any) -> None:
    """Contraprova: sem o carimbo da escalada, o vazio TOTAL continua ganhando a recuperacao — o
    cliente no vacuo segue sendo a pior saida medida no shadow."""
    _judge_ok(monkeypatch)
    regen = _fake_regen_seq([None, "400 1h no meu local amor"])
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(_state("Fica 750 1h amor"), _runtime_cardapio())  # type: ignore[arg-type]

    assert res.goto == END
    assert [c["gatilho"] for c in regen.chamadas] == ["preco", "mudo"]
    assert _msgs_update(res)["regen2"] == "400 1h no meu local amor"


async def test_pos_escalada_leak_ainda_e_barrado(monkeypatch: Any) -> None:
    """Contraprova de SEGURANCA: vazamento nao vira excecao por haver escalada aberta. O turno
    continua bloqueado + handoff, exatamente como sem escalada."""
    cap = _Capturador()
    monkeypatch.setattr(mod_defesa, "abrir_handoff", cap)
    monkeypatch.setattr(mod, "_regenerar", _fake_regen(None))  # regen indisponivel -> fallback

    res = await mod.output_guard(_state_pos_escalada("sou uma IA amor"), _runtime())  # type: ignore[arg-type]

    assert res.goto == END
    assert len(cap.chamadas) == 1  # handoff aberto
    msgs = _msgs_update(res)
    assert all(not str(c).strip() for c in msgs.values())  # nada sai ao cliente


async def test_sem_escalada_repeticao_segue_regenerando(monkeypatch: Any) -> None:
    """Contraprova do c10: sem o rastro da escalada, a repeticao continua no trilho de hoje — a
    isencao restringe pelo carimbo, nao desliga o detector."""
    _judge_ok(monkeypatch)
    regen = _fake_regen("Me confirma o horario amor ?")
    monkeypatch.setattr(mod, "_regenerar", regen)

    bolha = "Consigo te encaixar às 19:30 amor, fecha ?"
    res = await mod.output_guard(_state(bolha, historico=[bolha]), _runtime())  # type: ignore[arg-type]

    assert res.goto == END
    assert regen.chamadas and regen.chamadas[0]["gatilho"] == "repeticao"
    assert _msgs_update(res)["regen1"] == "Me confirma o horario amor ?"
