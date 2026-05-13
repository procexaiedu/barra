"""Entidades e value objects do contexto Escaladas."""

from enum import StrEnum


class TipoEscalada(StrEnum):
    """Taxonomia fechada de motivos de escalada — espelha ``tipo_escalada_enum`` no banco.

    Texto livre humano-legível segue em ``escaladas.observacao``; este enum é a
    chave de agregação usada no dashboard.
    """

    pix_validado = "pix_validado"
    pix_duvidoso = "pix_duvidoso"
    foto_portaria = "foto_portaria"
    aviso_saida = "aviso_saida"
    fora_de_oferta = "fora_de_oferta"
    comportamento_atipico = "comportamento_atipico"
    indisponibilidade = "indisponibilidade"
    outro = "outro"


_ROTULOS: dict[TipoEscalada, str] = {
    TipoEscalada.pix_validado: "Pix de deslocamento validado",
    TipoEscalada.pix_duvidoso: "Pix duvidoso aguardando decisão",
    TipoEscalada.foto_portaria: "Cliente chegou (foto de portaria)",
    TipoEscalada.aviso_saida: "Cliente avisou que saiu de casa",
    TipoEscalada.fora_de_oferta: "Cliente pediu valor fora da tabela",
    TipoEscalada.comportamento_atipico: "Comportamento atípico antes de confirmar",
    TipoEscalada.indisponibilidade: "Sem agenda disponível",
    TipoEscalada.outro: "Outro",
}


def rotulo_tipo_escalada(tipo: TipoEscalada) -> str:
    """Rótulo humano-legível para exibição no painel/dashboard."""
    return _ROTULOS[tipo]
