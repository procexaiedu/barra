"use client"

import { useEffect, useRef, useState } from "react"
import { ChevronDown } from "lucide-react"
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
        className="flex items-center gap-1 text-base font-semibold text-text-primary hover:text-text-secondary outline-none"
      >
        {labelAtual}
        <ChevronDown size={14} className="text-text-muted" />
      </button>

      {aberto && (
        <div className="absolute right-0 top-full z-50 mt-1 min-w-[180px] rounded-lg border border-border bg-card py-1 shadow-lg">
          {opcoes.map((op) => (
            <button
              key={op.id ?? "__todas__"}
              onClick={() => {
                onModeloChange(op.id)
                setAberto(false)
              }}
              className={`w-full px-4 py-2 text-left text-sm hover:bg-ink-200 ${
                op.id === modeloId
                  ? "font-semibold text-text-primary"
                  : "text-text-secondary"
              }`}
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
    <div className="flex items-center justify-between px-8 pb-4 pt-8">
      <h1 className="font-serif text-[40px] font-medium leading-[48px] tracking-[-0.02em] text-text-primary">
        Painel
      </h1>
      <div className="flex items-center gap-6">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.08em] text-text-muted">
            MODELO
          </p>
          {multiplas ? (
            <SeletorModelo
              modelos={modelos}
              modeloId={modeloId}
              onModeloChange={onModeloChange}
            />
          ) : modelos.length === 1 ? (
            <p className="text-base font-semibold text-text-primary">{modelos[0].nome}</p>
          ) : (
            <p className="text-base font-semibold text-text-muted">Nenhuma modelo ativa</p>
          )}
        </div>
      </div>
    </div>
  )
}
