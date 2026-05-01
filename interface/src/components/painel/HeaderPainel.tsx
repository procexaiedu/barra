"use client"

import { useEffect, useState } from "react"
import { TriangleAlert } from "lucide-react"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { formatData, formatHorario } from "@/lib/formatters"
import type { ModeloAtiva } from "@/tipos/painel"

export function HeaderPainel({
  modeloAtiva,
  modelosAtivasCount,
}: {
  modeloAtiva: ModeloAtiva | null
  modelosAtivasCount: number
}) {
  const [agora, setAgora] = useState(new Date())

  useEffect(() => {
    const interval = setInterval(() => setAgora(new Date()), 60_000)
    return () => clearInterval(interval)
  }, [])

  const isoAgora = agora.toISOString()

  return (
    <div className="flex items-center justify-between px-8 pb-4 pt-8">
      <h1 className="font-serif text-[40px] font-medium leading-[48px] tracking-[-0.02em] text-text-primary">
        Painel
      </h1>
      <div className="flex items-center gap-6">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.08em] text-text-muted">
            MODELO
          </p>
          {modeloAtiva ? (
            <div className="flex items-center gap-2">
              <p className="text-base font-semibold text-text-primary">
                {modeloAtiva.nome}
              </p>
              {modelosAtivasCount > 1 && (
                <Tooltip>
                  <TooltipTrigger render={<span />} className="inline-flex">
                    <TriangleAlert size={16} className="text-warn-500" />
                  </TooltipTrigger>
                  <TooltipContent>há {modelosAtivasCount} modelos ativas</TooltipContent>
                </Tooltip>
              )}
            </div>
          ) : (
            <p className="text-base font-semibold text-text-muted">Nenhuma modelo ativa</p>
          )}
        </div>
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.08em] text-text-muted">
            AGORA
          </p>
          <p className="font-mono text-base font-semibold text-text-primary">
            {formatData(isoAgora)} · {formatHorario(isoAgora)}
          </p>
        </div>
      </div>
    </div>
  )
}
