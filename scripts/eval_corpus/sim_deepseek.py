"""Simulador de conversa A/B OFFLINE com fidelidade ao agente de produção (DeepSeek V4 Flash).

Substitui o papel do Vendedor no antigo `wf_simulador.js` (que rodava em Workflow com
subagentes Claude — INFIEL, porque o agente ao vivo usa DeepSeek, não Sonnet). Aqui o
Vendedor sob teste é chamado por `criar_chat_deepseek` (a MESMA factory do chat #1 de prod,
`graph.py:_criar_chat_principal`): mesmo modelo, mesma temperatura, mesmo thinking-disabled.

Dois interlocutores (cliente-sim e juiz) também rodam DeepSeek — basta plausibilidade, não
fidelidade. Mede CONDUTA/ESTILO (tamanho do turno da cotação, em-dash, âncora-N+1, incluso,
emoji, calor, repetição robótica, violação), NUNCA conversão (judge de desfecho κ=0.07).

§0: gasta crédito DeepSeek real (autorizado). Offline — não toca WhatsApp/banco/prod.

Uso:
  cd api && uv run python ../scripts/eval_corpus/sim_deepseek.py \
      --base   /caminho/prompt_base.txt \
      --variante /caminho/prompt_variante.txt \
      --tag-base base --tag-variante paredao \
      --personas preco_no_abridor,faz_x_quanto,decidido,sumido_rapido,info_depois_preco,preco_sensivel \
      --n-rep 2 --k 8 --conc 6 \
      --out /caminho/resultado_ab.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import unicodedata
from typing import Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from barra.core.llm import criar_chat_deepseek, nome_modelo
from barra.settings import Settings

# --------------------------------------------------------------------------- personas
# Ancoradas nos arquétipos de reação do corpus (eval_cotacao). Foco: personas que ELICITAM
# cotação (onde a anti-paredão age) e estressam os riscos (incluso some? voz seca? âncora quebra?).
PERSONAS: dict[str, str] = {
    "preco_no_abridor": (
        "Voce abre a conversa JA pedindo o preco, direto e seco: 'oi quanto e 1h?' / 'qual o valor?'. "
        "Quer o NUMERO antes de tudo; se ela enrolar, reforca 'so me fala o valor'."
    ),
    "faz_x_quanto": (
        "Voce abre perguntando uma pratica especifica E o preco junto: 'vc faz oral sem? quanto fica 1h?'. "
        "Quer servico + valor de cara; se ela responder so uma das duas, cobra a outra."
    ),
    "decidido": (
        "Voce e DECIDIDO. Ja quer marcar hoje. Pergunta valor de 1h e, ao receber, topa e parte pra "
        "logistica (horario, regiao, como chega). Nao enrola, nao pechincha."
    ),
    "sumido_rapido": (
        "Voce SOME. Manda 1-2 mensagens curtas, pergunta o preco e, ao receber a cotacao, esfria. "
        "A partir dai responde no maximo com monossilabos e logo encerra (encerrou=true sem dar motivo). "
        "Simula o sumico mudo (53% das perdas)."
    ),
    "info_depois_preco": (
        "Voce chegou por um anuncio e abre educado, SEM pedir preco ainda: 'Ola, tudo bem? Peguei seu "
        "contato num site, queria saber do seu atendimento'. Responde a saudacao. No 2o ou 3o envio pede "
        "o pacote: 'me passa valor, horario e local?'. Voce QUER o numero. Se ela responder so cardapio/"
        "regiao/'seria hoje?' SEM o valor, cobra o valor de novo UMA vez, seco. Se cotar, agradece e segue."
    ),
    "preco_sensivel": (
        "Voce e PRECO-SENSIVEL. Interessado mas acha caro. Pergunta o valor, reclama ('ta puxado'), "
        "contrapropoe bem abaixo (pede 250 num programa de 400) e insiste por desconto mais de uma vez "
        "antes de decidir."
    ),
    "curioso_morno": (
        "Voce e CURIOSO E MORNO. Pergunta muita coisa (o que ela faz, regiao, fotos, como funciona), "
        "elogia, demonstra interesse, mas custa a marcar. Fica 'vou ver', 'depois te chamo', sem fechar."
    ),
    "interno_quer_endereco": (
        "Voce quer marcar PESSOALMENTE e vai ATE ela (interno). Abra dizendo que quer marcar hoje e que "
        "VOCE vai no local dela. Aceite o valor de 1h sem pechinchar e crave um horario ('pode ser hj as "
        "21h'). Assim que ela combinar o horario, PECA o endereco e como chegar: 'me passa o endereco?', "
        "'como faco pra chegar ai?', e principalmente 'e quando eu chegar, faco como pra te achar?'. "
        "Voce quer saber como chega no local exato e como entra. Nao repete pergunta de preco; foca em fechar e ir."
    ),
    "desconfia_golpe": (
        "Voce DESCONFIA que e golpe/fake. Interessado, mas com o pe atras: acha que a foto pode ser "
        "falsa, tem medo de pagar e nao aparecer ninguem, ja tomou calote. Pede prova de que e real "
        "('me manda um video agora dizendo meu nome', 'como sei que nao e golpe?') e RESISTE a qualquer "
        "pagamento antecipado ('nao pago pix antes de ver', 'so pago na hora, pessoalmente'). Quer marcar, "
        "mas so se sentir seguro. Se ela contornar bem e sem ceder demais, voce topa e marca; se ela travar, "
        "ficar robotica ou prometer coisa demais, voce esfria e some."
    ),
    "lowball_irredutivel": (
        "Voce quer o programa mas SO fecha por 200 (num programa de 400). Pede 200 de cara e, quando "
        "ela recusa ou oferece o melhor dela, MARTELA 200 sem subir NUNCA ('200 e o maximo', 'ou 200 "
        "ou nada', 'se nao for 200 eu procuro outra'). Voce NAO aceita nem 1 real acima de 200 em "
        "hipotese alguma, e insiste turno apos turno. Testa se ela segura e depois desiste/escala."
    ),
    "adia_vou_pensar": (
        "Voce se interessa, pergunta o valor de 1h e, ao receber a cotacao, ADIA sem recusar: "
        "'vou pensar', 'depois te chamo', 'hoje ta corrido, qualquer coisa te aviso'. Voce NAO "
        "reclama do preco. Se ela apenas aceitar o adiamento ('ta bom, me chama'), voce encerra "
        "(encerrou=true). Se ela te fizer UMA pergunta leve e facil de responder (tipo que horas "
        "voce sai do trabalho / amanha fica melhor?), voce responde, esquenta e pode ate marcar."
    ),
    "externo_vem_ate_mim": (
        "Voce quer que ELA VA ATE VOCE (externo). Deixe claro cedo: 'consegue vir aqui em casa?' / "
        "'prefiro que voce venha ate mim'. Pergunta o valor de 1h. Aceita o valor sem pechinchar, "
        "passa seu endereco quando ela pedir ('rua das figueiras 88, jd proenca') e crava um horario "
        "hoje. Nao estranha custo de uber/pix se ela explicar; foca em fechar."
    ),
    "marca_sem_perguntar_preco": (
        "Voce e DECIDIDO e NUNCA pergunta o preco. Abre ja querendo marcar hoje: 'oi, consegue hoje "
        "as 21h? vou ai no seu local'. Vai direto pra logistica (horario, regiao, como chega) e crava "
        "o horario. Voce NAO pergunta valor em nenhum turno — segue combinando como se nao precisasse; "
        "se ELA falar o valor, voce so confirma ('fechou') e segue."
    ),
    "pergunta_distancia_cedo": (
        "Logo nas primeiras mensagens, ANTES de perguntar valor ou marcar, voce pergunta distancia e "
        "local exato: 'fica longe do centro?', 'demora quanto de uber dai?', 'qual o endereco?'. "
        "Insista UMA vez pelo endereco exato ('me passa a rua'). So depois pergunta o valor e, se "
        "gostar, marca pra hoje."
    ),
    "insiste_pickup": (
        "Voce quer marcar mas VAI DE CARRO BUSCAR ela (pickup) — nao vai ao local dela nem ela vem ao seu. "
        "Deixe claro cedo: 'eu te busco de carro', 'passo ai e a gente vai pro motel'. Aceita o valor de 1h "
        "sem pechinchar e crava um horario. Pergunta o PONTO DE ENCONTRO ('onde eu te pego?', 'me passa o "
        "ponto que eu chego de carro'). Voce NAO paga Pix de deslocamento (voce que dirige) — se ela cobrar "
        "pix de uber, estranhe ('pix de que? eu que vou ai te buscar'). Foca em fechar e buscar."
    ),
    "quer_video_chamada": (
        "Voce quer uma VIDEO CHAMADA ao vivo, nao um encontro presencial. Abra deixando claro: "
        "'oi, voce faz video chamada?' / 'queria agendar uma call de video com voce'. Pergunte valor e "
        "duracao. Aceite o valor sem pechinchar e crave um horario mais tarde HOJE, sempre a noite "
        "('pode ser hoje as 22h?', 'as 22h fica bom pra mim'). NUNCA peca 'agora' nem 'ja' — sempre um "
        "horario a noite. Voce NAO vai a lugar nenhum e ela nao vai ate voce — e tudo pela camera, sem "
        "endereco. Se ela pedir um Pix adiantado do valor da chamada, voce topa ('beleza, me passa a "
        "chave'). Foca so em marcar a call; nao pergunta endereco nem fala em se deslocar."
    ),
}


# --------------------------------------------------------------------------- schemas
class FalaCliente(BaseModel):
    bolhas: str = Field(
        description="Bolhas da fala do cliente, uma mensagem de WhatsApp por linha (Enter, nunca "
        "' / ' literal). So o texto."
    )
    encerrou: bool = Field(description="true se o cliente encerrou/sumiu de vez nesta fala.")


class Veredito(BaseModel):
    f_warmth_all: bool = Field(description="calor (vocativo amor/vida, 'rs', emoji organico, tom leve) em ~todas as falas da modelo")
    repeticao_robotica: bool = Field(description="recolou a MESMA sondagem/pergunta mecanicamente em 3+ turnos, soando robotica (mesmo variando palavras)")
    incluso_citado: bool = Field(description="a modelo chegou a dizer o que esta INCLUSO (beijo na boca, oral, namoradinha, carinhosa) em ALGUM turno?")
    fugiu_preco: bool = Field(description="o cliente PEDIU preco e a modelo NAO cotou no mesmo turno nem no seguinte (desconversou/adiou)")
    f_glued_urgency: bool = Field(description="no turno do PRECO havia urgencia/CTA de fechamento colada ao numero ('seria agora?', 'vamos fechar?', 'bora?'). Sondar 'seria hoje?' ANTES do preco NAO conta")
    violacao: bool = Field(description="a modelo quebrou regra de dominio (endereco completo cedo; comentou outra modelo; aceitou servico fora da lista; cravou taxa do cartao; admitiu ser IA; cobrou Pix no interno; revelou outro cliente)")
    violacao_regra: Literal["nenhuma", "endereco_cedo", "cross_modelo", "servico_indevido", "taxa_cravada", "admitiu_ia", "pix_indevido", "revelou_outro_cliente", "outra"]
    desfecho: Literal["fechou_logistica", "engajou", "silenciou", "desviou", "objecao_preco"]
    nota: str = Field(description="observacao curta; diga se a cotacao soou ENXUTA ou PAREDAO")


# --------------------------------------------------------------------------- prompts
def carrega_prompt(path: str) -> str:
    """Le o prompt renderizado e remove os marcadores de secao do render_v1_prompt.py."""
    txt = open(path, encoding="utf-8").read()
    return "\n".join(l for l in txt.splitlines() if not re.fullmatch(r"===[A-Z_]+===", l.strip()))


def msgs_vendedor(system: str, hist: list[dict]) -> list:
    """Mensagens do Vendedor: system (prompt de prod) + turnos como Human(cliente)/AI(modelo)."""
    out: list = [SystemMessage(system)]
    for h in hist:
        out.append(HumanMessage(h["bolhas"]) if h["lado"] == "C" else AIMessage(h["bolhas"]))
    return out


def render_hist(hist: list[dict]) -> str:
    return "\n".join(f"{'C' if h['lado'] == 'C' else 'M'}: {h['bolhas'].replace(chr(10), ' / ')}" for h in hist)


def prompt_cliente(persona_desc: str, hist: list[dict]) -> list:
    sys = (
        "Role-play de teste offline (nao e producao, nao envia nada a ninguem). Voce e o CLIENTE "
        "(o COMPRADOR) no WhatsApp de uma acompanhante (Elite Baby). Fale como homem brasileiro real "
        "no WhatsApp: curto, informal, minusculas, sem floreio.\n\n"
        "VOCE E O COMPRADOR — NUNCA faca o papel dela. Voce NUNCA, em hipotese alguma: cota preco ou "
        "recita a tabela ('600 1h', '150 por 15min'); diz 'no meu local'/'te recebo'/'aqui em casa'; "
        "se descreve como provedora ('sou tranquila', 'estilo namoradinha', 'faco beijo/oral'); passa "
        "endereco; pede nem manda foto de portaria; oferece o seu pix. ISSO TUDO E DA MODELO (M). Voce "
        "so faz o que um comprador faz: pergunta preco/servico/horario/local, aceita ou pechincha, "
        "marca, vai e chega. Se na conversa original uma fala for do VENDEDOR (linhas 'V:'), ela NAO e "
        "sua — jamais a repita como se fosse voce. O ' / ' que aparece juntando frases na conversa "
        "original (tanto nas suas falas 'VOCE:' quanto nas do vendedor 'V:') e SO notacao visual p/ "
        "'quebrei em mais de uma mensagem de WhatsApp' — nunca escreva o caractere '/' literal como "
        "separador na sua resposta; se sua fala original tinha varias mensagens, mande cada uma numa "
        "linha (Enter) separada.\n\n"
        "SEU PERFIL: " + persona_desc + "\n\n"
        "COMO AGIR: voce fala agora com a modelo (M) — uma IA em teste que NAO conduz igual ao vendedor. "
        "Se o seu perfil traz uma CONVERSA ORIGINAL (V = vendedor, VOCE = voce), o objetivo e reencenar "
        "aquele cliente pra comparar lado a lado, entao mantenha as suas falas (so as 'VOCE:') o MAIS "
        "LITERAIS possivel e NA MESMA ORDEM. As linhas 'V:' sao do VENDEDOR (a outra ponta), NUNCA suas. "
        "POREM — e aqui esta o ponto — cada fala sua original foi REACAO ao que o "
        "vendedor disse logo antes (o GATILHO). So use a sua proxima fala original quando a modelo "
        "chegar no MESMO ponto, isto e, quando ela disser algo equivalente ao gatilho daquela fala. Se "
        "a modelo ainda NAO criou o gatilho (foi por outro caminho, perguntou outra coisa, ou ainda nao "
        "deu aquela informacao), NAO cole a fala — responda ao que ela DE FATO disse, no personagem, e "
        "SEGURE a fala original ate o gatilho aparecer. Ex.: uma fala sua que reagia a um endereco/preco/"
        "horario do vendedor so faz sentido DEPOIS que a modelo der esse mesmo endereco/preco/horario; "
        "antes disso, nao diga (nao diga 'pertinho'/'ja estou no caminho'/'cheguei' se a modelo ainda "
        "nao combinou local e horario). Se ela te perguntar algo direto, RESPONDA a ela. A conversa "
        "original e so referencia do SEU comportamento: nunca cobre da modelo um preco/endereco/horario "
        "que so o vendedor original deu — vale o que a MODELO te disser. Preserve as decisoes do cliente "
        "(pede valor, aceita/pechincha, topa ir, chega...). Se o seu perfil NAO traz conversa original, "
        "apenas reaja no personagem ao que a modelo disser. Encerre (encerrou=true) quando as suas falas "
        "originais acabarem ou voce ja tiver combinado/fechado.\n\n"
        "Responda APENAS a sua proxima fala. 100% no personagem, 100% no papel de COMPRADOR."
    )
    h = render_hist(hist) if hist else "(voce ainda nao falou; abra a conversa)"
    return [SystemMessage(sys), HumanMessage("Conversa ate agora (C = voce, M = a modelo):\n" + h)]


def _sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn").lower()


# Falas que so a MODELO produz (auto-oferta em 1a pessoa / acerto de venda). Backstop ao vazamento
# de papel do cliente-LLM, que as vezes copia a fala do vendedor da conversa original como se fosse
# dele. Conservador de proposito: so o que um COMPRADOR praticamente nunca digita — nao pega
# pergunta de comprador ("vc faz oral sem?", "consegue 400?"), so a auto-descricao de provedora.
_RE_VOZ_MODELO = re.compile(
    r"\bsou (bem )?(tranquila|carinhosa|atenciosa|safada|gostosa)\b"
    r"|\bestilo namoradinha\b"
    r"|\bfaco (beijo|oral)\b"
    r"|\bte recebo\b"
    r"|\bfoto da portaria\b"
    r"|\b\d{3,4}\b.{0,12}\bno meu local\b"  # recitacao de tabela ("400 1h no meu local")
)


def sanear_fala_cliente(bolhas: list[str], linhas_vendedor: list[str] = ()) -> list[str]:
    """Descarta bolhas em voz de MODELO que vazaram pro cliente-LLM (ele e o COMPRADOR): tanto
    autodescricao fixa de provedora (_RE_VOZ_MODELO) quanto copia literal de uma fala REAL do
    Vendedor na conversa original (`linhas_vendedor`, ground-truth extraida do mesmo transcript
    que o ClienteLLM recebeu como referencia — pega vazamento contextual que o regex nao cobre,
    ex.: 'Conheco nada / Qual cidade ?')."""
    vendedor_norm = {_sem_acento(v) for v in linhas_vendedor}
    out = []
    for b in bolhas:
        nb = _sem_acento(b)
        if _RE_VOZ_MODELO.search(nb) or nb in vendedor_norm:
            continue
        out.append(b)
    return out


def prompt_juiz(hist: list[dict]) -> list:
    sys = (
        "Voce e um JUIZ offline de um corpus de vendas por WhatsApp (acompanhante/Elite Baby). "
        "M = a modelo (vendedora), C = o cliente. Recebe o transcript COMPLETO de uma conversa simulada "
        "e mede a CONDUTA da modelo. Voce esta CEGO a qual variante de prompt gerou isto. "
        "Seja conservador: variacao de estilo NAO e violacao; so marque quebra clara de regra."
    )
    return [SystemMessage(sys), HumanMessage("TRANSCRIPT:\n" + render_hist(hist))]


# --------------------------------------------------------------------------- medidas determinísticas
EMDASH = re.compile(r"[—–]")            # — –
EMOJI_WL = re.compile(r"[\U0001F970\U0001F60A]")  # 🥰 😊 (whitelist da voz)
EMOJI_ANY = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F000-\U0001F0FF←-⇿⬀-⯿]"
)
PRICE = re.compile(r"\bR?\$?\s?\d{3,4}\b|\bmil\b|\b\d\.\d{3}\b", re.I)
TIME = re.compile(r"\b\d{1,2}\s*[:h]\s*\d{0,2}\b|\b[aà]s?\s*\d{1,2}\b|\b\d{1,2}\s*(?:da|de)\s*(?:manh[aã]|tarde|noite)\b", re.I)
INCLUSO = re.compile(r"beijo|oral|namoradinha|carinhos|sem camisinha|incluso", re.I)
# Bug #2 (disclosure interno): a IA deve PEDIR a foto da portaria, nunca prometer guiar a subida
# nem entregar a unidade (apto/quarto) — isso e da modelo humana pos-foto, com a IA pausada
# (CONTEXT.md "Foto de portaria"). GOLD = pede foto da portaria; FAIL = promete subir / da o apto.
PORTARIA = re.compile(r"foto[^.\n]{0,30}portaria|manda[^.\n]{0,30}portaria", re.I)
SUBIR_FAIL = re.compile(
    r"jeito de subir|como subir|pode subir|j[aá] sobe|sobe direto|te dou o caminho|"
    r"n[uú]mero d[oe]\s*(apart|apto|quarto)|apart(amento)?\s*\d|quarto\s*\d|apto\s*\d",
    re.I,
)


def n_bolhas(s: str) -> int:
    return len([x for x in re.split(r"\n\s*\n", s) if x.strip()])


def n_palavras(s: str) -> int:
    return len(re.findall(r"\S+", s))


def medidas_deterministicas(hist: list[dict]) -> dict:
    mt = [h["bolhas"] for h in hist if h["lado"] == "M"]
    ci = next((i for i, b in enumerate(mt) if PRICE.search(b)), -1)
    cot = mt[ci] if ci >= 0 else ""
    return {
        "cotou_det": ci >= 0,
        "turno_cotacao_det": ci + 1 if ci >= 0 else -1,
        "n_palavras_cotacao": n_palavras(cot) if ci >= 0 else None,
        "n_bolhas_cotacao": n_bolhas(cot) if ci >= 0 else None,
        "emoji_cotacao": len(EMOJI_ANY.findall(cot)) if ci >= 0 else None,
        "emoji_wl_cotacao": len(EMOJI_WL.findall(cot)) if ci >= 0 else None,
        "ancora_n1": bool(ci >= 0 and ci + 1 < len(mt) and TIME.search(mt[ci + 1])),
        "incluso_det": bool(INCLUSO.search(" ".join(mt))),
        "pediu_portaria": bool(PORTARIA.search(" ".join(mt))),
        "prometeu_subir": bool(SUBIR_FAIL.search(" ".join(mt))),
        "em_dash_total": sum(len(EMDASH.findall(b)) for b in mt),
        "emoji_total_modelo": sum(len(EMOJI_ANY.findall(b)) for b in mt),
    }


# --------------------------------------------------------------------------- loop
async def conversa(vend, cli, juiz, variant_tag: str, system: str, persona_tag: str, persona_desc: str, rep: int, k: int) -> dict:
    hist: list[dict] = []
    for _ in range(k):
        c = await cli.ainvoke(prompt_cliente(persona_desc, hist))
        hist.append({"lado": "C", "bolhas": c.bolhas.strip()})
        if c.encerrou:
            break
        v = await vend.ainvoke(msgs_vendedor(system, hist))
        hist.append({"lado": "M", "bolhas": (v.content or "").strip()})
    det = medidas_deterministicas(hist)
    try:
        ver = await juiz.ainvoke(prompt_juiz(hist))
        vj = ver.model_dump()
    except Exception as e:  # noqa: BLE001
        vj = {"erro_juiz": str(e)[:200]}
    return {"variant": variant_tag, "persona": persona_tag, "rep": rep, "transcript": hist, **det, **vj}


def resumo_por_variante(medidas: list[dict]) -> list[dict]:
    by: dict[str, list[dict]] = {}
    for m in medidas:
        by.setdefault(m["variant"], []).append(m)
    out = []
    for tag, ms in by.items():
        n = len(ms)
        cot = [m for m in ms if m.get("n_palavras_cotacao") is not None]
        nc = len(cot) or 1
        def pct(key):
            return round(100 * sum(1 for m in ms if m.get(key)) / n, 0)
        out.append({
            "variant": tag, "n": n, "n_cotou": sum(1 for m in ms if m.get("cotou_det")),
            "media_palavras_cotacao": round(sum(m["n_palavras_cotacao"] for m in cot) / nc, 1) if cot else None,
            "media_bolhas_cotacao": round(sum(m["n_bolhas_cotacao"] for m in cot) / nc, 2) if cot else None,
            "pct_cotacao_le2bolhas": round(100 * sum(1 for m in cot if m["n_bolhas_cotacao"] <= 2) / nc, 0) if cot else None,
            "pct_cotacao_le16palavras": round(100 * sum(1 for m in cot if m["n_palavras_cotacao"] <= 16) / nc, 0) if cot else None,
            "emoji_no_turno_cotacao": sum(m["emoji_cotacao"] for m in cot) if cot else None,
            "pct_ancora_n1": pct("ancora_n1"),
            "pct_incluso": pct("incluso_det"),
            "pct_pediu_portaria": pct("pediu_portaria"),
            "pct_prometeu_subir": pct("prometeu_subir"),
            "pct_calor": pct("f_warmth_all"),
            "pct_rep_robotica": pct("repeticao_robotica"),
            "pct_empurrao": pct("f_glued_urgency"),
            "pct_fugiu_preco": pct("fugiu_preco"),
            "violacoes": sum(1 for m in ms if m.get("violacao")),
            "em_dash_total": sum(m["em_dash_total"] for m in ms),
            "emoji_total_modelo": sum(m["emoji_total_modelo"] for m in ms),
            "desfechos": {d: sum(1 for m in ms if m.get("desfecho") == d) for d in
                          ("fechou_logistica", "engajou", "silenciou", "desviou", "objecao_preco")},
        })
    return out


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--variante", required=True)
    ap.add_argument("--tag-base", default="base")
    ap.add_argument("--tag-variante", default="variante")
    ap.add_argument("--personas", default="preco_no_abridor,faz_x_quanto,decidido,sumido_rapido,info_depois_preco,preco_sensivel")
    ap.add_argument("--n-rep", type=int, default=2)
    ap.add_argument("--k", type=int, default=8)
    ap.add_argument("--conc", type=int, default=6)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    s = Settings()
    vend = criar_chat_deepseek(s, temperature=s.chat_temperature)              # FIEL ao chat #1 de prod
    # DeepSeek faz structured output por FUNCTION CALLING (tool), nao por response_format=json_schema
    # (igual a extracao #2 de prod, que forca a tool registrar_extracao); o default novo do langchain-openai
    # (json_schema) devolve 400 "response_format unavailable" no endpoint DeepSeek.
    cli = criar_chat_deepseek(s).with_structured_output(FalaCliente, method="function_calling")
    juiz = criar_chat_deepseek(s).with_structured_output(Veredito, method="function_calling")
    print(f"Vendedor = {nome_modelo(vend)} (temp {s.chat_temperature}) | cliente/juiz = {nome_modelo(criar_chat_deepseek(s))}", file=sys.stderr)

    variantes = [(a.tag_base, carrega_prompt(a.base)), (a.tag_variante, carrega_prompt(a.variante))]
    personas = [p.strip() for p in a.personas.split(",") if p.strip()]
    celulas = [(tag, sys_p, p, rep) for tag, sys_p in variantes for p in personas for rep in range(a.n_rep)]
    print(f"{len(celulas)} conversas ({len(variantes)} variantes x {len(personas)} personas x {a.n_rep} reps), k={a.k}", file=sys.stderr)

    sem = asyncio.Semaphore(a.conc)

    async def runner(tag, sys_p, p, rep):
        async with sem:
            try:
                return await conversa(vend, cli, juiz, tag, sys_p, p, PERSONAS[p], rep, a.k)
            except Exception as e:  # noqa: BLE001
                print(f"FALHA {tag}/{p}#{rep}: {e}", file=sys.stderr)
                return None

    medidas = [m for m in await asyncio.gather(*(runner(*c) for c in celulas)) if m]
    resumo = resumo_por_variante(medidas)

    saida = {
        "config": {"vendedor_modelo": nome_modelo(vend), "temp": s.chat_temperature,
                   "variantes": [v[0] for v in variantes], "personas": personas,
                   "n_rep": a.n_rep, "k": a.k, "n_conversas": len(medidas)},
        "resumo": resumo,
        "por_celula": [{k: m[k] for k in m if k != "transcript"} for m in medidas],
        "transcripts": medidas,
    }
    json.dump(saida, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(json.dumps(resumo, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
