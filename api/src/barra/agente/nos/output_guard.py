"""No output_guard: ultima rede ANTES da bolha sair ao cliente (ADR 0016).

Roda no caminho normal de saida (depois do post_process). Recebe o texto final do turno e decide
se a bolha pode seguir:

- Estagio 0 (deterministico, transformacao): SANEIA raciocinio vazado/placeholder/tag de exemplo,
  mantendo a fala real.
- Gate pre-envio (deterministico + regen one-shot, producao assistida): scan de vazamento no TEXTO
  DE SAIDA -- auto-referencia de IA / nome de LLM, fragmento de system/persona, segredo da agenda
  (revelar estar com outro cliente) --, detector de REPETICAO (bolha quase identica a uma bolha
  recente da propria IA, rastro de papagaio) e SONDA-DE-BALCAO (o probe cru "o que voce procura?").
  Turno sujo -> REGENERA 1x (chamada direta ao chat, sem tools, com o rascunho descartado como
  feedback); persistiu -> fallback por gatilho: leak -> bloqueia (handoff); repeticao/sonda ->
  dropa as bolhas ofensoras (silencio > papagaio/SAC, sem handoff); turno 100%-raciocinio -> mudo.
  Leak em LEGENDA de midia nao e regeneravel (ja persistida como arg de tool) -> bloqueia direto. (O scan deterministico cross-modelo foi removido -- supersede
  ADR 0016: a IA roda por modelo e nunca tem em contexto o nome/numero de OUTRA modelo; isolamento
  garantido no carregamento; backstop semantico = judge.)
- Etapa 2 (LLM-judge de AUP, vinculante): quando o gate passa e o texto NAO e uma negacao canned
  (pool curado pula a Etapa 2). Roda tambem sobre o texto REGENERADO -- a regen nao pula o judge.
  Prompt em `prompts/aup_saida.md` (fora do prefixo cacheado por-modelo). Violou -> bloqueia.
  Falha de infra do judge -> DEFAULT SEGURO: bloqueia+escala (sem regen: judge inseguro nao e
  garble consertavel, e sinal de risco).

Bloquear = abrir handoff p/ Fernando (ia_pausada=true, mesma porta do disclosure/jailbreak) E
zerar a bolha (mesmo id -> reducer substitui por vazia, igual post_process). O coordenador rele
ia_pausada apos o turno (cinto-suspensorio) e nao despacha. Roteamento SO por Command(goto=END)
-- sem aresta estatica de saida (armadilha do fan-out, graph.py).
"""

import logging
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from difflib import SequenceMatcher
from os.path import commonprefix
from typing import Any, Literal

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.messages.ai import UsageMetadata
from langgraph.graph import END
from langgraph.runtime import Runtime
from langgraph.types import Command
from pydantic import BaseModel, Field

from barra.core.db import conexao
from barra.core.metrics import (
    AUP_SAIDA_BLOQUEADO,
    OUTPUT_ECO_REGIAO_DETECTADO,
    OUTPUT_ENDERECO_SONEGADO,
    OUTPUT_INCLUSO_FANTASMA,
    OUTPUT_LEAK_DETECTADO,
    OUTPUT_PEDAGIO_DETECTADO,
    OUTPUT_PRECO_FANTASMA,
    OUTPUT_RACIOCINIO_SANEADO,
    OUTPUT_REGEN,
    OUTPUT_REPETICAO_DETECTADA,
    OUTPUT_SAUDACAO_CONFLITANTE,
    OUTPUT_SERVICO_FANTASMA,
    OUTPUT_SONDA_DETECTADA,
)
from barra.dominio.atendimentos.service import PRECO_MINIMO_SCAN, extrair_precos_citados
from barra.settings import get_settings

from .._canned import ESPERA_ESCALADA_CANNED, NEGACOES_CANNED
from .._defesa import escalar_defesa
from .._disciplina import (
    contem_endereco_de_encontro,
    contem_pedido_de_endereco,
    periodo_da_saudacao,
    tokens_de_lugar,
    tokens_do_endereco,
)
from .._instrumentar import instrumentar_tokens, medir_llm
from .._normalizar import normalizar
from .._parceria import eh_bolha_de_contato_da_parceira
from .._texto_turno import (
    extrair_texto_do_turno,
    kwargs_preservados,
    mensagens_do_turno,
    texto_da_mensagem,
)
from ..contexto import ContextAgente
from ..estado import EstadoAgente
from ..persona import render_aup_saida
from ._foco_do_turno import aceite_curto_no_burst, perguntas_do_burst

# Pools curados isentos das defesas de texto gerado (repeticao/judge de AUP): o conteudo e nosso,
# nao do LLM. Negacoes de disclosure + bolha de espera da escalada de guarda (post_process) —
# zerar ou regenerar a espera recriaria o vacuo que ela existe para matar.
_CANNED_CURADAS = frozenset(NEGACOES_CANNED) | frozenset(ESPERA_ESCALADA_CANNED)

logger = logging.getLogger(__name__)

_RESUMO_LEAK = "Output-guard barrou a bolha (vazamento detectado antes do envio)."
_RESUMO_AUP = "Output-guard barrou a bolha (LLM-judge de AUP reprovou antes do envio)."


class _JudgeInseguro(RuntimeError):
    """Judge de AUP nao produziu veredito confiavel (refusal/truncado/parse) -> default seguro."""


# Etapa 1 -- auto-referencia de IA / nomes de LLM no TEXTO DE SAIDA (admissao, nao pergunta do
# cliente: o _classificador casa perguntas; aqui casamos a RESPOSTA vazando identidade).
_MARCADORES_IA = re.compile(
    r"\b(sou (uma? )?(ia|i\.a\.|intelig[êe]ncia artificial|bot|rob[ôo]|chatbot)"
    r"|modelo de linguagem|language model|sou (o|a|um|uma) (claude|gpt|chatgpt|gemini|llama)"
    r"|fui (treinad|program)|sou uma? (programa|software|assistente virtual)"
    r"|anthropic|openai|deepseek)\b",
    re.IGNORECASE,
)
# Etapa 1 -- fragmento de system/persona/regras vazando na saida.
_MARCADORES_SYSTEM = re.compile(
    r"(</?persona>|<desconto>|</?regras?>|</?faq>|\[system\]"
    r"|prompt do sistema|system prompt|minhas instru[çc][õo]es|instru[çc][õo]es acima)",
    re.IGNORECASE,
)
# Etapa 1 -- segredo da agenda: a IA recusa horario em bloqueio com DESCULPA PESSOAL (salao,
# jantar, balada) e NUNCA revela que esta com outro cliente / em outro atendimento (CONTEXT.md
# "Agenda — comportamento da IA"). Os scans acima nao pegam essa admissao; aqui casamos as
# n-gramas inequivocas do vazamento. Conservador de proposito (so frases que so podem significar
# "com outro cliente"): a assimetria favorece barrar -- falso-positivo vira handoff (seguro),
# enquanto o vazamento e irreversivel uma vez enviado.
_MARCADORES_OUTRO_CLIENTE = re.compile(
    r"\b("
    r"outr[oa]s? clientes?"
    r"|com (um|uma|outr[oa]|mais um[a]?) cliente"
    # "com outra pessoa" SOLTO nao e vazamento: no dominio e quase sempre a recusa do terceiro
    # que o cliente quer trazer ("nao faco assim com outra pessoa" -- <composicoes>). Solto, barrou a
    # recusa correta DUAS vezes e matou o lead #36 (24/07). Agora so casa a AFIRMACAO de estado
    # ("to ocupada com outra pessoa"): exige o "to/estou" antes e nenhum "nao" no meio, o que
    # deixa passar a recusa e continua barrando a admissao.
    r"|(t[ôo]|estou)(?:(?!\bn[ãa]o\b)[^.!?\n]){0,15}com (outr[oa]|mais um[a]?) pessoa"
    r"|(t[ôo]|estou|tenho|t[ôo] com|estou com) (um |uma |o |a |outr[oa] )?cliente"
    # "estou atendendo agora" -- atende ALGUEM. O lookahead protege "te/voce atendendo" (o
    # PROPRIO cliente, fala legitima): so vaza quando o objeto NAO e o interlocutor.
    r"|(t[ôo]|estou) atendendo(?!\s+(voc|vc|te\b|o senhor|a senhora))"
    r"|(em|num|no|noutro|outro|nesse|neste) atendimento"
    r"|no meio de (um |outro )?atendimento"
    r"|atendendo (outr[oa]|um|uma|mais um|algu[ée]m|outr[oa] pessoa|cliente)"
    r")\b",
    re.IGNORECASE,
)


# Vazamento de RACIOCINIO: o chat #1 (thinking disabled, temp 1.3) as vezes derrama a cadeia de
# raciocinio no canal `content` em vez de conversar -- meta-fala que entrega a IA. Marcas (handoff
# 2026-06-26): planejamento em 1a pessoa ("meu proximo passo"), 3a pessoa sobre o cliente ("o
# cliente demonstrou"), vocab de maquina de estado ("em triagem", "avancou"), lista de analise ("a
# situacao mostra: -"). Conservador no que casa -- na duvida o judge (Etapa 2) e a rede fail-closed.
# Ampliado (shadow 300, 2026-06-30): narracao meta em 3a pessoa reportando a fala do cliente ("Ele
# perguntou 'X'", "o cliente acabou de responder com 'Y'") e meta do proprio processamento ("vou
# continuar respondendo", "acabou de chegar no meio do texto") escapavam do Estagio 0. Padroes
# testados contra 250 respostas validas (zero falso-positivo) + falas legitimas de 3o ("ele vai te
# receber", "ela e minha amiga", "vou te responder rapidinho") que continuam NAO casando.
_MARCADORES_RACIOCINIO = re.compile(
    r"\b("
    r"meu pr[óo]ximo passo|minha (resposta|interven[çc][ãa]o|fala) (suavizou|sobre)"
    r"|o cliente (demonstrou|quer saber|menciona|pediu|respondeu|acabou de)|claro interesse dele"
    # adverbio opcional entre o pronome e o verbo: "ele JA falou" escapava (o regex exigia
    # adjacencia). "ele vai te receber"/"ela e minha amiga" seguem NAO casando (verbo fora da lista).
    r"|(ele|ela) (?:j[áa] |ainda |mesmo |s[óo] |tamb[ée]m )?(perguntou|respondeu|disse|falou|mencionou|comentou)"
    # jargao de TIPO narrado ao cliente (rotulo interno de dominio): "que e interno", "externo entao".
    # Bolha real ao cliente nunca classifica o atendimento por esses rotulos (handoff 2026-07-01).
    r"|que [ée] (interno|externo|remoto)|(interno|externo|remoto) ent[ãa]o"
    r"|vou continuar respondendo|acabou de chegar no meio|vou responder (normal|o valor|agora)"
    r"|em triagem|triagem avan[çc]ou|a (situa[çc][ãa]o|conversa) (mostra|fluiu)"
    # fragmento de scratchpad: planejamento em voz alta / auto-correcao quebrada. Combos unicos
    # (nao "faz sentido" solto, que e fala legitima): "faz sentido na sequencia", a run-on
    # "entao.opa devagar", "preparado, entao".
    r"|faz sentido na sequ[êe]ncia|ent[ãa]o\.?\s*opa|preparado,? ent[ãa]o"
    # meta de espera pos-cotacao vazada (rodada de eval 2026-07-03): "Agora e esperar ele reagir
    # ao valor" saiu como bolha ao cliente. Conservador: exige o combo esperar+reagir ou a forma
    # "agora e (so) esperar"; "vou te esperar"/"te espero" (fala legitima) NAO casam.
    r"|esperar (ele|ela) reagir|agora [ée] (s[óo] )?esperar"
    # acatamento de ERRO DE TOOL em voz alta (prod 29/07, conversa 019f8d10): a extracao devolveu
    # "voce nao disse o preco ainda, cote primeiro" e o chat respondeu ao aviso como bolha ao
    # cliente ("Ainda nao combinei o valor com ele. Vou cotar agora."). Duas marcas estreitas: o
    # jargao do processo ("cotar", que ela nunca diz ao cliente -- ao cliente e "te passar o
    # valor") e o ato de venda referido em 3a pessoa. "combinei com ela" da amiga do menage (sem
    # objeto de venda) e "vou te passar o valor" seguem NAO casando.
    r"|vou cotar|(combinei|cotei|acertei|fechei) o (valor|pre[çc]o|programa)[^.!?]{0,20} com (ele|ela)"
    r")\b",
    re.IGNORECASE,
)


def tem_marcador_raciocinio(texto: str) -> bool:
    """True se o texto e meta-fala/raciocinio vazado (planejamento, 3a pessoa sobre o cliente,
    vocab de maquina de estado, lista de analise) em vez de fala client-facing (PURO)."""
    return bool(_MARCADORES_RACIOCINIO.search(texto))


# Placeholder de template nao preenchido: o chat as vezes cospe a chave literal do exemplo do prompt
# ("{valor} 1h no meu local") em vez de interpolar o dado real. Uma bolha com `{token}` nunca e fala
# valida ao cliente -- e entrega a IA na cara. FONTE UNICA do padrao: a rede final do envio importa
# daqui (`_saida_guard.tem_placeholder_eco`). Casa as TRES formas observadas -- a chave {palavra} dos
# exemplos (com acento: `{horário}`), o colchete instrucional inventado ([insira a rua]) e a RUBRICA
# entre parenteses ("(aqui vão as fotos e o vídeo)"). NAO casa o marker [quote]/[quote: trecho]
# ('quote' fora dos gatilhos do colchete).
#
# A rubrica em PARENTESES entrou em 12/08 (loop-massa r3, achado 5): a regen roda sem tools, nao ve
# as ToolMessages do turno e preenche o lugar do anexo com teatro. `(aqui vao as fotos e o video)`
# passava por TODOS os estagios -- inclusive o re-scan da 2a volta -- e entrava na janela historica
# como fala dela, disponivel para imitacao nos turnos seguintes.
# O gatilho tem de vir NO COMECO do parenteses e ser VERBO de rubrica: parenteses e pontuacao comum
# na fala dela ("600 1h (valor fechado)"), entao casar o miolo generico barraria bolha legitima.
_RE_PLACEHOLDER = re.compile(
    r"\{[a-zà-ÿ_]{2,20}\}"  # {valor}, {horario}, {horário}, {nome}, {duracao}, ...
    r"|\[\s*(?:insira|inserir|coloque|preench\w*|adicione|informe|seu|sua|valor|"
    r"hor[áa]rio|endere\w*|rua|bairro)\b[^\]]*\]"  # [insira a rua], [seu endereço], ...
    r"|\(\s*(?:insira|inserir|coloque|preench\w*|adicione|informe|"
    r"aqui\s+(?:vai|v[ãa]o|est[áa]|est[ãa]o)|segue\w*|enviando|mandando|anexo|anexad\w*)"
    r"\b[^)]*\)",  # (aqui vão as fotos e o vídeo), (segue o book), (enviando as fotos)
    re.IGNORECASE,
)


def tem_placeholder_template(texto: str) -> bool:
    """True se a bolha contem um placeholder de template nao preenchido (ex.: `{valor}`, `{horario}`)."""
    return bool(_RE_PLACEHOLDER.search(texto))


# Sonda-de-balcao (tell de atendente de SAC): na ABERTURA, depois do cumprimento, o chat as vezes
# solta um probe aberto "o que voce procura?" -- exatamente o lado <errado> do par de `persona.md`
# e proibido em `regras.md.j2` (<abertura> nunca pergunta o que ele quer; <cotacao> nao cola sonda
# no preco). A modelo conduz com ancora concreta ("Seria hoje?", "Esta em Campinas?"), nunca com o
# balcao. ESTREITO de proposito: so o probe CRU. A forma CALOROSA ("me conta o que voce procura?",
# com self-intro/convite) e voz legitima (fixtures reais) e NAO casa -- o `_RE_CONVITE_CALOROSO`
# resgata a bolha. "me chamou" (voce me chamou) nao e convite e segue caindo no drop.
#
# A oferta de atendimento ("Como posso te atender ?", "Posso te ajudar ?") entra como membro da
# classe alvo: `persona.md` a lista NOMINALMENTE entre as falas proibidas ("em que posso ajudar",
# "posso te ajudar?"), e ela foi ao cliente no turno de ABERTURA — o que decide se ele fica
# (loop-massa r2, eixo ghost_pos_cotacao). Os dois ramos ficam ESTREITOS pelo mesmo motivo dos
# vizinhos: o interrogativo com "como/em que" na frente, e a forma nua SÓ colada no "?" -- assim
# "posso te ajudar com o horario?" (oferta dentro de fala quente, com objeto) segue passando, e a
# fixture calorosa "me fala o que voce busca que eu te ajudo" nem chega a este ramo.
_RE_SONDA_BALCAO = re.compile(
    r"o que (voc[êe]|vc) (procura|busca|est[áa] (procurando|buscando)|deseja saber|gostaria de saber)"
    r"|o que gostaria de saber"
    r"|o que te traz (aqui|aq)\b"
    r"|pode perguntar (o que quiser|[àa] vontade)"
    r"|gosta de que tipo de (programa|servi[çc]o|atendimento)"
    r"|\b(como|o que|em que|no que|em q) (eu )?posso (te |lhe )?(atender|ajudar)"
    r"|\bposso (te |lhe )?(atender|ajudar)\s*\?",
    re.IGNORECASE,
)
_RE_CONVITE_CALOROSO = re.compile(r"\bme (conta|fala|diz|chamo)\b|\bmeu nome\b", re.IGNORECASE)


def tem_sonda_balcao(texto: str) -> bool:
    """True se a bolha e o probe CRU de balcao ("o que voce procura?" e as parafrases documentadas)
    SEM o convite caloroso/self-intro que o torna fala legitima. Proibido na abertura/cotacao; a
    forma calorosa ("me conta o que voce procura?") NAO casa e segue intacta."""
    return bool(_RE_SONDA_BALCAO.search(texto)) and not _RE_CONVITE_CALOROSO.search(texto)


def bolhas_sonda(texto: str) -> list[str]:
    """Bolhas do turno que sao sonda-de-balcao crua (PURA; devolve as originais p/ o drop).

    Vive no GATE, nao no Estagio 0: o drop mudo deixava o turno sem a pergunta que o modelo quis
    fazer e a conversa parava (lead RNine, 22/07 -- "Tudo bem sim amor" sozinho, com a 2a bolha
    comida). Como gatilho de regen, o chat reescreve o turno com a ancora concreta que a persona
    manda usar; o drop de hoje vira so o fallback de quando a regen falha ou reincide."""
    return [b for b in texto.split("\n\n") if tem_sonda_balcao(b)]


# Promessa aberta "sem limite" (feedback Fernando, reuniao 22/07): quantidade de finalizacoes nao
# se promete — "sem limite" deixa o servico aberto demais e nunca e fala valida da modelo. A prosa
# em <girias_do_cliente> proibe, mas o chat re-emitiu a frase 2x no replay (white-bear); trilho
# deterministico, mesmo padrao da sonda-de-balcao. So fala da IA passa por aqui — mensagem do
# cliente nao e afetada.
_RE_PROMESSA_SEM_LIMITE = re.compile(r"\bsem limites?\b", re.IGNORECASE)


def tem_promessa_sem_limite(texto: str) -> bool:
    """True se a bolha promete quantidade aberta ("sem limite") — drop da bolha inteira."""
    return bool(_RE_PROMESSA_SEM_LIMITE.search(texto))


