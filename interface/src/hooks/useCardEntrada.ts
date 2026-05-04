"use client"

import { useEffect, useRef, useState } from "react"
import type { CardDestaque } from "@/tipos/painel"

export function useCardEntrada(cards: CardDestaque[]): Set<string> {
  const prevRef = useRef<Set<string>>(new Set())
  // null = ainda não inicializado (antes do primeiro load com dados)
  const initializedRef = useRef(false)
  const [novos, setNovos] = useState<Set<string>>(new Set())

  useEffect(() => {
    const currentIds = new Set(cards.map((c) => c.atendimento_id))

    if (!initializedRef.current) {
      if (cards.length > 0) {
        initializedRef.current = true
        prevRef.current = currentIds
      }
      return
    }

    const entradas = new Set<string>()
    for (const id of currentIds) {
      if (!prevRef.current.has(id)) entradas.add(id)
    }
    prevRef.current = currentIds

    if (entradas.size > 0) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setNovos(entradas)
      const t = setTimeout(() => setNovos(new Set()), 700)
      return () => clearTimeout(t)
    }
  }, [cards])

  return novos
}
