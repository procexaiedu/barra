"use client"

import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { useRouter } from "next/navigation"
import { api } from "@/lib/api"
import { subscribeTabelas } from "@/lib/realtime"
import { supabase } from "@/lib/supabase"
import type {
  ConversaDetalheResponse,
  ConversaListaItem,
  ConversasListaResponse,
  FiltrosClientes,
  ModeloResumo,
} from "@/tipos/clientes"

type Status = "loading" | "success" | "error"

const filtrosIniciais: FiltrosClientes = {
  busca: "",
  recorrencia: "todas",
  motivoPerda: "todos",
  periodo: "todos",
  modeloId: "todas",
}

function buildListaPath(filtros: FiltrosClientes, cursor?: string | null) {
  const params = new URLSearchParams({ limit: "50" })
  const busca = filtros.busca.trim()
  if (busca) params.set("q", busca)
  if (filtros.recorrencia === "novas") params.set("recorrente", "false")
  if (filtros.recorrencia === "recorrentes") params.set("recorrente", "true")
  if (filtros.motivoPerda !== "todos") params.set("motivo_perda", filtros.motivoPerda)
  if (filtros.periodo !== "todos") params.set("periodo", filtros.periodo)
  if (filtros.modeloId !== "todas") params.set("modelo_id", filtros.modeloId)
  if (cursor) params.set("cursor", cursor)
  return `/v1/crm/conversas?${params.toString()}`
}

function normalizar(valor: string | null | undefined): string {
  return (valor ?? "").trim()
}

interface ModelosResponse {
  id: string
  nome: string
}

