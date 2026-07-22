"""Tail cronológico do tráfego de produção — uma linha por MENSAGEM, com a mecânica do turno.

Por que existe: o painel `/observabilidade` lista só `direcao='ia'`, então uma mensagem de cliente
que a IA NÃO respondeu (modelo pausada, worker parado, debounce preso) é invisível — foi assim que
8 mensagens ficaram sem resposta sem ninguém notar. Aqui o eixo é o tempo, não a resposta: cliente
e IA na mesma trilha, e a lacuna vira um marcador explícito.

Cruza duas fontes por turno:
- Postgres de prod (SELECT puro, NUNCA escreve): quem falou, o quê, e o estado do atendimento no
  momento (`#N`, estado, tipo, `ia_pausada` + motivo).
- Langfuse: o root span do turno já é autossuficiente (`core/tracing.resumir_trace_turno`), então o
  `desfecho` (extração, erros de tool, reoferta, disclosure), latência e custo saem do nível de
  trace — sem garimpar as ~20 observations do LangChain.

O casamento msg↔trace NUNCA chuta em silêncio (mesma disciplina de `core/ancora_feedback`): o campo
`trace_match` diz se foi `texto` (substring exata da resposta — o agente quebra a fala em bolhas,
então o conteúdo da bolha é substring do `resposta_ia` do trace), `tempo` (só proximidade temporal
dentro do mesmo atendimento) ou `ausente`.

Uso (da raiz do repo):
    uv run python scripts/tail_prod.py                  # últimos 30 min
    uv run python scripts/tail_prod.py --desde 24h
    uv run python scripts/tail_prod.py --follow         # ao vivo, poll de 5s
    uv run python scripts/tail_prod.py --desde 2h --json # p/ o Claude Code ler
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import unicodedata
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

_RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_RAIZ / "api" / "src"))

import psycopg  # noqa: E402
from dotenv import load_dotenv  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402

from barra.settings import get_settings  # noqa: E402

# Janela de busca do trace em torno da mensagem. Assimétrica de propósito: o trace nasce ANTES da
# mensagem ser gravada (o turno roda, depois o envio persiste), então a folga para trás é larga e a
# para frente é só skew de relógio.
TOLERANCIA_ANTES = timedelta(minutes=6)
TOLERANCIA_DEPOIS = timedelta(minutes=1)
# Abaixo disto o texto é curto demais p/ um match por substring significar alguma coisa ("ok", "sim").
MIN_CHARS_MATCH = 12

_SQL = """
SELECT
  m.id, m.created_at, m.direcao::text AS direcao, m.tipo::text AS tipo, m.conteudo,
  m.media_object_key, m.conversa_id, m.atendimento_id,
  cl.telefone AS cliente_telefone, cl.nome AS cliente_nome,
  mo.nome AS modelo_nome, mo.status::text AS modelo_status,
  at.numero_curto, at.estado::text AS estado, at.tipo_atendimento::text AS tipo_atendimento,
  at.ia_pausada, at.ia_pausada_motivo::text AS ia_pausada_motivo,
  at.pix_status::text AS pix_status
FROM barravips.mensagens m
JOIN barravips.conversas co ON co.id = m.conversa_id
JOIN barravips.clientes  cl ON cl.id = co.cliente_id
JOIN barravips.modelos   mo ON mo.id = co.modelo_id
LEFT JOIN barravips.atendimentos at ON at.id = m.atendimento_id
WHERE m.created_at >= %(desde)s
  AND (%(origem)s = 'todos' OR co.origem = %(origem)s)
