"""criar_chat_openrouter: shape do extra_body por flag (require_parameters / reasoning_off).

Sem API real (só constrói o wrapper ChatOpenAI e inspeciona o extra_body). O default preserva
#2/#3 (require_parameters=true); o chat #1 em DeepSeek desliga require_parameters (404 "no
endpoints" no deepseek-v4-flash) e o reasoning (espelha effort=low do Sonnet).
"""

from __future__ import annotations

from barra.core.llm import criar_chat_openrouter
from barra.settings import Settings


def _settings() -> Settings:
    # deepseek_api_key: o default llm_chat_provider=deepseek exige a chave no validator; sem .env
    # aqui, passamos uma fake p/ o Settings bootar (estes testes so inspecionam o extra_body OpenRouter).
    return Settings(  # type: ignore[call-arg]
        openrouter_api_key="sk-test", deepseek_api_key="sk-test", _env_file=None
    )


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


def test_temperatura_default_none_nao_seta() -> None:
    # #2/#3 chamam sem temperatura -> determinístico (default do provider).
    chat = criar_chat_openrouter(_settings(), modelo="qualquer/modelo")
    assert chat.temperature is None


def test_temperatura_propagada_quando_passada() -> None:
    # Chat #1 em DeepSeek: 1.3 (recomendação DeepSeek p/ chat), só honrada com reasoning OFF.
    chat = criar_chat_openrouter(
        _settings(),
        modelo="deepseek/deepseek-v4-flash",
        require_parameters=False,
        reasoning_off=True,
        temperature=1.3,
    )
    assert chat.temperature == 1.3


def test_quantizations_no_provider() -> None:
    # Piso de qualidade do roteamento: vai em provider.quantizations, ao lado de require_parameters.
    chat = criar_chat_openrouter(
        _settings(), modelo="deepseek/deepseek-v4-flash", quantizations=["fp8"]
    )
    assert chat.extra_body == {"provider": {"require_parameters": True, "quantizations": ["fp8"]}}


def test_chat_quantizations_sem_require_parameters() -> None:
    # Chat #1: require_parameters=False (404 com ele) mas com piso de quant + reasoning off.
    chat = criar_chat_openrouter(
        _settings(),
        modelo="deepseek/deepseek-v4-flash",
        require_parameters=False,
        reasoning_off=True,
        quantizations=["fp8"],
    )
    assert chat.extra_body == {
        "provider": {"quantizations": ["fp8"]},
        "reasoning": {"enabled": False},
    }
