"""Rede final de saída no `enviar_turno`: o último ponto antes da bolha ir ao cliente (SEC-OUT-01).

O `output_guard` (ADR 0016) é um nó do grafo — cobre só o caminho do LLM. Os despachos canned
(transcrição falhou, `coordenador`) e o reengajamento (`timeouts`) enfileiram `enviar_turno`
DIRETO, pulando o guard. Além disso, o `output_guard` não redige PII. Estas funções puras dão a
`enviar_turno` duas defesas independentes que valem para TODOS os caminhos:

- **Vazamento de IA** (`tem_marcador_ia`, reusado do `output_guard` — fonte única do regex): a bolha
  admite ser IA/bot/LLM. Match → o `enviar_turno` bloqueia o turno e escala (a bolha não sai).
- **Eco de PII** (`redigir_pii_eco`): a IA repete CPF/RG/telefone que o PRÓPRIO cliente mandou
  (SEC-PII-02). Redação é **por eco**: só mascara o token se ele também aparece no inbound recente
  do cliente. Isso é deliberado — a chave Pix da modelo (que pode ser CPF/telefone, `workers/pix.py`)
  NUNCA vem do cliente, então nunca é mascarada e o fluxo do Pix de deslocamento segue intacto.
  Endereço/CEP ficam de fora (a IA combina endereço de atendimento externo legitimamente).
"""

from __future__ import annotations

import random
import re
from collections.abc import Callable

from barra.agente.fluxo import rotular_turno
from barra.agente.nos.output_guard import tem_marcador_ia

__all__ = [
    "extrair_tokens_pii",
    "normalizar_emoji_voz",
    "normalizar_travessao",
    "redigir_pii_eco",
    "tem_marcador_ia",
    "tem_placeholder_eco",
]

# PII do cliente que a IA não deve ecoar. Endereço/CEP de propósito fora (saída legítima). O `tipo`
# alimenta a métrica; em sobreposição de formato (telefone de 11 dígitos casa o shape de CPF) o
# rótulo pode ser impreciso, mas a redação — que é o que importa — acontece igual.
_PADROES_PII: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("cpf", re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")),
    ("rg", re.compile(r"\b\d{1,2}\.\d{3}\.\d{3}-?[\dxX]\b")),
    # RG corrido (sem pontuacao): 9 digitos EXATOS. 9 (nao 8) evita colidir com CEP, que fica de
    # fora de proposito (endereco e saida legitima). CPF (11) e telefone (10-13) tem outros shapes,
    # entao o cerco de digito-vizinho impede sobreposicao.
    ("rg", re.compile(r"(?<!\d)\d{9}(?!\d)")),
    (
        "telefone",
        re.compile(r"(?<!\d)(?:\+?55\s?)?\(?\d{2}\)?[\s.\-]?9?\d{4}[\s.\-]?\d{4}(?!\d)"),
    ),
)

# Comprimentos válidos do token (só dígitos) por tipo — corta falso-positivo de número curto/longo.
# RG aceita 7 (dígito verificador 'X' some no strip de dígitos) a 9.
_TAMANHOS_VALIDOS: dict[str, set[int]] = {
    "cpf": {11},
    "rg": {7, 8, 9},
    "telefone": {10, 11, 12, 13},
}

_REDIGIDO = "***"


def _digitos(texto: str) -> str:
    return re.sub(r"\D", "", texto)


def _valido(tipo: str, digitos: str) -> bool:
    return len(digitos) in _TAMANHOS_VALIDOS[tipo]


def _chaves(tipo: str, digitos: str) -> set[str]:
    """Chaves de equivalência p/ casar eco apesar de variação de formato. Telefone também casa pela
    cauda de 8 dígitos (absorve prefixo +55/DDD entre cliente e IA)."""
    chaves = {digitos}
    if tipo == "telefone" and len(digitos) >= 8:
        chaves.add(digitos[-8:])
    return chaves


def extrair_tokens_pii(texto: str) -> set[str]:
    """Conjunto de chaves normalizadas de toda PII (CPF/RG/telefone) achada no texto.

    Usado tanto para montar o set do inbound do cliente quanto para o pre-check barato da saída
    (se a saída não tem nenhum shape de PII, o `enviar_turno` nem consulta o banco)."""
    tokens: set[str] = set()
    for tipo, padrao in _PADROES_PII:
        for m in padrao.finditer(texto):
            d = _digitos(m.group())
            if _valido(tipo, d):
                tokens |= _chaves(tipo, d)
    return tokens


