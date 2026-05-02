"use client"

import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { useRouter } from "next/navigation"
import { api } from "@/lib/api"
import { subscribeTabelas } from "@/lib/realtime"
import { supabase } from "@/lib/supabase"
import type {
  AgendaResponse,
  AtualizarBloqueioInput,
  BloqueioAgenda,
  CriarBloqueioInput,
  VisaoAgenda,
} from "@/tipos/agenda"

type Status = "loading" | "success" | "error"

const BRT_OFFSET = "-03:00"

function partsEmSaoPaulo(date: Date) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/Sao_Paulo",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(date)
  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? ""
  return { ano: get("year"), mes: get("month"), dia: get("day") }
}

export function dataInputSaoPaulo(date = new Date()) {
  const p = partsEmSaoPaulo(date)
  return `${p.ano}-${p.mes}-${p.dia}`
}

export function dataBrt(iso: string): string {
  const p = partsEmSaoPaulo(new Date(iso))
  return `${p.ano}-${p.mes}-${p.dia}`
}

export function isoAgenda(data: string, horario: string) {
  if (horario === "24:00") {
    const d = dataDeInput(data)
    d.setDate(d.getDate() + 1)
    return `${dataInput(d)}T00:00:00${BRT_OFFSET}`
  }
  return `${data}T${horario}:00${BRT_OFFSET}`
}

export function dataDeInput(data: string) {
  return new Date(`${data}T12:00:00${BRT_OFFSET}`)
}

export function dataInput(date: Date) {
  const ano = date.getFullYear()
  const mes = String(date.getMonth() + 1).padStart(2, "0")
  const dia = String(date.getDate()).padStart(2, "0")
  return `${ano}-${mes}-${dia}`
}

function inicioSemana(date: Date) {
  const d = new Date(date)
  const dia = d.getDay()
  const deslocamento = dia === 0 ? -6 : 1 - dia
  d.setDate(d.getDate() + deslocamento)
  return d
}

function fimSemana(date: Date) {
  const d = inicioSemana(date)
  d.setDate(d.getDate() + 6)
  return d
}

function fimMes(date: Date) {
  return new Date(date.getFullYear(), date.getMonth() + 1, 0)
}

function periodoVisivel(visao: VisaoAgenda, dataSelecionada: string) {
  const base = dataDeInput(dataSelecionada)
  if (visao === "dia") {
    return {
      inicio: `${dataSelecionada}T00:00:00${BRT_OFFSET}`,
      fim: `${dataSelecionada}T23:59:59${BRT_OFFSET}`,
      label: new Intl.DateTimeFormat("pt-BR", {
        day: "2-digit",
        month: "long",
        year: "numeric",
        timeZone: "America/Sao_Paulo",
      }).format(base),
    }
  }
  if (visao === "semana") {
    const inicio = inicioSemana(base)
    const fim = fimSemana(base)
    return {
      inicio: `${dataInput(inicio)}T00:00:00${BRT_OFFSET}`,
      fim: `${dataInput(fim)}T23:59:59${BRT_OFFSET}`,
      label: `${dataInput(inicio).slice(8, 10)}-${dataInput(fim).slice(8, 10)} ${new Intl.DateTimeFormat("pt-BR", { month: "long", year: "numeric" }).format(fim)}`,
    }
  }
  const inicio = new Date(base.getFullYear(), base.getMonth(), 1)
  const fim = fimMes(base)
  return {
    inicio: `${dataInput(inicio)}T00:00:00${BRT_OFFSET}`,
    fim: `${dataInput(fim)}T23:59:59${BRT_OFFSET}`,
    label: new Intl.DateTimeFormat("pt-BR", {
      month: "long",
      year: "numeric",
      timeZone: "America/Sao_Paulo",
    }).format(base),
  }
}

function deslocar(data: string, visao: VisaoAgenda, direcao: -1 | 1) {
  const d = dataDeInput(data)
  if (visao === "dia") d.setDate(d.getDate() + direcao)
  if (visao === "semana") d.setDate(d.getDate() + 7 * direcao)
  if (visao === "mes") d.setMonth(d.getMonth() + direcao, 1)
  return dataInput(d)
}

