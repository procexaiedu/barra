"""Pre-aquecimento do prefixo global de cache (item #1).

Dois invariantes, sem tocar a API real (chat fake via monkeypatch de `criar_chat_anthropic`):
  1. byte-identidade: o prefixo aquecido (tools + BP_GERAL) bate EXATAMENTE com o que o no llm
     monta — protege contra drift (aquecer um prefixo que ninguem le).
  2. best-effort: falha no `ainvoke` nao propaga atraves do try/except do `startup`.
"""

import pytest

import barra.agente.llm as agente_llm
from barra.agente.ferramentas import INPUT_EXAMPLES, STRICT_TOOLS, TOOLS
from barra.agente.llm import (
    build_system_messages,
    build_tools_para_bind,
    preaquecer_prefixo_global,
)
from barra.agente.persona import render_prefixo_geral
from barra.settings import Settings


def _settings() -> Settings:
    return Settings(anthropic_api_key="sk-teste")


class _ChatFake:
    """Captura o que `preaquecer_prefixo_global` passa ao bind/ainvoke (sem rede)."""

    def __init__(self, *, erro: bool = False) -> None:
        self.max_tokens = 1024
        self.tools_recebidas: object = None
        self.mensagens_recebidas: object = None
        self._erro = erro

    def bind_tools(self, tools: object) -> "_ChatFake":
        self.tools_recebidas = tools
        return self

    async def ainvoke(self, mensagens: object) -> str:
        if self._erro:
            raise RuntimeError("falha simulada na API")
        self.mensagens_recebidas = mensagens
        return "ok"


@pytest.mark.anyio
async def test_prefixo_aquecido_bate_com_o_do_no_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings()
    fake = _ChatFake()
    monkeypatch.setattr(agente_llm, "criar_chat_anthropic", lambda _s: fake)

    await preaquecer_prefixo_global(settings)

    # tools: mesmo bind que `no_llm` (build_tools_para_bind com os mesmos args).
    esperado_tools = build_tools_para_bind(
        TOOLS,
        ttl=settings.cache_ttl_geral,
        strict_tools=STRICT_TOOLS if settings.anthropic_strict_tools else frozenset(),
        exemplos=INPUT_EXAMPLES,
    )
    assert fake.tools_recebidas == esperado_tools

    # system: BP_GERAL byte-identico ao de prepare_context (mesmo render + ttl, SEM BP_MODELO).
    esperado_system = build_system_messages(
        geral_md=render_prefixo_geral(), ttl_geral=settings.cache_ttl_geral
    )
    msgs = fake.mensagens_recebidas
    assert isinstance(msgs, list)
    assert [m.content for m in msgs[:-1]] == [m.content for m in esperado_system]
    assert msgs[-1].content == "ok"  # HumanMessage volatil, fora do prefixo cacheado
    assert fake.max_tokens == 1  # API rejeita 0; output e descartado


@pytest.mark.anyio
async def test_falha_no_aquecimento_nao_propaga_no_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings()
    monkeypatch.setattr(
        agente_llm, "criar_chat_anthropic", lambda _s: _ChatFake(erro=True)
    )

    # Espelha o try/except do startup: o aquecimento e otimizacao, nunca pre-requisito.
    try:
        await preaquecer_prefixo_global(settings)
    except Exception:
        pass
    else:
        pytest.fail("setup invalido: o fake deveria ter levantado")

    # Confirma que a excecao SO foi engolida pelo try acima (a funcao em si propaga).
    with pytest.raises(RuntimeError):
        await preaquecer_prefixo_global(settings)
