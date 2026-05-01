import { Bot, Hand, User } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { formatHorario } from "@/lib/formatters"
import { cn } from "@/lib/utils"
import type { BloqueioAgenda as BloqueioAgendaTipo, EstadoBloqueio, OrigemBloqueio } from "@/tipos/agenda"

const estadoConfig: Record<EstadoBloqueio, { label: string; variant: "active" | "paused" | "closed" }> = {
  bloqueado: { label: "Bloqueado", variant: "paused" },
  em_atendimento: { label: "Em atendimento", variant: "active" },
  concluido: { label: "Concluído", variant: "closed" },
  cancelado: { label: "Cancelado", variant: "paused" },
}

const origemConfig: Record<OrigemBloqueio, { label: string; Icon: typeof Bot }> = {
  ia: { label: "IA", Icon: Bot },
  painel_fernando: { label: "Fernando", Icon: User },
  manual: { label: "Manual", Icon: Hand },
}

export function BloqueioAgenda({
  bloqueio,
  compacto = false,
  onClick,
}: {
  bloqueio: BloqueioAgendaTipo
  compacto?: boolean
  onClick: () => void
}) {
  const estado = estadoConfig[bloqueio.estado]
  const origem = origemConfig[bloqueio.origem]
  const titulo = bloqueio.atendimento?.cliente_nome
    ?? bloqueio.observacao
    ?? "Bloqueio manual"
  const vinculo = bloqueio.atendimento ? `#${bloqueio.atendimento.numero_curto}` : null
  const OrigemIcon = origem.Icon

  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "w-full rounded-lg border border-border bg-card text-left transition-colors hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:outline-none",
        compacto ? "p-2" : "p-3",
        bloqueio.estado === "cancelado" && "opacity-60"
      )}
    >
      <div className="flex items-center gap-2">
        <span className="font-mono text-xs font-medium text-text-muted">
          {formatHorario(bloqueio.inicio)}-{formatHorario(bloqueio.fim)}
        </span>
        {!compacto && <Badge variant={estado.variant}>{estado.label}</Badge>}
      </div>
      <p
        className={cn(
          "mt-1 truncate text-sm font-medium text-text-primary",
          bloqueio.estado === "cancelado" && "line-through"
        )}
      >
        {titulo}
      </p>
      {!compacto && (
        <div className="mt-2 flex items-center gap-2 text-xs text-text-muted">
          <Tooltip>
            <TooltipTrigger render={<span className="inline-flex items-center" />}>
              <OrigemIcon size={16} strokeWidth={1.5} />
            </TooltipTrigger>
            <TooltipContent>{origem.label}</TooltipContent>
          </Tooltip>
          <span>{origem.label}</span>
          {vinculo && <span className="font-mono">{vinculo}</span>}
        </div>
      )}
    </button>
  )
}
