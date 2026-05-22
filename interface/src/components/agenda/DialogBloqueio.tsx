"use client"

import { useCallback, useMemo, useRef, useState } from "react"
import { ArrowLeft, Loader2, Plus, X } from "lucide-react"
import {
  FormularioCamposAtendimento,
  type FormularioCamposAtendimentoRef,
} from "@/components/atendimentos/FormularioCamposAtendimento"
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
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { dataDeInput, dataInput, isoAgenda } from "@/hooks/useAgenda"
import { ApiError, api } from "@/lib/api"
import { formatBRL, formatData, formatRotulo, formatTelefone } from "@/lib/formatters"
import { cn } from "@/lib/utils"
import { aplicarMascaraTelefone, normalizarTelefoneE164 } from "@/components/clientes/utils"
import type {
  AtendimentoCriadoResponse,
  AtendimentoListaItem,
  AtendimentosListaResponse,
} from "@/tipos/atendimentos"
import type { Cliente, ClienteListItem, ClientesListaResponse } from "@/tipos/clientes"
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

const DURACOES = [
  { min: 30, label: "30min" },
  { min: 60, label: "1h" },
  { min: 90, label: "1h30" },
  { min: 120, label: "2h" },
  { min: 150, label: "2h30" },
  { min: 180, label: "3h" },
  { min: 210, label: "3h30" },
  { min: 240, label: "4h" },
  { min: 270, label: "4h30" },
  { min: 300, label: "5h" },
  { min: 360, label: "6h" },
]

function duracaoLabel(min: number): string {
  const h = Math.floor(min / 60)
  const m = min % 60
  return m === 0 ? `${h}h` : `${h}h${String(m).padStart(2, "0")}`
}

function calcDuracaoMin(inicio: string, fim: string): number {
  const [h1, m1] = inicio.split(":").map(Number)
  const [h2, m2] = fim === "24:00" ? [24, 0] : fim.split(":").map(Number)
  let total = h2 * 60 + m2 - (h1 * 60 + m1)
  if (total <= 0) total += 24 * 60
  return total
}

