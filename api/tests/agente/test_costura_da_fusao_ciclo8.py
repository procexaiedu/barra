"""Ciclo 8 — a COSTURA da fusao: fundir bolhas apaga a fronteira de FRASE que o guard usa.

O ciclo 7 consertou metade. A fusao deterministica do book (`post_process._concatenar_bolhas`) so
intercala ". " quando a bolha da ESQUERDA termina em alfanumerico; as bolhas da persona quase
nunca terminam em pontuacao (regra de voz) e muitas terminam em EMOJI — ali o separador vira
espaco puro e a fronteira de frase SOME.

Cadeia real medida (turno de midia, dois passes do LLM):
    passe 1: "Sou eu mesma amor 🥰" + tools de midia
    passe 2: 'Já escrevi a bolha "Sou eu mesma amor 🥰" neste turno — vou enviá-la junto com a mídia.'
    fusao  : as duas viram UMA bolha, separadas por espaco
    guard  : `_RE_FIM_DE_FRASE` nao acha fronteira -> `len(frases) < 2` -> resgate "" -> TURNO
             ZERADO -> guard_regen -> 2 bolhas sem o enquadramento.

Duas correcoes, uma por superficie ("corrigir uma e deixar a outra e nao corrigir"):
  1. `output_guard._COSTURA_DE_BOLHA`: emoji + espaco + maiuscula tambem e fim de frase, nos
     QUATRO sitios que julgam por frase (a cirurgia de narracao e os tres detectores de midia).
     So o split muda — o texto entregue ao cliente continua byte-a-byte o do modelo.
  2. `post_process._fundir_bolhas_do_book`: o Estagio 0 do guard roda por bolha ANTES da fusao,
     entao bolha que o guard descartaria inteira nunca entra na fundida. E o invariante
     distributivo escrito no codigo: fundir(guard(a), guard(b)), nao guard(fundir(a, b)).

O que NAO se fez, e por que: emendar o texto no post_process (inserir ". " depois do emoji). O
texto fundido vai LITERAL ao cliente — `workers/_chunking` so re-parte por `\\n\\n` — entao o ponto
apareceria dentro da bolha no WhatsApp, contra a regra de voz. Ver
`test_fusao_de_duas_falas_boas_nao_vaza_pontuacao_na_saida`.

Offline: sem DB, sem LLM, sem credito.
"""

import importlib
import re
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from barra.agente._texto_turno import extrair_texto_do_turno, mensagens_do_turno
from barra.agente.contexto import ContextAgente
from barra.workers._chunking import chunk_texto

# nos/__init__ reexporta as FUNCOES post_process/output_guard, sombreando os submodulos
# (memoria "nos/__init__ sombreia submodulo").
pp = importlib.import_module("barra.agente.nos.post_process")
g = importlib.import_module("barra.agente.nos.output_guard")

_USAGE = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}
_RE_BOLHAS = re.compile(r"\n\s*\n")

# --- as falas do caso real -------------------------------------------------------------------

_BOA = "Sou eu mesma amor 🥰"
_NARRACAO_PASSE2 = (
    'Já escrevi a bolha "Sou eu mesma amor 🥰" neste turno — vou enviá-la junto com a mídia.'
)

# O caso canonico do ciclo 7, agora fundido DE VERDADE (o teste de la montou a bolha fundida a
# mao, com ". " entre todas — por isso o defeito passou batido).
_C7_FALA_1 = "Sou eu mesma amor, bem gata como nas fotos rs"
_C7_FALA_2 = "Gravei um vídeo pra você 🥰"  # o ENQUADRAMENTO que o cenario cobra
_C7_NARRACAO = "As mídias já saíram junto com a minha mensagem"


# --- rig (mesmo de test_post_process_fusao_book / test_output_guard_narracao_fusao) -----------


class _FakeResult:
    def __init__(self, row: dict[str, Any] | None) -> None:
        self._row = row

    async def fetchone(self) -> dict[str, Any] | None:
        return self._row


