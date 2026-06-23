"""criar_chat_deepseek: chat #1 DIRETO na API DeepSeek (api.deepseek.com), sem o pool OpenRouter.

Sem API real (só constrói o wrapper ChatOpenAI e inspeciona base_url/model/temperature/extra_body). O
direct garante o cache automatico do DeepSeek (so o endpoint oficial cacheia) e crava modelo/quant. O
id cru `deepseek-v4-flash` tem thinking LIGADO por default (doc oficial) -> a factory passa
`extra_body={"thinking": {"type": "disabled"}}`; NAO ha extra_body de provider/reasoning (OpenRouter).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from barra.core.llm import criar_chat_deepseek
from barra.settings import Settings


def _settings() -> Settings:
    return Settings(deepseek_api_key="sk-test", _env_file=None)  # type: ignore[call-arg]


def test_base_url_e_modelo_direto_deepseek() -> None:
    chat = criar_chat_deepseek(_settings())
    assert str(chat.openai_api_base) == "https://api.deepseek.com"
    assert chat.model_name == "deepseek-v4-flash"  # id atual (aliases legados saem 2026-07-24)


def test_temperatura_propagada() -> None:
    chat = criar_chat_deepseek(_settings(), temperature=1.3)
    assert chat.temperature == 1.3


def test_extra_body_trava_thinking_disabled() -> None:
    # O id cru `deepseek-v4-flash` liga thinking por default (doc oficial: "the thinking toggle
    # defaults to enabled") -> a factory trava non-thinking via extra_body. Sem provider/reasoning
    # (conceitos do OpenRouter, ausentes no endpoint direto).
    chat = criar_chat_deepseek(_settings())
    assert chat.extra_body == {"thinking": {"type": "disabled"}}


def test_validator_exige_chave_deepseek() -> None:
    # Caminhos de texto DeepSeek-only: o validator exige deepseek_api_key sempre.
    with pytest.raises(ValidationError, match="deepseek_api_key"):
        Settings(deepseek_api_key=None, _env_file=None)  # type: ignore[call-arg]


def test_validator_ok_com_chave() -> None:
    s = Settings(deepseek_api_key="sk-x", _env_file=None)  # type: ignore[call-arg]
    assert s.deepseek_api_key == "sk-x"
