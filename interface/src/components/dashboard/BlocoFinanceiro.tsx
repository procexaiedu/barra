"use client"

import { Banknote, HandCoins, Receipt, Wallet } from "lucide-react"
import type { FinanceiroBloco, KpisFechamentos } from "@/tipos/dashboard"
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
}

export function BlocoFinanceiro({
  financeiro,
  anterior,
  rangeComparacao,
  fechamentos,
  onAbrirLista,
}: Props) {
  return (
    <section aria-label="Resumo financeiro do período" className="flex flex-col gap-3">
      <header>
        <h2 className="text-base font-semibold text-text-primary">Financeiro</h2>
      </header>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-4">
        <TileKpi
          label="Faturamento bruto"
          icone={Banknote}
          iconeClassName="text-gold-500"
          tooltip="Valor final = bruto pago pelo cliente no atendimento fechado."
          valor={formatBRL(financeiro.valor_bruto_brl)}
          rangeComparacao={anterior ? rangeComparacao : null}
          tendencia={
            anterior ? (
              <IndicadorTendencia
                atual={financeiro.valor_bruto_brl}
                anterior={anterior.valor_bruto_brl}
                unidade="%"
                polaridade="direta"
              />
            ) : null
          }
          onClick={onAbrirLista ? () => onAbrirLista("faturamento_bruto") : undefined}
          ariaLabel="Abrir lista de fechamentos com faturamento bruto do período"
        />
        <TileKpi
          label="Faturamento líquido (agência)"
          icone={Wallet}
          iconeClassName="text-success-500"
          tooltip="Parcela da agência (bruto - repasse por snapshot do acordo)."
          valor={formatBRL(financeiro.valor_liquido_brl)}
          valorClassName="text-success-500"
          rangeComparacao={anterior ? rangeComparacao : null}
          tendencia={
            anterior ? (
              <IndicadorTendencia
                atual={financeiro.valor_liquido_brl}
                anterior={anterior.valor_liquido_brl}
                unidade="%"
                polaridade="direta"
              />
            ) : null
          }
          onClick={onAbrirLista ? () => onAbrirLista("faturamento_liquido") : undefined}
          ariaLabel="Abrir lista de fechamentos com faturamento líquido do período"
        />
        <TileKpi
          label="Repasse às modelos"
          icone={HandCoins}
          iconeClassName="text-text-muted"
          tooltip="Parcela da modelo conforme percentual do acordo no momento do fechamento."
          valor={formatBRL(financeiro.valor_repasse_modelo_brl)}
          onClick={onAbrirLista ? () => onAbrirLista("repasse") : undefined}
          ariaLabel="Abrir lista de fechamentos com repasse às modelos do período"
        />
        <TileKpi
          label="Ticket médio"
          icone={Receipt}
          iconeClassName="text-text-muted"
          tooltip="Valor bruto médio por fechamento no período."
          valor={formatBRL(fechamentos.valor_medio_brl)}
          linhaAuxiliar={
            <span>{`${fechamentos.contagem} fechamento(s)`}</span>
          }
        />
      </div>
      {financeiro.fechamentos_sem_snapshot > 0 ? (
        <p className="text-xs text-text-muted">
          {financeiro.fechamentos_sem_snapshot} fechamento(s) sem percentual de repasse cadastrado —
          contam como 100% líquido para a agência.
        </p>
      ) : null}
    </section>
  )
}
