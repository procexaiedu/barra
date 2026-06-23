"use client"

import { useEffect, useMemo, useRef, useState } from "react"
import { useSearchParams } from "next/navigation"
import { toast } from "sonner"
import { AgendaDiaLista } from "@/components/agenda/AgendaDiaLista"
import { CalendarioMes } from "@/components/agenda/CalendarioMes"
import { DialogBloqueio } from "@/components/agenda/DialogBloqueio"
import { DialogVisualizarBloqueio } from "@/components/agenda/DialogVisualizarBloqueio"
import { GradeSemanal } from "@/components/agenda/GradeSemanal"
import { HeaderAgenda } from "@/components/agenda/HeaderAgenda"
import { ToolbarAgenda } from "@/components/agenda/ToolbarAgenda"
import { ModalAtendimentoHistorico } from "@/components/clientes/ModalAtendimentoHistorico"
import { BannerErro } from "@/components/layout/BannerErro"
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
import { Skeleton } from "@/components/ui/skeleton"
import { useIsMobile } from "@/hooks/useMediaQuery"
import { dataDeInput, dataInput, dataInputSaoPaulo, isoAgenda, useAgenda } from "@/hooks/useAgenda"
import { ApiError } from "@/lib/api"
import type { AtualizarBloqueioInput, BloqueioAgenda, BloqueioFormState } from "@/tipos/agenda"

// 409 do backend quando o início do bloqueio cai fora da disponibilidade da modelo (ADR 0005).
function ehForaDisponibilidade(e: unknown): boolean {
  return (
    e instanceof ApiError &&
    e.code === "CONFLITO_ESTADO" &&
    (e.details as { campo?: string } | null)?.campo === "confirmar_fora_disponibilidade"
  )
}

// 409 do backend quando o horário fica dentro do buffer de preparo/intervalo (ADR 0025);
// Fernando força com confirmar_buffer, igual ao override fora da disponibilidade.
function ehBuffer(e: unknown): boolean {
  return (
    e instanceof ApiError &&
    e.code === "CONFLITO_ESTADO" &&
    (e.details as { campo?: string } | null)?.campo === "confirmar_buffer"
  )
}

// Overrides que o painel pode forçar ao criar/atualizar bloqueio; acumulam quando ambos disparam.
type Confirmacoes = { foraDisp?: boolean; buffer?: boolean }

function fimIsoOvernight(data: string, inicio: string, fim: string): string {
  if (fim !== "24:00" && fim < inicio) {
    const d = dataDeInput(data)
    d.setDate(d.getDate() + 1)
    return isoAgenda(dataInput(d), fim)
  }
  return isoAgenda(data, fim)
}

function fimParaGrade(inicio: string): string {
  const [h, m] = inicio.split(":").map(Number)
  const hFim = h + 1
  if (hFim >= 24) return "24:00"
  return `${String(hFim).padStart(2, "0")}:${String(m).padStart(2, "0")}`
}

function proximoSlotLivre(data: string, bloqueios: BloqueioAgenda[]): BloqueioFormState {
  const ocupados = new Set(
    bloqueios
      .filter(
        (b) =>
          b.inicio.slice(0, 10) === data &&
          (b.estado === "bloqueado" || b.estado === "em_atendimento")
      )
      .map((b) => b.inicio.slice(11, 16))
  )
  const hora =
    Array.from({ length: 14 }, (_, h) => `${String(h + 10).padStart(2, "0")}:00`).find(
      (item) => !ocupados.has(item)
    ) ?? "10:00"
  return { data, inicio: hora, fim: fimParaGrade(hora), observacao: "" }
}

function diasParaGrade(visao: "dia" | "semana", dataSelecionada: string): Date[] {
  const base = dataDeInput(dataSelecionada)
  if (visao === "dia") return [base]
  const d = new Date(base)
  const dia = d.getDay()
  const deslocamento = dia === 0 ? -6 : 1 - dia
  d.setDate(d.getDate() + deslocamento)
  return Array.from({ length: 7 }, (_, i) => {
    const item = new Date(d)
    item.setDate(d.getDate() + i)
    return item
  })
}

