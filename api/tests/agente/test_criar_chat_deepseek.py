"""criar_chat_deepseek: chat #1 DIRETO na API DeepSeek (api.deepseek.com), sem o pool OpenRouter.

Sem API real (só constrói o wrapper ChatOpenAI e inspeciona base_url/model/temperature). O direct
garante o cache automatico do DeepSeek (so o endpoint oficial cacheia) e crava modelo/quant. Como
`deepseek-chat` ja e non-thinking, NAO ha extra_body de provider/reasoning (conceitos do OpenRouter).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from barra.core.llm import criar_chat_deepseek
from barra.settings import Settings


def _settings() -> Settings:
    return Settings(  # type: ignore[call-arg]
        deepseek_api_key="sk-test", llm_chat_provider="anthropic", _env_file=None
    )


def test_base_url_e_modelo_direto_deepseek() -> None:
    chat = criar_chat_deepseek(_settings())
    assert str(chat.openai_api_base) == "https://api.deepseek.com"
    assert chat.model_name == "deepseek-chat"  # default = V4 Flash non-thinking


def test_temperatura_propagada() -> None:
    chat = criar_chat_deepseek(_settings(), temperature=1.3)
    assert chat.temperature == 1.3


def test_sem_extra_body_de_provider_ou_reasoning() -> None:
    # direct DeepSeek nao usa o roteamento/reasoning do OpenRouter.
    chat = criar_chat_deepseek(_settings())
    assert not chat.extra_body


def test_validator_exige_chave_quando_provider_deepseek() -> None:
    with pytest.raises(ValidationError, match="deepseek_api_key"):
        Settings(llm_chat_provider="deepseek", deepseek_api_key=None, _env_file=None)  # type: ignore[call-arg]


def test_validator_ok_com_chave() -> None:
    s = Settings(llm_chat_provider="deepseek", deepseek_api_key="sk-x", _env_file=None)  # type: ignore[call-arg]
    assert s.llm_chat_provider == "deepseek"
