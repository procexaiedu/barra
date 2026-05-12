"use client"

import { Suspense, useState } from "react"
import { AlertTriangle, CheckCircle2, TrendingUp, XCircle } from "lucide-react"
import { BannerErro } from "@/components/layout/BannerErro"
import { Skeleton } from "@/components/ui/skeleton"
import { BlocoFinanceiro } from "@/components/dashboard/BlocoFinanceiro"
import { BlocoMotivosEscalada } from "@/components/dashboard/BlocoMotivosEscalada"
import { BlocoPerdasPorMotivo } from "@/components/dashboard/BlocoPerdasPorMotivo"
import { DialogRangeCustom } from "@/components/dashboard/DialogRangeCustom"
import { DialogTodasEscaladas } from "@/components/dashboard/DialogTodasEscaladas"
import { FunilEstados } from "@/components/dashboard/FunilEstados"
import { HeaderDashboard } from "@/components/dashboard/HeaderDashboard"
import { IndicadorTendencia } from "@/components/dashboard/IndicadorTendencia"
import { ProfissionaisRanking } from "@/components/dashboard/ProfissionaisRanking"
import { TileKpi } from "@/components/dashboard/TileKpi"
import { ToolbarDashboard } from "@/components/dashboard/ToolbarDashboard"
import { formatPercent, formatRangeAbsoluto } from "@/components/dashboard/utils"
import { formatBRL } from "@/lib/formatters"
import { useDashboard } from "@/hooks/useDashboard"
import type { EstadoAtendimento } from "@/tipos/atendimentos"
import type { DashboardResumo } from "@/tipos/dashboard"

const ESTADOS_CANONICOS: EstadoAtendimento[] = [
  "Novo",
  "Triagem",
  "Qualificado",
  "Aguardando_confirmacao",
  "Confirmado",
  "Em_execucao",
  "Fechado",
  "Perdido",
]

export default function DashboardPage() {
  return (
    <Suspense>
      <DashboardInner />
    </Suspense>
  )
}

function DashboardInner() {
  const dashboard = useDashboard()
  const [rangeOpen, setRangeOpen] = useState(false)
  const [escaladasOpen, setEscaladasOpen] = useState(false)

  const filtros = dashboard.filtros
  const data = dashboard.data
  const filtroAplicado = data?.filtro_aplicado ?? null

  return (
    <div className="flex flex-col gap-6">
      <HeaderDashboard de={filtroAplicado?.de ?? null} ate={filtroAplicado?.ate ?? null} />

      <ToolbarDashboard
        periodo={filtros.periodo}
        de={filtros.de}
        ate={filtros.ate}
        modeloId={filtros.modelo_id}
        onPreset={dashboard.setPeriodoPreset}
        onAbrirCustom={() => setRangeOpen(true)}
        onModeloChange={dashboard.setModeloId}
      />

      {dashboard.status === "loading" && !data ? (
        <DashboardSkeletons />
      ) : dashboard.status === "error" && !data ? (
        <BannerErro mensagem={dashboard.error ?? undefined} onRetry={dashboard.refetch} />
      ) : data ? (
        <DashboardConteudo data={data} onAbrirEscaladas={() => setEscaladasOpen(true)} />
      ) : null}

      <DialogRangeCustom
        open={rangeOpen}
        onOpenChange={setRangeOpen}
        deAtual={filtros.de}
        ateAtual={filtros.ate}
        onAplicar={dashboard.setPeriodoCustom}
      />

      <DialogTodasEscaladas
        open={escaladasOpen}
        onOpenChange={setEscaladasOpen}
        data={dashboard.escaladas.data}
        status={dashboard.escaladas.status}
        error={dashboard.escaladas.error}
        onLoad={dashboard.escaladas.load}
        onReset={dashboard.escaladas.reset}
      />
    </div>
  )
}

interface ConteudoProps {
  data: DashboardResumo
  onAbrirEscaladas: () => void
}

