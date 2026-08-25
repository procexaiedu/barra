"""ADR-0049 §5 / ticket 05 — chave desconhecida RECORRENTE vira sugestao, nao alarme repetido.

O defeito que isto conserta nao e tecnico, e de atencao humana: o ⚠️ "esse Pix foi pra uma chave
fora da lista da casa" disparava a cada comprovante, e a ata mostra que os casos legitimos se
repetem toda semana (a modelo pagando uma divida pessoal, um fornecedor, a conta nova dela depois
de trocar de banco). Um alarme que dispara sempre para a mesma coisa deixa de ser alarme.

Aqui mora so a decisao pura — sem banco, sem HTTP. A fila derivada e o silencio no grupo estao em
`tests/integracao/test_chave_desconhecida_recorrente.py`.
"""

from datetime import date
from decimal import Decimal
from uuid import uuid4

from barra.dominio.grupo_financeiro.comprovante import (
    MINIMO_PARA_SUGERIR,
    ChaveComDono,
    ChaveVista,
    QuemMandou,
    deve_avisar_destino_fora_da_casa,
    montar_pergunta_da_sugestao,
    sugestoes_de_cadastro,
)

YASMIN = QuemMandou(modelo_id=uuid4(), nome="Yasmin")
BIANCA = QuemMandou(modelo_id=uuid4(), nome="Bianca")


def _vista(
    chave: str = "agiota@pix.example",
    *,
    vezes: int = 4,
    primeiro_em: date = date(2026, 7, 30),
    ultimo_em: date = date(2026, 8, 20),
    quem: tuple[QuemMandou, ...] = (YASMIN,),
    valor_total: Decimal = Decimal("1200.00"),
) -> ChaveVista:
    return ChaveVista(
        chave=chave,
        vezes=vezes,
        primeiro_em=primeiro_em,
        ultimo_em=ultimo_em,
        valor_total=valor_total,
        quem_mandou=quem,
    )


# --- 1. o alarme no grupo: so a primeira vez ----------------------------------------------------


def test_a_primeira_aparicao_de_um_destino_desconhecido_avisa() -> None:
    """O caso que merece alarme e continua tendo: destino novo recebendo dinheiro de venda."""
    assert deve_avisar_destino_fora_da_casa(da_modelo=False, vezes_antes=0) is True


def test_a_repeticao_do_mesmo_destino_nao_repete_o_aviso() -> None:
    """O criterio central do ticket. Da segunda vez em diante a informacao nao some — ela muda de
    canal: vai para a fila do painel, com contagem, periodo e um botao que resolve a duvida."""
    assert deve_avisar_destino_fora_da_casa(da_modelo=False, vezes_antes=1) is False
    assert deve_avisar_destino_fora_da_casa(da_modelo=False, vezes_antes=9) is False


def test_a_chave_da_propria_modelo_continua_falando_sempre() -> None:
    """A excecao, e ela nao e um esquecimento: "esse Pix caiu na conta dela" nao e alarme, e a
    ATRIBUICAO do dinheiro daquela venda (ADR-0047 §2). Vale por comprovante, nao por chave —
    calar na segunda esconderia de qual venda a casa nao recebeu."""
    assert deve_avisar_destino_fora_da_casa(da_modelo=True, vezes_antes=7) is True


# --- 2. a fila de sugestoes ---------------------------------------------------------------------


def test_a_primeira_aparicao_nao_entra_na_fila() -> None:
    """Ela ja teve o ⚠️ no grupo. A fila existe para a chave que VOLTOU."""
    assert sugestoes_de_cadastro([_vista(vezes=1)], []) == ()
    assert MINIMO_PARA_SUGERIR == 2


def test_a_partir_do_segundo_aparecimento_ela_entra_com_contagem_e_periodo() -> None:
    vista = _vista(vezes=2, primeiro_em=date(2026, 8, 19), ultimo_em=date(2026, 8, 20))

    (sugerida,) = sugestoes_de_cadastro([vista], [])

    assert sugerida.vezes == 2
    assert sugerida.dias == 1
    assert sugerida.de_uma_modelo_so == YASMIN