ORDER BY m.created_at ASC, m.id ASC
"""


def parse_janela(txt: str) -> timedelta:
    """'30m'/'2h'/'7d' -> timedelta."""
    m = re.fullmatch(r"(\d+)([mhd])", txt.strip().lower())
    if not m:
        raise argparse.ArgumentTypeError(f"janela inválida: {txt!r} (use 30m, 2h, 7d)")
    n, unidade = int(m.group(1)), m.group(2)
    return {"m": timedelta(minutes=n), "h": timedelta(hours=n), "d": timedelta(days=n)}[unidade]


def normalizar(s: str) -> str:
    """Casefold sem acento e sem espaço redundante — base do match por substring."""
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFD", s or "") if unicodedata.category(c) != "Mn"
    )
    return re.sub(r"\s+", " ", sem_acento).strip().casefold()


def buscar_mensagens(dsn: str, desde: datetime, origem: str) -> list[dict[str, Any]]:
    """Mensagens da janela, em ordem cronológica. Somente leitura."""
    with psycopg.connect(dsn, connect_timeout=15, row_factory=dict_row) as conn:
        conn.read_only = True
        res = conn.execute(_SQL, {"desde": desde, "origem": origem})
        return list(res.fetchall())


def buscar_traces(desde: datetime, ambiente: str) -> list[dict[str, Any]]:
    """Traces `turno` da janela, reduzidos ao que o tail mostra. Best-effort: Langfuse fora do ar
    (ou sem chave) degrada para lista vazia — o tail do Postgres continua valendo."""
    settings = get_settings()
    if not settings.langfuse_public_key:
        return []
    try:
        from langfuse import Langfuse

        client = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key or "",
            host=settings.langfuse_host,
        )
        # Filtra environment/name no cliente em vez de na query: o volume da janela é baixo e evita
        # depender da assinatura exata do endpoint entre versões do SDK.
        pagina = client.api.trace.list(from_timestamp=desde, limit=100)
    except Exception as e:  # telemetria indisponível não pode derrubar o tail
        print(f"[aviso] Langfuse indisponível ({type(e).__name__}); seguindo só com o Postgres")
        return []

    traces = []
    for t in pagina.data:
        if getattr(t, "environment", None) != ambiente:
            continue
        saida = t.output if isinstance(t.output, dict) else {}
        traces.append(
            {
                "trace_id": t.id,
                "timestamp": t.timestamp,
                "session_id": t.session_id,
                "resposta_ia": str(saida.get("resposta_ia") or ""),
                "desfecho": saida.get("desfecho") or {},
                "latencia_s": getattr(t, "latency", None),
                "custo": getattr(t, "total_cost", None),
                "level": getattr(t, "level", None),
            }
        )
    return traces


def casar_trace(msg: dict[str, Any], traces: list[dict[str, Any]]) -> tuple[dict | None, str]:
    """Acha o trace do turno que produziu esta mensagem da IA.

    Devolve `(trace, motivo)` onde motivo ∈ {texto, tempo, ausente}. Preferência por conteúdo
    (determinístico) sobre proximidade temporal (palpite) — e o motivo viaja para o output para que
    quem lê saiba de qual dos dois se trata, em vez de receber um match silencioso.
    """
    janela = [
        t
        for t in traces
        if msg["created_at"] - TOLERANCIA_ANTES
        <= t["timestamp"]
        <= msg["created_at"] + TOLERANCIA_DEPOIS
    ]
    if msg.get("atendimento_id"):
        alvo = str(msg["atendimento_id"])
        do_atendimento = [t for t in janela if t["session_id"] in (alvo, None)]
        janela = do_atendimento or janela
    if not janela:
        return None, "ausente"

    conteudo = normalizar(msg["conteudo"])
    if len(conteudo) >= MIN_CHARS_MATCH:
        casados = [t for t in janela if conteudo in normalizar(t["resposta_ia"])]
        if len(casados) == 1:
            return casados[0], "texto"
        if casados:
            janela = casados  # ambíguo no texto: desempata pelo tempo, mas admite que desempatou

    return min(janela, key=lambda t: abs(t["timestamp"] - msg["created_at"])), "tempo"


def montar_turnos(
    mensagens: list[dict[str, Any]], traces: list[dict[str, Any]], agora: datetime
) -> list[dict[str, Any]]:
    """Enriquece cada mensagem com o trace (só as da IA) e marca as do cliente sem resposta."""
    turnos: list[dict[str, Any]] = []
    for i, m in enumerate(mensagens):
        turno = dict(m)
        turno["id"] = str(m["id"])
        turno["conversa_id"] = str(m["conversa_id"])
        turno["atendimento_id"] = str(m["atendimento_id"]) if m["atendimento_id"] else None
        turno["created_at"] = m["created_at"].isoformat()

        if m["direcao"] == "ia":
            trace, motivo = casar_trace(m, traces)
            turno["trace_match"] = motivo
            turno["trace"] = (
                {**trace, "timestamp": trace["timestamp"].isoformat()} if trace else None
            )
        else:
            # Lacuna: nenhuma resposta da IA depois desta mensagem, na mesma conversa.
            respondida = any(
                p["direcao"] == "ia" and p["conversa_id"] == m["conversa_id"]
                for p in mensagens[i + 1 :]
            )
            turno["sem_resposta_s"] = (
                None if respondida else int((agora - m["created_at"]).total_seconds())
            )
        turnos.append(turno)
    return turnos


# --- render ------------------------------------------------------------------------------------

_COR = sys.stdout.isatty()


def _c(txt: str, cod: str) -> str:
    return f"\033[{cod}m{txt}\033[0m" if _COR else txt


def _escopo(t: dict[str, Any]) -> str:
    partes = [t["modelo_nome"]]
    if t.get("numero_curto"):
        partes.append(f"#{t['numero_curto']} {t.get('estado')}/{t.get('tipo_atendimento') or '?'}")
    return " ".join(partes)


def _mecanica(t: dict[str, Any]) -> str:
    tr = t.get("trace")
    if not tr:
        return _c("        ⚙ sem trace no Langfuse", "90")
    cab = [f"trace {tr['trace_id'][:8]} ({t['trace_match']})"]
    if tr.get("latencia_s") is not None:
        cab.append(f"{tr['latencia_s']:.1f}s")
    if tr.get("custo"):
        cab.append(f"R${tr['custo']:.4f}".replace(".", ","))
    desfecho = tr.get("desfecho") or {}
    for chave, valor in desfecho.items():
        cab.append(f"{chave}={json.dumps(valor, ensure_ascii=False)}")
    return _c("        ⚙ " + " · ".join(cab), "90")


def render(turnos: list[dict[str, Any]]) -> None:
    for t in turnos:
        hora = datetime.fromisoformat(t["created_at"]).astimezone().strftime("%d/%m %H:%M:%S")
        corpo = t["conteudo"] if t["tipo"] == "texto" else f"[{t['tipo']}] {t['conteudo']}".strip()
        if t["direcao"] == "cliente":
            quem = t.get("cliente_nome") or t["cliente_telefone"]
            print(f"{hora} {_c('←', '36')} {_escopo(t)}  {quem}")
            print(f'        "{corpo}"')
            if t.get("sem_resposta_s") is not None:
                minutos = t["sem_resposta_s"] // 60
                pausa = (
                    f" · ia_pausada ({t['ia_pausada_motivo']})"
                    if t.get("ia_pausada")
                    else " · IA ativa"
                )
                print(_c(f"        ⚠ {minutos}min sem resposta{pausa}", "33"))
        else:
            print(f"{hora} {_c('→', '32')} {_escopo(t)}  IA")
            print(f'        "{corpo}"')
            print(_mecanica(t))


def main() -> int:
    # `Settings` lê `.env` relativo ao cwd; carregar o de `api/` aqui deixa o script rodável da raiz
    # do repo sem depender de onde foi invocado. Fica DENTRO do main de propósito: importar o módulo
    # (os testes fazem isso) não pode vazar o .env pro os.environ do processo.
    load_dotenv(_RAIZ / "api" / ".env")
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument(
        "--desde", type=parse_janela, default=timedelta(minutes=30), help="janela: 30m, 2h, 7d"
    )
    p.add_argument("--follow", action="store_true", help="acompanha ao vivo (poll)")
    p.add_argument("--intervalo", type=int, default=5, help="segundos entre polls no --follow")
    p.add_argument("--json", action="store_true", help="saída JSON (para agentes/pipes)")
    p.add_argument("--origem", default="prod", choices=["prod", "e2e", "todos"])
    p.add_argument("--ambiente", default="producao", help="environment do trace no Langfuse")
    args = p.parse_args()

    janela = args.desde
    dsn = get_settings().database_url
    if not dsn:
        print("DATABASE_URL ausente (api/.env)", file=sys.stderr)
        return 1

    agora = datetime.now(UTC)
    desde = agora - janela
    mensagens = buscar_mensagens(dsn, desde, args.origem)
    turnos = montar_turnos(mensagens, buscar_traces(desde, args.ambiente), agora)

    if args.json:
        print(json.dumps(turnos, ensure_ascii=False, indent=2, default=str))
        return 0

    if not turnos:
        print(f"(nenhuma mensagem em {args.origem} nos últimos {janela})")
    render(turnos)

    if not args.follow:
        return 0

    vistos = {t["id"] for t in turnos}
    print(_c(f"\n— acompanhando (poll {args.intervalo}s, Ctrl-C para sair) —", "90"))
    try:
        while True:
            time.sleep(args.intervalo)
            agora = datetime.now(UTC)
            recentes = buscar_mensagens(
                dsn, agora - max(janela, timedelta(minutes=10)), args.origem
            )
            novas = [m for m in recentes if str(m["id"]) not in vistos]
            if novas:
                render(
                    montar_turnos(
                        novas, buscar_traces(novas[0]["created_at"], args.ambiente), agora
                    )
                )
                vistos.update(str(m["id"]) for m in novas)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