function DashboardConteudo({ data, onAbrirEscaladas }: ConteudoProps) {
  const kpis = data.kpis_periodo
  const anterior = data.kpis_periodo_anterior

  const linhasFunil = ESTADOS_CANONICOS.map((estado) => {
    const linha = data.funil_estados.find((l) => l.estado === estado)
    return { estado, contagem: linha?.contagem ?? 0 }
  })

  const ticketBruto = formatBRL(kpis.fechamentos.valor_bruto_brl)
  const ticketMedio = formatBRL(kpis.fechamentos.valor_medio_brl)
  const denominadorConversao = kpis.fechamentos.contagem + kpis.perdas.contagem

  const totalAtendimentos = data.funil_estados.reduce((soma, l) => soma + l.contagem, 0)
  const pctPerdasVolume =
    totalAtendimentos > 0 ? (kpis.perdas.contagem / totalAtendimentos) * 100 : null
  const pctEscaladasVolume =
    totalAtendimentos > 0 ? (kpis.escaladas.contagem / totalAtendimentos) * 100 : null

  const rangeComparacao = data.janela_comparacao
    ? formatRangeAbsoluto(data.janela_comparacao.de, data.janela_comparacao.ate)
    : null

  return (
    <>
      <section aria-label="KPIs do período" className="flex flex-col gap-3">
        <header>
          <h2 className="text-base font-semibold text-text-primary">No período</h2>
        </header>
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-4">
          <TileKpi
            label="Taxa de conversão"
            icone={TrendingUp}
            iconeClassName="text-gold-500"
            tooltip="Fechamentos dividido pelo total de atendimentos decididos no período (fechados + perdidos). Atendimentos ainda em aberto não entram na conta."
            valor={
              kpis.taxa_conversao_pct === null ? (
                <span className="text-text-muted">—</span>
              ) : (
                formatPercent(kpis.taxa_conversao_pct)
              )
            }
            linhaAuxiliar={
              <span>
                {`${kpis.fechamentos.contagem} fechado / ${denominadorConversao} decididos`}
              </span>
            }
            rangeComparacao={anterior ? rangeComparacao : null}
            tendencia={
              kpis.taxa_conversao_pct !== null && anterior !== null ? (
                <IndicadorTendencia
                  atual={kpis.taxa_conversao_pct}
                  anterior={anterior.taxa_conversao_pct ?? 0}
                  unidade="pp"
                  polaridade="direta"
                />
              ) : null
            }
          />
          <TileKpi
            label="Fechamentos"
            icone={CheckCircle2}
            iconeClassName="text-success-500"
            tooltip="Atendimentos encerrados como Fechado por registro explícito (comando ou painel). O valor bruto soma o valor final pago em cada um."
            valor={kpis.fechamentos.contagem}
            valorClassName="text-success-500"
            linhaAuxiliar={
              <span>
                {ticketBruto} bruto · ticket médio {ticketMedio}
              </span>
            }
            rangeComparacao={anterior ? rangeComparacao : null}
            tendencia={
              anterior ? (
                <IndicadorTendencia
                  atual={kpis.fechamentos.contagem}
                  anterior={anterior.fechamentos.contagem}
                  unidade="%"
                  polaridade="direta"
                />
              ) : null
            }
          />
          <TileKpi
            label="Perdas"
            icone={XCircle}
            iconeClassName="text-danger-500"
            tooltip="Atendimentos encerrados como Perdido — por registro explícito ou timeout determinístico (cliente sumiu antes de confirmar)."
            valor={kpis.perdas.contagem}
            valorClassName="text-danger-500"
            linhaAuxiliar={
              pctPerdasVolume !== null ? (
                <span>{`${formatPercent(pctPerdasVolume)} do volume`}</span>
              ) : (
                <span className="text-text-muted">—</span>
              )
            }
            rangeComparacao={anterior ? rangeComparacao : null}
            tendencia={
              anterior ? (
                <IndicadorTendencia
                  atual={kpis.perdas.contagem}
                  anterior={anterior.perdas.contagem}
                  unidade="%"
                  polaridade="invertida"
                />
              ) : null
            }
          />
          <TileKpi
            label="Atendimentos escalados"
            icone={AlertTriangle}
            iconeClassName="text-warn-500"
            tooltip="Atendimentos em que a IA pausou e escalou para Fernando ou para a modelo (handoff). Mede onde a IA pediu ajuda."
            valor={kpis.escaladas.contagem}
            linhaAuxiliar={
              pctEscaladasVolume !== null ? (
                <span>{`${formatPercent(pctEscaladasVolume)} do volume`}</span>
              ) : (
                <span className="text-text-muted">—</span>
              )
            }
            rangeComparacao={anterior ? rangeComparacao : null}
            tendencia={
              anterior ? (
                <IndicadorTendencia
                  atual={kpis.escaladas.contagem}
                  anterior={anterior.escaladas.contagem}
                  unidade="%"
                  polaridade="invertida"
                />
              ) : null
            }
          />
        </div>
      </section>

      <BlocoFinanceiro
        financeiro={data.financeiro}
        anterior={data.financeiro_periodo_anterior}
        rangeComparacao={rangeComparacao}
        fechamentos={kpis.fechamentos}
      />

      <FunilEstados linhas={linhasFunil} />

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <BlocoPerdasPorMotivo linhas={data.perdas_por_motivo} totalPerdas={kpis.perdas.contagem} />
        <BlocoMotivosEscalada data={data.motivos_escalada} onAbrirTodas={onAbrirEscaladas} />
      </div>

      <ProfissionaisRanking profissionais={data.profissionais} />
    </>
  )
}

function DashboardSkeletons() {
  return (
    <div aria-busy="true" className="flex flex-col gap-6">
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, idx) => (
          <Skeleton key={idx} className="h-[116px] w-full rounded-lg" />
        ))}
      </div>

      <div className="rounded-lg bg-card p-6 ring-1 ring-foreground/10">
        <ul className="flex flex-col gap-2">
          {Array.from({ length: 8 }).map((_, idx) => (
            <li key={idx} className="grid h-8 grid-cols-[200px_1fr_60px_56px] items-center gap-3">
              <Skeleton className="h-4 w-32 rounded-md" />
              <Skeleton className="h-4 w-full rounded-md" />
              <Skeleton className="h-4 w-10 justify-self-end rounded-md" />
              <Skeleton className="h-4 w-10 justify-self-end rounded-md" />
            </li>
          ))}
        </ul>
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <Skeleton className="h-[260px] w-full rounded-lg" />
        <Skeleton className="h-[260px] w-full rounded-lg" />
      </div>

      <Skeleton className="h-[120px] w-full rounded-lg" />
    </div>
  )
}
