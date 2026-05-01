"use client"

import { CheckCircle2, CalendarOff } from "lucide-react"
import Link from "next/link"
import { usePainelResumo } from "@/hooks/usePainelResumo"
import { HeaderPainel } from "@/components/painel/HeaderPainel"
import { CardDestaque } from "@/components/painel/CardDestaque"
import { TileMetrica } from "@/components/painel/TileMetrica"
import { LinhaAgenda } from "@/components/painel/LinhaAgenda"
import { AtalhoContextual } from "@/components/painel/AtalhoContextual"
import { BannerErro } from "@/components/layout/BannerErro"
import { Skeleton } from "@/components/ui/skeleton"
import { Card } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { formatBRL, formatDiaSemana, formatData } from "@/lib/formatters"

export default function PainelGeral() {
  const { data, status, error, refetch } = usePainelResumo()

  if (status === "loading") {
    return <PainelSkeleton />
  }

  if (status === "error" || !data) {
    return (
      <div className="p-8">
        <BannerErro mensagem={error ?? undefined} onRetry={refetch} />
      </div>
    )
  }

  const agora = new Date()
  const diaSemana = formatDiaSemana(agora)
  const dataFormatada = formatData(agora.toISOString())

  return (
    <div>
      <HeaderPainel
        modeloAtiva={data.modelo_ativa}
        modelosAtivasCount={data.modelos_ativas_count}
      />

      <section aria-label="Aguardando você" className="px-8 py-5">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-base font-semibold text-text-primary">Aguardando você</h2>
          {data.cards_destaque.length > 0 && (
            <span className="text-xs font-medium text-text-muted">
              {data.cards_destaque.length} aguardando ação
            </span>
          )}
        </div>

        {data.cards_destaque.length === 0 ? (
          <Card className="rounded-lg bg-card p-6">
            <div className="flex items-start gap-3">
              <CheckCircle2 size={20} className="mt-0.5 text-success-500" />
              <div>
                <p className="text-sm text-text-primary">
                  Nada precisa de você agora.
                </p>
                <p className="mt-1 text-[13px] text-text-muted">
                  Atendimentos que precisarem da sua decisão aparecem aqui.
                </p>
              </div>
            </div>
          </Card>
        ) : (
          <div className="grid gap-4 xl:grid-cols-2">
            {data.cards_destaque.map((card) => (
              <CardDestaque key={card.atendimento_id} card={card} />
            ))}
          </div>
        )}
      </section>

      <section aria-label="Métricas de hoje" className="px-8 py-5">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-base font-semibold text-text-primary">Hoje</h2>
          <span className="text-xs font-medium capitalize text-text-muted">
            {diaSemana} · {dataFormatada}
          </span>
        </div>
        <div className="grid grid-cols-4 gap-4">
          <TileMetrica
            label="ATENDIMENTOS ABERTOS"
            valor={String(data.metricas_dia.abertos)}
          />
          <TileMetrica
            label="FECHAMENTOS HOJE"
            valor={String(data.metricas_dia.fechamentos_hoje)}
            colorClass="text-success-500"
          />
          <TileMetrica
            label="PERDAS HOJE"
            valor={String(data.metricas_dia.perdas_hoje)}
            colorClass="text-danger-500"
          />
          <TileMetrica
            label="VALOR BRUTO HOJE"
            valor={formatBRL(data.metricas_dia.valor_bruto_hoje_brl)}
          />
        </div>
      </section>

      <section aria-label="Agenda de hoje" className="px-8 py-5">
        <h2 className="mb-4 text-base font-semibold text-text-primary">Agenda de hoje</h2>
        {data.agenda_dia.length === 0 ? (
          <Card className="rounded-lg bg-card p-6">
            <div className="flex items-start gap-3">
              <CalendarOff size={20} className="mt-0.5 text-text-muted" />
              <div>
                <p className="text-sm text-text-primary">
                  Nenhum horário reservado hoje.
                </p>
                <Button variant="ghost" size="sm" className="mt-2" nativeButton={false} render={<Link href="/agenda?action=bloquear" />}>
                  Bloquear horário
                </Button>
              </div>
            </div>
          </Card>
        ) : (
          <Card className="overflow-hidden rounded-lg bg-card">
            {data.agenda_dia.map((linha) => (
              <LinhaAgenda key={linha.id} linha={linha} />
            ))}
          </Card>
        )}
      </section>

      <AtalhoContextual
        metricas={data.metricas_dia}
        modeloAtiva={data.modelo_ativa}
      />
    </div>
  )
}

function PainelSkeleton() {
  return (
    <div aria-busy="true">
      <div className="flex items-center justify-between px-8 pb-4 pt-8">
        <Skeleton className="h-12 w-40" />
        <div className="flex gap-6">
          <Skeleton className="h-10 w-32" />
          <Skeleton className="h-10 w-44" />
        </div>
      </div>

      <div className="px-8 py-5">
        <Skeleton className="mb-4 h-6 w-48" />
        <div className="grid gap-4 xl:grid-cols-2">
          {[0, 1].map((i) => (
            <Skeleton key={i} className="h-[120px] rounded-lg" />
          ))}
        </div>
      </div>

      <div className="px-8 py-5">
        <Skeleton className="mb-4 h-6 w-24" />
        <div className="grid grid-cols-4 gap-4">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-24 rounded-lg" />
          ))}
        </div>
      </div>

      <div className="px-8 py-5">
        <Skeleton className="mb-4 h-6 w-36" />
        <Skeleton className="h-[168px] rounded-lg" />
      </div>
    </div>
  )
}
