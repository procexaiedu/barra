"use client"

import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import { api, ApiError } from "@/lib/api"
import type { FiltroPeriodo } from "@/tipos/dashboard"
import type {
  CategoriaDespesa,
  DespesasListaResponse,
  FinanceiroResumoResponse,
  FormaPagamentoReceita,
  ReceitasListaResponse,
  RepassesPagamentosListaResponse,
  RepassesPorModeloResponse,
} from "@/tipos/financeiro"

type Status = "loading" | "success" | "error"
type View = "geral" | "receitas" | "despesas" | "repasses"

const PERIODOS_VALIDOS: ReadonlySet<string> = new Set([
  "hoje", "7d", "30d", "mes", "tudo", "custom",
])
const VIEWS_VALIDAS: ReadonlySet<string> = new Set([
  "geral", "receitas", "despesas", "repasses",
])

export interface FiltrosFinanceiro {
  periodo: FiltroPeriodo
  de: string | null
  ate: string | null
  modelo_ids: string[]
  categoria: CategoriaDespesa[]
  forma_pagamento: FormaPagamentoReceita | null
  view: View
}

function parseFiltros(params: URLSearchParams): FiltrosFinanceiro {
  const periodoRaw = params.get("periodo")
  const periodo = (periodoRaw && PERIODOS_VALIDOS.has(periodoRaw)
    ? periodoRaw : "mes") as FiltroPeriodo
  const de = params.get("de")
  const ate = params.get("ate")
  const viewRaw = params.get("view")
  const view = (viewRaw && VIEWS_VALIDAS.has(viewRaw) ? viewRaw : "geral") as View

  const dataValida = (s: string | null): s is string =>
    !!s && /^\d{4}-\d{2}-\d{2}$/.test(s)

  const periodoCustom = periodo === "custom" && dataValida(de) && dataValida(ate)
  return {
    periodo: periodoCustom ? "custom" : periodo,
    de: periodoCustom ? de : null,
    ate: periodoCustom ? ate : null,
    modelo_ids: params.getAll("modelo_id"),
    categoria: params.getAll("categoria") as CategoriaDespesa[],
    forma_pagamento: (params.get("forma_pagamento") as FormaPagamentoReceita | null) || null,
    view,
  }
}

function montarPath(filtros: FiltrosFinanceiro, recurso: string): string {
  const params = new URLSearchParams()
  params.set("periodo", filtros.periodo)
  if (filtros.periodo === "custom" && filtros.de && filtros.ate) {
    params.set("de", filtros.de)
    params.set("ate", filtros.ate)
  }
  for (const id of filtros.modelo_ids) params.append("modelo_id", id)
  if (recurso === "/despesas") {
    for (const c of filtros.categoria) params.append("categoria", c)
  }
  if (recurso === "/receitas" && filtros.forma_pagamento) {
    params.set("forma_pagamento", filtros.forma_pagamento)
  }
  return `/v1/financeiro${recurso}?${params.toString()}`
}

function montarQueryString(filtros: FiltrosFinanceiro): string {
  const params = new URLSearchParams()
  if (filtros.periodo !== "mes") params.set("periodo", filtros.periodo)
  if (filtros.periodo === "custom" && filtros.de && filtros.ate) {
    params.set("de", filtros.de)
    params.set("ate", filtros.ate)
  }
  for (const id of filtros.modelo_ids) params.append("modelo_id", id)
  for (const c of filtros.categoria) params.append("categoria", c)
  if (filtros.forma_pagamento) params.set("forma_pagamento", filtros.forma_pagamento)
  if (filtros.view !== "geral") params.set("view", filtros.view)
  const s = params.toString()
  return s ? `?${s}` : ""
}

