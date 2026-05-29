"use client"

import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import { api } from "@/lib/api"
import { subscribeTabelas } from "@/lib/realtime"
import { supabase } from "@/lib/supabase"
import type {
  AbaModelo,
  AtivarModeloResponse,
  ConectarWhatsappResponse,
  CriarModeloInput,
  FiltrosModelos,
  MidiaInput,
  MidiaItem,
  ModeloDetalheResponse,
  ModeloListaItem,
  ModelosListaResponse,
  PatchModeloInput,
  PausarModeloResponse,
  UploadUrlResponse,
  WhatsappStatusResponse,
} from "@/tipos/modelos"

type Status = "loading" | "success" | "error"

const abasValidas: AbaModelo[] = ["perfil", "disponibilidade", "midia"]

const filtrosIniciais: FiltrosModelos = {
  busca: "",
  status: "todos",
  evolution: "todos",
  tipo: "todos",
  nivel: "todos",
}

function abaFromQuery(value: string | null): AbaModelo {
  return abasValidas.includes(value as AbaModelo) ? (value as AbaModelo) : "perfil"
}

function buildListaPath(filtros: FiltrosModelos, cursor?: string | null) {
  const params = new URLSearchParams({ limit: "50" })
  const busca = filtros.busca.trim()
  if (busca) params.set("q", busca)
  if (filtros.status !== "todos") params.set("status", filtros.status)
  if (filtros.evolution !== "todos") params.set("evolution", filtros.evolution)
  if (filtros.tipo !== "todos") params.set("tipo", filtros.tipo)
  if (filtros.nivel !== "todos") params.set("nivel", filtros.nivel)
  if (cursor) params.set("cursor", cursor)
  return `/v1/modelos?${params.toString()}`
}

function toArray(value: unknown): string[] {
  if (Array.isArray(value)) return value.map(String)
  if (typeof value !== "string") return []
  const trimmed = value.trim()
  if (!trimmed) return []
  if (trimmed.startsWith("{") && trimmed.endsWith("}")) {
    return trimmed.slice(1, -1).split(",").map((item) => item.trim().replace(/^"|"$/g, "")).filter(Boolean)
  }
  return trimmed.split(",").map((item) => item.trim()).filter(Boolean)
}

function normalizarDetalhe(res: ModeloDetalheResponse): ModeloDetalheResponse {
  return {
    ...res,
    modelo: {
      ...res.modelo,
      idiomas: toArray(res.modelo.idiomas),
      tipo_atendimento_aceito: toArray(res.modelo.tipo_atendimento_aceito) as ModeloDetalheResponse["modelo"]["tipo_atendimento_aceito"],
      valor_padrao: Number(res.modelo.valor_padrao),
      percentual_repasse: res.modelo.percentual_repasse === null ? null : Number(res.modelo.percentual_repasse),
    },
    programas: (res.programas ?? []).map((p) => ({ ...p, preco: Number(p.preco) })),
    fetiches: (res.fetiches ?? []).map((f) => ({
      ...f,
      preco: f.preco === null ? null : Number(f.preco),
    })),
  }
}

