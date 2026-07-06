"""OBS-05 — guarda da fonte ÚNICA da config de tracing.

Investigação (2026-05-30): SEC-10 (PR #53, commit beddaed) já consolidou a config de
tracing em `settings.py` numa única fonte de verdade. Não há campo duplicado nem morto
para remover: os três campos `langchain_*` existem e cada um é lido exatamente uma vez em
`barra.core.tracing`. Estes testes pinam esse invariante para impedir regressão (reintrodução
de um campo de tracing duplicado/morto) e cobrem o que o teste do SEC-10 não cobre:
`langchain_project` e `langchain_api_key` como fonte consumida.
"""

import inspect
import logging
import os
from typing import ClassVar

import pytest

from barra.core import tracing
from barra.settings import Settings

# Os campos de config de tracing que devem existir — e SÓ eles. Qualquer campo extra cujo nome
# remeta a tracing (langchain/langsmith/trace) indica duplicata ou fonte morta reintroduzida.
_CAMPOS_TRACING = frozenset({"langchain_tracing_v2", "langchain_api_key", "langchain_project"})


class _FakeClient:
    """Captura os kwargs do Client (api_key) sem tocar a rede."""

    instancias: ClassVar[list["_FakeClient"]] = []

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        _FakeClient.instancias.append(self)


@pytest.fixture(autouse=True)
def _reset(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeClient.instancias = []
    monkeypatch.setattr(tracing, "Client", _FakeClient)
    monkeypatch.setattr(tracing.run_trees, "_CLIENT", None, raising=False)
    monkeypatch.delenv("LANGCHAIN_PROJECT", raising=False)
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "")


def test_setup_tracing_consome_project_e_api_key_de_settings() -> None:
    """A única fonte de `project`/`api_key` é o campo de settings — não há mirror duplicado."""
    settings = Settings(
        langchain_tracing_v2=True, langchain_api_key="key-abc", langchain_project="proj-xyz"
    )

    client = tracing.setup_tracing(settings)

    assert client is _FakeClient.instancias[-1]
    assert client.kwargs["api_key"] == "key-abc"
    assert os.environ["LANGCHAIN_PROJECT"] == "proj-xyz"
    assert os.environ["LANGCHAIN_TRACING_V2"] == "true"


def test_settings_expoe_apenas_os_campos_de_tracing_consolidados() -> None:
    """Não existe campo de tracing duplicado/morto além dos três consolidados pelo SEC-10."""
    relacionados = {
        nome
        for nome in Settings.model_fields
        if any(t in nome for t in ("langchain", "langsmith", "trace"))
    }
    assert relacionados == _CAMPOS_TRACING


def test_cada_campo_de_tracing_e_lido_em_core_tracing() -> None:
    """Nenhum dos campos é morto: cada um é consumido em barra.core.tracing."""
    fonte = inspect.getsource(tracing)
    for campo in _CAMPOS_TRACING:
        assert f"settings.{campo}" in fonte, f"campo de tracing nao-lido (morto?): {campo}"


def test_langfuse_chave_ausente_loga_warning_de_boot(caplog: pytest.LogCaptureFixture) -> None:
    """Chave Langfuse vazia (cenário do redeploy git que zera o Env do stack) não pode ficar muda:
    `_ligar_langfuse_handler` preserva o contrato (retorna None) MAS grita um WARNING de boot, para
    distinguir 'tracing off de propósito' de 'a chave evaporou em prod'."""
    settings = Settings(langfuse_public_key="", langchain_tracing_v2=False)
    with caplog.at_level(logging.WARNING):
        handler = tracing._ligar_langfuse_handler(settings)
    assert handler is None
    assert any(
        r.levelno == logging.WARNING and "langfuse_prod" in r.message and "ausente" in r.message
        for r in caplog.records
    )


def test_langfuse_obrigatorio_derruba_o_boot_sem_tracing() -> None:
    """Trava de boot da observabilidade (piloto de producao assistida): com
    `langfuse_obrigatorio=true` (Env de prod), tracing que nao sobe (chave evaporada pelo redeploy
    git) LEVANTA RuntimeError em vez de rodar cego — o deploy falha na hora, com humano olhando."""
    settings = Settings(
        langfuse_public_key="", langfuse_obrigatorio=True, langchain_tracing_v2=False
    )
    with pytest.raises(RuntimeError, match="langfuse_obrigatorio"):
        tracing.setup_langfuse(settings)


