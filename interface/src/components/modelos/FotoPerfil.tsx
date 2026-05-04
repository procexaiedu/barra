import { UserRound } from "lucide-react"

export function FotoPerfil({
  url,
  nome,
  size = "md",
}: {
  url: string | null
  nome: string
  size?: "sm" | "md" | "lg"
}) {
  const classe = size === "lg" ? "size-20" : size === "sm" ? "size-9" : "size-14"
  const icon = size === "lg" ? 28 : size === "sm" ? 16 : 20
  return (
    <div className={`${classe} shrink-0 overflow-hidden rounded-full border border-border bg-ink-200`}>
      {url ? (
        <img src={url} alt={`Foto de perfil de ${nome}`} className="h-full w-full object-cover" />
      ) : (
        <div className="flex h-full w-full items-center justify-center text-text-muted">
          <UserRound size={icon} strokeWidth={1.5} />
        </div>
      )}
    </div>
  )
}
