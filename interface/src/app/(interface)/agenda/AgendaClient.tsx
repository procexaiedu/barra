"use client"

import { useEffect, useMemo, useRef, useState } from "react"
import { useSearchParams } from "next/navigation"
import { toast } from "sonner"
import { CalendarioMes } from "@/components/agenda/CalendarioMes"
import { DialogBloqueio } from "@/components/agenda/DialogBloqueio"
import { DialogVisualizarBloqueio } from "@/components/agenda/DialogVisualizarBloqueio"
import { GradeSemanal } from "@/components/agenda/GradeSemanal"
import { HeaderAgenda } from "@/components/agenda/HeaderAgenda"
import { ToolbarAgenda } from "@/components/agenda/ToolbarAgenda"
import { ModalAtendimentoHistorico } from "@/components/clientes/ModalAtendimentoHistorico"
import { BannerErro } from "@/components/layout/BannerErro"
import { Skeleton } from "@/components/ui/skeleton"
import { dataDeInput, dataInput, dataInputSaoPaulo, isoAgenda, useAgenda } from "@/hooks/useAgenda"
import type { AtualizarBloqueioInput, BloqueioAgenda, BloqueioFormState } from "@/tipos/agenda"

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
  const [tipoAtendimento, setTipoAtendimento] = useState<"" | "interno" | "externo">("")
  const [atendimentoVisualizandoId, setAtendimentoVisualizandoId] = useState<string | null>(null)

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

  const criar = async (form: BloqueioFormState) => {
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
      })
      toast.success("Bloqueio criado")
      setDialog({ modo: "fechado", bloqueio: null })
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Erro do servidor. Tente novamente.")
    }
  }

  const atualizar = async (id: string, form: BloqueioFormState, atendimentoId?: string | null) => {
    try {
      const payload: AtualizarBloqueioInput = {
        inicio: isoAgenda(form.data, form.inicio),
        fim: fimIsoOvernight(form.data, form.inicio, form.fim),
        observacao: form.observacao.trim() || null,
      }
      if (atendimentoId !== undefined) payload.atendimento_id = atendimentoId
      await agenda.atualizarBloqueio(id, payload)
      toast.success("Bloqueio atualizado")
      setDialog({ modo: "fechado", bloqueio: null })
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Erro do servidor. Tente novamente.")
    }
  }

  const moverBloqueio = async (id: string, novoInicio: string, novoFim: string) => {
    try {
      await agenda.atualizarBloqueio(id, { inicio: novoInicio, fim: novoFim, observacao: null })
      toast.success("Bloqueio movido")
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
      toast.success("Bloqueio cancelado")
      setDialog({ modo: "fechado", bloqueio: null })
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Erro do servidor. Tente novamente.")
    }
  }

  if (agenda.status === "loading") return <AgendaSkeleton />

  if (agenda.status === "error") {
    return (
      <section className="space-y-3">
        <HeaderAgenda modelo={agenda.modeloId ? (agenda.agenda?.modelo ?? null) : null} bloqueios={[]} />
        <BannerErro mensagem={agenda.error ?? undefined} onRetry={agenda.refetch} />
      </section>
    )
  }

  const hojeStr = dataInputSaoPaulo()

  return (
    <section className="space-y-3">
      <HeaderAgenda modelo={agenda.modeloId ? (agenda.agenda?.modelo ?? null) : null} bloqueios={bloqueios} />
      <ToolbarAgenda
        visao={agenda.visao}
        periodoLabel={agenda.periodo.label}
        modeloId={agenda.modeloId}
        tipoAtendimento={tipoAtendimento}
        onVisaoChange={agenda.setVisao}
        onAnterior={agenda.anterior}
        onProximo={agenda.proximo}
        onHoje={agenda.hoje}
        onModeloChange={agenda.setModeloId}
        onTipoAtendimentoChange={setTipoAtendimento}
        onCriar={() => abrirCriacao(proximoSlotLivre(agenda.dataSelecionada, bloqueios))}
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
    </section>
  )
}

export function AgendaSkeleton() {
  return (
    <section className="space-y-6" aria-busy="true">
      <div className="flex items-start justify-between">
        <div>
          <Skeleton className="h-12 w-40" />
          <Skeleton className="mt-2 h-4 w-32" />
        </div>
        <div className="grid grid-cols-3 gap-3">
          <Skeleton className="h-20 w-32" />
          <Skeleton className="h-20 w-32" />
          <Skeleton className="h-20 w-32" />
        </div>
      </div>
      <div className="rounded-lg border border-border bg-card p-3">
        <div className="flex items-center justify-between">
          <Skeleton className="h-9 w-48" />
          <Skeleton className="h-9 w-56" />
          <Skeleton className="h-9 w-40" />
        </div>
      </div>
      <div className="overflow-hidden rounded-lg border border-border bg-card">
        <div className="grid h-12 border-b border-border" style={{ gridTemplateColumns: "52px repeat(7, 1fr)" }}>
          {Array.from({ length: 8 }, (_, i) => (
            <Skeleton key={i} className="m-2 h-8 rounded-md" />
          ))}
        </div>
        <div className="space-y-1 p-4">
          {Array.from({ length: 6 }, (_, i) => (
            <Skeleton key={i} className="h-16 rounded-lg" />
          ))}
        </div>
      </div>
    </section>
  )
}
