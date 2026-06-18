"""Teste do DeepSeek V4 Flash como chat principal — cenário 1 (interno happy path).

Roda o AGENTE REAL (grafo, com as tools que a conversa aciona) conduzindo o MESMO roteiro de
cliente que o Sonnet conduziu (print do rig Lucia), e gera um HTML de 3 colunas
(Cliente | Sonnet baseline | V4 Flash) para cotejo de voz/jogada lado a lado.

Mecanismo (espelha tests/agente/test_e2e_conducao.py): troca `criar_chat_anthropic` por
`criar_chat_openrouter(deepseek-v4-flash)` no módulo do grafo — SEM tocar o código de prod — e
reusa `evals.e2e.rodar_e2e` + `ClienteRoteirizado`.

§0: gasta crédito OpenRouter (do dev, fora da regra Anthropic); o DB é seed efêmero + ROLLBACK
(não persiste). Não manda WhatsApp, não roda em prod. Read-only de fato sobre o banco.

Rodar de `api/`:  uv run python evals/teste_v4flash_cenario1.py
"""

from __future__ import annotations

# ruff: noqa: E402 — script standalone: os imports de `barra`/`evals` exigem o sys.path montado abaixo.
import asyncio
import html
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]  # api/
sys.path.insert(0, str(ROOT))  # acha o pacote `evals`
sys.path.insert(0, str(ROOT / "src"))  # acha o pacote `barra`

from langchain_core.messages import SystemMessage
from langchain_openai import ChatOpenAI
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from barra.settings import Settings, get_settings
from evals.e2e.cliente import ClienteRoteirizado
from evals.e2e.perfil import PerfilCaso
from evals.e2e.runner import rodar_e2e

MODELO_CANDIDATO = "deepseek/deepseek-v4-flash"


def _chat_v4(settings: Settings) -> ChatOpenAI:
    """Chat candidato via OpenRouter. SEM `require_parameters` — probe provou que nenhum provider
    do deepseek-v4-flash o satisfaz (404 'no endpoints' SEMPRE, mesmo sem tool_choice). E forced
    tool-choice (extração #2) funciona sem ele. O `cache_control` (Anthropic-only) é neutralizado
    à parte. Nota p/ a migração: o criar_chat_openrouter de PROD força require_parameters — terá
    de virar provider-aware (ligado p/ Anthropic-via-OR, desligado p/ DeepSeek)."""
    return ChatOpenAI(
        model=MODELO_CANDIDATO,
        api_key=settings.openrouter_api_key,
        base_url="https://openrouter.ai/api/v1",
        max_tokens=settings.anthropic_max_tokens,
        max_retries=2,
        timeout=60.0,
    )


def _neutralizar_cache_anthropic() -> None:
    """Remove os 4 breakpoints de `cache_control` (Anthropic-only) que o grafo injeta — inúteis
    pro DeepSeek e a causa do 404 de roteamento. Patcha só as REFERÊNCIAS nos nós que as usam
    (não toca o código de prod): tools cruas (ChatOpenAI converte), system em string pura, janela
    no-op. Caching do DeepSeek é implícito no provider, não precisa de marcação."""
    import barra.core.llm as core_llm
    from barra.agente.nos import llm as no_llm_mod
    from barra.agente.nos import prepare_context as prep_mod

    # O judge do output-guard (#3) importa criar_chat_openrouter em import tardio (require_parameters
    # → 404 no DeepSeek; ao falhar, o guard escala e PAUSA o turno). Substitui por uma versão sem
    # require_parameters. Único outro consumidor (extração barata) já foi desligado.
    core_llm.criar_chat_openrouter = lambda settings, *, modelo: ChatOpenAI(  # type: ignore[assignment]
        model=modelo,
        api_key=settings.openrouter_api_key,
        base_url="https://openrouter.ai/api/v1",
        max_tokens=settings.anthropic_max_tokens,
        max_retries=2,
        timeout=60.0,
    )

    no_llm_mod.build_tools_para_bind = lambda tools, **_k: list(tools)  # type: ignore[assignment]

    def _system_sem_cache(
        *, geral_md: str, ttl_geral: str, modelo_md: str | None = None, **_k: Any
    ) -> list[SystemMessage]:
        msgs = [SystemMessage(content=geral_md)]
        if modelo_md is not None:
            msgs.append(SystemMessage(content=modelo_md))
        return msgs

    prep_mod.build_system_messages = _system_sem_cache  # type: ignore[assignment]
    prep_mod.marcar_cache_na_penultima = lambda mensagens, **_k: mensagens  # type: ignore[assignment]

    # _custo.PRECO_OPENROUTER[deepseek] só tem input/output; calcular_custo_brl acessa as chaves
    # de cache direto (KeyError mesmo * 0). Completa em runtime com a tarifa real (cache_read
    # ~1/50 do input; DeepSeek não cobra sobretaxa de write). Não edita o arquivo de prod.
    from barra.agente import _custo

    _custo.PRECO_OPENROUTER_USD_PER_MTOK[MODELO_CANDIDATO].update(
        {"cache_read": 0.0028, "cache_write_5m": 0.09, "cache_write_1h": 0.09}
    )