# Chave Pix inventada: "a chave certa e so a que o sistema anexa" (regras.md.j2 <nucleo> e
# <tipos_de_encontro>) nao tinha rede mecanica — a proibicao era so prompt (auditoria editorial
# 2026-07-23). Bolha da IA contendo o SHAPE de uma chave (e-mail, EVP/UUID, CPF formatado ou
# 11+ digitos corridos) nunca e fala valida: chave digitada pelo modelo e inventada por definicao
# (a real chega por side-effect do dominio, fora da bolha). Conservador de proposito — precos
# (3-4 digitos), horas ("20:30") e numero de rua nao casam; telefone formatado com espacos escapa
# (aceito: falso-negativo fica pro prompt, falso-positivo derrubaria fala legitima).
_RE_CHAVE_PIX = re.compile(
    r"[\w.+\-]+@[\w\-]+\.[\w.\-]{2,}"  # e-mail
    r"|\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"  # chave aleatoria (EVP)
    r"|(?<![\d.])\d{3}\.\d{3}\.\d{3}-\d{2}(?![\d.])"  # CPF formatado
    r"|(?<!\d)\d{11,14}(?!\d)",  # CPF/telefone cru (11-14 digitos corridos)
    re.IGNORECASE,
)


def tem_chave_pix(texto: str) -> bool:
    """True se a bolha contem o shape de uma chave Pix (e-mail, EVP, CPF, telefone cru) — a IA
    nunca digita chave (a certa e anexada pelo sistema); drop da bolha inteira."""
    return bool(_RE_CHAVE_PIX.search(texto))


# Eco de REGIAO: o cliente chuta um bairro e a IA confirma como se fosse o dela. `regras.md.j2`
# (<tipos_de_encontro>) proibe literalmente -- "a regiao que sai da sua boca e EXATAMENTE a do seu
# <dados_da_modelo>, palavra por palavra: voce NUNCA a troca por um bairro vizinho, pelo 'centro'
# generico nem pelo bairro do ponto que ELE citou" -- e mesmo assim, atendimento #41 (24/07 08:10):
# cliente "atendimento centro", IA "Isso amor, aqui no centro", com o cadastro dizendo Cambui. A
# proibicao era so prosa; este e o trilho.
#
# ESTREITO de proposito (mesma disciplina do `_RE_CHAVE_PIX`): so casa a forma de CONFIRMAR/situar
# um lugar -- um abridor de confirmacao/locativo (isso/aqui/fico/moro/atendo/...) perto de um
# "no/na/do/da" seguido de nome PROPRIO (maiuscula) ou do "centro" generico. "Vou te mandar no Pix"
# nao tem abridor; "to no hotel na rua Santos Dumont" so tem substantivo comum minusculo. O que
# escapar fica pro prompt: falso-positivo aqui derrubaria fala legitima.
#
# SEM `re.IGNORECASE`, e nao por descuido: a flag valeria tambem para a classe `[A-Z...]` da captura
# e ANULARIA o teste de maiuscula que separa nome proprio de substantivo comum. Medido contra as 525
# falas reais da IA em prod: com IGNORECASE, "mas sou eu mesma nas fotos", "no completo" e "no
# periodo combinado" viravam ofensa. O abridor leva o `(?i:...)` inline, que e do que ele precisa.
_RE_ECO_REGIAO = re.compile(
    r"\b(?i:isso|aqui|fico|ficar|estou|est[oó]|t[ôo]|fica|sou|moro|atendo|atender)\b"
    r"[\w\s,'-]{0,14}?"
    r"\b(?i:n[oa]s?|d[oa]s?|em)\s+"
    r"((?i:centr[oã]o?)|[A-ZÁÀÂÃÉÊÍÓÔÕÚÜÇ][\wÀ-ÿ]+(?:\s+[A-ZÁÀÂÃÉÊÍÓÔÕÚÜÇ][\wÀ-ÿ]+)?)",
    re.UNICODE,
)

# Nome PROPRIO que nao e lugar: a captura acima pega qualquer maiuscula depois do locativo, e estes
# aparecem na fala legitima dela ("fico no WhatsApp", "atendo no Hotel"). Comparados ja normalizados.
_TERMOS_NAO_LUGAR = frozenset(
    {
        "hotel",
        "rua",
        "avenida",
        "av",
        "apto",
        "apartamento",
        "quarto",
        "casa",
        "local",
        "predio",
        "endereco",
        "bairro",
        "regiao",
        "pix",
        "whatsapp",
        "zap",
        "uber",
        "carro",
        "video",
        "chamada",
    }
)


def bolhas_eco_regiao(texto: str, permitidos: set[str]) -> list[str]:
    """Bolhas do turno que situam a modelo num lugar FORA do cadastro dela (PURA; devolve as
    originais p/ o drop).

    `permitidos` = tokens normalizados do que ela pode dizer (regiao operacional, nome do local e
    endereco). Vazio -> nada a comparar, nenhuma bolha casa: sem cadastro nao ha "fora do cadastro",
    e inventar um veredito aqui derrubaria fala legitima de modelo com ficha incompleta.
    """
    if not permitidos:
        return []
    ofensoras: list[str] = []
    for bolha in texto.split("\n\n"):
        for bruto in _RE_ECO_REGIAO.findall(bolha):
            tokens = set(normalizar(bruto).split())
            if tokens & _TERMOS_NAO_LUGAR or _cobre_o_cadastro(tokens, permitidos):
                continue
            ofensoras.append(bolha)
            break
    return ofensoras


def _cobre_o_cadastro(tokens: set[str], permitidos: set[str]) -> bool:
    """True se algum token capturado e o lugar do cadastro — por PREFIXO, nao por igualdade.

    O prefixo cobre o apelido/diminutivo que ela usa de verdade na conversa: "To no Cambuizinho"
    (fala real de prod) e o Cambui do cadastro, nao um bairro inventado."""
    return any(t.startswith(p) or p.startswith(t) for t in tokens for p in permitidos)


# Incluso FANTASMA: a IA declara incluso um item que NAO esta na linha "Inclusos" do <fetiches> da
# modelo. `regras.md.j2` proibe em DOIS sites (<fora_do_cardapio> e o preambulo de
# <exemplos>) -- "'ta incluso' voce so diz de item que esta NOMINALMENTE na linha 'Inclusos' do seu
# <fetiches> ... nem quando ele aparece num exemplo desta conduta" -- e a prosa perdeu para o
# exemplo concreto: corrida do conduta_gate 30/07, modelo com "(sem fetiches cadastrados)", a IA
# emitiu "Beijo na boca e oral sem camisinha ja vem junto 🥰", copia do <exemplo> de apresentacao.
# A proibicao era so prosa; este e o trilho (mesma familia de `sonda`/`regiao`).
#
# ESTREITO de proposito, em quatro camadas, porque falso-positivo aqui derruba fala boa:
#  1. so as formas de DECLARAR incluso ("ta incluso", "ja vem junto"); o verbo "inclui" fica de fora
#     -- ele e a fala legitima do programa ("o normal ja inclui a penetracao", <girias_do_cliente>);
#  2. claim NEGADO nao conta ("beijo na boca nao ta incluso" e recusa correta);
#  3. bolha que fala de PROGRAMA/valor/logistica (`_TERMOS_NAO_FETICHE`) nao e claim de fetiche --
#     "Tudo isso ta incluso no completo" e "O completo tem anal incluso amor" sao falas reais e
#     prescritas, e o incluso do programa nao sai do <fetiches>;
#  4. claim que nao NOMEIA nada (`_SEM_ITEM`: "Ja vem junto sim amor", resposta curta a uma pergunta
#     do turno anterior) nao da p/ julgar -- sem item nomeado nao ha "fora da linha", e barrar ali
#     mataria a bolha curta que e a voz dela.
_RE_DECLARA_INCLUSO = re.compile(r"\b(inclus[oa]s?|incluid[oa]s?|(ja )?(vem|vao) junto)\b")
_RE_NEGACAO_INCLUSO = re.compile(r"\b(nao|nem)\b")
_JANELA_NEGACAO = 25  # chars antes do claim onde um "nao" o transforma em recusa (fala legitima)
_RE_TOKENS_ITEM = re.compile(r"[^\w]+")

# Palavra que faz o "incluso" ser do PROGRAMA (ou da logistica), nao de um item do <fetiches>:
# o que o pacote de encontro traz -- penetracao no Normal, anal no Completo (<girias_do_cliente>) --
# nunca dependeu da linha "Inclusos". Comparadas ja normalizadas.
_TERMOS_NAO_FETICHE = frozenset(
    {
        "programa",
        "programas",
        "pacote",
        "completo",
        "normal",
        "encontro",
        "anal",
        "penetracao",
        "sexo",
        "valor",
        "preco",
        "hora",
        "horas",
        "periodo",
        "pernoite",
        "deslocamento",
        "uber",
        "taxa",
        "hotel",
        "local",
        "quarto",
    }
)
# Token que NUNCA absolve, mesmo vindo do nome de um incluso dela. Ligacao ("sem" de "oral sem
# camisinha" salvaria "carinho sem pressa") e a CAMISINHA: ela nunca e item incluso (<fora_do_
# cardapio>: "nunca sai como 'incluso'"), e deixa-la no vocabulario faria "camisinha ta incluso"
# passar em toda modelo que tem "oral sem camisinha" na linha.
_FORA_DO_VOCABULARIO = frozenset(
    {"com", "sem", "por", "para", "pra", "dos", "das", "nos", "nas", "uma", "camisinha"}
)
# Palavra que aparece no claim mas nao NOMEIA item: pronome, o proprio verbo do claim e o vocativo.
# Bolha so com isto ("Ja vem junto sim amor") responde a pergunta do turno anterior e nao da p/
# julgar sem o item — barra-la mataria a bolha curta que e a voz dela.
_SEM_ITEM = frozenset(
    {
        "isso",
        "isto",
        "esse",
        "essa",
        "este",
        "esta",
        "tudo",
        "junto",
        "juntos",
        "vem",
        "vao",
        "incluso",
        "inclusa",
        "inclusos",
        "inclusas",
        "incluido",
        "incluida",
        "incluidos",
        "incluidas",
        "amor",
        "aqui",
        "voce",
        "minha",
        "meus",
        "minhas",
        "tambem",
        "claro",
        "mesmo",
        "sempre",
        "ainda",
        "muito",
        "muita",
    }
)


def tokens_de_incluso(*nomes: str | None) -> set[str]:
    """Vocabulario normalizado dos fetiches INCLUSOS da modelo (a linha "Inclusos" do <fetiches>).

    Descarta token de ate 2 letras e o que nunca absolve (`_FORA_DO_VOCABULARIO`).
    """
    tokens: set[str] = set()
    for nome in nomes:
        if nome:
            tokens |= {t for t in _RE_TOKENS_ITEM.split(normalizar(nome)) if len(t) > 2}
    return tokens - _FORA_DO_VOCABULARIO


def _declara_incluso(normalizada: str) -> bool:
    """True se a bolha AFIRMA que algo esta incluso (claim negado -- "nao ta incluso" -- nao conta)."""
    for m in _RE_DECLARA_INCLUSO.finditer(normalizada):
        antes = normalizada[max(0, m.start() - _JANELA_NEGACAO) : m.start()]
        if _RE_NEGACAO_INCLUSO.search(antes):
            continue
        return True
    return False


def bolhas_incluso_fantasma(texto: str, inclusos: set[str]) -> list[str]:
    """Bolhas do turno que declaram incluso um item FORA da linha "Inclusos" do <fetiches> (PURA;
    devolve as originais p/ o drop).

    `inclusos` = tokens normalizados dos nomes que a modelo tem como incluso. Ao contrario do eco de
    regiao, o conjunto VAZIO nao desliga o detector -- e o caso medido: sem linha "Inclusos" no
    bloco, NENHUM item pode ser declarado incluso (`<sem_fetiches>` na cauda, quando o <fetiches>
    inteiro esta vazio; aqui o detector cobre tambem o cardapio so de extras PAGOS, que tem lista
    mas nao tem linha "Inclusos" e por isso nao recebe a tag). A bolha e absolvida por UM token que
    seja da linha dela (generoso de proposito: "oral sem" abrevia "oral sem camisinha"), por falar
    de programa/valor/logistica (`_TERMOS_NAO_FETICHE`) ou por nao nomear item nenhum (`_SEM_ITEM`).
    """
    ofensoras: list[str] = []
    for bolha in texto.split("\n\n"):
        n = normalizar(bolha)
        if not _declara_incluso(n):
            continue
        tokens = set(_RE_TOKENS_ITEM.split(n))
        if tokens & _TERMOS_NAO_FETICHE or tokens & inclusos:
            continue
        if not {t for t in tokens if len(t) > 3 and t not in _SEM_ITEM}:
            continue
        ofensoras.append(bolha)
    return ofensoras


# Preço FANTASMA: o valor citado na bolha não existe no conjunto fechado de valores legítimos da
# modelo (tabela + totais-com-extra + degraus da escada de desconto + valor já na mesa +
# eco de número que o CLIENTE citou). Rodada 3 do eval (fase 1-E): o LLM copia/escolhe o número da
# tabela e nada validava a bolha — preço inventado, acima da tabela ou diferente do já cotado
# passava direto (o único check era o piso, via extração, DEPOIS do envio). "NUNCA preço inventado"
# era só prosa+caps; este é o trilho (família da sonda/região/incluso: regenera 1x, dropa a bolha).
#
# ESTREITO de proposito — falso-positivo derruba cotação boa. Só conta como "preço citado" o número
# em CONTEXTO monetário; o scanner (`extrair_precos_citados`) mudou de casa e hoje mora no DOMÍNIO
# (dominio/atendimentos/service.py), importado no topo deste módulo: o mesmo scanner que julga a
# BOLHA na saída julga, na extração, se o `valor_acordado` já saiu da boca da IA (guarda do valor
# fantasma). Duas cópias do regex divergiriam e uma legitimaria o que a outra derruba.


def bolhas_preco_fantasma(texto: str, validos: set[int]) -> list[str]:
    """Bolhas do turno que citam preço FORA do conjunto legítimo (PURA; devolve as originais p/
    o drop).

    `validos` = tabela + totais-com-extra pré-computados + degraus do desconto + valor na mesa +
    números que o cliente citou (eco/recusa do número DELE é fala legítima). Vazio (modelo sem
    programa cadastrado) -> detector desligado, como no eco de região: sem tabela não há "fora
    da tabela"."""
    if not validos:
        return []
    return [
        b for b in texto.split("\n\n") if any(v not in validos for v in extrair_precos_citados(b))
    ]


# Serviço FANTASMA ("Faço sim amor" para anal fora do cadastro): a derrota mais grave do shadow v2
# (recusa_limite 40%) — o cadastro não tem campo "não faço X" e, na dúvida, o LLM AFIRMAVA fazer.
# `bolhas_incluso_fantasma` pega quem DECLARA incluso; este pega quem AFIRMA FAZER um serviço de
# risco que não está no cardápio (fetiches + programas). Closed-world: o que não está no cadastro
# a modelo NÃO faz.
#
# ESTREITO em três camadas (falso-positivo derruba recusa/fala boa):
#  1. só AFIRMAÇÕES ("faço sim", "pode sim", "consigo", "rola", "topo") — a recusa ("não faço")
#     tem negação ANTES e não casa; o eco-negação ("faço anal não") tem negação DEPOIS e não casa
#     (mesma lição do ven_004: regex cego a negação pune a resposta certa);
#  2. só serviços da LISTA DE RISCO (anal, grego, natural, chuva dourada, fisting…) — o vocabulário
#     onde prometer errado é dano real. "Pode sim" para "posso te beijar?" não tem token de risco
#     e passa (beijo é conduta aberta, não cardápio);
#  3. absolvição pelo CADASTRO: token de risco coberto pelo vocabulário da modelo (nome de fetiche,
#     nome de programa — "Completo" cobre anal/grego pela conduta do <girias_do_cliente>; "oral sem
#     camisinha" nos inclusos cobre "natural") não dispara.
_RE_AFIRMA_FAZER = re.compile(
    r"\b(?:fa[cç]o|pode|podemos|consigo|rola|topo|aceito|tem)\s+(?:sim\b|tudo\b)?"
)
_RE_NEGACAO_PERTO = re.compile(r"\b(?:nao|nunca|nem)\b")
_JANELA_NEGACAO_SERVICO = 30  # chars antes/depois onde a negação transforma o claim em recusa
_SERVICOS_DE_RISCO = frozenset(
    {"anal", "grego", "natural", "fisting", "dourada", "inversao", "dominacao"}
)


def vocabulario_de_servicos(
    nomes_fetiches: Iterable[str], nomes_programas: Iterable[str]
) -> set[str]:
    """Vocabulário normalizado do que a modelo FAZ (nomes de fetiche + de programa), com as
    expansões de conduta do domínio: programa "Completo" cobre anal/grego (<girias_do_cliente>:
    o anal mora no Completo) e "oral sem camisinha" cobre o apelido "natural"."""
    tokens: set[str] = set()
    for nome in (*nomes_fetiches, *nomes_programas):
        if nome:
            tokens |= {t for t in _RE_TOKENS_ITEM.split(normalizar(nome)) if len(t) > 2}
    if "completo" in tokens:
        tokens |= {"anal", "grego"}
    if "natural" in tokens or {"oral", "camisinha"} <= tokens:
        tokens.add("natural")
    return tokens


_RE_TOKEN_DE_RISCO = re.compile(r"\b(?:" + "|".join(sorted(_SERVICOS_DE_RISCO)) + r")\b")
_JANELA_AFIRMACAO = 40  # chars em volta do token de risco onde a afirmação conta como promessa


def bolhas_servico_fantasma(texto: str, vocabulario: set[str]) -> list[str]:
    """Bolhas do turno que AFIRMAM fazer um serviço de risco fora do cadastro (PURA; devolve as
    originais p/ o drop).

    A afirmação precisa estar na VIZINHANÇA do token de risco ("faço anal sim", "anal? pode sim")
    — verbo longe do token não conta ("Pode chegar 20h" + "anal" em outra frase da bolha não é
    promessa). Negação perto do token, de qualquer lado, absolve ("não faço anal", "faço anal
    não" — eco-negação, lição do ven_004). Ao contrário do preço, o vocabulário VAZIO não desliga
    o detector — é o caso medido: modelo sem o fetiche cadastrado é exatamente quem não faz, e
    "Faço sim" ali é a promessa errada."""
    ofensoras: list[str] = []
    for bolha in texto.split("\n\n"):
        n = normalizar(bolha)
        for m in _RE_TOKEN_DE_RISCO.finditer(n):
            if m.group(0) in vocabulario:
                continue
            perto = n[
                max(0, m.start() - _JANELA_NEGACAO_SERVICO) : m.end() + _JANELA_NEGACAO_SERVICO
            ]
            if _RE_NEGACAO_PERTO.search(perto):
                continue
            antes = n[max(0, m.start() - _JANELA_AFIRMACAO) : m.start()]
            depois = n[m.end() : m.end() + _JANELA_AFIRMACAO]
            if _RE_AFIRMA_FAZER.search(antes) or _RE_AFIRMA_FAZER.search(depois):
                ofensoras.append(bolha)
                break
    return ofensoras


# Afirmação NUA em cima de pedido de risco (rodada 6b): o cliente pergunta "faz anal?" e a
# resposta é "Pode sim amor" — sem nomear o serviço, `bolhas_servico_fantasma` não enxerga (ele
# varre tokens de risco NA RESPOSTA). Aqui o token de risco vem do BURST do cliente: pedido de
# risco fora do cadastro + bolha curta de pura afirmação (sem negação, sem nomear serviço coberto)
# = a mesma promessa fantasma, dita por "sim". Estreito: só afirmações inequívocas ("pode sim",
# "faço sim", "claro", "sim" abrindo bolha curta) — mistura legítima ("Pode ser 22h") não casa;
# bolha que NOMEIA um token de risco fica com o detector-irmão (que absolve pelo cadastro).
_RE_AFIRMACAO_NUA = re.compile(
    r"\b(?:faco|fazemos|pode|podemos|consigo|rola|topo|aceito|tem)\s+(?:sim|tudo)\b"
    r"|\bclaro\b|\bcom\s+certeza\b|\badoro\b"
)
_RE_SIM_ABRINDO = re.compile(r"^\s*sim\b")
_MAX_BOLHA_AFIRMACAO_NUA = 45


