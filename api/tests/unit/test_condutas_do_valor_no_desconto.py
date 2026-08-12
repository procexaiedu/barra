"""As três condutas de 11/08/2026 que dividem o bloco `<desconto>` — e a ordem em que elas ficam.

1. **Oferta condicionada ao dia** (ADR-0041): com o dia desconhecido, a condição viaja DENTRO da
   oferta em vez de virar interrogatório. Substitui a sonda seca ("Seria hoje ?") no caso do SALTO.
2. **Subir o tempo antes de descer o preço**: o `<desconto>` só sabia DESCER o tempo ("250
   30minutos amor"); faltava o movimento inverso, que é a jogada ANTERIOR à escada.
3. **Cartão ativo e sem taxa**: era passivo (só se ele pedisse) e falava do acréscimo da
   maquininha. Vira a última carta antes de perder a venda, e a taxa some da fala.

As três entram no MESMO bloco, e três inserções individualmente certas podem ser coletivamente
incoerentes: o que este teste fixa é a ORDEM lida de cima a baixo (defender → subir o tempo →
descer o tempo → o dia decide o preço → segunda rodada → recusa e cartão) e a precedência entre as
três regras que disputam o mesmo turno.

Sem DB, sem crédito: lê o prefixo geral pelo caminho real (`render_prefixo_geral`).
"""

import re

from barra.agente.persona import render_prefixo_geral


def _bloco(nome: str) -> str:
    texto = render_prefixo_geral()
    achado = re.search(rf"^<{nome}>$(.*?)^</{nome}>$", texto, re.S | re.M)
    assert achado is not None, f"bloco <{nome}> sumiu do BP_GERAL"
    return achado.group(1)


def _degraus() -> list[str]:
    """Os degraus numerados do `<desconto>`, na ordem em que ele é lido — cada um com os
    sub-itens indentados que pertencem a ele (o degrau do DIA mora quase todo neles)."""
    return re.findall(r"^\d+\. (.+?)(?=^\d+\. |\Z)", _bloco("desconto"), re.M | re.S)


# --- a ordem final da escada ----------------------------------------------------------------------


def test_a_escada_tem_seis_degraus_na_ordem_da_decisao() -> None:
    """Subir o tempo vem ANTES de descer o tempo, que vem antes de descer o preço: a leitura de
    cima a baixo é a maior venda primeiro, a menor depois, e o desconto por último."""
    degraus = _degraus()

    assert len(degraus) == 6, f"o <desconto> mudou de tamanho: {len(degraus)} degraus"
    assert degraus[0].startswith("Defenda o valor primeiro")
    assert degraus[1].startswith("Antes de descer QUALQUER preço, suba o TEMPO")
    assert "desça o tempo, não o preço" in degraus[2]
    assert "é o DIA do encontro que decide o seu desconto" in degraus[3]
    assert degraus[4].startswith("Só quando o encontro é para OUTRO DIA")
    assert "não há oferta nova" in degraus[5]


def test_a_precedencia_das_tres_regras_que_disputam_o_turno_esta_escrita() -> None:
    """Defender (degrau 1) x aceitar o número DELE (ADR-0040) x subir o tempo (degrau 2). O
    primeiro degrau já carrega a exceção do ADR-0040 ("a escada nem começa"), e o degrau 2 declara
    que é a jogada ANTERIOR à escada — não uma resposta à objeção."""
    degraus = _degraus()

    # o número dele vence a defesa, e o dono da decisão é o bloco do contexto
    assert "há um caso em que a escada nem começa" in degraus[0]
    assert "<valor_dele_serve>" in degraus[0]
    # subir o tempo declara a sua posição na fila, e que não gasta desconto
    assert "jogada ANTERIOR à escada, não uma resposta à objeção" in degraus[1]
    assert "preço só desce depois que o tempo não colou" in degraus[1]
    assert "subir o tempo não gasta desconto nenhum" in degraus[1]


# --- 1. oferta condicionada ao dia ------------------------------------------------------------------


def test_o_degrau_do_dia_traz_a_excecao_do_salto_e_aponta_o_bloco_do_contexto() -> None:
    dia = _degraus()[3]

    assert "SALTO sobre o que ele já ouviu" in dia
    assert "<oferta_condicionada_ao_dia>" in dia
    assert "traz os DOIS números prontos" in dia
    # o segundo número nunca sai de cabeça — sem o par no contexto a exceção não existe
    assert "O segundo número você NUNCA improvisa" in dia
    # e a sonda do dia continua sendo a regra FORA da exceção (não foi revogada em geral)
    assert "Fora dela, defenda o valor e descubra o dia" in dia


# --- 2. subir o tempo -------------------------------------------------------------------------------


