"use client"

import { UserPlus } from "lucide-react"
import { Button } from "@/components/ui/button"

export function HeaderModelos({
  esconderAdicionar,
  onAdicionar,
}: {
  esconderAdicionar: boolean
  onAdicionar: () => void
}) {
  return (
    <header className="flex items-center justify-between gap-4">
      <h1 className="font-serif text-[40px] font-medium leading-[48px] text-text-primary">
        Modelos
      </h1>
      {!esconderAdicionar && (
        <Button variant="primary" onClick={onAdicionar}>
          <UserPlus size={16} strokeWidth={1.5} />
          Adicionar modelo
        </Button>
      )}
    </header>
  )
}