# --- Cenário 1: interno happy path, conduzido pelo Sonnet no rig Lucia (print do dev) ---------
# Falas do CLIENTE (lado verde do print), em ordem. A 1a é a abertura; o resto é o roteiro.
ABERTURA = "Oii, tudo bem?"
ROTEIRO_CLIENTE = [
    "tudo sim! você tá atendendo? qual o valor amor?",
    "isso amor, vou aí sim. quero 1h",
    "hoje sim, pode ser umas 23h?",
    "ah entendi! então consigo 22h hoje, fecha?",
]
# Respostas do SONNET (lado laranja "Procex"), alinhadas turno a turno com (ABERTURA + ROTEIRO).
# Baseline já gravado — custo Anthropic zero. \n separa as bolhas do mesmo turno.
BASELINE_SONNET = [
    "Oii boa noite 😊",
    "Tô sim amor 🥰\nPrograma completo 1h é R$800, 2h R$1.200\nvocê vem no meu local?",
    "Ótimo amor\nseria hoje mesmo?",
    "Ai amor, 23h já é um pouquinho tarde pra mim hoje 🙈\nconsigo até meia-noite não, mas amanhã"
    " cedo a partir das 10h consigo, ou qualquer horário dentro do dia que preferir",
    "22h fecha sim amor 🥰\nme passa seu nome e te mando o endereço completo",
]

# Modelo sintética: preços alinhados ao print (1h=800, 2h=1200) p/ a cotação ser comparável.
# Agenda fica livre (sem bloqueio/disponibilidade seedada) — divergência de aceitar/recusar
# horário pode ser do SETUP, não do modelo (anotado no HTML).
MODELO = {
    "nome": "Manu",
    "tipo_atendimento_aceito": ["interno", "externo"],
    "programas": [
        {"nome": "Encontro", "duracao_nome": "1 hora", "horas": 1, "preco": 800},
        {"nome": "Encontro", "duracao_nome": "2 horas", "horas": 2, "preco": 1200},
    ],
}


async def rodar() -> list[dict[str, Any]]:
    from barra.agente import graph as graph_mod

    settings = get_settings()
    # A extração forçada barata usa criar_chat_openrouter de prod (require_parameters → 404 no
    # DeepSeek). Desliga: o forçamento #2 passa a usar o chat principal (V4 Flash), que honra
    # tool_choice sem require_parameters.
    settings.extracao_no_modelo_barato = False
    _neutralizar_cache_anthropic()
    # Injeta o V4 Flash no nó de chat #1 (mesmo ponto do test_e2e_conducao). A extração barata #2
    # e o judge #3 seguem o que está no .env (já são OpenRouter/deepseek).
    graph_mod.criar_chat_anthropic = lambda *a, **k: _chat_v4(settings)  # type: ignore[assignment]
    graph = graph_mod.build_graph(settings)

    perfil = PerfilCaso(
        nome="interno_happy_path_v4flash",
        abertura=ABERTURA,
        modelo=MODELO,
        roteiro_cliente=ROTEIRO_CLIENTE,
        tipo_esperado="interno",
        desfecho_real="convertido_provavel",
        thread_ref="rig_lucia:cenario1_sonnet",
    )
    cliente = ClienteRoteirizado(ROTEIRO_CLIENTE)

    conn = await AsyncConnection.connect(
        settings.database_url, autocommit=False, row_factory=dict_row, prepare_threshold=None
    )
    try:
        res = await rodar_e2e(conn, perfil, cliente, graph=graph, max_turnos=8)
    finally:
        await conn.rollback()  # nada persiste em prod
        await conn.close()

    entradas = [ABERTURA, *ROTEIRO_CLIENTE]
    linhas = []
    for i, t in enumerate(res.turnos):
        linhas.append(
            {
                "cliente": entradas[i] if i < len(entradas) else "(sem input)",
                "sonnet": BASELINE_SONNET[i] if i < len(BASELINE_SONNET) else "—",
                "v4": t.texto or "(sem texto — só tool)",
                "tools": ", ".join(t.tool_calls),
                "estado": (t.estado_final or {}).get("estado"),
            }
        )
    print(
        f"desfecho={res.desfecho_conducao} estado_final={res.estado_final} "
        f"turnos={res.n_turnos} custo_brl={res.custo_brl:.4f}"
    )
    return linhas


