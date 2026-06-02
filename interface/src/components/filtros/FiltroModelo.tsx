"use client"

import { useEffect, useMemo, useState } from "react"
import { Check, ChevronDown } from "lucide-react"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"
import { useModelosOpcoes } from "@/hooks/useModelosOpcoes"

interface Props {
  /** Seleção atual. Single mode = array de 0 ou 1 id. Vazio = "Todas" (sem filtro). */
  value: string[]
  onChange: (ids: string[]) => void
  /** Multi-seleção (default) vs single (fecha ao escolher). */
  multi?: boolean
  /** Oferece a opção "Todas". Desligue para single obrigatório (Agenda). */
  incluiTodas?: boolean
  label?: string
  className?: string
}

function normaliza(s: string): string {
  return s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase()
}

/** Seletor de modelo padrão do painel: Popover com busca acento-insensível.
 *  Substitui FiltroModelo (single) e FiltroModeloMulti (multi). Seleção vazia =
 *  "Todas" (sem filtro), exceto quando `incluiTodas=false` (single obrigatório). */
export function FiltroModelo({
  value,
  onChange,
  multi = true,
  incluiTodas = true,
  label = "Filtrar por modelo",
  className,
}: Props) {
  const { modelos } = useModelosOpcoes()
  const [open, setOpen] = useState(false)
  const [termo, setTermo] = useState("")

  const carregando = modelos === null
  const opcoes = useMemo(() => modelos ?? [], [modelos])
  const selecionadas = useMemo(() => new Set(value), [value])

  // Single obrigatório (Agenda): sem "Todas", seleciona o 1º modelo assim que a
  // lista carrega — evita que o pai fique com seleção vazia enquanto a UI exibe um.
  useEffect(() => {
    if (multi || incluiTodas || value.length > 0) return
    const primeiro = opcoes[0]
    if (primeiro) onChange([primeiro.id])
  }, [multi, incluiTodas, value.length, opcoes, onChange])

  const termoNorm = normaliza(termo.trim())
  const filtradas = useMemo(() => {
    if (!termoNorm) return opcoes
    return opcoes.filter((m) => normaliza(m.nome).includes(termoNorm))
  }, [opcoes, termoNorm])

  const rotulo = useMemo(() => {
    if (value.length === 0) return "Todas"
    if (value.length === 1) {
      return opcoes.find((o) => o.id === value[0])?.nome ?? "1 modelo"
    }
    return `${value.length} modelos`
  }, [value, opcoes])

  const selecionarTodas = () => {
    onChange([])
    if (!multi) setOpen(false)
  }

  const escolher = (id: string) => {
    if (!multi) {
      onChange([id])
      setOpen(false)
      return
    }
    const prox = new Set(selecionadas)
    if (prox.has(id)) prox.delete(id)
    else prox.add(id)
    // Reordena pela lista carregada para serialização de URL estável.
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
        aria-label={label}
        className={cn(
          "flex h-9 min-w-[9rem] items-center justify-between gap-2 rounded-lg border border-input bg-input px-3 text-sm text-text-primary outline-none transition-colors hover:border-border-strong focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-50",
          className,
        )}
      >
        <span className="flex items-center gap-2 truncate">
          <span className="truncate">{rotulo}</span>
          {value.length > 1 && (
            <span className="shrink-0 rounded-full bg-gold-500/15 px-1.5 text-[10px] font-semibold text-gold-500 tabular-nums">
              {value.length}
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
          {incluiTodas && (
            <li>
              <button
                type="button"
                onClick={selecionarTodas}
                className="flex w-full items-center justify-between rounded-md px-2 py-1.5 text-left text-sm outline-none transition-colors hover:bg-accent focus-visible:bg-accent"
              >
                <span className={cn(value.length === 0 ? "font-medium text-gold-500" : "text-text-primary")}>
                  Todas
                </span>
                {value.length === 0 && <Check size={14} strokeWidth={2} className="text-gold-500" />}
              </button>
            </li>
          )}
          {filtradas.length === 0 ? (
            <li className="px-2 py-1.5 text-xs text-text-muted">Nenhuma modelo</li>
          ) : (
            filtradas.map((m) => {
              const ativa = selecionadas.has(m.id)
              return (
                <li key={m.id}>
                  <button
                    type="button"
                    onClick={() => escolher(m.id)}
                    aria-pressed={ativa}
                    className="flex w-full items-center justify-between gap-2 rounded-md px-2 py-1.5 text-left text-sm text-text-primary outline-none transition-colors hover:bg-accent focus-visible:bg-accent"
                  >
                    <span className="truncate">{m.nome}</span>
                    {ativa && <Check size={14} strokeWidth={2} className="shrink-0 text-gold-500" />}
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
