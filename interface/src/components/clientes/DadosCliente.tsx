"use client"

import { useState } from "react"
import {
  Archive,
  ArchiveRestore,
  CheckCircle2,
  Clock,
  Info,
  Loader2,
  MapPin,
  Package,
  Pencil,
  TrendingUp,
  User,
  Wallet,
  XCircle,
  type LucideIcon,
} from "lucide-react"
import { toast } from "sonner"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { ModalEditarCliente } from "@/components/clientes/ModalEditarCliente"
import { formatBRL, formatData, formatTempoRelativo } from "@/lib/formatters"
import { rotuloPerfil } from "@/lib/perfilFisico"
import type {
  AtendimentoHistoricoItem,
  Cliente,
  ClienteDetalhe,
  EditarClienteRequest,
  PerfilCalculado,
  PerfilFisico,
} from "@/tipos/clientes"

const TIPO_LABEL: Record<"interno" | "externo", string> = {
  interno: "Interno (vai à modelo)",
  externo: "Externo (vai ao cliente)",
}

const FORMA_PAGAMENTO_LABEL: Record<"pix" | "dinheiro" | "outro" | "cartao", string> = {
  pix: "Pix",
  dinheiro: "Dinheiro",
  outro: "Outro",
  cartao: "Cartão",
}

