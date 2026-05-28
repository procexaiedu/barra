"use client"

import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { useRouter } from "next/navigation"
import { api } from "@/lib/api"
import { subscribeTabelas } from "@/lib/realtime"
import { supabase } from "@/lib/supabase"
import type {
  Cliente,
  ClienteConversaResumo,
  ClienteDetalheResponse,
  ClienteListaItem,
  ClientesAgregadosResponse,
  ConversaDetalheResponse,
  CriarClienteRequest,
  EditarClienteRequest,
  FiltrosClientes,
  ModeloResumo,
} from "@/tipos/clientes"

type Status = "loading" | "success" | "error"

const filtrosIniciais: FiltrosClientes = {
  busca: "",
  periodo: "todos",
  dataInicio: null,
  dataFim: null,
  modeloId: "todas",
  perfis: [],
}

function buildListaPath(filtros: FiltrosClientes, cursor?: string | null) {
  const params = new URLSearchParams({ limit: "50" })
  const busca = filtros.busca.trim()
  if (busca) params.set("q", busca)
  // A Lista não tem UI de período custom (só o Mapa, Task 9); por isso só
  // serializa presets aqui. `periodo === "custom"` sem datas é NO-OP.
  if (filtros.periodo !== "todos" && filtros.periodo !== "custom") {
    params.set("periodo", filtros.periodo)
  }
  if (filtros.modeloId !== "todas") params.set("modelo_id", filtros.modeloId)
  for (const perfil of filtros.perfis) params.append("perfis", perfil)
  if (cursor) params.set("cursor", cursor)
  return `/v1/crm/clientes?${params.toString()}`
}

interface ModelosResponse {
  id: string
  nome: string
}