def bolhas_afirmacao_nua_de_risco(
    burst_cliente: Sequence[str], texto: str, vocabulario: set[str]
) -> list[str]:
    """Bolhas curtas de pura afirmação respondendo a um pedido de risco fora do cadastro (PURA)."""
    armados = {
        m.group(0) for fala in burst_cliente for m in _RE_TOKEN_DE_RISCO.finditer(normalizar(fala))
    } - vocabulario
    if not armados:
        return []
    ofensoras: list[str] = []
    for bolha in texto.split("\n\n"):
        n = normalizar(bolha).strip()
        if not n or len(n) > _MAX_BOLHA_AFIRMACAO_NUA:
            continue
        if _RE_TOKEN_DE_RISCO.search(n) or _RE_NEGACAO_PERTO.search(n):
            continue
        if _RE_AFIRMACAO_NUA.search(n) or (_RE_SIM_ABRINDO.search(n) and len(n) <= 25):
            ofensoras.append(bolha)
    return ofensoras


# PEDÁGIO (rodada 4 do eval): o "Seria hoje ?" virou muleta universal — resposta cuja ÚNICA
# substância é empurrão VAZIO, inclusive em cima de pergunta concreta do cliente (~13 derrotas da
# taxonomia; efeito colateral do exemplo do <desconto> da rodada 2 generalizando demais). O
# empurrão acompanha o conteúdo do turno, nunca o substitui (site canônico: <cotacao>). O gatilho
# só ARMA com pergunta do cliente pendente no burst — despedida/emoji dele sem pergunta não arma
# (o empurrão-só ali pode ser a jogada, e a despedida tem prosa própria).
#
# "Substância" é definida pelo complemento, fechado dos dois lados: bolha que casa a família do
# empurrão vazio ("seria hoje/agora/que horas", "vamos marcar") ou o filler curto de interjeição
# ("poxa amor", "oii", emoji) NÃO é substância; qualquer outra coisa é — em particular proposta
# com horário concreto ("Consigo às 22h ?") tem dígito e é resposta legítima à pergunta de hora,
# e recusa ("não faço amor") tem negação. Rede de MELHORIA (família do endereço): regenera 1x;
# persistiu -> pass-through.
_RE_EMPURRAO_VAZIO = re.compile(
    r"(?:poxa |poxa amor |amor )?"
    r"(?:seria (?:hoje|agora|que horas|quando)|que horas (?:seria|pode|prefere)|"
    r"quando (?:seria|pode)|(?:vamos|bora|podemos|quer) marcar)"
    r"(?: amor| vida| gata| entao)?"
)
_FILLER_SEM_SUBSTANCIA = frozenset(
    {
        "poxa",
        "poxa amor",
        "poxa vida",
        "oi",
        "oii",
        "oie",
        "amor",
        "rs",
        "haha",
        "hahaha",
        "kk",
        "kkk",
        "que bom",
        "que otimo",
        "entendi",
        "ata",
        "hmm",
        "tudo bem",
    }
)


def _normalizar_pedagio(bolha: str) -> str:
    return " ".join(_RE_NAO_PALAVRA.sub(" ", normalizar(bolha)).split())


def resposta_so_pedagio(texto: str) -> bool:
    """True se TODA bolha do turno é empurrão vazio ou filler — e há ao menos um empurrão (PURA).

    Uma única bolha de substância absolve o turno inteiro: o empurrão acompanhando conteúdo é a
    jogada certa, o alvo é só o empurrão SOZINHO."""
    bolhas = [b for b in texto.split("\n\n") if b.strip()]
    if not bolhas:
        return False
    tem_empurrao = False
    for b in bolhas:
        n = _normalizar_pedagio(b)
        if not n:  # só emoji/pontuação
            continue
        if _RE_EMPURRAO_VAZIO.fullmatch(n):
            tem_empurrao = True
            continue
        if n in _FILLER_SEM_SUBSTANCIA:
            continue
        return False
    return tem_empurrao


def saudacao_em_conflito(texto: str, saudacao_cliente: str | None) -> bool:
    """True se a resposta saúda com período DIFERENTE do que o cliente usou no burst (PURA).

    Rodada 4 (~5 derrotas): "Boa noite" em cima do "boa tarde" dele. Sem saudação do cliente ou
    sem saudação na resposta, nada dispara — "boa noite" legítimo à noite só é julgado quando ELE
    deu a referência do período."""
    if not saudacao_cliente:
        return False
    periodo_resposta = periodo_da_saudacao(texto)
    return periodo_resposta is not None and periodo_resposta != saudacao_cliente


# Delimitador de EXEMPLO vazando na bolha: os few-shots de `regras.md.j2`/`persona.md` moldam a fala
# ideal com tags de papel (`<ela>...</ela>`, `<ele>...</ele>`, `<exemplo>`) e os pares de
# contraste (`<certo>/<errado>/<par>/<porque>`). Sob decodificacao estocastica (temp 0.7) o chat as
# vezes COPIA o delimitador de fechamento colado a uma fala boa ("tudo bem, e voce?</ela>"). Ao
# contrario de raciocinio/placeholder (bolha inteira descartavel) e das tags de SECAO pesadas de
# `_MARCADORES_SYSTEM` (que barram o turno -> handoff), aqui a bolha e fala legitima com um residuo de
# molde no fim/inicio: strippa-se SO a substring da tag e mantem-se a fala. Angle-bracket + palavra de
# molde nunca aparece em mensagem real de cliente, entao o strip nao tem colateral.
#
# `ele` entrou junto com `cliente`: o falante dos few-shots de `regras.md.j2` foi renomeado
# <cliente> -> <ele> (F18, colisao com o BLOCO DE DADO <cliente ...> do turno). `cliente` fica no
# regex por compatibilidade — persona.md e prompts antigos/cacheados ainda podem moldar com ele.
_RE_TAG_EXEMPLO = re.compile(
    r"</?(?:ela|ele|cliente|exemplo|certo|errado|par|porque)>", re.IGNORECASE
)


def _bolha_descartavel(b: str) -> bool:
    """Bolha que o Estagio 0 strippa: raciocinio vazado, placeholder de template nao preenchido,
    promessa aberta "sem limite", OU chave Pix digitada. Nenhuma e fala valida ao cliente -- as
    duas primeiras entregam a IA; a terceira e promessa de quantidade que a operacao proibiu
    (reuniao 22/07); a quarta e chave inventada (a real e anexada pelo sistema, nunca pela bolha).

    A sonda-de-balcao NAO entra aqui: ela e fala do tipo certo dita do jeito errado, entao merece
    regen (gatilho `sonda` do gate) em vez do drop mudo -- ver `bolhas_sonda`.

    CARVE-OUT (ADR-0042): a bolha DETERMINISTICA de contato da parceira -- a que o coordenador
    anexa com o telefone dela, no mesmo trilho da chave Pix -- casa `_RE_CHAVE_PIX` pelo ramo
    `\\d{11,14}` (um E.164 tem 13 digitos corridos) e morreria em silencio aqui. A saida NAO e
    afrouxar `_RE_CHAVE_PIX`, que protege a chave de TODA modelo: e absolver UMA forma exata, a
    que so o sistema produz (`eh_bolha_de_contato_da_parceira` faz fullmatch da bolha inteira).
    Chave Pix de verdade -- e-mail, EVP, CPF, numero solto, numero no meio de uma frase --
    continua sendo derrubada, e o carve-out nao vale para nenhum dos outros tres gatilhos."""
    return (
        tem_marcador_raciocinio(b)
        or tem_placeholder_template(b)
        or tem_promessa_sem_limite(b)
        or (tem_chave_pix(b) and not eh_bolha_de_contato_da_parceira(b))
    )


def _limpar_bolhas(texto: str) -> str:
    """Estagio 0 (transformacao pura de um agregado): descarta as bolhas de raciocinio/placeholder e
    strippa o delimitador de exemplo (`_RE_TAG_EXEMPLO`) das que sobram, mantendo a fala.

    Distributivo sobre o `\\n\\n` (bolha nao cruza fronteira de mensagem): aplicar isto no agregado do
    turno OU no content de cada AIMessage e rejuntar rende o mesmo texto -- o que preserva o invariante
    do `_sanear_raciocinio` (o coordenador re-deriva o texto das mensagens). Sem leak/tag -> devolve o
    texto identico (no-op, curto-circuito la em cima). Bolha que era SO a tag (`</ela>` sozinha) some
    de vez -- so a substring da tag e removida, mas a bolha vazia resultante nao vai ao cliente."""
    saidas: list[str] = []
    for b in texto.split("\n\n"):
        if _bolha_descartavel(b):
            continue
        limpa = _RE_TAG_EXEMPLO.sub("", b)
        if limpa.strip():
            saidas.append(limpa)
    return "\n\n".join(saidas)


# Detector de REPETICAO (rastro de papagaio): bolha do turno quase identica a uma bolha recente da
# propria IA -- o padrao classico e o cliente silenciar e a IA re-perguntar a MESMA coisa. Humano
# nao repete verbatim: reformula ("como te falei...") ou fica quieto. Limiares conservadores: so
# bolhas com >= _REPETICAO_MIN chars normalizados (cumprimento curto -- "oi amor", "kkk" -- repete
# legitimamente) e similaridade >= _REPETICAO_LIMIAR; uma reformulacao real ("como te falei: <o
# endereco>") ja cai abaixo do limiar. Janela = ultimas _REPETICAO_JANELA bolhas ja enviadas.
_REPETICAO_LIMIAR = 0.90
_REPETICAO_MIN = 25  # piso p/ match FUZZY (reformulacao parcial: "como te falei: <endereco>")
# Piso menor p/ reenvio EXATO (ratio 1.0): a bolha de preco curta ("400 1h no meu local", 19 chars
# normalizados) passava sob o piso fuzzy de 25 e o papagaio literal ia ao cliente (onda 1, finding
# C). Ainda isenta saudacao/gracejo curto ("oi amor" 7, "boa tarde amor" 14) que repete legitimamente.
_REPETICAO_MIN_VERBATIM = 15
_REPETICAO_JANELA = 12

# Sondas canonicas do prompt que repetem ABAIXO do piso ("seria hoje" tem 10 chars normalizados):
# sao justamente as falas que o `<ja_sondou_o_dia>` promete dizer UMA vez na conversa inteira, e o
# diagnostico 11/08 mediu "Seria hoje ?" saindo verbatim duas vezes em dois cenarios sem o detector
# ver nada. Conjunto fechado (nao um piso menor p/ todo mundo): saudacao/gracejo curto continua
# repetindo de graca.
_SONDAS_REPETIVEIS = frozenset(
    {"seria hoje", "seria agora", "que horas", "seria que horas", "e hoje", "vem agora", "vem hoje"}
)

_RE_NAO_PALAVRA = re.compile(r"[^\w\s]+")
_RE_ESPACOS = re.compile(r"\s+")
# Cauda de voz que o envio pode remover DEPOIS do guard (`normalizar_vocativo_voz`/emoji, camada de
# voz do worker, workers/_saida_guard.py): vocativo trailing e o "rs". Sai da CHAVE de comparacao —
# nao do texto — para o guard julgar a bolha que o cliente de fato recebe. Sem isso o julgamento
# ficava do lado errado por um fio: "seria que horas hoje amor" x "seria que horas hoje" da ratio
# 0,889, um cabelo abaixo do limiar 0,90, e a pergunta duplicada foi ao cliente (trace 66b8161e).
_CAUDA_DE_VOZ = ("amor", "vida", "rs")


def _normalizar_bolha(b: str) -> str:
    """Normaliza p/ comparacao de repeticao: minusculas, sem pontuacao/emoji, espacos colapsados e
    sem a cauda de voz (vocativo/"rs"), que o envio remove por sorteio depois do guard."""
    tokens = _RE_ESPACOS.sub(" ", _RE_NAO_PALAVRA.sub(" ", b.lower())).strip().split()
    while len(tokens) > 1 and tokens[-1] in _CAUDA_DE_VOZ:
        tokens.pop()
    return " ".join(tokens)


def _bolhas_historicas(messages: Sequence[BaseMessage]) -> list[str]:
    """Ultimas bolhas que a IA JA ENVIOU nesta conversa -- AIMessages historicas re-injetadas pelo
    prepare_context (sem usage_metadata; inverso exato de `mensagens_do_turno`)."""
    bolhas = [
        b
        for m in messages
        if isinstance(m, AIMessage) and m.usage_metadata is None
        for b in texto_da_mensagem(m).split("\n\n")
        if b.strip()
    ]
    return bolhas[-_REPETICAO_JANELA:]


# Piso das PERGUNTAS: refazer verbatim uma pergunta que ela ja fez e o papagaio mais visivel do
# funil ("Qual seu nome ?" duas vezes seguidas, medido ao vivo em 12/08 — 13 chars normalizados,
# um a menos que o piso verbatim, e a `_SONDAS_REPETIVEIS` e allowlist: so cobre o que alguem
# lembrou de listar). Pergunta e outra classe: afirmacao curta repete de graca ("Perfeito", "Oii"),
# pergunta repetida sempre soa como quem nao leu a resposta. 9 deixa de fora o "tudo bem" (8) da
# saudacao e pega "seria hoje" (10) e "qual seu nome" (13).
_REPETICAO_MIN_PERGUNTA = 9


def _conta_para_repeticao(bolha: str, normalizada: str) -> bool:
    """A bolha entra na conta do detector? (piso de tamanho, piso de pergunta/numero OU sonda)."""
    if "?" in bolha and len(normalizada) >= _REPETICAO_MIN_PERGUNTA:
        return True
    # Bolha CURTA que carrega numero: "A 2h fica 700 amor" reenviada verbatim tinha 13 chars
    # normalizados e passava sob o piso de 15 (medido ao vivo 12/08, roteiro duas_portas). O piso
    # verbatim existe pela saudacao curta que repete de graca — e saudacao nao tem numero dentro.
    if _RE_DIGITOS.search(normalizada) and len(normalizada) >= _MESMOS_NUMEROS_MIN:
        return True
    return len(normalizada) >= _REPETICAO_MIN_VERBATIM or normalizada in _SONDAS_REPETIVEIS


# Piso do fuzzy quando as duas bolhas citam os MESMOS numeros. O papagaio mais caro do funil e a
# bolha de fechamento reformulada em cima da MESMA hora — "Consigo às 17h, fecha ?" no turno 2,
# "Consigo às 17h então" no 3, "Consigo às 17h, te espero" no 4 (medido ao vivo em 12/08, 4 de 40
# conversas, e o feedback do grupo de testes: a mesma bolha saindo tres vezes). Nenhuma passava:
# 20-24 chars normalizados contra um piso fuzzy de 25. O piso existe para nao flagrar saudacao
# curta reformulada — e saudacao nao carrega numero. Numeros DIFERENTES ("400 1h" x "700 2h")
# continuam fora: mesma forma com dado novo e informacao, nao papagaio.
_MESMOS_NUMEROS_MIN = 12
_RE_DIGITOS = re.compile(r"\d+")


def _tem_numero_novo(nova: str, vista: str) -> bool:
    """A bolha nova carrega algum numero que a anterior NAO tinha?

    E o invariante escrito duas linhas acima ("mesma forma com dado NOVO e informacao, nao
    papagaio") e pinado por `test_repeticao_nao_flagra_bolha_de_forma_igual_com_numero_novo` --
    mas ele so era aplicado no `_mesma_abertura` (que exige numeros IGUAIS). No ramo fuzzy nao
    havia isenção nenhuma: "400 1h + 100 o uber ida e volta" contra "400 1h + o uber ida e volta"
    da ratio 0,926 com 29 chars e era flagrada como papagaio -- justo a bolha que carregava o
    numero inedito do turno (loop-massa r2, eixo externo t6: guard disparou, a regen recebeu
    "repita menos" e o turno custou +88%). O par do teste so passava por duas margens acidentais
    (ratio 0,8947 e 19 chars).
    """
    return bool(set(_RE_DIGITOS.findall(nova)) - set(_RE_DIGITOS.findall(vista)))


def _piso_fuzzy(bolha: str, vista: str, *, duas_perguntas: bool = False) -> int:
    """O piso de tamanho do match fuzzy para ESTE par de bolhas normalizadas."""
    numeros = _RE_DIGITOS.findall(bolha)
    if numeros and numeros == _RE_DIGITOS.findall(vista):
        return _MESMOS_NUMEROS_MIN
    # Duas PERGUNTAS quase iguais ("qual seu nome" x "e qual seu nome", ratio 0,93): o piso de 25
    # foi calibrado contra a saudacao reformulada, e refazer a pergunta ja feita e a classe onde
    # ate a variacao de uma palavra e papagaio (medido ao vivo 12/08, roteiro dado_na_mesa).
    # Perguntas DIFERENTES nao chegam perto do limiar ("qual seu nome" x "qual seu bairro": 0,71).
    if duas_perguntas:
        return _REPETICAO_MIN_PERGUNTA
    return _REPETICAO_MIN


# Ultimo degrau do papagaio de fechamento: a reformulacao que muda so a CAUDA em cima da mesma
# oferta -- "consigo as 17h fecha" x "consigo as 17h entao" da ratio 0,80 e passa longe do limiar,
# mesmo com o piso de mesmos-numeros (medido ao vivo em 12/08, roteiro duas_portas). O que essas
# duas bolhas tem em comum nao e a forma inteira: e a ABERTURA -- a mesma oferta, com o mesmo
# numero, dita de novo. Exigir que o prefixo compartilhado (cortado na fronteira de palavra)
# carregue o numero mantem fora o par que so compartilha o comeco generico ("te espero as 20h" x
# "consigo as 20h fecha" nao compartilha prefixo nenhum) e o par com dado NOVO ("400 1h no meu
# local" x "700 2h no meu local" tem numeros diferentes).
_ABERTURA_MIN = 12


_COBERTURA_MIN = 0.90


def _mesma_abertura(nova: str, vista: str) -> bool:
    """As duas bolhas normalizadas reofertam a MESMA coisa -- mudando so a cauda ou so o comeco?

    Dois recortes do mesmo papagaio, os dois exigindo os MESMOS numeros nas duas bolhas:
    prefixo compartilhado que carrega o numero (a cauda muda) e cobertura quase total da bolha
    menor dentro da maior — "isso amor, 400 a 1h + o uber ida e volta" seguido de "400 1h + o uber
    ida e volta" e a mesma cotacao dita duas vezes (ratio 0,79; medido ao vivo 12/08, roteiro
    externo), mas nao compartilha abertura nenhuma.
    """
    numeros = _RE_DIGITOS.findall(nova)
    if not numeros or numeros != _RE_DIGITOS.findall(vista):
        return False
    comum = commonprefix([nova, vista])
    comum = comum[: comum.rindex(" ")] if " " in comum and comum not in (nova, vista) else comum
    if len(comum) >= _ABERTURA_MIN and _RE_DIGITOS.search(comum):
        return True
    curta, longa = sorted((nova, vista), key=len)
    if len(curta) < _MESMOS_NUMEROS_MIN:
        return False
    coberto = sum(b.size for b in SequenceMatcher(None, curta, longa).get_matching_blocks())
    return coberto / len(curta) >= _COBERTURA_MIN


# A dobradinha de fechamento: DUAS perguntas de fechamento na MESMA resposta ("Podemos combinar
# 21h?" seguida de "Fechou 21h entao amor?", feedback do grupo de testes em 12/08). Nao e repeticao
# de forma -- as duas frases nao se parecem -- e por isso nenhum limiar de similaridade as pega; e
# repeticao de ATO: pedir duas vezes o mesmo sim no mesmo turno soa ansioso e da ao cliente duas
# perguntas para responder. So conta PERGUNTA (a confirmacao afirmativa depois do aceite -- "te
# espero as 20h entao" -- e conduta certa) e so dentro do turno; oferta de duas portas legitima traz
# horas DIFERENTES na mesma bolha, nao duas bolhas pedindo o sim.
_RE_PEDIDO_DE_FECHAMENTO = re.compile(
    r"\b(fecha|fechamos|fechou|fechado|combinamos|combinar|confirmo|confirma|confirmar|"
    r"pode ser|posso te esperar|te espero|marco|marcamos)\b"
)


