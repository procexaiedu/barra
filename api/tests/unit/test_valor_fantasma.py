"""Guarda do VALOR FANTASMA — só é `valor_acordado` o número que a IA ofertou (ou que está na
tabela). Peças puras + o conjunto legítimo contra um FakeConn. Sem DB, sem crédito.

O bug vivo (11/08, cenário escada_val2): o cliente insistiu "vai amor, 300 e fecho agora", a IA
RECUSOU ("não consigo por 300 não") e a extração gravou `valor_acordado=300` + `aceita_valor` —
o cliente "aceitando" o número DELE. O piso não pegou porque 300 era exatamente o teto de 25%
sobre a tabela de 400. O caminho completo (descarte + payload aplicado + métrica + aviso ao LLM)
está em tests/integracao/test_registrar_extracao.py (needs_db).
"""

from typing import Any

from barra.dominio.atendimentos.service import (
    _sem_valor_fantasma,
    _valor_fora_do_conjunto,
    _valores_ja_ofertados,
    extrair_precos_citados,
    precos_ofertados_na_fala,
)

# --- o que conta como OFERTA na fala da modelo (puro) ---------------------------------------


def test_preco_em_contexto_monetario_e_oferta() -> None:
    assert precos_ofertados_na_fala("Fica 400 1h no meu local amor") == {400}
    assert precos_ofertados_na_fala("consigo 350 se vier hoje") == {350}
    assert precos_ofertados_na_fala("sai por R$ 700 as 2h") == {700}


def test_clausula_negada_nao_e_oferta() -> None:
    """A fala do bug. Sem isto a própria recusa legitimaria o número recusado — e, pior, ficaria
    no histórico legitimando o mesmo 300 nos turnos seguintes (foi assim que a IA capitulou)."""
    assert precos_ofertados_na_fala("Poxa amor, não consigo por 300 não") == set()
    # Eco-negação (negação DEPOIS do número, lição do ven_004): "por 300 não" é recusa também.
    assert precos_ofertados_na_fala("consigo por 300 não amor") == set()
    # Mas o scanner cru continua vendo o número — a diferença é só a leitura de oferta.
    assert extrair_precos_citados("Poxa amor, não consigo por 300 não") == {300}


def test_aceite_do_valor_dele_em_forma_natural_e_oferta() -> None:
    """ADR-0040: quando quem nomeia o número é o CLIENTE, a fala natural do sim dela não tem "R$",
    nem "por", nem duração colada — e sem casar o scanner o `valor_acordado` inteiro é descartado
    como fantasma e `aceita_valor` cai junto: a venda de 700 não é registrada.

    A saída barata era prescrever no prompt UMA frase que o scanner já lesse ("Consigo 700 sim
    amor"). Recusada pelo dono do produto: conduta prescrita como frase vira tique (o "Seria hoje
    ?" já é um tique medido em prod) e uma frase com CARGA FUNCIONAL pune toda variação — o sistema
    puniria a IA por dizer a mesma coisa com outras palavras. Então quem alarga é o detector, e
    estes testes variam a fala de propósito."""
    assert precos_ofertados_na_fala("Fechado 700 amor, consigo às 21h ?") == {700}
    assert precos_ofertados_na_fala("Tabom, 700 então amor") == {700}
    assert precos_ofertados_na_fala("Combinado 700 amor") == {700}
    assert precos_ofertados_na_fala("Faço 700 sim amor") == {700}
    assert precos_ofertados_na_fala("é 700 então, te espero") == {700}
    assert precos_ofertados_na_fala("Fechado 1.200 amor") == {1200}


def test_o_ramo_de_fechamento_continua_barrado_pela_clausula_negada() -> None:
    """A guarda que existe por causa do bug de 11/08 (a IA RECUSOU 300 e o extrator gravou 300)
    não pode ser afrouxada pelo ramo novo: o token de aceite dentro de uma cláusula NEGADA não
    oferta nada, e a negação vale dos dois lados em pt-BR."""
    assert precos_ofertados_na_fala("não é 700 não amor") == set()
    assert precos_ofertados_na_fala("não consigo fechar 700 amor") == set()
    assert precos_ofertados_na_fala("nem 700 eu consigo") == set()
    # e a oferta boa na cláusula vizinha sobrevive — recusar um número e aceitar outro na mesma
    # bolha é fala canônica da negociação.
    assert precos_ofertados_na_fala("não consigo 650 não, mas fechado 700") == {700}
    # eco-negação (negação DEPOIS do número) também barra o ramo novo — e o scanner CRU continua
    # vendo o número, que é a diferença entre citar e ofertar.
    assert precos_ofertados_na_fala("fechado 700 não amor") == set()
    assert extrair_precos_citados("fechado 700 não amor") == {700}


def test_numero_solto_e_hora_seguem_fora_do_ramo_de_fechamento() -> None:
    """Falso-positivo aqui legitima um valor que ela nunca falou. O token de fechamento é
    obrigatório e vem COLADO no número."""
    assert extrair_precos_citados("Av. Aquidaba 130") == set()
    assert extrair_precos_citados("vamos às 21 então") == set()
    assert extrair_precos_citados("Fechado amor, te espero") == set()
    assert extrair_precos_citados("meu quarto é o 704") == set()