export function useClientes(opts: { selectedIdInicial?: string | null } = {}) {
  const [filtros, setFiltros] = useState<FiltrosClientes>(filtrosIniciais)
  const [incluirArquivados, setIncluirArquivados] = useState(false)
  const [debouncedBusca, setDebouncedBusca] = useState("")
  const [items, setItems] = useState<ClienteListaItem[]>([])
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  // Conversas (pares cliente,modelo) do cliente selecionado — alimentam o seletor de modelo.
  const [conversas, setConversas] = useState<ClienteConversaResumo[]>([])
  const [conversaAtivaId, setConversaAtivaId] = useState<string | null>(null)
  const [detalhe, setDetalhe] = useState<ConversaDetalheResponse | null>(null)
  // Cliente selecionado sem nenhuma conversa (recém-criado) → placeholder "sem histórico".
  const [clienteSemHistorico, setClienteSemHistorico] = useState<
    ClienteDetalheResponse["cliente"] | null
  >(null)
  const [listaStatus, setListaStatus] = useState<Status>("loading")
  const [detalheStatus, setDetalheStatus] = useState<Status>("loading")
  const [listaError, setListaError] = useState<string | null>(null)
  const [detalheError, setDetalheError] = useState<string | null>(null)
  const [modelos, setModelos] = useState<ModeloResumo[]>([])
  const router = useRouter()
  const itemsRef = useRef<ClienteListaItem[]>([])
  const nextCursorRef = useRef<string | null>(null)
  const selectedIdRef = useRef<string | null>(null)
  // Deep-link via ?cliente=<id> (ex.: link da MAPA-5 vindo do InfoWindow do mapa).
  // Consumido só no primeiro mount; cliques posteriores caem no fluxo normal.
  const initialIdRef = useRef<string | null>(opts.selectedIdInicial ?? null)
  const firstListaDone = useRef(false)
  const firstDetalheDone = useRef(false)
  const refetchTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const buscaTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const realtimeEvents = useRef(0)

  const filtrosEfetivos = useMemo<FiltrosClientes>(
    () => ({
      busca: debouncedBusca,
      periodo: filtros.periodo,
      dataInicio: filtros.dataInicio,
      dataFim: filtros.dataFim,
      modeloId: filtros.modeloId,
      perfis: filtros.perfis,
    }),
    [
      debouncedBusca,
      filtros.periodo,
      filtros.dataInicio,
      filtros.dataFim,
      filtros.modeloId,
      filtros.perfis,
    ]
  )

  const filtrosAplicados =
    filtrosEfetivos.busca.trim() !== "" ||
    filtrosEfetivos.periodo !== "todos" ||
    filtrosEfetivos.modeloId !== "todas" ||
    filtrosEfetivos.perfis.length > 0

  // Carrega o detalhe rico de uma conversa específica (par cliente,modelo).
  const carregarConversa = useCallback(async (conversaId: string) => {
    if (!firstDetalheDone.current) setDetalheStatus("loading")
    try {
      const res = await api<ConversaDetalheResponse>(`/v1/crm/conversas/${conversaId}`)
      setDetalhe(res)
      setConversaAtivaId(conversaId)
      setClienteSemHistorico(null)
      setDetalheStatus("success")
      setDetalheError(null)
      firstDetalheDone.current = true
    } catch (e) {
      if (!firstDetalheDone.current) setDetalheStatus("error")
      setDetalheError(e instanceof Error ? e.message : "Erro desconhecido")
    }
  }, [])

  // Carrega o cliente: resolve a lista de conversas e abre a mais recente.
  const loadDetalhe = useCallback(
    async (clienteId: string) => {
      if (!firstDetalheDone.current) setDetalheStatus("loading")
      try {
        const res = await api<ClienteDetalheResponse>(`/v1/crm/clientes/${clienteId}`)
        setConversas(res.conversas)
        if (res.conversas.length === 0) {
          // Cliente novo sem atendimento → placeholder "sem histórico".
          setDetalhe(null)
          setConversaAtivaId(null)
          setClienteSemHistorico(res.cliente)
          setDetalheStatus("success")
          setDetalheError(null)
          firstDetalheDone.current = true
          return
        }
        await carregarConversa(res.conversas[0].id)
      } catch (e) {
        if (!firstDetalheDone.current) setDetalheStatus("error")
        setDetalheError(e instanceof Error ? e.message : "Erro desconhecido")
      }
    },
    [carregarConversa]
  )

  const selecionarCliente = useCallback(
    (id: string) => {
      selectedIdRef.current = id
      setSelectedId(id)
      firstDetalheDone.current = false
      setDetalhe(null)
      setConversas([])
      setConversaAtivaId(null)
      setClienteSemHistorico(null)
      loadDetalhe(id)
    },
    [loadDetalhe]
  )

  const limparSelecao = useCallback(() => {
    selectedIdRef.current = null
    setSelectedId(null)
    setDetalhe(null)
    setConversas([])
    setConversaAtivaId(null)
    setClienteSemHistorico(null)
    setDetalheStatus("success")
    firstDetalheDone.current = true
  }, [])

  const loadLista = useCallback(
    async (mode: "replace" | "append" = "replace", manterSelecao = false) => {
      if (mode === "replace" && !manterSelecao) {
        limparSelecao()
        setDetalheStatus("loading")
      }
      if (!firstListaDone.current && mode === "replace") setListaStatus("loading")
      try {
        const cursor = mode === "append" ? nextCursorRef.current : null
        const res = await api<ClientesAgregadosResponse>(
          buildListaPath(filtrosEfetivos, cursor)
        )
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
          selecionarCliente(proximoId)
        } else {
          limparSelecao()
        }
      } catch (e) {
        if (!firstListaDone.current) setListaStatus("error")
        setListaError(e instanceof Error ? e.message : "Erro desconhecido")
      }
    },
    [filtrosEfetivos, loadDetalhe, selecionarCliente, limparSelecao]
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
    const idInicial = initialIdRef.current
    initialIdRef.current = null
    const timer = setTimeout(() => {
      if (idInicial) {
        // Pré-seleciona o id do deep-link e evita o flicker do primeiro item da lista
        // sendo selecionado antes do correto.
        selectedIdRef.current = idInicial
        setSelectedId(idInicial)
        loadDetalhe(idInicial)
        loadLista("replace", true)
      } else {
        loadLista("replace", false)
      }
    }, 0)
    return () => clearTimeout(timer)
  }, [filtrosEfetivos, incluirArquivados, loadLista, loadDetalhe])

  useEffect(() => {
    api<ModelosResponse[]>("/v1/modelos")
      .then((rows) => setModelos(rows.map((r) => ({ id: r.id, nome: r.nome }))))
      .catch(() => setModelos([]))
  }, [])

  const criarCliente = useCallback(
    async (payload: CriarClienteRequest): Promise<Cliente> => {
      const res = await api<Cliente>("/v1/crm/clientes", {
        method: "POST",
        body: JSON.stringify(payload),
      })
      await loadLista("replace", true)
      return res
    },
    [loadLista]
  )

  const editarCliente = useCallback(
    async (clienteId: string, payload: EditarClienteRequest): Promise<Cliente> => {
      const res = await api<Cliente>(`/v1/crm/clientes/${clienteId}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      })
      await loadLista("replace", true)
      return res
    },
    [loadLista]
  )

  const arquivarCliente = useCallback(
    async (clienteId: string): Promise<void> => {
      await api(`/v1/crm/clientes/${clienteId}/arquivar`, { method: "POST" })
      await loadLista("replace", true)
    },
    [loadLista]
  )

  const desarquivarCliente = useCallback(
    async (clienteId: string): Promise<void> => {
      await api(`/v1/crm/clientes/${clienteId}/desarquivar`, { method: "POST" })
      await loadLista("replace", true)
    },
    [loadLista]
  )

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

  const clienteArquivado = useMemo(() => {
    const atual = items.find((item) => item.id === selectedId)
    return atual ? atual.arquivado_em !== null : false
  }, [items, selectedId])

  return {
    filtros,
    setFiltros,
    filtrosAplicados,
    incluirArquivados,
    setIncluirArquivados,
    items,
    nextCursor,
    selectedId,
    conversas,
    conversaAtivaId,
    detalhe,
    clienteSemHistorico,
    clienteArquivado,
    listaStatus,
    detalheStatus,
    listaError,
    detalheError,
    modelos,
    refetch,
    carregarMais,
    selecionarCliente,
    selecionarConversa: carregarConversa,
    criarCliente,
    editarCliente,
    arquivarCliente,
    desarquivarCliente,
  }
}
