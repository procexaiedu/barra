"""Ciclo 10 — "consigo assim que vc terminar aí?" não é pergunta sobre outro cliente, é agenda.

Caso medido (cenário `encaixe_apos_o_atual`): agenda com bloqueio 17:30→18:45 e
`proximo_livre="Qui 13/08 19:30"` JÁ no contexto. No t1 ("ta livre agora?") a IA respondeu certo
("a partir das 19:30"). No t2 ("consigo assim que vc terminar ai?") ela respondeu "Pode sim amor"
E chamou `escalar(motivo="outro", resumo="...confirmar disponibilidade sem revelar agenda de
outros clientes")` — o próprio thinking pós-tool se corrigiu ("I should have just confirmed
19:30. Escalating was wrong.").

A causa é uma colisão, não uma falta de dado: a linha 3 do <nucleo> ("Ninguém fica sabendo de
outro cliente, nunca") faz a fala dele PARECER questão de sigilo, e nenhuma das cláusulas que
desarmam a escalada cobria essa forma:

1. <conduta_de_agenda> só armava quando o HORÁRIO PEDIDO cai em bloqueio — aqui ele não pediu hora
   nenhuma, e o vazio empurrou pro <nucleo> linha 8 ("situação sem regra → escale");
2. o item `- outro —` do <quando_usar_escalar> exclui "pergunta sobre a SUA agenda ou
   disponibilidade", mas o modelo classificou o turno como SIGILO, não como agenda;
3. "Não escale o que você resolve sozinha" fala de disponibilidade, não dessa forma;
4. a docstring de `escalar` (que vira a `description` da tool, a superfície mais perto do dedo)
   também não a nomeava.

Corrigir uma superfície e deixar a outra é não corrigir (lição do projeto), então os asserts
cobrem as três superfícies editadas de uma vez. Todos leem o que o modelo VÊ — prompt renderizado
e descrição de tool: o defeito era texto, não código.
"""

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from barra.agente.ferramentas.escalada import escalar
from barra.agente.persona import JANELA_AGENDA_HORAS, render_prefixo_geral

_PROMPTS = Path(__file__).parents[2] / "src" / "barra" / "agente" / "prompts"


def _bloco_conduta_de_agenda() -> str:
    """Só o <conduta_de_agenda> do prompt renderizado.

    Os asserts de AUSÊNCIA precisam desse recorte: "Pode sim amor" é fala legítima da
    <apresentacao> (aceitar item do catálogo) e um assert global só provaria que a conduta antiga
    existe. O que este ciclo proíbe é a fala pronta DENTRO da cláusula nova.

    A tag ABRE em linha própria; citada no meio da prosa (o <nucleo> linha 3 aponta pra ela) é
    referência, não abertura — por isso o recorte casa "\\n<conduta_de_agenda>\\n"."""
    geral = render_prefixo_geral()
    inicio = geral.index("\n<conduta_de_agenda>\n")
    return geral[inicio : geral.index("</conduta_de_agenda>", inicio)]


def test_conduta_de_agenda_cobre_o_cliente_que_ja_supoe_o_compromisso() -> None:
    """O vácuo era o caso SEM horário pedido: a conduta de indisponibilidade só arma quando a hora
    dele cai em bloqueio. A cláusula nova nomeia a forma, diz que não há bloqueio a contornar
    (logo não é "situação sem regra") e manda oferecer a própria janela no mesmo turno."""
    geral = render_prefixo_geral()

    assert "Ele já SUPÕE o compromisso, sem pedir hora nenhuma" in geral
    assert (
        "como não há horário pedido, não há bloqueio a contornar, então isso não é situação sem "
        "regra e NUNCA é escalada" in geral
    )
    assert (
        "o próximo horário livre que já está no seu <agenda> sai neste turno e a bolha fecha nele"
        in geral
    )


def test_a_clausula_nova_nao_afrouxa_o_sigilo_do_nucleo() -> None:
    """O risco de mexer aqui é virar licença pra falar do outro cliente. A linha 3 do <nucleo>
    continua byte a byte, e a cláusula resolve pela SIMETRIA: não confirma e não desmente — o
    sigilo se preserva porque ela fala só da própria janela, nunca do outro."""
    geral = render_prefixo_geral()

    # o núcleo intacto
    assert "3. Ninguém fica sabendo de outro cliente, nunca" in geral

    # e a cláusula nova fechando as duas saídas erradas
    assert "Não confirme nem desminta o que ele supôs" in geral
    assert 'nem admitir o outro cliente ("meu cliente sai às X" não existe na sua boca)' in geral
    assert "nem jurar que não há ninguém" in geral
    assert "você não fala do outro, fala de você" in geral


