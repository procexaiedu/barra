"""Conversas FIXAS (cliente roteirizado) para gerar calibracao barata e reutilizavel (EVAL-12).

Cada `CenarioFixo` carrega uma lista de FALAS DE CLIENTE pre-escritas (`mensagens_cliente`) -- tiradas
quase literais das conversas REAIS que temos documentadas (`docs/agente/conversas-reais/001..004`) +
variacoes -- em vez de uma `PersonaCliente` que pede falas ao Sonnet. O arnes `gerar_conversas.py
--fixo` roda cada um via `sim/loop.py:jornada` contra o GRAFO REAL com `ClienteRoteirizado`, gravando
em `evals/calibracao/conversas_fixas.jsonl`. So a IA roda ao vivo (custa ~metade do cliente-LLM); o
corpus e congelavel e reusavel.

Reusa os MESMOS roteiros de atos dual-control de `cenarios.py` (`_roteiro_pix`/`_roteiro_portaria`):
o cliente fixo so escreve o TEXTO; mandar Pix / foto de portaria continua sendo ato que muta o estado
real (atos.py). Regra de dimensionamento dos roteiros aqui: como todas as falas sao consumidas ANTES
de qualquer ato, a foto/pix dispara logo apos a ultima fala (`portaria_em`/`a_partir` ~= nº de falas).

NAO-GATE e NAO-DETERMINISTICO (sim/README.md): o gate segue sendo o corpus `scripted_5/` via
runner.py. Estas conversas servem so para o humano rotular ✓/✕ na evals-notas.html -- nunca contam
para o cutover. ANTI-LEAKAGE: as falas sao do CLIENTE realista, nunca embutem o veredito esperado.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .cenarios import RoteiroAtos, _roteiro_pix, _roteiro_portaria
from .cliente import AtoNome


@dataclass
class CenarioFixo:
    """Uma conversa fixa: falas de cliente pre-escritas + estado inicial + roteiro opcional de atos.

    `atos_disponiveis` espelha quais atos o `decidir_ato` pode disparar (igual a `PersonaCliente`),
    so para a guarda de consistencia do teste offline -- o cliente fixo nao "tem" atos, e o roteiro
    quem os aplica.
    """

    nome: str
    mensagens_cliente: list[str]
    estado_inicial: dict[str, Any] = field(
        default_factory=lambda: {"atendimento_estado": "Triagem"}
    )
    decidir_ato: RoteiroAtos | None = None
    max_turnos: int = 8
    atos_disponiveis: list[AtoNome] = field(default_factory=list)


CENARIOS_FIXOS: list[CenarioFixo] = [
    # --- F4.1: jornada FIXA que COMECA em `Novo` (1o contato, antes da triagem) ------------------
    # Gemea deterministica de `cenarios.primeiro_contato_novo`: parte de `Novo` (as demais nascem em
    # `Triagem`) e a 1a fala ("oi" + preco) dispara Novo->Triagem pela conversa. Fecha interno por
    # portaria -- a maquina de estados desde a entrada, com cliente roteirizado (sem cliente-LLM).
    CenarioFixo(
        nome="fixo_primeiro_contato_novo",
        mensagens_cliente=[
            "Oi, tudo bem?",
            "vi seu anuncio. quanto e 1h hoje a noite?",
            "e ai no seu local? prefiro ir ate voce",
            "fechou, pode ser umas 22h?",
            "qual seu endereco",
            "to indo ai",
            "cheguei, to na portaria",
        ],
        estado_inicial={"atendimento_estado": "Novo"},
        decidir_ato=_roteiro_portaria(aviso_em=None, portaria_em=8),
        max_turnos=11,
        atos_disponiveis=["enviar_foto_portaria"],
    ),
    # --- 4 BASE: 1:1 das conversas reais que converteram (001..004) -----------------------------
    CenarioFixo(
        # 001: interno, recusa de anal em 3 camadas, desconto unico ancorado, fecha por portaria.
        nome="fixo_001_anal_desconto",
        mensagens_cliente=[
            "Oi, vi voce no Barra Vip 😍",
            "Quanto e o cache?",
            "Voce faz anal?",
            "Mas voce faz? Queria demais",
            "ta. atende casal tambem? curiosidade",
            "nao, seria so pra mim. e e ai no seu local? prefiro ir ate voce",
            "nao consegue melhorar o preco? 😅",
            "pode ser hoje umas 22h",
            "as 22h entao? qual seu endereco",
            "ok, combinado, to indo ai",
        ],
        decidir_ato=_roteiro_portaria(aviso_em=10, portaria_em=11),
        max_turnos=14,
        atos_disponiveis=["enviar_aviso_saida", "enviar_foto_portaria"],
    ),
    CenarioFixo(
        # 002: cliente pergunta casal/dupla, recua pra solo (modelo nao insiste), fecha por portaria.
        nome="fixo_002_dupla_solo",
        mensagens_cliente=[
            "Oi, vi voce no Barra Vip's",
            "Como funciona? Quanto?",
            "voce atende casal? ou tem alguma amiga pra fazer dupla?",
            "hmm, e a dupla fica quanto?",
            "deixa, vou querer so voce mesmo entao 😅",
            "e ai no seu local? vou ate voce, pode ser 1h",
            "que horas voce pode hoje?",
            "fechou, qual o apto?",
            "to chegando, na portaria",
        ],
        decidir_ato=_roteiro_portaria(aviso_em=None, portaria_em=10),
        max_turnos=13,
        atos_disponiveis=["enviar_foto_portaria"],
    ),
    CenarioFixo(
        # 003: cliente bilingue (ES/PT) propoe role externo "louco"; modelo ancora no apto dela
        # (interno) e o cliente topa; "me da um bom preco" absorvido; "donde es?"; fecha por portaria.
        nome="fixo_003_es_externo_ancora",
        mensagens_cliente=[
            "Ola, vi voce no Barra Vip's",
            "si, estoy aqui no RJ. quanto?",
            "me manda fotos. eu cubro todas as despesas",
            "estou num bar com meu amigo e a namorada dele vendo o Super Bowl. vem se juntar a nos, "
            "depois a gente vai pro hotel",
            "demais. me da um bom preco",
            "ta, e se eu for ai no teu apartamento entao? donde es?",
            "yes, 1 hora. vou de uber",
            "estou a caminho, sozinho num uber",
            "llegando, estou aqui na portaria",
        ],
        decidir_ato=_roteiro_portaria(aviso_em=None, portaria_em=10),
        max_turnos=13,
        atos_disponiveis=["enviar_foto_portaria"],
    ),
    CenarioFixo(
        # 004: cliente quer VIDEOCHAMADA paga antes de marcar + cartao parcelado. A IA RECUSA
        # videochamada (decisao de produto, FAQ negativa); cartao e aceito com taxa, parcelado e P1.
        # Adversarial: termina em recusa/esclarecimento, sem ato.
        nome="fixo_004_videocall_cartao",
        mensagens_cliente=[
            "Bom dia, tudo bem?",
            "vi um anuncio seu, queria mais informacoes. quanto e 1h?",
            "voce faz video chamada antes? pra eu confirmar que e voce",
            "quanto e a videochamada? e quanto tempo?",
            "e da pra pagar no cartao de credito parcelado?",
            "entao ta, mas a videochamada eu queria muito viu",
        ],
        max_turnos=8,
    ),
    # --- 3 VARIACOES (mesmo tom real, exercitam outra fronteira) ---------------------------------
    CenarioFixo(
        # variacao de 001: pechincha forte ABAIXO do piso de desconto -> a IA escala (fora_de_oferta)
        # em vez de negociar. Adversarial; observavel pela tool `escalar` (linha em escaladas).
        nome="fixo_var_desconto_abaixo_piso",
        mensagens_cliente=[
            "Oi, quanto e 1h hoje?",
            "nossa, ta caro. faz por bem menos?",
            "qual o melhor preco que voce consegue fazer?",
            "consigo pagar uns 400 no maximo, topa?",
            "vai, faz por 400 que eu vou agora",
            "400 e fechamos, pode ser?",
        ],
        max_turnos=8,
    ),
    CenarioFixo(
        # variacao EXTERNO: a modelo se desloca ao hotel do cliente; Pix de deslocamento (valido)
        # faz o atendimento avancar pra Confirmado e a IA pausa. Exercita a mecanica do pix.
        nome="fixo_var_externo_pix",
        mensagens_cliente=[
            "Oi, vi voce no Barra Vip",
            "voce vai ate o cliente? to num hotel na barra",
            "quanto fica 1h aqui no meu hotel hoje a noite?",
            "como funciona o pagamento? tem que mandar algo antes?",
            "beleza, me passa o pix do deslocamento que eu mando o comprovante",
            "combina pra umas 22h entao",
        ],
        decidir_ato=_roteiro_pix("enviar_pix_valido", a_partir=6),
        max_turnos=10,
        atos_disponiveis=["enviar_pix_valido"],
    ),
    CenarioFixo(
        # variacao de 003: gringo de fato (EN puro). A IA acompanha o idioma; interno, fecha por
        # portaria; inclui recusa de anal em ingles.
        nome="fixo_var_gringo_ingles",
        mensagens_cliente=[
            "Hi, I saw you on Barra Vips",
            "how much for one hour tonight? I can go to your place",
            "do you do anal?",
            "ok no problem. where are you? I'll take an uber",
            "perfect, let's do one hour. what time works tonight?",
            "great, I'm on my way, alone in an uber",
            "I'm here at the entrance",
        ],
        decidir_ato=_roteiro_portaria(aviso_em=None, portaria_em=8),
        max_turnos=11,
        atos_disponiveis=["enviar_foto_portaria"],
    ),
]


# --- HELD-OUT: medição de generalização, NUNCA usado para iterar (anti-overfit) --------------------
# O loop de iteração (Loop A) roda só `CENARIOS_FIXOS`. Estes cobrem fronteiras do corpus real ainda
# NÃO exercitadas pelos de iteração -- cartão com taxa (decisão 2026-06-02), revelação progressiva de
# endereço (§7), cliente que volta sem cobrar (§12). Se o agente fica "redondo" nos de iteração mas
# falha aqui, isso é OVERFIT -- por isso este conjunto é separado e a medição ≥90% roda os DOIS.
CENARIOS_FIXOS_HELDOUT: list[CenarioFixo] = [
    CenarioFixo(
        # cartão: a IA aceita com taxa de ~10% da maquininha e NÃO oferece parcelamento (faq.md:35-36,
        # decisao 2026-06-02 / ADR 0013). Fecha interno por portaria.
        nome="fixo_heldout_cartao_taxa",
        mensagens_cliente=[
            "Oi, quanto e 1h?",
            "aceita cartao? levo so o cartao hoje",
            "da pra parcelar em 3x?",
            "beleza, entao pix mesmo. pode ser hoje 21h?",
            "qual seu endereco",
            "to indo ai",
            "cheguei, to na portaria",
        ],
        decidir_ato=_roteiro_portaria(aviso_em=None, portaria_em=8),
        max_turnos=11,
        atos_disponiveis=["enviar_foto_portaria"],
    ),
    CenarioFixo(
        # revelacao progressiva de endereco (§7): cliente pede AP cedo; a IA da bairro e so libera o
        # apartamento depois do cliente confirmar que vem.
        nome="fixo_heldout_localizacao_progressiva",
        mensagens_cliente=[
            "Oi vi voce no Barra Vip",
            "me passa seu endereco completo",
            "qual o apartamento?",
            "ta, e quanto fica 1h?",
            "fechou, vou ate voce agora",
            "to chegando, qual o ap?",
            "to na portaria",
        ],
        decidir_ato=_roteiro_portaria(aviso_em=None, portaria_em=8),
        max_turnos=11,
        atos_disponiveis=["enviar_foto_portaria"],
    ),
    CenarioFixo(
        # cliente esfria ("vou pensar") e volta sozinho (§12): a IA recebe sem cobrar, sem novo
        # desconto, sem "sumiu?" (anti-padrao §19.3). Fecha por portaria.
        nome="fixo_heldout_volta_sem_cobrar",
        mensagens_cliente=[
            "Oi, quanto 1h?",
            "hmm, vou pensar e te falo",
            "voltei, bora marcar pra hoje",
            "e ai no seu local, pode ser 22h?",
            "qual o endereco",
            "to indo",
            "cheguei na portaria",
        ],
        decidir_ato=_roteiro_portaria(aviso_em=None, portaria_em=8),
        max_turnos=11,
        atos_disponiveis=["enviar_foto_portaria"],
    ),
]


def todos_fixos() -> list[CenarioFixo]:
    """Iteração + held-out -- o conjunto completo p/ a MEDIÇÃO de generalização e p/ gerar o corpus de
    calibração. O Loop A itera só sobre `CENARIOS_FIXOS`; nunca sobre o held-out."""
    return [*CENARIOS_FIXOS, *CENARIOS_FIXOS_HELDOUT]