def test_negacao_nao_contamina_a_clausula_vizinha() -> None:
    """Estreito de propósito: recusar um número e ofertar outro na mesma bolha é a fala canônica
    da escada de desconto — a oferta boa tem que sobreviver."""
    assert precos_ofertados_na_fala("não faço por 300, mas consigo 350 se for hoje") == {350}
    assert precos_ofertados_na_fala("consigo 350, mas não hoje") == {350}


def test_separador_de_milhar_nao_parte_o_numero() -> None:
    """A quebra por cláusula não pode cortar "1.000" no ponto — seria um fantasma inventado pelo
    próprio detector."""
    assert precos_ofertados_na_fala("a pernoite fica 1.000 amor") == {1000}
    assert precos_ofertados_na_fala("sai por 400,00 certinho") == {400}


# --- pertencer ao conjunto (puro) ------------------------------------------------------------


def test_valor_fora_do_conjunto_devolve_o_numero() -> None:
    assert _valor_fora_do_conjunto("300", {400, 700}) == 300
    assert _valor_fora_do_conjunto("400", {400, 700}) is None


def test_centavos_nao_mudam_a_identidade_do_numero() -> None:
    """ "350,00" é o 350 que a IA falou; 349,50 casa pelo arredondamento. Escalar por centavo é
    falso-positivo caro (derruba venda boa)."""
    assert _valor_fora_do_conjunto("350.00", {350}) is None
    assert _valor_fora_do_conjunto("349.50", {350}) is None
    assert _valor_fora_do_conjunto("349.49", {349}) is None
    assert _valor_fora_do_conjunto("360", {350}) == 360


def test_valor_ilegivel_nao_e_fantasma() -> None:
    """Fail-open na leitura: quem barra lixo é a validação do payload, não esta guarda."""
    assert _valor_fora_do_conjunto("nao-e-numero", {400}) is None


# --- o conjunto legítimo (tabela U falas), contra um FakeConn --------------------------------


class _FakeConn:
    """Responde às três queries de `_valores_ja_ofertados` pelo trecho de SQL."""

    def __init__(self, programas: list[dict[str, Any]], falas: list[str]) -> None:
        self.programas = programas
        self.falas = falas

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> Any:
        if "FROM barravips.atendimentos" in sql:
            linhas = [{"modelo_id": "m1", "conversa_id": "c1"}]
        elif "modelo_programas" in sql:
            linhas = self.programas
        else:
            linhas = [{"conteudo": t} for t in self.falas]

        class _R:
            async def fetchone(self) -> Any:
                return linhas[0] if linhas else None

            async def fetchall(self) -> Any:
                return linhas

        return _R()


def _linha(preco: Any, minimo: Any = None) -> dict[str, Any]:
    return {"preco": preco, "preco_minimo": minimo}


async def _legitimos(
    programas: list[dict[str, Any]], falas: list[str], turno: str | None = None
) -> set[int]:
    conn = _FakeConn(programas, falas)
    return await _valores_ja_ofertados(conn, "a1", turno)  # type: ignore[arg-type]


async def test_tabela_entra_com_preco_e_preco_minimo() -> None:
    assert await _legitimos([_linha(400, 350), _linha(700)], []) == {400, 350, 700}


async def test_falas_do_historico_entram_e_recusa_nao() -> None:
    legitimos = await _legitimos(
        [_linha(400)],
        ["Fica 400 1h amor", "consigo 350 se vier hoje", "não consigo por 300 não"],
    )
    assert legitimos == {400, 350}


async def test_fala_do_turno_corrente_entra() -> None:
    """Ela ainda não está em `mensagens`; sem ela a cotação do próprio turno (o total com extra de
    fetiche, 400+400, que não está na tabela) seria descartada como fantasma."""
    assert 800 in await _legitimos([_linha(400)], [], "fica 800 com o extra amor")


async def test_modelo_sem_tabela_desliga_o_detector() -> None:
    """Mesma convenção do `bolhas_preco_fantasma`: sem tabela não há "fora da tabela", e descartar
    tudo travaria a venda de um cadastro incompleto."""
    assert await _legitimos([], ["consigo 350 amor"]) == set()


# --- o descarte no payload (puro) ------------------------------------------------------------


def test_descarte_tira_valor_e_aceite_e_preserva_o_resto() -> None:
    payload = {
        "valor_acordado": "300",
        "duracao_horas": "1",
        "sinais_qualificacao": {"aceita_valor": True, "responde_objetivamente": True},
        "proxima_acao_esperada": "combinar o horario",
    }
    limpo = _sem_valor_fantasma(payload, 300, {400, 700})

    assert "valor_acordado" not in limpo
    # `aceita_valor` foi inferido do MESMO evento falso; os outros sinais ficam.
    assert limpo["sinais_qualificacao"] == {"responde_objetivamente": True}
    assert limpo["duracao_horas"] == "1"
    assert limpo["proxima_acao_esperada"] == "combinar o horario"
    # Auditoria no evento, igual ao `drift_descartado`/`tipo_descartado`.
    assert limpo["valor_descartado"] == {"proposto": 300, "legitimos": [400, 700]}


def test_descarte_sem_outro_sinal_nao_deixa_dict_vazio_no_merge() -> None:
    """Dict vazio no `sinais_qualificacao` viraria um `|| '{}'` inútil no UPSERT."""
    limpo = _sem_valor_fantasma(
        {"valor_acordado": "300", "sinais_qualificacao": {"aceita_valor": True}}, 300, {400}
    )
    assert "sinais_qualificacao" not in limpo
