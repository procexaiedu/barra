"use client"

import { useEffect, useState } from "react"
import { Dialog, DialogBody, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
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
      <DialogContent size="sm">
        <DialogHeader className="flex-col items-start gap-1">
          <DialogTitle className="text-lg font-semibold">
            Definir repasse retroativo · {modeloNome}
          </DialogTitle>
          <p className="text-sm text-text-muted">
            Aplica o percentual escolhido apenas aos atendimentos selecionados (e que ainda
            não tinham snapshot). Cada um vira um evento de correção no histórico.
          </p>
        </DialogHeader>

        <DialogBody>
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
                <tr className="border-b border-border bg-muted/30 text-[10.5px] uppercase tracking-[0.1em] text-text-muted">
                  <th className="px-3 py-2 text-left font-medium">
                    <input
                      type="checkbox"
                      checked={selecionados.size === itens.length}
                      onChange={(e) => {
                        setSelecionados(
                          e.target.checked ? new Set(itens.map((x) => x.atendimento_id)) : new Set()
                        )
                      }}
                      className="h-3.5 w-3.5 rounded border-input bg-transparent accent-primary"
                    />
                  </th>
                  <th className="px-3 py-2 text-left font-medium">Data</th>
                  <th className="px-3 py-2 text-left font-medium">#</th>
                  <th className="px-3 py-2 text-left font-medium">Cliente</th>
                  <th className="px-3 py-2 text-right font-medium">Valor</th>
                </tr>
              </thead>
              <tbody>
                {itens.map((a) => (
                  <tr key={a.atendimento_id} className="border-b border-border/60 transition-colors hover:bg-muted/25 last:border-b-0">
                    <td className="px-3 py-2">
                      <input
                        type="checkbox"
                        checked={selecionados.has(a.atendimento_id)}
                        onChange={() => toggle(a.atendimento_id)}
                        className="h-3.5 w-3.5 rounded border-input bg-transparent accent-primary"
                      />
                    </td>
                    <td className="px-3 py-2 font-mono tabular-nums text-text-muted">{formatData(a.fechado_em)}</td>
                    <td className="px-3 py-2 font-mono text-xs tabular-nums">#{a.numero_curto}</td>
                    <td className="px-3 py-2 text-text-primary">{a.cliente_nome}</td>
                    <td className="px-3 py-2 text-right font-mono tabular-nums">{formatBRL(a.valor_bruto)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
        </DialogBody>

        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={salvando}>
            Cancelar
          </Button>
          <Button onClick={salvar} disabled={salvando || selecionados.size === 0}>
            {salvando ? "Aplicando…" : `Aplicar (${selecionados.size})`}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
