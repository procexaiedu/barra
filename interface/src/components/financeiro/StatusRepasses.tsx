"use client"

import { CheckCircle2 } from "lucide-react"
import { formatBRL } from "@/lib/formatters"
import { cn } from "@/lib/utils"

interface Props {
  calculado: number
  pago: number
  saldo: number
  bruto: number
  semSnapshot?: { qtd: number; valor: number }
}

// Bloco composto que substitui três KPIs avulsos (Repasses calculado,
// Repasses pagos, Saldo a pagar). Eles contam uma história só — quanto a
// Elite Baby deve às modelos do período — e ficam mais claros juntos, com a
// barra de progresso pago/calculado servindo de ancoragem visual.
export function StatusRepasses({
  calculado,
  pago,
  saldo,
  bruto,
  semSnapshot,
}: Props) {
  const pctPago = calculado > 0 ? (pago / calculado) * 100 : 0
  const pctDoBruto = bruto > 0 ? (calculado / bruto) * 100 : 0
  const saldoZero = saldo === 0
  const saldoNegativo = saldo < 0
  const semRepasse = calculado === 0

  const corSaldo = saldoNegativo
    ? "text-danger-500"
    : saldoZero && !semRepasse
      ? "text-success-500"
      : !saldoZero
        ? "text-warn-500"
        : "text-text-secondary"

  return (
    <section className="flex h-full flex-col gap-3 rounded-lg bg-card p-4 ring-1 ring-border-subtle shadow-elev-1">
      <header className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.08em] text-text-primary">
          <span className="h-3 w-0.5 rounded-full bg-gold-500" aria-hidden />
          Status de repasses
        </h3>
        {bruto > 0 && (
          <span className="font-mono text-[10.5px] tabular-nums text-text-disabled">
            calculado = {pctDoBruto.toFixed(1)}% do bruto
          </span>
        )}
      </header>

      <div className="grid grid-cols-3 gap-x-3 gap-y-1">
        <Coluna rotulo="Calculado" valor={formatBRL(calculado)} />
        <Coluna
          rotulo="Pago"
          valor={formatBRL(pago)}
          trailing={
            calculado > 0 ? `${pctPago.toFixed(0)}% do calculado` : undefined
          }
        />
        <Coluna
          rotulo={saldoNegativo ? "Pago a mais" : "Saldo a pagar"}
          valor={formatBRL(Math.abs(saldo))}
          corValor={corSaldo}
          okQuando={saldoZero && !semRepasse}
          okTexto="Em dia"
        />
      </div>

      {calculado > 0 && (
        <div
          className="relative h-1.5 w-full overflow-hidden rounded-full bg-muted/70"
          role="progressbar"
          aria-valuenow={Math.round(pctPago)}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label="Percentual de repasses já pagos sobre o calculado"
        >
          <div
            className={cn(
              "h-full transition-[width] duration-500 ease-out",
              saldoNegativo
                ? "bg-danger-500"
                : saldoZero
                  ? "bg-success-500"
                  : "bg-primary",
            )}
            style={{
              width: `${Math.max(0, Math.min(100, saldoNegativo ? 100 : pctPago))}%`,
            }}
          />
        </div>
      )}

      <footer className="flex flex-wrap items-center justify-between gap-2 text-[11px] leading-tight">
        <p className="text-text-muted">
          {semRepasse ? (
            "Sem fechamentos com repasse no período."
          ) : saldoNegativo ? (
            <span className="text-danger-500">
              Pago a mais que o calculado — verificar estorno.
            </span>
          ) : saldoZero ? (
            <span className="inline-flex items-center gap-1 text-success-500">
              <CheckCircle2 className="size-3.5" aria-hidden /> Tudo quitado no
              período.
            </span>
          ) : (
            <>
              Falta liquidar{" "}
              <span className="font-mono font-medium tabular-nums text-text-secondary">
                {formatBRL(Math.abs(saldo))}
              </span>{" "}
              para fechar o ciclo.
            </>
          )}
        </p>
        {semSnapshot && semSnapshot.qtd > 0 && (
          <span className="rounded-sm bg-warn-500/[0.08] px-1.5 py-0.5 text-[10.5px] font-medium text-warn-500">
            {semSnapshot.qtd} sem %{" "}
            <span className="tabular-nums opacity-80">
              ({formatBRL(semSnapshot.valor)})
            </span>
          </span>
        )}
      </footer>
    </section>
  )
}

function Coluna({
  rotulo,
  valor,
  trailing,
  corValor,
  okQuando,
  okTexto,
}: {
  rotulo: string
  valor: string
  trailing?: string
  corValor?: string
  okQuando?: boolean
  okTexto?: string
}) {
  return (
    <div className="flex min-w-0 flex-col gap-0.5">
      <span className="truncate text-[10px] font-medium uppercase tracking-[0.1em] text-text-muted">
        {rotulo}
      </span>
      {okQuando ? (
        <span className="inline-flex items-center gap-1 text-[15px] font-semibold text-success-500">
          <CheckCircle2 className="size-4" aria-hidden />
          {okTexto ?? "Em dia"}
        </span>
      ) : (
        <span
          className={cn(
            "truncate font-mono text-[15px] font-semibold tabular-nums leading-tight",
            corValor ?? "text-text-primary",
          )}
        >
          {valor}
        </span>
      )}
      {trailing && (
        <span className="truncate font-mono text-[10.5px] text-text-disabled tabular-nums">
          {trailing}
        </span>
      )}
    </div>
  )
}
