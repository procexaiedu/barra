"use client"

import { useState } from "react"
import { AlertCircle, Plus, Trash2 } from "lucide-react"
import { api, ApiError } from "@/lib/api"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { formatBRL, formatData } from "@/lib/formatters"
import type {
  RepassePagoResponse,
  RepassesPagamentosListaResponse,
  RepassesPorModeloResponse,
  SaldoModelo,
} from "@/tipos/financeiro"
import type { useFinanceiro } from "@/hooks/useFinanceiro"
import { FormRepasse } from "./FormRepasse"
import { DialogPreencherRepasse } from "./DialogPreencherRepasse"

export function RepassesPorModelo({
  repasses,
  pagamentos,
  loading,
  fin,
}: {
  repasses: RepassesPorModeloResponse | null
  pagamentos: RepassesPagamentosListaResponse | null
  loading: boolean
  fin: ReturnType<typeof useFinanceiro>
}) {
  const [formAberto, setFormAberto] = useState<{
    modelo_id?: string
  } | null>(null)
  const [dialogRetroAberto, setDialogRetroAberto] = useState<{
    modelo_id: string
    modelo_nome: string
  } | null>(null)

  if (loading && !repasses) return <Skeleton className="h-64" />
  if (!repasses) return null

  return (
    <div className="space-y-4">
      <header className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-text-muted uppercase">Saldo por modelo</h2>
        <Button size="sm" onClick={() => setFormAberto({})}>
          <Plus className="size-4" />
          Registrar pagamento
        </Button>
      </header>

      <div className="overflow-x-auto rounded-lg border border-border bg-card">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border bg-muted/30 text-xs uppercase text-text-muted">
              <th className="px-3 py-2 text-left">Modelo</th>
              <th className="px-3 py-2 text-right">Fechamentos</th>
              <th className="px-3 py-2 text-right">Bruto</th>
              <th className="px-3 py-2 text-right">Calculado</th>
              <th className="px-3 py-2 text-right">Pago</th>
              <th className="px-3 py-2 text-right">Saldo</th>
              <th className="px-3 py-2 text-left">Pendência</th>
              <th className="px-3 py-2"></th>
            </tr>
          </thead>
          <tbody>
            {repasses.items.map((s) => (
              <LinhaModelo
                key={s.modelo_id}
                saldo={s}
                onPagar={() => setFormAberto({ modelo_id: s.modelo_id })}
                onPreencher={() =>
                  setDialogRetroAberto({
                    modelo_id: s.modelo_id,
                    modelo_nome: s.modelo_nome,
                  })
                }
              />
            ))}
          </tbody>
        </table>
      </div>

      <header className="flex items-center justify-between pt-2">
        <h2 className="text-sm font-semibold text-text-muted uppercase">Pagamentos no período</h2>
      </header>
      <TabelaPagamentos
        pagamentos={pagamentos}
        loading={loading}
        onMudou={fin.refetch}
      />

      <FormRepasse
        open={!!formAberto}
        onOpenChange={(open) => setFormAberto(open ? formAberto : null)}
        modeloIdInicial={formAberto?.modelo_id ?? null}
        onSalvo={() => {
          setFormAberto(null)
          fin.refetch()
        }}
      />
      {dialogRetroAberto && (
        <DialogPreencherRepasse
          open={!!dialogRetroAberto}
          onOpenChange={(open) => setDialogRetroAberto(open ? dialogRetroAberto : null)}
          modeloId={dialogRetroAberto.modelo_id}
          modeloNome={dialogRetroAberto.modelo_nome}
          onSalvo={() => {
            setDialogRetroAberto(null)
            fin.refetch()
          }}
        />
      )}
    </div>
  )
}

