"""Cliente FIXO (roteirizado) para gerar conversas de calibracao sem cliente-LLM (EVAL-12).

Motivacao (alem do `ClienteSimulado`, nao no lugar): o cliente-LLM custa credito e e nao-
deterministico. O lado do CLIENTE de uma conversa PODE ser pre-escrito a mao; so o lado da IA tem
que rodar ao vivo (e o que se avalia). Um cliente fixo torna a geracao ~metade do custo (so um LLM
roda) e REUTILIZAVEL (gera 1x, congela, rotula de graca quantas vezes quiser).

`ClienteRoteirizado` satisfaz o mesmo `ClienteLike` (cliente.py) que o `jornada` (loop.py) espera:
o loop nao distingue um do outro -- toda a maquina de seeding/invoke/observabilidade/Trajetoria se
reaproveita intacta. A unica diferenca e que `decidir` devolve a proxima fala de uma lista fixa em
vez de chamar o Sonnet. SEM chamada de LLM -> esta classe e testavel/usavel offline.

As falas fixas vem quase literais das conversas REAIS (`docs/agente/conversas-reais/001..004`) --
ver `cenarios_fixos.py`. Anti-leakage: como nao ha prompt de persona, nao ha gabarito a vazar; ainda
assim as falas sao do CLIENTE realista, nunca embutem o veredito esperado (coberto por teste).
"""

from __future__ import annotations

from typing import Any

from .cliente import AcaoCliente


class ClienteRoteirizado:
    """Cliente cujas falas sao pre-escritas e deterministicas -- devolve a proxima a cada `decidir`.

    IGNORA `historico_visivel` de proposito: o roteiro e fixo, nao reage ao que a IA disse (a IA e
    quem varia). Quando o roteiro acaba (a IA pediu mais turnos do que ha falas), devolve
    `mensagem_padrao` -- por padrao "?", a fala que um cliente real impaciente manda quando esta
    esperando (aparece literalmente em 003/004). Nao inventa conteudo novo nem vaza gabarito.

    Dimensione `mensagens` ao `max_turnos` e aos passos de ato (um ato consome um indice mas NAO uma
    fala -- ver loop.py:jornada); a lista pode "sobrar" se a IA pausar antes (foto/pix), tudo bem.
    """

    def __init__(self, mensagens: list[str], *, mensagem_padrao: str = "?") -> None:
        self._mensagens = list(mensagens)
        self._cursor = 0
        self._mensagem_padrao = mensagem_padrao

    async def decidir(
        self, historico_visivel: list[str], *, settings: Any | None = None
    ) -> AcaoCliente:
        """Proxima fala do roteiro (ou `mensagem_padrao` se esgotou). Sem LLM, sem rede, sem DB."""
        if self._cursor < len(self._mensagens):
            texto = self._mensagens[self._cursor]
            self._cursor += 1
        else:
            texto = self._mensagem_padrao
        return AcaoCliente(mensagem=texto)
