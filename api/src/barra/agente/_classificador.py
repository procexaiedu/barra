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
"""

import re

from langchain_core.messages import BaseMessage, HumanMessage

# Identidade: generico (ia/bot/robo) E modelo nomeado (gpt/claude/gemini) -- MESMO balde,
# tratados igual (canned + contador, escala na 3a). Ver 10 §2.1.
PADROES_DISCLOSURE = [
    r"\b((você|vc|tu) )?é (uma? |um )?(ia|ai|bot|rob[ôo]|chatbot|gpt|chatgpt|claude|gemini|llama)\b",
    r"\b(é|to falando com|é mesmo) (uma? )?(pessoa|humana?|real|de verdade)\b",
]

# Jailbreak / override de instrucao: escala DIRETO (sem canned, sem contagem). Ver 10 §2.1, §4.4.
PADROES_JAILBREAK = [
    r"\bdan mode\b",
    r"\b(developer|dev) mode\b",
    r"ignore (previous|all|prior) instructions",
    r"\besquece tudo\b.*\bvoc[eê]\b",
    r"\[system\]",
    r"</persona>",
]

PADROES_PROVA = [
    r"\b(manda|envia|me manda) (um |uma )?(audio|foto|vídeo|video)\b.*(agora|já)\b",
    r"\b(\d+\s+dedos)\b",
]


def classificar_janela(historico: list[BaseMessage]) -> tuple[str | None, str | None]:
    """Classifica a(s) ultima(s) mensagem(ns) do cliente na janela (10 §8).

    Retorna (categoria, confianca). categoria in {jailbreak_attempt, disclosure_attempt,
    prova_humanidade_attempt, None}; confianca in {'alta', None}. Ordem de checagem:
    jailbreak -> disclosure -> prova (jailbreak vence quando casa as duas familias).
    """
    t = _texto_da_cauda_cliente(historico).lower()
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
