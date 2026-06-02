"use client"

import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import { api } from "@/lib/api"
import { subscribeTabelas } from "@/lib/realtime"
import { supabase } from "@/lib/supabase"
import type {
  ComprovanteUrlResponse,
  FiltroStatusPix,
  FiltrosPix,
  MotivoRejeicao,
  PixDetalheResponse,
  PixListaItem,
  PixListaResponse,
} from "@/tipos/pix"

type Status = "loading" | "success" | "error"
type ComprovanteStatus = "idle" | "loading" | "success" | "error"

const filtrosIniciais: FiltrosPix = {
  busca: "",
  status: "pendentes",
  modelo_ids: [],
  motivo_em_revisao: "todos",
  periodo: "todos",
  atendimento_id: null,
}

function buildListaPath(filtros: FiltrosPix, cursor: string | null) {
  const params = new URLSearchParams({ limit: "50" })
  const busca = filtros.busca.trim()
  if (busca) params.set("q", busca.startsWith("#") ? busca.slice(1) : busca)
  if (filtros.status !== "pendentes") params.set("status", filtros.status)
  else params.set("status", "pendentes")
  for (const id of filtros.modelo_ids) params.append("modelo_id", id)
  if (filtros.motivo_em_revisao !== "todos") params.set("motivo_em_revisao", filtros.motivo_em_revisao)
  if (filtros.periodo !== "todos") params.set("periodo", filtros.periodo)
  if (filtros.atendimento_id) params.set("atendimento_id", filtros.atendimento_id)
  if (cursor) params.set("cursor", cursor)
  return `/v1/pix?${params.toString()}`
}

function statusFromQuery(value: string | null): FiltroStatusPix {
  switch (value) {
    case "em_revisao":
    case "pendentes":
      return "pendentes"
    case "validado_auto":
      return "validado_auto"
    case "validado_manual":
      return "validado_manual"
    case "rejeitado":
      return "rejeitado"
    case "todos":
      return "todos"
    default:
      return "pendentes"
  }
}

