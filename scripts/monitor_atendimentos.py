"""Vigia de prod em dois estágios: detecta barato, julga caro.

Estágio 1 (este script, custo zero): a cada tick do launchd, lê o banco de prod e pergunta "mudou
alguma coisa?". Na esmagadora maioria dos ticks a resposta é não — e aí o script morre em silêncio
sem gastar um token. Sem esse portão, acompanhar prod de 5 em 5 minutos seriam ~288 invocações de
LLM por dia para olhar uma tela parada.

Estágio 2 (`claude -p`, só quando há novidade): recebe um briefing JSON já montado — a thread do
atendimento, o estado, e a mecânica de cada turno vinda do Langfuse — e julga a conduta contra o
CONTEXT.md/ADRs. O briefing carrega tudo que o julgamento precisa, então o estágio 2 roda sem rede
e com ferramentas de leitura apenas.

O estado vive em `~/.barra-monitor/estado.json` (fora do repo). Ele é o que impede o mesmo turno de
ser julgado — e notificado — a cada tick: a janela de leitura é folgada de propósito (cobre vários
ticks, para uma falha isolada não abrir buraco) e a deduplicação é por id de mensagem, não por
tempo.

Somente leitura em prod. Não envia nada a cliente, não escreve no banco.

Uso:
    uv run python scripts/monitor_atendimentos.py --dry-run   # mostra o briefing, não chama o LLM
    uv run python scripts/monitor_atendimentos.py             # tick real (o launchd chama assim)
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import tail_prod  # mesmo diretório: reusa a leitura de prod e o casamento com o Langfuse

BASE = Path(os.environ.get("BARRA_MONITOR_DIR", Path.home() / ".barra-monitor"))
ESTADO = BASE / "estado.json"
BRIEFINGS = BASE / "briefings"
RELATORIOS = BASE / "relatorios"
LOG = BASE / "monitor.log"

# Folga sobre o intervalo do launchd (5 min): um tick que falhe ou demore não deixa buraco, porque o
# seguinte reencontra as mesmas mensagens — a dedup por id é que evita o retrabalho.
JANELA = timedelta(minutes=30)
# Poda do estado: ids mais velhos que isto não voltam a aparecer na janela, então não precisam ficar.
RETENCAO = timedelta(hours=6)
TIMEOUT_JULGAMENTO_S = 600


def log(msg: str) -> None:
    linha = f"{datetime.now(UTC).isoformat(timespec='seconds')} {msg}"
    print(linha)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(linha + "\n")


def carregar_estado() -> dict[str, Any]:
    if not ESTADO.exists():
        return {"mensagens_vistas": {}, "atendimentos_conhecidos": []}
    try:
        return json.loads(ESTADO.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        # Estado corrompido não pode travar o vigia: recomeça limpo. O custo é uma rodada de
        # re-notificação, preferível a ficar cego até alguém perceber.
        log("estado ilegível — recomeçando do zero")
        return {"mensagens_vistas": {}, "atendimentos_conhecidos": []}


def salvar_estado(estado: dict[str, Any], agora: datetime) -> None:
    corte = (agora - RETENCAO).isoformat()
    estado["mensagens_vistas"] = {
        mid: ts for mid, ts in estado["mensagens_vistas"].items() if ts > corte
    }
    ESTADO.write_text(json.dumps(estado, ensure_ascii=False, indent=2), encoding="utf-8")


def notificar(titulo: str, corpo: str) -> None:
    """Notificação nativa do macOS. Best-effort: falhar aqui não pode abortar o tick."""
    script = (
        f"display notification {json.dumps(corpo)} "
        f"with title {json.dumps('Barra — prod')} subtitle {json.dumps(titulo)}"
    )
    exe = shutil.which("osascript")
    if not exe:
        log("osascript não encontrado (notificação perdida)")
        return
    try:
        subprocess.run([exe, "-e", script], check=False, capture_output=True, timeout=10)  # noqa: S603
    except (OSError, subprocess.SubprocessError):
        log("osascript falhou (notificação perdida)")


def montar_briefing(novos: list[dict[str, Any]], contexto: list[dict[str, Any]]) -> dict[str, Any]:
    """Briefing do estágio 2: o que é novo + a thread completa de cada atendimento tocado.

    O julgamento precisa do histórico para saber se a IA se repetiu, se já tinha cotado ou se o
    estado devia ter avançado — um turno isolado não sustenta veredito nenhum.
    """
    ids_tocados = {t.get("atendimento_id") for t in novos}
    threads: dict[str, list[dict[str, Any]]] = {}
    for t in contexto:
        aid = t.get("atendimento_id")
        if aid in ids_tocados and aid is not None:
            threads.setdefault(aid, []).append(t)
    return {
        "gerado_em": datetime.now(UTC).isoformat(),
        "turnos_novos": novos,
        "threads": threads,
    }


PROMPT = """Você é o vigia do agente da Elite Baby em PRODUÇÃO. Um atendimento se mexeu agora.

Briefing (JSON com os turnos novos e a thread completa de cada atendimento tocado):
{briefing}

Leia o briefing e julgue a CONDUTA do agente contra `CONTEXT.md`, os ADRs em `docs/adr/` e os
prompts em `api/src/barra/agente/prompts/`. Perguntas que importam:

