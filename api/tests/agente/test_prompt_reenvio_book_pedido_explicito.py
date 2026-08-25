"""Deadlock foto×confirmação no fechamento (campanha 13/08, caso eb04:157801611563258 t8-t12).

O cliente condicionou a confirmação a uma mídia atual TRÊS vezes ("me manda uma foto ou vídeo
atual mesmo que eu confirmo na hora o horário") e o modelo recusou verbalmente todas ("As minhas
fotos e o vídeo já estão aí com você amor") sem nunca chamar `enviar_midia` — com mídia seedada
disponível. Causa: a trava anti-flood do book ("<ja_enviou_book> → NÃO reenvie, redirecione")
não tinha exceção para pedido EXPLÍCITO de prova, e o próprio `<midia>` fornecia a fala da recusa
("As minhas fotos estão aí amor") como ilustração — o modelo seguiu a letra e a venda travou:
ele não confirma sem ver, ela não manda porque "já mandou".

O fix vive em DUAS superfícies (corrigir uma e deixar a outra é não corrigir): a tag dinâmica
`<ja_enviou_book>` (contexto_dinamico.md.j2 — presente no turno do pedido, gated só por
`book_ja_enviado`, independente de estado) e o bloco estático `<midia>` (regras.md.j2 — renderiza
todo turno). A exceção é condicionada ao pedido explícito dele (gatilho no contexto do turno, não
tique), nomeia a recusa verbal como proibida (negação ativa) e dá a conduta substituta: chamar
`enviar_midia` e cravar a confirmação na MESMA mensagem, UMA vez — dúvida repetida sem pedido
explícito continua não reabrindo o envio (anti-flood preservado).
"""

from barra.agente.persona import render_contexto_dinamico, render_prefixo_geral


def _tag_ja_enviou_book() -> str:
    out = render_contexto_dinamico(
        numero_curto=7,
        estado="Qualificado",
        slots_faltantes=[],
        proximo_passo="cravar o horário",
        pix_status="não aplicável",
        book_ja_enviado=True,
    )
    inicio = out.index("<ja_enviou_book>")
    fim = out.index("</ja_enviou_book>")
    return out[inicio:fim]


def test_tag_ja_enviou_book_tem_excecao_de_pedido_explicito() -> None:
    """A tag dinâmica — a superfície mais próxima do turno — carrega a exceção completa:
    gatilho (pedido explícito), recusa nomeada como proibida, e a conduta substituta
    (enviar_midia + confirmação na mesma mensagem)."""
    tag = _tag_ja_enviou_book()
    # A trava anti-flood continua de pé...
    assert "NÃO reenvie" in tag
    # ...mas com a exceção do pedido explícito vencendo a trava.
    assert "EXCEÇÃO única" in tag
    assert "PEDINDO explicitamente" in tag
    # Negação ativa: a recusa verbal é nomeada como o comportamento proibido nesse gatilho.
    assert "recusa verbal é o comportamento proibido" in tag
    # Conduta substituta: envia e fecha na mesma mensagem, pela ferramenta.
    assert "enviar_midia" in tag
    assert "MESMA mensagem" in tag


def test_tag_ja_enviou_book_nao_reabre_flood() -> None:
    """A exceção é UM reenvio condicionado ao pedido explícito — dúvida repetida sem pedido
    não reabre o envio (o defeito original do flood não volta pela porta da exceção)."""
    tag = _tag_ja_enviou_book()
    assert "UMA vez" in tag
    assert "SEM pedido explícito continua não reabrindo o envio" in tag


def test_midia_estatico_tem_a_mesma_excecao() -> None:
    """O bloco <midia> de regras.md.j2 (renderiza TODO turno, sem gate de fase) tinha a trava
    absoluta E a ilustração da recusa — as duas superfícies precisam contar a mesma história."""
    out = render_prefixo_geral()
    midia = out[out.index("<midia>") : out.index("</midia>")]
    assert "EXCEÇÃO única" in midia
    assert "PEDINDO explicitamente" in midia
    assert "recusa verbal é o comportamento proibido" in midia
    assert "enviar_midia e crave a confirmação na MESMA mensagem" in midia
    # Anti-flood preservado no estático também.
    assert "O reenvio vale UMA vez" in midia
    # E a ilustração da recusa ("as fotos já estão aí") ficou explicitamente subordinada
    # à exceção: ela vale pra dúvida SEM pedido novo, nunca por cima do pedido explícito.
    assert "quem manda é a exceção do reenvio" in midia
