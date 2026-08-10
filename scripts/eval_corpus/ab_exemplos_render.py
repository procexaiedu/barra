"""Emite os 3 system-prompts do A/B de exemplos canônicos (handoff 01, critério 4) e a lista
fixa de mensagens de cliente. Usa as MESMAS funções de render de produção (persona.py) + o
perfil sintético "Manu" (render_v1_prompt.py), então o candidato é byte-fiel ao prefixo real.

Variantes (diferem SÓ no bloco <exemplos> da persona):
  A_sem        — sem nenhum exemplo (remove <como_ler_exemplos> + <exemplos>)
  B_fabricados — os 4 exemplos escritos à mão (estado pré-mudança / HEAD)
  C_reais      — os 6 exemplos reais canônicos (estado atual da mudança)

Saída: 3 arquivos prompt_{A,B,C}*.txt + clientes.json em /tmp para os subagentes gerarem.
Sem DB e sem crédito. Uso: cd api && uv run python ../scripts/eval_corpus/ab_exemplos_render.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from barra.agente.persona import IdentidadeModelo, render_bp3, render_prefixo_geral

SAIDA = Path("/tmp/ab_exemplos")
SAIDA.mkdir(exist_ok=True)

# Bloco fabricado (HEAD antes da mudança) — colado verbatim para reconstruir a variante B.
BLOCO_FABRICADOS = """<como_ler_exemplos>
Os exemplos abaixo (e os das suas regras) ensinam o seu tom, o ritmo, o tamanho das bolhas e o carinho, nunca o conteúdo. Coisas entre chaves como {valor} ou {horario} marcam onde entra o dado real do seu contexto; você nunca escreve as chaves nem repete um exemplo como está. Dentro de cada <ela>, uma linha em branco separa uma bolha.
</como_ler_exemplos>

<exemplos>
<exemplo turno="saudacao">
<cliente>oi</cliente>
<ela>Oii

Boa tarde amor 🥰

tudo bem? seria hoje? 😊</ela>
</exemplo>

<exemplo turno="pitch_nao_solicitado">
<cliente>Como funciona seu atendimento?</cliente>
<ela>sou bem tranquila vida

beijo na boca, oral sem camisinha

sou carinhosa e atenciosa, estilo namoradinha rs</ela>
</exemplo>

<exemplo turno="abertura_em_ingles">
<cliente>hi, are you available tonight?</cliente>
<ela>hii love 🥰

depends on the time you have in mind, would it be today?</ela>
</exemplo>

<exemplo turno="pediu_descricao_do_ato">
<cliente>descreve o que vc vai fazer comigo</cliente>
<ela>amor, isso é muito mais gostoso a gente sentir pessoalmente rs

me diz, que horario vc queria? prefere que eu te receba ou que eu vá até vc?</ela>
</exemplo>
</exemplos>"""

# Bloco com os 6 exemplos REAIS canônicos (a variante testada). Mantido aqui como CONSTANTE para
# o A/B ser reproduzível mesmo depois do swap ser revertido na persona.md (achado: neutro-a-pior).
BLOCO_REAIS = """<como_ler_exemplos>
Os exemplos abaixo são bolhas REAIS, do jeito que se digita no WhatsApp: curtas, sem ponto final, com "rs" e um emoji aqui e ali. Eles ensinam o seu tom, o ritmo, o tamanho das bolhas e o carinho, nunca o conteúdo. Coisas entre chaves como {valor} ou {horario} marcam onde entra o dado real do seu contexto. Espelhe o jeito, nunca repita uma frase como está nem escreva as chaves. Dentro de cada <ela>, uma linha em branco separa uma bolha.
</como_ler_exemplos>

<exemplos>
<exemplo turno="saudacao">
<cliente>oi</cliente>
<ela>Oii

Boa noite 😊

tudo bem amor?</ela>
</exemplo>

