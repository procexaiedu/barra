"""OBS-05 — guarda da fonte ÚNICA da config de tracing.

O tracing de produção é o Langfuse self-hosted (ADR 0019); o caminho LangSmith (`setup_tracing` +
anonymizer + campos `langchain_*`) foi retirado. Estes testes pinam o invariante de fonte única:
não pode reaparecer campo de tracing morto/duplicado em `Settings`, e o que existe é lido em
`barra.core.tracing`.
"""

import os

import pytest

from barra.core import tracing
from barra.settings import Settings


def test_settings_nao_tem_campo_de_tracing_morto() -> None:
    """Nenhum campo `langchain_*`/`langsmith_*` sobrevive: o LangSmith saiu inteiro."""
    relacionados = {
        nome for nome in Settings.model_fields if any(t in nome for t in ("langchain", "langsmith"))
    }
    assert relacionados == set()


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
    )
    try:
        # `permitir_em_teste`: com ambiente="teste" o setup é no-op por padrão (a suíte não enche o
        # Langfuse de trace de LLM fake); aqui o alvo do teste é justamente a ancoragem, então o rig
        # pede o opt-in — o mesmo que `evals.harness.habilitar_tracing` faz.
        handler = tracing.setup_langfuse(settings, servico="barra-worker", permitir_em_teste=True)
        assert handler is not None
        assert os.environ["LANGFUSE_TRACING_ENVIRONMENT"] == "teste"
        assert os.environ["OTEL_SERVICE_NAME"] == "barra-worker"
    finally:  # o código cria via os.environ.setdefault (fora do monkeypatch) — limpa p/ não vazar
        os.environ.pop("LANGFUSE_TRACING_ENVIRONMENT", None)
        os.environ.pop("OTEL_SERVICE_NAME", None)


def test_setup_langfuse_e_noop_em_ambiente_teste(monkeypatch: pytest.MonkeyPatch) -> None:
    """Higiene do projeto Langfuse: sob `ambiente="teste"` (o conftest o força) o setup é no-op.

    A suíte constrói a app com as chaves reais do `.env`; sem esta trava cada TestClient mandava
    para o Langfuse self-hosted um trace de LLM FAKE — a origem dos traces sem nome e do
    trace-monstro de 300+ observations. Quem precisa de trace em teste (rigs) passa
    `permitir_em_teste=True`.
    """
    import langfuse

    def _explode() -> None:
        raise AssertionError("nao deveria tocar o SDK em ambiente=teste")

    monkeypatch.setattr(langfuse, "get_client", lambda: _explode(), raising=False)
    monkeypatch.setattr(tracing, "_LANGFUSE_HANDLER", None, raising=False)

    settings = Settings(
        ambiente="teste",
        langfuse_public_key="pk-x",
        langfuse_secret_key="sk-x",
    )
    assert tracing.setup_langfuse(settings, servico="barra-api") is None


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
    assert {"deepseek-v4-flash"} <= set(por_nome)
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
