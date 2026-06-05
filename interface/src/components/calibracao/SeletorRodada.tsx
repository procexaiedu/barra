"use client"

import { useRef, useState } from "react"
import { Download, Upload } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import type { RodadaResumo } from "@/tipos/calibracao"

/** Escolhe a rodada ativa, sobe um .jsonl novo (gerar_conversas.py) e exporta o golden. */
export function SeletorRodada({
  rodadas,
  rodadaId,
  onSelecionar,
  onCriar,
  onExportar,
}: {
  rodadas: RodadaResumo[]
  rodadaId: string | null
  onSelecionar: (id: string) => void
  onCriar: (nome: string, arquivo: File) => Promise<void>
  onExportar: () => Promise<void>
}) {
  const [nome, setNome] = useState("")
  const [enviando, setEnviando] = useState(false)
  const [exportando, setExportando] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  async function enviar(e: React.FormEvent) {
    e.preventDefault()
    const arquivo = fileRef.current?.files?.[0]
    if (!arquivo || !nome.trim()) return
    setEnviando(true)
    try {
      await onCriar(nome.trim(), arquivo)
      setNome("")
      if (fileRef.current) fileRef.current.value = ""
    } finally {
      setEnviando(false)
    }
  }

  async function exportar() {
    setExportando(true)
    try {
      await onExportar()
    } finally {
      setExportando(false)
    }
  }

  return (
    <Card className="flex flex-col gap-4 p-4">
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-[13px] text-text-muted">
          Rodada
          <select
            value={rodadaId ?? ""}
            onChange={(e) => onSelecionar(e.target.value)}
            className="h-9 min-w-56 rounded-lg border border-border bg-background px-3 text-sm text-text-primary"
          >
            <option value="" disabled>
              {rodadas.length ? "Selecione uma rodada" : "Nenhuma rodada — suba um .jsonl"}
            </option>
            {rodadas.map((r) => (
              <option key={r.id} value={r.id}>
                {r.nome} ({r.total_falas} falas)
              </option>
            ))}
          </select>
        </label>

        <Button
          type="button"
          variant="secondary"
          onClick={exportar}
          disabled={!rodadaId || exportando}
        >
          <Download /> {exportando ? "Exportando…" : "Exportar golden.jsonl"}
        </Button>
      </div>

      <form onSubmit={enviar} className="flex flex-wrap items-end gap-3 border-t border-border pt-4">
        <label className="flex flex-col gap-1 text-[13px] text-text-muted">
          Nome da nova rodada
          <Input
            value={nome}
            onChange={(e) => setNome(e.target.value)}
            placeholder="ex.: 2026-06-05-piloto"
            className="min-w-56"
          />
        </label>
        <label className="flex flex-col gap-1 text-[13px] text-text-muted">
          Arquivo .jsonl (gerar_conversas.py)
          <input
            ref={fileRef}
            type="file"
            accept=".jsonl,application/x-ndjson,text/plain"
            className="text-sm text-text-muted file:mr-3 file:rounded-lg file:border file:border-border file:bg-muted file:px-3 file:py-1.5 file:text-sm file:text-text-primary"
          />
        </label>
        <Button type="submit" variant="primary" disabled={enviando}>
          <Upload /> {enviando ? "Subindo…" : "Criar rodada"}
        </Button>
      </form>
    </Card>
  )
}
