"""Memoria DUPLA do detector de repeticao (FIX 3a do diagnostico de degradacao tardia, 14/08).

Unit puro (sem DB/LLM): so `bolhas_repetidas` e `_bolhas_historicas`.

O detector lia so as ultimas 12 bolhas da IA e 26% dos ecos do saturado ficavam fora dessa
memoria. Alargar a janela INTEIRA para 40 (a proposta crua) foi medido sobre 949 turnos com fala
da IA do corpus da campanha (`.scratch/campanha-substituicao-20260813`): 6 flags a mais, das quais
so as 3 VERBATIM eram papagaio -- as 3 de similaridade frouxa eram re-ancoragem legitima, e a pior
delas era a confirmacao do fechamento. Dai a memoria dupla: janela larga so p/ o reenvio EXATO.

Os casos com `ref:` no nome vem literalmente do corpus.
"""

import importlib

from langchain_core.messages import AIMessage, HumanMessage

# nos/__init__ reexporta a funcao output_guard, sombreando o submodulo (memoria do projeto).
mod = importlib.import_module("barra.agente.nos.output_guard")


def _enche(n: int) -> list[str]:
    """n bolhas de enchimento, todas diferentes entre si e de qualquer bolha dos testes."""
    return [f"Bolha de enchimento numero {i} sem nada em comum com as outras" for i in range(n)]


# --------------------------------------------------------- memoria LARGA: reenvio verbatim


def test_verbatim_longe_flagra_fora_das_12_ultimas() -> None:
    """Byte-identico nunca e re-ancoragem: 20 bolhas atras continua sendo papagaio."""
    bolha = "Consigo às 14h, fecha ?"
    assert mod.bolhas_repetidas(bolha, [bolha, *_enche(20)]) == [bolha]


def test_verbatim_ref_c4_lote_eb04_t15() -> None:
    """`Consigo às 14h, fecha ?` reenviada verbatim 13 bolhas da IA depois (c4-lote/eb04
    :19134800761083 t15) -- foi ao cliente porque a memoria era 12."""
    bolha = "Consigo às 14h, fecha ?"
    hist = [bolha, *_enche(12)]
    assert mod.bolhas_repetidas(bolha, hist) == [bolha]


def test_verbatim_ref_ciclo1_eb02_30472893644814_t6() -> None:
    """`Sou bem tranquila, estilo namoradinha` de volta 14 bolhas depois -- e o eco que o
    cliente do loop-massa r2 nomeou ("Vc ja falou isso rs")."""
    vista = "Sou bem tranquila, estilo namoradinha"
    nova = "Sou bem tranquila, estilo namoradinha rs"  # a cauda de voz sai da chave
    assert mod.bolhas_repetidas(nova, [vista, *_enche(13)]) == [nova]


def test_verbatim_alem_da_janela_do_modelo_nao_tem_o_que_ler() -> None:
    """`_bolhas_historicas` entrega no MAXIMO a janela que o modelo le -- 40 bolhas. Alem disso
    nao ha memoria a alargar (medido: 60 e 40 dao o mesmo resultado no corpus)."""
    msgs = [AIMessage(content=f"bolha {i}") for i in range(80)]
    assert len(mod._bolhas_historicas(msgs)) == mod._REPETICAO_JANELA_VERBATIM == 40
    assert mod._bolhas_historicas(msgs)[0] == "bolha 40"


