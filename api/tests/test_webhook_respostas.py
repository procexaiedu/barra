"""Fase 2 (UX §6) — texto das confirmações e erros de comando do grupo de Coordenação.

Funções puras (sem I/O): garantem o vocabulário canônico e o formato BR do valor, e que todo erro
tem caminho de recuperação (nunca beco sem saída). O wiring (quando/por qual `tipo` enviar) é
coberto na costura do webhook (`test_webhook_integration.py`, `test_f1_1_*`).
"""

from decimal import Decimal

from barra.webhook.respostas import (
    texto_confirmacao,
    texto_erro_comando,
    texto_erro_dominio,
)


def test_confirmacao_fechado_usa_formato_br() -> None:
    txt = texto_confirmacao("registrar_fechado", {"valor_final": Decimal("1500")}, 42)
    assert txt == "✅ #42 fechado · R$ 1.500,00 registrado"


def test_confirmacao_perdido_cita_motivo() -> None:
    txt = texto_confirmacao("registrar_perdido", {"motivo": "sumiu"}, 7)
    assert txt == "✅ #7 marcado como perdido · motivo: sumiu"


def test_confirmacao_devolucao() -> None:
    assert texto_confirmacao("devolver_para_ia", {}, 12) == "✅ #12 devolvido para a IA"


def test_confirmacao_comando_desconhecido_tem_eco_defensivo() -> None:
    # Nunca silencioso: comando sem eco próprio ainda confirma com o #N.
    assert texto_confirmacao("xpto", {}, 9) == "✅ #9 registrado"


def test_erro_numero_curto_ausente_da_exemplo_com_n() -> None:
    txt = texto_erro_comando("numero_curto_ausente")
    assert txt.startswith("❓")
    assert "*fechado #42 1500*" in txt


def test_erro_valor_ambiguo() -> None:
    assert "só o valor final" in texto_erro_comando("valor_ambiguo")


def test_erro_valor_final_obrigatorio() -> None:
    assert "Faltou o valor" in texto_erro_comando("valor_final_obrigatorio")


def test_erro_motivo_perda_lista_os_seis_motivos() -> None:
    txt = texto_erro_comando("motivo_perda_obrigatorio")
    for motivo in ("preço", "sumiu", "risco", "indisponibilidade", "fora_de_area", "outro"):
        assert motivo in txt


def test_erro_codigo_desconhecido_cai_no_generico() -> None:
    # Caminho de saída sempre: lista os comandos válidos.
    txt = texto_erro_comando("nao_existe")
    assert "*fechado 1500*" in txt
    assert "*perdido sumiu*" in txt
    assert "*IA assume*" in txt
    assert texto_erro_comando(None) == txt


def test_erro_dominio_mapeia_codigos_conhecidos() -> None:
    assert texto_erro_dominio("OBSERVACAO_OBRIGATORIA") == texto_erro_comando(
        "observacao_obrigatoria"
    )
    assert texto_erro_dominio("CONFLITO_ESTADO") == texto_erro_comando("conflito_estado")
    assert texto_erro_dominio("RECURSO_NAO_ENCONTRADO") == texto_erro_comando(
        "atendimento_nao_encontrado"
    )


def test_erro_dominio_codigo_inesperado_cai_no_generico() -> None:
    assert texto_erro_dominio("ALGO_NOVO") == texto_erro_comando(None)
