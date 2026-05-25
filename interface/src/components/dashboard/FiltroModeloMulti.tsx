"use client"

import { useEffect, useMemo, useState } from "react"
import { Check, ChevronDown } from "lucide-react"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { Input } from "@/components/ui/input"
import { api, ApiError } from "@/lib/api"
import { cn } from "@/lib/utils"

interface ModeloListaItem {
  id: string
  nome: string
}

interface ModelosResponse {
  items: ModeloListaItem[]
  next_cursor: string | null
}

interface Props {
  modeloIds: string[]
  onChange: (ids: string[]) => void
}

function normaliza(s: string): string {
  return s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase()
}

/**
 * Filtro multi-select de modelos do dashboard. Seleção vazia = "Todas"
 * (sem filtro). Distinto do `FiltroModelo` single-select usado na agenda,
 * onde uma única modelo é obrigatória.
 */
export function FiltroModeloMulti({ modeloIds, onChange }: Props) {
  const [modelos, setModelos] = useState<ModeloListaItem[] | null>(null)
  const [open, setOpen] = useState(false)
  const [termo, setTermo] = useState("")

  useEffect(() => {
    let cancelado = false
    api<ModelosResponse>("/v1/modelos?limit=100")
      .then((res) => {
        if (cancelado) return
        setModelos(res.items.map((m) => ({ id: m.id, nome: m.nome })))
      })
      .catch((e) => {
        if (cancelado) return
        if (e instanceof ApiError && e.status === 401) return
        setModelos([])
      })
    return () => {
      cancelado = true
    }
  }, [])

  const carregando = modelos === null
  const opcoes = useMemo(() => modelos ?? [], [modelos])
  const selecionadas = useMemo(() => new Set(modeloIds), [modeloIds])

  const termoNorm = normaliza(termo.trim())
  const filtradas = useMemo(() => {
    if (!termoNorm) return opcoes
    return opcoes.filter((m) => normaliza(m.nome).includes(termoNorm))
  }, [opcoes, termoNorm])

  const rotulo = useMemo(() => {
    if (modeloIds.length === 0) return "Todas"
    if (modeloIds.length === 1) {
      return opcoes.find((o) => o.id === modeloIds[0])?.nome ?? "1 modelo"
    }
    return `${modeloIds.length} modelos`
  }, [modeloIds, opcoes])

  const toggle = (id: string) => {
    const prox = new Set(selecionadas)
    if (prox.has(id)) prox.delete(id)
    else prox.add(id)
    // Reordena pela lista carregada para uma serialização de URL estável.
    onChange(opcoes.filter((o) => prox.has(o.id)).map((o) => o.id))
  }

  return (
    <Popover
      open={open}
      onOpenChange={(prox) => {
        setOpen(prox)
        if (!prox) setTermo("")
      }}
    >
      <PopoverTrigger
        disabled={carregando}
        aria-label="Filtrar por modelo"
        className="flex h-9 min-w-[9rem] items-center justify-between gap-2 rounded-md border border-input bg-input px-3 text-sm text-text-primary outline-none transition-colors hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:opacity-50"
      >
        <span className="flex items-center gap-2 truncate">
          <span className={cn("truncate", modeloIds.length === 0 && "text-text-muted")}>
            {rotulo}
          </span>
          {modeloIds.length > 1 && (
            <span className="shrink-0 rounded-full bg-gold-500/15 px-1.5 text-[10px] font-semibold text-gold-500 tabular-nums">
              {modeloIds.length}
            </span>
          )}
        </span>
        <ChevronDown size={14} strokeWidth={1.5} className="shrink-0 text-text-muted" />
      </PopoverTrigger>
      <PopoverContent align="end" className="w-[var(--anchor-width)] min-w-[220px] p-2">
        <Input
          value={termo}
          onChange={(e) => setTermo(e.target.value)}
          placeholder="Buscar modelo…"
          className="mb-2 h-9"
          autoFocus
        />
        <ul className="max-h-60 overflow-y-auto">
          <li>
            <button
              type="button"
              onClick={() => onChange([])}
              className="flex w-full items-center justify-between rounded-md px-2 py-1.5 text-left text-sm outline-none transition-colors hover:bg-accent focus-visible:bg-accent"
            >
              <span className={cn(modeloIds.length === 0 ? "font-medium text-gold-500" : "text-text-primary")}>
                Todas
              </span>
              {modeloIds.length === 0 && <Check size={14} strokeWidth={2} className="text-gold-500" />}
            </button>
          </li>
          {filtradas.length === 0 ? (
            <li className="px-2 py-1.5 text-xs text-text-muted">Nenhuma modelo</li>
          ) : (
            filtradas.map((m) => {
              const ativa = selecionadas.has(m.id)
              return (
                <li key={m.id}>
                  <button
                    type="button"
                    onClick={() => toggle(m.id)}
                    aria-pressed={ativa}
                    className="flex w-full items-center justify-between gap-2 rounded-md px-2 py-1.5 text-left text-sm text-text-primary outline-none transition-colors hover:bg-accent focus-visible:bg-accent"
                  >
                    <span className="truncate">{m.nome}</span>
                    {ativa && (
                      <Check size={14} strokeWidth={2} className="shrink-0 text-gold-500" />
                    )}
                  </button>
                </li>
              )
            })
          )}
        </ul>
      </PopoverContent>
    </Popover>
  )
}
