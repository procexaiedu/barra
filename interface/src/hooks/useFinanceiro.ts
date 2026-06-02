"use client"

import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { useSearchParams } from "next/navigation"
import { api, ApiError } from "@/lib/api"
import type { FiltroPeriodo } from "@/tipos/dashboard"
import type {
  FinanceiroResumoResponse,
  FinanceiroSerieResponse,
  FormaPagamentoReceita,
  ReceitasListaResponse,
  RepassesPagamentosListaResponse,
  RepassesPorModeloResponse,
} from "@/tipos/financeiro"

type Status = "loading" | "success" | "error"
type View = "geral" | "receitas" | "repasses"

const PERIODOS_VALIDOS: ReadonlySet<string> = new Set([
  "hoje", "7d", "30d", "mes", "tudo", "custom",
])
const VIEWS_VALIDAS: ReadonlySet<string> = new Set([
  "geral", "receitas", "repasses",
])

// Itens por página em cada visualização. Hoje carrega menos porque o dia
// raramente tem >25 fechamentos — pegar 50 seria over-fetch. Os outros
// períodos pegam 50 (padrão SaaS: Stripe/Linear), com "carregar mais" via
// cursor para os volumes maiores. "Saldo por modelo" não usa esse limit
// (backend retorna todas as modelos; a paginação dela é client-side).
const LIMIT_POR_PERIODO: Record<FiltroPeriodo, number> = {
  hoje: 25,
  "7d": 50,
  "30d": 50,
  mes: 50,
  tudo: 50,
  custom: 50,
}

export interface FiltrosFinanceiro {
  periodo: FiltroPeriodo
  de: string | null
  ate: string | null
  modelo_ids: string[]
  forma_pagamento: FormaPagamentoReceita | null
  view: View
}

function parseFiltros(params: URLSearchParams): FiltrosFinanceiro {
  const periodoRaw = params.get("periodo")
  const periodo = (periodoRaw && PERIODOS_VALIDOS.has(periodoRaw)
    ? periodoRaw : "tudo") as FiltroPeriodo
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
    forma_pagamento: (params.get("forma_pagamento") as FormaPagamentoReceita | null) || null,
    view,
  }
}

function montarPath(
  filtros: FiltrosFinanceiro,
  recurso: string,
  opcoes?: { limit?: number; cursor?: string | null },
): string {
  const params = new URLSearchParams()
  params.set("periodo", filtros.periodo)
  if (filtros.periodo === "custom" && filtros.de && filtros.ate) {
    params.set("de", filtros.de)
    params.set("ate", filtros.ate)
  }
  for (const id of filtros.modelo_ids) params.append("modelo_id", id)
  if (recurso === "/receitas" && filtros.forma_pagamento) {
    params.set("forma_pagamento", filtros.forma_pagamento)
  }
  if (opcoes?.limit) params.set("limit", String(opcoes.limit))
  if (opcoes?.cursor) params.set("cursor", opcoes.cursor)
  return `/v1/financeiro${recurso}?${params.toString()}`
}

function montarQueryString(filtros: FiltrosFinanceiro): string {
  const params = new URLSearchParams()
  if (filtros.periodo !== "tudo") params.set("periodo", filtros.periodo)
  if (filtros.periodo === "custom" && filtros.de && filtros.ate) {
    params.set("de", filtros.de)
    params.set("ate", filtros.ate)
  }
  for (const id of filtros.modelo_ids) params.append("modelo_id", id)
  if (filtros.forma_pagamento) params.set("forma_pagamento", filtros.forma_pagamento)
  if (filtros.view !== "geral") params.set("view", filtros.view)
  const s = params.toString()
  return s ? `?${s}` : ""
}

