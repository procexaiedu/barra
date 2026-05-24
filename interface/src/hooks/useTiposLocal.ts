"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import { toast } from "sonner"
import { api } from "@/lib/api"
import { formatRotulo } from "@/lib/formatters"
import type {
  ContagemTipoLocalResponse,
  TiposLocalResponse,
} from "@/tipos/atendimentos"

interface RemocaoEmAndamento {
  nome: string
  contagem: number
}

/**
 * Estado e fluxo do Combobox "Tipo de local": lista combinada (backend + criados
 * na sessão), criação otimista e remoção de sugestões com substituição/limpeza.
 *
 * Fluxo de remoção: consulta a contagem; se 0, confirma simples e deleta; se >0,
 * abre o modal de substituição (exposto via `remocao`). Após sucesso, recarrega.
 */
export function useTiposLocal() {
  const [tiposBackend, setTiposBackend] = useState<string[]>([])
  const [tiposCriadosSessao, setTiposCriadosSessao] = useState<string[]>([])
  const [remocao, setRemocao] = useState<RemocaoEmAndamento | null>(null)

  const tiposCombinados = useMemo(
    () => Array.from(new Set([...tiposBackend, ...tiposCriadosSessao])).sort(),
    [tiposBackend, tiposCriadosSessao],
  )

  const carregar = useCallback(() => {
    api<TiposLocalResponse>("/v1/atendimentos/tipos-local")
      .then((r) => setTiposBackend(r.items))
      .catch(() => {})
  }, [])

  useEffect(() => {
    carregar()
  }, [carregar])

  const adicionarTipoSessao = useCallback((novo: string) => {
    setTiposCriadosSessao((prev) => [...prev, novo])
  }, [])

  const deletar = useCallback(async (nome: string) => {
    await api(
      `/v1/atendimentos/tipos-local/${encodeURIComponent(nome)}`,
      { method: "DELETE" },
    )
    // limpa também da lista criada nesta sessão, se for o caso
    setTiposCriadosSessao((prev) => prev.filter((t) => t !== nome))
    carregar()
  }, [carregar])

  // Chamado pelo botão de lixeira: decide entre confirmação simples (0) e modal (>0).
  const iniciarRemocao = useCallback(
    async (nome: string) => {
      try {
        const { contagem } = await api<ContagemTipoLocalResponse>(
          `/v1/atendimentos/tipos-local/${encodeURIComponent(nome)}/contagem`,
        )
        const rotulo = formatRotulo(nome) ?? nome
        if (contagem === 0) {
          if (!window.confirm(`Remover "${rotulo}" das sugestões?`)) return
          await deletar(nome)
          toast.success(`Tipo de local "${rotulo}" removido`)
        } else {
          setRemocao({ nome, contagem })
        }
      } catch (e) {
        toast.error(e instanceof Error ? e.message : "Erro ao verificar tipo")
      }
    },
    [deletar],
  )

  const cancelarRemocao = useCallback(() => setRemocao(null), [])

  const aposRemover = useCallback(() => {
    setRemocao(null)
    carregar()
  }, [carregar])

  return {
    tiposCombinados,
    adicionarTipoSessao,
    iniciarRemocao,
    remocao,
    cancelarRemocao,
    aposRemover,
  }
}
