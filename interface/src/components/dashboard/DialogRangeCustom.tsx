"use client"

import { useMemo, useState } from "react"
import {
  Dialog,
  DialogContent,
  DialogTitle,
} from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { RangeCalendar } from "@/components/ui/range-calendar"
import { diffDiasInclusivo, hojeBrtIso } from "./utils"

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
  deAtual: string | null
  ateAtual: string | null
  onAplicar: (de: string, ate: string) => void
}

export function DialogRangeCustom({ open, onOpenChange, deAtual, ateAtual, onAplicar }: Props) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="w-full max-w-md rounded-lg bg-card p-6 ring-1 ring-foreground/10">
        <DialogTitle className="text-lg font-semibold text-text-primary">
          Período personalizado
        </DialogTitle>
        {open ? (
          <FormConteudo
            deInicial={deAtual ?? ""}
            ateInicial={ateAtual ?? ""}
            onAplicar={(de, ate) => {
              onAplicar(de, ate)
              onOpenChange(false)
            }}
            onCancelar={() => onOpenChange(false)}
          />
        ) : null}
      </DialogContent>
    </Dialog>
  )
}

interface FormProps {
  deInicial: string
  ateInicial: string
  onAplicar: (de: string, ate: string) => void
  onCancelar: () => void
}

function FormConteudo({ deInicial, ateInicial, onAplicar, onCancelar }: FormProps) {
  const hoje = useMemo(() => hojeBrtIso(), [])
  const [de, setDe] = useState<string>(deInicial)
  const [ate, setAte] = useState<string>(ateInicial)

  const erro = useMemo(() => {
    if (!de || !ate) return null
    if (de > ate) return "A data inicial não pode ser maior que a final."
    if (ate > hoje) return "A data final não pode estar no futuro."
    if (diffDiasInclusivo(de, ate) > 90) return "Janela limitada a 90 dias."
    return null
  }, [de, ate, hoje])

  const podeAplicar = de !== "" && ate !== "" && erro === null

  const handleAplicar = () => {
    if (!podeAplicar) return
    onAplicar(de, ate)
  }

  return (
    <>
      <div className="mt-5 flex justify-center">
        <RangeCalendar
          value={{ de: de || null, ate: ate || null }}
          onChange={(range) => {
            setDe(range.de ?? "")
            setAte(range.ate ?? "")
          }}
          maxIso={hoje}
        />
      </div>

      {erro ? (
        <p className="mt-3 text-sm text-danger-500" role="alert">
          {erro}
        </p>
      ) : null}

      <div className="mt-6 flex items-center justify-end gap-2">
        <Button variant="ghost" size="lg" onClick={onCancelar}>
          Cancelar
        </Button>
        <Button variant="primary" size="lg" disabled={!podeAplicar} onClick={handleAplicar}>
          Aplicar
        </Button>
      </div>
    </>
  )
}
