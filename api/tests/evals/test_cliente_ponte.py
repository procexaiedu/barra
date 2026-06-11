"""Prova a PONTE Claude Code do cliente simulado (sim/cliente_ponte.py) -- sem LLM/rede.

A ponte existe para a regra "API so para o agente do Barra": o lado cliente dos cenarios robo
e respondido por agente do Claude Code via arquivos. Cobre: protocolo pedido/resposta (prompt
renderizado, leitura da fala), tolerancia a escrita parcial, timeout, resposta vazia, o guard
anti-leakage herdado de `montar_prompt_cliente`, custo de API sempre zero e o roteamento em
`massa._construir_cliente`.
"""

import asyncio
import importlib
import json
import sys
from pathlib import Path

import pytest

_API = Path(__file__).resolve().parents[2]  # api/
if str(_API) not in sys.path:
    sys.path.insert(0, str(_API))

cliente_mod = importlib.import_module("evals.sim.cliente")
ponte_mod = importlib.import_module("evals.sim.cliente_ponte")
massa = importlib.import_module("evals.sim.massa")

PersonaCliente = cliente_mod.PersonaCliente
ClientePonte = ponte_mod.ClientePonte

_PERSONA = PersonaCliente(
    nome="Carlos", o_que_quer="atendimento interno hoje a noite", orcamento="ate 800"
)


def _ponte(tmp_path: Path, **kw) -> ClientePonte:
    kw.setdefault("timeout_s", 5.0)
    kw.setdefault("intervalo_s", 0.05)
    return ClientePonte(_PERSONA, tmp_path / "ponte", "interno_qualificacao#k1", **kw)


async def test_pedido_renderizado_e_resposta_lida(tmp_path: Path) -> None:
    ponte = _ponte(tmp_path)

    async def _responder() -> None:
        pedido = ponte.dir_ponte / "interno_qualificacao-k1__t1.pedido.json"
        while not pedido.exists():  # noqa: ASYNC110 -- polling de arquivo, sem Event cross-tarefa
            await asyncio.sleep(0.02)
        dados = json.loads(pedido.read_text(encoding="utf-8"))
        # O pedido carrega o prompt JA renderizado (mesmo formato do ClienteSimulado).
        assert dados["conversa_id"] == "interno_qualificacao#k1"
        assert dados["turno"] == 1
        assert dados["mensagens"][0]["role"] == "system"
        assert "Sua intencao: atendimento interno hoje a noite" in dados["mensagens"][0]["content"]
        assert "oi, tudo bem?" in dados["mensagens"][1]["content"]
        resposta = ponte.dir_ponte / "interno_qualificacao-k1__t1.resposta.json"
        # Escrita parcial primeiro: o leitor deve tolerar e retentar.
        resposta.write_text('{"mensagem": "oi prin', encoding="utf-8")
        await asyncio.sleep(0.1)
        resposta.write_text(
            json.dumps({"mensagem": "oi princesa, qual o valor? "}), encoding="utf-8"
        )

    tarefa = asyncio.ensure_future(_responder())
    acao = await ponte.decidir(["oi, tudo bem?"])
    await tarefa
    assert acao.mensagem == "oi princesa, qual o valor?"
    assert acao.ato is None
    assert ponte.custo_brl_acumulado == 0.0


async def test_timeout_sem_resposta(tmp_path: Path) -> None:
    ponte = _ponte(tmp_path, timeout_s=0.15)
    with pytest.raises(TimeoutError, match=r"__t1\.resposta\.json"):
        await ponte.decidir([])
    # O pedido ficou no disco (auditoria do que o responder deveria ter visto).
    assert (ponte.dir_ponte / "interno_qualificacao-k1__t1.pedido.json").exists()


async def test_resposta_vazia_e_erro(tmp_path: Path) -> None:
    ponte = _ponte(tmp_path)
    (tmp_path / "ponte").mkdir()
    (tmp_path / "ponte" / "interno_qualificacao-k1__t1.resposta.json").write_text(
        json.dumps({"mensagem": "   "}), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="mensagem vazia"):
        await ponte.decidir([])


async def test_anti_leakage_herdado(tmp_path: Path) -> None:
    persona = PersonaCliente(nome="X", o_que_quer="cumprir as expectativas", orcamento="500")
    ponte = ClientePonte(persona, tmp_path / "ponte", "c#k0", timeout_s=1.0)
    with pytest.raises(ValueError, match="anti-leakage"):
        await ponte.decidir([])
    assert not (tmp_path / "ponte").exists()  # recusa ANTES de escrever qualquer pedido


async def test_turnos_incrementam_nome_do_arquivo(tmp_path: Path) -> None:
    ponte = _ponte(tmp_path, timeout_s=0.05)
    for esperado in ("__t1", "__t2"):
        with pytest.raises(TimeoutError, match=esperado):
            await ponte.decidir([])


def test_construir_cliente_roteia_pela_ponte(tmp_path: Path) -> None:
    plano = massa.montar_plano(k_robo=1)
    robo = next(it for it in plano if it.tipo == "robo")
    fixo = next(it for it in plano if it.tipo == "fixo")
    assert isinstance(massa._construir_cliente(robo, tmp_path), ClientePonte)
    assert not isinstance(massa._construir_cliente(robo, None), ClientePonte)
    # Fixos seguem roteirizados mesmo com a ponte ligada (falas reais, custo zero de qualquer jeito).
    assert not isinstance(massa._construir_cliente(fixo, tmp_path), ClientePonte)