function calcFimDeDuracao(inicio: string, min: number): string {
  const [h, m] = inicio.split(":").map(Number)
  const totalMin = h * 60 + m + min
  if (totalMin >= 24 * 60) {
    const over = totalMin - 24 * 60
    if (over === 0) return "24:00"
    return `${String(Math.floor(over / 60)).padStart(2, "0")}:${String(over % 60).padStart(2, "0")}`
  }
  return `${String(Math.floor(totalMin / 60)).padStart(2, "0")}:${String(totalMin % 60).padStart(2, "0")}`
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

function formFromBloqueio(bloqueio: BloqueioAgenda): BloqueioFormState {
  const inicioData = bloqueio.inicio.slice(0, 10)
  const fimData = bloqueio.fim.slice(0, 10)
  const fimHorario = fimData > inicioData && bloqueio.fim.slice(11, 16) === "00:00"
    ? "24:00"
    : bloqueio.fim.slice(11, 16)
  return {
    modelo_id: bloqueio.modelo_id,
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
  onVerAtendimento,
}: {
  bloqueio: BloqueioAgenda | null
  modeloId: string | null
  initial: BloqueioFormState
  bloqueios: BloqueioAgenda[]
  onClose: () => void
  onCriar: (form: BloqueioFormState) => Promise<void>
  onAtualizar: (id: string, form: BloqueioFormState, atendimentoId?: string | null) => Promise<void>
  onCancelar: (id: string, confirmar: boolean) => Promise<void>
  onVerAtendimento: (atendimentoId: string) => void
}) {
  const [form, setForm] = useState(() => bloqueio ? formFromBloqueio(bloqueio) : initial)
  const [submitting, setSubmitting] = useState(false)
  const [confirmOpen, setConfirmOpen] = useState(false)

  const [tipo, setTipo] = useState<"agendamento" | "bloqueio">(
    bloqueio?.atendimento_id ? "agendamento" : "bloqueio"
  )

  const [duracaoMin, setDuracaoMin] = useState(() => {
    const f = bloqueio ? formFromBloqueio(bloqueio) : initial
    return calcDuracaoMin(f.inicio, f.fim)
  })

  // null = sem mudança, { id: string } = novo, { id: null } = desvinculado
  const [atendimentoEdit, setAtendimentoEdit] = useState<{ id: string | null } | null>(null)

  const [busca, setBusca] = useState("")
  const [resultadosBusca, setResultadosBusca] = useState<AtendimentoListaItem[]>([])
  const [buscaAberta, setBuscaAberta] = useState(false)
  const [buscando, setBuscando] = useState(false)
  const [atendimentoSelecionado, setAtendimentoSelecionado] = useState<AtendimentoListaItem | null>(null)
  const buscaTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Criação rápida de atendimento dentro do dialog
  const [criandoAtendimento, setCriandoAtendimento] = useState(false)
  const [buscaCliente, setBuscaCliente] = useState("")
  const [resultadosCliente, setResultadosCliente] = useState<ClienteListItem[]>([])
  const [buscandoCliente, setBuscandoCliente] = useState(false)
  const [clienteSelecionado, setClienteSelecionado] = useState<ClienteListItem | Cliente | null>(null)
  const buscaClienteTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const [criandoClienteRapido, setCriandoClienteRapido] = useState(false)
  const [novoClienteNome, setNovoClienteNome] = useState("")
  const [novoClienteTelefone, setNovoClienteTelefone] = useState("")
  const [submittingCliente, setSubmittingCliente] = useState(false)
  const [submittingNovoAtendimento, setSubmittingNovoAtendimento] = useState(false)
  const camposAtendRef = useRef<FormularioCamposAtendimentoRef>(null)

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

  // Fonte única de verdade do modelo_id, na ordem de prioridade: modelo escolhida
  // no form (seletor do dialog) > modelo herdada do contexto da agenda (prop).
  // Tudo que depende do modelo (sub-form de programas, criação de atendimento,
  // POST) deve usar este valor para nunca divergir do que está visível na UI.
  const modeloIdEfetivo = form.modelo_id ?? modeloId ?? null
  const temModelo = Boolean(modeloIdEfetivo)
  const podeSalvar = !readOnly && !intervaloInvalido && !observacaoInvalida && temModelo
  const podeCancelar = bloqueio && bloqueio.estado !== "concluido" && bloqueio.estado !== "cancelado"
  const ehAgendamento = Boolean(bloqueio?.atendimento_id)
  const acaoLabel = ehAgendamento ? "Deletar agendamento" : "Cancelar bloqueio"
  const tituloCancelamento = bloqueio?.estado === "em_atendimento"
    ? `${acaoLabel} em atendimento?`
    : `${acaoLabel}?`
  const textoCancelamento = bloqueio?.estado === "em_atendimento"
    ? `Este ${ehAgendamento ? "agendamento" : "bloqueio"} já está marcado como Em atendimento. Confirme apenas se o atendimento já terminou.`
    : ehAgendamento
      ? "Este agendamento ficará marcado como cancelado e liberará o horário."
      : "Este horário ficará liberado na agenda. Se houver atendimento vinculado, confira se ele também precisa ser ajustado nos Atendimentos."

  const mostraAcoesAtendimento =
    editando &&
    Boolean(bloqueio?.atendimento_id) &&
    bloqueio?.estado === "em_atendimento"

  // Resolve o atendimento a exibir no card
  const atendimentoDisplay = (() => {
    if (editando) {
      if (atendimentoEdit === null) return bloqueio?.atendimento ?? null
      if (atendimentoEdit.id === null) return null
      if (!atendimentoSelecionado) return null
      return {
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
        programa_principal_nome: null as string | null,
      }
    }
    if (!atendimentoSelecionado) return null
    return {
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
      programa_principal_nome: null as string | null,
    }
  })()

  const modeloIdForm = form.modelo_id
  const buscarAtendimentos = useCallback(async (texto: string) => {
    if (!texto.trim()) {
      setResultadosBusca([])
      setBuscaAberta(false)
      return
    }
    setBuscando(true)
    try {
      const modeloIdBusca = modeloIdForm ?? modeloId
      const searchParams: Record<string, string> = { q: texto }
      if (modeloIdBusca) searchParams.modelo_id = modeloIdBusca
      const params = new URLSearchParams(searchParams)
      const res = await api<AtendimentosListaResponse>(`/v1/atendimentos?${params}`)
      setResultadosBusca(res.items.slice(0, 5))
      setBuscaAberta(true)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Erro ao buscar atendimentos")
      setBuscaAberta(false)
    } finally {
      setBuscando(false)
    }
  }, [modeloId, modeloIdForm])

  const handleBuscaChange = (texto: string) => {
    setBusca(texto)
    if (buscaTimer.current) clearTimeout(buscaTimer.current)
    buscaTimer.current = setTimeout(() => buscarAtendimentos(texto), 400)
  }

  const selecionarAtendimento = (item: AtendimentoListaItem) => {
    setAtendimentoSelecionado(item)
    setBusca(`#${item.numero_curto} · ${item.cliente.nome ?? formatTelefone(item.cliente.telefone)}`)
    setResultadosBusca([])
    setBuscaAberta(false)
    setForm((f) => ({ ...f, atendimento_id: item.id }))
    if (editando) setAtendimentoEdit({ id: item.id })
  }

  const limparAtendimento = () => {
    setAtendimentoSelecionado(null)
    setBusca("")
    setResultadosBusca([])
    setBuscaAberta(false)
    setForm((f) => ({ ...f, atendimento_id: undefined }))
  }

  const limparBusca = () => {
    setBusca("")
    setResultadosBusca([])
    setBuscaAberta(false)
  }

  const desvincularAtendimento = () => {
    setAtendimentoSelecionado(null)
    setBusca("")
    setResultadosBusca([])
    setBuscaAberta(false)
    setForm((f) => ({ ...f, atendimento_id: undefined }))
    setAtendimentoEdit({ id: null })
  }

  const buscarClientes = useCallback(async (texto: string) => {
    if (!texto.trim()) {
      setResultadosCliente([])
      return
    }
    setBuscandoCliente(true)
    try {
      const params = new URLSearchParams({ q: texto.trim(), limit: "8" })
      const res = await api<ClientesListaResponse>(`/v1/crm/clientes?${params}`)
      setResultadosCliente(res.items)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Erro ao buscar clientes")
    } finally {
      setBuscandoCliente(false)
    }
  }, [])

  const handleBuscaClienteChange = (texto: string) => {
    setBuscaCliente(texto)
    setClienteSelecionado(null)
    setCriandoClienteRapido(false)
    if (buscaClienteTimer.current) clearTimeout(buscaClienteTimer.current)
    buscaClienteTimer.current = setTimeout(() => buscarClientes(texto), 400)
  }

  const abrirCriarAtendimento = () => {
    setCriandoAtendimento(true)
    // Reaproveita o texto digitado na busca de atendimento como busca de cliente.
    setBuscaCliente(busca)
    if (busca.trim()) {
      if (buscaClienteTimer.current) clearTimeout(buscaClienteTimer.current)
      buscaClienteTimer.current = setTimeout(() => buscarClientes(busca), 400)
    }
  }

  const voltarParaBusca = () => {
    setCriandoAtendimento(false)
    setClienteSelecionado(null)
    setResultadosCliente([])
    setCriandoClienteRapido(false)
    setNovoClienteNome("")
    setNovoClienteTelefone("")
  }

  const selecionarCliente = (cliente: ClienteListItem) => {
    setClienteSelecionado(cliente)
    setResultadosCliente([])
    setBuscaCliente(cliente.nome ?? cliente.telefone_mascarado ?? "")
  }

  const criarClienteRapido = async () => {
    const telefoneNormalizado = normalizarTelefoneE164(novoClienteTelefone)
    if (!telefoneNormalizado) return
    setSubmittingCliente(true)
    try {
      const cliente = await api<Cliente>("/v1/crm/clientes", {
        method: "POST",
        body: JSON.stringify({
          telefone: telefoneNormalizado,
          nome: novoClienteNome.trim() || null,
        }),
      })
      setClienteSelecionado(cliente)
      setCriandoClienteRapido(false)
      setBuscaCliente(cliente.nome ?? formatTelefone(cliente.telefone))
      toast.success("Cliente criado")
    } catch (e) {
      if (e instanceof ApiError && e.status === 409 && e.detail === "telefone_duplicado") {
        toast.error("Telefone já cadastrado")
      } else {
        toast.error(e instanceof Error ? e.message : "Erro ao criar cliente")
      }
    } finally {
      setSubmittingCliente(false)
    }
  }

  const criarAtendimentoEVincular = async () => {
    if (!clienteSelecionado) return
    if (!modeloIdEfetivo) {
      toast.error("Selecione uma modelo antes de criar o atendimento")
      return
    }
    setSubmittingNovoAtendimento(true)
    let dadosParciaisFalharam = false
    try {
      const res = await api<AtendimentoCriadoResponse>("/v1/atendimentos", {
        method: "POST",
        body: JSON.stringify({
          cliente_id: clienteSelecionado.id,
          modelo_id: modeloIdEfetivo,
        }),
      })

      const coletado = camposAtendRef.current?.coletarDados()
      const payload = coletado?.payload ?? {}
      const programas = coletado?.programas ?? []

      if (Object.keys(payload).length > 0) {
        try {
          await api(`/v1/atendimentos/${res.id}/dados`, {
            method: "PATCH",
            body: JSON.stringify(payload),
          })
        } catch {
          dadosParciaisFalharam = true
        }
      }
      for (const p of programas) {
        try {
          await api(`/v1/atendimentos/${res.id}/servicos`, {
            method: "POST",
            body: JSON.stringify(p),
          })
        } catch {
          dadosParciaisFalharam = true
        }
      }

      const telefone =
        "telefone" in clienteSelecionado
          ? clienteSelecionado.telefone
          : clienteSelecionado.telefone_mascarado ?? ""
      const item: AtendimentoListaItem = {
        id: res.id,
        numero_curto: res.numero_curto,
        cliente: {
          id: clienteSelecionado.id,
          nome: clienteSelecionado.nome,
          telefone,
        },
        modelo: { id: modeloIdEfetivo, nome: "" },
        estado: res.estado,
        tipo_atendimento: (payload.tipo_atendimento as AtendimentoListaItem["tipo_atendimento"]) ?? null,
        urgencia: (payload.urgencia as AtendimentoListaItem["urgencia"]) ?? null,
        ia_pausada: false,
        ia_pausada_motivo: null,
        responsavel_atual: "IA",
        motivo_escalada: null,
        proxima_acao_esperada: null,
        valor_acordado: payload.valor_acordado ?? null,
        updated_at: new Date().toISOString(),
        programa_principal_nome: null,
      }
      selecionarAtendimento(item)
      voltarParaBusca()
      if (dadosParciaisFalharam) {
        toast.warning(
          `Atendimento #${res.numero_curto} criado, mas alguns dados não puderam ser salvos. Edite para completar.`,
        )
      } else {
        toast.success(`Atendimento #${res.numero_curto} criado`)
      }
    } catch (e) {
      if (e instanceof ApiError && e.status === 409 && e.detail === "atendimento_aberto_existente") {
        toast.error("Cliente já tem atendimento em aberto com esta modelo — selecione o existente.")
      } else if (e instanceof ApiError && e.status === 409 && e.detail === "cliente_arquivado") {
        toast.error("Cliente está arquivado. Desarquive antes de criar atendimento.")
      } else {
        toast.error(e instanceof Error ? e.message : "Erro ao criar atendimento")
      }
    } finally {
      setSubmittingNovoAtendimento(false)
    }
  }

  const modoBloqueio =
    (!editando && tipo === "bloqueio") ||
    (editando && !bloqueio?.atendimento_id && atendimentoEdit?.id == null)

  const handleInicioChange = (inicio: string) => {
    if (modoBloqueio) {
      setForm((atual) => ({ ...atual, inicio }))
      return
    }
    const novoFim = calcFimDeDuracao(inicio, duracaoMin)
    setForm((atual) => ({ ...atual, inicio, fim: novoFim }))
  }

  const handleFimChange = (fim: string) => {
    setForm((atual) => ({ ...atual, fim }))
  }

  const handleDuracaoChange = (min: number) => {
    setDuracaoMin(min)
    setForm((atual) => ({ ...atual, fim: calcFimDeDuracao(atual.inicio, min) }))
  }

  const submit = async () => {
    if (!podeSalvar) return
    setSubmitting(true)
    try {
      if (bloqueio) {
        const atId = atendimentoEdit !== null ? atendimentoEdit.id : undefined
        await onAtualizar(bloqueio.id, form, atId)
      } else {
        await onCriar(form)
      }
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

  // Duração atual pode não estar na lista predefinida (ex.: bloqueio de 45min)
  const opcoesDuracao = DURACOES.some((d) => d.min === duracaoMin)
    ? DURACOES
    : [{ min: duracaoMin, label: duracaoLabel(duracaoMin) }, ...DURACOES]

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
        className="fixed top-1/2 left-1/2 z-50 flex w-[min(96vw,88rem)] -translate-x-1/2 -translate-y-1/2 flex-col max-h-[92vh] min-h-[70vh] rounded-lg border border-border bg-popover text-popover-foreground shadow-[0_16px_48px_rgba(0,0,0,0.7)]"
      >
        {/* Header */}
        <div className="flex flex-shrink-0 items-start justify-between gap-4 border-b border-border px-8 py-4">
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
        <div className="flex-1 overflow-y-auto px-8 py-6">
          <div className={cn(
            "grid gap-x-8 gap-y-5",
            // Modo "criar bloqueio puro" (sem atendimento) colapsa para 1 coluna estreita centralizada
            (!editando && tipo === "bloqueio")
              ? "max-w-2xl mx-auto grid-cols-1"
              : "lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]"
          )}>

            {/* ═══════════════ COLUNA ESQUERDA: contexto/atendimento ═══════════════ */}
            <div className="space-y-5">

            {/* Tipo: só na criação */}
            {!editando && (
              <div>
                <Label>Tipo</Label>
                <div className="mt-2 flex gap-2">
                  <button
                    type="button"
                    onClick={() => { setTipo("bloqueio"); limparAtendimento() }}
                    className={cn(
                      "rounded-md border px-3 py-1.5 text-sm font-medium transition-colors",
                      tipo === "bloqueio"
                        ? "border-primary bg-accent text-text-primary"
                        : "border-border text-text-muted hover:border-border-strong hover:text-text-secondary"
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
                        ? "border-primary bg-accent text-text-primary"
                        : "border-border text-text-muted hover:border-border-strong hover:text-text-secondary"
                    )}
                  >
                    Agendamento
                  </button>
                </div>
              </div>
            )}

            {/* Seleção de modelo: só na criação sem modeloId fixo */}
            {!editando && !modeloId && (
              <div className="pb-1">
                <Label htmlFor="agenda-modelo">Modelo</Label>
                <div className="mt-2 w-full max-w-xs">
                  <FiltroModelo
                    modeloId={form.modelo_id ?? null}
                    onChange={(val) => {
                      if (form.modelo_id && form.modelo_id !== val) {
                        setAtendimentoSelecionado(null)
                        setBusca("")
                        setResultadosBusca([])
                        setBuscaAberta(false)
                        setForm((f) => ({ ...f, modelo_id: val ?? undefined, atendimento_id: undefined }))
                      } else {
                        setForm((f) => ({ ...f, modelo_id: val ?? undefined }))
                      }
                    }}
                    hideTodas
                  />
                </div>
              </div>
            )}

            {/* Busca de atendimento: criação (agendamento) ou edição (qualquer estado editável) */}
            {((!editando && tipo === "agendamento") || (editando && !readOnly)) && !criandoAtendimento && (
              <div className="relative">
                {(!editando || atendimentoDisplay === null) && (
                  <Label htmlFor="busca-atendimento">Atendimento</Label>
                )}
                {atendimentoDisplay === null && (
                  <div className="relative mt-2">
                    <Input
                      id="busca-atendimento"
                      value={busca}
                      onChange={(e) => handleBuscaChange(e.target.value)}
                      placeholder="Nome, número ou #ID do atendimento..."
                      className="h-10 border-border pr-8"
                      autoComplete="off"
                    />
                    {buscando && (
                      <Loader2 size={14} className="absolute right-2.5 top-1/2 -translate-y-1/2 animate-spin text-text-muted" />
                    )}
                    {busca && !buscando && (
                      <button
                        type="button"
                        onClick={editando ? limparBusca : limparAtendimento}
                        className="absolute right-2 top-1/2 -translate-y-1/2 text-text-muted hover:text-text-primary"
                        aria-label="Limpar busca"
                      >
                        <X size={14} />
                      </button>
                    )}
                    {buscaAberta && resultadosBusca.length > 0 && (
                      <div className="absolute z-[60] mt-1 w-full overflow-hidden rounded-lg border border-border bg-popover shadow-[0_8px_24px_rgba(0,0,0,0.6)]">
                        {resultadosBusca.map((item) => (
                          <button
                            key={item.id}
                            type="button"
                            onClick={() => selecionarAtendimento(item)}
                            className="flex w-full items-center gap-3 px-3 py-2.5 text-left text-sm hover:bg-accent border-b border-border last:border-0"
                          >
                            <span className="font-mono text-xs text-text-muted">#{item.numero_curto}</span>
                            <span className="flex-1 truncate font-medium text-text-primary">
                              {item.cliente.nome ?? formatTelefone(item.cliente.telefone)}
                            </span>
                            <div className="flex items-center gap-1.5 shrink-0">
                              {item.tipo_atendimento && (
                                <span className="rounded-full bg-accent px-1.5 py-0.5 text-xs text-text-muted">
                                  {item.tipo_atendimento === "interno" ? "Int" : "Ext"}
                                </span>
                              )}
                              <span className="text-xs text-text-muted">{formatRotulo(item.estado)}</span>
                            </div>
                          </button>
                        ))}
                        <button
                          type="button"
                          onClick={abrirCriarAtendimento}
                          className="flex w-full items-center gap-2 px-3 py-2.5 text-left text-sm text-text-primary hover:bg-accent"
                        >
                          <Plus size={14} strokeWidth={1.5} />
                          <span>Criar novo atendimento</span>
                        </button>
                      </div>
                    )}
                    {buscaAberta && resultadosBusca.length === 0 && !buscando && busca.trim() && (
                      <div className="absolute z-[60] mt-1 w-full overflow-hidden rounded-lg border border-border bg-popover shadow-[0_8px_24px_rgba(0,0,0,0.6)]">
                        <p className="px-3 py-2.5 text-xs text-text-muted">Nenhum atendimento encontrado.</p>
                        <button
                          type="button"
                          onClick={abrirCriarAtendimento}
                          className="flex w-full items-center gap-2 border-t border-border px-3 py-2.5 text-left text-sm text-text-primary hover:bg-accent"
                        >
                          <Plus size={14} strokeWidth={1.5} />
                          <span>Criar novo atendimento</span>
                        </button>
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}

            {/* Seção expansível: criação rápida de atendimento */}
            {criandoAtendimento && (
              <div className="space-y-3 rounded-lg border border-border bg-surface-raised p-3">
                <div className="flex items-center justify-between">
                  <p className="text-sm font-semibold text-text-primary">Novo atendimento</p>
                  <button
                    type="button"
                    onClick={voltarParaBusca}
                    disabled={submittingNovoAtendimento || submittingCliente}
                    className="flex items-center gap-1 text-xs text-text-muted hover:text-text-primary disabled:opacity-60"
                  >
                    <ArrowLeft size={12} strokeWidth={1.5} />
                    Voltar
                  </button>
                </div>

                {!criandoClienteRapido && (
                  <div className="relative">
                    <Label htmlFor="busca-cliente-rapido">Cliente</Label>
                    <div className="relative mt-2">
                      <Input
                        id="busca-cliente-rapido"
                        value={buscaCliente}
                        onChange={(e) => handleBuscaClienteChange(e.target.value)}
                        placeholder="Nome ou telefone..."
                        className="h-10 border-border pr-8"
                        autoComplete="off"
                        disabled={submittingNovoAtendimento}
                      />
                      {buscandoCliente && (
                        <Loader2 size={14} className="absolute right-2.5 top-1/2 -translate-y-1/2 animate-spin text-text-muted" />
                      )}
                      {resultadosCliente.length > 0 && !clienteSelecionado && (
                        <div className="absolute z-[60] mt-1 w-full overflow-hidden rounded-lg border border-border bg-popover shadow-[0_8px_24px_rgba(0,0,0,0.6)]">
                          {resultadosCliente.map((cliente) => (
                            <button
                              key={cliente.id}
                              type="button"
                              onClick={() => selecionarCliente(cliente)}
                              className="flex w-full items-center justify-between gap-3 border-b border-border px-3 py-2.5 text-left text-sm hover:bg-accent last:border-0"
                            >
                              <span className="flex-1 truncate font-medium text-text-primary">
                                {cliente.nome ?? "Sem nome"}
                              </span>
                              <span className="font-mono text-xs text-text-muted">
                                {cliente.telefone_mascarado ? formatTelefone(cliente.telefone_mascarado) : ""}
                              </span>
                            </button>
                          ))}
                        </div>
                      )}
                    </div>
                    {!buscandoCliente && resultadosCliente.length === 0 && buscaCliente.trim() && !clienteSelecionado && (
                      <div className="mt-2 flex items-center justify-between gap-3 rounded-md border border-dashed border-border px-3 py-2 text-xs text-text-muted">
                        <span>Nenhum cliente encontrado.</span>
                        <button
                          type="button"
                          onClick={() => {
                            setCriandoClienteRapido(true)
                            setNovoClienteNome(buscaCliente)
                          }}
                          className="flex items-center gap-1 text-text-primary hover:underline"
                        >
                          <Plus size={12} strokeWidth={1.5} />
                          Criar cliente
                        </button>
                      </div>
                    )}
                    {clienteSelecionado && (
                      <div className="mt-2 flex items-center justify-between gap-3 rounded-md border border-border bg-muted px-3 py-2 text-sm">
                        <div className="min-w-0">
                          <p className="truncate font-medium text-text-primary">
                            {clienteSelecionado.nome ?? "Sem nome"}
                          </p>
                          <p className="font-mono text-xs text-text-muted">
                            {"telefone" in clienteSelecionado
                              ? formatTelefone(clienteSelecionado.telefone)
                              : clienteSelecionado.telefone_mascarado
                                ? formatTelefone(clienteSelecionado.telefone_mascarado)
                                : ""}
                          </p>
                        </div>
                        <button
                          type="button"
                          onClick={() => {
                            setClienteSelecionado(null)
                            setBuscaCliente("")
                          }}
                          disabled={submittingNovoAtendimento}
                          className="rounded-md p-1 text-text-muted hover:bg-muted hover:text-text-primary disabled:opacity-60"
                          aria-label="Trocar cliente"
                        >
                          <X size={13} strokeWidth={1.5} />
                        </button>
                      </div>
                    )}
                  </div>
                )}

                {criandoClienteRapido && (
                  <div className="space-y-2 rounded-md border border-border bg-muted p-3">
                    <div className="flex items-center justify-between">
                      <p className="text-xs font-semibold uppercase tracking-wider text-text-muted">
                        Cliente novo
                      </p>
                      <button
                        type="button"
                        onClick={() => {
                          setCriandoClienteRapido(false)
                          setNovoClienteNome("")
                          setNovoClienteTelefone("")
                        }}
                        disabled={submittingCliente}
                        className="text-xs text-text-muted hover:text-text-primary disabled:opacity-60"
                      >
                        Cancelar
                      </button>
                    </div>
                    <div>
                      <Label htmlFor="novo-cliente-rapido-nome">Nome</Label>
                      <Input
                        id="novo-cliente-rapido-nome"
                        value={novoClienteNome}
                        onChange={(e) => setNovoClienteNome(e.target.value)}
                        placeholder="Opcional"
                        className="mt-1.5 h-9 border-border"
                        disabled={submittingCliente}
                        autoComplete="off"
                      />
                    </div>
                    <div>
                      <Label htmlFor="novo-cliente-rapido-telefone">Telefone</Label>
                      <Input
                        id="novo-cliente-rapido-telefone"
                        value={novoClienteTelefone}
                        onChange={(e) => setNovoClienteTelefone(aplicarMascaraTelefone(e.target.value))}
                        placeholder="(11) 99999-9999"
                        className="mt-1.5 h-9 border-border"
                        disabled={submittingCliente}
                        autoComplete="off"
                        inputMode="numeric"
                      />
                      {novoClienteTelefone.length > 0 && normalizarTelefoneE164(novoClienteTelefone) === null && (
                        <p className="mt-1 text-xs text-state-lost">
                          Telefone incompleto. Use 10 ou 11 dígitos.
                        </p>
                      )}
                    </div>
                    <div className="flex justify-end">
                      <Button
                        variant="primary"
                        onClick={criarClienteRapido}
                        disabled={submittingCliente || normalizarTelefoneE164(novoClienteTelefone) === null}
                      >
                        {submittingCliente && <Loader2 className="animate-spin" />}
                        Criar
                      </Button>
                    </div>
                  </div>
                )}

                <FormularioCamposAtendimento
                  ref={camposAtendRef}
                  modeloId={modeloIdEfetivo}
                  disabled={submittingNovoAtendimento}
                  variant="stack"
                  herdarPeriodo={tipo === "agendamento"}
                  periodoHerdado={{
                    data: form.data,
                    horario: form.inicio,
                    duracaoHoras: duracaoMin / 60,
                  }}
                />

                <div className="flex justify-end">
                  <Button
                    variant="primary"
                    onClick={criarAtendimentoEVincular}
                    disabled={!clienteSelecionado || submittingNovoAtendimento}
                  >
                    {submittingNovoAtendimento && <Loader2 className="animate-spin" />}
                    Criar atendimento e vincular
                  </Button>
                </div>
              </div>
            )}

            {/* Card de info do atendimento vinculado */}
            {atendimentoDisplay && (
              <div className="overflow-hidden rounded-lg border border-border bg-surface-raised">
                <div className="flex items-center gap-3 border-b border-border px-3 py-2.5">
                  <span className="font-mono text-xs text-text-muted">
                    #{atendimentoDisplay.numero_curto}
                  </span>
                  <span className="text-sm font-semibold text-text-primary">
                    {atendimentoDisplay.cliente_nome ?? atendimentoDisplay.cliente_telefone_formatado}
                  </span>
                  <div className="ml-auto flex items-center gap-2 shrink-0">
                    {atendimentoDisplay.tipo_atendimento && (
                      <span className="rounded-full bg-accent px-2 py-0.5 text-xs font-medium text-text-secondary">
                        {atendimentoDisplay.tipo_atendimento === "interno" ? "Interno" : "Externo"}
                      </span>
                    )}
                    <span className="text-xs text-text-muted">{formatRotulo(atendimentoDisplay.estado)}</span>
                    {editando && !readOnly && (
                      <button
                        type="button"
                        onClick={desvincularAtendimento}
                        className="ml-1 rounded-md p-1 text-text-muted hover:bg-muted hover:text-text-primary"
                        title="Desvincular atendimento"
                      >
                        <X size={13} strokeWidth={1.5} />
                      </button>
                    )}
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
                {/* Botão alterar atendimento em edit mode */}
                {editando && !readOnly && (
                  <div className="border-t border-border px-3 py-2">
                    <button
                      type="button"
                      onClick={() => { desvincularAtendimento() }}
                      className="text-xs text-text-muted hover:text-text-primary underline-offset-2 hover:underline"
                    >
                      Alterar atendimento
                    </button>
                  </div>
                )}
              </div>
            )}

            </div>{/* ═══════════════ FIM COLUNA ESQUERDA ═══════════════ */}

            {/* ═══════════════ COLUNA DIREITA: horário + observação ═══════════════ */}
            <div className="space-y-5">

            {/* Seção: Horário */}
            <section className="rounded-lg border border-border bg-card p-4">
              <p className="mb-4 text-xs font-semibold uppercase tracking-wider text-text-muted">
                Horário
              </p>
              <div className="space-y-3">
                <div>
                  <Label htmlFor="agenda-data">Data</Label>
                  <Input
                    id="agenda-data"
                    type="date"
                    value={form.data}
                    disabled={readOnly}
                    onChange={(event) => setForm((atual) => ({ ...atual, data: event.target.value }))}
                    className="mt-2 h-10 border-border"
                  />
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <CampoHorario
                    id="agenda-inicio"
                    label="Início"
                    value={form.inicio}
                    disabled={readOnly}
                    onChange={handleInicioChange}
                  />
                  {modoBloqueio ? (
                    <CampoHorario
                      id="agenda-fim"
                      label="Fim"
                      value={form.fim}
                      disabled={readOnly}
                      onChange={handleFimChange}
                    />
                  ) : (
                    <CampoDuracao
                      id="agenda-duracao"
                      value={duracaoMin}
                      opcoes={opcoesDuracao}
                      disabled={readOnly}
                      onChange={handleDuracaoChange}
                    />
                  )}
                </div>
                {!modoBloqueio && (
                  <div>
                    <Label>Fim</Label>
                    <div className="mt-2 flex h-10 items-center gap-1.5 text-sm text-text-primary">
                      {form.fim}
                      {overnight && (
                        <span className="text-xs text-text-muted">(próx. dia)</span>
                      )}
                    </div>
                  </div>
                )}
              </div>
              {intervaloInvalido && (
                <p className="mt-3 text-sm text-state-lost">Fim precisa ser maior que início.</p>
              )}
              {conflito && (
                <p className="mt-3 text-sm text-state-handoff">
                  Este horário se sobrepõe a outro bloqueio ativo.
                </p>
              )}
            </section>

            {/* Seção: Observação */}
            <section className="rounded-lg border border-border bg-card p-4">
              <Label htmlFor="agenda-observacao" className="text-xs font-semibold uppercase tracking-wider text-text-muted">
                Observação
              </Label>
              <textarea
                id="agenda-observacao"
                value={form.observacao}
                maxLength={180}
                disabled={readOnly}
                onChange={(event) => setForm((atual) => ({ ...atual, observacao: event.target.value }))}
                className="mt-2 min-h-24 w-full rounded-lg border border-border bg-input px-3 py-2 text-sm text-text-primary outline-none placeholder:text-text-muted focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:opacity-60"
              />
              <p className={cn("mt-1 text-xs", observacaoInvalida ? "text-state-lost" : "text-text-muted")}>
                {form.observacao.length}/160
              </p>
            </section>

            </div>{/* ═══════════════ FIM COLUNA DIREITA ═══════════════ */}
          </div>
        </div>

        {/* Footer */}
        <div className="flex flex-shrink-0 items-center justify-between gap-3 border-t border-border px-8 py-4">
          <div className="flex items-center gap-2">
            {bloqueio?.atendimento_id && (
              <Button variant="ghost" onClick={() => onVerAtendimento(bloqueio.atendimento_id!)}>
                Ver atendimento
              </Button>
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
                {acaoLabel}
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
              {bloqueio?.estado === "em_atendimento" ? "Confirmar cancelamento" : acaoLabel}
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
                className="mt-2 h-10 w-full rounded-lg border border-border bg-input px-3 text-sm text-text-primary outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:opacity-60"
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
        className="mt-2 h-10 w-full rounded-lg border border-border bg-input px-3 text-sm text-text-primary outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:opacity-60"
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

function CampoDuracao({
  id,
  value,
  opcoes,
  disabled,
  onChange,
}: {
  id: string
  value: number
  opcoes: { min: number; label: string }[]
  disabled: boolean
  onChange: (min: number) => void
}) {
  return (
    <div>
      <Label htmlFor={id}>Duração</Label>
      <select
        id={id}
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(Number(event.target.value))}
        className="mt-2 h-10 w-full rounded-lg border border-border bg-input px-3 text-sm text-text-primary outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:opacity-60"
      >
        {opcoes.map((d) => (
          <option key={d.min} value={d.min}>
            {d.label}
          </option>
        ))}
      </select>
    </div>
  )
}
