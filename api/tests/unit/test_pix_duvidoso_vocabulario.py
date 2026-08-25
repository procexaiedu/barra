"""Ticket 07 — o "Pix duvidoso" tem UM vocabulario, e ele vale nos dois caminhos.

A capacidade existia pela metade e so de um lado: `workers/pix.py` extraia `plausibilidade_visual`
e nomeava a duvida com palavras proprias ("plausibilidade", "legibilidade", "valor", "chave"),
enquanto o comprovante do Grupo financeiro nao tinha sinal de plausibilidade nem nome para as
duvidas que ja detectava. O painel tinha um terceiro conjunto de slugs que o backend nunca
escreveu.

Estes testes sao puros (sem banco, sem provider): o vocabulario, a precedencia e a decisao de
falar-ou-nao sao dominio, e essa e a razao de terem saido de dentro das cadeias `if/elif`.
"""

from __future__ import annotations

from decimal import Decimal
from typing import get_args
from uuid import uuid4

from barra.dominio.grupo_financeiro.comprovante import (
    DESCONHECIDA,
    MOTIVOS_DE_SUSPEITA,
    PRECEDENCIA_DA_SUSPEITA,
    EstabelecimentoComDono,
    LeituraDoComprovante,
    MotivoDeSuspeita,
    PapelResolvido,
    deve_falar_no_grupo,
    ler_suspeita,
    marcar_suspeita,
    papel_do_estabelecimento,
    suspeita_do_comprovante,
    suspeita_mais_grave,
)
from barra.dominio.pix.schemas import REJEICAO_SUGERIDA, MotivoRejeicao

# --- o vocabulario e fechado, e as tres copias dele nao podem divergir -------------------------


def test_a_precedencia_cobre_o_vocabulario_inteiro() -> None:
    """Motivo sem lugar na ordem seria motivo que `suspeita_mais_grave` nunca devolve — e ele
    sumiria em silencio no dia em que disparasse junto com outro."""
    assert set(PRECEDENCIA_DA_SUSPEITA) == set(get_args(MotivoDeSuspeita))
    assert len(PRECEDENCIA_DA_SUSPEITA) == len(set(PRECEDENCIA_DA_SUSPEITA))
    assert MOTIVOS_DE_SUSPEITA == frozenset(get_args(MotivoDeSuspeita))


def test_toda_suspeita_tem_uma_rejeicao_sugerida_valida() -> None:
    """A ponte maquina->humano nao pode ter buraco: um motivo sem sugestao devolveria `undefined`
    no dialogo de rejeicao do painel, que e o mesmo defeito que este ticket veio consertar."""
    assert set(REJEICAO_SUGERIDA) == set(get_args(MotivoDeSuspeita))
    assert set(REJEICAO_SUGERIDA.values()) <= set(get_args(MotivoRejeicao))


def test_montagem_tem_veredito_proprio_e_nao_cai_em_outro() -> None:
    """O "Pix zoado" da ata: antes do ticket 07 o operador so tinha `outro` para fraude, e a
    fraude ficava indistinguivel de tudo que nao tem nome."""
    assert "comprovante_falso" in get_args(MotivoRejeicao)
    assert REJEICAO_SUGERIDA["imagem_implausivel"] == "comprovante_falso"


# --- o carimbo em `motivo_em_revisao` ----------------------------------------------------------


def test_marcar_e_ler_devolvem_o_motivo_e_a_prosa_inteira() -> None:
    marcado = marcar_suspeita("valor_abaixo_do_esperado", "valor extraido 80.00 < esperado R$100")
    assert marcado.startswith("valor_abaixo_do_esperado: ")
    assert ler_suspeita(marcado) == (
        "valor_abaixo_do_esperado",
        "valor extraido 80.00 < esperado R$100",
    )


def test_o_detalhe_pode_ter_dois_pontos_dentro() -> None:
    """A prosa de hoje ja usa ":" internamente ("vision inconclusivo: finish_reason=length"). So o
    PRIMEIRO separador e limite — se o corte fosse por todos, o detalhe chegaria picado ao painel."""
    marcado = marcar_suspeita("sem_leitura", "vision inconclusivo: finish_reason=length")
    assert ler_suspeita(marcado) == ("sem_leitura", "vision inconclusivo: finish_reason=length")


def test_prosa_antiga_sem_carimbo_volta_inteira_sem_motivo() -> None:
    """Fail-open: toda linha gravada antes deste ticket tem prosa crua. Um parser estrito
    transformaria o historico inteiro em "motivo desconhecido" e apagaria o detalhe da tela."""
    assert ler_suspeita("chave divergente: extraida x, esperada y") == (
        None,
        "chave divergente: extraida x, esperada y",
    )
    assert ler_suspeita(None) == (None, "")
    assert ler_suspeita("") == (None, "")


