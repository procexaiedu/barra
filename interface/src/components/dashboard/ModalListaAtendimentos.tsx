"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { useRouter } from "next/navigation"
import { ArrowUpRight } from "lucide-react"
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { BannerErro } from "@/components/layout/BannerErro"
import { badgeForEstado, estadoLabel } from "@/components/atendimentos/utils"
import { formatRangeAbsoluto, janelaDoPeriodo } from "@/components/dashboard/utils"
import { api, ApiError } from "@/lib/api"
import { formatBRL, formatTelefone } from "@/lib/formatters"
import { cn } from "@/lib/utils"
import type { FiltrosDashboard } from "@/hooks/useDashboard"
import type {
  AtendimentoListaItem,
  AtendimentosListaResponse,
} from "@/tipos/atendimentos"

export type TipoMetricaModal =
  | "fechamentos"
  | "perdas"
  | "escaladas"
  | "faturamento_bruto"
  | "faturamento_liquido"
  | "repasse"

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
  tipo: TipoMetricaModal | null
  filtrosDashboard: FiltrosDashboard
  nomeModelo: string | null
}

type Status = "idle" | "loading" | "success" | "error"

const TITULO: Record<TipoMetricaModal, string> = {
  fechamentos: "Fechamentos no período",
  perdas: "Perdas no período",
  escaladas: "Atendimentos escalados no período",
  faturamento_bruto: "Faturamento bruto — fechamentos",
  faturamento_liquido: "Faturamento líquido — fechamentos",
  repasse: "Repasse às modelos — fechamentos",
}

function filtrosBase(tipo: TipoMetricaModal): URLSearchParams {
  const params = new URLSearchParams()
  if (tipo === "perdas") params.set("estado", "Perdido")
  else if (tipo === "escaladas") params.set("ia_pausada", "true")
  else params.set("estado", "Fechado")
  return params
}

function montarPath(
  tipo: TipoMetricaModal,
  filtros: FiltrosDashboard,
  cursor: string | null,
): string {
  const params = filtrosBase(tipo)
  params.set("limit", "50")
  const janela = janelaDoPeriodo(filtros)
  if (janela) {
    params.set("data_inicio", janela.de)
    params.set("data_fim", janela.ate)
  }
  if (filtros.modelo_id) params.set("modelo_id", filtros.modelo_id)
  if (cursor) params.set("cursor", cursor)
  return `/v1/atendimentos?${params.toString()}`
}

function montarHrefVerTodos(
  tipo: TipoMetricaModal,
  filtros: FiltrosDashboard,
): string {
  const params = filtrosBase(tipo)
  const janela = janelaDoPeriodo(filtros)
  if (janela) {
    params.set("de", janela.de)
    params.set("ate", janela.ate)
  }
  if (filtros.modelo_id) params.set("modelo_id", filtros.modelo_id)
  return `/atendimentos?${params.toString()}`
}

function formatarValorFinal(valor: number | string | null): string {
  if (valor === null || valor === undefined) return "—"
  const n = typeof valor === "string" ? Number(valor) : valor
  if (!Number.isFinite(n)) return "—"
  return formatBRL(n)
}