export function useClientes() {
  const [filtros, setFiltros] = useState<FiltrosClientes>(filtrosIniciais)
  const [debouncedBusca, setDebouncedBusca] = useState("")
  const [items, setItems] = useState<ConversaListaItem[]>([])
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [detalhe, setDetalhe] = useState<ConversaDetalheResponse | null>(null)
  const [listaStatus, setListaStatus] = useState<Status>("loading")
  const [detalheStatus, setDetalheStatus] = useState<Status>("loading")
  const [listaError, setListaError] = useState<string | null>(null)
  const [detalheError, setDetalheError] = useState<string | null>(null)
  const [modelos, setModelos] = useState<ModeloResumo[]>([])
  const router = useRouter()
  const itemsRef = useRef<ConversaListaItem[]>([])
  const nextCursorRef = useRef<string | null>(null)
  const detalheRef = useRef<ConversaDetalheResponse | null>(null)
  const selectedIdRef = useRef<string | null>(null)
  const firstListaDone = useRef(false)
  const firstDetalheDone = useRef(false)
  const refetchTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const buscaTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const realtimeEvents = useRef(0)

  const filtrosEfetivos = useMemo(
    () => ({ ...filtros, busca: debouncedBusca }),
    [filtros, debouncedBusca]
  )

  const filtrosAplicados =
    filtrosEfetivos.busca.trim() !== "" ||
    filtrosEfetivos.recorrencia !== "todas" ||
    filtrosEfetivos.motivoPerda !== "todos" ||
    filtrosEfetivos.periodo !== "todos" ||
    filtrosEfetivos.modeloId !== "todas"

  const aplicarDetalhe = useCallback(
    (res: ConversaDetalheResponse) => {
      detalheRef.current = res
      setDetalhe(res)
    },
    []
  )

  const loadDetalhe = useCallback(
    async (id: string) => {
      if (!firstDetalheDone.current) setDetalheStatus("loading")
      try {
        const res = await api<ConversaDetalheResponse>(`/v1/crm/conversas/${id}`)
        aplicarDetalhe(res)
        setDetalheStatus("success")
        setDetalheError(null)
        firstDetalheDone.current = true
      } catch (e) {
        if (!firstDetalheDone.current) setDetalheStatus("error")
        setDetalheError(e instanceof Error ? e.message : "Erro desconhecido")
      }
    },
    [aplicarDetalhe]
  )

  const selecionarConversa = useCallback(
    (id: string) => {
      selectedIdRef.current = id
      setSelectedId(id)
      firstDetalheDone.current = false
      detalheRef.current = null
      setDetalhe(null)
      loadDetalhe(id)
    },
    [loadDetalhe]
  )

  const loadLista = useCallback(
    async (mode: "replace" | "append" = "replace", manterSelecao = false) => {
      if (mode === "replace" && !manterSelecao) {
        selectedIdRef.current = null
        detalheRef.current = null
        setSelectedId(null)
        setDetalhe(null)
        setDetalheStatus("loading")
      }
      if (!firstListaDone.current && mode === "replace") setListaStatus("loading")
      try {
        const cursor = mode === "append" ? nextCursorRef.current : null
        const res = await api<ConversasListaResponse>(buildListaPath(filtrosEfetivos, cursor))
        const novosItems = mode === "append" ? [...itemsRef.current, ...res.items] : res.items
        itemsRef.current = novosItems
        nextCursorRef.current = res.next_cursor
        setItems(novosItems)
        setNextCursor(res.next_cursor)
        setListaStatus("success")
        setListaError(null)
        firstListaDone.current = true

        const atual = selectedIdRef.current
        const aindaPresente = atual && novosItems.some((item) => item.id === atual)

        if (manterSelecao && atual && aindaPresente) {
          await loadDetalhe(atual)
          return
        }
        const proximoId = novosItems[0]?.id ?? null
        if (proximoId) {
          selecionarConversa(proximoId)
        } else {
          selectedIdRef.current = null
          setSelectedId(null)
          detalheRef.current = null
          setDetalhe(null)
          setDetalheStatus("success")
          firstDetalheDone.current = true
        }
      } catch (e) {
        if (!firstListaDone.current) setListaStatus("error")
        setListaError(e instanceof Error ? e.message : "Erro desconhecido")
      }
    },
    [filtrosEfetivos, loadDetalhe, selecionarConversa]
  )

  const refetch = useCallback(() => {
    loadLista("replace", true)
  }, [loadLista])

  const carregarMais = useCallback(() => {
    if (nextCursor) loadLista("append", true)
  }, [loadLista, nextCursor])

  const debouncedRealtimeRefetch = useCallback(() => {
    realtimeEvents.current += 1
    if (refetchTimer.current) clearTimeout(refetchTimer.current)
    refetchTimer.current = setTimeout(() => {
      if (process.env.NODE_ENV !== "production" && realtimeEvents.current > 1) {
        console.debug(`[clientes] refetch coalescido por ${realtimeEvents.current} eventos`)
      }
      realtimeEvents.current = 0
      loadLista("replace", true)
    }, 250)
  }, [loadLista])



  useEffect(() => {
    if (buscaTimer.current) clearTimeout(buscaTimer.current)
    buscaTimer.current = setTimeout(() => setDebouncedBusca(filtros.busca), 300)
    return () => {
      if (buscaTimer.current) clearTimeout(buscaTimer.current)
    }
  }, [filtros.busca])

  useEffect(() => {
    firstListaDone.current = false
    firstDetalheDone.current = false
    itemsRef.current = []
    nextCursorRef.current = null
    const timer = setTimeout(() => {
      loadLista("replace", false)
    }, 0)
    return () => clearTimeout(timer)
  }, [filtrosEfetivos, loadLista])

  useEffect(() => {
    api<ModelosResponse[]>("/v1/modelos")
      .then((rows) => setModelos(rows.map((r) => ({ id: r.id, nome: r.nome }))))
      .catch(() => setModelos([]))
  }, [])

  useEffect(() => {
    const cleanupRealtime = subscribeTabelas(
      "crm",
      ["conversas", "clientes", "atendimentos"],
      debouncedRealtimeRefetch
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
      if (refetchTimer.current) clearTimeout(refetchTimer.current)
    }
  }, [debouncedRealtimeRefetch, router])

  return {
    filtros,
    setFiltros,
    filtrosAplicados,
    items,
    nextCursor,
    selectedId,
    detalhe,
    listaStatus,
    detalheStatus,
    listaError,
    detalheError,
    modelos,
    refetch,
    carregarMais,
    selecionarConversa,
  }
}
