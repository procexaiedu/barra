"""Recibo da Venda registrada (spec 0005, ticket 02).

O agente lanca DIRETO e mostra o que lancou — nao existe "posso lancar?". Quem afirmou o fato foi
o humano do grupo; pedir confirmacao seria devolver a ele o trabalho que o agente veio tirar. O
recibo e a porta de correcao: uma linha, os campos como o grupo os disse, e o convite explicito a
corrigir (o ticket 05 le a correcao por quote nesta mensagem).

Curto de proposito: o grupo e habitado. Campo que nao foi dito nao aparece — recibo nao e
formulario, e conferencia de relance.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from barra.dominio.grupo_financeiro.modelos import FormaPagamento
from barra.dominio.grupo_financeiro.pendencia import EM_ESPECIE_COM_A_MODELO, em_especie

CONVITE_DE_CORRECAO = "corrige aí se algo estiver errado"


def montar_recibo(
    *,
    linhas: Sequence[tuple[str, Decimal]],
    data: date,
    cliente: str | None = None,
    duracao_minutos: int | None = None,
    local: str | None = None,
) -> str:
    """UM recibo para as N Vendas registradas que nasceram do MESMO anuncio.

    "✅ Registrei: Yasmin R$ 700,00 · 08/08 · Cliente Gabriel · 1h · no nosso local — …"
    "✅ Registrei: Yasmin R$ 1.300,00 + Julia R$ 1.300,00 · 07/08 · Cliente Igor e um amigo · 2h"

    Uma mensagem, e nao uma por linha: o que aconteceu no mundo foi um atendimento so, e repetir
    cliente/dia/duracao em dois recibos transformaria um registro em spam num grupo habitado. O
    par nome+valor aparece explicito de proposito — e exatamente o que pode estar trocado quando
    a gestora escreve valores diferentes para cada uma, e o recibo e a porta de correcao.
    """
    quem = " + ".join(f"{modelo} {formatar_reais(valor)}" for modelo, valor in linhas)
    partes = [quem, f"{data:%d/%m}"]
    if cliente:
        partes.append(f"Cliente {cliente}")
    if duracao_minutos:
        partes.append(formatar_duracao(duracao_minutos))
    if local:
        partes.append(local)
    return f"✅ Registrei: {' · '.join(partes)} — {CONVITE_DE_CORRECAO}"


def montar_aviso_de_duplicata(
    *, linhas: Sequence[tuple[str, Decimal]], data: date, cliente: str | None = None
) -> str:
    """ "♻️ Essa já estava registrada: Yasmin R$ 1.300,00 · 07/08 · Cliente Igor — não lancei de novo."

    O agente RESPONDE ao anuncio duplicado em vez de engolir em silencio: quem postou precisa
    saber que a venda esta no sistema (senao reposta de novo), e precisa ver QUAL venda foi
    reconhecida — se o dedup pegou o fato errado, e por esta mensagem que o grupo descobre.
    """
    quem = " + ".join(f"{modelo} {formatar_reais(valor)}" for modelo, valor in linhas)
    partes = [quem, f"{data:%d/%m}"]
    if cliente:
        partes.append(f"Cliente {cliente}")
    return f"♻️ Essa já estava registrada: {' · '.join(partes)} — não lancei de novo."


def montar_recibo_de_pagamento(
    *,
    forma: FormaPagamento,
    valor: Decimal,
    data: date,
    cliente: str | None = None,
) -> str:
    """ "✅ Anotei: pix · Cliente Lucas · R$ 600,00 · 12/08 — corrige aí se algo estiver errado".

    O agente responde a forma de pagamento absorvida DIZENDO DE QUAL VENDA ESTA FALANDO. Nao e
    cortesia: ligar "Sim" a venda certa e o unico passo do modulo que depende de contexto de
    conversa, e portanto o unico que pode errar de mulher/cliente sem ninguem notar. Ecoar o par
    (cliente + valor + dia) transforma um erro invisivel em uma linha que o grupo corrige de
    relance — a mesma porta de correcao do recibo da venda.

    Dinheiro sai marcado **em especie com a modelo**: e o aviso de que aquela venda NAO vai
    aparecer na coluna de comprovante e ninguem precisa procurar Pix nenhum por ela.
    """
    partes = [f"{forma} ({EM_ESPECIE_COM_A_MODELO})" if em_especie(forma) else forma]
    if cliente:
        partes.append(f"Cliente {cliente}")
    partes += [formatar_reais(valor), f"{data:%d/%m}"]
    return f"✅ Anotei: {' · '.join(partes)} — {CONVITE_DE_CORRECAO}"


MAX_CLIENTES_NO_RECIBO_COLETIVO = 3
"""Quantos clientes o recibo coletivo nomeia antes de contar o resto. Mesmo teto da pergunta de
desempate, e pela mesma razao: uma lista de sete nomes deixa de ser conferivel de relance."""


def montar_recibo_de_pagamento_coletivo(
    *, forma: FormaPagamento, vendas: Sequence[tuple[str | None, Decimal]], total: Decimal
) -> str:
    """ "✅ Anotei: pix nas 4 vendas em aberto — Igor · Gustavo · Antonio (e mais 1) · R$ 3.150,00 — …"

    O recibo de UMA resposta que fechou N pendencias de uma vez. Ele carrega o **numero de vendas
    e o total** porque e isso que o gestor confere de cabeca contra o que ele achava que estava
    respondendo: quem disse "todos foram pix" pensando nas quatro da cobranca da manha descobre
    aqui, na hora, se o agente pegou cinco.

    Por isso tambem os nomes: a escrita coletiva e a mais larga do modulo, e um recibo que so
    dissesse "4 vendas" seria incorrigivel — nao daria para saber qual sobrou de fora do que a
    pessoa tinha em mente.
    """
    nomes = [cliente or f"{formatar_reais(valor)}" for cliente, valor in vendas]
    mostrados = nomes[:MAX_CLIENTES_NO_RECIBO_COLETIVO]
    resto = len(nomes) - len(mostrados)
    cauda = f" (e mais {resto})" if resto > 0 else ""
    marca = f"{forma} ({EM_ESPECIE_COM_A_MODELO})" if em_especie(forma) else forma
    return (
        f"✅ Anotei: {marca} nas {len(nomes)} vendas em aberto — "
        f"{' · '.join(mostrados)}{cauda} · {formatar_reais(total)} — {CONVITE_DE_CORRECAO}"
    )


def montar_recibo_de_anulacao(
    *, valor: Decimal, data: date, cliente: str | None = None, tinha_comprovante: bool = False
) -> str:
    """ "🗑️ Cancelei: Cliente Denis · R$ 700,00 · 07/08 — se foi engano, é só postar de novo."

    A unica fala do modulo que confirma um APAGAMENTO, e por isso ela nomeia o que morreu com os
    mesmos tres campos do recibo da venda: cancelar a venda errada tira dinheiro da conferencia
    sem deixar sintoma nenhum — a cobranca da manha simplesmente para de pedir, e ninguem procura
    o que nao esta sendo pedido.

    O convite muda de "corrige aí" para "posta de novo" de proposito: nao ha campo a corrigir aqui,
    ha um fato a desfazer — e desfazer tem gesto exato. O indice de dedup e PARCIAL (`WHERE
    anulada_em IS NULL`), entao repostar o mesmo anuncio depois do cancelamento registra a venda de
    novo. Dizer isso na propria mensagem e o que separa um convite de verdade de um "me avisa" que
    nao explica o que fazer.
    """
    partes = []
    if cliente:
        partes.append(f"Cliente {cliente}")
    partes += [formatar_reais(valor), f"{data:%d/%m}"]
    linha = f"🗑️ Cancelei: {' · '.join(partes)} — se foi engano, é só postar o anúncio de novo"
    if tinha_comprovante:
        # A venda ja tinha sido fechada por um Pix: o comprovante continua valendo (dinheiro que
        # entrou nao deixa de ter entrado) e agora sobra sem par. Dizer isso aqui e o que impede a
        # conferencia de virar um mistério no fim do mes — o `pix_sem_venda_em_pix` do fechamento
        # vai apontar a mesma coisa, mas so quando alguem pedir o extrato.
        linha += (
            "\n⚠️ Essa venda já tinha comprovante — o Pix continua contado e agora está sem par."
        )
    return linha


def montar_pergunta_de_anulacao(candidatas: Sequence[tuple[str | None, Decimal]]) -> str:
    """ "❓ Cancelar qual? Denis (R$ 700,00) · Alex (R$ 600,00) — me diz o nome do cliente."

    Mesma escada da pergunta de desempate da forma de pagamento, e pela mesma razao: entendeu-se o
    QUE fazer e nao de qual venda — e escolher sozinho seria apagar dinheiro no escuro.
    """
    nomes = [
        f"{cliente} ({formatar_reais(valor)})" if cliente else formatar_reais(valor)
        for cliente, valor in candidatas
    ]
    mostrados = nomes[:MAX_CLIENTES_NO_RECIBO_COLETIVO]
    resto = len(nomes) - len(mostrados)
    cauda = f" (e mais {resto})" if resto > 0 else ""
    return f"❓ Cancelar qual? {' · '.join(mostrados)}{cauda} — me diz o nome do cliente."


def formatar_reais(valor: Decimal) -> str:
    """R$ 1.300,00 — pt-BR na mao (sem `locale`, que depende do sistema onde o worker roda)."""
    inteiro, _, centavos = f"{valor:.2f}".partition(".")
    milhar = f"{int(inteiro):,}".replace(",", ".")
    return f"R$ {milhar},{centavos}"


def formatar_duracao(minutos: int) -> str:
    """60 -> "1h"; 90 -> "1h30"; 30 -> "30min" — a grafia que o proprio grupo usa."""
    horas, resto = divmod(minutos, 60)
    if horas and resto:
        return f"{horas}h{resto:02d}"
    if horas:
        return f"{horas}h"
    return f"{resto}min"
