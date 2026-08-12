"""Regras de negócio do contexto `modelos` (a profissional da agência).

Hoje só a derivação da tabela de preços a partir do preço de 1 hora — ver
`derivar_linha_da_tabela`. Puro: sem DB, sem settings, sem IA.
"""

from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal

# Parâmetros da derivação (Fernando, 11/08/2026, ao subir a Catarina). São CONSTANTES, não
# settings: mexer neles reescreve tabelas já materializadas no banco, e uma tabela cadastrada não
# pode mudar de valor porque alguém girou um percentual global — foi exatamente esse acoplamento
# que o `preco_minimo` do ADR-0037 desfez do lado do desconto.
_FATOR_PERIODO_LONGO = Decimal("0.8")
_HORAS_PARA_O_FATOR = Decimal("3")
_HORAS_DE_PERNOITE = Decimal("6")
_MULTIPLO_DE_FALA = Decimal("100")
_HORAS_MINIMAS_DERIVAVEIS = Decimal("1")


@dataclass(frozen=True)
class LinhaDerivada:
    """Uma linha de `modelo_programas`: o par (`preco`, `preco_minimo`) de uma duração.

    Nomes iguais aos das colunas de propósito — esta linha é feita para ser MATERIALIZADA no
    banco, não recalculada em runtime. Um `tuple` nu convidaria a inverter os dois na hora de
    escrever, e trocar preço por mínimo é um erro que o CHECK do banco só pega quando o mínimo é
    o maior dos dois.
    """

    preco: Decimal
    preco_minimo: Decimal


def teto_de_cem(valor: Decimal) -> Decimal:
    """Arredonda PARA CIMA ao múltiplo de 100 (960 → 1000, 1280 → 1300, 400 → 400).

    Sempre para cima, nunca "para o mais próximo": arredondar para baixo devolveria ao cliente
    desconto que ninguém aprovou, e o número que sai daqui é o preço de tabela — o teto de tudo
    que a escada do ADR-0031 desconta depois.
    """
    return (valor / _MULTIPLO_DE_FALA).to_integral_value(rounding=ROUND_CEILING) * _MULTIPLO_DE_FALA


def derivar_linha_da_tabela(
    horas: Decimal, *, preco_1h: Decimal, minimo_1h: Decimal
) -> LinhaDerivada:
    """Preço e piso de uma duração qualquer, DERIVADOS do preço de 1 hora da modelo.

    Decisão de negócio de 11/08/2026 (Fernando, ao subir a Catarina): a tabela inteira de uma
    modelo passa a sair deterministicamente de duas entradas — o preço de 1h e o mínimo de 1h — e
    a ser MATERIALIZADA como linhas absolutas em `modelo_programas`. A IA continua sem multiplicar
    nada: ela lê a tabela pronta, e o prompt segue proibindo a conta ("proporcional não existe",
    `regras.md.j2`). Esta função é o site ÚNICO da derivação; se o painel e um script de carga
    tivessem cada um a sua, divergiriam no arredondamento e a modelo teria duas tabelas.

    As contas:

        preço(h)  = teto_de_cem(preco_1h x h x fator),  fator = 0,8 a partir de 3h, senão 1
        mínimo(h) = preço(h)                            de 6h em diante
                  = teto_de_cem(minimo_1h x h)          abaixo disso

    O fator de 0,8 é o PARÂMETRO ("20% no período longo"); o desconto EFETIVO é outro, porque o
    teto em 100 devolve parte dele: em 3h, 400 x 3 x 0,8 = 960 sobe para 1000, e o desconto real
    fica em 16,7%. Isso é intencional e não é um bug de arredondamento — a tabela existe para ser
    FALADA no WhatsApp, e "mil" fecha venda que "novecentos e sessenta" faz o cliente reler. Quem
    quiser 20% cheios muda o fator, não o arredondamento.

    De 6h em diante (pernoite) `preco_minimo == preco`: a linha é NÃO DESCONTÁVEL na semântica do
    ADR-0037, e a escada percentual inteira fica clampada no próprio preço de tabela — a cauda
    nem oferece contraproposta nela (`contraproposta_da_escada` → None). É a regra do Fernando "do
    pernoite em diante a linha não desconta": o pernoite já É o desconto de volume, descontar de
    novo em cima dele venderia a noite pelo preço de uma tarde.

    O mínimo NUNCA passa do preço, mesmo quando a conta pediria: `minimo_1h` folgado (acima de
    80% do preço de 1h) faria o piso ultrapassar a tabela na faixa de 3h a 5h, onde só o preço
    leva o fator — e piso acima do preço viola o CHECK `modelo_programas_preco_minimo_ate_preco`
    e faria a escada clampada cotar MAIS CARO justamente ao dar desconto. O clamp fecha isso na
    origem, em vez de deixar o banco recusar a linha depois.

    Abaixo de 1 hora a derivação RECUSA em vez de responder (Fernando, 11/08/2026). Meia hora não
    custa metade de uma hora: o custo fixo do encontro — deslocamento, preparo, quarto — não se
    divide, então a linha curta é piso COMERCIAL cravado à mão, não conta. Os 30min da Catarina
    são 250/250 em prod; a fórmula devolveria 200/150 e rebaixaria o piso dela em 40%. Fail-closed
    de propósito: rodar o derivador sobre a tabela inteira dela tem que estourar, não sobrescrever
    o cadastro em silêncio.
    """
    if horas < _HORAS_MINIMAS_DERIVAVEIS:
        raise ValueError(
            f"duração de {horas} h não é derivável: abaixo de 1 hora o preço e o mínimo são "
            "cadastrados À MÃO (piso comercial — o custo fixo do encontro não se divide), "
            f"recebido: {horas!r}"
        )

    fator = _FATOR_PERIODO_LONGO if horas >= _HORAS_PARA_O_FATOR else Decimal("1")
    preco = teto_de_cem(preco_1h * horas * fator)
    if horas >= _HORAS_DE_PERNOITE:
        return LinhaDerivada(preco=preco, preco_minimo=preco)
    return LinhaDerivada(preco=preco, preco_minimo=min(teto_de_cem(minimo_1h * horas), preco))
