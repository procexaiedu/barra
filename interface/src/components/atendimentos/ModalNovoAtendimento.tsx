"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { Loader2, Search, X } from "lucide-react"
import { toast } from "sonner"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { ApiError, api } from "@/lib/api"
import { formatTelefone } from "@/lib/formatters"
import type {
  ClienteListItem,
  ClientesListaResponse,
  ModeloResumo,
} from "@/tipos/clientes"
import type {
  CriarAtendimentoRequest,
  CriarAtendimentoResultado,
} from "@/tipos/atendimentos"

interface ModeloOpcao {
  id: string
  nome: string
}

interface ModalNovoAtendimentoProps {
  open: boolean
  onClose: () => void
  onCriar: (payload: CriarAtendimentoRequest) => Promise<CriarAtendimentoResultado>
  onCriado: (atendimentoId: string) => void
}

export function ModalNovoAtendimento({
  open,
  onClose,
  onCriar,
  onCriado,
}: ModalNovoAtendimentoProps) {
  const [busca, setBusca] = useState("")
  const [resultados, setResultados] = useState<ClienteListItem[]>([])
  const [buscando, setBuscando] = useState(false)
  const [clienteSelecionado, setClienteSelecionado] = useState<ClienteListItem | null>(null)
  const [modelos, setModelos] = useState<ModeloOpcao[]>([])
  const [modeloId, setModeloId] = useState<string>("")
  const [submitting, setSubmitting] = useState(false)
  const buscaTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    let cancelado = false
    api<ModeloResumo[]>("/v1/modelos")
      .then((rows) => {
        if (cancelado) return
        setModelos(rows.map((r) => ({ id: r.id, nome: r.nome })))
      })
      .catch(() => {
        if (cancelado) return
        setModelos([])
      })
    return () => {
      cancelado = true
    }
  }, [])

  const buscar = useCallback(async (texto: string) => {
    if (!texto.trim()) {
      setResultados([])
      setBuscando(false)
      return
    }
    setBuscando(true)
    try {
      const params = new URLSearchParams({
        q: texto.trim(),
        incluir_arquivados: "false",
        limit: "10",
      })
      const res = await api<ClientesListaResponse>(`/v1/crm/clientes?${params}`)
      setResultados(res.items.slice(0, 8))
    } catch {
      setResultados([])
    } finally {
      setBuscando(false)
    }
  }, [])

  const handleBuscaChange = (texto: string) => {
    setBusca(texto)
    setClienteSelecionado(null)
    if (buscaTimer.current) clearTimeout(buscaTimer.current)
    buscaTimer.current = setTimeout(() => buscar(texto), 250)
  }

  const selecionarCliente = (cliente: ClienteListItem) => {
    setClienteSelecionado(cliente)
    setBusca(cliente.nome ?? cliente.telefone_mascarado ?? "")
    setResultados([])
  }

  const limparCliente = () => {
    setClienteSelecionado(null)
    setBusca("")
    setResultados([])
  }

  const handleClose = () => {
    if (submitting) return
    onClose()
  }

  const handleSubmit = async () => {
    if (!clienteSelecionado || !modeloId) return
    setSubmitting(true)
    try {
      const resultado = await onCriar({
        cliente_id: clienteSelecionado.id,
        modelo_id: modeloId,
      })
      if (resultado.tipo === "criado") {
        toast.success(`Atendimento #${resultado.atendimento.numero_curto} criado`)
        onCriado(resultado.atendimento.id)
      } else {
        toast.info("Já existe atendimento aberto no par, abrindo…")
        onCriado(resultado.atendimento_id)
      }
      onClose()
    } catch (e) {
      if (e instanceof ApiError) {
        if (e.status === 409 && e.detail === "cliente_arquivado") {
          toast.error("Cliente está arquivado. Desarquive antes de criar atendimento.")
        } else if (e.status === 404) {
          toast.error("Cliente ou modelo não encontrado.")
        } else {
          toast.error(e.message || "Erro ao criar atendimento")
        }
      } else {
        toast.error(e instanceof Error ? e.message : "Erro ao criar atendimento")
      }
      setSubmitting(false)
    }
  }

  const podeSalvar = Boolean(clienteSelecionado && modeloId) && !submitting

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!o) handleClose()
      }}
    >
      <DialogContent className="w-full max-w-lg rounded-lg border border-border bg-popover p-6 text-popover-foreground shadow-[0_16px_48px_rgba(0,0,0,0.7)]">
        <DialogTitle>Novo atendimento</DialogTitle>
        <DialogDescription className="mt-1">
          Selecione o cliente e a modelo para abrir um atendimento.
        </DialogDescription>

        <div className="mt-5 space-y-4">
          <div className="relative">
            <Label htmlFor="novo-atend-cliente">Cliente</Label>
            <div className="relative mt-2">
              <Search
                size={14}
                strokeWidth={1.5}
                className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-text-muted"
              />
              <Input
                id="novo-atend-cliente"
                value={busca}
                onChange={(e) => handleBuscaChange(e.target.value)}
                placeholder="Nome ou telefone..."
                className="h-10 pl-9 pr-8"
                disabled={submitting}
                autoComplete="off"
              />
              {buscando && (
                <Loader2
                  size={14}
                  className="absolute right-3 top-1/2 -translate-y-1/2 animate-spin text-text-muted"
                />
              )}
              {!buscando && busca && (
                <button
                  type="button"
                  onClick={limparCliente}
                  className="absolute right-2 top-1/2 -translate-y-1/2 rounded-md p-1 text-text-muted hover:bg-muted hover:text-text-primary"
                  aria-label="Limpar cliente"
                >
                  <X size={14} />
                </button>
              )}
              {resultados.length > 0 && !clienteSelecionado && (
                <div className="absolute z-10 mt-1 max-h-60 w-full overflow-y-auto rounded-lg border border-border bg-popover shadow-[0_8px_24px_rgba(0,0,0,0.6)]">
                  {resultados.map((cliente) => (
                    <button
                      key={cliente.id}
                      type="button"
                      onClick={() => selecionarCliente(cliente)}
                      className="flex w-full items-center justify-between gap-3 px-3 py-2.5 text-left text-sm hover:bg-ink-200 border-b border-border last:border-0"
                    >
                      <span className="flex-1 truncate font-medium text-text-primary">
                        {cliente.nome ?? "Sem nome"}
                      </span>
                      <span className="font-mono text-xs text-text-muted">
                        {cliente.telefone_mascarado
                          ? formatTelefone(cliente.telefone_mascarado)
                          : ""}
                      </span>
                    </button>
                  ))}
                </div>
              )}
            </div>
            {clienteSelecionado && (
              <p className="mt-1 text-xs text-text-muted">
                Selecionado: {clienteSelecionado.nome ?? "Sem nome"} ·{" "}
                {clienteSelecionado.telefone_mascarado
                  ? formatTelefone(clienteSelecionado.telefone_mascarado)
                  : ""}
              </p>
            )}
          </div>

          <div>
            <Label htmlFor="novo-atend-modelo">Modelo</Label>
            <select
              id="novo-atend-modelo"
              value={modeloId}
              onChange={(e) => setModeloId(e.target.value)}
              disabled={submitting || modelos.length === 0}
              className="mt-2 h-10 w-full rounded-lg border border-input bg-input px-3 text-sm text-text-primary outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:opacity-60"
            >
              <option value="" disabled>
                {modelos.length === 0 ? "Carregando…" : "Selecione…"}
              </option>
              {modelos.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.nome}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="mt-6 flex justify-end gap-2">
          <Button variant="ghost" onClick={handleClose} disabled={submitting}>
            Cancelar
          </Button>
          <Button variant="primary" onClick={handleSubmit} disabled={!podeSalvar}>
            {submitting && <Loader2 className="animate-spin" />}
            Criar atendimento
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
