"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { api } from "@/lib/api"
import type {
  AvaliacaoResposta,
  AvaliarRequest,
  TurnoObservabilidade,
  TurnosObservabilidadeResponse,
} from "@/tipos/observabilidade"

type Status = "loading" | "success" | "error"

export type OrigemTurnos = "prod" | "e2e"

export interface FiltrosObservabilidade {
  apenasNaoAvaliadas: boolean
  // prod = tráfego real (default); e2e = corridas do harness de avaliação (cliente = Claude Code)
  origem: OrigemTurnos
}

function buildPath(filtros: FiltrosObservabilidade, cursor?: string | null) {
  const p = new URLSearchParams({ limit: "50", origem: filtros.origem })
  if (filtros.apenasNaoAvaliadas) p.set("apenas_nao_avaliadas", "true")
  if (cursor) p.set("cursor", cursor)
  return `/v1/observabilidade?${p.toString()}`
}

export function useObservabilidade(filtros: FiltrosObservabilidade) {
  const [items, setItems] = useState<TurnoObservabilidade[]>([])
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [status, setStatus] = useState<Status>("loading")
  const [error, setError] = useState<string | null>(null)
  const itemsRef = useRef<TurnoObservabilidade[]>([])
  const cursorRef = useRef<string | null>(null)
  const firstDone = useRef(false)

  const load = useCallback(
    async (mode: "replace" | "append" = "replace") => {
      if (!firstDone.current && mode === "replace") setStatus("loading")
      try {
        const cursor = mode === "append" ? cursorRef.current : null
        const res = await api<TurnosObservabilidadeResponse>(buildPath(filtros, cursor))
        const recebidos = Array.isArray(res.items) ? res.items : []
        const novos = mode === "append" ? [...itemsRef.current, ...recebidos] : recebidos
        itemsRef.current = novos
        cursorRef.current = res.next_cursor ?? null
        setItems(novos)
        setNextCursor(res.next_cursor ?? null)
        setStatus("success")
        setError(null)
        firstDone.current = true
      } catch (e) {
        if (!firstDone.current) setStatus("error")
        setError(e instanceof Error ? e.message : "Erro desconhecido")
      }
    },
    [filtros],
  )

  const carregarMais = useCallback(() => {
    if (cursorRef.current) void load("append")
  }, [load])

  const avaliar = useCallback(
    async (respostaIaId: string, body: AvaliarRequest): Promise<AvaliacaoResposta> => {
      const av = await api<AvaliacaoResposta>(`/v1/observabilidade/${respostaIaId}/avaliar`, {
        method: "POST",
        body: JSON.stringify(body),
      })
      itemsRef.current = itemsRef.current.map((t) =>
        t.resposta_ia_id === respostaIaId ? { ...t, avaliacao: av } : t,
      )
      setItems(itemsRef.current)
      return av
    },
    [],
  )

  useEffect(() => {
    firstDone.current = false
    const t = setTimeout(() => void load("replace"), 0)
    return () => clearTimeout(t)
  }, [load])

  return {
    items,
    nextCursor,
    status,
    error,
    carregarMais,
    avaliar,
    recarregar: () => load("replace"),
  }
}
