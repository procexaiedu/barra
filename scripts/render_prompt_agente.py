"""Renderiza, num único arquivo, TUDO que chega ao LLM do agente num turno.

Não é código de produção — é uma ferramenta de visualização. Usa as MESMAS funções de
render de `barra.agente` (persona, regras, BP3, contexto dinâmico, reminder, tools) para
não haver byte-drift com o que o `prepare_context` monta de verdade.

O payload real ao Sonnet tem 3 segmentos, nesta ordem:
  1. tools        (BP_TOOLS)   — catálogo de ferramentas, cacheado
  2. system       (BP_GERAL + BP_MODELO) — persona+regras (geral) + dado da modelo
  3. messages     (janela)     — Human/AI + contexto dinâmico e reminder colados na CAUDA

As partes GERAIS (tools, persona, regras) são byte-idênticas em produção. As partes
POR-MODELO e DINÂMICAS dependem do banco a cada turno — aqui usamos dados de EXEMPLO,
claramente rotulados, só para mostrar a ESTRUTURA e o lugar de cada coisa.

Uso:
    cd api && uv run python ../scripts/render_prompt_agente.py
Gera: prompt_agente_renderizado.md na raiz do repo.
"""

import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

# Permite rodar de qualquer cwd: garante src/ no path.
_SRC = Path(__file__).resolve().parent.parent / "api" / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from barra.agente.ferramentas import INPUT_EXAMPLES, STRICT_TOOLS, TOOLS  # noqa: E402
from barra.agente.llm import build_tools_para_bind  # noqa: E402
from barra.agente.persona import (  # noqa: E402
    IdentidadeModelo,
    render_aup_saida,
    render_bp3,
    render_contexto_dinamico,
    render_prefixo_geral,
    render_reminder,
)

# Valores GERAIS que em prod vêm de settings (fixados aqui p/ não depender de .env).
DESCONTO_MAX_PCT = 0.15  # settings.desconto_max_pct
TTL_TOOLS = "1h"  # settings.cache_ttl_geral

# ───────────────────────── dados de EXEMPLO (por-modelo / dinâmico) ─────────────────────────
MODELO_EXEMPLO = IdentidadeModelo(
    nome="Bia",
    idade=24,
    idiomas=["pt-BR", "en-US"],
    localizacao_operacional="Zona Sul, São Paulo",
    tipos_aceitos=["interno", "externo"],
)

PROGRAMAS_EXEMPLO = [
    {"nome": "Encontro", "duracao_nome": "1 hora", "preco": 800},
    {"nome": "Encontro", "duracao_nome": "2 horas", "preco": 1400},
    {"nome": "Pernoite", "duracao_nome": "12 horas (pernoite)", "preco": 4000},
]

FETICHES_EXEMPLO = [
    {"nome": "Beijo na boca", "preco": None},
    {"nome": "Inversão", "preco": 300},
]

_hoje = date(2026, 6, 16)
_agora = datetime(2026, 6, 16, 14, 30)
CONTEXTO_DINAMICO_EXEMPLO = {
    "data_atual": _hoje,
    "hora_atual": "14:30",
    "numero_curto": 7,
    "estado": "Qualificado",
    "slots_faltantes": ["horário", "endereço"],
    "proximo_passo": "confirmar horário e fechar a cotação",
    "tipo_atendimento": "externo",
    "urgencia": "alta",
    "pix_status": "ainda não pedido",
    "data_desejada": _hoje,
    "horario_desejado": None,
    "endereco": None,
    "bairro": None,
    "recorrente": True,
    "observacoes_internas": "cliente educado, já fechou antes sem enrolar",
    "ultimo_motivo_perda": None,
    "cliente_nome": "Marcos",
    "historico_anteriores": "fechou 2x (R$2.8k)",
    "dia_ja_sondado": False,
    "bloqueios": [
        {
            "inicio": _agora + timedelta(hours=3),
            "fim": _agora + timedelta(hours=5),
            "proximo_livre": _agora + timedelta(hours=5, minutes=30),
        }
    ],
    "disponibilidade": [
        {
            "dia": "seg",
            "hora_inicio": "10:00",
            "hora_fim": "22:00",
            "data_inicio": "01/06/2026",
            "data_fim": None,
        }
    ],
}

JANELA_EXEMPLO = [
    ("Human (cliente)", "oi, tudo bem?"),
    ("AI (IA)", "oii amor tudo otimo e vc? rs"),
    ("Human (cliente)", "to bem! queria saber como funciona com vc"),
    ("AI (IA)", "conta pra mim o que vc procura que eu te explico direitinho 😋"),
    ("Human (cliente) — msg ATUAL deste turno", "quero hoje, quanto fica 2h?"),
]


