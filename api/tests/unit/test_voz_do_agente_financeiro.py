"""A voz do Agente financeiro e reconhecivel por ela mesma (spec 0005).

Este arquivo existe para uma lista nao envelhecer. `voz.PREFIXOS_DO_AGENTE` e a segunda tranca do
corte de eco — a que segura o recibo do proprio agente quando o `fromMe` vem invertido (a modelo e
participante do grupo e o WhatsApp dela e outra instancia no mesmo webhook). Uma fala nova que
nasca sem prefixo registrado abre esse buraco em silencio, entao o teste MONTA cada fala real do
modulo e exige que a voz se reconheca.

Sem banco e sem provider: tudo aqui e funcao pura de dominio.
"""

from datetime import date
from decimal import Decimal
from uuid import uuid4

from barra.dominio.grupo_financeiro.cobranca import (
    CobrancaDaAgencia,
    montar_aviso_de_cobranca_duplicada,
    montar_confirmacao_de_quitacao,
    montar_pergunta_do_comprovante_ambiguo,
    montar_recibo_da_cobranca,
)
from barra.dominio.grupo_financeiro.comprovante import (
    PEDIDO_DE_REENVIO,
    ComprovanteDoGrupo,
    PlanoDeAbate,
    montar_aviso_de_chave_desconhecida,
    montar_aviso_de_comprovante_repetido,
    montar_confirmacao_de_abate,
    montar_pergunta_do_comprovante,
)
from barra.dominio.grupo_financeiro.correcao import (
    AVISO_DE_CORRECAO_AMBIGUA,
    AVISO_DE_CORRECAO_DUPLICADA,
)
from barra.dominio.grupo_financeiro.fechamento import (
    TUDO_CONCILIADO,
    Extrato,
    montar_fala_do_fechamento,
)
from barra.dominio.grupo_financeiro.modelos import VendaRegistrada
from barra.dominio.grupo_financeiro.pagamento import montar_pergunta_de_desempate
from barra.dominio.grupo_financeiro.pendencia import Pendencia
from barra.dominio.grupo_financeiro.pergunta import montar_pergunta_minima
from barra.dominio.grupo_financeiro.recibo import (
    montar_aviso_de_duplicata,
    montar_recibo,
    montar_recibo_de_pagamento,
)
from barra.dominio.grupo_financeiro.rotina import MovimentoDoGrupo, montar_cobranca_da_manha
from barra.dominio.grupo_financeiro.voz import e_fala_do_agente

DIA = date(2026, 8, 13)
MODELO = uuid4()


def _venda(valor: str, *, cliente: str = "Gabriel", forma: str | None = None) -> VendaRegistrada:
    return VendaRegistrada(
        id=uuid4(),
        modelo_id=MODELO,
        valor=Decimal(valor),
        data=DIA,
        mensagem_id=uuid4(),
        cliente_nome=cliente,
        forma_pagamento=forma,
    )


def _cobranca() -> CobrancaDaAgencia:
    return CobrancaDaAgencia(
        id=uuid4(),
        grupo_id=uuid4(),
        modelo_id=MODELO,
        mensagem_id=uuid4(),
        descricao="3RJ Suporte/Anúncio: 3 DIAS",
        valor=Decimal("385.80"),
        data=DIA,
    )


def _comprovante_ja_lido() -> ComprovanteDoGrupo:
    return ComprovanteDoGrupo(
        id=uuid4(),
        grupo_id=uuid4(),
        mensagem_id=uuid4(),
        classificacao="fechamento",
        valor=Decimal("1200.00"),
        data_transferencia=DIA,
    )