def redigir_pii_eco(texto: str, tokens_cliente: set[str]) -> tuple[str, list[str]]:
    """Mascara em `texto` só a PII cujo token normalizado também está em `tokens_cliente` (eco).

    Devolve `(texto_redigido, tipos_redigidos)`. `tokens_cliente` vazio → nada muda.
    """
    if not tokens_cliente:
        return texto, []
    redigidos: list[str] = []

    def _substituir(tipo: str) -> Callable[[re.Match[str]], str]:
        def _f(m: re.Match[str]) -> str:
            d = _digitos(m.group())
            if _valido(tipo, d) and (_chaves(tipo, d) & tokens_cliente):
                redigidos.append(tipo)
                return _REDIGIDO
            return m.group()

        return _f

    for tipo, padrao in _PADROES_PII:
        texto = padrao.sub(_substituir(tipo), texto)
    return texto, redigidos


# --- Eco de placeholder de ensino (SEC-OUT — bolha quebrada, não vai ao cliente) ------
# Os exemplos <ela> da persona/regras usam {valor}, {horario}, etc. como marcadores de "aqui entra
# o dado real", e a persona manda NUNCA escrever as chaves (persona.md). O DeepSeek às vezes copia
# o token literal (tic de modelo, "LLM resiste à instrução") — uma bolha com {valor} é uma cotação
# QUEBRADA (sem o número), pior que não responder. Casa as duas formas observadas: a chave
# {palavra} dos exemplos e o colchete instrucional inventado ([insira a rua], [seu endereço]).
# NÃO casa o marker [quote]/[quote: trecho] — o chunking já o removeu antes desta rede, e 'quote'
# não está nos gatilhos do colchete. Match → o enviar_turno bloqueia o turno e escala (handoff).
_PLACEHOLDER = re.compile(
    r"\{[a-zà-ÿ_]{2,20}\}"  # {valor}, {horario}, {nome}, {duracao}, {endereco}, ...
    r"|\[\s*(?:insira|inserir|coloque|preench\w*|adicione|informe|seu|sua|valor|"
    r"hor[áa]rio|endere\w*|rua|bairro)\b[^\]]*\]",  # [insira a rua], [seu endereço], ...
    re.IGNORECASE,
)


def tem_placeholder_eco(texto: str) -> bool:
    """True se a bolha tem placeholder de ensino não-substituído ({valor}, [insira ...]) (PURO).

    É uma cotação/fala QUEBRADA que não pode ir ao cliente: silenciar o token deixaria a bolha
    sem o dado (preço sem número), então o caller bloqueia+escala em vez de redigir. Não casa o
    marker [quote]/[quote: trecho] (já removido pelo chunking; 'quote' fora dos gatilhos)."""
    return bool(_PLACEHOLDER.search(texto))


# --- Normalização de emoji da voz (camada de calibração, não segurança) -------
# Mineração do corpus do Vendedor (scripts/eval_corpus/voz_por_momento.py, 2026-06-18): emoji é
# RARO (10,7% das bolhas, 94,7% delas com exatamente 1), de vocabulário minúsculo e afetivo
# (🥰 😊 dominam), concentrado na ABERTURA e ausente na venda dura (1% na sondagem). O modelo, por
# format-bias de RLHF ("From Lists to Emojis", ACL 2025), tende a saturar (E2E rig Lucia: 32%, só
# 🥰 repetido). Esta rede crava o whitelist e seca a venda; e como o prompt sozinho não basta (o
# DeepSeek satura mesmo instruído na persona.md), também afina a FREQUÊNCIA nos atos não-secos via
# sorteio per-bolha calibrado ao corpus (_EMOJI_KEEP_POR_ATO abaixo), seguindo stateless.

# Whitelist de voz: os dois únicos emoji que a persona usa (persona.md <voz>).
_EMOJI_PERMITIDOS = frozenset({"🥰", "😊"})

# Atos em que o Vendedor humano NÃO usa emoji (persona.md: "da cotação em diante é tudo seco").
_ATOS_SECOS = frozenset({"cotacao", "sondagem", "desconto", "logistica"})

# Trava de frequência nos atos NÃO-secos: mantém o emoji da bolha só com esta probabilidade,
# calibrada (keep = taxa_alvo_corpus / baseline_DeepSeek, medição 2026-06-22 sobre 765 bolhas) p/
# trazer a frequência do agente à do corpus humano (perfil_estilo_por_momento.json: saudação 27%,
# outro 9%). Os atos secos já zeram via _ATOS_SECOS; ato fora do dict = 1.0 (sem thinning).
_EMOJI_KEEP_POR_ATO = {"saudacao": 0.57, "outro": 0.34}

# RNG padrão do thinning (sorteio per-bolha). Injetável nos testes p/ determinismo.
_RNG = random.Random()  # noqa: S311 — uso cosmético (thinning de emoji), não criptográfico

