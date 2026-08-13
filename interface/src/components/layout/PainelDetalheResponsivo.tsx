"use client"

import type { ReactNode } from "react"
import { X } from "lucide-react"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import {
  Sheet,
  SheetBody,
  SheetClose,
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
          {/* max-w-full: a 375px o 96vw deixava ~15px de backdrop — sobra fina
              demais para acertar o toque e o único jeito de fechar. */}
          <SheetContent side="right" className="w-full max-w-full sm:w-[440px]">
            <SheetHeader className="flex-row items-center justify-between gap-3">
              <SheetTitle>{tituloDetalhe}</SheetTitle>
              <SheetClose
                render={
                  <Button variant="ghost" size="icon-sm" aria-label="Fechar">
                    <X size={18} strokeWidth={1.5} />
                  </Button>
                }
              />
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