export function useFinanceiro() {
  const searchParams = useSearchParams()

  const filtros = useMemo(
    () => parseFiltros(new URLSearchParams(searchParams.toString())),
    [searchParams]
  )

  const [resumo, setResumo] = useState<FinanceiroResumoResponse | null>(null)
  const [serie, setSerie] = useState<FinanceiroSerieResponse | null>(null)
  const [receitas, setReceitas] = useState<ReceitasListaResponse | null>(null)
  const [repasses, setRepasses] = useState<RepassesPorModeloResponse | null>(null)
  const [pagamentos, setPagamentos] = useState<RepassesPagamentosListaResponse | null>(null)
  const [status, setStatus] = useState<Status>("loading")
  const [error, setError] = useState<string | null>(null)
  const [carregandoMaisReceitas, setCarregandoMaisReceitas] = useState(false)
  const [carregandoMaisPagamentos, setCarregandoMaisPagamentos] = useState(false)

  const abortRef = useRef<AbortController | null>(null)
  const firstLoadDone = useRef(false)
  const limitAtual = LIMIT_POR_PERIODO[filtros.periodo]

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
      const limit = LIMIT_POR_PERIODO[filtros.periodo]
      promises.push(
        api<FinanceiroResumoResponse>(montarPath(filtros, ""), { signal: ctrl.signal })
          .then(setResumo)
      )
      if (filtros.view === "geral") {
        promises.push(
          api<FinanceiroSerieResponse>(montarPath(filtros, "/serie"), { signal: ctrl.signal })
            .then(setSerie)
        )
      }
      if (filtros.view === "receitas") {
        promises.push(
          api<ReceitasListaResponse>(
            montarPath(filtros, "/receitas", { limit }),
            { signal: ctrl.signal },
          ).then(setReceitas),
        )
      }
      if (filtros.view === "repasses") {
        promises.push(
          api<RepassesPorModeloResponse>(montarPath(filtros, "/repasses"), { signal: ctrl.signal })
            .then(setRepasses)
        )
        promises.push(
          api<RepassesPagamentosListaResponse>(
            montarPath(filtros, "/repasses/pagamentos", { limit }),
            { signal: ctrl.signal },
          ).then(setPagamentos),
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

  // Paginação por cursor — anexa o próximo lote ao state atual mantendo a
  // ordem. O backend devolve next_cursor=null quando esgota; a UI esconde o
  // botão "carregar mais" nesse caso.
  const carregarMaisReceitas = useCallback(async () => {
    if (!receitas?.next_cursor || carregandoMaisReceitas) return
    setCarregandoMaisReceitas(true)
    try {
      const proximo = await api<ReceitasListaResponse>(
        montarPath(filtros, "/receitas", {
          limit: limitAtual,
          cursor: receitas.next_cursor,
        }),
      )
      setReceitas({
        filtro_aplicado: proximo.filtro_aplicado,
        items: [...receitas.items, ...proximo.items],
        next_cursor: proximo.next_cursor,
      })
    } catch (e) {
      const detail = e instanceof ApiError ? e.detail
        : e instanceof Error ? e.message : "Erro desconhecido"
      setError(detail)
    } finally {
      setCarregandoMaisReceitas(false)
    }
  }, [receitas, filtros, limitAtual, carregandoMaisReceitas])

  const carregarMaisPagamentos = useCallback(async () => {
    if (!pagamentos?.next_cursor || carregandoMaisPagamentos) return
    setCarregandoMaisPagamentos(true)
    try {
      const proximo = await api<RepassesPagamentosListaResponse>(
        montarPath(filtros, "/repasses/pagamentos", {
          limit: limitAtual,
          cursor: pagamentos.next_cursor,
        }),
      )
      setPagamentos({
        filtro_aplicado: proximo.filtro_aplicado,
        items: [...pagamentos.items, ...proximo.items],
        next_cursor: proximo.next_cursor,
      })
    } catch (e) {
      const detail = e instanceof ApiError ? e.detail
        : e instanceof Error ? e.message : "Erro desconhecido"
      setError(detail)
    } finally {
      setCarregandoMaisPagamentos(false)
    }
  }, [pagamentos, filtros, limitAtual, carregandoMaisPagamentos])

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
      if (typeof window === "undefined") return
      // Next 16: window.history.replaceState para mudancas de query string
      // evita o round-trip de Server Components do router.replace e sincroniza
      // com useSearchParams imediatamente. Corrige bug intermitente em que
      // cliques rapidos nas abas (Visao geral / Receitas / Repasses) eram
      // engolidos por uma transicao pendente. Doc: shallow routing em
      // docs/01-app/01-getting-started/04-linking-and-navigating.md.
      window.history.replaceState(null, "", `/financeiro${montarQueryString(proximo)}`)
    },
    [],
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
    serie,
    receitas,
    repasses,
    pagamentos,
    setPeriodoPreset,
    setPeriodoCustom,
    setModeloIds,
    setFormaPagamento,
    setView,
    refetch,
    // Paginação por cursor — UI esconde "carregar mais" quando next_cursor=null.
    carregarMaisReceitas,
    carregarMaisPagamentos,
    carregandoMaisReceitas,
    carregandoMaisPagamentos,
    limitAtual,
    // helpers para o componente:
    montarPathExport: (recurso: "/receitas/export" | "/repasses/pagamentos/export") =>
      montarPath(filtros, recurso),
  }
}

export type { View as FinanceiroView }
