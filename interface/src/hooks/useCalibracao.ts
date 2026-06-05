"use client"

import { useCallback, useEffect, useRef, useState } from "react"

import { api, apiFormData } from "@/lib/api"
import type {
  ExportResponse,
  FalasResponse,
  RodadaResumo,
  RodadasResponse,
} from "@/tipos/calibracao"

type Status = "loading" | "success" | "error"

export function useCalibracao() {
  const [rodadas, setRodadas] = useState<RodadaResumo[]>([])
  const [rodadaId, setRodadaId] = useState<string | null>(null)
  const [dados, setDados] = useState<FalasResponse | null>(null)
  // Sem rodada selecionada nao ha nada a carregar -> "success" (a page mostra o placeholder).
  const [status, setStatus] = useState<Status>("success")
  const [error, setError] = useState<string | null>(null)

  // Reutilizavel pelo `criar` (event handler). No mount usamos o padrao `.then` inline abaixo —
  // setState em callback de promise satisfaz react-hooks/set-state-in-effect.
  const recarregarRodadas = useCallback(async () => {
    const r = await api<RodadasResponse>("/v1/calibracao/rodadas")
    setRodadas(r.rodadas)
  }, [])

  useEffect(() => {
    api<RodadasResponse>("/v1/calibracao/rodadas")
      .then((r) => setRodadas(r.rodadas))
      .catch(() => {})
  }, [])

  const rodadaIdRef = useRef(rodadaId)
  useEffect(() => {
    rodadaIdRef.current = rodadaId
  }, [rodadaId])

  const carregarFalas = useCallback(async () => {
    const id = rodadaIdRef.current
    if (!id) return
    try {
      const r = await api<FalasResponse>(`/v1/calibracao/rodadas/${id}/falas`)
      setDados(r)
      setStatus("success")
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao carregar falas")
      setStatus("error")
    }
  }, [])

  useEffect(() => {
    carregarFalas()
  }, [rodadaId, carregarFalas])

  // Event handler (fora de effect) -> setState sincrono e permitido.
  const selecionar = useCallback((id: string) => {
    setStatus("loading")
    setRodadaId(id)
  }, [])

  const criar = useCallback(
    async (nome: string, arquivo: File) => {
      const fd = new FormData()
      fd.set("nome", nome)
      fd.set("arquivo", arquivo)
      const nova = await apiFormData<RodadaResumo>("/v1/calibracao/rodadas", fd)
      await recarregarRodadas()
      selecionar(nova.id)
      return nova
    },
    [recarregarRodadas, selecionar],
  )

  const marcar = useCallback(async (falaPk: string, passou: boolean, observacao: string) => {
    const obs = observacao.trim() || null
    await api<void>("/v1/calibracao/rotulos", {
      method: "PUT",
      body: JSON.stringify({ fala_pk: falaPk, passou, observacao: obs }),
    })
    setDados((prev) =>
      prev
        ? {
            ...prev,
            falas: prev.falas.map((f) =>
              f.id === falaPk ? { ...f, meu_rotulo: { passou, observacao: obs } } : f,
            ),
          }
        : prev,
    )
  }, [])

  const exportar = useCallback(async () => {
    const id = rodadaIdRef.current
    if (!id) return null
    const r = await api<ExportResponse>(`/v1/calibracao/rodadas/${id}/export`)
    const blob = new Blob([r.golden], { type: "application/x-ndjson" })
    const url = URL.createObjectURL(blob)
    const a = document.createElement("a")
    a.href = url
    a.download = "golden.jsonl"
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    setTimeout(() => URL.revokeObjectURL(url), 1000)
    return r
  }, [])

  return { rodadas, rodadaId, dados, status, error, selecionar, criar, marcar, exportar }
}
