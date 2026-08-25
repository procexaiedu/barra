"use client"

import { ArrowDownLeft, ArrowUpRight, Equal } from "lucide-react"
import { formatBRL } from "@/lib/formatters"
import { cn } from "@/lib/utils"
import type { SaldoDoRazao } from "@/tipos/razao"

/**
 * O número com sinal que o gestor pediu (ADR-0045 §1): *"a casa te deve R$ 600"* ou *"você deve
 * R$ 600 pra casa"*. Nunca três colunas para ele somar de cabeça.
 *
 * O verde é para a casa devendo e o âmbar para ela devendo — e não vermelho: ela devendo é o
 * estado NORMAL de quem recebeu em espécie ou no Pix dela, não um erro. O default conservador do
 * "não dito" (ADR-0047 §4) empurra o saldo justamente para esse lado.
 */
export function SaldoComSinal({
  saldo,
  tamanho = "md",
  nome,
}: {
  saldo: SaldoDoRazao
  tamanho?: "sm" | "md" | "lg"
  /** Quando informado, a frase nomeia a modelo em vez de dizer "ela". */
  nome?: string
}) {
  const dela = nome ?? "ela"
  const zerado = Math.abs(saldo.saldo_brl) < 0.005
  const aCasaDeve = saldo.saldo_brl > 0

  const Icone = zerado ? Equal : aCasaDeve ? ArrowUpRight : ArrowDownLeft
  const frase = zerado
    ? "Conta zerada"
    : aCasaDeve
      ? `A casa deve a ${dela}`
      : `${nome ?? "Ela"} deve à casa`
  const cor = zerado
    ? "text-text-muted"
    : aCasaDeve
      ? "text-success-500"
      : "text-warn-500"
  const escala =
    tamanho === "lg" ? "text-3xl" : tamanho === "sm" ? "text-base" : "text-xl"

  return (
    <div className="flex flex-col gap-0.5">
      <span className="flex items-center gap-1 text-[11px] font-medium uppercase tracking-[0.08em] text-text-muted">
        <Icone className={cn("size-3.5", cor)} aria-hidden />
        {frase}
      </span>
      <span className={cn("font-mono font-semibold tabular-nums leading-none", escala, cor)}>
        {formatBRL(Math.abs(saldo.saldo_brl))}
      </span>
    </div>
  )
}

/**
 * A leitura de temporada que o ADR-0045 §7 descreve: o saldo é derivado, o pagamento já feito
 * fica AO LADO dele, e a diferença é "falta pagar R$ X" (ou crédito, se pagou a mais). Nada
 * congela — comprovante que chegar amanhã muda os três números.
 */
export function FaltaPagar({ saldo }: { saldo: SaldoDoRazao }) {
  const falta = saldo.falta_pagar_brl
  const quitado = Math.abs(falta) < 0.005
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[11px] font-medium uppercase tracking-[0.08em] text-text-muted">
        {quitado ? "Acertado" : falta > 0 ? "Falta pagar" : "Pago a mais"}
      </span>
      <span
        className={cn(
          "font-mono text-base font-semibold tabular-nums leading-none",
          quitado ? "text-text-muted" : falta > 0 ? "text-text-primary" : "text-warn-500",
        )}
      >
        {formatBRL(Math.abs(falta))}
      </span>
      {saldo.pago_brl > 0 && (
        <span className="font-mono text-[11px] tabular-nums text-text-muted">
          já pago {formatBRL(saldo.pago_brl)}
        </span>
      )}
    </div>
  )
}
