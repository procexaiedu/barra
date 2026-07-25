"""Chat FAKE roteirizado para o harness fiel (`evals/harness_fiel.py`).

Substitui o DeepSeek nos DOIS papéis que o turno exerce sobre o mesmo objeto de chat: a fala do nó
`llm` (uma `AIMessage` sem tool_call, que roteia o turno para `extrair`) e a extração forçada
(distinguida pelo `tool_choice` no `bind_tools`). Com ele o grafo REAL roda ponta a ponta,
determinístico e sem consumir crédito (§0) — o teste escreve o roteiro dos dois papéis e afirma o
que o Atendimento passa a valer.

Usado pelos testes que exercitam a proveniência do horário e a promoção da intenção.
"""

from typing import Any

from langchain_core.messages import AIMessage, BaseMessage

_USAGE = {"input_tokens": 10, "output_tokens": 8, "total_tokens": 18}


class _Extrator:
    """O bind forçado (`tool_choice=registrar_extracao`) do nó `extrair`: devolve os args da
    extração do turno. Esgotado o roteiro, repete o último (turnos extras não quebram o teste)."""

    def __init__(self, roteiro: list[dict[str, Any]]) -> None:
        self._roteiro = roteiro
        self._i = 0

    async def ainvoke(self, _messages: Any) -> AIMessage:
        args = self._roteiro[min(self._i, len(self._roteiro) - 1)]
        self._i += 1
        return AIMessage(
            content="",
            usage_metadata=_USAGE,  # type: ignore[arg-type]
            response_metadata={"finish_reason": "tool_calls"},
            tool_calls=[
                {
                    "name": "registrar_extracao",
                    "args": args,
                    "id": f"ex{self._i}",
                    "type": "tool_call",
                }
            ],
        )


class ChatRoteirizado:
    """`falas` = o que a IA diz em cada turno; `extracoes` = os args da extração forçada de cada
    turno. Guarda as janelas recebidas pelo nó `llm` — é por elas que se afirma o que a IA passou a
    ter no contexto."""

    model = "deepseek-fake"

    def __init__(self, falas: list[str], extracoes: list[dict[str, Any]]) -> None:
        self._falas = falas
        self._i = 0
        self._extrator = _Extrator(extracoes)
        self.janelas: list[list[BaseMessage]] = []

    def bind_tools(self, _tools: Any, *, tool_choice: Any = None, **_kw: Any) -> Any:
        return self._extrator if tool_choice == "registrar_extracao" else self

    async def ainvoke(self, messages: Any) -> AIMessage:
        self.janelas.append(list(messages))
        fala = self._falas[min(self._i, len(self._falas) - 1)]
        self._i += 1
        return AIMessage(content=fala, usage_metadata=_USAGE)  # type: ignore[arg-type]

    def contexto_do_ultimo_turno(self) -> str:
        """A janela inteira do último turno, concatenada — inclui os blocos que o contexto dinâmico
        anexou na última HumanMessage (é onde vive o `<local_de_encontro>`)."""
        return "\n".join(str(m.content) for m in self.janelas[-1])
