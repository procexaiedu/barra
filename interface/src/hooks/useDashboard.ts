"use client"

import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import { api, ApiError } from "@/lib/api"
import { subscribeTabelas } from "@/lib/realtime"
import { supabase } from "@/lib/supabase"
import type {
  DashboardEscaladasResponse,
  DashboardResumo,
  FiltroPeriodo,
} from "@/tipos/dashboard"

type Status = "loading" | "success" | "error"
type EscaladasStatus = "idle" | "loading" | "success" | "error"

const PERIODOS_VALIDOS: ReadonlySet<string> = new Set(["hoje", "7d", "30d", "tudo", "custom"])

export interface FiltrosDashboard {
  periodo: FiltroPeriodo
  de: string | null
  ate: string | null
  modelo_id: string | null
}

const filtrosDefault: FiltrosDashboard = {
  periodo: "7d",
  de: null,
  ate: null,
  modelo_id: null,
}

function parseFiltrosFromSearch(params: URLSearchParams): FiltrosDashboard {
  const periodoRaw = params.get("periodo")
  const periodo = (periodoRaw && PERIODOS_VALIDOS.has(periodoRaw) ? periodoRaw : "7d") as FiltroPeriodo
  const de = params.get("de")
  const ate = params.get("ate")
  const modelo_id = params.get("modelo_id")
  if (periodo === "custom") {
    if (!de || !ate || !/^\d{4}-\d{2}-\d{2}$/.test(de) || !/^\d{4}-\d{2}-\d{2}$/.test(ate)) {
      return { ...filtrosDefault, modelo_id }
    }
    return { periodo, de, ate, modelo_id }
  }
  return { periodo, de: null, ate: null, modelo_id }
}

function montarPath(filtros: FiltrosDashboard, recurso: "" | "/escaladas"): string {
  const params = new URLSearchParams()
  params.set("periodo", filtros.periodo)
  if (filtros.periodo === "custom" && filtros.de && filtros.ate) {
    params.set("de", filtros.de)
    params.set("ate", filtros.ate)
  }
  if (filtros.modelo_id) params.set("modelo_id", filtros.modelo_id)
  return `/v1/dashboard${recurso}?${params.toString()}`
}

function montarQueryString(filtros: FiltrosDashboard): string {
  const params = new URLSearchParams()
  if (filtros.periodo !== "7d") params.set("periodo", filtros.periodo)
  if (filtros.periodo === "custom" && filtros.de && filtros.ate) {
    params.set("de", filtros.de)
    params.set("ate", filtros.ate)
  }
  if (filtros.modelo_id) params.set("modelo_id", filtros.modelo_id)
  const s = params.toString()
  return s ? `?${s}` : ""
}

