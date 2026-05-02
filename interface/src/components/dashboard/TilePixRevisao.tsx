"use client"

import { useRouter } from "next/navigation"
import { ArrowRight, Receipt } from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { cn } from "@/lib/utils"

interface Props {
  total: number
}

export function TilePixRevisao({ total }: Props) {
  const router = useRouter()
  const semPendentes = total === 0
  const irParaFila = () => router.push("/pix?status=em_revisao")

  return (
    <section
      aria-label="Pix em revisão pendentes"
      className={cn(
        "flex items-center justify-between gap-4 rounded-lg bg-card p-6 ring-1 ring-foreground/10",
        !semPendentes && "border-l-3 border-l-warn-500"
      )}
    >
      <div className="flex flex-col gap-1">
        <span className="text-xs font-medium uppercase tracking-[0.08em] text-text-muted">
          Pix em revisão pendentes (agora)
        </span>
        <span className="font-sans text-[40px] font-medium leading-[48px] text-text-primary">
          {total}
        </span>
        <span className="text-[13px] text-text-muted">
          Não filtrado por período — fila operacional ativa.
        </span>
      </div>

      {semPendentes ? (
        <Tooltip>
          <TooltipTrigger
            render={
              <span
                role="button"
                aria-disabled="true"
                tabIndex={0}
                className="inline-flex h-9 cursor-not-allowed items-center gap-2 rounded-md bg-transparent px-3 text-sm font-medium text-text-muted opacity-60 outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
              />
            }
          >
            <Receipt size={16} strokeWidth={1.5} />
            Ir para fila
            <ArrowRight size={16} strokeWidth={1.5} />
          </TooltipTrigger>
          <TooltipContent side="left">Sem Pix aguardando decisão.</TooltipContent>
        </Tooltip>
      ) : (
        <Button variant="secondary" size="lg" onClick={irParaFila} className="gap-2">
          <Receipt size={16} strokeWidth={1.5} />
          Ir para fila
          <ArrowRight size={16} strokeWidth={1.5} />
        </Button>
      )}
    </section>
  )
}