export function useAgenda() {
  const hoje = useMemo(() => dataInputSaoPaulo(), [])
  const [visao, setVisao] = useState<VisaoAgenda>("mes")
  const [dataSelecionada, setDataSelecionada] = useState(hoje)
  const [modeloId, setModeloId] = useState<string | null>(null)
  const [agenda, setAgenda] = useState<AgendaResponse | null>(null)
  const [status, setStatus] = useState<Status>("loading")
  const [error, setError] = useState<string | null>(null)
  const firstDone = useRef(false)
  const refetchTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const realtimeEvents = useRef(0)
  const router = useRouter()

  const periodo = useMemo(
    () => periodoVisivel(visao, dataSelecionada),
    [dataSelecionada, visao]
  )

  const carregar = useCallback(async () => {
    if (!firstDone.current) setStatus("loading")
    try {
      const params = new URLSearchParams({ inicio: periodo.inicio, fim: periodo.fim })
      if (modeloId) params.append("modelo_id", modeloId)
      const res = await api<AgendaResponse>(`/v1/agenda/bloqueios?${params.toString()}`)
      setAgenda(res)
      setStatus("success")
      setError(null)
      firstDone.current = true
    } catch (e) {
      if (!firstDone.current) setStatus("error")
      setError(e instanceof Error ? e.message : "Erro desconhecido")
    }
  }, [periodo.fim, periodo.inicio, modeloId])

  const debouncedRefetch = useCallback(() => {
    realtimeEvents.current += 1
    if (refetchTimer.current) clearTimeout(refetchTimer.current)
    refetchTimer.current = setTimeout(() => {
      if (process.env.NODE_ENV !== "production" && realtimeEvents.current > 1) {
        console.debug(`[agenda] refetch coalescido por ${realtimeEvents.current} eventos`)
      }
      realtimeEvents.current = 0
      carregar()
    }, 250)
  }, [carregar])

  useEffect(() => {
    const timer = setTimeout(() => {
      carregar()
    }, 0)
    return () => clearTimeout(timer)
  }, [carregar])

  useEffect(() => {
    const cleanupRealtime = subscribeTabelas("agenda", ["bloqueios", "eventos"], debouncedRefetch)
    const { data: authSub } = supabase.auth.onAuthStateChange((evt, session) => {
      if ((evt === "TOKEN_REFRESHED" || evt === "SIGNED_IN") && session) {
        supabase.realtime.setAuth(session.access_token)
      }
      if (evt === "SIGNED_OUT") router.replace("/login")
    })
    return () => {
      cleanupRealtime()
      authSub.subscription.unsubscribe()
      if (refetchTimer.current) clearTimeout(refetchTimer.current)
    }
  }, [debouncedRefetch, router])

  const criarBloqueio = useCallback(async (input: CriarBloqueioInput) => {
    await api<BloqueioAgenda>("/v1/agenda/bloqueios", {
      method: "POST",
      body: JSON.stringify(input),
    })
    await carregar()
  }, [carregar])

  const atualizarBloqueio = useCallback(async (id: string, input: AtualizarBloqueioInput) => {
    await api<BloqueioAgenda>(`/v1/agenda/bloqueios/${id}`, {
      method: "PATCH",
      body: JSON.stringify(input),
    })
    await carregar()
  }, [carregar])

  const cancelarBloqueio = useCallback(async (id: string, confirmar: boolean) => {
    await api<{ ok: boolean }>(`/v1/agenda/bloqueios/${id}/cancelar`, {
      method: "POST",
      body: JSON.stringify({ confirmar }),
    })
    await carregar()
  }, [carregar])

  return {
    agenda,
    status,
    error,
    visao,
    setVisao,
    dataSelecionada,
    setDataSelecionada,
    modeloId,
    setModeloId,
    periodo,
    hoje: () => setDataSelecionada(dataInputSaoPaulo()),
    anterior: () => setDataSelecionada((atual) => deslocar(atual, visao, -1)),
    proximo: () => setDataSelecionada((atual) => deslocar(atual, visao, 1)),
    refetch: carregar,
    criarBloqueio,
    atualizarBloqueio,
    cancelarBloqueio,
  }
}