def test_palavra_qualquer_antes_do_separador_nao_vira_motivo() -> None:
    """Closed-world tambem aqui: so os sete motivos do vocabulario contam como carimbo."""
    assert ler_suspeita("bagunca: alguma coisa") == (None, "bagunca: alguma coisa")


# --- a precedencia, que e a mesma dos dois lados -----------------------------------------------


def test_a_montagem_ganha_do_valor_a_menor() -> None:
    """Se a imagem e ficcao, o valor dela tambem e: reportar "valor a menor" de um comprovante
    falso e discutir o numero errado."""
    assert (
        suspeita_mais_grave(["valor_abaixo_do_esperado", "imagem_implausivel"])
        == "imagem_implausivel"
    )


def test_a_foto_repetida_ganha_de_tudo() -> None:
    assert (
        suspeita_mais_grave(["titular_divergente", "imagem_repetida", "sem_leitura"])
        == "imagem_repetida"
    )


def test_dinheiro_faltando_ganha_de_nome_que_nao_bate() -> None:
    assert (
        suspeita_mais_grave(["titular_divergente", "valor_abaixo_do_esperado"])
        == "valor_abaixo_do_esperado"
    )


def test_sem_sinal_nenhum_nao_ha_suspeita() -> None:
    assert suspeita_mais_grave([]) is None
    assert suspeita_mais_grave([None, None]) is None


# --- o comprovante do grupo, agora com as mesmas palavras --------------------------------------


def _leitura(**campos: object) -> LeituraDoComprovante:
    base: dict[str, object] = {
        "e_comprovante": True,
        "legivel": True,
        "valor": Decimal("1200.00"),
    }
    base.update(campos)
    return LeituraDoComprovante(**base)  # type: ignore[arg-type]


def test_comprovante_limpo_para_destino_conhecido_nao_e_suspeito() -> None:
    casa = PapelResolvido(papel="casa")
    assert suspeita_do_comprovante(_leitura(), destino=casa) is None


def test_a_plausibilidade_nasce_verdadeira_e_nao_acusa_ninguem() -> None:
    """⚠️ O campo e novo e o leitor ainda nao o preenche. Se o default fosse `False`, o silencio
    do OCR viraria suspeita de fraude sobre TODO comprovante do grupo, de uma vez."""
    assert _leitura().plausivel is True
    assert suspeita_do_comprovante(_leitura(), destino=PapelResolvido(papel="casa")) is None


def test_montagem_no_grupo_usa_a_palavra_do_outro_caminho() -> None:
    suspeita = suspeita_do_comprovante(
        _leitura(plausivel=False, motivo_se_implausivel="fonte trocada no valor"),
        destino=PapelResolvido(papel="casa"),
    )
    assert suspeita == "imagem_implausivel"


def test_foto_repetida_ganha_mesmo_com_a_imagem_perfeita() -> None:
    """A dedup por foto do grupo (sha256 do conteudo) nao muda de comportamento — ela ganha nome."""
    assert suspeita_do_comprovante(_leitura(), repetida=True) == "imagem_repetida"
    assert suspeita_do_comprovante(_leitura(plausivel=False), repetida=True) == "imagem_repetida"


def test_falha_nossa_e_sem_leitura_e_nao_duvida_da_modelo() -> None:
    assert suspeita_do_comprovante(None) == "sem_leitura"


def test_valor_ilegivel_ou_zerado_e_imagem_ilegivel() -> None:
    casa = PapelResolvido(papel="casa")
    assert suspeita_do_comprovante(_leitura(legivel=False), destino=casa) == "imagem_ilegivel"
    assert suspeita_do_comprovante(_leitura(valor=None), destino=casa) == "imagem_ilegivel"
    assert (
        suspeita_do_comprovante(_leitura(valor=Decimal("0.00")), destino=casa) == "imagem_ilegivel"
    )


def test_destino_fora_do_cadastro_e_destino_desconhecido() -> None:
    assert suspeita_do_comprovante(_leitura(), destino=DESCONHECIDA) == "destino_desconhecido"


def test_terceiro_cadastrado_nao_e_suspeito() -> None:
    """`terceiro` existe justamente para o cadastro poder dizer "conheco esta chave e ela nao e da
    operacao" e PARAR de alarmar (ADR-0049 §5). Se ele contasse como suspeita, cadastrar o agiota
    do exemplo nao adiantaria nada."""
    assert suspeita_do_comprovante(_leitura(), destino=PapelResolvido(papel="terceiro")) is None


def test_a_chave_da_propria_modelo_nao_e_suspeita() -> None:
    dona = uuid4()
    dela = PapelResolvido(papel="modelo", dono_id=dona, dono_nome="Yasmin")
    assert suspeita_do_comprovante(_leitura(), destino=dela) is None