export function AgendaClient() {
  const searchParams = useSearchParams()
  const dataParam = searchParams.get("data") ?? undefined
  const bloqueioParam = searchParams.get("bloqueio") ?? undefined

  const agenda = useAgenda({ data: dataParam })
  const isMobile = useIsMobile()

  type DialogModo = "fechado" | "visualizar" | "editar" | "criar"
  type DialogState = { modo: DialogModo; bloqueio: BloqueioAgenda | null }
  const [dialog, setDialog] = useState<DialogState>({ modo: "fechado", bloqueio: null })
  const [initialForm, setInitialForm] = useState<BloqueioFormState>({
    data: dataParam ?? agenda.dataSelecionada,
    inicio: "10:00",
    fim: "11:00",
    observacao: "",
  })
  const bloqueioInicialHandled = useRef(false)
  const [tipoAtendimento, setTipoAtendimento] = useState<"" | "interno" | "externo" | "remoto">("")
  const [atendimentoVisualizandoId, setAtendimentoVisualizandoId] = useState<string | null>(null)
  // Override "fora da disponibilidade": guarda a confirmação a refazer com a flag (ADR 0005).
  const [foraDisp, setForaDisp] = useState<{ confirmar: () => Promise<void> } | null>(null)
  // Override "dentro do buffer de preparo" (ADR 0025): mesma mecânica de confirmação.
  const [buffer, setBuffer] = useState<{ confirmar: () => Promise<void> } | null>(null)

  const bloqueios = useMemo(() => {
    let items = [...(agenda.agenda?.bloqueios ?? [])]
    if (tipoAtendimento) {
      items = items.filter((b) => b.atendimento?.tipo_atendimento === tipoAtendimento)
    }
    return items.sort((a, b) => a.inicio.localeCompare(b.inicio))
  }, [agenda.agenda?.bloqueios, tipoAtendimento])

  // Abre dialog para deep link ?bloqueio= após primeiro carregamento
  useEffect(() => {
    async function abrirBloqueioInicial() {
      if (bloqueioInicialHandled.current) return
      if (agenda.status !== "success" || !bloqueioParam) return
      const b = bloqueios.find((x) => x.id === bloqueioParam)
      if (!b) return
      bloqueioInicialHandled.current = true
      setDialog({ modo: "visualizar", bloqueio: b })
    }
    void abrirBloqueioInicial()
  }, [agenda.status, bloqueioParam, bloqueios])

  const abrirCriacao = (form: BloqueioFormState) => {
    setDialog({ modo: "criar", bloqueio: null })
    setInitialForm(form)
  }

  const criar = async (form: BloqueioFormState, conf: Confirmacoes = {}) => {
    const modeloId = form.modelo_id ?? agenda.agenda?.modelo?.id
    if (!modeloId) {
      toast.error("Selecione uma modelo.")
      return
    }
    try {
      await agenda.criarBloqueio({
        modelo_id: modeloId,
        inicio: isoAgenda(form.data, form.inicio),
        fim: fimIsoOvernight(form.data, form.inicio, form.fim),
        observacao: form.observacao.trim() || null,
        ...(form.atendimento_id ? { atendimento_id: form.atendimento_id } : {}),
        ...(conf.foraDisp ? { confirmar_fora_disponibilidade: true } : {}),
        ...(conf.buffer ? { confirmar_buffer: true } : {}),
      })
      toast.success(form.atendimento_id ? "Agendamento criado" : "Bloqueio criado")
      setDialog({ modo: "fechado", bloqueio: null })
      setForaDisp(null)
      setBuffer(null)
    } catch (e) {
      if (ehForaDisponibilidade(e) && !conf.foraDisp) {
        setForaDisp({ confirmar: () => criar(form, { ...conf, foraDisp: true }) })
        return
      }
      if (ehBuffer(e) && !conf.buffer) {
        setBuffer({ confirmar: () => criar(form, { ...conf, buffer: true }) })
        return
      }
      toast.error(e instanceof Error ? e.message : "Erro do servidor. Tente novamente.")
    }
  }

  const atualizar = async (
    id: string,
    form: BloqueioFormState,
    atendimentoId?: string | null,
    conf: Confirmacoes = {},
  ) => {
    try {
      const payload: AtualizarBloqueioInput = {
        inicio: isoAgenda(form.data, form.inicio),
        fim: fimIsoOvernight(form.data, form.inicio, form.fim),
        observacao: form.observacao.trim() || null,
      }
      if (atendimentoId !== undefined) payload.atendimento_id = atendimentoId
      if (conf.foraDisp) payload.confirmar_fora_disponibilidade = true
      if (conf.buffer) payload.confirmar_buffer = true
      await agenda.atualizarBloqueio(id, payload)
      const ehAgendamento =
        atendimentoId !== undefined ? Boolean(atendimentoId) : Boolean(dialog.bloqueio?.atendimento_id)
      toast.success(ehAgendamento ? "Agendamento atualizado" : "Bloqueio atualizado")
      setDialog({ modo: "fechado", bloqueio: null })
      setForaDisp(null)
      setBuffer(null)
    } catch (e) {
      if (ehForaDisponibilidade(e) && !conf.foraDisp) {
        setForaDisp({ confirmar: () => atualizar(id, form, atendimentoId, { ...conf, foraDisp: true }) })
        return
      }
      if (ehBuffer(e) && !conf.buffer) {
        setBuffer({ confirmar: () => atualizar(id, form, atendimentoId, { ...conf, buffer: true }) })
        return
      }
      toast.error(e instanceof Error ? e.message : "Erro do servidor. Tente novamente.")
    }
  }

  const moverBloqueio = async (id: string, novoInicio: string, novoFim: string) => {
    try {
      await agenda.atualizarBloqueio(id, { inicio: novoInicio, fim: novoFim, observacao: null })
      const movido = bloqueios.find((b) => b.id === id)
      toast.success(movido?.atendimento_id ? "Agendamento movido" : "Bloqueio movido")
    } catch (e) {
      const msg = e instanceof Error ? e.message : ""
      if (msg.toLowerCase().includes("sobrepos")) {
        toast.error("Conflito com outro bloqueio neste horário.")
      } else {
        toast.error(msg || "Erro ao mover.")
      }
      await agenda.refetch()
    }
  }

  const cancelar = async (id: string, confirmar: boolean) => {
    try {
      await agenda.cancelarBloqueio(id, confirmar)
      toast.success(dialog.bloqueio?.atendimento_id ? "Agendamento cancelado" : "Bloqueio cancelado")
      setDialog({ modo: "fechado", bloqueio: null })
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Erro do servidor. Tente novamente.")
    }
  }

  if (agenda.status === "loading") return <AgendaSkeleton />

  if (agenda.status === "error") {
    return (
      <section className="flex flex-col gap-4">
        <HeaderAgenda modelo={agenda.modeloId ? (agenda.agenda?.modelo ?? null) : null} bloqueios={[]} />
        <BannerErro mensagem={agenda.error ?? undefined} onRetry={agenda.refetch} />
      </section>
    )
  }

  const hojeStr = dataInputSaoPaulo()

  return (
    <section className="flex flex-col gap-4">
      <HeaderAgenda
        modelo={agenda.modeloId ? (agenda.agenda?.modelo ?? null) : null}
        bloqueios={bloqueios}
        visao={agenda.visao}
        onVisaoChange={agenda.setVisao}
        onCriar={() => abrirCriacao(proximoSlotLivre(agenda.dataSelecionada, bloqueios))}
      />
      <ToolbarAgenda
        periodoLabel={agenda.periodo.label}
        modeloId={agenda.modeloId}
        tipoAtendimento={tipoAtendimento}
        bloqueios={bloqueios}
        onAnterior={agenda.anterior}
        onProximo={agenda.proximo}
        onHoje={agenda.hoje}
        onModeloChange={agenda.setModeloId}
        onTipoAtendimentoChange={setTipoAtendimento}
      />

      {agenda.visao === "mes" ? (
        <CalendarioMes
          visao={agenda.visao}
          dataSelecionada={agenda.dataSelecionada}
          bloqueios={bloqueios}
          onSelecionarDia={agenda.setDataSelecionada}
          onCriarNoDia={(data) => abrirCriacao(proximoSlotLivre(data, bloqueios))}
          onEditarBloqueio={(b) => setDialog({ modo: "visualizar", bloqueio: b })}
          onMover={moverBloqueio}
        />
      ) : isMobile ? (
        <AgendaDiaLista
          data={agenda.dataSelecionada}
          bloqueios={bloqueios}
          dataHoje={hojeStr}
          onNavegar={agenda.setDataSelecionada}
          onHoje={agenda.hoje}
          onCriarNoDia={(data) => abrirCriacao(proximoSlotLivre(data, bloqueios))}
          onEditar={(b) => setDialog({ modo: "visualizar", bloqueio: b })}
        />
      ) : (
        <GradeSemanal
          dias={diasParaGrade(agenda.visao, agenda.dataSelecionada)}
          bloqueios={bloqueios}
          dataHoje={hojeStr}
          onCriar={(data, inicio) =>
            abrirCriacao({ data, inicio, fim: fimParaGrade(inicio), observacao: "" })
          }
          onEditar={(b) => setDialog({ modo: "visualizar", bloqueio: b })}
          onMover={moverBloqueio}
        />
      )}

      {dialog.modo === "visualizar" && dialog.bloqueio && (
        <DialogVisualizarBloqueio
          bloqueio={dialog.bloqueio}
          open
          onOpenChange={(v) => {
            if (!v) setDialog({ modo: "fechado", bloqueio: null })
          }}
          onEditar={() => setDialog({ modo: "editar", bloqueio: dialog.bloqueio })}
        />
      )}

      {(dialog.modo === "criar" || dialog.modo === "editar") && (
        <DialogBloqueio
          bloqueio={dialog.bloqueio}
          modeloId={agenda.agenda?.modelo?.id ?? null}
          initial={initialForm}
          bloqueios={bloqueios}
          onClose={() => setDialog({ modo: "fechado", bloqueio: null })}
          onCriar={criar}
          onAtualizar={atualizar}
          onCancelar={cancelar}
          onVerAtendimento={(id) => {
            setDialog({ modo: "fechado", bloqueio: null })
            setAtendimentoVisualizandoId(id)
          }}
        />
      )}

      <ModalAtendimentoHistorico
        atendimentoId={atendimentoVisualizandoId}
        onClose={() => setAtendimentoVisualizandoId(null)}
      />

      <AlertDialog open={foraDisp !== null} onOpenChange={(aberto) => { if (!aberto) setForaDisp(null) }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Fora do período de trabalho</AlertDialogTitle>
            <AlertDialogDescription>
              Este horário está fora da disponibilidade configurada da modelo (folga/viagem).
              Quer criar mesmo assim? O período não será alterado.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Voltar</AlertDialogCancel>
            <AlertDialogAction onClick={() => { void foraDisp?.confirmar() }}>
              Criar mesmo assim
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={buffer !== null} onOpenChange={(aberto) => { if (!aberto) setBuffer(null) }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Dentro do buffer de preparo</AlertDialogTitle>
            <AlertDialogDescription>
              Este horário fica colado a outro bloqueio ou dentro do intervalo mínimo de preparo
              (a IA não reservaria aqui). Quer criar mesmo assim?
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Voltar</AlertDialogCancel>
            <AlertDialogAction onClick={() => { void buffer?.confirmar() }}>
              Criar mesmo assim
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </section>
  )
}

export function AgendaSkeleton() {
  return (
    <section className="flex flex-col gap-4" aria-busy="true">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="flex flex-col gap-2">
          <Skeleton className="h-9 w-40 rounded-md" />
          <Skeleton className="h-4 w-44 rounded-md" />
        </div>
        <Skeleton className="h-[4.75rem] w-80 rounded-lg" />
      </div>
      <div className="rounded-lg border border-border bg-card p-2">
        <div className="flex items-center justify-between">
          <Skeleton className="h-8 w-48 rounded-md" />
          <Skeleton className="h-9 w-56 rounded-md" />
          <Skeleton className="h-9 w-40 rounded-md" />
        </div>
      </div>
      <div className="overflow-hidden rounded-lg border border-border bg-card">
        <div className="grid h-12 border-b border-border" style={{ gridTemplateColumns: "52px repeat(7, 1fr)" }}>
          {Array.from({ length: 8 }, (_, i) => (
            <Skeleton key={i} className="m-2 h-8 rounded-md" />
          ))}
        </div>
        <div className="flex flex-col gap-1 p-4">
          {Array.from({ length: 6 }, (_, i) => (
            <Skeleton key={i} className="h-16 rounded-lg" />
          ))}
        </div>
      </div>
    </section>
  )
}
