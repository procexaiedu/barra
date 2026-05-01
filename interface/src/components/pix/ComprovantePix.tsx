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
    <section className="rounded-lg border border-border bg-card p-5">
      <h3 className="text-xs font-semibold uppercase tracking-[0.08em] text-text-muted">
        Comprovante
      </h3>
      <div className="mt-3 flex items-center gap-2">
        <Paperclip size={16} strokeWidth={1.5} className="text-text-muted" />
        <span className="font-mono text-[13px] text-text-primary">
          {pix.nome_arquivo}
        </span>
        <span className="font-mono text-xs text-text-muted">
          · {formatBytes(pix.tamanho)}
        </span>
      </div>
      <div className="mt-3">
        {indisponivel ? (
          <Tooltip>
            <TooltipTrigger
              render={
                <span className="inline-flex">
                  <Button variant="secondary" size="sm" disabled>
                    <Eye size={16} strokeWidth={1.5} />
                    Visualizar comprovante
                  </Button>
                </span>
              }
            />
            <TooltipContent>Arquivo não está mais disponível</TooltipContent>
          </Tooltip>
        ) : erro ? (
          <Button variant="danger" size="sm" onClick={onTentarNovamente}>
            <Eye size={16} strokeWidth={1.5} />
            Tentar novamente
          </Button>
        ) : (
          <Button
            variant="secondary"
            size="sm"
            onClick={onVisualizar}
            disabled={carregando}
          >
            <Eye size={16} strokeWidth={1.5} />
            {carregando ? "Carregando…" : "Visualizar comprovante"}
          </Button>
        )}
      </div>
    </section>
  )
}
