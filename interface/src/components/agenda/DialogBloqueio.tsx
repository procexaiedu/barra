"use client"

import { useCallback, useMemo, useRef, useState } from "react"
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
import { Badge } from "@/components/ui/badge"
import { Button, buttonVariants } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { dataDeInput, dataInput, isoAgenda } from "@/hooks/useAgenda"
import { api } from "@/lib/api"
import { formatBRL, formatData, formatRotulo } from "@/lib/formatters"
import { cn } from "@/lib/utils"
import type { AtendimentoListaItem, AtendimentosListaResponse } from "@/tipos/atendimentos"
import type { BloqueioAgenda, BloqueioFormState, EstadoBloqueio } from "@/tipos/agenda"
import { FiltroModelo } from "@/components/dashboard/FiltroModelo"
import { toast } from "sonner"

const MOTIVOS_PERDA = ["preco", "sumiu", "risco", "indisponibilidade", "fora_de_area", "outro"] as const

const estadoBadgeVariant: Record<EstadoBloqueio, "active" | "paused" | "closed" | "lost"> = {
  bloqueado: "paused",
  em_atendimento: "active",
  concluido: "closed",
  cancelado: "paused",
}

const estadoLabel: Record<EstadoBloqueio, string> = {
  bloqueado: "Bloqueado",
  em_atendimento: "Em atendimento",
  concluido: "Concluído",
  cancelado: "Cancelado",
}

function parseDecimal(input: string): number | null {
  const normalizado = input.replace(/\s/g, "").replace(/\./g, "").replace(",", ".")
  const valor = Number(normalizado)
  return Number.isFinite(valor) && valor >= 0 ? valor : null
}

function formatValor(v: string | number | null | undefined): string {
  if (v == null || v === "") return "—"
  const n = typeof v === "string" ? parseFloat(v) : v
  return isNaN(n) ? "—" : formatBRL(n)
}

const horarios = [
  ...Array.from({ length: 48 }, (_, i) => {
    const h = Math.floor(i / 2)
    const m = i % 2 === 0 ? "00" : "30"
    return `${String(h).padStart(2, "0")}:${m}`
  }),
  "24:00",
]