export function DadosCliente({
  cliente,
  historico,
  arquivado = false,
  onEditarCliente,
  onArquivarCliente,
  onDesarquivarCliente,
}: {
  cliente: ClienteDetalhe
  historico: AtendimentoHistoricoItem[]
  arquivado?: boolean
  onEditarCliente?: (id: string, payload: EditarClienteRequest) => Promise<Cliente>
  onArquivarCliente?: (id: string) => Promise<void>
  onDesarquivarCliente?: (id: string) => Promise<void>
}) {
  const [modalEditarAberto, setModalEditarAberto] = useState(false)
  const [confirmArquivarAberto, setConfirmArquivarAberto] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  const fechados = historico.filter((h) => h.estado === "Fechado")
  const perdidos = historico.filter((h) => h.estado === "Perdido")
  const receita = fechados.reduce((acc, curr) => acc + (Number(curr.valor_final) || 0), 0)
  const ticketMedio = fechados.length > 0 ? receita / fechados.length : 0
  const ultimoFechamentoEm = fechados[0]?.created_at ?? null
  const podeArquivar = Boolean(onArquivarCliente && onDesarquivarCliente)

  const handleArquivarOuDesarquivar = async () => {
    if (!onArquivarCliente || !onDesarquivarCliente) return
    setSubmitting(true)
    try {
      if (arquivado) {
        await onDesarquivarCliente(cliente.id)
        toast.success("Cliente desarquivado")
      } else {
        await onArquivarCliente(cliente.id)
        toast.success("Cliente arquivado")
      }
      setConfirmArquivarAberto(false)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Erro ao atualizar cliente")
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div
      aria-label="Dados do cliente"
      className="rounded-lg border border-border bg-card"
    >
      {(onEditarCliente || podeArquivar) && (
        <div className="flex items-center justify-between gap-2 border-b border-border px-5 py-3">
          <div className="flex items-center gap-2">
            <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-text-muted">
              Cliente
            </span>
            {arquivado && <Badge variant="paused">Arquivado</Badge>}
          </div>
          <div className="flex items-center gap-1">
            {onEditarCliente && (
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label="Editar cliente"
                onClick={() => setModalEditarAberto(true)}
              >
                <Pencil size={14} strokeWidth={1.5} />
              </Button>
            )}
            {podeArquivar && (
              <Button
                variant={arquivado ? "ghost" : "danger"}
                size="sm"
                onClick={() => setConfirmArquivarAberto(true)}
              >
                {arquivado ? (
                  <>
                    <ArchiveRestore size={14} strokeWidth={1.5} />
                    Desarquivar
                  </>
                ) : (
                  <>
                    <Archive size={14} strokeWidth={1.5} />
                    Arquivar cliente
                  </>
                )}
              </Button>
            )}
          </div>
        </div>
      )}
      <div className="grid grid-cols-4 divide-x divide-border">
        <Metrica label="Fechados" icon={CheckCircle2}>
          <span className="text-2xl font-semibold text-text-primary">
            {fechados.length > 0 ? fechados.length : "—"}
          </span>
        </Metrica>
        <Metrica label="Perdidos" icon={XCircle}>
          <span className={`text-2xl font-semibold ${perdidos.length > 0 ? "text-state-lost" : "text-text-primary"}`}>
            {perdidos.length > 0 ? perdidos.length : "—"}
          </span>
        </Metrica>
        <Metrica label="Receita Total" icon={Wallet}>
          <span className={`text-lg font-semibold ${receita > 0 ? "text-state-closed" : "text-text-primary"}`}>
            {receita > 0 ? formatBRL(receita) : "—"}
          </span>
        </Metrica>
        <Metrica label="Ticket Médio" icon={TrendingUp}>
          <span className="text-lg font-semibold text-text-primary">
            {ticketMedio > 0 ? formatBRL(ticketMedio) : "—"}
          </span>
        </Metrica>
      </div>

      <div className="border-t border-border">
        <div className="px-5 pt-3 pb-1">
          <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-text-muted">
            Perfil do cliente
          </span>
        </div>
        <div className="divide-y divide-border">
          <div className="grid grid-cols-3 divide-x divide-border">
            <Metrica label="Último fechamento" icon={Clock}>
              {ultimoFechamentoEm ? (
                <span className="text-sm text-text-primary">
                  {formatData(ultimoFechamentoEm)}{" "}
                  <span className="text-text-muted">· {formatTempoRelativo(ultimoFechamentoEm)}</span>
                </span>
              ) : (
                <span className="text-sm text-text-primary">Nenhum</span>
              )}
            </Metrica>
            <Metrica label="Modelo preferida" icon={User}>
              <span className="text-sm text-text-primary">
                {cliente.modelo_preferida?.nome ?? "—"}
              </span>
            </Metrica>
            <Metrica
              label="Preferência de Local"
              icon={MapPin}
              tooltip="Interno: cliente vai à modelo. Externo: modelo vai ao cliente."
            >
              <span className="text-sm text-text-primary">
                {cliente.tipo_atendimento_mais_frequente
                  ? TIPO_LABEL[cliente.tipo_atendimento_mais_frequente]
                  : "—"}
              </span>
            </Metrica>
          </div>
          <div className="grid grid-cols-3 divide-x divide-border">
            <Metrica label="Programa preferido" icon={Package}>
              <span className="text-sm text-text-primary">
                {cliente.programa_preferido?.nome ?? "—"}
              </span>
            </Metrica>
            <Metrica label="Duração preferida" icon={Clock}>
              <span className="text-sm text-text-primary">
                {cliente.duracao_preferida?.nome ?? "—"}
              </span>
            </Metrica>
            <Metrica label="Pagamento preferido" icon={Wallet}>
              <span className="text-sm text-text-primary">
                {cliente.forma_pagamento_preferida
                  ? FORMA_PAGAMENTO_LABEL[cliente.forma_pagamento_preferida]
                  : "—"}
              </span>
            </Metrica>
          </div>
        </div>
      </div>

      <PerfilFisicoSecao
        declarados={cliente.perfis_preferidos}
        calculado={cliente.perfil_calculado}
      />

      {onEditarCliente && modalEditarAberto && (
        <ModalEditarCliente
          key={`${cliente.id}:${cliente.telefone}:${cliente.nome ?? ""}`}
          open={modalEditarAberto}
          clienteId={cliente.id}
          nomeAtual={cliente.nome}
          telefoneAtual={cliente.telefone}
          perfisAtuais={cliente.perfis_preferidos}
          onClose={() => setModalEditarAberto(false)}
          onSalvar={onEditarCliente}
        />
      )}

      {podeArquivar && (
        <AlertDialog open={confirmArquivarAberto} onOpenChange={setConfirmArquivarAberto}>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>
                {arquivado ? "Desarquivar cliente?" : "Arquivar cliente?"}
              </AlertDialogTitle>
              <AlertDialogDescription>
                {arquivado
                  ? "O cliente voltará a aparecer nas listagens padrão."
                  : "Cliente sumirá das listagens; histórico preservado."}
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel disabled={submitting}>Cancelar</AlertDialogCancel>
              <AlertDialogAction
                variant={arquivado ? "primary" : "danger"}
                onClick={handleArquivarOuDesarquivar}
                disabled={submitting}
              >
                {submitting && <Loader2 className="animate-spin" />}
                {arquivado ? "Desarquivar" : "Arquivar"}
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      )}
    </div>
  )
}

function PerfilFisicoSecao({
  declarados,
  calculado,
}: {
  declarados: PerfilFisico[]
  calculado: PerfilCalculado
}) {
  const maxQtd = calculado.breakdown.reduce((acc, b) => Math.max(acc, b.qtd), 0)
  const temCalculo = calculado.breakdown.length > 0 || calculado.nao_classificadas > 0
  return (
    <div className="border-t border-border">
      <div className="px-5 pt-3 pb-1">
        <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-text-muted">
          Perfil físico
        </span>
      </div>
      <div className="grid grid-cols-2 divide-x divide-border">
        <div className="flex flex-col gap-2 px-5 py-4">
          <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-text-muted">
            Declarado
          </span>
          {declarados.length > 0 ? (
            <div className="flex flex-wrap gap-1.5">
              {declarados.map((p) => (
                <span
                  key={p}
                  className="rounded-full border border-border px-2.5 py-0.5 text-xs text-text-primary"
                >
                  {rotuloPerfil(p)}
                </span>
              ))}
            </div>
          ) : (
            <span className="text-sm text-text-muted">Sem preferência declarada</span>
          )}
        </div>
        <div className="flex flex-col gap-2 px-5 py-4">
          <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-text-muted">
            Histórico por tipo · todas as modelos
          </span>
          {temCalculo ? (
            <div className="flex flex-col gap-1.5">
              {calculado.breakdown.map((b) => (
                <BarraTipo key={b.tipo} label={rotuloPerfil(b.tipo)} qtd={b.qtd} max={maxQtd} />
              ))}
              {calculado.nao_classificadas > 0 && (
                <span className="mt-0.5 text-xs text-text-muted">
                  — não classificadas: {calculado.nao_classificadas}
                </span>
              )}
            </div>
          ) : (
            <span className="text-sm text-text-muted">Sem fechados ainda</span>
          )}
        </div>
      </div>
    </div>
  )
}

function BarraTipo({ label, qtd, max }: { label: string; qtd: number; max: number }) {
  const pct = max > 0 ? Math.round((qtd / max) * 100) : 0
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="w-16 shrink-0 text-text-primary">{label}</span>
      <span className="h-2 flex-1 overflow-hidden rounded-full bg-accent">
        <span className="block h-full rounded-full bg-state-active" style={{ width: `${pct}%` }} />
      </span>
      <span className="w-5 shrink-0 text-right tabular-nums text-text-primary">{qtd}</span>
    </div>
  )
}

function Metrica({
  label,
  tooltip,
  icon: Icon,
  children,
}: {
  label: string
  tooltip?: string
  icon?: LucideIcon
  children: React.ReactNode
}) {
  return (
    <div className="flex flex-col gap-1.5 px-5 py-4">
      <span className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.08em] text-text-muted">
        {Icon ? <Icon size={12} strokeWidth={1.75} aria-hidden className="text-text-muted" /> : null}
        {label}
        {tooltip ? (
          <Tooltip>
            <TooltipTrigger
              type="button"
              aria-label={`Sobre ${label}`}
              className="inline-flex items-center text-text-muted/60 transition-colors hover:text-text-primary focus-visible:text-text-primary focus-visible:outline-none"
            >
              <Info size={12} strokeWidth={1.75} aria-hidden />
            </TooltipTrigger>
            <TooltipContent side="top" className="max-w-[260px] text-left leading-snug normal-case tracking-normal">
              {tooltip}
            </TooltipContent>
          </Tooltip>
        ) : null}
      </span>
      {children}
    </div>
  )
}
