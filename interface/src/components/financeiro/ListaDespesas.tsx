"use client"

import { useState } from "react"
import { Plus, Trash2 } from "lucide-react"
import { api, ApiError } from "@/lib/api"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { Badge } from "@/components/ui/badge"
import { formatBRL, formatData } from "@/lib/formatters"
import {
  ROTULO_CATEGORIA,
  type DespesasListaResponse,
  type DespesaLinha,
} from "@/tipos/financeiro"
import type { useFinanceiro } from "@/hooks/useFinanceiro"
import { FormDespesa } from "./FormDespesa"
import { ListaRecorrentes } from "./ListaRecorrentes"

type SubAba = "lancamentos" | "recorrentes"

export function ListaDespesas({
  lista,
  loading,
  fin,
}: {
  lista: DespesasListaResponse | null
  loading: boolean
  fin: ReturnType<typeof useFinanceiro>
}) {
  const [subAba, setSubAba] = useState<SubAba>("lancamentos")
  const [formAberto, setFormAberto] = useState<"despesa" | null>(null)

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex gap-1 rounded-lg border border-border bg-card p-0.5">
          <Button
            size="sm"
            variant={subAba === "lancamentos" ? "primary" : "ghost"}
            onClick={() => setSubAba("lancamentos")}
          >
            Lançamentos
          </Button>
          <Button
            size="sm"
            variant={subAba === "recorrentes" ? "primary" : "ghost"}
            onClick={() => setSubAba("recorrentes")}
          >
            Recorrentes
          </Button>
        </div>
        {subAba === "lancamentos" && (
          <Button size="sm" onClick={() => setFormAberto("despesa")}>
            <Plus className="size-4" />
            Nova despesa
          </Button>
        )}
      </div>

      {subAba === "lancamentos" && (
        <TabelaDespesas lista={lista} loading={loading} onMudou={fin.refetch} />
      )}
      {subAba === "recorrentes" && <ListaRecorrentes onMudou={fin.refetch} />}

      <FormDespesa
        open={formAberto === "despesa"}
        onOpenChange={(open) => setFormAberto(open ? "despesa" : null)}
        onSalvo={() => {
          setFormAberto(null)
          fin.refetch()
        }}
      />
    </div>
  )
}

function TabelaDespesas({
  lista,
  loading,
  onMudou,
}: {
  lista: DespesasListaResponse | null
  loading: boolean
  onMudou: () => void
}) {
  if (loading && !lista) return <Skeleton className="h-64" />
  if (!lista || lista.items.length === 0) {
    return (
      <div className="rounded-lg border border-border bg-card p-8 text-center text-sm text-text-muted">
        Nenhuma despesa no período.
      </div>
    )
  }
  return (
    <div className="overflow-x-auto rounded-lg border border-border bg-card">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border bg-muted/30 text-xs uppercase text-text-muted">
            <th className="px-3 py-2 text-left">Data</th>
            <th className="px-3 py-2 text-left">Categoria</th>
            <th className="px-3 py-2 text-left">Descrição</th>
            <th className="px-3 py-2 text-left">Origem</th>
            <th className="px-3 py-2 text-right">Valor</th>
            <th className="px-3 py-2"></th>
          </tr>
        </thead>
        <tbody>
          {lista.items.map((d, idx) => (
            <LinhaDespesa
              key={d.id ?? `proj-${d.recorrente_id}-${d.competencia_mes}-${idx}`}
              despesa={d}
              onMudou={onMudou}
            />
          ))}
        </tbody>
      </table>
    </div>
  )
}

function LinhaDespesa({
  despesa,
  onMudou,
}: {
  despesa: DespesaLinha
  onMudou: () => void
}) {
  const [excluindo, setExcluindo] = useState(false)
  const projetada = despesa.origem === "recorrente_projetada"

  async function materializar() {
    setExcluindo(true)
    try {
      await api("/v1/financeiro/despesas/materializar-recorrente", {
        method: "POST",
        body: JSON.stringify({
          recorrente_id: despesa.recorrente_id,
          competencia_mes: despesa.competencia_mes,
        }),
      })
      toast.success("Despesa materializada.")
      onMudou()
    } catch (e) {
      toast.error(e instanceof ApiError ? e.detail : "Erro ao materializar")
    } finally {
      setExcluindo(false)
    }
  }

  async function excluir() {
    if (!despesa.id) return
    if (!confirm("Excluir esta despesa?")) return
    setExcluindo(true)
    try {
      await api(`/v1/financeiro/despesas/${despesa.id}`, { method: "DELETE" })
      toast.success("Despesa excluída.")
      onMudou()
    } catch (e) {
      toast.error(e instanceof ApiError ? e.detail : "Erro ao excluir")
    } finally {
      setExcluindo(false)
    }
  }

  return (
    <tr className="border-b border-border/60 hover:bg-muted/20">
      <td className="px-3 py-2 text-text-muted">{formatData(despesa.data)}</td>
      <td className="px-3 py-2">{ROTULO_CATEGORIA[despesa.categoria]}</td>
      <td className="px-3 py-2 text-text-muted">{despesa.descricao || "—"}</td>
      <td className="px-3 py-2">
        <BadgeOrigem despesa={despesa} />
      </td>
      <td className="px-3 py-2 text-right tabular-nums">{formatBRL(despesa.valor)}</td>
      <td className="px-3 py-2 text-right">
        {projetada ? (
          <Button size="xs" variant="outline" onClick={materializar} disabled={excluindo}>
            Materializar
          </Button>
        ) : (
          <Button
            size="xs"
            variant="ghost"
            onClick={excluir}
            disabled={excluindo}
            aria-label="Excluir"
          >
            <Trash2 className="size-3.5" />
          </Button>
        )}
      </td>
    </tr>
  )
}

function BadgeOrigem({ despesa }: { despesa: DespesaLinha }) {
  if (despesa.origem === "pontual") {
    return <Badge variant="active">manual</Badge>
  }
  if (despesa.origem === "recorrente_materializada") {
    return <Badge variant="closed">recorrente</Badge>
  }
  return (
    <Badge variant="paused" className="border-dashed">
      projetada
    </Badge>
  )
}
