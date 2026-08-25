"use client"

import { useCallback, useEffect, useState } from "react"
import { api, ApiError } from "@/lib/api"
import type {
  ConferenciaPorFormaResponse,
  EstadoDaTemporada,
  TemporadasListaResponse,
} from "@/tipos/razao"

type Status = "loading" | "success" | "error"

export interface FiltrosTemporadas {
  /** `null` = todas, inclusive fechadas e canceladas. */
  estado: EstadoDaTemporada | null
  /** Período da CONFERÊNCIA (as temporadas trazem o período delas). */
  periodo: string
  de: string | null
  ate: string | null
  modelo_ids: string[]
}

function montarQuery(filtros: FiltrosTemporadas, incluirPeriodo: boolean): string {
  const params = new URLSearchParams()
  if (incluirPeriodo) {
    params.set("periodo", filtros.periodo)
    if (filtros.periodo === "custom" && filtros.de && filtros.ate) {
      params.set("de", filtros.de)
      params.set("ate", filtros.ate)
    }
  }
  for (const id of filtros.modelo_ids) params.append("modelo_id", id)
  return params.toString()
}

/**
 * O "financeiro dos telefonistas": as temporadas com o saldo de cada modelo e a conferência por
 * forma de pagamento.
 *
 * As duas chamadas são independentes de propósito — a conferência responde pelo PERÍODO do
 * filtro do header, e cada temporada responde pelo período dela. Amarrá-las obrigaria a escolher
 * um recorte só, e o gestor pergunta as duas coisas ao mesmo tempo.
 */
export function useTemporadas(filtros: FiltrosTemporadas) {
  const [temporadas, setTemporadas] = useState<TemporadasListaResponse | null>(null)
  const [conferencia, setConferencia] = useState<ConferenciaPorFormaResponse | null>(null)
  const [status, setStatus] = useState<Status>("loading")
  const [error, setError] = useState<string | null>(null)

  const { estado, periodo, de, ate } = filtros
  const modelosKey = filtros.modelo_ids.join(",")

  const carregar = useCallback(async () => {
    const alvo: FiltrosTemporadas = {
      estado,
      periodo,
      de,
      ate,
      modelo_ids: modelosKey ? modelosKey.split(",") : [],
    }
    try {
      const qsTemporadas = montarQuery(alvo, false)
      const params = new URLSearchParams(qsTemporadas)
      if (alvo.estado) params.set("estado", alvo.estado)
      const [lista, conf] = await Promise.all([
        api<TemporadasListaResponse>(`/v1/financeiro/temporadas?${params.toString()}`),
        api<ConferenciaPorFormaResponse>(
          `/v1/financeiro/conferencia?${montarQuery(alvo, true)}`,
        ),
      ])
      setTemporadas(lista)
      setConferencia(conf)
      setStatus("success")
      setError(null)
    } catch (e) {
      setStatus("error")
      setError(
        e instanceof ApiError ? e.detail : e instanceof Error ? e.message : "Erro desconhecido",
      )
    }
  }, [estado, periodo, de, ate, modelosKey])

  useEffect(() => {
    // `carregar` é async: os setState só rodam depois do await. Mesmo padrão do useFinanceiro.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    carregar()
  }, [carregar])

  return { temporadas, conferencia, status, error, refetch: carregar }
}