def _falas_do_agente() -> dict[str, str]:
    """Uma amostra de CADA fala que o modulo sabe produzir, montada pelas funcoes de verdade."""
    venda = _venda("700")
    extrato = Extrato(
        modelo_id=MODELO,
        vendido=Decimal("700.00"),
        a_comprovar=Decimal("700.00"),
        vendas=1,
        pendencias=(Pendencia(venda_id=venda.id, tipo="comprovante"),),
    )
    manha = montar_cobranca_da_manha(
        extrato=extrato,
        a_cobrar=[_venda("700")],
        movimento=MovimentoDoGrupo(vendas=1, valor=Decimal("700.00")),
        hoje=DIA,
    )
    assert manha is not None
    return {
        "recibo": montar_recibo(
            linhas=[("Yasmin", Decimal("700.00"))], data=DIA, cliente="Gabriel"
        ),
        "duplicata": montar_aviso_de_duplicata(
            linhas=[("Yasmin", Decimal("700.00"))], data=DIA, cliente="Gabriel"
        ),
        "pagamento": montar_recibo_de_pagamento(
            forma="pix", valor=Decimal("600.00"), data=DIA, cliente="Lucas"
        ),
        "pergunta_minima": montar_pergunta_minima(
            faltas=("valor",), cliente="Gabriel", nomes_desconhecidos=(), por_modelo=False
        ),
        "abate": montar_confirmacao_de_abate(
            PlanoDeAbate(abatidas=(venda,), valor_abatido=Decimal("700.00")),
            valor=Decimal("700.00"),
            data=DIA,
        ),
        "comprovante_sem_par": montar_pergunta_do_comprovante(valor=Decimal("385.80"), data=DIA),
        "desempate_de_pagamento": montar_pergunta_de_desempate(forma="pix", candidatas=[venda]),
        "reenvio": PEDIDO_DE_REENVIO,
        "comprovante_repetido": montar_aviso_de_comprovante_repetido(_comprovante_ja_lido()),
        "correcao_duplicada": AVISO_DE_CORRECAO_DUPLICADA,
        "correcao_ambigua": AVISO_DE_CORRECAO_AMBIGUA,
        "chave_desconhecida": montar_aviso_de_chave_desconhecida(chave="+55 71 99984 0879"),
        "fechamento": montar_fala_do_fechamento(extrato),
        "tudo_conciliado": TUDO_CONCILIADO,
        "cobranca": montar_recibo_da_cobranca(
            descricao="3RJ Suporte/Anúncio: 3 DIAS", valor=Decimal("385.80"), data=DIA
        ),
        "cobranca_duplicada": montar_aviso_de_cobranca_duplicada(
            descricao="3RJ Suporte/Anúncio: 3 DIAS", valor=Decimal("385.80"), data=DIA
        ),
        "quitacao": montar_confirmacao_de_quitacao(
            cobranca=_cobranca(), valor=Decimal("385.80"), data=DIA
        ),
        "comprovante_ambiguo": montar_pergunta_do_comprovante_ambiguo(
            cobranca=_cobranca(), valor=Decimal("385.80"), data=DIA
        ),
        "rotina_da_manha": manha,
    }


def test_toda_fala_do_agente_e_reconhecida_como_dele() -> None:
    """Se esta lista quebrar, o corte de eco ficou com um buraco do tamanho da fala nova."""
    nao_reconhecidas = {
        nome: fala for nome, fala in _falas_do_agente().items() if not e_fala_do_agente(fala)
    }
    assert nao_reconhecidas == {}


def test_fala_de_humano_do_grupo_nunca_e_confundida_com_a_do_agente() -> None:
    """As mensagens reais do export — inclusive as que tem emoji e cifra — continuam passando."""
    do_grupo = [
        "Atendimento no nosso local \nCliente Gabriel \nPerfil bianca/yasmin \n700 1h",
        "Foi pix ou din ?",
        "Dinheiro",
        "Sim",
        "Torre 2 Apt 2706",
        "*3RJ Suporte/Anúncio:*\n3 DIAS | R$ 385,80",
        "Yasmin confere por favor \n\n600 pix \n600 pix",
        "✅",  # o "ok" de emoji, que um humano manda e o agente nunca manda sozinho
        "Já registrei o pagamento no caderno",  # comeca com a palavra, nao com o prefixo
    ]
    assert [fala for fala in do_grupo if e_fala_do_agente(fala)] == []
