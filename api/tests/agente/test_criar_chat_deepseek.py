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


# --- thinking (braco B do A/B de evals — .scratch/ab-thinking-chat) ------------------------------
# Prod nunca liga: default do knob e "disabled" e nenhum caminho passa `thinking` explicitamente
# fora do chat #1 (graph._criar_chat_principal + regen do output_guard, ambos via settings).


def test_thinking_default_disabled_no_settings() -> None:
    assert _settings().deepseek_thinking_chat == "disabled"


def test_thinking_disabled_devolve_wrapper_puro() -> None:
    from barra.core.llm import _ChatDeepSeekThinking

    chat = criar_chat_deepseek(_settings(), thinking="disabled")
    assert not isinstance(chat, _ChatDeepSeekThinking)


def test_thinking_high_monta_extra_body_e_omite_temperatura() -> None:
    # Doc oficial (guides/thinking_mode): thinking.type=enabled + reasoning_effort low/high/max;
    # a temperatura e IGNORADA em thinking -> a factory a omite mesmo se passada.
    from barra.core.llm import _ChatDeepSeekThinking

    chat = criar_chat_deepseek(_settings(), temperature=0.7, thinking="high")
    assert isinstance(chat, _ChatDeepSeekThinking)
    assert chat.extra_body == {"thinking": {"type": "enabled"}, "reasoning_effort": "high"}
    assert chat.temperature is None
    assert str(chat.openai_api_base) == "https://api.deepseek.com"


def test_thinking_reinjeta_reasoning_content_no_payload() -> None:
    # Loop de tool call em thinking: o provider exige `reasoning_content` de volta nas assistant
    # dos turnos seguintes (400 sem ele — guides/thinking_mode). O langchain-openai nao serializa
    # o campo; a subclasse reinjeta no payload a partir de additional_kwargs.
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

    chat = criar_chat_deepseek(_settings(), thinking="high")
    mensagens = [
        HumanMessage(content="quero marcar hoje"),
        AIMessage(
            content="",
            additional_kwargs={"reasoning_content": "checando a agenda antes de responder"},
            tool_calls=[{"name": "consultar_agenda", "args": {}, "id": "call_1"}],
        ),
        ToolMessage(content="{}", tool_call_id="call_1"),
    ]
    payload = chat._get_request_payload(mensagens)
    roles = [m["role"] for m in payload["messages"]]
    assert roles == ["user", "assistant", "tool"]
    assert payload["messages"][1]["reasoning_content"] == "checando a agenda antes de responder"
    # As nao-assistant nunca ganham o campo.
    assert "reasoning_content" not in payload["messages"][0]


def test_thinking_captura_reasoning_content_da_resposta() -> None:
    # langchain-openai NAO extrai reasoning_content ("use a provider-specific subclass", doc do
    # pacote) -> a subclasse captura p/ additional_kwargs, de onde a reinjecao (teste acima) le.
    chat = criar_chat_deepseek(_settings(), thinking="high")
    resposta = {
        "id": "cmpl-x",
        "model": "deepseek-v4-flash",
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": "consigo sim amor",
                    "reasoning_content": "cliente pediu horario; agenda livre",
                },
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }
    result = chat._create_chat_result(resposta, None)
    msg = result.generations[0].message
    assert msg.additional_kwargs["reasoning_content"] == "cliente pediu horario; agenda livre"
    assert msg.content == "consigo sim amor"
