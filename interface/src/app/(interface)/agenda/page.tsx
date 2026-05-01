"use client"

import { useMemo, useState } from "react"
import { toast } from "sonner"
import { CalendarioMes } from "@/components/agenda/CalendarioMes"
import { DialogBloqueio } from "@/components/agenda/DialogBloqueio"
import { HeaderAgenda } from "@/components/agenda/HeaderAgenda"
import { PainelDia } from "@/components/agenda/PainelDia"
import { ToolbarAgenda } from "@/components/agenda/ToolbarAgenda"
import { BannerErro } from "@/components/layout/BannerErro"
import { Skeleton } from "@/components/ui/skeleton"
import { isoAgenda, useAgenda } from "@/hooks/useAgenda"
import type { BloqueioAgenda, BloqueioFormState } from "@/tipos/agenda"

function proximoFim(inicio: string) {
  const hora = Number(inicio.slice(0, 2))
  return hora === 23 ? "24:00" : `${String(hora + 1).padStart(2, "0")}:00`
}

function proximoSlotLivre(data: string, bloqueios: BloqueioAgenda[]) {
  const ocupados = new Set(
    bloqueios
      .filter((b) => b.inicio.slice(0, 10) === data && (b.estado === "bloqueado" || b.estado === "em_atendimento"))
      .map((b) => b.inicio.slice(11, 16))
  )
  const hora = Array.from({ length: 24 }, (_, h) => `${String(h).padStart(2, "0")}:00`)
    .find((item) => !ocupados.has(item)) ?? "00:00"
  return { data, inicio: hora, fim: proximoFim(hora), observacao: "" }
}

export default function Agenda() {
  const agenda = useAgenda()
  const [dialogOpen, setDialogOpen] = useState(false)
  const [bloqueioSelecionado, setBloqueioSelecionado] = useState<BloqueioAgenda | null>(null)
  const [initialForm, setInitialForm] = useState<BloqueioFormState>({
    data: agenda.dataSelecionada,
    inicio: "00:00",
    fim: "01:00",
    observacao: "",
  })

  const bloqueios = useMemo(
    () => [...(agenda.agenda?.bloqueios ?? [])].sort((a, b) => a.inicio.localeCompare(b.inicio)),
    [agenda.agenda?.bloqueios]
  )
  const bloqueiosDia = useMemo(
    () => bloqueios.filter((b) => b.inicio.slice(0, 10) === agenda.dataSelecionada),
    [agenda.dataSelecionada, bloqueios]
  )

  const abrirCriacao = (form: BloqueioFormState) => {
    setBloqueioSelecionado(null)
    setInitialForm(form)
    setDialogOpen(true)
  }

  const criar = async (form: BloqueioFormState) => {
    const modeloId = agenda.agenda?.modelo?.id
    if (!modeloId) {
      toast.error("Nenhuma modelo ativa.")
      return
    }
    try {
      await agenda.criarBloqueio({
        modelo_id: modeloId,
        inicio: isoAgenda(form.data, form.inicio),
        fim: isoAgenda(form.data, form.fim),
        observacao: form.observacao.trim() || null,
      })
      toast.success("Bloqueio criado")
      setDialogOpen(false)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Erro do servidor. Tente novamente.")
    }
  }

  const atualizar = async (id: string, form: BloqueioFormState) => {
    try {
      await agenda.atualizarBloqueio(id, {
        inicio: isoAgenda(form.data, form.inicio),
        fim: isoAgenda(form.data, form.fim),
        observacao: form.observacao.trim() || null,
      })
      toast.success("Bloqueio atualizado")
      setDialogOpen(false)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Erro do servidor. Tente novamente.")
    }
  }

  const cancelar = async (id: string, confirmar: boolean) => {
    try {
      await agenda.cancelarBloqueio(id, confirmar)
      toast.success("Bloqueio cancelado")
      setDialogOpen(false)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Erro do servidor. Tente novamente.")
    }
  }

  if (agenda.status === "loading") {
    return <AgendaSkeleton />
  }

  if (agenda.status === "error") {
    return (
      <section className="space-y-6">
        <HeaderAgenda modelo={null} bloqueios={[]} />
        <BannerErro mensagem={agenda.error ?? undefined} onRetry={agenda.refetch} />
      </section>
    )
  }

  return (
    <section className="space-y-6">
      <HeaderAgenda modelo={agenda.agenda?.modelo ?? null} bloqueios={bloqueios} />
      <ToolbarAgenda
        visao={agenda.visao}
        periodoLabel={agenda.periodo.label}
        onVisaoChange={agenda.setVisao}
        onAnterior={agenda.anterior}
        onProximo={agenda.proximo}
        onHoje={agenda.hoje}
      />
      <div className="grid grid-cols-[minmax(0,1fr)_minmax(360px,420px)] items-start gap-6">
        <CalendarioMes
          visao={agenda.visao}
          dataSelecionada={agenda.dataSelecionada}
          bloqueios={bloqueios}
          onSelecionarDia={agenda.setDataSelecionada}
          onCriarNoDia={(data) => abrirCriacao(proximoSlotLivre(data, bloqueios))}
          onEditarBloqueio={(bloqueio) => {
            setBloqueioSelecionado(bloqueio)
            setDialogOpen(true)
          }}
        />
        <PainelDia
          dataSelecionada={agenda.dataSelecionada}
          bloqueios={bloqueiosDia}
          onCriarSlot={(inicio) => abrirCriacao({
            data: agenda.dataSelecionada,
            inicio,
            fim: proximoFim(inicio),
            observacao: "",
          })}
          onEditarBloqueio={(bloqueio) => {
            setBloqueioSelecionado(bloqueio)
            setDialogOpen(true)
          }}
        />
      </div>
      {dialogOpen && (
        <DialogBloqueio
          bloqueio={bloqueioSelecionado}
          modeloId={agenda.agenda?.modelo?.id ?? null}
          initial={initialForm}
          bloqueios={bloqueios}
          onClose={() => setDialogOpen(false)}
          onCriar={criar}
          onAtualizar={atualizar}
          onCancelar={cancelar}
        />
      )}
    </section>
  )
}

function AgendaSkeleton() {
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
      <div className="grid grid-cols-[minmax(0,1fr)_minmax(360px,420px)] items-start gap-6">
        <div className="min-w-0 rounded-lg border border-border bg-card p-4">
          <div className="grid grid-cols-7 gap-2">
            {Array.from({ length: 35 }, (_, i) => (
              <Skeleton key={i} className="h-32 rounded-lg" />
            ))}
          </div>
        </div>
        <div className="rounded-lg border border-border bg-card p-4">
          <Skeleton className="h-12 w-40" />
          <div className="mt-4 space-y-2">
            {Array.from({ length: 8 }, (_, i) => (
              <Skeleton key={i} className="h-11 rounded-lg" />
            ))}
          </div>
        </div>
      </div>
    </section>
  )
}