class _FakeConn:
    async def execute(self, query: str, *args: Any, **kwargs: Any) -> _FakeResult:
        return _FakeResult({"ia_pausada": False})


class _FakePool:
    @asynccontextmanager
    async def connection(self) -> Any:
        yield _FakeConn()


class _Runtime:
    def __init__(self, context: ContextAgente) -> None:
        self.context = context


def _runtime() -> _Runtime:
    ctx = ContextAgente(
        db_pool=_FakePool(),  # type: ignore[arg-type]
        redis=None,  # type: ignore[arg-type]
        modelo_id=str(uuid4()),
        atendimento_id=str(uuid4()),
        cliente_id=str(uuid4()),
        turno_id=str(uuid4()),
    )
    return _Runtime(ctx)


def _ai(texto: str, _id: str) -> AIMessage:
    return AIMessage(content=texto, id=_id, usage_metadata=_USAGE)


def _com_book(m: AIMessage, n_midias: int = 3) -> AIMessage:
    m.tool_calls = [
        {
            "name": "enviar_midia",
            "args": {"tag": "apresentacao", "tipo": "video" if i == n_midias - 1 else "foto"},
            "id": f"{m.id}-tc{i}",
            "type": "tool_call",
        }
        for i in range(n_midias)
    ]
    return m


def _tool_msgs(m: AIMessage) -> list[ToolMessage]:
    return [
        ToolMessage(content="registro interno", id=f"t-{tc['id']}", tool_call_id=tc["id"])
        for tc in m.tool_calls
    ]


def _bolhas(texto: str) -> list[str]:
    return [b for b in _RE_BOLHAS.split(texto) if b.strip()]


def _aplicar(messages: list[BaseMessage], update: dict[str, Any]) -> list[BaseMessage]:
    """Aplica o update do no como o reducer `add_messages` faria (substitui por id)."""
    reescritas = {str(m.id): m for m in update.get("messages", [])}
    return [reescritas.get(str(m.id), m) for m in messages]


def _texto_ao_cliente(messages: list[BaseMessage]) -> str:
    """O que sai do post_process + Estagio 0 do guard — a mesma re-derivacao do coordenador."""
    msgs = mensagens_do_turno(messages)
    texto, _ = g._sanear_raciocinio(msgs, extrair_texto_do_turno(messages))
    return str(texto)


# --- 1: a cadeia real do defeito -------------------------------------------------------------


async def test_cadeia_real_passe1_mais_passe2_preserva_a_fala_boa() -> None:
    """O caso medido de ponta a ponta: passe 1 (fala boa + tools) + passe 2 (narracao) -> fusao ->
    guard. Antes: turno ZERADO. Agora: a bolha boa sai inteira e a narracao some."""
    a1 = _com_book(_ai(_BOA, "a1"))
    messages: list[BaseMessage] = [
        HumanMessage(content="essas fotos são suas mesmo ?", id="h1"),
        a1,
        *_tool_msgs(a1),
        _ai(_NARRACAO_PASSE2, "a2"),
    ]
    depois = _aplicar(messages, await pp.post_process({"messages": messages}, _runtime()))  # type: ignore[arg-type]

    despachado = _texto_ao_cliente(depois)
    assert despachado == _BOA
    assert _bolhas(despachado) == [_BOA]
    assert "neste turno" not in despachado


def test_bolha_unica_fundida_com_emoji_e_resgatada_pela_costura() -> None:
    """A prova do lado do GUARD, sem depender do filtro do post_process: a bolha ja fundida (como
    saia da producao) perde so a frase de narracao."""
    fundida = pp._concatenar_bolhas([_BOA, _NARRACAO_PASSE2])
    assert fundida == f"{_BOA} {_NARRACAO_PASSE2}"  # separador = espaco puro (emoji a esquerda)
    assert g._sem_narracao_de_mecanica(fundida) == _BOA
    assert g._limpar_bolhas_sem_zerar(fundida) == _BOA
    texto, msgs = g._sanear_raciocinio([_ai(fundida, "a1")], fundida)
    assert texto == _BOA
    assert [str(m.content) for m in msgs] == [_BOA]


