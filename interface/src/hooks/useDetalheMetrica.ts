"use client"

import { useCallback, useEffect, useState } from "react"
import { api } from "@/lib/api"
import type { ItemAberto, ItemFechamento, ItemPerda } from "@/tipos/painel"

export type TipoModal = "abertos" | "fechamentos" | "perdas"

const ENDPOINT: Record<TipoModal, string> = {
  abertos: "/v1/painel/detalhe/abertos",
  fechamentos: "/v1/painel/detalhe/fechamentos-hoje",
  perdas: "/v1/painel/detalhe/perdas-hoje",
}

export interface DetalheMetricaState {
  modalAberto: TipoModal | null
  mostrarLucro: boolean
  tituloCustom: string | null
  detalheAbertos: ItemAberto[]
  detalheFechamentos: ItemFechamento[]
  detalhePerdas: ItemPerda[]
  loading: boolean
  error: string | null
  abrir: (tipo: TipoModal, lucro?: boolean, titulo?: string) => void
  fechar: () => void
  retry: () => void
}

export function useDetalheMetrica(modeloId: string | null): DetalheMetricaState {
  const [modalAberto, setModalAberto] = useState<TipoModal | null>(null)
  const [mostrarLucro, setMostrarLucro] = useState(false)
  const [tituloCustom, setTituloCustom] = useState<string | null>(null)
  const [detalheAbertos, setDetalheAbertos] = useState<ItemAberto[]>([])
  const [detalheFechamentos, setDetalheFechamentos] = useState<ItemFechamento[]>([])
  const [detalhePerdas, setDetalhePerdas] = useState<ItemPerda[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [tentativa, setTentativa] = useState(0)

  useEffect(() => {
    if (!modalAberto) return
    let active = true
    const tipo = modalAberto
    const params = modeloId ? `?modelo_id=${modeloId}` : ""
    api<{ itens: ItemAberto[] | ItemFechamento[] | ItemPerda[] }>(`${ENDPOINT[tipo]}${params}`)
      .then((d) => {
        if (!active) return
        if (tipo === "abertos") {
          setDetalheAbertos(d.itens as ItemAberto[])
        } else if (tipo === "fechamentos") {
          setDetalheFechamentos(
            [...(d.itens as ItemFechamento[])].sort(
              (a, b) => (b.valor_final ?? 0) - (a.valor_final ?? 0)
            )
          )
        } else {
          setDetalhePerdas(d.itens as ItemPerda[])
        }
        setLoading(false)
      })
      .catch((e) => {
        if (!active) return
        setError(e instanceof Error ? e.message : "Erro ao carregar detalhes.")
        setLoading(false)
      })
    return () => { active = false }
  }, [modalAberto, modeloId, tentativa])

  const abrir = useCallback((tipo: TipoModal, lucro = false, titulo?: string) => {
    setDetalheAbertos([])
    setDetalheFechamentos([])
    setDetalhePerdas([])
    setMostrarLucro(lucro)
    setTituloCustom(titulo ?? null)
    setError(null)
    setLoading(true)
    setModalAberto(tipo)
  }, [])

  const fechar = useCallback(() => setModalAberto(null), [])

  const retry = useCallback(() => {
    setError(null)
    setLoading(true)
    setTentativa((c) => c + 1)
  }, [])

  return {
    modalAberto, mostrarLucro, tituloCustom,
    detalheAbertos, detalheFechamentos, detalhePerdas,
    loading, error,
    abrir, fechar, retry,
  }
}