def _dobradinha_de_fechamento(nova: str, bolha: str, anteriores: Sequence[tuple[str, str]]) -> bool:
    """A bolha repete, no mesmo turno, um pedido de fechamento que ja foi feito?

    Exige numeros PRESENTES e IGUAIS nas duas bolhas -- e o que identifica "o mesmo sim". O
    `not numeros or ...` que morava aqui era vacuamente verdadeiro quando a bolha nova nao tinha
    digito, e ai qualquer segunda pergunta com verbo da familia virava dobradinha: "Consigo as 21h,
    fecha?" + "Pode ser aqui no meu apartamento?" flagrava a SEGUNDA, que e a pergunta de logistica
    que fecha a venda. `pode ser`/`te espero`/`confirma` estao na regex de fechamento, entao o
    estrago pegava logistica, lugar e ate flerte. Isso contradizia o proprio invariante do teste
    `test_repeticao_nao_flagra_fechamento_seguido_de_outra_pergunta` ("pedir o sim e depois pedir o
    endereco e o turno bem conduzido"), que so passava por escolher segundas bolhas sem esses verbos.
    """
    if "?" not in bolha or not _RE_PEDIDO_DE_FECHAMENTO.search(nova):
        return False
    numeros = _RE_DIGITOS.findall(nova)
    if not numeros:
        return False
    return any(
        "?" in anterior_bolha
        and _RE_PEDIDO_DE_FECHAMENTO.search(anterior)
        and numeros == _RE_DIGITOS.findall(anterior)
        for anterior, anterior_bolha in anteriores
    )


# Fusao de bolhas: quantas bolhas consecutivas ja enviadas a fala nova pode ter juntado numa so.
# 4 e o teto de bolhas por turno da persona -- acima disso a "junta" seria um turno inteiro colado
# a outro, que nao e a forma do papagaio observado.
_FUSAO_MAX_BOLHAS = 4


def _fundiu_bolhas(nova_inteira: str, historicas_normalizadas: Sequence[str]) -> bool:
    """A fala nova INTEIRA e a juncao de bolhas que ela ja mandou em sequencia?

    O detector e por BOLHA, e a mesma fala escapava so trocando de embalagem: as duas bolhas do
    turno anterior ("Sou bem tranquila" + "Estilo namoradinha") voltaram FUNDIDAS numa bolha so, e
    cada metade sozinha dava ratio ~0,59 -- longe do limiar (loop-massa r2, eixo explorador; dano
    observado: o cliente respondeu "Vc ja falou isso rs"). Comparar o turno inteiro contra a
    juncao das bolhas CONSECUTIVAS devolve a simetria -- o mesmo conteudo, na mesma ordem, e pego
    venha ele em uma bolha ou em quatro.

    Mesmo limiar e mesmo piso do fuzzy, e a mesma isencao de NUMERO NOVO (`_tem_numero_novo`): uma
    fala que junta o que ja foi dito MAIS um numero inedito e informacao, nao papagaio.
    """
    if len(nova_inteira) < _REPETICAO_MIN:
        return False
    total = len(historicas_normalizadas)
    for i in range(total):
        for j in range(i + 2, min(i + _FUSAO_MAX_BOLHAS, total) + 1):
            junta = " ".join(historicas_normalizadas[i:j]).strip()
            if not junta or _tem_numero_novo(nova_inteira, junta):
                continue
            if SequenceMatcher(None, nova_inteira, junta).ratio() >= _REPETICAO_LIMIAR:
                return True
    return False


def bolhas_repetidas(
    texto: str, historicas: Sequence[str], *, houve_aceite: bool = False
) -> list[str]:
    """Bolhas do turno quase identicas a uma bolha recente da propria IA -- ou a outra bolha
    anterior do MESMO turno (PURA; devolve as bolhas originais, nao normalizadas, p/ o drop).

    Reenvio EXATO (ratio 1.0) conta ja no piso menor (_REPETICAO_MIN_VERBATIM) -- pega a bolha de
    preco curta que passava sob o piso fuzzy; match FUZZY segue exigindo _REPETICAO_MIN p/ nao
    flagar saudacao curta reformulada, EXCETO quando as duas bolhas carregam os mesmos numeros (ver
    `_MESMOS_NUMEROS_MIN`). As sondas canonicas (`_SONDAS_REPETIVEIS`) contam ABAIXO do piso:
    repeti-las e a violacao que o proprio prompt nomeia. Negacao canned repetida nao e rastro
    (pool curado) -> isenta.

    `houve_aceite` desliga o ramo do ECO DE ABERTURA (`_mesma_abertura`), a cauda de FUSAO
    (`_fundiu_bolhas`) e -- desde 12/08 -- tambem `exato`/`fuzzy` para bolha que NAO e pergunta.
    Ele existe p/ pegar a
    reoferta que so troca a cauda ("Consigo as 17h, fecha ?" -> "Consigo as 17h entao ?"), mas e
    cego ao que o CLIENTE disse no meio: depois do "fechou" dele, "Consigo as 17h entao, te espero"
    reusa a mesma abertura e e a confirmacao certa -- o proprio comentario de
    `_dobradinha_de_fechamento` a chama de conduta certa. Sendo a unica bolha do turno, o drop
    zerava o texto e o turno saia MUDO no instante do fechamento.

    O furo que a versao anterior desta docstring admitia ("o eco literal continua coberto pelos
    ramos `exato`/`fuzzy`, que nao dependem deste gate") custou o t6 do `decidido_rapido_b`
    (loop-massa r3, achado 4a): o `<entregue_agora>` MANDOU entregar a rua, o modelo entregou, e a
    bolha da rua caiu no ramo `exato` -- duas vezes (rascunho e regen) -- levando o cliente a pedir
    o endereco de novo no turno seguinte. Re-entregar o dado combinado (rua, hora, valor) depois do
    aceite e a conduta certa, e o detector nao tem como distinguir "eco" de "resposta".
    O corte NAO e "desliga tudo no aceite": PERGUNTA repetida continua flagrada mesmo com aceite --
    e o papagaio que continua visivel ("quem nao leu a resposta", mesma razao do
    `_REPETICAO_MIN_PERGUNTA`), e re-perguntar depois do "fechou" e pior, nao melhor."""
    vistas = [n for b in historicas if _conta_para_repeticao(b, n := _normalizar_bolha(b))]
    perguntas = {_normalizar_bolha(b) for b in historicas if "?" in b}
    do_turno: list[tuple[str, str]] = []
    repetidas: list[str] = []
    for b in texto.split("\n\n"):
        if b.strip() in _CANNED_CURADAS:
            continue
        n = _normalizar_bolha(b)
        if not _conta_para_repeticao(b, n):
            continue
        e_pergunta = "?" in b
        exato = n in vistas
        fuzzy = any(
            not _tem_numero_novo(n, v)
            and len(n) >= _piso_fuzzy(n, v, duas_perguntas=e_pergunta and v in perguntas)
            and SequenceMatcher(None, n, v).ratio() >= _REPETICAO_LIMIAR
            for v in vistas
        )
        if houve_aceite and not e_pergunta:
            # Turno do aceite: re-entregar o DADO ja combinado nao e eco (ver docstring). So a
            # pergunta repetida sobrevive ao gate.
            exato = fuzzy = False
        eco = not houve_aceite and any(_mesma_abertura(n, v) for v in vistas)
        if exato or fuzzy or eco or _dobradinha_de_fechamento(n, b, do_turno):
            repetidas.append(b)
        vistas.append(n)
        if e_pergunta:
            perguntas.add(n)
        do_turno.append((n, b))
    # Ultimo recorte: a fala nova INTEIRA como juncao de bolhas ja enviadas (ver `_fundiu_bolhas`).
    # So quando NADA foi flagrado por bolha -- aqui o veredito e sobre o turno, nao sobre a bolha,
    # e o que volta e o turno inteiro (o que sobra depois do drop cai no trilho de recuperacao).
    #
    # `houve_aceite` desliga a cauda pelo MESMO motivo que desliga o eco de abertura, e com dano
    # maior: o turno do fechamento ("Fechado amor, 400 a 1h, te espero as 21h") e por construcao a
    # juncao das bolhas da oferta que ele acabou de aceitar, e como o veredito aqui e sobre o TURNO
    # INTEIRO o drop deixava o fechamento MUDO (revisao da r2). Fora do fechamento a cauda segue
    # armada -- o eco-fusao sem aceite continua flagrado.
    if repetidas or houve_aceite:
        return repetidas
    bolhas_do_turno = [
        b for b in texto.split("\n\n") if b.strip() and b.strip() not in _CANNED_CURADAS
    ]
    inteira = _normalizar_bolha(" ".join(bolhas_do_turno))
    if _fundiu_bolhas(inteira, [_normalizar_bolha(b) for b in historicas]):
        return bolhas_do_turno
    return []


def _drop_bolhas(texto: str, remover: set[str]) -> str:
    """Remove do agregado as bolhas repetidas (fallback da repeticao: silencio > papagaio)."""
    return "\n\n".join(b for b in texto.split("\n\n") if b not in remover)


def _falas_do_burst_atual(conversa_crua: Sequence[BaseMessage]) -> list[str]:
    """Falas do burst ATUAL do cliente: HumanMessages contiguas no FIM da janela crua do turno
    (`EstadoAgente.conversa_crua` — a janela ANTES da anexacao do contexto dinamico/lembrete).

    Vazia quando o ultimo a falar nao foi ele, ou quando o State nao publicou a janela (teste
    unitario que chama o guard direto, webhook fino) — os gatilhos que dependem do pedido DELE
    simplesmente nao armam.

    Para na marca de pausa, como `_burst_do_cliente` (_janela_do_turno; incidente 29/07, trace
    06db4298): numa retomada sem AIMessage entre a marca e as falas novas, bolhas de dias atras
    nao podem entrar como "burst atual" — um "onde fica?" pre-pausa armaria o gatilho de endereco
    num turno de reengajamento, e este burst divergiria do de `perguntas_do_burst` no MESMO guard.
    """
    from .._texto_turno import e_marca_pausa

    falas: list[str] = []
    for m in reversed(conversa_crua):
        if isinstance(m, HumanMessage) and not e_marca_pausa(m):
            falas.append(str(m.content))
            continue
        break
    return list(reversed(falas))


class _VeredictoAup(BaseModel):
    """Saida estruturada da Etapa 2 (judge de AUP vinculante).

    `motivo` e enum fechado (Literal): entra como constraint no schema do function-calling
    (guia a geracao) e garante vocabulario estavel na telemetria (`aup_saida_{motivo}`).
    Rotulo fora do vocabulario vira parsing_error -> retry 1x -> default seguro do caller.
    """

    viola: bool = Field(description="true se a bolha deve ser BARRADA (viola a AUP)")
    motivo: Literal[
        "ia_self", "system_leak", "cross_modelo", "aup_dura", "reasoning_leak", "nenhum"
    ] = Field(description="rotulo do porque; 'nenhum' quando viola=false")


async def _legendas_do_turno(conn: Any, turno_id: str) -> list[str]:
    """Legendas das midias anexadas neste turno (arg `legenda` de enviar_midia, em tool_calls).

    A legenda vai ao cliente como caption FORA da bolha de texto (o coordenador a despacha do
    `tool_calls`, nao do content da AIMessage) -- por isso precisa entrar no scan/judge do guard
    junto com o texto. Escopada por `turno_id` (deterministico): nao traz legenda de turno
    anterior. Espelha `ferramentas.midia._midias_do_turno`.
    """
    res = await conn.execute(
        "SELECT payload->>'legenda' AS legenda FROM barravips.tool_calls "
        "WHERE turno_id = %s AND tool_name = 'enviar_midia'",
        (turno_id,),
    )
    return [leg for r in await res.fetchall() if (leg := (r.get("legenda") or "").strip())]


# Tools cujo efeito ANEXA algo ao turno fora da bolha de texto. Ficam num parametro (`= ANY(%s)`) e
# nao no corpo do SQL de proposito: e uma lista, e o proximo anexo entra aqui sem reescrever a query.
_TOOLS_COM_ANEXO = ("enviar_midia", "registrar_extracao")


async def _anexos_do_turno(conn: Any, turno_id: str) -> list[str]:
    """O que o SISTEMA ja anexou a ESTE turno, dito em linguagem de fala (para o lembrete da regen).

    A regen roda SEM tools (re-entrar no grafo re-executaria efeito colateral) e a janela dela corta
    as ToolMessages do proprio turno (`_janela_ate_a_fala_do_cliente`) -- entao o modelo re-escreve
    sabendo que PROMETEU fotos e sem nenhum sinal de que elas ja estao indo. Medido (loop-massa r3,
    achado 5): `objetor_b` t8 com duas `enviar_midia` em `success` e a regen devolvendo rubrica de
    teatro ("(aqui vao as fotos e o video)"), e `externo_a` convertendo a chave Pix pendente em
    passado ("Te mandei o pix"). O conserto nao e dar tools a regen: e contar a ela o que ja saiu.

    Le do `tool_calls` (o que de fato COMMITOU), nunca das AIMessages -- o `_zerar_turno` do proprio
    guard tem o direito de apagar os `tool_calls` das mensagens.
    """
    res = await conn.execute(
        "SELECT tool_name,"
        " resultado->>'enviar_pin' AS pin,"
        " resultado->>'pix_solicitado' AS pix"
        " FROM barravips.tool_calls WHERE turno_id = %s AND tool_name = ANY(%s)",
        (turno_id, list(_TOOLS_COM_ANEXO)),
    )
    rows = await res.fetchall()
    anexos: list[str] = []
    if any((r.get("tool_name") or "") == "enviar_midia" for r in rows):
        anexos.append("as suas fotos/video")
    if any(str(r.get("pin") or "").lower() == "true" for r in rows):
        anexos.append("a localizacao do ponto de encontro")
    if any(str(r.get("pix") or "").lower() == "true" for r in rows):
        anexos.append("a sua chave Pix")
    return anexos


@dataclass(frozen=True)
class _CadastroGuard:
    """Recortes do cadastro da modelo que os detectores do gate consomem (uma leitura por turno).

    `permitidos_lugar`: vocabulario do eco de regiao (vazio = detector desligado — cadastro sem
    lugar ou atendimento externo). `tokens_endereco`: tokens que so aparecem quando ela ENTREGA o
    ponto (nome do hotel/rua, sem a regiao — `tokens_do_endereco`), p/ o gatilho `endereco`.

    Nao carrega mais estado/tipo/cotacao do atendimento: quem decide se o gatilho `endereco` arma e
    o CARIMBO `local_endereco_no_prompt` do State (estado.py) — reavaliar o gate aqui, com a linha
    relida DEPOIS da extracao, era o skew que cobrava um bloco ausente do prompt.
    """

    permitidos_lugar: set[str]
    tokens_endereco: set[str]


async def _cadastro_guard(conn: Any, ctx: ContextAgente) -> _CadastroGuard:
    """Vocabulario de lugar/endereco do cadastro + estado do atendimento, p/ os detectores.

    Eco de regiao desligado (permitidos vazio) em dois casos: cadastro sem nenhum campo de lugar,
    e atendimento EXTERNO — no externo quem se desloca e ela, entao falar do bairro DELE ("vou ai
    no Cambui") e a fala certa, e o cadastro dela nao e a referencia. Uma leitura so, na conexao
    que o guard ja abriu p/ as legendas.
    """
    res = await conn.execute(
        """
        SELECT mo.localizacao_operacional, mo.nome_local, mo.endereco_formatado,
               a.tipo_atendimento::text AS tipo_atendimento
          FROM barravips.modelos mo
          LEFT JOIN barravips.atendimentos a ON a.id = %s
         WHERE mo.id = %s
        """,
        (ctx.atendimento_id, ctx.modelo_id),
    )
    row = await res.fetchone()
    if row is None:
        return _CadastroGuard(set(), set())
    permitidos = (
        set()
        if row["tipo_atendimento"] == "externo"
        else tokens_de_lugar(
            row["localizacao_operacional"], row["nome_local"], row["endereco_formatado"]
        )
    )
    return _CadastroGuard(
        permitidos_lugar=permitidos,
        tokens_endereco=tokens_do_endereco(
            row.get("endereco_formatado"),
            row.get("nome_local"),
            row.get("localizacao_operacional"),
        ),
    )


@dataclass(frozen=True)
class _CardapioGuard:
    """Recortes do cardapio da modelo que os detectores do gate consomem.

    `inclusos`: a linha "Inclusos" do <fetiches> (`bolhas_incluso_fantasma`). `servicos`: tudo que
    ela FAZ — fetiches + programas, com as expansoes de conduta (`bolhas_servico_fantasma`).
    `precos_tabela`: triplas (preco, horas, preco_minimo) de `modelo_programas`, base do conjunto
    de valores legitimos (`bolhas_preco_fantasma`) — o `preco_minimo` (NULL na maioria das linhas)
    entra porque a escada de desconto que legitima os numeros e clampada por ele: sem o piso, o
    guard legitimaria os 25% cheios em cima de um pacote cadastrado como minimo e o feedback do
    gatilho `preco` ainda ENSINARIA a IA a ofertar la. `extras_cadastrados`: os precos cadastrados
    dos fetiches pagos com numero de verdade na coluna — sem eles o total que o <fetiches>
    renderiza pelo preco do painel (decisao de 2026-08-11) ficaria fora do conjunto e o guard
    derrubaria a cotacao correta. Sem o `cobra_por_pessoa` ao lado desde o ADR-0039: composicao
    nao tem mais conta propria, e o preco cadastrado dela ja e o TOTAL do extra.
    """

    inclusos: set[str]
    servicos: set[str]
    precos_tabela: list[tuple[Decimal, Decimal, Decimal | None]]
    extras_cadastrados: list[Decimal]


async def _cardapio_da_modelo(conn: Any, ctx: ContextAgente) -> _CardapioGuard:
    """Cardapio completo da modelo p/ os detectores de incluso/servico/preco fantasma.

    `inclusos` usa o mesmo recorte do `render_fetiches` (persona.py): `preco` NULL = incluso,
    preenchido = extra pago; vazio NAO desliga o detector de incluso — e o caso da falha medida.
    Duas leituras, na conexao que o guard ja abriu p/ as legendas.
    """
    res = await conn.execute(
        """
        SELECT f.nome, mf.preco
          FROM barravips.modelo_fetiches mf
          JOIN barravips.fetiches f ON f.id = mf.fetiche_id
         WHERE mf.modelo_id = %s
        """,
        (ctx.modelo_id,),
    )
    fetiches = await res.fetchall()
    res = await conn.execute(
        """
        SELECT p.nome, mp.preco, mp.preco_minimo, d.horas
          FROM barravips.modelo_programas mp
          JOIN barravips.programas p ON p.id = mp.programa_id
          JOIN barravips.duracoes d ON d.id = mp.duracao_id
         WHERE mp.modelo_id = %s
        """,
        (ctx.modelo_id,),
    )
    programas = await res.fetchall()
    from barra.dominio.atendimentos.service import preco_cadastrado_de_fetiche

    extras_cadastrados = [
        cadastrado
        for r in fetiches
        if r.get("preco") is not None
        and (cadastrado := preco_cadastrado_de_fetiche(r["preco"])) is not None
    ]
    return _CardapioGuard(
        inclusos=tokens_de_incluso(*[r["nome"] for r in fetiches if r.get("preco") is None]),
        servicos=vocabulario_de_servicos(
            [r["nome"] for r in fetiches], [r["nome"] for r in programas]
        ),
        precos_tabela=[
            (
                Decimal(str(r["preco"])),
                Decimal(str(r["horas"])),
                None if r.get("preco_minimo") is None else Decimal(str(r["preco_minimo"])),
            )
            for r in programas
            if r.get("preco") is not None and r.get("horas") is not None
        ],
        extras_cadastrados=extras_cadastrados,
    )


