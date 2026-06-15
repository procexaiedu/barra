"""PerfilCaso: ancora o cliente simulado num caso real do corpus.

Descreve UM atendimento pelo que conduz a venda — a modelo (cardapio/tipo aceito), a
abertura do cliente, a persona/objecoes (para o ClienteLLM reencenar) e o desfecho real
do corpus (rotulo de comparacao; a IA nunca o produz — ver __init__ e CONTEXT.md
"Registro de resultado").

A extracao de PerfilCaso a partir de `corpus.threads`/`corpus.turnos` e um passo offline
(ver README.md §extracao); os casos de validacao deste pacote sao montados a mao.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Linha de chegada da conducao pela IA: ate aqui a conversa com o cliente leva o atendimento.
# `Confirmado` so com Pix externo validado (ator externo), mas e estado-alvo valido tambem.
ESTADOS_CONDUZIDOS = frozenset({"Aguardando_confirmacao", "Confirmado"})

# Modelo sintetica fixa dos casos e2e. A ponte corpus(@lid)->modelo real e irrecuperavel
# (memoria corpus_lid_telefone_irrecuperavel), entao o cardapio real nao da pra recuperar; e
# preco/programa nao afetam a fidelidade da jogada (mesma premissa de evals/shadow). So o lado
# do CLIENTE vem do corpus; a modelo e este perfil placeholder coerente.
MODELO_SINTETICA: dict[str, Any] = {
    "nome": "Manu",
    "idade": 25,
    "tipo_atendimento_aceito": ["interno", "externo"],
    "localizacao_operacional": "Barra (Campinas-SP)",
    "endereco_formatado": "Chácara da Barra, Campinas-SP",
    "programas": [
        {"nome": "Encontro", "duracao_nome": "1 hora", "horas": 1, "preco": 400},
        {"nome": "Encontro", "duracao_nome": "2 horas", "horas": 2, "preco": 700},
        {"nome": "Pernoite", "duracao_nome": "12 horas", "horas": 12, "preco": 2500},
    ],
}


@dataclass
class PerfilCaso:
    """Um caso e2e. `modelo` segue o spec de `evals.harness._seed_modelo`."""

    nome: str  # rotulo do caso (ex.: "interno_decidido")
    abertura: str  # 1a mensagem do cliente (primeiro turno do agente)
    modelo: dict[str, Any]  # spec do harness: nome, tipo_atendimento_aceito, programas, ...
    # Respostas do cliente roteirizado, em ordem (offline, sem credito). Esgotou -> cliente sumiu.
    roteiro_cliente: list[str] = field(default_factory=list)
    # Persona/objecoes em linguagem natural — alimenta o ClienteLLM (corrida real, §0).
    persona: str = ""
    tipo_esperado: str | None = (
        None  # tipo_atendimento que o caso deveria fixar (interno/externo/remoto)
    )
    # Rotulos do corpus para comparacao (a IA nao os decide):
    desfecho_real: str | None = None  # corpus.threads.desfecho_proxy (ex.: convertido_provavel)
    label_bin: str | None = None  # corpus.eval_cotacao.label_bin: GOOD | BAD
    thread_ref: str | None = None  # origem no corpus (instancia:remote_jid), p/ rastreio
    # Eixo de COMPORTAMENTO do cliente (estratificacao de cobertura, nao so desfecho). Vazio nos
    # cenarios sinteticos de funcionalidade; preenchido por `extracao.extrair_nucleo`.
    eixo_comportamento: str = ""


def perfil_para_fixture(perfil: PerfilCaso) -> dict[str, Any]:
    """Converte um PerfilCaso na fixture de `evals.harness.seedar`.

    O atendimento nasce em `Novo` (primeiro contato, antes de triagem) — a conducao do
    agente e que deve avancar a maquina de estados ao longo dos turnos.
    """
    return {
        "cenario": {"modelo": perfil.modelo, "atendimento": {"estado": "Novo"}},
        "historico": [],
    }