def _bolhas(texto: str, lado: str) -> str:
    partes = [html.escape(b) for b in texto.split("\n") if b.strip()]
    return "".join(f'<div class="b {lado}">{p}</div>' for p in partes)


def gerar_html(linhas: list[dict[str, Any]]) -> Path:
    rows = []
    for i, ln in enumerate(linhas, 1):
        tools = (
            f'<span class="tools">tools: {html.escape(ln["tools"])}</span>' if ln["tools"] else ""
        )
        estado = (
            f'<span class="estado">→ {html.escape(str(ln["estado"]))}</span>'
            if ln["estado"]
            else ""
        )
        rows.append(f"""
  <div class="turno">
    <div class="t-num">turno {i}</div>
    <div class="col cliente"><div class="cap">Cliente</div>{_bolhas(ln["cliente"], "c")}</div>
    <div class="col sonnet"><div class="cap">Sonnet (prod)</div>{_bolhas(ln["sonnet"], "v")}</div>
    <div class="col v4"><div class="cap">V4 Flash {estado}</div>{_bolhas(ln["v4"], "v")}{tools}</div>
  </div>""")

    pagina = f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>V4 Flash vs Sonnet — cenário 1</title><style>
  body {{ margin:0; font-family:-apple-system,Segoe UI,Roboto,sans-serif; background:#f0f2f5; color:#111; }}
  .wrap {{ max-width:1100px; margin:0 auto; padding:24px 16px 80px; }}
  h1 {{ font-size:22px; margin:0 0 4px; }}
  .sub {{ color:#555; font-size:13px; margin:0 0 6px; line-height:1.5; }}
  .nota {{ background:#fff7e6; border:1px solid #ffe08a; border-radius:8px; padding:10px 14px;
           font-size:12.5px; color:#7a5c00; margin:14px 0 24px; line-height:1.5; }}
  .turno {{ display:grid; grid-template-columns:1fr 1fr 1fr; gap:10px; background:#fff;
            border:1px solid #e0e0e0; border-radius:12px; padding:14px; margin-bottom:14px; }}
  .t-num {{ grid-column:1/4; font-size:11px; text-transform:uppercase; letter-spacing:.5px;
            color:#889; font-weight:700; margin-bottom:2px; }}
  .cap {{ font-size:11px; font-weight:700; margin-bottom:6px; }}
  .cliente .cap {{ color:#e542a3; }}
  .sonnet .cap {{ color:#b06a00; }}
  .v4 .cap {{ color:#075e54; }}
  .b {{ padding:7px 10px; border-radius:8px; font-size:14px; line-height:1.4; margin-bottom:5px;
        box-shadow:0 1px 1px rgba(0,0,0,.06); white-space:pre-wrap; word-wrap:break-word; }}
  .b.c {{ background:#f3f4f6; }}
  .b.v {{ background:#d9fdd3; }}
  .sonnet .b.v {{ background:#fdeccd; }}
  .estado {{ font-weight:400; color:#075e54; font-size:10px; }}
  .tools {{ display:block; font-size:10.5px; color:#667; font-family:monospace; margin-top:4px; }}
</style></head><body><div class="wrap">
  <h1>V4 Flash vs Sonnet — cenário 1 (interno happy path)</h1>
  <p class="sub">Mesmo roteiro de cliente; agente real com as tools que a conversa aciona.
     Coluna do meio = Sonnet em prod (rig Lucia, já gravado). Coluna da direita = DeepSeek V4 Flash
     conduzindo agora.</p>
  <div class="nota">Modelo sintética "Manu": preços alinhados ao print (1h=800/2h=1200), mas
     <b>agenda livre</b> (sem disponibilidade seedada). Divergência de aceitar/recusar horário pode
     vir do setup, não do modelo. O foco do cotejo é <b>voz</b> e <b>estrutura da jogada</b>.</div>
  {"".join(rows)}
</div></body></html>"""
    saida = ROOT.parent / "v4flash_vs_sonnet_cenario1.html"
    saida.write_text(pagina, encoding="utf-8")
    return saida


async def main() -> None:
    if not os.environ.get("OPENROUTER_API_KEY") and not get_settings().openrouter_api_key:
        sys.exit("OPENROUTER_API_KEY não setado")
    linhas = await rodar()
    saida = gerar_html(linhas)
    print(f"OK -> {saida}")


if __name__ == "__main__":
    asyncio.run(main())