def _valores_legitimos(
    precos_tabela: list[tuple[Decimal, Decimal, Decimal | None]],
    valor_acordado: Any,
    messages: Sequence[BaseMessage],
    ids_do_turno: frozenset[str | None] | set[str | None] = frozenset(),
    extras_cadastrados: Sequence[Decimal] = (),
) -> set[int]:
    """Conjunto fechado de valores que a bolha PODE citar como preco (p/ `bolhas_preco_fantasma`).

    Por preco de tabela: o proprio e o total-com-extra (1 e 2 fetiches, a mesma conta
    pre-computada que o <fetiches> mostra — `render_fetiches`/ADR-0038), TUDO nos tres patamares
    da escada de desconto (cheio/degrau/piso,
    ADR-0031, via `valor_no_patamar`, site unico das contas). Os tres patamares porque o extra
    ACOMPANHA o pacote: com a 1h a 400/300, a fala correta "600 com a inversao" no piso da 1h
    (300 + 300) so passa se o conjunto tiver 600 — legitimar so o cheio barraria exatamente a
    negociacao que o <desconto> manda fazer. Mais o valor ja na mesa (`valor_acordado`), todo
    numero que apareceu em fala do CLIENTE na janela — ecoar/recusar o numero DELE e fala
    legitima ("250 nao consigo amor") — e o `pix_deslocamento_valor` de settings (a fala do uber
    prescrita pelo <tipos_de_encontro>). Truncado E arredondado entram (a IA arredonda de
    cabeca; a divergencia de 1 real nao pode derrubar bolha boa).

    Rodada 4: entram tambem os precos que a PROPRIA IA/vendedora ja citou no historico
    (AIMessages FORA do turno atual — `ids_do_turno` exclui as deste turno, senao o preco errado
    se legitimaria sozinho) e os degraus/piso da escada COMPUTADOS SOBRE eles: repetir o numero
    que ja esta na conversa e consistencia, nao invencao (historico seedado/real pode carregar
    promo fora da tabela de hoje), e a promocao legitima via escada continua valida a partir do
    preco em mesa. A direcao RESTRITIVA ("citou um preco -> os outros da tabela saem do conjunto")
    foi considerada e recusada: sem atribuicao por-pacote do numero citado, ela derrubaria a
    cotacao legitima de OUTRA duracao no turno seguinte.

    ADR-0039: o DOBRO do pacote saiu do conjunto. Ele estava aqui como o total do regime
    "por pessoa" (ADR-0035) e esse regime deixou de existir — composicao soma o mesmo extra dos
    atos, que ja entra pelo `linhas_de_uma_hora`. E o unico estreitamento desta mudanca (todo o
    resto so troca um numero por outro), e ele nao quebra conversa em andamento: o dobro que a IA
    tiver cotado ANTES continua legitimo pelo ramo das AIMessages do historico, que legitima todo
    preco ja saido da boca dela sem consultar tabela nenhuma."""
    from barra.dominio.atendimentos.service import (
        DURACAO_MINIMA_FETICHE_PAGO,
        PATAMARES,
        aceita_fetiche_pago,
        degrau_de_desconto,
        extra_de_fetiche,
        piso_de_desconto,
        valor_no_patamar,
    )

    valores: set[int] = set()

    def _add(x: Decimal) -> None:
        valores.add(int(x))
        valores.add(int(x.to_integral_value(rounding=ROUND_HALF_UP)))

    # Piso por VALOR de tabela (nao por linha): o preco citado no historico chega como numero
    # solto, sem programa nem duracao. Duas linhas de mesmo preco com pisos diferentes resolvem
    # pelo mais apertado — o unico valido para qualquer uma delas.
    minimos_por_preco: dict[Decimal, Decimal] = {}
    for preco, _, preco_minimo in precos_tabela:
        if preco_minimo is not None:
            anterior = minimos_por_preco.get(preco)
            minimos_por_preco[preco] = (
                preco_minimo if anterior is None else max(anterior, preco_minimo)
            )

    # Base do extra derivado (ADR-0038): as linhas de 1h da tabela. SEM atribuicao por programa —
    # a tupla que chega aqui nao carrega o nome do pacote, entao qualquer 1h da modelo legitima o
    # total de qualquer linha. Direcao ADITIVA, a mesma da rodada 4: o guard existe para pegar
    # numero que nao vem de tabela nenhuma, e apertar o par (programa x extra) sem saber de qual
    # pacote a bolha fala derrubaria cotacao legitima.
    linhas_de_uma_hora = [
        (preco, preco_minimo)
        for preco, horas, preco_minimo in precos_tabela
        if aceita_fetiche_pago(horas) and horas == DURACAO_MINIMA_FETICHE_PAGO
    ]

    for preco, horas, preco_minimo in precos_tabela:
        for patamar in PATAMARES:
            base = valor_no_patamar(preco, preco_minimo, patamar)
            _add(base)
            # Pacote < 1h nao tem fetiche pago (decisao 11/08/2026, `aceita_fetiche_pago`): a
            # linha entra no conjunto pelo preco dela e pela escada, mas NENHUM total de fetiche
            # — nem o derivado nem o do preco cadastrado. E aqui
            # que a regra vira deterministica: o <fetiches> parou de RENDERIZAR a linha do pacote
            # curto com extra, e o guard para de LEGITIMAR o total dela se ele vier assim mesmo.
            if not aceita_fetiche_pago(horas):
                continue
            # O dobro do pacote NAO entra mais (ADR-0039): composicao passou a somar o mesmo
            # extra dos atos, entao "1600 na 2h de 800" deixou de ser numero de tabela. E o unico
            # ponto desta mudanca que BLOQUEIA fala em vez de so troca-la — e ele so aperta a
            # frente da conversa: o dobro que a IA ja tiver citado num turno anterior continua
            # legitimo pelo ramo `extrair_precos_citados` la embaixo, que nao consulta tabela.
            # Um extra e dois: os dois totais que a tabela do <fetiches> imprime prontos.
            for linha in linhas_de_uma_hora:
                derivado = extra_de_fetiche(linha, horas, patamar=patamar)
                if derivado is not None:
                    _add(base + derivado)
                    _add(base + derivado * 2)
            # Totais pelo preco CADASTRADO do fetiche (decisao 2026-08-11): e o numero que o
            # <fetiches> renderiza, entao precisa ser citavel. O cadastro NAO acompanha o
            # patamar (o operador digitou um valor, nao uma escada), mas o pacote sim — por isso
            # ele soma sobre `base`, e nao sobre `preco`.
            for cadastrado in extras_cadastrados:
                com_cadastro = extra_de_fetiche(
                    None,
                    horas,
                    preco_cadastrado=cadastrado,
                )
                if com_cadastro is not None:
                    _add(base + com_cadastro)
                    _add(base + com_cadastro * 2)
    if valor_acordado is not None:
        _add(Decimal(str(valor_acordado)))
    for m in messages:
        if isinstance(m, HumanMessage):
            for bruto in _RE_NUMERO_DO_CLIENTE.findall(str(m.content)):
                valores.add(int(bruto.replace(".", "")))
        elif isinstance(m, AIMessage) and m.id not in ids_do_turno:
            # Preco ja citado pela propria IA/vendedora (historico, nunca o turno em julgamento):
            # o numero em contexto monetario ("600 1h", "R$ 600") + a escada sobre ele.
            for citado in extrair_precos_citados(str(m.content)):
                preco_citado = Decimal(citado)
                # O piso da linha acompanha o numero mesmo quando ele chega por aqui: sem isto o
                # pacote cadastrado como minimo (Catarina: 250 nos 30min) recuperaria a escada
                # cheia — bastava a IA ter cotado os 250 num turno anterior para 188 voltar ao
                # conjunto legitimo. Preco que nao casa com nenhuma linha (promo antiga do
                # historico seedado) segue sem piso, como antes.
                minimo_citado = minimos_por_preco.get(preco_citado)
                _add(preco_citado)
                _add(degrau_de_desconto(preco_citado, minimo_citado))
                _add(piso_de_desconto(preco_citado, minimo_citado))
    legitimos = {v for v in valores if v >= PRECO_MINIMO_SCAN}
    if legitimos:
        # Unico numero legitimo de FORA da tabela que vem de settings: o uber ida-e-volta que o
        # <tipos_de_encontro> PRESCREVE ("O uber ida e volta fica {pix_valor} amor") — sem ele o
        # guard derrubava a fala que o proprio prompt manda dar (turno MUDO com Pix pendente).
        # So entra com o conjunto ja populado: incondicional, ele ARMARIA o detector de modelo
        # sem tabela (`bolhas_preco_fantasma`: vazio = desligado).
        pix = get_settings().pix_deslocamento_valor
        legitimos.add(int(pix))
        legitimos.add(int(pix.to_integral_value(rounding=ROUND_HALF_UP)))
    return legitimos


# Numero que o CLIENTE citou (3-4 digitos, com ou sem separador de milhar): entra no conjunto
# legitimo como eco — recusar/citar o numero dele e fala valida da negociacao.
_RE_NUMERO_DO_CLIENTE = re.compile(r"\b(\d{1,2}\.\d{3}|\d{3,4})\b")


def tem_marcador_ia(texto: str) -> bool:
    """True se o texto contem auto-referencia de IA / nome de LLM (PURO).

    Usado pela Etapa 1 do guard e reusado pelo eval online de non_disclosure (EVAL-11) como
    rubrica deterministica barata (sem custo de LLM por turno amostrado).
    """
    return bool(_MARCADORES_IA.search(texto))


def tem_marcador_system(texto: str) -> bool:
    """True se o texto vaza fragmento de system/persona/regras (PURO). Mesmo regex da Etapa 1;
    reusado pelo eval online (`online_system_leak`, EVAL-11) — fonte unica do detector."""
    return bool(_MARCADORES_SYSTEM.search(texto))


def tem_marcador_outro_cliente(texto: str) -> bool:
    """True se o texto admite "estou com outro cliente" (segredo da agenda, CONTEXT.md). Mesmo
    regex da Etapa 1; reusado pelo eval online (`online_segredo_agenda`, EVAL-11)."""
    return bool(_MARCADORES_OUTRO_CLIENTE.search(texto))


def _reescrever_turno(
    msgs_turno: list[AIMessage], transformar: Callable[[str], str]
) -> list[AIMessage]:
    """Reescreve as AIMessages do turno cujo content muda sob `transformar`, preservando
    id/usage/response_metadata/tool_calls/additional_kwargs (o reducer troca pelo id; o
    `reasoning_content` do turno mora no ultimo, e a bolha dropada nao e razao p/ o trace perder o
    raciocinio que a explica). O coordenador RE-deriva o
    texto via `extrair_texto_do_turno(messages)` -- nao le um output do guard -- entao qualquer
    limpeza precisa viver NAS mensagens. `transformar` deve ser distributiva sobre o `\\n\\n`
    (bolha nao cruza fronteira de mensagem): aplicada por-mensagem e rejuntada, rende o mesmo
    agregado que aplicada no texto do turno."""
    reescritas: list[AIMessage] = []
    for m in msgs_turno:
        original = texto_da_mensagem(m)
        if not original:
            continue
        limpo = transformar(original)
        if limpo != original:
            reescritas.append(
                AIMessage(
                    id=m.id,
                    content=limpo,
                    tool_calls=m.tool_calls,
                    usage_metadata=m.usage_metadata,
                    response_metadata=m.response_metadata,
                    additional_kwargs=kwargs_preservados(m),
                )
            )
    return reescritas


def _sanear_raciocinio(msgs_turno: list[AIMessage], texto: str) -> tuple[str, list[AIMessage]]:
    """Estagio 0: strippa o RACIOCINIO vazado e o DELIMITADOR DE EXEMPLO do texto do turno, mantendo
    a fala real.

    O texto ao cliente e o agregado do turno separado por `\\n\\n` (`extrair_texto_do_turno`), e o
    chunker quebra na mesma marca -- entao cada `\\n\\n` e uma bolha. `_limpar_bolhas` descarta as
    bolhas de meta-fala/placeholder (`_bolha_descartavel`) E strippa a substring da tag de exemplo
    (`_RE_TAG_EXEMPLO`, ex.: `</ela>`) das que sobram; devolve (texto_saneado, AIMessages reescritas
    via `_reescrever_turno`). Turno limpo -> (texto, []) (no-op, comportamento de hoje).
    """
    texto_saneado = _limpar_bolhas(texto)
    if texto_saneado == texto:
        return texto, []
    return texto_saneado, _reescrever_turno(msgs_turno, _limpar_bolhas)


def _zerar_turno(msgs: Sequence[AIMessage]) -> list[AIMessage]:
    """Zera as AIMessages (mesmo id -> reducer troca), PRESERVANDO usage_metadata +
    response_metadata + o resto de `additional_kwargs`: o coordenador acumula o custo do turno
    lendo `usage_metadata` (turno barrado queimou tokens) e precifica pela tabela do modelo
    (`response_metadata.model_name`). O content vazio -> nenhuma bolha sai; sem tool_calls copiados
    (nem o espelho cru em `additional_kwargs`), o check de truncamento (coordenador 5c, exige
    tool_calls) nao re-dispara.

    `additional_kwargs` volta porque e onde mora o `reasoning_content` (o thinking do turno, lido
    por `_texto_turno.raciocinio_do_turno`) -- e ele NUNCA e despachado ao cliente
    (`extrair_texto_do_turno` le `content`). Descarta-lo aqui apagava do trace a peca que explica a
    fala em todo turno com regen: `raciocinio: null` no root span, sem justificativa escrita
    nenhuma para o descarte (loop-massa r2, eixos externo t6 e explorador t7)."""
    return [
        AIMessage(
            id=m.id,
            content="",
            usage_metadata=m.usage_metadata,
            response_metadata=m.response_metadata,
            additional_kwargs=kwargs_preservados(m),
        )
        for m in msgs
    ]


# Regeneracao one-shot (producao assistida): cap do rascunho descartado no feedback (nao inflar o
# prompt da regen com um turno-monstro) e a razao por gatilho, na 2a pessoa da persona.
_RASCUNHO_MAX = 1200
_FEEDBACK_GATILHO = {
    "leak": (
        "ela deixava escapar fala interna (raciocinio, instrucao de sistema ou detalhe da sua "
        "operacao que voce nunca diria a um cliente)"
    ),
    "repeticao": "ela repetia quase igual algo que voce ja tinha mandado antes nesta conversa",
    "mudo": (
        "ela era so raciocinio interno ou veio VAZIA -- nenhuma fala de verdade chegou ao "
        "cliente, e ele esta esperando resposta"
    ),
    "sonda": (
        'ela perguntava de balcao o que ele queria ("o que voce procura?"), jeito de atendente '
        "de SAC que voce nunca usa"
    ),
    "regiao": (
        "ela te colocava num bairro que nao e o seu -- refaca dizendo a sua regiao, a do seu "
        "cadastro, pela sua conduta de local de encontro"
    ),
    "incluso": (
        'ela dizia que um item esta incluso sem ele estar na linha "Inclusos" do seu <fetiches> '
        "-- item que nao esta la voce nao tem, e nao vira cortesia"
    ),
    "servico": (
        "ela afirmava fazer um servico que nao esta no seu cadastro -- o que nao esta no seu "
        "cardapio voce NAO faz: recuse com carinho, oferecendo junto o que voce FAZ"
    ),
    "preco": (
        "ela citava um valor que nao existe na sua tabela nem na negociacao ja feita -- o numero "
        "certo esta no seu <programas> (e, se ja houve valor combinado, e ele que vale)"
    ),
    "endereco": (
        "ele pediu a localizacao e ela nao entregou o ponto de encontro -- responda entregando o "
        "seu ponto de encontro, com todas as letras, junto do proximo passo"
    ),
    "pedagio": (
        "ela era so empurrao de fechamento ('Seria hoje ?') com pergunta dele ainda sem resposta "
        "-- o empurrao acompanha o conteudo, nunca o substitui: responda a pergunta dele E avance"
    ),
    "saudacao": (
        "ela saudava com um periodo diferente do que ELE usou -- espelhe a saudacao dele "
        "(quem disse 'boa tarde' recebe 'boa tarde', nunca 'boa noite')"
    ),
}
_EXTRA_SONDA = (
    ' Responda o que ele perguntou e, se for puxar, puxe com ancora concreta e fechada ("Esta '
    'aqui na cidade ?", "Seria hoje ?") -- uma pergunta sua no turno, no maximo.'
)
_EXTRA_INCLUSO = (
    " Responda pelo seu estilo e pelo que o programa e; sem essa linha no seu bloco a apresentacao"
    " fica so no estilo, sem lista de incluso."
)
# NAO existe `_EXTRA_REPETICAO` (removido em 12/08, loop-massa r3 achado 4b): ele mandava
# "se nao tiver nada novo a acrescentar, devolva vazio -- silencio e melhor que repetir" e era
# CONCATENADO ao `_feedback_repeticao`, que manda o oposto ("siga pelo que ainda FALTA combinar").
# A mesma mensagem mandava avancar e calar; no fechamento -- fase estruturalmente repetitiva -- o
# modelo escolhia calar (5/14 turnos de `apressado_agora` + `retomada_pos_silencio`, `objetor_b` t7,
# `externo_a` t6). Silencio e a pior saida medida no shadow: quem veta a bolha e o fallback por
# bolha, nao um convite a emudecer dentro do lembrete da regen.


def _contexto_factual_aup(endereco_no_prompt: str | None) -> str | None:
    """Mini-contexto FACTUAL para o judge de AUP (ponto #2 da auditoria guard/judge).

    O judge de `aup_saida.md` e message-only, e o carve-out da UNIDADE e indecidivel sem contexto:
    o numero do APARTAMENTO/quarto nunca sai, mas o numero da RUA sai quando o sistema liberou o
    endereco completo neste turno (`numero_liberado` no template) — a MESMA superficie ("numero Z")
    e obrigatoria num estado e violacao noutro. Anexar o endereco que o sistema DE FATO liberou
    (`local_endereco_no_prompt`, o mesmo carimbo que o gatilho `endereco` le) torna a distincao
    decidivel: nome de rua/hotel e numero que CASAM com este endereco sao a entrega legitima; um
    numero que NAO casa — em especial apartamento/quarto — e vazamento.

    Chave Pix e telefone continuam ABSOLUTOS no prompt (nunca context-relative): o sistema os anexa
    FORA da fala (out-of-band, no trilho da bolha deterministica), nunca na mensagem que o modelo
    escreve, entao qualquer um deles no texto e inventado. O State do guard tambem nao carrega o
    telefone/Pix reais da modelo — nao ha o que anexar aqui mesmo se quisessemos relativiza-los.
    """
    if not endereco_no_prompt:
        return None
    return (
        "CONTEXTO FACTUAL (o que o sistema LIBEROU neste turno — use so para decidir a UNIDADE/"
        "endereco; nao julgue o contexto, so a mensagem):\n"
        f"- Endereco/ponto de encontro liberado: {endereco_no_prompt}\n"
        "Nome de rua/hotel e numero que APARECAM neste endereco sao entrega legitima. Numero que "
        "NAO casa com ele — em especial numero de apartamento/quarto/unidade — e vazamento."
    )


