"use client"

import { Suspense, useCallback, useEffect, useState } from "react"
import { Download } from "lucide-react"
import { BannerErro } from "@/components/layout/BannerErro"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"
import { supabase } from "@/lib/supabase"
import { toast } from "sonner"
import { useFinanceiro, type FinanceiroView } from "@/hooks/useFinanceiro"
import { useReceitaContexto } from "@/hooks/useReceitaContexto"
import { PainelFinanceiro } from "@/components/financeiro/PainelFinanceiro"
import { ListaReceitas } from "@/components/financeiro/ListaReceitas"
import { InspectorReceita } from "@/components/financeiro/InspectorReceita"
import { RepassesPorModelo } from "@/components/financeiro/RepassesPorModelo"
import { ToolbarFinanceiro } from "@/components/financeiro/ToolbarFinanceiro"
import { FiltroModelo } from "@/components/filtros/FiltroModelo"
import { FiltroPeriodo } from "@/components/filtros/FiltroPeriodo"
import type { ReceitaLinha } from "@/tipos/financeiro"
import type { PeriodoSelecionado } from "@/tipos/filtros"

const VIEWS: { id: FinanceiroView; label: string }[] = [
  { id: "geral", label: "Visão geral" },
  { id: "receitas", label: "Receitas" },
  { id: "repasses", label: "Repasses" },
]

export default function FinanceiroPage() {
  return (
    <Suspense fallback={<Skeleton className="h-[60vh] w-full rounded-lg" />}>
      <FinanceiroInner />
    </Suspense>
  )
}

function FinanceiroInner() {
  const fin = useFinanceiro()
  const view = fin.filtros.view

  const onPeriodoChange = (v: PeriodoSelecionado) => {
    if (v.periodo === "custom") {
      if (v.de && v.ate) fin.setPeriodoCustom(v.de, v.ate)
    } else {
      fin.setPeriodoPreset(v.periodo)
    }
  }

  return (
    <div className="flex flex-col gap-8">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <h1 className="font-serif text-[32px] font-medium leading-tight tracking-[-0.01em] text-text-primary">
            Financeiro
          </h1>
          <p className="mt-1 text-[13px] text-text-muted">
            Receitas, repasses por modelo e visão geral.
          </p>
        </div>
        <div className="flex flex-wrap items-end gap-2">
          <FiltroPeriodo
            value={{ periodo: fin.filtros.periodo, de: fin.filtros.de, ate: fin.filtros.ate }}
            onChange={onPeriodoChange}
          />
          <div className="flex flex-col gap-1">
            <span className="text-xs font-medium text-text-muted">Modelo</span>
            <FiltroModelo value={fin.filtros.modelo_ids} onChange={fin.setModeloIds} />
          </div>
          <ExportarBotao fin={fin} view={view} />
        </div>
      </header>

      <div className="flex flex-col gap-4">
        <div
          role="tablist"
          aria-label="Visões do Financeiro"
          className="flex gap-1 border-b border-border"
        >
          {VIEWS.map((v) => {
            const ativo = v.id === view
            return (
              <button
                key={v.id}
                type="button"
                role="tab"
                aria-selected={ativo}
                onClick={() => fin.setView(v.id)}
                className={cn(
                  "relative px-3 pb-2.5 pt-1 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                  ativo
                    ? "text-text-primary after:absolute after:inset-x-0 after:-bottom-px after:h-px after:bg-gold-500"
                    : "text-text-muted hover:text-text-secondary",
                )}
              >
                {v.label}
              </button>
            )
          })}
        </div>

        <ToolbarFinanceiro fin={fin} />
      </div>

      {fin.error && <BannerErro mensagem={fin.error} onRetry={fin.refetch} />}

      {view === "geral" && (
        <PainelFinanceiro
          resumo={fin.resumo}
          serie={fin.serie}
          loading={fin.status === "loading"}
          onSelecionarModelo={(id) => fin.setModeloIds([id])}
        />
      )}
      {view === "receitas" && <ViewReceitas fin={fin} />}
      {view === "repasses" && (
        <RepassesPorModelo
          repasses={fin.repasses}
          pagamentos={fin.pagamentos}
          loading={fin.status === "loading"}
          fin={fin}
        />
      )}
    </div>
  )
}

