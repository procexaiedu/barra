"use client"

import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { useRouter } from "next/navigation"
import { toast } from "sonner"
import { ApiError, api, apiFormData } from "@/lib/api"
import { subscribeTabelas } from "@/lib/realtime"
import { supabase } from "@/lib/supabase"
import type {
  AtendimentoCriadoResponse,
  AtendimentoDetalheResponse,
  AtendimentoListaItem,
  AtendimentosListaResponse,
  CriarAtendimentoRequest,
  CorrigirRegistroPayload,
  CriarAtendimentoResultado,
  EditarDadosPayload,
  EstadoAtendimento,
  EstadoKanbanDestino,
  FecharAtendimentoDados,
  FiltrosAtendimentos,
  MidiaInternaAtendimento,
  MotivoPerda,
  ResumoAtendimentos,
} from "@/tipos/atendimentos"

type Status = "loading" | "success" | "error"

function montarFiltrosIniciais(): FiltrosAtendimentos {
  return {
    busca: "",
    estado: "abertos",
    tipo: "todos",
    urgencia: "todas",
    ia: "todos",
    qualificacao: "todos",
    periodo: { periodo: "tudo", de: null, ate: null },
    modeloIds: [],
  }
}

function normalizarListaResponse(res: AtendimentosListaResponse): AtendimentosListaResponse {
  return {
    items: Array.isArray(res.items) ? res.items : [],
    next_cursor: res.next_cursor ?? null,
  }
}

function normalizarDetalheResponse(res: AtendimentoDetalheResponse): AtendimentoDetalheResponse {
  return {
    ...res,
    mensagens: Array.isArray(res.mensagens) ? res.mensagens : [],
    eventos: Array.isArray(res.eventos) ? res.eventos : [],
    comprovantes_pix: Array.isArray(res.comprovantes_pix) ? res.comprovantes_pix : [],
    servicos: Array.isArray(res.servicos) ? res.servicos : [],
    midias_internas: Array.isArray(res.midias_internas) ? res.midias_internas : [],
  }
}

export interface FiltrosUrlAtendimentos {
  motivoPerda?: string | null
  motivoEscalada?: string | null
}

function montarParamsAtendimentos(
  filtros: FiltrosAtendimentos,
  filtrosUrl: FiltrosUrlAtendimentos
): URLSearchParams {
  const params = new URLSearchParams()
  const busca = filtros.busca.trim()
  if (busca) params.set("q", busca.startsWith("#") ? busca.slice(1) : busca)
  if (filtros.estado !== "abertos") params.set("estado", filtros.estado)
  if (filtros.tipo !== "todos") params.set("tipo_atendimento", filtros.tipo)
  if (filtros.urgencia !== "todas") params.set("urgencia", filtros.urgencia)
  if (filtros.ia !== "todos") params.set("ia_pausada", filtros.ia === "pausada" ? "true" : "false")
  if (filtros.qualificacao !== "todos") params.set("qualificacao_completa", filtros.qualificacao === "completa" ? "true" : "false")
  if (filtrosUrl.motivoPerda && filtros.estado === "Perdido") {
    params.set("motivo_perda", filtrosUrl.motivoPerda)
  }
  if (filtrosUrl.motivoEscalada && filtros.ia === "pausada") {
    params.set("motivo_escalada", filtrosUrl.motivoEscalada)
  }
  if (filtros.periodo.de) params.set("data_inicio", filtros.periodo.de)
  if (filtros.periodo.ate) params.set("data_fim", filtros.periodo.ate)
  for (const id of filtros.modeloIds) params.append("modelo_id", id)
  return params
}

function buildListaPath(
  filtros: FiltrosAtendimentos,
  filtrosUrl: FiltrosUrlAtendimentos,
  cursor?: string | null
) {
  const params = montarParamsAtendimentos(filtros, filtrosUrl)
  params.set("limit", "50")
  if (cursor) params.set("cursor", cursor)
  return `/v1/atendimentos?${params.toString()}`
}

function buildResumoPath(
  filtros: FiltrosAtendimentos,
  filtrosUrl: FiltrosUrlAtendimentos
) {
  return `/v1/atendimentos/resumo?${montarParamsAtendimentos(filtros, filtrosUrl).toString()}`
}

