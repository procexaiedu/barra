"use client"

import { useEffect, useMemo, useState } from "react"
import { api, ApiError } from "@/lib/api"

interface ModeloListaItem {
  id: string
  nome: string
}

interface ModelosResponse {
  items: ModeloListaItem[]
  next_cursor: string | null
}

interface Props {
  modeloId: string | null
  onChange: (modeloId: string | null) => void
  hideTodas?: boolean
}

export function FiltroModelo({ modeloId, onChange, hideTodas }: Props) {
  const [modelos, setModelos] = useState<ModeloListaItem[] | null>(null)

  useEffect(() => {
    let cancelado = false
    api<ModelosResponse>("/v1/modelos?limit=100")
      .then((res) => {
        if (cancelado) return
        setModelos(res.items.map((m) => ({ id: m.id, nome: m.nome })))
      })
      .catch((e) => {
        if (cancelado) return
        if (e instanceof ApiError && e.status === 401) return
        setModelos([])
      })
    return () => {
      cancelado = true
    }
  }, [])

  const carregando = modelos === null
  const opcoes = useMemo(() => modelos ?? [], [modelos])

  // Com hideTodas não existe opção vazia, então um <select> sem value casado
  // exibe o primeiro modelo da lista sem disparar onChange — a UI mostra um
  // modelo "selecionado" enquanto o estado do pai segue null. Sincroniza o
  // estado com o que está visível assim que a lista carrega.
  useEffect(() => {
    if (!hideTodas) return
    if (modeloId != null) return
    const primeiro = opcoes[0]
    if (primeiro) onChange(primeiro.id)
  }, [hideTodas, modeloId, opcoes, onChange])

  return (
    <label className="flex items-center gap-2">
      <span className="sr-only">Modelo</span>
      <select
        value={modeloId ?? ""}
        onChange={(event) => onChange(event.target.value || null)}
        disabled={carregando}
        className="h-9 rounded-md border border-input bg-input px-3 text-sm text-text-primary outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:opacity-50"
      >
        {!hideTodas && <option value="">Todas</option>}
        {opcoes.map((m) => (
          <option key={m.id} value={m.id}>
            {m.nome}
          </option>
        ))}
      </select>
    </label>
  )
}
