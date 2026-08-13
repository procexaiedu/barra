"""Contrato dicionario->SELECT do `prepare_context`.

O `test_contrato_variaveis_contexto` amarra template->dicionario. Faltava o elo de tras: o
dicionario e um `row` de query, e ler `atendimento.get("coluna")` de uma coluna que o SELECT nao
trouxe devolve `None` em SILENCIO — o Jinja nao renderiza o bloco e a conduta degrada sem erro
nenhum. Foi exatamente o que aconteceu com `proxima_acao_esperada` (commit 80e623b): a tag
`<acao_pendente>`, descrita no codigo como "a leitura mais fresca do que a conversa pede", nunca
chegou ao prompt — confirmado no trace 71c7196e, onde o bloco renderizado sai sem ela.

Este teste fecha a CLASSE, nao a instancia: qualquer chave nova lida do row do atendimento tem de
estar no SELECT que produziu o row.
"""

import re
from pathlib import Path

FONTE = (
    Path(__file__).resolve().parents[2] / "src" / "barra" / "agente" / "nos" / "prepare_context.py"
)

# `atendimento.get("x")`, `atendimento.get('x')` e `atendimento["x"]` — as tres formas de leitura.
_RE_LEITURA = re.compile(r"""atendimento(?:\.get\(|\[)["']([a-z_]+)["']""")


def _colunas_do_select() -> set[str]:
    """As colunas do SELECT de `_carregar_atendimento` (o unico que produz o row `atendimento`)."""
    fonte = FONTE.read_text(encoding="utf-8")
    corpo = fonte.split("async def _carregar_atendimento", 1)[1]
    select = re.search(r"SELECT\s+(.*?)\s+FROM\s+barravips\.atendimentos", corpo, re.S)
    assert select is not None, "SELECT de _carregar_atendimento nao encontrado"
    return {
        coluna.strip() for coluna in select.group(1).replace("\n", " ").split(",") if coluna.strip()
    }


def test_toda_chave_lida_do_atendimento_esta_no_select() -> None:
    lidas = set(_RE_LEITURA.findall(FONTE.read_text(encoding="utf-8")))
    assert lidas, "nenhuma leitura de `atendimento` encontrada — o regex do teste apodreceu"

    faltando = lidas - _colunas_do_select()
    assert not faltando, (
        f"chave(s) lida(s) do row do atendimento mas AUSENTE(s) no SELECT: {sorted(faltando)}. "
        "O row nao levanta KeyError: `.get` devolve None e a tag correspondente some do prompt em "
        "silencio. Some a coluna ao SELECT de `_carregar_atendimento`."
    )


def test_o_select_nao_carrega_coluna_que_ninguem_le() -> None:
    """Simetrico, e barato: coluna paga (I/O + memoria) todo turno sem consumidor e resto de
    refactor. Falha aqui e sinal de limpeza, nao de bug."""
    ociosas = _colunas_do_select() - set(_RE_LEITURA.findall(FONTE.read_text(encoding="utf-8")))
    assert not ociosas, f"coluna(s) no SELECT sem nenhum leitor: {sorted(ociosas)}"


def test_hora_sai_no_mesmo_formato_para_a_ia_e_para_o_extrator() -> None:
    """`<hora>` renderizada como `HH:MM` nos DOIS templates que a imprimem.

    O `ja_registrado.md.j2` usava `{{ horario_desejado }}` cru — o repr de `datetime.time`, que sai
    `17:00:00`. Esse bloco existe justamente para o extrator saber o que ja esta gravado, entao ele
    ECOAVA `17:00:00` no payload; a coercao de hora nao aceita segundos e DESCARTAVA o campo. O
    horario que o cliente cravou se perdia em silencio (observado ao vivo em 12/08, roteiro
    dado_na_mesa: `extracao com campos fora do schema (descartados): [horario_desejado='17:00:00']`).
    """
    prompts = FONTE.parents[1] / "prompts"
    for template in ("ja_registrado.md.j2", "contexto_dinamico.md.j2"):
        texto = (prompts / template).read_text(encoding="utf-8")
        assert "{{ horario_desejado }}" not in texto, (
            f"{template} imprime `horario_desejado` cru (vira 'HH:MM:SS'). "
            "Use `.strftime('%H:%M')`, como manda o formato que a coercao da extracao aceita."
        )


def test_bloqueios_recortam_por_sobreposicao_nao_por_inicio() -> None:
    """A janela de bloqueios tem de pegar o encontro EM CURSO.

    Com `inicio >= agora`, um bloqueio das 20h as 22h sumia da lista quando o cliente escrevia as
    21h — e `bloqueios_raw` e a unica fonte de ocupacao do <agenda>, do `horario_minimo`, do
    `proximo_horario` e das `janelas_livres`. A IA lia "sem bloqueios" e oferecia a outro cliente a
    hora em que a modelo estava ocupada. Verificado contra o banco: predicado antigo devolvia 0
    linhas, `fim > agora` devolve 1.

    O proprio filtro de estado ja provava a intencao: 'em_atendimento' designa bloqueio que JA
    comecou, e com o predicado antigo esse estado nunca casava.
    """
    fonte = FONTE.read_text(encoding="utf-8")
    query = re.search(
        r"SELECT inicio, fim\s+FROM barravips\.bloqueios(.*?)\"\"\"", fonte, re.S
    )
    assert query is not None, "query de bloqueios nao encontrada"
    corpo = query.group(1)

    assert "fim >" in corpo, "o recorte tem de ser por SOBREPOSICAO (`fim > agora`)"
    assert "inicio >=" not in corpo, (
        "`inicio >= agora` esconde o bloqueio EM CURSO da agenda inteira — a IA passa a oferecer "
        "horario ocupado."
    )
