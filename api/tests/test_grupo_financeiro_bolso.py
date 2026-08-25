"""Em que bolso o dinheiro caiu — a tabela de evidência do ADR-0047 (tickets 14 e 21).

O ADR-0045 §4 dizia que isso era cadastro da modelo. O ADR-0047 revogou porque o dono negou o
pressuposto: *"varia, não existe só um padrão"*. O bolso virou **fato da venda**, resolvido por
evidência — e é essa tabela, com a precedência dela, que este arquivo pina.

Cobre:
- `bolso.resolver_bolso`: as cinco linhas da tabela e a ordem em que elas se atropelam.
- `bolso.confrontar_bolso`: `não dito` resolve direto; bolso **afirmado** que diverge vira
  pergunta, nunca reescrita calada — mexer no bolso inverte o sinal do saldo.
- `pagamento.ler_fala_de_bolso`: a fala explícita ("caiu na minha conta", "ficou com você"), a
  negação que descarta em vez de inverter, e o que o grupo diz o dia inteiro e não é bolso.
- `pagamento.escolher_venda_do_bolso`: a mesma escada de `escolher_pagamento` (quote > nome dito >
  nome no contexto > única > ambígua).
- `comprovante.e_do_cliente_para_a_casa`: a classe nova do ticket 14 e a guarda que impede a
  regressão cara (pagador ilegível **não** vira classe nova — o abate FIFO continua acontecendo).
- O efeito no razão: bolso `empresa` desliga o débito do bruto e deixa só a comissão.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from barra.dominio.grupo_financeiro.bolso import (
    BOLSO_NAO_DITO,
    PREFIXO_DA_PERGUNTA_DO_BOLSO,
    VendaComBolso,
    confrontar_bolso,
    montar_pergunta_do_bolso,
    montar_recibo_do_bolso,
    resolver_bolso,
)
from barra.dominio.grupo_financeiro.comprovante import (
    LeituraDoComprovante,
    e_do_cliente_para_a_casa,
    montar_aviso_de_cliente_para_a_casa,
)
from barra.dominio.grupo_financeiro.modelos import MensagemRegistrada
from barra.dominio.grupo_financeiro.pagamento import (
    escolher_venda_do_bolso,
    ler_fala_de_bolso,
)
from barra.dominio.grupo_financeiro.razao import VendaNoRazao, apurar, bolso_efetivo

BIANCA = UUID("b1a11ca0-0000-0000-0000-000000000001")
VENDA_A = UUID("aaaaaaaa-0000-0000-0000-000000000001")
VENDA_B = UUID("bbbbbbbb-0000-0000-0000-000000000002")
HOJE = date(2026, 8, 20)


def _venda(
    venda_id: UUID = VENDA_A,
    *,
    bolso: str = BOLSO_NAO_DITO,
    cliente: str | None = None,
    valor: str = "600.00",
) -> VendaComBolso:
    return VendaComBolso(
        id=venda_id,
        modelo_id=BIANCA,
        valor=Decimal(valor),
        data=HOJE,
        bolso=bolso,  # type: ignore[arg-type]
        cliente_nome=cliente,
    )


def _mensagem(texto: str, *, minutos: int = 0) -> MensagemRegistrada:
    return MensagemRegistrada(
        id=UUID("cccccccc-0000-0000-0000-000000000003"),
        texto=texto,
        de_mim=False,
        recebida_em=datetime(2026, 8, 20, 19, 0) - timedelta(minutes=minutos),
    )


# --- a tabela de evidência (ADR-0047 §2) --------------------------------------------------------


def test_sem_evidencia_nenhuma_o_bolso_e_nao_dito() -> None:
    """ "Não dito" é estado LEGÍTIMO, não erro (§3) — e este módulo nunca chuta `dela` aqui.

    O default conservador é do RAZÃO (`bolso_efetivo`). Resolvê-lo já na leitura apagaria a
    diferença entre "ninguém disse" e "disseram que foi dela", e é essa diferença que decide se a
    cobrança da manhã ainda pergunta.
    """
    resolvido = resolver_bolso()

    assert resolvido.bolso == BOLSO_NAO_DITO
    assert resolvido.evidencia == "nenhuma"
    assert not resolvido.dito
    assert bolso_efetivo(resolvido.bolso) == "dela"


def test_dinheiro_e_sempre_dela_sem_ninguem_dizer_nada() -> None:
    """Espécie não tem outro bolso — a última linha da tabela, e a única que é regra e não fala."""
    resolvido = resolver_bolso(forma="dinheiro")

    assert resolvido.bolso == "dela"
    assert resolvido.evidencia == "especie"


def test_cartao_nao_tem_linha_propria_e_cai_em_nao_dito() -> None:
    """Não existe `maquininha_da_modelo` no cadastro (§6): débito/crédito/link seguem a tabela.

    Sem evidência, a venda no crédito é tão "não dita" quanto a no pix — e é a cobrança da manhã
    que a alcança, não uma pergunta nova por venda.
    """
    for forma in ("debito", "credito", "link"):
        assert resolver_bolso(forma=forma).bolso == BOLSO_NAO_DITO


def test_fala_explicita_vence_a_forma() -> None:
    """ "Ficou com você" numa venda no crédito decide — a fala é mais forte que a regra da forma."""
    resolvido = resolver_bolso(fala="dela", forma="credito")

    assert resolvido.bolso == "dela"
    assert resolvido.evidencia == "fala"


def test_comprovante_do_cliente_para_a_casa_vence_a_fala() -> None:
    """A imagem do banco vence o que alguém digitou: o dinheiro caiu na conta da casa."""
    resolvido = resolver_bolso(comprovante_do_cliente_para_a_casa=True, fala="dela")

    assert resolvido.bolso == "empresa"
    assert resolvido.evidencia == "comprovante_do_cliente_para_a_casa"


def test_comprovante_dela_para_a_casa_esta_no_topo_da_precedencia() -> None:
    """Ela transferindo para a casa prova que o dinheiro passou pela conta dela — nada vence isso."""
    resolvido = resolver_bolso(
        comprovante_dela_para_a_casa=True,
        comprovante_do_cliente_para_a_casa=True,
        fala="empresa",
        forma="dinheiro",
    )

    assert resolvido.bolso == "dela"
    assert resolvido.evidencia == "comprovante_dela_para_a_casa"


# --- a evidência que chega DEPOIS (ticket 14) ---------------------------------------------------


def test_bolso_nao_dito_a_evidencia_resolve_direto() -> None:
    """O caso da esmagadora maioria das vendas: não há nada a desmentir, então não há pergunta."""
    mudanca = confrontar_bolso(
        BOLSO_NAO_DITO, resolver_bolso(comprovante_do_cliente_para_a_casa=True)
    )

    assert mudanca.conduta == "fixar"
    assert (mudanca.de, mudanca.para) == (BOLSO_NAO_DITO, "empresa")


def test_bolso_afirmado_que_diverge_vira_pergunta_e_nao_reescrita() -> None:
    """Mexer no bolso inverte o SINAL do saldo — reescrever isso por uma imagem é o erro caro.

    É o critério do ticket 14: "quando ele foi afirmado como `dela` por fala ou por outro
    comprovante, vira pergunta, nunca correção automática".
    """
    mudanca = confrontar_bolso("dela", resolver_bolso(comprovante_do_cliente_para_a_casa=True))

    assert mudanca.conduta == "perguntar"
    assert (mudanca.de, mudanca.para) == ("dela", "empresa")

    pergunta = montar_pergunta_do_bolso(mudanca, valor=Decimal("600.00"), cliente_nome="Lucas")
    assert pergunta.startswith(PREFIXO_DA_PERGUNTA_DO_BOLSO)
    assert "cliente pagando a casa" in pergunta


def test_evidencia_que_confirma_o_que_ja_esta_anotado_e_muda() -> None:
    """O agente não ecoa o que já está certo — repetir a cada comprovante viraria ruído no grupo."""
    assert confrontar_bolso("dela", resolver_bolso(forma="dinheiro")).conduta == "nada"


def test_sem_evidencia_nada_e_escrito() -> None:
    """Foto que não era comprovante, fala que não falou de bolso: nada a escrever."""
    assert confrontar_bolso("dela", resolver_bolso()).conduta == "nada"
    assert confrontar_bolso(BOLSO_NAO_DITO, resolver_bolso()).conduta == "nada"


def test_o_recibo_do_bolso_traz_o_de_para_inteiro() -> None:
    """Sem o "era", quem lê não distingue "anotou o que eu disse" de "entendeu outra coisa"."""
    mudanca = confrontar_bolso(
        BOLSO_NAO_DITO, resolver_bolso(comprovante_do_cliente_para_a_casa=True)
    )
    recibo = montar_recibo_do_bolso(mudanca, valor=Decimal("600.00"), cliente_nome="Lucas")

    assert "na conta da casa" in recibo
    assert "era: não dito" in recibo
    assert "R$ 600,00" in recibo


# --- a fala explícita (ticket 21) ---------------------------------------------------------------


def test_as_duas_falas_que_o_adr_cita_sao_lidas() -> None:
    """ "caiu na minha conta" e "ficou com você" — os dois exemplos do ADR-0047 §2, os dois `dela`."""
    assert ler_fala_de_bolso("Caiu na minha conta") == ler_fala_de_bolso("caiu na minha conta")
    for texto in ("Caiu na minha conta", "Ficou com você", "ficou comigo"):
        fala = ler_fala_de_bolso(texto)
        assert fala is not None and fala.bolso == "dela", texto


def test_a_fala_da_casa_e_lida_como_empresa() -> None:
    for texto in ("caiu na conta da casa", "o cliente pagou direto pra vocês", "caiu pra gente"):
        fala = ler_fala_de_bolso(texto)
        assert fala is not None and fala.bolso == "empresa", texto


def test_pergunta_nao_e_resposta() -> None:
    """ "Ficou com você?" é a gestora perguntando — absorvê-la escreveria o que ninguém afirmou."""
    assert ler_fala_de_bolso("Ficou com você?") is None


def test_negacao_descarta_e_nunca_inverte() -> None:
    """ "não caiu na minha conta" CONTÉM "caiu na minha conta".

    Sem a guarda, a negação viraria a afirmação contrária do que foi dito — o pior erro possível
    neste campo. E ela descarta em vez de inverter: "não caiu na minha conta" não prova que caiu na
    da casa (pode ter caído na da parceira). A venda segue `não dito` e a manhã cobra.
    """
    assert ler_fala_de_bolso("não caiu na minha conta") is None
    assert ler_fala_de_bolso("nem ficou comigo") is None


def test_o_que_o_grupo_diz_o_dia_inteiro_nao_e_bolso() -> None:
    """Duas ausências deliberadas da tabela, e as duas custariam um saldo invertido.

    "pode enviar no meu pix" é a modelo DITANDO a chave dela (ticket 12); "ele foi pra casa" é o
    cliente indo embora — nenhuma das duas fala de onde o dinheiro caiu.
    """
    for texto in ("Pode enviar no meu pix", "ele foi pra casa", "Foi pix", "Sim", "600 1h"):
        assert ler_fala_de_bolso(texto) is None, texto


def test_frase_perdida_num_texto_longo_nao_decide() -> None:
    """Mexer no sinal do saldo por três palavras no meio de um parágrafo é o palpite proibido."""
    longo = (
        "amiga desculpa a demora eu tava no salão e depois fui no mercado mas enfim "
        "ficou comigo o dinheiro"
    )
    assert ler_fala_de_bolso(longo) is None


# --- de qual venda a fala fala ------------------------------------------------------------------


def test_o_quote_decide_antes_de_tudo() -> None:
    escolha = escolher_venda_do_bolso(
        texto="ficou com você",
        candidatas=[_venda(VENDA_A, cliente="Lucas"), _venda(VENDA_B, cliente="Igor")],
        venda_citada=VENDA_B,
    )

    assert escolha.motivo == "escolhida"
    assert escolha.venda is not None and escolha.venda.id == VENDA_B


def test_o_nome_dito_na_propria_fala_vence_o_historico() -> None:
    escolha = escolher_venda_do_bolso(
        texto="o do Igor ficou com você",
        contexto=[_mensagem("Cliente Lucas 600 1h")],
        candidatas=[_venda(VENDA_A, cliente="Lucas"), _venda(VENDA_B, cliente="Igor")],
    )

    assert escolha.venda is not None and escolha.venda.id == VENDA_B


def test_o_nome_do_contexto_recente_desempata() -> None:
    escolha = escolher_venda_do_bolso(
        texto="ficou com você",
        contexto=[_mensagem("O Lucas de ontem")],
        candidatas=[_venda(VENDA_A, cliente="Lucas"), _venda(VENDA_B, cliente="Igor")],
    )

    assert escolha.venda is not None and escolha.venda.id == VENDA_A


def test_duas_candidatas_e_nada_que_aponte_e_ambigua() -> None:
    """Escrever na venda errada inverte o saldo de um atendimento e ninguém reconfere."""
    escolha = escolher_venda_do_bolso(
        texto="ficou com você",
        candidatas=[_venda(VENDA_A, cliente="Lucas"), _venda(VENDA_B, cliente="Igor")],
    )

    assert escolha.motivo == "ambigua"
    assert escolha.venda is None


def test_sem_candidata_nenhuma_a_fala_nao_tem_alvo() -> None:
    assert escolher_venda_do_bolso(texto="ficou com você", candidatas=[]).motivo == "sem_venda"


def test_venda_com_bolso_ja_afirmado_continua_candidata() -> None:
    """Filtrá-la faria a contradição cair calada na venda vizinha — o erro que ninguém descobre."""
    escolha = escolher_venda_do_bolso(
        texto="ficou com você", candidatas=[_venda(VENDA_A, bolso="empresa")]
    )

    assert escolha.venda is not None and escolha.venda.id == VENDA_A
    assert escolha.venda.afirmado


# --- a classe nova de comprovante (ticket 14) ---------------------------------------------------


def _leitura(pagador: str | None) -> LeituraDoComprovante:
    return LeituraDoComprovante(
        e_comprovante=True,
        legivel=True,
        valor=Decimal("600.00"),
        data=HOJE,
        pagador=pagador,
        chave_destino="00000000-0000-0000-0000-000000000000",
        titular_destino="Agencia Barra",
    )


def test_cliente_pagando_a_casa_e_a_classe_nova() -> None:
    assert e_do_cliente_para_a_casa(
        _leitura("Lucas Prado"), pagador_e_a_modelo=False, destino_e_da_casa=True
    )


def test_ela_pagando_a_casa_continua_sendo_fechamento() -> None:
    """O comprovante de transferência dela para a casa continua abatendo em FIFO, sem regressão."""
    assert not e_do_cliente_para_a_casa(
        _leitura("Bianca Souza"), pagador_e_a_modelo=True, destino_e_da_casa=True
    )


def test_destino_fora_da_casa_nao_e_a_classe_nova() -> None:
    """Uma perna só nunca basta: sem o destino da casa isto pode ser a Entrada da modelo."""
    assert not e_do_cliente_para_a_casa(
        _leitura("Lucas Prado"), pagador_e_a_modelo=False, destino_e_da_casa=False
    )


def test_o_aviso_da_classe_nova_diz_o_efeito_e_nao_so_a_leitura() -> None:
    """Sem "não abati nada", a modelo pergunta depois se o dinheiro entrou.

    E ela não pode receber a pergunta do comprovante sem par ("é de quê?") nem o alarme de chave
    fora da lista: os dois dizem que ela tem uma transferência para explicar, e ela não tem.
    """
    aviso = montar_aviso_de_cliente_para_a_casa(
        valor=Decimal("600.00"), data=HOJE, pagador="Lucas Prado"
    )

    assert "R$ 600,00" in aviso
    assert "Lucas Prado" in aviso
    assert "não abati nada" in aviso


def test_pagador_ilegivel_nao_vira_classe_nova() -> None:
    """A guarda que impede a regressão cara.

    "pagador desconhecido + destino da casa" é como metade dos fechamentos legítimos chega (o OCR
    falha no nome com frequência). Classificá-los aqui pararia o abate FIFO da casa inteira em
    silêncio — e o comprovante ainda vale pelo VALOR, que é o que abate venda.
    """
    assert not e_do_cliente_para_a_casa(
        _leitura(None), pagador_e_a_modelo=False, destino_e_da_casa=True
    )


# --- o efeito no razão --------------------------------------------------------------------------


def test_bolso_empresa_desliga_o_debito_do_bruto_e_mantem_a_comissao() -> None:
    """O comprovante do cliente → casa é o que impede o razão de debitar dela o que ela não teve.

    Com `bolso = 'dela'` (inclusive pelo default de "não dito") a mesma venda deixaria a modelo
    devendo 600; com `empresa`, a casa deve a ela a comissão. É o sinal do saldo invertido — por
    isso o ticket 14 exige pergunta quando o bolso já foi afirmado.
    """
    venda = VendaNoRazao(
        valor=Decimal("1200.00"), bolso="empresa", percentual_repasse_snapshot=Decimal("50")
    )

    razao = apurar([venda])

    assert razao.debitos == Decimal("0.00")
    assert razao.creditos == Decimal("600.00")
    assert razao.saldo == Decimal("600.00")
    assert razao.a_casa_deve == Decimal("600.00")


def test_bolso_nao_dito_e_tratado_como_dela_pelo_razao() -> None:
    """Errar para esse lado é conservador (§4): o saldo mostra a modelo devendo e alguém confere."""
    venda = VendaNoRazao(valor=Decimal("1200.00"), percentual_repasse_snapshot=Decimal("50"))

    razao = apurar([venda])

    assert razao.debitos == Decimal("1200.00")
    assert razao.ela_deve == Decimal("600.00")
