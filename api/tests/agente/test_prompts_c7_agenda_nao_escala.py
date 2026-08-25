"""Ciclo 7 — pergunta sobre a PRÓPRIA agenda não é "dúvida", é dado que ela já tem.

Caso medido: `<periodo_de_trabalho>` em `<sem_restricao>`, cliente pergunta "vc vai estar aí na
sexta até que hora?". A IA RESPONDEU na bolha ("Fico sim amor, te espero até 14h rs") e, no mesmo
turno, chamou `escalar` com motivo "outro" — o vendedor real respondeu "Até sexta-feira vida" e
seguiu. Três superfícies se contradiziam e a única muda era justamente a que valia:

1. `bloco_da_modelo.md.j2` — o ramo `<sem_restricao>` dizia só "atende qualquer dia", sem dizer o
   que isso significa quando ELE pergunta até que horas ela fica: sem hora de encerrar, a conduta
   de "período encerrado" não tem o que aplicar e a pergunta fica sem resposta escrita.
2. `regras.md.j2` <nucleo> linha 8 — "situação sem regra → você escala" cobria o buraco de cima:
   sem restrição no bloco, faltar a hora PARECE situação sem regra.
3. `regras.md.j2` <quando_usar_escalar> — "outro = situação grave sem motivo na lista" não excluía
   a pergunta de agenda, e a lista do "não escale o que você resolve sozinha" não a nomeava.
4. `ferramentas/escalada.py` — a docstring de `escalar` (que VIRA a `description` da tool) tem a
   própria lista de "Quando NÃO usar" e também não a nomeava: é a superfície mais perto do dedo.

Corrigir uma e deixar as outras é não corrigir (lição do projeto), por isso os asserts cobrem as
quatro de uma vez. Todos são de leitura do que o modelo VÊ — prompt renderizado e descrição de
tool: o defeito era texto, não código.
"""

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from barra.agente.ferramentas.escalada import escalar
from barra.agente.persona import (
    JANELA_AGENDA_HORAS,
    render_bloco_da_modelo,
    render_prefixo_geral,
)

_PROMPTS = Path(__file__).parents[2] / "src" / "barra" / "agente" / "prompts"

# O cadastro mínimo que o `<periodo_de_trabalho>` precisa. `disponibilidade=[]` é a afirmação
# explícita "esta modelo não tem restrição de horário" — passar a chave (em vez de omitir) é o que
# separa o ramo testado do buraco silencioso do Jinja, que renderiza variável desconhecida como
# VAZIO e cairia no MESMO ramo por acidente.
_SEM_RESTRICAO: dict[str, Any] = {
    "disponibilidade": [],
    "tabela_max_horas": 2.0,
    "sem_fetiches": False,
    "sem_menage": False,
    "sem_video_chamada": False,
    "sem_externo": False,
    "sem_periodo_longo": False,
}

_COM_RESTRICAO: dict[str, Any] = {
    **_SEM_RESTRICAO,
    "disponibilidade": [
        {
            "dia": "sexta",
            "hora_inicio": "10:00",
            "hora_fim": "22:00",
            "data_inicio": "2026-01-01",
            "data_fim": None,
        }
    ],
}


def test_sem_restricao_se_auto_responde_em_vez_de_ficar_mudo() -> None:
    """O ramo `<sem_restricao>` precisa dizer o que a ausência de restrição SIGNIFICA na fala.

    Três coisas, e as três são o que faltava no turno medido: (a) não existe hora de encerrar, logo
    a conduta de folga/expediente encerrado não se aplica; (b) a pergunta "até que horas você fica"
    tem resposta AQUI — disponibilidade ampla, com a hora combinada junto quando já houver; (c) isso
    não é dúvida nem motivo de escalada."""
    bloco = render_bloco_da_modelo(**_SEM_RESTRICAO)

    assert "<sem_restricao>" in bloco
    assert "NÃO tem hora de encerrar" in bloco
    assert 'nada em você "cai fora do período"' in bloco
    assert "até que horas você fica/atende?" in bloco
    assert "se já houver hora combinada neste papo ela vai junto" in bloco
    assert "nunca é dúvida, situação sem regra nem motivo de escalada" in bloco


def test_a_conduta_nova_prescreve_intencao_e_nao_uma_fala_pronta() -> None:
    """Lição "conduta nova vira tique": frase literal no prompt volta idêntica em toda conversa.

    O bloco carrega as PERGUNTAS dele (gatilho a reconhecer) e a intenção, nunca a bolha dela — e
    diz explicitamente que a forma varia. A fala do turno medido ("Fico sim amor, te espero até
    14h rs") não pode virar template."""
    bloco = render_bloco_da_modelo(**_SEM_RESTRICAO)

    assert "a forma é sua e varia a cada conversa, nunca uma fala decorada" in bloco
    assert "Fico sim amor" not in bloco
    assert "te espero até" not in bloco