export function usePix() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const initialFiltros = useMemo<FiltrosPix>(() => {
    const atendimentoId = searchParams.get("atendimento")
    const statusQuery = searchParams.get("status")
    return {
      ...filtrosIniciais,
      atendimento_id: atendimentoId,
      status: atendimentoId ? "todos" : statusFromQuery(statusQuery),
    }
  }, [searchParams])

  const [filtros, setFiltros] = useState<FiltrosPix>(initialFiltros)
  const [debouncedBusca, setDebouncedBusca] = useState("")
  const [items, setItems] = useState<PixListaItem[]>([])
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [detalhe, setDetalhe] = useState<PixDetalheResponse | null>(null)
  const [listaStatus, setListaStatus] = useState<Status>("loading")
  const [detalheStatus, setDetalheStatus] = useState<Status>("loading")
  const [listaError, setListaError] = useState<string | null>(null)
  const [detalheError, setDetalheError] = useState<string | null>(null)
  const [comprovante, setComprovante] = useState<ComprovanteUrlResponse | null>(null)
  const [comprovanteStatus, setComprovanteStatus] = useState<ComprovanteStatus>("idle")
  const [carregandoMais, setCarregandoMais] = useState(false)

  const itemsRef = useRef<PixListaItem[]>([])
  const nextCursorRef = useRef<string | null>(null)
  const detalheRef = useRef<PixDetalheResponse | null>(null)
  const selectedIdRef = useRef<string | null>(null)
  const listaGenRef = useRef(0)
  const appendingRef = useRef(false)
  const firstListaDone = useRef(false)
  const firstDetalheDone = useRef(false)
  const refetchTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const buscaTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const realtimeEvents = useRef(0)

  const filtrosEfetivos = useMemo<FiltrosPix>(
    () => ({
      busca: debouncedBusca,
      status: filtros.status,
      modelo_ids: filtros.modelo_ids,
      motivo_em_revisao: filtros.motivo_em_revisao,
      periodo: filtros.periodo,
      atendimento_id: filtros.atendimento_id,
    }),
    [
      debouncedBusca,
      filtros.status,
      filtros.modelo_ids,
      filtros.motivo_em_revisao,
      filtros.periodo,
      filtros.atendimento_id,
    ]
  )

  const filtrosAplicados =
    filtrosEfetivos.busca.trim() !== "" ||
    filtrosEfetivos.status !== "pendentes" ||
    filtrosEfetivos.modelo_ids.length > 0 ||
    filtrosEfetivos.motivo_em_revisao !== "todos" ||
    filtrosEfetivos.periodo !== "todos" ||
    filtrosEfetivos.atendimento_id !== null

  const loadComprovante = useCallback(async (id: string) => {
    setComprovanteStatus("loading")
    try {
      const res = await api<ComprovanteUrlResponse>(`/v1/pix/${id}/comprovante-url`)
      if (selectedIdRef.current !== id) return // outro Pix foi selecionado nesse meio-tempo
      setComprovante(res)
      setComprovanteStatus("success")
    } catch {
      if (selectedIdRef.current !== id) return
      setComprovante(null)
      setComprovanteStatus("error")
    }
  }, [])

  const loadDetalhe = useCallback(
    async (id: string) => {
      if (!firstDetalheDone.current) setDetalheStatus("loading")
      try {
        const res = await api<PixDetalheResponse>(`/v1/pix/${id}`)
        if (selectedIdRef.current !== id) return // seleção mudou antes da resposta chegar
        detalheRef.current = res
        setDetalhe(res)
        setDetalheStatus("success")
        setDetalheError(null)
        firstDetalheDone.current = true
        if (res.pix.comprovante_disponivel) {
          loadComprovante(id)
        } else {
          setComprovante(null)
          setComprovanteStatus("idle")
        }
      } catch (e) {
        if (selectedIdRef.current !== id) return
        if (!firstDetalheDone.current) setDetalheStatus("error")
        setDetalheError(e instanceof Error ? e.message : "Erro desconhecido")
      }
    },
    [loadComprovante]
  )

  const selectPix = useCallback(
    (id: string) => {
      selectedIdRef.current = id
      setSelectedId(id)
      firstDetalheDone.current = false
      detalheRef.current = null
      setDetalhe(null)
      setComprovante(null)
      setComprovanteStatus("idle")
      loadDetalhe(id)
    },
    [loadDetalhe]
  )

  const loadLista = useCallback(
    async (
      mode: "replace" | "append" = "replace",
      manterSelecao = false,
      atualizarDetalhe = false
    ) => {
      if (mode === "append") {
        // Ignora cliques repetidos em "Carregar mais": um append já em voo (ou sem
        // próxima página) duplicaria itens com o mesmo cursor.
        if (appendingRef.current || !nextCursorRef.current) return
        appendingRef.current = true
        setCarregandoMais(true)
      }
      const gen = ++listaGenRef.current
      if (mode === "replace" && !manterSelecao) {
        selectedIdRef.current = null
        detalheRef.current = null
        setSelectedId(null)
        setDetalhe(null)
        setDetalheStatus("loading")
        setComprovante(null)
        setComprovanteStatus("idle")
      }
      if (!firstListaDone.current && mode === "replace") setListaStatus("loading")
      try {
        const cursor = mode === "append" ? nextCursorRef.current : null
        const res = await api<PixListaResponse>(buildListaPath(filtrosEfetivos, cursor))
        if (gen !== listaGenRef.current) return // resposta de uma carga mais antiga; descarta
        const novosItems = mode === "append" ? [...itemsRef.current, ...res.items] : res.items
        itemsRef.current = novosItems
        nextCursorRef.current = res.next_cursor
        setItems(novosItems)
        setNextCursor(res.next_cursor)
        setListaStatus("success")
        setListaError(null)
        firstListaDone.current = true

        const atual = selectedIdRef.current
        const deveManter = manterSelecao && atual && novosItems.some((item) => item.id === atual)
        const proximoId = deveManter ? atual : novosItems[0]?.id ?? null
        if (proximoId) {
          if (proximoId !== atual || !detalheRef.current || atualizarDetalhe) selectPix(proximoId)
        } else {
          selectedIdRef.current = null
          setSelectedId(null)
          detalheRef.current = null
          setDetalhe(null)
          setDetalheStatus("success")
          setComprovante(null)
          setComprovanteStatus("idle")
        }
      } catch (e) {
        if (gen !== listaGenRef.current) return
        if (!firstListaDone.current) setListaStatus("error")
        setListaError(e instanceof Error ? e.message : "Erro desconhecido")
      } finally {
        if (mode === "append") {
          appendingRef.current = false
          setCarregandoMais(false)
        }
      }
    },
    [filtrosEfetivos, selectPix]
  )

  const refetch = useCallback(() => {
    loadLista("replace", true, true)
  }, [loadLista])

  const carregarMais = useCallback(() => {
    loadLista("append", true)
  }, [loadLista])

  const aprovar = useCallback(
    async (id: string) => {
      await api(`/v1/pix/${id}/aprovar`, { method: "POST", body: JSON.stringify({}) })
      await loadLista("replace", true, true)
    },
    [loadLista]
  )

  const rejeitar = useCallback(
    async (id: string, motivo: MotivoRejeicao, observacao: string | null) => {
      await api(`/v1/pix/${id}/rejeitar`, {
        method: "POST",
        body: JSON.stringify({ motivo, observacao }),
      })
      await loadLista("replace", true, true)
    },
    [loadLista]
  )

  const reabrir = useCallback(
    async (id: string) => {
      await api(`/v1/pix/${id}/reabrir`, { method: "POST", body: JSON.stringify({}) })
      await loadLista("replace", true, true)
    },
    [loadLista]
  )

  const debouncedRealtimeRefetch = useCallback(() => {
    realtimeEvents.current += 1
    if (refetchTimer.current) clearTimeout(refetchTimer.current)
    refetchTimer.current = setTimeout(() => {
      if (process.env.NODE_ENV !== "production" && realtimeEvents.current > 1) {
        console.debug(`[pix] refetch coalescido por ${realtimeEvents.current} eventos`)
      }
      realtimeEvents.current = 0
      loadLista("replace", true, true)
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
    // Stale-while-revalidate: mantém lista/seleção durante o refetch por mudança de
    // filtro (sem flick para skeleton). O skeleton só vale na 1ª carga.
    const timer = setTimeout(() => {
      loadLista("replace", true)
    }, 0)
    return () => clearTimeout(timer)
  }, [filtrosEfetivos, loadLista])

  useEffect(() => {
    const cleanupRealtime = subscribeTabelas(
      "pix",
      ["comprovantes_pix", "atendimentos"],
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
    comprovante,
    comprovanteStatus,
    carregandoMais,
    refetch,
    carregarMais,
    selectPix,
    recarregarComprovante: () => {
      if (selectedIdRef.current) loadComprovante(selectedIdRef.current)
    },
    aprovar,
    rejeitar,
    reabrir,
  }
}