export function useFinanceiro() {
  const router = useRouter()
  const searchParams = useSearchParams()

  const filtros = useMemo(
    () => parseFiltros(new URLSearchParams(searchParams.toString())),
    [searchParams]
  )

  const [resumo, setResumo] = useState<FinanceiroResumoResponse | null>(null)
  const [receitas, setReceitas] = useState<ReceitasListaResponse | null>(null)
  const [despesas, setDespesas] = useState<DespesasListaResponse | null>(null)
  const [repasses, setRepasses] = useState<RepassesPorModeloResponse | null>(null)
  const [pagamentos, setPagamentos] = useState<RepassesPagamentosListaResponse | null>(null)
  const [status, setStatus] = useState<Status>("loading")
  const [error, setError] = useState<string | null>(null)

  const abortRef = useRef<AbortController | null>(null)
  const firstLoadDone = useRef(false)

  const fetchView = useCallback(async () => {
    if (abortRef.current) abortRef.current.abort()
    const ctrl = new AbortController()
    abortRef.current = ctrl

    // setStatus('loading') foi removido: default state já é 'loading' e só
    // setamos 'success'/'error' após o await. Isso evita disparar o lint
    // react-hooks/set-state-in-effect (setState síncrono no body do effect).
    try {
      // Resumo sempre. Outras consultas só sob demanda da view.
      const promises: Promise<unknown>[] = []
      promises.push(
        api<FinanceiroResumoResponse>(montarPath(filtros, ""), { signal: ctrl.signal })
          .then(setResumo)
      )
      if (filtros.view === "receitas") {
        promises.push(
          api<ReceitasListaResponse>(montarPath(filtros, "/receitas"), { signal: ctrl.signal })
            .then(setReceitas)
        )
      }
      if (filtros.view === "despesas") {
        promises.push(
          api<DespesasListaResponse>(montarPath(filtros, "/despesas"), { signal: ctrl.signal })
            .then(setDespesas)
        )
      }
      if (filtros.view === "repasses") {
        promises.push(
          api<RepassesPorModeloResponse>(montarPath(filtros, "/repasses"), { signal: ctrl.signal })
            .then(setRepasses)
        )
        promises.push(
          api<RepassesPagamentosListaResponse>(montarPath(filtros, "/repasses/pagamentos"), { signal: ctrl.signal })
            .then(setPagamentos)
        )
      }
      await Promise.all(promises)
      if (ctrl.signal.aborted) return
      setStatus("success")
      setError(null)
      firstLoadDone.current = true
    } catch (e) {
      if (ctrl.signal.aborted) return
      if (e instanceof DOMException && e.name === "AbortError") return
      if (!firstLoadDone.current) setStatus("error")
      const detail = e instanceof ApiError ? e.detail
        : e instanceof Error ? e.message : "Erro desconhecido"
      setError(detail)
    }
  }, [filtros])

  useEffect(() => {
    // fetchView é async — setStates só rodam após o await; o lint detecta
    // a chamada como potencial setState síncrono, mas o caminho até lá passa
    // por `await Promise.all(...)`. Mesmo padrão do useDashboard.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    fetchView()
    return () => {
      if (abortRef.current) abortRef.current.abort()
    }
  }, [fetchView])

  const aplicarFiltros = useCallback(
    (proximo: FiltrosFinanceiro) => {
      router.replace(`/financeiro${montarQueryString(proximo)}`, { scroll: false })
    },
    [router]
  )

  const setPeriodoPreset = useCallback(
    (periodo: Exclude<FiltroPeriodo, "custom">) =>
      aplicarFiltros({ ...filtros, periodo, de: null, ate: null }),
    [aplicarFiltros, filtros]
  )

  const setPeriodoCustom = useCallback(
    (de: string, ate: string) =>
      aplicarFiltros({ ...filtros, periodo: "custom", de, ate }),
    [aplicarFiltros, filtros]
  )

  const setModeloIds = useCallback(
    (modelo_ids: string[]) =>
      aplicarFiltros({ ...filtros, modelo_ids }),
    [aplicarFiltros, filtros]
  )

  const setCategoria = useCallback(
    (categoria: CategoriaDespesa[]) =>
      aplicarFiltros({ ...filtros, categoria }),
    [aplicarFiltros, filtros]
  )

  const setFormaPagamento = useCallback(
    (forma: FormaPagamentoReceita | null) =>
      aplicarFiltros({ ...filtros, forma_pagamento: forma }),
    [aplicarFiltros, filtros]
  )

  const setView = useCallback(
    (view: View) => aplicarFiltros({ ...filtros, view }),
    [aplicarFiltros, filtros]
  )

  const refetch = useCallback(() => {
    fetchView()
  }, [fetchView])

  return {
    filtros,
    status,
    error,
    resumo,
    receitas,
    despesas,
    repasses,
    pagamentos,
    setPeriodoPreset,
    setPeriodoCustom,
    setModeloIds,
    setCategoria,
    setFormaPagamento,
    setView,
    refetch,
    // helpers para o componente:
    montarPathExport: (recurso: "/receitas/export" | "/despesas/export" | "/repasses/pagamentos/export") =>
      montarPath(filtros, recurso),
  }
}

export type { View as FinanceiroView }
