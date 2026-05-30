"use client"

import { AlertTriangle, Info } from "lucide-react"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { cn } from "@/lib/utils"
import { ESCALADA_FAIXAS } from "./utils"

interface Props {
  contagem: number
  nReferencia?: number | null
  onClick?: () => void
}

const PCT_FMT = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 1 })

// Limite superior do eixo: usar o maior entre 100 e atual+10 garante que valores
// críticos extremos (>100% se um atendimento gerar várias escaladas) caibam.
function calcularMax(pct: number): number {
  return Math.max(100, Math.ceil((pct + 10) / 10) * 10)
}

export function BulletEscaladas({ contagem, nReferencia, onClick }: Props) {
  const base = nReferencia ?? 0
  const pct = base > 0 ? (contagem / base) * 100 : 0
  const max = calcularMax(pct)
  const interativo = Boolean(onClick)

  const faixaBom = (ESCALADA_FAIXAS.bom / max) * 100
  const faixaAtencao = (ESCALADA_FAIXAS.atencao / max) * 100
  const posicaoBarra = (pct / max) * 100

  const classificacao =
    pct === 0
      ? "neutra"
      : pct <= ESCALADA_FAIXAS.bom
        ? "bom"
        : pct <= ESCALADA_FAIXAS.atencao
          ? "atencao"
          : "critico"

  const corMarcador = {
    neutra: "var(--text-muted)",
    bom: "var(--success-500)",
    atencao: "var(--warn-500)",
    critico: "var(--danger-500)",
  }[classificacao]

  const conteudo = (
    <>
      <header className="flex items-center gap-2">
        <AlertTriangle size={14} strokeWidth={1.75} aria-hidden className="text-warn-500" />
        <span className="text-xs font-medium uppercase tracking-[0.08em] text-text-muted">
          Atendimentos escalados
        </span>
        <Tooltip>
          <TooltipTrigger
            type="button"
            aria-label="Sobre faixas de escalada"
            onClick={(event) => event.stopPropagation()}
            onKeyDown={(event) => {
              if (event.key === "Enter" || event.key === " ") {
                event.stopPropagation()
              }
            }}
            className="inline-flex items-center text-text-muted transition-colors hover:text-text-primary focus-visible:text-text-primary focus-visible:outline-none"
          >
            <Info size={12} strokeWidth={1.75} aria-hidden />
          </TooltipTrigger>
          <TooltipContent side="top" className="max-w-[280px] text-left leading-snug">
            <p>
              % de atendimentos pausados que viraram escalada para Fernando ou modelo.
              Faixas: <strong>Bom</strong> ≤ {ESCALADA_FAIXAS.bom}%,{" "}
              <strong>Atenção</strong> ≤ {ESCALADA_FAIXAS.atencao}%,{" "}
              <strong>Crítico</strong> &gt; {ESCALADA_FAIXAS.atencao}%.
            </p>
          </TooltipContent>
        </Tooltip>
      </header>

      <div className="flex items-baseline gap-2">
        <span className="font-sans text-[40px] font-medium leading-[48px] text-text-primary tabular-nums">
          {PCT_FMT.format(pct)}%
        </span>
        <span className="text-[13px] text-text-muted">
          {contagem} {contagem === 1 ? "escalada" : "escaladas"}
        </span>
      </div>

      <div
        role="img"
        aria-label={`Escalada em ${PCT_FMT.format(pct)}% — classificação ${classificacao}`}
        className="relative h-7 w-full overflow-hidden rounded-md ring-1 ring-foreground/10"
      >
        <div
          className="absolute inset-y-0 left-0"
          style={{ width: `${faixaBom}%`, background: "var(--success-500)", opacity: 0.18 }}
        />
        <div
          className="absolute inset-y-0"
          style={{
            left: `${faixaBom}%`,
            width: `${faixaAtencao - faixaBom}%`,
            background: "var(--warn-500)",
            opacity: 0.2,
          }}
        />
        <div
          className="absolute inset-y-0"
          style={{
            left: `${faixaAtencao}%`,
            width: `${100 - faixaAtencao}%`,
            background: "var(--danger-500)",
            opacity: 0.18,
          }}
        />
        <div
          className="absolute top-1/2 h-2 rounded-full"
          style={{
            left: 0,
            width: `${Math.min(posicaoBarra, 100)}%`,
            transform: "translateY(-50%)",
            background: corMarcador,
          }}
        />
        <div
          className="absolute top-1/2 h-5 w-1 -translate-y-1/2 rounded-sm"
          style={{
            left: `calc(${Math.min(posicaoBarra, 100)}% - 2px)`,
            background: corMarcador,
          }}
          aria-hidden
        />
      </div>

      <footer className="flex items-center justify-between text-[11px] text-text-muted">
        <div className="flex items-center gap-3">
          <span className="inline-flex items-center gap-1">
            <span aria-hidden className="h-2 w-2 rounded-sm bg-success-500/40" />
            Bom ≤ {ESCALADA_FAIXAS.bom}%
          </span>
          <span className="inline-flex items-center gap-1">
            <span aria-hidden className="h-2 w-2 rounded-sm bg-warn-500/40" />
            Atenção ≤ {ESCALADA_FAIXAS.atencao}%
          </span>
          <span className="inline-flex items-center gap-1">
            <span aria-hidden className="h-2 w-2 rounded-sm bg-danger-500/40" />
            Crítico
          </span>
        </div>
        {base > 0 ? (
          <span className="font-mono tabular-nums">base n={base}</span>
        ) : (
          <span className="font-mono tabular-nums">sem volume</span>
        )}
      </footer>
    </>
  )

  const baseClass =
    "flex flex-col gap-3 rounded-lg bg-card p-6 ring-1 ring-foreground/10 text-left"

  if (interativo) {
    return (
      <div
        role="button"
        tabIndex={0}
        onClick={onClick}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault()
            onClick?.()
          }
        }}
        aria-label="Atendimentos escalados — abrir lista detalhada"
        className={cn(
          baseClass,
          "cursor-pointer transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
        )}
      >
        {conteudo}
      </div>
    )
  }

  return <div className={baseClass}>{conteudo}</div>
}
