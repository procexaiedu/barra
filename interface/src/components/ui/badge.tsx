import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils"

const badgeVariants = cva(
  "inline-flex items-center rounded-full border px-3 py-1 text-xs font-medium",
  {
    variants: {
      variant: {
        active:  "border-state-active/30  bg-state-active/15  text-state-active",
        paused:  "border-state-paused/30  bg-state-paused/15  text-state-paused",
        handoff: "border-state-handoff/30 bg-state-handoff/15 text-state-handoff",
        info:    "border-state-info/30    bg-state-info/15    text-state-info",
        revisao: "border-state-lost/30    bg-state-lost/15    text-state-lost",
        closed:  "border-state-closed/30  bg-state-closed/15  text-state-closed",
        lost:    "border-state-lost/30    bg-state-lost/15    text-state-lost",
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
