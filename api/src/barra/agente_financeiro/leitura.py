"""O ouvido de TEXTO do Agente financeiro: mensagem do grupo -> intencao lida (spec 0005).

Irmao de `comprovante.py` (olho) e `transcricao.py` (ouvido de audio), e pela mesma divisao: aqui
mora so a IDA AO PROVIDER e a validacao do que ele devolveu; o que fazer com a intencao — escrever
a forma, postar o extrato, perguntar de qual venda — segue sendo da porta unica.

**Por que isto existe.** Ate 14/08 a leitura de fala era allowlist fechada (`pagamento.py`,
`correcao.py`, `fechamento.py`): uma lista de palavras permitidas, e qualquer palavra fora dela
descartava a mensagem inteira em silencio. O modo de falha era barato de raciocinar e caro de
operar — o grupo escrevia "todos foram pix" e nada acontecia, a cobranca da manha voltava
identica no dia seguinte, e cada fraseado novo ("foi tudo no pix menos o do Igor") era uma rodada
de manutencao. Uma allowlist nao tem cauda: ou a frase esta na lista, ou nao existe.

**As duas trancas que ficaram**, porque o que esta em jogo aqui e escrita em dinheiro:

* **A LLM aponta por INDICE, nunca por id.** A porta manda a lista das vendas abertas numerada e
  o modelo responde `[0, 2]`. Indice fora da lista e descartado, entao nao existe resposta que
  escreva numa venda que a porta nao ofereceu — o mesmo closed-world do resolver de nomes, de
  graca. Com UUID no prompt, um id plausivel e alucinavel; com indice, o pior caso e apontar a
  venda errada DENTRE as que estavam abertas, que e o que o recibo pega.
* **A LLM le, a porta decide.** Ela nao diz "escreva pix na venda X": diz o que entendeu, e a
  escada de conduta (recibo, pergunta de desempate, silencio) continua deterministica. Confianca
  baixa vira a pergunta que ja existe, nao um palpite gravado.

Sem `DEEPSEEK_API_KEY` o leitor e `None` e a porta cai na allowlist — que continua no repositorio
por isso, e nao por indecisao. E o mesmo `None` explicito do olho e do ouvido: em 24/07 a chave do
OpenRouter sumiu num redeploy e o OCR passou dias marcando tudo `em_revisao` sem ninguem entender
por que. Configuracao faltando tem que ser visivel, e o grupo nao pode ficar surdo porque um Env se
perdeu — com a allowlist atras, um dia ruim do provider custa a cauda, nao a conversa inteira.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Annotated, Any, Literal, get_args

from openai import AsyncOpenAI
from openai.types.shared_params import ResponseFormatJSONObject
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, ValidationError

from barra.dominio.grupo_financeiro.modelos import (
    FormaPagamento,
    MensagemRegistrada,
    VendaRegistrada,
)
from barra.dominio.grupo_financeiro.recibo import formatar_reais

_logger = logging.getLogger(__name__)

_BASE_URL_DEEPSEEK = "https://api.deepseek.com"
"""DIRETO na DeepSeek, e nao no pool do OpenRouter — o mesmo endereco dos tres caminhos de texto do
agente de venda (`core/llm.py::criar_chat_deepseek`), pelas mesmas duas razoes que pesam aqui:

1. **O cache de prefixo automatico so existe no endpoint oficial.** O `PROMPT` deste modulo e fixo
   e vai como system na frente de toda chamada, entao o prefixo fica quente e o hit custa ~98%
   menos. Num grupo que fala o dia inteiro, e a diferenca entre um custo que ninguem nota e um que
   aparece na fatura.
2. **Crava modelo e quantizacao**, sem a roleta de FP4 do load-balance. Leitura de dinheiro nao
   pode mudar de qualidade porque o roteador escolheu outro host.

O leitor do OLHO (`comprovante.py`) continua no OpenRouter com Gemini, e isso e proposital: OCR de
comprovante e a tarefa em que o Gemini e melhor, e la nao ha prefixo fixo para cachear. Duas
tarefas, dois provedores, duas chaves — e nenhuma delas fica cega porque a outra perdeu a sua.

