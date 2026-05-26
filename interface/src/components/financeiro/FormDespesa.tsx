"use client"

import { useState } from "react"
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { api, ApiError } from "@/lib/api"
import { toast } from "sonner"
import {
  CATEGORIAS_DESPESA,
  ROTULO_CATEGORIA,
  type CategoriaDespesa,
} from "@/tipos/financeiro"

export function FormDespesa({
  open,
  onOpenChange,
  onSalvo,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  onSalvo: () => void
}) {
  const [categoria, setCategoria] = useState<CategoriaDespesa>("outro")
  const [valor, setValor] = useState("")
  const [data, setData] = useState<string>(() => new Date().toISOString().slice(0, 10))
  const [descricao, setDescricao] = useState("")
  const [salvando, setSalvando] = useState(false)

  function reset() {
    setCategoria("outro")
    setValor("")
    setData(new Date().toISOString().slice(0, 10))
    setDescricao("")
  }

  async function salvar() {
    const valorNum = parseFloat(valor.replace(",", "."))
    if (!Number.isFinite(valorNum) || valorNum <= 0) {
      toast.error("Valor inválido.")
      return
    }
    setSalvando(true)
    try {
      await api("/v1/financeiro/despesas", {
        method: "POST",
        body: JSON.stringify({
          categoria,
          valor: valorNum,
          data,
          descricao: descricao || null,
        }),
      })
      toast.success("Despesa lançada.")
      reset()
      onSalvo()
    } catch (e) {
      toast.error(e instanceof ApiError ? e.detail : "Erro ao salvar")
    } finally {
      setSalvando(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="w-full max-w-md rounded-lg bg-card p-6 ring-1 ring-foreground/10">
        <DialogTitle className="text-lg font-semibold">Nova despesa</DialogTitle>
        <div className="mt-4 space-y-3">
          <div>
            <Label>Categoria</Label>
            <select
              className="mt-1 w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
              value={categoria}
              onChange={(e) => setCategoria(e.target.value as CategoriaDespesa)}
            >
              {CATEGORIAS_DESPESA.map((c) => (
                <option key={c} value={c}>
                  {ROTULO_CATEGORIA[c]}
                </option>
              ))}
            </select>
          </div>
          <div>
            <Label>Valor (R$)</Label>
            <Input
              inputMode="decimal"
              placeholder="0,00"
              value={valor}
              onChange={(e) => setValor(e.target.value)}
              className="mt-1"
            />
          </div>
          <div>
            <Label>Data</Label>
            <Input
              type="date"
              value={data}
              onChange={(e) => setData(e.target.value)}
              className="mt-1"
            />
          </div>
          <div>
            <Label>Descrição (opcional)</Label>
            <Textarea
              rows={2}
              value={descricao}
              onChange={(e) => setDescricao(e.target.value)}
              className="mt-1"
            />
          </div>
        </div>
        <div className="mt-6 flex justify-end gap-2">
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={salvando}>
            Cancelar
          </Button>
          <Button onClick={salvar} disabled={salvando || !valor}>
            {salvando ? "Salvando…" : "Salvar"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