def test_invariante_distributivo_fusao_x_bolhas_separadas() -> None:
    """guard(fusao(a, b)) tem de se comportar como guard(a) + guard(b) — era exatamente isso que
    quebrava: separadas davam a fala boa, fundidas davam "" (turno mudo)."""
    for a, b in (
        (_BOA, _NARRACAO_PASSE2),
        (_C7_FALA_2, _C7_NARRACAO),
        ("Te espero hoje amor 😊", "Já mandei as mídias neste turno, não repito nada."),
    ):
        separadas = g._limpar_bolhas(f"{a}\n\n{b}")
        fundida = g._limpar_bolhas_sem_zerar(pp._concatenar_bolhas([a, b]))
        assert separadas == a
        assert fundida == a


def test_caso_canonico_do_ciclo7_com_a_fusao_real_preserva_o_enquadramento() -> None:
    """A fusao REAL das tres bolhas do ciclo 7 (a 2a termina em emoji): antes o resgate parava na
    1a frase e o enquadramento do video — o que o cenario `duvida_das_fotos` cobra — ia junto com
    a narracao."""
    fundida = pp._concatenar_bolhas([_C7_FALA_1, _C7_FALA_2, _C7_NARRACAO])
    assert fundida == f"{_C7_FALA_1}. {_C7_FALA_2} {_C7_NARRACAO}"
    resgate = g._sem_narracao_de_mecanica(fundida)
    assert resgate == f"{_C7_FALA_1}. {_C7_FALA_2}"
    assert _C7_NARRACAO not in resgate


# --- 2: o outro lado — a narracao continua caindo --------------------------------------------


def test_narracao_pura_continua_sumindo_inteira() -> None:
    """Sem frase boa a salvar, nada muda: a bolha some (a costura nao inventa fala)."""
    for bolha in (
        _NARRACAO_PASSE2,
        _C7_NARRACAO,
        "As mídias já saíram no turno, não preciso repetir nada.",
        # costura no meio e as DUAS frases sujas: nao sobra nada para resgatar.
        f"{_C7_NARRACAO} 🥰 Já escrevi a bolha neste turno",
    ):
        assert g._limpar_bolhas(bolha) == ""
        assert g._resgatar_narracao(bolha) == ""
        assert g._limpar_bolhas_sem_zerar(bolha) == ""


def test_narracao_em_turno_multi_bolha_segue_dropando_a_bolha() -> None:
    """Com irma viva o modo resgate nem liga — pin do comportamento do ciclo 5/7."""
    turno = f"{_BOA}\n\n{_NARRACAO_PASSE2}"
    assert g._limpar_bolhas(turno) == _BOA


# --- 3: a fala boa nao paga o conserto -------------------------------------------------------


def test_fusao_de_duas_falas_boas_nao_vaza_pontuacao_na_saida() -> None:
    """A alternativa descartada (inserir ". " sempre que a esquerda nao termina em pontuacao)
    apareceria AQUI: o texto fundido vai literal ao cliente, o chunking so re-parte por `\\n\\n`.
    A bolha da persona nao termina em pontuacao — o emoji segue emendado por espaco."""
    fundida = pp._concatenar_bolhas([_BOA, "Vem hoje que eu te espero"])
    assert fundida == "Sou eu mesma amor 🥰 Vem hoje que eu te espero"
    assert "🥰." not in fundida and "🥰 ." not in fundida
    # o guard e no-op sobre fala boa fundida, e o cliente recebe UMA bolha, sem ponto enxertado.
    assert g._limpar_bolhas(fundida) == fundida
    chunks, _ = chunk_texto(fundida)
    assert chunks == [fundida]