**Medido em 14/08** (7 frases x 3 repeticoes, incluindo as negativas que nao podem virar escrita):
DeepSeek direto com `json_object` deu 21/21 de JSON valido e 21/21 de acerto; o mesmo modelo pelo
OpenRouter com `json_schema` estrito deu 16/21 e 14/21. Nao era o modelo — era o contrato errado,
por um caminho que nao o suporta (ver `_FORMATO_DA_SAIDA`)."""

_THINKING_DESLIGADO = {"thinking": {"type": "disabled"}}
"""O id cru `deepseek-v4-flash` vem com thinking LIGADO por default (doc do provider), e ligado ele
corrompe o structured output: `content` volta vazio (o orcamento inteiro vai para
`reasoning_content`) ou com JSON malformado.

A GRAFIA importa, e errar nela nao da erro — da silencio. `thinking: {"type": "disabled"}` e o
contrato do endpoint DIRETO; `reasoning: {"enabled": false}` e do OpenRouter e aqui simplesmente
nao desliga nada. Um parametro que o provider ignora nao levanta: ele so deixa o thinking ligado e
a leitura passa a falhar do jeito acima, o que na medicao de 14/08 pareceu incompetencia do
modelo."""

_FORMATO_DA_SAIDA: ResponseFormatJSONObject = {"type": "json_object"}
"""`json_object`, e NAO `json_schema` estrito: o endpoint direto rejeita o segundo com HTTP 400
(medido 14/08 — 21 de 21 chamadas). E por isso que o `PROMPT` termina com um exemplo do formato e
com a palavra "json": e o contrato que o `json_object` exige em troca de nao receber o schema.

O schema nao desaparece — ele vira VALIDACAO pos-hoc no Pydantic (`_Saida`), que e onde ele tem que
valer de qualquer jeito. Nenhum `strict` de provider dispensa conferir o que chegou; a diferenca e
so se a recusa acontece no servidor deles ou aqui."""

_TIMEOUT_S = 12.0
_MAX_RETRIES = 1
_MAX_TOKENS = 300

MAX_VENDAS_NO_PROMPT = 10
"""Teto da lista oferecida ao modelo. Grupo com mais pendencias que isto tem um problema que nao e
de leitura — e a cobranca da manha ja nomeia so as recentes pela mesma razao."""

MAX_MENSAGENS_DE_CONTEXTO = 6
"""Quanto do fio da conversa vai junto. O que decide a fala e quase sempre a mensagem anterior (a
cobranca que ela responde, o anuncio que ela comenta); historico longo so aumenta o custo e o
espaco para o modelo se prender a uma venda velha."""

PROMPT = """Voce le mensagens de um grupo de WhatsApp onde uma agencia registra vendas de acompanhantes.
Participam a modelo e os gestores. Devolve SO o JSON do schema.

Sua tarefa e dizer o que a ULTIMA mensagem esta fazendo. Ela quase sempre nao esta fazendo nada
disso — o grupo tem conversa, piada, foto e combinado. Na duvida, "nada".

TIPOS:
- "forma_de_pagamento": alguem esta dizendo COMO uma venda ja anunciada foi paga ("foi pix",
  "todos em dinheiro", "o do Gabriel foi pix", "esse foi no din"). Preencha `forma` e `vendas`.
- "pedido_de_fechamento": alguem esta pedindo o extrato/saldo ("fechamento", "como ta a conta?",
  "confere ai pra mim").
