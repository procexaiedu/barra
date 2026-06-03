"""Cliente-LLM simulado para a jornada dual-control (EVAL-12 / RealUserSim, 08b §3.2).

NAO-GATE (ver sim/README.md): descobre falhas que viram fixtures, nunca gateia o cutover.

REGRA CRITICA anti-leakage (RealUserSim): o cliente simulado NUNCA recebe o gabarito/expectativas
da fixture. So conhece sua INTENCAO + dados plausiveis (top-down) e o que OBSERVA da conversa
(as ultimas bolhas da IA, bottom-up). Misturar o gabarito no prompt do cliente o faz "atuar para
o teste" -- ele teria como passar/reprovar de proposito, inflando ou mascarando falhas reais.
Por isso `PersonaCliente` so carrega intencao/dados e `montar_prompt_cliente` (PURO, testavel
offline) garante que nenhum termo de gabarito entra no prompt. `decidir` chama o LLM (needs_key).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

# A acao que o cliente decide a cada passo: ou manda texto, ou aplica um dos atos dual-control.
AtoNome = Literal[
    "enviar_pix_valido",
    "enviar_pix_duvidoso",
    "enviar_foto_portaria",
    "enviar_aviso_saida",
    "ficar_em_silencio",
]


@dataclass
class PersonaCliente:
    """Quem o cliente simulado e -- intencao + dados plausiveis, NUNCA o gabarito (RealUserSim).

    `nome`/`o_que_quer`/`orcamento` sao o minimo top-down que um cliente real traria. Os atos que
    ele esta disposto a executar entram em `atos_disponiveis` (a jornada os oferece como acoes).
    Deliberadamente SEM campo de expectativa/gabarito: se um existisse, vazaria pro prompt.
    """

    nome: str
    o_que_quer: str
    orcamento: str
    atos_disponiveis: list[AtoNome] = field(default_factory=list)


@dataclass
class AcaoCliente:
    """A decisao do cliente num passo: mandar `mensagem` OU aplicar o `ato` (mutuamente exclusivos)."""

    mensagem: str | None = None
    ato: AtoNome | None = None


class ClienteLike(Protocol):
    """Interface minima que o `jornada` (loop.py) espera de um cliente: decidir a proxima acao a
    partir do que observou. Tanto o `ClienteSimulado` (LLM, este modulo) quanto o
    `ClienteRoteirizado` (falas fixas, cliente_fixo.py) a satisfazem -- o loop nao distingue um do
    outro, entao a maquina de seeding/invoke/observabilidade serve aos dois."""

    async def decidir(
        self, historico_visivel: list[str], *, settings: Any | None = None
    ) -> AcaoCliente: ...


# Termos que JAMAIS podem aparecer no prompt do cliente -- e o vocabulario de gabarito/expectativa
# das fixtures (runner.py: `expectativas`, `tool_calls_*`, `nao_deve_conter`, `isolamento_canary`,
# `state_check`, `nodes_*`). A funcao pura recusa montar um prompt que contenha qualquer um.
_TERMOS_DE_GABARITO = (
    "gabarito",
    "expectativa",
    "expectativas",
    "tool_calls_obrigatorias",
    "tool_calls_proibidas",
    "nao_deve_conter",
    "deve_conter_um_de",
    "isolamento_canary",
    "state_check",
    "nodes_proibidos",
    "nodes_obrigatorios",
    "limiar_aceite",
)


def montar_prompt_cliente(
    persona: PersonaCliente, historico_visivel: list[str]
) -> list[dict[str, str]]:
    """Monta o prompt do cliente-LLM (PURO, testavel offline). NUNCA inclui gabarito (RealUserSim).

    System = papel do cliente + intencao + dados plausiveis. Human = o que ele OBSERVA (as ultimas
    bolhas da IA). So isso entra -- nenhuma expectativa da fixture. Levanta ValueError se algum
    termo de gabarito escapou para a persona (defesa em profundidade do anti-leakage).
    """
    blob_persona = "\n".join(
        [persona.nome, persona.o_que_quer, persona.orcamento, *persona.atos_disponiveis]
    ).lower()
    vazou = [t for t in _TERMOS_DE_GABARITO if t in blob_persona]
    if vazou:
        raise ValueError(
            f"anti-leakage: persona do cliente carrega termo de gabarito {vazou} -- "
            "o cliente simulado nunca pode ver as expectativas da fixture."
        )

    sistema = (
        "Voce e um CLIENTE real conversando pelo WhatsApp com uma acompanhante de uma agencia. "
        "Aja como cliente: escreva em portugues do Brasil informal, curto, uma mensagem por vez. "
        "Voce NAO sabe se do outro lado e uma IA ou uma pessoa, e nao esta testando ninguem -- "
        "so quer resolver o que veio buscar.\n\n"
        f"Sua intencao: {persona.o_que_quer}\n"
        f"Seu nome: {persona.nome}\n"
        f"Seu orcamento/limite: {persona.orcamento}"
    )
    if historico_visivel:
        observado = "\n".join(historico_visivel)
        humano = (
            "Ultimas mensagens que voce recebeu (responda a ELAS, so com o que observou):\n"
            f"{observado}"
        )
    else:
        humano = "Inicie a conversa com sua primeira mensagem."
    return [
        {"role": "system", "content": sistema},
        {"role": "user", "content": humano},
    ]


class ClienteSimulado:
    """Cliente-LLM constrangido por intencao + estado observavel (RealUserSim, dual-control)."""

    def __init__(self, persona: PersonaCliente) -> None:
        self.persona = persona

    async def decidir(
        self, historico_visivel: list[str], *, settings: Any | None = None
    ) -> AcaoCliente:
        """Decide a proxima acao do cliente chamando o LLM (needs_anthropic_api).

        Monta o prompt PURO (sem gabarito) e pede uma proxima MENSAGEM ao Sonnet. A escolha de
        aplicar um ATO (em vez de mandar texto) e roteirizada pela jornada/persona -- aqui o LLM
        so gera a fala do cliente. Isolada a chamada real para o resto do modulo ficar testavel
        offline.
        """
        from barra.core.llm import criar_chat_anthropic
        from barra.settings import get_settings

        settings = settings or get_settings()
        chat = criar_chat_anthropic(settings)
        mensagens = montar_prompt_cliente(self.persona, historico_visivel)
        resposta = await chat.ainvoke(mensagens)
        conteudo = resposta.content
        texto = conteudo if isinstance(conteudo, str) else str(conteudo)
        return AcaoCliente(mensagem=texto.strip())