function calcDuracao(inicio: string, fim: string): string | null {
  const [h1, m1] = inicio.split(":").map(Number)
  const [h2, m2] = fim === "24:00" ? [24, 0] : fim.split(":").map(Number)
  let totalMin = h2 * 60 + m2 - (h1 * 60 + m1)
  if (totalMin === 0) return null
  if (totalMin < 0) totalMin += 24 * 60
  const horas = Math.floor(totalMin / 60)
  const mins = totalMin % 60
  if (mins === 0) return `${horas}h`
  return `${horas}h${String(mins).padStart(2, "0")}`
}

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

  const [tipo, setTipo] = useState<"agendamento" | "bloqueio">(
    bloqueio?.atendimento_id ? "agendamento" : "bloqueio"
  )

  const [busca, setBusca] = useState("")
  const [resultadosBusca, setResultadosBusca] = useState<AtendimentoListaItem[]>([])
  const [buscaAberta, setBuscaAberta] = useState(false)
  const [buscando, setBuscando] = useState(false)
  const [atendimentoSelecionado, setAtendimentoSelecionado] = useState<AtendimentoListaItem | null>(null)
  const buscaTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const formRef = useRef(form)
  formRef.current = form

  const [confirmConverterOpen, setConfirmConverterOpen] = useState(false)
  const [confirmPerderOpen, setConfirmPerderOpen] = useState(false)
  const [valorFinal, setValorFinal] = useState("")
  const [motivo, setMotivo] = useState<string>(MOTIVOS_PERDA[0])
  const [observacaoPerda, setObservacaoPerda] = useState("")
  const [submittingConverter, setSubmittingConverter] = useState(false)
  const [submittingPerder, setSubmittingPerder] = useState(false)

  const readOnly = bloqueio?.estado === "concluido" || bloqueio?.estado === "cancelado"
  const editando = Boolean(bloqueio)
  const intervaloInvalido = form.fim === form.inicio
  const observacaoInvalida = form.observacao.length > 160
  const inicioIso = isoAgenda(form.data, form.inicio)
  const overnight = form.fim !== "24:00" && form.fim < form.inicio
  const fimIso = (() => {
    if (!overnight) return isoAgenda(form.data, form.fim)
    const d = dataDeInput(form.data)
    d.setDate(d.getDate() + 1)
    return isoAgenda(dataInput(d), form.fim)
  })()
  const conflito = useMemo(
    () => bloqueios.some((item) => {
      if (item.id === bloqueio?.id) return false
      if (item.estado !== "bloqueado" && item.estado !== "em_atendimento") return false
      return sobrepoe(inicioIso, fimIso, item.inicio, item.fim)
    }),
    [bloqueio?.id, bloqueios, fimIso, inicioIso]
  )

  const temModelo = Boolean(modeloId) || Boolean(form.modelo_id)
  const podeSalvar = !readOnly && !intervaloInvalido && !observacaoInvalida && temModelo
  const podeCancelar = bloqueio && bloqueio.estado !== "concluido" && bloqueio.estado !== "cancelado"
  const tituloCancelamento = bloqueio?.estado === "em_atendimento"
    ? "Cancelar bloqueio em atendimento?"
    : "Cancelar bloqueio?"
  const textoCancelamento = bloqueio?.estado === "em_atendimento"
    ? "Este bloqueio já está marcado como Em atendimento. Confirme apenas se o atendimento já terminou."
    : "Este horário ficará liberado na agenda. Se houver atendimento vinculado, confira se ele também precisa ser ajustado nos Atendimentos."

  const mostraAcoesAtendimento =
    editando &&
    Boolean(bloqueio?.atendimento_id) &&
    bloqueio?.estado === "em_atendimento"

  const atendimentoDisplay = editando
    ? bloqueio?.atendimento
    : atendimentoSelecionado
      ? {
          numero_curto: atendimentoSelecionado.numero_curto,
          cliente_nome: atendimentoSelecionado.cliente.nome,
          cliente_telefone_formatado: atendimentoSelecionado.cliente.telefone,
          estado: atendimentoSelecionado.estado,
          tipo_atendimento: atendimentoSelecionado.tipo_atendimento as string | null,
          valor_acordado: atendimentoSelecionado.valor_acordado as string | number | null,
          endereco: null as string | null,
          bairro: null as string | null,
          data_desejada: null as string | null,
          horario_desejado: null as string | null,
        }
      : null

  const buscarAtendimentos = useCallback(async (texto: string) => {
    if (!texto.trim()) {
      setResultadosBusca([])
      setBuscaAberta(false)
      return
    }
    setBuscando(true)
    try {
      const modeloIdBusca = modeloId ?? formRef.current.modelo_id
      const searchParams: Record<string, string> = { q: texto }
      if (modeloIdBusca) searchParams.modelo_id = modeloIdBusca
      const params = new URLSearchParams(searchParams)
      const res = await api<AtendimentosListaResponse>(`/v1/atendimentos/?${params}`)
      setResultadosBusca(res.items.slice(0, 5))
      setBuscaAberta(true)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Erro ao buscar atendimentos")
      setBuscaAberta(false)
    } finally {
      setBuscando(false)
    }
  }, [modeloId])

  const handleBuscaChange = (texto: string) => {
    setBusca(texto)
    if (buscaTimer.current) clearTimeout(buscaTimer.current)
    buscaTimer.current = setTimeout(() => buscarAtendimentos(texto), 400)
  }

  const selecionarAtendimento = (item: AtendimentoListaItem) => {
    setAtendimentoSelecionado(item)
    setBusca(`#${item.numero_curto} · ${item.cliente.nome ?? item.cliente.telefone}`)
    setResultadosBusca([])
    setBuscaAberta(false)
    setForm((f) => ({ ...f, atendimento_id: item.id }))
  }

  const limparAtendimento = () => {
    setAtendimentoSelecionado(null)
    setBusca("")
    setResultadosBusca([])
    setBuscaAberta(false)
    setForm((f) => ({ ...f, atendimento_id: undefined }))
  }

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

  const converter = async () => {
    const valor = parseDecimal(valorFinal)
    if (valor === null || !bloqueio?.atendimento_id) return
    setSubmittingConverter(true)
    try {
      await api(`/v1/atendimentos/${bloqueio.atendimento_id}/fechar`, {
        method: "POST",
        body: JSON.stringify({ valor_final: valor }),
      })
      toast.success("Atendimento convertido com sucesso")
      setConfirmConverterOpen(false)
      onClose()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Erro ao converter")
    } finally {
      setSubmittingConverter(false)
    }
  }

  const perder = async () => {
    if (!motivo || !bloqueio?.atendimento_id) return
    if (motivo === "outro" && !observacaoPerda.trim()) return
    setSubmittingPerder(true)
    try {
      await api(`/v1/atendimentos/${bloqueio.atendimento_id}/perder`, {
        method: "POST",
        body: JSON.stringify({ motivo, observacao: observacaoPerda.trim() || null }),
      })
      toast.success("Perda registrada")
      setConfirmPerderOpen(false)
      onClose()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Erro ao registrar perda")
    } finally {
      setSubmittingPerder(false)
    }
  }

  const titulo = editando
    ? bloqueio?.atendimento_id ? "Editar agendamento" : "Editar bloqueio"
    : tipo === "agendamento" ? "Criar agendamento" : "Criar bloqueio"

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
        className="fixed top-1/2 left-1/2 z-50 flex w-full max-w-2xl -translate-x-1/2 -translate-y-1/2 flex-col max-h-[90vh] rounded-lg border border-border bg-popover text-popover-foreground shadow-[0_16px_48px_rgba(0,0,0,0.7)]"
      >
        {/* Header */}
        <div className="flex flex-shrink-0 items-start justify-between gap-4 border-b border-border px-5 py-4">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2.5">
              <h2 id="dialog-bloqueio-title" className="text-lg font-semibold leading-tight text-text-primary">
                {titulo}
              </h2>
              {editando && bloqueio && (
                <Badge variant={estadoBadgeVariant[bloqueio.estado]}>
                  {estadoLabel[bloqueio.estado]}
                </Badge>
              )}
            </div>
            {bloqueio?.modelo_nome && (
              <p className="mt-1 text-sm font-medium text-text-secondary">
                {bloqueio.modelo_nome}
              </p>
            )}
            {bloqueio?.atendimento && (
              <p className="mt-0.5 font-mono text-xs text-text-muted">
                #{bloqueio.atendimento.numero_curto} · {bloqueio.atendimento.cliente_nome ?? bloqueio.atendimento.cliente_telefone_formatado}
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

        {/* Scrollable body */}
        <div className="flex-1 overflow-y-auto px-5 py-4">
          <div className="grid grid-cols-3 gap-3">

            {/* Tipo: só na criação */}
            {!editando && (
              <div className="col-span-3">
                <Label>Tipo</Label>
                <div className="mt-2 flex gap-2">
                  <button
                    type="button"
                    onClick={() => { setTipo("bloqueio"); limparAtendimento() }}
                    className={cn(
                      "rounded-md border px-3 py-1.5 text-sm font-medium transition-colors",
                      tipo === "bloqueio"
                        ? "border-gold-500 bg-ink-200 text-text-primary"
                        : "border-ink-400 text-text-muted hover:border-ink-500 hover:text-text-secondary"
                    )}
                  >
                    Bloqueio
                  </button>
                  <button
                    type="button"
                    onClick={() => setTipo("agendamento")}
                    className={cn(
                      "rounded-md border px-3 py-1.5 text-sm font-medium transition-colors",
                      tipo === "agendamento"
                        ? "border-gold-500 bg-ink-200 text-text-primary"
                        : "border-ink-400 text-text-muted hover:border-ink-500 hover:text-text-secondary"
                    )}
                  >
                    Agendamento
                  </button>
                </div>
              </div>
            )}

            {/* Seleção de modelo: só na criação sem modeloId fixo */}
            {!editando && !modeloId && (
              <div className="col-span-3 pb-1">
                <Label htmlFor="agenda-modelo">Modelo</Label>
                <div className="mt-2 w-full max-w-xs">
                  <FiltroModelo
                    modeloId={form.modelo_id ?? null}
                    onChange={(val) => setForm(f => ({ ...f, modelo_id: val ?? undefined }))}
                    hideTodas
                  />
                </div>
              </div>
            )}

            {/* Busca de atendimento: só na criação de agendamento */}
            {!editando && tipo === "agendamento" && (
              <div className="relative col-span-3">
                <Label htmlFor="busca-atendimento">Atendimento</Label>
                <div className="relative mt-2">
                  <Input
                    id="busca-atendimento"
                    value={busca}
                    onChange={(e) => handleBuscaChange(e.target.value)}
                    placeholder="Nome, número ou #ID do atendimento..."
                    className="h-10 border-ink-400 pr-8"
                    autoComplete="off"
                  />
                  {buscando && (
                    <Loader2 size={14} className="absolute right-2.5 top-1/2 -translate-y-1/2 animate-spin text-text-muted" />
                  )}
                  {busca && !buscando && (
                    <button
                      type="button"
                      onClick={limparAtendimento}
                      className="absolute right-2 top-1/2 -translate-y-1/2 text-text-muted hover:text-text-primary"
                      aria-label="Limpar seleção"
                    >
                      <X size={14} />
                    </button>
                  )}
                </div>
                {buscaAberta && resultadosBusca.length > 0 && (
                  <div className="absolute z-[60] mt-1 w-full overflow-hidden rounded-lg border border-ink-400 bg-popover shadow-[0_8px_24px_rgba(0,0,0,0.6)]">
                    {resultadosBusca.map((item) => (
                      <button
                        key={item.id}
                        type="button"
                        onClick={() => selecionarAtendimento(item)}
                        className="flex w-full items-center gap-3 px-3 py-2.5 text-left text-sm hover:bg-ink-200 border-b border-border last:border-0"
                      >
                        <span className="font-mono text-xs text-text-muted">#{item.numero_curto}</span>
                        <span className="flex-1 truncate font-medium text-text-primary">
                          {item.cliente.nome ?? item.cliente.telefone}
                        </span>
                        <div className="flex items-center gap-1.5 shrink-0">
                          {item.tipo_atendimento && (
                            <span className="rounded-full bg-ink-300 px-1.5 py-0.5 text-xs text-text-muted">
                              {item.tipo_atendimento === "interno" ? "Int" : "Ext"}
                            </span>
                          )}
                          <span className="text-xs text-text-muted">{formatRotulo(item.estado)}</span>
                        </div>
                      </button>
                    ))}
                  </div>
                )}
                {buscaAberta && resultadosBusca.length === 0 && !buscando && busca.trim() && (
                  <p className="mt-1 text-xs text-text-muted">Nenhum atendimento encontrado.</p>
                )}
              </div>
            )}

            {/* Card de info do atendimento vinculado */}
            {atendimentoDisplay && (
              <div className="col-span-3 overflow-hidden rounded-lg border border-border bg-surface-raised">
                <div className="flex items-center gap-3 border-b border-border px-3 py-2.5">
                  <span className="font-mono text-xs text-text-muted">
                    #{atendimentoDisplay.numero_curto}
                  </span>
                  <span className="text-sm font-semibold text-text-primary">
                    {atendimentoDisplay.cliente_nome ?? atendimentoDisplay.cliente_telefone_formatado}
                  </span>
                  <div className="ml-auto flex items-center gap-2 shrink-0">
                    {atendimentoDisplay.tipo_atendimento && (
                      <span className="rounded-full bg-ink-300 px-2 py-0.5 text-xs font-medium text-text-secondary">
                        {atendimentoDisplay.tipo_atendimento === "interno" ? "Interno" : "Externo"}
                      </span>
                    )}
                    <span className="text-xs text-text-muted">{formatRotulo(atendimentoDisplay.estado)}</span>
                  </div>
                </div>
                <div className="space-y-1.5 px-3 py-3 text-sm">
                  <div className="flex items-baseline justify-between gap-4">
                    <span className="shrink-0 text-text-muted">Valor acordado</span>
                    <span className="font-medium text-text-primary">
                      {formatValor(atendimentoDisplay.valor_acordado)}
                    </span>
                  </div>
                  <div className="flex items-baseline justify-between gap-4">
                    <span className="shrink-0 text-text-muted">Horário desejado</span>
                    <span className="text-text-primary">
                      {atendimentoDisplay.data_desejada && atendimentoDisplay.horario_desejado
                        ? `${formatData(atendimentoDisplay.data_desejada)} · ${String(atendimentoDisplay.horario_desejado).slice(0, 5)}`
                        : "—"}
                    </span>
                  </div>
                  <div className="flex items-baseline justify-between gap-4">
                    <span className="shrink-0 text-text-muted">Local</span>
                    <span className="text-right text-text-primary">
                      {[atendimentoDisplay.endereco, atendimentoDisplay.bairro].filter(Boolean).join(", ") || "—"}
                    </span>
                  </div>
                </div>
              </div>
            )}

            {/* Seção: Horário */}
            <div className="col-span-3 border-t border-border pt-4">
              <p className="mb-3 text-xs font-semibold uppercase tracking-wider text-text-muted">
                Horário
              </p>
            </div>

            <div className="col-span-3">
              <Label htmlFor="agenda-data">Data</Label>
              <Input
                id="agenda-data"
                type="date"
                value={form.data}
                disabled={readOnly}
                onChange={(event) => setForm((atual) => ({ ...atual, data: event.target.value }))}
                className="mt-2 h-10 border-ink-400"
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
            <div>
              <Label>Duração</Label>
              <div className="mt-2 flex h-10 items-center text-sm text-text-muted">
                {calcDuracao(form.inicio, form.fim) ?? "—"}
              </div>
            </div>

            {/* Seção: Observação */}
            <div className="col-span-3 border-t border-border pt-4">
              <Label htmlFor="agenda-observacao">Observação</Label>
              <textarea
                id="agenda-observacao"
                value={form.observacao}
                maxLength={180}
                disabled={readOnly}
                onChange={(event) => setForm((atual) => ({ ...atual, observacao: event.target.value }))}
                className="mt-2 min-h-20 w-full rounded-lg border border-ink-400 bg-input px-3 py-2 text-sm text-text-primary outline-none placeholder:text-text-muted focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:opacity-60"
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
        </div>

        {/* Footer */}
        <div className="flex flex-shrink-0 items-center justify-between gap-3 border-t border-border px-5 py-4">
          <div className="flex items-center gap-2">
            {bloqueio?.atendimento_id && (
              <Link
                href={`/atendimentos?id=${bloqueio.atendimento_id}`}
                className={buttonVariants({ variant: "ghost" })}
              >
                Ver atendimento
              </Link>
            )}
            {mostraAcoesAtendimento && (
              <>
                <Button variant="ghost" onClick={() => setConfirmConverterOpen(true)} disabled={submitting}>
                  Converter
                </Button>
                <Button variant="danger" onClick={() => setConfirmPerderOpen(true)} disabled={submitting}>
                  Perder
                </Button>
              </>
            )}
          </div>
          <div className="flex items-center gap-2">
            {podeCancelar && (
              <Button variant="danger" onClick={() => setConfirmOpen(true)} disabled={submitting}>
                Cancelar bloqueio
              </Button>
            )}
            {!readOnly && (
              <Button variant="primary" onClick={submit} disabled={!podeSalvar || submitting}>
                {submitting && <Loader2 className="animate-spin" />}
                {editando ? "Salvar" : tipo === "agendamento" ? "Criar agendamento" : "Criar bloqueio"}
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

      <AlertDialog open={confirmConverterOpen} onOpenChange={setConfirmConverterOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Converter atendimento</AlertDialogTitle>
            <AlertDialogDescription>
              Registre o valor final para marcar o atendimento como fechado.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <div className="px-6 pb-2">
            <Label htmlFor="valor-final">Valor final (R$)</Label>
            <Input
              id="valor-final"
              value={valorFinal}
              onChange={(e) => setValorFinal(e.target.value)}
              placeholder="0,00"
              className="mt-2 h-10"
              disabled={submittingConverter}
            />
          </div>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={submittingConverter}>Cancelar</AlertDialogCancel>
            <AlertDialogAction
              onClick={converter}
              disabled={submittingConverter || parseDecimal(valorFinal) === null}
            >
              {submittingConverter && <Loader2 className="animate-spin" />}
              Confirmar
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={confirmPerderOpen} onOpenChange={setConfirmPerderOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Registrar perda</AlertDialogTitle>
            <AlertDialogDescription>
              Informe o motivo para registrar o atendimento como perdido.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <div className="space-y-3 px-6 pb-2">
            <div>
              <Label htmlFor="motivo-perda">Motivo</Label>
              <select
                id="motivo-perda"
                value={motivo}
                onChange={(e) => setMotivo(e.target.value)}
                disabled={submittingPerder}
                className="mt-2 h-10 w-full rounded-lg border border-ink-400 bg-input px-3 text-sm text-text-primary outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:opacity-60"
              >
                {MOTIVOS_PERDA.map((m) => (
                  <option key={m} value={m}>{formatRotulo(m)}</option>
                ))}
              </select>
            </div>
            {motivo === "outro" && (
              <div>
                <Label htmlFor="obs-perda">
                  Observação <span className="text-state-lost">*</span>
                </Label>
                <Input
                  id="obs-perda"
                  value={observacaoPerda}
                  onChange={(e) => setObservacaoPerda(e.target.value)}
                  placeholder="Descreva o motivo..."
                  className="mt-2 h-10"
                  disabled={submittingPerder}
                />
              </div>
            )}
          </div>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={submittingPerder}>Cancelar</AlertDialogCancel>
            <AlertDialogAction
              variant="danger"
              onClick={perder}
              disabled={submittingPerder || (motivo === "outro" && !observacaoPerda.trim())}
            >
              {submittingPerder && <Loader2 className="animate-spin" />}
              Registrar perda
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
        className="mt-2 h-10 w-full rounded-lg border border-ink-400 bg-input px-3 text-sm text-text-primary outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:opacity-60"
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