- "anulacao_de_venda": alguem dizendo que um atendimento NAO aconteceu e deve sair da conta
  ("cancela esse atendimento", "o do Denis nao veio, cancela", "desconsidera o do Rafael",
  "esse ai nao rolou, tira"). Em `vendas`, o numero da venda cancelada — **UMA**. Se a mensagem
  cita um cliente que esta na lista ("o do Denis", "do Rafael"), procure a linha dele e devolva o
  numero DAQUELA linha; nao devolva lista vazia quando o nome esta escrito na mensagem e na lista.
  Sem cliente nomeado, ai sim lista vazia — e isso inclui o demonstrativo sozinho ("cancela esse
  atendimento", "esse ai nao aconteceu"), mesmo que uma venda pareca a mais provavel pela
  conversa: apagar a venda errada nao deixa sintoma nenhum, e perguntar custa uma mensagem.
- "nada": qualquer outra coisa.

CAMPO `vendas`: os NUMEROS das vendas da lista abaixo a que a mensagem se refere. Um nome de
cliente citado na mensagem SEMPRE identifica a venda dele — vale para pagamento e para anulacao.
As regras de cautela abaixo sao sobre a mensagem que NAO nomeia ninguem:
- **So devolva a lista inteira quando a mensagem DISSER que sao todas.** Precisa estar escrito
  ("todos", "todas", "tudo", "geral", "o resto"). Uma resposta seca como "foi pix" ou "pix" NAO e
  "todas": e alguem falando de UMA venda sem dizer qual, e a resposta certa e a lista VAZIA.
  Quando ha uma pendencia so, a lista com aquela unica venda e obviamente correta — o cuidado
  vale quando ha varias.
- "todos", "todas", "tudo" -> TODOS os numeros da lista.
- "os dois", "ambas" -> so quando a lista tem exatamente dois; senao, lista vazia.
- um nome de cliente -> so o numero daquele cliente.
- referencia por DIA ("o de ontem", "o de sabado", "o da semana passada") -> lista VAZIA: a lista
  mostra a data de cada venda, mas nao diz que dia e hoje, e "ontem" resolvido por chute escreve
  dinheiro na venda de outro dia.
- excecao ("foi tudo pix menos o do Igor") -> todos MENOS o do Igor.
- **mensagem que e SO a forma** ("pix", "dinheiro", "foi pix", "foi no din", "sim") com MAIS DE UMA
  venda na lista -> lista VAZIA, sempre. Nao importa se uma delas parece a mais provavel pela
  ordem ou pelo assunto: quem sabe a qual pergunta essa resposta pertence e o agente, que a fez.
- a mensagem fala de pagamento mas nao da para saber de qual venda -> lista VAZIA. Nao chute:
  quem chuta marca a venda errada, ela some da conferencia e a certa nunca mais e cobrada. A
  lista vazia faz o agente PERGUNTAR de qual, que e o certo.

CUIDADO — estas NAO sao anulacao (tipo "nada"):
- o atendimento que mudou de hora ou de dia ("ele remarcou pra amanha", "vai ser mais tarde"):
  a venda continua de pe
- o cliente que reclamou, sumiu na conversa ou nao fechou ANTES de existir anuncio
- "cancela o pix", "cancelei a transferencia" — isso e pagamento, nao venda
- reclamacao sem verbo de cancelar ("esse cliente e chato", "o do Denis deu problema")

CUIDADO — estas NAO sao resposta de forma de pagamento (tipo "nada"):
- alguem ditando ou pedindo uma chave Pix ("minha chave pix e ...", "pode enviar nesse pix",
  "manda o pix pra ela")
- alguem conferindo em voz alta com valores ("confere: 600 pix, 600 pix")
- uma PERGUNTA sobre a forma ("foi pix ou dinheiro?", "todos foram pix?") — quem pergunta e o
  gestor cobrando, nao alguem respondendo
- falar de pix como meio ("vou passar o pix", "ja mandei o pix") sem dizer de qual venda

CAMPO `forma`: so o que foi DITO. Nunca ha forma padrao — na duvida, `confianca` "baixa".
- so "pix", "dinheiro", "debito", "credito" ou "link". Se nao houve forma nenhuma, deixe `forma`
  NULO (nunca escreva outra palavra nesse campo) e responda `tipo` "nada".
- "cartao" e "maquininha" NAO sao forma: sao a familia. "no cartao de credito" e credito, "passei
  no debito" e debito, "mandei o link" e link — mas "recebi no cartao", sozinho, e `tipo` "nada",
  porque escolher uma das tres por chute manda o operador procurar o dinheiro na adquirente
  errada, e ele so descobre no fim do mes.
- "tambem", "tbm", "idem", "o mesmo", "igual" COPIAM a forma da ultima que foi dita nas mensagens
  acima: se a anterior foi dinheiro, esta e dinheiro. Se nenhuma aparece ali, `tipo` e "nada".
- a forma vem da fala de quem responde, nao da pergunta do gestor ("foi pix ou dinheiro?" oferece
  as duas e nao escolhe nenhuma).

`confianca`: "alta" se a mensagem e claramente uma dessas coisas; "baixa" se voce esta
interpretando. Baixa faz o agente perguntar em vez de escrever — prefira baixa quando hesitar.

Responda em json puro, sem markdown e sem texto em volta. Formato exato (exemplo FICTICIO, nunca
copie os valores daqui):
{"tipo": "forma_de_pagamento", "forma": "pix", "vendas": [0, 1], "confianca": "alta"}
"""
# O exemplo e obrigatorio, nao decorativo: o `json_object` do endpoint direto exige que o prompt
# mostre o formato (e que a palavra "json" apareca nele). Sem isso a saida volta em prosa ou em
# markdown, e o Pydantic recusa — o modelo teria "entendido" a frase e a leitura morreria na
# validacao. Valores ficticios pela mesma razao do prompt do olho: o unico exemplo do prompt e o
# que o modelo tende a emitir quando esta em duvida.


@dataclass(frozen=True)
class IntencaoDoGrupo:
    """O que a mensagem esta fazendo, ja resolvido contra as vendas que a porta ofereceu."""

    tipo: Literal["forma_de_pagamento", "pedido_de_fechamento", "anulacao_de_venda", "nada"]
    forma: FormaPagamento | None = None
    vendas: tuple[VendaRegistrada, ...] = ()
    """As vendas apontadas, JA filtradas pela lista oferecida — nunca uma que a porta nao mandou."""
    confiavel: bool = True


LerIntencao = Callable[
    [str, Sequence[VendaRegistrada], Sequence[MensagemRegistrada]],
    Awaitable[IntencaoDoGrupo | None],
]
"""Ler uma mensagem de texto do grupo. `None` = nao deu para ler (provider fora, resposta
inconclusiva) — distinto de `IntencaoDoGrupo("nada")`, que e "li, e nao era nada"."""


FORMAS_CONHECIDAS: frozenset[str] = frozenset(get_args(FormaPagamento))
"""As cinco formas, derivadas do `FormaPagamento` do dominio — nunca reescritas a mao aqui.

Forma nova entra em `grupo_financeiro/modelos.py` e chega aqui sozinha. Foi a copia manual que
deixou este leitor em `pix`/`dinheiro` depois do desmembramento do cartao (ADR-0046 §4)."""


def _so_forma_conhecida(bruto: object) -> object:
    """As CINCO formas passam (em qualquer caixa); o resto — "nada", "", "n/a" — vira `None`.

    A lista e `FORMAS_CONHECIDAS`, derivada do proprio `Literal` do schema, e nao uma segunda
    tupla escrita a mao: a divergencia que este ticket consertou foi exatamente essa — o
    `FormaPagamento` do dominio virou cinco (ADR-0046 §4) e esta funcao ficou em duas, entao
    "foi no credito" voltava `None` pelo leitor LLM enquanto o leitor deterministico
    (`grupo_financeiro/pagamento.py`) ja lia as cinco.
    """
    if not isinstance(bruto, str):
        return bruto
    limpo = bruto.strip().lower()
    return limpo if limpo in FORMAS_CONHECIDAS else None


class _Saida(BaseModel):
    """Schema de saida. `extra="forbid"` <-> `additionalProperties:false` (sem isso o roteamento
    dinamico do OpenRouter pode aceitar campo extra em silencio)."""

    model_config = ConfigDict(extra="forbid")

    tipo: Literal["forma_de_pagamento", "pedido_de_fechamento", "anulacao_de_venda", "nada"] = (
        Field(description="O que a ultima mensagem esta fazendo.")
    )
    forma: Annotated[FormaPagamento | None, BeforeValidator(_so_forma_conhecida)] = Field(
        None, description="A forma dita, quando o tipo e forma_de_pagamento."
    )
    """Palavra fora das cinco formas vira `None` em vez de derrubar a leitura inteira.

    Medido em 14/08/2026: bastou o prompt dizer que sem forma a resposta e "nada" para o modelo
    passar a escrever `"forma": "nada"` — e o `ValidationError` matava tambem o `tipo`, que estava
    certo. Um campo que so e lido quando `tipo == "forma_de_pagamento"` nao pode ter poder de veto
    sobre os outros: e a mesma fronteira LLM->tool que ja custou turno neste projeto."""
    vendas: list[int] = Field(
        default_factory=list, description="Numeros das vendas da lista a que a mensagem se refere."
    )
    confianca: Literal["alta", "baixa"] = Field(
        "baixa", description="alta so quando a leitura e clara."
    )


def _lista_de_vendas(abertas: Sequence[VendaRegistrada]) -> str:
    """As vendas abertas como o modelo as ve: numeradas, com o que identifica cada uma.

    Cliente, valor e dia — os mesmos tres campos do recibo, porque sao os que o grupo usa para
    falar de uma venda ("o do Gabriel", "o de 700", "o de ontem").
    """
    if not abertas:
        return "(nenhuma venda em aberto)"
    linhas = []
    for numero, venda in enumerate(abertas):
        quem = venda.cliente_nome or "cliente nao dito"
        linhas.append(f"{numero}. {quem} · {formatar_reais(venda.valor)} · {venda.data:%d/%m}")
    return "\n".join(linhas)


def _fio_da_conversa(contexto: Sequence[MensagemRegistrada]) -> str:
    """As ultimas mensagens, da mais ANTIGA para a mais nova — que e como se le uma conversa.

    `contexto` chega do mais recente para o mais antigo (a ordem em que a porta consulta) e e
    invertido aqui: a lista ao contrario faria o modelo tratar a cobranca como resposta e a
    resposta como cobranca.
    """
    recentes = list(contexto[:MAX_MENSAGENS_DE_CONTEXTO])
    recentes.reverse()
    if not recentes:
        return "(sem conversa anterior)"
    return "\n".join(
        f"{'agente' if m.de_mim else 'grupo'}: {m.texto.strip()}" for m in recentes if m.texto
    )


_cliente_cache: dict[str, AsyncOpenAI] = {}


def _cliente(api_key: str) -> AsyncOpenAI:
    """Um cliente por chave, reusado pelo processo (o da API nao tem `ctx` de worker onde morar)."""
    cliente = _cliente_cache.get(api_key)
    if cliente is None:
        cliente = AsyncOpenAI(
            api_key=api_key,
            base_url=_BASE_URL_DEEPSEEK,
            timeout=_TIMEOUT_S,
            max_retries=_MAX_RETRIES,
        )
        _cliente_cache[api_key] = cliente
    return cliente


def leitor_de_intencao(settings: Any) -> LerIntencao | None:
    """Monta o leitor que a porta usa, ou `None` quando nao ha provider configurado.

    Le `deepseek_api_key`, e nao a do OpenRouter: o texto do grupo segue o MESMO provider dos
    caminhos de texto do agente de venda. O olho continua no OpenRouter — sao duas chaves porque
    sao duas tarefas, e nenhuma delas deve ficar cega porque a outra perdeu a sua.
    """
    api_key = getattr(settings, "deepseek_api_key", None)
    if not api_key:
        return None
    modelo = getattr(settings, "deepseek_model_chat", None) or "deepseek-v4-flash"
    cliente = _cliente(api_key)

    async def ler(
        texto: str,
        abertas: Sequence[VendaRegistrada],
        contexto: Sequence[MensagemRegistrada],
    ) -> IntencaoDoGrupo | None:
        oferecidas = list(abertas[:MAX_VENDAS_NO_PROMPT])
        entrada = (
            f"VENDAS EM ABERTO (sem forma de pagamento dita):\n{_lista_de_vendas(oferecidas)}\n\n"
            f"CONVERSA ANTERIOR:\n{_fio_da_conversa(contexto)}\n\n"
            f"ULTIMA MENSAGEM (e sobre ela que voce responde):\n{texto.strip()}"
        )
        try:
            resposta = await cliente.chat.completions.create(
                model=modelo,
                response_format=_FORMATO_DA_SAIDA,
                extra_body=_THINKING_DESLIGADO,
                # System FIXO na frente: e o prefixo que o cache automatico do endpoint oficial
                # mantem quente. Inverter a ordem (dados antes do prompt) jogaria fora o desconto.
                messages=[
                    {"role": "system", "content": PROMPT},
                    {"role": "user", "content": entrada},
                ],
                # Veredito reproduzivel, como a extracao e o judge da casa: a mesma frase nao pode
                # escolher vendas diferentes em duas leituras.
                temperature=0.0,
                max_tokens=_MAX_TOKENS,
            )
        except Exception:
            # Silencio com log, e NAO excecao: a mensagem ja esta gravada e o resto da porta (a
            # foto do comprovante, o anuncio, a delecao) nao tem nada a ver com o leitor de fala.
            _logger.warning("grupo_financeiro_leitura_falhou", exc_info=True)
            return None

        escolha = resposta.choices[0]
        conteudo = escolha.message.content
        motivo = getattr(escolha, "finish_reason", None)
        if motivo in ("length", "content_filter") or not conteudo or not conteudo.strip():
            # Conteudo vazio com 200 OK e o caso REAL, nao a hipotese: modelo "thinking" gasta o
            # orcamento em `reasoning_content` e devolve `content` em branco. Medido em 14/08 com
            # `max_tokens` apertado — o schema estrito nao protege disso, porque nao houve saida
            # nenhuma para validar.
            _logger.info("grupo_financeiro_leitura_vazia motivo=%s", motivo)
            return None
        try:
            lida = _Saida.model_validate_json(conteudo)
        except ValidationError:
            # JSON quebrado NAO pode subir: esta funcao roda dentro do webhook, e uma excecao aqui
            # derruba o turno inteiro — a mensagem ja gravada, o comprovante que vinha junto, tudo.
            # E o mesmo buraco que ja custou caro na fronteira LLM->tool do agente de venda.
            _logger.warning("grupo_financeiro_leitura_invalida conteudo=%r", conteudo[:200])
            return None
        return _resolver(lida, oferecidas)

    return ler


def _resolver(lida: _Saida, oferecidas: Sequence[VendaRegistrada]) -> IntencaoDoGrupo:
    """A TRANCA: o indice vira venda, e indice que a porta nao ofereceu simplesmente nao existe.

    Descartar em silencio (em vez de invalidar a leitura inteira) e deliberado: um modelo que
    devolve `[0, 7]` com cinco vendas na lista acertou o 0. Jogar fora a resposta toda por causa
    do 7 transformaria uma leitura util em silencio, que e o defeito que este modulo veio corrigir.
    """
    vendas = tuple(
        oferecidas[numero] for numero in dict.fromkeys(lida.vendas) if 0 <= numero < len(oferecidas)
    )
    forma: FormaPagamento | None = lida.forma
    if lida.tipo == "anulacao_de_venda":
        # Anulacao aponta venda e NAO carrega forma: cancelar nao diz nada sobre como se pagaria.
        return IntencaoDoGrupo(
            tipo="anulacao_de_venda", vendas=vendas, confiavel=lida.confianca == "alta"
        )
    if lida.tipo != "forma_de_pagamento":
        # Fechamento e "nada" nao carregam forma nem alvo, mesmo que o modelo tenha preenchido:
        # pedir o extrato nao e sobre uma venda, e "nada" e a ausencia de intencao.
        return IntencaoDoGrupo(tipo=lida.tipo, confiavel=lida.confianca == "alta")
    if forma is None:
        # "Forma de pagamento" sem forma nao e leitura, e ruido: cai como nada e o turno segue
        # para as outras leituras da porta.
        return IntencaoDoGrupo(tipo="nada")
    return IntencaoDoGrupo(
        tipo="forma_de_pagamento",
        forma=forma,
        vendas=vendas,
        confiavel=lida.confianca == "alta",
    )


def total(vendas: Sequence[VendaRegistrada]) -> Decimal:
    """Soma o que o coletivo pegou — o numero que o recibo mostra para ser conferido de cabeca."""
    return sum((v.valor for v in vendas), Decimal("0.00"))