- A IA respondeu? Se um cliente ficou sem resposta, por quê (ia_pausada? qual motivo?).
- A cotação bate com a tabela da modelo? Houve desconto além do piso?
- A extração pegou tipo de atendimento, duração e horário corretamente (campo `desfecho` do trace)?
- O estado do atendimento avançou como a máquina de estados manda?
- Vazou algo que não devia: dado de outra modelo, endereço/unidade cedo demais, PII, quebra de persona?
- A mecânica travou: erro de tool, guard bloqueando saída, Pix parado em revisão?

Escreva o relatório em `{relatorio}` (markdown, conciso — só o que merece atenção humana; se estiver
tudo certo, diga isso em duas linhas). Não altere nenhum outro arquivo e não toque em produção.

Ao final, imprima UMA linha começando com `VEREDITO:` seguida de `ok` ou de um resumo do problema
mais grave em até 100 caracteres."""


def julgar(briefing_path: Path, relatorio_path: Path, modelo: str) -> str:
    """Estágio 2. Ferramentas de leitura apenas — o vigia observa, nunca conserta sozinho."""
    prompt = PROMPT.format(
        briefing=briefing_path.read_text(encoding="utf-8"), relatorio=relatorio_path
    )
    exe = shutil.which("claude")
    if not exe:
        return "claude CLI não encontrado no PATH"
    try:
        r = subprocess.run(  # noqa: S603 — argv fixo, sem shell; o prompt é dado nosso, não entrada de terceiro
            [exe, "-p", prompt, "--model", modelo, "--allowedTools", "Read,Grep,Glob,Write"],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_JULGAMENTO_S,
            cwd=str(Path(__file__).resolve().parents[1]),
        )
    except subprocess.TimeoutExpired:
        return "julgamento estourou o tempo"
    except OSError as e:
        return f"claude CLI indisponível ({e})"
    if r.returncode != 0:
        return f"claude saiu com {r.returncode}: {r.stderr.strip()[:200]}"
    for linha in reversed(r.stdout.strip().splitlines()):
        if linha.strip().startswith("VEREDITO:"):
            return linha.split("VEREDITO:", 1)[1].strip()
    return r.stdout.strip()[-200:] or "sem veredito"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--dry-run", action="store_true", help="monta o briefing e para (não chama o LLM)"
    )
    p.add_argument("--modelo", default="sonnet", help="modelo do estágio 2")
    p.add_argument(
        "--janela", type=tail_prod.parse_janela, default=JANELA, help="quanto olhar para trás"
    )
    args = p.parse_args()

    for d in (BASE, BRIEFINGS, RELATORIOS):
        d.mkdir(parents=True, exist_ok=True)

    agora = datetime.now(UTC)
    primeira_vez = not ESTADO.exists()
    dsn = tail_prod.get_settings().database_url
    mensagens = tail_prod.buscar_mensagens(dsn, agora - args.janela, "prod")
    estado = carregar_estado()
    if not mensagens:
        if primeira_vez and not args.dry_run:
            # Marco zero com prod quieto. Sem gravar aqui, o estado só nasceria junto com a primeira
            # mensagem futura — que o bootstrap abaixo então engoliria calado, perdendo exatamente o
            # primeiro atendimento que este vigia existe para acompanhar.
            salvar_estado(estado, agora)
            log("marco zero: janela vazia, estado inicializado")
        return 0

    vistos = estado["mensagens_vistas"]
    conhecidos = set(estado["atendimentos_conhecidos"])

    turnos = tail_prod.montar_turnos(
        mensagens, tail_prod.buscar_traces(agora - args.janela, "producao"), agora
    )
    novos = [t for t in turnos if t["id"] not in vistos]
    if not novos:
        return 0  # o caso comum: nada mudou, nenhum token gasto

    if primeira_vez and not args.dry_run:
        # Marco zero: sem estado prévio, tudo que já está no banco parece "novo". Julgar e notificar
        # esse acervo seria uma enxurrada retroativa — o vigia existe para o que acontece daqui pra
        # frente. Registra o que já passou e sai calado.
        for t in novos:
            vistos[t["id"]] = t["created_at"]
        estado["atendimentos_conhecidos"] = sorted(
            conhecidos | {t["atendimento_id"] for t in novos if t["atendimento_id"]}
        )
        salvar_estado(estado, agora)
        log(f"marco zero: {len(novos)} turno(s) pré-existentes registrados sem julgar")
        return 0

    atendimentos_novos = sorted(
        {
            t["atendimento_id"]
            for t in novos
            if t["atendimento_id"] and t["atendimento_id"] not in conhecidos
        }
    )
    rotulo = {t["atendimento_id"]: f"{t['modelo_nome']} #{t.get('numero_curto')}" for t in novos}

    carimbo = agora.strftime("%Y%m%dT%H%M%S")
    briefing_path = BRIEFINGS / f"{carimbo}.json"
    relatorio_path = RELATORIOS / f"{carimbo}.md"
    briefing_path.write_text(
        json.dumps(montar_briefing(novos, turnos), ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    log(
        f"novidade: {len(novos)} turno(s), {len(atendimentos_novos)} atendimento(s) novo(s) → {briefing_path.name}"
    )

    if args.dry_run:
        print(briefing_path.read_text(encoding="utf-8"))
        return 0

    veredito = julgar(briefing_path, relatorio_path, args.modelo)
    log(f"veredito: {veredito}")

    for aid in atendimentos_novos:
        notificar(f"Atendimento novo — {rotulo.get(aid, aid)}", veredito)

    for t in novos:
        vistos[t["id"]] = t["created_at"]
    estado["atendimentos_conhecidos"] = sorted(
        conhecidos | {t["atendimento_id"] for t in novos if t["atendimento_id"]}
    )
    salvar_estado(estado, agora)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
