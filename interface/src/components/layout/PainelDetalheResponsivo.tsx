"use client"

import type { ReactNode } from "react"
import { cn } from "@/lib/utils"
import {
  Sheet,
  SheetBody,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import { useIsMobile } from "@/hooks/useMediaQuery"

/**
 * Layout master-detail responsivo. Em `lg+` renderiza lista + detalhe lado a
 * lado (grid `[Npx_1fr]`); em mobile a lista ocupa a tela e o detalhe abre num
 * Sheet deslizante.
 *
 * O estado `detalheAberto` é CONTROLADO pela página — não derive de "tem item
 * selecionado", pois vários hooks auto-selecionam o primeiro item no load (o
 * que abriria o drawer sozinho). Ligue `detalheAberto`/`onFecharDetalhe` ao tap
 * explícito do usuário na lista.
 */
export function PainelDetalheResponsivo({
  lista,
  detalhe,
  detalheAberto,
  onFecharDetalhe,
  tituloDetalhe = "Detalhe",
  gridClassName = "lg:grid-cols-[360px_minmax(0,1fr)]",
  className,
}: {
  lista: ReactNode
  detalhe: ReactNode
  detalheAberto: boolean
  onFecharDetalhe: () => void
  tituloDetalhe?: string
  gridClassName?: string
  className?: string
}) {
  const isMobile = useIsMobile()

  if (isMobile) {
    return (
      <div className={cn("min-h-0", className)}>
        <div className="h-full overflow-y-auto">{lista}</div>
        <Sheet
          open={detalheAberto}
          onOpenChange={(aberto) => {
            if (!aberto) onFecharDetalhe()
          }}
        >
          <SheetContent side="right" className="w-full max-w-[96vw] sm:w-[440px]">
            <SheetHeader>
              <SheetTitle>{tituloDetalhe}</SheetTitle>
            </SheetHeader>
            <SheetBody className="p-0">{detalhe}</SheetBody>
          </SheetContent>
        </Sheet>
      </div>
    )
  }

  return (
    <div className={cn("grid min-h-0 gap-4", gridClassName, className)}>
      <div className="min-h-0 overflow-y-auto">{lista}</div>
      <div className="min-h-0 overflow-y-auto">{detalhe}</div>
    </div>
  )
}
