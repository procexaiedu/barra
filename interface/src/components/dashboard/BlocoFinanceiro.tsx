"use client"

import { Wallet } from "lucide-react"
import type { FinanceiroBloco, KpisFechamentos, SerieTemporalPonto } from "@/tipos/dashboard"
import { formatBRL } from "@/lib/formatters"
import { IndicadorTendencia } from "./IndicadorTendencia"
import type { TipoMetricaModal } from "./ModalListaAtendimentos"
import { TileKpi } from "./TileKpi"

interface Props {
  financeiro: FinanceiroBloco
  anterior: FinanceiroBloco | null
  rangeComparacao: string | null
  fechamentos: KpisFechamentos
  onAbrirLista?: (tipo: TipoMetricaModal) => void
  serieLiquido?: SerieTemporalPonto[]
}

interface LinhaWaterfallProps {
  rotulo: string
  valor: number
  total: number
  cor: string
  onClick?: () => void
  ariaLabel?: string
  highlight?: boolean
}

function LinhaWaterfall({
  rotulo,
  valor,
  total,
  cor,
  onClick,
  ariaLabel,
  highlight,
}: LinhaWaterfallProps) {
  const pct = total > 0 ? Math.max(2, Math.min(100, (valor / total) * 100)) : 0
  const interativo = Boolean(onClick)
  const baseClass = "grid grid-cols-[140px_1fr_140px] items-center gap-3 rounded-md px-2 py-2"
  const interactiveClass = interativo
    ? "cursor-pointer transition-colors hover:bg-accent focus-visible:bg-accent focus-visible:outline-none"
    : ""
  return (
    <div
      role={interativo ? "button" : undefined}
      tabIndex={interativo ? 0 : undefined}
      onClick={onClick}
      onKeyDown={(event) => {
        if (interativo && (event.key === "Enter" || event.key === " ")) {
          event.preventDefault()
          onClick?.()
        }
      }}
      aria-label={ariaLabel}
      className={`${baseClass} ${interactiveClass}`}
    >
      <span className={`text-sm ${highlight ? "font-semibold text-text-primary" : "text-text-muted"}`}>
        {rotulo}
      </span>
      <div className="relative h-3 overflow-hidden rounded-full bg-muted">
        <div
          className="h-full rounded-full transition-[width] duration-300"
          style={{ width: `${pct}%`, background: cor }}
        />
      </div>
      <span
        className={`text-right text-sm font-mono tabular-nums ${
          highlight ? "font-semibold text-text-primary" : "text-text-primary"
        }`}
      >
        {formatBRL(valor)}
      </span>
    </div>
  )
}

export function BlocoFinanceiro({
  financeiro,
  anterior,
  rangeComparacao,
  fechamentos,
  onAbrirLista,
  serieLiquido,
}: Props) {
  const total = Math.max(
    financeiro.valor_bruto_brl,
    financeiro.valor_liquido_brl + financeiro.valor_repasse_modelo_brl,
    1
  )

  return (
    <section aria-label="Resumo financeiro do período" className="flex flex-col gap-4">
      <header className="flex items-baseline justify-between">
        <h2 className="text-base font-semibold text-text-primary">Financeiro</h2>
        {rangeComparacao ? (
          <span className="font-mono text-[11px] text-text-muted">
            Comparado com {rangeComparacao}
          </span>
        ) : null}
      </header>

      <TileKpi
        label="Faturamento líquido (Elite Baby)"
        icone={Wallet}
        iconeClassName="text-success-500"
        tooltip="Parcela da Elite Baby (bruto - repasse modelo). Sparkline mostra evolução por semana."
        valor={formatBRL(financeiro.valor_liquido_brl)}
        valorClassName="text-success-500"
        destaque
        serie={serieLiquido}
        corSparkline="var(--success-500)"
        tendencia={
          anterior ? (
            <IndicadorTendencia
              atual={financeiro.valor_liquido_brl}
              anterior={anterior.valor_liquido_brl}
              unidade="%"
              polaridade="direta"
              baseAtual={fechamentos.contagem}
              baseAnterior={anterior.fechamentos_total}
            />
          ) : null
        }
        nReferencia={fechamentos.contagem}
        onClick={onAbrirLista ? () => onAbrirLista("faturamento_liquido") : undefined}
        ariaLabel="Abrir lista de fechamentos com faturamento líquido do período"
      />

      <div className="flex flex-col gap-1 rounded-lg bg-card p-4 ring-1 ring-foreground/10">
        <h3 className="px-2 pb-2 text-xs font-medium uppercase tracking-[0.08em] text-text-muted">
          Decomposição do bruto
        </h3>
        <LinhaWaterfall
          rotulo="Bruto"
          valor={financeiro.valor_bruto_brl}
          total={total}
          cor="var(--gold-500)"
          onClick={onAbrirLista ? () => onAbrirLista("faturamento_bruto") : undefined}
          ariaLabel="Abrir lista de fechamentos com faturamento bruto"
        />
        <LinhaWaterfall
          rotulo="− Repasse modelo"
          valor={financeiro.valor_repasse_modelo_brl}
          total={total}
          cor="var(--gold-500)"
          onClick={onAbrirLista ? () => onAbrirLista("repasse") : undefined}
          ariaLabel="Abrir lista de fechamentos com repasse às modelos"
        />
        <LinhaWaterfall
          rotulo="Líquido"
          valor={financeiro.valor_liquido_brl}
          total={total}
          cor="var(--success-500)"
          onClick={onAbrirLista ? () => onAbrirLista("faturamento_liquido") : undefined}
          ariaLabel="Abrir lista de fechamentos com faturamento líquido"
          highlight
        />
      </div>

      <p className="px-2 text-xs text-text-muted">
        <span className="font-mono tabular-nums">Ticket médio {formatBRL(fechamentos.valor_medio_brl)}</span>
        {" · "}
        <span>{fechamentos.contagem} fechamento(s)</span>
        {financeiro.fechamentos_sem_snapshot > 0 ? (
          <>
            {" · "}
            <span>
              {financeiro.fechamentos_sem_snapshot} sem percentual de repasse —{" "}
              {formatBRL(financeiro.valor_sem_repasse_definido_brl)} contam 100% líquido
            </span>
          </>
        ) : null}
      </p>
    </section>
  )
}
