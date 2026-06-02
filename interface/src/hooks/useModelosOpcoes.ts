"use client"

import { useEffect, useState } from "react"
import { api, ApiError } from "@/lib/api"

export interface ModeloOpcao {
  id: string
  nome: string
}

interface ModelosResponse {
  items: { id: string; nome: string }[]
  next_cursor: string | null
}

/** Fonte única das opções de modelo para os filtros (antes duplicado em
 *  FiltroModelo e FiltroModeloMulti). `null` enquanto carrega; `[]` em erro/401. */
export function useModelosOpcoes(): { modelos: ModeloOpcao[] | null } {
  const [modelos, setModelos] = useState<ModeloOpcao[] | null>(null)

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

  return { modelos }
}
