"use client"

import { useEffect, useRef, useState } from "react"
import { ChevronDown } from "lucide-react"
import { cn } from "@/lib/utils"
import type { ModeloAtiva } from "@/tipos/painel"

function SeletorModelo({
  modelos,
  modeloId,
  onModeloChange,
}: {
  modelos: ModeloAtiva[]
  modeloId: string | null
  onModeloChange: (id: string | null) => void
}) {
  const [aberto, setAberto] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  const labelAtual = modeloId
    ? (modelos.find((m) => m.id === modeloId)?.nome ?? "Todas as modelos")
    : "Todas as modelos"

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setAberto(false)
      }
    }
    if (aberto) document.addEventListener("mousedown", handleClickOutside)
    return () => document.removeEventListener("mousedown", handleClickOutside)
  }, [aberto])

  const opcoes = [
    { id: null, nome: "Todas as modelos" },
    ...modelos.map((m) => ({ id: m.id, nome: m.nome })),
  ]

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setAberto((v) => !v)}
        aria-expanded={aberto}
        className="flex items-center gap-1.5 text-sm font-semibold text-text-primary outline-none transition-colors hover:text-text-secondary focus-visible:text-text-primary"
      >
        {labelAtual}
        <ChevronDown size={14} className="text-text-muted" aria-hidden />
      </button>

      {aberto && (
        <div className="absolute right-0 top-full z-50 mt-1.5 min-w-[180px] rounded-lg bg-popover py-1 shadow-md ring-1 ring-foreground/10">
          {opcoes.map((op) => (
            <button
              key={op.id ?? "__todas__"}
              onClick={() => {
                onModeloChange(op.id)
                setAberto(false)
              }}
              className={cn(
                "w-full px-3 py-2 text-left text-sm transition-colors hover:bg-accent focus-visible:bg-accent focus-visible:outline-none",
                op.id === modeloId ? "font-semibold text-text-primary" : "text-text-secondary",
              )}
            >
              {op.nome}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

export function HeaderPainel({
  modelos,
  modeloId,
  onModeloChange,
}: {
  modelos: ModeloAtiva[]
  modeloId: string | null
  onModeloChange: (id: string | null) => void
}) {
  const multiplas = modelos.length > 1

  return (
    <header className="flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        <h1 className="font-serif text-[32px] font-medium leading-tight tracking-[-0.01em] text-text-primary">
          Painel
        </h1>
        <p className="mt-1 text-[13px] text-text-muted">
          Tudo que precisa da sua atenção, num só lugar.
        </p>
      </div>
      <div className="flex flex-col items-end gap-1">
        <span className="text-[11px] font-medium uppercase tracking-[0.08em] text-text-muted">
          Modelo
        </span>
        {multiplas ? (
          <SeletorModelo
            modelos={modelos}
            modeloId={modeloId}
            onModeloChange={onModeloChange}
          />
        ) : modelos.length === 1 ? (
          <p className="text-sm font-semibold text-text-primary">{modelos[0].nome}</p>
        ) : (
          <p className="text-sm font-semibold text-text-muted">Nenhuma modelo ativa</p>
        )}
      </div>
    </header>
  )
}
