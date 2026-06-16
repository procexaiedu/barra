"""Classificador heuristico de disclosure/jailbreak sobre a janela (10 §8).

Roda DENTRO do grafo (chamado pelo prepare_context, 03 §7), nao no webhook: com debounce
first-wins + drain loop a unidade de processamento e a JANELA do turno, nao um evento de
mensagem unico -- classificar no webhook perderia o disclosure que esta na 2a/3a mensagem de
um burst (10 §8). O regex do webhook fica so como sinal leve de metrica/log.

Duas familias SEPARADAS (decisao grilling 2026-05-23):
- identidade (generico ia/bot/robo E modelo nomeado gpt/claude/gemini) -> MESMO balde,
  canned + contador, escala na 3a (10 §2.1);
- jailbreak / override de instrucao -> escala DIRETO, sem canned nem contagem (10 §2.1, §4.4).

Os padroes aqui partem do esqueleto do 10 §8, ajustados para casar os tres exemplos que o
10 §3.1 declara como alta confianca ("vc e IA?", "e robo?", "vc e real?"): o sujeito
(voce/vc) e opcional e o substantivo de "pessoa real" tambem -- senao "e robo?" e "vc e
real?" (sem "voce" / sem "pessoa") nao casariam o esqueleto literal.

NORMALIZACAO (memoria `classificador_disclosure_depende_acento`): o texto passa por
`normalizar` ANTES da regex -- diacriticos removidos + casefold + whitespace colapsado. Os
padroes operam SO sobre texto normalizado (sem acento, minusculo): "é"->"e", "robô"->"robo",
"você"->"voce", "já"->"ja". Por isso NAO ha variante acentuada aqui -- acento nunca chega a
regex. O efeito colateral e que "é"(verbo) colapsa em "e"(conjuncao) e "ia"(IA) em "ia"(verbo):
para nao gerar falso-positivo em fala normal ("e ia te chamar"), o disclosure exige um GATE --
sujeito (voce/vc/tu) OU artigo (um/uma) OU um substantivo forte (bot/robo/gpt/...) que nao
aparece em conversa normal. Ver os comentarios por padrao abaixo.
"""

import re

from langchain_core.messages import BaseMessage, HumanMessage

from ._normalizar import normalizar

# Identidade: generico (ia/bot/robo) E modelo nomeado (gpt/claude/gemini) -- MESMO balde,
# tratados igual (canned + contador, escala na 3a). Ver 10 §2.1. Texto JA normalizado (sem acento).
_NOUNS_IDENTIDADE = r"(ia|ai|bot|robo|chatbot|gpt|chatgpt|claude|gemini|llama)"
# Substantivos FORTES (sem "ia"/"ai", que colidem com o verbo "ia" e o adverbio "ai"=aí): nao
# aparecem em fala normal de cliente, entao dispensam o gate de sujeito/artigo.
_NOUNS_FORTES = r"(bot|robo|chatbot|gpt|chatgpt|claude|gemini|llama)"
PADROES_DISCLOSURE = [
    # com SUJEITO ("voce/vc/tu e <noun>"): o sujeito desambigua "e"(=é) de "e"(=conjuncao).
    rf"\b(voce |vc |tu )e (um |uma )?{_NOUNS_IDENTIDADE}\b",
    # com ARTIGO ("e um/uma <noun>"): o artigo desambigua "e ia"(verbo) de "e um(a) ia"(identidade).
    rf"\be (um |uma ){_NOUNS_IDENTIDADE}\b",
    # substantivo FORTE sozinho ("e bot?", "e robo?"): dispensa sujeito/artigo (nao e fala normal).
    rf"\be {_NOUNS_FORTES}\b",
    # "pessoa real": "vc e real?", "to falando com uma pessoa?", "e mesmo humana?".
    r"\b(e|to falando com|e mesmo) (uma? )?(pessoa|humana?|real|de verdade)\b",
]

# Jailbreak / override de instrucao: escala DIRETO (sem canned, sem contagem). Ver 10 §2.1, §4.4.
PADROES_JAILBREAK = [
    r"\bdan mode\b",
    r"\b(developer|dev) mode\b",
    r"ignore (previous|all|prior) instructions",
    r"\besquece tudo\b.*\bvoce\b",
    r"\[system\]",
    r"</persona>",
]

PADROES_PROVA = [
    r"\b(manda|envia|me manda) (um |uma )?(audio|foto|video)\b.*(agora|ja)\b",
    r"\b(\d+\s+dedos)\b",
]


def classificar_janela(historico: list[BaseMessage]) -> tuple[str | None, str | None]:
    """Classifica a(s) ultima(s) mensagem(ns) do cliente na janela (10 §8).

    Retorna (categoria, confianca). categoria in {jailbreak_attempt, disclosure_attempt,
    prova_humanidade_attempt, None}; confianca in {'alta', None}. Ordem de checagem:
    jailbreak -> disclosure -> prova (jailbreak vence quando casa as duas familias).
    """
    t = normalizar(_texto_da_cauda_cliente(historico))
    if any(re.search(p, t) for p in PADROES_JAILBREAK):
        return "jailbreak_attempt", "alta"
    if any(re.search(p, t) for p in PADROES_DISCLOSURE):
        return "disclosure_attempt", "alta"
    if any(re.search(p, t) for p in PADROES_PROVA):
        return "prova_humanidade_attempt", "alta"
    return None, None


def _texto_da_cauda_cliente(historico: list[BaseMessage]) -> str:
    """Concatena as HumanMessages finais consecutivas da janela (10 §8).

    A unidade e a cauda do cliente no turno (1+ mensagens do burst do debounce), nao a janela
    inteira: para na primeira mensagem que nao for do cliente (AIMessage da IA/modelo). Sem
    HumanMessage no fim -> string vazia -> sem deteccao.
    """
    cauda: list[str] = []
    for msg in reversed(historico):
        if isinstance(msg, HumanMessage):
            cauda.append(str(msg.content))
        else:
            break
    cauda.reverse()
    return " ".join(cauda)
