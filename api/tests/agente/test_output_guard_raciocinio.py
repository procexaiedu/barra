"""Vazamento de RACIOCINIO na saida (output_guard / non-disclosure, tolerancia-zero).

O chat #1 (DeepSeek V4 Flash, thinking disabled, temp 1.3) as vezes derrama a cadeia de
raciocinio no canal `content` -- meta-fala que entrega a IA ao cliente tao claramente quanto o
`ia_self`. Diferente dos outros leaks, a acao e SANEAR (stripar a bolha de raciocinio, manter a
fala real); so se nada legitimo sobrar o turno fica mudo. O judge (Etapa 2) e a rede fail-closed
p/ fraseado novo que escapa do regex.

Amostras reais: o unico turno vazado colhido pelo harness (terminal_8.json, cenario eb02), mais
fala legitima do corpus do Vendedor p/ medir falso-positivo.
"""

import importlib

import pytest

mod = importlib.import_module("barra.agente.nos.output_guard")


# Bolhas REAIS que vazaram (terminal_8.json, 1 turno do cenario interno eb02). Cada uma so pode
# ser raciocinio: planejamento em 1a pessoa, 3a pessoa sobre o cliente, vocab de maquina de estado,
# lista de analise, fragmento de scratchpad.
BOLHAS_VAZADAS = [
    "Hmm, pensando por partes: o cliente demonstrou interesse, perguntou 'depende do horário "
    "e do local...' — isso é importante. Ele quer saber logística. Triagem avançou, mas precisa "
    "do meu próximo passo.",
    "A conversa fluiu a partir da primeira troca (ele perguntou, eu respondi), mas é natural que "
    "em triagem ele queira entender melhor: como funciona, horários disponíveis hoje, "
    "possibilidades.",
    "A situação mostra:\n- Pediu dinâmica inicial\n- Avanço recente na resposta\n- Claro interesse "
    "dele\n- Minha intervenção suavizou e gerou abertura\n- Agora menciona querer confirmação",
    "Faz sentido na sequência... Preparado, então.opa, devagar.",
    "Parece uma boa pergunta pra responder em triagem... mas na real, pode ser qualquer coisa: "
    "imagino que Fernando preparou essas lacunas diferentes pra dar mais variedade.",
    # meta de espera pos-cotacao (eval 2026-07-03, terminal v2_3): comentario sobre a propria
    # estrategia da cotacao saiu como bolha ao cliente.
    "Agora é esperar ele reagir ao valor 😊",
    "agora é só esperar",
]


# Vazamento de JARGAO DE TIPO / deducao narrada (bloqueador confirmado, avaliacao 2026-07-01,
# eb04:100532349874202): o chat classificou o atendimento em voz alta ao cliente. O adverbio "ja"
# entre "ele" e "falou" quebrava a adjacencia do regex antigo; o rotulo "interno" nao tinha token.
BOLHAS_VAZADAS_TIPO = [
    "ah ele já falou que é interno então, pode vir amor",
    "ele já falou que é interno",
    "que é interno então",
    "ela ainda disse que quer 2h",
]


@pytest.mark.parametrize("bolha", BOLHAS_VAZADAS_TIPO)
def test_detecta_jargao_de_tipo_e_adverbio(bolha: str) -> None:
    # "ele JA falou" (adverbio) e "que e interno" (rotulo de dominio) tem que casar.
    assert mod.tem_marcador_raciocinio(bolha) is True


def test_detecta_a_bolha_canonica_de_raciocinio() -> None:
    # Tracer bullet: a bolha mais inequivoca (planejamento 1a pessoa + 3a pessoa sobre o cliente +
    # maquina de estado) tem que ser reconhecida como vazamento de raciocinio.
    bolha = BOLHAS_VAZADAS[0]
    assert mod.tem_marcador_raciocinio(bolha) is True


@pytest.mark.parametrize("bolha", BOLHAS_VAZADAS)
def test_detecta_todas_as_bolhas_vazadas_reais(bolha: str) -> None:
    # Recall na amostra real: tolerancia-zero exige pegar TODA forma do unico turno vazado colhido.
    assert mod.tem_marcador_raciocinio(bolha) is True


