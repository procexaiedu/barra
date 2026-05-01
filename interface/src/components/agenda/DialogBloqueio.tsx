import { useMemo, useState } from "react"
import Link from "next/link"
import { Loader2, X } from "lucide-react"
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
import { Button, buttonVariants } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { isoAgenda } from "@/hooks/useAgenda"
import { cn } from "@/lib/utils"
import type { BloqueioAgenda, BloqueioFormState } from "@/tipos/agenda"

const horarios = Array.from({ length: 25 }, (_, h) => `${String(h).padStart(2, "0")}:00`)

function formFromBloqueio(bloqueio: BloqueioAgenda): BloqueioFormState {
  const inicioData = bloqueio.inicio.slice(0, 10)
  const fimData = bloqueio.fim.slice(0, 10)
  const fimHorario = fimData > inicioData && bloqueio.fim.slice(11, 16) === "00:00"
    ? "24:00"
    : bloqueio.fim.slice(11, 16)
  return {
    data: inicioData,
    inicio: bloqueio.inicio.slice(11, 16),
    fim: fimHorario,
    observacao: bloqueio.observacao ?? "",
  }
}

function sobrepoe(aInicio: string, aFim: string, bInicio: string, bFim: string) {
  return new Date(aInicio).getTime() < new Date(bFim).getTime()
    && new Date(aFim).getTime() > new Date(bInicio).getTime()
}

