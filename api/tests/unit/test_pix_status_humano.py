"""_pix_status_humano (prepare_context): traduz o enum pix_status para texto da cauda volatil.

Expor o enum cru ("nao_solicitado", "em_revisao") faz a IA adivinhar o significado. O mapa deve
cobrir os 5 valores reais da coluna `atendimentos.pix_status` (nao_solicitado, aguardando,
em_revisao, validado, invalido).

Regressao (AGENTE): o mapa tinha a chave fantasma 'pendente' (valor que NAO existe no enum) e
faltava 'nao_solicitado' -- justo o DEFAULT de todo atendimento em Triagem/interno/remoto -> o
fallback `.get(status, status)` devolvia o enum cru "nao_solicitado" ao LLM em quase todo turno.
"""

from barra.agente.nos.prepare_context import _pix_status_humano

# Os 5 valores reais do enum pix_status (atendimentos), conferidos contra infra/sql + service.py.
_VALORES_REAIS = ["nao_solicitado", "aguardando", "em_revisao", "validado", "invalido"]


def test_default_nao_solicitado_nao_vaza_enum_cru() -> None:
    # O caso que regrediu: o default de todo atendimento novo.
    assert _pix_status_humano("nao_solicitado") == "ainda não pedido"


def test_todos_os_valores_reais_tem_texto_humano() -> None:
    # Nenhum valor real pode cair no fallback (que devolveria o enum cru).
    for status in _VALORES_REAIS:
        assert _pix_status_humano(status) != status


def test_none_e_nao_aplicavel() -> None:
    assert _pix_status_humano(None) == "não aplicável"
