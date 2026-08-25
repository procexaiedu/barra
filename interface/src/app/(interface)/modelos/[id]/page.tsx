"use client"

import { Suspense } from "react"
import Link from "next/link"
import { useParams, useSearchParams } from "next/navigation"
import { ArrowLeft } from "lucide-react"
import { PageHeader } from "@/components/layout/PageHeader"
import { Skeleton } from "@/components/ui/skeleton"
import { ExtratoDaModelo } from "@/components/financeiro/ExtratoDaModelo"
import { useExtratoModelo } from "@/hooks/useExtratoModelo"
import { formatData } from "@/lib/formatters"

/**
 * A ficha financeira da modelo — o "financeiro individual" da reunião de 20/08.
 *
 * Rota própria (e não uma aba dentro de `/modelos`) porque ela é o destino de um LINK: a linha da
 * temporada em `/financeiro` leva direto ao extrato daquela modelo já recortado pela temporada, e
 * um painel interno não tem endereço para onde apontar.
 */
export default function FichaFinanceiraDaModelo() {
  return (
    <Suspense fallback={<Skeleton className="h-[60vh] w-full rounded-lg" />}>
      <FichaInterna />
    </Suspense>
  )
}

function FichaInterna() {
  const params = useParams<{ id: string }>()
  const searchParams = useSearchParams()
  const modeloId = typeof params?.id === "string" ? params.id : null
  const temporadaId = searchParams.get("temporada_id")
  const de = searchParams.get("de")
  const ate = searchParams.get("ate")

  const { extrato, status, error, refetch } = useExtratoModelo(modeloId, {
    temporadaId,
    de,
    ate,
  })

  const recorte = extrato?.temporada_cidade
    ? `Temporada em ${extrato.temporada_cidade}${
        extrato.de && extrato.ate ? ` · ${formatData(extrato.de)} → ${formatData(extrato.ate)}` : ""
      }`
    : extrato?.de && extrato?.ate
      ? `${formatData(extrato.de)} → ${formatData(extrato.ate)}`
      : "Saldo corrente contínuo, sem período estanque."

  return (
    <div className="flex flex-col gap-8">
      <PageHeader
        title={extrato?.modelo_nome ?? "Extrato da modelo"}
        description={recorte}
      >
        <Link
          href="/financeiro"
          className="inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-[12px] font-medium text-text-secondary transition-colors hover:text-text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <ArrowLeft className="size-3.5" aria-hidden />
          Temporadas
        </Link>
      </PageHeader>

      <ExtratoDaModelo
        extrato={extrato}
        loading={status === "loading"}
        error={error}
        onRetry={refetch}
      />
    </div>
  )
}
