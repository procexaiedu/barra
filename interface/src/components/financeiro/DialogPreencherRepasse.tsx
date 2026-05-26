"use client"

import { useEffect, useState } from "react"
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Skeleton } from "@/components/ui/skeleton"
import { api, ApiError } from "@/lib/api"
import { toast } from "sonner"
import { formatBRL, formatData } from "@/lib/formatters"
import type {
  AtendimentoSemSnapshotLinha,
  AtendimentosSemSnapshotResponse,
} from "@/tipos/financeiro"

export function DialogPreencherRepasse({
  open,
  onOpenChange,
  modeloId,
  modeloNome,
  onSalvo,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  modeloId: string
  modeloNome: string
  onSalvo: () => void
}) {
  const [itens, setItens] = useState<AtendimentoSemSnapshotLinha[] | null>(null)
  const [selecionados, setSelecionados] = useState<Set<string>>(new Set())
  const [percentual, setPercentual] = useState<string>("40")
  const [salvando, setSalvando] = useState(false)

  useEffect(() => {
    if (!open) return
    // Reset ao abrir: padrão aceito; lint detecta como setState síncrono.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setItens(null)
    setSelecionados(new Set())
    api<AtendimentosSemSnapshotResponse>(
      `/v1/financeiro/atendimentos-sem-snapshot?modelo_id=${modeloId}`
    ).then(
      (r) => {
        setItens(r.items)
        setSelecionados(new Set(r.items.map((x) => x.atendimento_id)))
      },
      () => setItens([])
    )
  }, [open, modeloId])

  function toggle(id: string) {
    const next = new Set(selecionados)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    setSelecionados(next)
  }

  async function salvar() {
    if (selecionados.size === 0) return toast.error("Selecione ao menos um atendimento.")
    const pct = parseFloat(percentual.replace(",", "."))
    if (!Number.isFinite(pct) || pct < 0 || pct > 100) return toast.error("Percentual inválido.")
    setSalvando(true)
    try {
      const r = await api<{ atualizados: number }>(
        "/v1/financeiro/atendimentos/preencher-repasse-retroativo",
        {
          method: "POST",
          body: JSON.stringify({
            atendimento_ids: Array.from(selecionados),
            percentual: pct,
          }),
        }
      )
      toast.success(`${r.atualizados} atendimento(s) atualizado(s).`)
      onSalvo()
    } catch (e) {
      toast.error(e instanceof ApiError ? e.detail : "Erro ao salvar")
    } finally {
      setSalvando(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="w-full max-w-lg rounded-lg bg-card p-6 ring-1 ring-foreground/10">
        <DialogTitle className="text-lg font-semibold">
          Definir repasse retroativo · {modeloNome}
        </DialogTitle>
        <p className="mt-1 text-sm text-text-muted">
          Aplica o percentual escolhido apenas aos atendimentos selecionados (e que ainda
          não tinham snapshot). Cada um vira um evento de correção no histórico.
        </p>

        <div className="mt-4">
          <Label>Percentual (%)</Label>
          <Input
            inputMode="decimal"
            value={percentual}
            onChange={(e) => setPercentual(e.target.value)}
            className="mt-1 w-32"
          />
        </div>

        <div className="mt-4 max-h-72 overflow-y-auto rounded-md border border-border">
          {!itens ? (
            <Skeleton className="h-40" />
          ) : itens.length === 0 ? (
            <div className="p-6 text-center text-sm text-text-muted">
              Nenhum atendimento sem snapshot para esta modelo.
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border bg-muted/30 text-xs uppercase text-text-muted">
                  <th className="px-3 py-2 text-left">
                    <input
                      type="checkbox"
                      checked={selecionados.size === itens.length}
                      onChange={(e) => {
                        setSelecionados(
                          e.target.checked ? new Set(itens.map((x) => x.atendimento_id)) : new Set()
                        )
                      }}
                    />
                  </th>
                  <th className="px-3 py-2 text-left">Data</th>
                  <th className="px-3 py-2 text-left">#</th>
                  <th className="px-3 py-2 text-left">Cliente</th>
                  <th className="px-3 py-2 text-right">Valor</th>
                </tr>
              </thead>
              <tbody>
                {itens.map((a) => (
                  <tr key={a.atendimento_id} className="border-b border-border/60">
                    <td className="px-3 py-2">
                      <input
                        type="checkbox"
                        checked={selecionados.has(a.atendimento_id)}
                        onChange={() => toggle(a.atendimento_id)}
                      />
                    </td>
                    <td className="px-3 py-2 text-text-muted">{formatData(a.fechado_em)}</td>
                    <td className="px-3 py-2 font-mono text-xs">#{a.numero_curto}</td>
                    <td className="px-3 py-2">{a.cliente_nome}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{formatBRL(a.valor_bruto)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="mt-6 flex justify-end gap-2">
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={salvando}>
            Cancelar
          </Button>
          <Button onClick={salvar} disabled={salvando || selecionados.size === 0}>
            {salvando ? "Aplicando…" : `Aplicar (${selecionados.size})`}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