# Faixas Unicode de emoji (mesmo recorte da estilometria do corpus). Inclui pictographs/emoticons,
# símbolos & dingbats, setas, estrelas suplementares, seletores de variação e bandeiras.
_EMOJI = re.compile(
    "["
    "\U0001f300-\U0001faff"
    "\U00002600-\U000027bf"
    "\U00002190-\U000021ff"
    "\U00002b00-\U00002bff"
    "\U0000fe00-\U0000fe0f"
    "\U0001f1e6-\U0001f1ff"
    "]"
)


def _normalizar_bolha(bolha: str, rng: random.Random | None = None) -> str:
    """Aplica whitelist + máx-1 + seca-na-venda + trava-de-frequência a UMA bolha. Não injeta emoji que o modelo não pôs."""
    matches = list(_EMOJI.finditer(bolha))
    if not matches:
        return bolha
    ato = rotular_turno(bolha)
    if ato in _ATOS_SECOS:
        manter = -1  # ato seco → remove todos
    else:
        # mantém só o ÚLTIMO emoji do whitelist (o corpus usa emoji como sufixo); o resto cai.
        permitidos = [i for i, m in enumerate(matches) if m.group() in _EMOJI_PERMITIDOS]
        manter = permitidos[-1] if permitidos else -1
        # trava de FREQUÊNCIA: o teto por-bolha não basta (o DeepSeek satura). Mantém o emoji só com
        # prob _EMOJI_KEEP_POR_ATO[ato], calibrada à taxa do corpus humano naquele ato.
        if manter >= 0 and (rng or _RNG).random() >= _EMOJI_KEEP_POR_ATO.get(ato, 1.0):
            manter = -1
    partes: list[str] = []
    fim = 0
    for i, m in enumerate(matches):
        partes.append(bolha[fim : m.start()])
        if i == manter:
            partes.append(m.group())
        fim = m.end()
    partes.append(bolha[fim:])
    # limpa o espaço/sujeira que a remoção deixa (espaço duplo, espaço antes de pontuação, sobra).
    texto = "".join(partes)
    texto = re.sub(r"[ \t]{2,}", " ", texto)
    texto = re.sub(r"\s+([,.!?])", r"\1", texto)
    return texto.strip()


def normalizar_emoji_voz(chunks: list[str], rng: random.Random | None = None) -> list[str]:
    """Normaliza o emoji de cada bolha do turno. Descarta bolha que ficou vazia (era só emoji fora
    do whitelist); se isso esvaziar o turno inteiro, devolve os chunks originais (não engole o turno).
    """
    out = [_normalizar_bolha(c, rng) for c in chunks]
    nao_vazios = [c for c in out if c.strip()]
    return nao_vazios or chunks


# --- Normalização de travessão da voz (camada de calibração, não segurança) ---
# persona.md <voz>: "nada de travessão (aquele traço longo de teclado de computador), que ninguém
# digita no celular e te entrega como robô. Onde pensaria em usar um, quebre a bolha ou use
# vírgula." O DeepSeek vaza '—' (em-dash) mesmo instruído (tic de modelo, mais comum em formatação
# de endereço: "Rua X — Bairro"). Esta rede crava a regra de forma determinística: troca o em-dash
# (U+2014) por vírgula — a opção sempre-gramatical (a outra, "quebrar a bolha", é impossível pós-
# chunking, e a vírgula casa o "use vírgula" da persona). NUNCA toca o hífen ASCII '-' (bem-vindo,
# guarda-roupa são legítimos) nem o en-dash U+2013 (raro e ambíguo com faixa numérica; sem
# evidência de vazamento). Stateless; não injeta nada que o modelo não pôs.
_TRAVESSAO = re.compile(r"\s*—+\s*")  # em-dash '—', o "traço longo" da persona <voz>


def _normalizar_travessao_bolha(bolha: str) -> str:
    """Troca em-dash por vírgula numa bolha e limpa a sujeira da troca. No-op sem em-dash."""
    if "—" not in bolha:
        return bolha
    texto = _TRAVESSAO.sub(", ", bolha)
    texto = re.sub(r"^\s*,\s*", "", texto)  # ponta inicial (lista/ênfase solta) → só some
    texto = re.sub(r"\s*,\s*$", "", texto)  # ponta final → só some
    texto = re.sub(r",\s*,", ",", texto)  # vírgula dupla
    texto = re.sub(r"[ \t]{2,}", " ", texto)  # espaço duplo
    texto = re.sub(r"\s+([,.!?])", r"\1", texto)  # espaço antes de pontuação
    return texto.strip()


def normalizar_travessao(chunks: list[str]) -> list[str]:
    """Troca o travessão (em-dash) por vírgula em cada bolha do turno (persona <voz>). Não toca o
    hífen ASCII nem o en-dash; preserva a contagem de bolhas (transform por-bolha, sem dropar)."""
    return [_normalizar_travessao_bolha(c) for c in chunks]