export function useDashboard() {
  const router = useRouter()
  const searchParams = useSearchParams()

  const filtrosFromUrl = useMemo(
    () => parseFiltrosFromSearch(new URLSearchParams(searchParams.toString())),
    [searchParams]
  )

  const [data, setData] = useState<DashboardResumo | null>(null)
  const [status, setStatus] = useState<Status>("loading")
  const [error, setError] = useState<string | null>(null)

  const filtros = filtrosFromUrl

  const filtrosRef = useRef(filtros)
  const firstLoadDone = useRef(false)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const realtimeEvents = useRef(0)
  const abortRef = useRef<AbortController | null>(null)

  const fetchResumo = useCallback(async () => {
    const filtrosAtuais = filtrosRef.current
    if (abortRef.current) abortRef.current.abort()
    const controller = new AbortController()
    abortRef.current = controller
    if (!firstLoadDone.current) setStatus("loading")
    try {
      const res = await api<DashboardResumo>(montarPath(filtrosAtuais, ""), {
        signal: controller.signal,
      })
      if (controller.signal.aborted) return
      setData(res)
      setStatus("success")
      setError(null)
      firstLoadDone.current = true
    } catch (e) {
      if (controller.signal.aborted) return
      if (e instanceof DOMException && e.name === "AbortError") return
      if (!firstLoadDone.current) setStatus("error")
      const detail = e instanceof ApiError ? e.detail : e instanceof Error ? e.message : "Erro desconhecido"
      setError(detail)
    }
  }, [])

  const aplicarFiltros = useCallback(
    (proximo: FiltrosDashboard) => {
      router.replace(`/dashboard${montarQueryString(proximo)}`, { scroll: false })
    },
    [router]
  )

  const setPeriodoPreset = useCallback(
    (periodo: Exclude<FiltroPeriodo, "custom">) => {
      aplicarFiltros({ ...filtrosRef.current, periodo, de: null, ate: null })
    },
    [aplicarFiltros]
  )

  const setPeriodoCustom = useCallback(
    (de: string, ate: string) => {
      aplicarFiltros({ ...filtrosRef.current, periodo: "custom", de, ate })
    },
    [aplicarFiltros]
  )

  const setModeloId = useCallback(
    (modelo_id: string | null) => {
      aplicarFiltros({ ...filtrosRef.current, modelo_id })
    },
    [aplicarFiltros]
  )

  const debouncedRefetch = useCallback(() => {
    realtimeEvents.current += 1
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => {
      if (process.env.NODE_ENV !== "production" && realtimeEvents.current > 1) {
        console.debug(`[dashboard] refetch coalescido por ${realtimeEvents.current} eventos`)
      }
      realtimeEvents.current = 0
      fetchResumo()
    }, 250)
  }, [fetchResumo])

  useEffect(() => {
    filtrosRef.current = filtros
    fetchResumo()
  }, [filtros, fetchResumo])

  useEffect(() => {
    const cleanupRealtime = subscribeTabelas(
      "dashboard",
      ["atendimentos", "comprovantes_pix", "escaladas"],
      debouncedRefetch
    )

    const { data: authSub } = supabase.auth.onAuthStateChange((evt, session) => {
      if ((evt === "TOKEN_REFRESHED" || evt === "SIGNED_IN") && session) {
        supabase.realtime.setAuth(session.access_token)
      }
      if (evt === "SIGNED_OUT") router.replace("/login")
    })

    return () => {
      cleanupRealtime()
      authSub.subscription.unsubscribe()
      if (debounceRef.current) clearTimeout(debounceRef.current)
      if (abortRef.current) abortRef.current.abort()
    }
  }, [debouncedRefetch, router])

  const [escaladasResp, setEscaladasResp] = useState<DashboardEscaladasResponse | null>(null)
  const [escaladasStatus, setEscaladasStatus] = useState<EscaladasStatus>("idle")
  const [escaladasError, setEscaladasError] = useState<string | null>(null)
  const escaladasAbortRef = useRef<AbortController | null>(null)

  const carregarEscaladas = useCallback(async () => {
    if (escaladasAbortRef.current) escaladasAbortRef.current.abort()
    const controller = new AbortController()
    escaladasAbortRef.current = controller
    setEscaladasStatus("loading")
    setEscaladasError(null)
    try {
      const res = await api<DashboardEscaladasResponse>(
        montarPath(filtros, "/escaladas"),
        { signal: controller.signal }
      )
      if (controller.signal.aborted) return
      setEscaladasResp(res)
      setEscaladasStatus("success")
    } catch (e) {
      if (controller.signal.aborted) return
      if (e instanceof DOMException && e.name === "AbortError") return
      setEscaladasStatus("error")
      const detail = e instanceof ApiError ? e.detail : e instanceof Error ? e.message : "Erro desconhecido"
      setEscaladasError(detail)
    }
  }, [filtros])

  const resetEscaladas = useCallback(() => {
    if (escaladasAbortRef.current) escaladasAbortRef.current.abort()
    setEscaladasResp(null)
    setEscaladasStatus("idle")
    setEscaladasError(null)
  }, [])

  return {
    filtros,
    data,
    status,
    error,
    refetch: fetchResumo,
    setPeriodoPreset,
    setPeriodoCustom,
    setModeloId,
    escaladas: {
      data: escaladasResp,
      status: escaladasStatus,
      error: escaladasError,
      load: carregarEscaladas,
      reset: resetEscaladas,
    },
  }
}
