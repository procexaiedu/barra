import { Card } from "@/components/ui/card"
import { cn } from "@/lib/utils"

export function TileMetrica({
  label,
  valor,
  colorClass,
}: {
  label: string
  valor: string
  colorClass?: string
}) {
  return (
    <Card className="rounded-lg bg-card p-6">
      <dl>
        <dt className="text-xs font-semibold uppercase tracking-[0.08em] text-text-muted">
          {label}
        </dt>
        <dd
          className={cn(
            "mt-2 font-sans text-[40px] font-medium leading-[48px] tracking-[-0.02em]",
            colorClass ?? "text-text-primary"
          )}
        >
          {valor}
        </dd>
      </dl>
    </Card>
  )
}