async def test_fusao_de_falas_boas_com_book_continua_saindo_em_uma_bolha() -> None:
    """O contrato do <midia> (`_book_em_uma_bolha` no eval) nao afrouxou: turno de book com duas
    falas boas continua fundindo em UMA bolha, sem pontuacao nova."""
    a1 = _com_book(_ai(f"{_BOA}\n\nVem hoje que eu te espero", "a1"))
    messages: list[BaseMessage] = [
        HumanMessage(content="é você mesma ?", id="h1"),
        a1,
        *_tool_msgs(a1),
    ]
    depois = _aplicar(messages, await pp.post_process({"messages": messages}, _runtime()))  # type: ignore[arg-type]
    texto = extrair_texto_do_turno(depois)
    assert _bolhas(texto) == ["Sou eu mesma amor 🥰 Vem hoje que eu te espero"]


async def test_post_process_nao_funde_a_bolha_que_o_guard_descartaria() -> None:
    """O invariante do lado da FUSAO: a narracao nao entra na fundida — as duas falas boas se
    juntam e a bolha suja fica de fora (o guard veria o mesmo resultado bolha a bolha)."""
    a1 = _com_book(_ai(f"{_C7_FALA_1}\n\n{_C7_FALA_2}\n\n{_C7_NARRACAO}", "a1"))
    messages: list[BaseMessage] = [
        HumanMessage(content="é você mesma ?", id="h1"),
        a1,
        *_tool_msgs(a1),
    ]
    depois = _aplicar(messages, await pp.post_process({"messages": messages}, _runtime()))  # type: ignore[arg-type]
    texto = extrair_texto_do_turno(depois)
    assert _bolhas(texto) == [f"{_C7_FALA_1}. {_C7_FALA_2}"]
    assert _C7_NARRACAO not in texto


# --- 4: os tres detectores de midia usam a MESMA costura --------------------------------------


def test_costura_impede_uma_bolha_de_absolver_a_outra() -> None:
    """Sem a costura, a fusao punha as duas bolhas na MESMA frase e a negacao/absolvicao de uma
    desarmava o claim da outra — falso negativo nascido da fusao, nao da fala."""
    fundida = pp._concatenar_bolhas(["Não vou te mandar foto agora 🥰", "Te mandei agora, olha lá"])
    assert g.bolhas_midia_recem_afirmada(fundida) == [fundida]

    fundida_promessa = pp._concatenar_bolhas(["Não te mando foto 🥰", "Te mando o vídeo já já"])
    assert g.bolhas_promessa_de_midia(fundida_promessa, pediu_midia=True) == [fundida_promessa]

    fundida_passado = pp._concatenar_bolhas(
        ["Nunca mando nada antes 🥰", "Olha o vídeo que te mandei"]
    )
    assert g.bolhas_midia_ja_enviada(fundida_passado) == [fundida_passado]


def test_costura_nao_corta_emoji_no_MEIO_da_fala() -> None:
    """A costura exige MAIUSCULA depois do emoji justamente para nao partir a fala em que o emoji
    e ornamento no meio — la a co-ocorrencia DENTRO da frase e o que os detectores medem."""
    bolha = "Gravei um vídeo 🥰 pra você"
    assert g.bolhas_midia_recem_afirmada(bolha) == [bolha]
    assert g._frases_normalizadas(bolha) == ["gravei um video 🥰 pra voce"]


def test_frases_normalizadas_e_aditivo_sobre_o_split_historico() -> None:
    """Tudo que ja partia continua partindo; a costura so acrescenta corte. O espaco nas bordas e
    o mesmo do split historico (os detectores casam por `\\b`): nao se strippa, para nao mudar
    nada alem da fronteira nova."""
    assert [f.strip() for f in g._frases_normalizadas("Te espero hoje. Vem agora ?")] == [
        "te espero hoje",
        "vem agora",
    ]
    assert g._frases_normalizadas("Te espero hoje 🥰 Vem agora") == [
        "te espero hoje 🥰",
        "vem agora",
    ]
    assert g._frases_normalizadas("") == []
