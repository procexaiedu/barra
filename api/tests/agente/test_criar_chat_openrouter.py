"""criar_chat_openrouter: shape do extra_body por flag (require_parameters / reasoning_off).

Sem API real (só constrói o wrapper ChatOpenAI e inspeciona o extra_body). O default preserva
#2/#3 (require_parameters=true); o chat #1 em DeepSeek desliga require_parameters (404 "no
endpoints" no deepseek-v4-flash) e o reasoning (espelha effort=low do Sonnet).
"""

from __future__ import annotations

from barra.core.llm import criar_chat_openrouter
from barra.settings import Settings


def _settings() -> Settings:
    return Settings(openrouter_api_key="sk-test", _env_file=None)  # type: ignore[call-arg]


def test_default_forca_require_parameters_sem_reasoning() -> None:
    # #2/#3: roteamento dinâmico forçado a um provider que honra tool_choice/json_schema.
    chat = criar_chat_openrouter(_settings(), modelo="qualquer/modelo")
    assert chat.extra_body == {"provider": {"require_parameters": True}}


def test_chat_deepseek_sem_require_parameters_e_reasoning_off() -> None:
    # Chat #1 em DeepSeek: sem require_parameters (404 com ele) e reasoning desligado.
    chat = criar_chat_openrouter(
        _settings(),
        modelo="deepseek/deepseek-v4-flash",
        require_parameters=False,
        reasoning_off=True,
    )
    assert chat.extra_body == {"reasoning": {"enabled": False}}


def test_modelo_propagado() -> None:
    chat = criar_chat_openrouter(_settings(), modelo="deepseek/deepseek-v4-flash")
    assert chat.model_name == "deepseek/deepseek-v4-flash"
