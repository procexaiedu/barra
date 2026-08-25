"""Correções de prompt da rodada 3 do loop de massa (família prompts + DESCs).

Cada teste pina UM achado refutado, com o mecanismo no docstring — o que se perde ao apagar a
linha é a lição, não o texto. Todos são de RENDER: o defeito de cada um era uma superfície que o
modelo lê, e a prova é o texto que sai.
"""

from typing import Any

from barra.agente.ferramentas.extracao import (
    _DESC_DATA,
    _DESC_DURACAO,
    _DESC_HORARIO,
    _DESC_LIMPAR,
    SinaisQualificacao,
)
from barra.agente.persona import (
    render_aup_saida,
    render_contexto_dinamico,
    render_prefixo_geral,
    render_reminder,
)


def _contexto(**over: Any) -> str:
    base: dict[str, Any] = {
        "numero_curto": 7,
        "estado": "Qualificado",
        "slots_faltantes": [],
        "proximo_passo": "cravar o horário",
        "pix_status": "não aplicável",
    }
    return render_contexto_dinamico(**{**base, **over})


# --- prompt #3 — <valor_cotado> rotulava como "você já cotou" o pacote que ELE puxou -------------
def test_valor_cotado_nao_diz_que_ela_cotou_o_pacote_que_ele_puxou() -> None:
    """`duracao_pedida_no_burst` re-ancora o `pacote_em_pauta` na duração que o CLIENTE mencionou
    (prepare_context, rodada 6). O preço que entra é o da TABELA dela — nunca saiu da boca dela —,
    e o belief o apresentava como "preço que VOCÊ já cotou e ele AINDA NÃO aceitou", com a trava
    "não re-mande este valor sozinho" apontando para a resposta certa. Três eixos independentes."""
    dele = _contexto(
        preco_na_mesa=True,
        pacote_em_pauta={"horas": "3", "preco": "1200", "origem": "ele"},
    )
    assert "<valor_cotado>1200 (3h)" in dele
    assert "AINDA NÃO aceitou" not in dele
    assert "AINDA NÃO disse este número a ele" in dele

    dela = _contexto(preco_na_mesa=True, pacote_em_pauta={"horas": "1", "preco": "500"})
    assert "<valor_cotado>500 (1h)" in dela
    assert "preço que VOCÊ já cotou e ele AINDA NÃO aceitou" in dela
    assert "não re-mande este valor sozinho" in dela


# --- prompt #2b — o bloco irmão ignorava o <pacote_maior_na_sua_tabela> --------------------------
def test_escada_travada_sem_o_dia_cita_o_pacote_maior() -> None:
    """`<escada_travada_sem_o_dia>` prescrevia UMA jogada (defesa + pergunta do dia) e não
    mencionava o pacote maior nenhuma vez — enquanto o bloco irmão `<escada_sem_numero>` menciona e
    `regras.md.j2` crava que dentro da escada o TEMPO vem antes do DIA. O bloco dinâmico, mais
    concreto, ganha do estático: em negociacao_dura_a t4 a tag do pacote estava renderizada e o
    raciocínio não a citou uma vez."""
    out = _contexto(
        preco_na_mesa=True,
        n_contrapropostas=0,
        escada_estado="sem_dia",
        pacote_maior={"horas": "2", "preco": "700"},
    )
    assert "<escada_travada_sem_o_dia>" in out
    assert "<pacote_maior_na_sua_tabela>" in out.split("<escada_travada_sem_o_dia>")[1]


# --- prompt #6 + guard #2 — o Pix em três canais contraditórios ----------------------------------
def test_tag_do_pix_nao_e_muda() -> None:
    """`<pix_deslocamento>{{ pix_status }}</pix_deslocamento>` era a única tag de VALOR NU do bloco:
    o modelo tinha de adivinhar o que fazer com "aguardando comprovante". Com `regras` dizendo que
    o sistema manda a chave e o `<acao_pendente>` reinjetando "enviar a chave Pix", a saída
    consistente com os três era alucinar o envio ("Te mandei o pix", externo_a t6/t7/t8)."""
    out = _contexto(tipo_atendimento="externo", pix_status="aguardando comprovante")
    assert '<pix_deslocamento status="aguardando comprovante">' in out
    assert "nunca diga que foi VOCÊ quem mandou" in out


def test_acao_pendente_isenta_o_que_e_do_sistema() -> None:
    """`<acao_pendente>` devolve a `proxima_acao_esperada` VERBATIM com autoridade de registro do
    sistema ("vem antes de qualquer outro passo") — inclusive quando a ação é do SISTEMA (a chave
    Pix, o pin do endereço), que ela não tem como executar na bolha. E a isenção é SÓ do que é do
    sistema (chave Pix + pin no mapa): o endereço/número EM TEXTO é fala dela — em eb01 o
    boilerplate genérico ("mandar a localização") fez a IA calar "anota o número do ap" 3x."""
    out = _contexto(acao_pendente="enviar a chave Pix ao cliente")
    assert "ação que é do SISTEMA e não sua" in out
    # do sistema são só a chave e o PIN; endereço/número em texto são fala DELA
    assert "NÃO são do sistema" in out
    assert "<local_de_encontro>" in out.split("<acao_pendente>")[1]
    # a proibição vem com a fala de substituição (incidente #36): cravar o encontro
    assert "Me confirma o horário que eu te passo o número certinho amor" in out


