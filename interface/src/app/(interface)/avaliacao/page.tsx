import { PageHeader } from "@/components/layout/PageHeader"
import { PainelObservabilidade } from "@/components/observabilidade/PainelObservabilidade"

/** Tela de Avaliação: cada resposta do agente no tráfego real (ou e2e), agrupada
 *  por conversa em chat e avaliada por Fernando — vira o gabarito que mede se a
 *  IA substitui o vendedor. */
export default function AvaliacaoPage() {
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Avaliação"
        description="Cada resposta do agente, avaliada por você — vira o gabarito que mede se a IA substitui o vendedor."
      />
      <PainelObservabilidade />
    </div>
  )
}