export function useAtendimentos(
  initialId?: string | null,
  filtrosIniciaisOverride?: Partial<FiltrosAtendimentos>,
  filtrosUrl: FiltrosUrlAtendimentos = {}
) {
  const [filtros, setFiltros] = useState<FiltrosAtendimentos>(() => ({
    ...montarFiltrosIniciais(),
    ...filtrosIniciaisOverride,
  }))
  const [debouncedBusca, setDebouncedBusca] = useState("")
  const [items, setItems] = useState<AtendimentoListaItem[]>([])
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [resumo, setResumo] = useState<ResumoAtendimentos | null>(null)
  const [resumoStatus, setResumoStatus] = useState<Status>("loading")
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [detalhe, setDetalhe] = useState<AtendimentoDetalheResponse | null>(null)
  const [listaStatus, setListaStatus] = useState<Status>("loading")
  const [detalheStatus, setDetalheStatus] = useState<Status>("loading")
  const [listaError, setListaError] = useState<string | null>(null)
  const [detalheError, setDetalheError] = useState<string | null>(null)
  const [corrigirAlvoId, setCorrigirAlvoId] = useState<string | null>(null)
  const router = useRouter()
  const itemsRef = useRef<AtendimentoListaItem[]>([])
  const nextCursorRef = useRef<string | null>(null)
  const detalheRef = useRef<AtendimentoDetalheResponse | null>(null)
  const selectedIdRef = useRef<string | null>(null)
  const pendingInitialId = useRef<string | null>(initialId ?? null)
  const firstListaDone = useRef(false)
  const firstDetalheDone = useRef(false)
  const refetchTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const buscaTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const realtimeEvents = useRef(0)
  const filtrosUrlRef = useRef<FiltrosUrlAtendimentos>(filtrosUrl)

  const filtrosEfetivos = useMemo<FiltrosAtendimentos>(
    () => ({
      busca: debouncedBusca,
      estado: filtros.estado,
      tipo: filtros.tipo,
      urgencia: filtros.urgencia,
      ia: filtros.ia,
      qualificacao: filtros.qualificacao,
      periodo: filtros.periodo,
      modeloIds: filtros.modeloIds,
    }),
    [
      debouncedBusca,
      filtros.estado,
      filtros.tipo,
      filtros.urgencia,
      filtros.ia,
      filtros.qualificacao,
      filtros.periodo,
      filtros.modeloIds,
    ]
  )

  // "Todos" é o período default → não conta como filtro aplicado.
  const periodoAplicado = filtrosEfetivos.periodo.periodo !== "tudo"
  const filtrosAplicados = filtrosEfetivos.busca.trim() !== ""
    || filtrosEfetivos.estado !== "abertos"
    || filtrosEfetivos.tipo !== "todos"
    || filtrosEfetivos.urgencia !== "todas"
    || filtrosEfetivos.ia !== "todos"
    || filtrosEfetivos.qualificacao !== "todos"
    || filtrosEfetivos.modeloIds.length > 0
    || periodoAplicado

  const loadDetalhe = useCallback(async (id: string) => {
    if (!firstDetalheDone.current) setDetalheStatus("loading")
    try {
      const res = normalizarDetalheResponse(await api<AtendimentoDetalheResponse>(`/v1/atendimentos/${id}`))
      detalheRef.current = res
      setDetalhe(res)
      setDetalheStatus("success")
      setDetalheError(null)
      firstDetalheDone.current = true
    } catch (e) {
      if (!firstDetalheDone.current) setDetalheStatus("error")
      setDetalheError(e instanceof Error ? e.message : "Erro desconhecido")
    }
  }, [])

  const selectAtendimento = useCallback((id: string) => {
    selectedIdRef.current = id
    setSelectedId(id)
    firstDetalheDone.current = false
    detalheRef.current = null
    setDetalhe(null)
    loadDetalhe(id)
  }, [loadDetalhe])

  const loadLista = useCallback(async (
    mode: "replace" | "append" = "replace",
    manterSelecao = false,
    atualizarDetalhe = false
  ) => {
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
      const res = normalizarListaResponse(await api<AtendimentosListaResponse>(buildListaPath(filtrosEfetivos, filtrosUrlRef.current, cursor)))
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
      const pendingId = pendingInitialId.current
      const initialMatch = pendingId && novosItems.some((item) => item.id === pendingId) ? pendingId : null
      if (initialMatch) pendingInitialId.current = null
      const proximoId = deveManter ? atual : (initialMatch ?? novosItems[0]?.id ?? null)
      if (proximoId) {
        if (proximoId !== atual || !detalheRef.current || atualizarDetalhe) selectAtendimento(proximoId)
      } else {
        selectedIdRef.current = null
        setSelectedId(null)
        detalheRef.current = null
        setDetalhe(null)
        setDetalheStatus("success")
      }
    } catch (e) {
      if (!firstListaDone.current) setListaStatus("error")
      setListaError(e instanceof Error ? e.message : "Erro desconhecido")
    }
  }, [filtrosEfetivos, selectAtendimento])

  const loadResumo = useCallback(async () => {
    setResumoStatus("loading")
    try {
      const res = await api<ResumoAtendimentos>(buildResumoPath(filtrosEfetivos, filtrosUrlRef.current))
      setResumo(res)
      setResumoStatus("success")
    } catch {
      setResumo(null)
      setResumoStatus("error")
    }
  }, [filtrosEfetivos])

  const refetch = useCallback(() => {
    loadLista("replace", true, true)
  }, [loadLista])

  const carregarMais = useCallback(() => {
    if (nextCursor) loadLista("append", true)
  }, [loadLista, nextCursor])

  const devolver = useCallback(async (id: string) => {
    await api(`/v1/atendimentos/${id}/devolver`, {
      method: "POST",
      body: JSON.stringify({ observacao: null }),
    })
    await loadLista("replace", true)
  }, [loadLista])

  const abrirCorrigir = useCallback((id: string) => setCorrigirAlvoId(id), [])
  const fecharCorrigir = useCallback(() => setCorrigirAlvoId(null), [])

  const numeroDe = useCallback((id: string): number | null => {
    const naLista = itemsRef.current.find((item) => item.id === id)
    if (naLista) return naLista.numero_curto
    if (detalheRef.current?.atendimento.id === id) return detalheRef.current.atendimento.numero_curto
    return null
  }, [])

  const fechar = useCallback(async (id: string, dados: FecharAtendimentoDados) => {
    const numero = numeroDe(id)
    await api(`/v1/atendimentos/${id}/fechar`, {
      method: "POST",
      body: JSON.stringify({
        valor_final: dados.valorFinal,
        ...(dados.formaPagamento ? { forma_pagamento: dados.formaPagamento } : {}),
        ...(dados.isentarTaxa ? { isentar_taxa: true } : {}),
      }),
    })
    await loadLista("replace", false)
    toast.success(`Atendimento #${numero ?? "?"} fechado`, {
      action: { label: "Corrigir", onClick: () => abrirCorrigir(id) },
    })
  }, [loadLista, numeroDe, abrirCorrigir])

  const perder = useCallback(async (id: string, motivo: MotivoPerda, observacao: string | null) => {
    const numero = numeroDe(id)
    await api(`/v1/atendimentos/${id}/perder`, {
      method: "POST",
      body: JSON.stringify({ motivo, observacao }),
    })
    await loadLista("replace", false)
    toast.success(`Atendimento #${numero ?? "?"} marcado como perdido`, {
      action: { label: "Corrigir", onClick: () => abrirCorrigir(id) },
    })
  }, [loadLista, numeroDe, abrirCorrigir])

  // Correção de Registro de resultado (Fechado↔Perdido + valor/motivo). Reaproveita
  // o comando corrigir_registro do backend, que reconcilia bloqueio e Financeiro.
  const corrigirRegistro = useCallback(async (id: string, payload: CorrigirRegistroPayload) => {
    await api(`/v1/atendimentos/${id}/corrigir-registro`, {
      method: "POST",
      body: JSON.stringify(payload),
    })
    if (selectedIdRef.current === id) await loadDetalhe(id)
    await loadLista("replace", true, true)
    toast.success(
      payload.novo_resultado === "Fechado"
        ? "Resultado corrigido para fechado"
        : "Resultado corrigido para perdido"
    )
  }, [loadDetalhe, loadLista])

  const excluir = useCallback(async (id: string) => {
    const numero = numeroDe(id)
    await api(`/v1/atendimentos/${id}`, { method: "DELETE" })
    await loadLista("replace", false)
    await loadResumo()
    toast.success(`Atendimento #${numero ?? "?"} excluído`)
  }, [loadLista, loadResumo, numeroDe])

  const moverEstado = useCallback(async (id: string, estado: EstadoKanbanDestino) => {
    setItems((current) =>
      current.map((item) => item.id === id ? { ...item, estado: estado as EstadoAtendimento } : item)
    )
    try {
      await api(`/v1/atendimentos/${id}/estado`, {
        method: "PATCH",
        body: JSON.stringify({ estado }),
      })
    } catch (e) {
      await loadLista("replace", true)
      throw e
    }
  }, [loadLista])

  const editarDados = useCallback(async (id: string, dados: EditarDadosPayload) => {
    await api(`/v1/atendimentos/${id}/dados`, {
      method: "PATCH",
      body: JSON.stringify(dados),
    })
    if (selectedIdRef.current === id) await loadDetalhe(id)
    await loadLista("replace", true)
  }, [loadDetalhe, loadLista])

  const criarAtendimento = useCallback(
    async (payload: CriarAtendimentoRequest): Promise<CriarAtendimentoResultado> => {
      try {
        const res = await api<AtendimentoCriadoResponse>("/v1/atendimentos", {
          method: "POST",
          body: JSON.stringify(payload),
        })
        // Não recarrega aqui: o modal ainda vai gravar dados/serviços via PATCH/POST.
        // O refetch acontece em onCriado, depois que tudo foi salvo.
        return { tipo: "criado", atendimento: res }
      } catch (e) {
        if (e instanceof ApiError && e.status === 409) {
          if (e.detail === "atendimento_aberto_existente") {
            const atendimentoId = (e.details?.atendimento_id as string | undefined) ?? null
            if (atendimentoId) {
              return { tipo: "existente", atendimento_id: atendimentoId }
            }
          }
        }
        throw e
      }
    },
    []
  )

  const uploadMidia = useCallback(async (atendimentoId: string, file: File, tipo: string): Promise<void> => {
    const form = new FormData()
    form.append("arquivo", file)
    form.append("tipo", tipo)
    const nova = await apiFormData<MidiaInternaAtendimento>(`/v1/atendimentos/${atendimentoId}/midias`, form)
    setDetalhe((prev) => prev ? { ...prev, midias_internas: [...prev.midias_internas, nova] } : prev)
    if (detalheRef.current) {
      detalheRef.current = { ...detalheRef.current, midias_internas: [...detalheRef.current.midias_internas, nova] }
    }
  }, [])

  const deletarMidia = useCallback(async (atendimentoId: string, midiaId: string): Promise<void> => {
    await api(`/v1/atendimentos/${atendimentoId}/midias/${midiaId}`, { method: "DELETE" })
    setDetalhe((prev) => prev ? { ...prev, midias_internas: prev.midias_internas.filter((m) => m.id !== midiaId) } : prev)
    if (detalheRef.current) {
      detalheRef.current = { ...detalheRef.current, midias_internas: detalheRef.current.midias_internas.filter((m) => m.id !== midiaId) }
    }
  }, [])

  const debouncedRealtimeRefetch = useCallback(() => {
    realtimeEvents.current += 1
    if (refetchTimer.current) clearTimeout(refetchTimer.current)
    refetchTimer.current = setTimeout(() => {
      if (process.env.NODE_ENV !== "production" && realtimeEvents.current > 1) {
        console.debug(`[atendimentos] refetch coalescido por ${realtimeEvents.current} eventos`)
      }
      realtimeEvents.current = 0
      loadLista("replace", true, true)
      loadResumo()
    }, 250)
  }, [loadLista, loadResumo])

  useEffect(() => {
    filtrosUrlRef.current = filtrosUrl
  }, [filtrosUrl])

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
      loadResumo()
    }, 0)
    return () => clearTimeout(timer)
  }, [filtrosEfetivos, loadLista, loadResumo])

  useEffect(() => {
    const cleanupRealtime = subscribeTabelas(
      "atendimentos",
      ["atendimentos", "mensagens", "eventos", "comprovantes_pix"],
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
    resumo,
    resumoStatus,
    selectedId,
    detalhe,
    listaStatus,
    detalheStatus,
    listaError,
    detalheError,
    refetch,
    carregarMais,
    selectAtendimento,
    devolver,
    fechar,
    perder,
    corrigirRegistro,
    corrigirAlvoId,
    abrirCorrigir,
    fecharCorrigir,
    moverEstado,
    excluir,
    editarDados,
    criarAtendimento,
    loadDetalhe,
    uploadMidia,
    deletarMidia,
  }
}
