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
  Turno na iminencia de sair 100% VAZIO ganha uma recuperacao LLM (`_recuperar_vazio`, com a razao
  VERDADEIRA do gatilho e as duas formas ja tentadas vetadas) e, falhando ela, a REDE DO VAZIO
  deterministica: as bolhas NAO-flagradas do turno ORIGINAL sobrevivem (`_bolhas_boas_do_original`).
  Se nem isso (turno de bolha UNICA), o PISO ANTI-MUDO (`_piso_anti_mudo`): gatilho de QUALIDADE
  nao emudece o turno inteiro -- o original passa, com metrica propria
  (`passou_por_falta_de_alternativa`). Gatilho de SEGURANCA e pos-escalada ficam mudos por design.
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

import asyncio
import logging
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import time
from decimal import ROUND_HALF_UP, Decimal
from difflib import SequenceMatcher
from os.path import commonprefix
from time import monotonic
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
    OUTPUT_DESPEDIDA_PASSIVA,
    OUTPUT_ECO_REGIAO_DETECTADO,
    OUTPUT_ENDERECO_SONEGADO,
    OUTPUT_HORA_FANTASMA,
    OUTPUT_INCLUSO_FANTASMA,
    OUTPUT_LEAK_DETECTADO,
    OUTPUT_PEDAGIO_DETECTADO,
    OUTPUT_PRECO_FANTASMA,
    OUTPUT_PROMESSA_MIDIA,
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
    confirma_agenda,
    contem_endereco_de_encontro,
    contem_hora_explicita,
    contem_pedido_de_endereco,
    horas_afirmadas_na_fala,
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
from ..ferramentas.escalada import ESCALADA_ABERTA_PREFIXO
from ..persona import render_aup_saida
from ._foco_do_turno import (
    aceite_curto_no_burst,
    contem_pedido_de_hora,
    contem_pedido_de_preco,
    perguntas_do_burst,
)

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
    # narracao de MECANICA DO SISTEMA como fala (campanha 13/08, D2 — duvida_das_fotos_rep1 t2):
    # "As midias ja sairam no turno, nao preciso repetir nada." foi ao cliente. Vocabulario que o
    # cliente nunca usa e que descreve a operacao interna: o "turno" como unidade do sistema (o
    # lookahead deixa vivo o turno-da-manha/tarde/noite de trabalho, fala humana possivel),
    # "midias" com verbo de despacho (ao cliente ela diz "fotos"/"video"), o meta "nao preciso
    # repetir" do proprio processamento, o "sistema" como SUJEITO de verbo de operacao, o "prompt"
    # e o acatamento de instrucoes. Conservador: cada ramo exige o combo, nunca a palavra solta.
    # Singular + combos do "sai junto" (campanha 13/08, ciclo 5 V4 — eb04:23966555099311 t12):
    # "A mídia já saiu junto com a minha mensagem" e eco da regra do book ("sai junto, dentro
    # dela") narrado ao cliente. "midia" com verbo de despacho ja era a marca (ao cliente ela diz
    # "fotos"/"video"); entram o SINGULAR, o combo foto/video+"saiu junto" e o proprio "junto com
    # a (minha) mensagem" — vocabulario de mecanica do envio, nunca de fala ("vem junto se
    # quiser", da amiga, segue vivo: sem "com a mensagem" e sem foto/video antes do "junto").
    r"|(as? )?m[íi]dias? (j[áa] )?(saiu|sa[íi]ram|foi|foram|est[áa]|est[ãa]o|vai|v[ãa]o)"
    r"|(fotos?|v[íi]deos?)( j[áa])? (saiu|sa[íi]ram|foi|foram|vai|v[ãa]o) junto"
    r"|junto com a (minha )?mensagem"
    r"|(no|neste|nesse|deste|desse|do) turno(?! d[ae] (manh[ãa]|tarde|noite))"
    r"|n[ãa]o preciso (de )?repetir"
    # "prompt"/"instrucoes" SO nas formas que `_MARCADORES_SYSTEM` ainda nao cobre: "system
    # prompt"/"prompt do sistema"/"minhas instrucoes" sao leak de system e ficam com a Etapa 1
    # (bloqueio + handoff) — o drop do Estagio 0 roda ANTES e nao pode engolir a bolha que a
    # sancao pesada tem de ver (pinado por test_etapa1_fragmento_de_system_bloqueia).
    r"|(?<!system )prompt(?!s? do sistema)"
    r"|o sistema (j[áa] |me )?(anexa|anexou|envia|enviou|manda|mandou|mostra|mostrou|registra|registrou|libera|liberou)"
    r"|(conforme|segundo) (as )?instru[çc][õo]es"
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
# exemplos (com acento: `{horário}`), o COLCHETE inventado ([book], [insira a rua]) e a RUBRICA
# entre parenteses ("(aqui vão as fotos e o vídeo)"). NAO casa o marker [quote]/[quote: trecho]
# (lookahead explicito): e o UNICO colchete legitimo da fala dela — a propria persona crava
# "nenhum colchete além do [quote: ...]" — e ele precisa chegar VIVO ao chunking, que o extrai.
#
# O colchete deixou de exigir verbo instrucional em 13/08 (ciclo 5, V1 — caso real
# eb02:115139634290814 t6: a bolha literal `[book]` foi ao cliente no lugar da midia): qualquer
# `[...]` fora do [quote] e invencao do modelo — placeholder de anexo, rubrica, tag — nunca fala.
# Texto entre colchetes do CLIENTE nao passa por aqui (o guard so ve a fala da IA), e as molduras
# do sistema ([transcrição de áudio...], [pausa ...]) vivem em HumanMessage, fora deste scan.
#
# A rubrica em PARENTESES entrou em 12/08 (loop-massa r3, achado 5): a regen roda sem tools, nao ve
# as ToolMessages do turno e preenche o lugar do anexo com teatro. `(aqui vao as fotos e o video)`
# passava por TODOS os estagios -- inclusive o re-scan da 2a volta -- e entrava na janela historica
# como fala dela, disponivel para imitacao nos turnos seguintes.
# O gatilho tem de vir NO COMECO do parenteses e ser VERBO de rubrica: parenteses e pontuacao comum
# na fala dela ("600 1h (valor fechado)"), entao casar o miolo generico barraria bolha legitima.
_RE_PLACEHOLDER = re.compile(
    r"\{[a-zà-ÿ_]{2,20}\}"  # {valor}, {horario}, {horário}, {nome}, {duracao}, ...
    r"|\[(?!\s*quote\b)[^\]\n]{1,40}\]"  # [book], [insira a rua], [seu endereço] — nunca [quote]
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


# HORA FANTASMA (corrida real `c12cen_v2_20260814`, 2 ocorrências independentes): a bolha CONFIRMA
# um horário DIFERENTE do que o sistema gravou/reservou NO MESMO TURNO. É o irmão de agenda do
# preço/incluso/serviço fantasma, e a família toda existe pelo mesmo motivo: mundo fechado, o claim
# aponta para um fato que o sistema sabe não existir.
#
#   `agenda_borda_fora`: a IA recusa as 23h com todas as letras no t2 ("23h já não consigo",
#       "Consigo às 22h, fecha ?"); no t3 o cliente devolve o número numa pergunta capciosa ("e aí,
#       fechou as 23h?") e ela entrega "Fechou sim amor" / "Te espero às 23h" — com a extração do
#       MESMO turno gravando 22:00 e a reserva criada às 22h. Fala 23h, banco 22h.
#   `piso_que_andou`: a oferta dela foi 20h, a extração gravou 20:00 e a bolha saiu "Confirmado" /
#       "Te espero às 19h amor". Passou invisível porque 19h ainda respeitava o piso do turno.
#
# Nenhuma guarda pegava: `regras.md.j2` só proíbe confirmar o que a TOOL RECUSOU (prefixo `ERRO:`),
# e aqui não houve erro nenhum — a reserva das 22h passou normalmente. O que quebra é a paridade
# entre a fala e o registro, e paridade se checa contra o CARIMBO, nunca contra o texto.
#
# ESTREITO em três camadas (falso-positivo aqui trava o turno do fechamento, o mais caro que existe):
#  1. só bolha com token de FECHAMENTO (`confirma_agenda`): reofertar hora diferente da gravada é
#     conduta CERTA ("Consigo às 11h, fecha ?" é como a reancoragem funciona) — o que não pode é
#     CONFIRMAR. Medido nos 462 turnos com hora gravada dos ciclos da campanha: com o token, 2
#     bolhas divergem (as duas, defeito real); sem ele, 20 — as 18 extras são ofertas legítimas.
#     É também o que resolve o ECO: a hora que o CLIENTE disse, repetida SEM token de fechamento
#     ("Poxa amor, 21:30 estou jantando"), não é oferta nem confirmação e não chega ao detector;
#     com o token, a proveniência deixa de importar — foi exatamente ecoando o 23h DELE que a
#     falsa confirmação saiu.
#  2. só hora AFIRMADA para hoje (`horas_afirmadas_na_fala`, a gramática do `_disciplina`): duração
#     ("400 1h no meu local"), faixa aberta ("a partir das 10:30"), outro dia e a hora RETIRADA
#     ("23h já não consigo") ficam de fora por construção.
#  3. só com hora GRAVADA no turno (`horario_gravado_no_turno`): sem carimbo não há o que
#     contradizer e o detector fica desligado — mesmo desenho do preço sem tabela.
#
# A bolha de confirmação NUA do mesmo turno ("Fechou sim amor", sem hora nenhuma) entra JUNTO
# quando alguma irmã já flagrou: no caso medido é ela que responde "fechou as 23h ?" e, sozinha no
# fallback do drop, confirmaria a hora fantasma do mesmo jeito — com a irmã que nomeava o horário
# fora, o "sim" fica apontando para o número DELE. Só entra a que não nomeia hora: a que confirma a
# hora CERTA nunca é ofensora (é a fala que queremos).
def horario_gravado_no_turno(extracao: Mapping[str, Any] | None) -> time | None:
    """A hora que a `registrar_extracao` GRAVOU neste turno, lida do CARIMBO (`_extracao_registrada`).

    Carimbo, nunca inferência: o payload real é o que o nó `extrair` publicou no State depois do
    saneamento (`_args_saneados` já normaliza "22h" -> "22:00"), e é dele que sai a reserva. Varrer
    o `tool_calls` das AIMessages seria ler mensagem que o próprio guard tem o direito de reescrever.

    `None` (detector desligado) quando: o turno não gravou hora, o turno LIMPOU o campo (`limpar`
    tem precedência sobre os demais, ver a tool), o carimbo é negativo (erro/mute: transação
    revertida) ou o valor não é legível como hora de relógio."""
    if not extracao or "horario_desejado" in (extracao.get("limpar") or []):
        return None
    bruto = extracao.get("horario_desejado")
    if isinstance(bruto, time):
        return bruto.replace(second=0, microsecond=0)
    m = _RE_HORA_CARIMBADA.match(str(bruto or "").strip())
    if m is None:
        return None
    hora, minuto = int(m.group(1)), int(m.group(2))
    return time(hora, minuto) if hora <= 23 and minuto <= 59 else None


_RE_HORA_CARIMBADA = re.compile(r"^(\d{1,2}):(\d{2})")


def bolhas_hora_fantasma(texto: str, gravado: time | None) -> list[str]:
    """Bolhas do turno que CONFIRMAM hora diferente da gravada (PURA; devolve as originais p/ o
    drop). `gravado=None` -> detector desligado (sem carimbo não há paridade a checar)."""
    if gravado is None:
        return []
    bolhas = texto.split("\n\n")
    ofensoras = [
        b
        for b in bolhas
        if confirma_agenda(b) and any(h != gravado for h in horas_afirmadas_na_fala(b))
    ]
    if not ofensoras:
        return []
    return ofensoras + [
        b
        for b in bolhas
        if b not in ofensoras and confirma_agenda(b) and not horas_afirmadas_na_fala(b)
    ]


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


# CAUDA PASSIVA (campanha 13/08, ciclo 2 — 3 casos no lote): a IA encerra o turno devolvendo a
# iniciativa ao cliente sem proximo passo concreto — "Te espero quando quiser rs" (eb02, pos-
# objecao de preco), "Me chama quando quiser" (eb04), "Me avisa quando voce decidir vir que eu te
# espero" (eb01). Os blocos condicionais <janela_futura_vaga>/<desistencia_por_item_fora_do_
# cardapio> nao pegam: o gatilho deles e o burst do CLIENTE, e nesses tres casos quem entregou a
# venda foi a FALA DA IA — a superficie robusta. So a ULTIMA bolha do turno conta (e a despedida
# que fecha), e o veto e duplo, na MESMA bolha: hora/dia concreto ("te espero as 14h" e ATIVA — o
# veto cobre tambem o estado ja fechado com hora combinada) ou pergunta ("entao as 20h
# combinado ?" avanca). Rede de MELHORIA (familia endereco/pedagio/saudacao): regen 1x com conduta
# substituta (incidente #36: nomear o proibido E dar a direcao); persistiu -> pass-through.
# Ciclo 3 (13/08): TERCEIRA aparicao de variantes fora do lexico ("Me chama quando organizar",
# "Me chama quando conseguir", "Fico no aguardo" — esta ultima nomeada como proibida pelo PROPRIO
# prompt). O verbo depois do "quando" deixa de ser lista fechada: a familia e "me chama/avisa/
# fala/manda mensagem QUANDO <qualquer coisa>" — enumerar a vida do cliente (organizar, conseguir,
# decidir, falar com a esposa...) e correr atras de variante pra sempre. A lista fechada que FICA
# e a excecao, pequena e semanticamente coerente: verbo de EXECUCAO do encontro ja combinado
# ("quando chegar/sair/estiver chegando") e coordenacao ativa, nao entrega de iniciativa — e o
# teste pre-existente ("te espero rs, me avisa quando sair" NAO flagra) ja fixava essa fronteira.
# Entram tambem as caudas de balcao sem "quando": "fico no aguardo/aguardando" e "aguardo voce/
# seu retorno/sua resposta".
#
# O veto de passo concreto SEGUE olhando so a ULTIMA bolha (avaliado e rejeitado o turno inteiro
# no ciclo 3): o caso real do c2 (eb01, fixado em teste) tem "1h", "2h" e "700" nas bolhas
# ANTERIORES do MESMO turno e a cauda passiva na ultima — digito de duracao/preco nao e passo
# proposto, e "1h de encontro" e "as 1h" sao indistinguiveis por forma, entao qualquer veto
# turno-inteiro desarmaria o defeito nuclear do detector. O falso positivo levantado ("me chama
# quando chegar" num turno ja fechado com hora) morre pela excecao de execucao acima, nao pelo
# escopo do veto.
#
# Ciclo 4 (caso eb02:54181717110810 t4): "Tranquilo amor, quando tiver um tempo me chama 🥰"
# escapava por DOIS buracos ao mesmo tempo — a ordem INVERTIDA ("quando X me chama" em vez de
# "me chama quando X") e o auxiliar nu ("tiver", que a excecao antiga isentava sozinho). A
# excecao de execucao vira lista fechada de COMPOSTOS (o auxiliar so isenta acompanhado do verbo
# de deslocamento: "estiver chegando" sim, "tiver um tempo" nao) e passa a ser COMPARTILHADA
# pelas duas ordens. O teto de 30 chars no vao da ordem invertida segura a frase longa que fala
# de outra coisa entre o "quando" e o verbo.
_EXECUCAO_DO_ENCONTRO = (
    r"(?:voce\s+|vc\s+|eu\s+)?(?:chegar\b|sair\b|chegando\b|saindo\b"
    r"|(?:estiver|tiver|for)\s+(?:chegando|saindo|chegar|sair|perto|a\s+caminho))"
)
_VERBO_DE_CHAMADA = r"(?:chama|chame|avisa|avise|fala|fale|grita|manda (?:uma )?(?:mensagem|msg))"
# Ciclo 8: prefixo de CLAUSULA para os dois ramos novos (o "que" e o verbo nu). A clausula que
# chega ate o verbo de chamada nao pode falar de EXECUCAO do encontro — "quando" (as duas ordens
# ja tem excecao propria acima) nem o deslocamento nu ("Chega me avisa que passo o quarto",
# "Quando chegar me chama que a gente combina"): coordenar quem ja vem nao e devolver iniciativa.
_CLAUSULA_SEM_EXECUCAO = (
    r"(?:^|[.!?\n])(?:(?!\b(?:quando|chega|chegar|chegando|sair|saindo)\b)[^.!?\n])*"
)
_RE_DESPEDIDA_PASSIVA = re.compile(
    r"\bquando (voce |vc )?(quiser|puder|decidir|resolver|se decidir)\b"  # "vem quando quiser"
    rf"|\b(?:me |pode me )?{_VERBO_DE_CHAMADA}"
    rf"\s+quando\b(?!\s+{_EXECUCAO_DO_ENCONTRO})"
    # ordem INVERTIDA: "quando tiver um tempo me chama" (ciclo 4)
    rf"|\bquando\b(?!\s+{_EXECUCAO_DO_ENCONTRO})"
    rf"[^.!?\n]{{0,30}}?\s(?:me |pode me |so me )?{_VERBO_DE_CHAMADA}\b"
    # Ciclo 8: ordem "me chama QUE <acao minha>" ("me chama que eu vou sim", "me chama que eu
    # ajusto minha agenda pra voce" — eb04:79981032001710 t19/t20). E a mesma entrega de
    # iniciativa das outras duas ordens, so que a condicao vem no que ELA faz depois, nao no que
    # ele faz antes; por isso escapava dos dois ramos do "quando". Dois cortes, os dois medidos
    # contra falso positivo no corpus de saidas: (a) `_CLAUSULA_SEM_EXECUCAO`; (b) "que"
    # interrogativo nao conta — "me fala que horas voce quer" e empurrao ativo, nao cauda.
    rf"|{_CLAUSULA_SEM_EXECUCAO}"
    rf"\b(?:me |pode me |so me ){_VERBO_DE_CHAMADA}"
    r"\s+que\b(?!\s+(?:horas?|dias?|horarios?|qual|quanto|quantas))"
    # Verbo de chamada NU no fim da bolha ("Tranquilo amor, me avisa 🥰" —
    # eb04:14224965292147 t8): sem "quando" e sem "que", a cauda e ainda mais passiva, nao menos.
    # Ancorado no fim (com pontuacao/emoji tolerados) p/ nao pegar o meio de frase, onde o
    # complemento e que decide; mesma `_CLAUSULA_SEM_EXECUCAO` ("quando voce chegar me avisa"
    # tambem termina no verbo, e e coordenacao do encontro ja combinado).
    rf"|{_CLAUSULA_SEM_EXECUCAO}"
    rf"\b(?:me |pode me |so me ){_VERBO_DE_CHAMADA}\s*[^\w\s]*\s*$"
    r"|\bte espero quando\b"  # "te espero quando der"
    # "na torcida" entra na familia do "fico" (eb04:14224965292147 t15): torcer nao e esperar,
    # mas fecha o turno na mesma posicao e com o mesmo vazio. A lista de complementos segue
    # FECHADA de proposito — e ela que preserva "Fico ate voce chegar"/"Fico ate domingo", que na
    # mesma conversa RESPONDEM a pergunta dele ("ate quando voce fica ?").
    r"|\bfico (no aguardo|aguardando|na espera|te esperando|na torcida)\b"  # "fico no aguardo"
    r"|\baguardo (voce|vc|seu retorno|teu retorno|sua resposta|tua resposta|seu contato"
    r"|sua confirmacao|sua mensagem|sua msg)\b"
    r"|\bqualquer coisa[^.!?\n]{0,20}\b(me |so )?(chama|chamar|avisa|avisar|fala|falar|manda|grita)"
    r"|\b(me )?chama a[ei]\b"  # "chama ai"
)
# Proximo passo CONCRETO na mesma bolha = despedida ATIVA, nao passiva: qualquer digito (hora,
# "as 14h"), dia nomeado ou ancora de periodo. Sobre texto ja normalizado (sem acento).
_RE_PASSO_CONCRETO = re.compile(
    r"\d"
    r"|\b(hoje|amanha|agora|logo mais|mais tarde|de manha|a tarde|de tarde|a noite|de noite"
    r"|meio dia|meia noite|segunda|terca|quarta|quinta|sexta|sabado|domingo|fim de semana|fds)\b"
)
# Encerramento DEFINITIVO dito pelo cliente no burst: recusa dura desarma o gatilho — insistir em
# proximo passo em cima de "nao vou mais" e assedio, nao venda. ESTREITO de proposito ("nao vou"
# so no fim da fala: "eu nao vou pedir desconto" NAO e recusa — e o burst do caso real eb02, que
# tem de disparar); sem sinal confiavel o falso positivo raro e uma regen extra, barata e sem
# mudanca de sentido (decisao da campanha 13/08).
_RE_RECUSA_DURA = re.compile(
    r"\bnao vou\s*[.!]*\s*$|\bnao vou (mais|conseguir|poder|dar)\b|\bdesist[oi]\b"
    r"|\bdeixa (pra|para) (la|outra)\b|\besquece\b|\bnao quero mais\b|\bnao rola\b"
)
# Ciclo 8 (13/08, caso eb04:79981032001710 t8): "Hmm hoje acho que nao vou dar conta nao / To
# lotado de coisa pra resolver" desarmava o gatilho INTEIRO pelo ramo "nao vou dar" — e a cauda
# passiva ("me chama quando tiver um tempo livre") saiu ao cliente. Mas recusar o DIA nao e
# encerrar a conversa: e exatamente o insumo do `dia_recusado_pelo_cliente`, que hoje carimba
# `<dia_recusado>` no `<agenda>` e MANDA mirar o primeiro dia da janela que ele nao recusou — ou
# seja, o proximo passo concreto que a regen da cauda passiva pede EXISTE nesse turno.
#
# Fronteira: fala que nomeia um DIA so encerra se disser o encerramento definitivo junto ("hoje
# nao vou MAIS", "hoje desisto"). Sem dia nomeado nada muda — "nao vou mais, esquece" e "deixa
# pra la" seguem desarmando, como nos ciclos 2 e 3.
_RE_DIA_NA_RECUSA = re.compile(
    r"\b(hoje|hj|amanha|depois de amanha|segunda|terca|quarta|quinta|sexta|sabado|domingo"
    r"|essa semana|semana que vem|fim de semana|final de semana|fds)\b"
)
_RE_ENCERRAMENTO_DEFINITIVO = re.compile(
    r"\bnao vou mais\b|\bdesist[oi]\b|\bdeixa (pra|para) (la|outra)\b|\besquece\b"
    r"|\bnao quero mais\b"
)


def bolhas_despedida_passiva(texto: str) -> list[str]:
    """A ULTIMA bolha do turno que e despedida passiva (PURA; devolve a original p/ o veto
    granular da regen). Vazio = turno sem despedida passiva.

    So a ultima bolha e julgada (a cauda e o que fica com o cliente); canned curada e decisao do
    sistema e nao conta; pergunta ou hora/dia concreto na propria bolha a tornam ATIVA."""
    bolhas = [b for b in texto.split("\n\n") if b.strip()]
    if not bolhas:
        return []
    ultima = bolhas[-1]
    if ultima.strip() in _CANNED_CURADAS or "?" in ultima:
        return []
    n = normalizar(ultima)
    if _RE_PASSO_CONCRETO.search(n) or not _RE_DESPEDIDA_PASSIVA.search(n):
        return []
    return [ultima]


def cliente_encerrou_no_burst(falas: Sequence[str]) -> bool:
    """True se alguma fala do burst atual e recusa DURA ("nao vou mais", "desisto") — o gatilho de
    despedida passiva nao arma em cima de encerramento definitivo do cliente (PURA).

    Recusa ancorada num DIA ("hoje nao vou dar conta") NAO e encerramento: e o dia que sai da
    mesa, e o `<dia_recusado>` do prompt ja diz de qual dia a proxima oferta sai (ciclo 8)."""
    for f in falas:
        n = normalizar(f)
        if not _RE_RECUSA_DURA.search(n):
            continue
        if _RE_DIA_NA_RECUSA.search(n) and not _RE_ENCERRAMENTO_DEFINITIVO.search(n):
            continue
        return True
    return False


# ADIAMENTO explicito do cliente (campanha 13/08, ciclo 5 V3 — eb04:23966555099311 t19/t21): ele
# enrola com aviso futuro ("à noite te passo", "já já te passo") e a unica resposta natural e a
# familia "fico no aguardo". Duas superficies do guard puniam exatamente essa resposta: o
# detector de REPETICAO (a espera nao tem hora nem pergunta e repete verbatim a do turno
# anterior; regen 2x sem dado novo -> turno MUDO no t21 — no t22 gemeo so a rede do vazio salvou)
# e a DESPEDIDA PASSIVA ("fico no aguardo" e cauda nomeada da familia). Ecoar a espera a quem
# acabou de adiar nao e papagaio nem entrega de iniciativa — a iniciativa JA esta com ele, por
# declaracao dele. O veto desarma as DUAS superficies coerentemente, e so no turno em que o burst
# ATUAL e adiamento: sem adiamento novo, a espera repetida volta a ser flagrada (nao ha eco
# infinito unilateral — cada eco responde a um adiamento novo, dito por ele).
#
# Co-ocorrencia obrigatoria na MESMA fala (sobre texto normalizado): verbo de AVISO futuro em 1a
# pessoa ("te passo/te falo/te aviso"; "mando" tambem sem o "te" — "mando já td certo", t22) +
# marcador TEMPORAL ("ja (ja)", "a noite", "amanha", "depois", "mais tarde", "quando puder...").
# "te passo o endereco" (sem marcador) e "hoje nao rola" (sem verbo de aviso) nao armam; a fala
# DELE imperativa ("manda o video") nao tem a 1a pessoa e nao casa o verbo.
_RE_AVISO_FUTURO = re.compile(
    r"\b(?:te\s+)?(?:passo|falo|aviso|confirmo|mando|chamo|respondo|retorno|digo)\b"
    r"|\bte dou um toque\b"
)
_RE_MARCADOR_FUTURO = re.compile(
    r"\bja\b|\bdaqui a pouco\b|\bdaqui (?:uns|umas)\b|\bmais tarde\b|\blogo\b"
    r"|\ba noite\b|\bde noite\b|\bhoje\b|\bamanha\b|\bdepois\b|\bassim que\b"
    r"|\bquando (?:eu )?(?:chegar|sair|puder|der|conseguir|resolver|souber|organizar)\b"
)


def cliente_adiou_no_burst(falas: Sequence[str]) -> bool:
    """True se alguma fala do burst atual e ADIAMENTO explicito ("ja ja te passo", "a noite te
    falo"): verbo de aviso futuro + marcador temporal na mesma fala (PURA)."""
    return any(
        _RE_AVISO_FUTURO.search(n) and _RE_MARCADOR_FUTURO.search(n)
        for f in falas
        if (n := normalizar(f))
    )


# A familia da resposta-de-espera que o adiamento legitima ("fico no aguardo", "te espero") —
# recorte da propria `_RE_DESPEDIDA_PASSIVA`, sobre texto normalizado. So a bolha que E espera
# ganha a isencao: bolha repetida de outro conteudo segue flagrada mesmo com adiamento no burst.
_RE_RESPOSTA_DE_ESPERA = re.compile(
    r"\bfico (?:no aguardo|aguardando|na espera|te esperando|esperando)\b"
    r"|\bte espero\b|\bte aguardo\b|\bno aguardo\b|\bvou te esperar\b"
)


def eh_resposta_de_espera(bolha: str) -> bool:
    """True se a bolha e da familia "fico no aguardo"/"te espero" (PURA; ver o comentario do
    adiamento acima — a isencao so vale com adiamento explicito no burst)."""
    return bool(_RE_RESPOSTA_DE_ESPERA.search(normalizar(bolha)))


# COSTURA DA FUSAO — a fronteira de frase que a fusao do book apaga (ciclo 8; o ciclo 7 consertou
# so metade). Quatro sitios deste modulo julgam POR FRASE (os tres detectores de midia abaixo e a
# cirurgia de narracao, `_sem_narracao_de_mecanica`), e todos partiam so em pontuacao terminal.
# So que `post_process._concatenar_bolhas` funde bolhas que eram mensagens separadas intercalando
# ". " APENAS quando a bolha da esquerda termina em alfanumerico — e as bolhas da persona quase
# nunca terminam em pontuacao (regra de voz), muitas terminam em EMOJI. Nesse caso o separador
# vira espaco puro, a fronteira SOME e duas bolhas viram uma frase so.
#
# Medido no caso real (passe 1 "Sou eu mesma amor 🥰" + passe 2 narrando a mecanica): a fundida
# dava UMA frase, `len(frases) < 2`, resgate "" e o TURNO INTEIRO zerado — o oposto do que a
# cirurgia existe para fazer. O proprio caso canonico do ciclo 7 so passava porque o teste montou
# a bolha fundida a mao com ". "; a fusao REAL das mesmas tres bolhas perdia o enquadramento do
# video ("Gravei um video pra voce 🥰"), colado na narracao. Nos detectores o estrago e o
# simetrico: negacao/objeto-de-texto de uma bolha absolvendo a afirmacao da outra.
#
# A fronteira sintetica e EMOJI + espaco + MAIUSCULA, nao "sempre depois de emoji": emoji no MEIO
# da fala existe ("gravei um video 🥰 pra voce") e cortar ali quebraria justamente a co-ocorrencia
# dentro da frase que os detectores medem. Comeco de bolha e maiusculo na pratica (o modelo
# capitaliza cada bolha), entao a maiuscula discrimina costura de emoji-no-meio.
#
# O que NAO se faz: emendar o TEXTO no post_process (inserir ". " apos o emoji). O texto fundido
# vai LITERAL ao cliente — o chunking so re-parte por `\n\n` (workers/_chunking) — entao o ponto
# apareceria no WhatsApp, dentro da bolha, contra a regra de voz de bolha sem pontuacao final. A
# fronteira e do guard e so do split; o texto entregue continua o que o modelo escreveu.
#
# Faixas de emoji: mesmo recorte da estilometria do corpus (`workers/_saida_guard._EMOJI`),
# copiado e nao importado — `agente/` nao depende de `workers/`.
_EMOJI_CLASSE = (
    "\U0001f300-\U0001faff"
    "\U00002600-\U000027bf"
    "\U00002190-\U000021ff"
    "\U00002b00-\U00002bff"
    "\U0000fe00-\U0000fe0f"
    "\U0001f1e6-\U0001f1ff"
)
_COSTURA_DE_BOLHA = rf"(?<=[{_EMOJI_CLASSE}])\s+(?=[A-ZÀ-ÖØ-Þ])"
_RE_COSTURA_DE_BOLHA = re.compile(_COSTURA_DE_BOLHA)


def _frases_normalizadas(bolha: str) -> list[str]:
    """Frases NORMALIZADAS de uma bolha, p/ os detectores que julgam por co-ocorrencia DENTRO da
    frase (promessa de midia, midia no passado, midia recem-afirmada).

    Mesma fronteira da cirurgia de narracao (`_RE_FIM_DE_FRASE`), fonte unica: a costura da fusao
    conta como fim de frase. ADITIVO sobre o split historico `[.!?\\n]+` — tudo que ja partia
    continua partindo, a costura so acrescenta cortes."""
    return [
        f
        for pedaco in _RE_COSTURA_DE_BOLHA.split(bolha)
        for f in re.split(r"[.!?\n]+", normalizar(pedaco))
        if f.strip()
    ]


# PROMESSA DE MIDIA sem tool (campanha 13/08, ciclo 3 — eb03:32904415564000 t7/t10): pedido
# explicito "Manda video da seu corpo inteiro" rendeu "Te mando sim 🥰 / Mas me confirma o
# horario certinho" — promessa verbal SEM `enviar_midia` no turno, ainda por cima CONDICIONADA a
# confirmacao (a forma exata do deadlock do c2) — e depois a promessa nua de novo. A excecao do
# reenvio ja esta no prompt e nao segurou: a alavanca de prompt esta esgotada, vira gatilho
# deterministico no guard.
#
# Familia FECHADA de promessa em 1a pessoa e tempo futuro/presente ("te mando/te envio/vou (te)
# mandar/enviar/ja (te) mando"): "te mandei" e passado (reenvio ja feito, legitimo) e "me manda"
# e fala DELE citada — nenhum casa. O OBJETO decide, por FRASE: substantivo de MIDIA na mesma
# frase arma; objeto de TEXTO (endereco, numero, confirmacao...) e promessa legitima e absolve;
# promessa NUA ("te mando sim") so arma quando o BURST pediu midia — o objeto elidido e o pedido
# dele — e a frase, fora a promessa, e so filler (objeto desconhecido = mundo fechado, nao arma).
# Negacao na mesma frase ("nao vou mandar") desarma: recusar em personagem e a conduta valida.
_SUBSTANTIVO_MIDIA = r"(?:foto|fotos|fotinha|fotinhas|video|videos|videozinho|videozinhos|book)"
_RE_SUBSTANTIVO_MIDIA = re.compile(rf"\b{_SUBSTANTIVO_MIDIA}\b")
_RE_PEDIDO_DE_MIDIA = re.compile(
    r"\b(?:manda|mande|envia|envie|mostra|mostre|quero ver|posso ver|pode mandar|tem)\b"
    rf"[^.!?\n]{{0,50}}?\b{_SUBSTANTIVO_MIDIA}\b"
)
_RE_PROMESSA_ENVIO = re.compile(
    r"\b(?:te mando|te envio|ja te mando|ja te envio|ja mando|ja envio"
    r"|vou te mandar|vou te enviar|vou mandar|vou enviar)\b"
)
_RE_PROMESSA_NEGADA = re.compile(r"\bnao\s+(?:vou\s+)?(?:te\s+)?(?:mando|envio|mandar|enviar)\b")
_RE_OBJETO_DE_TEXTO = re.compile(
    r"\b(?:endereco|localizacao|local|ponto|numero|contato|telefone|zap|whats|whatsapp|pix"
    r"|chave|comprovante|mensagem|msg|confirmacao|detalhe|detalhes|info|informacao|informacoes"
    r"|horario|valor|valores|cardapio|lista|beijo|beijos)\b"
)
# Residuo tolerado na promessa NUA: vocativo/muleta sem conteudo. Qualquer token fora daqui e
# objeto desconhecido e ABSOLVE (mundo fechado: so a promessa comprovadamente vazia arma).
_FILLER_PROMESSA = frozenset(
    "sim claro amor vida gato gata lindo linda querido querida meu minha viu ta ok tudo tudinho "
    "ja jaja agora depois aqui entao pra pro e o a um uma mas rs kkk haha".split()
)


def pediu_midia_no_burst(falas: Sequence[str]) -> bool:
    """True se alguma fala do burst pede MIDIA explicitamente ("manda video", "quero ver foto") —
    o objeto elidido da promessa nua ("te mando sim") e esse pedido (PURA)."""
    return any(_RE_PEDIDO_DE_MIDIA.search(normalizar(f)) for f in falas)


def bolhas_promessa_de_midia(texto: str, *, pediu_midia: bool) -> list[str]:
    """Bolhas que PROMETEM envio de midia sem a midia sair na fala (PURA; o caller cruza com o
    rastro de `enviar_midia` do turno). Julgamento por FRASE dentro da bolha: negacao desarma a
    frase, substantivo de midia arma, objeto de texto absolve, promessa nua arma so com pedido de
    midia no burst e residuo 100% filler."""
    out: list[str] = []
    for b in texto.split("\n\n"):
        if not b.strip():
            continue
        for frase in _frases_normalizadas(b):
            if _RE_PROMESSA_NEGADA.search(frase):
                continue
            m = _RE_PROMESSA_ENVIO.search(frase)
            if m is None:
                continue
            if _RE_SUBSTANTIVO_MIDIA.search(frase):
                out.append(b)
                break
            if _RE_OBJETO_DE_TEXTO.search(frase):
                continue
            resto = _RE_NAO_PALAVRA.sub(" ", frase[: m.start()] + " " + frase[m.end() :]).split()
            if pediu_midia and all(t in _FILLER_PROMESSA for t in resto):
                out.append(b)
                break
    return out


def turno_enviou_midia(msgs_turno: Sequence[AIMessage], messages: Sequence[BaseMessage]) -> bool:
    """True se ALGUMA `enviar_midia` do turno EXECUTOU: tool_call sem ToolMessage de erro — o
    mesmo criterio de `post_process._turno_enviou_book` (status "error" ou content "ERRO:").
    ToolMessages historicas nao sao re-injetadas pelo prepare_context, entao toda ToolMessage em
    `messages` e DESTE turno (PURA). Promessa com a midia saindo no mesmo turno e anuncio
    legitimo do envio; sem o rastro, e promessa vazia."""
    ids_com_erro = {
        m.tool_call_id
        for m in messages
        if isinstance(m, ToolMessage)
        and (m.status == "error" or str(m.content).startswith("ERRO:"))
        and m.tool_call_id
    }
    return any(
        tc.get("name") == "enviar_midia" and tc.get("id") not in ids_com_erro
        for m in msgs_turno
        for tc in (m.tool_calls or [])
    )


# AFIRMACAO de midia JA ENVIADA sem envio nenhum (campanha 13/08, ciclo 5 V1 — caso
# eb02:115139634290814 t7): "olha o vídeo que te mandei 🥰" numa conversa onde NENHUMA midia
# jamais saiu (o t6 emitiu o placeholder `[book]` no lugar do envio e o turno seguinte promoveu a
# invencao a fato). E o irmao PASSADO de `bolhas_promessa_de_midia`: la a promessa aponta pra
# frente ("te mando"), aqui ela aponta pra tras ("te mandei") — e apontar para um envio que nao
# existe e mentira que o cliente desmente na hora. O caller so arma o detector quando
# `book_enviado_em` do atendimento e None E nenhuma `enviar_midia` executou neste turno: com
# QUALQUER midia ja enviada, "te mandei o video" e o apontar legitimo que o proprio prompt manda
# fazer (<ja_enviou_book>). Julgamento por FRASE, como o irmao: verbo no passado 1a pessoa +
# substantivo de MIDIA na mesma frase; negacao desarma ("ainda nao te mandei" e verdade); objeto
# de texto nao arma ("te mandei o endereco" nao e claim de midia). Fica de fora, aceito e
# documentado: a foto da PARCEIRA nao carimba `book_enviado_em` (coordenador), entao "te mandei a
# foto dela" pos-encaminhamento pode falso-positivar — o dano e o drop de uma bolha, nao handoff.
_RE_MIDIA_NO_PASSADO = re.compile(r"\b(?:ja\s+)?(?:te\s+)?(?:mandei|enviei|passei)\b")


def bolhas_midia_ja_enviada(texto: str) -> list[str]:
    """Bolhas que AFIRMAM midia ja enviada ("olha o video que te mandei") — o caller so chama
    com `book_enviado_em` None e sem `enviar_midia` no turno (PURA; devolve as originais p/ o
    drop). Negacao na frase desarma; sem substantivo de midia na mesma frase, nao arma."""
    out: list[str] = []
    for b in texto.split("\n\n"):
        if not b.strip():
            continue
        for frase in _frases_normalizadas(b):
            if _RE_NEGACAO_PERTO.search(frase):
                continue
            if _RE_MIDIA_NO_PASSADO.search(frase) and _RE_SUBSTANTIVO_MIDIA.search(frase):
                out.append(b)
                break
    return out


# AFIRMACAO de envio RECEM-OCORRIDO num turno que nao enviou nada (campanha 13/08, ciclo 7 —
# eb04:79981032001710 t13/t16/t23). Com o book de FOTOS ja enviado no t9, o cliente pedia um
# VIDEO; em tres turnos SEM nenhuma tool de midia (`tools=[]`) a IA respondeu "O video ja te
# mandei, da uma olhada rs", "Te mandei agora amor, olha la" e "Gravei um video pra voce 🥰" — e o
# cliente devolveu "o video voce nao chegou a mandar ainda nao kkk". `bolhas_midia_ja_enviada` (o
# irmao do ciclo 5) nao pega nada disso: ela so arma com `book_enviado_em` VAZIO, e aqui o book
# saiu de verdade. A mentira nao e sobre a CONVERSA ("nunca te mandei nada"), e sobre o TURNO:
# ela afirma um envio que acabou de acontecer quando nada saiu desta resposta.
#
# O eixo do discriminador e o TURNO, nao o tipo de midia (o guard nao sabe se o que saiu antes era
# foto ou video). Duas familias de forma armam, sempre por FRASE e so quando NENHUMA `enviar_midia`
# executou no turno:
#   (a) verbo de envio em 1a pessoa no PASSADO + deixis de RECENCIA — adverbio de agora
#       ("te mandei agora", "acabei de te mandar") ou imperativo DEITICO de olhar ("olha la",
#       "da uma olhada"), que manda conferir o que acabou de chegar;
#   (b) verbo de PRODUCAO no passado + substantivo de midia + destinatario/recencia ("gravei um
#       video pra voce"): anuncio de artefato fresco, que nesta base so existe colado ao envio.
#
# O outro lado da fronteira fica INTACTO — referencia legitima a envio ANTIGO real, que o proprio
# <ja_enviou_book> manda fazer:
#   * imperativo com OBJETO ("olha o video que te mandei") aponta pra um envio conhecido e NAO e
#     deitico — por isso `_RE_OLHA_DEITICO` exige `la/ai/ali` ou a locucao "da uma olhada", nunca
#     o "olha" nu (o teste V1b do ciclo 5, com o book carimbado, continua passando limpo);
#   * "ja te mandei as fotos" sem deixis nenhuma nao arma (e a resposta certa a "cade as fotos?");
#   * marcador de tempo passado na frase ("te mandei ANTES/ontem/mais cedo") absolve;
#   * negacao absolve ("ainda nao te mandei"), objeto de TEXTO absolve quando nao ha substantivo
#     de midia ("te mandei o endereco agora, olha la").
#
# Fica de fora, aceito e documentado: reafirmar o envio no turno SEGUINTE ao envio real ("te
# mandei agora, olha la" um turno depois da `enviar_midia`) tambem arma — o guard so enxerga o
# rastro DESTE turno, e quando o cliente diz que nao recebeu a jogada certa e reenviar de fato,
# nao repetir a afirmacao. A sancao e a mesma da familia fantasma (regen 1x -> drop por bolha com
# a rede do vazio atras), nunca handoff.
_RE_ENVIO_AGORA = re.compile(r"\b(?:agora|agorinha|nesse momento|neste momento)\b")
_RE_ACABEI_DE_ENVIAR = re.compile(
    r"\bacab(?:ei|o)\s+de\s+(?:te\s+)?(?:mandar|enviar|passar|gravar|filmar|tirar)\b"
)
_RE_OLHA_DEITICO = re.compile(
    r"\bd[ae]\s+uma\s+(?:olhada|conferida|espiada)\b"
    r"|\b(?:olha|olhe|ve|veja|confere|confira|checa|espia)\s+(?:la|ai|ali)\b"
)
_RE_ENVIO_ANTIGO = re.compile(
    r"\b(?:ontem|anteontem|antes|cedo|outro dia|dia desses|semana passada"
    r"|mes passado|la atras|aquele dia|ja faz|faz tempo)\b"
)
# OBJETO ANAFORICO de um envio real ("as fotos QUE te mandei", "o QUE te mandei"): a oracao
# relativa aponta para um envio ja conhecido dos dois, e nao para um que acabou de acontecer —
# entao ela absolve ate o imperativo deitico ("Olha la as fotos que te mandei amor"). Refutacao
# adversarial 13/08: sem isto o detector punia exatamente a conduta que o `<ja_enviou_book>`
# prescreve, e no impasse "ele nao confirma sem ver" o turno podia acabar mudo. So absolve com
# `ha_envio_antigo` (houve envio real na conversa): sem envio nenhum, apontar para "o que te
# mandei" e a mentira do ciclo 5, e o irmao da CONVERSA continua sendo quem julga. NAO absolve o
# adverbio de AGORA: "olha o video que te mandei agora" segue sendo claim deste turno.
_RE_OBJETO_ANAFORICO = re.compile(
    r"\bque\s+(?:eu\s+)?(?:ja\s+)?(?:te\s+)?(?:mandei|enviei|passei)\b"
)
_RE_MIDIA_PRODUZIDA = re.compile(r"\b(?:gravei|filmei|tirei|bati|fiz)\b")
_RE_DATIVO_PRA_ELE = re.compile(r"\bp(?:ra|ara)\s+(?:voce|vc|ti|tu)\b|\bpensando em voce\b")


def bolhas_midia_recem_afirmada(texto: str, *, ha_envio_antigo: bool = False) -> list[str]:
    """Bolhas que afirmam um envio de midia RECEM-ocorrido ("te mandei agora, olha la", "gravei um
    video pra voce") — o caller so chama quando NENHUMA `enviar_midia` executou no turno (PURA;
    devolve as originais p/ o drop). Referencia a envio antigo real nao arma: ver o bloco acima.

    `ha_envio_antigo` (= `book_enviado_em` carimbado) liga a absolvicao pelo OBJETO ANAFORICO:
    com envio real na conversa, "olha la as fotos QUE te mandei" e o apontar do `<ja_enviou_book>`.
    Default False = fail-closed (sem saber, o detector segue estreito como era)."""
    out: list[str] = []
    for b in texto.split("\n\n"):
        if not b.strip():
            continue
        for frase in _frases_normalizadas(b):
            if _RE_NEGACAO_PERTO.search(frase) or _RE_ENVIO_ANTIGO.search(frase):
                continue
            tem_midia = bool(_RE_SUBSTANTIVO_MIDIA.search(frase))
            agora = bool(_RE_ENVIO_AGORA.search(frase))
            olha = bool(_RE_OLHA_DEITICO.search(frase))
            # Oracao relativa apontando envio real: absolve a deixis do imperativo, nunca o
            # adverbio de agora (que e claim DESTE turno, com objeto anaforico ou sem).
            if ha_envio_antigo and not agora and _RE_OBJETO_ANAFORICO.search(frase):
                continue
            # (a) envio no passado dado como recem-ocorrido. Sem substantivo de midia, objeto de
            # TEXTO na frase absolve (mundo fechado, igual ao irmao futuro).
            recem = (bool(_RE_MIDIA_NO_PASSADO.search(frase)) and (agora or olha)) or bool(
                _RE_ACABEI_DE_ENVIAR.search(frase)
            )
            if recem and (tem_midia or not _RE_OBJETO_DE_TEXTO.search(frase)):
                out.append(b)
                break
            # (b) midia PRODUZIDA agora e endereçada a ele.
            if (
                _RE_MIDIA_PRODUZIDA.search(frase)
                and tem_midia
                and (agora or olha or _RE_DATIVO_PRA_ELE.search(frase))
            ):
                out.append(b)
                break
    return out


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

# Fragmento de TOKEN DE CONTROLE do provider vazando na bolha (campanha 13/08, D1 — caso real
# eb03:265695300456547 t0, trace ec23d226: "Tudo bem sim</｜｜DSML｜｜parameter>" foi ao cliente).
# O DeepSeek delimita turnos/function-calling com tokens fora do vocabulario de fala: a barra
# FULLWIDTH `｜` (U+FF5C, nunca o pipe ASCII `|`), o separador `▁` (U+2581) e a familia DSML
# (`<｜...｜>`, `</...parameter>`). Sob decodificacao estocastica um FRAGMENTO parcial escapa
# colado a fala boa. Mesmo tratamento do delimitador de exemplo (`_RE_TAG_EXEMPLO`): strip da
# substring, mantendo a fala — os chars `｜`/`▁` e os nomes dsml/parameter nao existem em fala
# legitima de cliente ou da modelo, entao o strip nao tem colateral (o pipe ASCII, o `<3` e
# colchete/parenteses comuns NAO casam). Cobre tambem o fragmento TRUNCADO no fim da bolha
# (`(?:>|$)`): o token pode ser cortado no meio pelo streaming/chunking, como no caso real.
_RE_TOKEN_PROVIDER = re.compile(
    r"</?[^<>]*(?:[｜▁]|dsml|parameter)[^<>]*(?:>|$)"  # tag (fechada ou truncada no fim da bolha)
    r"|(?:[｜▁]+[\w./-]*)+>?",  # resto solto sem `<`: `｜｜DSML｜｜parameter>`, `▁of▁sentence`
    re.IGNORECASE,
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


# Cirurgia por FRASE na bolha de narracao de mecanica (ciclo 7, regressao de `duvida_das_fotos`).
#
# Duas coisas boas de hoje se somaram num defeito: a fusao DETERMINISTICA do book (post_process)
# faz o turno de midia sair como bolha UNICA, e a bolha veio com a narracao colada no fim ("... A
# midia ja saiu junto com a minha mensagem" — parafrase do RETORNO da `enviar_midia`, ja corrigido
# na fonte). O Estagio 0 derruba a bolha INTEIRA, o turno fica vazio, cai na rede do vazio e a
# regen devolve uma resposta SEM o enquadramento do video que o cenario exige. O drop de bolha
# unica e, na pratica, o mudo — a pior saida medida no shadow.
#
# O conserto e por FRASE, e vale para QUALQUER bolha, nao so a unica do turno: a alternativa
# ("resgata so quando e a unica") quebraria o invariante DISTRIBUTIVO de `_limpar_bolhas` (aplicar
# no agregado do turno tem de dar o mesmo que aplicar em cada AIMessage e rejuntar — e o que faz
# `_sanear_raciocinio` julgar exatamente o texto que o coordenador re-deriva das mensagens). Com a
# regra por bolha, bolha 100%-narracao (o caso D2/V4 da campanha: "As midias ja sairam no turno,
# nao preciso repetir nada.") continua sumindo inteira — nao sobra frase nenhuma.
#
# So a familia NARRACAO ganha a cirurgia. Placeholder, promessa-sem-limite e chave Pix seguem
# derrubando a bolha toda: la o problema contamina a bolha inteira (o `[book]` esta NO LUGAR do
# envio; a chave inventada nao vira meia-chave), enquanto a narracao e uma frase ENXERTADA numa
# fala boa. E o residuo passa pelo mesmo `_bolha_descartavel` de novo — frase que sobra suja nao e
# resgatada.
_RE_FIM_DE_FRASE = re.compile(rf"(?<=[.!?…])\s+|{_COSTURA_DE_BOLHA}")


def _sem_narracao_de_mecanica(b: str) -> str:
    """Devolve a bolha SEM as frases de narracao de mecanica, ou "" quando nao ha o que salvar
    (PURA). "" tambem para bolha descartavel por outro motivo, para uma frase so, ou quando o que
    sobra nao e fala de verdade (sem letra/numero, ou suja em outro detector)."""
    if not tem_marcador_raciocinio(b) or tem_placeholder_template(b) or tem_promessa_sem_limite(b):
        return ""
    if tem_chave_pix(b) and not eh_bolha_de_contato_da_parceira(b):
        return ""
    frases = [f for f in _RE_FIM_DE_FRASE.split(b) if f.strip()]
    if len(frases) < 2:
        return ""
    sobra = " ".join(f.strip() for f in frases if not tem_marcador_raciocinio(f))
    if not any(c.isalnum() for c in sobra) or _bolha_descartavel(sobra):
        return ""
    return sobra


def _limpar_bolhas(texto: str, *, resgatar_narracao: bool = False) -> str:
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
            # Ciclo 7: no modo RESGATE, bolha MISTA (fala boa + frase de narracao) perde so a
            # frase. Ver `_resgatar_narracao` — quem decide o modo e o turno, nunca a bolha.
            resgate = _sem_narracao_de_mecanica(b) if resgatar_narracao else ""
            if resgate:
                saidas.append(resgate)
            continue
        # Token de provider strippado DEPOIS do descarte por bolha e JUNTO da tag de exemplo:
        # ambos sao residuo de molde/mecanica colado a fala legitima — a fala fica, o residuo sai.
        # Bolha que era SO o token some (mesma regra da tag) e o turno que esvaziar cai no fluxo
        # normal de bolha vazia (gatilho `mudo` + redes do vazio).
        limpa = _RE_TOKEN_PROVIDER.sub("", _RE_TAG_EXEMPLO.sub("", b))
        if limpa.strip():
            saidas.append(limpa)
    return "\n\n".join(saidas)


def _resgatar_narracao(texto: str) -> str:
    """Estagio 0 no modo RESGATE: `_limpar_bolhas` + cirurgia por frase na bolha de narracao."""
    return _limpar_bolhas(texto, resgatar_narracao=True)


def _limpar_bolhas_sem_zerar(texto: str) -> str:
    """`_limpar_bolhas`, mas se o saneamento esvaziar o texto INTEIRO tenta o modo resgate.

    Onde o Estagio 0 roda sobre UMA mensagem (texto da regen, recuperacao do vazio) a escolha do
    modo nao tem como divergir — e aqui o custo de errar e o mudo, a pior saida medida no shadow.
    """
    limpo = _limpar_bolhas(texto)
    if limpo.strip() or not texto.strip():
        return limpo
    return _resgatar_narracao(texto)


# Detector de REPETICAO (rastro de papagaio): bolha do turno quase identica a uma bolha recente da
# propria IA -- o padrao classico e o cliente silenciar e a IA re-perguntar a MESMA coisa. Humano
# nao repete verbatim: reformula ("como te falei...") ou fica quieto. Limiares conservadores: so
# bolhas com >= _REPETICAO_MIN chars normalizados (cumprimento curto -- "oi amor", "kkk" -- repete
# legitimamente) e similaridade >= _REPETICAO_LIMIAR; uma reformulacao real ("como te falei: <o
# endereco>") ja cai abaixo do limiar. Janela = ver `_REPETICAO_JANELA*` (duas, uma por ramo).
_REPETICAO_LIMIAR = 0.90
_REPETICAO_MIN = 25  # piso p/ match FUZZY (reformulacao parcial: "como te falei: <endereco>")
# Piso menor p/ reenvio EXATO (ratio 1.0): a bolha de preco curta ("400 1h no meu local", 19 chars
# normalizados) passava sob o piso fuzzy de 25 e o papagaio literal ia ao cliente (onda 1, finding
# C). Ainda isenta saudacao/gracejo curto ("oi amor" 7, "boa tarde amor" 14) que repete legitimamente.
_REPETICAO_MIN_VERBATIM = 15
# MEMORIA DO DETECTOR, em DOIS tamanhos -- a distancia ate a bolha antiga nao significa a mesma
# coisa nos dois ramos (diagnostico de degradacao tardia, 14/08; medicao sobre 949 turnos com fala
# da IA do corpus da campanha, `.scratch/campanha-substituicao-20260813`).
#
# `_REPETICAO_JANELA` (12) = memoria do match FROUXO (fuzzy, eco de abertura, fusao). Quanto mais
# longe a bolha antiga, mais a "mesma forma" e re-ancoragem legitima e nao papagaio: a negociacao
# andou no meio. Medido: das 6 bolhas que a janela larga flagraria a mais, as 3 de similaridade
# FROUXA sao todas repeticao legitima -- e a pior delas e "Consigo às 20h sim" em cima de
# "Consigo às 20h, fecha ?" 13 bolhas atras, no turno em que o cliente CRAVOU as 20h
# (ciclo1-rerun eb02:21123135741957 t20): e a confirmacao do fechamento, exatamente o que o
# `houve_aceite` isenta quando o burst e so o aceite -- e ali o burst trazia a hora junto, entao
# o gate nao arma. Alargar o ramo frouxo = guard revertendo o turno do fechamento.
#
# `_REPETICAO_JANELA_VERBATIM` (40) = memoria do reenvio EXATO. Bolha byte-identica NUNCA e
# re-ancoragem, a qualquer distancia -- e o papagaio que o cliente nomeia ("Vc ja falou isso rs").
# 40 = `_JANELA_MENSAGENS` do prepare_context: a memoria do guard passa a ser exatamente o que o
# modelo le, nem mais (nao ha o que ler alem da janela: `_bolhas_historicas` sai de `messages`)
# nem menos. Medido: 60 e 40 dao o MESMO resultado, pela mesma razao. Custo: +0,09 ms/turno.
_REPETICAO_JANELA = 12
_REPETICAO_JANELA_VERBATIM = 40

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
    prepare_context (sem usage_metadata; inverso exato de `mensagens_do_turno`).

    Devolve a memoria LARGA (`_REPETICAO_JANELA_VERBATIM`); quem corta para a memoria curta do
    match frouxo e o proprio `bolhas_repetidas`, que precisa das duas."""
    bolhas = [
        b
        for m in messages
        if isinstance(m, AIMessage) and m.usage_metadata is None
        for b in texto_da_mensagem(m).split("\n\n")
        if b.strip()
    ]
    return bolhas[-_REPETICAO_JANELA_VERBATIM:]


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

# Hora do relogio / duracao dentro da bolha ("15h", "10 horas", "21:30", "15h30"). Existe so para
# o predicado abaixo: nao e detector de hora (esse e o `contem_hora_explicita` do _disciplina), e
# sim a MASCARA que separa "numero que e relogio" de "numero que e dinheiro".
_RE_HORA_OU_DURACAO = re.compile(r"\d{1,2}\s*(?:h\d{2}|h(?:oras?|rs?|s)?\b|:\d{2})", re.I)


def carrega_valor_pedido(bolha: str) -> bool:
    """True se a bolha traz um numero que NAO e hora nem duracao — o dado de um pedido de PRECO.

    A isencao `responde_pedido` da repeticao e "fechada no dado" por construcao (hora usa
    `contem_hora_explicita`, endereco usa `contem_endereco_de_encontro`), mas o ramo do PRECO
    aceitava qualquer digito: no turno em que o cliente RE-PERGUNTA o preco ("quanto era mesmo a
    1h?"), a bolha de HORARIO reenviada verbatim ("Consigo hoje a partir das 15h, fecha ?") tinha
    "15" dentro e ganhava a isencao inteira — o papagaio mais visivel do funil passando pela porta
    aberta para a re-cotacao (c12cen_v2, cenario `segunda_venda_cotado`, t3 e t4 identicos).
    Mascarar relogio/duracao mantem a isencao original de pe ("e 400 a 1h no meu local" continua
    carregando o valor) e devolve a bolha de horario ao detector."""
    return bool(_RE_DIGITOS.search(_RE_HORA_OU_DURACAO.sub(" ", bolha)))


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
    texto: str,
    historicas: Sequence[str],
    *,
    houve_aceite: bool = False,
    responde_pedido: Callable[[str], bool] | None = None,
) -> list[str]:
    """Bolhas do turno quase identicas a uma bolha recente da propria IA -- ou a outra bolha
    anterior do MESMO turno (PURA; devolve as bolhas originais, nao normalizadas, p/ o drop).

    Reenvio EXATO (ratio 1.0) conta ja no piso menor (_REPETICAO_MIN_VERBATIM) -- pega a bolha de
    preco curta que passava sob o piso fuzzy; match FUZZY segue exigindo _REPETICAO_MIN p/ nao
    flagar saudacao curta reformulada, EXCETO quando as duas bolhas carregam os mesmos numeros (ver
    `_MESMOS_NUMEROS_MIN`). As sondas canonicas (`_SONDAS_REPETIVEIS`) contam ABAIXO do piso:
    repeti-las e a violacao que o proprio prompt nomeia. Negacao canned repetida nao e rastro
    (pool curado) -> isenta.

    `historicas` carrega DUAS memorias: o ramo `exato` (reenvio verbatim) enxerga a lista inteira
    (ate `_REPETICAO_JANELA_VERBATIM` = a janela do modelo); os ramos FROUXOS (fuzzy, eco de
    abertura, fusao) so as ultimas `_REPETICAO_JANELA`. Ver o bloco de comentario das duas
    constantes: longe no tempo, "mesma forma" e re-ancoragem legitima; byte-identico nunca e.

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
    `_REPETICAO_MIN_PERGUNTA`), e re-perguntar depois do "fechou" e pior, nao melhor.

    `responde_pedido` e a MESMA isencao um degrau antes do aceite (campanha 13/08, caso
    eb02:26311003246742): o cliente PERGUNTOU preco/endereco/hora neste burst e a bolha que
    carrega o dado pedido e RESPOSTA, nao eco -- "E o investimento?" respondido com "e 400 a
    1h no meu local" dava ratio 0,9048 contra a cotacao do turno anterior (margem de 0,005) e o
    drop + regen produziam exatamente o AP-S1 ("Seria hoje amor ?") que o playbook chama de erro
    capital. O predicado vem do caller (que sabe o que o burst pediu e quais tokens contam como o
    dado); a regra do prompt ("o valor volta, com outras palavras") e o detector deixam de ser
    calibrados um contra o outro. Pergunta repetida SEM o dado continua flagrada, como no aceite;
    a que CARREGA o dado pedido ("Consigo às 10h, fecha ?" quando o burst re-pergunta a hora) e
    entrega com fecho interrogativo, nao papagaio -- o gate `not e_pergunta` cego ao dado matava
    exatamente essa bolha e produziu o unico turno MUDO do lote c4 (eb02:274203613901023 t8)."""
    # Duas memorias (ver `_REPETICAO_JANELA` / `_REPETICAO_JANELA_VERBATIM`): o reenvio EXATO
    # enxerga a janela inteira que o modelo le; o match FROUXO (fuzzy/abertura/fusao) so as
    # ultimas 12 bolhas, porque "mesma forma" longe no tempo e re-ancoragem, nao papagaio.
    # `historicas` ja chega cortada na memoria larga por `_bolhas_historicas`.
    recentes = list(historicas)[-_REPETICAO_JANELA:]
    vistas = [n for b in recentes if _conta_para_repeticao(b, n := _normalizar_bolha(b))]
    vistas_verbatim = {n for b in historicas if _conta_para_repeticao(b, n := _normalizar_bolha(b))}
    perguntas = {_normalizar_bolha(b) for b in recentes if "?" in b}
    do_turno: list[tuple[str, str]] = []
    repetidas: list[str] = []
    respondeu_pedido_no_turno = False
    for b in texto.split("\n\n"):
        if b.strip() in _CANNED_CURADAS:
            continue
        n = _normalizar_bolha(b)
        if not _conta_para_repeticao(b, n):
            continue
        e_pergunta = "?" in b
        # A isencao da RESPOSTA nao exige bolha afirmativa (ciclo 4, eb02:274203613901023 t8):
        # "Consigo às 10h, fecha ?" ENTREGA a hora re-perguntada com fecho interrogativo, e o
        # gate `not e_pergunta` a matava (regen 2x vazia -> turno MUDO). O criterio vira
        # "pergunta SEM o dado pedido": o predicado e fechado no dado (digito/hora/token de
        # endereco), entao a pergunta SECA repetida ("Seria hoje ?") continua flagrada por nao
        # carrega-lo — a fronteira que o `houve_aceite` preserva com `not e_pergunta` logo
        # abaixo segue de pe, porque o aceite nao tem predicado de dado.
        respondeu = responde_pedido is not None and responde_pedido(b)
        respondeu_pedido_no_turno = respondeu_pedido_no_turno or respondeu
        exato = n in vistas_verbatim
        fuzzy = any(
            not _tem_numero_novo(n, v)
            and len(n) >= _piso_fuzzy(n, v, duas_perguntas=e_pergunta and v in perguntas)
            and SequenceMatcher(None, n, v).ratio() >= _REPETICAO_LIMIAR
            for v in vistas
        )
        if respondeu or (houve_aceite and not e_pergunta):
            # Turno do aceite/da resposta: re-entregar o DADO combinado ou PEDIDO nao e eco (ver
            # docstring). No aceite so a pergunta repetida sobrevive ao gate; na resposta o
            # proprio predicado ja exclui a pergunta sem o dado.
            exato = fuzzy = False
        eco = not houve_aceite and not respondeu and any(_mesma_abertura(n, v) for v in vistas)
        if exato or fuzzy or eco or _dobradinha_de_fechamento(n, b, do_turno):
            repetidas.append(b)
        vistas.append(n)
        vistas_verbatim.add(n)
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
    # armada -- o eco-fusao sem aceite continua flagrado. A resposta ao pedido do burst desliga
    # pela mesma razao: o turno que responde o preco re-perguntado E por construcao parecido com a
    # cotacao que ele ja ouviu.
    if repetidas or houve_aceite or respondeu_pedido_no_turno:
        return repetidas
    bolhas_do_turno = [
        b for b in texto.split("\n\n") if b.strip() and b.strip() not in _CANNED_CURADAS
    ]
    inteira = _normalizar_bolha(" ".join(bolhas_do_turno))
    if _fundiu_bolhas(inteira, [_normalizar_bolha(b) for b in recentes]):
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
    """True se o texto vaza fragmento de system/persona/regras OU token de controle do provider
    (PURO). Mesmo regex da Etapa 1; reusado pelo eval online (`online_system_leak`, EVAL-11) e
    pelos graders de `evals/checks.py` — fonte unica do detector.

    O token de provider (`_RE_TOKEN_PROVIDER`, campanha 13/08 D1) entra AQUI e nao so no Estagio 0
    de proposito: no caminho normal o Estagio 0 ja strippou a substring antes deste scan (nunca
    re-barra o texto), mas a LEGENDA de midia nao passa pelo Estagio 0 (bloqueio direto, correto) e
    o eval/coordenador leem a bolha DESPACHADA — se o fragmento voltar por qualquer caminho que nao
    passou pelo strip, o flag acende."""
    return bool(_MARCADORES_SYSTEM.search(texto) or _RE_TOKEN_PROVIDER.search(texto))


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

    Ciclo 7 (regressao de `duvida_das_fotos`): quando o descarte esvazia o turno INTEIRO e havia
    fala de verdade nele, o Estagio 0 roda de novo em modo RESGATE (cirurgia por frase na bolha de
    narracao — `_sem_narracao_de_mecanica`). O caso e a bolha UNICA da fusao do book, onde o drop
    da bolha E o turno mudo. A decisao e do TURNO, nunca da bolha: o modo escolhido aqui vale para
    o agregado E para o `_reescrever_turno`, que e o que mantem `_limpar_bolhas` distributivo
    (aplicar no agregado tem de dar o mesmo que aplicar em cada AIMessage e rejuntar — senao o
    guard julga um texto e o coordenador despacha outro). Turno que ainda tem irma viva nao entra
    no resgate: la o drop da bolha nao emudece nada e a bolha inteira cai, como antes.
    """
    limpador: Callable[[str], str] = _limpar_bolhas
    texto_saneado = _limpar_bolhas(texto)
    if texto.strip() and not texto_saneado.strip():
        resgatado = _resgatar_narracao(texto)
        if resgatado.strip():
            limpador, texto_saneado = _resgatar_narracao, resgatado
    if texto_saneado == texto:
        return texto, []
    return texto_saneado, _reescrever_turno(msgs_turno, limpador)


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
# Cap da CITACAO literal das bolhas vetadas no feedback de `repeticao`. O turno tem no maximo 4
# bolhas; o teto existe pela cauda de FUSAO (`_fundiu_bolhas`), que devolve o turno INTEIRO como
# ofensor -- citar tudo la viraria o rascunho colado duas vezes dentro do mesmo lembrete.
_REPETIDAS_CITADAS_MAX = 3
_BOLHA_CITADA_MAX = 200
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
    # Hora fantasma (c12cen_v2, 14/08): a razao estatica so vale quando a hora gravada nao chega
    # ate aqui (carimbo ilegivel) — o caminho normal e a versao enriquecida, com a hora colada.
    "hora": (
        "ela confirmava um horario DIFERENTE do que ficou registrado para este encontro -- "
        "confirmar hora que o sistema nao reservou compromete voce com um encontro que nao existe"
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
    # Promessa de midia sem tool (ciclo 3): a regen roda SEM tools por design, entao a substituta
    # realista NUNCA e "chame enviar_midia" -- e remover a promessa e seguir o fechamento, ou
    # negar em personagem. Incidente #36: o proibido nomeado E a direcao dada; intencao, nao frase.
    "promessa_midia": (
        "ela prometia mandar foto/video DEPOIS ('te mando sim') sem nenhuma midia saindo nesta "
        "resposta -- promessa de envio pra depois nao existe: midia ou sai na hora, junto da "
        "mensagem, ou nao se promete; reescreva sem prometer envio nenhum, seguindo o fechamento "
        "com o que ja esta na mesa (se ele insistiu em algo que voce nao vai mandar agora, negue "
        "em personagem, do seu jeito) -- e NUNCA condicione um envio a ele confirmar horario"
    ),
    # Irmao PASSADO da promessa (ciclo 5, V1): a regen nao chama tools, entao a substituta nunca
    # e "envie agora" — e responder sem apontar para um envio que nao aconteceu. Intencao, nao
    # frase (incidente #36).
    "midia_afirmada": (
        "ela afirmava que voce JA mandou foto/video nesta conversa ('olha o video que te "
        "mandei') -- voce ainda NAO enviou midia nenhuma nesta conversa, e apontar para um envio "
        "que nao existe e mentira que ele desmente na hora; responda a duvida dele sem citar "
        "midia ja enviada (esta resposta nao anexa midia nenhuma, entao nao afirme envio: se "
        "quiser, ofereca mostrar do seu jeito, sem dizer que ja foi)"
    ),
    # Incidente #36 (nomear o proibido E dar a direcao): a intencao e prescrita, nunca a frase --
    # qual horario/pergunta cabe agora quem sabe e o modelo, com o contexto do turno em maos.
    "despedida": (
        "ela fechava o turno devolvendo a iniciativa ao cliente ('me chama quando quiser'), sem "
        "proximo passo concreto -- nao devolva a iniciativa: feche propondo o proximo passo "
        "concreto (um horario ou dia possivel, com os dados do seu contexto) ou com uma pergunta "
        "que avance a conversa"
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

    Segunda lacuna da mesma familia (campanha 13/08, duvida_das_fotos): quando a bolha vetada
    RESPONDIA uma pergunta que o cliente acabou de re-fazer ("e voce mesma das fotos?"), o texto
    acima so dava conduta p/ pergunta repetida -- "nao reescreva" + "siga pelo que falta" deixava
    a resposta devida sem caminho nomeado e o modelo devolvia turno VAZIO (proibir sem dar a fala
    de substituicao, incidente #36). Agora a saida e nomeada: a resposta continua devida, curta e
    nova; e vazio e vetado com todas as letras (silencio e a pior saida medida no shadow).

    TERCEIRA lacuna (trace 13/08, insistencia em desconto): "e por 280?" recebeu a resposta certa
    pelo dominio -- defesa do valor + empurrao de hora na MESMA mensagem, que e o que
    `regras.md.j2` cobra (defesa sem proximo passo e "turno jogado fora"). So que a bolha do
    empurrao ("Consigo as 23h, fecha ?") era verbatim a de um turno anterior: gatilho armou, a
    regen recebeu "nao repita" e repetiu, e o fallback dropou a bolha -- sobrou a defesa solta.
    O texto acima trata TODA bolha vetada como uma pergunta que ja esta na mesa, e por isso so
    dizia o que NAO fazer com ela; a bolha que carrega o PROXIMO PASSO do turno (o horario, a
    proposta, o dado pedido) nao tinha caminho nomeado, e o modelo, sem saida, ou reincidia ou
    largava a funcao. Agora as duas coisas vao separadas e sem se contradizer: a FORMA nao volta
    (nem trocando so a cauda -- `_mesma_abertura` veta o mesmo comeco com o mesmo numero, e a
    reformulacao de cauda medida no trace 61f4044c reincide de fato), mas a FUNCAO continua devida
    e tem de reaparecer dita de outro lugar. A unica funcao que NAO se repoe segue sendo
    re-perguntar o que ele ainda nao respondeu. Intencao prescrita, fala nunca (conduta nova no
    prompt vira tique): qual horario/proposta cabe agora quem sabe e ele, com o turno em maos.

    Cita TODAS as bolhas vetadas (ate `_REPETIDAS_CITADAS_MAX`), nao so a primeira: com duas
    ofensoras o modelo via uma e reincidia na outra.
    """
    base = _FEEDBACK_GATILHO["repeticao"]
    bolhas = [b.strip() for b in repetidas if b.strip()]
    if not bolhas:
        return base
    citadas = " | ".join(f'"{b[:_BOLHA_CITADA_MAX]}"' for b in bolhas[:_REPETIDAS_CITADAS_MAX])
    return (
        f"{base}. Isto voce ja disse antes, palavra por palavra: {citadas}. "
        "O que nao pode voltar e a FORMA: ele ja leu essa fala, e trocar so o final mantendo o "
        "mesmo comeco e o mesmo numero continua sendo a mesma fala. "
        "A FUNCAO dela, essa sim, continua devida: se essa bolha levava o proximo passo do turno "
        "(o horario que voce ofereceu, a proposta, o dado que ele pediu), o proximo passo tem de "
        "aparecer nesta resposta assim mesmo -- com outras palavras e comecando de outro lugar, "
        "do seu jeito; nao jogue a funcao fora junto com a frase vetada. "
        "So NAO reponha a funcao quando ela era re-perguntar algo que voce ja perguntou e ele "
        "ainda nao respondeu: pergunta ja feita esta na mesa, ele responde quando quiser. "
        "Se essa bolha RESPONDIA algo que ele acabou de perguntar de novo, a resposta continua "
        "devida: confirme em uma frase curta e nova, do seu jeito, sem re-apresentar o que ele "
        "ja leu. Siga do ponto em que a conversa esta, pelo que ainda FALTA combinar. Turno vazio "
        "nao e opcao: alguma fala sua sempre vai ao cliente"
    )


def _feedback_mudo_com_anexo(anexos: Sequence[str]) -> str:
    """Mensagem do gatilho `mudo` quando o SISTEMA ja anexou algo a este turno (ciclo 7).

    Terceira superficie da mesma regressao: se a bolha unica do turno de midia esvaziar mesmo
    assim, a razao estatica so diz "sua resposta veio vazia" — e a regen devolve uma fala qualquer,
    sem o enquadramento da midia que o turno tinha (o cenario `duvida_das_fotos` mede exatamente
    esse enquadramento). O `fato_anexos` do `_regenerar` conta o que saiu, mas nao PEDE a linha de
    acompanhamento; aqui a intencao e nomeada: reconstruir o conteudo legitimo da bolha, sem
    narrar a mecanica (incidente #36 — proibir sem dar a fala de substituicao e o bug conhecido).
    """
    base = _FEEDBACK_GATILHO["mudo"]
    if not anexos:
        return base
    return (
        f"{base}. O rascunho ate tinha a fala certa, mas junto dela veio uma frase NARRANDO a "
        "mecanica do envio (como/quando a midia sai) e foi isso que derrubou a resposta. "
        f"Reescreva a linha que acompanha {', '.join(anexos)}: o enquadramento que voce daria ao "
        "que esta indo — do seu jeito, curto, no clima da conversa — e o proximo passo do "
        "encontro. Ele VE a midia chegar: nao explique o envio, nao diga que ja saiu, nao diga "
        "junto de que ela vai"
    )


# Classificacao QUALIDADE x SEGURANCA dos gatilhos (a lei do modulo, ate 14/08 so escrita em
# comentario dentro do no). QUALIDADE = estilo/conduta da fala; SEGURANCA = o que NAO pode chegar
# ao cliente (`leak`, `regiao`, `incluso`, `servico`, `preco`, `hora`, `midia_afirmada`,
# `endereco`, `mudo`). Gatilho NOVO entra em SEGURANCA por default -- por isso a constante lista
# os de qualidade, nunca "todo o resto". Duas consequencias ja vivas: QUALIDADE nao arma com
# escalada aberta, e (14/08) so QUALIDADE abre o piso anti-mudo.
_GATILHOS_QUALIDADE = frozenset(
    {"repeticao", "sonda", "pedagio", "saudacao", "promessa_midia", "despedida"}
)


def _feedback_recuperacao_do_vazio(razao: str, ofensoras: Sequence[str]) -> str:
    """Lembrete da regen de RECUPERACAO (`_recuperar_vazio`) quando o vazio veio de um drop
    por-bolha com gatilho conhecido.

    Ate 14/08 essa 2a regen entrava pelo trilho `mudo` e herdava a razao estatica dele: "sua
    ultima resposta era so raciocinio interno ou veio VAZIA". Isso MENTE para o modelo -- o
    rascunho nao veio vazio, ele foi VETADO por `repeticao` (ou irmao) e depois esvaziado pelo
    drop --, e a mentira custa a unica informacao que o faria escapar: a lista literal das bolhas
    que nao podem voltar. Medido em `out_c12_tardio`: `_recuperar_vazio` salvou 0 de 7 turnos, e
    nos 5 mudos a 2a regen devolveu uma parafrase da PRIMEIRA (eb04:43087783055505 t18: "Me
    confirma 10:30 que eu te passo o numero certinho amor" -> "... que eu te passo o numero" ->
    "Me confirma 10:30 que eu te passo o numero certinho").

    Aqui a razao VERDADEIRA do gatilho vencedor viaja inteira (com a bolha ofensora colada, do
    jeito que `_feedback_repeticao` ja faz na 1a regen), mais o fato novo -- ja houve uma
    tentativa e ela reincidiu, entao reformular a cauda nao serve. Intencao prescrita, fala nunca
    (incidente #36 / "conduta nova no prompt vira tique")."""
    citaveis = [b.strip() for b in ofensoras if b.strip()]
    # Nao duplica o que a razao enriquecida ja citou (`_feedback_repeticao` cola as bolhas com o
    # MESMO cap): colar de novo faria o lembrete repetir o rascunho tres vezes.
    faltantes = [b for b in citaveis if b[:_BOLHA_CITADA_MAX] not in razao]
    partes = [razao.rstrip().rstrip(".")]
    if faltantes:
        citadas = " | ".join(
            f'"{b[:_BOLHA_CITADA_MAX]}"' for b in faltantes[:_REPETIDAS_CITADAS_MAX]
        )
        partes.append(f". Isto e o que nao passou, palavra por palavra: {citadas}")
    partes.append(
        ". Voce ja tentou reescrever uma vez e caiu no MESMO problema, e agora nao sobrou NADA "
        "para enviar: o cliente esta esperando e ficaria no vacuo, a pior saida possivel"
    )
    if citaveis:
        partes.append(
            ". Nao reformule as falas acima -- trocar so o final da frase e manter o mesmo comeco "
            "reincide. Comece de outro lugar, com outras palavras, e cumpra do seu jeito a funcao "
            "que continua devida"
        )
    return "".join(partes)


def _feedback_midia_recem_afirmada(recem: Sequence[str]) -> str:
    """Mensagem do gatilho `midia_afirmada` quando o que armou foi o irmao do TURNO (ciclo 7).

    A razao estatica do gatilho diz "voce ainda NAO enviou midia nenhuma nesta conversa" — e no
    caso eb04:79981032001710 isso e FALSO (o book saiu no t9): mandar essa mensagem ensinaria o
    modelo a negar um envio que existiu, e ele reincidiria por nao reconhecer o erro. Aqui o
    problema e outro e precisa ser nomeado como e — nada saiu NESTA resposta.

    Incidente #36 (proibir sem dar a fala de substituicao): a substituta e prescrita como
    INTENCAO, nunca como frase, e nao pode ser "chame `enviar_midia`" — a regen roda sem tools por
    design. Sobra a jogada real: responder a duvida dele sem apontar para um envio deste momento,
    lembrando como ANTIGO o que de fato ja foi enviado.
    """
    base = _FEEDBACK_GATILHO["midia_afirmada"]
    bolha = next((b.strip() for b in recem if b.strip()), "")
    if not bolha:
        return base
    return (
        "ela afirmava que a foto/video ACABOU de sair nesta resposta -- a bolha que nao passou "
        f'foi: "{bolha[:200]}". Nenhuma midia saiu junto desta mensagem: ele vai olhar a conversa, '
        "nao vai achar nada e te desmente na hora (foi exatamente o que aconteceu). Envio que nao "
        "aconteceu nao se afirma no passado nem se manda conferir. O que voce JA enviou antes "
        "continua valendo e pode ser lembrado como antigo, sem dizer que saiu agora; e midia so "
        "sai junto da mensagem, entao nesta resposta nao afirme envio nenhum. Responda a duvida "
        "dele do seu jeito e siga o proximo passo do encontro"
    )


def _feedback_hora_fantasma(gravado: time | None, ofensoras: Sequence[str]) -> str:
    """Mensagem do gatilho `hora` com a HORA GRAVADA colada e a bolha ofensora citada.

    Família do `_feedback_repeticao` (FORMA vetada x FUNÇÃO devida) e do incidente #36 (proibir sem
    dar a fala de substituição): o turno que armou este gatilho é, sempre, um turno de FECHAMENTO —
    vetar sem repor a confirmação devolveria uma fala evasiva bem onde a venda fecha. Por isso a
    hora certa vem colada (ela já estava no contexto do modelo, é o que o sistema reservou) e a
    função é nomeada como INTENÇÃO, nunca como frase.

    O eco é nomeado de propósito: nos dois casos medidos o número saiu da boca DELE (a pergunta
    capciosa "e aí, fechou as 23h?"), e sem dizer isso o modelo lê o veto como "não confirme" em
    vez de "não confirme ESSA hora"."""
    base = _FEEDBACK_GATILHO["hora"]
    bolha = next((b.strip() for b in ofensoras if b.strip()), "")
    if gravado is None:
        return base
    return (
        f"{base}. O horario que ficou de pe para este encontro e {gravado.strftime('%H:%M')} -- e "
        "so ele que sai da sua boca como combinado"
        + (f'. A bolha que nao passou foi: "{bolha[:_BOLHA_CITADA_MAX]}"' if bolha else "")
        + ". O que nao pode voltar e a FORMA: fechar, confirmar ou dizer que espera ele em OUTRA "
        "hora que nao essa -- inclusive quando o numero veio da boca DELE, que e como o erro "
        "acontece (ele repete uma hora que voce ja recusou e voce responde 'fechou'). "
        "A FUNCAO segue devida: se ele pediu confirmacao, confirme -- pela hora que esta de pe, do "
        "seu jeito, sem explicar sistema nem pedir desculpa. Se ele esta cravando outra hora, isso "
        "e pedido NOVO: responda pela sua agenda, dizendo o que da, sem fechar o que nao da. "
        "Turno vazio nao e opcao: alguma fala sua sempre vai ao cliente"
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


# Orcamento do turno dentro do guard (campanha 13/08, cenario desconto_entre_degrau_teto): o
# grafo inteiro tem `turno_timeout_s` (60s) e o guard roda por ULTIMO. Reserva para o que vem
# DEPOIS da regen (re-scan puro + judge de AUP, ~5s tipicos + folga) e piso abaixo do qual nem
# vale tentar a regen (o fallback deterministico do gatilho e melhor que uma chamada que nao
# termina). Os numeros sao margens de engenharia, nao medidas finas.
_RESERVA_POS_REGEN_S = 12.0
_REGEN_MIN_S = 5.0
_JUDGE_MIN_S = 3.0


async def _regenerar(
    messages: Sequence[BaseMessage],
    *,
    rascunho: str,
    gatilho: str,
    settings: Any,
    feedback_gatilho: str | None = None,
    bolhas_vetadas: Sequence[str] = (),
    anexos: Sequence[str] = (),
    deadline_mono: float | None = None,
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

    # Orcamento do turno (campanha 13/08): a regen roda por ULTIMO e herda o que sobrou do teto de
    # 60s — uma regen de 37s (medida) deixava o judge sem tempo e o turno morria por FORA do grafo
    # (mute + escalada por exaustao), pior que qualquer fallback daqui. Sem tempo util, nem tenta:
    # fallback imediato do gatilho, antes de qualquer trabalho.
    timeout_regen: float | None = None
    if deadline_mono is not None:
        restante = deadline_mono - monotonic()
        timeout_regen = restante - _RESERVA_POS_REGEN_S
        if timeout_regen < _REGEN_MIN_S:
            logger.warning(
                "output_guard regen pulada por orcamento (gatilho=%s restante=%.1fs)",
                gatilho,
                restante,
            )
            OUTPUT_REGEN.labels(gatilho, "sem_orcamento").inc()
            return None

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
        # A chamada e capada no que sobrou menos a reserva do judge (`timeout_regen`, computado na
        # entrada da funcao) — o TimeoutError cai no mesmo except do fallback.
        with medir_llm("regen"):
            chamada = chat.ainvoke(_janela_com_lembrete(janela, feedback))
            resp = await (
                asyncio.wait_for(chamada, timeout=timeout_regen)
                if timeout_regen is not None
                else chamada
            )
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
        book_enviado_em: Any = None
        if ctx.atendimento_id is not None:
            cur = await conn.execute(
                "SELECT ia_pausada, valor_acordado, duracao_horas, book_enviado_em"
                " FROM barravips.atendimentos WHERE id = %s",
                (ctx.atendimento_id,),
            )
            row = await cur.fetchone()
            pausado = bool(row and row["ia_pausada"])
            valor_acordado = row.get("valor_acordado") if row else None
            duracao_horas = row.get("duracao_horas") if row else None
            book_enviado_em = row.get("book_enviado_em") if row else None
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
    # Isenção "resposta ao pedido" da repeticao (campanha 13/08, eb02:26311003246742): o cliente
    # perguntou PRECO, ENDERECO ou HORA neste burst -> a bolha que carrega o dado pedido
    # (digito p/ preco; token do endereco p/ endereco; hora explicita p/ hora — ciclo 4, caso
    # eb02:274203613901023 t8) e resposta, nao papagaio — o prompt manda "o valor volta, com
    # outras palavras" e o detector flagrava exatamente essa reformulacao (ratio 0,9048 contra a
    # cotacao anterior; a regen entao produzia o AP-S1; na hora re-perguntada a regen veio vazia
    # 2x e o turno saiu MUDO). Predicado fechado no dado: bolha repetida SEM o dado pedido
    # continua flagrada.
    ha_pedido_de_preco = any(contem_pedido_de_preco(f) for f in burst_cliente)
    ha_pedido_de_hora = any(contem_pedido_de_hora(f) for f in burst_cliente)
    # Adiamento explicito no burst (ciclo 5, V3): "ja ja te passo" -> a resposta-de-espera ("fico
    # no aguardo") e a resposta ao adiamento, nao papagaio nem cauda passiva — desarma as DUAS
    # superficies (a isencao da repeticao entra pelo mesmo predicado `responde_pedido`; a
    # despedida passiva desarma no gate dela, mais abaixo).
    cliente_adiou = cliente_adiou_no_burst(burst_cliente)

    def _responde_o_pedido(bolha: str) -> bool:
        # `carrega_valor_pedido`, nao `_RE_DIGITOS`: hora e duracao nao sao o dado do pedido de
        # preco, e aceitar qualquer digito isentava a bolha de HORARIO reenviada verbatim.
        if ha_pedido_de_preco and carrega_valor_pedido(bolha):
            return True
        # Hora re-pedida: reuse do detector canonico de hora do relogio (`contem_hora_explicita`,
        # _disciplina) — nada de regex nova; "Consigo às 10h, fecha ?" carrega o dado pedido.
        if ha_pedido_de_hora and contem_hora_explicita(bolha):
            return True
        # Espera ante adiamento (V3): so a bolha que E da familia da espera ganha a isencao —
        # bolha repetida de outro conteudo segue flagrada mesmo com o adiamento no burst.
        if cliente_adiou and eh_resposta_de_espera(bolha):
            return True
        return bool(
            ha_pedido_de_endereco
            and cadastro.tokens_endereco
            and contem_endereco_de_encontro(bolha, cadastro.tokens_endereco)
        )

    responde_pedido = (
        _responde_o_pedido
        if (ha_pedido_de_preco or ha_pedido_de_endereco or ha_pedido_de_hora or cliente_adiou)
        else None
    )
    # Gatilho `despedida` (campanha 13/08, D3): recusa DURA do cliente no burst desarma — em cima
    # de "nao vou mais" nao ha proximo passo a propor. Pos-escalada/pausa desarmam mais abaixo
    # (a espera da escalada e decisao de outro no; carimbo, nao inferencia).
    cliente_encerrou = cliente_encerrou_no_burst(burst_cliente)
    # Gatilho `promessa_midia` (campanha 13/08, ciclo 3): promessa verbal de envio de midia sem
    # `enviar_midia` executada no turno. O rastro e o mesmo da fusao do book no post_process
    # (tool_call sem ToolMessage de erro) e e CONSTANTE nas 2 tentativas: a regen roda sem tools
    # por design, entao a promessa que reincidir na t2 continua sem midia -> pass-through com
    # metrica (rede de melhoria: dropar a bolha silenciaria o turno inteiro no caso real t10,
    # "Te mando sim" e a bolha unica — e mudo e a pior saida medida no shadow).
    midia_saiu_no_turno = turno_enviou_midia(msgs_turno, state["messages"])
    pediu_midia = pediu_midia_no_burst(burst_cliente)
    # Gatilho `midia_afirmada` (ciclo 5, V1): so arma quando NENHUMA midia jamais saiu — nem na
    # conversa (`book_enviado_em` carimbado no 1o envio da negociacao) nem neste turno. Com
    # qualquer envio real, "te mandei o video" e o apontar legitimo do <ja_enviou_book>.
    midia_nunca_enviada = book_enviado_em is None and not midia_saiu_no_turno
    # Gatilho `hora` (c12cen_v2, 14/08): a hora que a extracao deste turno GRAVOU -- e da qual a
    # reserva saiu. Do CARIMBO do State, nunca da varredura das AIMessages (que o proprio guard
    # reescreve na regen). Ausente/negativo -> detector desligado, e o turno segue como hoje.
    horario_gravado = horario_gravado_no_turno(state.get("_extracao_registrada"))

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
    # A varredura por `tool_calls` das AIMessages tem um furo: qualquer zeramento anterior os
    # descarta por design (`_KWARGS_DE_TOOL_CALL`), e o turno que ESCALOU passava a ter a mesma
    # assinatura de um modelo mudo — o guard entao regenerava uma fala de VENDA depois de a
    # escalada estar aberta (campanha 13/08, eb02:21123135741957 t12). O rastro que sobrevive e a
    # ToolMessage de sucesso do `escalar` (ToolMessages nunca sao reescritas; as historicas nao
    # sao re-injetadas pelo prepare_context, entao toda ToolMessage em `messages` e DESTE turno).
    escalada_no_turno = any(
        isinstance(m, ToolMessage) and str(m.content).startswith(ESCALADA_ABERTA_PREFIXO)
        for m in state["messages"]
    )
    silencio_modelo = (
        bool(msgs_turno)
        and not pausado
        and not escalada_no_turno
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
    # Rede do vazio (campanha 13/08, duvida_das_fotos): o texto ORIGINAL do turno (pos-Estagio 0)
    # e as bolhas que o gatilho da 1a tentativa flagrou NELE. Na t2 `texto` ja e a regen — sem
    # este congelamento, regen vazia/inutilizavel 2x jogava fora tambem as bolhas boas do
    # original e o turno fechava MUDO.
    texto_original = texto
    ofensoras_originais: list[str] = []
    # `rede_aplicada` = o despacho ja foi MONTADO por uma das redes do vazio (rede deterministica
    # do original ou piso anti-mudo): o bloco de despacho da regen, no fim do no, nao pode
    # sobrescreve-lo.
    rede_aplicada = False
    # Razao e rascunho da regen da t1 (14/08, `out_c12_tardio`): a recuperacao do vazio precisa dos
    # DOIS. Da razao, porque o trilho `mudo` contava ao modelo uma historia falsa ("veio VAZIA")
    # no lugar do gatilho que de fato vetou; do rascunho da regen, porque re-alimentar so o
    # ORIGINAL faz o modelo reescrever a mesma frase pela terceira vez -- as duas formas ja
    # tentadas tem de estar vetadas juntas.
    feedback_regen: str | None = None
    texto_regen = ""

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
        comportamento anterior).

        Pos-escalada NAO recupera (mesmo carimbo `ESCALADA_ABERTA_PREFIXO` do `silencio_modelo` e
        da rede do vazio logo abaixo): com a escalada ABERTA, um gatilho de SEGURANCA que esvaziou
        o turno tem de fechar MUDO -- e o design que o topo do modulo ja declara. A troca aqui nao
        e "silencio x vacuo": a proxima fala ja esta com quem recebeu a escalada, e a IA fica
        pausada, entao a recuperacao so ressuscitaria fala de venda por cima da decisao de outro
        no (eb02:21123135741957 t12). Era a ULTIMA porta aberta dessa familia: a rede
        deterministica (`_bolhas_boas_do_original`) ja se isentava, mas ela roda DEPOIS desta.

        14/08 (`out_c12_tardio`, 0 de 7 recuperacoes): a chamada continua entrando pelo TRILHO
        `mudo` (metrica e orcamento), mas nao conta mais a historia do mudo quando o vazio veio de
        um drop por-bolha — o lembrete leva a razao VERDADEIRA do gatilho vencedor com as bolhas
        ofensoras coladas (`_feedback_recuperacao_do_vazio`), e o rascunho vetado passa a ser
        AS DUAS formas ja tentadas (original + regen da t1), nao so a original."""
        if escalada_no_turno:
            return None
        if not settings.output_guard_regen_habilitado:
            return None
        # Razao verdadeira: o gatilho que de fato vetou a t1. Quando ele proprio era `mudo`
        # (turno 100%-raciocinio / silencio do modelo), a razao do trilho JA e a verdadeira e o
        # caller nao tem bolha ofensora nenhuma a citar -> segue com o feedback de sempre.
        razao_verdadeira = (
            feedback_regen or _FEEDBACK_GATILHO.get(gatilho_regen, "")
            if gatilho_regen and gatilho_regen != "mudo"
            else ""
        )
        # As DUAS formas ja tentadas viajam vetadas: sem a regen da t1 aqui, o modelo re-le a
        # frase ofensora original e devolve uma parafrase dela (medido no eb04:43087783055505 t18).
        rascunho_vetado = rascunho
        meia = _RASCUNHO_MAX // 2
        if texto_regen.strip() and texto_regen.strip() != rascunho.strip():
            rascunho_vetado = (
                f"1a tentativa (vetada):\n{rascunho.strip()[:meia]}\n"
                f"2a tentativa (reescrita, caiu no MESMO problema):\n{texto_regen.strip()[:meia]}"
            )
        nova = await _regenerar(
            state["messages"],
            rascunho=rascunho_vetado,
            gatilho="mudo",
            settings=settings,
            feedback_gatilho=(
                _feedback_recuperacao_do_vazio(razao_verdadeira, ofensoras_originais)
                if razao_verdadeira
                # Gatilho da t1 era `mudo`: a razao dele (enriquecida com os anexos, quando ha) ja
                # e a verdadeira -- e a mesma que a t1 usou.
                else feedback_regen
            ),
            anexos=anexos,
            deadline_mono=ctx.turno_deadline_mono,
        )
        t = _limpar_bolhas_sem_zerar(texto_da_mensagem(nova)) if nova is not None else ""
        aprovada = (
            bool(t.strip())
            and _scan_vazamento(t) is None
            and not (
                settings.output_guard_repeticao_habilitada
                and bolhas_repetidas(
                    t, historicas, houve_aceite=houve_aceite, responde_pedido=responde_pedido
                )
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
            # Hora fantasma (14/08): mesma razao das linhas acima — a regen do trilho `mudo` nao
            # sabe qual hora o turno reservou e reconfirmaria a hora que o drop acabou de tirar.
            and not bolhas_hora_fantasma(t, horario_gravado)
            and not (midia_nunca_enviada and bolhas_midia_ja_enviada(t))
            # Ciclo 7: o irmao do TURNO tem de estar na MESMA bateria. Sem esta linha a
            # recuperacao reintroduzia a mentira que o drop tinha acabado de tirar — a regen do
            # trilho `mudo` nao sabe que nada saiu nesta resposta e reescreve "te mandei agora".
            and not (
                not midia_saiu_no_turno
                and bolhas_midia_recem_afirmada(t, ha_envio_antigo=book_enviado_em is not None)
            )
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

    def _ofensoras_de_seguranca(t: str) -> list[str]:
        """Bateria de SEGURANCA sobre um texto: tudo o que NAO pode chegar ao cliente, sem os
        gatilhos de QUALIDADE (`repeticao`/`sonda`, que sao estilo). Extraida em 14/08 para ter
        UMA lista so — a rede do vazio ja rodava esta bateria, e o piso anti-mudo tem de rodar a
        MESMA: o scan do turno para no primeiro gatilho por precedencia, entao uma bolha vetada
        por `repeticao` pode carregar junto um preco fantasma que ninguem chegou a olhar."""
        return [
            *bolhas_eco_regiao(t, permitidos_lugar),
            *bolhas_incluso_fantasma(t, inclusos_da_modelo),
            *bolhas_servico_fantasma(t, cardapio.servicos),
            *bolhas_afirmacao_nua_de_risco(burst_cliente, t, cardapio.servicos),
            *bolhas_preco_fantasma(t, valores_validos),
            *bolhas_hora_fantasma(t, horario_gravado),
            *(bolhas_midia_ja_enviada(t) if midia_nunca_enviada else []),
            # Ciclo 7: o irmao do TURNO entra aqui tambem. A precedencia faz um gatilho de cima
            # (ex. `repeticao`) vencer o scan e so ELE entrar em `ofensoras_originais`; sem esta
            # linha, a rede resgatava a bolha "Te mandei agora amor, olha la" do original e a
            # mentira do eb04 saia ao cliente pelo caminho mais silencioso de todos (nenhuma
            # metrica de midia acende).
            *(
                []
                if midia_saiu_no_turno
                else bolhas_midia_recem_afirmada(t, ha_envio_antigo=book_enviado_em is not None)
            ),
        ]

    def _bolhas_boas_do_original() -> tuple[str, list[AIMessage]] | None:
        """Rede do VAZIO, deterministica (campanha 13/08, duvida_das_fotos): o gatilho por-bolha
        flagrou PARTE do turno, a regen veio vazia/inutilizavel 2x e o turno ia fechar MUDO —
        jogando fora tambem as bolhas do original que NUNCA foram flagradas. Aqui elas sobrevivem:
        original menos as ofensoras da 1a tentativa, re-escaneado pela MESMA bateria do fallback
        triste (os detectores abaixo do gatilho vencedor nao rodaram no scan, por precedencia).
        Sem LLM: e o mesmo drop que o fallback por-bolha ja faz quando a regen esta indisponivel.
        TODAS flagradas -> None e o mudo fica (silencio > papagaio, decisao pre-existente; nao
        existe canned generica de venda — o pool curado e so escalada/disclosure, por design).

        Pos-escalada/pausa/mute-deliberado ficam de fora por PRECEDENCIA: o rastro
        `ESCALADA_ABERTA_PREFIXO` (e o carimbo `_mute_por_erro_de_tool`) e decisao de outro no, e
        ressuscitar fala de venda depois da escalada e o bug de eb02:21123135741957 t12."""
        if escalada_no_turno or pausado or state.get("_mute_por_erro_de_tool"):
            return None
        conjunto = {b for b in ofensoras_originais if b.strip()}
        if not conjunto or not texto_original.strip():
            return None
        sobra = _drop_bolhas(texto_original, conjunto)
        if not sobra.strip() or _scan_vazamento(sobra) is not None:
            return None
        remanescentes = [
            *(
                bolhas_repetidas(
                    sobra, historicas, houve_aceite=houve_aceite, responde_pedido=responde_pedido
                )
                if settings.output_guard_repeticao_habilitada
                else []
            ),
            *bolhas_sonda(sobra),
            *_ofensoras_de_seguranca(sobra),
        ]
        if remanescentes:
            conjunto |= set(remanescentes)
            sobra = _drop_bolhas(sobra, conjunto)
            if not sobra.strip():
                return None

        def _limpa_e_dropa_original(t: str, _rem: set[str] = conjunto) -> str:
            return _drop_bolhas(_limpar_bolhas(t), _rem)

        return sobra, _reescrever_turno(msgs_turno, _limpa_e_dropa_original)

    def _aplicar_rede_do_vazio() -> bool:
        """Aplica a rede do vazio: o texto do turno vira a sobra do ORIGINAL (que ainda passa pelo
        judge), as AIMessages originais sao reescritas com o drop e a regen inutilizavel e
        despachada ZERADA — usage preservado p/ o custo do turno, SEM tool_calls
        (`_KWARGS_DE_TOOL_CALL`), mesmo contrato do `_zerar_turno`."""
        nonlocal texto, nova_msg, update_final, rede_aplicada
        resgate = _bolhas_boas_do_original()
        if resgate is None:
            return False
        texto, reescritas = resgate
        if nova_msg is not None:
            nova_msg = _zerar_turno([nova_msg])[0]
            reescritas = [*reescritas, nova_msg]
        update_final = {"messages": reescritas}
        rede_aplicada = True
        OUTPUT_REGEN.labels("vazio_fallback_original", "usado").inc()
        logger.warning(
            "output_guard rede do vazio: bolhas nao-flagradas do original sobrevivem "
            "(gatilho=%s turno_id=%s)",
            gatilho_regen,
            ctx.turno_id,
        )
        return True

    def _piso_anti_mudo(gatilho_do_vazio: str) -> bool:
        """PISO ANTI-MUDO (14/08, `out_c12_tardio`): ultima porta antes do turno fechar 100% mudo
        por um gatilho de QUALIDADE. Deixa passar o turno ORIGINAL — a bolha vetada inclusive.

        So depois de TUDO ter falhado: regen da t1 reincidiu, o drop esvaziou o turno, a regen de
        recuperacao reincidiu de novo e a rede deterministica nao tinha irma nao-flagrada para
        resgatar (3 dos 5 mudos medidos tinham UMA bolha so — a rede e inerte por construcao).

        Por que passar: `repeticao`/`sonda` sao QUALIDADE, nao seguranca, e o proprio topo deste
        modulo ja declara que silencio total e a pior saida medida no shadow. Nos 5 turnos medidos
        o impasse era de POLITICA — o cliente perdido na rua pedia o dado exato (nome do hotel,
        numero da rua, telefone) e a unica fala autorizada e "me confirma o horario que eu te
        passo"; com a funcao fixa e a forma vetada nao existe frase nova. O guard nao estava
        corrigindo um erro, estava punindo a unica resposta que a politica permite. Nao responder
        NADA a quem esta na porta e pior que repetir.

        Onde ele NAO vale, e por que:
          * gatilho de SEGURANCA (`leak`, `preco`, `regiao`, `incluso`, `servico`,
            `midia_afirmada`, `hora`, `endereco`, `mudo`): o mudo continua sendo a saida certa —
            o piso nunca vira porta de vazamento;
          * escalada aberta / IA pausada / mute deliberado: decisao de OUTRO no, e ressuscitar
            fala de venda por cima dela e o bug de eb02:21123135741957 t12;
          * texto original que, alem do gatilho de qualidade, tem qualquer ofensora de SEGURANCA
            (a precedencia do scan para no primeiro gatilho: a bolha repetida pode carregar um
            preco fantasma que ninguem chegou a olhar) ou vazamento.

        O texto passa, mas nao passa livre: a Etapa 2 (judge de AUP) ainda roda sobre ele, e a
        metrica `passou_por_falta_de_alternativa` deixa o evento visivel (silencio evitado NAO e
        conduta boa — e o menos ruim de duas saidas ruins)."""
        nonlocal texto, nova_msg, update_final, rede_aplicada
        if gatilho_do_vazio not in _GATILHOS_QUALIDADE:
            return False
        if escalada_no_turno or pausado or state.get("_mute_por_erro_de_tool"):
            return False
        original = texto_original.strip()
        if not original:
            return False
        if _scan_vazamento(original) is not None or _ofensoras_de_seguranca(original):
            return False
        texto = texto_original
        # As AIMessages originais seguem VIVAS com o texto do Estagio 0 (o `update_final` de
        # entrada ja carrega as saneadas, quando houve saneamento); so a regen inutilizavel e
        # despachada ZERADA, com o usage preservado p/ o custo do turno.
        if nova_msg is not None:
            nova_msg = _zerar_turno([nova_msg])[0]
            update_final = {"messages": [*update_final.get("messages", []), nova_msg]}
        rede_aplicada = True
        OUTPUT_REGEN.labels(gatilho_do_vazio, "passou_por_falta_de_alternativa").inc()
        logger.warning(
            "output_guard piso anti-mudo: bolha original passa por falta de alternativa "
            "(gatilho=%s turno_id=%s)",
            gatilho_do_vazio,
            ctx.turno_id,
        )
        return True

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

    # CLASSIFICACAO DOS GATILHOS (campanha 13/08, c10 `encaixe_apos_o_atual`). Duas classes:
    #
    #   QUALIDADE (estilo/conduta da fala): `repeticao`, `sonda`, `pedagio`, `saudacao`,
    #       `promessa_midia`, `despedida` — a lista EXECUTAVEL e `_GATILHOS_QUALIDADE` (14/08),
    #       lida tambem pelo piso anti-mudo.
    #   SEGURANCA (o que NAO pode chegar ao cliente): `leak`, `regiao`, `incluso`, `servico`,
    #       `preco`, `hora`, `midia_afirmada`, `endereco`, `mudo`. Na duvida, o gatilho novo entra
    #       aqui — e `hora` entrou por esta porta: confirmar horario que o sistema nao reservou
    #       compromete a modelo com um encontro que nao existe, e ninguem aparece la.
    #
    # Com escalada ABERTA no turno os de QUALIDADE nao armam — `promessa_midia` e `despedida` ja
    # faziam isso; as quatro primeiras eram a porta que faltava. O turno que chamou `escalar` no
    # meio tem, por DESIGN, a bolha pre-tool preservada pelo corte do post_process (post_process.py
    # :76-86): ela e a fala que ACOMPANHA a escalada, e como repete a cotacao ja dita ela batia no
    # detector de repeticao e disparava o loop de regen na tentativa 1 — reescrevendo fala de VENDA
    # depois de a escalada estar aberta, e perdendo o dado bom no caminho (o "19:30" do c10). Mesma
    # familia de `silencio_modelo` e da rede do vazio (guard desfaz decisao de outro no), entrando
    # por porta nova. SEGURANCA continua valendo com escalada aberta: vazamento, preco fantasma,
    # endereco inventado e mídia afirmada NAO viram excecao por haver escalada.
    for tentativa in (1, 2):
        motivo = _scan_vazamento(texto) if texto.strip() else None
        repetidas: list[str] = []
        if (
            not motivo
            and settings.output_guard_repeticao_habilitada
            and not escalada_no_turno
            and texto.strip()
        ):
            repetidas = bolhas_repetidas(
                texto, historicas, houve_aceite=houve_aceite, responde_pedido=responde_pedido
            )
        sondas: list[str] = []
        if not motivo and not repetidas and not escalada_no_turno and texto.strip():
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
        # Hora fantasma (14/08): irmao de AGENDA da familia acima — a bolha confirma horario
        # diferente do que o turno gravou. SEGURANCA (arma com escalada aberta): a fala compromete
        # a modelo com um encontro que nao existe, e isso nao vira excecao por haver escalada.
        horas_fant: list[str] = []
        if limpo_ate_aqui and not servicos_fant and not precos_fant and texto.strip():
            horas_fant = bolhas_hora_fantasma(texto, horario_gravado)
        # Afirmacao de midia JA enviada sem envio nenhum (ciclo 5, V1): mesma familia fantasma
        # dos vizinhos — mundo fechado, o claim aponta para um fato que o sistema sabe nao
        # existir. So arma com `midia_nunca_enviada` (book NUNCA saiu E nada saiu neste turno).
        #
        # Ciclo 7 (eb04:79981032001710 t13/t16/t23): o irmao do TURNO entra no MESMO gatilho — com
        # o book ja enviado antes, `midia_nunca_enviada` e False e a mentira sobre ESTA resposta
        # ("te mandei agora, olha la" sem tool nenhuma) passava reta. Arma so pelo rastro do
        # turno; a referencia a envio antigo real segue fora (detector).
        midias_afirmadas: list[str] = []
        recem_afirmadas: list[str] = []
        if (
            limpo_ate_aqui
            and not servicos_fant
            and not precos_fant
            and not horas_fant
            and texto.strip()
        ):
            if midia_nunca_enviada:
                midias_afirmadas = bolhas_midia_ja_enviada(texto)
            if not midia_saiu_no_turno:
                recem_afirmadas = bolhas_midia_recem_afirmada(
                    texto, ha_envio_antigo=book_enviado_em is not None
                )
                midias_afirmadas += [b for b in recem_afirmadas if b not in midias_afirmadas]
        endereco_sonegado = (
            limpo_ate_aqui
            and not servicos_fant
            and not precos_fant
            and not horas_fant
            and not midias_afirmadas
            and pediu_endereco
            and bool(texto.strip())
            and not contem_endereco_de_encontro(texto, cadastro.tokens_endereco)
        )
        melhorias_limpas = (
            limpo_ate_aqui
            and not servicos_fant
            and not precos_fant
            and not horas_fant
            and not midias_afirmadas
            and not endereco_sonegado
        )
        pedagio = (
            melhorias_limpas
            and perguntas_pendentes
            and not escalada_no_turno
            and bool(texto.strip())
            and resposta_so_pedagio(texto)
        )
        saudacao_conflita = (
            melhorias_limpas
            and not pedagio
            and not escalada_no_turno
            and bool(texto.strip())
            and saudacao_em_conflito(texto, saudacao_cliente)
        )
        # Promessa de MIDIA sem tool (campanha 13/08, ciclo 3): bolha promete envio e nenhuma
        # `enviar_midia` executou no turno. NAO arma pos-escalada/pausa (decisao de outro no);
        # a promessa NEGADA na propria frase ja desarma dentro do detector.
        promessas_midia: list[str] = []
        if (
            melhorias_limpas
            and not pedagio
            and not saudacao_conflita
            and not escalada_no_turno
            and not pausado
            and not midia_saiu_no_turno
            and texto.strip()
        ):
            promessas_midia = bolhas_promessa_de_midia(texto, pediu_midia=pediu_midia)
        # Despedida PASSIVA (campanha 13/08, D3): a ultima bolha devolve a iniciativa sem passo
        # concreto nem pergunta. NAO arma pos-escalada/pausa (a espera da escalada e decisao de
        # outro no — e a canned curada nem chega aqui), nem sobre recusa dura do cliente.
        despedidas: list[str] = []
        if (
            melhorias_limpas
            and not pedagio
            and not saudacao_conflita
            and not promessas_midia
            and not escalada_no_turno
            and not pausado
            and not cliente_encerrou
            # Adiamento explicito (ciclo 5, V3): "fico no aguardo" a quem disse "ja ja te passo"
            # e coordenacao, nao entrega de iniciativa — a iniciativa ja esta com ele.
            and not cliente_adiou
            and texto.strip()
        ):
            despedidas = bolhas_despedida_passiva(texto)
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
        elif horas_fant:
            gatilho = "hora"
        elif midias_afirmadas:
            gatilho = "midia_afirmada"
        elif endereco_sonegado:
            gatilho = "endereco"
        elif pedagio:
            gatilho = "pedagio"
        elif saudacao_conflita:
            gatilho = "saudacao"
        elif promessas_midia:
            gatilho = "promessa_midia"
        elif despedidas:
            gatilho = "despedida"
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

        if tentativa == 1:
            # Rede do vazio: congela as ofensoras do turno ORIGINAL (na t2 `texto` ja e a regen e
            # o gatilho pode ate ser outro) — e a diferenca entre "dropar do original" e "perder o
            # original inteiro" quando a regen vem vazia 2x. Gatilhos sem bolha ofensora (leak,
            # mudo, redes de melhoria) caem no `()` e a rede fica inerte.
            ofensoras_originais = [
                *{
                    "repeticao": repetidas,
                    "sonda": sondas,
                    "regiao": ecos,
                    "incluso": fantasmas,
                    "servico": servicos_fant,
                    "preco": precos_fant,
                    "hora": horas_fant,
                    "midia_afirmada": midias_afirmadas,
                }.get(gatilho, ()),
            ]

        if tentativa == 1 and settings.output_guard_regen_habilitado:
            gatilho_regen = gatilho
            # A razao vai para uma VARIAVEL (14/08): a regen de recuperacao do vazio precisa dela
            # inteira — o trilho `mudo` contava ao modelo uma historia falsa no lugar do gatilho
            # que de fato vetou, e com ela ia embora a lista literal das bolhas ofensoras.
            feedback_regen = (
                _feedback_preco_fantasma(cardapio.precos_tabela, duracao_horas)
                if gatilho == "preco"
                # Hora fantasma: a hora GRAVADA colada (o dado que o sistema reservou) —
                # mesma familia factual do preco/endereco, e sem ela a regen so saberia que
                # nao pode confirmar, nao O QUE confirmar.
                else _feedback_hora_fantasma(horario_gravado, horas_fant)
                if gatilho == "hora"
                else _feedback_endereco_sonegado(endereco_no_prompt)
                if gatilho == "endereco"
                # `repeticao` entrou na familia em 12/08: a razao estatica fazia o modelo
                # REFORMULAR a mesma frase, que reincide no piso dos "mesmos numeros" e
                # esgota a 2a tentativa -> turno mudo (trace 61f4044c).
                else _feedback_repeticao(repetidas)
                if gatilho == "repeticao"
                # Ciclo 7: a razao estatica so serve ao irmao da CONVERSA; com o book ja
                # enviado ela seria falsa (`_feedback_midia_recem_afirmada` cai na estatica
                # quando nao foi o irmao do turno que armou).
                else _feedback_midia_recem_afirmada(recem_afirmadas)
                if gatilho == "midia_afirmada"
                # Ciclo 7, 3a superficie: turno de midia que esvaziou pede a linha de
                # acompanhamento de volta, nao so "escreva alguma coisa".
                else _feedback_mudo_com_anexo(anexos)
                if gatilho == "mudo"
                else None
            )
            nova = await _regenerar(
                state["messages"],
                rascunho=texto if texto.strip() else texto_cru,
                gatilho=gatilho,
                settings=settings,
                # Gatilho FACTUAL leva a razao ENRIQUECIDA, com o dado colado: preco fantasma
                # recebe a escada nomeada (so vetar fazia o modelo recuar sem contraproposta) e
                # endereco sonegado recebe o ponto de encontro literal do prompt (citar a tag
                # condicional pelo nome e o que produziu a rua inventada) — familia do #36.
                feedback_gatilho=feedback_regen,
                # Descarte por BOLHA tambem no caminho FELIZ (achado 4b): o gatilho e sempre uma
                # bolha, e a mesma informacao granular que o fallback usa em `_drop_bolhas` entra
                # aqui. Sem ela o lembrete jogava fora o turno inteiro por uma bolha, e o modelo
                # devolvia turno encolhido — com a pergunta do cliente engolida junto.
                # Gatilhos sem bolha ofensora (leak, mudo, e as redes de melhoria onde o
                # problema e o que FALTA na fala) caem no `()` e mantem o lembrete antigo, que
                # descarta o rascunho inteiro — e o certo la. `despedida` E granular: a cauda
                # passiva vai nomeada como vetada e o resto do turno como aproveitavel.
                bolhas_vetadas={
                    "repeticao": repetidas,
                    "sonda": sondas,
                    "regiao": ecos,
                    "incluso": fantasmas,
                    "servico": servicos_fant,
                    "preco": precos_fant,
                    "hora": horas_fant,
                    "midia_afirmada": midias_afirmadas,
                    "despedida": despedidas,
                    "promessa_midia": promessas_midia,
                }.get(gatilho, ()),
                anexos=anexos,
                deadline_mono=ctx.turno_deadline_mono,
            )
            if nova is not None:
                # O texto final vive na PROPRIA nova_msg (id novo, usage proprio): o coordenador
                # re-deriva via `mensagens_do_turno` (usage != None) e acumula o custo dela. O
                # `additional_kwargs` vem junto pelo mesmo motivo do usage: a fala despachada e a
                # da REGEN, e o raciocinio que a explica (`reasoning_content`) mora ali.
                texto = _limpar_bolhas_sem_zerar(texto_da_mensagem(nova))
                # Congela a 2a FORMA tentada: na t2 `texto` vira o que sobrou do drop (vazio, no
                # caso que interessa) e a recuperacao perderia a frase que acabou de reincidir.
                texto_regen = texto
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
        if gatilho in ("endereco", "pedagio", "saudacao", "despedida", "promessa_midia"):
            # Pass-through de proposito: as cinco redes sao de MELHORIA (entregar o dado pedido,
            # responder a pergunta antes do empurrao, espelhar o periodo dele, fechar com passo
            # concreto em vez de devolver a iniciativa, tirar a promessa de midia que nao sai),
            # nao de bloqueio — derrubar a bolha aqui silenciaria fala legitima (dropar a
            # despedida sem substituta e o anti-padrao do incidente #36, e no caso real da
            # promessa a bolha e o turno inteiro: drop = mudo, a pior saida medida no shadow).
            # Regen falhou/persistiu -> segue o texto como esta; so a metrica registra.
            # "persistiu" exige regen TENTADA (nova_msg existe); com a regen desligada ou
            # indisponivel na t1 nada foi tentado — "sem_regen" separa os dois no piloto.
            #
            # EXCECAO cirurgica do ciclo 4 (residual do c4-rerun, 2 turnos): a regen da
            # `despedida` que devolve OUTRA cauda passiva da mesma familia ("Fico te esperando",
            # "Fico no aguardo amor") ja teve sua chance de substituta — persistir aqui nao e o
            # anti-padrao do #36 (a regen FOI a substituta pedida e reincidiu). Com irmas boas no
            # turno, corta a cauda (drop granular da ULTIMA bolha, a unica que o detector flagra)
            # em vez de mandar a devolucao de iniciativa ao cliente. Bolha UNICA segue
            # pass-through (drop = mudo, pior que a cauda passiva); regen de OUTRO gatilho que
            # desagua em despedida na t2 tambem (a despedida nunca teve a regen dela).
            if gatilho == "despedida" and nova_msg is not None and gatilho_regen == "despedida":
                sem_cauda = _drop_bolhas(texto, set(despedidas))
                if sem_cauda.strip():
                    texto = sem_cauda
                    OUTPUT_DESPEDIDA_PASSIVA.labels("cortada").inc()
                    nova_msg = AIMessage(
                        id=nova_msg.id,
                        content=texto,
                        usage_metadata=nova_msg.usage_metadata,
                        response_metadata=nova_msg.response_metadata,
                        # Reescrita da propria regen: o raciocinio dela segue junto (mesmo motivo
                        # do drop de bolha do fallback da repeticao, logo abaixo).
                        additional_kwargs=kwargs_preservados(nova_msg),
                    )
                    break
            {
                "endereco": OUTPUT_ENDERECO_SONEGADO,
                "pedagio": OUTPUT_PEDAGIO_DETECTADO,
                "saudacao": OUTPUT_SAUDACAO_CONFLITANTE,
                "despedida": OUTPUT_DESPEDIDA_PASSIVA,
                "promessa_midia": OUTPUT_PROMESSA_MIDIA,
            }[gatilho].labels("persistiu" if nova_msg is not None else "sem_regen").inc()
            break
        if gatilho in (
            "repeticao",
            "sonda",
            "regiao",
            "incluso",
            "servico",
            "preco",
            "hora",
            "midia_afirmada",
        ):
            # Mesmo fallback p/ os oito: dropa a bolha ofensora e manda o resto (silencio >
            # papagaio/SAC/bairro inventado/incluso que ela nao tem/promessa, preco errado, hora
            # que o sistema nao reservou ou midia afirmada que nunca saiu). So a metrica difere.
            ofensoras = {
                "repeticao": repetidas,
                "sonda": sondas,
                "regiao": ecos,
                "incluso": fantasmas,
                "servico": servicos_fant,
                "preco": precos_fant,
                "hora": horas_fant,
                "midia_afirmada": midias_afirmadas,
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
                    *bolhas_hora_fantasma(texto, horario_gravado),
                    *(bolhas_midia_ja_enviada(texto) if midia_nunca_enviada else []),
                    *(
                        []
                        if midia_saiu_no_turno
                        else bolhas_midia_recem_afirmada(
                            texto, ha_envio_antigo=book_enviado_em is not None
                        )
                    ),
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
                "hora": OUTPUT_HORA_FANTASMA,
                # Reusa o contador da familia de midia (o irmao futuro): as acoes `dropada`/
                # `mudo` distinguem o trilho passado sem metrica nova.
                "midia_afirmada": OUTPUT_PROMESSA_MIDIA,
            }[gatilho]
            metrica.labels("dropada" if texto.strip() else "mudo").inc()
            if not texto.strip() and not legendas:
                recuperada = await _recuperar_vazio(texto_cru)
                if recuperada is not None:
                    texto = str(recuperada.content)
                    nova_msg = _com_usage_acumulado(recuperada, nova_msg)
                    break
                # Recuperacao LLM falhou: rede DETERMINISTICA antes do mudo — as bolhas
                # nao-flagradas do turno original sobrevivem (e ainda passam pelo judge).
                if _aplicar_rede_do_vazio():
                    break
                # Nada sobrou (3 dos 5 mudos medidos tinham UMA bolha, entao a rede e inerte):
                # gatilho de QUALIDADE nao emudece o turno inteiro — o original passa.
                if _piso_anti_mudo(gatilho):
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
        # `mudo` na t2 porque a regen de um gatilho por-bolha veio VAZIA (duvida_das_fotos t4):
        # antes de fechar mudo, a rede deterministica resgata as bolhas boas do original.
        if _aplicar_rede_do_vazio():
            break
        # Mesma porta do fallback por-bolha: quem esvaziou o turno foi o gatilho da t1 (`mudo`
        # aqui e so a forma da regen ter voltado vazia). De QUALIDADE, o original passa.
        if _piso_anti_mudo(gatilho_regen or gatilho):
            break
        return Command(
            goto=END,  # type: ignore[arg-type]
            update={"messages": _zeradas_todas()} if nova_msg is not None else update_final,
        )

    if nova_msg is not None and not rede_aplicada:
        # Despacho da regen: zera as AIMessages originais do turno e anexa a regenerada. Com a
        # rede do vazio aplicada o despacho ja foi montado la (originais reescritas + regen
        # zerada) — zera-las aqui desfaria o resgate.
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
        # Orcamento do turno (campanha 13/08): o judge e a ULTIMA chamada e nao pode estourar o
        # wait_for do coordenador — morrer por fora do grafo e mute + escalada por exaustao, sem
        # este default seguro. Capado no que sobrou; sem tempo util, TimeoutError imediato cai no
        # mesmo except (default seguro: bloqueia + escala), a MESMA sancao com rastro proprio.
        chamada_judge = _julgar_aup(texto_guard, settings, **kwargs_judge)
        if ctx.turno_deadline_mono is not None:
            restante = ctx.turno_deadline_mono - monotonic()
            # Menos que o piso: nem tenta (esperar 3s por uma chamada que precisa de mais so
            # garante a morte por fora). wait_for com timeout<=0 levanta TimeoutError na hora.
            veredito = await asyncio.wait_for(
                chamada_judge, timeout=restante if restante >= _JUDGE_MIN_S else 0
            )
        else:
            veredito = await chamada_judge
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