def test_o_cartao_entra_pela_MESMA_funcao_pelo_estabelecimento() -> None:
    """O print da maquininha nao tem chave, mas responde a mesma pergunta com o mesmo tipo
    (`PapelResolvido`) — entao a suspeita dele nao precisa de uma linha propria."""
    registro = (EstabelecimentoComDono(nome="PagBank * Elite", papel="casa"),)
    leitura = _leitura(e_comprovante=False, e_de_cartao=True, estabelecimento="PAGBANK *ELITE")
    conhecida = papel_do_estabelecimento(leitura.estabelecimento, registro)
    assert suspeita_do_comprovante(leitura, destino=conhecida) is None

    desconhecida = papel_do_estabelecimento("INFINITEPAY *YAS", registro)
    assert suspeita_do_comprovante(leitura, destino=desconhecida) == "destino_desconhecido"


# --- suspeita nunca trava, e nem sempre fala ---------------------------------------------------


def test_a_acusacao_de_montagem_nao_sai_no_grupo() -> None:
    """Quem postou a foto e a modelo (ou a gestora dela). "Esse comprovante parece montagem" dito
    num grupo de trabalho e uma acusacao publica feita por um robo a partir de um palpite de OCR —
    e, se ela estiver certa, avisar so ensina a fazer uma montagem melhor. A duvida vale, mas vale
    no painel."""
    assert deve_falar_no_grupo("imagem_implausivel") is False


def test_falha_nossa_tambem_morre_calada() -> None:
    """Pedir reenvio enquanto o provider esta fora e um loop que ela paga com paciencia."""
    assert deve_falar_no_grupo("sem_leitura") is False


def test_o_que_ja_falava_continua_falando() -> None:
    assert deve_falar_no_grupo("imagem_ilegivel") is True
    assert deve_falar_no_grupo("imagem_repetida") is True
    assert deve_falar_no_grupo("destino_desconhecido") is True


def test_comprovante_sem_suspeita_nao_tem_o_que_falar() -> None:
    assert deve_falar_no_grupo(None) is False


# --- o filtro do painel casa o carimbo ---------------------------------------------------------


class _FiltroCapturado:
    """Guarda o SQL e os params de `listar_pix` — o que interessa aqui e a clausula, nao a linha."""

    def __init__(self) -> None:
        self.query = ""
        self.params: list[object] = []

    async def execute(self, query: str, params: list[object] | None = None) -> _FiltroCapturado:
        self.query = query
        self.params = list(params or [])
        return self

    async def fetchall(self) -> list[dict[str, object]]:
        return []


async def test_o_filtro_do_painel_casa_o_motivo_carimbado() -> None:
    """O dropdown manda o slug; a coluna guarda "slug: prosa". Igualdade exata devolvia lista
    vazia para TODO motivo — o filtro existia e nunca achou nada. Prefixo casa o slug e deixa o
    detalhe livre."""
    from barra.dominio.pix.routes import listar_pix

    conn = _FiltroCapturado()
    await listar_pix(conn=conn, limit=50, motivo_em_revisao="destino_desconhecido")  # type: ignore[arg-type]

    assert "p.motivo_em_revisao LIKE %s" in conn.query
    padrao = next(p for p in conn.params if isinstance(p, str) and p.startswith("destino_"))
    gravado = marcar_suspeita("destino_desconhecido", "chave divergente: extraida x@y.com")
    assert padrao == "destino_desconhecido: %"
    assert gravado.startswith(padrao[:-1])


async def test_o_filtro_nao_confunde_dois_motivos_com_o_mesmo_comeco() -> None:
    """`titular_divergente` nao pode arrastar linha de outro motivo: o separador faz parte do
    padrao, entao o prefixo casa o slug INTEIRO, nunca um pedaco dele."""
    from barra.dominio.pix.routes import listar_pix

    conn = _FiltroCapturado()
    await listar_pix(conn=conn, limit=50, motivo_em_revisao="titular_divergente")  # type: ignore[arg-type]

    padrao = next(p for p in conn.params if isinstance(p, str) and p.startswith("titular_"))
    outro = marcar_suspeita("destino_desconhecido", "qualquer coisa")
    assert not outro.startswith(padrao[:-1])


async def test_prosa_antiga_continua_alcancavel_pela_igualdade() -> None:
    """Toda linha gravada antes do carimbo e prosa crua, sem slug. Ela so existe inteira — um LIKE
    de prefixo por vocabulario nunca a acharia, e por isso o caminho de igualdade fica."""
    from barra.dominio.pix.routes import listar_pix

    conn = _FiltroCapturado()
    await listar_pix(conn=conn, limit=50, motivo_em_revisao="vision inconclusivo")  # type: ignore[arg-type]

    assert "p.motivo_em_revisao = %s" in conn.query
    assert "vision inconclusivo" in conn.params
