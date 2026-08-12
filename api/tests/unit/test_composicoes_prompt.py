"""Taxonomia de COMPOSIÇÕES no prompt (11/08/2026): o `<menage>` virou `<composicoes>`.

O que estes testes seguram é a coerência que um rename silencioso quebra sem erro nenhum:

1. o bloco novo existe e o antigo não sobrou em lugar nenhum do BP_GERAL — uma referência
   cruzada órfã (`<menage>`) manda a IA procurar uma tag que não está no prompt;
2. as quatro composições têm parágrafo próprio, porque é o cardápio que passou a ter quatro
   itens (migration 20260811232000) e o prompt precisa dizer que uma não vale pela outra;
3. o ramo "trazer uma amiga/parceira" (escalada com `outro`) continua INTACTO — ele é de outra
   frente, que vem depois desta e vai revogá-lo; mexer nele agora atrapalha aquele trabalho;
4. os exemplos literais novos ganharam par em `<armadilhas_de_voz>`, com variação obrigatória —
   conduta prescrita como frase literal vira tique (o "Seria hoje ?" já é um, medido em prod).
"""

from typing import Any

from barra.agente.persona import render_fetiches, render_persona

# Cadastro de uma modelo que oferece as DUAS composições "dele" e nenhuma com outra modelo.
_PROGRAMAS: list[dict[str, Any]] = [
    {"nome": "Encontro", "duracao_nome": "1 hora", "duracao_horas": 1, "preco": 400},
    {"nome": "Encontro", "duracao_nome": "2 horas", "duracao_horas": 2, "preco": 700},
]
_AS_QUATRO: list[dict[str, Any]] = [
    {"nome": "Acompanhante dele — mulher", "preco": 1, "cobra_por_pessoa": True},
    {"nome": "Acompanhante dele — homem", "preco": 1, "cobra_por_pessoa": True},
    {"nome": "Dupla de modelos", "preco": 1, "cobra_por_pessoa": True},
    {"nome": "Dois casais (2 modelos)", "preco": 1, "cobra_por_pessoa": True},
]


def test_bloco_composicoes_substitui_o_menage_sem_deixar_referencia_orfa() -> None:
    txt = render_persona()

    assert "\n<composicoes>\n" in txt and "\n</composicoes>\n" in txt
    assert "<menage>" not in txt and "</menage>" not in txt


def test_as_quatro_composicoes_tem_paragrafo_proprio() -> None:
    """O ponto do bloco: cada composição é um item separado, e ter uma não dá a outra."""
    bloco = render_persona().split("\n<composicoes>\n")[1].split("\n</composicoes>")[0]

    assert "a mulher dele" in bloco
    assert "outro homem" in bloco
    assert "trazer uma amiga sua" in bloco
    assert "dois casais" in bloco
    # A regra que faz a ausência virar recusa, escrita no bloco (o dado vem do cardápio).
    assert "a que não está lá você não faz" in bloco
    assert "ter um não é ter o outro" in bloco


def test_rotulo_da_lista_continua_sendo_interno() -> None:
    """A regra que autoriza rótulos de painel descritivos: o nome do item nunca sai na fala."""
    bloco = render_persona().split("\n<composicoes>\n")[1].split("\n</composicoes>")[0]

    assert "rótulo INTERNO" in bloco
    assert "espelha quem ELE disse que vem" in bloco


def test_o_ramo_da_amiga_revoga_a_escalada() -> None:
    """A revogação do ADR-0042, no site que a carregava: o ramo "você trazer uma amiga" NÃO escala
    mais — a modelo do canal fecha a dupla sozinha. Este teste guarda a revogação nos dois sentidos
    (a conduta velha não pode voltar; a nova tem de estar dita), porque a fala revogada é
    exatamente a que o modelo já viu 100 vezes no corpus e reproduz sozinho."""
    bloco = render_persona().split("\n<composicoes>\n")[1].split("\n</composicoes>")[0]

    assert "Deixa eu ver com ela e já te retorno" not in bloco
    assert "escale com outro" not in bloco
    assert "essa venda é SUA e você fecha sozinha" in bloco
    assert "A amiga também é oferta sua de pós-venda" in bloco
    # Os dois casais entram no MESMO ramo (também têm outra modelo dentro).
    assert "ou quer dois casais" in bloco
    # Sem o bloco da parceira no turno, nada disso existe: a recusa closed-world é o default.
    assert "Sem esse bloco no turno, não há amiga a oferecer" in bloco


def test_exemplos_literais_do_bloco_vem_marcados_como_ilustracao() -> None:
    bloco = render_persona().split("\n<composicoes>\n")[1].split("\n</composicoes>")[0]

    assert "Ilustração de forma, não frase pronta" in bloco
    assert "com o valor que estiver na SUA tabela" in bloco


def test_armadilhas_de_voz_ganharam_os_pares_da_composicao() -> None:
    """Cada literal novo do `<composicoes>` tem o seu contra-exemplo na persona — é o par que
    impede a frase de virar script."""
    armadilhas = render_persona().split("<armadilhas_de_voz>")[1].split("</armadilhas_de_voz>")[0]

    # 1. recitar o rótulo interno da lista.
    assert "Faço acompanhante dele mulher sim amor" in armadilhas
    # 2. cotar a composição que NÃO está na lista dela (o ganho closed-world).
    assert "eu e um amigo meu" in armadilhas
    # 3. cotar por cima da palavra ambígua em vez de perguntar quem vem.
    assert "vocês fazem menage?" in armadilhas
    assert "não diz QUEM vem" in armadilhas


def test_fetiches_lista_as_quatro_composicoes_na_secao_por_pessoa() -> None:
    """O render por-modelo com o cadastro novo: as quatro entram na MESMA seção "Por pessoa",
    com o mesmo extra (ADR-0039 — a taxonomia não mexeu em número nenhum)."""
    txt = render_fetiches(_AS_QUATRO, _PROGRAMAS)
    por_pessoa = txt.split("Por pessoa")[1]

    for f in _AS_QUATRO:
        assert f["nome"] in por_pessoa
    # Extra = a linha de 1h (400); a coluna é o total para os dois, e o pacote não dobra.
    assert "| Encontro (1 hora) | R$800 |" in por_pessoa
    assert "| Encontro (2 horas) | R$1.100 |" in por_pessoa
    assert "R$1.400" not in txt  # 700 x 2, o regime revogado do ADR-0035


def test_cardapio_parcial_e_o_que_faz_a_recusa_existir() -> None:
    """O caso da Catarina: com só a composição de MULHER cadastrada, a de homem não aparece em
    lugar nenhum do bloco dela — e "o que não está na lista" é o que a IA recusa."""
    txt = render_fetiches([_AS_QUATRO[0]], _PROGRAMAS)

    assert "Acompanhante dele — mulher" in txt
    assert "homem" not in txt
