"""M3f — mapping puro motivo -> (tipo, responsavel) + bucket (04 §3.4/§3.6, 09 §4.3).

DB-free: as funcoes sao puras. Cobre TODOS os motivos roteaveis — o Literal da tool (o que o
LLM pode emitir) + os motivos INTERNOS emitidos como string por coordenador/services
(test_cobertura_enum_completa garante que a tabela ESPERADO nao fica defasada se o enum mudar)
e o default seguro para um motivo desconhecido.
"""

from typing import get_args

import pytest

from barra.agente.ferramentas.escalada import EscaladaPayload
from barra.dominio.escaladas.modelos import TipoEscalada
from barra.dominio.escaladas.service import (
    OBS_LEMBRETE_SEM_RESPOSTA,
    card_escalada_vai_ao_grupo,
    mapear_bucket,
    mapear_motivo,
)

# motivo -> (tipo esperado, responsavel esperado, bucket esperado)
ESPERADO: dict[str, tuple[TipoEscalada, str, str]] = {
    # Operacionais -> capacidade
    "fora_de_oferta": (TipoEscalada.fora_de_oferta, "modelo", "capacidade"),
    "horario_indisponivel": (TipoEscalada.indisponibilidade, "modelo", "capacidade"),
    "reagendamento_pos_bloqueio": (TipoEscalada.indisponibilidade, "modelo", "capacidade"),
    "politica_nova_necessaria": (TipoEscalada.outro, "Fernando", "capacidade"),
    "exaustao_iteracoes": (TipoEscalada.outro, "Fernando", "capacidade"),
    "timeout_grafo": (TipoEscalada.outro, "Fernando", "capacidade"),
    # modelo_recusou: Fernando, mas bucket DEFESA (safety da API, nao falha de capacidade)
    "modelo_recusou": (TipoEscalada.outro, "Fernando", "defesa"),
    # AUP / persona / jailbreak -> comportamento_atipico, Fernando, defesa
    "disclosure_insistente": (TipoEscalada.comportamento_atipico, "Fernando", "defesa"),
    "disclosure_explicito": (TipoEscalada.comportamento_atipico, "Fernando", "defesa"),
    "jailbreak_attempt": (TipoEscalada.comportamento_atipico, "Fernando", "defesa"),
    "pedido_explicito_repetido": (TipoEscalada.comportamento_atipico, "Fernando", "defesa"),
    "prova_humanidade_persistente": (TipoEscalada.comportamento_atipico, "Fernando", "defesa"),
    "cross_modelo_fishing": (TipoEscalada.comportamento_atipico, "Fernando", "defesa"),
    # Safety-critico (menor/ilegal): comportamento_atipico, Fernando, defesa
    "conteudo_ilegal": (TipoEscalada.comportamento_atipico, "Fernando", "defesa"),
    # Generico (default seguro)
    "outro": (TipoEscalada.outro, "Fernando", "capacidade"),
}


@pytest.mark.parametrize("motivo", list(ESPERADO))
def test_mapear_motivo(motivo: str) -> None:
    esperado_tipo, esperado_resp, _ = ESPERADO[motivo]
    assert mapear_motivo(motivo) == (esperado_tipo, esperado_resp)


@pytest.mark.parametrize("motivo", list(ESPERADO))
def test_mapear_bucket(motivo: str) -> None:
    _, _, esperado_bucket = ESPERADO[motivo]
    assert mapear_bucket(motivo) == esperado_bucket


# Motivos INTERNOS: fora do schema do LLM (nao estao no Literal da tool — poluiriam o espaco de
# decisao e o grammar strict), emitidos como string por coordenador (exaustao/timeout/recusa),
# atendimentos/service (reagendamento) e legado do classificador (disclosure_explicito).
MOTIVOS_INTERNOS = {
    "reagendamento_pos_bloqueio",
    "exaustao_iteracoes",
    "timeout_grafo",
    "modelo_recusou",
    "disclosure_explicito",
}


def test_cobertura_enum_completa() -> None:
    """ESPERADO cobre exatamente o Literal do LLM (EscaladaPayload) + os motivos internos."""
    motivos_enum = set(get_args(EscaladaPayload.model_fields["motivo"].annotation))
    assert motivos_enum | MOTIVOS_INTERNOS == set(ESPERADO)
    # Interno NUNCA vaza pro schema do LLM (se vazar, o enum da tool engordou de volta).
    assert motivos_enum.isdisjoint(MOTIVOS_INTERNOS)


def test_default_seguro_motivo_desconhecido() -> None:
    """Motivo fora do enum cai no default seguro: Fernando + outro + bucket capacidade."""
    assert mapear_motivo("xpto_inexistente") == (TipoEscalada.outro, "Fernando")
    assert mapear_bucket("xpto_inexistente") == "capacidade"


def test_card_escalada_vai_ao_grupo() -> None:
    """Roteamento por owner (UX §9.6): modelo → grupo; Fernando → painel/fila, salvo o
    lembrete-sem-resposta (que continua no grupo)."""
    # owner=modelo: sempre vai ao grupo, com ou sem observação.
    assert card_escalada_vai_ao_grupo("modelo", None) is True
    assert card_escalada_vai_ao_grupo("modelo", "fora_de_oferta") is True
    # owner=Fernando: não vai ao grupo (jailbreak/política/exaustão são do painel).
    assert card_escalada_vai_ao_grupo("Fernando", None) is False
    assert card_escalada_vai_ao_grupo("Fernando", "disclosure_insistente") is False
    # Exceção: lembrete-sem-resposta é Fernando mas continua na thread do grupo.
    assert card_escalada_vai_ao_grupo("Fernando", OBS_LEMBRETE_SEM_RESPOSTA) is True