function ViewReceitas({ fin }: { fin: ReturnType<typeof useFinanceiro> }) {
  const [selecionada, setSelecionada] = useState<ReceitaLinha | null>(null)
  const contexto = useReceitaContexto(
    selecionada?.atendimento_id ?? null,
    fin.filtros,
  )

  // Limpa a seleção quando a lista carregada não contém mais o id selecionado
  // (ex.: trocou de período/filtro).
  useEffect(() => {
    if (!selecionada || !fin.receitas) return
    const aindaPresente = fin.receitas.items.some(
      (r) => r.atendimento_id === selecionada.atendimento_id,
    )
    // Reset síncrono sincronizando seleção com a lista (mudou período/filtro
    // e a linha não está mais visível). Mesmo padrão do useFinanceiro.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (!aindaPresente) setSelecionada(null)
  }, [fin.receitas, selecionada])

  // Navegação J (próximo) / K (anterior) / Esc (fechar).
  const handleKey = useCallback(
    (e: KeyboardEvent) => {
      const ae = document.activeElement
      const tag = ae?.tagName
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return
      if (e.metaKey || e.ctrlKey || e.altKey) return

      const itens = fin.receitas?.items ?? []
      if (itens.length === 0) return

      if (e.key === "Escape") {
        if (selecionada) {
          setSelecionada(null)
          e.preventDefault()
        }
        return
      }
      if (e.key !== "j" && e.key !== "k") return
      e.preventDefault()

      const idx = selecionada
        ? itens.findIndex((r) => r.atendimento_id === selecionada.atendimento_id)
        : -1
      const prox =
        e.key === "j"
          ? Math.min(itens.length - 1, idx === -1 ? 0 : idx + 1)
          : Math.max(0, idx === -1 ? 0 : idx - 1)
      const alvo = itens[prox]
      if (alvo) setSelecionada(alvo)
    },
    [fin.receitas, selecionada],
  )

  useEffect(() => {
    window.addEventListener("keydown", handleKey)
    return () => window.removeEventListener("keydown", handleKey)
  }, [handleKey])

  return (
    <div className="flex min-h-0 flex-1 gap-4">
      <div className="flex min-w-0 flex-1 flex-col gap-2">
        <ListaReceitas
          lista={fin.receitas}
          loading={fin.status === "loading"}
          selectedId={selecionada?.atendimento_id ?? null}
          onSelect={setSelecionada}
          onCarregarMais={fin.carregarMaisReceitas}
          carregandoMais={fin.carregandoMaisReceitas}
          proximoLote={fin.limitAtual}
        />
        <p className="text-[11px] text-text-muted">
          <kbd className="rounded-md border border-border bg-muted px-1 py-0.5 font-mono text-[10px] tabular-nums">j</kbd>
          <span className="mx-1">/</span>
          <kbd className="rounded-md border border-border bg-muted px-1 py-0.5 font-mono text-[10px] tabular-nums">k</kbd>
          <span className="ml-1.5">navegar</span>
          <span className="mx-2">·</span>
          <kbd className="rounded-md border border-border bg-muted px-1 py-0.5 font-mono text-[10px] tabular-nums">esc</kbd>
          <span className="ml-1.5">fechar</span>
        </p>
      </div>
      {selecionada && (
        <InspectorReceita
          linha={selecionada}
          contexto={contexto.contexto}
          loading={contexto.status === "loading"}
          error={contexto.error}
          onClose={() => setSelecionada(null)}
        />
      )}
    </div>
  )
}

function ExportarBotao({
  fin,
  view,
}: {
  fin: ReturnType<typeof useFinanceiro>
  view: FinanceiroView
}) {
  const [baixando, setBaixando] = useState(false)
  if (view === "geral") return null
  const recursoMap = {
    receitas: "/receitas/export",
    repasses: "/repasses/pagamentos/export",
  } as const
  const recurso = recursoMap[view as keyof typeof recursoMap]
  if (!recurso) return null

  async function baixar() {
    setBaixando(true)
    try {
      const path = fin.montarPathExport(recurso!)
      const { data: { session } } = await supabase.auth.getSession()
      const baseURL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"
      const r = await fetch(`${baseURL}${path}`, {
        headers: session ? { authorization: `Bearer ${session.access_token}` } : {},
      })
      if (!r.ok) throw new Error(`Erro ${r.status}`)
      const blob = await r.blob()
      const url = URL.createObjectURL(blob)
      const disposition = r.headers.get("content-disposition") ?? ""
      const matched = disposition.match(/filename="([^"]+)"/)
      const filename = matched?.[1] ?? `${view}.csv`
      const a = document.createElement("a")
      a.href = url
      a.download = filename
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Falha ao exportar CSV")
    } finally {
      setBaixando(false)
    }
  }

  return (
    <Button variant="outline" onClick={baixar} disabled={baixando}>
      <Download size={16} strokeWidth={1.5} />
      {baixando ? "Baixando…" : "Exportar CSV"}
    </Button>
  )
}