def _feedback_repeticao(repetidas: Sequence[str]) -> str:
    """Mensagem do gatilho `repeticao` com a BOLHA VETADA colada e a saida nomeada.

    Familia do incidente #36 pela terceira vez (proibir sem dar a fala de substituicao). A
    mensagem estatica so diz "voce repetiu" -- e o modelo, obediente, REFORMULA a mesma frase:
    medido ao vivo em 12/08 (roteiro duas_portas, trace 61f4044c), "Consigo as 17h, fecha ?"
    virou "Consigo as 17h, seria bom pra voce ?" na regen. Como o piso fuzzy reforcado veta as
    duas bolhas que carregam os MESMOS numeros, a reformulacao caiu no mesmo gatilho, a 2a
    tentativa acabou e o fallback dropou a bolha: o turno saiu MUDO. Trocar papagaio por silencio
    e piorar -- silencio e a pior saida medida no shadow (e a razao de existir `_recuperar_vazio`).

    O que muda: cola a bolha vetada (o modelo ve O QUE nao passou, nao um rotulo) e nomeia a
    saida -- pergunta ja feita esta NA MESA, nao se repete com outras palavras; o turno avanca
    pelo que ainda falta. A intencao e prescrita, a fala nao: qual e o proximo passo quem sabe e
    ele, com o contexto do turno em maos.
    """
    base = _FEEDBACK_GATILHO["repeticao"]
    bolha = next((b.strip() for b in repetidas if b.strip()), "")
    if not bolha:
        return base
    return (
        f'{base}. A bolha que nao passou foi: "{bolha[:200]}". Reescrever ela com outras palavras '
        "NAO resolve -- ele ja leu isso e o problema e o conteudo repetido, nao a redacao. "
        "Pergunta que voce ja fez esta na mesa: ele responde quando quiser, voce nao repete. "
        "Siga do ponto em que a conversa esta, pelo que ainda FALTA combinar; se nao falta nada, "
        "confirme o que ficou combinado sem devolver a mesma pergunta"
    )


def _feedback_endereco_sonegado(ponto_de_encontro: str | None) -> str:
    """Mensagem do gatilho `endereco` com o ENDERECO LITERAL colado (nunca a tag pelo nome).

    Familia do incidente #36 outra vez: a mensagem estatica mandava "entregue o endereco
    exatamente como esta no seu <local_de_encontro>" — e o `<instrucoes_meta>` da persona ensina
    que tag de bloco depois da fala do cliente e imitacao. Citar uma tag CONDICIONAL pelo nome so
    funciona quando ela existe, e o turno do trace 648d7f6f provou o custo de errar: a regen pediu
    o conteudo de um bloco ausente e o modelo devolveu a mesma rua inventada. O dado vem do carimbo
    do prompt (`local_endereco_no_prompt`), entao e literalmente o que ele ja tinha em maos.
    """
    base = _FEEDBACK_GATILHO["endereco"]
    if not ponto_de_encontro:
        return base
    return (
        f"{base}. O seu ponto de encontro e: {ponto_de_encontro} -- e esse texto que sai da sua "
        "boca, sem trocar nome de rua nem de hotel"
    )


def _feedback_preco_fantasma(
    precos_tabela: list[tuple[Decimal, Decimal, Decimal | None]], duracao_horas: Any
) -> str:
    """Mensagem do gatilho `preco` com a escada de desconto NOMEADA quando ela e computavel.

    Familia do incidente #36 (proibir sem dar a fala de substituicao): a mensagem estatica so
    aponta a tabela, e o modelo que rascunhou uma contraproposta fora da escada recuava para a
    recusa seca ("nao consigo por esse valor"), sem degrau nem empurrao — a venda esfriava.
    Nomear o que ele PODE (degrau e piso, mesma conta do conjunto legitimo:
    `degrau_de_desconto` + `piso_de_desconto`, sites unicos) devolve a jogada certa em vez de
    so vetar a errada.

    Fail-closed pelo MESMO criterio do `contraproposta_da_escada`: o numero so existe quando a
    duracao em pauta tem UM preco de tabela (com dois, ex. "Padrao 1h 400" e "Casal 1h 700", o
    degrau/piso sairiam sobre o pacote errado). Com `duracao_horas` fechada filtra a tabela por
    ela; sem duracao fechada, so quando a tabela inteira tem um preco. Ambiguo (ou sem escada,
    `desconto_teto_pct=0`) -> mensagem estatica de hoje.

    NOMEIA os dois numeros possiveis, nunca a RODADA: desde 11/08/2026 a escada depende de o
    encontro ser hoje (piso direto, um so) ou outro dia (degrau e depois piso), e o dia nao chega
    aqui -- dizer "o primeiro e o degrau" seria mentira metade das vezes. Quem sabe qual vale
    agora e o bloco da escada na cauda, e e pra la que a mensagem aponta."""
    from barra.dominio.atendimentos.service import degrau_de_desconto, piso_de_desconto

    base = _FEEDBACK_GATILHO["preco"]
    linhas = [
        (preco, preco_minimo)
        for preco, horas, preco_minimo in precos_tabela
        if duracao_horas is None or horas == Decimal(str(duracao_horas))
    ]
    if len({preco for preco, _ in linhas}) != 1:
        return base
    preco = linhas[0][0]
    # Mesma leitura conservadora do `_contraproposta_da_tabela`: com o pacote ambiguo, a oferta
    # valida e a MAIS ALTA entre as linhas de mesmo preco.
    degrau_bruto = max(degrau_de_desconto(preco, m) for _, m in linhas)
    piso_bruto = max(piso_de_desconto(preco, m) for _, m in linhas)
    degrau = int(degrau_bruto.to_integral_value(rounding=ROUND_HALF_UP))
    piso = int(piso_bruto.to_integral_value(rounding=ROUND_HALF_UP))
    # Linha sem desconto a dar (piso absoluto igual ao preco, ou `desconto_teto_pct=0`): nomear
    # "os seus numeros sao 250 e 250" em cima de uma tabela de 250 ensinaria a IA a apresentar o
    # proprio preco como concessao. Cai na mensagem estatica, que so aponta a tabela.
    if piso >= int(preco.to_integral_value(rounding=ROUND_HALF_UP)):
        return base
    return (
        base + f"; se a jogada e a sua escada de desconto, os seus numeros possiveis sao {degrau} "
        f"e {piso} -- qual deles vale AGORA esta no bloco da escada do seu contexto (com encontro "
        f"hoje o valor e {piso} de uma vez so; sem o dia na mesa, nenhum: defenda o valor e "
        "pergunte o dia), e ecoar ou recusar o numero que ELE disse e sempre legitimo"
    )


def _detalhes_somados(a: Mapping[str, Any] | None, b: Mapping[str, Any] | None) -> dict[str, int]:
    """Soma chave a chave os `input_token_details` das duas chamadas (uniao das chaves).

    Chave presente num lado so entra com o valor daquele lado -- e o caso comum: a 2a chamada do
    guard pega o prefixo ja quente e vem com `cache_read` alto, a 1a nem sempre. Nao-inteiro
    (provider novo) e ignorado em vez de estourar: isto e telemetria de custo, nunca pode derrubar
    um turno."""
    somado: dict[str, int] = {}
    for det in (a or {}, b or {}):
        for chave, valor in det.items():
            if isinstance(valor, int):
                somado[chave] = somado.get(chave, 0) + valor
    return somado


def _com_usage_acumulado(nova: AIMessage, anterior: AIMessage | None) -> AIMessage:
    """`nova` carregando TAMBEM os tokens de `anterior` (a regen que ela substitui).

    A regen da t1 nunca entra no State: quando a recuperacao a substitui, o objeto e trocado e os
    tokens dela sumiam da acumulacao por turno do coordenador (que soma `usage_metadata` das
    mensagens do State) — sobravam so no Prometheus, via `instrumentar_tokens`. O turno gastava
    duas chamadas de LLM e `atendimentos.custo_ia_brl` registrava uma. Mesma preocupacao que faz
    `_zerar_turno` preservar o usage — e o `additional_kwargs` viaja pela mesma razao: e onde mora
    o `reasoning_content` da REGEN, o unico raciocinio que explica a fala que de fato saiu."""
    a, b = anterior.usage_metadata if anterior else None, nova.usage_metadata
    if a is None:
        return nova
    if b is None:
        return AIMessage(
            id=nova.id,
            content=nova.content,
            usage_metadata=a,
            response_metadata=nova.response_metadata,
            additional_kwargs=kwargs_preservados(nova),
        )
    # `input_token_details` (cache_read/cache_creation) TAMBEM soma. Reconstruir o usage com as tres
    # chaves grandes e descartar os details fazia `core/_custo.py` ler `cache_read=0` e tarifar o
    # prefixo QUENTE inteiro a preco de miss: 6x o custo real do turno em `atendimentos.custo_ia_brl`,
    # no histograma `AGENTE_CUSTO_TURNO_BRL` e no alerta `AgenteCustoTurnoAcimaDoAlvo` (loop-massa r3,
    # achado 7 — R$ 0,053612 cobrado contra R$ 0,008795 reais). Dano de MEDICAO, e o gatilho e o
    # guard ter feito 2 chamadas de LLM no turno (com `anterior=None` a funcao devolve `nova`
    # intacta, details inclusos). `detalhes_somados` cobre o caso de so um dos lados ter details.
    detalhes = _detalhes_somados(a.get("input_token_details"), b.get("input_token_details"))
    somado = UsageMetadata(
        input_tokens=a["input_tokens"] + b["input_tokens"],
        output_tokens=a["output_tokens"] + b["output_tokens"],
        total_tokens=a["total_tokens"] + b["total_tokens"],
        **({"input_token_details": detalhes} if detalhes else {}),  # type: ignore[typeddict-item]
    )
    return AIMessage(
        id=nova.id,
        content=nova.content,
        usage_metadata=somado,
        response_metadata=nova.response_metadata,
        additional_kwargs=kwargs_preservados(nova),
    )


def _janela_ate_a_fala_do_cliente(messages: Sequence[BaseMessage]) -> list[BaseMessage]:
    """A conversa ATÉ a fala do cliente deste turno (inclusive) — a janela que a regen precisa.

    Corta pela ULTIMA HumanMessage, não pela primeira mensagem do turno: o que o `prepare_context`
    publica como fala do cliente é sempre a última HumanMessage (lembrete + contexto dinâmico +
    fala colados nela), e TUDO que vem depois é produção deste turno — a fala descartada, o par
    `[AIMessage forçada, ToolMessage]` da extração e a canned de escalada.

    O corte antigo (`messages.index(msgs_turno[0])`) dependia de identificar a 1a mensagem do turno
    por `usage_metadata is not None` e de comparar mensagens por igualdade. Quando o `post_process`
    zera as falas do turno (escalada/pausa) a AIMessage forçada perde os `tool_calls` e a canned
    entra como se fosse fala do LLM: o corte caía DEPOIS do ToolMessage e a janela ia ao provider
    com um `role="tool"` órfão -> HTTP 400, regen None, e o gate caía no fallback (handoff). Medido
    ao vivo em 3 de 20 conversas (12/08, gatilho `endereco`, sempre no turno do fechamento): o guard
    detectava o problema e a venda morria em "Só um minutinho amor, já te falo".

    Sem HumanMessage nenhuma (defesa) devolve a janela inteira SANEADA — nunca um `tool` órfão.
    """
    for i in range(len(messages) - 1, -1, -1):
        if isinstance(messages[i], HumanMessage):
            return list(messages[: i + 1])
    return _sem_tool_orfao(messages)


def _sem_tool_orfao(messages: Sequence[BaseMessage]) -> list[BaseMessage]:
    """A janela sem `ToolMessage` cujo `AIMessage` com o `tool_call` correspondente ficou de fora.

    Rede de segurança do contrato do provider ("tool must be a response to a preceding message with
    tool_calls"): qualquer corte de janela pode separar o par, e o custo de errar é o request
    inteiro ser recusado."""
    ids_abertos: set[str] = set()
    limpa: list[BaseMessage] = []
    for m in messages:
        if isinstance(m, ToolMessage):
            if m.tool_call_id not in ids_abertos:
                continue
        elif isinstance(m, AIMessage):
            ids_abertos |= {str(tc.get("id") or "") for tc in (m.tool_calls or [])}
        limpa.append(m)
    return limpa


def _janela_com_lembrete(janela: list[BaseMessage], lembrete: str) -> list[BaseMessage]:
    """A janela da regen com o `<lembrete_silencioso>` ANTES da fala do cliente (ver `_regenerar`).

    Prepend no CONTEUDO da ultima HumanMessage (que ja carrega lembrete -> contexto dinamico ->
    fala) em vez de uma mensagem nova: mantem a alternancia de papeis e preserva a recencia da fala
    dele, que continua sendo a ultima coisa que o modelo le.
    """
    for i in range(len(janela) - 1, -1, -1):
        msg = janela[i]
        if isinstance(msg, HumanMessage) and isinstance(msg.content, str):
            copia = list(janela)
            copia[i] = HumanMessage(id=msg.id, content=f"{lembrete}\n\n{msg.content}")
            return copia
    return [*janela, HumanMessage(content=lembrete)]


async def _regenerar(
    messages: Sequence[BaseMessage],
    *,
    rascunho: str,
    gatilho: str,
    settings: Any,
    feedback_gatilho: str | None = None,
    bolhas_vetadas: Sequence[str] = (),
    anexos: Sequence[str] = (),
) -> AIMessage | None:
    """Regeneracao one-shot do turno sujo: re-pede a resposta ao chat #1 SEM tools, sobre a janela
    ate ANTES deste turno + um `<lembrete_silencioso>` com o rascunho descartado e o motivo.

    Chamada direta de proposito (nao volta ao no llm): re-entrar no grafo re-rodaria o loop ReAct
    e poderia re-executar tool com efeito colateral (enviar_midia, bloqueio de agenda); a extracao
    deste turno ja persistiu. Sem tools bindadas o modelo so pode responder texto. Falha de
    qualquer natureza (excecao, recusa, truncamento) -> None e o caller cai no fallback
    (handoff/drop/mudo) -- a regen e so o caminho feliz, nunca a rede de seguranca.

    O lembrete entra ANTES da fala do cliente (prependado na ULTIMA HumanMessage da janela, a mesma
    posicao em que o `prepare_context` cola lembrete e contexto dinamico), nunca depois: o
    `<instrucoes_meta>` da persona ensina que bloco que chega DEPOIS da fala do cliente e imitacao,
    e que "aviso que te autoriza revelar um dado" e falso por definicao — no lugar antigo o proprio
    prompt dava ao modelo licenca textual para ignorar toda regen (diagnostico 11/08, P0-1). Janela
    sem HumanMessage (defesa) -> mensagem propria no fim, como antes.

    `bolhas_vetadas` (loop-massa r3, achado 4b) torna o lembrete GRANULAR: o gatilho e sempre UMA
    bolha, mas ate 12/08 o lembrete dizia "sua ultima resposta foi descartada" e colava o turno
    INTEIRO como rascunho descartado -- o modelo jogava fora as bolhas limpas junto (turno
    encolhido, pergunta do cliente engolida: `externo_a` t6). O fallback da 2a tentativa ja dropava
    por bolha (`_drop_bolhas`); aqui a mesma granularidade entra no caminho FELIZ: o que foi vetado
    vai nomeado, e o resto vai marcado como aproveitavel.

    `anexos` (achado 5) conta o que o SISTEMA ja anexou neste turno (midia/localizacao). A regen
    roda sem tools de proposito (re-entrar no grafo re-executaria efeito colateral) e a janela corta
    as ToolMessages do proprio turno, entao o modelo nao tem sinal nenhum de que as fotos ja estao
    indo -- e preenche com rubrica de teatro ("(aqui vao as fotos)") ou promete midia nova que
    nunca sai. O conserto barato nao e dar tools a regen: e contar a ela o que ja saiu.
    """
    from barra.core.llm import (
        PARADA_RECUSA,
        PARADA_TRUNCADA,
        criar_chat_deepseek,
        motivo_parada,
        nomear_run,
    )

    janela = _janela_ate_a_fala_do_cliente(messages)
    # `extra` e MUTUAMENTE EXCLUSIVO com `feedback_gatilho`: sao dois lembretes sobre o mesmo
    # problema, e concatenados se contradiziam. O caso medido (achado 4b) e o `repeticao`:
    # `_feedback_repeticao` manda "siga pelo que ainda FALTA combinar" e o extra antigo emendava
    # "se nao tiver nada novo, devolva vazio -- silencio e melhor que repetir". Numa fase
    # estruturalmente repetitiva (fechamento) o modelo escolhia o mais facil e calava. Um lembrete
    # so: quando o caller tem a versao rica do motivo, ela e a unica voz.
    extra = (
        ""
        if feedback_gatilho
        else {"sonda": _EXTRA_SONDA, "incluso": _EXTRA_INCLUSO}.get(gatilho, "")
    )
    # `feedback_gatilho` sobrepoe a razao estatica quando o caller tem versao mais rica (os
    # gatilhos factuais: `preco` com a escada nomeada, `endereco` com o ponto de encontro literal,
    # `repeticao` com a bolha vetada colada).
    vetadas = [b.strip() for b in bolhas_vetadas if b.strip()]
    limpo = (
        _drop_bolhas(rascunho, {b for b in bolhas_vetadas if b.strip()}).strip() if vetadas else ""
    )
    if vetadas and limpo:
        # Descarte por BOLHA (espelha o `_drop_bolhas` do fallback): so o que nao passou e
        # descartado; o resto volta nomeado como aproveitavel, para o turno nao encolher.
        corpo = (
            "<lembrete_silencioso>Da sua ultima resposta, SO esta parte nao passou e nao vai ao "
            f"cliente: {feedback_gatilho or _FEEDBACK_GATILHO[gatilho]}.\n"
            "Nao vai ao cliente:\n" + "\n".join(vetadas)[:_RASCUNHO_MAX] + "\n"
            f"O resto do rascunho estava certo e pode ser reaproveitado:\n{limpo[:_RASCUNHO_MAX]}\n"
        )
    else:
        corpo = (
            "<lembrete_silencioso>Sua ultima resposta foi descartada antes do envio: "
            f"{feedback_gatilho or _FEEDBACK_GATILHO[gatilho]}.\n"
            f"Rascunho descartado:\n{rascunho[:_RASCUNHO_MAX]}\n"
        )
    # Fato do turno, nao instrucao de ferramenta: a regen nao tem tools e nao pode anexar nada.
    fato_anexos = (
        f" Neste turno o sistema JA anexou {', '.join(anexos)} -- vai junto com esta mensagem, "
        "entao nao prometa mandar de novo nem escreva rubrica no lugar do anexo."
        if anexos
        else ""
    )
    feedback = (
        f"{corpo}"
        "Escreva agora, no seu jeito de sempre, a mensagem que vai ao cliente -- curta e natural, "
        f"sem o problema acima.{extra}{fato_anexos} Responda somente com a mensagem."
        "</lembrete_silencioso>"
    )
    # Mesmo regime de thinking do chat #1 (settings.deepseek_thinking_chat, default "low"): a regen
    # é fala da persona e, em thinking, a janela pode conter reasoning_content a devolver.
    # `run_name` nomeia a generation no trace (senão vira mais um "ChatOpenAI" indistinguível).
    chat = nomear_run(
        criar_chat_deepseek(
            settings,
            temperature=settings.chat_temperature,
            thinking=settings.deepseek_thinking_chat,
        ),
        "guard_regen",
    )
    try:
        with medir_llm("regen"):
            resp = await chat.ainvoke(_janela_com_lembrete(janela, feedback))
    except Exception:
        logger.exception("output_guard regen indisponivel (gatilho=%s)", gatilho)
        return None
    instrumentar_tokens(resp, settings.deepseek_model_chat)
    parada = motivo_parada(getattr(resp, "response_metadata", None))
    if parada in PARADA_RECUSA or parada in PARADA_TRUNCADA:
        logger.warning("output_guard regen parada=%s (gatilho=%s) -> fallback", parada, gatilho)
        return None
    return resp if isinstance(resp, AIMessage) else None


