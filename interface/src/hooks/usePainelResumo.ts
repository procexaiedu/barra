"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { useRouter } from "next/navigation"
import { api } from "@/lib/api"
import { supabase } from "@/lib/supabase"
import { subscribeTabelas } from "@/lib/realtime"
import type { PainelResumo } from "@/tipos/painel"

type Status = "loading" | "success" | "error"

export function usePainelResumo() {
  const [data, setData] = useState<PainelResumo | null>(null)
  const [status, setStatus] = useState<Status>("loading")
  const [error, setError] = useState<string | null>(null)
  const router = useRouter()
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const firstLoadDone = useRef(false)

  const fetchResumo = useCallback(async () => {
    if (!firstLoadDone.current) setStatus("loading")
    try {
      const res = await api<PainelResumo>("/v1/painel/resumo")
      setData(res)
      setStatus("success")
      setError(null)
      firstLoadDone.current = true
    } catch (e) {
      if (!firstLoadDone.current) setStatus("error")
      setError(e instanceof Error ? e.message : "Erro desconhecido")
    }
  }, [])

  const debouncedRefetch = useCallback(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => {
      fetchResumo()
    }, 250)
  }, [fetchResumo])

  useEffect(() => {
    const controller = new AbortController()

    const init = async () => {
      await fetchResumo()
    }
    init()

    const cleanupRealtime = subscribeTabelas(
      "painel",
      ["atendimentos", "comprovantes_pix", "bloqueios", "eventos"],
      debouncedRefetch
    )

    const { data: authSub } = supabase.auth.onAuthStateChange((evt, session) => {
      if ((evt === "TOKEN_REFRESHED" || evt === "SIGNED_IN") && session) {
        supabase.realtime.setAuth(session.access_token)
      }
      if (evt === "SIGNED_OUT") router.replace("/login")
    })

    return () => {
      controller.abort()
      cleanupRealtime()
      authSub.subscription.unsubscribe()
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
  }, [fetchResumo, debouncedRefetch, router])

  return { data, status, error, refetch: fetchResumo }
}
