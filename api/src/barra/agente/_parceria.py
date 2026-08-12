"""O discriminante dos dois fluxos da parceira, e a bolha determinística do contato (ADR-0042).

Os dois fluxos partem da MESMA pessoa, na MESMA conversa, e divergem em tudo:

| | fluxo A — ENCAMINHAMENTO | fluxo B — DUPLA |
|---|---|---|
| gatilho | ele quer um ATO que ela não faz | ele quer DUAS MULHERES |
| quem fecha | a parceira (a IA sai da venda) | a modelo do canal, sozinha |
| valor | **nenhum**, nunca | o total das duas, da tabela DELA |
| telefone | nome + telefone + fotos | **nunca** |

Os modos de falha são os piores possíveis — passar o telefone numa conversa de dupla queima o
canal e perde as duas vendas; cotar as duas num pedido de anal promete o que ela não faz. Por isso
o discriminante NÃO pode ser uma inferência da LLM: é uma pergunta sobre a FAMÍLIA que o burst
mencionou, respondida por `fetiches_no_burst` (regex, `nos/_foco_do_turno.py`) cruzada com o
cadastro dela e com a autorização do par (`dominio/modelos/parcerias.py`).

`fluxo_da_parceira` devolve **no máximo um** valor. Não é uma convenção: é a assinatura. Não existe
caminho que produza os dois fluxos no mesmo turno porque não existe valor de retorno que os
carregue juntos — o `if/elif` só tem uma saída.

**Composição vence ato.** Num burst misto ("vocês duas fazem anal?") o fluxo é o B. O motivo é
assimetria de dano: B nunca emite telefone, e o ato fora do cardápio continua recebendo a recusa
closed-world de sempre (`<fora_do_cardapio>`) dentro do encontro que ela está vendendo. O caminho
inverso (A com composição na mesa) mandaria o contato da parceira para quem estava comprando as
duas — a falha que queima o canal.
"""

import re
from collections.abc import Container, Sequence
from typing import Literal

from barra.dominio.modelos.parcerias import Parceria

__all__ = [
    "FAMILIAS_DE_DUPLA",
    "FluxoParceria",
    "eh_bolha_de_contato_da_parceira",
    "fluxo_da_parceira",
    "formatar_bolha_contato_parceira",
]

FluxoParceria = Literal["encaminhamento", "dupla"]

# As famílias de composição que envolvem a PARCEIRA — "você com outra menina" e "dois casais".
# `acompanhante_mulher`/`acompanhante_homem` ficam de fora de propósito: a segunda pessoa ali é
# DELE (a esposa, um amigo), a parceira não entra, e tratá-las como dupla ofereceria uma modelo
# que ninguém pediu. Espelha `_FAMILIAS_SEM_RESOLUCAO` de `nos/prepare_context.py` — são as duas
# famílias que o resolver de cardápio deliberadamente não resolve, porque a conduta delas é esta.
FAMILIAS_DE_DUPLA: tuple[str, ...] = ("dupla_de_modelos", "dois_casais")


def fluxo_da_parceira(
    familias: Sequence[str],
    *,
    familias_fora_do_cardapio: Container[str],
    parceria: Parceria | None,
) -> tuple[FluxoParceria, str] | None:
    """Qual fluxo da parceira este turno arma — ou None (o caso normal). PURA.

    `familias` = a saída de `fetiches_no_burst` (o que o burst ATUAL do cliente pôs em pauta).
    `familias_fora_do_cardapio` = as famílias que o cadastro DELA não cobre (status `fora` do
    `_resolver_fetiches_em_pauta`) — o lado "ela não faz" da conta.
    `parceria` = a autorização do par; None desliga os dois fluxos.

    Devolve `(fluxo, chave)`: para a dupla, a família de composição em pauta; para o
    encaminhamento, a família do ato. Nunca os dois — ver a docstring do módulo.

    Os DOIS ramos consultam o cardápio, em sentidos opostos, e é isso que os torna coerentes com o
    closed-world do resto do sistema:
    - **dupla** exige a composição DENTRO do cardápio dela (é de lá que sai o número das duas). Com
      a parceria autorizada mas o item ausente, ela não faz esse arranjo — e vender sem preço seria
      pior que recusar;
    - **encaminhamento** exige o ato FORA do cardápio dela (é o que ela não faz) e DENTRO dos atos
      autorizados do par (é o que a parceira faz).
    """
    if parceria is None:
        return None
    for chave in familias:
        if (
            chave in FAMILIAS_DE_DUPLA
            and parceria.dupla_ativa
            and chave not in familias_fora_do_cardapio
        ):
            return "dupla", chave
    if not parceria.encaminhamento_ativo:
        return None
    for chave in familias:
        if chave in familias_fora_do_cardapio and chave in parceria.encaminhamento_atos:
            return "encaminhamento", chave
    return None


# --- A bolha determinística do contato ---------------------------------------------------------
# O telefone da parceira NUNCA entra no prompt e nunca sai da boca da LLM: ele é anexado pelo
# sistema, depois do turno, no MESMO trilho da chave Pix (`workers/coordenador.py`, que lê o número
# fresh do cadastro e o cola como última bolha). A tool `envolver_parceira` só registra a intenção;
# ela não devolve o número.
#
# COLISÃO COM A REDE ANTI-PIX: `nos/output_guard.py:_RE_CHAVE_PIX` casa `\d{11,14}` corridos e o
# Estágio 0 DESCARTA a bolha inteira — é a rede que impede a IA de digitar chave inventada. O
# telefone em E.164 (`+5521995346564`, 13 dígitos) casa esse padrão e a bolha morreria em silêncio.
# A saída NÃO é relaxar o regex (ele protege toda chave Pix de toda modelo): é um carve-out de UMA
# forma exata, a que só o sistema produz. `eh_bolha_de_contato_da_parceira` faz `fullmatch` sobre a
# bolha INTEIRA — prefixo literal, um nome, dois-pontos, um número E.164 e nada mais. Uma chave Pix
# de verdade (e-mail, EVP, CPF, número solto, número dentro de uma frase) continua sendo derrubada.
_PREFIXO_CONTATO = "contato da"

_RE_BOLHA_CONTATO_PARCEIRA = re.compile(
    rf"{_PREFIXO_CONTATO} [^\W\d_][^\n:]{{0,39}}: \+\d{{12,14}}",
    re.IGNORECASE,
)


def formatar_bolha_contato_parceira(nome: str, telefone: str) -> str:
    """A bolha determinística com o contato da parceira (fluxo A), anexada após o texto da IA.

    Objetiva, sem termo de carinho, no estilo de mensagem de dado — igual à bolha do Pix. O formato
    é contrato com `eh_bolha_de_contato_da_parceira`: mudá-lo aqui sem mudar lá faz a rede anti-Pix
    voltar a comer a bolha em silêncio.
    """
    return f"{_PREFIXO_CONTATO} {nome.strip()}: {_e164(telefone)}"


def eh_bolha_de_contato_da_parceira(bolha: str) -> bool:
    """True se a bolha é EXATAMENTE a bolha de contato que o sistema monta (PURA).

    Carve-out da rede anti-Pix, e só dela. Estreito de propósito: a bolha inteira tem de ser a
    forma canônica — texto solto com um telefone no meio não é absolvido.
    """
    return bool(_RE_BOLHA_CONTATO_PARCEIRA.fullmatch(bolha.strip()))


def _e164(telefone: str) -> str:
    """Normaliza o número do cadastro para E.164 (`+55...`). O painel grava com e sem o `+`."""
    digitos = re.sub(r"\D", "", telefone)
    return f"+{digitos}"
