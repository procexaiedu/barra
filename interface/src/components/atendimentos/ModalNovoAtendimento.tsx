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
import { ModalCriarCliente } from "@/components/clientes/ModalCriarCliente"
import {
  FormularioCamposAtendimento,
  type FormularioCamposAtendimentoRef,
} from "@/components/atendimentos/FormularioCamposAtendimento"
import type {
  Cliente,
  ClienteListItem,
  ClientesListaResponse,
  CriarClienteRequest,
} from "@/tipos/clientes"
import type { ModelosListaResponse } from "@/tipos/modelos"
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
  onCriarCliente: (payload: CriarClienteRequest) => Promise<Cliente>
  onCriado: (atendimentoId: string) => void
  /** Cliente pré-selecionado ao abrir (ex.: vindo da tela de Clientes). */
  clienteInicial?: ClienteListItem | null
}

export function ModalNovoAtendimento({
  open,
  onClose,
  onCriar,
  onCriarCliente,
  onCriado,
  clienteInicial,
}: ModalNovoAtendimentoProps) {
  // O modal é montado fresh a cada abertura, então basta inicializar o state com
  // o cliente pré-selecionado; o usuário ainda pode trocar ou limpar.
  const [busca, setBusca] = useState(
    clienteInicial?.nome ?? clienteInicial?.telefone_mascarado ?? ""
  )
  const [resultados, setResultados] = useState<ClienteListItem[]>([])
  const [buscando, setBuscando] = useState(false)
  const [clienteSelecionado, setClienteSelecionado] = useState<ClienteListItem | null>(
    clienteInicial ?? null
  )
  const [modelos, setModelos] = useState<ModeloOpcao[]>([])
  const [modeloId, setModeloId] = useState<string>("")
  const [carregandoModelos, setCarregandoModelos] = useState(true)
  const [erroModelos, setErroModelos] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [modalClienteAberto, setModalClienteAberto] = useState(false)
  const [temConflito, setTemConflito] = useState(false)
  const buscaTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const camposRef = useRef<FormularioCamposAtendimentoRef>(null)

  useEffect(() => {
    let cancelado = false
    api<ModelosListaResponse>("/v1/modelos?status=ativa&limit=100")
      .then((res) => {
        if (cancelado) return
        setModelos(res.items.map((r) => ({ id: r.id, nome: r.nome })))
        setCarregandoModelos(false)
      })
      .catch(() => {
        if (cancelado) return
        setModelos([])
        setErroModelos(true)
        setCarregandoModelos(false)
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
    let atendId: string | null = null
    let dadosParciaisFalharam = false
    try {
      const resultado = await onCriar({
        cliente_id: clienteSelecionado.id,
        modelo_id: modeloId,
      })
      atendId =
        resultado.tipo === "criado" ? resultado.atendimento.id : resultado.atendimento_id

      const coletado = camposRef.current?.coletarDados()
      const payload = coletado?.payload ?? {}
      const programas = coletado?.programas ?? []

      if (Object.keys(payload).length > 0) {
        try {
          await api(`/v1/atendimentos/${atendId}/dados`, {
            method: "PATCH",
            body: JSON.stringify(payload),
          })
        } catch {
          dadosParciaisFalharam = true
        }
      }

      for (const p of programas) {
        try {
          await api(`/v1/atendimentos/${atendId}/servicos`, {
            method: "POST",
            body: JSON.stringify(p),
          })
        } catch {
          dadosParciaisFalharam = true
        }
      }

      if (resultado.tipo === "criado") {
        if (dadosParciaisFalharam) {
          toast.warning(
            `Atendimento #${resultado.atendimento.numero_curto} criado, mas alguns dados não puderam ser salvos. Edite para completar.`,
          )
        } else {
          toast.success(`Atendimento #${resultado.atendimento.numero_curto} criado`)
        }
      } else {
        toast.info("Já existe atendimento aberto no par, abrindo…")
      }
      onCriado(atendId)
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

  const podeSalvar = Boolean(clienteSelecionado && modeloId) && !submitting && !temConflito

  const aoCriarCliente = (cliente: Cliente) => {
    const item: ClienteListItem = {
      id: cliente.id,
      nome: cliente.nome,
      telefone_mascarado: cliente.telefone,
      primeiro_contato_modelo_id: null,
      arquivado_em: cliente.arquivado_em,
      created_at: cliente.created_at,
      updated_at: cliente.updated_at,
    }
    selecionarCliente(item)
    setModalClienteAberto(false)
  }

  return (
    <>
      <Dialog
        open={open}
        onOpenChange={(o) => {
          if (!o) handleClose()
        }}
      >
        <DialogContent className="flex max-h-[90vh] w-[min(94vw,72rem)] max-w-none flex-col overflow-hidden rounded-xl border border-border-strong bg-surface-raised p-0 shadow-[0_16px_48px_rgba(0,0,0,0.7)]">
          <div className="border-b border-border-subtle px-5 py-4">
            <DialogTitle className="font-serif text-xl font-medium leading-tight text-text-primary">
              Novo atendimento
            </DialogTitle>
            <DialogDescription className="mt-1 text-xs text-text-muted">
              Selecione cliente e modelo. Os demais campos são opcionais e podem ser
              preenchidos agora ou editados depois.
            </DialogDescription>
          </div>

          <div className="grid grid-cols-1 gap-4 border-b border-border-subtle bg-surface px-5 py-4 sm:grid-cols-2">
            <div className="relative">
              <div className="flex items-center justify-between">
                <Label htmlFor="novo-atend-cliente">Cliente</Label>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => setModalClienteAberto(true)}
                  disabled={submitting}
                >
                  + Novo cliente
                </Button>
              </div>
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
                        className="flex w-full items-center justify-between gap-3 border-b border-border px-3 py-2.5 text-left text-sm last:border-0 hover:bg-accent"
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
                  {carregandoModelos
                    ? "Carregando…"
                    : erroModelos
                      ? "Erro ao carregar modelos"
                      : modelos.length === 0
                        ? "Nenhuma modelo ativa"
                        : "Selecione…"}
                </option>
                {modelos.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.nome}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto">
            <FormularioCamposAtendimento
              ref={camposRef}
              modeloId={modeloId || null}
              disabled={submitting}
              variant="horizontal"
              onConflitoChange={setTemConflito}
            />
          </div>

          <div className="flex justify-end gap-2 border-t border-border-subtle bg-surface px-5 py-3">
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
      <ModalCriarCliente
        open={modalClienteAberto}
        onClose={() => setModalClienteAberto(false)}
        onCriar={onCriarCliente}
        onCriado={aoCriarCliente}
      />
    </>
  )
}