def test_aup_saida_libera_o_anuncio_sem_chave() -> None:
    """`regras.md.j2` prescreve "já te mando o pix" e a bala de `system_leak` do `aup_saida.md` não
    tinha carve-out para a forma ANÚNCIO-SEM-CHAVE — as duas superfícies que o judge lê empurravam
    para barrar, e a fronteira ficava no sorteio (7/20 e 4/16 `viola=True` com a locução, 0/32 sem
    ela). A bala da chave ESCRITA continua intacta: o carve-out é por presença de chave."""
    out = render_aup_saida()
    assert "já te mando o pix" in out
    assert "Só a presença de chave/conta na mensagem decide" in out
    # a bala original não afrouxou
    assert "A chave certa **só o sistema" in out
    assert "chave que aparece aqui é inventada ou de outra pessoa, **viola**" in out


# --- prompt #4 — falta o simétrico do ADR-0040 para o aceite ao número DELA ----------------------
def test_reminder_nao_le_como_trava_absoluta_de_repetir_o_valor() -> None:
    """A exigência "o número precisa APARECER na sua mensagem" existia num lugar só
    (`<valor_dele_serve>`), que só renderiza quando o número é DELE. Do outro lado o lembrete dizia
    "crave o horário, sem re-cotar" e o modelo leu como trava absoluta — fechou sem o número."""
    out = render_reminder(fase="Qualificado", nome="Manu")
    assert "APARECER na sua mensagem" in out
    assert "não é re-cotar" in out


# --- prompt #5 / #8 / extração #9 — as superfícies do BP_GERAL -----------------------------------
def test_reconhecimento_de_midia_sem_promessa_de_envio() -> None:
    """Com `<ja_enviou_book>` no contexto o prompt manda "reconhecer e redirecionar", mas o verbo
    reconhecer tinha UMA forma pronta no prompt inteiro — e era uma PROMESSA ("Te mando sim amor").
    pedido_midia t7 executou exatamente isso: prometeu mídia que não ia sair."""
    out = render_prefixo_geral()
    assert "Reconhecer aqui olha para o que JÁ saiu" in out
    assert "ilustração da intenção, não fala pronta" in out


def test_enumeracao_anti_invencao_cobre_fato_do_local() -> None:
    """`persona.md` enumerava seis famílias (preço, serviço, endereço, viagem, promoção, história)
    e estacionamento/portaria/elevador/wifi não estão em nenhuma — enquanto `regras.md.j2` empurra
    reasseguro "curto e positivo" para pergunta de segurança. Nem o cadastro modela amenidade, nem
    os detectores do guard cobrem (são todos sobre atos/serviços)."""
    out = render_prefixo_geral()
    assert "FATO DO LOCAL" in out
    assert "FATO do local é outra coisa" in out


def test_prompt_nao_pede_mais_o_nome_do_cliente() -> None:
    """A tool não tem campo de nome, o INSERT do webhook não aproveita nem o `pushName` e só rotas
    de painel escrevem `clientes.nome`: o prompt mandava colher um dado sem destino, no turno mais
    caro da conversa (o do fechamento)."""
    out = render_prefixo_geral()
    assert "Qual seu nome amor" not in out
    assert "nunca uma pergunta de cadastro" in out


# --- as DESCs da extração (o outro prompt que o modelo lê) ---------------------------------------
def _desc_aceita_valor() -> str:
    campo = SinaisQualificacao.model_fields["aceita_valor"]
    return campo.description or ""


def test_desc_da_data_ganha_a_clausula_anti_palpite_do_horario() -> None:
    """A assimetria era literal: `_DESC_HORARIO` já dizia que a hora sai de uma FALA e que o relógio
    é só base de cálculo; `_DESC_DATA` não tinha equivalente, e o único "CRÍTICO" dela ia na direção
    oposta. A fonte do dia fantasma é a âncora `<agenda hoje=>` (a extração é cega à fala da IA do
    turno), contra a qual a própria DESC manda resolver relativos — 5 payloads em 4 eixos."""
    assert "sozinho ele nunca é a resposta" in _DESC_HORARIO  # o irmão que já existia
    assert "A data sai SEMPRE de uma FALA DELE" in _DESC_DATA
    assert "sozinha ela nunca é a resposta" in _DESC_DATA


def test_desc_da_duracao_subordina_a_reoferta_ao_fechamento_dele() -> None:
    """ "vale a duração que ELE trouxe" estava sintaticamente subordinada a "ele fechar", e o modelo
    leu solto: em objetor_a t2 o cliente PERGUNTOU 30 min e foi recusado, e a duração entrou assim
    mesmo. 0.5h em si é legítimo (há pacote de 30 min pinado) — o defeito é duração sem linha na
    tabela DESTA modelo, e o caso medido é a que ela RECUSOU."""
    assert "no turno EM QUE ELE FECHA — e só nele" in _DESC_DURACAO
    assert "a duração que VOCÊ RECUSOU nesta conversa" in _DESC_DURACAO


def test_desc_do_aceite_nomeia_a_objecao_de_preco_e_o_caminho_de_desfazer() -> None:
    """Duas lacunas medidas: nenhuma cláusula tratava lowball/objeção como não-aceite (objetor_b
    t10, "faz 250 que eu chamo o uber"), e NENHUMA DESC dizia ao extrator que
    `limpar: ["valor_acordado"]` desfaz um aceite errado — o `False` do sinal é apagado pelo
    `exclude_defaults` e não desce sozinho."""
    desc = _desc_aceita_valor()
    assert "Objeção de preço" in desc
    assert 'limpar: ["valor_acordado"]' in desc
    assert 'limpar: ["valor_acordado"]' in _DESC_LIMPAR
