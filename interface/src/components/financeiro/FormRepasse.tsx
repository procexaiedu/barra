"use client"

import { useEffect, useState } from "react"
import { Dialog, DialogBody, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { api, ApiError } from "@/lib/api"
import { toast } from "sonner"

interface ModeloMini {
  id: string
  nome: string
}

const FORMAS = ["pix", "dinheiro", "outro"] as const
type Forma = (typeof FORMAS)[number]

export function FormRepasse({
  open,
  onOpenChange,
  modeloIdInicial,
  onSalvo,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  modeloIdInicial: string | null
  onSalvo: () => void
}) {
  const [modelos, setModelos] = useState<ModeloMini[]>([])
  const [modeloId, setModeloId] = useState<string>("")
  const [valor, setValor] = useState("")
  const [data, setData] = useState<string>(() => new Date().toISOString().slice(0, 10))
  const [forma, setForma] = useState<Forma>("pix")
  const [observacao, setObservacao] = useState("")
  const [comprovanteKey, setComprovanteKey] = useState<string | null>(null)
  const [uploadando, setUploadando] = useState(false)
  const [salvando, setSalvando] = useState(false)

  useEffect(() => {
    if (!open) return
    // Reset ao abrir: padrão aceito; lint detecta como setState síncrono.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setModeloId(modeloIdInicial ?? "")
    setValor("")
    setObservacao("")
    setComprovanteKey(null)
    setForma("pix")
    setData(new Date().toISOString().slice(0, 10))
    api<{ items: ModeloMini[] }>("/v1/modelos?limit=100").then(
      (r) => setModelos(r.items),
      () => setModelos([])
    )
  }, [open, modeloIdInicial])

  async function uploadComprovante(file: File) {
    setUploadando(true)
    try {
      const { object_key, put_url } = await api<{ object_key: string; put_url: string }>(
        `/v1/financeiro/repasses/pagamentos/comprovante-upload-url?filename=${encodeURIComponent(file.name)}`,
        { method: "POST" }
      )
      const r = await fetch(put_url, { method: "PUT", body: file })
      if (!r.ok) throw new Error(`Upload falhou (${r.status})`)
      setComprovanteKey(object_key)
      toast.success("Comprovante anexado.")
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Falha no upload")
    } finally {
      setUploadando(false)
    }
  }

  async function salvar() {
    if (!modeloId) return toast.error("Escolha a modelo.")
    const valorNum = parseFloat(valor.replace(",", "."))
    if (!Number.isFinite(valorNum) || valorNum <= 0) return toast.error("Valor inválido.")
    setSalvando(true)
    try {
      await api("/v1/financeiro/repasses/pagamentos", {
        method: "POST",
        body: JSON.stringify({
          modelo_id: modeloId,
          data_pagamento: data,
          valor: valorNum,
          forma_pagamento: forma,
          observacao: observacao || null,
          comprovante_object_key: comprovanteKey,
        }),
      })
      toast.success("Pagamento registrado.")
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
        <DialogHeader>
          <DialogTitle className="text-lg font-semibold">Registrar pagamento de repasse</DialogTitle>
        </DialogHeader>
        <DialogBody className="space-y-3">
          <div>
            <Label>Modelo</Label>
            <select
              className="mt-1 h-9 w-full rounded-lg border border-input bg-input px-3 text-sm text-text-primary outline-none transition-colors hover:border-border-strong focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
              value={modeloId}
              onChange={(e) => setModeloId(e.target.value)}
            >
              <option value="">— selecione —</option>
              {modelos.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.nome}
                </option>
              ))}
            </select>
          </div>
          <div className="grid grid-cols-2 gap-3">
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
          </div>
          <div>
            <Label>Forma</Label>
            <div className="mt-1 flex gap-1">
              {FORMAS.map((f) => (
                <Button
                  key={f}
                  type="button"
                  size="sm"
                  variant={forma === f ? "primary" : "outline"}
                  onClick={() => setForma(f)}
                >
                  {f}
                </Button>
              ))}
            </div>
          </div>
          <div>
            <Label>Observação (opcional)</Label>
            <Textarea
              rows={2}
              value={observacao}
              onChange={(e) => setObservacao(e.target.value)}
              className="mt-1"
            />
          </div>
          <div>
            <Label>Comprovante (opcional)</Label>
            <div className="mt-1 flex items-center gap-2">
              <input
                type="file"
                accept="image/*,application/pdf"
                onChange={(e) => {
                  const f = e.target.files?.[0]
                  if (f) uploadComprovante(f)
                }}
                disabled={uploadando}
                className="text-xs"
              />
              {comprovanteKey && (
                <span className="text-xs text-success-500">✓ anexado</span>
              )}
            </div>
          </div>
        </DialogBody>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={salvando}>
            Cancelar
          </Button>
          <Button onClick={salvar} disabled={salvando || !modeloId || !valor}>
            {salvando ? "Salvando…" : "Salvar"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
