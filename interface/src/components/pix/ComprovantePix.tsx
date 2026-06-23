"use client"

import { Eye, Paperclip } from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { formatBytes } from "./utils"
import type { PixDetalhe } from "@/tipos/pix"

export function ComprovantePix({
  pix,
  comprovanteStatus,
  onVisualizar,
  onTentarNovamente,
}: {
  pix: PixDetalhe
  comprovanteStatus: "idle" | "loading" | "success" | "error"
  onVisualizar: () => void
  onTentarNovamente: () => void
}) {
  const indisponivel = !pix.comprovante_disponivel
  const carregando = comprovanteStatus === "loading"
  const erro = comprovanteStatus === "error"

  return (
    <section className="rounded-lg bg-card p-3 shadow-elev-1 ring-1 ring-border-subtle">
      <div className="flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          <Paperclip size={14} strokeWidth={1.5} className="shrink-0 text-text-muted" />
          <span className="truncate font-mono text-[13px] text-text-primary">
            {pix.nome_arquivo}
          </span>
          <span className="shrink-0 font-mono text-xs text-text-muted">
            · {formatBytes(pix.tamanho)}
          </span>
        </div>
        {indisponivel ? (
          <Tooltip>
            <TooltipTrigger
              render={
                <span className="inline-flex shrink-0">
                  <Button variant="secondary" size="sm" disabled>
                    <Eye size={14} strokeWidth={1.5} />
                    Visualizar comprovante
                  </Button>
                </span>
              }
            />
            <TooltipContent>Arquivo não está mais disponível</TooltipContent>
          </Tooltip>
        ) : erro ? (
          <Button variant="danger" size="sm" className="shrink-0" onClick={onTentarNovamente}>
            <Eye size={14} strokeWidth={1.5} />
            Tentar novamente
          </Button>
        ) : (
          <Button
            variant="secondary"
            size="sm"
            className="shrink-0"
            onClick={onVisualizar}
            disabled={carregando}
          >
            <Eye size={14} strokeWidth={1.5} />
            {carregando ? "Carregando…" : "Visualizar comprovante"}
          </Button>
        )}
      </div>
    </section>
  )
}