def test_langfuse_sem_trava_segue_no_op_e_zera_o_gauge() -> None:
    """Default (dev/teste, sem chaves): comportamento atual preservado — None sem raise; o gauge
    `barra_tracing_langfuse_ligado` espelha 0 p/ o dashboard."""
    from prometheus_client import REGISTRY

    settings = Settings(langfuse_public_key="", langchain_tracing_v2=False)
    assert tracing.setup_langfuse(settings) is None
    assert REGISTRY.get_sample_value("barra_tracing_langfuse_ligado") == 0.0


def test_setup_langfuse_ancora_environment_e_service_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pacote pré-tráfego: com a chave presente, o handler ancora o `environment` (=settings.ambiente,
    separa rig de prod) e o `service.name` (=servico) via env var ANTES do get_client. Mockamos o SDK
    p/ não tocar a rede."""
    import langfuse
    import langfuse.langchain

    class _FakeLFClient:
        def auth_check(self) -> bool:
            return True

    monkeypatch.setattr(langfuse, "get_client", lambda: _FakeLFClient(), raising=False)
    monkeypatch.setattr(langfuse.langchain, "CallbackHandler", lambda: object(), raising=False)
    monkeypatch.setattr(tracing, "_LANGFUSE_HANDLER", None, raising=False)
    monkeypatch.delenv("LANGFUSE_TRACING_ENVIRONMENT", raising=False)
    monkeypatch.delenv("OTEL_SERVICE_NAME", raising=False)

    settings = Settings(
        ambiente="teste",
        langfuse_public_key="pk-x",
        langfuse_secret_key="sk-x",
        langchain_tracing_v2=False,
    )
    try:
        handler = tracing.setup_langfuse(settings, servico="barra-worker")
        assert handler is not None
        assert os.environ["LANGFUSE_TRACING_ENVIRONMENT"] == "teste"
        assert os.environ["OTEL_SERVICE_NAME"] == "barra-worker"
    finally:  # o código cria via os.environ.setdefault (fora do monkeypatch) — limpa p/ não vazar
        os.environ.pop("LANGFUSE_TRACING_ENVIRONMENT", None)
        os.environ.pop("OTEL_SERVICE_NAME", None)


def test_registrar_modelos_langfuse_cria_definicoes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Custo do trace: `registrar_modelos_langfuse` cria a definição de cada modelo com preço, p/ o
    Langfuse precificar o total_cost (senão 0). Confere nomes, pattern (com alias legado) e preços
    derivados das tabelas de `_custo`."""
    import langfuse

    from barra.agente._custo import modelos_para_langfuse

    criados: list[dict[str, object]] = []

    class _Models:
        def create(self, **kw: object) -> None:
            criados.append(kw)

    class _Client:
        class api:
            models = _Models()

    monkeypatch.setattr(langfuse, "get_client", lambda: _Client(), raising=False)
    monkeypatch.setattr(tracing, "_LANGFUSE_HANDLER", object(), raising=False)

    tracing.registrar_modelos_langfuse(modelos_para_langfuse())

    por_nome = {c["model_name"]: c for c in criados}
    assert {"deepseek-v4-flash", "claude-haiku-4-5"} <= set(por_nome)
    ds = por_nome["deepseek-v4-flash"]
    assert ds["input_price"] == 0.14 / 1_000_000
    assert ds["output_price"] == 0.28 / 1_000_000
    assert "deepseek-chat" in str(ds["match_pattern"])  # alias legado coberto


def test_registrar_modelos_langfuse_noop_sem_handler(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sem handler (tracing off — ex.: pytest), é no-op: nem toca o SDK."""
    import langfuse

    def _boom() -> object:
        raise AssertionError("get_client não deveria ser chamado sem handler")

    monkeypatch.setattr(langfuse, "get_client", _boom, raising=False)
    monkeypatch.setattr(tracing, "_LANGFUSE_HANDLER", None, raising=False)

    tracing.registrar_modelos_langfuse([{"model_name": "x", "match_pattern": "y"}])


def test_modelos_para_langfuse_deriva_das_tabelas_de_preco() -> None:
    """Anti-drift: os preços registrados no Langfuse DERIVAM das tabelas `PRECO_*` de `_custo`
    (fonte única) — mexeu na tarifa, o registro acompanha, sem número duplicado."""
    from barra.agente import _custo

    modelos = {m["model_name"]: m for m in _custo.modelos_para_langfuse()}
    ds = modelos["deepseek-v4-flash"]
    assert ds["input_price"] == _custo.PRECO_DEEPSEEK_USD_PER_MTOK["input"] / 1_000_000
    assert ds["output_price"] == _custo.PRECO_DEEPSEEK_USD_PER_MTOK["output"] / 1_000_000
    hk = modelos["claude-haiku-4-5"]
    assert hk["input_price"] == _custo.PRECO_HAIKU_USD_PER_MTOK["input"] / 1_000_000
