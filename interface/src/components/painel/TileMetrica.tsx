import { Info, TrendingDown, TrendingUp, Minus } from "lucide-react"
import { Card } from "@/components/ui/card"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { cn } from "@/lib/utils"

interface Tendencia {
  delta: number
  label: string
  inverso?: boolean
  formatDelta?: (n: number) => string
}

function TendenciaTag({ delta, label, inverso, formatDelta }: Tendencia) {
  const neutro = delta === 0
  const positivo = inverso ? delta < 0 : delta > 0
  const negativo = inverso ? delta > 0 : delta < 0

  const Icon = neutro ? Minus : positivo ? TrendingUp : TrendingDown
  const sinal = delta > 0 ? "+" : ""
  const valorFormatado = formatDelta ? formatDelta(Math.abs(delta)) : String(Math.abs(delta))

  return (
    <p
      className={cn(
        "mt-1.5 flex items-center gap-1 text-[11px] font-medium",
        neutro && "text-text-muted",
        positivo && "text-success-500",
        negativo && "text-danger-500"
      )}
    >
      <Icon size={11} strokeWidth={2} aria-hidden />
      {sinal}{valorFormatado} {label}
    </p>
  )
}

export function TileMetrica({
  label,
  valor,
  colorClass,
  tooltip,
  onClick,
  isZero,
  tendencia,
  flashing,
  metricaSecundaria,
}: {
  label: string
  valor: string
  colorClass?: string
  tooltip?: string
  onClick?: () => void
  isZero?: boolean
  tendencia?: Tendencia
  flashing?: boolean
  metricaSecundaria?: { label: string; valor: string }
}) {
  return (
    <Card
      className={cn(
        "relative rounded-lg bg-card p-5",
        onClick && "cursor-pointer transition-colors hover:bg-surface-hover active:bg-surface-pressed",
        flashing && "tile-update-flash"
      )}
      onClick={onClick}
      role={onClick ? "button" : undefined}
      tabIndex={onClick ? 0 : undefined}
      onKeyDown={onClick ? (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onClick() } } : undefined}
    >
      <dl className="flex h-full flex-col">
        <dt className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-[0.08em] text-text-muted">
          {label}
          {tooltip ? (
            <Tooltip>
              <TooltipTrigger
                type="button"
                aria-label={`Sobre ${label}`}
                className="inline-flex items-center text-text-muted/60 transition-colors hover:text-text-primary focus-visible:text-text-primary focus-visible:outline-none"
                onClick={(e) => e.stopPropagation()}
              >
                <Info size={11} strokeWidth={1.75} aria-hidden />
              </TooltipTrigger>
              <TooltipContent side="top">
                {tooltip}
              </TooltipContent>
            </Tooltip>
          ) : null}
        </dt>
        <dd
          className={cn(
            "mt-2 font-sans text-[36px] font-medium leading-[44px] tracking-[-0.02em]",
            isZero ? "text-text-muted" : (colorClass ?? "text-text-primary")
          )}
        >
          {valor}
        </dd>
        {tendencia ? <TendenciaTag {...tendencia} /> : null}
        {metricaSecundaria && (
          <div className="mt-auto flex items-center justify-between border-t border-border-subtle pt-2.5 pb-0.5">
            <span className="text-[11px] text-text-muted">{metricaSecundaria.label}</span>
            <span className="font-mono text-[11px] font-medium text-text-secondary">{metricaSecundaria.valor}</span>
          </div>
        )}
      </dl>
    </Card>
  )
}