# Fala LEGITIMA real (corpus do Vendedor / runs do harness, 470 bolhas limpas mineradas) + casos
# adversariais perto dos marcadores mas legitimos. Stripar isto seca a conversa a toa -> a recall
# alta nao pode comer fala client-facing. O lado seguro da assimetria e justamente NAO flagar isto.
BOLHAS_LEGITIMAS = [
    "me chamo Manu rs, me conta o que você procura?",
    "sou bem tranquila, atenciosa, estilo namoradinha",
    "seria hoje? se pá depois das 17h30 já tô de boas",
    "o valor de 1h é 400 no meu local amor",
    "você vem no meu local? ou quer combinar de outra forma?",
    "então que horário você consegue vir pra cá?",
    "qual período você tinha em mente?",
    "hoje, 400 1h ou 700 2h no meu local aqui na Barra",
    "o local é aqui na Chácara da Barra, em Campinas",
    "aí a gente confirma certinho",
    "É um ambiente bem reservado e gostosinho 🥰",
    "Me conta o que você quer saber?",
    # adversariais: perto dos marcadores, mas fala legitima --
    "faz sentido amor, então bora marcar",  # "faz sentido" solto (nao "na sequencia")
    "imagino que você vai gostar bastante 🥰",  # "imagino" sobre o cliente, em personagem
    "então normalmente eu atendo aqui no meu local",  # "então normal..." dentro de fala real
    "que horário fica bom pra você?",  # 2a pessoa (o proprio cliente), nao 3a
    "ele vai te receber lá em cima amor",  # 3a legit (porteiro): verbo fora da lista
    "ela é minha amiga, vem junto se quiser",  # 3a legit: "e" nao e verbo de fala
    "é um ambiente bem reservado e interno amor",  # "interno" descritivo, sem "que e" nem "entao"
    "vou te esperar aqui amor",  # esperar SEM "reagir" e sem "agora e": fala legitima
    "te espero rs, me avisa quando sair",  # idem
]


@pytest.mark.parametrize("bolha", BOLHAS_LEGITIMAS)
def test_nao_flagra_fala_legitima(bolha: str) -> None:
    # Falso-positivo: stripar fala real degrada a conversa. Nenhuma bolha legitima pode ser flagrada.
    assert mod.tem_marcador_raciocinio(bolha) is False


# Placeholder de template nao preenchido: o chat cospe a chave literal do exemplo do prompt em vez do
# dado real (amostra real: terminal_8c.json, cenario eb04 — "{valor} 1h no meu local"). Uma bolha com
# `{token}` ASCII entrega a IA e nunca e fala valida; o Estagio 0 a descarta junto com o raciocinio.
BOLHAS_COM_PLACEHOLDER = [
    "{valor} 1h no meu local amor",
    "te espero às {horario} amor 🥰",
    "fico no {nome}, centro de Campinas",
    # Formas que so a rede final do envio pegava: chave acentuada e colchete instrucional. Desde a
    # unificacao do padrao elas caem no Estagio 0 e ganham a regeneracao (antes: handoff seco).
    "te espero às {horário} amor",
    "é na [insira a rua] número 10",
]


@pytest.mark.parametrize("bolha", BOLHAS_COM_PLACEHOLDER)
def test_detecta_placeholder_nao_preenchido(bolha: str) -> None:
    assert mod.tem_placeholder_template(bolha) is True


@pytest.mark.parametrize("bolha", BOLHAS_LEGITIMAS)
def test_placeholder_nao_flagra_fala_legitima(bolha: str) -> None:
    # Nenhuma fala real tem `{token}` ASCII — preco/horario/local saem como numero, nao como chave.
    assert mod.tem_placeholder_template(bolha) is False


# Delimitador de EXEMPLO vazado: os few-shots de regras.md.j2/persona.md moldam a fala ideal com tags
# de papel (<ela>, <cliente>, <exemplo>) + pares de contraste (<certo>/<errado>/<par>/<porque>). Sob
# temp 0.7 o chat COPIA o fechamento colado a uma fala boa. Amostra real: terminal_B.json (cenarios
# eb04:golpe e eb02:reengajamento, 2026-07-01). Diferente do raciocinio, a bolha e fala LEGITIMA com
# residuo de molde -> o Estagio 0 strippa SO a substring da tag e mantem a fala (nao vira handoff nem
# bolha vazia).
BOLHAS_COM_TAG_EXEMPLO = [
    (
        "consigo sim amor, seria que horas?</ela>",
        "consigo sim amor, seria que horas?",
    ),  # fala legit c/ tag
    ("tudo bem sim, e você?</ela>", "tudo bem sim, e você?"),  # real (eb02 reengajamento)
    ("<ela>600 1h no meu local amor", "600 1h no meu local amor"),
    ("pode vir amor, te recebo já</cliente>", "pode vir amor, te recebo já"),
    ("</exemplo>seria hoje amor?", "seria hoje amor?"),
    ("não faço anal não amor</errado>", "não faço anal não amor"),
]


