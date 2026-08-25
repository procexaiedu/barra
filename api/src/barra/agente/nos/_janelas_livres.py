"""Pré-cálculo das JANELAS LIVRES da agenda — o positivo que faltava no contexto (#41, 24/07).

O `<agenda>` só dizia o NEGATIVO (os bloqueios) mais dois horários-âncora (`horario_minimo`,
`proximo_horario`). Ler "quando estou livre" a partir disso é uma subtração que o LLM faz mal: no
#41 o dia estava vago desde as 10h, o único número concreto que sobrou no contexto foi o
`proximo_livre` de um bloqueio das 16-17, e a IA o vendeu como "17:30 é o horário que tenho livre
hoje". A aritmética (recortar as sessões de trabalho, descontar bloqueio + buffer dos dois lados,
arredondar pra hora social) é determinística — roda aqui, em Python puro, e a IA só verbaliza.

É camada de conversa, igual ao `_proximo_livre`: oferece o intervalo em que ela pode COMEÇAR um
atendimento; a duração efetiva o pré-cálculo não conhece, e a reserva re-valida na criação.
"""

from datetime import datetime, timedelta
from typing import Any

from barra.dominio.agenda.service import buffer_do_bloqueio_min
from barra.dominio.modelos.disponibilidade import sessoes_disponibilidade

from ._proximo_livre import _arredonda_meia_hora_acima

# Vão livre curto demais pra virar oferta: o menor programa do cardápio dura 1h, então uma fresta
# de 40min entre dois compromissos não é horário que ela possa oferecer — anunciá-la só produziria
# uma proposta que a reserva recusa depois.
_MIN_JANELA_MIN = 60


def janelas_livres(
    inicio: datetime,
    fim: datetime,
    blocos: list[dict[str, Any]],
    regras_disp: list[dict[str, Any]],
    buffer_min: int,
) -> list[tuple[datetime, datetime]]:
    """Intervalos reserváveis dentro de `[inicio, fim)`, já descontados bloqueios e buffer.

    Cada bloqueio é descontado ALARGADO pelo buffer dos dois lados (ADR 0025: gap >= buffer, a
    adjacência não é reservável) — a mesma aritmética do `proximo_livre`, aplicada ao intervalo
    inteiro em vez de a um ponto. O início de cada janela sobe pra próxima meia-hora (fala social);
    o fim é o instante em que o próximo compromisso — ou o expediente — fecha, sem arredondar (para
    baixo perderia minutos reais; para cima ofereceria o que não existe).

    O buffer é POR BLOCO (emenda ADR 0025, 2026-08-14): o bloco `externo` alarga por
    `agenda_buffer_externo_min` (a viagem até a casa do cliente e a volta), os demais e o bloco sem
    tipo seguem em `buffer_min`. Mesma função (`buffer_do_bloqueio_min`) do `proximo_livre` e do
    gate da reserva — janela oferecida que a reserva recusa é o bug que esta simetria evita.
    """
    livres: list[tuple[datetime, datetime]] = []
    for sessao in sessoes_disponibilidade(regras_disp, inicio, fim):
        pedacos = [sessao]
        for bloco in blocos:
            buffer = timedelta(
                minutes=buffer_do_bloqueio_min(bloco.get("tipo_atendimento"), buffer_min=buffer_min)
            )
            ocupado_ini, ocupado_fim = bloco["inicio"] - buffer, bloco["fim"] + buffer
            restantes: list[tuple[datetime, datetime]] = []
            for p_ini, p_fim in pedacos:
                if ocupado_fim <= p_ini or ocupado_ini >= p_fim:
                    restantes.append((p_ini, p_fim))
                    continue
                if p_ini < ocupado_ini:
                    restantes.append((p_ini, ocupado_ini))
                if ocupado_fim < p_fim:
                    restantes.append((ocupado_fim, p_fim))
            pedacos = restantes
        for p_ini, p_fim in pedacos:
            ofertavel = _arredonda_meia_hora_acima(p_ini)
            if p_fim - ofertavel >= timedelta(minutes=_MIN_JANELA_MIN):
                livres.append((ofertavel, p_fim))
    return sorted(livres)