def test_chave_ja_cadastrada_nao_e_sugerida() -> None:
    """Cadastrar E o gesto que tira a linha da fila: a fila e derivada, nao uma tabela que alguem
    tem que lembrar de limpar. Vale para QUALQUER papel — inclusive `terceiro`, que existe
    justamente para parar de perguntar sobre o agiota do exemplo do dono."""
    registro = [ChaveComDono(chave="agiota@pix.example", papel="terceiro", titular="Erick")]

    assert sugestoes_de_cadastro([_vista()], registro) == ()


def test_chave_cadastrada_com_outra_pontuacao_tambem_nao_e_sugerida() -> None:
    """O OCR le a grafia da tela do banco; quem cadastrou digitou outra. Se a fila comparasse
    literal, a mesma chave voltaria a pedir classificacao depois de classificada."""
    registro = [ChaveComDono(chave="+55 71 99984-0879", papel="casa", titular="Elite Ltda")]

    assert sugestoes_de_cadastro([_vista(chave="+5571999840879")], registro) == ()


def test_chave_inativa_conta_como_explicada() -> None:
    """Inativar nunca deletar: a conta desligada tem dono e continua explicando comprovante
    antigo. Sugeri-la de novo seria pedir ao gestor que classificasse duas vezes a mesma conta."""
    registro = [
        ChaveComDono(chave="agiota@pix.example", papel="terceiro", titular="Erick", ativo=False)
    ]

    assert sugestoes_de_cadastro([_vista()], registro) == ()


def test_a_fila_poe_em_cima_a_que_mais_apareceu() -> None:
    """A fila e curta e o que custa caro e o destino que mais recebeu sem nome."""
    fila = sugestoes_de_cadastro(
        [_vista("pouco@pix", vezes=2), _vista("muito@pix", vezes=9)],
        [],
    )

    assert [s.chave for s in fila] == ["muito@pix", "pouco@pix"]


def test_a_fila_nao_escreve_nada() -> None:
    """ "Sugestao nunca vira cadastro sozinha" (criterio do ticket), dito em codigo: a funcao e
    pura e o registro que ela recebeu sai intacto — nao existe caminho que a promova a linha."""
    registro: list[ChaveComDono] = []

    sugestoes_de_cadastro([_vista()], registro)

    assert registro == []


# --- 3. a pergunta que o gestor le --------------------------------------------------------------


def test_a_pergunta_e_a_frase_do_adr() -> None:
    vista = _vista(vezes=4, primeiro_em=date(2026, 7, 30), ultimo_em=date(2026, 8, 20))

    assert montar_pergunta_da_sugestao(vista) == (
        "Apareceu 4 vezes em 3 semanas, sempre recebendo da Yasmin — de quem é?"
    )


def test_com_varias_modelos_a_pergunta_conta_quantas() -> None:
    """A mesma chave desconhecida recebendo de tres modelos e outra conversa — e nomear uma delas
    seria escolher uma suspeita sem motivo."""
    vista = _vista(quem=(YASMIN, BIANCA))

    assert "recebendo de 2 modelos" in montar_pergunta_da_sugestao(vista)
    assert vista.de_uma_modelo_so is None


def test_tudo_no_mesmo_dia_nao_vira_periodo_falso() -> None:
    """Duas fotos na mesma noite sao recorrencia, mas nao sao "em 0 dias"."""
    vista = _vista(vezes=2, primeiro_em=date(2026, 8, 20), ultimo_em=date(2026, 8, 20))

    assert "Apareceu 2 vezes no mesmo dia" in montar_pergunta_da_sugestao(vista)


def test_a_janela_longa_vira_meses() -> None:
    vista = _vista(vezes=6, primeiro_em=date(2026, 5, 22), ultimo_em=date(2026, 8, 20))

    assert "em 3 meses" in montar_pergunta_da_sugestao(vista)


def test_sem_modelo_nenhuma_a_pergunta_ainda_e_uma_pergunta() -> None:
    """Defesa de borda: sem grupo resolvido, a frase encolhe mas continua perguntavel."""
    assert montar_pergunta_da_sugestao(_vista(quem=())).endswith("— de quem é?")