@pytest.mark.parametrize("bruta,limpa", BOLHAS_COM_TAG_EXEMPLO)
def test_strippa_tag_de_exemplo_mantendo_a_fala(bruta: str, limpa: str) -> None:
    # A tag de molde sai; a fala client-facing fica intacta (nao vira handoff nem bolha vazia).
    assert mod._limpar_bolhas(bruta) == limpa


def test_bolha_so_tag_de_exemplo_some() -> None:
    # Bolha que e SO o delimitador (nada de fala) desaparece -- nao vai bolha vazia ao cliente.
    assert mod._limpar_bolhas("</ela>") == ""
    # E no meio de fala boa: a tag-only some sem deixar `\n\n` orfao.
    assert mod._limpar_bolhas("boa fala amor\n\n</ela>") == "boa fala amor"


@pytest.mark.parametrize("bolha", BOLHAS_LEGITIMAS)
def test_limpar_bolhas_no_op_em_fala_legitima(bolha: str) -> None:
    # Sem tag/raciocinio/placeholder o Estagio 0 nao toca a fala (curto-circuito texto_saneado==texto).
    assert mod._limpar_bolhas(bolha) == bolha


def test_sanear_reescreve_a_mensagem_com_tag_vazada() -> None:
    # Caminho real do guard: a AIMessage com a tag no fim e reescrita (mesmo id, usage preservado) e o
    # texto agregado sai limpo -- o coordenador re-deriva a fala limpa das mensagens, nao um output do
    # guard. `</ela>` colado a uma fala boa NAO pode virar handoff nem sumir a fala.
    from langchain_core.messages import AIMessage

    msg = AIMessage(id="m1", content="tudo bem sim, e você?</ela>")
    texto_saneado, reescritas = mod._sanear_raciocinio([msg], "tudo bem sim, e você?</ela>")
    assert texto_saneado == "tudo bem sim, e você?"
    assert [m.id for m in reescritas] == ["m1"]
    assert reescritas[0].content == "tudo bem sim, e você?"


# Sonda-de-balcao CRUA (tell de SAC): amostra real do harness (terminal_8b.json, 4/8 cenarios) --
# depois do cumprimento a IA soltava o probe aberto, proibido na abertura (`regras.md.j2:<abertura>`)
# e no par de `persona.md`. Estagio 0 dropa a bolha crua, deixando o cumprimento correto intacto.
BOLHAS_SONDA_CRUA = [
    "O que você procura ?",
    "Vi que me chamou, o que você procura ?",  # "me chamou" != convite caloroso -> ainda cai
    "o que você busca amor?",
    "o que você está procurando?",
    "o que gostaria de saber?",
    "o que te traz aqui?",
    "pode perguntar o que quiser 😊",
    "gosta de que tipo de programa?",
]


@pytest.mark.parametrize("bolha", BOLHAS_SONDA_CRUA)
def test_detecta_sonda_de_balcao_crua(bolha: str) -> None:
    assert mod.tem_sonda_balcao(bolha) is True


# Forma CALOROSA / self-intro: probe embrulhado num convite ("me conta") ou apresentacao ("me
# chamo") e voz legitima -- decisao ja encodada nas fixtures BOLHAS_LEGITIMAS. NAO pode ser dropada.
BOLHAS_SONDA_CALOROSA = [
    "me chamo Manu rs, me conta o que você procura?",
    "me conta o que você procura amor 🥰",
    "me fala o que você busca que eu te ajudo",
    "Me conta o que você quer saber?",  # "quer saber" nem esta no regex do probe
]


@pytest.mark.parametrize("bolha", BOLHAS_SONDA_CALOROSA)
def test_nao_flagra_sonda_calorosa(bolha: str) -> None:
    # Convite caloroso / self-intro resgata a bolha: fica intacta (assimetria a favor de preservar voz).
    assert mod.tem_sonda_balcao(bolha) is False
    assert mod._limpar_bolhas(bolha) == bolha


def test_estagio0_dropa_sonda_mantendo_cumprimento() -> None:
    # Caminho real da abertura: cumprimento em bolhas + o probe cru como ultima bolha. O Estagio 0
    # dropa so o probe e devolve o cumprimento correto ("Oii / boa tarde amor / tudo bem sim").
    turno = "Oii\n\nBoa tarde amor 🥰\n\nTudo bem sim\n\nO que você procura ?"
    assert mod._limpar_bolhas(turno) == "Oii\n\nBoa tarde amor 🥰\n\nTudo bem sim"
