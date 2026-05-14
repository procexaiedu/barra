"use client"

import { useEffect, useState } from "react"
import { api, ApiError } from "@/lib/api"

type Run = {
  ts: string
  fila: "barra" | "agente"
  stampLog?: string
  duracaoSec?: number
  runsExecuted?: number
  runsCap?: number
  tasksTotal?: number
  pass?: number
  rework?: number
  blocked?: number
  timeout?: number
  exception?: number
  trunc?: number
  nothing?: number
  humanOnly?: number
  invocacoes?: number
  marcosTotal?: number
  stopReason?: string
  commitsAheadOrigin?: number | null
  log?: string
}

function formatDuracao(sec?: number) {
  if (!sec || sec <= 0) return "—"
  const m = Math.round(sec / 60)
  if (m < 60) return `${m} min`
  const h = Math.floor(m / 60)
  const r = m % 60
  return r === 0 ? `${h}h` : `${h}h${r}min`
}

function formatTs(iso: string) {
  try {
    return new Date(iso).toLocaleString("pt-BR")
  } catch {
    return iso
  }
}

export default function OvernightDevPage() {
  const [ultimo, setUltimo] = useState<Run | null>(null)
  const [historico, setHistorico] = useState<Run[]>([])
  const [erro, setErro] = useState<string | null>(null)
  const [carregando, setCarregando] = useState(true)

  useEffect(() => {
    let cancelado = false
    async function carrega() {
      setCarregando(true)
      try {
        const u = await api<Run>("/v1/dev/overnight/ultimo")
        const h = await api<{ itens: Run[] }>("/v1/dev/overnight/historico?limite=10")
        if (cancelado) return
        setUltimo(u)
        setHistorico(h.itens)
        setErro(null)
      } catch (e) {
        if (cancelado) return
        const msg = e instanceof ApiError ? e.detail : "Falha ao carregar overnight"
        setErro(msg)
      } finally {
        if (!cancelado) setCarregando(false)
      }
    }
    void carrega()
    return () => {
      cancelado = true
    }
  }, [])

  if (carregando) {
    return <p className="text-text-muted">Carregando…</p>
  }
  if (erro) {
    return (
      <div className="space-y-2">
        <h1 className="text-2xl font-semibold">Overnight</h1>
        <p className="text-warn-500">{erro}</p>
        <p className="text-text-muted text-sm">
          Esta página lê <code>.claude/state/overnight/runs.jsonl</code> da máquina local. Rode{" "}
          <code>scripts\overnight-loop.ps1</code> ou <code>scripts\overnight-agente.ps1</code> para gerar dados.
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold">Overnight</h1>
        <p className="text-text-muted text-sm">
          Inspeção do último pipeline autônomo + tendência das últimas execuções.
        </p>
      </header>

      {ultimo && <CardUltimo run={ultimo} />}

      <section className="space-y-2">
        <h2 className="text-lg font-medium">Histórico</h2>
        <TabelaHistorico itens={historico} />
      </section>
    </div>
  )
}

function CardUltimo({ run }: { run: Run }) {
  const isBarra = run.fila === "barra"
  return (
    <section className="rounded-lg border border-border bg-card p-5 space-y-3">
      <div className="flex items-baseline justify-between gap-4">
        <div>
          <span className="text-xs uppercase tracking-wide text-text-muted">Último ({run.fila})</span>
          <p className="text-sm">{formatTs(run.ts)}</p>
        </div>
        <span className="text-xs text-text-muted">
          {run.stopReason ?? "—"} · {formatDuracao(run.duracaoSec)}
        </span>
      </div>

      {isBarra ? (
        <div className="grid grid-cols-4 gap-3 text-sm">
          <Metric label="PASS" value={run.pass ?? 0} good />
          <Metric label="rework" value={run.rework ?? 0} warn={!!run.rework} />
          <Metric label="blocked" value={run.blocked ?? 0} warn={!!run.blocked} />
          <Metric label="timeout" value={run.timeout ?? 0} warn={!!run.timeout} />
          <Metric label="exception" value={run.exception ?? 0} warn={!!run.exception} />
          <Metric label="nothing-to-do" value={run.nothing ?? 0} />
          <Metric label="human-only" value={run.humanOnly ?? 0} />
          <Metric label="trunc" value={run.trunc ?? 0} />
        </div>
      ) : (
        <div className="grid grid-cols-3 gap-3 text-sm">
          <Metric label="marcos" value={run.marcosTotal ?? 0} good={!!run.marcosTotal} />
          <Metric label="invocacoes" value={run.invocacoes ?? 0} />
          <Metric label="duracao" value={formatDuracao(run.duracaoSec)} />
        </div>
      )}

      {run.commitsAheadOrigin != null && run.commitsAheadOrigin > 0 && (
        <p className="text-warn-500 text-sm">
          ⚠ main local está <strong>{run.commitsAheadOrigin}</strong> commit(s) à frente de origin/main.
          Rode <code>git push origin main</code> quando pronto.
        </p>
      )}

      {run.log && (
        <p className="text-text-muted text-xs">
          log: <code className="break-all">{run.log}</code>
        </p>
      )}
    </section>
  )
}

function Metric({
  label,
  value,
  good,
  warn,
}: {
  label: string
  value: number | string
  good?: boolean
  warn?: boolean
}) {
  const cls = good ? "text-success-500" : warn ? "text-warn-500" : ""
  return (
    <div>
      <p className="text-xs text-text-muted">{label}</p>
      <p className={`text-lg font-medium ${cls}`}>{value}</p>
    </div>
  )
}

function TabelaHistorico({ itens }: { itens: Run[] }) {
  if (itens.length === 0) return <p className="text-text-muted text-sm">Sem histórico.</p>
  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="w-full text-sm">
        <thead className="bg-muted text-left text-xs uppercase tracking-wide text-text-muted">
          <tr>
            <th className="px-3 py-2">Quando</th>
            <th className="px-3 py-2">Fila</th>
            <th className="px-3 py-2">Total</th>
            <th className="px-3 py-2">PASS / rework</th>
            <th className="px-3 py-2">Duração</th>
            <th className="px-3 py-2">Stop</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {itens.map((r, i) => (
            <tr key={`${r.ts}-${i}`}>
              <td className="px-3 py-2">{formatTs(r.ts)}</td>
              <td className="px-3 py-2">{r.fila}</td>
              <td className="px-3 py-2">{r.tasksTotal ?? r.marcosTotal ?? "—"}</td>
              <td className="px-3 py-2">
                {r.fila === "barra" ? `${r.pass ?? 0} / ${r.rework ?? 0}` : "—"}
              </td>
              <td className="px-3 py-2">{formatDuracao(r.duracaoSec)}</td>
              <td className="px-3 py-2 text-text-muted">{r.stopReason ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