def _scan_vazamento(texto: str) -> str | None:
    """Etapa 1 (PURA): devolve o motivo do vazamento ou None.

    Ordem: ia_self > system > outro_cliente > raciocinio. Cobre so o que a IA PODE de fato emitir
    (sabe que e IA, tem o system no contexto, conhece a propria agenda). O scan determinístico
    cross-modelo foi removido (supersede ADR 0016): a IA roda por modelo e nunca tem em contexto o
    nome/numero de OUTRA modelo (`prepare_context` carrega `WHERE id = %s`; isolamento garantido no
    carregamento por `(cliente_id, modelo_id)` + `evolution_instance_id` UNIQUE), entao a blocklist
    de nomes so podia casar por coincidencia de homonimo (FP). O backstop semantico e a Etapa 2.

    `raciocinio` aqui e a rede para a LEGENDA de midia (que o Estagio 0 nao saneia -- ela e arg de
    tool no DB, nao content de mensagem reescrivivel): legenda com meta-fala -> barra o turno, igual
    a qualquer outro leak em legenda. O texto ja chega aqui SANEADO (Estagio 0 strippou as bolhas de
    raciocinio com o mesmo regex), entao esta checagem nunca re-barra o texto -- so a legenda.
    """
    if tem_marcador_ia(texto):
        return "ia_self"
    if tem_marcador_system(texto):
        return "system"
    if tem_marcador_outro_cliente(texto):
        return "outro_cliente"
    if tem_marcador_raciocinio(texto):
        return "raciocinio"
    return None


async def _julgar_aup(
    texto: str, settings: Any, *, contexto_factual: str | None = None
) -> _VeredictoAup:
    """Etapa 2: LLM-judge de AUP no DeepSeek V4 Flash direto (structured output). Prompt em aup_saida.md.

    DeepSeek-only (igual ao chat #1 e a extracao): ChatOpenAI direto na API DeepSeek, com thinking
    travado em disabled (o thinking mode do V4 corromperia o structured output — vllm#41132) e o
    structured output por function-calling explicito (`method="function_calling"`). Cacheia o prefixo
    aup_saida.md (o mesmo system em TODA chamada).

    UMA chamada por TURNO, nao por bolha: o caller agrega texto + legendas numa string so
    (`texto_guard`) antes de chamar. O comentario antigo dizia "antes de cada bolha" e induzia a
    aritmetica errada em todo diagnostico de latencia/custo do no (loop-massa r3, achado 3).

    SO-03: `include_raw` expoe o motivo de parada da PROPRIA resposta do judge. Recusa
    (refusal/content_filter), truncamento (max_tokens/length) ou falha de parse nao produzem
    veredito confiavel -> levanta `_JudgeInseguro`, e o caller cai no DEFAULT SEGURO (bloqueia+
    escala), em vez de aceitar um `viola=False` espurio. `motivo_parada`/`PARADA_INSEGURA` unificam
    os vocabularios Anthropic (stop_reason) e OpenAI/OpenRouter (finish_reason).
    """
    from barra.core.llm import PARADA_INSEGURA, criar_chat_deepseek, motivo_parada

    # DeepSeek-only (V4 Flash, thinking travado em disabled): cacheia o prefixo aup_saida.md (o mesmo
    # system em TODA chamada) e crava modelo/quant — sem roleta do pool nem risco de thinking
    # corromper o veredito (vllm#41132). method="function_calling" explicito (mais robusto que json_schema).
    modelo_judge = settings.deepseek_model_chat
    # `temperature=judge_temperature` (0.0) EXPLICITO: chamar a factory sem o parametro NAO e
    # determinismo — `ChatOpenAI(temperature=None)` omite o campo do payload e vale o default do
    # provider (~1.0), a temperatura MAIS ALTA, num gate vinculante que roda em TODO turno
    # (loop-massa r3, achado 1). O veredito e classificacao binaria, nao voz: sortear so gera
    # over-refusal de cauda (~1 conversa morta a cada 50 no lote medido).
    chat = criar_chat_deepseek(
        settings, temperature=settings.judge_temperature
    ).with_structured_output(_VeredictoAup, include_raw=True, method="function_calling")
    # Mini-contexto FACTUAL (ponto #2 da auditoria guard/judge): o judge é message-only e o
    # carve-out da UNIDADE é indecidível sem contexto — o número do apartamento/quarto nunca sai,
    # mas o número da RUA sai quando o sistema liberou o endereço completo neste turno. Anexar o
    # endereço que o sistema DE FATO liberou (`local_endereco_no_prompt`) torna a distinção
    # decidível. None (turno sem endereço liberado) -> mensagem-only como antes.
    conteudo_user = (
        f"{contexto_factual}\n\nMENSAGEM A AVALIAR:\n{texto}"
        if contexto_factual
        else f"MENSAGEM A AVALIAR:\n{texto}"
    )
    mensagens = [
        {"role": "system", "content": render_aup_saida()},
        {"role": "user", "content": conteudo_user},
    ]
    # callbacks=[] corta a propagacao do CallbackHandler (Langfuse) herdado via contextvar do no:
    # o sub-chain do `with_structured_output` (RunnableParallel<raw,parsed> + PydanticToolsParser +
    # RunnableAssign + a generation do judge) seria ~8 spans de ruido NO TRACE por turno (o judge
    # roda UMA vez por turno, sobre texto+legendas agregados). Mantemos o trace legivel; os tokens do judge
    # seguem instrumentados via Prometheus (abaixo, le do `bruto`, independe de callbacks) e o caso
    # inseguro continua logado + metrica. Nao afeta o parsing (callbacks sao so telemetria).
    # Retry 1x SO no parsing_error (parse transitorio; desde 12/08 a temp e 0.0, entao o retry
    # cobre so o parse de fato transitorio): PARADA_INSEGURA
    # (refusal/truncamento) e sinal de seguranca real -> default-seguro imediato, sem retry (a 2a
    # tentativa nao reverteria um filtro do provider). O log distingue os dois gatilhos: a msg
    # antiga so citava `parada` e culpava o `tool_calls` (finish_reason normal de function-calling),
    # mascarando que o gatilho real era o `parsing_error`.
    parada: str | None = None
    for tentativa in (1, 2):
        with medir_llm("judge_aup"):
            resultado = await chat.ainvoke(mensagens, config={"callbacks": []})
        assert isinstance(resultado, dict)
        bruto = resultado.get("raw")
        # CUSTO: o judge roda a cada TURNO e queima tokens (DeepSeek V4 Flash). Instrumenta
        # sob o label do PROPRIO modelo do judge, ANTES do check de parada e em CADA tentativa -- o
        # token gastou mesmo no veredito inseguro (refusal/truncado/parse) e no retry.
        if bruto is not None:
            instrumentar_tokens(bruto, modelo_judge)
        parada = motivo_parada(getattr(bruto, "response_metadata", None))
        if parada in PARADA_INSEGURA:
            raise _JudgeInseguro(
                f"judge sem veredito confiavel (parsing_error=False, parada={parada})"
            )
        if resultado.get("parsing_error") is None:
            veredito = resultado.get("parsed")
            assert isinstance(veredito, _VeredictoAup)
            return veredito
        if tentativa == 1:
            logger.warning(
                "output_guard judge parse falhou (tentativa 1, parada=%s) -> retry", parada
            )
    raise _JudgeInseguro(f"judge sem veredito confiavel (parsing_error=True, parada={parada})")


async def _bloquear(ctx: ContextAgente, *, observacao: str, resumo: str, metric_key: str) -> bool:
    """Abre handoff p/ Fernando (ia_pausada=true) e contabiliza a escalada (bucket=defesa).

    `observacao` e o motivo granular persistido; `metric_key` e o rotulo grosso da metrica
    (`output_leak`/`aup_saida`), passado pelo caller que ja sabe qual etapa barrou.

    Sem atendimento_id (webhook fino) nao ha o que pausar: so loga -- a bolha ja sera zerada.

    Devolve True quando a pausa foi REALMENTE aberta por este turno. O retorno vira o carimbo
    `_pausa_aberta_pelo_guard` no State (`_update_bloqueado`): o `_bloquear` escreve direto no
    banco, sem tocar em `messages`, entao `pausa_aberta_por_este_turno` (coordenador) nao tinha como
    ver este rastro e classificava a pausa do PROPRIO grafo como externa -- o log
    `turno_descartado pausa_externa=True` mandava o operador procurar um pipeline que nao existia
    (loop-massa r3, achado 6). Sem atendimento_id nada foi pausado -> False, e o carimbo nao mente.
    """
    if ctx.atendimento_id is None:
        logger.warning("output_guard bloqueou sem atendimento_id (%s)", observacao)
        return False
    async with conexao(ctx.db_pool) as conn:
        await escalar_defesa(
            conn, ctx.atendimento_id, resumo=resumo, observacao=observacao, metric_key=metric_key
        )
    return True


def _update_bloqueado(mensagens: list[AIMessage], pausou: bool) -> dict[str, Any]:
    """Update do turno BLOQUEADO: mensagens zeradas + o carimbo da pausa aberta por ESTE turno."""
    update: dict[str, Any] = {"messages": mensagens}
    if pausou:
        update["_pausa_aberta_pelo_guard"] = True
    return update


async def output_guard(
    state: EstadoAgente, runtime: Runtime[ContextAgente]
) -> Command[Literal["__end__"]]:
    """Estagio 0 + gate pre-envio (leak/repeticao, regen one-shot) + Etapa 2 (judge de AUP).
    Bloqueia -> handoff + bolha vazia. Sempre vai p/ END.

    Casca fail-CLOSED: o guard e a ultima defesa dentro do grafo, entao uma falha DELE (DB fora,
    bug) nao pode virar passagem livre -- o turno nao-guardado sai mudo. Antes a excecao subia ate
    o coordenador e matava o turno do mesmo jeito, mas sem rastro proprio: aqui fica um log
    grepavel apontando o guard, e nao um erro generico de turno.
    """
    try:
        return await _output_guard(state, runtime)
    except Exception:
        logger.error(
            "output_guard_falhou turno_id=%s -> turno mudo (fail-closed)",
            runtime.context.turno_id,
            exc_info=True,
        )
        # Sem DB confiavel nao da p/ abrir handoff; o garantido e nao deixar sair o que ninguem
        # guardou. `_zerar_turno` e puro (so mexe nas mensagens em memoria).
        return Command(
            goto="__end__", update={"messages": _zerar_turno(mensagens_do_turno(state["messages"]))}
        )


