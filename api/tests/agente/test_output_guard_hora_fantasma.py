"""Hora FANTASMA: a bolha CONFIRMA horario diferente do que o turno GRAVOU (corrida real
`c12cen_v2_20260814`, 14/08).

Duas ocorrencias independentes na mesma corrida:
  - `agenda_borda_fora`: a IA recusa as 23h no t2 ("23h ja nao consigo" / "Consigo as 22h, fecha ?"),
    o cliente devolve o numero na pergunta capciosa ("e ai, fechou as 23h?") e ela entrega "Fechou
    sim amor" / "Te espero as 23h" -- com a extracao do MESMO turno gravando 22:00 e a reserva
    criada as 22h;
  - `piso_que_andou`: oferta dela as 20h, extracao gravou 20:00, bolha saiu "Confirmado" / "Te
    espero as 19h amor".
Nenhuma guarda pegava: `regras.md.j2` so proibe confirmar o que a TOOL RECUSOU (`ERRO:`), e aqui a
reserva passou normalmente.

Familia do preco/incluso/servico fantasma: detector PURO, estreito, com regen 1x e drop da bolha no
fallback. Os controles NEGATIVOS valem tanto quanto as capturas -- reprovar a bolha certa trava o
turno do fechamento, o mais caro que existe:
  (i)  confirmar a hora CERTA nunca dispara;
  (ii) ecoar a hora que o CLIENTE disse, SEM token de fechamento, nunca dispara (a recusa com
       desculpa pessoal e a conduta certa);
  (iii) REOFERTAR outra hora ("Consigo as 11h, fecha ?") nunca dispara -- e assim que a
       reancoragem funciona.
"""

import importlib
from contextlib import asynccontextmanager
from datetime import time
from typing import Any
from uuid import uuid4

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from barra.agente.contexto import ContextAgente
from barra.agente.ferramentas.escalada import ESCALADA_ABERTA_PREFIXO
from barra.agente.nos.output_guard import (
    _feedback_hora_fantasma,
    bolhas_hora_fantasma,
    horario_gravado_no_turno,
)

mod = importlib.import_module("barra.agente.nos.output_guard")
mod_defesa = importlib.import_module("barra.agente._defesa")

_USAGE = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}

# --- detector puro: as duas capturas reais ------------------------------------------------------


def test_confirmacao_da_hora_recusada_no_turno_anterior_cai() -> None:
    # agenda_borda_fora: a hora e DELE (eco da pergunta capciosa) e mesmo assim a confirmacao cai --
    # com token de fechamento a proveniencia deixa de absolver.
    texto = "Fechou sim amor\n\nTe espero às 23h aqui, na chácara da barra"
    assert bolhas_hora_fantasma(texto, time(22, 0)) == [
        "Te espero às 23h aqui, na chácara da barra",
        "Fechou sim amor",
    ]


def test_confirmacao_de_hora_abaixo_da_ofertada_cai() -> None:
    # piso_que_andou: 19h ainda respeitava o piso do turno, e por isso nenhum check pegou.
    assert bolhas_hora_fantasma("Confirmado\n\nTe espero às 19h amor 🥰", time(20, 0)) == [
        "Te espero às 19h amor 🥰",
        "Confirmado",
    ]


# --- controles NEGATIVOS ------------------------------------------------------------------------


def test_confirmar_a_hora_certa_nao_dispara() -> None:
    assert bolhas_hora_fantasma("Confirmado\n\nTe espero às 22h amor 🥰", time(22, 0)) == []
    assert bolhas_hora_fantasma("Fechado às 22:00, te espero", time(22, 0)) == []


def test_eco_da_hora_do_cliente_sem_fechamento_nao_dispara() -> None:
    # A recusa com desculpa PESSOAL e a conduta certa: o numero e dele, e a bolha nao fecha nada.
    texto = "Poxa amor, 23h já não consigo\n\nConsigo às 22h, fecha ?"
    assert bolhas_hora_fantasma(texto, time(22, 0)) == []


