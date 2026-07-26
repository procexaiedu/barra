"""O extrator exercido pela bancada + as VARIANTES que ela compara.

Tres implementacoes com a mesma forma (`(item, janela) -> payload`):

  - `ExtratorGravado` — devolve o payload que a PRODUCAO registrou no turno (campo `gravado` do
    golden set). E o BASELINE: roda sem credito, entra no gate e diz onde o extrator estava.
  - `ExtratorRoteirizado` — payload por id de item; e o fake dos testes da ferramenta.
  - `ExtratorDeepSeek` — o de verdade: mesma factory de chat de prod, mesmo schema de tool, bind
    forcado (`tool_choice`). Custa credito (§0) e so roda no alvo deliberado.

As VARIANTES sao as decisoes em aberto do extrator, cada uma um eixo que a bancada liga/desliga:
temperatura, presenca do bloco de estado registrado, descricao do aceite autocontida x
referenciada e promocao de intencao derivada.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from langchain_core.messages import BaseMessage
from langchain_core.utils.function_calling import convert_to_openai_tool

from barra.agente.ferramentas.extracao import ExtracaoPayload, registrar_extracao
from barra.core.llm import criar_chat_deepseek
from barra.settings import get_settings

from .golden import ItemGolden

_TOOL_EXTRACAO = "registrar_extracao"

# `proxima_acao_esperada` e obrigatoria no schema (nota interna do painel) e NAO e campo medido —
# os payloads do golden set a omitem e a normalizacao a preenche com este placeholder.
_ACAO_NAO_ROTULADA = "nao rotulada"

# Descricao AUTOCONTIDA do aceite: a de producao delega a regra do avanco-que-equivale-a-sim para
# "a sua conduta de <desconto>" — um bloco do BP_GERAL que a chamada barata da extracao NAO envia,
# entao a referencia fica orfa. Esta versao diz a regra no proprio campo. Variante da bancada; a
# troca em prod e outro ticket (08-descricao-autocontida-do-aceite).
DESC_ACEITE_AUTOCONTIDA = (
    "cliente ACEITOU o valor cotado — o sim dele, explícito ('pode ser', 'fechou', "
    "'vamos marcar') ou o avanço que só faz sentido se ele topou o preço: marcar o horário do "
    "encontro DEPOIS de você ter cotado, ou aceitar o desconto que você ofereceu. NÃO marque por "
    "ter cotado, nem por cortesia ou reconhecimento ('obrigado', 'ok', 'entendi', 'blz'), nem por "
    "ele só perguntar o preço: agradecer não é aceitar. Pergunta de logística (onde é, como "
    "chega) não é aceite enquanto ele não tiver topado o valor. Adiamento ('hoje não consigo', "
    "'espero começo do mês') NÃO é aceite. Este é o ÚNICO sinal de aceite — gravar "
    "`valor_acordado` não o infere — e ele fecha a negociação de preço, então marcá-lo cedo trava "
    "a sua escada de desconto."
)

# Descricao PRE-PATCH do aceite: a linha unica que rodava ate 24/07 (commit d51454e), sem a regra
# de cortesia e sem o "gravar `valor_acordado` nao o infere". Endurecer a descricao veio no MESMO
# commit que tirou a derivacao, entao a variante pre-patch precisa das duas metades.
DESC_ACEITE_PRE_PATCH = "cliente concordou com o valor cotado (não apenas perguntou o preço)"


@dataclass(frozen=True)
class Variante:
    """Um eixo (ou combinacao) que a bancada compara com numero em vez de opiniao.

    `temperatura` None = o default do provider (o que roda hoje: a chamada da extracao nao passa
    temperature). `bloco_estado` False tira o `<ja_registrado>` da cauda. `descricao_aceite` troca
    a descricao do campo `aceita_valor` no schema da tool. `promocao_intencao` liga a promocao
    derivada (horario gravado + evidenciado => 'agendamento') na leitura do campo intencao — no
    nivel TRAJETORIA ela nao e desligavel: mora no dominio.
    """

    nome: str
    temperatura: float | None = None
    bloco_estado: bool = True
    descricao_aceite: str | None = None
    promocao_intencao: bool = True
    aceite_derivado_do_valor: bool = False


VARIANTES: dict[str, Variante] = {
    "base": Variante("base"),
    "temp-zero": Variante("temp-zero", temperatura=0.0),
    "sem-bloco-estado": Variante("sem-bloco-estado", bloco_estado=False),
    "aceite-autocontido": Variante("aceite-autocontido", descricao_aceite=DESC_ACEITE_AUTOCONTIDA),
    "sem-promocao-intencao": Variante("sem-promocao-intencao", promocao_intencao=False),
    # O patch de 24/07 (d51454e) subiu sem evidencia: a ultima extracao de producao aconteceu antes
    # dele. A variante reconstitui o comportamento ANTERIOR nas duas metades que o nivel campo
    # alcanca — (a) `valor_acordado` gravado DERIVAVA o aceite, e como o valor e gravado ja na
    # cotacao, o aceite acendia no turno em que a IA cotou; (b) a descricao do campo era a linha
    # unica, sem a regra de cortesia. A terceira metade (o `limpar` que passou a REBAIXAR em vez de
    # omitir) mora no dominio e so aparece no nivel trajetoria.
    "pre-patch-24-07": Variante(
        "pre-patch-24-07",
        descricao_aceite=DESC_ACEITE_PRE_PATCH,
        aceite_derivado_do_valor=True,
    ),
}


class Extrator(Protocol):
    """Forma do extrator: recebe o item e a janela dedicada, devolve o payload da extracao."""

    async def __call__(
        self, item: ItemGolden, janela: list[BaseMessage]
    ) -> dict[str, Any]: ...  # pragma: no cover - protocolo


def normalizar_payload(args: dict[str, Any]) -> dict[str, Any]:
    """Args achatados da tool -> payload como o dominio o recebe.

    Mesma revalidacao do corpo da tool (`ExtracaoPayload` + `model_dump(exclude_defaults=True)`):
    e o que garante que o payload do extrator real e o do golden set cheguem iguais ao replay.
    """
    dados = {k: v for k, v in args.items() if k != "runtime"}
    dados.setdefault("proxima_acao_esperada", _ACAO_NAO_ROTULADA)
    payload = ExtracaoPayload(**dados)
    return payload.model_dump(mode="json", exclude_defaults=True)


def esquema_extracao(descricao_aceite: str | None = None) -> dict[str, Any]:
    """Schema OpenAI da `registrar_extracao`, com a descricao do aceite trocada quando a variante
    pede. Sem override devolve o schema de prod, byte a byte."""
    esquema: dict[str, Any] = convert_to_openai_tool(registrar_extracao)
    if descricao_aceite is not None:
        trocas = _trocar_descricao(esquema, "aceita_valor", descricao_aceite)
        if trocas == 0:
            # Falhar alto: uma variante que nao troca nada mediria a mesma coisa duas vezes.
            raise RuntimeError("campo `aceita_valor` nao encontrado no schema da extracao")
    return esquema


def _trocar_descricao(no: Any, campo: str, texto: str) -> int:
    """Substitui a `description` de `campo` onde quer que ele apareca no schema (o campo mora num
    sub-model, que o gerador pode emitir inline ou em `$defs`). Devolve quantas trocas fez."""
    trocas = 0
    if isinstance(no, dict):
        propriedades = no.get("properties")
        if isinstance(propriedades, dict) and isinstance(propriedades.get(campo), dict):
            propriedades[campo]["description"] = texto
            trocas += 1
        for valor in no.values():
            trocas += _trocar_descricao(valor, campo, texto)
    elif isinstance(no, list):
        for valor in no:
            trocas += _trocar_descricao(valor, campo, texto)
    return trocas


class ExtratorGravado:
    """Baseline: devolve o que a producao registrou no turno. Sem credito, deterministico."""

    nome = "gravado"

    async def __call__(self, item: ItemGolden, janela: list[BaseMessage]) -> dict[str, Any]:
        return dict(item.gravado)


class ExtratorRoteirizado:
    """Fake roteirizado por id de item (teste da ferramenta). Item fora do roteiro -> payload vazio.

    Guarda as janelas recebidas: e por elas que o teste afirma a ENTRADA que a bancada montou.
    """

    nome = "roteirizado"

    def __init__(self, roteiro: dict[str, dict[str, Any]]) -> None:
        self._roteiro = roteiro
        self.janelas: list[list[BaseMessage]] = []

    async def __call__(self, item: ItemGolden, janela: list[BaseMessage]) -> dict[str, Any]:
        self.janelas.append(list(janela))
        return dict(self._roteiro.get(item.id, {}))


class ExtratorDeepSeek:
    """O extrator de verdade: DeepSeek V4 Flash direto, bind forcado na `registrar_extracao`.

    ⚠️ §0: cada chamada gasta credito real. A tool NAO e executada (nada e escrito no banco) —
    a bancada le os args da tool call, que e o que o nivel campo mede.
    """

    nome = "deepseek"

    def __init__(self, variante: Variante) -> None:
        chat = criar_chat_deepseek(get_settings(), temperature=variante.temperatura)
        self._chat = chat.bind_tools(
            [esquema_extracao(variante.descricao_aceite)], tool_choice=_TOOL_EXTRACAO
        )

    async def __call__(self, item: ItemGolden, janela: list[BaseMessage]) -> dict[str, Any]:
        resposta = await self._chat.ainvoke(janela)
        chamadas = getattr(resposta, "tool_calls", None) or []
        # Sem tool_call util (truncou/recusou): payload vazio — o mesmo efeito do guard do no
        # `extrair`, que descarta o forcado em vez de persistir payload parcial.
        return dict(chamadas[0].get("args") or {}) if chamadas else {}
