import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils"

// Controle segmentado (§7.9): poço recuado (bg-muted) com a aba ativa elevada
// em bg-card. Sem estado interno — quem usa controla o `active` de cada item,
// que vira `aria-pressed` e dirige o estilo.
const segmentedItemVariants = cva(
  cn(
    "flex items-center justify-center rounded-md text-xs font-medium transition-all duration-150",
    "text-text-muted hover:text-text-primary",
    "aria-[pressed=true]:bg-card aria-[pressed=true]:text-text-primary aria-[pressed=true]:shadow-sm",
    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
  ),
  {
    variants: {
      size: {
        default: "px-2.5 py-1",
        icon: "p-1.5",
      },
    },
    defaultVariants: {
      size: "default",
    },
  }
)

function Segmented({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="segmented"
      role="group"
      className={cn("flex rounded-lg border border-border bg-muted p-0.5", className)}
      {...props}
    />
  )
}

function SegmentedItem({
  className,
  size,
  active,
  type = "button",
  ...props
}: React.ComponentProps<"button"> &
  VariantProps<typeof segmentedItemVariants> & { active: boolean }) {
  return (
    <button
      data-slot="segmented-item"
      type={type}
      aria-pressed={active}
      className={cn(segmentedItemVariants({ size, className }))}
      {...props}
    />
  )
}

export { Segmented, SegmentedItem, segmentedItemVariants }