def _sec(titulo: str) -> str:
    return f"\n\n{'=' * 90}\n## {titulo}\n{'=' * 90}\n"


def main() -> None:
    partes: list[str] = []
    partes.append(
        "# Prompt completo do agente (renderização de UM turno)\n\n"
        "Ordem real do payload ao Sonnet: **tools → system (BP_GERAL + BP_MODELO) → "
        "messages (janela; contexto dinâmico + reminder colados na ÚLTIMA mensagem)**.\n\n"
        "- **GERAL** = byte-idêntico p/ todas as modelas (cacheado 1x).\n"
        "- **POR-MODELO / DINÂMICO** = vem do banco a cada turno; aqui é dado de EXEMPLO só p/ "
        "mostrar a estrutura.\n"
    )

    # 1. TOOLS (BP_TOOLS) — GERAL
    tools = build_tools_para_bind(
        TOOLS, ttl=TTL_TOOLS, strict_tools=STRICT_TOOLS, exemplos=INPUT_EXAMPLES
    )
    partes.append(_sec("SEGMENTO 1 — tools (BP_TOOLS) · GERAL · cacheado"))
    partes.append(
        f"São {len(tools)} ferramentas. O `cache_control` fica na última. JSON como vai à API:\n"
    )
    partes.append("```json\n" + json.dumps(tools, ensure_ascii=False, indent=2) + "\n```")

    # 2a. BP_GERAL (persona + regras) — GERAL
    partes.append(_sec("SEGMENTO 2a — system / BP_GERAL (persona + regras) · GERAL · cacheado"))
    partes.append("```\n" + render_prefixo_geral(DESCONTO_MAX_PCT) + "\n```")

    # 2b. BP_MODELO (identidade + programas + fetiches) — POR-MODELO (exemplo)
    partes.append(
        _sec("SEGMENTO 2b — system / BP_MODELO (identidade + programas + fetiches) · POR-MODELO")
    )
    partes.append("> Dados de EXEMPLO (modelo fictícia 'Bia'). Em prod vêm de `barravips.modelos`.\n")
    partes.append(
        "```\n" + render_bp3(MODELO_EXEMPLO, PROGRAMAS_EXEMPLO, FETICHES_EXEMPLO) + "\n```"
    )

    # 3. JANELA + contexto dinâmico + reminder
    partes.append(_sec("SEGMENTO 3 — messages (janela deslizante) · POR-PAR cliente↔modelo"))
    partes.append(
        "> Conteúdo de EXEMPLO. O contexto dinâmico e o reminder são COLADOS na última "
        "HumanMessage (a msg atual do cliente), nesta ordem: reminder → msg → contexto.\n"
    )
    linhas_janela = []
    for papel, texto in JANELA_EXEMPLO[:-1]:
        linhas_janela.append(f"[{papel}]\n{texto}\n")
    partes.append("```\n" + "\n".join(linhas_janela) + "```")

    partes.append(_sec("SEGMENTO 3 (cauda) — a ÚLTIMA HumanMessage do turno, montada"))
    papel_ultima, texto_ultima = JANELA_EXEMPLO[-1]
    reminder = render_reminder(CONTEXTO_DINAMICO_EXEMPLO["estado"]).strip()
    contexto = render_contexto_dinamico(**CONTEXTO_DINAMICO_EXEMPLO)
    cauda = f"{reminder}\n\n{texto_ultima}\n\n{contexto}"
    partes.append(
        "> reminder só entra com ≥8 turnos da IA na janela; mostrado aqui p/ visualização.\n"
    )
    partes.append(f"```\n[{papel_ultima}]\n{cauda}\n```")

    # 4. AUP guard — judge SEPARADO (não entra no payload do chat)
    partes.append(_sec("APÊNDICE — AUP output-guard (judge SEPARADO, NÃO entra no chat)"))
    partes.append(
        "> Roda numa chamada própria sobre a SAÍDA da IA (ADR 0016). Não afeta o cache do chat.\n"
    )
    partes.append("```\n" + render_aup_saida() + "\n```")

    saida = Path(__file__).resolve().parent.parent / "prompt_agente_renderizado.md"
    saida.write_text("\n".join(partes), encoding="utf-8")
    print(f"escrito: {saida}")


if __name__ == "__main__":
    main()
