"use client"

import { useCallback, useEffect, useMemo, useRef, useState, useTransition } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import { api, ApiError } from "@/lib/api"
import { subscribeTabelas } from "@/lib/realtime"
import { supabase } from "@/lib/supabase"
import type {
  DashboardEscaladasResponse,
  DashboardResumo,
  FiltroPeriodo,
  SerieMetrica,
  SerieResposta,
} from "@/tipos/dashboard"

type Status = "loading" | "success" | "error"
type EscaladasStatus = "idle" | "loading" | "success" | "error"

const PERIODOS_VALIDOS: ReadonlySet<string> = new Set(["hoje", "7d", "30d", "mes", "tudo", "custom"])

export interface FiltrosDashboard {
  periodo: FiltroPeriodo
  de: string | null
  ate: string | null
  modelo_ids: string[]
}

const filtrosDefault: FiltrosDashboard = {
  periodo: "tudo",
  de: null,
  ate: null,
  modelo_ids: [],
}

function parseFiltrosFromSearch(params: URLSearchParams): FiltrosDashboard {
  const periodoRaw = params.get("periodo")
  const periodo = (periodoRaw && PERIODOS_VALIDOS.has(periodoRaw) ? periodoRaw : "tudo") as FiltroPeriodo
  const de = params.get("de")
  const ate = params.get("ate")
  const modelo_ids = params.getAll("modelo_id")
  if (periodo === "custom") {
    if (!de || !ate || !/^\d{4}-\d{2}-\d{2}$/.test(de) || !/^\d{4}-\d{2}-\d{2}$/.test(ate)) {
      return { ...filtrosDefault, modelo_ids }
    }
    return { periodo, de, ate, modelo_ids }
  }
  return { periodo, de: null, ate: null, modelo_ids }
}

function montarPath(filtros: FiltrosDashboard, recurso: "" | "/escaladas"): string {
  const params = new URLSearchParams()
  params.set("periodo", filtros.periodo)
  if (filtros.periodo === "custom" && filtros.de && filtros.ate) {
    params.set("de", filtros.de)
    params.set("ate", filtros.ate)
  }
  for (const id of filtros.modelo_ids) params.append("modelo_id", id)
  return `/v1/dashboard${recurso}?${params.toString()}`
}

function montarPathSerie(metrica: SerieMetrica, modeloIds: string[]): string {
  const params = new URLSearchParams()
  params.set("metrica", metrica)
  params.set("unidade", "semana")
  params.set("n", "12")
  for (const id of modeloIds) params.append("modelo_id", id)
  return `/v1/dashboard/serie?${params.toString()}`
}

// Sparklines exibidos hoje na tela. Mudar aqui se quiser adicionar/remover.
const METRICAS_SPARKLINE: SerieMetrica[] = [
  "conversao",
  "liquido",
  "fechamentos",
  "perdas",
  "escaladas",
]

function montarQueryString(filtros: FiltrosDashboard): string {
  const params = new URLSearchParams()
  if (filtros.periodo !== "tudo") params.set("periodo", filtros.periodo)
  if (filtros.periodo === "custom" && filtros.de && filtros.ate) {
    params.set("de", filtros.de)
    params.set("ate", filtros.ate)
  }
  for (const id of filtros.modelo_ids) params.append("modelo_id", id)
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
  const [series, setSeries] = useState<Partial<Record<SerieMetrica, SerieResposta>>>({})
  const [isPending, startTransition] = useTransition()

  const filtros = filtrosFromUrl

  const filtrosRef = useRef(filtros)
  const firstLoadDone = useRef(false)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const realtimeEvents = useRef(0)
  const abortRef = useRef<AbortController | null>(null)
  const seriesAbortRef = useRef<AbortController | null>(null)

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

  const fetchSeries = useCallback(async () => {
    const filtrosAtuais = filtrosRef.current
    if (seriesAbortRef.current) seriesAbortRef.current.abort()
    const controller = new AbortController()
    seriesAbortRef.current = controller
    try {
      const resultados = await Promise.all(
        METRICAS_SPARKLINE.map((metrica) =>
          api<SerieResposta>(montarPathSerie(metrica, filtrosAtuais.modelo_ids), {
            signal: controller.signal,
          }).catch((e: unknown) => {
            // Falha individual de série não derruba a tela — apenas omitimos.
            if (process.env.NODE_ENV !== "production") {
              console.debug(`[dashboard] série ${metrica} falhou`, e)
            }
            return null
          })
        )
      )
      if (controller.signal.aborted) return
      const proximo: Partial<Record<SerieMetrica, SerieResposta>> = {}
      METRICAS_SPARKLINE.forEach((metrica, idx) => {
        const res = resultados[idx]
        if (res) proximo[metrica] = res
      })
      setSeries(proximo)
    } catch {
      // Best-effort — sparkline ausente não bloqueia a UI.
    }
  }, [])

  const aplicarFiltros = useCallback(
    (proximo: FiltrosDashboard) => {
      startTransition(() => {
        router.replace(`/dashboard${montarQueryString(proximo)}`, { scroll: false })
      })
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

  const setModeloIds = useCallback(
    (modelo_ids: string[]) => {
      aplicarFiltros({ ...filtrosRef.current, modelo_ids })
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
      fetchSeries()
    }, 250)
  }, [fetchResumo, fetchSeries])

  useEffect(() => {
    filtrosRef.current = filtros
    fetchResumo()
    fetchSeries()
  }, [filtros, fetchResumo, fetchSeries])

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
      if (seriesAbortRef.current) seriesAbortRef.current.abort()
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

  // Verdadeiro enquanto a navegação por filtro estiver em transição OU enquanto
  // o fetch dela ainda não tiver chegado — usado para o efeito de dimm na tela.
  // Usa `data !== null` em vez de `firstLoadDone.current` (refs não podem ser lidos no render).
  const isRefreshing = isPending || (status === "loading" && data !== null)

  return {
    filtros,
    data,
    status,
    error,
    series,
    isRefreshing,
    refetch: fetchResumo,
    refetchSeries: fetchSeries,
    setPeriodoPreset,
    setPeriodoCustom,
    setModeloIds,
    escaladas: {
      data: escaladasResp,
      status: escaladasStatus,
      error: escaladasError,
      load: carregarEscaladas,
      reset: resetEscaladas,
    },
  }
}