def test_subir_o_tempo_entrega_dado_e_nao_prescreve_a_pergunta() -> None:
    """O dono do produto: "tem que acontecer de forma natural, não um script". O bloco aponta o
    dado do contexto e proíbe frase pronta — a fala é dela."""
    subir = _degraus()[1]

    assert "<pacote_maior_na_sua_tabela>" in subir
    assert "com as SUAS palavras" in subir
    assert "não existe fala pronta pra isso" in subir
    assert "nunca a mesma frase duas vezes" in subir
    # nenhuma pergunta literal foi prescrita no degrau
    assert "?" not in subir.replace('"Seria hoje ?"', "")


def test_sondar_o_tempo_nao_se_confunde_com_sondar_o_dia() -> None:
    """O detalhe que quase passa batido no print da vendedora: ela JÁ sabia que era hoje. A
    pergunta era de DURAÇÃO, não de DIA — e as duas têm regras (e disciplinas) diferentes."""
    subir = _degraus()[1]

    assert "Sondar o TEMPO não é sondar o DIA" in subir
    assert "tem regra própria e não substitui esta" in subir


def test_o_valor_do_pacote_maior_e_o_cheio_da_tabela() -> None:
    """O "valor especial" da vendedora não custou nada: 800 é o preço CHEIO da 2h. O prompt não
    pode deixar isso virar licença para inventar número abaixo da tabela."""
    subir = _degraus()[1]

    assert "no valor CHEIO da tabela" in subir
    assert "nunca um número abaixo da tabela" in subir


# --- 3. cartão --------------------------------------------------------------------------------------


def test_o_cartao_e_ativo_no_ultimo_degrau_e_nao_e_rodada_nova() -> None:
    desconto = _bloco("desconto")
    ultimo = _degraus()[5]

    assert "o cartão sai de VOCÊ" in ultimo and "sem esperar ele pedir" in ultimo
    assert "Cartão não é número novo nem rodada nova" in ultimo
    # ele entra ENTRE a recusa e a escalada, não depois dela
    assert ultimo.index("Poxa amor não consigo") < ultimo.index("CARTÃO")
    assert ultimo.index("CARTÃO") < ultimo.index("fora_de_oferta")
    # e responder um pedido dele continua valendo em qualquer ponto
    assert "Cartão você aceita em qualquer ponto se ELE perguntar" in desconto


def test_a_taxa_do_cartao_sumiu_da_fala() -> None:
    """Decisão do dono: maquininha/acréscimo/taxa não existem mais na boca dela — nem com número,
    nem com o "normal do cartão"."""
    desconto = _bloco("desconto")

    assert "tem o acréscimo da maquininha" not in desconto
    assert "normal do cartão rs" not in desconto
    assert "taxa, acréscimo e maquininha NÃO existem na sua fala" in _degraus()[5]


# --- os pares de <armadilhas_de_voz> ----------------------------------------------------------------


def _pares() -> list[tuple[str, str, str]]:
    return re.findall(
        r"<par><errado>(.*?)</errado><certo>(.*?)</certo><porque>(.*?)</porque></par>",
        _bloco("armadilhas_de_voz"),
    )


def test_cada_conduta_nova_ganhou_o_seu_par_de_armadilha() -> None:
    """Todo exemplo literal que entra no prompt precisa do par que proíbe repeti-lo — é o que
    impede a conduta nova de virar o próximo tique ("Seria hoje ?" virou um, medido em prod)."""
    pares = _pares()

    condicionada = [p for p in pares if "<oferta_condicionada_ao_dia>" in p[0]]
    tempo = [p for p in pares if "qual era o valor mesmo" in p[0]]
    cartao = [p for p in pares if "maquininha" in p[0]]

    assert len(condicionada) == 1 and len(tempo) == 1 and len(cartao) == 1


def test_o_par_da_oferta_condicionada_proibe_a_sonda_e_exige_variacao() -> None:
    errado, certo, porque = next(p for p in _pares() if "<oferta_condicionada_ao_dia>" in p[0])

    # o lado ERRADO é a conduta revogada: defender e perguntar o dia
    assert "Seria hoje ?" in errado
    # o lado CERTO diz os dois números, com a condição dentro da oferta
    assert "600" in certo and "700" in certo
    # e o porquê carrega a proibição de repetir a própria bolha do exemplo
    assert "a do exemplo inclusive" in porque
    assert "números ilustrativos" in porque


def test_o_par_do_tempo_nao_prescreve_pergunta_nenhuma() -> None:
    errado, certo, porque = next(p for p in _pares() if "qual era o valor mesmo" in p[0])

    # o errado é repetir o número que ele já ouviu
    assert "400 1h no meu local" in errado
    # o certo é descrição de intenção entre parênteses, no formato dos vizinhos — não uma frase
    assert certo.strip().startswith("(ele já ouviu")
    assert "com as suas palavras" in certo
    assert "sondar o TEMPO não é sondar o DIA" in porque


def test_o_par_do_cartao_tira_a_taxa_e_mantem_o_convite_ativo() -> None:
    errado, certo, porque = next(p for p in _pares() if "maquininha" in p[0])

    assert "acréscimo da maquininha" in errado
    assert "maquininha" not in certo and "acréscimo" not in certo
    assert "sem ele pedir" in porque
    assert "cartão não é desconto" in porque
