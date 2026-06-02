"""Guard de boot: CORS curinga e proibido em producao (WIN-SEC-09)."""

import pytest

from barra.main import build_app
from barra.settings import Settings


def _settings(ambiente: str, **kwargs: object) -> Settings:
    # Segredos obrigatorios em producao por default; testes especificos sobrescrevem p/ vazio.
    base: dict[str, object] = {"evolution_webhook_token": "tok", "supabase_jwt_secret": "seg"}
    base.update(kwargs)
    return Settings(ambiente=ambiente, **base)  # type: ignore[arg-type]


def test_boot_aborta_com_cors_curinga_em_producao(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "barra.main.get_settings", lambda: _settings("producao", cors_origins=["*"])
    )
    with pytest.raises(RuntimeError):
        build_app()


@pytest.mark.parametrize("regex", [".*", ".+", "^.*$", "https?://.*"])
def test_boot_aborta_com_regex_amplo_em_producao(
    monkeypatch: pytest.MonkeyPatch, regex: str
) -> None:
    monkeypatch.setattr(
        "barra.main.get_settings",
        lambda: _settings(
            "producao", cors_origins=["https://app.elitebaby.com"], cors_origin_regex=regex
        ),
    )
    with pytest.raises(RuntimeError):
        build_app()


def test_boot_permite_regex_restrito_em_producao(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "barra.main.get_settings",
        lambda: _settings(
            "producao",
            cors_origins=["https://app.elitebaby.com"],
            cors_origin_regex=r"https://[a-z]+\.elitebaby\.com",
        ),
    )
    assert build_app() is not None


def test_boot_permite_cors_curinga_fora_de_producao(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("barra.main.get_settings", lambda: _settings("teste", cors_origins=["*"]))
    assert build_app() is not None


def test_boot_permite_origins_explicitos_em_producao(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "barra.main.get_settings",
        lambda: _settings("producao", cors_origins=["https://app.elitebaby.com"]),
    )
    assert build_app() is not None


def test_boot_aborta_sem_webhook_token_em_producao(monkeypatch: pytest.MonkeyPatch) -> None:
    # Fail-closed: sem token o /webhook/evolution aceitaria POST nao autenticado.
    monkeypatch.setattr(
        "barra.main.get_settings",
        lambda: _settings(
            "producao", cors_origins=["https://app.elitebaby.com"], evolution_webhook_token=""
        ),
    )
    with pytest.raises(RuntimeError):
        build_app()


def test_boot_aborta_sem_jwt_secret_em_producao(monkeypatch: pytest.MonkeyPatch) -> None:
    # Fail-closed: sem secret o JWT do painel perde a verificacao de assinatura.
    monkeypatch.setattr(
        "barra.main.get_settings",
        lambda: _settings(
            "producao", cors_origins=["https://app.elitebaby.com"], supabase_jwt_secret=""
        ),
    )
    with pytest.raises(RuntimeError):
        build_app()