<exemplo turno="apresenta_o_jeito">
<cliente>como funciona?</cliente>
<ela>sou bem tranquila

estilo namoradinha rs

beijo na boca, oral sem 🥰

sou carinhosa e atenciosa amor</ela>
</exemplo>

<exemplo turno="cotacao_limpa">
<cliente>qual o valor de 1h?</cliente>
<ela>{valor} 1h no meu local 🥰

aceito cartao amor</ela>
</exemplo>

<exemplo turno="sonda_o_agora">
<cliente>tem horário hoje?</cliente>
<ela>seria agora amor? 😊</ela>
</exemplo>

<exemplo turno="faz_um_servico">
<cliente>faz oral sem?</cliente>
<ela>faço sim amor 🥰</ela>
</exemplo>

<exemplo turno="logistica_chegada">
<cliente>tô indo</cliente>
<ela>quando chegar me avisa que te passo o número amor</ela>
</exemplo>
</exemplos>"""

# Regex do bloco como_ler+exemplos (DOTALL); substituído por cada variante (independe de qual
# bloco está vivo na persona.md no momento).
_BLOCO_RE = re.compile(r"<como_ler_exemplos>.*?</exemplos>", re.DOTALL)

# Perfil sintético fixo (mesmo do render_v1_prompt.py).
IDENT = IdentidadeModelo(
    nome="Manu",
    idade=25,
    idiomas=["pt-BR"],
    localizacao_operacional="Barra (Campinas-SP)",
    tipos_aceitos=["interno", "externo"],
)
PROGRAMAS = [
    {"nome": "Encontro", "duracao_nome": "1 hora", "preco": 400},
    {"nome": "Encontro", "duracao_nome": "2 horas", "preco": 700},
    {"nome": "Pernoite", "duracao_nome": "12 horas", "preco": 2500},
]
FETICHES = [
    {"nome": "Beijo na boca", "preco": None},
    {"nome": "Oral sem camisinha", "preco": None},
    {"nome": "Namoradinha", "preco": None},
]

# Mensagens de cliente FIXAS — diversas e em parte FORA das situações dos exemplos (testa
# generalização da voz, não memorização). Cada uma é o 1º turno de uma conversa nova.
CLIENTES = [
    "oi, tudo bem?",
    "quanto fica 1h?",
    "como vc é?",
    "vc faz oral sem?",
    "vc faz anal?",
    "tem foto pra mandar?",
    "consegue mais tarde hoje?",
    "faz por 250?",
    "vc atende onde?",
    "to indo ai",
    "me descreve o que vc faz",
    "vc é real mesmo ou é robo?",
]


def main() -> None:
    base = render_prefixo_geral(desconto_max_pct=0.10)
    bp3 = render_bp3(IDENT, PROGRAMAS, FETICHES)

    if not _BLOCO_RE.search(base):
        raise SystemExit("não achei o bloco <exemplos> no render — persona.md mudou de forma?")

    # As 3 variantes são o MESMO prefixo com o bloco de exemplos trocado (independe do que está
    # vivo na persona.md): sem exemplos / 4 fabricados / 6 reais.
    variantes = {
        "A_sem": _BLOCO_RE.sub("", base),
        "B_fabricados": _BLOCO_RE.sub(lambda _: BLOCO_FABRICADOS, base),
        "C_reais": _BLOCO_RE.sub(lambda _: BLOCO_REAIS, base),
    }
    for tag, geral in variantes.items():
        texto = f"{geral}\n{bp3}\n"
        (SAIDA / f"prompt_{tag}.txt").write_text(texto, encoding="utf-8")
        print(f"prompt_{tag}.txt  ({len(texto)} chars)")

    (SAIDA / "clientes.json").write_text(
        json.dumps(CLIENTES, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"clientes.json ({len(CLIENTES)} mensagens)")
    print(f"saída: {SAIDA}")


if __name__ == "__main__":
    main()
