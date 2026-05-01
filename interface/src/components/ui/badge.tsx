import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils"

const badgeVariants = cva(
  "inline-flex items-center rounded-full px-3 py-1 text-xs font-medium",
  {
    variants: {
      variant: {
        active: "bg-ink-300 text-state-active",
        paused: "bg-ink-300 text-state-paused",
        handoff: "bg-ink-300 text-state-handoff",
        revisao: "bg-ink-300 text-state-handoff",
        closed: "bg-ink-300 text-state-closed",
        lost: "bg-ink-300 text-state-lost",
      },
    },
    defaultVariants: {
      variant: "active",
    },
  }
)

function Badge({
  className,
  variant,
  ...props
}: React.ComponentProps<"span"> & VariantProps<typeof badgeVariants>) {
  return (
    <span
      data-slot="badge"
      className={cn(badgeVariants({ variant }), className)}
      {...props}
    />
  )
}

export { Badge, badgeVariants }