export function DialogBloqueio({
  bloqueio,
  modeloId,
  initial,
  bloqueios,
  onClose,
  onCriar,
  onAtualizar,
  onCancelar,
}: {
  bloqueio: BloqueioAgenda | null
  modeloId: string | null
  initial: BloqueioFormState
  bloqueios: BloqueioAgenda[]
  onClose: () => void
  onCriar: (form: BloqueioFormState) => Promise<void>
  onAtualizar: (id: string, form: BloqueioFormState) => Promise<void>
  onCancelar: (id: string, confirmar: boolean) => Promise<void>
}) {
  const [form, setForm] = useState(() => bloqueio ? formFromBloqueio(bloqueio) : initial)
  const [submitting, setSubmitting] = useState(false)
  const [confirmOpen, setConfirmOpen] = useState(false)

  const readOnly = bloqueio?.estado === "concluido" || bloqueio?.estado === "cancelado"
  const editando = Boolean(bloqueio)
  const intervaloInvalido = form.fim <= form.inicio
  const observacaoInvalida = form.observacao.length > 160
  const inicioIso = isoAgenda(form.data, form.inicio)
  const fimIso = isoAgenda(form.data, form.fim)
  const conflito = useMemo(
    () => bloqueios.some((item) => {
      if (item.id === bloqueio?.id) return false
      if (item.estado !== "bloqueado" && item.estado !== "em_atendimento") return false
      return sobrepoe(inicioIso, fimIso, item.inicio, item.fim)
    }),
    [bloqueio?.id, bloqueios, fimIso, inicioIso]
  )

  const podeSalvar = !readOnly && !intervaloInvalido && !observacaoInvalida && Boolean(modeloId)
  const podeCancelar = bloqueio && bloqueio.estado !== "concluido" && bloqueio.estado !== "cancelado"
  const tituloCancelamento = bloqueio?.estado === "em_atendimento"
    ? "Cancelar bloqueio em atendimento?"
    : "Cancelar bloqueio?"
  const textoCancelamento = bloqueio?.estado === "em_atendimento"
    ? "Este bloqueio já está marcado como Em atendimento. Confirme apenas se o atendimento já terminou."
    : "Este horário ficará liberado na agenda. Se houver atendimento vinculado, confira se ele também precisa ser ajustado nos Atendimentos."

  const submit = async () => {
    if (!podeSalvar) return
    setSubmitting(true)
    try {
      if (bloqueio) await onAtualizar(bloqueio.id, form)
      else await onCriar(form)
    } finally {
      setSubmitting(false)
    }
  }

  const cancelar = async () => {
    if (!bloqueio) return
    setSubmitting(true)
    try {
      await onCancelar(bloqueio.id, bloqueio.estado === "em_atendimento")
      setConfirmOpen(false)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <>
      <div className="fixed inset-0 z-40 bg-background/80" onClick={onClose} />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="dialog-bloqueio-title"
        onKeyDown={(event) => {
          if (event.key === "Escape") onClose()
        }}
        className="fixed top-1/2 left-1/2 z-50 w-full max-w-lg -translate-x-1/2 -translate-y-1/2 rounded-lg border border-border bg-popover p-5 text-popover-foreground"
      >
        <div className="mb-5 flex items-start justify-between gap-4">
          <div>
            <h2 id="dialog-bloqueio-title" className="text-lg font-semibold text-text-primary">
              {editando ? "Editar bloqueio" : "Criar bloqueio"}
            </h2>
            {bloqueio?.atendimento && (
              <p className="mt-1 text-sm text-text-muted">
                Atendimento #{bloqueio.atendimento.numero_curto} · {bloqueio.atendimento.cliente_nome ?? bloqueio.atendimento.cliente_telefone_formatado}
              </p>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1 text-text-muted hover:bg-muted hover:text-text-primary focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:outline-none"
            aria-label="Fechar"
          >
            <X size={18} strokeWidth={1.5} />
          </button>
        </div>

        <div className="grid grid-cols-3 gap-3">
          <div className="col-span-3">
            <Label htmlFor="agenda-data">Data</Label>
            <Input
              id="agenda-data"
              type="date"
              value={form.data}
              disabled={readOnly}
              onChange={(event) => setForm((atual) => ({ ...atual, data: event.target.value }))}
              className="mt-2 h-10"
            />
          </div>
          <CampoHorario
            id="agenda-inicio"
            label="Início"
            value={form.inicio}
            disabled={readOnly}
            onChange={(inicio) => setForm((atual) => ({ ...atual, inicio }))}
          />
          <CampoHorario
            id="agenda-fim"
            label="Fim"
            value={form.fim}
            disabled={readOnly}
            onChange={(fim) => setForm((atual) => ({ ...atual, fim }))}
          />
          <div className="col-span-3">
            <Label htmlFor="agenda-observacao">Observação</Label>
            <textarea
              id="agenda-observacao"
              value={form.observacao}
              maxLength={180}
              disabled={readOnly}
              onChange={(event) => setForm((atual) => ({ ...atual, observacao: event.target.value }))}
              className="mt-2 min-h-24 w-full rounded-lg border border-input bg-input px-3 py-2 text-sm text-text-primary outline-none placeholder:text-text-muted focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:opacity-60"
            />
            <p className={cn("mt-1 text-xs", observacaoInvalida ? "text-state-lost" : "text-text-muted")}>
              {form.observacao.length}/160
            </p>
          </div>
        </div>

        {intervaloInvalido && (
          <p className="mt-3 text-sm text-state-lost">Fim precisa ser maior que início.</p>
        )}
        {conflito && (
          <p className="mt-3 text-sm text-state-handoff">
            Este horário se sobrepõe a outro bloqueio ativo.
          </p>
        )}

        <div className="mt-5 flex items-center justify-between gap-3 border-t border-border pt-4">
          <div>
            {bloqueio?.atendimento_id && (
              <Link
                href={`/atendimentos?selecionado=${bloqueio.atendimento_id}`}
                className={buttonVariants({ variant: "ghost" })}
              >
                Ver atendimento
              </Link>
            )}
          </div>
          <div className="flex items-center gap-2">
            <Button variant="ghost" onClick={onClose} disabled={submitting}>
              Cancelar
            </Button>
            {podeCancelar && (
              <Button variant="danger" onClick={() => setConfirmOpen(true)} disabled={submitting}>
                Cancelar bloqueio
              </Button>
            )}
            {!readOnly && (
              <Button variant="primary" onClick={submit} disabled={!podeSalvar || submitting}>
                {submitting && <Loader2 className="animate-spin" />}
                {editando ? "Salvar" : "Criar bloqueio"}
              </Button>
            )}
          </div>
        </div>
      </div>

      <AlertDialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{tituloCancelamento}</AlertDialogTitle>
            <AlertDialogDescription>{textoCancelamento}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={submitting}>
              {bloqueio?.estado === "em_atendimento" ? "Voltar" : "Cancelar"}
            </AlertDialogCancel>
            <AlertDialogAction
              variant="danger"
              onClick={cancelar}
              disabled={submitting}
            >
              {submitting && <Loader2 className="animate-spin" />}
              {bloqueio?.estado === "em_atendimento" ? "Confirmar cancelamento" : "Cancelar bloqueio"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}

function CampoHorario({
  id,
  label,
  value,
  disabled,
  onChange,
}: {
  id: string
  label: string
  value: string
  disabled: boolean
  onChange: (value: string) => void
}) {
  return (
    <div>
      <Label htmlFor={id}>{label}</Label>
      <select
        id={id}
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
        className="mt-2 h-10 w-full rounded-lg border border-input bg-input px-3 text-sm text-text-primary outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:opacity-60"
      >
        {horarios.map((hora) => (
          <option key={hora} value={hora}>
            {hora}
          </option>
        ))}
      </select>
    </div>
  )
}