def test_o_outro_ramo_do_periodo_de_trabalho_continua_intacto() -> None:
    """Guarda do teste de cima: os dois ramos são exclusivos. Sem isto, uma conduta que vazasse
    para o ramo COM restrição diria a uma modelo com expediente que ela não tem hora de encerrar —
    exatamente o oposto do `<observacao>`."""
    com = render_bloco_da_modelo(**_COM_RESTRICAO)

    assert "<observacao>" in com and "é quando você ENCERRA" in com
    assert "<sem_restricao>" not in com
    assert "NÃO tem hora de encerrar" not in com


def test_nucleo_qualifica_a_duvida_sem_afrouxar_a_protecao() -> None:
    """A linha 8 continua valendo inteira para pedido estranho e política inexistente (é ela que
    segura AUP/safety junto das linhas 7 e 9); o que sai da definição de "situação sem regra" é
    só a falta de dado sobre a agenda DELA, que não é falta — está nos blocos."""
    geral = render_prefixo_geral()

    # a proteção original, byte a byte
    assert (
        "Na dúvida — pedido estranho, situação sem regra, política que não existe — você escala."
        in geral
    )
    assert "Improviso perde cliente premium; escalar nunca perde." in geral
    assert "a justificativa é o próprio sinal: pare e escale" in geral

    # a qualificação, apontando para onde o dado mora
    assert 'Falta de dado sobre a sua PRÓPRIA disponibilidade não é "situação sem regra"' in geral
    assert (
        "a sua hora, o seu dia, até quando você fica se respondem pelo "
        "<periodo_de_trabalho>/<agenda>/consultar_agenda" in geral
    )


def test_conduta_de_agenda_cobre_o_caso_sem_restricao() -> None:
    """§190 respondia pergunta de horário com a hora do `<periodo_de_trabalho>`/`<horario_minimo>`
    — e sem restrição não HÁ hora ali. O vazio é o que empurrava pra escalada."""
    geral = render_prefixo_geral()

    assert "Quando o seu <periodo_de_trabalho> não traz restrição de horário" in geral
    assert "você não tem hora de encerrar: a resposta é a sua disponibilidade ampla" in geral


def test_quando_usar_escalar_fecha_as_duas_portas_do_motivo_outro() -> None:
    """O motivo usado no turno medido foi "outro". A definição ("situação GRAVE sem motivo na
    lista") não excluía a pergunta de agenda, e a lista do "não escale o que você resolve sozinha"
    — que já nomeia "é bot?", desconto na escada e horário redirecionado — também não."""
    geral = render_prefixo_geral()

    assert (
        "Pergunta sobre a SUA agenda ou disponibilidade também não entra: nada nela é grave"
        in geral
    )
    assert "se você já respondeu na bolha, não sobrou nada pra escalar" in geral
    assert "Nem pergunta dele sobre a SUA disponibilidade" in geral


def test_a_descricao_da_tool_escalar_diz_o_mesmo_que_a_conduta() -> None:
    """A 4ª superfície, e a mais próxima do dedo do modelo: a docstring da tool VIRA a `description`
    que o provider entrega junto do schema. Ela já tinha a própria lista de "Quando NÃO usar"
    (disclosure 1ª/2ª, desconto na escada, horário redirecionado, teto de duração) e a pergunta de
    agenda não estava lá — conduta corrigida no prompt e tool dizendo outra coisa é a mesma lição
    de sempre ("corrigir uma superfície e deixar a outra é não corrigir"), agora entre prosa e
    ferramenta.

    Normaliza o espaço em branco antes de casar: a `description` carrega as quebras de linha e a
    indentação da docstring, então asserto colado no texto cru quebraria a cada reflow do arquivo —
    e o que interessa aqui é a CLÁUSULA, não onde o autoformat pôs o \\n."""
    desc = " ".join(escalar.description.split())

    assert "Nem na pergunta dele sobre a SUA disponibilidade" in desc
    assert "responde-se pelo <periodo_de_trabalho>/<agenda>" in desc
    # os vizinhos que já estavam na lista continuam de pé — a cláusula somou, não substituiu
    assert "1ª ou 2ª pergunta de disclosure" in desc
    assert "teto de duração não é motivo de escalada" in desc


def test_nenhuma_variavel_nova_entrou_nos_templates_editados() -> None:
    """O modo de falha mais caro do projeto: variável desconhecida vira VAZIO em silêncio e o
    trecho desaparece do prompt sem erro nenhum. `StrictUndefined` transforma isso em exceção —
    renderizamos os dois templates com EXATAMENTE o dicionário que os `render_*` de produção
    passam, e qualquer variável nova estoura aqui em vez de sumir em prod."""
    env = Environment(
        loader=FileSystemLoader(_PROMPTS),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )
    env.globals["janela_agenda_horas"] = JANELA_AGENDA_HORAS

    regras = env.get_template("regras.md.j2").render(
        desconto_degrau_pct=0.1, desconto_teto_pct=0.2, pix_valor="R$50"
    )
    assert "<nucleo>" in regras and "<quando_usar_escalar>" in regras

    bloco = env.get_template("bloco_da_modelo.md.j2").render(**_SEM_RESTRICAO)
    assert "<sem_restricao>" in bloco
