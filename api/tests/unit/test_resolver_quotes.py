"""Resolução do alvo de quote → (evolution_message_id, texto do balão) por bolha.

Puro (sem banco, sem chave). Cobre `_resolver_quotes`: `[quote]` puro (última msg), `[quote: trecho]`
casando uma msg específica do turno, miss com fallback gracioso para a última, e os casos degenerados
(sem inbound, alvo None). O `inbound` é a lista que o coordenador já carrega: dicts com
`evolution_message_id` e `conteudo`, em ordem cronológica.
"""

from barra.workers.coordenador import _resolver_quotes


def _inbound() -> list[dict[str, object]]:
    return [
        {"evolution_message_id": "evo-1", "conteudo": "atende casal?"},
        {"evolution_message_id": "evo-2", "conteudo": "quanto fica?"},
        {"evolution_message_id": "evo-3", "conteudo": "tem amanhã?"},
    ]


def test_alvo_none_nao_cita() -> None:
    ids, textos = _resolver_quotes([None, None], _inbound())
    assert ids == [None, None]
    assert textos == [None, None]


def test_quote_puro_cita_ultima_mensagem() -> None:
    ids, textos = _resolver_quotes([""], _inbound())
    assert ids == ["evo-3"]
    assert textos == ["tem amanhã?"]


def test_trecho_casa_mensagem_especifica_do_turno() -> None:
    # cita a M1 ("atende casal?") mesmo não sendo a última do turno.
    ids, textos = _resolver_quotes(["atende casal"], _inbound())
    assert ids == ["evo-1"]
    assert textos == ["atende casal?"]


def test_trecho_case_insensitive() -> None:
    ids, textos = _resolver_quotes(["ATENDE Casal"], _inbound())
    assert ids == ["evo-1"]
    assert textos == ["atende casal?"]


def test_trecho_acento_insensivel() -> None:
    # LLM solta diacríticos do PT-BR ao recortar; o match dobra acento (NFKD) e casa mesmo assim.
    inbound = [
        {"evolution_message_id": "evo-1", "conteudo": "que horário você tem?"},
        {"evolution_message_id": "evo-2", "conteudo": "tem amanhã?"},
    ]
    ids, textos = _resolver_quotes(["horario voce"], inbound)
    assert ids == ["evo-1"]
    assert textos == ["que horário você tem?"]  # texto do balão preserva o acento original


def test_trecho_miss_cai_na_ultima() -> None:
    # trecho que não existe em nenhuma inbound → fallback gracioso para a última (não trava).
    ids, textos = _resolver_quotes(["preço de pernoite"], _inbound())
    assert ids == ["evo-3"]
    assert textos == ["tem amanhã?"]


def test_multiplos_casam_pega_o_ultimo() -> None:
    inbound = [
        {"evolution_message_id": "evo-1", "conteudo": "você faz anal?"},
        {"evolution_message_id": "evo-2", "conteudo": "e anal com mais alguém?"},
    ]
    ids, textos = _resolver_quotes(["anal"], inbound)
    assert ids == ["evo-2"]
    assert textos == ["e anal com mais alguém?"]


def test_sem_inbound_tudo_none() -> None:
    # canned/reengajamento: nenhum inbound no turno → alvo ignorado.
    ids, textos = _resolver_quotes(["", "atende casal"], [])
    assert ids == [None, None]
    assert textos == [None, None]


def test_mix_de_bolhas_resolve_por_posicao() -> None:
    ids, textos = _resolver_quotes(["atende casal", None, ""], _inbound())
    assert ids == ["evo-1", None, "evo-3"]
    assert textos == ["atende casal?", None, "tem amanhã?"]