def test_bolhas_historicas_ignora_a_fala_do_turno_e_o_cliente() -> None:
    """Invariante pre-existente que a janela maior nao pode afrouxar: so AIMessage HISTORICA
    (sem usage_metadata) entra."""
    msgs = [
        HumanMessage(content="oi"),
        AIMessage(content="Oii amor\n\nTudo bem ?"),
        AIMessage(
            content="fala DESTE turno",
            usage_metadata={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
        ),
    ]
    assert mod._bolhas_historicas(msgs) == ["Oii amor", "Tudo bem ?"]


# --------------------------------------------------------- memoria CURTA: match frouxo


def test_mesma_abertura_longe_nao_flagra() -> None:
    """Reoferta com a mesma abertura 20 bolhas depois: a negociacao andou no meio, isso e
    re-ancoragem. Dentro das 12 continua flagrando (teste seguinte)."""
    assert (
        mod.bolhas_repetidas("Consigo às 17h então ?", ["Consigo às 17h, fecha ?", *_enche(20)])
        == []
    )


def test_mesma_abertura_perto_continua_flagrando() -> None:
    """Sem regressao do ramo frouxo dentro da memoria curta."""
    assert mod.bolhas_repetidas(
        "Consigo às 17h então ?", ["Consigo às 17h, fecha ?", *_enche(5)]
    ) == ["Consigo às 17h então ?"]


def test_fuzzy_longe_nao_flagra() -> None:
    nova = "400 1h no meu local amor"
    assert mod.bolhas_repetidas(nova, ["400 1h no meu local aqui", *_enche(20)]) == []
    assert mod.bolhas_repetidas(nova, ["400 1h no meu local aqui", *_enche(5)]) == [nova]


def test_frouxo_longe_ref_ciclo1_eb02_21123135741957_t20() -> None:
    """O falso positivo que a janela larga CRUA produzia, no pior turno possivel.

    O cliente cravou as 20h e fechou ("Fecho com vc mas as 14h complica, seria a noite, umas
    20h"); `houve_aceite` nao arma porque o burst nao e so o aceite. Com o ramo frouxo lendo 13
    bolhas atras, `Consigo às 20h sim` batia em `Consigo às 20h, fecha ?` e o guard reescrevia o
    turno do FECHAMENTO -- o modo de falha que o proprio modulo ja documenta duas vezes.
    """
    hist = ["Consigo às 20h, fecha ?", *_enche(12)]
    assert mod.bolhas_repetidas("Perfeito\n\nConsigo às 20h sim\n\nTe espero", hist) == []


def test_fusao_de_bolhas_so_olha_a_memoria_curta() -> None:
    """A cauda de FUSAO e match frouxo por construcao (ratio sobre a juncao) -> memoria curta."""
    historicas = ["Sou bem tranquila", "Estilo namoradinha, bem carinhosa com voce"]
    fundida = "Sou bem tranquila estilo namoradinha, bem carinhosa com voce"
    assert mod.bolhas_repetidas(fundida, [*historicas, *_enche(5)]) == [fundida]
    assert mod.bolhas_repetidas(fundida, [*historicas, *_enche(20)]) == []


# --------------------------------------------------------- as isencoes seguem valendo de longe


def test_verbatim_longe_ainda_isento_quando_responde_o_pedido() -> None:
    """`400 1h no meu local` verbatim 22 bolhas depois (c5/lote/eb02:115139634290814 t12) NAO
    volta pela janela larga: o cliente perguntou `Valor?` e a bolha e RESPOSTA, nao papagaio.
    A janela nao e a porta desse caso -- a isencao de `responde_pedido` e, e por design."""
    bolha = "400 1h no meu local"
    hist = [bolha, *_enche(22)]
    assert mod.bolhas_repetidas(bolha, hist) == [bolha]
    assert (
        mod.bolhas_repetidas(bolha, hist, responde_pedido=lambda b: bool(mod._RE_DIGITOS.search(b)))
        == []
    )


def test_verbatim_longe_ainda_isento_no_aceite_quando_nao_e_pergunta() -> None:
    """`houve_aceite` continua desligando exato/fuzzy p/ bolha que nao e pergunta, a qualquer
    distancia -- re-entregar o dado combinado depois do "fechou" e conduta certa."""
    bolha = "Te espero às 21h no meu local então"
    hist = [bolha, *_enche(20)]
    assert mod.bolhas_repetidas(bolha, hist) == [bolha]
    assert mod.bolhas_repetidas(bolha, hist, houve_aceite=True) == []


def test_numero_diferente_de_longe_nao_e_eco() -> None:
    """Hora NOVA na mesma forma e oferta nova, nao papagaio -- inclusive de longe (era o 2o caso
    "literal" do diagnostico, `Consigo às 20h` x `Consigo às 10h`: a janela nunca foi a causa)."""
    assert (
        mod.bolhas_repetidas("Consigo às 20h, fecha ?", ["Consigo às 10h, fecha ?", *_enche(20)])
        == []
    )
