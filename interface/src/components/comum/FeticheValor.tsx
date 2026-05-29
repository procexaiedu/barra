import { formatBRL } from "@/lib/formatters"
import { cn } from "@/lib/utils"

/**
 * Pílula de valor de um fetiche, consistente em todas as superfícies (cadastro, admin,
 * atendimento, breakdown): `incluso` (neutro) ou `+R$X` (dourado = extra pago).
 */
export function FeticheValor({ preco, className }: { preco: number | null; className?: string }) {
  if (preco === null) {
    return (
      <span
        className={cn(
          "inline-flex items-center rounded-full border border-border-subtle bg-muted px-2 py-0.5 text-[11px] font-medium text-text-muted",
          className,
        )}
      >
        incluso
      </span>
    )
  }
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border border-border-brand/40 bg-gold-500/10 px-2 py-0.5 text-[11px] font-medium tabular-nums text-text-brand",
        className,
      )}
    >
      +{formatBRL(preco)}
    </span>
  )
}