def test_reoferta_de_outra_hora_nao_dispara() -> None:
    # Reofertar hora diferente da gravada e conduta CERTA -- so CONFIRMAR e mentira.
    assert bolhas_hora_fantasma("Consigo às 11h, fecha ?", time(10, 0)) == []
    assert bolhas_hora_fantasma("Consigo hoje às 14h amor, pode ser ?", time(11, 0)) == []


def test_duracao_faixa_aberta_e_outro_dia_ficam_de_fora() -> None:
    assert bolhas_hora_fantasma("400 1h no meu local amor\n\nFechado, te espero", time(22, 0)) == []
    assert bolhas_hora_fantasma("Te espero hoje, consigo a partir das 10:30", time(10, 0)) == []
    assert bolhas_hora_fantasma("Combinado, amanhã às 15h então", time(22, 0)) == []


def test_confirmacao_nua_sozinha_nao_dispara() -> None:
    # Sem irma que nomeie hora divergente, "Fechado amor" nao tem com o que ser contradita.
    assert bolhas_hora_fantasma("Fechado amor, te espero", time(22, 0)) == []


def test_sem_carimbo_o_detector_desliga() -> None:
    assert bolhas_hora_fantasma("Te espero às 23h amor", None) == []


# --- carimbo do turno ---------------------------------------------------------------------------


def test_horario_gravado_le_as_formas_do_carimbo() -> None:
    assert horario_gravado_no_turno({"horario_desejado": "22:00"}) == time(22, 0)
    assert horario_gravado_no_turno({"horario_desejado": "22:00:00"}) == time(22, 0)
    assert horario_gravado_no_turno({"horario_desejado": time(22, 30)}) == time(22, 30)


def test_horario_gravado_desliga_sem_hora_limpo_ou_ilegivel() -> None:
    assert horario_gravado_no_turno(None) is None  # carimbo negativo (erro/mute)
    assert horario_gravado_no_turno({"intencao": "cotacao"}) is None
    # `limpar` tem precedencia sobre os demais campos: o turno APAGOU a hora, nao gravou.
    assert (
        horario_gravado_no_turno(
            {"horario_desejado": "22:00", "limpar": ["horario_desejado"]},
        )
        is None
    )
    assert horario_gravado_no_turno({"horario_desejado": "noite"}) is None


# --- feedback da regen (FORMA vetada x FUNCAO devida) -------------------------------------------


def test_feedback_cola_a_hora_gravada_e_cita_a_bolha() -> None:
    msg = _feedback_hora_fantasma(time(22, 0), ["Te espero às 23h aqui"])
    assert "22:00" in msg
    assert "Te espero às 23h aqui" in msg
    assert "FORMA" in msg and "FUNCAO" in msg


def test_feedback_sem_hora_legivel_cai_na_estatica() -> None:
    assert _feedback_hora_fantasma(None, ["Te espero às 23h"]) == mod._FEEDBACK_GATILHO["hora"]


# --- fluxo no no (mesmo rig do test_output_guard_regen: sem DB, sem LLM) -------------------------


