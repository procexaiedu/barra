"""Perfis de cliente para variar a persona nas rodadas em massa (EVAL-12 / RealUserSim).

Um `PerfilCliente` varia so a FORMA da conversa (ritmo, tom, pechincha, desconfianca) -- NUNCA o
objetivo (`o_que_quer`) nem os atos. Os roteiros `decidir_ato` dos cenarios (cenarios.py) disparam
por indice+estado; mudar o objetivo dessincronizaria o roteiro da intencao e a jornada morreria
"por construcao". Mudar so a forma e seguro: os guards por estado (`Aguardando_confirmacao` etc.)
continuam constrangendo os atos.

Anti-leakage (RealUserSim): o `estilo` entra no prompt do cliente, entao passa pelo mesmo check de
termos de gabarito de `montar_prompt_cliente` -- um perfil jamais pode citar expectativa de fixture.

PURO: zero LLM, zero DB.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from .cliente import PersonaCliente


@dataclass(frozen=True)
class PerfilCliente:
    """Variacao de FORMA da persona: como o cliente escreve e negocia, nao o que ele quer."""

    nome: str
    estilo: str


PERFIS: tuple[PerfilCliente, ...] = (
    PerfilCliente(
        nome="apressado",
        estilo=(
            "voce esta com pressa: mensagens muito curtas, sem rodeio, quer resolver rapido e "
            "cobra resposta objetiva (preco e horario logo de cara)"
        ),
    ),
    PerfilCliente(
        nome="regateiro",
        estilo=(
            "voce sempre tenta pagar menos: reclama do preco uma vez e pede para melhorar, mas "
            "sem travar a conversa -- se nao rolar, voce aceita e segue o que veio fazer"
        ),
    ),
    PerfilCliente(
        nome="desconfiado",
        estilo=(
            "voce e desconfiado: faz perguntas para confirmar que ela e real (foto recente, "
            "detalhe do local), mas sem virar interrogatorio -- confirmado o basico, voce segue"
        ),
    ),
    PerfilCliente(
        nome="recorrente",
        estilo=(
            "voce ja foi cliente dela antes e escreve com intimidade de quem volta: cumprimenta "
            "como conhecido, referencia 'da outra vez' de forma vaga e vai direto ao ponto"
        ),
    ),
    PerfilCliente(
        nome="laconico",
        estilo=(
            "voce escreve pouquissimo: respostas de uma a cinco palavras, abreviacoes (vc, blz, "
            "qto), nunca elabora -- quem puxa a conversa e ela"
        ),
    ),
    PerfilCliente(
        nome="prolixo",
        estilo=(
            "voce escreve demais: mensagens longas, conta contexto irrelevante da sua vida, "
            "enrola para decidir -- mas no fim sempre volta ao que veio resolver"
        ),
    ),
)


def variar_persona(persona: PersonaCliente, perfil: PerfilCliente | None) -> PersonaCliente:
    """Copia da persona com o `estilo` do perfil (PURA). `None` = persona original (amostra k0).

    So a forma muda: nome/intencao/orcamento/atos sao preservados -- e o que mantem os roteiros
    `decidir_ato` sincronizados com a jornada.
    """
    if perfil is None:
        return persona
    return replace(persona, estilo=perfil.estilo)