function LinhaModelo({
  saldo,
  onPagar,
  onPreencher,
}: {
  saldo: SaldoModelo
  onPagar: () => void
  onPreencher: () => void
}) {
  const saldoNegativo = saldo.saldo < 0
  return (
    <tr className="border-b border-border/60 hover:bg-muted/20">
      <td className="px-3 py-2 font-medium">{saldo.modelo_nome}</td>
      <td className="px-3 py-2 text-right tabular-nums text-text-muted">{saldo.fechamentos_total}</td>
      <td className="px-3 py-2 text-right tabular-nums">{formatBRL(saldo.valor_bruto)}</td>
      <td className="px-3 py-2 text-right tabular-nums">{formatBRL(saldo.valor_repasse_calculado)}</td>
      <td className="px-3 py-2 text-right tabular-nums text-text-muted">{formatBRL(saldo.valor_repasse_pago)}</td>
      <td
        className={`px-3 py-2 text-right tabular-nums font-semibold ${
          saldoNegativo ? "text-destructive" : ""
        }`}
        title={saldoNegativo ? "Pago a mais (estorno?) — compense no próximo lançamento" : undefined}
      >
        {formatBRL(saldo.saldo)}
      </td>
      <td className="px-3 py-2">
        {saldo.fechamentos_sem_snapshot > 0 ? (
          <button
            type="button"
            onClick={onPreencher}
            className="inline-flex items-center gap-1 text-xs text-warning hover:underline"
          >
            <AlertCircle className="size-3.5" />
            {saldo.fechamentos_sem_snapshot} sem repasse · {formatBRL(saldo.valor_sem_snapshot)}
          </button>
        ) : (
          <span className="text-xs text-text-muted">—</span>
        )}
      </td>
      <td className="px-3 py-2 text-right">
        <Button size="xs" variant="outline" onClick={onPagar}>
          Pagar
        </Button>
      </td>
    </tr>
  )
}

function TabelaPagamentos({
  pagamentos,
  loading,
  onMudou,
}: {
  pagamentos: RepassesPagamentosListaResponse | null
  loading: boolean
  onMudou: () => void
}) {
  if (loading && !pagamentos) return <Skeleton className="h-32" />
  if (!pagamentos || pagamentos.items.length === 0) {
    return (
      <div className="rounded-lg border border-border bg-card p-6 text-center text-sm text-text-muted">
        Nenhum pagamento no período.
      </div>
    )
  }
  return (
    <div className="overflow-x-auto rounded-lg border border-border bg-card">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border bg-muted/30 text-xs uppercase text-text-muted">
            <th className="px-3 py-2 text-left">Data</th>
            <th className="px-3 py-2 text-left">Modelo</th>
            <th className="px-3 py-2 text-right">Valor</th>
            <th className="px-3 py-2 text-left">Forma</th>
            <th className="px-3 py-2 text-left">Observação</th>
            <th className="px-3 py-2"></th>
          </tr>
        </thead>
        <tbody>
          {pagamentos.items.map((p) => (
            <LinhaPagamento key={p.id} pagamento={p} onMudou={onMudou} />
          ))}
        </tbody>
      </table>
    </div>
  )
}

function LinhaPagamento({
  pagamento,
  onMudou,
}: {
  pagamento: RepassePagoResponse
  onMudou: () => void
}) {
  const [excluindo, setExcluindo] = useState(false)

  async function excluir() {
    if (!confirm("Excluir este pagamento? Saldo será recalculado.")) return
    setExcluindo(true)
    try {
      await api(`/v1/financeiro/repasses/pagamentos/${pagamento.id}`, { method: "DELETE" })
      toast.success("Pagamento excluído.")
      onMudou()
    } catch (e) {
      toast.error(e instanceof ApiError ? e.detail : "Erro ao excluir")
    } finally {
      setExcluindo(false)
    }
  }

  return (
    <tr className="border-b border-border/60 hover:bg-muted/20">
      <td className="px-3 py-2 text-text-muted">{formatData(pagamento.data_pagamento)}</td>
      <td className="px-3 py-2">{pagamento.modelo_nome ?? "—"}</td>
      <td className="px-3 py-2 text-right tabular-nums">{formatBRL(pagamento.valor)}</td>
      <td className="px-3 py-2 text-text-muted">{pagamento.forma_pagamento}</td>
      <td className="px-3 py-2 text-text-muted">{pagamento.observacao || "—"}</td>
      <td className="px-3 py-2 text-right">
        <Button size="xs" variant="ghost" onClick={excluir} disabled={excluindo} aria-label="Excluir">
          <Trash2 className="size-3.5" />
        </Button>
      </td>
    </tr>
  )
}
