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
      <h1 className="font-serif text-[28px] font-medium leading-none text-text-primary">
        Modelos
      </h1>
      {!esconderAdicionar && (
        <Button variant="primary" size="sm" onClick={onAdicionar}>
          <UserPlus size={14} strokeWidth={1.5} />
          Adicionar modelo
        </Button>
      )}
    </header>
  )
}