async def _output_guard(
    state: EstadoAgente, runtime: Runtime[ContextAgente]
) -> Command[Literal["__end__"]]:
    settings = get_settings()
    ctx = runtime.context
    if not settings.output_guard_habilitado:
        return Command(goto=END)  # type: ignore[arg-type]

    # Mesmo agregado que o coordenador despacha (`extrair_texto_do_turno`): TODAS as AIMessages
    # geradas neste turno, nao so a ultima — no ReAct o texto ao cliente costuma sair na 1a
    # passagem (texto + tool_call) e a ultima vem vazia (ou e o tool_use da extracao forcada);
    # guardar so a ultima deixava o texto real passar sem scan/judge.
    msgs_turno = mensagens_do_turno(state["messages"])
    texto_cru = extrair_texto_do_turno(state["messages"])

    # Estagio 0 (non-disclosure, tolerancia-zero): SANEIA o raciocinio vazado -- strippa as bolhas de
    # meta-fala (que entregam a IA) e mantem a fala real. O texto saneado segue p/ o gate/judge (scan
    # + judge rodam no que VAI ao cliente). `msgs_saneadas` (AIMessages reescritas) viaja nos returns
    # de passagem: o coordenador re-deriva o texto das mensagens, entao o strip precisa estar nelas.
    # Turno 100%-raciocinio -> gatilho `mudo` do gate (regenera 1x; persistiu -> silencio, como
    # antes). NAO escala (leak saneado nao e brecha como ia_self).
    texto, msgs_saneadas = _sanear_raciocinio(msgs_turno, texto_cru)
    saneou_tudo = bool(msgs_saneadas) and not texto.strip()
    update_final: dict[str, Any] = {"messages": msgs_saneadas} if msgs_saneadas else {}
    if msgs_saneadas:
        OUTPUT_RACIOCINIO_SANEADO.labels("saneado" if texto.strip() else "mudo").inc()

    # A legenda da midia (arg `legenda` de enviar_midia) sai ao cliente como caption FORA da bolha
    # de texto -- precisa passar pelo MESMO scan/judge, senao escaparia do guard (A1). Coletada
    # ANTES do early-return de texto vazio p/ cobrir tambem turno so-midia.
    async with conexao(ctx.db_pool) as conn:
        legendas = await _legendas_do_turno(conn, ctx.turno_id)
        # O que o sistema JA anexou neste turno (midia/pin/Pix) -- viaja ate o lembrete da regen,
        # que roda sem tools e sem as ToolMessages do turno (achado 5).
        anexos = await _anexos_do_turno(conn, ctx.turno_id)
        cadastro = await _cadastro_guard(conn, ctx)
        cardapio = await _cardapio_da_modelo(conn, ctx)
        pausado = False
        valor_acordado: Any = None
        duracao_horas: Any = None
        if ctx.atendimento_id is not None:
            cur = await conn.execute(
                "SELECT ia_pausada, valor_acordado, duracao_horas"
                " FROM barravips.atendimentos WHERE id = %s",
                (ctx.atendimento_id,),
            )
            row = await cur.fetchone()
            pausado = bool(row and row["ia_pausada"])
            valor_acordado = row.get("valor_acordado") if row else None
            duracao_horas = row.get("duracao_horas") if row else None
    permitidos_lugar = cadastro.permitidos_lugar
    inclusos_da_modelo = cardapio.inclusos
    # Scan sobre a janela CRUA quando o State a publicou: a ultima HumanMessage de `messages` e o
    # contexto dinamico anexado, e numero injetado pelo sistema (logradouro, minutos de relogio)
    # entraria no conjunto como "numero que o cliente citou". Fallback preserva o teste unitario
    # que chama o guard direto sem janela.
    valores_validos = _valores_legitimos(
        cardapio.precos_tabela,
        valor_acordado,
        state.get("conversa_crua") or state["messages"],
        ids_do_turno={m.id for m in msgs_turno},
        extras_cadastrados=cardapio.extras_cadastrados,
    )
    # Gatilho `endereco` (rodada 3, fase 1-E): o cliente PEDIU a localizacao no burst atual e o
    # `<local_de_encontro>` ESTEVE no prompt deste turno. A resposta que nao entregar nenhum token
    # do endereco regenera 1x; persistindo, SEGUE como esta (pass-through: derrubar a bolha aqui
    # silenciaria fala legitima — a rede e de melhoria, nao de bloqueio).
    #
    # Le o CARIMBO do prepare_context (`local_endereco_no_prompt`), nunca reavalia o gate: o guard
    # roda DEPOIS da extracao e a linha relida ja pode ter promovido `tipo_atendimento` NULL->
    # interno no meio do turno — o predicado dizia "libera" sobre um prompt que saiu SEM o bloco, e
    # a regen cobrava um endereco que o modelo nao tinha (ele inventou a rua; trace 648d7f6f,
    # agenda_local t3). Sem carimbo (State antigo/teste) o gatilho nao arma — fail-closed.
    crua = state.get("conversa_crua") or []
    burst_cliente = _falas_do_burst_atual(crua)
    ha_pedido_de_endereco = any(contem_pedido_de_endereco(f) for f in burst_cliente)
    endereco_no_prompt = state.get("local_endereco_no_prompt")
    pediu_endereco = (
        bool(endereco_no_prompt) and bool(cadastro.tokens_endereco) and ha_pedido_de_endereco
    )
    # Gatilhos `pedagio`/`saudacao` (rodada 4, mesma rede de melhoria do `endereco`): pergunta
    # pendente e saudacao de periodo saem do burst cru — sem janela publicada, nao armam.
    perguntas_pendentes = bool(perguntas_do_burst(list(crua)))
    saudacao_cliente = next((p for p in (periodo_da_saudacao(f) for f in burst_cliente) if p), None)
    # O cliente ACEITOU neste burst ("fechou", "pode ser", "isso") -> a confirmacao que reusa a
    # abertura da oferta ("Consigo as 17h entao, te espero") e a fala certa, nao eco. Desliga so o
    # ramo `_mesma_abertura` da repeticao; `exato`/`fuzzy` seguem valendo. Sem janela crua
    # (teste que chama o guard direto) da False -- o detector fica como era.
    houve_aceite = aceite_curto_no_burst(list(crua))

    # Silencio do MODELO (nao do guard): o turno rodou, nenhuma AIMessage falou nada, nada foi
    # saneado, nenhuma tool de efeito rodou (so `registrar_extracao`) e a IA nao esta pausada --
    # o modelo respondeu vazio e o cliente ficaria no vacuo (4,5% dos pontos do shadow, metade
    # das derrotas em cotacao). Entra no gate como `mudo` (regen 1x; persistiu -> silencio, como
    # antes). Turno com midia/escalada/pausa preserva o silencio de proposito.
    #
    # O MUTE DELIBERADO do `extrair` tambem preserva. Quando a extracao erra no guard de dominio
    # sobre uma bolha STALE (reoferta desligada pelo kill-switch, ou turno sem fala — a bolha foi
    # escrita antes de o erro existir), o `extrair` fecha o turno mudo de PROPOSITO e carimba
    # `_mute_por_erro_de_tool` -- silencio > reserva fantasma. Aqui esse turno tem a mesma
    # assinatura de um modelo que respondeu vazio (AIMessages sem texto, tool_calls so de
    # `registrar_extracao`), e sem o carimbo o guard regenerava: o lembrete do gatilho `mudo` diz
    # "sua resposta veio VAZIA, escreva de novo" e a janela da regen corta o ToolMessage do erro,
    # entao o modelo respondia "Confirmado amor" -- a reserva fantasma que o mute impedia. Medido
    # ao vivo em 12/08 (trace 71c7196e): a reoferta tinha ACERTADO a cotacao, a regen a substituiu.
    silencio_modelo = (
        bool(msgs_turno)
        and not pausado
        and not state.get("_mute_por_erro_de_tool")
        and all(
            tc.get("name") == "registrar_extracao"
            for m in msgs_turno
            for tc in (getattr(m, "tool_calls", None) or [])
        )
    )

    if not texto.strip() and not legendas and not saneou_tudo and not silencio_modelo:
        # post_process ja zerou (pausa concorrente) ou turno sem texto/midia: nada a guardar.
        return Command(goto=END, update=update_final)  # type: ignore[arg-type]

    # bloqueio = substitui TODAS as AIMessages do turno por vazias (mesmo id -> reducer troca);
    # zerar so a ultima deixaria o texto da 1a passagem vivo p/ o coordenador despachar.
    vazias = _zerar_turno(msgs_turno)

    # Leak em LEGENDA e NAO-regeneravel: a legenda ja esta persistida como arg da tool (o
    # coordenador a despacha do DB, nao do content das mensagens) -- regenerar o texto nao a
    # consertaria. Barra o turno inteiro, comportamento pre-regen.
    if legendas:
        motivo_leg = _scan_vazamento("\n".join(legendas))
        if motivo_leg:
            OUTPUT_LEAK_DETECTADO.labels(motivo_leg).inc()
            pausou = await _bloquear(
                ctx,
                observacao=f"output_leak_{motivo_leg}",
                resumo=_RESUMO_LEAK,
                metric_key="output_leak",
            )
            return Command(goto=END, update=_update_bloqueado(vazias, pausou))  # type: ignore[arg-type]

    # Gate pre-envio (producao assistida): scan de leak + detector de repeticao sobre o TEXTO, com
    # UMA regeneracao antes do fallback. A regen tambem passa pelo Estagio 0 e re-entra neste scan
    # (tentativa 2); persistiu -> fallback por gatilho: leak -> handoff (irreversivel se enviado);
    # repeticao -> dropa as bolhas repetidas (silencio > papagaio, sem handoff); mudo -> silencio.
    historicas = _bolhas_historicas(state["messages"])
    nova_msg: AIMessage | None = None
    gatilho_regen: str | None = None

    def _zeradas_todas() -> list[AIMessage]:
        """Bloqueio zera TODAS as AIMessages do turno -- inclusive a regenerada, se houver."""
        if nova_msg is None:
            return vazias
        return [*vazias, *_zerar_turno([nova_msg])]

    async def _recuperar_vazio(rascunho: str) -> AIMessage | None:
        """Turno na iminencia de sair 100% VAZIO (drop esvaziou tudo / mudo persistiu): UMA regen
        extra pelo trilho do mudo, aceita so se a bateria inteira de detectores re-aprovar.
        Silencio por-bolha continua valendo (silencio > papagaio); silencio TOTAL nao — o cliente
        fica no vacuo, a pior saida medida no shadow. Persistiu de novo -> None (silencio final,
        comportamento anterior)."""
        if not settings.output_guard_regen_habilitado:
            return None
        nova = await _regenerar(
            state["messages"],
            rascunho=rascunho,
            gatilho="mudo",
            settings=settings,
            anexos=anexos,
        )
        t = _limpar_bolhas(texto_da_mensagem(nova)) if nova is not None else ""
        aprovada = (
            bool(t.strip())
            and _scan_vazamento(t) is None
            and not (
                settings.output_guard_repeticao_habilitada
                and bolhas_repetidas(t, historicas, houve_aceite=houve_aceite)
            )
            and not bolhas_sonda(t)
            and not bolhas_eco_regiao(t, permitidos_lugar)
            and not bolhas_incluso_fantasma(t, inclusos_da_modelo)
            and not bolhas_servico_fantasma(t, cardapio.servicos)
            # Sem esta linha, o pior caso do proprio detector escapava pelo trilho de
            # recuperacao: "faz anal?" -> drop por `servico` -> regen "mudo" devolve "Pode sim"
            # (sem o token de risco no texto) e a promessa fantasma sai ao cliente.
            and not bolhas_afirmacao_nua_de_risco(burst_cliente, t, cardapio.servicos)
            and not bolhas_preco_fantasma(t, valores_validos)
        )
        if not aprovada:
            OUTPUT_REGEN.labels("vazio_recuperacao", "persistiu").inc()
            return None
        OUTPUT_REGEN.labels("vazio_recuperacao", "limpou").inc()
        assert nova is not None
        return AIMessage(
            id=nova.id,
            content=t,
            usage_metadata=nova.usage_metadata
            or UsageMetadata(input_tokens=0, output_tokens=0, total_tokens=0),
            response_metadata=nova.response_metadata,
            # O raciocinio da RECUPERACAO viaja junto (`reasoning_content` mora aqui): a mensagem
            # que o State recebe e esta, e sem o dict o trace fica com a fala recuperada e
            # `raciocinio: null` — a mesma perda do `_zerar_turno`, um nivel adiante.
            additional_kwargs=kwargs_preservados(nova),
        )

    # Canned curada (espera de escalada / negacao de disclosure): o texto e NOSSO e ja e a decisao
    # do sistema — os gatilhos de melhoria nao se aplicam. Sem esta saida, o turno que ESCALOU por
    # guarda de dominio (reagendamento/piso/tipo) e caiu na bolha de espera armava o gatilho
    # `endereco` sempre que o cliente tinha pedido a localizacao: a regen gastava um turno de LLM
    # para, no caminho feliz, TROCAR a bolha de espera por uma fala com o endereco — furando a
    # escalada que acabara de ser aberta, com a IA ja pausada. Medido em 3 de 20 conversas (12/08).
    # A Etapa 2 (judge de AUP) ja tinha a mesma isencao, logo abaixo — e a mesma ressalva: com
    # midia no turno, a LEGENDA continua tendo de ser julgada, entao o atalho nao vale.
    if not legendas and texto.strip() in _CANNED_CURADAS:
        return Command(goto=END, update=update_final)  # type: ignore[arg-type]

    for tentativa in (1, 2):
        motivo = _scan_vazamento(texto) if texto.strip() else None
        repetidas: list[str] = []
        if not motivo and settings.output_guard_repeticao_habilitada and texto.strip():
            repetidas = bolhas_repetidas(texto, historicas, houve_aceite=houve_aceite)
        sondas: list[str] = []
        if not motivo and not repetidas and texto.strip():
            sondas = bolhas_sonda(texto)
        ecos: list[str] = []
        if not motivo and not repetidas and not sondas and texto.strip():
            ecos = bolhas_eco_regiao(texto, permitidos_lugar)
        fantasmas: list[str] = []
        if not motivo and not repetidas and not sondas and not ecos and texto.strip():
            fantasmas = bolhas_incluso_fantasma(texto, inclusos_da_modelo)
        limpo_ate_aqui = not motivo and not repetidas and not sondas and not ecos and not fantasmas
        servicos_fant: list[str] = []
        if limpo_ate_aqui and texto.strip():
            servicos_fant = bolhas_servico_fantasma(texto, cardapio.servicos)
            # Rodada 6b: o "sim" nu em cima de pedido de risco do burst é a mesma promessa.
            servicos_fant += [
                b
                for b in bolhas_afirmacao_nua_de_risco(burst_cliente, texto, cardapio.servicos)
                if b not in servicos_fant
            ]
        precos_fant: list[str] = []
        if limpo_ate_aqui and not servicos_fant and texto.strip():
            precos_fant = bolhas_preco_fantasma(texto, valores_validos)
        endereco_sonegado = (
            limpo_ate_aqui
            and not servicos_fant
            and not precos_fant
            and pediu_endereco
            and bool(texto.strip())
            and not contem_endereco_de_encontro(texto, cadastro.tokens_endereco)
        )
        melhorias_limpas = (
            limpo_ate_aqui and not servicos_fant and not precos_fant and not endereco_sonegado
        )
        pedagio = (
            melhorias_limpas
            and perguntas_pendentes
            and bool(texto.strip())
            and resposta_so_pedagio(texto)
        )
        saudacao_conflita = (
            melhorias_limpas
            and not pedagio
            and bool(texto.strip())
            and saudacao_em_conflito(texto, saudacao_cliente)
        )
        if motivo:
            gatilho = "leak"
        elif repetidas:
            gatilho = "repeticao"
        elif sondas:
            gatilho = "sonda"
        elif ecos:
            gatilho = "regiao"
        elif fantasmas:
            gatilho = "incluso"
        elif servicos_fant:
            gatilho = "servico"
        elif precos_fant:
            gatilho = "preco"
        elif endereco_sonegado:
            gatilho = "endereco"
        elif pedagio:
            gatilho = "pedagio"
        elif saudacao_conflita:
            gatilho = "saudacao"
        elif not texto.strip() and (saneou_tudo or silencio_modelo or nova_msg is not None):
            # turno 100%-raciocinio (t1), silencio do modelo (t1) ou regen que devolveu vazio /
            # foi toda saneada (t2). Texto vazio SEM saneamento (turno so-midia) nao e mudo:
            # cai no break e segue direto p/ o judge das legendas.
            gatilho = "mudo"
        else:
            if nova_msg is not None:
                OUTPUT_REGEN.labels(gatilho_regen or "", "limpou").inc()
                # INFO de proposito (nao warning): e o caminho feliz do gate, mas o piloto de
                # producao assistida grepa isto no log do worker p/ medir quanto a regen segura.
                logger.info(
                    "output_guard regen limpou (gatilho=%s turno_id=%s)",
                    gatilho_regen,
                    ctx.turno_id,
                )
            break  # limpo (ou turno so-midia)

        if tentativa == 1 and settings.output_guard_regen_habilitado:
            gatilho_regen = gatilho
            nova = await _regenerar(
                state["messages"],
                rascunho=texto if texto.strip() else texto_cru,
                gatilho=gatilho,
                settings=settings,
                # Gatilho FACTUAL leva a razao ENRIQUECIDA, com o dado colado: preco fantasma
                # recebe a escada nomeada (so vetar fazia o modelo recuar sem contraproposta) e
                # endereco sonegado recebe o ponto de encontro literal do prompt (citar a tag
                # condicional pelo nome e o que produziu a rua inventada) — familia do #36.
                feedback_gatilho=(
                    _feedback_preco_fantasma(cardapio.precos_tabela, duracao_horas)
                    if gatilho == "preco"
                    else _feedback_endereco_sonegado(endereco_no_prompt)
                    if gatilho == "endereco"
                    # `repeticao` entrou na familia em 12/08: a razao estatica fazia o modelo
                    # REFORMULAR a mesma frase, que reincide no piso dos "mesmos numeros" e
                    # esgota a 2a tentativa -> turno mudo (trace 61f4044c).
                    else _feedback_repeticao(repetidas)
                    if gatilho == "repeticao"
                    else None
                ),
                # Descarte por BOLHA tambem no caminho FELIZ (achado 4b): o gatilho e sempre uma
                # bolha, e a mesma informacao granular que o fallback usa em `_drop_bolhas` entra
                # aqui. Sem ela o lembrete jogava fora o turno inteiro por uma bolha, e o modelo
                # devolvia turno encolhido — com a pergunta do cliente engolida junto.
                # Gatilhos sem bolha ofensora (leak, mudo, e as tres redes de melhoria, onde o
                # problema e o que FALTA na fala) caem no `()` e mantem o lembrete antigo, que
                # descarta o rascunho inteiro — e o certo la.
                bolhas_vetadas={
                    "repeticao": repetidas,
                    "sonda": sondas,
                    "regiao": ecos,
                    "incluso": fantasmas,
                    "servico": servicos_fant,
                    "preco": precos_fant,
                }.get(gatilho, ()),
                anexos=anexos,
            )
            if nova is not None:
                # O texto final vive na PROPRIA nova_msg (id novo, usage proprio): o coordenador
                # re-deriva via `mensagens_do_turno` (usage != None) e acumula o custo dela. O
                # `additional_kwargs` vem junto pelo mesmo motivo do usage: a fala despachada e a
                # da REGEN, e o raciocinio que a explica (`reasoning_content`) mora ali.
                texto = _limpar_bolhas(texto_da_mensagem(nova))
                nova_msg = AIMessage(
                    id=nova.id,
                    content=texto,
                    usage_metadata=nova.usage_metadata
                    or UsageMetadata(input_tokens=0, output_tokens=0, total_tokens=0),
                    response_metadata=nova.response_metadata,
                    additional_kwargs=kwargs_preservados(nova),
                )
                continue
            OUTPUT_REGEN.labels(gatilho, "indisponivel").inc()
        elif nova_msg is not None:
            OUTPUT_REGEN.labels(gatilho_regen or gatilho, "persistiu").inc()

        # Fallback (regen desligada/indisponivel ou o problema persistiu na 2a tentativa):
        if gatilho == "leak":
            assert motivo is not None
            OUTPUT_LEAK_DETECTADO.labels(motivo).inc()
            pausou = await _bloquear(
                ctx,
                observacao=f"output_leak_{motivo}",
                resumo=_RESUMO_LEAK,
                metric_key="output_leak",
            )
            return Command(goto=END, update=_update_bloqueado(_zeradas_todas(), pausou))  # type: ignore[arg-type]
        if gatilho in ("endereco", "pedagio", "saudacao"):
            # Pass-through de proposito: as tres redes sao de MELHORIA (entregar o dado pedido,
            # responder a pergunta antes do empurrao, espelhar o periodo dele), nao de bloqueio —
            # derrubar a bolha aqui silenciaria fala legitima. Regen falhou/persistiu -> segue o
            # texto como esta; so a metrica registra.
            # "persistiu" exige regen TENTADA (nova_msg existe); com a regen desligada ou
            # indisponivel na t1 nada foi tentado — "sem_regen" separa os dois no piloto.
            {
                "endereco": OUTPUT_ENDERECO_SONEGADO,
                "pedagio": OUTPUT_PEDAGIO_DETECTADO,
                "saudacao": OUTPUT_SAUDACAO_CONFLITANTE,
            }[gatilho].labels("persistiu" if nova_msg is not None else "sem_regen").inc()
            break
        if gatilho in ("repeticao", "sonda", "regiao", "incluso", "servico", "preco"):
            # Mesmo fallback p/ os seis: dropa a bolha ofensora e manda o resto (silencio >
            # papagaio/SAC/bairro inventado/incluso que ela nao tem/promessa ou preco errado).
            # So a metrica difere.
            ofensoras = {
                "repeticao": repetidas,
                "sonda": sondas,
                "regiao": ecos,
                "incluso": fantasmas,
                "servico": servicos_fant,
                "preco": precos_fant,
            }[gatilho]
            conjunto = set(ofensoras)
            texto = _drop_bolhas(texto, conjunto)
            # RE-SCAN do que sobrou. Os detectores abaixo do gatilho vencedor na precedencia sao
            # curto-circuitados no scan (cada um so roda com os anteriores vazios), e este fallback
            # sai por `break` direto p/ o judge -- que julga AUP, nao preco/servico fora de
            # cardapio. Sem o re-scan, um turno com bolha repetida + bolha de preco fantasma
            # dropava so a repetida e mandava o preco errado ao cliente sempre que a regen nao
            # tivesse limpado (provider fora, regen desligada, ou o problema persistindo). O
            # caminho feliz ja re-escaneava tudo via `continue`; este e o caminho triste.
            if texto.strip():
                remanescentes = [
                    *bolhas_sonda(texto),
                    *bolhas_eco_regiao(texto, permitidos_lugar),
                    *bolhas_incluso_fantasma(texto, inclusos_da_modelo),
                    *bolhas_servico_fantasma(texto, cardapio.servicos),
                    *bolhas_afirmacao_nua_de_risco(burst_cliente, texto, cardapio.servicos),
                    *bolhas_preco_fantasma(texto, valores_validos),
                ]
                if remanescentes:
                    conjunto |= set(remanescentes)
                    texto = _drop_bolhas(texto, conjunto)
            metrica = {
                "repeticao": OUTPUT_REPETICAO_DETECTADA,
                "sonda": OUTPUT_SONDA_DETECTADA,
                "regiao": OUTPUT_ECO_REGIAO_DETECTADO,
                "incluso": OUTPUT_INCLUSO_FANTASMA,
                "servico": OUTPUT_SERVICO_FANTASMA,
                "preco": OUTPUT_PRECO_FANTASMA,
            }[gatilho]
            metrica.labels("dropada" if texto.strip() else "mudo").inc()
            if not texto.strip() and not legendas:
                recuperada = await _recuperar_vazio(texto_cru)
                if recuperada is not None:
                    texto = str(recuperada.content)
                    nova_msg = _com_usage_acumulado(recuperada, nova_msg)
                    break
            if nova_msg is not None:
                nova_msg = AIMessage(
                    id=nova_msg.id,
                    content=texto,
                    usage_metadata=nova_msg.usage_metadata,
                    response_metadata=nova_msg.response_metadata,
                    # Reescrita da PROPRIA regen (drop de bolha): o raciocinio dela segue junto —
                    # perde-lo aqui desfaz, no ultimo passo, o que os dois sites acima preservam.
                    additional_kwargs=kwargs_preservados(nova_msg),
                )
            else:

                def _limpa_e_dropa(t: str, _rep: set[str] = conjunto) -> str:
                    return _drop_bolhas(_limpar_bolhas(t), _rep)

                update_final = {"messages": _reescrever_turno(msgs_turno, _limpa_e_dropa)}
            break  # o que sobrou (se sobrou) ainda passa pelo judge
        # gatilho == "mudo": nada util a enviar -- silencio > raciocinio/papagaio. Com midia no
        # turno as legendas ainda precisam do judge (break); sem midia, antes de fechar mudo,
        # uma ultima tentativa de recuperacao (a falha da regen e estocastica) -- persistiu,
        # fecha mudo como antes.
        if legendas:
            break
        recuperada = await _recuperar_vazio(texto_cru)
        if recuperada is not None:
            texto = str(recuperada.content)
            nova_msg = _com_usage_acumulado(recuperada, nova_msg)
            break
        return Command(
            goto=END,  # type: ignore[arg-type]
            update={"messages": _zeradas_todas()} if nova_msg is not None else update_final,
        )

    if nova_msg is not None:
        # Despacho da regen: zera as AIMessages originais do turno e anexa a regenerada.
        update_final = {"messages": [*vazias, nova_msg]}

    # Canned curada (negacao de disclosure / espera de escalada): pula a Etapa 2 (texto ja
    # confiavel). So sem midia -- uma legenda precisa sempre passar pela Etapa 2, mesmo que a
    # bolha de texto seja canned.
    if not legendas and texto.strip() in _CANNED_CURADAS:
        return Command(goto=END, update=update_final)  # type: ignore[arg-type]

    if not settings.output_guard_judge_habilitado:
        return Command(goto=END, update=update_final)  # type: ignore[arg-type]

    texto_guard = "\n".join(p for p in (texto, *legendas) if p.strip())
    if not texto_guard.strip():
        # tudo dropado pela repeticao e sem legenda: nada a julgar, fecha mudo.
        return Command(goto=END, update=update_final)  # type: ignore[arg-type]

    # Etapa 2: LLM-judge de AUP vinculante sobre texto + legendas (inclusive texto REGENERADO --
    # a regen nao pula o judge). Falha de infra -> default seguro.
    #
    # NAO isente aqui a bolha de contato da parceira. A tentacao aparece toda vez que um turno de
    # encaminhamento e barrado com `system_leak` (12/08), e a leitura e sempre a mesma: "o judge
    # reprovou um texto que o SISTEMA montou". Ele nao reprovou -- essa bolha NUNCA chega aqui. Ela
    # nasce depois do grafo inteiro, no `workers/coordenador.py`, anexada aos `chunks` ja prontos; o
    # que o guard ve e `extrair_texto_do_turno`, que so agrega AIMessage com `usage_metadata`, ou
    # seja, producao do LLM. Um carve-out por FORMA de texto aqui seria pior que inutil: o
    # `fullmatch` de `eh_bolha_de_contato_da_parceira` aceita 39 chars livres no slot do nome, entao
    # o modelo -- que ve a forma canonica no proprio historico depois do 1o encaminhamento -- poderia
    # escrever `contato da Yasmin, ela cobra 800: +5511987654321` e PULAR o judge inteiro.
    # Quando um turno de encaminhamento e barrado, a causa esta na fala do modelo (narrar a entrega)
    # e o conserto e no prompt -- ver `prompts/contexto_dinamico.md.j2` e `ferramentas/parceria.py`.
    # Só anexa o kwarg quando HÁ contexto factual: sem endereço liberado a chamada fica
    # byte-idêntica à message-only de antes (nada muda no caso comum, e o prefixo do judge segue
    # cacheado). `_contexto_factual_aup` devolve None nesse caso.
    contexto_factual = _contexto_factual_aup(endereco_no_prompt)
    kwargs_judge: dict[str, Any] = (
        {"contexto_factual": contexto_factual} if contexto_factual else {}
    )
    try:
        veredito = await _julgar_aup(texto_guard, settings, **kwargs_judge)
    except Exception:
        logger.exception("output_guard judge falhou (turno_id=%s) -> default seguro", ctx.turno_id)
        AUP_SAIDA_BLOQUEADO.labels("judge_falhou", "infra").inc()
        pausou = await _bloquear(
            ctx, observacao="aup_saida_judge_falhou", resumo=_RESUMO_AUP, metric_key="aup_saida"
        )
        return Command(goto=END, update=_update_bloqueado(_zeradas_todas(), pausou))  # type: ignore[arg-type]

    if veredito.viola:
        # WARNING no ramo `viola` (loop-massa r3, achado 8c): so o ramo de INFRA logava
        # (`logger.exception` acima), entao num post-mortem os dois ramos -- decisao do judge e
        # ausencia de decisao -- eram indistinguiveis, apesar de terem a MESMA sancao (bolha zerada
        # + IA pausada + handoff). Sem esta linha a atribuicao por-turno so existia em
        # `escaladas.observacao`, isto e, so indo ao banco.
        logger.warning(
            "output_guard aup viola (motivo=%s turno_id=%s) -> bolha zerada + handoff",
            veredito.motivo,
            ctx.turno_id,
        )
        AUP_SAIDA_BLOQUEADO.labels("violou", veredito.motivo).inc()
        pausou = await _bloquear(
            ctx,
            observacao=f"aup_saida_{veredito.motivo}",
            resumo=_RESUMO_AUP,
            metric_key="aup_saida",
        )
        return Command(goto=END, update=_update_bloqueado(_zeradas_todas(), pausou))  # type: ignore[arg-type]

    return Command(goto=END, update=update_final)  # type: ignore[arg-type]