export function ModalListaAtendimentos({
  open,
  onOpenChange,
  tipo,
  filtrosDashboard,
  nomeModelo,
}: Props) {
  const router = useRouter()
  const [items, setItems] = useState<AtendimentoListaItem[]>([])
  const [cursor, setCursor] = useState<string | null>(null)
  const [status, setStatus] = useState<Status>("idle")
  const [error, setError] = useState<string | null>(null)
  const [loadingMais, setLoadingMais] = useState(false)
  const abortRef = useRef<AbortController | null>(null)

  const carregar = useCallback(
    async (proximoCursor: string | null) => {
      if (!tipo) return
      if (abortRef.current) abortRef.current.abort()
      const controller = new AbortController()
      abortRef.current = controller
      if (proximoCursor) {
        setLoadingMais(true)
      } else {
        setItems([])
        setCursor(null)
        setStatus("loading")
        setError(null)
      }
      try {
        const res = await api<AtendimentosListaResponse>(
          montarPath(tipo, filtrosDashboard, proximoCursor),
          { signal: controller.signal },
        )
        if (controller.signal.aborted) return
        setItems((anteriores) =>
          proximoCursor ? [...anteriores, ...res.items] : res.items,
        )
        setCursor(res.next_cursor ?? null)
        setStatus("success")
      } catch (e) {
        if (controller.signal.aborted) return
        if (e instanceof DOMException && e.name === "AbortError") return
        const detail =
          e instanceof ApiError
            ? e.detail
            : e instanceof Error
              ? e.message
              : "Erro desconhecido"
        setError(detail)
        setStatus("error")
      } finally {
        setLoadingMais(false)
      }
    },
    [tipo, filtrosDashboard],
  )

  useEffect(() => {
    if (open && tipo) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      carregar(null)
    }
    return () => {
      if (!open && abortRef.current) abortRef.current.abort()
    }
  }, [open, tipo, carregar])

  const janela = janelaDoPeriodo(filtrosDashboard)
  const rangeTexto = janela
    ? formatRangeAbsoluto(janela.de, janela.ate)
    : "Todo o histórico"
  const subtitulo = nomeModelo ? `${rangeTexto} · ${nomeModelo}` : rangeTexto

  const navegarParaAtendimento = (id: string) => {
    onOpenChange(false)
    router.push(`/atendimentos?id=${id}`)
  }

  const navegarVerTodos = () => {
    if (!tipo) return
    onOpenChange(false)
    router.push(montarHrefVerTodos(tipo, filtrosDashboard))
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex w-full max-w-xl flex-col gap-5 rounded-lg bg-card p-6 ring-1 ring-foreground/10">
        <div className="flex flex-col gap-1">
          <DialogTitle className="text-lg font-semibold text-text-primary">
            {tipo ? TITULO[tipo] : ""}
          </DialogTitle>
          <p className="text-xs text-text-muted">{subtitulo}</p>
        </div>

        <div className="max-h-[60vh] min-h-[120px] overflow-y-auto pr-1">
          {status === "loading" ? (
            <ul className="flex flex-col gap-2">
              {Array.from({ length: 6 }).map((_, idx) => (
                <li key={idx}>
                  <Skeleton className="h-12 w-full rounded-md" />
                </li>
              ))}
            </ul>
          ) : status === "error" ? (
            <BannerErro mensagem={error ?? undefined} onRetry={() => carregar(null)} />
          ) : items.length === 0 ? (
            <p className="text-sm text-text-muted">Nenhum atendimento neste filtro.</p>
          ) : (
            <ul className="flex flex-col">
              {items.map((item) => {
                const cliente = item.cliente.nome ?? formatTelefone(item.cliente.telefone)
                return (
                  <li key={item.id}>
                    <button
                      type="button"
                      onClick={() => navegarParaAtendimento(item.id)}
                      className={cn(
                        "grid w-full grid-cols-[64px_1fr_auto_100px] items-center gap-3 rounded-md px-2 py-2 text-left",
                        "transition-colors hover:bg-ink-200",
                        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
                      )}
                    >
                      <span className="font-mono text-xs text-text-muted">
                        #{item.numero_curto}
                      </span>
                      <span className="flex min-w-0 flex-col">
                        <span className="truncate text-sm font-medium text-text-primary">
                          {cliente}
                        </span>
                        <span className="truncate text-[11px] text-text-muted">
                          {item.modelo.nome}
                        </span>
                      </span>
                      <Badge variant={badgeForEstado(item.estado)} className="shrink-0">
                        {estadoLabel[item.estado]}
                      </Badge>
                      <span className="text-right font-mono text-xs tabular-nums text-text-primary">
                        {formatarValorFinal(item.valor_acordado)}
                      </span>
                    </button>
                  </li>
                )
              })}
            </ul>
          )}

          {status === "success" && cursor ? (
            <div className="mt-3 flex justify-center">
              <Button
                variant="ghost"
                size="sm"
                disabled={loadingMais}
                onClick={() => carregar(cursor)}
              >
                {loadingMais ? "Carregando…" : "Carregar mais"}
              </Button>
            </div>
          ) : null}
        </div>

        <div className="flex items-center justify-between gap-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={navegarVerTodos}
            className="gap-1"
          >
            Ver todos com este filtro em /atendimentos
            <ArrowUpRight size={14} strokeWidth={1.75} aria-hidden />
          </Button>
          <Button variant="ghost" size="lg" onClick={() => onOpenChange(false)}>
            Fechar
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
