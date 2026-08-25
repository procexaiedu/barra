"""PerfilCaso: ancora o cliente simulado num caso real do corpus.

Descreve UM atendimento pelo que conduz a venda — a modelo (cardapio/tipo aceito), a
abertura do cliente, a persona/objecoes (para o ClienteLLM reencenar) e o desfecho real
do corpus (rotulo de comparacao; a IA nunca o produz — ver __init__ e CONTEXT.md
"Registro de resultado").

A extracao de PerfilCaso a partir de `corpus.threads`/`corpus.turnos` e um passo offline
(ver README.md §extracao); os casos de validacao deste pacote sao montados a mao.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .cliente import FalaDoCliente

# Linha de chegada da conducao pela IA: ate aqui a conversa com o cliente leva o atendimento.
# `Confirmado` so com Pix externo validado (ator externo), mas e estado-alvo valido tambem.
ESTADOS_CONDUZIDOS = frozenset({"Aguardando_confirmacao", "Confirmado"})

# Modelo sintetica fixa dos casos e2e. A ponte corpus(@lid)->modelo real e irrecuperavel
# (memoria corpus_lid_telefone_irrecuperavel), entao o cardapio real nao da pra recuperar; e
# preco/programa nao afetam a fidelidade da jogada (mesma premissa de evals/shadow). So o lado
# do CLIENTE vem do corpus; a modelo e este perfil placeholder coerente.
#
# O cadastro cobre os TRES tipos (interno/externo/remoto) e o cardapio traz a linha de video
# chamada. Nao e enfeite: sem ela, todo cliente do corpus que pede chamada bate num cadastro que
# nao vende chamada e o caso vira handoff POR CADASTRO SINTETICO — o instrumento mede o
# placeholder, nao a conduta da IA (ciclo 7 da campanha: 2 de 14 threads reais do lote vendiam
# video chamada, 150 por 15 minutos). O harness terminal ja resolvia isso INCONDICIONALMENTE
# (scripts/eval_corpus/replay_agente_terminal.py: `PROGRAMAS` + `_fixture_cenario`, que forca
# `["interno","externo","remoto"]`; idem replay_agente_adversarial.py) — aqui seguimos o mesmo
# precedente, com os MESMOS valores (a duracao "15 minutos" e get-or-create por nome no catalogo
# global: divergir criaria uma segunda linha). Incondicional tambem porque nao ha sinal de thread
# para condicionar: `corpus.threads.tipo_atendimento_proxy` so produz interno/externo/ambos
# (ver `extracao._TIPO_PROXY`), nunca 'remoto'.
MODELO_SINTETICA: dict[str, Any] = {
    "nome": "Manu",
    "idade": 25,
    "tipo_atendimento_aceito": ["interno", "externo", "remoto"],
    "localizacao_operacional": "Barra (Campinas-SP)",
    "endereco_formatado": "Rua Latino Coelho, 421 - Chácara da Barra, Campinas-SP",
    "programas": [
        {"nome": "Encontro", "duracao_nome": "1 hora", "horas": 1, "preco": 400},
        {"nome": "Encontro", "duracao_nome": "2 horas", "horas": 2, "preco": 700},
        {"nome": "Pernoite", "duracao_nome": "12 horas", "horas": 12, "preco": 2500},
        # `e_video_chamada` (core/catalogo) casa pelo substring "chamada": e este nome que faz a
        # cauda parar de renderizar <sem_video_chamada> e que tira a linha remota da escada de
        # desconto (`_linhas_da_duracao(apenas_presenciais=True)`).
        {
            "nome": "Video chamada",
            "duracao_nome": "15 minutos",
            "horas": 0.25,
            "preco": 150,
            "ordem": 1,
        },
    ],
}


@dataclass
class PerfilCaso:
    """Um caso e2e. `modelo` segue o spec de `evals.harness._seed_modelo`."""

    nome: str  # rotulo do caso (ex.: "interno_decidido")
    # 1a mensagem do cliente (primeiro turno do agente). `list[str]` = as bolhas de um BURST — o
    # cliente mandando duas mensagens seguidas antes de a IA responder (ver `cliente.FalaDoCliente`).
    abertura: FalaDoCliente
    modelo: dict[str, Any]  # spec do harness: nome, tipo_atendimento_aceito, programas, ...
    # Respostas do cliente roteirizado, em ordem (offline, sem credito). Esgotou -> cliente sumiu.
    # Cada item e uma bolha (str) ou um burst de bolhas (list[str]).
    roteiro_cliente: Sequence[FalaDoCliente] = field(default_factory=list)
    # Persona/objecoes em linguagem natural — alimenta o ClienteLLM (corrida real, §0).
    persona: str = ""
    # Falas reais do Vendedor (V:) no transcript original, uma por linha, no mesmo texto que o
    # ClienteLLM ve na persona — lista de bloqueio p/ sanear_fala_cliente nao deixar o ClienteLLM
    # copiar a voz do Vendedor (ver evals.e2e.extracao._montar).
    linhas_vendedor: list[str] = field(default_factory=list)
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
    # --- Relogio e agenda inicial do caso (F0 da matriz de cenarios, 13/08) ---------------------
    # Sao os MESMOS parametros de `runner.rodar_e2e`, declarados aqui porque quem roda a massa
    # (`massa.rodar_massa`) chama o runner sem eles: o cenario e a unica coisa que o loop carrega,
    # entao um caso de agenda que declarasse o relogio so no call-site seria impossivel de rodar em
    # massa. Argumento explicito do `rodar_e2e` vence estes; ausentes = relogio de parede e agenda
    # vazia, o comportamento de todos os casos anteriores a esta chave.
    #
    # `agora` ancora o seed E cada turno (memoria `rig_relogio_injetado_finge_7_dias`: ancorar so um
    # lado fabrica tempo decorrido e marca de pausa sintetica). `bloqueios`/`atendimento` seguem o
    # spec de `harness.seedar` (`{inicio, fim|duracao_min, estado?, atendimento?}` / os campos de
    # `_seed_atendimento`), com as horas relativas a `agora`.
    agora: datetime | None = None
    passo_min: int = 0  # avanco constante entre turnos
    offsets_min: list[int] | None = None  # offsets por turno (vencem `passo_min`)
    bloqueios: list[dict[str, Any]] = field(default_factory=list)
    atendimento: dict[str, Any] = field(default_factory=dict)


def perfil_para_fixture(perfil: PerfilCaso) -> dict[str, Any]:
    """Converte um PerfilCaso na fixture de `evals.harness.seedar`.

    O atendimento nasce em `Novo` (primeiro contato, antes de triagem) — a conducao do
    agente e que deve avancar a maquina de estados ao longo dos turnos.
    """
    return {
        "cenario": {"modelo": perfil.modelo, "atendimento": {"estado": "Novo"}},
        "historico": [],
    }
