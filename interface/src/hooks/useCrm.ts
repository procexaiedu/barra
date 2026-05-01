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
  FiltrosCrm,
  ModeloResumo,
} from "@/tipos/crm"

type Status = "loading" | "success" | "error"

const filtrosIniciais: FiltrosCrm = {
  busca: "",
  recorrencia: "todas",
  motivoPerda: "todos",
  periodo: "todos",
  modeloId: "todas",
}

function buildListaPath(filtros: FiltrosCrm, cursor?: string | null) {
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

export function useCrm() {
  const [filtros, setFiltros] = useState<FiltrosCrm>(filtrosIniciais)
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
  const [nomeInput, setNomeInput] = useState("")
  const [observacoesInput, setObservacoesInput] = useState("")
  const router = useRouter()
  const itemsRef = useRef<ConversaListaItem[]>([])
  const nextCursorRef = useRef<string | null>(null)
  const detalheRef = useRef<ConversaDetalheResponse | null>(null)
  const selectedIdRef = useRef<string | null>(null)
  const nomeInputRef = useRef("")
  const observacoesInputRef = useRef("")
  const nomeDirtyRef = useRef(false)
  const observacoesDirtyRef = useRef(false)
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

  const nomeServer = detalhe?.cliente.nome ?? ""
  const observacoesServer = detalhe?.conversa.observacoes_internas ?? ""
  const nomeDirty = normalizar(nomeInput) !== normalizar(nomeServer)
  const observacoesDirty = normalizar(observacoesInput) !== normalizar(observacoesServer)

  useEffect(() => {
    nomeDirtyRef.current = nomeDirty
  }, [nomeDirty])
  useEffect(() => {
    observacoesDirtyRef.current = observacoesDirty
  }, [observacoesDirty])

  const aplicarDetalhe = useCallback(
    (res: ConversaDetalheResponse, sincronizarInputs: boolean) => {
      detalheRef.current = res
      setDetalhe(res)
      if (sincronizarInputs || !nomeDirtyRef.current) {
        const novo = res.cliente.nome ?? ""
        nomeInputRef.current = novo
        setNomeInput(novo)
      }
      if (sincronizarInputs || !observacoesDirtyRef.current) {
        const novo = res.conversa.observacoes_internas ?? ""
        observacoesInputRef.current = novo
        setObservacoesInput(novo)
      }
    },
    []
  )

  const loadDetalhe = useCallback(
    async (id: string, opts: { sincronizar: boolean } = { sincronizar: true }) => {
      if (!firstDetalheDone.current) setDetalheStatus("loading")
      try {
        const res = await api<ConversaDetalheResponse>(`/v1/crm/conversas/${id}`)
        aplicarDetalhe(res, opts.sincronizar)
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
      nomeInputRef.current = ""
      observacoesInputRef.current = ""
      setNomeInput("")
      setObservacoesInput("")
      firstDetalheDone.current = false
      detalheRef.current = null
      setDetalhe(null)
      loadDetalhe(id, { sincronizar: true })
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
        nomeInputRef.current = ""
        observacoesInputRef.current = ""
        setNomeInput("")
        setObservacoesInput("")
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
        const dirtyAtivo = nomeDirtyRef.current || observacoesDirtyRef.current

        if (manterSelecao && atual && aindaPresente) {
          await loadDetalhe(atual, { sincronizar: false })
          return
        }
        if (manterSelecao && atual && !aindaPresente && dirtyAtivo) {
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
          nomeInputRef.current = ""
          observacoesInputRef.current = ""
          setNomeInput("")
          setObservacoesInput("")
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
        console.debug(`[crm] refetch coalescido por ${realtimeEvents.current} eventos`)
      }
      realtimeEvents.current = 0
      loadLista("replace", true)
    }, 250)
  }, [loadLista])

  const alterarNome = useCallback((valor: string) => {
    nomeInputRef.current = valor
    setNomeInput(valor)
  }, [])

  const alterarObservacoes = useCallback((valor: string) => {
    observacoesInputRef.current = valor
    setObservacoesInput(valor)
  }, [])

  const descartarNome = useCallback(() => {
    const restaurado = detalheRef.current?.cliente.nome ?? ""
    nomeInputRef.current = restaurado
    setNomeInput(restaurado)
  }, [])

  const descartarObservacoes = useCallback(() => {
    const restaurado = detalheRef.current?.conversa.observacoes_internas ?? ""
    observacoesInputRef.current = restaurado
    setObservacoesInput(restaurado)
  }, [])

  const salvarNomeCliente = useCallback(async () => {
    const detalheAtual = detalheRef.current
    if (!detalheAtual) return
    const enviar = nomeInputRef.current.trim() || null
    await api<{ id: string; nome: string | null; telefone: string }>(
      `/v1/crm/clientes/${detalheAtual.cliente.id}`,
      {
        method: "PATCH",
        body: JSON.stringify({ nome: enviar }),
      }
    )
    if (detalheRef.current) {
      const proximo: ConversaDetalheResponse = {
        ...detalheRef.current,
        cliente: { ...detalheRef.current.cliente, nome: enviar },
      }
      detalheRef.current = proximo
      setDetalhe(proximo)
      const sincronizado = enviar ?? ""
      nomeInputRef.current = sincronizado
      setNomeInput(sincronizado)
    }
    const idAtual = selectedIdRef.current
    if (idAtual) await loadDetalhe(idAtual, { sincronizar: false })
  }, [loadDetalhe])

  const salvarObservacoes = useCallback(async () => {
    const id = selectedIdRef.current
    if (!id) return
    const enviar = observacoesInputRef.current.trim() || null
    await api<{ id: string; observacoes_internas: string | null }>(
      `/v1/crm/conversas/${id}`,
      {
        method: "PATCH",
        body: JSON.stringify({ observacoes_internas: enviar }),
      }
    )
    if (detalheRef.current) {
      const proximo: ConversaDetalheResponse = {
        ...detalheRef.current,
        conversa: { ...detalheRef.current.conversa, observacoes_internas: enviar },
      }
      detalheRef.current = proximo
      setDetalhe(proximo)
      const sincronizado = enviar ?? ""
      observacoesInputRef.current = sincronizado
      setObservacoesInput(sincronizado)
    }
    await loadDetalhe(id, { sincronizar: false })
  }, [loadDetalhe])

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
    nomeInput,
    observacoesInput,
    nomeDirty,
    observacoesDirty,
    refetch,
    carregarMais,
    selecionarConversa,
    alterarNome,
    alterarObservacoes,
    descartarNome,
    descartarObservacoes,
    salvarNomeCliente,
    salvarObservacoes,
  }
}
