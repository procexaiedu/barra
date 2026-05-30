import { Button } from "@/components/ui/button"

export function BannerErro({
  mensagem,
  onRetry,
}: {
  mensagem?: string
  onRetry: () => void
}) {
  return (
    <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-6">
      <p className="text-sm text-foreground">
        {mensagem ?? "Não foi possível carregar."}
      </p>
      <Button variant="ghost" size="sm" onClick={onRetry} className="mt-2">
        Tentar novamente
      </Button>
    </div>
  )
}
