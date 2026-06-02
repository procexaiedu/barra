"use client"

import { Suspense, useState } from "react"
import { CheckCircle2, TrendingUp, XCircle } from "lucide-react"
import { BannerErro } from "@/components/layout/BannerErro"
import { Skeleton } from "@/components/ui/skeleton"
import { BlocoFinanceiro } from "@/components/dashboard/BlocoFinanceiro"
import { BlocoMotivosEscalada } from "@/components/dashboard/BlocoMotivosEscalada"
import { BlocoPerdasPorMotivo } from "@/components/dashboard/BlocoPerdasPorMotivo"
import { BulletEscaladas } from "@/components/dashboard/BulletEscaladas"
import { FunilVendas } from "@/components/dashboard/FunilVendas"
import { DialogRangeCustom } from "@/components/dashboard/DialogRangeCustom"
import { DialogTodasEscaladas } from "@/components/dashboard/DialogTodasEscaladas"
import { HeaderDashboard } from "@/components/dashboard/HeaderDashboard"
import { IndicadorTendencia } from "@/components/dashboard/IndicadorTendencia"
import {
  ModalListaAtendimentos,
  type TipoMetricaModal,
} from "@/components/dashboard/ModalListaAtendimentos"
import { ProfissionaisRanking } from "@/components/dashboard/ProfissionaisRanking"
import { TileKpi } from "@/components/dashboard/TileKpi"
import { ToolbarDashboard } from "@/components/dashboard/ToolbarDashboard"
import { formatPercent, formatRangeAbsoluto } from "@/components/dashboard/utils"
import { formatBRL } from "@/lib/formatters"
import { cn } from "@/lib/utils"
import { useDashboard } from "@/hooks/useDashboard"
import type { DashboardResumo, SerieMetrica, SerieResposta } from "@/tipos/dashboard"

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
  const [metricaAberta, setMetricaAberta] = useState<TipoMetricaModal | null>(null)

  const filtros = dashboard.filtros
  const data = dashboard.data

  const rotuloModeloFiltrado =
    filtros.modelo_ids.length === 0
      ? null
      : filtros.modelo_ids.length === 1
        ? data?.profissionais.find((p) => p.modelo.id === filtros.modelo_ids[0])?.modelo.nome ?? null
        : `${filtros.modelo_ids.length} modelos`

  const rangeComparacao = data?.janela_comparacao
    ? formatRangeAbsoluto(data.janela_comparacao.de, data.janela_comparacao.ate)
    : null

  return (
    <div className="flex flex-col gap-8">
      <HeaderDashboard />

      <ToolbarDashboard
        periodo={filtros.periodo}
        de={filtros.de}
        ate={filtros.ate}
        modeloIds={filtros.modelo_ids}
        rangeComparacao={rangeComparacao}
        onPreset={dashboard.setPeriodoPreset}
        onAbrirCustom={() => setRangeOpen(true)}
        onModeloChange={dashboard.setModeloIds}
      />

      {dashboard.status === "loading" && !data ? (
        <DashboardSkeletons />
      ) : dashboard.status === "error" && !data ? (
        <BannerErro mensagem={dashboard.error ?? undefined} onRetry={dashboard.refetch} />
      ) : data ? (
        <div
          aria-busy={dashboard.isRefreshing}
          className={cn(
            "flex flex-col gap-8 transition-opacity duration-150",
            dashboard.isRefreshing ? "pointer-events-none opacity-60" : ""
          )}
        >
          <DashboardConteudo
            data={data}
            series={dashboard.series}
            modeloIdsSelecionadas={filtros.modelo_ids}
            onAbrirEscaladas={() => setEscaladasOpen(true)}
            onAbrirMetrica={setMetricaAberta}
          />
        </div>
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

      <ModalListaAtendimentos
        open={metricaAberta !== null}
        onOpenChange={(v) => {
          if (!v) setMetricaAberta(null)
        }}
        tipo={metricaAberta}
        filtrosDashboard={filtros}
        nomeModelo={rotuloModeloFiltrado}
      />
    </div>
  )
}

interface ConteudoProps {
  data: DashboardResumo
  series: Partial<Record<SerieMetrica, SerieResposta>>
  modeloIdsSelecionadas: string[]
  onAbrirEscaladas: () => void
  onAbrirMetrica: (tipo: TipoMetricaModal) => void
}

function DashboardConteudo({
  data,
  series,
  modeloIdsSelecionadas,
  onAbrirEscaladas,
  onAbrirMetrica,
}: ConteudoProps) {
  const kpis = data.kpis_periodo
  const anterior = data.kpis_periodo_anterior

  const ticketBruto = formatBRL(kpis.fechamentos.valor_bruto_brl)
  const ticketMedio = formatBRL(kpis.fechamentos.valor_medio_brl)
  const decididos = kpis.fechamentos.contagem + kpis.perdas.contagem

  return (
    <>
      {/* Seção 1 — Resultado (NSM) */}
      <section aria-label="Resultado" className="flex flex-col gap-3">
        <header>
          <h2 className="flex items-center gap-2.5 text-base font-semibold text-text-primary">
            <span className="h-4 w-1 rounded-full bg-gold-500" aria-hidden />
            Resultado
          </h2>
        </header>
        <div className="grid grid-cols-1 gap-4">
          <TileKpi
            label="Taxa de conversão"
            icone={TrendingUp}
            iconeClassName="text-gold-500"
            tooltip="Fechamentos ÷ atendimentos decididos (fechados + perdidos). Atendimentos em aberto não entram."
            valor={
              kpis.taxa_conversao_pct === null ? (
                <span className="text-text-muted">—</span>
              ) : (
                formatPercent(kpis.taxa_conversao_pct)
              )
            }
            linhaAuxiliar={
              <span>{`${kpis.fechamentos.contagem} fechado / ${decididos} decididos`}</span>
            }
            destaque
            serie={series.conversao?.pontos}
            corSparkline="var(--gold-500)"
            formatarSparkline={(v) => formatPercent(v)}
            nReferencia={decididos}
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
        </div>
      </section>

      {/* Seção 2 — Operação */}
      <section aria-label="Operação" className="flex flex-col gap-3">
        <header>
          <h2 className="flex items-center gap-2.5 text-base font-semibold text-text-primary">
            <span className="h-4 w-1 rounded-full bg-gold-500" aria-hidden />
            Operação
          </h2>
        </header>
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          <TileKpi
            label="Fechamentos"
            icone={CheckCircle2}
            iconeClassName="text-success-500"
            tooltip="Atendimentos encerrados como Fechado por registro explícito (comando ou painel)."
            valor={kpis.fechamentos.contagem}
            valorClassName="text-success-500"
            linhaAuxiliar={
              <span>
                {ticketBruto} bruto · ticket médio {ticketMedio}
              </span>
            }
            serie={series.fechamentos?.pontos}
            corSparkline="var(--success-500)"
            nReferencia={decididos}
            tendencia={
              anterior ? (
                <IndicadorTendencia
                  atual={kpis.fechamentos.contagem}
                  anterior={anterior.fechamentos.contagem}
                  unidade="%"
                  polaridade="direta"
                  baseAtual={kpis.fechamentos.contagem}
                  baseAnterior={anterior.fechamentos.contagem}
                />
              ) : null
            }
            onClick={() => onAbrirMetrica("fechamentos")}
            ariaLabel="Abrir lista de fechamentos do período"
          />
          <TileKpi
            label="Perdas"
            icone={XCircle}
            iconeClassName="text-danger-500"
            tooltip="Atendimentos encerrados como Perdido — por registro explícito ou timeout determinístico."
            valor={kpis.perdas.contagem}
            valorClassName="text-danger-500"
            linhaAuxiliar={
              decididos > 0 ? (
                <span>{`${formatPercent((kpis.perdas.contagem / decididos) * 100)} dos decididos`}</span>
              ) : (
                <span className="text-text-muted">—</span>
              )
            }
            serie={series.perdas?.pontos}
            corSparkline="var(--danger-500)"
            nReferencia={decididos}
            tendencia={
              anterior ? (
                <IndicadorTendencia
                  atual={kpis.perdas.contagem}
                  anterior={anterior.perdas.contagem}
                  unidade="%"
                  polaridade="invertida"
                  baseAtual={kpis.perdas.contagem}
                  baseAnterior={anterior.perdas.contagem}
                />
              ) : null
            }
            onClick={() => onAbrirMetrica("perdas")}
            ariaLabel="Abrir lista de perdas do período"
          />
          <BulletEscaladas
            contagem={kpis.escaladas.contagem}
            nReferencia={kpis.escaladas.n_referencia ?? kpis.volume_periodo ?? null}
            onClick={() => onAbrirMetrica("escaladas")}
          />
        </div>
      </section>

      {/* Seção 3 — Financeiro (waterfall + sparkline) */}
      <BlocoFinanceiro
        financeiro={data.financeiro}
        anterior={data.financeiro_periodo_anterior}
        rangeComparacao={null}
        fechamentos={kpis.fechamentos}
        onAbrirLista={onAbrirMetrica}
        serieLiquido={series.liquido?.pontos}
      />

      {/* Seção 4 — Funil de vendas por coorte (4 etapas; perdas como saída lateral) */}
      <FunilVendas funil={data.funil} />

      {/* Seção 5 — Diagnóstico (perdas + escaladas) */}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <BlocoPerdasPorMotivo
          linhas={data.perdas_por_motivo}
          totalPerdas={kpis.perdas.contagem}
          totalDecididos={decididos}
        />
        <BlocoMotivosEscalada data={data.motivos_escalada} onAbrirTodas={onAbrirEscaladas} />
      </div>

      {/* Seção 6 — Modelos */}
      <ProfissionaisRanking
        profissionais={data.profissionais}
        modeloIdsSelecionadas={modeloIdsSelecionadas}
      />
    </>
  )
}

function DashboardSkeletons() {
  return (
    <div aria-busy="true" className="flex flex-col gap-8">
      <Skeleton className="h-[180px] w-full rounded-lg" />
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {Array.from({ length: 3 }).map((_, idx) => (
          <Skeleton key={idx} className="h-[160px] w-full rounded-lg" />
        ))}
      </div>
      <Skeleton className="h-[260px] w-full rounded-lg" />
      <Skeleton className="h-[180px] w-full rounded-lg" />
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <Skeleton className="h-[260px] w-full rounded-lg" />
        <Skeleton className="h-[260px] w-full rounded-lg" />
      </div>
      <Skeleton className="h-[120px] w-full rounded-lg" />
    </div>
  )
}