export function useModelos() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const [filtros, setFiltros] = useState<FiltrosModelos>(filtrosIniciais)
  const [debouncedBusca, setDebouncedBusca] = useState("")
  const [items, setItems] = useState<ModeloListaItem[]>([])
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(searchParams.get("modelo"))
  const [aba, setAbaState] = useState<AbaModelo>(() => abaFromQuery(searchParams.get("aba")))
  const [detalhe, setDetalhe] = useState<ModeloDetalheResponse | null>(null)
  const [listaStatus, setListaStatus] = useState<Status>("loading")
  const [detalheStatus, setDetalheStatus] = useState<Status>("loading")
  const [listaError, setListaError] = useState<string | null>(null)
  const [detalheError, setDetalheError] = useState<string | null>(null)
  const [dirty, setDirty] = useState(false)
  const filtrosEfetivos = useMemo<FiltrosModelos>(
    () => ({
      busca: debouncedBusca,
      status: filtros.status,
      evolution: filtros.evolution,
      tipo: filtros.tipo,
      nivel: filtros.nivel,
    }),
    [debouncedBusca, filtros.status, filtros.evolution, filtros.tipo, filtros.nivel]
  )
  const itemsRef = useRef<ModeloListaItem[]>([])
  const selectedIdRef = useRef<string | null>(selectedId)
  const detalheRef = useRef<ModeloDetalheResponse | null>(null)
  const nextCursorRef = useRef<string | null>(null)
  const firstListaDone = useRef(false)
  const firstDetalheDone = useRef(false)
  const refetchTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const buscaTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const realtimeEvents = useRef(0)

  const filtrosAplicados =
    filtrosEfetivos.busca.trim() !== "" ||
    filtrosEfetivos.status !== "todos" ||
    filtrosEfetivos.evolution !== "todos" ||
    filtrosEfetivos.tipo !== "todos" ||
    filtrosEfetivos.nivel !== "todos"

  const replaceUrl = useCallback(
    (modeloId: string | null, proximaAba: AbaModelo = aba) => {
      const params = new URLSearchParams()
      if (modeloId) params.set("modelo", modeloId)
      params.set("aba", proximaAba)
      router.replace(`/modelos?${params.toString()}`, { scroll: false })
    },
    [aba, router]
  )

  const loadDetalhe = useCallback(async (id: string, showLoading = true) => {
    if (showLoading && !firstDetalheDone.current) {
      setDetalheStatus("loading")
    }
    try {
      const detalheRes = await api<ModeloDetalheResponse>(`/v1/modelos/${id}`)
      const detalheNormalizado = normalizarDetalhe(detalheRes)
      detalheRef.current = detalheNormalizado
      setDetalhe(detalheNormalizado)
      setDetalheStatus("success")
      setDetalheError(null)
      firstDetalheDone.current = true
    } catch (e) {
      if (!firstDetalheDone.current) {
        setDetalheStatus("error")
      }
      const message = e instanceof Error ? e.message : "Erro desconhecido"
      setDetalheError(message)
    }
  }, [])

  const selecionarModelo = useCallback(
    (id: string, proximaAba: AbaModelo = aba) => {
      selectedIdRef.current = id
      setSelectedId(id)
      setAbaState(proximaAba)
      firstDetalheDone.current = false
      detalheRef.current = null
      setDetalhe(null)
      setDirty(false)
      replaceUrl(id, proximaAba)
      loadDetalhe(id)
    },
    [aba, loadDetalhe, replaceUrl]
  )

  const loadLista = useCallback(
    async (mode: "replace" | "append" = "replace", manterSelecao = false) => {
      if (!firstListaDone.current && mode === "replace") setListaStatus("loading")
      try {
        const cursor = mode === "append" ? nextCursorRef.current : null
        const res = await api<ModelosListaResponse>(buildListaPath(filtrosEfetivos, cursor))
        const novosItems = mode === "append" ? [...itemsRef.current, ...res.items] : res.items
        itemsRef.current = novosItems
        setItems(novosItems)
        setNextCursor(res.next_cursor)
        nextCursorRef.current = res.next_cursor
        setListaStatus("success")
        setListaError(null)
        firstListaDone.current = true

        const atual = selectedIdRef.current
        const idQuery = searchParams.get("modelo")
        const candidatoQuery = idQuery && novosItems.some((item) => item.id === idQuery) ? idQuery : null
        const aindaPresente = atual && novosItems.some((item) => item.id === atual)
        const proximoId =
          manterSelecao && aindaPresente
            ? atual
            : candidatoQuery ?? novosItems.find((item) => item.status === "ativa")?.id ?? novosItems[0]?.id ?? null

        if (proximoId) {
          if (proximoId !== atual || !detalheRef.current) selecionarModelo(proximoId, aba)
          else loadDetalhe(proximoId, false)
        } else {
          selectedIdRef.current = null
          setSelectedId(null)
          setDetalhe(null)
          setDetalheStatus("success")
          replaceUrl(null, aba)
        }
      } catch (e) {
        if (!firstListaDone.current) setListaStatus("error")
        setListaError(e instanceof Error ? e.message : "Erro desconhecido")
      }
    },
    [aba, filtrosEfetivos, loadDetalhe, replaceUrl, searchParams, selecionarModelo]
  )

  const refetch = useCallback(() => {
    loadLista("replace", true)
  }, [loadLista])

  const carregarMais = useCallback(() => {
    if (nextCursor) loadLista("append", true)
  }, [loadLista, nextCursor])

  const setAba = useCallback(
    (proximaAba: AbaModelo) => {
      setAbaState(proximaAba)
      replaceUrl(selectedIdRef.current, proximaAba)
    },
    [replaceUrl]
  )

  const patchModelo = useCallback(
    async (input: PatchModeloInput) => {
      const id = selectedIdRef.current
      if (!id) return null
      const res = await api(`/v1/modelos/${id}`, { method: "PATCH", body: JSON.stringify(input) })
      await loadDetalhe(id, false)
      return res
    },
    [loadDetalhe]
  )

  const criarModelo = useCallback(
    async (input: CriarModeloInput) => {
      const modelo = await api<{ id: string }>(`/v1/modelos`, { method: "POST", body: JSON.stringify(input) })
      firstListaDone.current = false
      await loadLista("replace", false)
      selecionarModelo(modelo.id, "perfil")
      return modelo
    },
    [loadLista, selecionarModelo]
  )

  const conectarWhatsapp = useCallback(async (confirmarRotacao = false) => {
    const id = selectedIdRef.current
    if (!id) return null
    return api<ConectarWhatsappResponse>(`/v1/modelos/${id}/conectar-whatsapp`, {
      method: "POST",
      body: JSON.stringify({ confirmar_rotacao: confirmarRotacao }),
    })
  }, [])

  const desparearWhatsapp = useCallback(async () => {
    const id = selectedIdRef.current
    if (!id) return
    await api(`/v1/modelos/${id}/desparear-whatsapp`, { method: "POST", body: JSON.stringify({}) })
    await loadDetalhe(id, false)
  }, [loadDetalhe])

  const whatsappStatus = useCallback(async (modeloId: string) => {
    return api<WhatsappStatusResponse>(`/v1/modelos/${modeloId}/whatsapp/status`)
  }, [])

  const recarregarDetalhe = useCallback(async () => {
    const id = selectedIdRef.current
    if (!id) return
    await loadDetalhe(id, false)
  }, [loadDetalhe])

  const pausarModelo = useCallback(async () => {
    const id = selectedIdRef.current
    if (!id) return null
    const res = await api<PausarModeloResponse>(`/v1/modelos/${id}/pausar`, {
      method: "POST",
      body: JSON.stringify({}),
    })
    await loadDetalhe(id, false)
    return res
  }, [loadDetalhe])

  const ativarModelo = useCallback(async () => {
    const id = selectedIdRef.current
    if (!id) return null
    const res = await api<AtivarModeloResponse>(`/v1/modelos/${id}/ativar`, {
      method: "POST",
      body: JSON.stringify({}),
    })
    await loadDetalhe(id, false)
    return res
  }, [loadDetalhe])

  const vincularProgramaModelo = useCallback(
    async (programaId: string, duracaoId: string, preco: number) => {
      const id = selectedIdRef.current
      if (!id) return
      await api(`/v1/modelos/${id}/programas`, {
        method: "POST",
        body: JSON.stringify({ programa_id: programaId, duracao_id: duracaoId, preco }),
      })
      await loadDetalhe(id, false)
    },
    [loadDetalhe],
  )

  const atualizarPrecoProgramaModelo = useCallback(
    async (programaId: string, duracaoId: string, preco: number) => {
      const id = selectedIdRef.current
      if (!id) return
      await api(`/v1/modelos/${id}/programas/${programaId}/duracoes/${duracaoId}`, {
        method: "PATCH",
        body: JSON.stringify({ preco }),
      })
      await loadDetalhe(id, false)
    },
    [loadDetalhe],
  )

  const desvincularProgramaModelo = useCallback(
    async (programaId: string, duracaoId: string) => {
      const id = selectedIdRef.current
      if (!id) return
      await api(`/v1/modelos/${id}/programas/${programaId}/duracoes/${duracaoId}`, {
        method: "DELETE",
      })
      await loadDetalhe(id, false)
    },
    [loadDetalhe],
  )

  const vincularFeticheModelo = useCallback(
    async (feticheId: string, preco: number | null) => {
      const id = selectedIdRef.current
      if (!id) return
      await api(`/v1/modelos/${id}/fetiches`, {
        method: "POST",
        body: JSON.stringify({ fetiche_id: feticheId, preco }),
      })
      await loadDetalhe(id, false)
    },
    [loadDetalhe],
  )

  const atualizarPrecoFeticheModelo = useCallback(
    async (feticheId: string, preco: number | null) => {
      const id = selectedIdRef.current
      if (!id) return
      await api(`/v1/modelos/${id}/fetiches/${feticheId}`, {
        method: "PATCH",
        body: JSON.stringify({ preco }),
      })
      await loadDetalhe(id, false)
    },
    [loadDetalhe],
  )

  const desvincularFeticheModelo = useCallback(
    async (feticheId: string) => {
      const id = selectedIdRef.current
      if (!id) return
      await api(`/v1/modelos/${id}/fetiches/${feticheId}`, {
        method: "DELETE",
      })
      await loadDetalhe(id, false)
    },
    [loadDetalhe],
  )

  const listarMidia = useCallback(async (params: URLSearchParams) => {
    const id = selectedIdRef.current
    if (!id) return []
    return api<MidiaItem[]>(`/v1/modelos/${id}/midia?${params.toString()}`)
  }, [])

  const criarUploadUrl = useCallback(async (filename: string, contentType: string, perfil = false) => {
    const id = selectedIdRef.current
    if (!id) return null
    const path = perfil ? "foto-perfil/upload-url" : "midia/upload-url"
    return api<UploadUrlResponse>(`/v1/modelos/${id}/${path}`, {
      method: "POST",
      body: JSON.stringify({ filename, content_type: contentType }),
    })
  }, [])

  const criarMidia = useCallback(async (input: MidiaInput) => {
    const id = selectedIdRef.current
    if (!id) return
    await api(`/v1/modelos/${id}/midia`, { method: "POST", body: JSON.stringify(input) })
    await loadDetalhe(id, false)
  }, [loadDetalhe])

  const atualizarMidia = useCallback(async (midiaId: string, input: Partial<Pick<MidiaItem, "tipo" | "tag" | "aprovada">>) => {
    const id = selectedIdRef.current
    if (!id) return
    await api(`/v1/modelos/${id}/midia/${midiaId}`, { method: "PATCH", body: JSON.stringify(input) })
    await loadDetalhe(id, false)
  }, [loadDetalhe])

  const deletarMidia = useCallback(async (midiaId: string) => {
    const id = selectedIdRef.current
    if (!id) return
    await api(`/v1/modelos/${id}/midia/${midiaId}`, { method: "DELETE" })
    await loadDetalhe(id, false)
  }, [loadDetalhe])

  const atualizarFotoPerfil = useCallback(async (objectKey: string | null) => {
    const id = selectedIdRef.current
    if (!id) return
    if (objectKey) {
      await api(`/v1/modelos/${id}/foto-perfil`, { method: "PATCH", body: JSON.stringify({ object_key: objectKey }) })
    } else {
      await api(`/v1/modelos/${id}/foto-perfil`, { method: "DELETE" })
    }
    await loadDetalhe(id, false)
  }, [loadDetalhe])

  const debouncedRealtimeRefetch = useCallback(() => {
    realtimeEvents.current += 1
    if (refetchTimer.current) clearTimeout(refetchTimer.current)
    refetchTimer.current = setTimeout(() => {
      if (process.env.NODE_ENV !== "production" && realtimeEvents.current > 1) {
        console.debug(`[modelos] refetch coalescido por ${realtimeEvents.current} eventos`)
      }
      realtimeEvents.current = 0
      loadLista("replace", true)
      // CONNECTION_UPDATE atualiza barravips.modelos no DB; sem refetch do
      // detalhe, o badge "WhatsApp pronto" no perfil dependeria do polling.
      const id = selectedIdRef.current
      if (id) loadDetalhe(id, false)
    }, 250)
  }, [loadLista, loadDetalhe])

  useEffect(() => {
    if (buscaTimer.current) clearTimeout(buscaTimer.current)
    buscaTimer.current = setTimeout(() => setDebouncedBusca(filtros.busca), 300)
    return () => {
      if (buscaTimer.current) clearTimeout(buscaTimer.current)
    }
  }, [filtros.busca])

  useEffect(() => {
    firstListaDone.current = false
    nextCursorRef.current = null
    itemsRef.current = []
    const timer = setTimeout(() => loadLista("replace", false), 0)
    return () => clearTimeout(timer)
  }, [filtrosEfetivos, loadLista])

  useEffect(() => {
    const cleanupRealtime = subscribeTabelas(
      "modelos",
      ["modelos", "modelo_midia", "programas", "modelo_programas"],
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
    aba,
    detalhe,
    listaStatus,
    detalheStatus,
    listaError,
    detalheError,
    dirty,
    setDirty,
    refetch,
    carregarMais,
    selecionarModelo,
    setAba,
    patchModelo,
    criarModelo,
    conectarWhatsapp,
    desparearWhatsapp,
    whatsappStatus,
    recarregarDetalhe,
    pausarModelo,
    ativarModelo,
    vincularProgramaModelo,
    atualizarPrecoProgramaModelo,
    desvincularProgramaModelo,
    vincularFeticheModelo,
    atualizarPrecoFeticheModelo,
    desvincularFeticheModelo,
    listarMidia,
    criarUploadUrl,
    criarMidia,
    atualizarMidia,
    deletarMidia,
    atualizarFotoPerfil,
  }
}
