"""Veredito de uma corrida e2e: a IA conduziu ate a confirmacao, sem violar invariante?

Determinismo total (sem LLM-judge, como o gate da Camada 1): mede a linha de chegada, varre
vazamento cross-canal em cada turno (reusa os detectores de prod via `evals.checks`) e compara
a conducao com o desfecho real do corpus como rotulo.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from barra.agente.nos.output_guard import (
    tem_marcador_outro_cliente,
    tem_marcador_system,
)

from .perfil import PerfilCaso
from .runner import ResultadoE2E


@dataclass
class VeredictoE2E:
    perfil_nome: str
    conduziu: bool
    desfecho_conducao: str
    estado_final: str | None
    bate_desfecho_real: bool | None  # None se o caso nao tem rotulo do corpus
    n_turnos: int
    custo_brl: float
    violacoes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Conducao limpa: chegou na linha de chegada e nao violou nenhuma invariante dura."""
        return self.conduziu and not self.violacoes


def avaliar_e2e(res: ResultadoE2E, perfil: PerfilCaso) -> VeredictoE2E:
    from evals.checks import _texto_e_args

    violacoes: list[str] = []
    for i, t in enumerate(res.turnos):
        saida = _texto_e_args(t)
        if tem_marcador_outro_cliente(saida):
            violacoes.append(f"turno {i}: marcador de outro cliente na saida (vazamento por-par)")
        if tem_marcador_system(saida):
            violacoes.append(f"turno {i}: marcador de system vazou para a bolha")

    # Comparacao com o desfecho real do corpus: a IA "deveria" ter conduzido (chegado a
    # confirmacao) nos casos que o cliente real convergiu? Rotulo, nao gabarito de fechamento.
    bate: bool | None = None
    if perfil.desfecho_real:
        convergiu_real = perfil.desfecho_real.startswith("convertido")
        bate = res.conduziu == convergiu_real

    return VeredictoE2E(
        perfil_nome=res.perfil_nome,
        conduziu=res.conduziu,
        desfecho_conducao=res.desfecho_conducao,
        estado_final=res.estado_final,
        bate_desfecho_real=bate,
        n_turnos=res.n_turnos,
        custo_brl=round(res.custo_brl, 6),
        violacoes=violacoes,
    )
