"use client"

import { useState } from "react"
import { toast } from "sonner"
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import type { AtendimentoDetalheResponse, EditarDadosPayload } from "@/tipos/atendimentos"

function parseDecimal(input: string): number | null {
  const normalizado = input.replace(/\s/g, "").replace(/\./g, "").replace(",", ".")
  const valor = Number(normalizado)
  return Number.isFinite(valor) && valor >= 0 ? valor : null
}

const controlClassName =
  "h-10 w-full rounded-lg border border-border-strong bg-surface-hover px-3 text-sm text-text-primary outline-none transition-colors placeholder:text-text-muted hover:bg-surface-pressed focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/60 disabled:cursor-not-allowed disabled:opacity-50"

export function ModalEdicao({
  detalhe,
  onClose,
  onSalvar,
}: {
  detalhe: AtendimentoDetalheResponse | null
  onClose: () => void
  onSalvar: (id: string, dados: EditarDadosPayload) => Promise<void>
}) {
  const at = detalhe?.atendimento
  const [submitting, setSubmitting] = useState(false)

  const [tipo, setTipo] = useState(at?.tipo_atendimento ?? "")
  const [urgencia, setUrgencia] = useState(at?.urgencia ?? "")
  const [dataDesejada, setDataDesejada] = useState(at?.data_desejada ?? "")
  const [horario, setHorario] = useState(at?.horario_desejado ? String(at.horario_desejado).slice(0, 5) : "")
  const [duracao, setDuracao] = useState(at?.duracao_horas != null ? String(at.duracao_horas) : "")
  const [endereco, setEndereco] = useState(at?.endereco ?? "")
  const [bairro, setBairro] = useState(at?.bairro ?? "")
  const [tipoLocal, setTipoLocal] = useState(at?.tipo_local ?? "")
  const [formaPagamento, setFormaPagamento] = useState(at?.forma_pagamento ?? "")
  const [valorAcordado, setValorAcordado] = useState(at?.valor_acordado != null ? String(at.valor_acordado) : "")

  if (!detalhe || !at) return null

  const handleSalvar = async () => {
    const dados: EditarDadosPayload = {}
    if (tipo) dados.tipo_atendimento = tipo as "interno" | "externo"
    if (urgencia) dados.urgencia = urgencia as EditarDadosPayload["urgencia"]
    if (dataDesejada) dados.data_desejada = dataDesejada
    if (horario) dados.horario_desejado = horario
    if (duracao) {
      const d = parseDecimal(duracao)
      if (d !== null) dados.duracao_horas = d
    }
    if (endereco) dados.endereco = endereco
    if (bairro) dados.bairro = bairro
    if (tipoLocal) dados.tipo_local = tipoLocal
    if (formaPagamento) dados.forma_pagamento = formaPagamento
    if (valorAcordado) {
      const v = parseDecimal(valorAcordado)
      if (v !== null) dados.valor_acordado = v
    }

    setSubmitting(true)
    try {
      await onSalvar(at.id, dados)
      toast.success(`Atendimento #${at.numero_curto} atualizado`)
      onClose()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Erro ao salvar")
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Dialog open={!!detalhe} onOpenChange={(open) => { if (!open) onClose() }}>
      <DialogContent className="flex max-h-[90vh] w-[min(calc(100vw-32px),640px)] max-w-none flex-col overflow-hidden rounded-xl border border-border-strong bg-surface-raised p-0 shadow-[0_16px_48px_rgba(0,0,0,0.7)]">
        <div className="border-b border-border-subtle px-5 py-4">
          <DialogTitle className="text-base font-semibold leading-6 text-text-primary">
            Editar #{at.numero_curto}
          </DialogTitle>
          <DialogDescription className="mt-1 text-xs text-text-muted">
            Ajuste os dados operacionais do atendimento.
          </DialogDescription>
        </div>

        <div className="scroll-thin grid gap-4 overflow-y-auto px-5 py-4">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <Campo label="Tipo de atendimento">
              <select
                value={tipo}
                onChange={(e) => setTipo(e.target.value)}
                className={controlClassName}
              >
                <option value="">—</option>
                <option value="interno">No local da modelo</option>
                <option value="externo">No local do cliente</option>
              </select>
            </Campo>

            <Campo label="Urgência">
              <select
                value={urgencia}
                onChange={(e) => setUrgencia(e.target.value)}
                className={controlClassName}
              >
                <option value="">—</option>
                <option value="imediato">Agora</option>
                <option value="agendado">Marcado</option>
                <option value="indefinido">Indefinido</option>
                <option value="estimado">Estimado</option>
              </select>
            </Campo>
          </div>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <Campo label="Data desejada">
              <Input className={controlClassName} type="date" value={dataDesejada} onChange={(e) => setDataDesejada(e.target.value)} />
            </Campo>
            <Campo label="Horário">
              <Input className={controlClassName} type="time" value={horario} onChange={(e) => setHorario(e.target.value)} />
            </Campo>
            <Campo label="Duração (h)">
              <Input className={controlClassName} inputMode="decimal" placeholder="2" value={duracao} onChange={(e) => setDuracao(e.target.value)} />
            </Campo>
          </div>

          <Campo label="Endereço">
            <Input className={controlClassName} placeholder="Rua, número" value={endereco} onChange={(e) => setEndereco(e.target.value)} />
          </Campo>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <Campo label="Bairro">
              <Input className={controlClassName} placeholder="Bairro" value={bairro} onChange={(e) => setBairro(e.target.value)} />
            </Campo>
            <Campo label="Tipo de local">
              <Input className={controlClassName} placeholder="apartamento, casa…" value={tipoLocal} onChange={(e) => setTipoLocal(e.target.value)} />
            </Campo>
          </div>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <Campo label="Forma de pagamento">
              <Input className={controlClassName} placeholder="pix, dinheiro…" value={formaPagamento} onChange={(e) => setFormaPagamento(e.target.value)} />
            </Campo>
            <Campo label="Valor acordado (R$)">
              <Input className={controlClassName} inputMode="decimal" placeholder="1.200,00" value={valorAcordado} onChange={(e) => setValorAcordado(e.target.value)} />
            </Campo>
          </div>
        </div>

        <div className="flex justify-end gap-2 border-t border-border-subtle bg-surface px-5 py-3">
          <Button variant="secondary" onClick={onClose} disabled={submitting}>Cancelar</Button>
          <Button variant="primary" onClick={handleSalvar} disabled={submitting}>
            {submitting ? "Salvando…" : "Salvar"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}

function Campo({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <Label className="text-[11px] font-medium leading-4 text-text-muted">{label}</Label>
      {children}
    </div>
  )
}
