import { formatBRL } from "@/lib/formatters"
import { estadoDoPiso } from "@/lib/precoMinimo"
import { cn } from "@/lib/utils"

/**
 * Pílula do preço mínimo de uma linha de tabela (ADR-0037), irmã de `FeticheValor`. Fica ABAIXO do
 * preço, porque o piso só existe em relação a ele.
 *
 * Os três estados são visualmente distintos de propósito: "sem mínimo" (neutro, cinza) NÃO é a
 * mesma coisa que um mínimo igual ao preço (dourado, "não desconta") — o primeiro deixa o
 * percentual global descontar à vontade, o segundo trava a linha.
 */
export function PisoValor({
  preco,
  precoMinimo,
  className,
}: {
  preco: number
  precoMinimo: number | null | undefined
  className?: string
}) {
  const estado = estadoDoPiso(preco, precoMinimo)
  if (estado.tipo === "desconhecido") return null

  if (estado.tipo === "sem_piso") {
    return (
      <span
        className={cn("text-[11px] leading-tight text-text-muted", className)}
        title="Sem mínimo próprio: nesta linha vale só o desconto padrão da casa."
      >
        sem mínimo
      </span>
    )
  }

  if (estado.tipo === "nao_descontavel") {
    return (
      <span
        className={cn(
          "inline-flex items-center gap-1 rounded-full border border-border-brand/40 bg-gold-500/10 px-2 py-0.5 text-[11px] font-medium leading-tight tabular-nums text-text-brand",
          className,
        )}
        title="Mínimo igual ao preço: a IA não desconta nada nesta linha."
      >
        mín. {formatBRL(estado.valor)} · não desconta
      </span>
    )
  }

  return (
    <span
      className={cn("text-[11px] leading-tight tabular-nums text-text-secondary", className)}
      title="A IA pode descontar até aqui, e não abaixo."
    >
      mín. {formatBRL(estado.valor)}
    </span>
  )
}
