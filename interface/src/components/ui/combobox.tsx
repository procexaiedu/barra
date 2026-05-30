"use client"

import * as React from "react"
import { ChevronDown, Plus, Trash2 } from "lucide-react"

import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"
import { formatRotulo } from "@/lib/formatters"

export type ComboboxProps = {
  value: string
  onChange: (v: string) => void
  options: string[]
  placeholder?: string
  displayFormat?: (v: string) => string
  onCreate?: (novo: string) => void
  /**
   * Opt-in: quando fornecido, cada item da lista ganha um botão de remover.
   * Sem essa prop, o Combobox segue idêntico (não quebra outros usos).
   */
  onDeletarItem?: (item: string) => void
  disabled?: boolean
  id?: string
  className?: string
  triggerClassName?: string
}

function normaliza(s: string): string {
  return s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase()
}

export function Combobox({
  value,
  onChange,
  options,
  placeholder,
  displayFormat,
  onCreate,
  onDeletarItem,
  disabled,
  id,
  className,
  triggerClassName,
}: ComboboxProps) {
  const [open, setOpen] = React.useState(false)
  const [termo, setTermo] = React.useState("")

  const formatar = React.useMemo(
    () => displayFormat ?? ((v: string) => formatRotulo(v) ?? v),
    [displayFormat],
  )

  const termoTrim = termo.trim()
  const termoNorm = normaliza(termoTrim)

  const filtradas = React.useMemo(() => {
    if (!termoNorm) return options
    // Filtra pelo rótulo exibido (e pela opção crua como fallback): quando a
    // option é uma chave técnica (ex.: "modelo:<uuid>"), só o formatado casa.
    return options.filter(
      (o) => normaliza(formatar(o)).includes(termoNorm) || normaliza(o).includes(termoNorm),
    )
  }, [options, termoNorm, formatar])

  const baterExato = React.useMemo(
    () => options.some((o) => o.toLowerCase() === termoTrim.toLowerCase()),
    [options, termoTrim],
  )
  const mostrarCriar = !!onCreate && termoTrim.length > 0 && !baterExato

  const selecionar = (v: string) => {
    onChange(v)
    setOpen(false)
    setTermo("")
  }

  const criar = () => {
    if (!onCreate) return
    const novo = termoTrim.toLowerCase()
    onCreate(novo)
    onChange(novo)
    setOpen(false)
    setTermo("")
  }

  return (
    <div data-slot="combobox" className={cn("relative", className)}>
      <Popover
        open={open}
        onOpenChange={(prox) => {
          setOpen(prox)
          if (!prox) setTermo("")
        }}
      >
        <PopoverTrigger
          id={id}
          data-slot="combobox-trigger"
          disabled={disabled}
          className={cn(
            "flex h-10 w-full items-center justify-between gap-2 rounded-lg border border-border-strong bg-surface-hover px-3 text-left text-sm text-text-primary outline-none transition-colors hover:bg-surface-pressed focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/60 disabled:cursor-not-allowed disabled:opacity-50",
            triggerClassName,
          )}
        >
          <span className={cn("truncate", !value && "text-text-muted")}>
            {value ? formatar(value) : placeholder ?? "Selecione…"}
          </span>
          <ChevronDown size={14} strokeWidth={1.5} className="shrink-0 text-text-muted" />
        </PopoverTrigger>
        <PopoverContent
          data-slot="combobox-content"
          align="start"
          className="w-[var(--anchor-width)] min-w-[200px] p-2"
        >
          <Input
            data-slot="combobox-search"
            value={termo}
            onChange={(e) => setTermo(e.target.value)}
            placeholder="Buscar…"
            className="mb-2 h-9"
            autoFocus
          />
          <ul data-slot="combobox-list" className="max-h-56 overflow-y-auto">
            {filtradas.length === 0 && !mostrarCriar && (
              <li className="px-2 py-1.5 text-xs text-text-muted">Nenhuma opção</li>
            )}
            {filtradas.map((opt) => (
              <li key={opt} className="group/combobox-item flex items-center gap-1">
                <button
                  type="button"
                  data-slot="combobox-item"
                  data-selected={value === opt ? "true" : undefined}
                  onClick={() => selecionar(opt)}
                  className="flex flex-1 items-center justify-between rounded-md px-2 py-1.5 text-left text-sm text-text-primary outline-none transition-colors hover:bg-surface-hover focus-visible:bg-surface-hover data-[selected=true]:bg-surface-hover"
                >
                  <span className="truncate">{formatar(opt)}</span>
                </button>
                {onDeletarItem && (
                  <button
                    type="button"
                    data-slot="combobox-delete"
                    onClick={() => onDeletarItem(opt)}
                    aria-label={`Remover ${formatar(opt)} das sugestões`}
                    className="shrink-0 rounded-md p-1.5 text-text-muted opacity-60 outline-none transition-colors hover:bg-surface-hover hover:text-state-lost focus-visible:bg-surface-hover focus-visible:opacity-100 group-hover/combobox-item:opacity-100"
                  >
                    <Trash2 size={13} strokeWidth={1.5} />
                  </button>
                )}
              </li>
            ))}
            {mostrarCriar && (
              <li>
                <button
                  type="button"
                  data-slot="combobox-create"
                  onClick={criar}
                  className="flex w-full items-center gap-1.5 rounded-md px-2 py-1.5 text-left text-sm text-text-primary outline-none transition-colors hover:bg-surface-hover focus-visible:bg-surface-hover"
                >
                  <Plus size={14} strokeWidth={1.5} className="shrink-0 text-text-muted" />
                  <span className="truncate">
                    Criar &ldquo;{termoTrim.toLowerCase()}&rdquo;
                  </span>
                </button>
              </li>
            )}
          </ul>
        </PopoverContent>
      </Popover>
    </div>
  )
}