class _FakeResult:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    async def fetchall(self) -> list[dict[str, Any]]:
        return self._rows

    async def fetchone(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None


class _FakeConn:
    async def execute(self, query: str, *args: Any, **kwargs: Any) -> _FakeResult:
        return _FakeResult([])


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


def _state(texto: str, gravado: str | None, *, escalada: bool = False) -> dict[str, Any]:
    msgs: list[BaseMessage] = [
        HumanMessage(content="oi", id="h1"),
        HumanMessage(content="e aí, fechou as 23h?", id="h2"),
        AIMessage(content=texto, id="a1", usage_metadata=_USAGE),
    ]
    if escalada:
        msgs.append(
            ToolMessage(content=f"{ESCALADA_ABERTA_PREFIXO} ok", tool_call_id="t1", id="tm1")
        )
    return {
        "messages": msgs,
        "_extracao_registrada": None if gravado is None else {"horario_desejado": gravado},
    }


class _Capturador:
    def __init__(self) -> None:
        self.chamadas: list[dict[str, Any]] = []

    async def __call__(self, conn: Any, **kwargs: Any) -> None:
        self.chamadas.append(kwargs)


def _fake_regen(content: str | None) -> Any:
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
    async def _ok(texto: str, settings: Any, **_kw: Any) -> Any:
        return mod._VeredictoAup(viola=False, motivo="nenhum")

    monkeypatch.setattr(mod, "_julgar_aup", _ok)


def _msgs_update(res: Any) -> dict[str, Any]:
    return {m.id: m.content for m in (res.update or {}).get("messages", [])}


_TURNO_FANTASMA = "Fechou sim amor\n\nTe espero às 23h aqui, na chácara da barra"


async def test_hora_fantasma_e_gatilho_de_regen(monkeypatch: Any) -> None:
    cap = _Capturador()
    monkeypatch.setattr(mod_defesa, "abrir_handoff", cap)
    _judge_ok(monkeypatch)
    regen = _fake_regen("Consigo às 22h amor\n\nTe espero aqui na Chácara da Barra")
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(_state(_TURNO_FANTASMA, "22:00"), _runtime())  # type: ignore[arg-type]

    assert regen.chamadas and regen.chamadas[0]["gatilho"] == "hora"
    # O feedback vai enriquecido: a hora reservada colada e a bolha ofensora citada.
    assert "22:00" in regen.chamadas[0]["feedback_gatilho"]
    assert "Te espero às 23h" in regen.chamadas[0]["feedback_gatilho"]
    msgs = _msgs_update(res)
    assert msgs["a1"] == ""
    assert msgs["regen1"].startswith("Consigo às 22h")
    assert not cap.chamadas  # hora fantasma NUNCA vira handoff


async def test_hora_fantasma_persistiu_dropa_a_confirmacao_inteira(monkeypatch: Any) -> None:
    # Reincidiu: caem a bolha que nomeia a hora fantasma E a confirmacao NUA do mesmo turno --
    # sozinha, ela confirmaria o "fechou as 23h ?" dele do mesmo jeito.
    cap = _Capturador()
    monkeypatch.setattr(mod_defesa, "abrir_handoff", cap)
    _judge_ok(monkeypatch)
    regen = _fake_regen("Isso amor\n\nFechado, te espero às 23h\n\nTo aqui na Chácara da Barra")
    monkeypatch.setattr(mod, "_regenerar", regen)

    res = await mod.output_guard(_state(_TURNO_FANTASMA, "22:00"), _runtime())  # type: ignore[arg-type]

    assert not cap.chamadas
    msgs = _msgs_update(res)
    assert msgs["a1"] == ""
    assert msgs["regen1"] == "Isso amor\n\nTo aqui na Chácara da Barra"


async def test_turno_com_a_hora_certa_passa_intacto(monkeypatch: Any) -> None:
    # Controle negativo NO NO: a bolha que confirma a hora gravada nao arma regen nenhuma.
    cap = _Capturador()
    monkeypatch.setattr(mod_defesa, "abrir_handoff", cap)
    _judge_ok(monkeypatch)
    regen = _fake_regen("nao deveria ser chamada")
    monkeypatch.setattr(mod, "_regenerar", regen)

    texto = "Fechou sim amor\n\nTe espero às 22h aqui, na chácara da barra"
    res = await mod.output_guard(_state(texto, "22:00"), _runtime())  # type: ignore[arg-type]

    assert not regen.chamadas
    assert not cap.chamadas
    assert _msgs_update(res).get("a1", texto) == texto or not _msgs_update(res)


async def test_hora_fantasma_arma_com_escalada_aberta(monkeypatch: Any) -> None:
    # SEGURANCA, nao qualidade: a escalada aberta desarma repeticao/sonda/pedagio, nunca isto --
    # a fala compromete a modelo com um encontro que nao existe.
    cap = _Capturador()
    monkeypatch.setattr(mod_defesa, "abrir_handoff", cap)
    _judge_ok(monkeypatch)
    regen = _fake_regen("Consigo às 22h amor")
    monkeypatch.setattr(mod, "_regenerar", regen)

    await mod.output_guard(_state(_TURNO_FANTASMA, "22:00", escalada=True), _runtime())  # type: ignore[arg-type]

    assert regen.chamadas and regen.chamadas[0]["gatilho"] == "hora"
