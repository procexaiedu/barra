"use client"

import { useEffect, useState } from "react"
import { api } from "@/lib/api"
import { isoAgenda } from "@/hooks/useAgenda"
import type { AgendaResponse, BloqueioAgenda } from "@/tipos/agenda"

// Estados de bloqueio que efetivamente ocupam a agenda da modelo. Alinhado à
// constraint bloqueios_sem_sobreposicao do banco (que só considera ativos).
const ESTADOS_ATIVOS = new Set(["bloqueado", "em_atendimento"])

export interface ConflitoAgendaInput {
  modelo_id: string | null
  data: string
  horario: string
  duracao_horas: number
  /** bloqueio do próprio atendimento em edição — não conta como conflito */
  excluir_bloqueio_id?: string | null
}

export interface ConflitoAgenda {
  conflitos: BloqueioAgenda[]
  carregando: boolean
}

/**
 * Detecta em tempo real bloqueios ativos que se sobrepõem ao período informado,
 * antes do backend rejeitar com 409. Só consulta quando modelo, data, horário e
 * duração estão todos preenchidos; aplica debounce de 300ms.
 */
export function useConflitoAgenda({
  modelo_id,
  data,
  horario,
  duracao_horas,
  excluir_bloqueio_id,
}: ConflitoAgendaInput): ConflitoAgenda {
  const [conflitos, setConflitos] = useState<BloqueioAgenda[]>([])
  const [carregando, setCarregando] = useState(false)

  const completo =
    Boolean(modelo_id) &&
    Boolean(data) &&
    Boolean(horario) &&
    Number.isFinite(duracao_horas) &&
    duracao_horas > 0

  useEffect(() => {
    let cancelado = false

    if (!completo || !modelo_id) {
      // Limpa de forma assíncrona (fora do corpo síncrono do efeito) para não
      // disparar cascading renders. Debounce curto também evita flicker.
      const limpar = setTimeout(() => {
        if (cancelado) return
        setConflitos([])
        setCarregando(false)
      }, 0)
      return () => {
        cancelado = true
        clearTimeout(limpar)
      }
    }

    const inicioIso = isoAgenda(data, horario)
    const fimIso = new Date(new Date(inicioIso).getTime() + duracao_horas * 3_600_000).toISOString()

    const timer = setTimeout(() => {
      if (cancelado) return
      setCarregando(true)
      const params = new URLSearchParams({
        modelo_id,
        inicio: inicioIso,
        fim: fimIso,
      })
      api<AgendaResponse>(`/v1/agenda/bloqueios?${params.toString()}`)
        .then((res) => {
          if (cancelado) return
          setConflitos(
            res.bloqueios.filter(
              (b) => ESTADOS_ATIVOS.has(b.estado) && b.id !== excluir_bloqueio_id,
            ),
          )
          setCarregando(false)
        })
        .catch(() => {
          if (cancelado) return
          setConflitos([])
          setCarregando(false)
        })
    }, 300)

    return () => {
      cancelado = true
      clearTimeout(timer)
    }
  }, [completo, modelo_id, data, horario, duracao_horas, excluir_bloqueio_id])

  return { conflitos, carregando }
}