def test_o_gatilho_e_familia_do_cliente_e_a_conduta_e_intencao_nao_fala_pronta() -> None:
    """Lição "conduta nova no prompt vira tique": fala pronta da persona volta idêntica em toda
    conversa. O que entrou foi a família de falas DELE (gatilho a reconhecer) mais a intenção — a
    resposta da IA no turno medido ("Pode sim amor") não pode virar template, e nenhum horário
    ilustrativo pode virar a hora que sai da boca dela."""
    agenda = _bloco_conduta_de_agenda()

    # a família do gatilho, na boca dele
    for fala_dele in (
        "assim que você terminar aí",
        "quando você acabar",
        "depois do seu cliente",
        "quando sair desse atendimento",
    ):
        assert fala_dele in agenda

    # a conduta é intenção, e o prompt diz isso explicitamente
    assert "A forma é sua e varia a cada conversa, nunca uma fala decorada." in agenda

    # nada da bolha medida virou molde: nem o aceite, nem a hora do caso
    assert "Pode sim amor" not in agenda
    assert "19:30" not in agenda


def test_quando_usar_escalar_nomeia_o_caso_na_lista_do_resolve_sozinha() -> None:
    """2ª superfície. A lista já nomeia "é bot?", desconto na escada, horário redirecionado,
    disponibilidade e remarcação; faltava a forma em que ele SUPÕE que ela está ocupada — que é
    justamente a que o modelo leu como sigilo e escalou com motivo "outro"."""
    geral = render_prefixo_geral()

    assert "Nem o cliente SUPONDO que você está ocupada agora e pedindo pra ser o próximo" in geral
    assert (
        "ele não pediu horário nenhum e não há dado do outro cliente a proteger na sua resposta"
        in geral
    )
    assert "sem tocar no assunto do outro (<conduta_de_agenda>)" in geral

    # os vizinhos da lista continuam de pé — a cláusula somou, não substituiu
    assert 'Não escale o que você resolve sozinha: primeira pergunta de "é bot?"' in geral
    assert "Nem pergunta dele sobre a SUA disponibilidade" in geral
    assert "Nem o cliente REMARCANDO o encontro que ele mesmo marcou" in geral


def test_a_descricao_da_tool_escalar_diz_o_mesmo_que_a_conduta() -> None:
    """3ª superfície, e a mais próxima do dedo do modelo: a docstring VIRA a `description` que o
    provider entrega junto do schema. Prompt corrigido e tool dizendo outra coisa é a mesma lição
    de sempre, agora entre prosa e ferramenta.

    Normaliza o espaço em branco antes de casar: a `description` carrega as quebras de linha e a
    indentação da docstring, então asserto colado no texto cru quebraria a cada reflow."""
    desc = " ".join(escalar.description.split())

    assert "Nem quando ele SUPÕE que você está ocupada agora e pede pra ser o próximo" in desc
    assert "sem horário pedido não há nada a escalar" in desc
    assert "sem confirmar nem desmentir o compromisso que ele supôs" in desc

    # os vizinhos que já estavam na lista continuam de pé
    assert "1ª ou 2ª pergunta de disclosure" in desc
    assert "Nem na pergunta dele sobre a SUA disponibilidade" in desc
    assert "teto de duração não é motivo de escalada" in desc


def test_nenhuma_variavel_nova_entrou_no_regras() -> None:
    """Modo de falha mais caro do projeto: variável desconhecida vira VAZIO em silêncio e o trecho
    some do prompt sem erro nenhum. `StrictUndefined` transforma isso em exceção — renderizamos com
    EXATAMENTE o dicionário que o `render_prefixo_geral` de produção passa."""
    env = Environment(
        loader=FileSystemLoader(_PROMPTS),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )
    env.globals["janela_agenda_horas"] = JANELA_AGENDA_HORAS

    regras = env.get_template("regras.md.j2").render(
        desconto_degrau_pct=0.1, desconto_teto_pct=0.2, pix_valor="R$50"
    )
    assert "<conduta_de_agenda>" in regras and "<quando_usar_escalar>" in regras
